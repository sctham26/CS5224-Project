import importlib.util
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy

spec = importlib.util.spec_from_file_location("release_guard", Path(__file__).parents[1] / "scripts/check_backend_release.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
release_spec = importlib.util.spec_from_file_location("release_cli", Path(__file__).parents[1] / "scripts/release_backend.py")
release = importlib.util.module_from_spec(release_spec)
release_spec.loader.exec_module(release)


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


class RuntimeVerificationTests(unittest.TestCase):
    def test_both_services_must_use_stack_revisions_and_be_stable(self):
        outputs = {"ApiServiceArn": "service-api", "WorkerServiceArn": "service-worker",
                   "ApiTaskDefinitionArn": "api:4", "WorkerTaskDefinitionArn": "worker:4"}
        result = {"services": [{"serviceArn": arn, "taskDefinition": task, "runningCount": 1,
            "pendingCount": 0, "deployments": [{"rolloutState": "COMPLETED"}]}
            for arn, task in [("service-api", "api:4"), ("service-worker", "worker:4")]]}
        release.verify_services(result, outputs)
        for field, value in [("taskDefinition", "api:3"), ("pendingCount", 1),
                             ("serviceArn", "unrelated-service")]:
            bad = deepcopy(result)
            bad["services"][0][field] = value
            with self.assertRaises(ValueError):
                release.verify_services(bad, outputs)


if __name__ == "__main__":
    unittest.main()
