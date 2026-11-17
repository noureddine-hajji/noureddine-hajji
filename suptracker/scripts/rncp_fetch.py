"""Fetch the official RNCP export of France Compétences (data.gouv.fr, Licence Ouverte) into data/rncp/.

Robustesse 2035 per formation (owner, 2026-11-17): the skills a diploma develops are read from its RNCP fiche (blocks of
competences, ROME codes, NSF). The development sandbox cannot reach data.gouv.fr, so the `suptracker-rncp` workflow runs this.

Writes data/rncp/export-fiches-csv.zip (the export as published, the latest « export-fiches-csv-YYYY-MM-DD.zip » resource of
the dataset) and data/rncp/inventaire.json: the resource's name, date, URL and SHA-256, and for every CSV member its columns
and row count, so the reading code can be written against what is really published. Official hosts only.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

DATASET = "5eebbc067a14b6fecc9c9976"            # « Répertoire national des certifications professionnelles et répertoire spécifique »
API = f"https://www.data.gouv.fr/api/1/datasets/{DATASET}/"
HOSTS = {"www.data.gouv.fr", "static.data.gouv.fr"}
NAME = re.compile(r"^export-fiches-csv-(\d{4}-\d{2}-\d{2})\.zip$")


def official(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in HOSTS:
        raise SystemExit(f"refused host: {url}")
    return url


def latest(client: httpx.Client) -> dict:
    d = client.get(official(API)).raise_for_status().json()
    best = None
    for r in d.get("resources") or []:
        m = NAME.match(r.get("title") or "")
        if m and (best is None or m.group(1) > best[0]):
            best = (m.group(1), r)
    if best is None:
        raise SystemExit("no export-fiches-csv resource in the dataset")
    return {"date": best[0], "title": best[1]["title"], "url": official(best[1]["url"])}


def inventory(blob: bytes) -> list[dict]:
    out = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in sorted(z.namelist()):
            if not name.lower().endswith(".csv"):
                out.append({"membre": name})
                continue
            raw = z.read(name)
            text = None
            for enc in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            sep = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
            rows = list(csv.reader(io.StringIO(text), delimiter=sep))
            out.append({"membre": name, "encodage": enc, "separateur": sep, "colonnes": rows[0] if rows else [],
                        "lignes": max(0, len(rows) - 1)})
    return out


def main(argv: list[str]) -> int:
    d = Path(argv[1] if len(argv) > 1 else "data/rncp")
    d.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "SupCompass-open-data-reader"}) as client:
        meta = latest(client)
        resp = client.get(meta["url"])
        resp.raise_for_status()
        if urlparse(str(resp.url)).hostname not in HOSTS:
            raise SystemExit(f"redirected off the official hosts: {resp.url}")
        blob = resp.content
    meta["sha256"] = hashlib.sha256(blob).hexdigest()
    meta["membres"] = inventory(blob)
    (d / "export-fiches-csv.zip").write_bytes(blob)
    (d / "inventaire.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(json.dumps({k: meta[k] for k in ("date", "title", "sha256")}, ensure_ascii=False))
    for m in meta["membres"]:
        print(m.get("membre"), m.get("lignes"), (m.get("colonnes") or [])[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
