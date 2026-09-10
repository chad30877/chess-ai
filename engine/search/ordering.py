"""Basic, deterministic move ordering for alpha-beta search."""

from collections.abc import Iterable

import chess


_ORDER_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


def _captured_piece_type(board: chess.Board, move: chess.Move) -> chess.PieceType | None:
    if board.is_en_passant(move):
        return chess.PAWN
    captured_piece = board.piece_at(move.to_square)
    return captured_piece.piece_type if captured_piece is not None else None


def move_order_key(board: chess.Board, move: chess.Move) -> tuple[int, int, int, int]:
    """Rank promotions first, then captures using a simple victim/attacker score."""

    promotion_value = _ORDER_VALUES.get(move.promotion, 0)
    captured_piece_type = _captured_piece_type(board, move)
    attacker = board.piece_at(move.from_square)
    capture_value = 0
    if captured_piece_type is not None and attacker is not None:
        capture_value = (
            10 * _ORDER_VALUES[captured_piece_type]
            - _ORDER_VALUES[attacker.piece_type]
        )
    return (
        int(move.promotion is not None),
        promotion_value,
        int(captured_piece_type is not None),
        capture_value,
    )


def order_moves(
    board: chess.Board,
    moves: Iterable[chess.Move],
    preferred_move: chess.Move | None = None,
) -> list[chess.Move]:
    """Return a stable priority list, optionally led by a cached best move."""

    ordered = sorted(moves, key=lambda move: move_order_key(board, move), reverse=True)
    if preferred_move is not None and preferred_move in ordered:
        ordered.remove(preferred_move)
        ordered.insert(0, preferred_move)
    return ordered
