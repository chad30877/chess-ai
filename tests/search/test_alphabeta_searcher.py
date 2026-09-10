"""Tests for the alpha-beta search scaffold."""

import unittest
from math import inf

import chess

from engine.evaluation.evaluator import MaterialEvaluator
from engine.search.alphabeta import AlphaBetaSearcher
from engine.search.types import CHECKMATE_SCORE, DRAW_SCORE, SearchLimits


class ConstantEvaluator:
    """Simple evaluator used to exercise the search scaffold."""

    def __init__(self, score: float) -> None:
        self.score = score

    def evaluate(self, board: chess.Board) -> float:
        return self.score


class FenScoreEvaluator:
    """Evaluator that assigns fixed White-perspective scores to specific FENs."""

    def __init__(self, scores_by_fen: dict[str, float], default_score: float = 0.0) -> None:
        self.scores_by_fen = scores_by_fen
        self.default_score = default_score

    def evaluate(self, board: chess.Board) -> float:
        return self.scores_by_fen.get(board.fen(), self.default_score)


class RaisingEvaluator:
    """Evaluator used to verify that failed searches leave the root untouched."""

    def evaluate(self, board: chess.Board) -> float:
        raise RuntimeError("evaluation failed")


def _repetition_board(cycles: int, trailing_moves: list[str]) -> chess.Board:
    board = chess.Board()
    for move_uci in ["g1f3", "g8f6", "f3g1", "f6g8"] * cycles + trailing_moves:
        board.push_uci(move_uci)
    return board


def _minimax_reference(
    board: chess.Board,
    evaluator: MaterialEvaluator | ConstantEvaluator,
    depth: int,
    current_depth: int = 0,
) -> tuple[chess.Move | None, float, int, int]:
    if depth <= 0 or board.is_game_over():
        return None, _leaf_score_reference(board, evaluator, current_depth), current_depth, 1

    legal_moves = list(board.legal_moves)

    is_maximizing = board.turn == chess.WHITE
    best_move: chess.Move | None = None
    best_score = -inf if is_maximizing else inf
    depth_reached = current_depth
    nodes_searched = 1

    for move in legal_moves:
        next_board = board.copy(stack=False)
        next_board.push(move)
        _, child_score, child_depth, child_nodes = _minimax_reference(
            next_board,
            evaluator,
            depth - 1,
            current_depth + 1,
        )
        nodes_searched += child_nodes
        depth_reached = max(depth_reached, child_depth)

        if best_move is None:
            best_move = move
            best_score = child_score
            continue

        if is_maximizing and child_score > best_score:
            best_move = move
            best_score = child_score
        elif (not is_maximizing) and child_score < best_score:
            best_move = move
            best_score = child_score

    return best_move, best_score, depth_reached, nodes_searched


def _leaf_score_reference(
    board: chess.Board,
    evaluator: MaterialEvaluator | ConstantEvaluator,
    current_depth: int,
) -> float:
    if board.is_checkmate():
        mate_score = CHECKMATE_SCORE - current_depth
        return mate_score if board.turn == chess.BLACK else -mate_score

    if (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.is_seventyfive_moves()
        or board.is_fivefold_repetition()
    ):
        return DRAW_SCORE

    return evaluator.evaluate(board)


class AlphaBetaSearcherTest(unittest.TestCase):
    def test_constructor_accepts_default_max_depth(self) -> None:
        searcher = AlphaBetaSearcher(ConstantEvaluator(0.0), default_max_depth=3)

        self.assertEqual(searcher.default_limits.max_depth, 3)
        self.assertIsNone(searcher.default_limits.time_ms)

    def test_constructor_accepts_explicit_limits(self) -> None:
        limits = SearchLimits(max_depth=4, time_ms=200)

        searcher = AlphaBetaSearcher(ConstantEvaluator(0.0), limits=limits)

        self.assertIs(searcher.default_limits, limits)

    def test_constructor_rejects_limits_and_non_default_max_depth_together(self) -> None:
        with self.assertRaises(ValueError):
            AlphaBetaSearcher(
                ConstantEvaluator(0.0),
                limits=SearchLimits(max_depth=2),
                default_max_depth=3,
            )

    def test_constructor_rejects_non_boolean_claim_draw_policy(self) -> None:
        with self.assertRaises(ValueError):
            AlphaBetaSearcher(ConstantEvaluator(0.0), claim_draw=1)  # type: ignore[arg-type]

    def test_constructor_rejects_non_boolean_move_ordering_switch(self) -> None:
        with self.assertRaises(ValueError):
            AlphaBetaSearcher(ConstantEvaluator(0.0), move_ordering=1)  # type: ignore[arg-type]

    def test_constructor_rejects_non_boolean_transposition_switch(self) -> None:
        with self.assertRaises(ValueError):
            AlphaBetaSearcher(  # type: ignore[arg-type]
                ConstantEvaluator(0.0), use_transposition_table=1,
            )

    def test_constructor_rejects_non_boolean_pvs_switch(self) -> None:
        with self.assertRaises(ValueError):
            AlphaBetaSearcher(  # type: ignore[arg-type]
                ConstantEvaluator(0.0), use_pvs=1,
            )

    def test_constructor_validates_quiescence_depth(self) -> None:
        self.assertEqual(
            AlphaBetaSearcher(ConstantEvaluator(0.0)).quiescence_depth,
            4,
        )
        self.assertEqual(
            AlphaBetaSearcher(ConstantEvaluator(0.0), quiescence_depth=0).quiescence_depth,
            0,
        )
        for invalid in (-1, 1.5, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                AlphaBetaSearcher(  # type: ignore[arg-type]
                    ConstantEvaluator(0.0), quiescence_depth=invalid,
                )

    def test_search_returns_a_legal_move(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        searcher = AlphaBetaSearcher(
            MaterialEvaluator(), default_max_depth=1, quiescence_depth=0,
        )

        result = searcher.search(board)

        self.assertIsNotNone(result.best_move)
        assert result.best_move is not None
        self.assertIn(result.best_move, board.legal_moves)
        self.assertEqual(result.best_move, chess.Move.from_uci("d1d5"))
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.depth_reached, 1)
        self.assertGreater(result.nodes_searched, 1)
        self.assertEqual(result.cutoff_count, 0)

    def test_search_runs_at_depth_one_and_depth_two(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        searcher = AlphaBetaSearcher(
            MaterialEvaluator(), default_max_depth=3, quiescence_depth=0,
        )

        depth_one_result = searcher.search(board, limits=SearchLimits(max_depth=1))
        depth_two_result = searcher.search(board, limits=SearchLimits(max_depth=2))

        self.assertIsNotNone(depth_one_result.best_move)
        self.assertIsNotNone(depth_two_result.best_move)
        assert depth_one_result.best_move is not None
        assert depth_two_result.best_move is not None
        self.assertIn(depth_one_result.best_move, board.legal_moves)
        self.assertIn(depth_two_result.best_move, board.legal_moves)
        self.assertEqual(depth_one_result.depth_reached, 1)
        self.assertEqual(depth_two_result.depth_reached, 2)
        self.assertEqual(depth_one_result.completed_depth, 1)
        self.assertEqual(depth_two_result.completed_depth, 2)

    def test_depth_two_uses_minimax_reply_scores(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        searcher = AlphaBetaSearcher(
            MaterialEvaluator(), default_max_depth=2, quiescence_depth=0,
        )

        result = searcher.search(board)

        self.assertIsNotNone(result.best_move)
        self.assertNotEqual(result.best_move, chess.Move.from_uci("d1d5"))
        self.assertEqual(result.score, -5.0)
        self.assertEqual(result.depth_reached, 2)
        self.assertGreater(result.nodes_searched, 1)
        self.assertGreaterEqual(result.cutoff_count, 0)

    def test_nodes_searched_accumulates_with_deeper_search(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        searcher = AlphaBetaSearcher(
            MaterialEvaluator(), default_max_depth=3, quiescence_depth=0,
        )

        depth_one_result = searcher.search(board, limits=SearchLimits(max_depth=1))
        depth_two_result = searcher.search(board, limits=SearchLimits(max_depth=2))

        self.assertGreater(depth_one_result.nodes_searched, 1)
        self.assertGreater(depth_two_result.nodes_searched, depth_one_result.nodes_searched)

    def test_alpha_beta_matches_reference_minimax_at_same_depth(self) -> None:
        board = chess.Board("r2q1rk1/ppp2ppp/2n1bn2/3p4/3P4/2PB1N2/PP3PPP/RNBQ1RK1 w - - 0 1")
        evaluator = MaterialEvaluator()
        searcher = AlphaBetaSearcher(
            evaluator, default_max_depth=3, quiescence_depth=0,
        )

        result = searcher.search(board)
        expected_move, expected_score, expected_depth, expected_nodes = _minimax_reference(
            board,
            evaluator,
            depth=3,
        )

        self.assertEqual(result.best_move, expected_move)
        self.assertEqual(result.score, expected_score)
        self.assertEqual(result.depth_reached, expected_depth)
        self.assertLess(result.nodes_searched, expected_nodes)
        self.assertGreater(result.cutoff_count, 0)

    def test_move_ordering_preserves_score_and_reduces_fixture_nodes(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        limits = SearchLimits(max_depth=3)

        unordered = AlphaBetaSearcher(
            MaterialEvaluator(), move_ordering=False, quiescence_depth=0,
        ).search(board, limits)
        ordered = AlphaBetaSearcher(
            MaterialEvaluator(), move_ordering=True, quiescence_depth=0,
        ).search(board, limits)

        self.assertEqual(ordered.score, unordered.score)
        self.assertEqual(ordered.best_move, unordered.best_move)
        self.assertLess(ordered.nodes_searched, unordered.nodes_searched)

    def test_same_searcher_logic_supports_different_evaluators(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")

        board_after_d1d5 = board.copy(stack=False)
        board_after_d1d5.push(chess.Move.from_uci("d1d5"))

        board_after_d1g4 = board.copy(stack=False)
        board_after_d1g4.push(chess.Move.from_uci("d1g4"))

        capture_favoring = AlphaBetaSearcher(
            evaluator=FenScoreEvaluator(
                {
                    board_after_d1d5.fen(): 10.0,
                    board_after_d1g4.fen(): 1.0,
                }
            ),
            default_max_depth=1,
            quiescence_depth=0,
        )
        quiet_favoring = AlphaBetaSearcher(
            evaluator=FenScoreEvaluator(
                {
                    board_after_d1d5.fen(): 1.0,
                    board_after_d1g4.fen(): 10.0,
                }
            ),
            default_max_depth=1,
            quiescence_depth=0,
        )

        capture_result = capture_favoring.search(board)
        quiet_result = quiet_favoring.search(board)

        self.assertEqual(capture_result.best_move, chess.Move.from_uci("d1d5"))
        self.assertEqual(quiet_result.best_move, chess.Move.from_uci("d1g4"))

    def test_search_scores_stalemate_as_draw(self) -> None:
        board = chess.Board("7k/5Q2/7K/8/8/8/8/8 b - - 0 1")
        searcher = AlphaBetaSearcher(ConstantEvaluator(3.5), default_max_depth=2)

        result = searcher.search(board)

        self.assertIsNone(result.best_move)
        self.assertEqual(result.score, DRAW_SCORE)
        self.assertEqual(result.depth_reached, 0)
        self.assertEqual(result.nodes_searched, 1)
        self.assertEqual(result.cutoff_count, 0)

    def test_search_scores_checkmate_from_white_perspective(self) -> None:
        black_is_mated = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        white_is_mated = chess.Board("8/8/8/8/8/6k1/6q1/7K w - - 0 1")
        searcher = AlphaBetaSearcher(ConstantEvaluator(0.0), default_max_depth=1)

        black_result = searcher.search(black_is_mated)
        white_result = searcher.search(white_is_mated)

        self.assertEqual(black_result.score, CHECKMATE_SCORE)
        self.assertEqual(white_result.score, -CHECKMATE_SCORE)

    def test_search_handles_no_legal_moves_without_crashing(self) -> None:
        board = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        searcher = AlphaBetaSearcher(ConstantEvaluator(123.0), default_max_depth=2)

        result = searcher.search(board)

        self.assertIsNone(result.best_move)
        self.assertEqual(result.score, CHECKMATE_SCORE)
        self.assertEqual(result.depth_reached, 0)
        self.assertEqual(result.nodes_searched, 1)
        self.assertEqual(result.cutoff_count, 0)

    def test_search_scores_insufficient_material_as_draw(self) -> None:
        board = chess.Board("8/8/8/8/8/8/2k5/3K4 w - - 0 1")
        searcher = AlphaBetaSearcher(ConstantEvaluator(9.0), default_max_depth=1)

        result = searcher.search(board)

        self.assertEqual(result.score, DRAW_SCORE)
        self.assertEqual(result.nodes_searched, 1)

    def test_search_honors_claimable_draw_policy_at_root(self) -> None:
        board = _repetition_board(1, ["g1f3", "g8f6", "f3g1"])

        claiming_result = AlphaBetaSearcher(
            ConstantEvaluator(8.0), claim_draw=True,
        ).search(board)
        continuing_result = AlphaBetaSearcher(
            ConstantEvaluator(8.0), claim_draw=False,
        ).search(board)

        self.assertIsNone(claiming_result.best_move)
        self.assertEqual(claiming_result.score, DRAW_SCORE)
        self.assertEqual(claiming_result.nodes_searched, 1)
        self.assertIsNotNone(continuing_result.best_move)

    def test_search_preserves_history_for_fivefold_repetition_child(self) -> None:
        board = _repetition_board(3, ["g1f3", "g8f6", "f3g1"])
        repetition_move = chess.Move.from_uci("f6g8")
        repeated_position = board.copy(stack=False)
        repeated_position.push(repetition_move)
        original_fen = board.fen()
        original_stack = list(board.move_stack)
        searcher = AlphaBetaSearcher(
            FenScoreEvaluator({repeated_position.fen(): 100.0}, default_score=1.0),
            claim_draw=False,
        )

        result = searcher.search(board)

        self.assertEqual(result.best_move, repetition_move)
        self.assertEqual(result.score, DRAW_SCORE)
        self.assertEqual(board.fen(), original_fen)
        self.assertEqual(board.move_stack, original_stack)

    def test_search_exception_leaves_root_board_unchanged(self) -> None:
        board = _repetition_board(1, ["g1f3"])
        original_fen = board.fen()
        original_stack = list(board.move_stack)

        with self.assertRaisesRegex(RuntimeError, "evaluation failed"):
            AlphaBetaSearcher(RaisingEvaluator()).search(board)

        self.assertEqual(board.fen(), original_fen)
        self.assertEqual(board.move_stack, original_stack)

    def test_evaluate_leaf_delegates_to_evaluator(self) -> None:
        board = chess.Board()
        searcher = AlphaBetaSearcher(ConstantEvaluator(-0.5))

        self.assertEqual(searcher._evaluate_leaf(board), -0.5)


if __name__ == "__main__":
    unittest.main()
