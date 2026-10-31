"""Content-addressed artifact store with no delete and no overwrite.

Bytes are stored at ``<root>/sha256/<first two hex chars>/<sha256>``. Putting the same bytes twice
is a
no-op; putting different bytes at a path that already exists cannot happen by construction, and any
corruption of stored bytes is detected on read. Manifests (small JSON files describing an artifact)
live beside the store and are written once.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonutil import dumps_canonical

_CHUNK = 1024 * 1024


class ArtifactError(ValueError):
    """Raised for integrity failures or disallowed operations."""


def sha256_file(path: Path) -> str:
    """Stream a file and return its hex sha256."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Hex sha256 of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class StoredArtifact:
    """Where an artifact landed and how big it is."""

    sha256: str
    path: Path
    size_bytes: int
    already_present: bool


class ArtifactStore:
    """Write-once, content-addressed store. There is deliberately no ``delete`` method."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.blob_root = root / "sha256"
        self.manifest_root = root / "manifests"

    def blob_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ArtifactError("digest must be 64 lowercase hex characters")
        return self.blob_root / digest[:2] / digest

    def put_bytes(self, data: bytes) -> StoredArtifact:
        """Store bytes; return their address. Idempotent for identical bytes."""
        digest = sha256_bytes(data)
        target = self.blob_path(digest)
        if target.exists():
            if sha256_file(target) != digest:
                raise ArtifactError(f"stored blob is corrupt: {target}")
            return StoredArtifact(digest, target, len(data), already_present=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".incoming-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # link() fails if the target appeared meanwhile; identical content, so that is fine.
            with contextlib.suppress(FileExistsError):
                os.link(tmp_name, target)
        finally:
            Path(tmp_name).unlink(missing_ok=True)
        return StoredArtifact(digest, target, len(data), already_present=False)

    def put_file(self, source: Path) -> StoredArtifact:
        """Store a file's bytes without loading very large files twice into memory."""
        digest = sha256_file(source)
        target = self.blob_path(digest)
        if target.exists():
            if sha256_file(target) != digest:
                raise ArtifactError(f"stored blob is corrupt: {target}")
            return StoredArtifact(digest, target, source.stat().st_size, already_present=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".incoming-")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with source.open("rb") as src, tmp.open("wb") as dst:
                for chunk in iter(lambda: src.read(_CHUNK), b""):
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            if sha256_file(tmp) != digest:
                raise ArtifactError("source changed while being stored")
            with contextlib.suppress(FileExistsError):
                os.link(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        return StoredArtifact(digest, target, source.stat().st_size, already_present=False)

    def open_verified(self, digest: str) -> bytes:
        """Read a blob and verify its hash before returning the bytes."""
        target = self.blob_path(digest)
        if not target.is_file():
            raise ArtifactError(f"missing artifact {digest}")
        data = target.read_bytes()
        if sha256_bytes(data) != digest:
            raise ArtifactError(f"artifact {digest} failed verification")
        return data

    def write_manifest(self, name: str, manifest: dict[str, Any]) -> Path:
        """Write a manifest exactly once; a second write with the same name is refused."""
        if "/" in name or name.startswith(".") or not name:
            raise ArtifactError("manifest name must be a plain file name")
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        target = self.manifest_root / f"{name}.json"
        payload = (dumps_canonical(manifest) + "\n").encode("utf-8")
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError as exc:
            raise ArtifactError(
                f"manifest {target.name} already exists; write a new manifest, never overwrite"
            ) from exc
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        return target
