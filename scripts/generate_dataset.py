"""Generate self-play dataset for future ML training."""

import argparse
import csv
import json
import os
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import TextIO

from engine.game import create_board, is_game_over, make_move
from engine.players import GreedyPlayer, RandomPlayer

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


def play_single_game(game_id: int, seed: int | None = None) -> list[dict[str, str | int]]:
    if game_id <= 0:
        raise ValueError("game_id must be greater than 0")

    board = create_board()
    rng = random.Random(game_id if seed is None else seed)

    if game_id % 2 == 1:
        white_player = RandomPlayer(rng=rng)
        black_player = GreedyPlayer(rng=rng)
    else:
        white_player = GreedyPlayer(rng=rng)
        black_player = RandomPlayer(rng=rng)

    white_player_label, black_player_label = _player_labels_for_game(game_id)

    game_rows: list[Row] = []
    ply = 0

    while not is_game_over(board):
        current_player = white_player if board.turn else black_player
        move = current_player.choose_move(board)
        ply += 1

        game_rows.append(
            {
                "game_id": game_id,
                "ply": ply,
                "fen": board.fen(),
                "side_to_move": "white" if board.turn else "black",
                "selected_move": move.uci(),
                "result": "",
                "white_player": white_player_label,
                "black_player": black_player_label,
            }
        )

        make_move(board, move)

    result = board.result()
    return [{**row, "result": result} for row in game_rows]


def worker_run_games(
    start_id: int,
    num_games: int,
    base_seed: int = BASE_WORKER_SEED,
) -> list[dict[str, str | int]]:
    if start_id <= 0:
        raise ValueError("start_id must be greater than 0")
    if num_games <= 0:
        raise ValueError("num_games must be greater than 0")

    process_seed = base_seed + os.getpid() + start_id
    worker_rng = random.Random(process_seed)

    rows: list[Row] = []
    for game_id in range(start_id, start_id + num_games):
        game_seed = worker_rng.randrange(0, 2**63)
        rows.extend(play_single_game(game_id, seed=game_seed))
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

    stats["draws"] += 1


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate self-play move dataset.")
    parser.add_argument("--games", type=int, default=20, help="Number of games to generate.")
    parser.add_argument(
        "--format",
        choices=["csv", "jsonl"],
        default="csv",
        help="Output dataset format.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="dataset.csv",
        help="Output file path. Default: dataset.csv or dataset.jsonl",
    )
    args = parser.parse_args()

    if args.games <= 0:
        raise ValueError("--games must be greater than 0")

    start_time = perf_counter()
    output_path = Path(args.output) if args.output else Path(f"dataset.{args.format}")
    max_workers = determine_max_workers(args.games)
    chunks = build_game_chunks(args.games, max_workers)
    stats = initialize_stats(args.games)
    moves_recorded = 0
    completed_games = 0
    next_start_id_to_write = 1
    pending_chunks: dict[int, tuple[int, list[Row]]] = {}
    row_buffer: list[Row] = []

    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        csv_writer = None
        if args.format == "csv":
            csv_writer = create_csv_writer(output_file)
        elif args.format != "jsonl":
            raise ValueError(f"Unsupported output format: {args.format}")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk = {
                executor.submit(worker_run_games, start_id, num_games): (
                    worker_index,
                    start_id,
                    num_games,
                )
                for worker_index, (start_id, num_games) in enumerate(chunks, start=1)
            }

            for future in as_completed(future_to_chunk):
                worker_index, start_id, num_games = future_to_chunk[future]
                pending_chunks[start_id] = (num_games, future.result())
                completed_games += num_games
                elapsed_seconds = perf_counter() - start_time
                end_id = start_id + num_games - 1
                print(
                    f"Worker {worker_index} completed games {start_id}-{end_id}. "
                    f"Completed games: {completed_games}/{args.games}. "
                    f"Elapsed: {elapsed_seconds:.2f} seconds"
                )

                while next_start_id_to_write in pending_chunks:
                    ready_num_games, ready_rows = pending_chunks.pop(next_start_id_to_write)
                    row_buffer.extend(ready_rows)
                    update_stats_for_chunk(
                        stats,
                        next_start_id_to_write,
                        ready_num_games,
                        ready_rows,
                    )
                    next_start_id_to_write += ready_num_games

                    while len(row_buffer) >= ROW_FLUSH_SIZE:
                        moves_recorded += flush_buffer(
                            output_file,
                            args.format,
                            row_buffer,
                            csv_writer,
                            ROW_FLUSH_SIZE,
                        )

        moves_recorded += flush_buffer(output_file, args.format, row_buffer, csv_writer)

    elapsed_seconds = perf_counter() - start_time

    print(f"Workers used: {max_workers}")
    print(f"Chunks scheduled: {len(chunks)}")
    print(f"Games generated: {stats['total_games']}")
    print(f"Moves recorded: {moves_recorded}")
    print(f"RandomPlayer wins: {stats['RandomPlayer_wins']}")
    print(f"GreedyPlayer wins: {stats['GreedyPlayer_wins']}")
    print(f"Draws: {stats['draws']}")
    print(f"Elapsed time: {elapsed_seconds:.2f} seconds")
    print(f"Dataset saved to: {output_path}")


if __name__ == "__main__":
    main()
