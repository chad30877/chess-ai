"""Mobility v1: per-piece geometric attacks excluding friendly occupied squares.

This is attack-space activity, not legal moves or safe mobility. Pins, check,
enemy attacks and king exposure do not filter destinations. Pawn diagonals
count even when empty; pawn pushes, castling and en passant are not added.
Sliding attacks stop at the first occupied square; enemy captures count.
Shared destinations count once for each attacking piece, not once per side.
"""

import chess

MOBILITY_PIECE_TYPES = {
    "pawn_mobility": chess.PAWN,
    "knight_mobility": chess.KNIGHT,
    "bishop_mobility": chess.BISHOP,
    "rook_mobility": chess.ROOK,
    "queen_mobility": chess.QUEEN,
    "king_mobility": chess.KING,
}


def mobility_for_color(board: chess.Board, color: chess.Color) -> dict[str, int]:
    """Sum each piece's eligible attack squares, without modifying the board."""
    friendly = board.occupied_co[color]
    return {
        name: sum((board.attacks_mask(square) & ~friendly).bit_count()
                  for square in board.pieces(kind, color))
        for name, kind in MOBILITY_PIECE_TYPES.items()
    }


def mobility_balance(board: chess.Board) -> dict[str, float]:
    """Always evaluate both colors and return White-minus-Black activity."""
    white, black = mobility_for_color(board, chess.WHITE), mobility_for_color(board, chess.BLACK)
    return {name: float(white[name] - black[name]) for name in MOBILITY_PIECE_TYPES}
