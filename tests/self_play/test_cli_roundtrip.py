"""Exercise process serialization and replay exports through real CLI entrypoints."""

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from engine.replay.replay_loader import load_replay_json
from engine.replay.replay_session import ReplaySession


ROOT = Path(__file__).resolve().parents[2]


class CliRoundtripTest(unittest.TestCase):
    def cli(self, module, *args):
        result = subprocess.run(
            [sys.executable, "-m", module, *map(str, args)], cwd=ROOT,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_multiprocess_generation_exports_replay_with_same_moves_and_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.cli("scripts.generate_dataset", "--games", 2, "--workers", 2,
                     "--seed", 42, "--max-plies", 4, "--batch-root", root / "batches")
            batch, = (root / "batches").iterdir()
            manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["counts"]["saved_games"], 2)
            with (batch / "games.csv").open(encoding="utf-8", newline="") as stream:
                games = list(csv.DictReader(stream))
            self.assertEqual(len(games), 2)
            for game in games:
                with self.subTest(game=game["game_id"]):
                    target = root / f"{game['game_id']}.json"
                    self.cli("scripts.export_replay_json", "--dataset", batch / "positions.csv",
                             "--game-id", game["game_id"], "--output", target)
                    exported = load_replay_json(str(target))
                    saved = load_replay_json(str(batch / game["replay_path"]))
                    self.assertEqual(exported["moves_uci"], saved["moves_uci"])
                    self.assertEqual(len(exported["moves_uci"]), 4)
                    self.assertEqual(exported["result"], "*")
                    self.assertEqual(exported["result"], saved["result"])
                    self.assertEqual(exported["metadata"]["status"], "truncated")
                    session = ReplaySession(exported["initial_fen"], exported["moves_uci"])
                    session.last()
                    self.assertEqual(session.current_result(), "*")


if __name__ == "__main__":
    unittest.main()
