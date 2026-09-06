"""Content-addressed cache with .meta.json sidecars recording url/time/licence."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_CACHE = Path(os.environ.get("SCE_CACHE", Path.home() / ".cache" / "sce"))


class Cache:
    def __init__(self, root: Path | str | None = None, *, offline: bool | None = None) -> None:
        """`offline` defaults to the SCE_OFFLINE environment variable.

        Passing it explicitly wins in both directions. The two used to be OR-ed,
        which meant a caller could switch offline mode on but never off, so a
        test suite that set the variable globally could not carve out an
        exception for the handful of tests that are supposed to reach the
        network.
        """
        self.root = Path(root) if root else DEFAULT_CACHE
        self.root.mkdir(parents=True, exist_ok=True)
        self.offline = (os.environ.get("SCE_OFFLINE") == "1") if offline is None else offline

    def key(self, *parts: Any) -> str:
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    def path(self, key: str, suffix: str) -> Path:
        return self.root / f"{key}{suffix}"

    def meta_path(self, key: str, suffix: str) -> Path:
        return self.root / f"{key}{suffix}.meta.json"

    def has(self, key: str, suffix: str) -> bool:
        return self.path(key, suffix).exists()

    def write_meta(self, key: str, suffix: str, meta: dict[str, Any]) -> None:
        meta = dict(meta)
        meta.setdefault("cached_at", datetime.now(UTC).isoformat(timespec="seconds"))
        self.meta_path(key, suffix).write_text(json.dumps(meta, indent=2))

    def read_meta(self, key: str, suffix: str) -> dict[str, Any]:
        p = self.meta_path(key, suffix)
        return json.loads(p.read_text()) if p.exists() else {}

    def get_bytes(
        self,
        key: str,
        suffix: str,
        producer: Callable[[], tuple[bytes, dict[str, Any]]],
    ) -> tuple[bytes, dict[str, Any]]:
        """Return cached bytes, or call `producer()` for (bytes, meta) and store."""
        p = self.path(key, suffix)
        if p.exists():
            return p.read_bytes(), self.read_meta(key, suffix)
        if self.offline:
            raise FileNotFoundError(f"offline: {p} not in cache")
        blob, meta = producer()
        p.write_bytes(blob)
        self.write_meta(key, suffix, meta)
        return blob, meta

    def get_json(
        self, key: str, producer: Callable[[], tuple[Any, dict[str, Any]]]
    ) -> tuple[Any, dict[str, Any]]:
        p = self.path(key, ".json")
        if p.exists():
            return json.loads(p.read_text()), self.read_meta(key, ".json")
        if self.offline:
            raise FileNotFoundError(f"offline: {p} not in cache")
        obj, meta = producer()
        p.write_text(json.dumps(obj))
        self.write_meta(key, ".json", meta)
        return obj, meta
