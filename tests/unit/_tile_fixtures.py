"""Tiny synthetic OpenMapTiles tiles for the offline tests.

Two neighbouring z14 tiles, `TX` and `TX + 1`, in one row. The AOI is centred on the seam
between them, so both are fetched. Geometry is in tile pixels with y down, 4096 per tile,
and every layer carries the 64 px buffer real tiles have, so the same cut and dedupe code
runs as on real data.
"""

from __future__ import annotations

import mapbox_vector_tile
from shapely.geometry import LineString, MultiPolygon, Point, box

from sce.aoi import AOI
from sce.providers import openfreemap_tiles as t

TX, TY = t.lonlat_to_tile(-0.1, 51.5)
VERSION = "20260101_000000_pt"
TEMPLATE = f"https://tiles.example/planet/{VERSION}/{{z}}/{{x}}/{{y}}.pbf"

_W, _S, _E, _N = t.tile_bounds_lonlat(TX + 1, TY)
SEAM_LON = _W
MID_LAT = (_S + _N) / 2


def aoi(radius_m: float = 500.0) -> AOI:
    """A square centred on the seam between the two tiles."""
    return AOI.from_point(SEAM_LON, MID_LAT, radius_m, name="seam")


def west_tile() -> bytes:
    """Tile TX (the west one)."""
    return mapbox_vector_tile.encode(
        [
            {
                "name": "building",
                "features": [
                    {
                        # One feature, two far-apart parts (merged by the tile builder), the second
                        # running over the east edge into the buffer.
                        "geometry": MultiPolygon([box(3000, 1000, 3100, 1100), box(4000, 1000, 4160, 1100)]),
                        "properties": {"render_height": 12, "render_min_height": 0},
                    },
                    {
                        # Same place on the seam, different attributes: must not merge with the above.
                        "geometry": box(4000, 1200, 4160, 1300),
                        "properties": {"render_height": 5, "render_min_height": 0},
                    },
                    {
                        # A raised roof part: dropped.
                        "geometry": box(3200, 1400, 3260, 1460),
                        "properties": {"render_height": 30, "render_min_height": 20},
                    },
                    {
                        # No height.
                        "geometry": box(3300, 1500, 3360, 1560),
                        "properties": {"render_height": 0, "render_min_height": 0},
                    },
                ],
            },
            {
                "name": "transportation",
                "features": [
                    {
                        "geometry": LineString([(3000, 2048), (4160, 2048)]),
                        "properties": {"class": "primary"},
                    },
                    {"geometry": LineString([(3000, 3000), (3900, 3000)]), "properties": {"class": "minor"}},
                    {
                        "geometry": LineString([(3000, 3200), (3900, 3200)]),
                        "properties": {"class": "path", "subclass": "footway"},
                    },
                    {"geometry": LineString([(3000, 3300), (3900, 3300)]), "properties": {"class": "rail"}},
                ],
            },
            {
                "name": "landuse",
                "features": [
                    {"geometry": box(2900, 900, 3800, 1900), "properties": {"class": "residential"}},
                    {"geometry": box(3900, 900, 4000, 1000), "properties": {"class": "neighbourhood"}},
                ],
            },
            {
                "name": "landcover",
                "features": [
                    {
                        "geometry": box(3100, 2500, 3400, 2800),
                        "properties": {"class": "grass", "subclass": "park"},
                    }
                ],
            },
            {
                "name": "park",
                "features": [{"geometry": box(3500, 2500, 3700, 2700), "properties": {"class": "park"}}],
            },
            {
                "name": "water",
                "features": [{"geometry": box(3000, 3000, 3300, 3250), "properties": {"class": "river"}}],
            },
            {
                "name": "poi",
                "features": [
                    {
                        "geometry": Point(3500, 1800),
                        "properties": {"class": "cafe", "subclass": "cafe", "name": "C"},
                    },
                    {
                        "geometry": Point(3550, 1850),
                        "properties": {"class": "bollard", "subclass": "bollard"},
                    },
                    # In the buffer: the east tile owns this one (it has it at x = 4).
                    {
                        "geometry": Point(4100, 1500),
                        "properties": {"class": "pharmacy", "subclass": "pharmacy"},
                    },
                ],
            },
        ],
        default_options={"y_coord_down": True},
    )


def east_tile() -> bytes:
    """Tile TX + 1 (the east one)."""
    return mapbox_vector_tile.encode(
        [
            {
                "name": "building",
                "features": [
                    {
                        # The rest of the first building, starting in the buffer.
                        "geometry": box(-64, 1000, 96, 1100),
                        "properties": {"render_height": 12, "render_min_height": 0},
                    },
                    {
                        "geometry": box(-64, 1200, 96, 1300),
                        "properties": {"render_height": 5, "render_min_height": 0},
                    },
                ],
            },
            {
                "name": "transportation",
                "features": [
                    {"geometry": LineString([(-64, 2048), (1000, 2048)]), "properties": {"class": "primary"}}
                ],
            },
            {"name": "poi", "features": [{"geometry": Point(4, 1500), "properties": {"class": "pharmacy"}}]},
        ],
        default_options={"y_coord_down": True},
    )


class FakeNetwork:
    """Stands in for the two HTTP calls; counts them."""

    def __init__(self, tiles: dict[tuple[int, int], bytes] | None = None, delay: float = 0.0) -> None:
        self.tiles = tiles or {(TX, TY): west_tile(), (TX + 1, TY): east_tile()}
        self.delay = delay
        self.tilejson_calls = 0
        self.tile_calls: list[tuple[int, int]] = []

    def install(self, monkeypatch) -> FakeNetwork:
        import time

        def tilejson() -> dict:
            self.tilejson_calls += 1
            return {"tiles": [TEMPLATE], "maxzoom": 14}

        def tile(url: str) -> bytes:
            if self.delay:
                time.sleep(self.delay)
            parts = url.split("/")
            xy = (int(parts[-2]), int(parts[-1].removesuffix(".pbf")))
            self.tile_calls.append(xy)
            return self.tiles.get(xy, b"")

        monkeypatch.setattr(t, "_get_tilejson", tilejson)
        monkeypatch.setattr(t, "_get_tile", tile)
        monkeypatch.setattr(t, "_tilejson", None)
        t._memo.clear()
        return self
