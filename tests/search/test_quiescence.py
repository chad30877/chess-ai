"""Tests for capture quiescence and check-evasion semantics."""

import unittest
from math import inf

import chess

from engine.evaluation.evaluator import MaterialEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits


class ConstantEvaluator:
    def __init__(self, score: float) -> None:
        self.score = score

    def evaluate(self, board: chess.Board) -> float:
        return self.score


class QuiescenceTest(unittest.TestCase):
    def test_capture_extension_avoids_horizon_exchange(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        limits = SearchLimits(max_depth=1)

        static_result = AlphaBetaSearcher(
            MaterialEvaluator(), quiescence_depth=0,
        ).search(board, limits)
        quiet_result = AlphaBetaSearcher(
            MaterialEvaluator(), quiescence_depth=4,
        ).search(board, limits)

        self.assertEqual(static_result.best_move, chess.Move.from_uci("d1d5"))
        self.assertEqual(static_result.score, 0.0)
        self.assertEqual(quiet_result.best_move, chess.Move.from_uci("d1g4"))
        self.assertEqual(quiet_result.score, -5.0)
        self.assertGreater(quiet_result.depth_reached, limits.max_depth)

    def test_checked_node_searches_all_evasions_without_stand_pat(self) -> None:
        board = chess.Board("4k3/8/8/8/8/8/8/4R1K1 b - - 0 1")
        searcher = AlphaBetaSearcher(ConstantEvaluator(17.0), quiescence_depth=2)

        result = searcher._quiescence(board, -inf, inf, 0, 2)

        self.assertIsNotNone(result.best_move)
        assert result.best_move is not None
        self.assertIn(result.best_move, board.legal_moves)
        self.assertGreater(result.nodes_searched, 1)
        self.assertGreaterEqual(result.depth_reached, 1)

    def test_hard_boundary_still_searches_one_check_evasion_ply(self) -> None:
        board = chess.Board("4k3/8/8/8/8/8/8/4R1K1 b - - 0 1")
        searcher = AlphaBetaSearcher(ConstantEvaluator(17.0), quiescence_depth=0)

        result = searcher._quiescence(board, -inf, inf, 3, 0)

        self.assertIsNotNone(result.best_move)
        self.assertGreater(result.nodes_searched, 1)
        self.assertEqual(result.depth_reached, 4)

    def test_quiet_node_at_boundary_returns_stand_pat_only(self) -> None:
        board = chess.Board()
        searcher = AlphaBetaSearcher(ConstantEvaluator(2.5), quiescence_depth=0)

        result = searcher._quiescence(board, -inf, inf, 3, 0)

        self.assertIsNone(result.best_move)
        self.assertEqual(result.score, 2.5)
        self.assertEqual(result.nodes_searched, 1)
        self.assertEqual(result.depth_reached, 3)


if __name__ == "__main__":
    unittest.main()
