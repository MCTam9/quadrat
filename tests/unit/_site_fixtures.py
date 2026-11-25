"""Fixture layers for a site, in the AOI's CRS, named after real providers.

Shared by tests/unit/test_site.py and tests/unit/test_api.py. Real provider
names matter: clipping asks the named provider to re-summarise each layer.
"""

from __future__ import annotations

import geopandas as gpd
import networkx as nx
import numpy as np
from affine import Affine
from shapely.geometry import LineString, box

from sce.types import LayerResult, Source

LON, LAT = -0.1, 51.5


def site_layers(aoi):
    """Buildings, streets+graph, terrain, land use, constraints and 3 years of climate."""
    cx, cy = aoi.geometry.centroid.x, aoi.geometry.centroid.y
    blds = gpd.GeoDataFrame(
        {
            "height_m": [9.0, np.nan, 30.0],
            "height_source": ["height", "", "height"],
            "building": ["residential", "yes", "office"],
            "building:levels": ["3", None, "10"],
        },
        geometry=[
            box(cx - 50, cy - 50, cx - 30, cy - 30),
            box(cx + 100, cy + 100, cx + 130, cy + 130),
            box(cx + 1000, cy + 1000, cx + 1040, cy + 1040),
        ],
        crs=aoi.crs,
    )
    g = nx.MultiDiGraph(crs=aoi.crs)
    g.add_node(1, x=cx, y=cy)
    g.add_node(2, x=cx + 100, y=cy)
    g.add_edge(1, 2, length=100.0)
    streets = gpd.GeoDataFrame(
        {"highway": ["residential"]}, geometry=[LineString([(cx, cy), (cx + 100, cy)])], crs=aoi.crs
    )
    minx, miny, maxx, maxy = aoi.bounds_metric
    res = 30.0
    n = int((maxx - minx) / res)
    yy, xx = np.mgrid[0:n, 0:n]
    terrain = {
        "array": (xx * 0.5 + yy * 0.2).astype(float),
        "transform": Affine(res, 0, minx, 0, -res, maxy),
        "crs": aoi.crs,
        "nodata": None,
        "res": (res, res),
    }
    osm = Source("OpenStreetMap contributors", "https://www.openstreetmap.org/copyright", "ODbL 1.0")
    landuse = gpd.GeoDataFrame(
        {"class": ["park", "residential"]},
        geometry=[box(cx - 200, cy - 200, cx, cy), box(cx, cy, cx + 200, cy + 200)],
        crs=aoi.crs,
    )
    constraints = gpd.GeoDataFrame(
        {"dataset": ["conservation-area"], "name": ["Test CA"]},
        geometry=[box(cx - 100, cy - 100, cx + 100, cy + 100)],
        crs=aoi.crs,
    )
    hours = 3 * 8760
    t = np.arange(hours)
    hourly = {
        "time": np.datetime64("2021-01-01T00:00") + t.astype("timedelta64[h]"),
        "temperature_c": 10
        + 8 * np.sin(2 * np.pi * (t / 8760 - 0.3))
        + 4 * np.sin(2 * np.pi * (t % 24) / 24),
        "dew_point_c": 5 + 6 * np.sin(2 * np.pi * (t / 8760 - 0.3)),
        "relative_humidity_pct": np.full(hours, 75.0),
        "pressure_pa": np.full(hours, 101300.0),
        "ghi_wm2": np.clip(400 * np.sin(2 * np.pi * ((t % 24) - 6) / 24), 0, None),
        "dni_wm2": np.clip(300 * np.sin(2 * np.pi * ((t % 24) - 6) / 24), 0, None),
        "dhi_wm2": np.clip(100 * np.sin(2 * np.pi * ((t % 24) - 6) / 24), 0, None),
        "wind_speed_ms": np.full(hours, 4.0),
        "wind_direction_deg": np.full(hours, 225.0),
        "cloud_cover_pct": np.full(hours, 60.0),
        "precipitation_mm": np.full(hours, 0.1),
    }
    climate = LayerResult(
        "climate",
        "fake",
        data={
            "hourly": hourly,
            "timezone": {"name": "Europe/London", "standard_offset_h": 0.0, "approximate": False},
            "elevation_m": 16.0,
            "grid_point_lonlat": [LON, LAT],
            "period": "2021-01-01 to 2023-12-31",
        },
        sources=[Source("Open-Meteo ERA5 archive", "https://open-meteo.com", "CC BY 4.0")],
    )
    return {
        "climate": climate,
        "landuse": LayerResult("landuse", "osm_landuse", gdf=landuse, sources=[osm]),
        "constraints": LayerResult("constraints", "uk_planning_data", gdf=constraints),
        "buildings": LayerResult("buildings", "osm_buildings", gdf=blds, coverage=2 / 3, sources=[osm]),
        "streets": LayerResult("streets", "osm_streets", gdf=streets, data={"graph": g}, sources=[osm]),
        "terrain": LayerResult("terrain", "copernicus_terrain", raster=terrain, data={}),
    }
