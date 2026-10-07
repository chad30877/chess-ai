"""Tests for search-layer data structures."""

import unittest

import chess

from engine.search.types import SearchLimits, SearchResult


class SearchLimitsTest(unittest.TestCase):
    def test_accepts_depth_and_optional_time_limit(self) -> None:
        stop_requested = lambda: False
        limits = SearchLimits(
            max_depth=3,
            time_ms=250,
            stop_requested=stop_requested,
        )

        self.assertEqual(limits.max_depth, 3)
        self.assertEqual(limits.time_ms, 250)
        self.assertIs(limits.stop_requested, stop_requested)

    def test_rejects_non_positive_values(self) -> None:
        with self.assertRaises(ValueError):
            SearchLimits(max_depth=0)

        for invalid_depth in (True, 1.5):
            with self.subTest(invalid_depth=invalid_depth), self.assertRaises(ValueError):
                SearchLimits(max_depth=invalid_depth)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            SearchLimits(max_depth=2, time_ms=0)

        for invalid_time in (True, 1.5):
            with self.subTest(invalid_time=invalid_time), self.assertRaises(ValueError):
                SearchLimits(max_depth=2, time_ms=invalid_time)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            SearchLimits(max_depth=2, stop_requested=False)  # type: ignore[arg-type]


class SearchResultTest(unittest.TestCase):
    def test_exposes_local_search_summary_fields(self) -> None:
        result = SearchResult(
            best_move=chess.Move.from_uci("e2e4"),
            score=0.7,
            depth_reached=3,
            nodes_searched=42,
            cutoff_count=5,
            transposition_hits=6,
            transposition_stores=7,
            pvs_scouts=8,
            pvs_researches=9,
            aspiration_searches=10,
            aspiration_researches=11,
            completed_depth=3,
            stop_reason="timeout",
        )

        self.assertEqual(result.best_move, chess.Move.from_uci("e2e4"))
        self.assertEqual(result.score, 0.7)
        self.assertEqual(result.depth_reached, 3)
        self.assertEqual(result.nodes_searched, 42)
        self.assertEqual(result.cutoff_count, 5)
        self.assertEqual(result.transposition_hits, 6)
        self.assertEqual(result.transposition_stores, 7)
        self.assertEqual(result.pvs_scouts, 8)
        self.assertEqual(result.pvs_researches, 9)
        self.assertEqual(result.aspiration_searches, 10)
        self.assertEqual(result.aspiration_researches, 11)
        self.assertEqual(result.completed_depth, 3)
        self.assertEqual(result.stop_reason, "timeout")

    def test_rejects_negative_debug_counts(self) -> None:
        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, depth_reached=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, nodes_searched=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, cutoff_count=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, transposition_hits=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, transposition_stores=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, pvs_scouts=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, pvs_researches=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, aspiration_searches=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, aspiration_researches=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, completed_depth=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, stop_reason="unknown")

    def test_completed_iteration_and_visited_depth_are_independent(self):
        for completed, visited in ((2, 1), (1, 4), (0, 0)):
            with self.subTest(completed=completed, visited=visited):
                result = SearchResult(best_move=None, score=0.0, completed_depth=completed,
                                      depth_reached=visited)
                self.assertEqual(result.completed_depth, completed)
                self.assertEqual(result.depth_reached, visited)


if __name__ == "__main__":
    unittest.main()
