"""Shared types for engine search components."""

from collections.abc import Callable
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
    stop_requested: Callable[[], bool] | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_depth, bool)
            or not isinstance(self.max_depth, int)
            or self.max_depth <= 0
        ):
            raise ValueError("max_depth must be a positive integer.")
        if self.time_ms is not None and (
            isinstance(self.time_ms, bool)
            or not isinstance(self.time_ms, int)
            or self.time_ms <= 0
        ):
            raise ValueError("time_ms must be a positive integer when provided.")
        if self.stop_requested is not None and not callable(self.stop_requested):
            raise ValueError("stop_requested must be callable when provided.")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Summary of a completed local search.

    `best_move` is the move selected at the root, if one exists.
    `score` is the searched White-perspective evaluation.
    Terminal scores follow the shared search rules:
    `+CHECKMATE_SCORE - ply` means Black is checkmated,
    `-CHECKMATE_SCORE + ply` means White is checkmated,
    and drawn end states score `DRAW_SCORE`.
    `depth_reached` is the deepest ply actually visited from the root, including
    any quiescence extension beyond the requested regular depth.
    `nodes_searched` counts visited positions, including the root node.
    `cutoff_count` counts alpha-beta cutoffs triggered during the search.
    `transposition_hits` counts table probes that found an entry, including a
    shallower entry used only for move ordering. `transposition_stores` counts
    accepted table writes.
    `completed_depth` is the deepest fully completed regular iterative-deepening
    iteration; it excludes quiescence extensions. `stop_reason` is ``timeout``
    or ``cancelled`` when a cooperative stop returned an earlier result.
    """

    best_move: chess.Move | None
    score: float
    depth_reached: int = 0
    nodes_searched: int = 0
    cutoff_count: int = 0
    completed_depth: int = 0
    stop_reason: str | None = None
    transposition_hits: int = 0
    transposition_stores: int = 0

    def __post_init__(self) -> None:
        if self.depth_reached < 0:
            raise ValueError("depth_reached must be non-negative.")
        if self.nodes_searched < 0:
            raise ValueError("nodes_searched must be non-negative.")
        if self.cutoff_count < 0:
            raise ValueError("cutoff_count must be non-negative.")
        if self.transposition_hits < 0:
            raise ValueError("transposition_hits must be non-negative.")
        if self.transposition_stores < 0:
            raise ValueError("transposition_stores must be non-negative.")
        if self.completed_depth < 0:
            raise ValueError("completed_depth must be non-negative.")
        if self.completed_depth > self.depth_reached:
            raise ValueError("completed_depth cannot exceed depth_reached.")
        if self.stop_reason not in (None, "timeout", "cancelled"):
            raise ValueError("stop_reason must be timeout, cancelled, or None.")


@runtime_checkable
class Searcher(Protocol):
    """Protocol implemented by local search backends."""

    def search(self, board: chess.Board, limits: SearchLimits | None = None) -> SearchResult:
        """Return the best move found for the given board."""
