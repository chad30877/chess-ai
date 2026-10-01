"""Coordination definitions, staged prices, legacy scores and actual settings."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

import chess

from engine.evaluation.config import EvaluationConfig, CoordinationTermConfig, COORDINATION_TERM_NAMES
from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.evaluation.coordination import coordination_for_color, coordination_balance
from engine.players import GreedyPlayer
from engine.strategy_config import strategy_config

ROOT = Path(__file__).resolve().parents[2]


def position(*pieces) -> chess.Board:
    board = chess.Board(None)
    for name, symbol in pieces:
        square = chess.parse_square(name)
        if board.piece_at(square) is not None:
            raise ValueError(f"Overlapping test pieces: {name}")
        board.set_piece_at(square, chess.Piece.from_symbol(symbol))
    return board


def config(**kwargs) -> EvaluationConfig:
    options = dict(material_enabled=False, pst_enabled=False, coordination_terms={
        name: CoordinationTermConfig(True, .1, .2) for name in COORDINATION_TERM_NAMES
    })
    options.update(kwargs)
    return EvaluationConfig(**options)


def three_benefits() -> chess.Board:
    return position(("c1", "B"), ("f1", "B"), ("a1", "R"), ("b1", "R"),
                    ("h8", "r"), ("b7", "p"), ("h7", "p"), ("e1", "K"), ("e8", "k"))


class CoordinationTest(unittest.TestCase):
    def test_bishop_pair_requires_both_square_colors(self):
        for squares, expected in (((), 0), (("c1",), 0), (("c1", "e3"), 0),
                                  (("c1", "f1"), 1)):
            with self.subTest(squares=squares):
                board = position(*((name, "B") for name in squares))
                self.assertEqual(coordination_for_color(board, chess.WHITE).bishop_pair, expected)

    def test_extra_and_promoted_bishops_do_not_multiply_pair_bonus(self):
        board = position(("c1", "B"), ("e3", "B"), ("g5", "B"))
        board.promoted = chess.BB_E3 | chess.BB_G5
        self.assertEqual(coordination_for_color(board, chess.WHITE).bishop_pair, 0)
        board.set_piece_at(chess.F1, chess.Piece(chess.BISHOP, chess.WHITE), promoted=True)
        board.set_piece_at(chess.H3, chess.Piece(chess.BISHOP, chess.WHITE), promoted=True)
        self.assertEqual(coordination_for_color(board, chess.WHITE).bishop_pair, 1)
        self.assertEqual(coordination_for_color(board.mirror(), chess.BLACK).bishop_pair, 1)

    def test_rook_file_classes_are_exclusive_and_relative_to_owner(self):
        board = position(("a1", "R"), ("b1", "R"), ("c1", "R"), ("d1", "R"),
                         ("b7", "p"), ("c4", "P"), ("d2", "P"), ("d7", "p"))
        white = coordination_for_color(board, chess.WHITE)
        self.assertEqual((white.rook_open_file, white.rook_half_open_file), (1, 1))
        # Same classification after changing both piece colors and ranks.
        self.assertEqual(coordination_for_color(board.mirror(), chess.BLACK), white)

    def test_each_rook_counts_including_same_file_and_promoted_rooks(self):
        board = position(("a1", "R"), ("a4", "R"), ("h8", "r"))
        board.promoted = chess.BB_A4
        self.assertEqual(coordination_for_color(board, chess.WHITE).rook_open_file, 2)
        self.assertEqual(coordination_balance(board)["rook_open_file"], 1)
        board.set_piece_at(chess.A7, chess.Piece(chess.PAWN, chess.BLACK))
        white = coordination_for_color(board, chess.WHITE)
        self.assertEqual((white.rook_open_file, white.rook_half_open_file), (0, 2))

    def test_non_pawn_blockers_and_pawn_rank_do_not_change_file_class(self):
        board = position(("a4", "R"), ("a2", "p"), ("a5", "N"), ("a6", "b"))
        self.assertEqual(coordination_for_color(board, chess.WHITE).rook_half_open_file, 1)
        board.remove_piece_at(chess.A2)
        self.assertEqual(coordination_for_color(board, chess.WHITE).rook_open_file, 1)
        board.set_piece_at(chess.A1, chess.Piece(chess.PAWN, chess.WHITE))
        white = coordination_for_color(board, chess.WHITE)
        self.assertEqual((white.rook_open_file, white.rook_half_open_file), (0, 0))

    def test_signs_turn_mirror_and_root_history_are_preserved(self):
        board = three_benefits()
        self.assertEqual(coordination_balance(board), dict.fromkeys(COORDINATION_TERM_NAMES, 1))
        for name, value in coordination_balance(board.mirror()).items():
            self.assertEqual(value, -1)
        history = chess.Board()
        for move in ("e2e4", "e7e5", "g1f3"):
            history.push_uci(move)
        before = history.fen(), list(history.move_stack)
        for phase in (False, True):
            evaluator = HandcraftedEvaluator(config=config(phase_enabled=phase))
            self.assertAlmostEqual(evaluator.evaluate(board.mirror()), -evaluator.evaluate(board))
            turned = board.copy(stack=True)
            turned.turn = not board.turn
            self.assertEqual(evaluator.evaluate(turned), evaluator.evaluate(board))
            evaluator.evaluate_breakdown(history)
        self.assertEqual((history.fen(), history.move_stack), before)

    def test_independent_switches_and_both_stage_weights_keep_raw_features(self):
        board = three_benefits()
        for phase in (False, True):
            cfg = config(phase_enabled=phase)
            baseline = HandcraftedEvaluator(config=cfg).evaluate_breakdown(board)
            for name in COORDINATION_TERM_NAMES:
                for field in ("weight", "endgame_weight"):
                    for enabled, multiplier in ((False, 1), (True, 0), (True, 2)):
                        terms = dict(cfg.coordination_terms)
                        settings = terms[name]
                        terms[name] = replace(settings, enabled=enabled,
                                              **{field: getattr(settings, field) * multiplier})
                        changed = HandcraftedEvaluator(config=replace(cfg, coordination_terms=terms)).evaluate_breakdown(board)
                        mg, eg = terms[name].weight, terms[name].endgame_weight
                        # Two bishops plus three rooks => phase 8/24=1/3.
                        expected = mg / 3 + eg * 2 / 3 if phase else mg
                        self.assertAlmostEqual(changed.terms[name].contribution, expected if enabled else 0)
                        endpoint = changed.stage_terms["middlegame"] if phase else changed.terms
                        self.assertEqual(endpoint[name].raw_value, 1)
                        for other in set(COORDINATION_TERM_NAMES) - {name}:
                            self.assertEqual(changed.terms[other], baseline.terms[other])
                        self.assertAlmostEqual(changed.total_score, sum(t.contribution for t in changed.terms.values()))

    def test_phase_hand_calculation_endgame_terms_and_middlegame_endpoint(self):
        board = three_benefits()
        cfg = config(phase_enabled=True)
        evaluator = HandcraftedEvaluator(config=cfg)
        result = evaluator.evaluate_breakdown(board)
        self.assertAlmostEqual(result.total_score, .3 / 3 + .6 * 2 / 3)
        self.assertAlmostEqual(sum(t.contribution for t in result.stage_terms["endgame"].values()), .6)
        for file in "cdfg":
            board.set_piece_at(chess.parse_square(file + "8"), chess.Piece(chess.QUEEN, chess.BLACK))
        self.assertAlmostEqual(evaluator.evaluate(board), .3)
        self.assertEqual(evaluator.evaluate_breakdown(board).phase["middlegame"], 1)
        empty = evaluator.evaluate_breakdown(position(("a1", "K"), ("h8", "k")))
        self.assertEqual(empty.phase["endgame"], 1)
        self.assertEqual(empty.total_score, 0)

    def test_legacy_versions_default_scores_and_prior_settings_are_preserved(self):
        board = chess.Board("7k/7p/2P5/8/P7/8/P7/K7 w - - 0 1")
        for name, expected in (("stable.json", 2.17), ("example_pst_half.json", 2.085),
                               ("example_tapered.json", 2.20), ("example_pawn_structure.json", 2.35),
                               ("example_mobility.json", 2.38), ("example_king_safety.json", 2.38)):
            payload = json.loads((ROOT / "configs/evaluation" / name).read_text(encoding="utf-8"))
            cfg = EvaluationConfig.from_dict(payload)
            self.assertTrue(all(not item.enabled for item in cfg.coordination_terms.values()))
            self.assertAlmostEqual(HandcraftedEvaluator(config=cfg).evaluate(board), expected)
            self.assertEqual(cfg, EvaluationConfig.from_dict(cfg.to_dict()))
            self.assertEqual(cfg.to_dict()["version"], 6)
            # Complete existing feature settings survive migration unchanged.
            for term, settings in payload["terms"].items():
                for key, value in settings.items():
                    self.assertEqual(cfg.to_dict()["terms"][term][key], value)
        default = HandcraftedEvaluator().evaluate_breakdown(three_benefits())
        self.assertEqual(default.total_score, default.terms["material"].contribution +
                         default.terms["piece_square"].contribution)
        material = MaterialEvaluator()
        self.assertEqual(material.evaluate(three_benefits()), material.evaluate_breakdown(three_benefits()).total_score)
        self.assertEqual(coordination_balance(chess.Board(None)), dict.fromkeys(COORDINATION_TERM_NAMES, 0))
        self.assertEqual(coordination_balance(chess.Board()), dict.fromkeys(COORDINATION_TERM_NAMES, 0))

    def test_v6_roundtrip_immutable_snapshot_and_example(self):
        cfg = config(phase_enabled=True)
        self.assertEqual(cfg, EvaluationConfig.from_dict(json.loads(json.dumps(cfg.to_dict()))))
        with self.assertRaises(TypeError):
            cfg.coordination_terms["bishop_pair"] = CoordinationTermConfig()
        with self.assertRaises(AttributeError):
            cfg.coordination_terms["bishop_pair"].enabled = False
        saved = strategy_config("Greedy", GreedyPlayer(config=cfg))["evaluator"]
        saved.pop("type")
        self.assertEqual(EvaluationConfig.from_dict(saved), cfg)
        example = EvaluationConfig.from_dict(json.loads(
            (ROOT / "configs/evaluation/example_coordination.json").read_text(encoding="utf-8")))
        self.assertTrue(example.phase_enabled)
        self.assertTrue(all(item.enabled for item in example.coordination_terms.values()))

    def test_invalid_values_versions_unknown_and_missing_fields_are_rejected(self):
        for kwargs in ({"enabled": 1}, {"weight": -1}, {"weight": True},
                       {"endgame_weight": float("inf")}, {"endgame_weight": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                CoordinationTermConfig(**kwargs)
        for terms in (None, {"unknown": CoordinationTermConfig()}, {"bishop_pair": {"weight": .1}}):
            with self.subTest(terms=terms), self.assertRaises(ValueError):
                EvaluationConfig(coordination_terms=terms)
        payload = config().to_dict()
        for name in COORDINATION_TERM_NAMES:
            for key, value in (("feature_version", 2), ("feature_version", True), ("enabled", "yes"),
                               ("weight", -.1), ("endgame_weight", float("inf"))):
                corrupt = deepcopy(payload)
                corrupt["terms"][name][key] = value
                with self.subTest(name=name, key=key), self.assertRaises(ValueError):
                    EvaluationConfig.from_dict(corrupt)
            for key in payload["terms"][name]:
                corrupt = deepcopy(payload)
                del corrupt["terms"][name][key]
                with self.subTest(name=name, missing=key), self.assertRaises(ValueError):
                    EvaluationConfig.from_dict(corrupt)
            corrupt = deepcopy(payload)
            del corrupt["terms"][name]
            with self.assertRaises(ValueError):
                EvaluationConfig.from_dict(corrupt)
        corrupt = deepcopy(payload)
        corrupt["terms"]["unexpected"] = {}
        with self.assertRaises(ValueError):
            EvaluationConfig.from_dict(corrupt)

    def test_greedy_moves_rook_from_closed_file_to_open_file(self):
        board = chess.Board("7k/7p/8/8/8/8/P7/R6K w - - 0 1")
        cfg = config(coordination_terms={"rook_open_file": CoordinationTermConfig(True, .1, .2)})
        move = GreedyPlayer(config=cfg).choose_move(board)
        self.assertIn(move.uci(), ("a1b1", "a1c1", "a1d1", "a1e1", "a1f1", "a1g1"))


if __name__ == "__main__":
    unittest.main()
