"""Tests for search-layer data structures."""

import unittest

import chess

from engine.search.types import SearchLimits, SearchResult


class SearchLimitsTest(unittest.TestCase):
    def test_accepts_depth_and_optional_time_limit(self) -> None:
        limits = SearchLimits(max_depth=3, time_ms=250)

        self.assertEqual(limits.max_depth, 3)
        self.assertEqual(limits.time_ms, 250)

    def test_rejects_non_positive_values(self) -> None:
        with self.assertRaises(ValueError):
            SearchLimits(max_depth=0)

        with self.assertRaises(ValueError):
            SearchLimits(max_depth=2, time_ms=0)


class SearchResultTest(unittest.TestCase):
    def test_exposes_local_search_summary_fields(self) -> None:
        result = SearchResult(
            best_move=chess.Move.from_uci("e2e4"),
            score=0.7,
            depth_reached=3,
            nodes_searched=42,
            cutoff_count=5,
        )

        self.assertEqual(result.best_move, chess.Move.from_uci("e2e4"))
        self.assertEqual(result.score, 0.7)
        self.assertEqual(result.depth_reached, 3)
        self.assertEqual(result.nodes_searched, 42)
        self.assertEqual(result.cutoff_count, 5)

    def test_rejects_negative_debug_counts(self) -> None:
        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, depth_reached=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, nodes_searched=-1)

        with self.assertRaises(ValueError):
            SearchResult(best_move=None, score=0.0, cutoff_count=-1)


if __name__ == "__main__":
    unittest.main()
