"""Geometric activity semantics, stages, backward compatibility and snapshots."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

import chess

from engine.evaluation.config import EvaluationConfig, MobilityTermConfig, MOBILITY_TERM_NAMES
from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.evaluation.mobility import mobility_for_color, mobility_balance
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
    options = dict(material_enabled=False, pst_enabled=False, mobility_terms={
        name: MobilityTermConfig(True, .1, .2) for name in MOBILITY_TERM_NAMES
    })
    options.update(kwargs)
    return EvaluationConfig(**options)


class MobilityTest(unittest.TestCase):
    def test_single_piece_center_and_corner_attack_counts(self):
        for symbol, name, center, corner in (
            ("P", "pawn_mobility", 2, 1), ("N", "knight_mobility", 8, 2),
            ("B", "bishop_mobility", 13, 7), ("R", "rook_mobility", 14, 14),
            ("Q", "queen_mobility", 27, 21), ("K", "king_mobility", 8, 3),
        ):
            for square, expected in (("d4", center), ("a2" if symbol == "P" else "a1", corner)):
                with self.subTest(symbol=symbol, square=square):
                    result = mobility_for_color(position((square, symbol)), chess.WHITE)
                    self.assertEqual(result[name], expected)
                    self.assertEqual(sum(result.values()), expected)

    def test_sliders_stop_at_friendly_and_enemy_blockers(self):
        # d5 cuts the upward ray at a friendly piece; f4 is an enemy
        # capture, counted once, while g4/h4 beyond it are excluded.
        board = position(("d4", "R"), ("d5", "P"), ("f4", "p"))
        self.assertEqual(mobility_for_color(board, chess.WHITE)["rook_mobility"], 8)
        board = position(("d4", "B"), ("e5", "P"), ("b6", "p"))
        # NE=0, NW=c5/b6=2, SE=e3/f2/g1=3, SW=c3/b2/a1=3.
        self.assertEqual(mobility_for_color(board, chess.WHITE)["bishop_mobility"], 8)

    def test_knights_exclude_friendly_destinations_and_jump_over_pieces(self):
        board = position(("d4", "N"), ("f5", "P"), ("e6", "p"), ("e4", "P"))
        self.assertEqual(mobility_for_color(board, chess.WHITE)["knight_mobility"], 7)

    def test_pawn_diagonals_count_empty_and_enemy_squares_but_not_pushes(self):
        board = position(("d2", "P"), ("e3", "P"), ("c3", "n"), ("d3", "r"), ("h7", "p"))
        self.assertEqual(mobility_for_color(board, chess.WHITE)["pawn_mobility"], 3)
        # d2 has one eligible diagonal; e3 has two. Blocking the push
        # changes no attack-space feature. A/H boundaries never wrap.
        self.assertEqual(mobility_for_color(board, chess.BLACK)["pawn_mobility"], 1)
        board.remove_piece_at(chess.D3)
        self.assertEqual(mobility_for_color(board, chess.WHITE)["pawn_mobility"], 3)

    def test_pins_checks_and_unsafe_king_destinations_are_not_legal_move_filters(self):
        pinned = chess.Board("4r2k/8/8/8/8/8/4N3/4K3 w - - 0 1")
        self.assertTrue(pinned.is_pinned(chess.WHITE, chess.E2))
        self.assertFalse(any(move.from_square == chess.E2 for move in pinned.legal_moves))
        self.assertEqual(mobility_for_color(pinned, chess.WHITE)["knight_mobility"], 6)
        checked = chess.Board("4r2k/8/8/8/8/8/8/4K3 w - - 0 1")
        self.assertTrue(checked.is_check())
        self.assertEqual(mobility_for_color(checked, chess.WHITE)["king_mobility"], 5)
        self.assertLess(len(list(checked.legal_moves)), 5)

    def test_shared_destinations_count_per_piece_not_as_side_union(self):
        board = position(("c3", "N"), ("e3", "N"))
        # Each knight has eight squares, including shared destinations.
        self.assertEqual(mobility_for_color(board, chess.WHITE)["knight_mobility"], 16)

    def test_both_colors_turn_invariance_mirror_sign_and_board_history(self):
        board = chess.Board()
        for move in ("e2e4", "e7e5", "g1f3"):
            board.push_uci(move)
        before = board.fen(), list(board.move_stack)
        raw = mobility_balance(board)
        self.assertNotEqual(raw["knight_mobility"], 0)
        mirror = mobility_balance(board.mirror())
        for name in MOBILITY_TERM_NAMES:
            self.assertEqual(mirror[name], -raw[name])
        for phase in (False, True):
            evaluator = HandcraftedEvaluator(config=config(phase_enabled=phase))
            self.assertAlmostEqual(evaluator.evaluate(board.mirror()), -evaluator.evaluate(board))
            turned = board.copy(stack=True)
            turned.turn = not board.turn
            self.assertEqual(evaluator.evaluate(turned), evaluator.evaluate(board))
        self.assertEqual((board.fen(), board.move_stack), before)

    def test_independent_switches_prices_raw_values_and_phase_interpolation(self):
        board = position(("d4", "N"), ("a8", "q"))
        # Phase=(N=1,Q=4)/24. White knight 8, Black queen 21.
        raw = mobility_balance(board)
        self.assertEqual(raw["knight_mobility"], 8)
        self.assertEqual(raw["queen_mobility"], -21)
        baseline_config = config()
        for phase in (False, True):
            cfg = replace(baseline_config, phase_enabled=phase)
            baseline = HandcraftedEvaluator(config=cfg).evaluate_breakdown(board)
            self.assertAlmostEqual(baseline.total_score, -13 * (.1 if not phase else (.1 * 5/24 + .2 * 19/24)))
            for name in MOBILITY_TERM_NAMES:
                for enabled, multiplier in ((False, 1), (True, 0), (True, 2)):
                    terms = dict(cfg.mobility_terms)
                    terms[name] = replace(terms[name], enabled=enabled,
                                          weight=.1 * multiplier, endgame_weight=.2 * multiplier)
                    result = HandcraftedEvaluator(config=replace(cfg, mobility_terms=terms)).evaluate_breakdown(board)
                    self.assertAlmostEqual(result.terms[name].contribution,
                                           baseline.terms[name].contribution * multiplier if enabled else 0)
                    for other in set(MOBILITY_TERM_NAMES) - {name}:
                        self.assertEqual(result.terms[other], baseline.terms[other])
                    endpoint = result.stage_terms["endgame"] if phase else result.terms
                    self.assertEqual(endpoint[name].raw_value, raw[name])
                    self.assertAlmostEqual(result.total_score, sum(t.contribution for t in result.terms.values()))
            serialized = baseline.to_dict()
            self.assertIn("overlap_risk", serialized["terms"]["knight_mobility"])

        pawn_only = config(phase_enabled=True, mobility_terms={
            "pawn_mobility": MobilityTermConfig(True, .1, .2),
        })
        evaluator = HandcraftedEvaluator(config=pawn_only)
        low = position(("d4", "P"), ("h7", "p"))
        self.assertAlmostEqual(evaluator.evaluate(low), .2)  # phase 0, raw 2-1=1
        for file in "abcdef":
            low.set_piece_at(chess.parse_square(file + "8"), chess.Piece(chess.QUEEN, chess.BLACK))
        self.assertAlmostEqual(evaluator.evaluate(low), .1)  # phase 1, same pawn raw

    def test_defaults_material_only_and_older_json_preserve_scores(self):
        board = chess.Board("7k/7p/2P5/8/P7/8/P7/K7 w - - 0 1")
        for filename, expected in (("stable.json", 2.17), ("example_pst_half.json", 2.085),
                                   ("example_tapered.json", 2.20), ("example_pawn_structure.json", 2.35)):
            payload = json.loads((ROOT / "configs/evaluation" / filename).read_text(encoding="utf-8"))
            self.assertIn(payload["version"], (1, 2, 3))
            cfg = EvaluationConfig.from_dict(payload)
            self.assertTrue(all(not setting.enabled for setting in cfg.mobility_terms.values()))
            self.assertAlmostEqual(HandcraftedEvaluator(config=cfg).evaluate(board), expected)
            self.assertEqual(EvaluationConfig.from_dict(cfg.to_dict()), cfg)
            self.assertEqual(cfg.to_dict()["version"], 6)
        material = MaterialEvaluator()
        self.assertEqual(material.evaluate(board), material.evaluate_breakdown(board).total_score)
        self.assertTrue(all(not setting.enabled for setting in EvaluationConfig().mobility_terms.values()))
        self.assertEqual(mobility_balance(chess.Board()), dict.fromkeys(MOBILITY_TERM_NAMES, 0))
        self.assertEqual(mobility_balance(chess.Board(None)), dict.fromkeys(MOBILITY_TERM_NAMES, 0))

    def test_current_schema_immutable_roundtrip_and_actual_player_snapshot(self):
        cfg = config(phase_enabled=True)
        self.assertEqual(cfg, EvaluationConfig.from_dict(json.loads(json.dumps(cfg.to_dict()))))
        with self.assertRaises(TypeError):
            cfg.mobility_terms["knight_mobility"] = MobilityTermConfig()
        with self.assertRaises(AttributeError):
            cfg.mobility_terms["knight_mobility"].enabled = False
        saved = strategy_config("Greedy", GreedyPlayer(config=cfg))["evaluator"]
        saved.pop("type")
        self.assertEqual(EvaluationConfig.from_dict(saved), cfg)
        example = EvaluationConfig.from_dict(json.loads(
            (ROOT / "configs/evaluation/example_mobility.json").read_text(encoding="utf-8")))
        self.assertTrue(all(setting.enabled for setting in example.mobility_terms.values()))

    def test_invalid_settings_versions_unknown_and_missing_fields_are_rejected(self):
        for kwargs in ({"enabled": 1}, {"weight": -1}, {"endgame_weight": float("nan")},
                       {"weight": True}, {"weight": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                MobilityTermConfig(**kwargs)
        for terms in (None, {"unknown": MobilityTermConfig()}, {"pawn_mobility": {"weight": .1}}):
            with self.subTest(terms=terms), self.assertRaises(ValueError):
                EvaluationConfig(mobility_terms=terms)
        payload = config().to_dict()
        for name in MOBILITY_TERM_NAMES:
            for key, value in (("feature_version", 2), ("feature_version", True),
                               ("enabled", "yes"), ("weight", -.1), ("endgame_weight", float("inf"))):
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
        corrupt["terms"]["unknown_mobility"] = {}
        with self.assertRaises(ValueError):
            EvaluationConfig.from_dict(corrupt)

    def test_greedy_uses_knight_activity_to_choose_central_destination(self):
        board = chess.Board("7k/7p/8/8/8/8/8/K5N1 w - - 0 1")
        cfg = config(mobility_terms={"knight_mobility": MobilityTermConfig(True, .1, .2)})
        self.assertEqual(GreedyPlayer(config=cfg).choose_move(board).uci(), "g1f3")


if __name__ == "__main__":
    unittest.main()
