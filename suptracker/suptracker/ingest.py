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
        for ods_id in ds.ods_ids:
            url = config.parquet_export_url(ods_id, ds.base)
            print(f"[get ] {ds.key} <- {url}")
            try:
                _download(url, dest)
            except Exception as exc:  # noqa: BLE001 - try next id, report at the end
                last_err = exc
                print(f"[fail] {ods_id}: {exc}", file=sys.stderr)
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
            raise RuntimeError(f"could not ingest {ds.key}: {last_err}") from last_err
    (raw_dir / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
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
