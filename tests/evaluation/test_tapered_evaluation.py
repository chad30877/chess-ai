"""Tapered endpoint semantics, phase boundaries, compatibility and snapshots."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.evaluation.pst import middlegame_phase, evaluate_piece_square_tables
from engine.players import GreedyPlayer
from engine.strategy_config import strategy_config

ROOT = Path(__file__).resolve().parents[2]


class TaperedEvaluationTest(unittest.TestCase):
    def test_phase_endpoints_pawns_and_promotion_cap(self):
        self.assertEqual(middlegame_phase(chess.Board()), 1.0)
        self.assertEqual(middlegame_phase(chess.Board("7k/8/8/8/8/8/PPPPPPPP/K7 w - - 0 1")), 0.0)
        promoted = chess.Board("qqqqqqqk/8/8/8/8/8/8/KQQQQQQQ w - - 0 1")
        self.assertEqual(middlegame_phase(promoted), 1.0)
        self.assertEqual(middlegame_phase(chess.Board("7k/8/8/8/8/8/8/KBNRQ3 w - - 0 1")), 8 / 24)

    def test_endpoint_scores_and_endgame_king_activity(self):
        evaluator = HandcraftedEvaluator(config=EvaluationConfig(phase_enabled=True))
        opening = chess.Board()
        opening.remove_piece_at(chess.B1)  # partial phase; restore unit on another square
        opening.set_piece_at(chess.C3, chess.Piece(chess.KNIGHT, chess.WHITE))
        result = evaluator.evaluate_breakdown(opening)
        self.assertEqual(result.phase["middlegame"], 1.0)
        self.assertAlmostEqual(result.total_score, HandcraftedEvaluator().evaluate(opening))
        center = chess.Board("7k/8/8/8/3K4/8/8/8 w - - 0 1")
        edge = chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1")
        result = evaluator.evaluate_breakdown(center)
        self.assertEqual(result.phase["endgame"], 1.0)
        self.assertAlmostEqual(result.total_score, 0.55)
        self.assertGreater(evaluator.evaluate(center), evaluator.evaluate(edge))

    def test_weighted_endpoint_interpolation_has_no_cross_terms(self):
        board = chess.Board("7k/8/8/8/3K4/8/8/Q7 w - - 0 1")
        result = HandcraftedEvaluator(config=EvaluationConfig(
            phase_enabled=True, piece_values={"Q": 9}, endgame_piece_values={"Q": 12},
            pst_weight=2, endgame_pst_weight=3,
        )).evaluate_breakdown(board)
        # One queen = 4/24 MG. King d4: MG=-.25, EG=.25;
        # queen a1=-.05; black king h8 mirrors h1: MG=.15, EG=-.30.
        expected_mg = 9 + 2 * (-.25 - .05 - .15)
        expected_eg = 12 + 3 * (.25 - .05 + .30)
        self.assertAlmostEqual(result.total_score, expected_mg / 6 + expected_eg * 5 / 6)
        self.assertAlmostEqual(sum(term.contribution for term in result.terms.values()), result.total_score)
        for term in result.terms.values():
            self.assertAlmostEqual(term.raw_value * term.weight, term.contribution)
        self.assertEqual(result.to_dict()["stage_terms"]["endgame"]["piece_square"]["weight"], 3)

    def test_phase_changes_linearly_without_material_price_dependency(self):
        board = chess.Board("7k/8/8/8/3K4/8/8/8 w - - 0 1")
        # Balanced pairs have zero material/PST contribution, only changing phase.
        evaluator = HandcraftedEvaluator(config=EvaluationConfig(
            phase_enabled=True, piece_values={"N": 100}, endgame_piece_values={"N": 1},
        ))
        scores = [evaluator.evaluate(board)]
        for white, black in ((chess.B1, chess.B8), (chess.C1, chess.C8)):
            board.set_piece_at(white, chess.Piece(chess.KNIGHT, chess.WHITE))
            board.set_piece_at(black, chess.Piece(chess.KNIGHT, chess.BLACK))
            scores.append(evaluator.evaluate(board))
        self.assertAlmostEqual(scores[1] - scores[0], scores[2] - scores[1])
        self.assertEqual(middlegame_phase(board), 4 / 24)

    def test_mirror_negates_scores_and_turn_does_not_change_phase(self):
        evaluator = HandcraftedEvaluator(config=EvaluationConfig(
            phase_enabled=True, endgame_piece_values={"Q": 10}, endgame_pst_weight=.7,
        ))
        for fen in (chess.STARTING_FEN, "7k/8/2n5/8/3K4/8/8/Q7 w - - 0 1"):
            board = chess.Board(fen)
            self.assertAlmostEqual(evaluator.evaluate(board.mirror()), -evaluator.evaluate(board))
            phase = middlegame_phase(board)
            score = evaluator.evaluate(board)
            board.turn = not board.turn
            self.assertEqual(middlegame_phase(board), phase)
            self.assertEqual(evaluator.evaluate(board), score)

    def test_switches_keep_endpoint_raw_values_and_disable_contributions(self):
        board = chess.Board("7k/8/8/8/3K4/8/8/Q7 w - - 0 1")
        for material, pst in ((False, False), (False, True), (True, False)):
            result = HandcraftedEvaluator(config=EvaluationConfig(
                phase_enabled=True, material_enabled=material, pst_enabled=pst,
            )).evaluate_breakdown(board)
            for terms in (result.terms, *result.stage_terms.values()):
                self.assertEqual(terms["material"].enabled, material)
                self.assertEqual(terms["piece_square"].enabled, pst)
                for name, enabled in (("material", material), ("piece_square", pst)):
                    if not enabled:
                        self.assertEqual(terms[name].contribution, 0)
                        self.assertNotEqual(terms[name].raw_value, 0)
            self.assertAlmostEqual(result.total_score, sum(t.contribution for t in result.terms.values()))

    def test_disabled_phase_preserves_legacy_score_and_board_history(self):
        board = chess.Board()
        for move in ("e2e4", "d7d5", "e4d5"):
            board.push_uci(move)
        before = board.fen(), list(board.move_stack)
        custom = HandcraftedEvaluator(config=EvaluationConfig(
            phase_enabled=False, endgame_piece_values={"Q": 99}, endgame_pst_weight=99,
        ))
        self.assertEqual(custom.evaluate(board), HandcraftedEvaluator().evaluate(board))
        HandcraftedEvaluator(config=EvaluationConfig(phase_enabled=True)).evaluate_breakdown(board)
        self.assertEqual((board.fen(), board.move_stack), before)
        self.assertEqual(custom.evaluate_breakdown(board).terms["piece_square"].raw_value,
                         evaluate_piece_square_tables(board))

    def test_v1_json_migrates_without_changing_scores(self):
        for name in ("stable.json", "example_pst_half.json"):
            payload = json.loads((ROOT / "configs/evaluation" / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            config = EvaluationConfig.from_dict(payload)
            self.assertFalse(config.phase_enabled)
            self.assertEqual(config.to_dict()["version"], 3)
            self.assertEqual(config, EvaluationConfig.from_dict(config.to_dict()))
            board = chess.Board("7k/8/8/8/3K4/8/8/Q7 w - - 0 1")
            legacy = HandcraftedEvaluator(config=EvaluationConfig(pst_weight=config.pst_weight))
            self.assertEqual(HandcraftedEvaluator(config=config).evaluate(board), legacy.evaluate(board))

    def test_current_config_roundtrip_immutable_and_actual_player_snapshot(self):
        config = EvaluationConfig(phase_enabled=True, endgame_piece_values={"N": 4},
                                  pst_weight=.3, endgame_pst_weight=.8)
        self.assertEqual(config, EvaluationConfig.from_dict(json.loads(json.dumps(config.to_dict()))))
        with self.assertRaises(TypeError):
            config.endgame_piece_values["N"] = 10
        snapshot = strategy_config("Greedy", GreedyPlayer(config=config))["evaluator"]
        del snapshot["type"]
        self.assertEqual(EvaluationConfig.from_dict(snapshot), config)
        example = EvaluationConfig.from_dict(json.loads(
            (ROOT / "configs/evaluation/example_tapered.json").read_text(encoding="utf-8")))
        self.assertTrue(example.phase_enabled)

    def test_invalid_phase_and_endgame_settings_are_rejected(self):
        for kwargs in ({"phase_enabled": 1}, {"endgame_pst_weight": -1},
                       {"endgame_pst_weight": float("nan")}, {"endgame_pst_weight": True},
                       {"endgame_piece_values": {"P": 0}}, {"endgame_piece_values": {"Q": -1}},
                       {"endgame_piece_values": {"X": 1}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                EvaluationConfig(**kwargs)
        payload = EvaluationConfig(phase_enabled=True).to_dict()
        for section, key, value in (("phase", "model_version", 2), ("phase", "model_version", True),
                                    ("phase", "enabled", "yes"),
                                    ("piece_square", "endgame_table_version", 2),
                                    ("piece_square", "endgame_weight", float("inf")),
                                    ("material", "endgame_piece_values", {"Q": 9})):
            corrupted = deepcopy(payload)
            target = corrupted["phase"] if section == "phase" else corrupted["terms"][section]
            target[key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                EvaluationConfig.from_dict(corrupted)


if __name__ == "__main__":
    unittest.main()
