"""Owner, 2026-11-18: what a trip between the student's town and the formation costs. Fetches three OFFICIAL open datasets
(blocked in the development sandbox) into suptracker/data/transports/, keeping only the columns the site reads:

  - SNCF, « Tarifs TGV INOUI et OUIGO » (price range per origin-destination, class and fare profile): tarifs_tgv.csv.gz;
  - SNCF, « Gares de voyageurs » (name, UIC code, position): gares.csv.gz;
  - Ministère de l'Économie, « Prix des carburants en France - flux instantané v2 » (price per station and fuel, with its update
    time): carburants.csv.gz.

Each file is written only when its content changed (no commit for a date alone); versions.csv records when each was read.
Run by the `suptracker-transports` workflow (monthly, workflow_dispatch, or a push of data/transports/request.json).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

UA = "Mozilla/5.0 (compatible; SupCompass transport costs; robot)"
SOURCES = {
    "tarifs_tgv": ("https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/tarifs-tgv-inoui-ouigo/exports/csv?use_labels=true",
                   {"transporteur": ("transporteur",), "origine": ("gare origine",), "origine_uic": ("gare origine - code uic",),
                    "destination": ("gare destination",), "destination_uic": ("gare destination - code uic",), "classe": ("classe",),
                    "profil": ("profil tarifaire",), "prix_min": ("prix minimum",), "prix_max": ("prix maximum",)}),
    "gares": ("https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/gares-de-voyageurs/exports/csv?use_labels=true",
              {"nom": ("nom_gare", "nom gare", "nom"), "uic": ("code_uic", "code uic"), "position": ("position géographique", "position geographique"),
               "commune": ("code commune",)}),
    "carburants": ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/exports/csv?use_labels=true",
                   {"id": ("id",), "departement": ("code_departement",), "gazole": ("prix gazole",), "gazole_maj": ("prix gazole mis à jour le",),
                    "e10": ("prix e10",), "e10_maj": ("prix e10 mis à jour le",), "sp95": ("prix sp95",), "sp95_maj": ("prix sp95 mis à jour le",)}),
}


def gz(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), mtime=0)


def norm(h: str) -> str:
    return " ".join((h or "").replace("﻿", "").strip().lower().split())


def pick(raw: bytes, cols: dict) -> list[dict] | None:
    """The rows with the wanted columns found by their (lower-cased) header names; None when a column is missing."""
    text = raw.decode("utf-8-sig", errors="replace")
    head = text.split("\n", 1)[0]
    delim = ";" if head.count(";") >= head.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = [norm(h) for h in next(reader, [])]
    idx = {}
    for k, names in cols.items():
        i = next((header.index(n) for n in names if n in header), None)
        if i is None:
            return None
        idx[k] = i
    return [{k: (row[i].strip() if i < len(row) else "") for k, i in idx.items()} for row in reader if row]


def main(out: str) -> int:
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    rf = d / "request.json"
    req = json.loads(rf.read_text()) if rf.exists() else {}
    vf = d / "versions.csv"
    versions = list(csv.DictReader(open(vf, encoding="utf-8"))) if vf.exists() else []
    log, now = [], datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with httpx.Client(follow_redirects=True, timeout=300, headers={"User-Agent": UA}) as client:
        for key, (url, cols) in SOURCES.items():
            if req.get(key) is False:
                continue
            try:
                r = client.get(url)
            except httpx.HTTPError as e:
                log.append({key: f"error {type(e).__name__}"})
                continue
            if r.status_code != 200:
                log.append({key: f"http {r.status_code}"})
                continue
            rows = pick(r.content, cols)
            if not rows:
                log.append({key: "columns not found (file kept unchanged)"})
                continue
            rows.sort(key=lambda x: tuple(x.values()))
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=list(cols), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
            body = gz(buf.getvalue())
            digest = hashlib.sha256(body).hexdigest()
            f = d / f"{key}.csv.gz"
            if f.exists() and hashlib.sha256(f.read_bytes()).hexdigest() == digest:
                log.append({key: f"unchanged ({len(rows)} rows)"})
                continue
            f.write_bytes(body)
            versions = [v for v in versions if v["fichier"] != f.name] + [{"fichier": f.name, "lu_le": now, "url": url,
                                                                           "lignes": str(len(rows)), "sha256": digest}]
            log.append({key: f"written ({len(rows)} rows)"})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["fichier", "lu_le", "url", "lignes", "sha256"], lineterminator="\n")
    w.writeheader()
    w.writerows(sorted(versions, key=lambda v: v["fichier"]))
    vf.write_text(buf.getvalue(), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False, indent=1))
    return 0 if all((d / f"{k}.csv.gz").exists() for k in SOURCES) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/transports"))
