"""Regression coverage for the retained match CLI after removing ML."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import call, patch

import chess

from engine.evaluator import MaterialEvaluator
from engine.players import GreedyPlayer, RandomPlayer
from scripts.engine_match import MatchStats, build_player, play_one_game, run_match


ROOT = Path(__file__).resolve().parents[1]


class EngineMatchTest(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.engine_match", *args],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )

    def test_player_types_material_semantics_and_seeded_legal_moves(self):
        board = chess.Board("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1")
        material = build_player("material", 1, 1)
        self.assertIsInstance(material, GreedyPlayer)
        self.assertIs(type(material.evaluator), MaterialEvaluator)
        self.assertEqual(material.evaluator.evaluate(board), 3.0)
        self.assertIsInstance(build_player("random", 1, 1), RandomPlayer)
        for kind in ("random", "material"):
            with self.subTest(kind=kind):
                first, second = build_player(kind, 3, 2), build_player(kind, 3, 2)
                moves = [first.choose_move(board) for _ in range(10)]
                self.assertEqual(moves, [second.choose_move(board) for _ in range(10)])
                self.assertTrue(all(move in board.legal_moves for move in moves))

    def test_colors_alternate_and_results_use_engine_a_perspective(self):
        positions = [
            ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", ("win", "loss")),
            ("8/8/8/8/8/5k2/6q1/7K w - - 0 1", ("loss", "win")),
            ("7k/8/8/8/8/8/8/K7 w - - 0 1", ("draw", "draw")),
        ]
        for fen, expected in positions:
            for game_id in (1, 2):
                with self.subTest(fen=fen, game_id=game_id), patch(
                    "scripts.engine_match.create_board", return_value=chess.Board(fen)
                ), patch("scripts.engine_match.build_player") as factory:
                    self.assertEqual(play_one_game(game_id, "material", "random"), expected[game_id - 1])
                    white, black = ("material", "random") if game_id == 1 else ("random", "material")
                    self.assertEqual(factory.call_args_list, [call(white, game_id, 1), call(black, game_id, 2)])

    def test_match_statistics(self):
        with patch("scripts.engine_match.play_one_game", side_effect=["win", "draw", "loss", "win"]):
            self.assertEqual(run_match("material", "random", 4), MatchStats(2, 1, 1))

    def test_cli_plays_two_complete_games_with_both_options(self):
        result = self.cli("--engine-a", "material", "--engine-b", "random", "--games", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Engine A: material", result.stdout)
        self.assertIn("Engine B: random", result.stdout)
        counts = [int(line.split(": ")[1]) for line in result.stdout.splitlines()
                  if line.startswith(("win: ", "draw: ", "loss: "))]
        self.assertEqual(len(counts), 3)
        self.assertEqual(sum(counts), 2)

    def test_cli_rejects_removed_options(self):
        for side in ("--engine-a", "--engine-b"):
            args = ["--engine-a", "material", "--engine-b", "random"]
            args[args.index(side) + 1] = "ml"
            with self.subTest(side=side):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid choice", result.stderr)
        result = self.cli("--engine-a", "material", "--engine-b", "random", "--ml-model", "obsolete.pkl")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: --ml-model", result.stderr)
        with self.assertRaisesRegex(ValueError, "Unsupported engine type"):
            build_player("ml", 1, 1)

    def test_cli_help_and_invalid_game_count(self):
        result = self.cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{material,random}", result.stdout)
        self.assertNotIn("--ml-model", result.stdout)
        result = self.cli("--engine-a", "random", "--engine-b", "material", "--games", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--games must be greater than 0", result.stderr)


if __name__ == "__main__":
    unittest.main()
