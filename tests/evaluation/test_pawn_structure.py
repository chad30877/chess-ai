"""Pawn model definitions, independently controlled scores and persisted configs."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

import chess

from engine.evaluation.config import EvaluationConfig, PawnTermConfig, PAWN_TERM_NAMES
from engine.evaluation.evaluator import HandcraftedEvaluator, MaterialEvaluator
from engine.evaluation.pawn_structure import pawn_structure_for_color, pawn_structure_balance
from engine.players import GreedyPlayer
from engine.strategy_config import strategy_config

ROOT = Path(__file__).resolve().parents[2]


def position(white=(), black=(), other=()) -> chess.Board:
    board = chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1")
    for color, names in ((chess.WHITE, white), (chess.BLACK, black)):
        for name in names:
            square = chess.parse_square(name)
            if board.piece_at(square) is not None:
                raise ValueError(f"Test fixture has overlapping pieces at {name}")
            board.set_piece_at(square, chess.Piece(chess.PAWN, color))
    for name, symbol in other:
        board.set_piece_at(chess.parse_square(name), chess.Piece.from_symbol(symbol))
    return board


def feature_config(**kwargs) -> EvaluationConfig:
    options = dict(material_enabled=False, pst_enabled=False, pawn_terms={
        "isolated_pawns": PawnTermConfig(True, .15, .20),
        "doubled_pawns": PawnTermConfig(True, .10, .15),
        "passed_pawns": PawnTermConfig(True, .05, .10),
    })
    options.update(kwargs)
    return EvaluationConfig(**options)


class PawnStructureTest(unittest.TestCase):
    def test_isolation_uses_adjacent_files_at_any_rank_including_edges(self):
        board = position(("a2", "a4", "c3", "d6", "h2"))
        self.assertEqual(pawn_structure_for_color(board, chess.WHITE).isolated, 3)
        board.set_piece_at(chess.B7, chess.Piece(chess.PAWN, chess.WHITE))
        self.assertEqual(pawn_structure_for_color(board, chess.WHITE).isolated, 1)
        board.set_piece_at(chess.G4, chess.Piece(chess.PAWN, chess.WHITE))
        self.assertEqual(pawn_structure_for_color(board, chess.WHITE).isolated, 0)

    def test_doubled_counts_extras_per_file_instead_of_pairs(self):
        board = position(("a2", "a3", "a4", "c2", "c3"), ("h6", "h7"))
        self.assertEqual(pawn_structure_for_color(board, chess.WHITE).doubled, 3)
        self.assertEqual(pawn_structure_for_color(board, chess.BLACK).doubled, 1)
        self.assertEqual(pawn_structure_balance(board)["doubled_pawns"], -2)

    def test_passers_exclude_enemy_on_own_or_adjacent_file_strictly_ahead(self):
        for enemy, expected in (("c5", 0), ("b5", 0), ("d5", 0),
                                ("a5", 1), ("c3", 1), ("b4", 1), ("d3", 1)):
            with self.subTest(enemy=enemy):
                result = pawn_structure_for_color(position(("c4",), (enemy,)), chess.WHITE)
                self.assertEqual(result.passed, expected)
        # A-file must not wrap around to H-file.
        self.assertEqual(pawn_structure_for_color(position(("a4",), ("h5",)), chess.WHITE).passed, 1)
        self.assertEqual(pawn_structure_for_color(position(("a4",), ("b5",)), chess.WHITE).passed, 0)

    def test_black_passers_use_downward_direction(self):
        for white, expected in (("e4", 0), ("d4", 0), ("f4", 0),
                               ("d5", 1), ("e6", 1), ("c4", 1)):
            with self.subTest(white=white):
                result = pawn_structure_for_color(position((white,), ("e5",)), chess.BLACK)
                self.assertEqual(result.passed, expected)

    def test_only_frontmost_doubled_pawn_receives_passed_bonus(self):
        board = position(("c2", "c4", "c6"), ("f3", "f5", "f7"))
        white = pawn_structure_for_color(board, chess.WHITE)
        black = pawn_structure_for_color(board, chess.BLACK)
        self.assertEqual((white.passed, white.passed_rank_units), (1, 5))
        self.assertEqual((black.passed, black.passed_rank_units), (1, 5))

    def test_passed_rank_units_are_symmetric_and_increase_with_advancement(self):
        for rank in range(2, 8):
            board = position((f"c{rank}",))
            white = pawn_structure_for_color(board, chess.WHITE)
            black = pawn_structure_for_color(board.mirror(), chess.BLACK)
            self.assertEqual(white.passed_rank_units, rank - 1)
            self.assertEqual(white, black)

    def test_non_pawn_blockers_and_turn_do_not_change_structure(self):
        board = position(("c4",), (), (("c5", "n"), ("d5", "r")))
        self.assertEqual(pawn_structure_for_color(board, chess.WHITE).passed, 1)
        before = pawn_structure_balance(board)
        board.turn = chess.BLACK
        self.assertEqual(pawn_structure_balance(board), before)

    def test_feature_signs_and_each_weight_and_switch_are_independent(self):
        board = position(("a2", "a4", "c6"), ("h7",))
        # White: 3 isolated, 1 extra, two frontmost passers of units 3+5.
        # Black: 1 isolated, 0 extra, one passer of unit 1.
        raw = pawn_structure_balance(board)
        self.assertEqual(raw, {"isolated_pawns": -2, "doubled_pawns": -1, "passed_pawns": 7})
        config = feature_config()
        baseline = HandcraftedEvaluator(config=config).evaluate_breakdown(board)
        self.assertAlmostEqual(baseline.total_score, -2 * .15 - .10 + 7 * .05)
        for name in PAWN_TERM_NAMES:
            for enabled, multiplier in ((False, 1), (True, 2), (True, 0)):
                settings = config.pawn_terms[name]
                changed_terms = dict(config.pawn_terms)
                changed_terms[name] = replace(settings, enabled=enabled, weight=settings.weight * multiplier)
                changed = HandcraftedEvaluator(config=replace(config, pawn_terms=changed_terms)).evaluate_breakdown(board)
                self.assertEqual(changed.terms[name].raw_value, raw[name])
                expected = raw[name] * settings.weight * multiplier if enabled else 0
                self.assertAlmostEqual(changed.terms[name].contribution, expected)
                for other in set(PAWN_TERM_NAMES) - {name}:
                    self.assertEqual(changed.terms[other], baseline.terms[other])
                self.assertAlmostEqual(changed.total_score, sum(t.contribution for t in changed.terms.values()))
                changed_terms[name] = replace(settings, enabled=enabled,
                                             endgame_weight=settings.endgame_weight * multiplier)
                endgame = HandcraftedEvaluator(config=replace(
                    config, phase_enabled=True, pawn_terms=changed_terms,
                )).evaluate_breakdown(board)
                expected_eg = raw[name] * settings.endgame_weight * multiplier if enabled else 0
                self.assertAlmostEqual(endgame.terms[name].contribution, expected_eg)

    def test_phase_interpolation_and_endpoint_raw_values_match_hand_calculation(self):
        board = position(("a2", "a4", "c6"), ("h7",), (("d1", "Q"),))
        config = feature_config(phase_enabled=True)
        result = HandcraftedEvaluator(config=config).evaluate_breakdown(board)
        mg = -2 * .15 - .10 + 7 * .05
        eg = -2 * .20 - .15 + 7 * .10
        self.assertAlmostEqual(result.total_score, mg / 6 + eg * 5 / 6)
        for name, raw in (("isolated_pawns", -2), ("doubled_pawns", -1), ("passed_pawns", 7)):
            for stage in ("middlegame", "endgame"):
                self.assertEqual(result.stage_terms[stage][name].raw_value, raw)
            self.assertAlmostEqual(result.terms[name].raw_value, result.terms[name].contribution)
        board.remove_piece_at(chess.D1)
        self.assertAlmostEqual(HandcraftedEvaluator(config=config).evaluate(board), eg)
        # Fill remaining phase units symmetrically; these pieces have no effect
        # on the enabled pawn terms, only on the mixture.
        for name in ("b1", "c1", "d1"):
            board.set_piece_at(chess.parse_square(name), chess.Piece(chess.QUEEN, chess.WHITE))
            board.set_piece_at(chess.square_mirror(chess.parse_square(name)),
                               chess.Piece(chess.QUEEN, chess.BLACK))
        self.assertAlmostEqual(HandcraftedEvaluator(config=config).evaluate(board), mg)
        disabled = HandcraftedEvaluator(config=replace(config, pawn_terms={})).evaluate_breakdown(board)
        self.assertEqual(disabled.total_score, 0)
        self.assertEqual(disabled.stage_terms["endgame"]["passed_pawns"].raw_value, 7)

    def test_mirror_negates_every_feature_and_scores_without_mutating_history(self):
        board = chess.Board()
        for move in ("e2e4", "d7d5", "e4d5", "c7c6", "d5c6"):
            board.push_uci(move)
        before = board.fen(), list(board.move_stack)
        for phase in (False, True):
            evaluator = HandcraftedEvaluator(config=feature_config(phase_enabled=phase))
            result = evaluator.evaluate_breakdown(board)
            mirror = evaluator.evaluate_breakdown(board.mirror())
            for name in PAWN_TERM_NAMES:
                self.assertAlmostEqual(mirror.terms[name].raw_value, -result.terms[name].raw_value)
                self.assertAlmostEqual(mirror.terms[name].contribution, -result.terms[name].contribution)
            self.assertAlmostEqual(mirror.total_score, -result.total_score)
        self.assertEqual((board.fen(), board.move_stack), before)

    def test_defaults_and_material_only_preserve_existing_scores(self):
        self.assertEqual(pawn_structure_balance(chess.Board()), dict.fromkeys(PAWN_TERM_NAMES, 0))
        self.assertEqual(pawn_structure_balance(position()), dict.fromkeys(PAWN_TERM_NAMES, 0))
        board = position(("a2", "a4", "c6"), ("h7",))
        config = EvaluationConfig()
        self.assertTrue(all(not setting.enabled for setting in config.pawn_terms.values()))
        default = HandcraftedEvaluator(config=config).evaluate_breakdown(board)
        self.assertEqual(default.total_score, default.terms["material"].contribution +
                         default.terms["piece_square"].contribution)
        material = MaterialEvaluator()
        self.assertEqual(material.evaluate(board), material.evaluate_breakdown(board).total_score)
        self.assertEqual(material.evaluate(board), 2.0)

    def test_old_configs_migrate_with_pawn_features_disabled(self):
        for name, version in (("stable.json", 1), ("example_pst_half.json", 1), ("example_tapered.json", 2)):
            payload = json.loads((ROOT / "configs/evaluation" / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], version)
            config = EvaluationConfig.from_dict(payload)
            self.assertEqual(config.to_dict()["version"], 3)
            self.assertTrue(all(not item.enabled for item in config.pawn_terms.values()))
            self.assertEqual(config.phase_enabled, version == 2)
            self.assertEqual(config, EvaluationConfig.from_dict(config.to_dict()))
            board = position(("a2", "a4", "c6"), ("h7",))
            # Two-pawn material advantage; MG PST +.17, EG PST +.20.
            expected = 2.20 if version == 2 else 2 + .17 * config.pst_weight
            self.assertAlmostEqual(HandcraftedEvaluator(config=config).evaluate(board), expected)

    def test_schema_roundtrip_immutable_settings_and_actual_player_snapshot(self):
        config = feature_config(phase_enabled=True)
        self.assertEqual(config, EvaluationConfig.from_dict(json.loads(json.dumps(config.to_dict()))))
        with self.assertRaises(TypeError):
            config.pawn_terms["isolated_pawns"] = PawnTermConfig()
        with self.assertRaises(AttributeError):
            config.pawn_terms["isolated_pawns"].weight = 1
        saved = strategy_config("Greedy", GreedyPlayer(config=config))["evaluator"]
        saved.pop("type")
        self.assertEqual(EvaluationConfig.from_dict(saved), config)
        example = EvaluationConfig.from_dict(json.loads(
            (ROOT / "configs/evaluation/example_pawn_structure.json").read_text(encoding="utf-8")))
        self.assertTrue(example.phase_enabled)
        self.assertTrue(all(setting.enabled for setting in example.pawn_terms.values()))

    def test_invalid_values_versions_unknown_and_missing_fields_are_rejected(self):
        for kwargs in ({"enabled": 1}, {"weight": -1}, {"weight": float("inf")},
                       {"endgame_weight": float("nan")}, {"endgame_weight": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PawnTermConfig(**kwargs)
        for terms in (None, {"unknown": PawnTermConfig()}, {"passed_pawns": {"enabled": True}}):
            with self.subTest(terms=terms), self.assertRaises(ValueError):
                EvaluationConfig(pawn_terms=terms)
        payload = feature_config().to_dict()
        for name in PAWN_TERM_NAMES:
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

    def test_greedy_uses_passed_pawn_advancement_bonus(self):
        board = position(("a6",), ("h7",))
        config = feature_config(pawn_terms={"passed_pawns": PawnTermConfig(True, .1, .2)})
        self.assertEqual(GreedyPlayer(config=config).choose_move(board).uci(), "a6a7")


if __name__ == "__main__":
    unittest.main()
