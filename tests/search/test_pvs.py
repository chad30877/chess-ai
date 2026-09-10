"""Tests for Principal Variation Search narrow-window behavior."""

import unittest

import chess

from engine.evaluation.evaluator import MaterialEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits
from engine.search.alphabeta import _SearchContext


class FenScoreEvaluator:
    def __init__(self, scores: dict[str, float], default: float) -> None:
        self.scores = scores
        self.default = default
        self.calls = 0

    def evaluate(self, board: chess.Board) -> float:
        self.calls += 1
        return self.scores.get(board.fen(), self.default)


def _child_fen(board: chess.Board, move: chess.Move) -> str:
    child = board.copy(stack=True)
    child.push(move)
    return child.fen()


class PrincipalVariationSearchTest(unittest.TestCase):
    def test_maximizing_and_minimizing_nodes_research_only_improvements(self) -> None:
        cases = (
            (chess.Board(), 0.1, 0.2, -5.0),
            (
                chess.Board(
                    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
                ),
                -0.1,
                -0.2,
                5.0,
            ),
        )

        for board, first_score, improved_score, default_score in cases:
            with self.subTest(turn=board.turn):
                moves = list(board.legal_moves)
                evaluator = FenScoreEvaluator(
                    {
                        _child_fen(board, moves[0]): first_score,
                        _child_fen(board, moves[1]): improved_score,
                    },
                    default=default_score,
                )
                result = AlphaBetaSearcher(
                    evaluator,
                    move_ordering=False,
                    quiescence_depth=0,
                    use_transposition_table=False,
                ).search(board, SearchLimits(max_depth=1))

                self.assertEqual(result.best_move, moves[1])
                self.assertEqual(result.score, improved_score)
                self.assertEqual(result.pvs_scouts, len(moves) - 1)
                self.assertEqual(result.pvs_researches, 1)

    def test_scout_cutoff_does_not_trigger_full_window_research(self) -> None:
        cases = (
            (chess.Board(), 2.0, -5.0),
            (
                chess.Board(
                    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
                ),
                -2.0,
                5.0,
            ),
        )

        for board, cutoff_score, default_score in cases:
            with self.subTest(turn=board.turn):
                moves = list(board.legal_moves)
                evaluator = FenScoreEvaluator(
                    {
                        _child_fen(board, moves[0]): 0.0,
                        _child_fen(board, moves[1]): cutoff_score,
                    },
                    default=default_score,
                )
                context = _SearchContext(None, None, None)
                searcher = AlphaBetaSearcher(
                    evaluator,
                    move_ordering=False,
                    quiescence_depth=0,
                    use_transposition_table=False,
                )

                result = searcher._search_recursive(
                    board,
                    depth=1,
                    alpha=-1.0,
                    beta=1.0,
                    current_depth=0,
                    context=context,
                )

                self.assertEqual(result.best_move, moves[1])
                self.assertEqual(result.score, cutoff_score)
                self.assertEqual(context.pvs_scouts, 1)
                self.assertEqual(context.pvs_researches, 0)
                self.assertEqual(evaluator.calls, 2)

    def test_pvs_matches_full_window_alpha_beta_on_tactical_fixture(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        limits = SearchLimits(max_depth=3)

        pvs = AlphaBetaSearcher(
            MaterialEvaluator(),
            quiescence_depth=0,
            use_transposition_table=False,
            aspiration_window=None,
        ).search(board, limits)
        full_window = AlphaBetaSearcher(
            MaterialEvaluator(),
            quiescence_depth=0,
            use_transposition_table=False,
            use_pvs=False,
            aspiration_window=None,
        ).search(board, limits)

        self.assertEqual(pvs.best_move, full_window.best_move)
        self.assertEqual(pvs.score, full_window.score)
        self.assertEqual(pvs.completed_depth, full_window.completed_depth)
        self.assertGreater(pvs.pvs_scouts, 0)
        self.assertGreater(pvs.pvs_researches, 0)
        self.assertLess(pvs.nodes_searched, full_window.nodes_searched)
        self.assertEqual(full_window.pvs_scouts, 0)
        self.assertEqual(full_window.pvs_researches, 0)


if __name__ == "__main__":
    unittest.main()
