"""Quadrat export function: `POST /api/export` on its own.

Deployed as a separate Vercel service (vercel.json) so the site function, which serves every
interactive request, can ship without the report and CAD stack that only export needs
(matplotlib, ezdxf, rhino3dm, trimesh). Auth, error shapes and site lookup are the ones in
`api/main.py`; a site loaded by the other function is restored here from the snapshot store.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Vercel loads this file as the service entrypoint; make sure the project root is importable
# so `api.main` resolves the same way it does under uvicorn and pytest.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from api.main import exports, make_app  # noqa: E402

__all__ = ["app"]

app = make_app("Quadrat export API")
app.include_router(exports)
