"""Presign must use Signature V4: the tenant bucket is SSE-KMS (SigV2 is rejected)."""

import sys
import types

import jobs


def test_s3_presign_client_forces_signature_v4(monkeypatch):
    captured = {}

    class FakeS3:
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            captured["operation"] = operation
            captured["params"] = Params
            return "https://example-bucket.s3.amazonaws.com/signed"

    def fake_client(name, **kwargs):
        captured["service"] = name
        captured["config"] = kwargs.get("config")
        return FakeS3()

    module = types.ModuleType("boto3")
    module.client = fake_client
    monkeypatch.setitem(sys.modules, "boto3", module)

    uploader = jobs.S3Uploader("tenant-bucket", ttl_seconds=120)
    result = uploader.presign("spip-songsifan")

    assert captured["service"] == "s3"
    config = captured["config"]
    assert config is not None, "a botocore Config must be passed"
    assert config.signature_version == "s3v4"
    assert config.s3["addressing_style"] == "virtual"
    assert captured["operation"] == "put_object"
    assert captured["params"]["ContentType"] == "text/csv"
    assert result["key"].startswith("tenants/spip-songsifan/uploads/")
    assert result["expires_in"] == 120
