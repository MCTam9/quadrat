"""Overpass endpoint fallback shared by every OSM provider.

The public overpass-api.de instance regularly answers "at capacity" (502/504)
under load, and a hosted app hitting it from shared cloud IPs makes that more
likely. Retrying the same query against a second free public instance turns a
failed report into a slightly slower one. Endpoints come from the
`SCE_OVERPASS_URLS` environment variable (comma-separated, tried in order).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import osmnx as ox

log = logging.getLogger("sce.providers.overpass")

PRIMARY = "https://overpass-api.de/api"
DEFAULT_URLS = (PRIMARY, "https://maps.mail.ru/osm/tools/overpass/api")
# Short enough that a dead mirror does not eat a serverless function's budget.
DEFAULT_TIMEOUT_S = 90
# After a failure, try an endpoint last for this long so every layer of a
# report does not wait out the same dead server again.
COOLDOWN_S = 600.0

_down_until: dict[str, float] = {}


def overpass_urls() -> list[str]:
    """Endpoints to try, in order."""
    raw = os.environ.get("SCE_OVERPASS_URLS", "")
    urls = [u.strip().rstrip("/") for u in raw.split(",") if u.strip()] or list(DEFAULT_URLS)
    now = time.monotonic()
    # Stable sort: healthy endpoints keep their order, recently failed ones go last.
    return sorted(urls, key=lambda u: _down_until.get(u, 0.0) > now)


def configure_osmnx(cache: Any) -> None:
    """Point osmnx's on-disk response cache at the sce cache."""
    ox.settings.cache_folder = str(cache.root / "osmnx")
    ox.settings.use_cache = True
    (cache.root / "osmnx").mkdir(parents=True, exist_ok=True)
    ox.settings.requests_timeout = int(os.environ.get("SCE_OVERPASS_TIMEOUT", DEFAULT_TIMEOUT_S))
    ox.settings.http_user_agent = "sce-site-context-report"


class _SettingsGate:
    """Share osmnx's global endpoint settings between concurrent queries safely.

    osmnx reads `ox.settings.overpass_url` while it makes the request, so two
    threads wanting different endpoints would overwrite each other. Threads that
    want the SAME endpoint (the normal case: streets and the feature query both
    on the primary) share the settings and run in parallel; a thread that wants
    a different one waits until the others finish. The original settings are
    restored when the last query leaves.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._active = 0
        self._url: str | None = None
        self._original: tuple[Any, Any] | None = None

    def enter(self, url: str) -> None:
        with self._cond:
            while self._active and self._url != url:
                self._cond.wait()
            if not self._active:
                self._original = ox.settings.overpass_url, ox.settings.overpass_rate_limit
                self._url = url
                ox.settings.overpass_url = url
                # osmnx's slot check sleeps until the server has capacity, which on an
                # overloaded instance can be minutes. Failing over is faster.
                ox.settings.overpass_rate_limit = False
            self._active += 1

    def leave(self) -> None:
        with self._cond:
            self._active -= 1
            if not self._active:
                assert self._original is not None
                ox.settings.overpass_url, ox.settings.overpass_rate_limit = self._original
                self._url = self._original = None
                self._cond.notify_all()


_gate = _SettingsGate()


def with_overpass_fallback[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Call an osmnx query function, moving to the next endpoint on failure.

    An empty result is a real answer, not an endpoint fault, so it is raised
    immediately rather than retried elsewhere. Safe to call from several threads.
    """
    from osmnx._errors import InsufficientResponseError

    errors: list[str] = []
    for url in overpass_urls():
        _gate.enter(url)
        try:
            return fn(*args, **kwargs)
        except InsufficientResponseError:
            raise
        except Exception as exc:
            _down_until[url] = time.monotonic() + COOLDOWN_S
            log.warning("Overpass %s failed: %s", url, str(exc).splitlines()[0][:200])
            errors.append(f"{url}: {str(exc).splitlines()[0][:200]}")
        finally:
            _gate.leave()
    raise RuntimeError("every Overpass endpoint failed: " + " | ".join(errors))


# -- one query for buildings, landuse and amenities ---------------------------

# Each feature provider registers its tag filter at import. Their union is one
# Overpass query; each provider then keeps the rows its own filter selects.
_FEATURE_TAGS: dict[str, dict[str, Any]] = {}
MEMO_MAX = 4
MEMO_TTL_S = 600.0
_memo: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_memo_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}


def register_feature_tags(name: str, tags: dict[str, Any]) -> None:
    _FEATURE_TAGS[name] = tags


def union_tags(*tag_dicts: dict[str, Any]) -> dict[str, Any]:
    """Merge osmnx tag filters: True (any value) absorbs a value list."""
    out: dict[str, Any] = {}
    for tags in tag_dicts:
        for key, val in tags.items():
            have = out.get(key)
            if val is True or have is True:
                out[key] = True
            elif have is None:
                out[key] = list(val) if isinstance(val, (list, tuple)) else [val]
            else:
                out[key] = list(dict.fromkeys([*have, *(val if isinstance(val, (list, tuple)) else [val])]))
    return out


def select_features(gdf: Any, tags: dict[str, Any]) -> Any:
    """Rows of `gdf` matching an osmnx-style tag filter, as the provider's own query would return.

    Columns that none of the selected rows carry are dropped, so the result has
    the columns a query for just these tags would have produced.
    """
    import pandas as pd

    mask = pd.Series(False, index=gdf.index)
    for key, val in tags.items():
        if key not in gdf.columns:
            continue
        col = gdf[key]
        mask |= col.notna() if val is True else col.isin(val if isinstance(val, (list, tuple)) else [val])
    out = gdf[mask].copy()
    keep = [c for c in out.columns if c == out.geometry.name or out[c].notna().any()]
    return out[keep]


def shared_features(polygon: Any, tags: dict[str, Any]) -> Any:
    """OSM features inside `polygon` matching `tags`, from one Overpass query shared by every provider.

    The first caller fetches the union of every registered feature provider's tags
    (plus its own); the others, and repeat calls for the same polygon, are served
    from an in-process memo, on top of osmnx's own on-disk response cache. Raises
    whatever the query raises (including `InsufficientResponseError` when the
    area has none of the tags); failures are not memoised.
    """
    all_tags = union_tags(*_FEATURE_TAGS.values(), tags)
    key = hashlib.sha1(f"{polygon.wkb_hex}|{sorted(all_tags.items(), key=str)}".encode()).hexdigest()
    with _memo_lock:
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:
        with _memo_lock:
            hit = _memo.get(key)
            if hit is not None and time.monotonic() - hit[0] < MEMO_TTL_S:
                _memo.move_to_end(key)
                gdf = hit[1]
            else:
                gdf = None
        if gdf is None:
            gdf = with_overpass_fallback(ox.features.features_from_polygon, polygon, tags=all_tags)
            with _memo_lock:
                _memo[key] = (time.monotonic(), gdf)
                while len(_memo) > MEMO_MAX:
                    _memo.popitem(last=False)
    return select_features(gdf, tags)
