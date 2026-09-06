"""Shared height parsing for building providers.

Not a provider itself; imported by osm_buildings and overture_buildings so the
"height tag, else levels * 3.0 m" rule is defined exactly once.
"""

from __future__ import annotations

import re

import pandas as pd

LEVEL_HEIGHT_M = 3.0

_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def parse_height_tag(value: object) -> float | None:
    """Parse an OSM/Overture free-text height into metres, or None.

    Handles bare numbers ("12.5"), metre-suffixed values ("12 m", "12m"),
    and rejects anything else (feet/inches, ranges, garbage) rather than
    guessing — an unparsed height must surface as missing, not zero.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    if "'" in text or '"' in text or "ft" in text.lower():
        return None
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def parse_levels_tag(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def height_and_source(height_raw: object, levels_raw: object) -> tuple[float, str]:
    """Return (height_m, height_source) applying the height-then-levels rule."""
    h = parse_height_tag(height_raw)
    if h is not None and h > 0:
        return h, "height"
    lv = parse_levels_tag(levels_raw)
    if lv is not None and lv > 0:
        return lv * LEVEL_HEIGHT_M, "levels"
    return float("nan"), ""
