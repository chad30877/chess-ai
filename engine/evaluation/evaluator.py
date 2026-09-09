"""Handcrafted evaluator implementations built from readable score terms."""

from collections.abc import Mapping
import math
from numbers import Real
from types import MappingProxyType

import chess

from engine.evaluation.config import (
    DEFAULT_PIECE_VALUES,
    EvaluationBreakdown,
    EvaluationConfig,
    EvaluationTerm,
)
from engine.evaluation.pst import evaluate_piece_square_tables
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
    return EvaluationBreakdown(
        terms=terms,
        total_score=sum(term.contribution for term in terms.values()),
    )


def evaluate(board: chess.Board, weights: Mapping[int | str, float] | None = None) -> float:
    """Backward-compatible helper returning the default handcrafted eval score."""

    return HandcraftedEvaluator(weights=weights).evaluate(board)
