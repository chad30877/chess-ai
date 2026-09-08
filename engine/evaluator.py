"""Handcrafted evaluator implementations built from readable score terms."""

from collections.abc import Mapping

import chess

from engine.interfaces import Evaluator
from engine.pst import evaluate_piece_square_tables

DEFAULT_WEIGHTS = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
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
        if isinstance(key, int):
            if key not in normalized:
                raise ValueError(f"Unsupported piece type key: {key}")
            normalized[key] = float(value)
            continue

        if isinstance(key, str):
            piece_key = key.upper()
            if piece_key not in PIECE_KEY_MAP:
                raise ValueError(f"Unsupported piece key: {key}")
            normalized[PIECE_KEY_MAP[piece_key]] = float(value)
            continue

        raise ValueError(f"Unsupported weight key type: {type(key)}")

    return normalized


class MaterialEvaluator(Evaluator):
    """Evaluate a non-terminal board by material balance from White's perspective."""

    def __init__(self, weights: Mapping[int | str, float] | None = None) -> None:
        self.weights = _normalize_weights(weights)

    def evaluate(self, board: chess.Board) -> float:
        return _evaluate_material_balance(board, self.weights)


class HandcraftedEvaluator(Evaluator):
    """Evaluate a position as material plus handcrafted piece-square bonuses."""

    def __init__(self, weights: Mapping[int | str, float] | None = None) -> None:
        self.material_evaluator = MaterialEvaluator(weights=weights)

    def evaluate(self, board: chess.Board) -> float:
        # Keep each term visible so future tuning does not mix material and PST logic.
        material_score = self.material_evaluator.evaluate(board)
        piece_square_score = evaluate_piece_square_tables(board)
        return material_score + piece_square_score


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


def evaluate(board: chess.Board, weights: Mapping[int | str, float] | None = None) -> float:
    """Backward-compatible helper returning the default handcrafted eval score."""

    return HandcraftedEvaluator(weights=weights).evaluate(board)
