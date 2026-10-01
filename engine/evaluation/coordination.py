"""Coordination v1: opposite-color bishop coverage and exclusive rook-file classes."""

from dataclasses import dataclass

import chess


@dataclass(frozen=True)
class Coordination:
    bishop_pair: int
    rook_open_file: int
    rook_half_open_file: int


def coordination_for_color(board: chess.Board, color: chess.Color) -> Coordination:
    """Award one bishop-pair unit only when both square colors are covered.

    Extra/promoted bishops never multiply the pair bonus. Each rook counts
    separately: no pawns on its file is open, enemy pawns only is half-open,
    any friendly pawn makes it neither. Pawn rank and non-pawn blockers do
    not affect file classification; this does not measure legal rook moves.
    """
    bishops = board.pieces_mask(chess.BISHOP, color)
    pair = int(bool(bishops & chess.BB_LIGHT_SQUARES) and bool(bishops & chess.BB_DARK_SQUARES))
    own_pawns = board.pieces_mask(chess.PAWN, color)
    enemy_pawns = board.pieces_mask(chess.PAWN, not color)
    open_rooks = half_open_rooks = 0
    for square in board.pieces(chess.ROOK, color):
        file = chess.BB_FILES[chess.square_file(square)]
        if own_pawns & file:
            continue
        if enemy_pawns & file:
            half_open_rooks += 1
        else:
            open_rooks += 1
    return Coordination(pair, open_rooks, half_open_rooks)


def coordination_balance(board: chess.Board) -> dict[str, float]:
    """Both colors, fixed White-minus-Black benefit direction."""
    white, black = coordination_for_color(board, chess.WHITE), coordination_for_color(board, chess.BLACK)
    return {
        "bishop_pair": float(white.bishop_pair - black.bishop_pair),
        "rook_open_file": float(white.rook_open_file - black.rook_open_file),
        "rook_half_open_file": float(white.rook_half_open_file - black.rook_half_open_file),
    }
