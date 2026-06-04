"""Blob storage for STL/gcode.

Local volume in dev (content-addressed by sha256). The function boundary IS the
S3-compatible seam: swap the body of `save_blob`/`read_blob` for an S3 client and nothing
else changes. Each FileVersion records the returned blob_key + checksum + size.
"""
from __future__ import annotations

import hashlib
import os

from .config import settings


def _safe_name(name: str) -> str:
    return os.path.basename(name).replace("/", "_").replace("\\", "_") or "file.bin"


def save_blob(content: bytes, *, original_filename: str) -> dict:
    checksum = hashlib.sha256(content).hexdigest()
    # content-addressed path, keeps a readable suffix
    key = f"{checksum[:2]}/{checksum}-{_safe_name(original_filename)}"
    path = os.path.join(settings.storage_dir, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return {"blob_key": key, "checksum": checksum, "size": len(content)}


def read_blob(blob_key: str) -> bytes:
    with open(os.path.join(settings.storage_dir, blob_key), "rb") as f:
        return f.read()
