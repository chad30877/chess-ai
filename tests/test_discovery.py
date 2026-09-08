"""Ensure responsibility folders remain included in unittest discovery."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def test_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_cases(item)
        else:
            yield item


class DiscoveryTest(unittest.TestCase):
    def test_every_test_module_is_discovered_once_under_tests_namespace(self):
        loader = unittest.TestLoader()
        suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        self.assertEqual(loader.errors, [])
        ids = [case.id() for case in test_cases(suite)]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate test cases")
        expected_modules = {
            ".".join(path.relative_to(ROOT).with_suffix("").parts)
            for path in (ROOT / "tests").rglob("test_*.py")
        }
        actual_modules = {test_id.rsplit(".", 2)[0] for test_id in ids}
        self.assertEqual(actual_modules, expected_modules)


if __name__ == "__main__":
    unittest.main()
