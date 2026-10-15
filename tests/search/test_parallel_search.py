import unittest
import chess
from engine.evaluation.evaluator import MaterialEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits
from engine.search.types import CHECKMATE_SCORE

class ParallelSearchTests(unittest.TestCase):
    def test_spawn_finds_mate_with_original_root_distance_and_preserves_board(self):
        board = chess.Board('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1')
        original = board.fen()
        searcher = AlphaBetaSearcher(MaterialEvaluator(), search_workers=2)
        try:
            result = searcher.search(board, SearchLimits(max_depth=2))
            after = board.copy(); after.push(result.best_move)
            self.assertTrue(after.is_checkmate())
            self.assertEqual(result.score, CHECKMATE_SCORE - 1)
            self.assertEqual(result.completed_depth, 2)
            self.assertEqual(board.fen(), original)
        finally:
            searcher.close()
