"""Download raw Parquet exports from the SIES Opendatasoft v2.1 API.

Each export lands untouched in data/raw/<key>.parquet; a manifest records the
ODS id actually served, byte size, sha256 and row count so builds are reproducible
and the verification suite can tell which upstream snapshot it is checking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pyarrow.parquet as pq

from . import config

MANIFEST = "manifest.json"


def _download(url: str, dest: Path, retries: int = 4) -> None:
    tmp = dest.with_suffix(".part")
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with httpx.stream("GET", url, timeout=httpx.Timeout(30.0, read=600.0),
                              follow_redirects=True) as r:
                r.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
            tmp.replace(dest)
            return
        except httpx.HTTPStatusError as exc:
            # 404 means "wrong id", not a transient failure: let the caller try the next id.
            if exc.response.status_code == 404 or attempt == retries:
                raise
        except httpx.TransportError:
            if attempt == retries:
                raise
        time.sleep(delay)
        delay *= 2


def _read_csv(path: Path):
    """A producer CSV of unknown delimiter and encoding, every column as text (no type guessing)."""
    import csv

    import pandas as pd
    raw = path.read_bytes()
    enc = "utf-8-sig"
    try:
        head = raw[:65536].decode(enc)
    except UnicodeDecodeError:
        enc, head = "latin-1", raw[:65536].decode("latin-1")
    sep = csv.Sniffer().sniff(head.splitlines()[0], delimiters=";,\t|").delimiter
    return pd.read_csv(path, sep=sep, dtype=str, encoding=enc, keep_default_na=False, na_values=[""])


def _xml_records(path: Path):
    """A zip of XML files as one row per record (each direct child of a file's root), the record kept as XML text."""
    import xml.etree.ElementTree as ET
    import zipfile

    import pandas as pd
    rows = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.lower().endswith(".xml"):
                continue
            root = ET.fromstring(z.read(name))
            for i, el in enumerate(root):
                rows.append({"file": name, "idx": i, "tag": el.tag, "xml": ET.tostring(el, encoding="unicode")})
    return pd.DataFrame(rows, columns=["file", "idx", "tag", "xml"])


def _ingest_file(ds, raw_dir: Path, dest: Path) -> dict:
    """Download a direct file and convert it to raw/<key>.parquet (text columns, as published)."""
    ext = ds.url.rsplit(".", 1)[-1].lower()
    src = raw_dir / f"{ds.key}.{ext}"
    print(f"[get ] {ds.key} <- {ds.url}")
    _download(ds.url, src)
    df = _xml_records(src) if ext == "zip" else _read_csv(src)
    df.to_parquet(dest, index=False)
    return {"url": ds.url, "kind": ds.kind, "year": ds.year, "bytes": src.stat().st_size, "sha256": _sha256(src),
            "rows": len(df), "columns": len(df.columns), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def sessions(path: Path) -> set[int]:
    """The Parcoursup sessions a downloaded vœux file really holds (its own "session" column, SIES alias "annee")."""
    names = pq.ParquetFile(path).schema_arrow.names
    col = next((c for c in ("session", "annee") if c in names), None)
    if col is None:
        return set()
    out = set()
    for v in pq.read_table(path, columns=[col]).column(0).to_pylist():
        try:
            out.add(int(float(str(v).strip())))
        except (TypeError, ValueError):
            continue
    return out


def check_session(ds, path: Path) -> str | None:
    """None when a vœux file holds exactly its registry year, else why it is refused."""
    if ds.kind != "voeux" or ds.year is None:
        return None
    got = sessions(path)
    return None if got == {ds.year} else f"holds session(s) {sorted(got) or 'none'}, not {ds.year}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest(raw_dir: Path = config.RAW_DIR) -> dict:
    p = raw_dir / MANIFEST
    return json.loads(p.read_text()) if p.exists() else {}


def ingest(raw_dir: Path = config.RAW_DIR, only: set[str] | None = None, force: bool = False) -> dict:
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(raw_dir)
    for ds in config.DATASETS:
        if only and ds.key not in only:
            continue
        dest = raw_dir / f"{ds.key}.parquet"
        if dest.exists() and not force:
            print(f"[skip] {ds.key} already present")
            continue
        last_err: Exception | None = None
        if ds.url:
            try:
                manifest[ds.key] = _ingest_file(ds, raw_dir, dest)
            except Exception as exc:  # noqa: BLE001
                if not ds.optional:
                    raise RuntimeError(f"could not ingest {ds.key}: {exc}") from exc
                print(f"[warn] optional {ds.key} not ingested: {exc}", file=sys.stderr)
                manifest.setdefault(ds.key, {})["error"] = str(exc)[:300]
            continue
        for ods_id in ds.ods_ids:
            url = config.parquet_export_url(ods_id, ds.base)
            print(f"[get ] {ds.key} <- {url}")
            try:
                _download(url, dest)
            except Exception as exc:  # noqa: BLE001 - try next id, report at the end
                last_err = exc
                print(f"[fail] {ods_id}: {exc}", file=sys.stderr)
                continue
            refused = check_session(ds, dest)
            if refused:                       # e.g. the rolling id already moved to the next campaign: try the next id
                dest.unlink(missing_ok=True)
                last_err = RuntimeError(f"{ods_id} {refused}")
                print(f"[skip] {ds.key}: {ods_id} {refused}", file=sys.stderr)
                continue
            meta = pq.ParquetFile(dest).metadata
            manifest[ds.key] = {
                "ods_id": ods_id,
                "url": url,
                "kind": ds.kind,
                "year": ds.year,
                "bytes": dest.stat().st_size,
                "sha256": _sha256(dest),
                "rows": meta.num_rows,
                "columns": meta.num_columns,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            last_err = None
            break
        if last_err is not None:
            if not ds.optional:
                raise RuntimeError(f"could not ingest {ds.key}: {last_err}") from last_err
            print(f"[warn] optional {ds.key} not ingested: {last_err}", file=sys.stderr)
            manifest.pop(ds.key, None)
            dest.unlink(missing_ok=True)
    (raw_dir / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    nxt = manifest.get(f"parcoursup_{config.NEXT_YEAR}")
    if nxt:                               # GitHub Actions shows this as a warning on the run (and in its summary)
        print(f"::warning title=Nouvelle campagne SIES::SIES a publié la session {config.NEXT_YEAR} "
              f"({nxt['rows']} formations, {nxt['ods_id']}). Le site affiche toujours {min(config.YEARS)}-{max(config.YEARS)} : "
              f"ajouter {config.NEXT_YEAR} à config.YEARS (sprint de mise à jour).")
    return manifest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    ap.add_argument("--only", nargs="*", help="dataset keys to fetch")
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    args = ap.parse_args(argv)
    ingest(args.raw_dir, set(args.only) if args.only else None, args.force)


if __name__ == "__main__":
    main()
