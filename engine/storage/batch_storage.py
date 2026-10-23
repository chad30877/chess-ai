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

    @classmethod
    def reopen(cls, path):
        writer = cls.__new__(cls)
        writer.path = Path(path)
        writer.data_root = writer.path.parent.parent
        writer.manifest = json.loads((writer.path / "manifest.json").read_text(encoding="utf-8"))
        writer.batch_id = writer.manifest["batch_id"]
        writer.output_format = "jsonl" if writer.manifest["files"]["positions"].endswith("jsonl") else "csv"
        writer._streams = ExitStack()
        writer._reopening = True
        writer.manifest["status"] = "generating"
        writer.manifest.pop("error", None)
        return writer

    def recover_committed_games(self):
        """由已提交棋譜重建索引，並回傳依發布順序排列的棋譜。"""
        replays = []
        for path in (self.path/'replays').glob('*.json'):
            replay = json.loads(path.read_text(encoding='utf-8'))
            metadata = replay['metadata']
            if 'summary' not in metadata:
                raise ValueError('棋譜缺少可恢復的提交資料')
            replays.append((metadata['summary']['game_number'], replay))
        replays.sort(key=lambda item: item[0])
        summaries = [replay['metadata']['summary'] for _, replay in replays]
        with (self.path/'games.csv').open('w', newline='', encoding='utf-8') as stream:
            rows = csv.DictWriter(stream, fieldnames=GAME_FIELDS)
            rows.writeheader()
            rows.writerows(summaries)
        import chess
        with (self.path/self.manifest['files']['positions']).open('w', newline='', encoding='utf-8') as stream:
            rows = csv.DictWriter(stream, fieldnames=POSITION_FIELDS)
            if self.output_format == 'csv':
                rows.writeheader()
            for _, replay in replays:
                metadata = replay['metadata']
                summary = metadata['summary']
                board = chess.Board(replay['initial_fen'])
                for ply, move in enumerate(replay['moves_uci'], 1):
                    position = dict(game_id=metadata['game_id'], ply=ply, fen=board.fen(),
                        side_to_move='white' if board.turn else 'black', selected_move=move,
                        result=summary['result'], white_player=summary['white_player'], black_player=summary['black_player'],
                        batch_id=self.batch_id, status=summary['status'], termination=summary['termination'],
                        claim_draw=self.manifest['settings']['rules']['claim_draw'])
                    if self.output_format == 'csv':
                        rows.writerow(position)
                    else:
                        stream.write(json.dumps(position, ensure_ascii=False)+'\n')
                    board.push_uci(move)
        counts = self.manifest['counts']
        counts.update(saved_games=len(summaries), completed_games=sum(s['status']=='completed' for s in summaries),
                      truncated_games=sum(s['status']=='truncated' for s in summaries), positions=sum(s['move_count'] for s in summaries))
        self.manifest['results'] = {result: sum(s['result']==result for s in summaries) for result in ('1-0','0-1','1/2-1/2','*')}
        self._save_manifest()
        return replays

    def set_work_complete(self, complete):
        """設定邏輯工作是否已全數完成，歷史中斷嘗試不增加工作數。"""
        self._logical_complete = bool(complete)

    def _save_manifest(self) -> None:
        self.manifest["updated_at"] = now_iso()
        write_json_atomic(self.path / "manifest.json", self.manifest)

    def add_json_artifact(self, key: str, filename: str, payload: dict) -> None:
        """Publish one named JSON artifact through the manifest."""

        if not isinstance(filename, str):
            raise ValueError("Artifact filename must be a string")
        relative_path = Path(filename)
        if not key or key in self.manifest["files"]:
            raise ValueError(f"Invalid or duplicate artifact key: {key}")
        if (
            relative_path.is_absolute()
            or len(relative_path.parts) != 1
            or relative_path.name in ("", ".", "..")
        ):
            raise ValueError("Artifact filename must stay directly inside the batch")
        artifact_path = self.path / relative_path
        if artifact_path.exists():
            raise FileExistsError(artifact_path)
        try:
            write_json_atomic(artifact_path, payload)
            self.manifest["files"][key] = filename
            self._save_manifest()
        except BaseException:
            self.manifest["files"].pop(key, None)
            artifact_path.unlink(missing_ok=True)
            raise

    def __enter__(self):
        try:
            if getattr(self, "_reopening", False):
                self.games_file = self._streams.enter_context((self.path / "games.csv").open("a", newline="", encoding="utf-8"))
                self.positions_file = self._streams.enter_context((self.path / self.manifest["files"]["positions"]).open("a", newline="", encoding="utf-8"))
                self.games_writer = csv.DictWriter(self.games_file, fieldnames=GAME_FIELDS)
                self.positions_writer = csv.DictWriter(self.positions_file, fieldnames=POSITION_FIELDS)
                return self
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

    def add_game(self, game: PlayedGame, seed: int, *, execution: dict | None = None) -> str:
        expected_id = self.manifest["counts"]["saved_games"] + 1
        if game.game_id != expected_id or expected_id > self.manifest["counts"]["requested_games"] and "experiment" not in self.manifest["settings"]:
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
        replay["metadata"].update(batch_id=self.batch_id, rules=rules, summary=summary)
        if execution is not None:
            # 發布序號連續；固定工作編號獨立於並行完成順序。
            replay["metadata"]["execution"] = execution
        # If a recoverable write fails, roll back this game's rows and replay.
        offsets = self.games_file.tell(), self.positions_file.tell()
        old_counts = self.manifest["counts"].copy()
        old_results = self.manifest["results"].copy()
        replay_path = self.path / relative_replay
        replay_created = False
        try:
            replay_created = True
            write_json_atomic(replay_path, replay)
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
            return game_id
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
        complete = getattr(self, "_logical_complete", self.manifest["counts"]["saved_games"] == self.manifest["counts"]["requested_games"])
        stopped = self.manifest["status"] == "stopped"
        self.manifest["status"] = "failed" if exc else "stopped" if stopped else "completed" if complete else "failed"
        self.manifest["finished_at"] = now_iso()
        if exc is not None:
            self.manifest["error"] = f"{type(exc).__name__}: {exc}"
        elif not complete and not stopped:
            self.manifest["error"] = "Generation stopped before all games were saved"
        self._save_manifest()
