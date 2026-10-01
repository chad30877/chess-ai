"""King safety geometry, stage fading, settings and history-independent semantics."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

import chess

from engine.evaluation.config import EvaluationConfig, KingSafetyTermConfig, KING_SAFETY_TERM_NAMES
from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.evaluation.king_safety import king_safety_for_color, king_safety_balance
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
    options = dict(material_enabled=False, pst_enabled=False, king_safety_terms={
        "king_pawn_shield": KingSafetyTermConfig(True, .1, 0),
        "king_zone_attacks": KingSafetyTermConfig(True, .05, 0),
        "king_file_exposure": KingSafetyTermConfig(True, .08, 0),
    })
    options.update(kwargs)
    return EvaluationConfig(**options)


class KingSafetyTest(unittest.TestCase):
    def test_shield_counts_only_immediate_forward_friendly_pawns(self):
        board = position(("g1", "K"), ("f2", "P"), ("g2", "P"), ("h3", "P"), ("h2", "p"), ("a8", "k"))
        self.assertEqual(king_safety_for_color(board, chess.WHITE).pawn_shield, 2)
        board.set_piece_at(chess.H2, chess.Piece(chess.PAWN, chess.WHITE))
        self.assertEqual(king_safety_for_color(board, chess.WHITE).pawn_shield, 3)
        mirrored = board.mirror()
        self.assertEqual(king_safety_for_color(mirrored, chess.BLACK).pawn_shield, 3)

    def test_shield_edges_and_last_rank_have_no_wraparound(self):
        for king, pawns, expected in (("a1", ("a2", "b2", "h2"), 2),
                                     ("h1", ("g2", "h2", "a2"), 2),
                                     ("d8", ("c7", "d7", "e7"), 0)):
            with self.subTest(king=king):
                board = position((king, "K"), *((name, "P") for name in pawns))
                self.assertEqual(king_safety_for_color(board, chess.WHITE).pawn_shield, expected)

    def test_file_exposure_distinguishes_half_open_and_open_files(self):
        board = position(("g1", "K"), ("f4", "P"), ("g7", "p"), ("a8", "k"))
        # f has an own pawn anywhere =>0, g only enemy pawn =>1, h no pawns =>2.
        self.assertEqual(king_safety_for_color(board, chess.WHITE).file_exposure, 3)
        board.set_piece_at(chess.H2, chess.Piece(chess.ROOK, chess.WHITE))
        self.assertEqual(king_safety_for_color(board, chess.WHITE).file_exposure, 3)
        board.set_piece_at(chess.G2, chess.Piece(chess.PAWN, chess.WHITE))
        self.assertEqual(king_safety_for_color(board, chess.WHITE).file_exposure, 2)
        self.assertEqual(king_safety_for_color(board.mirror(), chess.BLACK).file_exposure, 2)

    def test_exposed_file_edges_are_two_files_not_wrapped_three(self):
        for square in ("a1", "h1"):
            self.assertEqual(king_safety_for_color(position((square, "K")), chess.WHITE).file_exposure, 4)
        self.assertEqual(king_safety_for_color(position(("d4", "K")), chess.WHITE).file_exposure, 6)

    def test_zone_includes_king_and_occupied_squares_with_attack_union(self):
        board = position(("g1", "K"), ("g8", "r"), ("h8", "r"), ("a8", "k"))
        # g1/g2 and h1/h2; the king's square is included.
        self.assertEqual(king_safety_for_color(board, chess.WHITE).zone_attacks, 4)
        board.set_piece_at(chess.F3, chess.Piece(chess.BISHOP, chess.BLACK))
        # Bishop duplicates attacks on g2/h1: each attacked square counts once.
        self.assertEqual(king_safety_for_color(board, chess.WHITE).zone_attacks, 4)
        board.set_piece_at(chess.G2, chess.Piece(chess.PAWN, chess.WHITE))
        # g2 remains attacked though occupied; g1 is now shielded on the g-file.
        self.assertEqual(king_safety_for_color(board, chess.WHITE).zone_attacks, 3)

    def test_pinned_attackers_still_count_geometric_attacks(self):
        board = position(("g4", "K"), ("e1", "R"), ("e8", "k"), ("e7", "n"))
        self.assertTrue(board.is_pinned(chess.BLACK, chess.E7))
        self.assertEqual(king_safety_for_color(board, chess.WHITE).zone_attacks, 1)  # f5

    def test_missing_kings_have_zero_features_for_debug_positions(self):
        empty = chess.Board(None)
        self.assertEqual(king_safety_balance(empty), dict.fromkeys(KING_SAFETY_TERM_NAMES, 0))
        board = position(("a2", "P"), ("h7", "p"), ("h8", "k"))
        result = king_safety_for_color(board, chess.WHITE)
        self.assertEqual((result.pawn_shield, result.zone_attacks, result.file_exposure), (0, 0, 0))

    def test_turn_castling_rights_mirror_and_history_do_not_change_geometry(self):
        board = chess.Board()
        for move in ("e2e4", "d7d5", "e4d5", "d8d5"):
            board.push_uci(move)
        before = board.fen(), list(board.move_stack)
        raw = king_safety_balance(board)
        for name, value in king_safety_balance(board.mirror()).items():
            self.assertEqual(value, -raw[name])
        for phase in (False, True):
            evaluator = HandcraftedEvaluator(config=config(phase_enabled=phase))
            score = evaluator.evaluate(board)
            self.assertAlmostEqual(evaluator.evaluate(board.mirror()), -score)
            altered = board.copy(stack=False)
            altered.castling_rights = 0
            altered.turn = not altered.turn
            self.assertEqual(king_safety_balance(altered), raw)
            self.assertEqual(evaluator.evaluate(altered), score)
        self.assertEqual((board.fen(), board.move_stack), before)

    def test_signs_independent_weights_switches_and_disabled_raw_values(self):
        board = position(("g1", "K"), ("g2", "P"), ("a8", "k"), ("g8", "r"))
        # White shield 1 vs 0; attacked ring 1 vs 0; files white4 vs black4.
        raw = king_safety_balance(board)
        self.assertEqual(raw, {"king_pawn_shield": 1, "king_zone_attacks": -1, "king_file_exposure": 0})
        cfg = config()
        baseline = HandcraftedEvaluator(config=cfg).evaluate_breakdown(board)
        self.assertAlmostEqual(baseline.total_score, .1 - .05)
        for name in KING_SAFETY_TERM_NAMES:
            for enabled, multiplier in ((False, 1), (True, 2), (True, 0)):
                terms = dict(cfg.king_safety_terms)
                terms[name] = replace(terms[name], enabled=enabled, weight=terms[name].weight * multiplier)
                changed = HandcraftedEvaluator(config=replace(cfg, king_safety_terms=terms)).evaluate_breakdown(board)
                self.assertEqual(changed.terms[name].raw_value, raw[name])
                self.assertAlmostEqual(changed.terms[name].contribution,
                                       baseline.terms[name].contribution * multiplier if enabled else 0)
                for other in set(KING_SAFETY_TERM_NAMES) - {name}:
                    self.assertEqual(changed.terms[other], baseline.terms[other])
                self.assertAlmostEqual(changed.total_score, sum(t.contribution for t in changed.terms.values()))
        exposed = position(("d4", "K"), ("a8", "k"))
        self.assertEqual(king_safety_balance(exposed)["king_file_exposure"], -2)
        self.assertAlmostEqual(HandcraftedEvaluator(config=cfg).evaluate(exposed), -.16)

    def test_default_endgame_zero_and_phase_interpolation_preserve_king_activity(self):
        board = position(("g1", "K"), ("g2", "P"), ("a8", "k"), ("g8", "r"))
        cfg = config(phase_enabled=True)
        result = HandcraftedEvaluator(config=cfg).evaluate_breakdown(board)
        self.assertAlmostEqual(result.total_score, (.1 - .05) * 2 / 24)
        self.assertEqual(result.stage_terms["endgame"]["king_pawn_shield"].raw_value, 1)
        self.assertEqual(result.stage_terms["endgame"]["king_pawn_shield"].contribution, 0)
        custom = replace(cfg, king_safety_terms={"king_pawn_shield": KingSafetyTermConfig(True, .1, .3)})
        self.assertAlmostEqual(HandcraftedEvaluator(config=custom).evaluate(board), .1 * 2/24 + .3 * 22/24)
        full = board.copy()
        for file in "cde":
            full.set_piece_at(chess.parse_square(file + "1"), chess.Piece(chess.QUEEN, chess.WHITE))
            full.set_piece_at(chess.parse_square(file + "8"), chess.Piece(chess.QUEEN, chess.BLACK))
        self.assertAlmostEqual(HandcraftedEvaluator(config=custom).evaluate(full), .1)
        board.remove_piece_at(chess.G8)
        self.assertEqual(HandcraftedEvaluator(config=cfg).evaluate(board), 0)
        center = position(("d4", "K"), ("h8", "k"))
        edge = position(("a1", "K"), ("h8", "k"))
        with_pst = replace(cfg, pst_enabled=True)
        evaluator = HandcraftedEvaluator(config=with_pst)
        self.assertAlmostEqual(evaluator.evaluate(center), .55)
        self.assertGreater(evaluator.evaluate(center), evaluator.evaluate(edge))
        # With phase disabled the MG price is used even on a pawn-only board.
        self.assertAlmostEqual(HandcraftedEvaluator(config=replace(cfg, phase_enabled=False)).evaluate(board), .1)

    def test_v1_to_v4_scores_and_prior_settings_are_preserved(self):
        board = chess.Board("7k/7p/2P5/8/P7/8/P7/K7 w - - 0 1")
        for filename, expected in (("stable.json", 2.17), ("example_pst_half.json", 2.085),
                                   ("example_tapered.json", 2.20), ("example_pawn_structure.json", 2.35),
                                   ("example_mobility.json", 2.38)):
            payload = json.loads((ROOT / "configs/evaluation" / filename).read_text(encoding="utf-8"))
            cfg = EvaluationConfig.from_dict(payload)
            self.assertTrue(all(not item.enabled for item in cfg.king_safety_terms.values()))
            self.assertAlmostEqual(HandcraftedEvaluator(config=cfg).evaluate(board), expected)
            self.assertEqual(cfg, EvaluationConfig.from_dict(cfg.to_dict()))
            self.assertEqual(cfg.to_dict()["version"], 5)
        evaluator = MaterialEvaluator()
        self.assertEqual(evaluator.evaluate(board), evaluator.evaluate_breakdown(board).total_score)
        self.assertTrue(all(not item.enabled and item.endgame_weight == 0
                            for item in EvaluationConfig().king_safety_terms.values()))

    def test_v5_roundtrip_immutable_snapshot_and_example(self):
        cfg = config(phase_enabled=True)
        self.assertEqual(cfg, EvaluationConfig.from_dict(json.loads(json.dumps(cfg.to_dict()))))
        with self.assertRaises(TypeError):
            cfg.king_safety_terms["king_pawn_shield"] = KingSafetyTermConfig()
        with self.assertRaises(AttributeError):
            cfg.king_safety_terms["king_pawn_shield"].enabled = False
        saved = strategy_config("Greedy", GreedyPlayer(config=cfg))["evaluator"]
        saved.pop("type")
        self.assertEqual(EvaluationConfig.from_dict(saved), cfg)
        example = EvaluationConfig.from_dict(json.loads(
            (ROOT / "configs/evaluation/example_king_safety.json").read_text(encoding="utf-8")))
        self.assertTrue(example.phase_enabled)
        self.assertTrue(all(item.enabled and item.endgame_weight == 0 for item in example.king_safety_terms.values()))

    def test_invalid_settings_versions_unknown_and_missing_fields_are_rejected(self):
        for kwargs in ({"enabled": 1}, {"weight": -1}, {"weight": True},
                       {"endgame_weight": float("inf")}, {"endgame_weight": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                KingSafetyTermConfig(**kwargs)
        for terms in (None, {"unknown": KingSafetyTermConfig()}, {"king_pawn_shield": {"weight": .1}}):
            with self.subTest(terms=terms), self.assertRaises(ValueError):
                EvaluationConfig(king_safety_terms=terms)
        payload = config().to_dict()
        for name in KING_SAFETY_TERM_NAMES:
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


if __name__ == "__main__":
    unittest.main()
