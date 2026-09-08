"""Check engine packages and public entrypoints in fresh interpreters."""

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EngineImportsTest(unittest.TestCase):
    def test_modules_import_independently_without_cycles(self):
        modules = sorted(
            ".".join(path.relative_to(ROOT).with_suffix("").parts)
            for path in (ROOT / "engine").rglob("*.py")
            if path.name != "__init__.py"
        )
        modules += ["apps.play_ui", "apps.chess_application"]
        for module in modules:
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-c", f"import importlib; importlib.import_module({module!r})"],
                    cwd=ROOT, capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
