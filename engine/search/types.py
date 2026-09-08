"""Shared types for engine search components."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import chess

CHECKMATE_SCORE = 1_000_000.0
DRAW_SCORE = 0.0


@dataclass(frozen=True, slots=True)
class SearchLimits:
    """Local search constraints supplied by the caller."""

    max_depth: int = 1
    time_ms: int | None = None

    def __post_init__(self) -> None:
        if self.max_depth <= 0:
            raise ValueError("max_depth must be greater than 0.")
        if self.time_ms is not None and self.time_ms <= 0:
            raise ValueError("time_ms must be greater than 0 when provided.")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Summary of a completed local search.

    `best_move` is the move selected at the root, if one exists.
    `score` is the searched White-perspective evaluation.
    Terminal scores follow the shared search rules:
    `+CHECKMATE_SCORE - ply` means Black is checkmated,
    `-CHECKMATE_SCORE + ply` means White is checkmated,
    and drawn end states score `DRAW_SCORE`.
    `depth_reached` is the deepest ply actually visited from the root.
    `nodes_searched` counts visited positions, including the root node.
    `cutoff_count` counts alpha-beta cutoffs triggered during the search.
    """

    best_move: chess.Move | None
    score: float
    depth_reached: int = 0
    nodes_searched: int = 0
    cutoff_count: int = 0

    def __post_init__(self) -> None:
        if self.depth_reached < 0:
            raise ValueError("depth_reached must be non-negative.")
        if self.nodes_searched < 0:
            raise ValueError("nodes_searched must be non-negative.")
        if self.cutoff_count < 0:
            raise ValueError("cutoff_count must be non-negative.")


@runtime_checkable
class Searcher(Protocol):
    """Protocol implemented by local search backends."""

    def search(self, board: chess.Board, limits: SearchLimits | None = None) -> SearchResult:
        """Return the best move found for the given board."""
