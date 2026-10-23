"""完整評分數值與說明介面在單／多程序搜尋維持相同選步與分數。"""

import json
from pathlib import Path
import unittest

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits

ROOT = Path(__file__).resolve().parents[2]


class ExplanationEvaluator(HandcraftedEvaluator):
    def evaluate(self, board):
        return self.evaluate_breakdown(board).total_score


class NumericSearchTest(unittest.TestCase):
    def test_full_configuration_keeps_unique_capture_in_single_and_spawn_search(self):
        config = EvaluationConfig.from_dict(json.loads(
            (ROOT / 'configs/evaluation/benchmark-all.json').read_text()))
        board = chess.Board('7k/8/8/8/3q4/8/3Q4/6K1 w - - 0 1')
        before = board.fen(), list(board.move_stack)
        # 逐一強制根走法後以公開搜尋完成其餘深度，確認沒有同分替代。
        scores = {}
        verifier = AlphaBetaSearcher(ExplanationEvaluator(config=config), quiescence_depth=2)
        try:
            for move in list(board.legal_moves):
                child = board.copy()
                child.push(move)
                scores[move.uci()] = verifier.search(child, SearchLimits(max_depth=1)).score
        finally:
            verifier.close()
        self.assertEqual([move for move, score in scores.items() if score == max(scores.values())],
                         ['d2d4'])
        reference = None
        for workers, kind in ((1, ExplanationEvaluator), (1, HandcraftedEvaluator),
                              (2, HandcraftedEvaluator)):
            with self.subTest(workers=workers, evaluator=kind.__name__):
                searcher = AlphaBetaSearcher(kind(config=config), search_workers=workers,
                                            quiescence_depth=2)
                try:
                    result = searcher.search(board, SearchLimits(max_depth=2))
                finally:
                    searcher.close()
                # 優化前 01a22c9：唯一不丟失后子的吃后走法。
                self.assertEqual(result.best_move.uci(), 'd2d4')
                self.assertEqual(result.score, 9.56)
                self.assertEqual(result.completed_depth, 2)
                self.assertIsNone(result.stop_reason)
                self.assertEqual((board.fen(), board.move_stack), before)
                if reference is None:
                    reference = result
                elif workers == 1:
                    self.assertEqual(result, reference)
