"""Mesh exports (`.glb`, `.obj`) of the site: terrain surface plus building massing.

Coordinates. Every vertex is `(easting - ox, northing - oy, elevation)` where
`(ox, oy)` is `sce.export._georef.local_origin(aoi)` (the AOI centre, in the
AOI's projected metre CRS). The shift exists because float32 vertices lose
centimetres at UTM magnitudes; the origin and CRS are also recorded in
`georef.json` and, for GLB, in the scene extras. Elevation stays absolute
metres above the DEM datum; it is never shifted.

Axes. OBJ is Z-up: x = east, y = north, z = up. glTF is Y-up, so the GLB is
the same model rotated -90 degrees about x: (x, y, z) -> (x, z, -y), i.e.
x = east, y = up, z = -north. This is a proper rotation, so winding is kept.

Groups are named like the DXF/3DM layers: `TERRAIN`, `BLDG-MASSING`,
`BLDG-FOOTPRINT`. A building becomes a massing solid only when its height is
actually known; otherwise it is a flat face 5 cm above the ground, so a viewer
can see which buildings are modelled and which are not. Never invent a height.
Roads are not modelled yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..types import LayerResult
from ._georef import georef_dict, local_origin

MAX_TERRAIN_VERTS = 250
FOOTPRINT_LIFT_M = 0.05

# name -> RGBA 0..255, light green-grey / light grey / darker grey.
_COLOUR: dict[str, tuple[int, int, int, int]] = {
    "TERRAIN": (175, 190, 165, 255),
    "BLDG-MASSING": (205, 205, 210, 255),
    "BLDG-FOOTPRINT": (110, 110, 115, 255),
}


def _require_trimesh():
    try:
        import trimesh
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "write_glb()/write_obj() need the optional 'mesh' extra: install it with "
            "`pip install 'sce[mesh]'` (or `pip install trimesh mapbox-earcut` directly)."
        ) from exc
    return trimesh


class _Terrain:
    """Decimated height grid in local metres, with nearest-cell sampling."""

    def __init__(self, raster: dict, aoi: Any, origin: tuple[float, float]):
        arr = np.asarray(raster["array"], dtype="float64")
        if arr.ndim == 3:
            arr = arr[0]
        nodata = raster.get("nodata")
        if nodata is not None and not np.isnan(nodata):
            arr = np.where(arr == nodata, np.nan, arr)
        arr = np.where(np.isfinite(arr), arr, np.nan)
        t = raster["transform"]
        rows, cols = arr.shape
        # Cell-centre coordinates in the AOI CRS (north-up grids; rotation ignored).
        xs = t.c + (np.arange(cols) + 0.5) * t.a
        ys = t.f + (np.arange(rows) + 0.5) * t.e
        minx, miny, maxx, maxy = aoi.bounds_metric
        cx = np.nonzero((xs >= minx) & (xs <= maxx))[0]
        cy = np.nonzero((ys >= miny) & (ys <= maxy))[0]
        self.empty = cx.size < 2 or cy.size < 2
        if self.empty:
            self.xs = self.ys = self.z = np.zeros(0)
            return
        arr, xs, ys = arr[np.ix_(cy, cx)], xs[cx], ys[cy]
        self.full = (arr, xs, ys)  # full-resolution, for sampling
        sr = max(1, int(np.ceil(arr.shape[0] / MAX_TERRAIN_VERTS)))
        sc = max(1, int(np.ceil(arr.shape[1] / MAX_TERRAIN_VERTS)))
        self.z = arr[::sr, ::sc]
        self.xs = xs[::sc] - origin[0]
        self.ys = ys[::sr] - origin[1]
        self.origin = origin
        if self.z.shape[0] < 2 or self.z.shape[1] < 2 or not np.isfinite(self.z).any():
            self.empty = True

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Nearest-cell elevation at AOI-CRS points; NaN where there is no data."""
        arr, xs, ys = self.full
        if xs.size > 1:
            ci = np.clip(np.rint((x - xs[0]) / (xs[1] - xs[0])).astype(int), 0, xs.size - 1)
        else:
            ci = np.zeros(len(x), dtype=int)
        if ys.size > 1:
            ri = np.clip(np.rint((y - ys[0]) / (ys[1] - ys[0])).astype(int), 0, ys.size - 1)
        else:
            ri = np.zeros(len(y), dtype=int)
        return arr[ri, ci]

    def mesh_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """Vertices (n,3) and up-facing triangles; cells touching NaN are skipped."""
        nr, nc = self.z.shape
        gx, gy = np.meshgrid(self.xs, self.ys)
        verts = np.column_stack([gx.ravel(), gy.ravel(), self.z.ravel()])
        idx = np.arange(nr * nc).reshape(nr, nc)
        a, b = idx[:-1, :-1], idx[:-1, 1:]  # a=(r,c) b=(r,c+1)
        c, d = idx[1:, :-1], idx[1:, 1:]  # c=(r+1,c) d=(r+1,c+1)
        ok = np.isfinite(self.z)
        good = ok[:-1, :-1] & ok[:-1, 1:] & ok[1:, :-1] & ok[1:, 1:]
        a, b, c, d = a[good], b[good], c[good], d[good]
        # Rows run north to south, so a->c->b is counter-clockwise seen from above.
        faces = np.concatenate([np.column_stack([a, c, b]), np.column_stack([b, c, d])])
        used = np.unique(faces)
        remap = np.full(len(verts), -1, dtype=np.int64)
        remap[used] = np.arange(used.size)
        return verts[used], remap[faces]


def _clean_polygons(geom) -> list:
    """Valid, non-degenerate Polygon parts of a footprint."""
    if geom is None or geom.is_empty:
        return []
    if not geom.is_valid:
        from shapely.validation import make_valid

        geom = make_valid(geom)
    parts = list(getattr(geom, "geoms", [geom]))
    out = []
    while parts:
        g = parts.pop()
        if g.geom_type == "Polygon":
            if not g.is_empty and g.area > 1e-6:
                out.append(g)
        elif hasattr(g, "geoms"):
            parts.extend(g.geoms)
    return out


def _base_elevation(geom, terrain: _Terrain | None) -> float:
    """Lowest terrain sample under a footprint (vertices + centroid), else 0."""
    if terrain is None or terrain.empty:
        return 0.0
    pts = [np.asarray(p.exterior.coords)[:, :2] for p in _clean_polygons(geom)]
    if not pts:
        return 0.0
    c = geom.centroid
    xy = np.vstack([*pts, np.array([[c.x, c.y]])])
    z = terrain.sample(xy[:, 0], xy[:, 1])
    z = z[np.isfinite(z)]
    return float(z.min()) if z.size else 0.0


def _known_height(value: Any) -> float | None:
    try:
        h = float(value)
    except (TypeError, ValueError):
        return None
    return h if np.isfinite(h) and h > 0 else None


def _building_meshes(trimesh, result: LayerResult | None, terrain, origin):
    """(massing_mesh | None, footprint_mesh | None, counts)."""
    from shapely.affinity import translate

    counts = {"massing": 0, "footprint_only": 0}
    if result is None or result.gdf is None or result.gdf.empty:
        return None, None, counts
    gdf = result.gdf
    heights = gdf["height_m"] if "height_m" in gdf.columns else None
    massing: list = []
    flat: list = []
    for i, geom in enumerate(gdf.geometry):
        if geom is None or geom.is_empty:
            continue
        h = _known_height(heights.iloc[i]) if heights is not None else None
        base = _base_elevation(geom, terrain)
        for poly in _clean_polygons(geom):
            local = translate(poly, -origin[0], -origin[1])
            try:
                if h is not None:
                    m = trimesh.creation.extrude_polygon(local, h)
                    m.apply_translation([0, 0, base])
                    massing.append(m)
                    counts["massing"] += 1
                else:
                    v2, f = trimesh.creation.triangulate_polygon(local, engine="earcut")
                    v2, f = np.asarray(v2, dtype="float64"), np.asarray(f)
                    if len(f) == 0:
                        continue
                    # Force counter-clockwise so the face points up.
                    p0, p1, p2 = v2[f[:, 0]], v2[f[:, 1]], v2[f[:, 2]]
                    cross = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p1[:, 1] - p0[:, 1]) * (
                        p2[:, 0] - p0[:, 0]
                    )
                    f = np.where((cross < 0)[:, None], f[:, ::-1], f)
                    v3 = np.column_stack([v2, np.full(len(v2), base + FOOTPRINT_LIFT_M)])
                    flat.append(trimesh.Trimesh(v3, f, process=False))
                    counts["footprint_only"] += 1
            except Exception:  # degenerate ring the triangulator rejects: skip it
                continue
    cat = lambda ms: trimesh.util.concatenate(ms) if ms else None  # noqa: E731
    return cat(massing), cat(flat), counts


def _build(layers: dict[str, LayerResult], aoi) -> dict[str, Any]:
    """Named Z-up local-origin meshes, one per layer that has content."""
    trimesh = _require_trimesh()
    origin = local_origin(aoi)
    terrain = None
    meshes: dict[str, Any] = {}
    tr = layers.get("terrain")
    if tr is not None and tr.raster is not None:
        terrain = _Terrain(tr.raster, aoi, origin)
        if not terrain.empty:
            v, f = terrain.mesh_arrays()
            if len(f):
                meshes["TERRAIN"] = trimesh.Trimesh(v, f, process=False)
    massing, footprint, _ = _building_meshes(trimesh, layers.get("buildings"), terrain, origin)
    if massing is not None:
        meshes["BLDG-MASSING"] = massing
    if footprint is not None:
        meshes["BLDG-FOOTPRINT"] = footprint
    return meshes


def write_glb(path: str | Path, layers: dict[str, LayerResult], aoi) -> Path:
    """Write a Y-up binary glTF with one named mesh/node per layer."""
    trimesh = _require_trimesh()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    for name, mesh in _build(layers, aoi).items():
        v = np.asarray(mesh.vertices, dtype="float64")
        mesh = trimesh.Trimesh(
            np.column_stack([v[:, 0], v[:, 2], -v[:, 1]]).astype("float32"),
            mesh.faces,
            process=False,
        )
        r, g, b, a = (c / 255.0 for c in _COLOUR[name])
        mesh.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(
                name=name,
                baseColorFactor=[r, g, b, a],
                metallicFactor=0.0,
                roughnessFactor=0.9,
                doubleSided=True,
            )
        )
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    geo = georef_dict(aoi)
    scene.metadata.update(
        {
            "crs": geo["crs"],
            "local_origin": geo["local_origin"],
            "axes": "glTF Y-up: x=east, y=up, z=-north; elevation absolute metres",
            "units": "metre",
        }
    )
    path.write_bytes(scene.export(file_type="glb"))
    return path


def write_obj(path: str | Path, layers: dict[str, LayerResult], aoi) -> Path:
    """Write a Z-up Wavefront OBJ (one `o`/`g` group per layer) plus a `.mtl`."""
    _require_trimesh()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = path.with_suffix(".mtl")
    ox, oy = local_origin(aoi)
    lines = [
        "# Site Context Report mesh. Z-up: x=east, y=north, z=up (metres).",
        f"# Vertices are relative to local origin easting={ox} northing={oy} in {aoi.epsg};",
        "# elevation is absolute.",
        f"mtllib {mtl_path.name}",
    ]
    mtl: list[str] = []
    offset = 1
    for name, mesh in _build(layers, aoi).items():
        r, g, b, _ = (c / 255.0 for c in _COLOUR[name])
        mtl += [f"newmtl {name}", f"Kd {r:.3f} {g:.3f} {b:.3f}", "Ka 0 0 0", "Ks 0 0 0", ""]
        lines += [f"o {name}", f"g {name}", f"usemtl {name}"]
        lines += [f"v {x:.3f} {y:.3f} {z:.3f}" for x, y, z in mesh.vertices]
        lines += [f"f {a + offset} {b + offset} {c + offset}" for a, b, c in mesh.faces]
        offset += len(mesh.vertices)
    path.write_text("\n".join(lines) + "\n")
    mtl_path.write_text("\n".join(mtl))
    return path
