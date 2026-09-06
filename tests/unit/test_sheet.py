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
