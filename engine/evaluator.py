"""Material-based evaluator implementations."""

from collections.abc import Mapping

import chess

from engine.interfaces import Evaluator

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
    """Evaluate a board by material balance."""

    def __init__(self, weights: Mapping[int | str, float] | None = None) -> None:
        self.weights = _normalize_weights(weights)

    def evaluate(self, board: chess.Board) -> float:
        score = 0.0
        for piece_type, value in self.weights.items():
            score += len(board.pieces(piece_type, chess.WHITE)) * value
            score -= len(board.pieces(piece_type, chess.BLACK)) * value
        return score


def evaluate(board: chess.Board, weights: Mapping[int | str, float] | None = None) -> float:
    """Backward-compatible helper returning material score for a board."""
    return MaterialEvaluator(weights=weights).evaluate(board)
