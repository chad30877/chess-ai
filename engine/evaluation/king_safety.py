"""King safety v1 uses current location/occupancy, never castling rights/history."""

from dataclasses import dataclass

import chess


@dataclass(frozen=True)
class KingSafety:
    pawn_shield: int
    zone_attacks: int
    file_exposure: int


def king_safety_for_color(board: chess.Board, color: chess.Color) -> KingSafety:
    """Immediate forward pawn shield, attacked king ring, and exposed files.

    The ring includes the king and all adjacent on-board squares, occupied or
    empty. Each attacked square counts once; pinned attackers still count.
    On king/adjacent files: no friendly pawns costs one unit if enemy pawns
    remain, two if no pawns remain. Non-pawn blockers do not change exposure.
    Missing kings in debug positions contribute zero features for that color.
    """
    king = board.king(color)
    if king is None:
        return KingSafety(0, 0, 0)
    file, rank = chess.square_file(king), chess.square_rank(king)
    files = range(max(0, file - 1), min(7, file + 1) + 1)
    forward = rank + (1 if color == chess.WHITE else -1)
    own_pawns, enemy_pawns = board.pieces_mask(chess.PAWN, color), board.pieces_mask(chess.PAWN, not color)
    shield = sum(bool(own_pawns & chess.BB_SQUARES[chess.square(f, forward)])
                 for f in files) if 0 <= forward < 8 else 0
    zone = chess.SquareSet(chess.BB_KING_ATTACKS[king] | chess.BB_SQUARES[king])
    attacks = sum(board.is_attacked_by(not color, square) for square in zone)
    exposure = 0
    for f in files:
        if not own_pawns & chess.BB_FILES[f]:
            exposure += 1 if enemy_pawns & chess.BB_FILES[f] else 2
    return KingSafety(shield, attacks, exposure)


def king_safety_balance(board: chess.Board) -> dict[str, float]:
    """White-minus-Black shield, Black-minus-White danger; positive favors White."""
    white, black = king_safety_for_color(board, chess.WHITE), king_safety_for_color(board, chess.BLACK)
    return {
        "king_pawn_shield": float(white.pawn_shield - black.pawn_shield),
        "king_zone_attacks": float(black.zone_attacks - white.zone_attacks),
        "king_file_exposure": float(black.file_exposure - white.file_exposure),
    }
