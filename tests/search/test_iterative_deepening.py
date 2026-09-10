"""Tests for iterative deepening, time limits, and cooperative cancellation."""

import unittest
from unittest.mock import patch

import chess

from engine.evaluation.evaluator import MaterialEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits


class StopOnCall:
    def __init__(self, stop_call: int) -> None:
        self.stop_call = stop_call
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls >= self.stop_call


class StepClock:
    def __init__(self, advance_call: int) -> None:
        self.advance_call = advance_call
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return 1.0 if self.calls >= self.advance_call else 0.0


class IterativeDeepeningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.board = chess.Board()
        self.searcher = AlphaBetaSearcher(
            MaterialEvaluator(),
            quiescence_depth=0,
        )

    def test_unlimited_search_completes_requested_iterations(self) -> None:
        result = self.searcher.search(self.board, SearchLimits(max_depth=3))

        self.assertEqual(result.completed_depth, 3)
        self.assertEqual(result.depth_reached, 3)
        self.assertIsNone(result.stop_reason)
        self.assertIsNotNone(result.best_move)

    def test_cancellation_returns_last_completed_iteration_and_partial_depth(self) -> None:
        expected = self.searcher.search(self.board, SearchLimits(max_depth=1))
        stop = StopOnCall(24)
        original_fen = self.board.fen()
        original_stack = list(self.board.move_stack)

        result = self.searcher.search(
            self.board,
            SearchLimits(max_depth=4, stop_requested=stop),
        )

        self.assertEqual(result.best_move, expected.best_move)
        self.assertEqual(result.score, expected.score)
        self.assertEqual(result.completed_depth, 1)
        self.assertEqual(result.depth_reached, 2)
        self.assertEqual(result.stop_reason, "cancelled")
        self.assertEqual(self.board.fen(), original_fen)
        self.assertEqual(self.board.move_stack, original_stack)

    def test_timeout_returns_last_completed_iteration(self) -> None:
        expected = self.searcher.search(self.board, SearchLimits(max_depth=1))
        clock = StepClock(25)
        original_fen = self.board.fen()
        original_stack = list(self.board.move_stack)

        with patch("engine.search.alphabeta.monotonic", side_effect=clock):
            result = self.searcher.search(
                self.board,
                SearchLimits(max_depth=4, time_ms=500),
            )

        self.assertEqual(result.best_move, expected.best_move)
        self.assertEqual(result.score, expected.score)
        self.assertEqual(result.completed_depth, 1)
        self.assertEqual(result.depth_reached, 2)
        self.assertEqual(result.stop_reason, "timeout")
        self.assertEqual(self.board.fen(), original_fen)
        self.assertEqual(self.board.move_stack, original_stack)

    def test_immediate_cancellation_returns_legal_depth_zero_fallback(self) -> None:
        result = self.searcher.search(
            self.board,
            SearchLimits(max_depth=4, stop_requested=lambda: True),
        )

        self.assertIn(result.best_move, self.board.legal_moves)
        self.assertEqual(result.completed_depth, 0)
        self.assertEqual(result.depth_reached, 0)
        self.assertEqual(result.stop_reason, "cancelled")

    def test_terminal_result_precedes_stop_signal(self) -> None:
        board = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        stop = StopOnCall(1)

        result = self.searcher.search(
            board,
            SearchLimits(max_depth=4, stop_requested=stop),
        )

        self.assertIsNone(result.best_move)
        self.assertEqual(result.completed_depth, 0)
        self.assertIsNone(result.stop_reason)
        self.assertEqual(stop.calls, 0)


if __name__ == "__main__":
    unittest.main()
