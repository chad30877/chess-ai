"""Feature extraction for chess positions."""

import chess
import numpy as np

PIECE_ORDER = [
    (chess.WHITE, chess.PAWN),
    (chess.WHITE, chess.KNIGHT),
    (chess.WHITE, chess.BISHOP),
    (chess.WHITE, chess.ROOK),
    (chess.WHITE, chess.QUEEN),
    (chess.WHITE, chess.KING),
    (chess.BLACK, chess.PAWN),
    (chess.BLACK, chess.KNIGHT),
    (chess.BLACK, chess.BISHOP),
    (chess.BLACK, chess.ROOK),
    (chess.BLACK, chess.QUEEN),
    (chess.BLACK, chess.KING),
]

BASE_FEATURE_SIZE = 64 * len(PIECE_ORDER)
EXTRA_FEATURE_SIZE = 6
FEATURE_SIZE = BASE_FEATURE_SIZE + EXTRA_FEATURE_SIZE


def fen_to_features(fen: str) -> np.ndarray:
    """Convert a FEN string into a fixed-length numeric feature vector."""
    board = chess.Board(fen)
    features = np.zeros(FEATURE_SIZE, dtype=np.float32)

    # 12 piece planes x 64 squares
    for plane_idx, (color, piece_type) in enumerate(PIECE_ORDER):
        for square in board.pieces(piece_type, color):
            features[plane_idx * 64 + square] = 1.0

    offset = BASE_FEATURE_SIZE

    # Side to move: 1 for white, 0 for black
    features[offset] = 1.0 if board.turn == chess.WHITE else 0.0

    # Castling rights (KQkq)
    features[offset + 1] = 1.0 if board.has_kingside_castling_rights(chess.WHITE) else 0.0
    features[offset + 2] = 1.0 if board.has_queenside_castling_rights(chess.WHITE) else 0.0
    features[offset + 3] = 1.0 if board.has_kingside_castling_rights(chess.BLACK) else 0.0
    features[offset + 4] = 1.0 if board.has_queenside_castling_rights(chess.BLACK) else 0.0

    # Halfmove clock (light normalization)
    features[offset + 5] = min(board.halfmove_clock, 100) / 100.0

    return features


def result_to_target(result: str) -> int:
    """Map game result string to target label: white win=1, draw=0, black win=-1."""
    if result == "1-0":
        return 1
    if result == "0-1":
        return -1
    if result == "1/2-1/2":
        return 0
    raise ValueError(f"Unsupported result value: {result}")
