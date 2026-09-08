"""Versioned batch artifacts. Each published manifest counts committed games only."""

import csv
import json
from contextlib import ExitStack
from pathlib import Path
from engine.storage.data_ids import allocate_id, now_iso

from engine.sessions.self_play import PlayedGame

POSITION_FIELDS = [
    "game_id", "ply", "fen", "side_to_move", "selected_move", "result",
    "white_player", "black_player", "batch_id", "status", "termination",
    "claim_draw",
]
GAME_FIELDS = [
    "game_id", "game_number", "started_at", "finished_at", "white_player", "black_player",
    "seed", "result", "move_count", "status", "termination", "replay_path",
]


def write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(path)


class BatchWriter:
    def __init__(
        self, root: Path, *, name: str | None, tags: list[str], settings: dict,
        output_format: str = "csv",
    ) -> None:
        if output_format not in ("csv", "jsonl"):
            raise ValueError("output_format must be csv or jsonl")
        created_at = now_iso()
        self.data_root = root.parent
        self.batch_id = allocate_id(self.data_root, "batch", created_at)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / self.batch_id
        self.path.mkdir(exist_ok=False)
        self.output_format = output_format
        settings = settings.copy()
        requested_games = settings.pop("num_games")
        self.manifest = {
            "schema_version": 2, "batch_id": self.batch_id,
            "created_at": created_at, "updated_at": created_at, "status": "generating",
            "settings": settings,
            "files": {"games": "games.csv", "positions": f"positions.{output_format}"},
            "counts": {"requested_games": requested_games, "saved_games": 0,
                       "completed_games": 0, "truncated_games": 0, "positions": 0},
            "results": {"1-0": 0, "0-1": 0, "1/2-1/2": 0, "*": 0},
        }
        if name:
            self.manifest["name"] = name
        if tags:
            self.manifest["tags"] = list(dict.fromkeys(tags))
        self._streams = ExitStack()
        self._save_manifest()

    def _save_manifest(self) -> None:
        self.manifest["updated_at"] = now_iso()
        write_json_atomic(self.path / "manifest.json", self.manifest)

    def __enter__(self):
        try:
            (self.path / "replays").mkdir()
            self.games_file = self._streams.enter_context(
                (self.path / "games.csv").open("x", newline="", encoding="utf-8"))
            self.positions_file = self._streams.enter_context(
                (self.path / self.manifest["files"]["positions"]).open(
                    "x", newline="", encoding="utf-8"))
            self.games_writer = csv.DictWriter(self.games_file, fieldnames=GAME_FIELDS)
            self.games_writer.writeheader()
            self.positions_writer = csv.DictWriter(self.positions_file, fieldnames=POSITION_FIELDS)
            if self.output_format == "csv":
                self.positions_writer.writeheader()
            self.games_file.flush()
            self.positions_file.flush()
            return self
        except BaseException as exc:
            self.__exit__(type(exc), exc, exc.__traceback__)
            raise

    def add_game(self, game: PlayedGame, seed: int) -> None:
        expected_id = self.manifest["counts"]["saved_games"] + 1
        if game.game_id != expected_id or expected_id > self.manifest["counts"]["requested_games"]:
            raise ValueError(f"Expected game_id {expected_id} within requested game count")
        rules = self.manifest["settings"]["rules"]
        started_at = game.started_at or now_iso()
        game_id = allocate_id(self.data_root, "game", started_at)
        relative_replay = f"replays/{game_id}.json"
        summary = {
            "game_id": game_id, "game_number": game.game_id,
            "started_at": started_at, "finished_at": game.finished_at or now_iso(),
            "white_player": game.white_player, "black_player": game.black_player,
            "seed": seed, "result": game.result, "move_count": len(game.positions),
            "status": game.status, "termination": game.termination, "replay_path": relative_replay,
        }
        replay = {
            "schema_version": 2, "initial_fen": game.initial_fen,
            "moves_uci": [row["selected_move"] for row in game.positions], "result": game.result,
            "metadata": {key: summary[key] for key in (
                "game_id", "started_at", "finished_at", "white_player", "black_player", "status", "termination")},
        }
        replay["metadata"].update(batch_id=self.batch_id, rules=rules)
        # If a recoverable write fails, roll back this game's rows and replay.
        offsets = self.games_file.tell(), self.positions_file.tell()
        old_counts = self.manifest["counts"].copy()
        old_results = self.manifest["results"].copy()
        replay_path = self.path / relative_replay
        replay_created = False
        try:
            with replay_path.open("x", encoding="utf-8") as stream:
                replay_created = True
                json.dump(replay, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            for row in game.positions:
                position = {**row, "game_id": game_id, "batch_id": self.batch_id, "status": game.status,
                            "termination": game.termination,
                            "claim_draw": rules["claim_draw"]}
                if self.output_format == "csv":
                    self.positions_writer.writerow(position)
                else:
                    self.positions_file.write(json.dumps(position, ensure_ascii=False) + "\n")
            self.games_writer.writerow(summary)
            self.positions_file.flush()
            self.games_file.flush()
            counts = self.manifest["counts"]
            counts["saved_games"] += 1
            counts[f"{game.status}_games"] += 1
            counts["positions"] += len(game.positions)
            self.manifest["results"][game.result] += 1
            self._save_manifest()
        except BaseException:
            self.manifest["counts"] = old_counts
            self.manifest["results"] = old_results
            for stream, offset in zip((self.games_file, self.positions_file), offsets):
                stream.seek(offset)
                stream.truncate()
                stream.flush()
            if replay_created:
                replay_path.unlink(missing_ok=True)
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._streams.close()
        complete = self.manifest["counts"]["saved_games"] == self.manifest["counts"]["requested_games"]
        stopped = self.manifest["status"] == "stopped"
        self.manifest["status"] = "failed" if exc else "stopped" if stopped else "completed" if complete else "failed"
        self.manifest["finished_at"] = now_iso()
        if exc is not None:
            self.manifest["error"] = f"{type(exc).__name__}: {exc}"
        elif not complete and not stopped:
            self.manifest["error"] = "Generation stopped before all games were saved"
        self._save_manifest()
