import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("source", Path(__file__).parents[1] / "scripts/frontend_source.py")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class FrontendSourceTests(unittest.TestCase):
    def test_cloud_checks_use_integration_and_main_checks_its_exact_commit(self):
        self.assertEqual(source.select_source("push", "refs/heads/cloud-config", "a" * 40), "integration")
        self.assertEqual(source.select_source("pull_request", "refs/pull/2/merge", "a" * 40,
            head_ref="cloud-config"), "integration")
        self.assertEqual(source.select_source("push", "refs/heads/main", "a" * 40), "a" * 40)
        self.assertEqual(source.select_source("pull_request", "refs/pull/3/merge", "b" * 40), "b" * 40)

    def test_only_integration_can_be_manually_published_from_trusted_workflow_refs(self):
        self.assertEqual(source.select_source("workflow_dispatch", "refs/heads/cloud-config", "a" * 40,
            "integration", True), "integration")
        for branch in source.SOURCES - {"integration"}:
            self.assertEqual(source.select_source("workflow_dispatch", "refs/heads/cloud-config", "a" * 40,
                branch, False), branch)
            with self.assertRaises(ValueError):
                source.select_source("workflow_dispatch", "refs/heads/cloud-config", "a" * 40, branch, True)
        with self.assertRaises(ValueError):
            source.select_source("workflow_dispatch", "refs/heads/other", "a" * 40, "integration", True)
