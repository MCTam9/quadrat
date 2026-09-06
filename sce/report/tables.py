"""Turning the metric dictionaries into sheet rows.

Kept apart from the drawing code because deciding what deserves a line on the
sheet is an editorial judgement, not a layout one, and it changes more often.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Row:
    label: str
    value: str = ""
    note: str = ""
    is_section: bool = False


def _fmt(value: Any, spec: str = "{:.2f}", suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    try:
        return spec.format(value) + suffix
    except (TypeError, ValueError):
        return str(value)


# label, metric group, key, formatter, unit
SPEC: list[tuple[str, str, str, str, str]] = [
    ("__section__", "", "street network", "", ""),
    ("Intersection density", "street", "intersection_density_per_km2", "{:.0f}", " /km²"),
    ("Street length density", "street", "street_length_density_km_per_km2", "{:.1f}", " km/km²"),
    ("Mean segment length", "street", "segment_length_mean_m", "{:.0f}", " m"),
    ("Dead-end share", "street", "dead_end_share", "{:.1%}", ""),
    ("Orientation order φ", "street", "orientation_order_phi", "{:.2f}", ""),
    ("__section__", "", "built fabric", "", ""),
    ("Ground space index", "fabric", "gsi", "{:.2f}", ""),
    ("Floor space index", "fabric", "fsi", "{:.2f}", ""),
    ("Median footprint", "fabric", "footprint_area_median_m2", "{:.0f}", " m²"),
    ("Median block area", "fabric", "block_area_median_ha", "{:.2f}", " ha"),
    ("Blocks counted", "fabric", "block_count", "{:.0f}", ""),
    ("__section__", "", "access", "", ""),
    ("10-min walk reach", "access", "walk_reach_ratio", "{:.2f}", ""),
    ("Amenity categories", "access", "amenity_categories_reachable", "{:.0f}", ""),
    ("Nearest transport", "access", "transport_distance_m", "{:.0f}", " m"),
    ("__section__", "", "terrain", "", ""),
    ("Mean slope", "terrain", "slope_mean_deg", "{:.1f}", "°"),
    ("Area under 1:20", "terrain", "fraction_under_1_in_20", "{:.0%}", ""),
    ("Elevation range", "terrain", "elevation_range_m", "{:.0f}", " m"),
    ("Dominant aspect", "terrain", "dominant_aspect", "{}", ""),
    ("__section__", "", "climate", "", ""),
    ("Heating degree days", "climate", "hdd_18c", "{:.0f}", ""),
    ("Cooling degree days", "climate", "cdd_18c", "{:.0f}", ""),
    ("Annual GHI", "climate", "ghi_kwh_m2", "{:.0f}", " kWh/m²"),
    ("Prevailing wind", "climate", "prevailing_wind_direction", "{}", ""),
]

# Where a value is uncertain, the companion key that explains why.
NOTE_KEYS: dict[str, Callable[[dict], str]] = {
    "fsi": lambda m: (
        "" if m.get("fsi") is not None
        else f"height coverage {m.get('fsi_coverage', 0):.0%}, below 40% threshold"
    ),
}


def metric_rows(metrics: dict[str, Any]) -> list[Row]:
    """Build the sheet's schedule, dropping sections that produced nothing.

    A section with no data is omitted rather than printed full of dashes: an
    empty heading tells the reader nothing and costs a line of the sheet.
    """
    rows: list[Row] = []
    pending: Row | None = None
    section_had_content = False

    for label, group, key, spec, unit in SPEC:
        if label == "__section__":
            if pending is not None and not section_had_content:
                pass
            pending = Row(label=key, is_section=True)
            section_had_content = False
            continue
        group_metrics = metrics.get(group) or {}
        if key not in group_metrics:
            continue
        value = group_metrics.get(key)
        if pending is not None:
            rows.append(pending)
            pending = None
        section_had_content = True
        note = NOTE_KEYS.get(key, lambda _m: "")(group_metrics)
        rows.append(Row(label=label, value=_fmt(value, spec, unit), note=note))

    return rows
