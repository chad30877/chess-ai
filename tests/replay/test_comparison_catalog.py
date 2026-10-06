"""Verify candidate-perspective summaries against real saved comparison batches."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

import chess

from engine.evaluation.config import EvaluationConfig
from engine.replay.comparison_catalog import ComparisonCatalog, load_comparison
from engine.sessions.evaluation_comparison import ComparisonParticipant, run_evaluation_comparison


class ComparisonCatalogTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.result = run_evaluation_comparison(
            baseline=ComparisonParticipant.greedy("stable", EvaluationConfig()),
            candidate=ComparisonParticipant.greedy("candidate", EvaluationConfig(phase_enabled=True)),
            initial_fens=["7k/6Q1/5K2/8/8/8/8/8 b - - 0 1",
                          "7k/8/8/8/8/8/8/K7 w - - 0 1", chess.STARTING_FEN],
            max_plies=0, batch_root=self.root / "batches", name="mixed",
        )
        self.manifest = self.result.path / "manifest.json"
        self.artifact = self.result.path / "comparison.json"

    def test_candidate_score_excludes_unfinished_and_tracks_saved_settings(self):
        summary = load_comparison(self.manifest)
        self.assertEqual((summary.wins, summary.draws, summary.losses, summary.unfinished), (1, 2, 1, 2))
        self.assertEqual(summary.score_rate, 0.5)
        self.assertEqual([g.outcome for g in summary.games], ["loss", "win", "draw", "draw", "unfinished", "unfinished"])
        self.assertEqual([g.candidate_color for g in summary.games[:2]], ["black", "white"])
        self.assertTrue(summary.participants["candidate"]["evaluator"]["phase"]["enabled"])
        self.assertFalse(summary.participants["baseline"]["evaluator"]["phase"]["enabled"])
        self.assertEqual(summary.elapsed_seconds, sum(g.elapsed_seconds for g in summary.games))
        # No positions or moves are needed to display results.
        (self.result.path / "positions.csv").unlink()
        summary.games[0].path.write_text("not a replay", encoding="utf-8")
        self.assertEqual(load_comparison(self.manifest).score_rate, 0.5)

    def test_candidate_wins_with_either_color_and_non_half_score(self):
        payload = json.loads(self.artifact.read_text(encoding="utf-8"))
        payload["pairs"][0]["games"][0].update(result="0-1", candidate_outcome="win")
        payload["stats"]["candidate"].update(wins=2, losses=0, score=3.0)
        payload["stats"]["baseline"].update(wins=0, losses=2, score=1.0)
        self.artifact.write_text(json.dumps(payload), encoding="utf-8")
        games_path = self.result.path / "games.csv"
        with games_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        rows[0]["result"] = "0-1"
        with games_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fields)
            writer.writeheader()
            writer.writerows(rows)
        summary = load_comparison(self.manifest)
        self.assertEqual([g.outcome for g in summary.games[:2]], ["win", "win"])
        self.assertEqual(summary.score_rate, 0.75)

    def test_missing_replays_do_not_erase_results(self):
        summary = load_comparison(self.manifest)
        summary.games[0].path.unlink()
        loaded = load_comparison(self.manifest)
        self.assertIsNone(loaded.games[0].path)
        self.assertEqual(loaded.losses, 1)

    def test_schema_one_and_regular_batches_are_kept_separate(self):
        payload = json.loads(self.artifact.read_text(encoding="utf-8"))
        payload["schema_version"] = 1
        self.artifact.write_text(json.dumps(payload), encoding="utf-8")
        ordinary = self.root / "batches/ordinary"
        ordinary.mkdir()
        (ordinary / "manifest.json").write_text(json.dumps({"settings": {}, "files": {}}), encoding="utf-8")
        catalog = ComparisonCatalog(self.root)
        self.assertEqual(len(catalog.entries), 1)
        self.assertEqual(catalog.errors, [])

    def test_corrupt_summary_is_reported_without_replacing_valid_results(self):
        original = self.artifact.read_text(encoding="utf-8")
        for corruption in ("version", "stats", "baseline_stats", "boolean_stats", "color", "elapsed", "duplicate", "settings", "result"):
            with self.subTest(corruption=corruption):
                payload = json.loads(original)
                game = payload["pairs"][0]["games"][0]
                if corruption == "version":
                    payload["schema_version"] = 999
                elif corruption == "stats":
                    payload["stats"]["candidate"]["wins"] = 9
                elif corruption == "baseline_stats":
                    payload["stats"]["baseline"]["losses"] = 9
                elif corruption == "boolean_stats":
                    payload["stats"]["candidate"]["wins"] = True
                elif corruption == "color":
                    game["candidate_color"] = "white"
                elif corruption == "elapsed":
                    game["elapsed_seconds"] = float("nan")
                elif corruption == "duplicate":
                    payload["pairs"].append(payload["pairs"][0])
                elif corruption == "settings":
                    payload["participants"]["candidate"]["evaluator"] = {}
                else:
                    game["result"] = "0-1"
                self.artifact.write_text(json.dumps(payload), encoding="utf-8")
                catalog = ComparisonCatalog(self.root)
                self.assertEqual(catalog.entries, [])
                self.assertEqual(len(catalog.errors), 1)
        self.artifact.write_text(original, encoding="utf-8")
        self.assertEqual(len(ComparisonCatalog(self.root).entries), 1)

    def test_missing_artifact_invalid_json_and_escaping_path_are_reported(self):
        self.artifact.unlink()
        self.assertEqual(len(ComparisonCatalog(self.root).errors), 1)
        self.artifact.write_text("{", encoding="utf-8")
        self.assertEqual(len(ComparisonCatalog(self.root).errors), 1)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["files"]["comparison"] = "../outside.json"
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIn("leaves its batch", ComparisonCatalog(self.root).errors[0])

    def test_random_baseline_and_unpublished_csv_tail(self):
        result = run_evaluation_comparison(
            baseline=ComparisonParticipant.random_baseline(),
            candidate=ComparisonParticipant.greedy("candidate", EvaluationConfig()),
            initial_fens=["7k/8/8/8/8/8/8/K7 w - - 0 1"],
            batch_root=self.root / "batches",
        )
        with (result.path / "games.csv").open("a", encoding="utf-8") as stream:
            stream.write("unpublished,invalid,row\n")
        summary = load_comparison(result.path / "manifest.json")
        self.assertEqual(summary.draws, 2)
        self.assertEqual(summary.score_rate, 0.5)
        self.assertEqual(summary.participants["baseline"]["strategy"], "Random")


if __name__ == "__main__":
    unittest.main()
