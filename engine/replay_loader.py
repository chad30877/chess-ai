"""Utilities for loading replay JSON files."""

import json
from pathlib import Path

import chess


def load_replay_json(path: str) -> dict:
    """Load and validate replay JSON data from disk."""
    replay_path = Path(path)
    if not replay_path.exists():
        raise FileNotFoundError(f"Replay file not found: {replay_path}")

    with replay_path.open("r", encoding="utf-8") as replay_file:
        data = json.load(replay_file)

    if not isinstance(data, dict):
        raise ValueError("Replay JSON must contain an object at the top level.")

    if "initial_fen" not in data:
        raise ValueError("Replay JSON must contain 'initial_fen'.")
    if not isinstance(data["initial_fen"], str):
        raise ValueError("'initial_fen' must be a string.")

    chess.Board(data["initial_fen"])

    if "moves_uci" not in data:
        raise ValueError("Replay JSON must contain 'moves_uci'.")
    if not isinstance(data["moves_uci"], list):
        raise ValueError("'moves_uci' must be a list.")
    if not all(isinstance(move, str) for move in data["moves_uci"]):
        raise ValueError("All 'moves_uci' entries must be strings.")

    result = data.get("result", "*")
    if not isinstance(result, str):
        raise ValueError("'result' must be a string.")

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("'metadata' must be an object.")

    return {
        "initial_fen": data["initial_fen"],
        "moves_uci": data["moves_uci"],
        "result": result,
        "metadata": metadata,
    }
