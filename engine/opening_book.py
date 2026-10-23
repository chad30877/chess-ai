"""固定來源的具名開局與單局永久離庫政策。"""

import csv
import hashlib
import io
import json
import random
from pathlib import Path

import chess
import chess.pgn

DATA_ROOT = Path(__file__).resolve().parents[1] / "data/openings"


def validate_opening_limit(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("開局庫手數必須為非負整數（半回合）")


class OpeningBook:
    def __init__(self, root=DATA_ROOT):
        root = Path(root)
        self.source = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if (self.source.get("license") != "CC0-1.0"
                or set(self.source.get("sha256", {})) != {"a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv", "COPYING.txt"}):
            raise ValueError("開局庫來源清單無效")
        self.moves = {}
        for name, expected in self.source["sha256"].items():
            data = (root / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"開局庫資料損壞：{name}")
            if not name.endswith(".tsv"):
                continue
            for row in csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter="\t"):
                game = chess.pgn.read_game(io.StringIO(row["pgn"]))
                if game is None or game.errors:
                    raise ValueError(f"開局序列無效：{row['name']}")
                board = game.board()
                for move in game.mainline_moves():
                    if move not in board.legal_moves:
                        raise ValueError(f"開局走法非法：{row['name']}")
                    self.moves.setdefault(self.key(board), set()).add(move.uci())
                    board.push(move)

    @staticmethod
    def key(board):
        return " ".join(board.fen(en_passant="legal").split()[:4])

    def choices(self, board):
        return [chess.Move.from_uci(uci) for uci in sorted(self.moves.get(self.key(board), ()))
                if chess.Move.from_uci(uci) in board.legal_moves]


class OpeningPolicy:
    def __init__(self, seed, max_plies=12, book=None):
        validate_opening_limit(max_plies)
        self.book = book if book is not None else OpeningBook()
        self.seed, self.max_plies = seed, max_plies
        self.rng = random.Random(seed)
        self.moves = []
        self.exited = False
        self.exit_reason = None
        self.exit_ply = None

    def candidates(self, board):
        if self.exited:
            return []
        moves = self.book.choices(board)
        reason = "limit" if len(board.move_stack) >= self.max_plies else "missing" if not moves else None
        if reason:
            self.exited, self.exit_reason = True, reason
            self.exit_ply = len(board.move_stack)
            return []
        return moves

    def choose(self, board):
        moves = self.candidates(board)
        return self.rng.choice(moves) if moves else None

    def apply(self, board, move):
        moves = self.candidates(board)
        if moves:
            if move in moves:
                self.moves.append(move.uci())
            else:
                self.exited, self.exit_reason = True, "deviation"
                self.exit_ply = len(board.move_stack) + 1

    def snapshot(self):
        return dict(source=self.book.source, seed=self.seed, max_plies=self.max_plies,
                    moves_uci=list(self.moves), exited=self.exited,
                    exit_reason=self.exit_reason, exit_ply=self.exit_ply)
