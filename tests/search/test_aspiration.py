"""Tests for iterative-deepening aspiration windows."""

import unittest

import chess

from engine.evaluation.evaluator import MaterialEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits, SearchResult
from engine.search.alphabeta import _SearchContext, _SearchStopped


class ConstantEvaluator:
    def __init__(self, score: float) -> None:
        self.score = score

    def evaluate(self, board: chess.Board) -> float:
        return self.score


class TurnEvaluator:
    def __init__(self, white_turn_score: float, black_turn_score: float) -> None:
        self.white_turn_score = white_turn_score
        self.black_turn_score = black_turn_score

    def evaluate(self, board: chess.Board) -> float:
        return (
            self.white_turn_score
            if board.turn == chess.WHITE
            else self.black_turn_score
        )


class StopDuringAspirationRetrySearcher(AlphaBetaSearcher):
    """Deterministic test double that stops after an aspiration miss."""

    def __init__(self) -> None:
        super().__init__(ConstantEvaluator(0.0), quiescence_depth=0)
        self.root_calls = 0

    def _search_recursive(
        self,
        board: chess.Board,
        depth: int,
        alpha: float,
        beta: float,
        current_depth: int,
        context: _SearchContext | None = None,
    ) -> SearchResult:
        self.root_calls += 1
        assert context is not None
        context.nodes_searched += 1
        context.depth_reached = max(context.depth_reached, depth)
        if self.root_calls == 3:
            raise _SearchStopped("cancelled")
        score = 0.0 if self.root_calls == 1 else 5.0
        return SearchResult(
            best_move=next(iter(board.legal_moves)),
            score=score,
            depth_reached=depth,
            nodes_searched=1,
        )


class AspirationWindowTest(unittest.TestCase):
    def test_stable_score_stays_inside_window_without_research(self) -> None:
        result = AlphaBetaSearcher(
            ConstantEvaluator(0.5),
            quiescence_depth=0,
            use_transposition_table=False,
            use_pvs=False,
        ).search(chess.Board(), SearchLimits(max_depth=2))

        self.assertEqual(result.score, 0.5)
        self.assertEqual(result.completed_depth, 2)
        self.assertEqual(result.aspiration_searches, 1)
        self.assertEqual(result.aspiration_researches, 0)

    def test_fail_high_and_fail_low_retry_with_full_window(self) -> None:
        cases = (
            (chess.Board(), TurnEvaluator(5.0, 0.0), 5.0),
            (
                chess.Board(
                    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
                ),
                TurnEvaluator(0.0, -5.0),
                -5.0,
            ),
        )

        for board, evaluator, expected_score in cases:
            with self.subTest(turn=board.turn):
                result = AlphaBetaSearcher(
                    evaluator,
                    move_ordering=False,
                    quiescence_depth=0,
                    use_transposition_table=False,
                    use_pvs=False,
                ).search(board, SearchLimits(max_depth=2))

                self.assertEqual(result.score, expected_score)
                self.assertEqual(result.completed_depth, 2)
                self.assertEqual(result.aspiration_searches, 1)
                self.assertEqual(result.aspiration_researches, 1)

    def test_score_equal_to_either_window_edge_also_retries(self) -> None:
        cases = (
            (chess.Board(), TurnEvaluator(1.0, 0.0), 1.0),
            (
                chess.Board(
                    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
                ),
                TurnEvaluator(0.0, -1.0),
                -1.0,
            ),
        )

        for board, evaluator, expected_score in cases:
            with self.subTest(turn=board.turn):
                result = AlphaBetaSearcher(
                    evaluator,
                    quiescence_depth=0,
                    use_transposition_table=False,
                    use_pvs=False,
                ).search(board, SearchLimits(max_depth=2))

                self.assertEqual(result.score, expected_score)
                self.assertEqual(result.aspiration_researches, 1)

    def test_disabled_window_matches_enabled_search_on_tactical_fixture(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        limits = SearchLimits(max_depth=3)

        enabled = AlphaBetaSearcher(
            MaterialEvaluator(), quiescence_depth=0,
        ).search(board, limits)
        disabled = AlphaBetaSearcher(
            MaterialEvaluator(),
            quiescence_depth=0,
            aspiration_window=None,
        ).search(board, limits)

        self.assertEqual(enabled.best_move, disabled.best_move)
        self.assertEqual(enabled.score, disabled.score)
        self.assertEqual(enabled.completed_depth, disabled.completed_depth)
        self.assertLess(enabled.nodes_searched, disabled.nodes_searched)
        self.assertEqual(enabled.aspiration_searches, 2)
        self.assertGreater(enabled.aspiration_researches, 0)
        self.assertEqual(disabled.aspiration_searches, 0)
        self.assertEqual(disabled.aspiration_researches, 0)

    def test_stop_during_full_window_retry_returns_prior_completed_depth(self) -> None:
        searcher = StopDuringAspirationRetrySearcher()

        result = searcher.search(chess.Board(), SearchLimits(max_depth=2))

        self.assertEqual(searcher.root_calls, 3)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.completed_depth, 1)
        self.assertEqual(result.depth_reached, 2)
        self.assertEqual(result.stop_reason, "cancelled")
        self.assertEqual(result.aspiration_searches, 1)
        self.assertEqual(result.aspiration_researches, 1)


if __name__ == "__main__":
    unittest.main()
