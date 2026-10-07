"""以相同有限工作量量測批次耗時，包含程序啟動與保存成本。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import platform
import tempfile
from time import perf_counter

import chess

from engine.evaluation.config import EvaluationConfig
from engine.sessions.batch_run import BatchRun, BatchSettings
from engine.sessions.evaluation_comparison import ComparisonParticipant, ComparisonSearchConfig, run_evaluation_comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=16)
    parser.add_argument("--pairs", type=int, default=8)
    parser.add_argument("--plies", type=int, default=12)
    parser.add_argument("--depth", type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(dict(platform=platform.platform(), python=platform.python_version(),
                          cpu_count=os.cpu_count(), games=args.games, pairs=args.pairs,
                          max_plies=args.plies, depth=args.depth, base_seed=42), ensure_ascii=False))
    with tempfile.TemporaryDirectory(prefix="chess-batch-benchmark-") as temporary:
        root = Path(temporary) / "batches"
        search = ComparisonSearchConfig(depth_plies=args.depth)
        for mode in ("general", "evaluation"):
            expected = None
            for requested in (1, 4, 8):
                started = perf_counter()
                if mode == "general":
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        run = BatchRun(BatchSettings(white="Greedy", black="Greedy", games=args.games,
                                       workers=requested, max_plies=args.plies, base_seed=42), root, executor)
                        path = run.future.result()
                        if run.snapshot()["status"] != "completed":
                            raise RuntimeError(run.snapshot()["error"])
                else:
                    result = run_evaluation_comparison(
                        baseline=ComparisonParticipant.alphabeta("baseline", EvaluationConfig(), search=search),
                        candidate=ComparisonParticipant.alphabeta("candidate", EvaluationConfig(phase_enabled=True), search=search),
                        initial_fens=(chess.STARTING_FEN,), repetitions=args.pairs, base_seed=42,
                        max_plies=args.plies, workers=requested, batch_root=root)
                    path = result.path
                seconds = perf_counter() - started
                manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
                count = manifest["counts"]["saved_games"]
                signatures = {}
                with (path / "games.csv").open(encoding="utf-8", newline="") as stream:
                    for row in csv.DictReader(stream):
                        replay = json.loads((path / row["replay_path"]).read_text(encoding="utf-8"))
                        signatures[replay["metadata"]["execution"]["game_number"]] = (
                            row["seed"], row["white_player"], row["black_player"],
                            replay["moves_uci"], row["result"], row["termination"])
                if expected is not None and signatures != expected:
                    raise ValueError(f"{mode} 的 {requested} worker 棋局與單程序不一致")
                expected = signatures
                print(json.dumps(dict(mode=mode, requested_workers=requested, actual_workers=manifest["settings"]["workers"],
                                      seconds=round(seconds, 4), saved_games=count,
                                      games_per_second=round(count / seconds, 3), results_match=True), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
