"""Batch identifiers, reproducibility, failure handling and legacy input compatibility."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess

from apps.play_ui import create_session, prepare_replay_content
from engine.batch_storage import BatchWriter
from engine.replay_loader import load_replay_json
from scripts.export_replay_json import build_replay_payload, load_game_rows
from scripts.generate_dataset import (
    DATASET_FIELDNAMES, game_seed, generate_batch, generate_game, generation_settings,
    update_stats_for_game, initialize_stats,
)
from training.train_value_model import build_xy, load_rows


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class BatchGenerationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def generate(self, **kwargs):
        options = dict(games=2, batch_root=self.root / "batches", workers=1,
                       name="驗證批次", tags=["smoke", "棋規", "smoke"], seed=42, max_plies=6)
        options.update(kwargs)
        return generate_batch(**options)

    def verify_batch(self, path):
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        games = read_csv(path / manifest["files"]["games"])
        positions_path = path / manifest["files"]["positions"]
        if positions_path.suffix == ".csv":
            positions = read_csv(positions_path)
        else:
            positions = [json.loads(line) for line in positions_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["counts"]["saved_games"], len(games))
        self.assertEqual(manifest["counts"]["requested_games"], len(games))
        self.assertEqual(manifest["counts"]["positions"], len(positions))
        self.assertEqual(sum(int(g["move_count"]) for g in games), len(positions))
        self.assertEqual(len(list((path / "replays").glob("*.json"))), len(games))
        self.assertEqual([int(g["game_number"]) for g in games], list(range(1, len(games) + 1)))
        settings = manifest["settings"]
        for game in games:
            game_id = game["game_id"]
            selected = [row for row in positions if str(row["game_id"]) == game_id]
            replay_path = path / game["replay_path"]
            self.assertTrue(replay_path.resolve().is_relative_to(path.resolve()))
            replay, move_items, info = prepare_replay_content(str(replay_path))
            session, count = create_session(replay)
            self.assertEqual(count, int(game["move_count"]))
            self.assertEqual(len(move_items), count)
            self.assertEqual(replay["metadata"]["batch_id"], manifest["batch_id"])
            self.assertEqual(replay["metadata"]["game_id"], game_id)
            self.assertEqual(info["result"], game["result"])
            for ply, row in enumerate(selected, 1):
                session.goto_ply(ply - 1)
                self.assertEqual(int(row["ply"]), ply)
                self.assertEqual(row["fen"], session.current_fen())
                self.assertEqual(row["batch_id"], manifest["batch_id"])
                for field in ("result", "status", "termination", "white_player", "black_player"):
                    self.assertEqual(row[field], game[field])
            session.last()
            self.assertEqual(session.current_result(), game["result"])
            regenerated = generate_game(int(game["game_number"]), int(game["seed"]), initial_fen=settings["initial_fen"],
                                        claim_draw=settings["rules"]["claim_draw"], max_plies=settings.get("max_plies"))
            self.assertEqual([r["selected_move"] for r in regenerated.positions], replay["moves_uci"])
            self.assertEqual(regenerated.result, replay["result"])
            self.assertEqual(regenerated.final_fen, session.current_fen())
            self.assertRegex(game_id, r"^\d{8}_\d{6}$")
            self.assertEqual(replay_path.stem, game_id)
            self.assertEqual(replay["metadata"]["started_at"], game["started_at"])
            self.assertNotIn("seed", replay["metadata"])
            self.assertNotIn("seed", positions[0] if positions else {})
            self.assertNotIn("final_fen", game)
            self.assertNotIn("replay_path", replay["metadata"])
        for result, count in manifest["results"].items():
            self.assertEqual(count, sum(g["result"] == result for g in games))
        return manifest, games, positions

    def test_csv_batch_roundtrip_unique_paths_and_legacy_export(self):
        output = self.root / "legacy.csv"
        path = self.generate(output_path=output)
        manifest, games, positions = self.verify_batch(path)
        self.assertEqual(manifest["name"], "驗證批次")
        self.assertEqual(manifest["tags"], ["smoke", "棋規"])
        self.assertEqual(manifest["counts"]["truncated_games"], 2)
        self.assertEqual(manifest["counts"]["completed_games"], 0)
        self.assertEqual(games[0]["white_player"], "Random")
        self.assertEqual(games[1]["white_player"], "Greedy")
        legacy = read_csv(output)
        self.assertEqual(list(legacy[0]), DATASET_FIELDNAMES)
        ordinals = {g["game_id"]: g["game_number"] for g in games}
        self.assertEqual(legacy, [{**{key: row[key] for key in DATASET_FIELDNAMES},
                                   "game_id": ordinals[row["game_id"]]} for row in positions])
        before = (path / "manifest.json").read_bytes()
        second = self.generate()
        self.assertNotEqual(path, second)
        self.assertEqual((path / "manifest.json").read_bytes(), before)
        with self.assertRaises(FileExistsError):
            self.generate(output_path=output)
        self.assertEqual(read_csv(output), legacy)

    def test_jsonl_and_process_count_reproducibility(self):
        sequential = self.generate(output_format="jsonl", workers=1)
        parallel = self.generate(output_format="jsonl", workers=2)
        _, _, first = self.verify_batch(sequential)
        _, _, second = self.verify_batch(parallel)
        without_batch = lambda rows: [{k: v for k, v in row.items() if k not in ("batch_id", "game_id")} for row in rows]
        self.assertEqual(without_batch(first), without_batch(second))

    def test_zero_ply_completed_and_truncated_games_have_replays(self):
        for fen, status in [(chess.STARTING_FEN, "truncated"),
                            ("7k/8/8/8/8/8/8/K7 w - - 0 1", "completed")]:
            with self.subTest(status=status):
                path = self.generate(initial_fen=fen, max_plies=0)
                manifest, games, positions = self.verify_batch(path)
                self.assertEqual(manifest["counts"][f"{status}_games"], 2)
                self.assertEqual(positions, [])

    def test_natural_games_and_claim_policy_roundtrip(self):
        path = self.generate(max_plies=None, claim_draw=True)
        manifest, games, _ = self.verify_batch(path)
        self.assertEqual(manifest["counts"]["completed_games"], 2)
        self.assertTrue(all(g["result"] != "*" for g in games))

    def test_csv_exporter_preserves_batch_policy_and_old_format(self):
        path = self.generate(claim_draw=True)
        game_id = read_csv(path / "games.csv")[0]["game_id"]
        rows = load_game_rows(path / "positions.csv", game_id)
        replay = build_replay_payload(rows, 1)
        self.assertTrue(replay["metadata"]["rules"]["claim_draw"])
        self.assertEqual(replay["metadata"]["status"], "truncated")
        legacy = [{key: row[key] for key in DATASET_FIELDNAMES} for row in rows]
        old_replay = build_replay_payload(legacy, 1)
        self.assertEqual(old_replay["moves_uci"], replay["moves_uci"])
        self.assertNotIn("rules", old_replay["metadata"])

    def test_worker_failure_preserves_committed_games_and_marks_failed(self):
        real = generate_game
        def fail_second(game_id, *args, **kwargs):
            if game_id == 2:
                raise RuntimeError("test worker failure")
            return real(game_id, *args, **kwargs)
        with patch("scripts.generate_dataset.generate_game", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "test worker failure"):
                self.generate()
        path = next((self.root / "batches").iterdir())
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["counts"]["saved_games"], 1)
        self.assertEqual(len(read_csv(path / "games.csv")), 1)
        self.assertEqual(len(read_csv(path / "positions.csv")), manifest["counts"]["positions"])
        self.assertEqual(len(list((path / "replays").glob("*.json"))), 1)

    def test_failed_manifest_commit_rolls_back_only_current_game(self):
        settings = generation_settings(games=2, seed=42, workers=1, initial_fen=chess.STARTING_FEN,
                                       claim_draw=False, max_plies=2)
        batch = BatchWriter(self.root / "batches", name="failure", tags=[], settings=settings)
        with self.assertRaisesRegex(OSError, "test write failure"):
            with batch:
                batch.add_game(generate_game(1, 43, max_plies=2), 43)
                with patch.object(batch, "_save_manifest", side_effect=OSError("test write failure")):
                    batch.add_game(generate_game(2, 44, max_plies=2), 44)
        manifest = json.loads((batch.path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["counts"]["saved_games"], 1)
        self.assertEqual(len(read_csv(batch.path / "games.csv")), 1)
        self.assertEqual(len(read_csv(batch.path / "positions.csv")), 2)
        self.assertEqual(len(list((batch.path / "replays").glob("*.json"))), 1)

    def test_training_skips_unfinished_rows_for_both_formats(self):
        for suffix in ("csv", "jsonl"):
            path = self.root / f"training.{suffix}"
            rows = [{"fen": chess.STARTING_FEN, "result": result}
                    for result in ("1-0", "*", "1/2-1/2", "0-1")]
            if suffix == "csv":
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["fen", "result"])
                    writer.writeheader()
                    writer.writerows(rows)
            else:
                path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            x, y = build_xy(load_rows(path))
            self.assertEqual(x.shape, (3, 774))
            self.assertEqual(y.tolist(), [1, 0, -1])
        batch = self.generate()
        with self.assertRaisesRegex(ValueError, "no completed positions"):
            load_rows(batch / "positions.csv")

    def test_validation_happens_before_batch_creation(self):
        for kwargs in (dict(games=0), dict(workers=0), dict(max_plies=-1),
                       dict(initial_fen="invalid"), dict(output_format="xml")):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.generate(**kwargs)
        self.assertFalse((self.root / "batches").exists())

    def test_statistics_do_not_count_truncation_as_draw(self):
        stats = initialize_stats(1)
        update_stats_for_game(stats, 1, "*")
        self.assertEqual(stats["draws"], 0)
        self.assertEqual(stats["truncated"], 1)

    def test_loader_rejects_string_draw_policy_and_accepts_old_replay(self):
        old = load_replay_json("data/replays/sample_replay.json")
        session, _ = create_session(old)
        self.assertFalse(session.claim_draw)
        old["metadata"]["rules"] = {"claim_draw": "false"}
        path = self.root / "bad.json"
        path.write_text(json.dumps(old), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "boolean"):
            load_replay_json(str(path))


if __name__ == "__main__":
    unittest.main()
