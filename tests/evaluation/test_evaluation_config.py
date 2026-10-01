"""Versioned evaluation settings, term weights, and score breakdowns."""

from copy import deepcopy
import unittest

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.players import GreedyPlayer, RandomPlayer
from engine.strategy_config import strategy_config


class EvaluationConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.board = chess.Board("4k3/8/8/8/3N4/8/8/3qK3 w - - 0 1")

    def test_default_config_roundtrips_and_uses_white_pawn_scale(self) -> None:
        config = EvaluationConfig()

        self.assertEqual(config.piece_values["P"], 1.0)
        self.assertEqual(config, EvaluationConfig.from_dict(config.to_dict()))
        self.assertEqual(config.to_dict()["perspective"], "white")
        self.assertEqual(config.to_dict()["score_unit"], "pawn")
        with self.assertRaises(TypeError):
            config.piece_values["P"] = 2

    def test_default_score_matches_material_plus_unchanged_pst(self) -> None:
        evaluator = HandcraftedEvaluator()
        breakdown = evaluator.evaluate_breakdown(self.board)

        expected = MaterialEvaluator().evaluate(self.board)
        expected += breakdown.terms["piece_square"].raw_value
        self.assertAlmostEqual(evaluator.evaluate(self.board), expected)
        self.assertAlmostEqual(
            breakdown.total_score,
            sum(term.contribution for term in breakdown.terms.values()),
        )
        self.assertEqual(breakdown.perspective, "white")

    def test_weights_and_switches_change_only_their_contribution(self) -> None:
        default = HandcraftedEvaluator().evaluate_breakdown(self.board)
        custom = HandcraftedEvaluator(config=EvaluationConfig(
            piece_values={"Q": 12}, pst_weight=2.5,
        )).evaluate_breakdown(self.board)
        disabled = HandcraftedEvaluator(config=EvaluationConfig(
            material_enabled=False, pst_enabled=False, pst_weight=3,
        )).evaluate_breakdown(self.board)

        self.assertEqual(custom.terms["material"].raw_value, -9.0)
        self.assertAlmostEqual(
            custom.terms["piece_square"].contribution,
            default.terms["piece_square"].raw_value * 2.5,
        )
        self.assertEqual(disabled.terms["material"].contribution, 0.0)
        self.assertEqual(disabled.terms["piece_square"].contribution, 0.0)
        self.assertEqual(disabled.total_score, 0.0)
        self.assertNotEqual(disabled.terms["material"].raw_value, 0.0)
        self.assertIn("direction", default.to_dict()["terms"]["material"])

    def test_invalid_config_values_and_schema_are_rejected(self) -> None:
        for kwargs in (
            {"piece_values": {"X": 1}},
            {"piece_values": {"P": 0}},
            {"piece_values": {"N": -1}},
            {"piece_values": {"Q": float("nan")}},
            {"pst_weight": -1},
            {"pst_weight": float("inf")},
            {"pst_enabled": 1},
            {"version": 5},
            {"piece_values": {"P": True}},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                EvaluationConfig(**kwargs)
        with self.assertRaises(ValueError):
            HandcraftedEvaluator(config="not a config")

        payload = EvaluationConfig().to_dict()
        corruptions = []
        wrong_perspective = deepcopy(payload)
        wrong_perspective["perspective"] = "side_to_move"
        corruptions.append(wrong_perspective)
        wrong_table = deepcopy(payload)
        wrong_table["terms"]["piece_square"]["table_version"] = 2
        corruptions.append(wrong_table)
        missing_piece = deepcopy(payload)
        del missing_piece["terms"]["material"]["piece_values"]["Q"]
        corruptions.append(missing_piece)
        for corrupted in corruptions:
            with self.subTest(corrupted=corrupted), self.assertRaises(ValueError):
                EvaluationConfig.from_dict(corrupted)

    def test_strategy_snapshot_reads_the_injected_evaluator(self) -> None:
        config = EvaluationConfig(piece_values={"N": 4.25}, pst_weight=0.4)
        player = GreedyPlayer(config=config)

        saved = strategy_config("Greedy", player)

        self.assertEqual(saved["evaluator"]["type"], "handcrafted")
        evaluator_payload = {key: value for key, value in saved["evaluator"].items()
                             if key != "type"}
        self.assertEqual(EvaluationConfig.from_dict(evaluator_payload), config)
        self.assertEqual(strategy_config("Random", RandomPlayer()), {"strategy": "Random"})
        with self.assertRaises(ValueError):
            strategy_config("Greedy", None)


if __name__ == "__main__":
    unittest.main()
