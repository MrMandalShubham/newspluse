"""Object storage abstraction for raw article content.

Raw text is kept out of Postgres (which stores only metadata + a ``raw_ref``
pointer). Locally we write to a directory; in production a DO Spaces backend
implements the same interface.
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from pathlib import Path

from newspulse.config import settings

_CONTENT_TYPES = {
    ".json": "application/json",
    ".html": "text/html",
    ".pdf": "application/pdf",
    ".md": "text/markdown",
}


class ObjectStorage(ABC):
    """Minimal put/get contract shared by all storage backends."""

    @abstractmethod
    def put(self, key: str, data: bytes) -> str:
        """Store ``data`` under ``key`` and return a reference string."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Return the bytes previously stored under ``key``."""

    def public_url(self, key: str) -> str | None:
        """Return a public URL for the key, or None if not available."""
        return None


class LocalStorage(ObjectStorage):
    """Filesystem-backed storage for local development."""

    scheme = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"{self.scheme}://{key}"

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


class SpacesStorage(ObjectStorage):
    """DigitalOcean Spaces (S3-compatible) storage backend."""

    scheme = "spaces"

    def __init__(
        self, endpoint: str, bucket: str, key: str, secret: str,
    ) -> None:
        import boto3

        self.bucket = bucket
        self.endpoint = endpoint
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=endpoint.split(".")[0].split("//")[-1],
        )

    def put(self, key: str, data: bytes) -> str:
        suffix = Path(key).suffix.lower()
        ct = _CONTENT_TYPES.get(suffix, "application/octet-stream")
        extra: dict = {"ContentType": ct}
        if suffix in (".pdf", ".html", ".json"):
            extra["ACL"] = "public-read"
        self._s3.upload_fileobj(io.BytesIO(data), self.bucket, key, ExtraArgs=extra)
        return f"{self.scheme}://{key}"

    def get(self, key: str) -> bytes:
        buf = io.BytesIO()
        self._s3.download_fileobj(self.bucket, key, buf)
        return buf.getvalue()

    def public_url(self, key: str) -> str | None:
        return f"{self.endpoint}/{self.bucket}/{key}"


def get_storage() -> ObjectStorage:
    """Return the configured storage backend — Spaces if configured, else local."""
    if settings.spaces_endpoint and settings.spaces_bucket:
        return SpacesStorage(
            endpoint=settings.spaces_endpoint,
            bucket=settings.spaces_bucket,
            key=settings.spaces_key,
            secret=settings.spaces_secret,
        )
    return LocalStorage(settings.storage_dir)
