"""Core game utilities for no-UI chess self-play."""

import chess


def create_board(initial_fen: str = chess.STARTING_FEN) -> chess.Board:
    """Create a board; callers must keep its move stack for repetition rules."""
    return chess.Board(initial_fen)


def get_legal_moves(board: chess.Board) -> list[chess.Move]:
    """Return all legal moves for the current position."""
    return list(board.legal_moves)


def make_move(board: chess.Board, move: chess.Move) -> None:
    """Push a legal move to the board."""
    if move not in board.legal_moves:
        raise ValueError(f"Illegal move: {move}")
    board.push(move)


def get_outcome(board: chess.Board, *, claim_draw: bool = False) -> chess.Outcome | None:
    """Apply automatic rules, optionally claiming any available draw.

    claim_draw includes a draw claim available by announcing the next move,
    matching python-chess semantics. Execution limits are not chess outcomes.
    """
    return board.outcome(claim_draw=claim_draw)


def is_game_over(board: chess.Board, *, claim_draw: bool = False) -> bool:
    return get_outcome(board, claim_draw=claim_draw) is not None


def get_result(board: chess.Board, *, claim_draw: bool = False) -> str:
    outcome = get_outcome(board, claim_draw=claim_draw)
    return outcome.result() if outcome is not None else "*"
