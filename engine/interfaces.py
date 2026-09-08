"""Shared protocols for engine components."""

from typing import Protocol, runtime_checkable

import chess


@runtime_checkable
class Player(Protocol):
    """A move selector that chooses one legal move for a position."""

    def choose_move(self, board: chess.Board) -> chess.Move:
        """Return a legal move for the given board."""


@runtime_checkable
class Evaluator(Protocol):
    """A non-terminal position evaluator that returns a score from White's perspective.

    Positive scores favor White, negative scores favor Black, and the score must
    not flip based on whose turn it is. Searchers are responsible for applying
    shared terminal scoring rules for checkmate and drawn end states.
    """

    def evaluate(self, board: chess.Board) -> float:
        """Return a White-perspective evaluation score for the given board."""
