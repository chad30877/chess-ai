"""Tests for the alpha-beta player wrapper."""

import unittest

import chess

from engine.evaluation.evaluator import MaterialEvaluator
from engine.players import AlphaBetaPlayer
from engine.search import AlphaBetaSearcher, SearchLimits, SearchResult


class RecordingSearcher:
    """Test double that records search calls and returns a fixed result."""

    def __init__(self, result: SearchResult) -> None:
        self.result = result
        self.calls: list[chess.Board] = []

    def search(self, board: chess.Board, limits: object | None = None) -> SearchResult:
        self.calls.append(board)
        return self.result


class AlphaBetaPlayerTest(unittest.TestCase):
    def test_choose_move_delegates_to_searcher(self) -> None:
        board = chess.Board()
        searcher = RecordingSearcher(
            SearchResult(best_move=chess.Move.from_uci("e2e4"), score=0.5, depth_reached=1, nodes_searched=20)
        )
        player = AlphaBetaPlayer(searcher=searcher)

        move = player.choose_move(board)

        self.assertEqual(move, chess.Move.from_uci("e2e4"))
        self.assertEqual(searcher.calls, [board])
        self.assertEqual(board.fen(), chess.Board().fen())

    def test_choose_move_raises_when_search_returns_no_move(self) -> None:
        board = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        searcher = RecordingSearcher(
            SearchResult(best_move=None, score=1_000_000.0, depth_reached=0, nodes_searched=1)
        )
        player = AlphaBetaPlayer(searcher=searcher)

        with self.assertRaises(ValueError):
            player.choose_move(board)

    def test_choose_move_returns_legal_move_with_real_searcher(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        player = AlphaBetaPlayer(
            searcher=AlphaBetaSearcher(MaterialEvaluator(), default_max_depth=2)
        )

        move = player.choose_move(board)

        self.assertIn(move, board.legal_moves)

    def test_from_evaluator_builds_searcher_owned_evaluator(self) -> None:
        evaluator = MaterialEvaluator()
        player = AlphaBetaPlayer.from_evaluator(
            evaluator=evaluator,
            limits=SearchLimits(max_depth=2),
        )

        self.assertIsInstance(player.searcher, AlphaBetaSearcher)
        assert isinstance(player.searcher, AlphaBetaSearcher)
        self.assertIs(player.searcher.evaluator, evaluator)
        self.assertEqual(player.searcher.default_limits.max_depth, 2)


if __name__ == "__main__":
    unittest.main()
