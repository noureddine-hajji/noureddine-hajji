"""Sprint "Vitesse sur téléphone" (owner, 2026-11-16): the heaviest answers without a parameter, compressed ONCE at build.

The map layer (carte.couche, base and details) and the lists' badges (/api/reconnaissance) are the same bytes for every
visitor. Brotli at its highest quality makes them about a third smaller than gzip (1.1 MB instead of 1.6 MB on a phone on
slow 4G), but takes seconds: far too slow for a serverless instance's first request. So the build compresses them and
stores each compressed body under the SHA-256 of the exact JSON bytes it encodes, in the file beside the warehouse
(rapport_textes.duckdb: the warehouse itself must stay under its 95 MB budget). The server builds its JSON as before and
looks its digest up: found, it may send the brotli body to a browser that accepts it; not found (another warehouse, a code
change since the build, no brotli at build time), it sends gzip as before. A stored body is never trusted blindly: the build
checks that it decompresses to the JSON it was made from, and red team VT9 checks it again on the served files.
Nothing here changes a figure: the decompressed bytes ARE the JSON the server built.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

TABLE = "precomp_br"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def compress(raw: bytes) -> bytes | None:
    """Brotli at quality 11 (build only), checked by decompression; None when brotli is not installed."""
    try:
        import brotli
    except ImportError:
        return None
    br = brotli.compress(raw, quality=11, lgwin=24)
    if brotli.decompress(br) != raw:                     # never store a body that does not give back these bytes
        raise RuntimeError("precomp: brotli round trip failed")
    return br


def _side(con):
    """A cursor on the file beside the warehouse, or None (tests without it)."""
    from . import rapports as RP
    db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    f = RP.textes_path(Path(db[0])) if db and db[0] else None
    if f is None or not f.exists():
        return None
    return RP._texts_con(str(f), f.stat().st_mtime_ns).cursor()


def _has(c, schema_table: str) -> bool:
    schema, _, table = schema_table.rpartition(".")
    q = "SELECT count(*) FROM information_schema.tables WHERE table_name = ?" + (" AND table_schema = ?" if schema else "")
    return bool(c.execute(q, [table, schema] if schema else [table]).fetchone()[0])


def reconnaissance_payload(con) -> dict:
    """/api/reconnaissance: the State-label badges and fees (sprint V1), the strong-demand formations and the apprenticeship
    codes (sprint V2), both robustesse repères (owner, 2026-11-17), for the lists. One definition for the route and the build."""
    from . import apprentissage as APP
    from . import reconnaissance as RC
    from . import robustesse_formation as RF
    from . import tension as TS
    from . import vie as VIE
    # owner, 2026-11-17: both robustesse repères of every formation, read by Mes vœux beside each zone (never merged)
    return {**RC.compact(con, VIE.compact(con)), "tension": TS.compact(con), "apprentissage": APP.codes(con),
            "robustesse": RF.compact(con)}


def json_bytes(payload, sort_keys: bool = False) -> bytes:
    """Compact JSON. sort_keys: an answer read from SQL without an order (GROUP BY) must give the same bytes in every process,
    or its stored brotli body would never be found (found on /api/reconnaissance, 2026-11-16)."""
    import json
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False, sort_keys=sort_keys).encode()


def bodies(con) -> dict:
    """{name: JSON bytes} of every answer compressed at build: exactly the bytes the server sends."""
    from . import admis as ADM
    from . import carte as CA
    return {"carte_couche_base": CA.couche(con, ADM.mark, "base")["json"],
            "carte_couche_details": CA.couche(con, ADM.mark, "details")["json"],
            "reconnaissance": json_bytes(reconnaissance_payload(con), sort_keys=True)}


_LOOKUP: dict = {}


def lookup(con, raw: bytes) -> bytes | None:
    """The brotli body stored at build for exactly these JSON bytes, else None. Memoised per digest (the bodies are built
    once per warehouse and never change)."""
    d = digest(raw)
    if d in _LOOKUP:
        return _LOOKUP[d]
    out = None
    try:
        if _has(con, f"core.{TABLE}"):
            r = con.execute(f"SELECT data FROM core.{TABLE} WHERE digest = ?", [d]).fetchone()
        else:
            c = _side(con)
            r = c.execute(f"SELECT data FROM {TABLE} WHERE digest = ?", [d]).fetchone() if c is not None and _has(c, TABLE) else None
        out = bytes(r[0]) if r and r[0] is not None else None
    except Exception:                                      # a missing or unreadable side file: gzip, as before
        out = None
    if len(_LOOKUP) > 16:
        _LOOKUP.clear()
    _LOOKUP[d] = out
    return out


def build(con, textes: Path | None, bodies: dict) -> int:
    """Store {name: json bytes} compressed, keyed by digest (the side file, or core.* in tests without it). Returns the
    number of bodies stored (0 without brotli: the server then keeps gzip)."""
    rows = []
    for name, raw in bodies.items():
        br = compress(raw)
        if br is not None:
            rows.append([digest(raw), name, len(raw), br])

    def write(c, prefix):
        c.execute(f"CREATE OR REPLACE TABLE {prefix}{TABLE} (digest VARCHAR, name VARCHAR, n_json BIGINT, data BLOB)")
        if rows:
            c.executemany(f"INSERT INTO {prefix}{TABLE} VALUES (?, ?, ?, ?)", rows)

    if textes is None or not Path(textes).exists():
        write(con, "core.")
    else:
        import duckdb
        from . import rapports as RP
        RP._texts_con.cache_clear()                    # no read-only handle on the file while it is written
        tc = duckdb.connect(str(textes))
        try:
            write(tc, "")
            tc.execute("CHECKPOINT")
        finally:
            tc.close()
    _LOOKUP.clear()
    return len(rows)


def accepts_br(request) -> bool:
    """The browser accepts brotli (every current browser does over HTTPS); "br;q=0" means refused."""
    for part in (request.headers.get("accept-encoding") or "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if name.strip() != "br":
            continue
        q = 1.0
        for p in params.split(";"):
            k, _, v = p.strip().partition("=")
            if k == "q":
                try:
                    q = float(v)
                except ValueError:
                    q = 0.0
        return q > 0
    return False
