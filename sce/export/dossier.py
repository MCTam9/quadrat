"""The machine-readable proof this is a pipeline, not a picture.

One JSON: schema version, tool version, git SHA, generation time, AOI
provenance, every metric, per-layer provenance, the deduplicated source list
with licences, and coverage warnings. Deterministic apart from the timestamp.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..types import LayerResult

SCHEMA_VERSION = 1


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _dedup_sources(layers: dict[str, LayerResult]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for result in layers.values():
        if result is None:
            continue
        for src in result.sources:
            key = (src.name, src.licence, src.url)
            if key not in seen:
                seen[key] = src.to_dict()
    return sorted(seen.values(), key=lambda d: (d["name"], d["licence"], d["url"]))


def _warnings_of(assessment) -> list[str]:
    if assessment is None:
        return []
    if isinstance(assessment, dict):
        return list(assessment.get("warnings") or [])
    return list(assessment)


def _coverage_of(assessment) -> dict:
    return dict(assessment.get("coverage") or {}) if isinstance(assessment, dict) else {}


def write_dossier(
    path: str | Path,
    aoi,
    layers: dict[str, LayerResult],
    metrics: dict[str, dict],
    assessment: dict | list[str] | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "git_sha": _git_sha(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "aoi": aoi.provenance(),
        "metrics": {k: metrics[k] for k in sorted(metrics)},
        "layers": {k: layers[k].provenance() for k in sorted(layers) if layers[k] is not None},
        "sources": _dedup_sources(layers),
        "coverage": _coverage_of(assessment),
        "degraded": bool(assessment.get("degraded")) if isinstance(assessment, dict) else False,
        "warnings": sorted(_warnings_of(assessment)),
    }

    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return path
