"""Handcrafted evaluator implementations built from readable score terms."""

from collections.abc import Mapping
import math
from numbers import Real
from types import MappingProxyType

import chess

from engine.evaluation.config import (
    DEFAULT_PIECE_VALUES,
    PHASE_MODEL_VERSION,
    EvaluationBreakdown,
    EvaluationConfig,
    EvaluationTerm,
)
from engine.evaluation.pst import (
    evaluate_piece_square_tables, evaluate_endgame_piece_square_tables, middlegame_phase,
)
from engine.evaluation.pawn_structure import pawn_structure_balance
from engine.interfaces import Evaluator

DEFAULT_WEIGHTS = {
    chess.PAWN: DEFAULT_PIECE_VALUES["P"],
    chess.KNIGHT: DEFAULT_PIECE_VALUES["N"],
    chess.BISHOP: DEFAULT_PIECE_VALUES["B"],
    chess.ROOK: DEFAULT_PIECE_VALUES["R"],
    chess.QUEEN: DEFAULT_PIECE_VALUES["Q"],
}

PIECE_KEY_MAP = {
    "P": chess.PAWN,
    "N": chess.KNIGHT,
    "B": chess.BISHOP,
    "R": chess.ROOK,
    "Q": chess.QUEEN,
}


def _normalize_weights(weights: Mapping[int | str, float] | None) -> dict[int, float]:
    if weights is None:
        return DEFAULT_WEIGHTS.copy()

    normalized = DEFAULT_WEIGHTS.copy()
    for key, value in weights.items():
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"Piece value for {key} must be a finite non-negative number")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"Piece value for {key} must be a finite non-negative number")
        if isinstance(key, int):
            if key not in normalized:
                raise ValueError(f"Unsupported piece type key: {key}")
            normalized[key] = number
            continue

        if isinstance(key, str):
            piece_key = key.upper()
            if piece_key not in PIECE_KEY_MAP:
                raise ValueError(f"Unsupported piece key: {key}")
            normalized[PIECE_KEY_MAP[piece_key]] = number
            continue

        raise ValueError(f"Unsupported weight key type: {type(key)}")

    return normalized


class MaterialEvaluator(Evaluator):
    """Evaluate a non-terminal board by material balance from White's perspective."""

    def __init__(self, weights: Mapping[int | str, float] | None = None) -> None:
        self.weights = MappingProxyType(_normalize_weights(weights))
        self.config = EvaluationConfig.material_only(_symbol_weights(self.weights))

    def evaluate(self, board: chess.Board) -> float:
        return _evaluate_material_balance(board, self.weights)

    def evaluate_breakdown(self, board: chess.Board) -> EvaluationBreakdown:
        return _evaluate_breakdown(board, self.config, self.weights)


class HandcraftedEvaluator(Evaluator):
    """Evaluate a position as material plus handcrafted piece-square bonuses."""

    def __init__(
        self,
        weights: Mapping[int | str, float] | None = None,
        *,
        config: EvaluationConfig | None = None,
    ) -> None:
        if weights is not None and config is not None:
            raise ValueError("Pass either weights or config, not both")
        if config is not None and not isinstance(config, EvaluationConfig):
            raise ValueError("config must be an EvaluationConfig")
        self.config = config or EvaluationConfig(
            piece_values=_symbol_weights(_normalize_weights(weights)),
        )
        self.material_evaluator = MaterialEvaluator(weights=self.config.piece_values)

    def evaluate(self, board: chess.Board) -> float:
        return self.evaluate_breakdown(board).total_score

    def evaluate_breakdown(self, board: chess.Board) -> EvaluationBreakdown:
        return _evaluate_breakdown(board, self.config, self.material_evaluator.weights)


def evaluate_material(board: chess.Board, weights: Mapping[int | str, float] | None = None) -> float:
    """Return White material minus Black material."""

    normalized_weights = _normalize_weights(weights)
    return _evaluate_material_balance(board, normalized_weights)


def _evaluate_material_balance(board: chess.Board, weights: Mapping[int, float]) -> float:
    score = 0.0
    for piece_type, value in weights.items():
        score += len(board.pieces(piece_type, chess.WHITE)) * value
        score -= len(board.pieces(piece_type, chess.BLACK)) * value
    return score


def _symbol_weights(weights: Mapping[int, float]) -> dict[str, float]:
    return {chess.piece_symbol(piece_type).upper(): value for piece_type, value in weights.items()}


def _evaluate_breakdown(
    board: chess.Board,
    config: EvaluationConfig,
    material_weights: Mapping[int, float],
) -> EvaluationBreakdown:
    if config.phase_enabled:
        return _evaluate_tapered_breakdown(board, config, material_weights)
    material_raw = _evaluate_material_balance(board, material_weights)
    pst_raw = evaluate_piece_square_tables(board)
    material_contribution = material_raw if config.material_enabled else 0.0
    pst_contribution = pst_raw * config.pst_weight if config.pst_enabled else 0.0
    terms = {
        "material": EvaluationTerm(
            raw_value=material_raw,
            weight=1.0,
            contribution=material_contribution,
            enabled=config.material_enabled,
            unit="pawn balance",
            direction="positive favors White",
            stage="all",
            overlap_risk="piece values include material only",
        ),
        "piece_square": EvaluationTerm(
            raw_value=pst_raw,
            weight=config.pst_weight,
            contribution=pst_contribution,
            enabled=config.pst_enabled,
            unit="pawn positional bonus",
            direction="positive favors White",
            stage="all",
            overlap_risk="may overlap future location-based features",
        ),
    }
    terms.update(_pawn_terms(config, "middlegame", pawn_structure_balance(board)))
    return EvaluationBreakdown(
        terms=terms,
        total_score=sum(term.contribution for term in terms.values()),
    )


def evaluate(board: chess.Board, weights: Mapping[int | str, float] | None = None) -> float:
    """Backward-compatible helper returning the default handcrafted eval score."""

    return HandcraftedEvaluator(weights=weights).evaluate(board)


def _evaluate_tapered_breakdown(
    board: chess.Board,
    config: EvaluationConfig,
    material_weights: Mapping[int, float],
) -> EvaluationBreakdown:
    phase = middlegame_phase(board)
    endgame_weights = {PIECE_KEY_MAP[key]: value
                       for key, value in config.endgame_piece_values.items()}
    raw = {
        "middlegame": (_evaluate_material_balance(board, material_weights),
                       evaluate_piece_square_tables(board)),
        "endgame": (_evaluate_material_balance(board, endgame_weights),
                    evaluate_endgame_piece_square_tables(board)),
    }
    stage_terms = {}
    pawn_raw = pawn_structure_balance(board)
    for stage, (material, pst) in raw.items():
        weight = config.pst_weight if stage == "middlegame" else config.endgame_pst_weight
        stage_terms[stage] = {
            "material": EvaluationTerm(material, 1.0, material if config.material_enabled else 0.0,
                                       config.material_enabled, "pawn balance", "positive favors White",
                                       stage, "piece values include material only"),
            "piece_square": EvaluationTerm(pst, weight, pst * weight if config.pst_enabled else 0.0,
                                           config.pst_enabled, "pawn positional bonus",
                                           "positive favors White", stage,
                                           "may overlap future location-based features"),
        }
        stage_terms[stage].update(_pawn_terms(config, stage, pawn_raw))
    # Endpoint contributions are weighted before interpolation; raw PST and weight
    # cannot be interpolated separately without introducing cross terms.
    terms = {}
    for name in stage_terms["middlegame"]:
        mg, eg = stage_terms["middlegame"][name], stage_terms["endgame"][name]
        contribution = phase * mg.contribution + (1 - phase) * eg.contribution
        terms[name] = EvaluationTerm(
            phase * mg.raw_value * mg.weight + (1 - phase) * eg.raw_value * eg.weight,
            1.0, contribution, mg.enabled,
            "pawn weighted feature contribution" if name in config.pawn_terms else mg.unit,
            mg.direction, "tapered",
            mg.overlap_risk,
        )
    return EvaluationBreakdown(
        terms=terms, total_score=sum(term.contribution for term in terms.values()),
        phase={"enabled": True, "model_version": PHASE_MODEL_VERSION, "middlegame": phase, "endgame": 1 - phase},
        stage_terms=stage_terms,
    )


def _pawn_terms(
    config: EvaluationConfig, stage: str, raw: Mapping[str, float],
) -> dict[str, EvaluationTerm]:
    metadata = {
        "isolated_pawns": ("isolated pawn count balance (Black minus White)",
                           "may overlap doubled-pawn penalties and pawn PST"),
        "doubled_pawns": ("extra pawns per file balance (Black minus White)",
                          "may overlap isolated-pawn penalties and pawn PST"),
        "passed_pawns": ("passed pawn rank units balance (White minus Black; ranks 2..7=1..6)",
                         "advancement overlaps pawn PST; isolated passers can also incur penalties"),
    }
    terms = {}
    for name, settings in config.pawn_terms.items():
        weight = settings.endgame_weight if stage == "endgame" else settings.weight
        unit, overlap = metadata[name]
        terms[name] = EvaluationTerm(
            raw_value=raw[name], weight=weight,
            contribution=raw[name] * weight if settings.enabled else 0.0,
            enabled=settings.enabled, unit=unit, direction="positive favors White",
            stage=stage if config.phase_enabled else "all", overlap_risk=overlap,
        )
    return terms
