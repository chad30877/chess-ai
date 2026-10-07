"""驗證統一索引的類型區分、缺漏回退與唯讀發布前綴。"""

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import chess

from engine.evaluation.config import EvaluationConfig
from engine.replay.records_catalog import RecordsCatalog, load_batch_record, load_standalone_record
from engine.sessions.evaluation_comparison import ComparisonParticipant, run_evaluation_comparison
from engine.sessions.self_play import play_game
from engine.players import RandomPlayer
from engine.storage.batch_storage import BatchWriter


class RecordsCatalogTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def comparison(self):
        return run_evaluation_comparison(
            baseline=ComparisonParticipant.greedy("基準", EvaluationConfig()),
            candidate=ComparisonParticipant.greedy("候選", EvaluationConfig()),
            initial_fens=["7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"],
            batch_root=self.root / "batches",
        ).path

    def ordinary(self):
        settings = {"num_games": 2, "rules": {"claim_draw": False}, "strategies": {
            "white": {"strategy": "Random"}, "black": {"strategy": "Random"}}}
        with BatchWriter(self.root / "batches", name=None, tags=[], settings=settings) as writer:
            for number, timestamp in enumerate(("2026-09-09T15:59:59Z", "2026-09-09T16:00:01Z"), 1):
                game = play_game(number, RandomPlayer(), RandomPlayer(), "Random", "Random",
                                 initial_fen="7k/8/8/8/8/8/8/K7 w - - 0 1")
                game = replace(game, started_at=timestamp)
                writer.add_game(game, seed=number)
            return writer.path

    def standalone(self, **metadata):
        path = self.root / "replays/plain.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"initial_fen": chess.STARTING_FEN, "moves_uci": [],
                                    "result": "*", "metadata": metadata}), encoding="utf-8")
        return path

    def test_all_types_share_index_without_invented_settings_or_elapsed(self):
        comparison = self.comparison()
        ordinary = self.ordinary()
        standalone = self.standalone()
        catalog = RecordsCatalog(self.root)
        self.assertEqual({entry.kind for entry in catalog.entries}, {"comparison", "batch", "standalone"})
        compare = catalog.get(str(comparison.resolve()))
        self.assertEqual(compare.comparison.paired_score_rate, 0.5)
        self.assertEqual([g.outcome for g in compare.games], ["loss", "win"])
        regular = catalog.get(str(ordinary.resolve()))
        self.assertIsNone(regular.comparison)
        self.assertEqual(regular.counts["draw"], 2)
        self.assertIsNone(regular.elapsed_seconds)
        self.assertEqual(regular.settings["strategies"]["white"]["strategy"], "Random")
        single = catalog.get(str(standalone.resolve()))
        self.assertIsNone(single.settings)
        self.assertIsNone(single.games[0].white)
        self.assertIsNone(single.elapsed_seconds)
        self.assertEqual(single.dates, {"日期不詳"})

    def test_dates_use_each_game_and_summary_remains_whole_batch(self):
        path = self.ordinary()
        entry = load_batch_record(path / "manifest.json")
        self.assertEqual(entry.dates, {"2026-09-09", "2026-09-10"})
        self.assertEqual(len(entry.games_on("2026-09-09")), 1)
        self.assertEqual(entry.counts["draw"], 2)
        self.assertEqual(RecordsCatalog(self.root).on_date("2026-09-10"), [entry])

    def test_missing_corrupt_or_inconsistent_comparison_keeps_saved_games(self):
        path = self.comparison()
        artifact = path / "comparison.json"
        original = artifact.read_text(encoding="utf-8")
        bad = json.loads(original)
        bad["stats"]["candidate"]["wins"] = 99
        for payload in (None, "{", json.dumps(bad)):
            with self.subTest(payload=payload):
                if payload is None:
                    artifact.unlink()
                else:
                    artifact.write_text(payload, encoding="utf-8")
                summary = load_batch_record(path / "manifest.json")
                self.assertEqual(summary.kind, "comparison_unavailable")
                self.assertIsNone(summary.comparison)
                self.assertEqual(len(summary.games), 2)
                self.assertIn("比較摘要缺漏或損壞", summary.error)
                self.assertTrue(all(game.path.is_file() for game in summary.games))

    def test_prefix_missing_path_and_escape_are_not_hidden(self):
        path = self.ordinary()
        games_file = path / "games.csv"
        with games_file.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        rows[0]["replay_path"] = "../../outside.json"
        rows[1]["replay_path"] = "replays/missing.json"
        with games_file.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows + [dict(rows[0], game_id="unpublished")])
        summary = load_batch_record(path / "manifest.json")
        self.assertEqual(len(summary.games), 2)
        self.assertTrue(all(game.path is None for game in summary.games))
        self.assertIn("越出", summary.games[0].issue)
        self.assertEqual(summary.games[1].issue, "棋譜缺漏")
        self.assertEqual(summary.counts["draw"], 2)

    def test_corrupt_and_missing_manifests_stay_visible_and_reader_is_read_only(self):
        path = self.comparison()
        self.standalone()
        broken = self.root / "batches/broken"
        broken.mkdir()
        (broken / "manifest.json").write_text("{", encoding="utf-8")
        (self.root / "batches/missing").mkdir()
        (self.root / "replays/broken.json").write_text("{", encoding="utf-8")
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        catalog = RecordsCatalog(self.root)
        self.assertEqual(len(catalog.entries), 5)
        self.assertEqual(sum(bool(e.error) for e in catalog.entries), 3)
        catalog.refresh()
        after = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(catalog.get(str(path.resolve())).kind, "comparison")

    def test_standalone_exposes_only_saved_values(self):
        path = self.standalone(seed=42, white_player="Human", elapsed_seconds=3.5,
                               started_at="2026-09-09T16:00:00Z", finished_at="2030-01-01T00:00:00Z")
        record = load_standalone_record(path)
        self.assertEqual(record.settings, {"seed": 42})
        self.assertEqual(record.elapsed_seconds, 3.5)
        self.assertEqual(record.dates, {"2026-09-10"})
        path = self.standalone(finished_at="2030-01-01T00:00:00Z", elapsed_seconds=-1)
        self.assertIsNone(load_standalone_record(path).elapsed_seconds)


if __name__ == "__main__":
    unittest.main()
