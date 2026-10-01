"""Paired evaluation comparison, persistence, statistics, and CLI behavior."""

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import chess

from engine.evaluation.config import EvaluationConfig, PawnTermConfig, MobilityTermConfig
from engine.sessions.evaluation_comparison import (
    ComparisonParticipant,
    run_evaluation_comparison,
)
from scripts.compare_evaluations import load_evaluation_config


ROOT = Path(__file__).resolve().parents[2]
WHITE_WIN_FEN = "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class EvaluationComparisonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.baseline_config = EvaluationConfig(pst_weight=1.0)
        self.candidate_config = EvaluationConfig(piece_values={"N": 4.0}, pst_weight=0.25,
                                                 phase_enabled=True, endgame_pst_weight=0.75,
                                                 mobility_terms={
                                                     "knight_mobility": MobilityTermConfig(True, .04, .06),
                                                     "rook_mobility": MobilityTermConfig(True, .02, .03),
                                                 },
                                                 pawn_terms={
                                                     "isolated_pawns": PawnTermConfig(True, .2, .3),
                                                     "doubled_pawns": PawnTermConfig(True, .1, .2),
                                                     "passed_pawns": PawnTermConfig(True, .03, .07),
                                                 })
        self.baseline = ComparisonParticipant.greedy("stable", self.baseline_config)
        self.candidate = ComparisonParticipant.greedy("candidate", self.candidate_config)

    def run_comparison(self, **kwargs):
        options = {
            "baseline": self.baseline,
            "candidate": self.candidate,
            "initial_fens": [WHITE_WIN_FEN],
            "batch_root": self.root / "batches",
            "base_seed": 42,
        }
        options.update(kwargs)
        return run_evaluation_comparison(**options)

    def test_same_position_swaps_colors_and_saves_actual_configs(self) -> None:
        result = self.run_comparison(name="P5 smoke", tags=["smoke"])
        manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))
        comparison = json.loads((result.path / "comparison.json").read_text(encoding="utf-8"))
        games = read_csv(result.path / "games.csv")

        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["files"]["comparison"], "comparison.json")
        self.assertEqual(manifest["settings"]["color_assignment"], "paired_swap")
        settings = manifest["settings"]["comparison"]
        self.assertEqual(settings["budget"], {"mode": "fixed_depth", "depth_plies": 1})
        self.assertNotIn("time_ms", settings["budget"])
        self.assertEqual(
            settings["participants"]["candidate"]["evaluator"]["terms"]["material"]
            ["piece_values"]["N"],
            4.0,
        )
        evaluator = dict(settings["participants"]["candidate"]["evaluator"])
        evaluator.pop("type")
        self.assertEqual(EvaluationConfig.from_dict(evaluator), self.candidate_config)
        pair = comparison["pairs"][0]
        self.assertEqual(pair["initial_fen"], chess.Board(WHITE_WIN_FEN).fen())
        self.assertEqual(pair["seed"], 42)
        self.assertEqual(
            [(game["baseline_color"], game["candidate_color"]) for game in pair["games"]],
            [("white", "black"), ("black", "white")],
        )
        self.assertEqual([game["candidate_outcome"] for game in pair["games"]], ["loss", "win"])
        self.assertEqual(result.candidate_stats.to_dict(), {
            "wins": 1, "draws": 0, "losses": 1, "unfinished": 0,
            "completed_games": 2, "score": 1.0,
        })
        self.assertEqual(result.baseline_stats.to_dict(), result.candidate_stats.to_dict())
        self.assertEqual(
            [(game["white_player"], game["black_player"]) for game in games],
            [("stable", "candidate"), ("candidate", "stable")],
        )
        self.assertEqual([int(game["seed"]) for game in games], [42, 42])
        self.assertEqual(
            [game["game_id"] for game in games],
            [game["game_id"] for game in pair["games"]],
        )

    def test_truncated_games_are_unfinished_not_draws(self) -> None:
        result = self.run_comparison(initial_fens=[chess.STARTING_FEN], max_plies=0)
        manifest = json.loads((result.path / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result.candidate_stats.draws, 0)
        self.assertEqual(result.candidate_stats.unfinished, 2)
        self.assertEqual(result.baseline_stats.unfinished, 2)
        self.assertEqual(manifest["results"]["*"], 2)
        self.assertEqual(manifest["counts"]["truncated_games"], 2)

    def test_seeded_pairs_are_reproducible(self) -> None:
        first = self.run_comparison(initial_fens=[chess.STARTING_FEN], max_plies=4)
        second = self.run_comparison(initial_fens=[chess.STARTING_FEN], max_plies=4)

        def replay_moves(path: Path) -> list[list[str]]:
            return [
                json.loads(replay.read_text(encoding="utf-8"))["moves_uci"]
                for replay in sorted((path / "replays").glob("*.json"))
            ]

        self.assertEqual(replay_moves(first.path), replay_moves(second.path))
        self.assertEqual(first.candidate_stats, second.candidate_stats)
        first_pairs = json.loads((first.path / "comparison.json").read_text(encoding="utf-8"))["pairs"]
        second_pairs = json.loads((second.path / "comparison.json").read_text(encoding="utf-8"))["pairs"]
        self.assertEqual(
            [(pair["initial_fen"], pair["seed"]) for pair in first_pairs],
            [(pair["initial_fen"], pair["seed"]) for pair in second_pairs],
        )

    def test_random_remains_a_traceable_baseline(self) -> None:
        result = self.run_comparison(
            baseline=ComparisonParticipant.random_baseline("Random"),
            initial_fens=[chess.STARTING_FEN],
            max_plies=0,
        )
        comparison = json.loads((result.path / "comparison.json").read_text(encoding="utf-8"))

        baseline = comparison["participants"]["baseline"]
        self.assertEqual(baseline, {"label": "Random", "strategy": "Random"})
        self.assertNotIn("evaluator", baseline)

    def test_invalid_comparison_inputs_fail_before_creating_a_batch(self) -> None:
        with self.assertRaises(ValueError):
            ComparisonParticipant.greedy("", self.candidate_config)
        with self.assertRaises(ValueError):
            ComparisonParticipant("Random", "random", self.candidate_config)
        invalid_options = (
            {"candidate": ComparisonParticipant.greedy("stable", self.candidate_config)},
            {"initial_fens": []},
            {"initial_fens": ["invalid"]},
            {"repetitions": 0},
            {"repetitions": "1"},
            {"base_seed": -1},
            {"base_seed": True},
            {"max_plies": -1},
            {"claim_draw": "false"},
        )
        for options in invalid_options:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_comparison(**options)
        self.assertFalse((self.root / "batches").exists())

    def test_cli_accepts_versioned_config_and_rejects_fake_time_budget(self) -> None:
        config_path = self.root / "candidate.json"
        baseline_path = self.root / "baseline.json"
        config_path.write_text(json.dumps(self.candidate_config.to_dict()), encoding="utf-8")
        baseline_path.write_text(json.dumps(self.baseline_config.to_dict()), encoding="utf-8")
        batch_root = self.root / "cli-batches"
        command = [
            sys.executable, "-m", "scripts.compare_evaluations",
            "--candidate-config", str(config_path),
            "--baseline-config", str(baseline_path),
            "--initial-fen", WHITE_WIN_FEN,
            "--batch-root", str(batch_root),
            "--seed", "7",
        ]

        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Budget: fixed_depth, 1 ply", completed.stdout)
        batch = next(batch_root.iterdir())
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["saved_games"], 2)
        saved = dict(manifest["settings"]["comparison"]["participants"]["candidate"]["evaluator"])
        saved.pop("type")
        self.assertEqual(EvaluationConfig.from_dict(saved), self.candidate_config)
        rejected = subprocess.run(
            [*command, "--time-ms", "100"], cwd=ROOT,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("unrecognized arguments: --time-ms 100", rejected.stderr)

    def test_repository_example_configs_are_valid_and_distinct(self) -> None:
        stable = load_evaluation_config(ROOT / "configs/evaluation/stable.json")
        candidate = load_evaluation_config(ROOT / "configs/evaluation/example_pst_half.json")

        self.assertEqual(stable, EvaluationConfig())
        self.assertEqual(candidate.pst_weight, 0.5)
        self.assertNotEqual(stable, candidate)


if __name__ == "__main__":
    unittest.main()
