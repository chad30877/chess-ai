"""以相同局面比較 FEN 舊鍵與目前置換鍵；耗時不作例行測試斷言。"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chess

from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits
from engine.search.transposition import TranspositionKey, make_transposition_key


def legacy_fen_key(board, *, ply_from_root):
    """保留優化前的演算法，僅供對照量測。"""
    def identity(position):
        return tuple(position.fen(en_passant="legal").split()[:4])

    rewind = board.copy(stack=True)
    history = [identity(rewind)]
    while rewind.move_stack:
        move = rewind.pop()
        if rewind.is_irreversible(move):
            break
        history.append(identity(rewind))
    history.reverse()
    return TranspositionKey(identity(board), board.halfmove_clock, tuple(history), ply_from_root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--key-iterations", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or args.key_iterations < 1:
        parser.error("重複次數必須為正整數")

    history = chess.Board()
    for move in ("g1f3", "g8f6", "f3g1", "f6g8") * 4:
        history.push_uci(move)
    cases = {
        "start": (chess.Board(), 5, 0),
        "middlegame": (chess.Board(
            "r2q1rk1/ppp2ppp/2n1bn2/3p4/3P4/2PB1N2/PP3PPP/RNBQ1RK1 w - - 0 1"
        ), 3, 4),
        "history": (history, None, None),
    }
    report = dict(python=platform.python_version(), platform=platform.platform(),
                  chess_version=chess.__version__, workers=1, repeats=args.repeats,
                  key_iterations=args.key_iterations, cases={})
    for name, (board, depth, qdepth) in cases.items():
        rows = {mode: dict(key_seconds=[], search_seconds=[], results=[])
                for mode in ("legacy_fen", "current")}
        for repeat in range(args.repeats):
            # 交錯先後，降低暖機與背景負載造成的偏差。
            modes = list(rows) if repeat % 2 == 0 else list(reversed(rows))
            for mode in modes:
                factory = legacy_fen_key if mode == "legacy_fen" else make_transposition_key
                started = perf_counter()
                for _ in range(args.key_iterations):
                    factory(board, ply_from_root=0)
                rows[mode]["key_seconds"].append(perf_counter() - started)
                if depth is not None:
                    searcher = AlphaBetaSearcher(HandcraftedEvaluator(), quiescence_depth=qdepth)
                    before = board.fen(), tuple(board.move_stack)
                    try:
                        with patch("engine.search.alphabeta.make_transposition_key", factory):
                            started = perf_counter()
                            result = searcher.search(board, SearchLimits(max_depth=depth))
                            elapsed = perf_counter() - started
                    finally:
                        searcher.close()
                    if before != (board.fen(), tuple(board.move_stack)):
                        raise RuntimeError("搜尋修改輸入棋盤")
                    signature = asdict(result)
                    signature["best_move"] = result.best_move.uci() if result.best_move else None
                    rows[mode]["search_seconds"].append(elapsed)
                    rows[mode]["results"].append(signature)
        if depth is not None and rows["legacy_fen"]["results"] != rows["current"]["results"]:
            raise RuntimeError(f"{name} 的搜尋結果或節點計數不同")
        for row in rows.values():
            row["key_seconds_median"] = statistics.median(row["key_seconds"])
            if row["search_seconds"]:
                row["search_seconds_median"] = statistics.median(row["search_seconds"])
        report["cases"][name] = dict(fen=board.fen(), moves=[m.uci() for m in board.move_stack],
                                      depth=depth, quiescence_depth=qdepth, modes=rows)
    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
