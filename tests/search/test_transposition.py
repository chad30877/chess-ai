"""Tests for history-safe alpha-beta transposition caching."""

import unittest
from math import inf

import chess

from engine.evaluation.evaluator import MaterialEvaluator
from engine.search import (
    AlphaBetaSearcher,
    BoundType,
    SearchLimits,
    TranspositionEntry,
    TranspositionTable,
    classify_bound,
    make_transposition_key,
)
from engine.search.alphabeta import _SearchContext


class MutableEvaluator:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls = 0

    def evaluate(self, board: chess.Board) -> float:
        self.calls += 1
        return self.score


class TranspositionKeyTest(unittest.TestCase):
    def test_same_fen_with_different_reversible_history_has_different_key(self) -> None:
        board = chess.Board()
        for move in ("g1f3", "g8f6", "f3g1", "f6g8"):
            board.push_uci(move)
        without_history = board.copy(stack=False)
        original_fen = board.fen()
        original_stack = list(board.move_stack)

        history_key = make_transposition_key(board, ply_from_root=0)
        fen_only_key = make_transposition_key(without_history, ply_from_root=0)

        self.assertEqual(history_key.position, fen_only_key.position)
        self.assertEqual(history_key.halfmove_clock, fen_only_key.halfmove_clock)
        self.assertNotEqual(history_key, fen_only_key)
        self.assertEqual(board.fen(), original_fen)
        self.assertEqual(board.move_stack, original_stack)

    def test_root_ply_separates_root_relative_mate_scores(self) -> None:
        board = chess.Board("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")

        early_key = make_transposition_key(board, ply_from_root=1)
        late_key = make_transposition_key(board, ply_from_root=3)

        self.assertNotEqual(early_key, late_key)

    def test_rejects_negative_root_ply(self) -> None:
        for invalid in (-1, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                make_transposition_key(  # type: ignore[arg-type]
                    chess.Board(), ply_from_root=invalid,
                )


class TranspositionTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.key = make_transposition_key(chess.Board(), ply_from_root=0)

    def test_classifies_exact_lower_and_upper_bounds(self) -> None:
        self.assertIs(classify_bound(0.0, -1.0, 1.0), BoundType.EXACT)
        self.assertIs(classify_bound(1.0, -1.0, 1.0), BoundType.LOWER)
        self.assertIs(classify_bound(-1.0, -1.0, 1.0), BoundType.UPPER)

    def test_replacement_prefers_depth_then_exact_bound(self) -> None:
        table = TranspositionTable()
        first = TranspositionEntry(
            depth=2,
            score=3.0,
            bound=BoundType.LOWER,
            best_move=chess.Move.from_uci("e2e4"),
        )
        exact = TranspositionEntry(
            depth=2,
            score=2.5,
            bound=BoundType.EXACT,
            best_move=chess.Move.from_uci("d2d4"),
        )
        weaker = TranspositionEntry(
            depth=2,
            score=2.0,
            bound=BoundType.UPPER,
            best_move=None,
        )
        deeper = TranspositionEntry(
            depth=3,
            score=4.0,
            bound=BoundType.LOWER,
            best_move=chess.Move.from_uci("g1f3"),
        )

        self.assertTrue(table.store(self.key, first))
        self.assertTrue(table.store(self.key, exact))
        self.assertFalse(table.store(self.key, weaker))
        self.assertIs(table.probe(self.key), exact)
        self.assertTrue(table.store(self.key, deeper))
        self.assertIs(table.probe(self.key), deeper)
        self.assertEqual(len(table), 1)

    def test_rejects_negative_entry_depth(self) -> None:
        for invalid in (-1, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                TranspositionEntry(  # type: ignore[arg-type]
                    invalid, 0.0, BoundType.EXACT, None,
                )


class AlphaBetaTranspositionIntegrationTest(unittest.TestCase):
    def test_lower_and_upper_entries_close_matching_windows(self) -> None:
        board = chess.Board()
        key = make_transposition_key(board, ply_from_root=0)
        cases = (
            (BoundType.LOWER, 5.0, 0.0, 4.0),
            (BoundType.UPPER, -5.0, -4.0, 0.0),
        )

        for bound, score, alpha, beta in cases:
            with self.subTest(bound=bound):
                table = TranspositionTable()
                table.store(
                    key,
                    TranspositionEntry(
                        depth=1,
                        score=score,
                        bound=bound,
                        best_move=chess.Move.from_uci("e2e4"),
                    ),
                )
                context = _SearchContext(None, None, table)
                evaluator = MutableEvaluator(99.0)
                searcher = AlphaBetaSearcher(evaluator, quiescence_depth=0)

                result = searcher._search_recursive(
                    board,
                    depth=1,
                    alpha=alpha,
                    beta=beta,
                    current_depth=0,
                    context=context,
                )

                self.assertEqual(result.score, score)
                self.assertEqual(result.best_move, chess.Move.from_uci("e2e4"))
                self.assertEqual(result.nodes_searched, 1)
                self.assertEqual(result.cutoff_count, 1)
                self.assertEqual(evaluator.calls, 0)
                self.assertEqual(context.transposition_hits, 1)

    def test_repeated_node_reuses_exact_result_and_best_move(self) -> None:
        evaluator = MutableEvaluator(1.25)
        searcher = AlphaBetaSearcher(
            evaluator,
            quiescence_depth=0,
        )
        context = _SearchContext(
            deadline=None,
            stop_requested=None,
            transposition_table=TranspositionTable(),
        )
        board = chess.Board()

        first = searcher._search_recursive(board, 1, -inf, inf, 0, context)
        calls_after_first = evaluator.calls
        second = searcher._search_recursive(board, 1, -inf, inf, 0, context)

        self.assertEqual(second.best_move, first.best_move)
        self.assertEqual(second.score, first.score)
        self.assertEqual(second.nodes_searched, 1)
        self.assertEqual(evaluator.calls, calls_after_first)
        self.assertEqual(context.transposition_hits, 1)

    def test_public_search_reports_hits_and_can_disable_table(self) -> None:
        board = chess.Board("6k1/8/3q4/3r4/8/8/8/3Q2K1 w - - 0 1")
        limits = SearchLimits(max_depth=3)

        cached = AlphaBetaSearcher(
            MaterialEvaluator(),
            quiescence_depth=0,
        ).search(board, limits)
        uncached = AlphaBetaSearcher(
            MaterialEvaluator(),
            quiescence_depth=0,
            use_transposition_table=False,
        ).search(board, limits)

        self.assertEqual(cached.best_move, uncached.best_move)
        self.assertEqual(cached.score, uncached.score)
        self.assertGreater(cached.transposition_hits, 0)
        self.assertGreater(cached.transposition_stores, 0)
        self.assertEqual(uncached.transposition_hits, 0)
        self.assertEqual(uncached.transposition_stores, 0)

    def test_each_search_uses_a_fresh_table_after_evaluator_change(self) -> None:
        evaluator = MutableEvaluator(1.0)
        searcher = AlphaBetaSearcher(
            evaluator,
            quiescence_depth=0,
        )
        board = chess.Board()

        first = searcher.search(board, SearchLimits(max_depth=1))
        evaluator.score = 7.0
        second = searcher.search(board, SearchLimits(max_depth=1))

        self.assertEqual(first.score, 1.0)
        self.assertEqual(second.score, 7.0)
        self.assertEqual(second.transposition_hits, 0)


if __name__ == "__main__":
    unittest.main()
