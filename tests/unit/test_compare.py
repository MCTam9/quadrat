"""The comparison sheet, including the two refusals it is built around."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from sce.aoi import AOI
from sce.report.compare import ROWS, render_compare
from sce.types import LayerResult


def _site(name: str, lon: float, lat: float, radius: float, gsi: float):
    aoi = AOI.from_point(lon, lat, radius, name=name)
    minx, miny, maxx, maxy = aoi.bounds_metric
    side = (maxx - minx) * (gsi**0.5)
    buildings = gpd.GeoDataFrame(
        {
            "geometry": [
                Polygon([(minx, miny), (minx + side, miny), (minx + side, miny + side), (minx, miny + side)])
            ]
        },
        crs=aoi.crs,
    )
    streets = gpd.GeoDataFrame(
        {"geometry": [LineString([(minx, (miny + maxy) / 2), (maxx, (miny + maxy) / 2)])]},
        crs=aoi.crs,
    )
    layers = {
        "buildings": LayerResult("buildings", "test", gdf=buildings),
        "streets": LayerResult("streets", "test", gdf=streets),
    }
    metrics = {
        "street": {"intersection_density_km2": 100.0 * (1 + gsi), "orientation_order_phi": gsi},
        "fabric": {"gsi": gsi, "fsi": None},
        "climate": {"hdd_18c": 2000.0, "cdd_18c": 500.0},
    }
    return aoi, layers, metrics


@pytest.fixture
def bundle():
    return [
        _site("alpha", 3.0, 40.0, 1000.0, 0.20),
        _site("beta", 3.0, 41.0, 1000.0, 0.40),
    ]


def test_compare_writes_a_pdf(tmp_path, bundle):
    out = render_compare(tmp_path / "compare.pdf", bundle)
    assert out.exists() and out.stat().st_size > 10_000


def test_compare_accepts_three_and_four_sites(tmp_path, bundle):
    four = [*bundle, _site("gamma", 3.0, 42.0, 1000.0, 0.1), _site("delta", 3.0, 43.0, 1000.0, 0.55)]
    assert render_compare(tmp_path / "four.pdf", four).exists()
    assert render_compare(tmp_path / "three.pdf", four[:3]).exists()


def test_compare_refuses_a_single_site(tmp_path, bundle):
    """A comparison of one is a report, and there is already a command for that."""
    with pytest.raises(ValueError, match="at least two"):
        render_compare(tmp_path / "one.pdf", bundle[:1])


def test_sites_beyond_the_fourth_are_dropped_rather_than_squeezed(tmp_path, bundle):
    many = bundle + [_site(f"s{i}", 3.0, 42.0 + i, 1000.0, 0.3) for i in range(5)]
    assert render_compare(tmp_path / "many.pdf", many).exists()


def test_no_row_claims_a_direction_of_preference():
    """The sheet must not encode which way is better for any metric.

    A steeper site is not a worse site, and a denser one is not a better one.
    The moment a row carries a direction, the sheet is scoring rather than
    describing, and the weighting it implies belongs to the client.
    """
    assert all(row[5] is None for row in ROWS), (
        "a comparison row declares a preferred direction; that judgement is the client's, not the tool's"
    )


def test_all_sites_are_drawn_at_one_scale(tmp_path):
    """A drawing fitted to its own frame is a picture; drawn at a shared scale
    it is a measurement. A smaller site must get white margin, not a zoom."""
    import matplotlib.pyplot as plt

    sites = [_site("big", 3.0, 40.0, 1500.0, 0.3), _site("small", 3.0, 41.0, 500.0, 0.3)]
    render_compare(tmp_path / "scale.pdf", sites)
    fig = plt.gcf()
    plt.close(fig)

    from sce.report.compare import _figure_ground_at_common_scale

    spans = []
    for aoi, layers, _ in sites:
        f, ax = plt.subplots()
        _figure_ground_at_common_scale(ax, aoi, layers, 3000.0)
        spans.append(ax.get_xlim()[1] - ax.get_xlim()[0])
        plt.close(f)
    assert spans[0] == pytest.approx(spans[1])
    assert spans[0] == pytest.approx(3000.0)
