"""Snapshot storage: keep a loaded `Site` somewhere every serverless instance can reach.

Snapshots are an optimisation, never a dependency: every failure is logged as a
warning and reported as a miss, so a request can never break on the store.

`BlobStore` speaks Vercel Blob's HTTP API directly with `requests`, exactly as the
official `@vercel/blob` client does (the PyPI `vercel-blob` SDK would drag in
anyio, httpx2 and pydantic for two calls, and has no TTL option):

- put: `PUT https://vercel.com/api/blob/?pathname=<path>` with the bearer token and
  `x-api-version`, `x-vercel-blob-access: private`, `x-add-random-suffix: 0`,
  `x-allow-overwrite: 1`, `x-ttl-days: 7` (the platform deletes the blob after 7 days,
  so there is no cleanup code; an overwrite restarts the clock).
- get: `GET https://<store id>.private.blob.vercel-storage.com/<path>` with the bearer
  token. The store id is embedded in the token (`vercel_blob_rw_<id>_<secret>`).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

log = logging.getLogger("sce.store")

TIMEOUT_S = 20.0
TTL_DAYS = 7
API_URL = "https://vercel.com/api/blob"
API_VERSION = "12"
_TOKEN_PREFIX = "vercel_blob_rw_"


class SnapshotStore(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, data: bytes) -> None: ...


def sanitise_key(key: str) -> str:
    """A site key (`-0.10000,51.50000,1500`) as a safe file/blob name stem."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("._") or "site"


def pathname_for(key: str) -> str:
    return f"sites/{sanitise_key(key)}.zip"


class LocalStore:
    """A directory of snapshots, for development and tests."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / pathname_for(key)

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("snapshot read failed: %s", exc)
            return None

    def put(self, key: str, data: bytes) -> None:
        try:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError as exc:
            log.warning("snapshot write failed: %s", exc)


class BlobStore:
    """A private Vercel Blob store. `session` is anything with `requests`' `put`/`get`/`post`."""

    def __init__(self, token: str, *, session: Any = None, api_url: str | None = None) -> None:
        import requests

        self._token = token
        self._session = session or requests.Session()
        self._api_url = (api_url or os.environ.get("VERCEL_BLOB_API_URL") or API_URL).rstrip("/")
        self._store_id = self._store_id_from(token)

    @staticmethod
    def _store_id_from(token: str) -> str:
        if not token.startswith(_TOKEN_PREFIX):
            raise ValueError("not a Vercel Blob read-write token")
        store_id, sep, _ = token[len(_TOKEN_PREFIX) :].partition("_")
        if not sep or not store_id:
            raise ValueError("not a Vercel Blob read-write token")
        return store_id.lower()

    def _auth(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._token}"}

    def blob_url(self, key: str) -> str:
        path = quote(pathname_for(key), safe="/")
        return f"https://{self._store_id}.private.blob.vercel-storage.com/{path}"

    def get(self, key: str) -> bytes | None:
        try:
            r = self._session.get(self.blob_url(key), headers=self._auth(), timeout=TIMEOUT_S)
            if r.status_code == 404:
                return None
            if r.status_code != 200:
                log.warning("blob get failed: HTTP %s", r.status_code)
                return None
            return bytes(r.content)
        except Exception as exc:
            log.warning("blob get failed: %s", type(exc).__name__)
            return None

    def put(self, key: str, data: bytes) -> None:
        headers = {
            **self._auth(),
            "x-api-version": API_VERSION,
            "x-vercel-blob-access": "private",
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "x-content-type": "application/zip",
            "x-ttl-days": str(TTL_DAYS),
        }
        try:
            r = self._session.put(
                f"{self._api_url}/",
                params={"pathname": pathname_for(key)},
                headers=headers,
                data=data,
                timeout=TIMEOUT_S,
            )
            if not 200 <= r.status_code < 300:
                log.warning("blob put failed: HTTP %s", r.status_code)
        except Exception as exc:
            log.warning("blob put failed: %s", type(exc).__name__)

    def delete(self, key: str) -> None:
        """Remove a snapshot (used by the smoke test; the TTL handles normal expiry)."""
        try:
            self._session.post(
                f"{self._api_url}/delete",
                headers={**self._auth(), "x-api-version": API_VERSION},
                json={"urls": [self.blob_url(key)]},
                timeout=TIMEOUT_S,
            )
        except Exception as exc:
            log.warning("blob delete failed: %s", type(exc).__name__)


def default_store() -> SnapshotStore | None:
    """Blob when its token is set, else a local directory under SCE_CACHE; None when disabled."""
    if os.environ.get("SCE_SNAPSHOTS") == "0":
        return None
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if token:
        try:
            return BlobStore(token)
        except ValueError as exc:
            log.warning("snapshots disabled: %s", exc)
            return None
    return LocalStore(Path(os.environ.get("SCE_CACHE", "~/.cache/sce")).expanduser() / "snapshots")
