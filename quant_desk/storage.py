"""Atomic JSON persistence. The dashboard polls these state files every 30s while scheduled
agents write them, and agents can overlap a manual command — so an in-place truncate+write
(plain json.dump) exposes torn reads and interleaved-writer corruption. Writing to a temp file
in the same directory and os.replace()-ing it is atomic on POSIX: a concurrent reader always
sees either the complete old file or the complete new one, never a partial write.
"""
from __future__ import annotations

import json
import os


def atomic_write_json(path: str, obj, *, indent: int = 2) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())          # durable before the rename
        os.replace(tmp, path)             # atomic swap — readers never see a partial file
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
