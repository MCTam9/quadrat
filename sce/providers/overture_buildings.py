"""Building footprint provider, backed by the Overture Maps buildings theme.

Fallback for `osm_buildings` and, later, a height enricher for it: Overture's
buildings theme conflates OSM with Microsoft/Google building-footprint
datasets, so it can carry a height where OSM has none. Read directly from the
public S3 bucket as GeoParquet — no `overturemaps` CLI dependency, since the
contract says not to add one.

pyarrow is optional (`pip install 'sce[overture]'`) because it is ~170 MB and the hosted API
does not ship it. It is imported inside the functions that need it, and the provider only
registers when pyarrow is installed, so without it the building chain is OSM, then tiles.
"""

from __future__ import annotations

import importlib.util

import geopandas as gpd
import shapely

from ..registry import REGISTRY, Registry
from ..types import LayerResult, Provider, Source
from ._buildings import summarise_building_heights
from ._height import LEVEL_HEIGHT_M

BUCKET = "overturemaps-us-west-2"
# Bump when a newer release is known good; `_resolve_release` probes the
# bucket first and only falls back to this when listing fails.
DEFAULT_RELEASE = "2026-08-19.0"
THEME_PATH = "theme=buildings/type=building"
LICENCE_URL = "https://docs.overturemaps.org/attribution/"


def _resolve_release(s3) -> str:
    import pyarrow.fs as fs

    try:
        infos = s3.get_file_info(fs.FileSelector(f"{BUCKET}/release", recursive=False))
        releases = sorted(
            (info.path.rsplit("/", 1)[-1] for info in infos if info.type == fs.FileType.Directory),
        )
        if releases:
            return releases[-1]
    except Exception:
        pass
    return DEFAULT_RELEASE


def _height_from_row(height: float | None, num_floors: float | None) -> tuple[float, str]:
    if height is not None and height == height and height > 0:  # not NaN
        return float(height), "overture"
    if num_floors is not None and num_floors == num_floors and num_floors > 0:
        return float(num_floors) * LEVEL_HEIGHT_M, "overture"
    return float("nan"), ""


class OvertureBuildingsProvider(Provider):
    """Fallback building source, read as GeoParquet straight from S3."""

    name = "overture_buildings"
    layer = "buildings"
    licence = "ODbL 1.0"
    rank = 20
    commercial_ok = True

    def available(self, aoi) -> bool:
        return True

    def fetch(self, aoi, cache) -> LayerResult:
        import pyarrow.compute as pc
        import pyarrow.dataset as ds
        import pyarrow.fs as fs

        w, s, e, n = aoi.bbox_wgs84
        try:
            s3 = fs.S3FileSystem(anonymous=True, region="us-west-2")
            release = _resolve_release(s3)
            path = f"{BUCKET}/release/{release}/{THEME_PATH}/"
            dataset = ds.dataset(path, filesystem=s3, format="parquet", partitioning="hive")
            bbox_filter = (
                (pc.field("bbox", "xmin") < e)
                & (pc.field("bbox", "xmax") > w)
                & (pc.field("bbox", "ymin") < n)
                & (pc.field("bbox", "ymax") > s)
            )
            table = dataset.to_table(
                filter=bbox_filter,
                columns=["id", "geometry", "height", "num_floors", "subtype", "class"],
            )
        except Exception as exc:
            raise RuntimeError(f"overture_buildings: S3 read failed: {exc}") from exc

        if table.num_rows == 0:
            raise RuntimeError("overture_buildings: no building features returned for AOI bbox")

        df = table.to_pandas()
        geoms = shapely.from_wkb(df["geometry"].to_numpy())
        gdf = gpd.GeoDataFrame(df.drop(columns=["geometry"]), geometry=geoms, crs="EPSG:4326")
        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if len(gdf) == 0:
            raise RuntimeError("overture_buildings: no polygonal building features for AOI")

        parsed = [_height_from_row(h, f) for h, f in zip(gdf["height"], gdf["num_floors"], strict=False)]
        gdf["height_m"] = [p[0] for p in parsed]
        gdf["height_source"] = [p[1] for p in parsed]

        gdf_proj = aoi.to_metric(gdf)
        gdf_clipped = aoi.clip(gdf_proj)

        source = Source(
            name="Overture Maps Foundation — buildings theme",
            url=f"s3://{BUCKET}/release/{release}/{THEME_PATH}/",
            licence="ODbL 1.0",
            licence_url=LICENCE_URL,
            note=(
                "Overture buildings theme conflates OpenStreetMap contributions, so it inherits "
                "ODbL 1.0; read directly from the public GeoParquet release via pyarrow+S3"
            ),
            commercial_ok=True,
        )

        return self.summarise(
            LayerResult(layer=self.layer, provider=self.name, gdf=gdf_clipped, sources=[source]), aoi
        )

    def summarise(self, result: LayerResult, aoi) -> LayerResult:
        return summarise_building_heights(result)


def register(registry: Registry) -> None:
    """Add the provider only when pyarrow is importable (it is an optional extra)."""
    if importlib.util.find_spec("pyarrow") is not None:
        registry.register(OvertureBuildingsProvider())


register(REGISTRY)
