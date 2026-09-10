"""History-safe transposition-table primitives for local search."""

from dataclasses import dataclass
from enum import Enum

import chess


PositionIdentity = tuple[str, str, str, str]


class BoundType(str, Enum):
    """How a stored score relates to the search window that produced it."""

    EXACT = "exact"
    LOWER = "lower"
    UPPER = "upper"


@dataclass(frozen=True, slots=True)
class TranspositionKey:
    """A conservative key that preserves draw and mate-distance semantics."""

    position: PositionIdentity
    halfmove_clock: int
    reversible_history: tuple[PositionIdentity, ...]
    ply_from_root: int


@dataclass(frozen=True, slots=True)
class TranspositionEntry:
    """A cached regular-search result."""

    depth: int
    score: float
    bound: BoundType
    best_move: chess.Move | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.depth, bool)
            or not isinstance(self.depth, int)
            or self.depth < 0
        ):
            raise ValueError("depth must be a non-negative integer.")


def classify_bound(score: float, alpha: float, beta: float) -> BoundType:
    """Classify a completed score against its original alpha-beta window."""

    if score <= alpha:
        return BoundType.UPPER
    if score >= beta:
        return BoundType.LOWER
    return BoundType.EXACT


def _position_identity(board: chess.Board) -> PositionIdentity:
    fields = board.fen(en_passant="legal").split()
    return fields[0], fields[1], fields[2], fields[3]


def _reversible_history(board: chess.Board) -> tuple[PositionIdentity, ...]:
    """Return positions since the last irreversible move, oldest first."""

    rewind = board.copy(stack=True)
    positions = [_position_identity(rewind)]
    while rewind.move_stack:
        move = rewind.pop()
        if rewind.is_irreversible(move):
            break
        positions.append(_position_identity(rewind))
    positions.reverse()
    return tuple(positions)


def make_transposition_key(
    board: chess.Board,
    *,
    ply_from_root: int,
) -> TranspositionKey:
    """Build a key without mutating the board or discarding draw history."""

    if (
        isinstance(ply_from_root, bool)
        or not isinstance(ply_from_root, int)
        or ply_from_root < 0
    ):
        raise ValueError("ply_from_root must be a non-negative integer.")
    return TranspositionKey(
        position=_position_identity(board),
        halfmove_clock=board.halfmove_clock,
        reversible_history=_reversible_history(board),
        ply_from_root=ply_from_root,
    )


class TranspositionTable:
    """In-memory table with depth-preferred, exact-aware replacement."""

    def __init__(self) -> None:
        self._entries: dict[TranspositionKey, TranspositionEntry] = {}

    def probe(self, key: TranspositionKey) -> TranspositionEntry | None:
        return self._entries.get(key)

    def store(self, key: TranspositionKey, entry: TranspositionEntry) -> bool:
        """Store an entry when it is at least as useful as the old value."""

        previous = self._entries.get(key)
        if previous is not None:
            if entry.depth < previous.depth:
                return False
            if (
                entry.depth == previous.depth
                and previous.bound is BoundType.EXACT
                and entry.bound is not BoundType.EXACT
            ):
                return False
        self._entries[key] = entry
        return True

    def __len__(self) -> int:
        return len(self._entries)
