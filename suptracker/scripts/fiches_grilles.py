"""Harvest of the evaluation grids and expectations from the LIVE Parcoursup fiches (owner, 2026-11-13).

Run by the `suptracker-rapports` workflow, mode "grilles" (by hand, and every day after the reports' "live" mode). Each fiche
of the latest SIES campaign and cartographie session (rapports_live.codes) is read, its grid parsed by fiche_parse.parse,
and stored in data/fiches/:
  * etat.csv      one row per code: status (ok / sans_grille / rejetee / retry / failed), when it was read, the campaign the
                  grid serves (the fiche's "analysent les candidatures en avril-mai 2026"), the reason of a rejection;
  * champs.csv    the global grid: one row per field (rank, field, weight %, the detailed table's caption as a text id);
  * criteres.csv  the detailed grid: one row per criterion (field rank, rank, criterion and elements as text ids, importance 1-4);
  * attendus.csv  one row per code: national and complementary expectations, advice to candidates (text ids);
  * textes.csv.gz the texts, each stored ONCE under its digest (id), gzip members appended (a national text is shared by
                  every formation of a mention; the history stays small).
A fiche is read again when its last reading is older than REFRESH_DAYS (the grids change with each campaign: the 2027 fiches open
in December). Closed site (three fiches answer 404 / "indisponible"): nothing is written. Polite: one request at a time, paced,
the shared generic User-Agent.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from fiche_parse import parse  # noqa: E402
from rapports_harvest import UA, write  # noqa: E402
from rapports_live import codes, fetch_fiche  # noqa: E402

REFRESH_DAYS = 20
ETAT_COLS = ["cod_aff_form", "status", "lu_le", "session", "raison", "url"]
CHAMP_COLS = ["cod_aff_form", "session", "rang", "champ", "poids", "intitule_id"]
CRIT_COLS = ["cod_aff_form", "session", "champ_rang", "rang", "critere_id", "elements_id", "importance"]
ATT_COLS = ["cod_aff_form", "session", "nationaux_id", "complementaires_id", "conseils_id"]


def tid(t: str | None) -> str:
    return "" if not t else hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


def read_rows(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def known_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return {r["id"] for r in csv.DictReader(f)}


def append_texts(path: Path, rows: list[dict]) -> None:
    """One gzip member per run (append-only): a reader concatenates the members."""
    if not rows:
        return
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["id", "texte"])
    if not path.exists():
        w.writeheader()
    w.writerows(rows)
    with open(path, "ab") as f:
        f.write(gzip.compress(buf.getvalue().encode("utf-8"), mtime=0))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def harvest(http, db: str, out: Path, budget_s: float, pause: float = 1.0, refresh_days: int = REFRESH_DAYS) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    order = codes(db)
    etat = {r["cod_aff_form"]: r for r in read_rows(out / "etat.csv")}
    for c in order:
        etat.setdefault(c, {"cod_aff_form": c, "status": "todo", "lu_le": "", "session": "", "raison": "", "url": ""})
    champs = {}
    for r in read_rows(out / "champs.csv"):
        champs.setdefault(r["cod_aff_form"], []).append(r)
    crits = {}
    for r in read_rows(out / "criteres.csv"):
        crits.setdefault(r["cod_aff_form"], []).append(r)
    atts = {r["cod_aff_form"]: r for r in read_rows(out / "attendus.csv")}
    ids = known_ids(out / "textes.csv.gz")
    new_texts: list[dict] = []
    old = (datetime.now(timezone.utc) - timedelta(days=refresh_days)).strftime("%Y%m%d%H%M%S")
    first = [etat[c] for c in order if etat[c]["status"] in ("todo", "retry")]
    again = sorted((etat[c] for c in order if etat[c]["status"] in ("ok", "sans_grille", "rejetee", "failed") and etat[c]["lu_le"] < old),
                   key=lambda r: r["lu_le"])
    queue = first + again
    # is the site open? three fiches first (no write at all when closed)
    probe = [r["cod_aff_form"] for r in ([etat[c] for c in order if etat[c]["status"] == "ok"] or queue)[:3]] if queue else []
    if probe and all(fetch_fiche(http, c, pause)[0] is None for c in probe):
        return {"status": "closed", "checked_at": _now(), "todo": len(first)}

    def text_id(t: str | None) -> str:
        i = tid(t)
        if i and i not in ids:
            ids.add(i)
            new_texts.append({"id": i, "texte": t})
        return i

    n = 0
    for r in queue:
        if time.time() - t0 > budget_s:
            break
        c = r["cod_aff_form"]
        url, resp = fetch_fiche(http, c, pause)
        r["lu_le"] = _now()
        if url is None:
            r["status"] = "retry" if r["status"] == "todo" else "failed"
            r["raison"] = f"fiche {resp.status_code if resp is not None else 'none'}"
            continue
        p = parse(resp.text)
        r["url"], r["session"] = url, p["session"] or ""
        champs.pop(c, None)
        crits.pop(c, None)
        atts[c] = {"cod_aff_form": c, "session": p["session"] or "", "nationaux_id": text_id(p["attendus_nationaux"]),
                   "complementaires_id": text_id(p["attendus_complementaires"]), "conseils_id": text_id(p["conseils"])}
        if not p["ok"]:
            r["status"] = "sans_grille" if p["reason"] == "pas de grille" else "rejetee"
            r["raison"] = p["reason"]
        else:
            r["status"], r["raison"] = "ok", ""
            champs[c] = [{"cod_aff_form": c, "session": p["session"] or "", "rang": x["rang"], "champ": x["champ"], "poids": x["poids"],
                          "intitule_id": text_id(x.get("intitule"))} for x in p["champs"]]
            crits[c] = [{"cod_aff_form": c, "session": p["session"] or "", "champ_rang": k["champ_rang"], "rang": k["rang"],
                         "critere_id": text_id(k["critere"]), "elements_id": text_id(k["elements"]), "importance": k["importance"]}
                        for k in p["criteres"]]
        n += 1
        if n % 500 == 0:
            print(f"{n} fiches lues, {time.time() - t0:.0f} s", flush=True)
            _save(out, etat, champs, crits, atts, new_texts)
            new_texts = []
    _save(out, etat, champs, crits, atts, new_texts)
    by: dict = {}
    for r in etat.values():
        by[r["status"]] = by.get(r["status"], 0) + 1
    res = {"status": "open", "checked_at": _now(), "lues": n, "total": len(etat), "by_status": by}
    (out / "last_run.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def _save(out: Path, etat: dict, champs: dict, crits: dict, atts: dict, new_texts: list) -> None:
    key = lambda c: (len(c), c)  # noqa: E731  numeric order of the codes
    append_texts(out / "textes.csv.gz", new_texts)
    write(out / "etat.csv", ETAT_COLS, [etat[c] for c in sorted(etat, key=key)])
    write(out / "champs.csv", CHAMP_COLS, [x for c in sorted(champs, key=key) for x in champs[c]])
    write(out / "criteres.csv", CRIT_COLS, [x for c in sorted(crits, key=key) for x in crits[c]])
    write(out / "attendus.csv", ATT_COLS, [atts[c] for c in sorted(atts, key=key)])


def sample(http, out: Path, per_status: int = 6, pause: float = 1.0) -> dict:
    """Design material: a few fiches of each status the reader could not use (sans_grille, rejetee), saved MASKED (e-mail
    addresses and phone numbers replaced, as in what is read) under data/fiches/echantillon/<status>_<code>.html."""
    from fiche_parse import mask
    etat = read_rows(out / "etat.csv")
    dest = out / "echantillon"
    dest.mkdir(parents=True, exist_ok=True)
    picked: dict = {}
    for r in etat:
        if r["status"] in ("sans_grille", "rejetee") and len(picked.setdefault(r["status"], [])) < per_status:
            picked[r["status"]].append(r["cod_aff_form"])
    saved = []
    for st, cods in picked.items():
        for c in cods:
            url, resp = fetch_fiche(http, c, pause)
            if url is not None:
                (dest / f"{st}_{c}.html").write_text(mask(resp.text), encoding="utf-8")
                saved.append(f"{st}_{c}")
    return {"saved": saved}


def main(db: str, out: str, budget_min: float) -> None:
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as http:
        res = harvest(http, db, Path(out), budget_min * 60)
    print(json.dumps(res), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "--echantillon":
        with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as http:
            print(json.dumps(sample(http, Path(sys.argv[2]))), flush=True)
    else:
        main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 300)
