"""Shared terminal scoring for move-selection strategies."""

import chess

from engine.game import get_outcome
from engine.search.types import CHECKMATE_SCORE, DRAW_SCORE


def terminal_score(
    board: chess.Board,
    *,
    ply_from_root: int = 0,
    claim_draw: bool = False,
) -> float | None:
    """Return a White-perspective terminal score, or ``None`` if play continues."""

    outcome = get_outcome(board, claim_draw=claim_draw)
    if outcome is None:
        return None
    if outcome.winner is None:
        return DRAW_SCORE

    mate_score = CHECKMATE_SCORE - ply_from_root
    return mate_score if outcome.winner == chess.WHITE else -mate_score
