"""固定工作量量測搜尋與兩層程序派工；耗時不作例行測試斷言。"""

import argparse
import cProfile
from dataclasses import asdict
import pstats
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chess

from engine.evaluation.config import EvaluationConfig
from engine.evaluation.evaluator import HandcraftedEvaluator
from engine.search import AlphaBetaSearcher, SearchLimits
from engine.search.transposition import BoundType, TranspositionTable

CASES = {
    "start": (chess.STARTING_FEN, ("h2h3", "h7h6")),
    "middlegame": (
        "r2q1rk1/ppp2ppp/2n1bn2/3p4/3P4/2PB1N2/PP3PPP/RNBQ1RK1 w - - 0 1",
        ("a2a3", "a7a6"),
    ),
    "rook": ("8/5pk1/6p1/8/3R4/6P1/5PK1/7r w - - 0 35", ("f2f3", "f7f6")),
    "minor": ("8/5pk1/6p1/8/3N4/6P1/5PK1/7n w - - 0 35", ("f2f3", "f7f6")),
}
HISTORY_MOVES = ("g1f3", "g8f6", "f3g1", "f6g8")
CASES["history"] = chess.STARTING_FEN, ("h2h3", "h7h6")
quiet = chess.Board()
for move in ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "d2d3", "g8f6"):
    quiet.push_uci(move)
CASES["quiet"] = quiet.fen(), ("e1g1", "e8g8")


def install_latency_observer():
    """spawn 載入主模組時安裝觀測；每程序寫自己的暫存檔，不改正式 IPC。"""
    folder = os.environ.get("CHESS_BENCH_LATENCY_DIR")
    if not folder:
        return
    original = AlphaBetaSearcher.search

    def observed(searcher, board, limits=None):
        started = perf_counter()
        result = original(searcher, board, limits)
        row = dict(seconds=perf_counter() - started, nodes=result.nodes_searched,
                   completed_depth=result.completed_depth, workers=searcher.search_workers)
        with (Path(folder) / f"{os.getpid()}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
        return result

    AlphaBetaSearcher.search = observed


install_latency_observer()


class TreeMemory:
    def __init__(self, pid):
        self.pid = pid

    def __enter__(self):
        import psutil

        self.root = psutil.Process(self.pid)
        self.peak = 0
        self.max_processes = 0
        self.done = threading.Event()

        def sample():
            while not self.done.is_set():
                try:
                    processes = [self.root] + self.root.children(recursive=True)
                except psutil.Error:
                    processes = []
                total = 0
                for process in processes:
                    try:
                        total += process.memory_info().rss
                    except psutil.Error:
                        pass
                self.peak = max(self.peak, total)
                self.max_processes = max(self.max_processes, len(processes))
                self.done.wait(0.02)

        self.thread = threading.Thread(target=sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.done.set()
        self.thread.join()


def search_job(job):
    # 世代係數只供隔離基準比較，正式實作仍使用既定值 2。
    weight = job["age_weight"]
    TranspositionTable._priority = staticmethod(
        lambda entry, generation: (entry.depth + weight * generation, int(entry.bound is BoundType.EXACT))
    )
    fen, moves = CASES[job["case"]]
    board = chess.Board(fen)
    if job["case"] == "history":
        for move in HISTORY_MOVES:
            board.push_uci(move)
    config = EvaluationConfig.from_dict(job["evaluation"])
    searcher = AlphaBetaSearcher(HandcraftedEvaluator(config=config), search_workers=job["workers"],
                                quiescence_depth=job["quiescence_depth"])
    rows = []
    try:
        for step in range(job["steps"] + 1):
            if step and not job.get("reuse_position"):
                board.push_uci(moves[step - 1])
            before = board.fen(), tuple(board.move_stack)
            profiler = cProfile.Profile() if job.get("profile") else None
            started = perf_counter()
            if profiler:
                profiler.enable()
            result = searcher.search(board, SearchLimits(
                max_depth=job["depth"], time_ms=job["timeout_ms"],
                transposition_capacity=job["capacity"],
            ))
            if profiler:
                profiler.disable()
            elapsed = perf_counter() - started
            profile_rows = []
            if profiler:
                for (filename, line, name), (primitive, calls, own, cumulative, _) in pstats.Stats(profiler).stats.items():
                    normalized = filename.replace("\\", "/")
                    category = ("evaluation" if "/engine/evaluation/" in normalized else
                                "transposition_key" if "/engine/search/transposition.py" in normalized else
                                "search" if "/engine/search/" in normalized else
                                "board_history" if "/chess/" in normalized else "other")
                    profile_rows.append(dict(category=category, file=normalized, line=line,
                                             function=name, calls=calls, self_seconds=own,
                                             cumulative_seconds=cumulative))
                profile_rows.sort(key=lambda row: row["self_seconds"], reverse=True)
            if before != (board.fen(), tuple(board.move_stack)):
                raise RuntimeError("搜尋修改了輸入棋盤")
            if result.best_move not in board.legal_moves:
                raise RuntimeError("搜尋未提供合法走法")
            rows.append(dict(
                step=step, mode="cold" if step == 0 else "warm", fen=board.fen(),
                seconds=elapsed, nodes=result.nodes_searched, hits=result.transposition_hits,
                completed_depth=result.completed_depth, stop_reason=result.stop_reason,
                best_move=result.best_move.uci(), score=result.score,
                initial_fen=board.root().fen(), moves=[m.uci() for m in board.move_stack],
                result={**asdict(result), "best_move": result.best_move.uci()},
                measurement="profile" if profiler else "timing",
                profile=profile_rows,
                profile_self_seconds={category: sum(r["self_seconds"] for r in profile_rows
                    if r["category"] == category) for category in
                    ("evaluation", "transposition_key", "search", "board_history", "other")},
            ))
            print(f"{job['case']} / {job['workers']} worker / step {step}: "
                  f"depth {result.completed_depth}, {elapsed:.3f}s", flush=True)
            if result.completed_depth < job["depth"]:
                break
    finally:
        searcher.close()
    return dict(**job, rows=rows, all_completed=(len(rows) == job["steps"] + 1 and
                all(row["completed_depth"] == job["depth"] for row in rows)))


def batch_job(job):
    from engine.sessions.batch_run import BatchRun, BatchSettings

    with tempfile.TemporaryDirectory(prefix="chess-benchmark-") as temporary:
        folder = Path(temporary)
        log_dir = folder / "steps"
        log_dir.mkdir()
        os.environ["CHESS_BENCH_LATENCY_DIR"] = str(log_dir)
        install_latency_observer()
        started = perf_counter()
        with ThreadPoolExecutor(max_workers=1) as executor:
            run = BatchRun(BatchSettings(
                white="AlphaBeta", black="AlphaBeta", games=job["games"],
                workers=job["outer"], search_workers=job["inner"],
                search_depth=job["depth"], max_plies=job["plies"], base_seed=42,
                initial_fen=CASES["start"][0],
            ), folder / "batches", executor)
            path = run.future.result(timeout=job["job_timeout_s"])
            state = run.snapshot()
        elapsed = perf_counter() - started
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        replays = [json.loads(p.read_text(encoding="utf-8")) for p in (path / "replays").glob("*.json")]
        steps = [json.loads(line) for p in log_dir.glob("*.jsonl")
                 for line in p.read_text(encoding="utf-8").splitlines()]
        if state["status"] != "completed" or len(replays) != job["games"]:
            raise RuntimeError(f"批次未完整保存：{state}")
        if len(steps) != job["games"] * job["plies"]:
            raise RuntimeError("單步觀測數量與固定工作量不一致")
        if any(step["completed_depth"] != job["depth"] for step in steps):
            raise RuntimeError("批次包含未完成指定深度的搜尋")
        latencies = sorted(step["seconds"] for step in steps)
        return dict(**job, seconds=elapsed, games_per_second=len(replays) / elapsed,
                    actual_outer=manifest["settings"]["workers"],
                    saved_games=len(replays), observed_steps=len(steps),
                    step_seconds_median=statistics.median(latencies),
                    step_seconds_max=max(latencies), step_seconds=latencies,
                    nodes=sum(step["nodes"] for step in steps),
                    search_settings=manifest["settings"]["strategies"]["white"]["search"],
                    saved_status=manifest["status"])


def isolated(job):
    import psutil

    with tempfile.TemporaryDirectory(prefix="chess-benchmark-job-") as temporary:
        request, result = [Path(temporary) / name for name in ("request.json", "result.json")]
        request.write_text(json.dumps(job), encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                    "--job", str(request), "--result", str(result)])
        try:
            # 在外部程序取樣，避免監測執行緒競爭單程序搜尋的 GIL。
            with (TreeMemory(process.pid) if job["sample_memory"] else nullcontext()) as memory:
                status = process.wait(timeout=job["job_timeout_s"])
            if status != 0:
                raise RuntimeError(f"基準工作失敗，exit={status}：{job}")
            row = json.loads(result.read_text(encoding="utf-8"))
            return dict(**row, peak_tree_rss_bytes=memory.peak if memory else None,
                        max_processes=memory.max_processes if memory else None)
        finally:
            if process.poll() is None:
                parent = psutil.Process(process.pid)
                descendants = parent.children(recursive=True)
                for child in descendants:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                process.kill()
                psutil.wait_procs(descendants, timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, help="完整評分設定 JSON；省略維持預設")
    parser.add_argument("--profile", action="store_true", help="單 worker 剖析，獨立於一般計時")
    parser.add_argument("--reuse-position", action="store_true", help="steps 重複同局面以隔離程序重用成本")
    parser.add_argument("--suite", choices=("search", "capacity", "batch"), default="search")
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--quiescence-depth", type=int, default=0,
                        help="search/capacity 的靜態延伸深度；batch 使用正式預設 4")
    parser.add_argument("--cases", choices=tuple(CASES), nargs="+",
                        default=["start", "middlegame", "rook", "minor"])
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--steps", type=int, choices=(0, 1, 2), default=2)
    parser.add_argument("--timeout-ms", type=int, default=120000)
    parser.add_argument("--capacities", type=int, nargs="+", default=[128, 4096, 65536])
    parser.add_argument("--age-weights", type=int, nargs="+", default=[2])
    parser.add_argument("--games", type=int, default=4)
    parser.add_argument("--plies", type=int, default=2)
    parser.add_argument("--matrix", nargs="+", default=["1x1", "1x4", "2x2", "4x5"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-memory-sampling", action="store_true")
    parser.add_argument("--job", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        import psutil
    except ImportError:
        parser.error("效能量測需要選用套件：python -m pip install psutil")
    if args.job:
        job = json.loads(args.job.read_text(encoding="utf-8"))
        result = batch_job(job) if job["suite"] == "batch" else search_job(job)
        args.result.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return
    if args.output is None:
        parser.error("請提供 --output，保存可重現資料")
    if (args.repeats < 1 or not 0 < args.timeout_ms <= 120000 or args.games < 1 or args.plies < 1
            or args.depth < 1 or args.quiescence_depth < 0
            or any(value < 1 for value in args.workers + args.capacities)
            or any(value < 0 for value in args.age_weights)):
        parser.error("工作量必須為正整數，單次搜尋上限為 1..120000ms")
    evaluation = EvaluationConfig.from_dict(json.loads(args.evaluation.read_text(encoding="utf-8"))) if args.evaluation else EvaluationConfig()
    if args.evaluation and args.suite == "batch":
        parser.error("完整評分設定限 search/capacity；batch 維持既有預設")
    if args.profile and (args.suite == "batch" or any(w != 1 for w in args.workers)):
        parser.error("剖析限單 worker；未涵蓋子程序成本")
    matrix = []
    try:
        for pair in args.matrix:
            outer, inner = map(int, pair.split("x"))
            if outer < 1 or inner < 1:
                raise ValueError
            matrix.append((outer, inner))
    except ValueError:
        parser.error("matrix 格式為正整數 outerxinner")
    document = dict(
        platform=platform.platform(), python=platform.python_version(), logical_cpus=os.cpu_count(),
        psutil=psutil.__version__, chess=chess.__version__, evaluation=evaluation.to_dict(),
        revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, encoding="utf-8").strip(),
        dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], text=True, encoding="utf-8").strip()),
        all_terms_enabled=all(t["enabled"] for t in evaluation.to_dict()["terms"].values()),
        profiling_scope="parent only; profile allowed only with one worker",
        summary=[],
        options={key: str(value) if isinstance(value, Path) else value
                 for key, value in vars(args).items() if key not in ("job", "result")},
        search_defaults=dict(move_ordering=True, use_transposition_table=True, use_pvs=True,
                             aspiration_window=1.0, claim_draw=False),
        memory="external controller samples concurrent sum RSS of isolated job and all descendants every20ms; peak covers whole cold+warm job",
        rows=[],
    )
    jobs = []
    for repeat in range(args.repeats):
        if args.suite == "batch":
            for outer, inner in matrix:
                jobs.append(dict(suite="batch", repeat=repeat, outer=outer, inner=inner,
                                 games=args.games, plies=args.plies, depth=args.depth, job_timeout_s=180))
        else:
            for case in args.cases:
                for workers in (args.workers if args.suite == "search" else [1]):
                    for capacity in ([4096] if args.suite == "search" else args.capacities):
                        for age_weight in ([2] if args.suite == "search" else args.age_weights):
                            jobs.append(dict(
                                suite=args.suite, repeat=repeat, case=case, workers=workers,
                                depth=args.depth, quiescence_depth=args.quiescence_depth,
                                capacity=capacity, age_weight=age_weight, steps=args.steps,
                                timeout_ms=args.timeout_ms,
                                job_timeout_s=(args.steps + 1) * (args.timeout_ms / 1000 + 5) + 30,
                            ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for index, job in enumerate(jobs):
        job.update(evaluation=evaluation.to_dict(), profile=args.profile, reuse_position=args.reuse_position)
        job["sample_memory"] = not args.no_memory_sampling
        result = isolated(job)
        document["rows"].append(result)
        groups = {}
        for measured in document["rows"]:
            for row in measured.get("rows", []):
                key = (measured["case"], measured["workers"], measured["capacity"], row["step"], row["measurement"], measured["age_weight"])
                groups.setdefault(key, []).append(row)
        document["summary"] = [dict(case=key[0], workers=key[1], capacity=key[2], step=key[3],
            measurement=key[4], age_weight=key[5], samples=len(values), seconds_median=statistics.median(r["seconds"] for r in values),
            seconds_min=min(r["seconds"] for r in values), seconds_max=max(r["seconds"] for r in values),
            all_completed=all(r["completed_depth"] == args.depth and r["stop_reason"] is None for r in values))
            for key, values in groups.items()]
        args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{index + 1}/{len(jobs)}: {job['suite']} repeat {job['repeat']}", flush=True)


if __name__ == "__main__":
    main()
