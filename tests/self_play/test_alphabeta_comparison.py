"""Fixed-depth Alpha-Beta comparisons, actual settings, CLI and legacy behavior."""

from dataclasses import replace
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.players import AlphaBetaPlayer
from engine.search import AlphaBetaSearcher, SearchLimits
from engine.sessions.evaluation_comparison import (
    ComparisonParticipant, ComparisonSearchConfig, run_evaluation_comparison,
)
from engine.strategy_config import strategy_config

ROOT = Path(__file__).resolve().parents[2]
FEN = "7k/7p/8/8/8/8/P7/K7 w - - 0 1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class AlphaBetaComparisonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = EvaluationConfig.from_dict(read(ROOT / "configs/evaluation/example_coordination.json"))
        self.search = ComparisonSearchConfig(depth_plies=2, quiescence_depth=0,
                                             move_ordering=False, use_transposition_table=False,
                                             use_pvs=False, aspiration_window=None)
        self.baseline = ComparisonParticipant.alphabeta("stable", EvaluationConfig(), search=self.search)
        self.candidate = ComparisonParticipant.alphabeta("candidate", self.config, search=self.search)

    def run_comparison(self, **overrides):
        options = dict(baseline=self.baseline, candidate=self.candidate, initial_fens=[FEN],
                       max_plies=2, base_seed=42, batch_root=self.root / "batches")
        options.update(overrides)
        return run_evaluation_comparison(**options)

    def test_real_searches_complete_requested_depth_and_preserve_roots(self):
        original = AlphaBetaSearcher.search
        calls = []

        def search(searcher, board, limits=None):
            before = board.fen(), list(board.move_stack)
            result = original(searcher, board, limits)
            self.assertEqual((board.fen(), board.move_stack), before)
            self.assertEqual(result.completed_depth, 2)
            self.assertIsNone(result.stop_reason)
            self.assertIn(result.best_move, board.legal_moves)
            calls.append((searcher.claim_draw, searcher.default_limits.max_depth))
            return result

        with patch.object(AlphaBetaSearcher, "search", search):
            result = self.run_comparison(claim_draw=True)
        self.assertEqual(calls, [(True, 2)] * 4)
        self.assertEqual(result.candidate_stats.unfinished, 2)
        self.assertEqual(result.candidate_stats.draws, 0)

    def test_early_terminal_search_completes_color_pairs_with_and_without_table(self):
        for table in (False, True):
            with self.subTest(table=table):
                search_config = ComparisonSearchConfig(depth_plies=2, use_transposition_table=table)
                baseline = ComparisonParticipant.alphabeta("stable", EvaluationConfig(), search=search_config)
                candidate = ComparisonParticipant.alphabeta("candidate", EvaluationConfig(phase_enabled=True), search=search_config)
                original = AlphaBetaSearcher.search
                calls = []
                def search(searcher, board, limits=None):
                    before = board.fen(), list(board.move_stack)
                    result = original(searcher, board, limits)
                    self.assertEqual((result.completed_depth, result.depth_reached), (2, 1))
                    self.assertEqual((board.fen(), board.move_stack), before)
                    calls.append(result)
                    return result
                with patch.object(AlphaBetaSearcher, "search", search):
                    result = self.run_comparison(
                        baseline=baseline, candidate=candidate, repetitions=2, max_plies=None,
                        initial_fens=["7k/8/8/8/8/8/8/KR6 w - - 149 75"], control=lambda: True,
                    )
                self.assertEqual(len(calls), 4)
                self.assertEqual(result.candidate_stats.draws, 4)
                self.assertEqual(result.candidate_stats.unfinished, 0)
                manifest = read(result.path / "manifest.json")
                self.assertEqual(manifest["status"], "completed")
                self.assertEqual(manifest["counts"]["saved_games"], 4)
                summary = read(result.path / "comparison.json")
                self.assertEqual(summary["progress"]["completed_pairs"], 2)
                for pair in summary["pairs"]:
                    self.assertEqual([game["candidate_color"] for game in pair["games"]], ["black", "white"])
                    for game in pair["games"]:
                        self.assertEqual(game["termination"], "seventyfive_moves")
                        replay = read(result.path / "replays" / f"{game['game_id']}.json")
                        self.assertEqual(len(replay["moves_uci"]), 1)
                        self.assertEqual(replay["result"], "1/2-1/2")

    def test_schema_budget_configs_rules_and_color_pairs_are_saved_consistently(self):
        result = self.run_comparison(claim_draw=True)
        manifest = read(result.path / "manifest.json")
        summary = read(result.path / "comparison.json")
        settings = manifest["settings"]["comparison"]
        self.assertEqual(settings["schema_version"], 2)
        self.assertEqual(summary["schema_version"], 2)
        self.assertEqual(settings["budget"], {"mode": "fixed_depth", "depth_plies": 2})
        self.assertEqual(summary["budget"], settings["budget"])
        self.assertEqual(summary["participants"], settings["participants"])
        self.assertEqual(manifest["settings"]["rules"], {"claim_draw": True})
        for name, participant in (("baseline", self.baseline), ("candidate", self.candidate)):
            saved = settings["participants"][name]
            self.assertEqual(saved, participant.settings_snapshot(claim_draw=True))
            evaluator = dict(saved["evaluator"])
            evaluator.pop("type")
            self.assertEqual(EvaluationConfig.from_dict(evaluator), participant.evaluation_config)
            self.assertEqual(saved["search"], {
                "schema_version": 1, "algorithm": "alpha_beta", "max_depth": 2,
                "claim_draw": True, "move_ordering": False, "quiescence_depth": 0,
                "use_transposition_table": False, "use_pvs": False, "aspiration_window": None,
            })
        games = summary["pairs"][0]["games"]
        self.assertEqual([(g["baseline_color"], g["candidate_color"]) for g in games],
                         [("white", "black"), ("black", "white")])
        self.assertEqual(summary["pairs"][0]["seed"], 42)

    def test_paired_seeds_positions_and_moves_are_reproducible(self):
        first = self.run_comparison(repetitions=2)
        second = self.run_comparison(repetitions=2)
        def moves(result):
            return [read(path)["moves_uci"] for path in sorted((result.path / "replays").glob("*.json"))]
        self.assertEqual(moves(first), moves(second))
        self.assertEqual(first.candidate_stats, second.candidate_stats)
        self.assertEqual([pair["seed"] for pair in read(first.path / "comparison.json")["pairs"]], [42, 43])

    def test_random_baseline_and_terminal_games_keep_official_outcomes(self):
        result = self.run_comparison(baseline=ComparisonParticipant.random_baseline())
        summary = read(result.path / "comparison.json")
        self.assertEqual(summary["participants"]["baseline"], {"label": "Random", "strategy": "Random"})
        self.assertEqual(summary["budget"]["depth_plies"], 2)
        terminal = self.run_comparison(initial_fens=["7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"])
        self.assertEqual((terminal.candidate_stats.wins, terminal.candidate_stats.losses), (1, 1))
        self.assertEqual(terminal.candidate_stats.unfinished, 0)

    def test_actual_searcher_snapshot_reflects_runtime_settings_and_rejects_other_budgets(self):
        player = self.candidate.create_player(random.Random(42), claim_draw=True)
        player.searcher.quiescence_depth = 3
        player.searcher.use_pvs = True
        saved = strategy_config("AlphaBeta", player)
        self.assertEqual(saved["search"]["quiescence_depth"], 3)
        self.assertTrue(saved["search"]["use_pvs"])
        self.assertTrue(saved["search"]["claim_draw"])
        for limits in (SearchLimits(max_depth=2, time_ms=100),
                       SearchLimits(max_depth=2, stop_requested=lambda: False)):
            player.searcher.default_limits = limits
            with self.assertRaises(ValueError):
                strategy_config("AlphaBeta", player)
        with self.assertRaises(ValueError):
            strategy_config("AlphaBeta", AlphaBetaPlayer(object()))
        with self.assertRaises(ValueError):
            strategy_config("AlphaBeta", None)

    def test_invalid_settings_and_incomparable_searches_fail_before_creating_batch(self):
        for kwargs in ({"depth_plies": 0}, {"depth_plies": True}, {"quiescence_depth": -1},
                       {"use_pvs": 1}, {"move_ordering": 1}, {"use_transposition_table": 1},
                       {"aspiration_window": 0}, {"aspiration_window": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ComparisonSearchConfig(**kwargs)
        for kwargs in ({"strategy": "alphabeta", "evaluation_config": self.config},
                       {"strategy": "greedy", "evaluation_config": self.config, "search_config": self.search},
                       {"strategy": "random", "search_config": self.search},
                       {"strategy": "alphabeta", "search_config": self.search}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ComparisonParticipant(label="invalid", **kwargs)
        for baseline in (ComparisonParticipant.greedy("stable", EvaluationConfig()),
                         replace(self.baseline, search_config=replace(self.search, depth_plies=3)),
                         replace(self.baseline, search_config=replace(self.search, use_pvs=True))):
            with self.assertRaises(ValueError):
                self.run_comparison(baseline=baseline)
        self.assertFalse((self.root / "batches").exists())

    def test_changed_game_player_settings_fail_and_preserve_failure_manifest(self):
        original = ComparisonParticipant.create_player
        count = 0
        def create(participant, rng, *, claim_draw=False):
            nonlocal count
            count += 1
            player = original(participant, rng, claim_draw=claim_draw)
            if count == 4:
                player.searcher.quiescence_depth = 1
            return player
        with patch.object(ComparisonParticipant, "create_player", create), self.assertRaisesRegex(ValueError, "changed"):
            self.run_comparison()
        manifest = read(next((self.root / "batches").iterdir()) / "manifest.json")
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["counts"]["saved_games"], 0)

    def test_cli_alphabeta_search_options_and_default_greedy_are_preserved(self):
        base = [sys.executable, "-m", "scripts.compare_evaluations", "--baseline-config",
                "configs/evaluation/stable.json", "--candidate-config", "configs/evaluation/example_coordination.json",
                "--initial-fen", FEN, "--max-plies", "2", "--batch-root", str(self.root / "cli")]
        result = subprocess.run([*base, "--strategy", "alphabeta", "--depth", "2",
                                 "--quiescence-depth", "0", "--no-move-ordering", "--no-transposition-table",
                                 "--no-pvs", "--no-aspiration", "--claim-draw"],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Budget: fixed_depth, 2 plies", result.stdout)
        settings = read(next((self.root / "cli").iterdir()) / "manifest.json")["settings"]["comparison"]
        search = settings["participants"]["candidate"]["search"]
        self.assertEqual(search["max_depth"], 2)
        self.assertFalse(search["use_pvs"])
        self.assertIsNone(search["aspiration_window"])
        self.assertEqual(search["quiescence_depth"], 0)
        self.assertTrue(search["claim_draw"])
        greedy = subprocess.run([*base, "--max-plies", "0"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(greedy.returncode, 0, greedy.stderr)
        self.assertIn("Budget: fixed_depth, 1 ply", greedy.stdout)

    def test_cli_rejects_ignored_invalid_and_time_options_without_creating_batch(self):
        base = [sys.executable, "-m", "scripts.compare_evaluations", "--baseline-random",
                "--candidate-config", "configs/evaluation/stable.json", "--max-plies", "0",
                "--batch-root", str(self.root / "invalid")]
        for options in (("--depth", "2"), ("--quiescence-depth", "0"),
                        ("--strategy", "alphabeta", "--depth", "0"),
                        ("--strategy", "alphabeta", "--aspiration-window", "0"),
                        ("--time-ms", "100")):
            result = subprocess.run([*base, *options], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.root / "invalid").exists())

    def test_defaults_and_enabled_search_options_are_saved(self):
        participant = ComparisonParticipant.alphabeta("default", self.config)
        saved = participant.settings_snapshot()["search"]
        self.assertEqual(saved["max_depth"], 2)
        self.assertEqual(saved["quiescence_depth"], 4)
        self.assertEqual(saved["aspiration_window"], 1.0)
        self.assertTrue(saved["use_pvs"])
        self.assertTrue(saved["use_transposition_table"])
        self.assertTrue(saved["move_ordering"])
        self.assertIsInstance(participant.create_player(random.Random(0)).searcher.evaluator, HandcraftedEvaluator)


if __name__ == "__main__":
    unittest.main()
