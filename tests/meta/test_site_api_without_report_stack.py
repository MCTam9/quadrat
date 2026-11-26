"""The site function's bundle deletes the report stack (`trim_site_packages.py --profile site`).

On Vercel `api/main.py` serves every route except `/api/export`, which `api/export.py` serves with
the full install. So load, preview, analyse and climate must work with matplotlib, Pillow and the
CAD libraries absent. This runs them in a subprocess where importing any of those fails.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

ROOT = Path(__file__).parent.parent.parent
# What `--profile site` deletes, plus the export-only extras the site service never installs.
ABSENT = (
    *("matplotlib", "mpl_toolkits", "fontTools", "PIL", "kiwisolver", "cycler"),
    *("ezdxf", "rhino3dm", "trimesh"),
)

SCRIPT = textwrap.dedent(
    """
    import sys
    for name in {absent!r}:
        sys.modules[name] = None  # any import of these now raises ImportError

    sys.path[:0] = [{root!r}, {unit!r}]
    from _site_fixtures import site_layers
    from fastapi.testclient import TestClient

    import sce.pipeline
    import api.main as api_main

    def fake_fetch(aoi, cache, *a, on_layer=None, only=None, **kw):
        layers = {{k: v for k, v in site_layers(aoi).items() if only is None or k in only}}
        for name, res in layers.items():
            if on_layer:
                on_layer(name, res)
        return layers

    sce.pipeline.fetch_layers = fake_fetch
    api_main.STORE = None
    client = TestClient(api_main.app)
    lon, lat = -0.1, 51.5
    sid = api_main.site_key(lon, lat)
    load = client.post("/api/load", json={{"lon": lon, "lat": lat, "half_width_m": 300}})
    assert load.status_code == 200 and "event: ready" in load.text, load.text[-500:]
    assert '"layer": "terrain"' in load.text
    body = {{"site_id": api_main.site_key(lon, lat, api_main.padded_half_width(300)),
             "lon": lon, "lat": lat, "half_width_m": 300}}
    preview = client.post("/api/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["contours"]["features"], "no contours in the preview"
    assert client.post("/api/analyse", json=body).status_code == 200
    assert client.post("/api/climate", json={{"site_id": body["site_id"]}}).status_code in (200, 404)
    leaked = sorted(m for m in {absent!r} if sys.modules.get(m) is not None)
    assert not leaked, leaked
    print("ok")
    """
)


def test_site_routes_run_without_the_report_stack():
    script = SCRIPT.format(absent=ABSENT, root=str(ROOT), unit=str(ROOT / "tests" / "unit"))
    env = {**os.environ, "SCE_AUTH_DISABLED": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300
    )
    assert proc.returncode == 0 and proc.stdout.strip().endswith("ok"), proc.stderr[-3000:]
