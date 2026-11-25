"""The CRS spine. Everything in sce depends on this module.

One metric CRS is chosen once per site, stamped on the AOI, and enforced by
tests. No metric anywhere in the codebase is permitted to accept geographic
(degree-based) input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import Polygon, shape
from shapely.ops import transform as shapely_transform

WGS84 = CRS.from_epsg(4326)

# Above this latitude UTM distortion and zone convergence make LAEA the safer
# choice; below it UTM is the projection a GIS reader expects to see named.
POLAR_LAT = 80.0


class NonMetricCRSError(ValueError):
    """Raised when geometry in a geographic CRS reaches metric code."""


def assert_metric_crs(crs: Any, *, where: str = "metric") -> CRS:
    """Reject geographic CRSs at the door of every metric.

    Called at the top of every metric function. `tests/meta/test_crs_contract.py`
    asserts that every registered metric raises when handed EPSG:4326.
    """
    if crs is None:
        raise NonMetricCRSError(f"{where}: geometry has no CRS; expected a projected metric CRS")
    crs = CRS.from_user_input(crs)
    if crs.is_geographic:
        raise NonMetricCRSError(
            f"{where}: refusing geographic CRS {crs.to_string()!r}. "
            "Areas and lengths in degrees are meaningless. Project to the AOI metric CRS first."
        )
    unit = {ax.unit_name for ax in crs.axis_info}
    if not unit <= {"metre", "meter"}:
        raise NonMetricCRSError(f"{where}: CRS {crs.to_string()!r} is not in metres (units={unit})")
    return crs


def utm_crs_for(lon: float, lat: float) -> CRS:
    """The UTM CRS whose zone contains this point."""
    zone = int(math.floor((lon + 180.0) / 6.0) % 60) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def laea_crs_for(lon: float, lat: float) -> CRS:
    """A centroid-centred Lambert Azimuthal Equal Area CRS, in metres."""
    return CRS.from_proj4(
        f"+proj=laea +lat_0={lat:.8f} +lon_0={lon:.8f} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )


def _utm_zone(lon: float) -> int:
    return int(math.floor((lon + 180.0) / 6.0) % 60) + 1


def choose_metric_crs(lon: float, lat: float, radius_m: float) -> CRS:
    """UTM by default; LAEA when the AOI crosses a zone boundary or is polar.

    A UTM zone is 6 degrees wide. If the AOI extends past its own zone, or sits
    above 80 degrees, UTM stops being defensible and we centre a LAEA on the site.
    """
    if abs(lat) >= POLAR_LAT:
        return laea_crs_for(lon, lat)
    # Degrees of longitude spanned by the radius at this latitude.
    cos_lat = max(math.cos(math.radians(lat)), 1e-9)
    dlon = math.degrees(radius_m / (6_378_137.0 * cos_lat))
    if _utm_zone(lon - dlon) != _utm_zone(lon) or _utm_zone(lon + dlon) != _utm_zone(lon):
        return laea_crs_for(lon, lat)
    return utm_crs_for(lon, lat)


def true_north_square(lon: float, lat: float, half_width_m: float, crs: CRS) -> Polygon:
    """A square of ground half-width `half_width_m`, sides aligned to TRUE north,
    expressed in `crs`.

    UTM grid north departs from true north by the grid convergence (2.25 deg in
    central London, ~3 deg at a zone edge), so a box drawn in UTM coordinates is
    visibly rotated against a north-up map and against the square a user drew on
    it. Building the square in an azimuthal equidistant projection centred on
    the site (true north up, true distances from the centre) and projecting its
    corners keeps the standard EPSG grid for every export while the site itself
    is the upright square the user selected. In the AOI CRS it is a square
    rotated by the convergence, so code must use `aoi.geometry`, never assume an
    axis-aligned box; `bounds_metric` is its (slightly larger) bounding box.
    `half_width_m` is in the AOI CRS's metres, like every other length in sce:
    the local square is divided by the CRS point scale factor (UTM 0.9996 to
    ~1.001) so a 600 m site measures exactly 600 in the DXF and its area is
    exactly (2r)^2, as `aoi.area_m2` has always promised.
    """
    from pyproj import Proj

    local = CRS.from_proj4(f"+proj=aeqd +lat_0={lat:.9f} +lon_0={lon:.9f} +datum=WGS84 +units=m +no_defs")
    tf = Transformer.from_crs(local, crs, always_xy=True)
    k = math.sqrt(Proj(crs).get_factors(lon, lat).areal_scale)
    r = half_width_m / k
    # Four corners only: a straight edge in the local projection bends by well
    # under a millimetre in UTM over a few kilometres, and CAD users expect a
    # four-vertex boundary.
    return Polygon([tf.transform(x, y) for x, y in ((-r, -r), (r, -r), (r, r), (-r, r))])


@dataclass(frozen=True)
class AOI:
    """An area of interest with exactly one metric CRS, chosen once.

    `geometry` is always in `crs` (the metric CRS). `centroid_lonlat` keeps the
    WGS84 anchor for provider queries that speak degrees, so no other module
    ever has to reproject back by hand.
    """

    name: str
    geometry: Polygon
    crs: CRS
    centroid_lonlat: tuple[float, float]
    radius_m: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert_metric_crs(self.crs, where=f"AOI({self.name})")
        if self.geometry.is_empty:
            raise ValueError(f"AOI({self.name}): empty geometry")

    @classmethod
    def from_point(
        cls, lon: float, lat: float, radius_m: float, name: str = "site", *, crs: CRS | None = None
    ) -> AOI:
        """Buffer the PROJECTED centre, never degrees.

        The single most common geospatial error is buffering a lon/lat point by
        a value meant as metres. Doing it here, once, in projected space, means
        no caller can make that mistake.

        `crs` pins the metric CRS instead of choosing one. The web app fetches a
        padded square once and clips smaller squares out of it; the inner squares
        must share the padded square's CRS or the clip would silently reproject.
        """
        if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
            raise ValueError(f"lon/lat out of range: {lon},{lat}")
        if radius_m <= 0:
            raise ValueError("radius_m must be positive")
        crs = choose_metric_crs(lon, lat, radius_m) if crs is None else CRS.from_user_input(crs)
        geom = true_north_square(lon, lat, radius_m, crs)
        return cls(
            name=name,
            geometry=geom,
            crs=crs,
            centroid_lonlat=(lon, lat),
            radius_m=radius_m,
            meta={"kind": "point-square", "requested_radius_m": radius_m},
        )

    @classmethod
    def from_geojson(cls, obj: dict[str, Any], name: str = "site") -> AOI:
        """Build an AOI from a WGS84 GeoJSON geometry or Feature."""
        if obj.get("type") == "FeatureCollection":
            geoms = [shape(f["geometry"]) for f in obj["features"]]
            geom_ll = geoms[0] if len(geoms) == 1 else _union(geoms)
        elif obj.get("type") == "Feature":
            geom_ll = shape(obj["geometry"])
        else:
            geom_ll = shape(obj)
        lon, lat = geom_ll.centroid.x, geom_ll.centroid.y
        minx, miny, maxx, maxy = geom_ll.bounds
        approx_radius = max(maxx - minx, maxy - miny) / 2 * 111_320
        crs = choose_metric_crs(lon, lat, approx_radius)
        tf = Transformer.from_crs(WGS84, crs, always_xy=True)
        geom = shapely_transform(lambda x, y, z=None: tf.transform(x, y), geom_ll)
        return cls(
            name=name,
            geometry=geom,
            crs=crs,
            centroid_lonlat=(lon, lat),
            radius_m=None,
            meta={"kind": "geojson"},
        )

    # -- derived values every provider and metric shares -------------------

    @property
    def epsg(self) -> str:
        code = self.crs.to_epsg()
        return f"EPSG:{code}" if code else self.crs.to_string()

    @property
    def area_m2(self) -> float:
        """The one area denominator. Every density metric divides by this."""
        return float(self.geometry.area)

    @property
    def area_ha(self) -> float:
        return self.area_m2 / 10_000.0

    @property
    def area_km2(self) -> float:
        return self.area_m2 / 1e6

    @property
    def bounds_metric(self) -> tuple[float, float, float, float]:
        return tuple(self.geometry.bounds)  # type: ignore[return-value]

    @property
    def bbox_wgs84(self) -> tuple[float, float, float, float]:
        """west, south, east, north. What Overture, Overpass and STAC want."""
        tf = Transformer.from_crs(self.crs, WGS84, always_xy=True)
        geom_ll = shapely_transform(lambda x, y, z=None: tf.transform(x, y), self.geometry)
        return tuple(geom_ll.bounds)  # type: ignore[return-value]

    @property
    def geometry_wgs84(self) -> Polygon:
        tf = Transformer.from_crs(self.crs, WGS84, always_xy=True)
        return shapely_transform(lambda x, y, z=None: tf.transform(x, y), self.geometry)

    def to_metric(self, gdf):
        """Reproject a GeoDataFrame into this AOI's metric CRS."""
        if gdf is None or len(gdf) == 0:
            return gdf
        if gdf.crs is None:
            raise NonMetricCRSError(f"AOI({self.name}).to_metric: GeoDataFrame has no CRS")
        return gdf.to_crs(self.crs)

    def clip(self, gdf):
        """Clip to the AOI square after asserting the CRS matches."""
        if gdf is None or len(gdf) == 0:
            return gdf
        assert_metric_crs(gdf.crs, where=f"AOI({self.name}).clip")
        if CRS.from_user_input(gdf.crs) != self.crs:
            gdf = gdf.to_crs(self.crs)
        return gdf.clip(self.geometry)

    def key(self) -> str:
        """A stable identity for cache keys."""
        lon, lat = self.centroid_lonlat
        r = self.radius_m if self.radius_m is not None else round(self.geometry.length, 1)
        return f"{lon:.6f},{lat:.6f},r{r},{self.epsg}"

    def provenance(self) -> dict[str, Any]:
        lon, lat = self.centroid_lonlat
        return {
            "name": self.name,
            "lon": lon,
            "lat": lat,
            "radius_m": self.radius_m,
            "crs": self.epsg,
            "crs_wkt_name": self.crs.name,
            "area_ha": round(self.area_ha, 2),
            "area_km2": round(self.area_km2, 4),
            "bbox_wgs84": [round(v, 6) for v in self.bbox_wgs84],
            **self.meta,
        }


def _union(geoms):
    from shapely.ops import unary_union

    return unary_union(geoms)
