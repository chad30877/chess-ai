"""History-safe transposition-table primitives for local search."""

from dataclasses import dataclass
from enum import Enum
from heapq import heapify, heappop, heappush

DEFAULT_TRANSPOSITION_CAPACITY = 4_096

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
    """有界搜尋快取；每代抵銷兩層深度，等深度優先保留 EXACT。"""

    def __init__(self, capacity: int = DEFAULT_TRANSPOSITION_CAPACITY) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("capacity must be a positive integer.")
        self.capacity = capacity
        self._generation = 0
        self._serial = 0
        self._entries: dict[TranspositionKey, tuple[TranspositionEntry, int, int]] = {}
        self._heap: list[tuple[tuple[int, int], int, TranspositionKey]] = []

    def advance_generation(self) -> None:
        """開始同次搜尋的下一輪迭代，舊結果逐漸失去保留優先權。"""
        self._generation += 1

    @staticmethod
    def _priority(entry: TranspositionEntry, generation: int) -> tuple[int, int]:
        return entry.depth + 2 * generation, int(entry.bound is BoundType.EXACT)

    def probe(self, key: TranspositionKey) -> TranspositionEntry | None:
        stored = self._entries.get(key)
        return stored[0] if stored is not None else None

    def store(self, key: TranspositionKey, entry: TranspositionEntry) -> bool:
        """接受較有價值的結果；滿額時只淘汰最低價值的一項。"""
        priority = self._priority(entry, self._generation)
        previous = self._entries.get(key)
        if previous is not None:
            if priority < self._priority(previous[0], previous[1]):
                return False
        elif len(self._entries) >= self.capacity:
            while self._heap:
                victim_priority, serial, victim_key = self._heap[0]
                if victim_key in self._entries and self._entries[victim_key][2] == serial:
                    break
                heappop(self._heap)
            if priority < victim_priority:
                return False
            heappop(self._heap)
            del self._entries[victim_key]
        self._serial += 1
        self._entries[key] = entry, self._generation, self._serial
        heappush(self._heap, (priority, self._serial, key))
        # 同鍵更新的舊索引也維持有界；重建成本攤提至多次寫入。
        if len(self._heap) > 2 * self.capacity:
            self._heap = [
                (self._priority(value, generation), serial, stored_key)
                for stored_key, (value, generation, serial) in self._entries.items()
            ]
            heapify(self._heap)
        return True

    def __len__(self) -> int:
        return len(self._entries)
