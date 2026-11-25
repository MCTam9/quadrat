"""One vocabulary for land use, building use and height source, everywhere."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sce import vocab
from sce.providers.osm_landuse import _classify

ROOT = Path(__file__).resolve().parents[2]


def test_web_copy_is_generated_from_the_vocabulary():
    """web/lib/vocab.generated.ts must match `python -m sce.vocab --ts`."""
    path = ROOT / "web" / "lib" / "vocab.generated.ts"
    assert path.exists(), "run: python -m sce.vocab --ts > web/lib/vocab.generated.ts"
    assert path.read_text() == vocab.to_typescript(), (
        "web/lib/vocab.generated.ts is stale: python -m sce.vocab --ts > web/lib/vocab.generated.ts"
    )


def test_provider_emits_only_vocabulary_classes():
    for key, mapping in vocab.OSM_LANDUSE_TAGS.items():
        for value in mapping:
            assert _classify(pd.Series({key: value})) in vocab.LANDUSE_IDS
    assert _classify(pd.Series({"landuse": "unheard-of"})) == "other"


@pytest.mark.parametrize("tag,expected", [("farmland", "agriculture"), ("orchard", "agriculture")])
def test_farmland_is_agriculture_not_green(tag, expected):
    assert _classify(pd.Series({"landuse": tag})) == expected


def test_every_consumer_colours_every_class():
    from sce.export import qml, svg
    from sce.report import style

    for cid in vocab.LANDUSE_IDS:
        assert cid in svg._LANDUSE_FILL
        assert cid in qml._LANDUSE_COLOURS
        assert cid in style.LANDUSE_COLOURS


def test_building_tags_map_into_building_use():
    assert set(vocab.BUILDING_TAG_USE.values()) <= set(vocab.BUILDING_USE_IDS)
    assert vocab.BUILDING_TAG_USE["apartments"] == "residential"
    assert "yes" not in vocab.BUILDING_TAG_USE
