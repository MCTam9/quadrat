"""Metric registry and the top-level `compute_all` entry point.

Every metric function takes `(layers, aoi)` and declares the layers it needs
as a `REQUIRES` tuple attribute, so `compute_all` can skip cleanly when a
provider chain came up empty rather than raising deep inside a metric.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..aoi import AOI
from ..types import LayerResult
from .access import access_metrics
from .climate import climate_metrics
from .fabric import fabric_metrics
from .landuse import landuse_metrics
from .street import street_metrics
from .terrain import terrain_metrics

log = logging.getLogger("sce.metrics")

METRICS: dict[str, Callable[[dict[str, LayerResult], AOI], dict[str, Any]]] = {
    "street": street_metrics,
    "fabric": fabric_metrics,
    "landuse": landuse_metrics,
    "access": access_metrics,
    "terrain": terrain_metrics,
    "climate": climate_metrics,
}


def compute_all(layers: dict[str, LayerResult], aoi: AOI) -> dict[str, Any]:
    """Run every metric whose required layers are present.

    Never lets one metric's failure abort the run: a raised exception is
    caught, logged, and recorded under `"errors"` keyed by metric name, and
    every other metric still runs.
    """
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for name, fn in METRICS.items():
        requires: tuple[str, ...] = getattr(fn, "REQUIRES", ())
        missing = [layer for layer in requires if layer not in layers or layers[layer] is None]
        if missing:
            log.info("skipping metric %s: missing layers %s", name, missing)
            continue
        try:
            results[name] = fn(layers, aoi)
        except Exception as exc:  # noqa: BLE001 - one metric's failure must not abort the run
            log.warning("metric %s failed: %s", name, exc)
            errors[name] = f"{type(exc).__name__}: {exc}"

    results["errors"] = errors
    return results
