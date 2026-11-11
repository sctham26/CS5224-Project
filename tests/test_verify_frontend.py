import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("verify", Path(__file__).parents[1] / "scripts/verify_frontend.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def response(body, content_type="application/javascript"):
    stream = io.BytesIO(body)
    stream.headers = {"Content-Type": content_type}
    return stream


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dist = Path(self.temp.name)
        self.html = b'<script src="/assets/app.js"></script><link href="/assets/app.css" rel="stylesheet">'
        (self.dist / "index.html").write_bytes(self.html)

    @patch.object(verify, "urlopen")
    def test_published_build_and_release(self, request):
        request.side_effect = [response(self.html, "text/html"), response(b"js"),
                               response(b"css", "text/css"), response(json.dumps({"commit": "a" * 40}).encode())]
        verify.verify("https://example.cloudfront.net", self.dist, "a" * 40)
        self.assertEqual(request.call_count, 4)

    @patch.object(verify, "urlopen")
    def test_stale_html_fails(self, request):
        request.return_value = response(b"old build")
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify.verify("https://example.cloudfront.net", self.dist, "a" * 40)

    @patch.object(verify, "urlopen")
    def test_missing_asset_returning_html_fails(self, request):
        request.side_effect = [response(self.html, "text/html"), response(self.html, "text/html")]
        with self.assertRaisesRegex(ValueError, "Asset returned HTML"):
            verify.verify("https://example.cloudfront.net", self.dist, "a" * 40)

    @patch.object(verify, "urlopen")
    def test_stale_release_fails(self, request):
        request.side_effect = [response(self.html, "text/html"), response(b"js"), response(b"css"),
                               response(b'{"commit": "old"}')]
        with self.assertRaisesRegex(ValueError, "release SHA"):
            verify.verify("https://example.cloudfront.net", self.dist, "a" * 40)
