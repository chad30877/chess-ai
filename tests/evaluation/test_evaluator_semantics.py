"""Tests for shared evaluator score semantics."""

import unittest

import chess

from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator, evaluate_material
from engine.evaluation.pst import evaluate_piece_square_tables


class EvaluatorSemanticsTest(unittest.TestCase):
    def test_material_evaluator_is_white_perspective_not_side_to_move(self) -> None:
        board = chess.Board("4k3/8/8/8/8/8/8/3QK3 b - - 0 1")

        self.assertEqual(MaterialEvaluator().evaluate(board), 9.0)

    def test_handcrafted_evaluator_keeps_material_and_pst_as_separate_terms(self) -> None:
        board = chess.Board("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1")

        expected_score = evaluate_material(board) + evaluate_piece_square_tables(board)

        self.assertAlmostEqual(HandcraftedEvaluator().evaluate(board), expected_score)


if __name__ == "__main__":
    unittest.main()
