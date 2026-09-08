"""Generate self-play dataset for future ML training."""

import argparse
import csv
from contextlib import ExitStack
import json
import os
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import TextIO

import chess

from engine.game import create_board
from engine.batch_storage import BatchWriter
from engine.players import GreedyPlayer, RandomPlayer
from engine.self_play import PlayedGame, play_game
from engine.strategy_config import strategy_config

DATASET_FIELDNAMES = [
    "game_id",
    "ply",
    "fen",
    "side_to_move",
    "selected_move",
    "result",
    "white_player",
    "black_player",
]

WORKER_UTILIZATION = 1.0
BASE_WORKER_SEED = 10_000
ROW_FLUSH_SIZE = 10_000

Row = dict[str, str | int]

RANDOM_LABEL = "Random"
GREEDY_LABEL = "Greedy"


def _player_names_for_game(game_id: int) -> tuple[str, str]:
    if game_id % 2 == 1:
        return RandomPlayer.__name__, GreedyPlayer.__name__
    return GreedyPlayer.__name__, RandomPlayer.__name__


def _player_labels_for_game(game_id: int) -> tuple[str, str]:
    if game_id % 2 == 1:
        return RANDOM_LABEL, GREEDY_LABEL
    return GREEDY_LABEL, RANDOM_LABEL


def generate_game(
    game_id: int, seed: int | None = None, *, initial_fen: str = chess.STARTING_FEN,
    claim_draw: bool = False, max_plies: int | None = None,
) -> PlayedGame:
    rng = random.Random(game_id if seed is None else seed)

    if game_id % 2 == 1:
        white_player = RandomPlayer(rng=rng)
        black_player = GreedyPlayer(rng=rng)
    else:
        white_player = GreedyPlayer(rng=rng)
        black_player = RandomPlayer(rng=rng)

    white_player_label, black_player_label = _player_labels_for_game(game_id)

    return play_game(
        game_id, white_player, black_player, white_player_label, black_player_label,
        initial_fen=initial_fen, claim_draw=claim_draw, max_plies=max_plies,
    )


def play_single_game(game_id: int, seed: int | None = None) -> list[Row]:
    """Keep the original single-game, move-row interface."""
    return generate_game(game_id, seed).positions


def game_seed(base_seed: int, game_id: int) -> int:
    """Stable across processes, scheduling, and worker counts."""
    return base_seed + game_id


def worker_run_games(
    start_id: int,
    num_games: int,
    base_seed: int = BASE_WORKER_SEED,
) -> list[dict[str, str | int]]:
    if start_id <= 0:
        raise ValueError("start_id must be greater than 0")
    if num_games <= 0:
        raise ValueError("num_games must be greater than 0")

    rows: list[Row] = []
    for game_id in range(start_id, start_id + num_games):
        rows.extend(play_single_game(game_id, seed=game_seed(base_seed, game_id)))
    return rows


def determine_max_workers(total_games: int) -> int:
    if total_games <= 0:
        raise ValueError("total_games must be greater than 0")

    cpu_count = os.cpu_count() or 1
    max_workers = max(1, int(cpu_count * WORKER_UTILIZATION))
    return min(total_games, max_workers)


def build_game_chunks(total_games: int, max_workers: int) -> list[tuple[int, int]]:
    if total_games <= 0:
        raise ValueError("total_games must be greater than 0")
    if max_workers <= 0:
        raise ValueError("max_workers must be greater than 0")

    chunk_size = (total_games + max_workers - 1) // max_workers
    chunks: list[tuple[int, int]] = []
    start_id = 1
    remaining_games = total_games

    while remaining_games > 0:
        current_chunk_size = min(chunk_size, remaining_games)
        chunks.append((start_id, current_chunk_size))
        start_id += current_chunk_size
        remaining_games -= current_chunk_size

    return chunks


def write_csv(output_path: Path, rows: list[Row]) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=DATASET_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(output_path: Path, rows: list[Row]) -> None:
    with output_path.open("w", encoding="utf-8") as jsonl_file:
        for row in rows:
            jsonl_file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_rows(output_path: Path, output_format: str, rows: list[Row]) -> None:
    if output_format == "csv":
        write_csv(output_path, rows)
        return

    if output_format == "jsonl":
        write_jsonl(output_path, rows)
        return

    raise ValueError(f"Unsupported output format: {output_format}")


def initialize_stats(total_games: int) -> dict[str, int]:
    return {
        "total_games": total_games,
        f"{RandomPlayer.__name__}_wins": 0,
        f"{GreedyPlayer.__name__}_wins": 0,
        "draws": 0,
    }


def update_stats_for_game(stats: dict[str, int], game_id: int, result: str) -> None:
    white_name, black_name = _player_names_for_game(game_id)

    if result == "1-0":
        stats[f"{white_name}_wins"] += 1
        return

    if result == "0-1":
        stats[f"{black_name}_wins"] += 1
        return

    if result == "1/2-1/2":
        stats["draws"] += 1
    elif result == "*":
        stats["truncated"] = stats.get("truncated", 0) + 1
    else:
        raise ValueError(f"Unknown result: {result}")


def update_stats_for_chunk(
    stats: dict[str, int],
    start_id: int,
    num_games: int,
    rows: list[Row],
) -> None:
    game_results: dict[int, str] = {}
    for row in rows:
        game_id = int(row["game_id"])
        if game_id not in game_results:
            game_results[game_id] = str(row["result"])

    for game_id in range(start_id, start_id + num_games):
        update_stats_for_game(stats, game_id, game_results[game_id])


def create_csv_writer(output_file: TextIO) -> csv.DictWriter:
    writer = csv.DictWriter(output_file, fieldnames=DATASET_FIELDNAMES)
    writer.writeheader()
    return writer


def flush_buffer(
    output_file: TextIO,
    output_format: str,
    row_buffer: list[Row],
    csv_writer: csv.DictWriter | None = None,
    max_rows: int | None = None,
) -> int:
    if not row_buffer:
        return 0

    rows_to_write = len(row_buffer) if max_rows is None else min(len(row_buffer), max_rows)
    rows_to_flush = row_buffer[:rows_to_write]

    if output_format == "csv":
        if csv_writer is None:
            raise ValueError("csv_writer is required for CSV output")
        csv_writer.writerows(rows_to_flush)
    elif output_format == "jsonl":
        for row in rows_to_flush:
            output_file.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        raise ValueError(f"Unsupported output format: {output_format}")

    output_file.flush()
    del row_buffer[:rows_to_write]
    return rows_to_write


def _generate_job(job: tuple[int, int, str, bool, int | None]) -> tuple[PlayedGame, int]:
    game_id, seed, initial_fen, claim_draw, max_plies = job
    return generate_game(game_id, seed, initial_fen=initial_fen,
                         claim_draw=claim_draw, max_plies=max_plies), seed


def generation_settings(
    *, games: int, seed: int, workers: int, initial_fen: str,
    claim_draw: bool, max_plies: int | None,
) -> dict:
    settings = {
        "num_games": games, "initial_fen": initial_fen,
        "rules": {"claim_draw": claim_draw}, "workers": workers,
        "color_assignment": "alternate",
        "strategies": {"a": strategy_config("Random"), "b": strategy_config("Greedy")},
    }
    if max_plies is not None:
        settings["max_plies"] = max_plies
    return settings


def generate_batch(
    *, games: int = 20, batch_root: Path = Path("data/batches"),
    name: str | None = None, tags: list[str] | None = None,
    output_format: str = "csv", output_path: Path | None = None,
    seed: int = BASE_WORKER_SEED, workers: int | None = None,
    initial_fen: str = chess.STARTING_FEN, claim_draw: bool = False,
    max_plies: int | None = None,
) -> Path:
    """Always save an independent batch; optionally export the legacy row schema."""
    if games <= 0:
        raise ValueError("games must be greater than 0")
    if workers is not None and workers <= 0:
        raise ValueError("workers must be greater than 0")
    if max_plies is not None and max_plies < 0:
        raise ValueError("max_plies must be non-negative")
    if output_format not in ("csv", "jsonl"):
        raise ValueError("output_format must be csv or jsonl")
    board = create_board(initial_fen)
    if not board.is_valid():
        raise ValueError("initial_fen must be a valid standard chess position")
    initial_fen = board.fen()
    workers = min(games, workers) if workers is not None else determine_max_workers(games)
    # An explicitly requested single-file export also refuses to overwrite old data.
    # Reserve it before creating a batch, so an existing path fails without side effects.
    with ExitStack() as resources:
        export_file = None
        export_writer = None
        if output_path is not None:
            export_file = resources.enter_context(output_path.open("x", newline="", encoding="utf-8"))
            if output_format == "csv":
                export_writer = create_csv_writer(export_file)
        settings = generation_settings(games=games, seed=seed, workers=workers,
                                       initial_fen=initial_fen, claim_draw=claim_draw,
                                       max_plies=max_plies)
        with BatchWriter(Path(batch_root), name=name, tags=tags or [], settings=settings,
                         output_format=output_format) as batch:
            stats = initialize_stats(games)
            print(f"Batch directory: {batch.path}", flush=True)
            jobs = ((i, game_seed(seed, i), initial_fen, claim_draw, max_plies)
                    for i in range(1, games + 1))
            # Ordered map keeps files deterministic even when workers finish out of order.
            with ExitStack() as worker_resources:
                if workers == 1:
                    results = map(_generate_job, jobs)
                else:
                    executor = worker_resources.enter_context(ProcessPoolExecutor(max_workers=workers))
                    results = executor.map(_generate_job, jobs)
                for game, actual_seed in results:
                    batch.add_game(game, actual_seed)
                    update_stats_for_game(stats, game.game_id, game.result)
                    if export_file is not None:
                        flush_buffer(export_file, output_format, list(game.positions), export_writer)
                    print(f"Game {game.game_id}/{games}: {game.result} ({game.termination}), "
                          f"{len(game.positions)} plies", flush=True)
        print(f"Batch counts: {batch.manifest['counts']}")
        print(f"Results: {stats}")
        return batch.path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a self-play batch and optional single-file dataset.")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    parser.add_argument("--output", type=Path, help="Also export legacy rows to a NEW CSV/JSONL file.")
    parser.add_argument("--batch-root", type=Path, default=Path("data/batches"))
    parser.add_argument("--batch-name", help="Human-readable batch name; need not be unique.")
    parser.add_argument("--tag", action="append", default=[], help="Classification tag; repeat for multiple tags.")
    parser.add_argument("--seed", type=int, default=BASE_WORKER_SEED)
    parser.add_argument("--workers", type=int, help="Worker processes; default: min(games, CPU count).")
    parser.add_argument("--initial-fen", default=chess.STARTING_FEN)
    parser.add_argument("--claim-draw", action="store_true", help="Automatically claim available draws.")
    parser.add_argument("--max-plies", type=int, help="Execution limit in half-moves; 0 saves initial position only.")
    args = parser.parse_args()
    started = perf_counter()
    path = generate_batch(games=args.games, batch_root=args.batch_root, name=args.batch_name,
                          tags=args.tag, output_format=args.format, output_path=args.output,
                          seed=args.seed, workers=args.workers, initial_fen=args.initial_fen,
                          claim_draw=args.claim_draw, max_plies=args.max_plies)
    print(f"Batch saved to: {path}")
    print(f"Elapsed time: {perf_counter() - started:.2f} seconds")


if __name__ == "__main__":
    main()
