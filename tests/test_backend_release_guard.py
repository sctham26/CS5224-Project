import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("release_guard", Path(__file__).parents[1] / "scripts/check_backend_release.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class BaselineTests(unittest.TestCase):
    def test_schema_additions_and_dependency_changes_invalidate_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "migrations").mkdir()
            for path in [root / "migrations/001.sql", root / "requirements.txt", root / "pyproject.toml"]:
                path.write_text("reviewed")
            expected = guard.fingerprints(root)
            # Normal application edits are eligible for automatic release.
            (root / "app.py").write_text("new application code")
            self.assertEqual(guard.fingerprints(root), expected)
            (root / "requirements.txt").write_text("new dependencies")
            self.assertNotEqual(guard.fingerprints(root), expected)
            (root / "requirements.txt").write_text("reviewed")
            (root / "migrations/nested").mkdir()
            (root / "migrations/nested/002.sql").write_text("new schema")
            self.assertNotEqual(guard.fingerprints(root), expected)


if __name__ == "__main__":
    unittest.main()
