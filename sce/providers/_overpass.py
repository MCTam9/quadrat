"""Overpass endpoint fallback shared by every OSM provider.

The public overpass-api.de instance regularly answers "at capacity" (502/504)
under load, and a hosted app hitting it from shared cloud IPs makes that more
likely. Retrying the same query against a second free public instance turns a
failed report into a slightly slower one. Endpoints come from the
`SCE_OVERPASS_URLS` environment variable (comma-separated, tried in order).
"""

from __future__ import annotations

import logging
import os
import time
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


def with_overpass_fallback[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Call an osmnx query function, moving to the next endpoint on failure.

    An empty result is a real answer, not an endpoint fault, so it is raised
    immediately rather than retried elsewhere.
    """
    from osmnx._errors import InsufficientResponseError

    errors: list[str] = []
    original = ox.settings.overpass_url, ox.settings.overpass_rate_limit
    try:
        for url in overpass_urls():
            ox.settings.overpass_url = url
            # osmnx's slot check sleeps until the server has capacity, which on an
            # overloaded instance can be minutes. Failing over is faster.
            ox.settings.overpass_rate_limit = False
            try:
                return fn(*args, **kwargs)
            except InsufficientResponseError:
                raise
            except Exception as exc:
                _down_until[url] = time.monotonic() + COOLDOWN_S
                log.warning("Overpass %s failed: %s", url, str(exc).splitlines()[0][:200])
                errors.append(f"{url}: {str(exc).splitlines()[0][:200]}")
    finally:
        ox.settings.overpass_url, ox.settings.overpass_rate_limit = original
    raise RuntimeError("every Overpass endpoint failed: " + " | ".join(errors))
