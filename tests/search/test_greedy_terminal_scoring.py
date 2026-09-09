"""Tests for Greedy's shared terminal scoring and history handling."""

import random
import unittest

import chess

from engine.players import GreedyPlayer


class MisleadingTerminalEvaluator:
    """Prefer stalemate and reject mate if terminal scores are not centralized."""

    def evaluate(self, board: chess.Board) -> float:
        if board.is_stalemate():
            return 2_000_000.0
        if board.is_checkmate():
            return -2_000_000.0
        return 0.0


class FenScoreEvaluator:
    def __init__(self, scores_by_fen: dict[str, float], default_score: float) -> None:
        self.scores_by_fen = scores_by_fen
        self.default_score = default_score

    def evaluate(self, board: chess.Board) -> float:
        return self.scores_by_fen.get(board.fen(), self.default_score)


class RaisingEvaluator:
    def evaluate(self, board: chess.Board) -> float:
        raise RuntimeError("evaluation failed")


def _repetition_board(cycles: int, trailing_moves: list[str]) -> chess.Board:
    board = chess.Board()
    for move_uci in ["g1f3", "g8f6", "f3g1", "f6g8"] * cycles + trailing_moves:
        board.push_uci(move_uci)
    return board


class GreedyTerminalScoringTest(unittest.TestCase):
    def test_greedy_prefers_checkmate_over_misleading_evaluator_scores(self) -> None:
        board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
        player = GreedyPlayer(
            evaluator=MisleadingTerminalEvaluator(),
            rng=random.Random(0),
        )

        move = player.choose_move(board)
        board.push(move)

        self.assertTrue(board.is_checkmate())

    def test_greedy_honors_claimable_draw_policy_at_root(self) -> None:
        board = _repetition_board(1, ["g1f3", "g8f6", "f3g1"])

        with self.assertRaisesRegex(ValueError, "No legal moves"):
            GreedyPlayer(claim_draw=True).choose_move(board)

        self.assertIn(GreedyPlayer(claim_draw=False).choose_move(board), board.legal_moves)

    def test_greedy_preserves_history_when_scoring_repetition_child(self) -> None:
        board = _repetition_board(3, ["g1f3", "g8f6", "f3g1"])
        repetition_move = chess.Move.from_uci("f6g8")
        repeated_position = board.copy(stack=False)
        repeated_position.push(repetition_move)
        original_fen = board.fen()
        original_stack = list(board.move_stack)
        player = GreedyPlayer(
            evaluator=FenScoreEvaluator(
                {repeated_position.fen(): 100.0},
                default_score=1.0,
            ),
            rng=random.Random(0),
        )

        move = player.choose_move(board)

        self.assertEqual(move, repetition_move)
        self.assertEqual(board.fen(), original_fen)
        self.assertEqual(board.move_stack, original_stack)

    def test_greedy_exception_leaves_root_board_unchanged(self) -> None:
        board = _repetition_board(1, ["g1f3"])
        original_fen = board.fen()
        original_stack = list(board.move_stack)

        with self.assertRaisesRegex(RuntimeError, "evaluation failed"):
            GreedyPlayer(evaluator=RaisingEvaluator()).choose_move(board)

        self.assertEqual(board.fen(), original_fen)
        self.assertEqual(board.move_stack, original_stack)


if __name__ == "__main__":
    unittest.main()
