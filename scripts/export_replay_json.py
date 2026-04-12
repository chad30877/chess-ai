"""Export a single game from dataset CSV into replay JSON format."""

import argparse
import csv
import json
from pathlib import Path


def load_game_rows(dataset_path: Path, game_id: int) -> list[dict[str, str]]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with dataset_path.open("r", encoding="utf-8", newline="") as dataset_file:
        reader = csv.DictReader(dataset_file)
        rows = [row for row in reader if int(row["game_id"]) == game_id]

    if not rows:
        raise ValueError(f"Game id {game_id} not found in dataset.")

    rows.sort(key=lambda row: int(row["ply"]))
    return rows


def build_replay_payload(game_rows: list[dict[str, str]], game_id: int) -> dict:
    if not game_rows:
        raise ValueError("game_rows must not be empty.")

    initial_fen = game_rows[0]["fen"]
    moves_uci: list[str] = []
    saw_empty_selected_move = False

    for row in game_rows:
        selected_move = (row.get("selected_move") or "").strip()
        if selected_move:
            if saw_empty_selected_move:
                raise ValueError(
                    f"Game id {game_id} contains non-empty selected_move after an empty one."
                )
            moves_uci.append(selected_move)
        else:
            saw_empty_selected_move = True

    if not moves_uci:
        raise ValueError(f"Game id {game_id} has no moves to export.")

    result = game_rows[-1].get("result") or game_rows[0].get("result") or "*"

    metadata: dict[str, str | int] = {"game_id": game_id}
    white_player = game_rows[-1].get("white_player") or game_rows[0].get("white_player")
    black_player = game_rows[-1].get("black_player") or game_rows[0].get("black_player")

    if white_player:
        metadata["white_player"] = white_player
    if black_player:
        metadata["black_player"] = black_player

    return {
        "initial_fen": initial_fen,
        "moves_uci": moves_uci,
        "result": result,
        "metadata": metadata,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export one dataset game to replay JSON.")
    parser.add_argument("--dataset", type=str, required=True, help="Path to dataset CSV file.")
    parser.add_argument("--game-id", type=int, required=True, help="Game id to export.")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional output JSON path. Defaults to data/replays/game_<id>.json",
    )
    args = parser.parse_args()

    if args.game_id <= 0:
        raise ValueError("--game-id must be greater than 0")

    dataset_path = Path(args.dataset)
    output_path = (
        Path(args.output)
        if args.output is not None
        else Path("data/replays") / f"game_{args.game_id}.json"
    )

    game_rows = load_game_rows(dataset_path, args.game_id)
    payload = build_replay_payload(game_rows, args.game_id)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, indent=2)

    print(f"Replay exported to: {output_path}")
    print(f"Game id: {args.game_id}")
    print(f"Moves exported: {len(payload['moves_uci'])}")


if __name__ == "__main__":
    main()
