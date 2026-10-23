"""公開數值與分項入口保留既有全項、混合及特殊走法評分。"""

from dataclasses import replace
import json
from pathlib import Path
import unittest

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator

ROOT = Path(__file__).resolve().parents[2]


class NumericEvaluationTest(unittest.TestCase):
    def test_numeric_and_explanation_preserve_preoptimization_scores_and_history(self):
        full = EvaluationConfig.from_dict(json.loads(
            (ROOT / 'configs/evaluation/benchmark-all.json').read_text()))
        boards = [chess.Board(), chess.Board(
            '8/5pk1/6p1/8/3R4/6P1/5PK1/7r w - - 0 35')]
        for fen, moves in (
            ('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', ('e1g1', 'e8c8')),
            ('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1', ('e5d6',)),
            ('7k/P7/8/8/8/8/8/4K3 w - - 0 1', ('a7a8n',)),
        ):
            board = chess.Board(fen)
            for move in moves:
                board.push_uci(move)
            boards.append(board)
        # 由優化前 01a22c9 的公開介面記錄，避免兩條路徑一起算錯。
        cases = (
            (full, [-4.163336342344337e-17, .04666666666666667,
                    -.07000000000000003, 1.5, 2.9291666666666667]),
            (replace(full, phase_enabled=False),
             [-4.163336342344337e-17, -.12, -.07, 1.43, 2.45]),
            (replace(full, material_enabled=False, pst_weight=0, endgame_pst_weight=0,
                     pawn_terms={}, mobility_terms={}),
             [0., -.03333333333333333, -.03333333333333333, 0., -.006666666666666666]),
            (replace(full, material_enabled=False, pst_enabled=False, pawn_terms={},
                     mobility_terms={}, king_safety_terms={}, coordination_terms={}), [0.] * 5),
        )
        for config, expected in cases:
            evaluator = HandcraftedEvaluator(config=config)
            for board, score in zip(boards, expected):
                with self.subTest(config=config, fen=board.fen()):
                    before = board.fen(), list(board.move_stack)
                    self.assertEqual(evaluator.evaluate(board), score)
                    detail = evaluator.evaluate_breakdown(board)
                    self.assertEqual(detail.total_score, score)
                    self.assertEqual(sum(t.contribution for t in detail.terms.values()), score)
                    self.assertEqual((board.fen(), board.move_stack), before)
                    self.assertEqual(detail.perspective, 'white')
                    self.assertEqual(detail.score_unit, 'pawn')
