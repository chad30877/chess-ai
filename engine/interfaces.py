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
    """A position evaluator that returns a score from White's perspective."""

    def evaluate(self, board: chess.Board) -> float:
        """Return an evaluation score for the given board."""
