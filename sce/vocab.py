"""The fixed vocabularies every layer, metric, export and the web app key on.

Before this module, land-use class names lived in seven tables (provider,
metric, SVG, QML, sheet, two in the web app) and drifted: the provider emitted
"green" while the metric expected "green_space", the SVG coloured "park" and
"forest" which nothing emits, and farmland was filed as green so "agriculture"
could never appear. Every table is now derived from here, and the web app's
copy is generated (`python -m sce.vocab --ts`) and checked by a test.

Three vocabularies:

- land use: OSM tag -> class, plus each class's label and colours;
- building use: OSM `building` value -> class, plus labels and colours;
- height source: where a building's height came from.

Each class has two colours: `colour` for data views (the web map, charts) and
`sheet`, the muted tone used on the A3 sheet and in plan drawings (SVG, QML),
where land use is background to the figure-ground.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Klass:
    """One class in a vocabulary."""

    id: str
    label: str
    colour: str
    sheet: str


# Order matters: it is the disjoint allocation order used by the land-use
# metric (most specific first, each class claiming only unclaimed ground) and
# the legend order everywhere.
LANDUSE: tuple[Klass, ...] = (
    Klass("water", "Water", "#6fb1e4", "#a9c3d0"),
    Klass("green_space", "Green space", "#7fc98a", "#c3cfad"),
    Klass("transport", "Transport", "#8b9bb0", "#c4c4c4"),
    Klass("civic", "Civic and institutional", "#a78bfa", "#cfc6d3"),
    Klass("retail", "Retail", "#e58fb0", "#d3b7a8"),
    Klass("commercial", "Commercial", "#f0a35e", "#c9b8b0"),
    Klass("industrial", "Industrial", "#a8a29e", "#bdbdb4"),
    Klass("agriculture", "Agriculture", "#d8d27c", "#e6e2bd"),
    Klass("residential", "Residential", "#f3c89c", "#d8cfc0"),
    Klass("other", "Other", "#cbd5e1", "#dedad2"),
)
LANDUSE_IDS: tuple[str, ...] = tuple(k.id for k in LANDUSE)

# OSM key -> value -> land-use class. Keys are tried in this order.
OSM_LANDUSE_TAGS: dict[str, dict[str, str]] = {
    "landuse": {
        "residential": "residential",
        "commercial": "commercial",
        "retail": "retail",
        "industrial": "industrial",
        "railway": "transport",
        "religious": "civic",
        "education": "civic",
        "institutional": "civic",
        "governmental": "civic",
        "forest": "green_space",
        "grass": "green_space",
        "meadow": "green_space",
        "recreation_ground": "green_space",
        "allotments": "green_space",
        "flowerbed": "green_space",
        "village_green": "green_space",
        "farmland": "agriculture",
        "farmyard": "agriculture",
        "orchard": "agriculture",
        "vineyard": "agriculture",
        "cemetery": "other",
        "military": "other",
        "quarry": "other",
        "brownfield": "other",
        "construction": "other",
        "garages": "other",
    },
    "leisure": {"park": "green_space", "garden": "green_space", "pitch": "green_space"},
    "natural": {"water": "water", "wood": "green_space", "scrub": "green_space"},
}


def landuse_class(tags: dict[str, object]) -> str:
    """Land-use class for one OSM feature's tags; "other" when nothing matches."""
    for key, mapping in OSM_LANDUSE_TAGS.items():
        value = tags.get(key)
        if isinstance(value, str) and value in mapping:
            return mapping[value]
    return "other"


_TAG_VALUE_CLASS: dict[str, str] = {v: c for m in OSM_LANDUSE_TAGS.values() for v, c in m.items()}


def normalise_landuse(raw: object) -> str:
    """A vocabulary class for a stored class value or raw OSM tag value.

    Accepts class ids as-is, maps raw OSM values ("park", "farmland") through
    the tag table, and files anything else as "other".
    """
    s = str(raw).strip().lower() if raw is not None else ""
    if s in LANDUSE_IDS:
        return s
    return _TAG_VALUE_CLASS.get(s, "other")


BUILDING_USE: tuple[Klass, ...] = (
    Klass("residential", "Residential", "#0072b2", "#d8cfc0"),
    Klass("commercial", "Commercial and office", "#e69f00", "#c9b8b0"),
    Klass("retail", "Retail", "#cc79a7", "#d3b7a8"),
    Klass("industrial", "Industrial", "#d55e00", "#bdbdb4"),
    Klass("civic", "Civic, education and religious", "#009e73", "#cfc6d3"),
    Klass("other", "Other", "#56b4e9", "#dedad2"),
)
BUILDING_USE_IDS: tuple[str, ...] = tuple(k.id for k in BUILDING_USE)

_BUILDING_TAGS: dict[str, str] = {
    "residential": "residential house detached semidetached_house terrace terraced_house apartments flats "
    "bungalow dormitory houseboat static_caravan cabin farm",
    "commercial": "commercial office offices hotel bank",
    "retail": "retail supermarket kiosk shop mall",
    "industrial": "industrial warehouse factory manufacture service storage_tank",
    "civic": "civic public government school university college kindergarten hospital church chapel "
    "cathedral mosque synagogue temple religious monastery fire_station train_station transportation "
    "museum library theatre sports_hall",
}
# OSM `building` value -> building use. `yes` and unknown values are absent.
BUILDING_TAG_USE: dict[str, str] = {tag: use for use, tags in _BUILDING_TAGS.items() for tag in tags.split()}

# Where a building height came from. `unknown` covers every building with no height.
HEIGHT_SOURCE: tuple[Klass, ...] = (
    Klass("height", "Measured (height tag)", "#2563eb", "#2563eb"),
    Klass("lidar", "Measured (LiDAR)", "#1d4ed8", "#1d4ed8"),
    Klass("levels", "From storeys (levels × 3 m)", "#0d9488", "#0d9488"),  # noqa: RUF001
    Klass("unknown", "No height data", "#fecdd3", "#fecdd3"),
)
HEIGHT_SOURCE_IDS: tuple[str, ...] = tuple(k.id for k in HEIGHT_SOURCE)


def colours(vocab: tuple[Klass, ...], *, sheet: bool = False) -> dict[str, str]:
    """id -> hex colour for a vocabulary."""
    return {k.id: (k.sheet if sheet else k.colour) for k in vocab}


def labels(vocab: tuple[Klass, ...]) -> dict[str, str]:
    """id -> human label for a vocabulary."""
    return {k.id: k.label for k in vocab}


def to_typescript() -> str:
    """The web app's copy of these vocabularies, as typed TS constants."""

    def arr(vocab: tuple[Klass, ...]) -> str:
        rows = [f'  {{ id: "{k.id}", label: {json.dumps(k.label)}, colour: "{k.colour}" }},' for k in vocab]
        return "[\n" + "\n".join(rows) + "\n] as const"

    tags = json.dumps(BUILDING_TAG_USE, indent=2, sort_keys=True)
    return (
        "// GENERATED by `python -m sce.vocab --ts > web/lib/vocab.generated.ts`. Do not edit.\n"
        "// Source of truth: sce/vocab.py. tests/unit/test_vocab.py fails if this file is stale.\n\n"
        f"export const LANDUSE = {arr(LANDUSE)};\n"
        'export type LanduseId = (typeof LANDUSE)[number]["id"];\n\n'
        f"export const BUILDING_USE = {arr(BUILDING_USE)};\n"
        'export type BuildingUseId = (typeof BUILDING_USE)[number]["id"];\n\n'
        f"export const HEIGHT_SOURCE = {arr(HEIGHT_SOURCE)};\n"
        'export type HeightSourceId = (typeof HEIGHT_SOURCE)[number]["id"];\n\n'
        f"export const BUILDING_TAG_USE: Record<string, BuildingUseId> = {tags};\n"
    )


if __name__ == "__main__":  # pragma: no cover - exercised via test_vocab
    if "--ts" in sys.argv:
        sys.stdout.write(to_typescript())
    else:
        print(__doc__)
