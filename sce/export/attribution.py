"""Generate ATTRIBUTION.md from the provider registry. Ends the manual chore.

Grouped by licence so a reader can see at a glance which exports (GPKG, DXF)
inherit ODbL share-alike from OpenStreetMap-derived layers.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

_ODBL_MARKERS = ("odbl", "open database licence", "openstreetmap")


def _is_odbl(licence: str) -> bool:
    return any(marker in licence.lower() for marker in _ODBL_MARKERS)


def generate_attribution(registry, path: str | Path) -> Path:
    """Walk `registry.providers()` and write a licence-grouped ATTRIBUTION.md."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    by_licence: dict[str, list] = defaultdict(list)
    for provider in registry.providers():
        by_licence[provider.licence or "Unknown licence"].append(provider)

    lines = [
        "# Attribution",
        "",
        "Data sources and licences used by this tool. Generated from the provider",
        "registry by `sce attribution`; do not edit by hand.",
        "",
        "The tool's own source code is MIT (see LICENSE). That is separate from, and does",
        "not override, the terms below. Where they conflict, the data licence governs the",
        "data.",
        "",
    ]

    has_odbl = any(_is_odbl(lic) for lic in by_licence)
    if has_odbl:
        lines += [
            "## Notice: OpenStreetMap-derived data",
            "",
            "This tool's GeoPackage and DXF exports may contain data derived from "
            "OpenStreetMap, (c) OpenStreetMap contributors, licensed under the Open "
            "Database Licence (ODbL). Any export that includes an OSM-derived layer "
            "is a produced work under ODbL and must be shared under the same "
            "share-alike licence, with attribution to OpenStreetMap "
            "contributors, when redistributed.",
            "",
        ]

    for licence in sorted(by_licence):
        lines.append(f"## {licence}")
        lines.append("")
        for provider in sorted(by_licence[licence], key=lambda p: (p.layer, p.name)):
            commercial = "commercial use permitted" if provider.commercial_ok else "non-commercial only"
            credit = f" — {provider.credit}" if getattr(provider, "credit", "") else ""
            lines.append(f"- **{provider.name}** (layer: `{provider.layer}`) — {commercial}{credit}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n")
    return path
