"""Behavior across batch workers, compact artifacts, IDs and the replay index."""

import csv
import json
import random
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch

import chess

from apps.play_ui import create_session
from engine.sessions.batch_run import BatchRun, BatchSettings
from engine.storage.batch_storage import BatchWriter
from engine.storage.data_ids import allocate_id, date_key
from engine.players import GreedyPlayer, RandomPlayer
from engine.replay.replay_catalog import ReplayCatalog, result_badges
from engine.replay.replay_loader import load_replay_json
from engine.sessions.self_play import play_game
from scripts.generate_dataset import generate_game, generation_settings


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


class BatchUIStorageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_serial_numbers_are_concurrent_persistent_and_shared_across_locations(self):
        timestamp = "2026-09-09T01:02:03+08:00"
        replay = self.root / "batches/existing/replays/20260909_000042.json"
        replay.parent.mkdir(parents=True)
        replay.write_text("{}", encoding="utf-8")
        with ThreadPoolExecutor(max_workers=8) as executor:
            ids = list(executor.map(lambda _: allocate_id(self.root, "game", timestamp), range(24)))
        self.assertEqual(len(set(ids)), 24)
        self.assertEqual(sorted(ids)[0], "20260909_000043")
        self.assertEqual(allocate_id(self.root, "game", timestamp), "20260909_000067")
        self.assertEqual(allocate_id(self.root, "batch", timestamp), "20260909_0001")
        self.assertEqual(allocate_id(self.root, "game", "2026-09-09T16:00:00Z"), "20260910_000001")

    def test_completed_ui_batch_has_fixed_colors_and_seed_reproduction(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            run = BatchRun(BatchSettings(white="Greedy", black="Random", games=2, max_plies=8),
                           self.root / "batches", executor)
            run.future.result(timeout=10)
        state = run.snapshot()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["saved_games"], 2)
        batch = self.root / "batches" / state["batch_id"]
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["counts"]["positions"], 16)
        self.assertEqual(manifest["settings"]["color_assignment"], "fixed")
        forbidden = {"source_sha256", "pst_sha256", "pst_source", "runtime", "rng", "seed_derivation",
                     "legacy_export", "class", "label", "final_fen", "num_games"}
        def check(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for v in value.values():
                    check(v)
            elif isinstance(value, list):
                for v in value:
                    check(v)
            else:
                self.assertIsNotNone(value)
        check(manifest)
        for key in ("name", "tags", "error"):
            self.assertNotIn(key, manifest)
        for row in rows(batch / "games.csv"):
            self.assertEqual((row["white_player"], row["black_player"]), ("Greedy", "Random"))
            rng = random.Random(int(row["seed"]))
            game = play_game(int(row["game_number"]), GreedyPlayer(rng=rng), RandomPlayer(rng=rng),
                             "Greedy", "Random", max_plies=8)
            data = load_replay_json(str(batch / row["replay_path"]))
            self.assertEqual(data["moves_uci"], [r["selected_move"] for r in game.positions])
            session, _ = create_session(data)
            session.last()
            self.assertEqual(session.current_fen(), game.final_fen)
            self.assertEqual(session.current_result(), row["result"])
            self.assertNotIn("seed", data["metadata"])
            self.assertNotEqual(date_key(row["started_at"]), "日期不詳")
        self.assertTrue(all("seed" not in row for row in rows(batch / "positions.csv")))
        catalog = ReplayCatalog(self.root)
        self.assertEqual(len(catalog.entries), 2)
        self.assertEqual({e.group for e in catalog.entries}, {state["batch_id"]})

    def test_two_processes_share_the_same_daily_sequence(self):
        with ProcessPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(allocate_id, [self.root] * 8, ["game"] * 8,
                                    ["2026-09-09T01:00:00+08:00"] * 8))
        self.assertEqual(sorted(ids), [f"20260909_{i:06d}" for i in range(1, 9)])

    def test_pause_then_stop_during_choice_preserves_only_applied_moves(self):
        choosing, release = Event(), Event()
        class ControlledPlayer:
            calls = 0
            def __init__(self, **kwargs):
                pass
            def choose_move(self, board):
                ControlledPlayer.calls += 1
                if ControlledPlayer.calls == 2:
                    choosing.set()
                    if not release.wait(5):
                        raise RuntimeError("test synchronization timeout")
                return next(iter(board.legal_moves))
        with patch("engine.sessions.batch_run.RandomPlayer", ControlledPlayer), ThreadPoolExecutor(max_workers=1) as executor:
            run = BatchRun(BatchSettings(white="Random", black="Random", games=2, max_plies=4),
                           self.root / "batches", executor)
            try:
                self.assertTrue(choosing.wait(5))
                run.pause()
                release.set()
                with self.assertRaises(TimeoutError):
                    run.future.result(timeout=0.05)
                self.assertEqual(run.snapshot()["status"], "paused")
            finally:
                release.set()
                run.stop()
            run.future.result(timeout=5)
        self.assertEqual(run.snapshot()["status"], "stopped")
        batch = self.root / "batches" / run.snapshot()["batch_id"]
        game = rows(batch / "games.csv")[0]
        self.assertEqual((game["move_count"], game["result"], game["termination"]), ("1", "*", "user_stop"))
        data = load_replay_json(str(batch / game["replay_path"]))
        session, _ = create_session(data)
        session.last()
        self.assertEqual(len(session.current_board().move_stack), 1)
        self.assertEqual(session.current_result(), "*")
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["saved_games"], 1)
        self.assertNotIn("error", manifest)

    def test_interval_stop_keeps_finished_game_and_does_not_start_another(self):
        saved = Event()
        original = BatchRun._interval
        def interval(run):
            saved.set()
            return original(run)
        with patch.object(BatchRun, "_interval", interval), ThreadPoolExecutor(max_workers=1) as executor:
            run = BatchRun(BatchSettings(games=3, interval=60, initial_fen="7k/8/8/8/8/8/8/K7 w - - 0 1"),
                           self.root / "batches", executor)
            try:
                self.assertTrue(saved.wait(5))
                self.assertEqual(run.snapshot()["saved_games"], 1)
                run.pause()
                run.resume()
            finally:
                run.stop()
            run.future.result(timeout=5)
        batch = self.root / "batches" / run.snapshot()["batch_id"]
        games = rows(batch / "games.csv")
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["result"], "1/2-1/2")

    def test_worker_failure_preserves_earlier_game_and_records_error_only_on_failure(self):
        original = play_game
        def fail_second(number, *args, **kwargs):
            if number == 2:
                raise RuntimeError("controlled AI error")
            return original(number, *args, **kwargs)
        with patch("engine.sessions.batch_run.play_game", fail_second), ThreadPoolExecutor(max_workers=1) as executor:
            run = BatchRun(BatchSettings(games=3, max_plies=2), self.root / "batches", executor)
            run.future.result(timeout=5)
        self.assertEqual(run.snapshot()["status"], "failed")
        batch = self.root / "batches" / run.snapshot()["batch_id"]
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("controlled AI error", manifest["error"])
        self.assertEqual(manifest["counts"]["saved_games"], 1)
        self.assertEqual(len(ReplayCatalog(self.root).entries), 1)

    def test_cross_midnight_batch_and_standalone_group_by_actual_game_start(self):
        settings = generation_settings(games=2, seed=42, workers=1, initial_fen=chess.STARTING_FEN,
                                       claim_draw=False, max_plies=1)
        with BatchWriter(self.root / "batches", name=None, tags=[], settings=settings) as writer:
            for number, timestamp in enumerate(("2026-09-08T23:59:58+08:00", "2026-09-09T00:00:01+08:00"), 1):
                game = replace(generate_game(number, 42, max_plies=1), started_at=timestamp)
                writer.add_game(game, seed=42)
        standalone = self.root / "replays"
        standalone.mkdir()
        payload = dict(initial_fen=chess.STARTING_FEN, moves_uci=[], result="*",
                       metadata={"started_at": "2026-09-08T16:01:00Z", "white_player": "Human",
                                 "black_player": "Greedy", "game_id": "20260909_000002"})
        (standalone / "human.json").write_text(json.dumps(payload), encoding="utf-8")
        catalog = ReplayCatalog(self.root)
        self.assertEqual(catalog.options(), ["2026-09-09", "2026-09-08"])
        catalog.choose(0)
        self.assertEqual({group[0] for group in catalog.options()}, {writer.batch_id, "standalone"})
        human = next(e for e in catalog.entries if e.white == "Human")
        self.assertEqual(human.time_label, "00:01:00")
        catalog.back()
        catalog.choose(1)
        self.assertEqual(catalog.options(), [(writer.batch_id, writer.batch_id)])

    def test_v1_lookup_uses_saved_prefix_and_unknown_dates_without_mutation(self):
        batch = self.root / "batches/legacy"
        batch.mkdir(parents=True)
        replay = batch / "game_000001.json"
        replay.write_text('{"initial_fen": "unused", "moves_uci": []}', encoding="utf-8")
        manifest = dict(schema_version=1, batch_id="legacy", name="舊資料",
                        files={"games": "games.csv"}, counts={"saved_games": 1})
        source = json.dumps(manifest)
        (batch / "manifest.json").write_text(source, encoding="utf-8")
        (batch / "games.csv").write_text("game_id,white_player,black_player,result,replay_path\n1,Random,Greedy,0-1,game_000001.json\n2,Random,Greedy,*,missing.json\n", encoding="utf-8")
        catalog = ReplayCatalog(self.root)
        self.assertEqual(len(catalog.entries), 1)
        self.assertEqual(catalog.entries[0].date, "日期不詳")
        self.assertEqual((batch / "manifest.json").read_text(encoding="utf-8"), source)
        # Indexes may not escape the owning batch, even if the target exists.
        (batch / "games.csv").write_text("game_id,replay_path\n1,../legacy/../../outside.json\n", encoding="utf-8")
        catalog.refresh()
        self.assertEqual(catalog.entries, [])
        self.assertEqual(catalog.skipped, 1)

    def test_winner_badge_color_is_independent_of_white_black_assignment(self):
        white_win, black_loss = result_badges("1-0")
        white_loss, black_win = result_badges("0-1")
        self.assertEqual(white_win, black_win)
        self.assertEqual(white_loss, black_loss)
        self.assertNotEqual(white_win[1], white_loss[1])
        self.assertEqual(result_badges("1/2-1/2")[0][0], "和")
        self.assertEqual(result_badges("*")[0][0], "未完成")


if __name__ == "__main__":
    unittest.main()
