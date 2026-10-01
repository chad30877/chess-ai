"""Pawn model v1: geometric structure, independent of turn and move legality."""

from dataclasses import dataclass

import chess


@dataclass(frozen=True)
class PawnStructure:
    isolated: int
    doubled: int
    passed: int
    passed_rank_units: int


def pawn_structure_for_color(board: chess.Board, color: chess.Color) -> PawnStructure:
    """Count isolated pawns, extra pawns per file, and frontmost passers.

    Isolation checks either adjacent file at any rank. A passer has no enemy
    pawn strictly ahead on its own/adjacent files and no friendly pawn ahead
    on its own file. Non-pawn blockers and attacks do not affect this feature.
    Passed rank units are relative rank minus one: ranks 2..7 give 1..6.
    """
    own = tuple(board.pieces(chess.PAWN, color))
    enemy = tuple(board.pieces(chess.PAWN, not color))
    files = [0] * 8
    for square in own:
        files[chess.square_file(square)] += 1
    isolated = passed = passed_units = 0
    for square in own:
        file, rank = chess.square_file(square), chess.square_rank(square)
        if not any(files[adjacent] for adjacent in (file - 1, file + 1) if 0 <= adjacent < 8):
            isolated += 1

        def ahead(other: chess.Square) -> bool:
            other_rank = chess.square_rank(other)
            return other_rank > rank if color == chess.WHITE else other_rank < rank

        enemy_ahead = any(abs(chess.square_file(other) - file) <= 1 and ahead(other)
                          for other in enemy)
        friendly_ahead = any(chess.square_file(other) == file and ahead(other) for other in own)
        if not enemy_ahead and not friendly_ahead:
            passed += 1
            passed_units += max(0, min(rank if color == chess.WHITE else 7 - rank, 6))
    return PawnStructure(isolated, sum(max(0, count - 1) for count in files), passed, passed_units)


def pawn_structure_balance(board: chess.Board) -> dict[str, float]:
    """Positive values favor White: Black-minus-White defects, reverse passers."""
    white = pawn_structure_for_color(board, chess.WHITE)
    black = pawn_structure_for_color(board, chess.BLACK)
    return {
        "isolated_pawns": float(black.isolated - white.isolated),
        "doubled_pawns": float(black.doubled - white.doubled),
        "passed_pawns": float(white.passed_rank_units - black.passed_rank_units),
    }
