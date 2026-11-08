"""Explicit opt-in backend configuration; never start placeholder images."""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class BackendConfig:
    postgres_version: str = "18.6"  # Available in ap-southeast-1 on 2026-10-23.
    multi_az: bool = True
    persist_uploads: bool = False
    visibility_seconds: int = 900
    job_lease_seconds: int = 840
    max_receive_count: int = 5
    upload_url_ttl_seconds: int = 300
    api_image: str | None = None
    worker_image: str | None = None
    worker_command: tuple[str, ...] = ()
    jwt_issuer: str | None = None
    jwt_audience: tuple[str, ...] = ()
    authorization_scopes: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    def __post_init__(self):
        if not re.fullmatch(r"\d+\.\d+", self.postgres_version):
            raise ValueError("postgres_version must be an available major.minor release")
        if int(self.postgres_version.split(".")[0]) < 16:
            raise ValueError("Database bootstrap requires PostgreSQL 16 or later")
        if type(self.persist_uploads) is not bool:
            raise ValueError("persist_uploads must be a JSON boolean")
        if type(self.multi_az) is not bool:
            raise ValueError("multi_az must be a JSON boolean")
        for value, low, high, name in [
            (self.visibility_seconds, 30, 43200, "visibility_seconds"),
            (self.max_receive_count, 1, 1000, "max_receive_count"),
            (self.upload_url_ttl_seconds, 60, 900, "upload_url_ttl_seconds"),
        ]:
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Invalid {name}")
        if type(self.job_lease_seconds) is not int or not 1 <= self.job_lease_seconds <= self.visibility_seconds - 30:
            raise ValueError("job_lease_seconds must leave at least 30 seconds before queue visibility expires")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
                raise ValueError("allowed_origins must contain explicit HTTPS origins")

    def validate_runtime(self):
        image_pattern = r"\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}"
        for name, image in [("api_image", self.api_image), ("worker_image", self.worker_image)]:
            if not image or not re.fullmatch(image_pattern, image):
                raise ValueError(f"{name} must be an immutable private ECR digest URI")
        if not self.jwt_issuer or urlsplit(self.jwt_issuer).scheme != "https" or not urlsplit(self.jwt_issuer).netloc:
            raise ValueError("An HTTPS jwt_issuer is required")
        if not self.jwt_audience or not self.authorization_scopes:
            raise ValueError("jwt_audience and access-token authorization_scopes are required")
        if not self.allowed_origins or not self.worker_command or not all(isinstance(x, str) and x for x in self.worker_command):
            raise ValueError("allowed_origins and a real worker_command are required")

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        for key in ("worker_command", "jwt_audience", "authorization_scopes", "allowed_origins"):
            if key in data:
                if not isinstance(data[key], list) or not all(isinstance(x, str) for x in data[key]):
                    raise ValueError(f"{key} must be a JSON string array")
                data[key] = tuple(data[key])
        return cls(**data)
