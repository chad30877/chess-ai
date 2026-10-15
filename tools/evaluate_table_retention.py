"""隔離比較每次清空與跨搜尋保留置換表，不修改正式搜尋生命週期。"""

import argparse
import json
import os
from pathlib import Path
import platform
import sys
from time import perf_counter
import tracemalloc
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chess

from engine.evaluation.evaluator import MaterialEvaluator
from engine.search import AlphaBetaSearcher, BoundType, SearchLimits, TranspositionTable


CASES = {
    "reversible": (chess.STARTING_FEN, ("g1f3", "g8f6", "b1c3")),
    "captures": (
        "r2q1rk1/ppp2ppp/2n1bn2/3p4/3P4/2PB1N2/PP3PPP/RNBQ1RK1 w - - 0 1",
        ("f3e5", "c6e5", "d4e5"),
    ),
}


class ObservedTable(TranspositionTable):
    """額外記錄資料來源；正式表仍處理所有容量與淘汰決策。"""

    def __init__(self, capacity):
        super().__init__(capacity)
        self.search_id = 0
        self.origins = {}
        self.window = (0, float("-inf"), float("inf"))
        self.prior_hits = 0
        self.prior_score_uses = 0
        self.prior_direct_returns = 0

    def probe(self, key):
        entry = super().probe(key)
        if entry is not None and self.origins.get(key) != self.search_id:
            self.prior_hits += 1
            depth, alpha, beta = self.window
            if entry.depth >= max(depth, 0):
                if entry.bound is BoundType.EXACT:
                    self.prior_score_uses += 1
                    self.prior_direct_returns += 1
                elif entry.bound is BoundType.LOWER and entry.score > alpha:
                    self.prior_score_uses += 1
                    self.prior_direct_returns += int(entry.score >= beta)
                elif entry.bound is BoundType.UPPER and entry.score < beta:
                    self.prior_score_uses += 1
                    self.prior_direct_returns += int(entry.score <= alpha)
        return entry

    def store(self, key, entry):
        accepted = super().store(key, entry)
        if accepted:
            self.origins[key] = self.search_id
        # 觀測用來源索引也有界，記憶體量測另註明包含此額外成本。
        if len(self.origins) > 2 * self.capacity:
            self.origins = {
                key: origin for key, origin in self.origins.items()
                if super(ObservedTable, self).probe(key) is not None
            }
        return accepted


class ObservedSearcher(AlphaBetaSearcher):
    """只觀測目前查表視窗，實際搜尋仍由原實作執行。"""

    def _search_recursive(self, board, depth, alpha, beta, current_depth, context=None):
        if context is not None and context.transposition_table is not None:
            context.transposition_table.window = (depth, alpha, beta)
        return super()._search_recursive(board, depth, alpha, beta, current_depth, context)


def run_case(case, depth, capacity, retained, *, measure_memory=False, repeat_root=False):
    fen, moves = CASES[case]
    board = chess.Board(fen)
    table = None
    search_id = 0

    def create_table(requested_capacity):
        nonlocal table
        if table is None or not retained:
            table = ObservedTable(requested_capacity)
        table.search_id = search_id
        return table

    rows = []
    searcher = ObservedSearcher(MaterialEvaluator(), quiescence_depth=0)
    if measure_memory:
        tracemalloc.start()
    try:
        with patch("engine.search.alphabeta.TranspositionTable", create_table):
            for search_id in range(len(moves) + 1):
                before = board.fen(), list(board.move_stack)
                started = perf_counter()
                result = searcher.search(board, SearchLimits(max_depth=depth, transposition_capacity=capacity))
                elapsed = perf_counter() - started
                if (board.fen(), board.move_stack) != before:
                    raise RuntimeError("研究搜尋修改了輸入棋盤")
                if result.completed_depth != depth or result.best_move not in board.legal_moves:
                    raise RuntimeError("研究搜尋未完成或選步不合法")
                rows.append({
                    "root": search_id, "fen": board.fen(), "elapsed_s": elapsed,
                    "nodes": result.nodes_searched, "hits": result.transposition_hits,
                    "prior_hits": table.prior_hits,
                    "prior_score_uses": table.prior_score_uses,
                    "prior_direct_returns": table.prior_direct_returns,
                    "occupancy": len(table), "best_move": result.best_move.uci(),
                    "score": result.score,
                })
                table.prior_hits = table.prior_score_uses = table.prior_direct_returns = 0
                if search_id < len(moves) and not repeat_root:
                    board.push_uci(moves[search_id])
        memory = tracemalloc.get_traced_memory() if measure_memory else None
    finally:
        if measure_memory:
            tracemalloc.stop()
    return {
        "case": case, "depth": depth, "capacity": capacity,
        "retained": retained, "rows": rows,
        "elapsed_s": sum(row["elapsed_s"] for row in rows),
        "nodes": sum(row["nodes"] for row in rows),
        "hits": sum(row["hits"] for row in rows),
        "prior_hits": sum(row["prior_hits"] for row in rows),
        "prior_score_uses": sum(row["prior_score_uses"] for row in rows),
        "prior_direct_returns": sum(row["prior_direct_returns"] for row in rows),
        "max_occupancy": max(row["occupancy"] for row in rows),
        "traced_current_peak_bytes": memory,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depths", type=int, nargs="+", default=[3, 4])
    parser.add_argument("--capacities", type=int, nargs="+", default=[128, 4096])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--measure-memory", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats 必須為正整數")
    if any(value < 1 for value in args.depths + args.capacities):
        parser.error("depths 與 capacities 必須為正整數")
    results = []
    for repeat in range(args.repeats):
        for case in CASES:
            for depth in args.depths:
                for capacity in args.capacities:
                    # 交替次序減少固定先後順序的暖機偏差。
                    for retained in ((False, True) if repeat % 2 == 0 else (True, False)):
                        result = run_case(case, depth, capacity, retained, measure_memory=args.measure_memory)
                        result["repeat"] = repeat
                        results.append(result)
    control = run_case("captures", min(args.depths), max(args.capacities), True, repeat_root=True)
    if control["prior_direct_returns"] == 0:
        raise RuntimeError("重複相同根局面的觀測對照沒有記錄到舊分數重用")
    print(json.dumps({
        "python": sys.version, "platform": platform.platform(), "logical_cpus": os.cpu_count(),
        "options": vars(args), "evaluator": "MaterialEvaluator/default",
        "search": "single worker, qdepth=0, other options default",
        "memory_note": "tracemalloc 包含觀測索引與棋盤；不是 RSS 或程序樹記憶體。啟用追蹤的耗時不可與未追蹤值混合。",
        "same_root_observation_control": control,
        "results": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
