"""Object storage abstraction for raw article content.

Raw text is kept out of Postgres (which stores only metadata + a ``raw_ref``
pointer). Locally we write to a directory; in production a DO Spaces backend
implements the same interface. Phase 1 ships the local backend only.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from newspulse.config import settings


class ObjectStorage(ABC):
    """Minimal put/get contract shared by all storage backends."""

    @abstractmethod
    def put(self, key: str, data: bytes) -> str:
        """Store ``data`` under ``key`` and return a reference string."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Return the bytes previously stored under ``key``."""


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


def get_storage() -> ObjectStorage:
    """Return the configured storage backend (local for now)."""
    return LocalStorage(settings.storage_dir)
