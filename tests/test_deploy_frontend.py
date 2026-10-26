import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("deploy", Path(__file__).parents[1] / "scripts/deploy_frontend.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dist = Path(self.temp.name)
        (self.dist / "assets").mkdir()
        (self.dist / "index.html").write_text('<script src="/assets/app.js"></script>')

    @patch.object(deploy, "aws")
    def test_wrong_account_stops_before_writes(self, aws):
        aws.return_value = "111111111111"
        with self.assertRaisesRegex(ValueError, "account mismatch"):
            deploy.deploy(self.dist, "test-bucket", "EXAMPLE123", "825990809862", "a" * 40)
        self.assertEqual(aws.call_count, 1)

    @patch.object(deploy, "aws")
    def test_assets_before_html_and_invalidation_waited(self, aws):
        aws.side_effect = ["825990809862", "", "", "", "", "I123", ""]
        deploy.deploy(self.dist, "test-bucket", "EXAMPLE123", "825990809862", "a" * 40)
        calls = [c.args for c in aws.call_args_list]
        self.assertTrue(calls[1][3].endswith("/assets"))
        self.assertTrue(calls[3][3].endswith("/index.html"))
        self.assertTrue(calls[4][3].endswith("/release.json"))
        self.assertEqual(calls[-1][:3], ("cloudfront", "wait", "invalidation-completed"))
        self.assertFalse(any("--delete" in c for c in calls))

    @patch.object(deploy, "aws")
    def test_failed_asset_upload_never_switches_html(self, aws):
        aws.side_effect = ["825990809862", RuntimeError("upload failed")]
        with self.assertRaises(RuntimeError):
            deploy.deploy(self.dist, "test-bucket", "EXAMPLE123", "825990809862", "a" * 40)
        self.assertEqual(aws.call_count, 2)

    @patch.object(deploy, "aws")
    def test_missing_build_stops_before_aws(self, aws):
        (self.dist / "index.html").unlink()
        with self.assertRaisesRegex(ValueError, "Vite build"):
            deploy.deploy(self.dist, "test-bucket", "EXAMPLE123", "825990809862", "a" * 40)
        aws.assert_not_called()
