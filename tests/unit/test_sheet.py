"""The sheet's own small decisions, checked without drawing a whole figure."""

from __future__ import annotations

from sce.report.sheet import _terrain_sub, _warnings_of


def test_terrain_subtitle_names_the_model_actually_used():
    """With --dtm fabdem the panel is bare earth. Saying DSM would be a lie, and
    it is exactly the kind of lie a GIS reader catches."""
    assert "DSM" in _terrain_sub({"terrain": {"elevation_min_m": 10, "elevation_max_m": 50}})
    bare = _terrain_sub({"terrain": {"elevation_min_m": 10, "elevation_max_m": 50, "terrain_model": "DTM"}})
    assert "DTM" in bare and "DSM" not in bare


def test_terrain_subtitle_is_empty_without_elevation():
    assert _terrain_sub({}) == ""
    assert _terrain_sub({"terrain": {}}) == ""


def test_warnings_accepts_the_assessment_dict_or_a_bare_list():
    assert _warnings_of(None) == []
    assert _warnings_of(["a"]) == ["a"]
    assert _warnings_of({"warnings": ["b"], "degraded": True}) == ["b"]
    assert _warnings_of({"coverage": {}}) == []


# -- layout ------------------------------------------------------------------------------------


def _layout_texts(fig):
    """Every label that is part of the sheet's layout, with its box on the page.

    Text drawn inside a map or bar (contour labels, scale bar, bar captions) is left out:
    it is clipped to its panel and may sit on the drawing by design.
    """
    from matplotlib.legend import Legend
    from matplotlib.text import Annotation, Text

    renderer = fig.canvas.get_renderer()
    out = [t for t in fig.texts if t.get_text().strip()]
    for ax in fig.axes:
        out += [c for c in ax.get_children() if isinstance(c, Annotation) and c.get_text().strip()]
        if ax.name == "polar":
            out += [t for t in ax.get_xticklabels() if t.get_text().strip()]
        legend = ax.get_legend()
        if isinstance(legend, Legend):
            out += [t for t in legend.get_texts() if t.get_text().strip()]
    return [
        (t.get_text(), t.get_window_extent(renderer)) for t in out if isinstance(t, Text) and t.get_visible()
    ]


def test_sheet_labels_never_overlap(tmp_path):
    """Panel titles, notes, legends and compass letters each get their own space on the page."""
    import matplotlib.pyplot as plt
    from _site_fixtures import site_layers

    from sce.aoi import AOI
    from sce.pipeline import analyse
    from sce.report.sheet import build_sheet

    aoi = AOI.from_point(-0.1, 51.5, 300, name="Test site")
    layers = site_layers(aoi)
    metrics, assessment = analyse(layers, aoi)
    fig = build_sheet(aoi, layers, metrics, assessment)
    fig.canvas.draw()
    boxes = _layout_texts(fig)
    clashes = [
        (a, b)
        for i, (a, box_a) in enumerate(boxes)
        for b, box_b in boxes[i + 1 :]
        if box_a.overlaps(box_b) and box_a.intersection(box_a, box_b).width > 0.5
    ]
    page = fig.bbox
    off_page = [
        t for t, box in boxes if box.x0 < page.x0 or box.x1 > page.x1 or box.y0 < page.y0 or box.y1 > page.y1
    ]
    plt.close(fig)
    assert not clashes, clashes
    assert not off_page, off_page


def test_sheet_uses_the_bundled_archivo():
    from matplotlib import font_manager

    from sce.report import style

    style.apply()
    for family, weight in ((style.FONT, 400), (style.FONT, 600), (style.FONT_WIDE, 700)):
        path = font_manager.findfont(
            font_manager.FontProperties(family=family, weight=weight), fallback_to_default=False
        )
        assert path.startswith(str(style.FONT_DIR)), (family, weight, path)


def test_sheet_header_uses_the_title_else_the_aoi_name():
    import matplotlib.pyplot as plt
    from _site_fixtures import site_layers

    from sce.aoi import AOI
    from sce.pipeline import analyse
    from sce.report.sheet import build_sheet

    aoi = AOI.from_point(-0.1, 51.5, 300, name="site")
    layers = site_layers(aoi)
    metrics, _ = analyse(layers, aoi)
    for title, expected in (("Trafalgar Square", "Trafalgar Square"), (None, "site"), ("  ", "site")):
        fig = build_sheet(aoi, layers, metrics, title=title)
        assert expected in {t.get_text() for t in fig.texts}
        plt.close(fig)
