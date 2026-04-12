"""Core game utilities for no-UI chess self-play."""

import chess


def create_board() -> chess.Board:
    """Create and return a new chess board in the initial position."""
    return chess.Board()


def get_legal_moves(board: chess.Board) -> list[chess.Move]:
    """Return all legal moves for the current position."""
    return list(board.legal_moves)


def make_move(board: chess.Board, move: chess.Move) -> None:
    """Push a legal move to the board."""
    if move not in board.legal_moves:
        raise ValueError(f"Illegal move: {move}")
    board.push(move)


def is_game_over(board: chess.Board) -> bool:
    """Return whether the game has ended."""
    return board.is_game_over()
