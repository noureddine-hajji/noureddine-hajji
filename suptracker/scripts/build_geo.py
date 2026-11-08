"""Build the self-hosted base map of the "Carte" page: static/geo/france.json.

Source: departements-avec-outre-mer.geojson of github.com/gregoiredavid/france-geojson, made from IGN Admin Express
(Licence ouverte / Etalab). Run once by hand:
    python scripts/build_geo.py path/to/departements-avec-outre-mer.geojson
The output holds, for metropolitan France and each overseas département drawn as an inset, its projection (a local
equirectangular: x = (lon - lon0) * cos(lat0) * k + ox, y = (lat1 - lat) * k + oy, in a 1000 x 1000 box) and the
simplified outline of each département as an SVG path. The page projects every formation with the SAME parameters
(red team C2 re-derives them).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "suptracker" / "static" / "geo" / "france.json"
# area (département codes), lon/lat box, and the rectangle it is drawn in (x, y, width, height) in the 1000 x 1000 box
AREAS = [
    ("metro", None, (-5.3, 41.3, 9.7, 51.2), (170, 10, 820, 980)),
    ("971", ("971",), (-61.9, 15.8, -60.9, 16.6), (10, 10, 150, 130)),
    ("972", ("972",), (-61.3, 14.35, -60.75, 14.9), (10, 150, 150, 150)),
    ("973", ("973",), (-54.7, 2.0, -51.5, 5.9), (10, 310, 150, 190)),
    ("974", ("974",), (55.18, -21.42, 55.86, -20.85), (10, 510, 150, 130)),
    ("976", ("976",), (44.98, -13.03, 45.32, -12.63), (10, 650, 150, 170)),
]
TOL = {"metro": 0.012, "971": 0.004, "972": 0.003, "973": 0.012, "974": 0.003, "976": 0.002}


def proj_params(box, rect):
    lon0, lat0, lon1, lat1 = box
    x, y, w, h = rect
    c = math.cos(math.radians((lat0 + lat1) / 2))
    k = min(w / ((lon1 - lon0) * c), h / (lat1 - lat0))
    # centre the drawing in its rectangle
    ox = x + (w - (lon1 - lon0) * c * k) / 2
    oy = y + (h - (lat1 - lat0) * k) / 2
    return {"lon0": lon0, "lat1": lat1, "cos": round(c, 6), "k": round(k, 4), "ox": round(ox, 2), "oy": round(oy, 2),
            "box": list(box), "rect": list(rect)}


def project(p, lon, lat):
    return ((lon - p["lon0"]) * p["cos"] * p["k"] + p["ox"], (p["lat1"] - lat) * p["k"] + p["oy"])


def dp(pts, tol):
    """Douglas-Peucker on (lon, lat) points."""
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy) or 1e-12
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x1 * y0 - y1 * x0) / n
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return dp(pts[: idx + 1], tol)[:-1] + dp(pts[idx:], tol)


def rings(geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        yield poly[0]                    # outer ring only (no département has a meaningful hole at this scale)


def main(src: str) -> None:
    g = json.load(open(src, encoding="utf-8"))
    out = {"source": "IGN Admin Express, via github.com/gregoiredavid/france-geojson (Licence ouverte / Etalab)", "areas": []}
    for name, codes, box, rect in AREAS:
        p = proj_params(box, rect)
        deps = []
        for f in g["features"]:
            code = f["properties"]["code"]
            if (codes is None and code in ("971", "972", "973", "974", "976")) or (codes is not None and code not in codes):
                continue
            parts = []
            for ring in rings(f["geometry"]):
                pts = [tuple(x) for x in ring]
                # a closed ring: split it at its farthest point from the start, simplify each half
                far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
                s = dp(pts[: far + 1], TOL[name])[:-1] + dp(pts[far:], TOL[name])
                if len(s) < 4:
                    continue
                xy = [project(p, lon, lat) for lon, lat in s]
                parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in xy) + "Z")
            if parts:
                deps.append({"code": code, "nom": f["properties"]["nom"], "d": "".join(parts)})
        out["areas"].append({"id": name, "proj": p, "departements": deps})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(OUT, OUT.stat().st_size, "bytes", sum(len(a["departements"]) for a in out["areas"]), "départements")


if __name__ == "__main__":
    main(sys.argv[1])
