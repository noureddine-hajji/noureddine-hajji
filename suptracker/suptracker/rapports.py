"""Parcoursup public reports ("rapports publics des commissions d'examen des vœux"), per formation.

Source: the report PDFs archived by the Internet Archive, harvested and parsed by scripts/rapports_harvest.py (the
`suptracker-rapports` workflow) into data/rapports/harvest/: pdf_index.csv, synthese.csv, doublettes.csv, masked.csv,
qualitatif.jsonl.gz. Nothing here downloads anything.

A report is USED only when it is identified and verified:
  * its formation code is printed in its tables "(1234)" (2024 on), else it is the g_ti_cod of its link (older reports),
  * and its candidates who confirmed the vœu (summed over the calling groups) EQUAL the SIES nb_voe_pp of that code and
    session. Any other report is left out (counted in core.rapport_audit).
One report per (code, session): the latest verified capture.

Figures: per bac type and doublette, as published (confirmed, ranked, "en position de recevoir une proposition",
accepted). The rate shown is en_position / confirmed: the formation's own access rate broken down by doublette, computed
from published counts (never a chance of admission). "Autres doublettes" is the formation's own bucket.
Texts: the jury's criteria (with their published importance), the specialties it takes into account and their weight,
eliminating criteria, method, algorithm, advice: verbatim, never interpreted. Options (maths expertes...) are only
QUOTED when the jury names them. Signatures are never stored.
"""
from __future__ import annotations

import csv
import gzip
import json
import re
from pathlib import Path

from . import journey as J

HARVEST = Path(__file__).resolve().parents[1] / "data" / "rapports" / "harvest"
BAC = {"Baccalauréat Général": "bg", "Baccalauréat Technologique": "bt", "Baccalauréat Professionnel": "bp"}
IMPORTANCE = ("Essentiel", "Très important", "Important", "Complémentaire")
USABLE = ("ok", "ok_repare")          # ok_repare: rebuilt by qpdf and COMPLETE (scripts/rapports_harvest.complete)
LINK_RE = re.compile(r"g_ea_cod=([0-9A-Z]+)|g_ti_cod=(\d+)|c_ja_cod=(\d+)")


def clean_eds_list(items: list) -> list:
    """Twin of scripts/rapports_parse.clean_eds_list: the list stops at the first line that is not a specialty."""
    out = []
    for x in items:
        x = str(x).strip()
        if not x or "?" in x or len(x) > 90 or re.match(r"(?i)(crit[èe]res?|vous avez|pr[ée]ciser|non,|oui,)", x):
            break
        out.append(x)
    return out


def _bac(label: str) -> str | None:
    for k, v in BAC.items():
        if label.startswith(k):
            return v
    return None


def _link(url: str) -> dict:
    out = {}
    for m in LINK_RE.finditer(url or ""):
        if m.group(1):
            out["g_ea_cod"] = m.group(1)
        if m.group(2):
            out["g_ti_cod"] = m.group(2)
        if m.group(3):
            out["c_ja_cod"] = m.group(3)
    return out


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _insert(con, sql: str, rows: list) -> None:
    if rows:                                   # DuckDB refuses an empty executemany (e.g. no report matches the warehouse)
        con.executemany(sql, rows)


def _read(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def build(con, harvest: Path | None = HARVEST) -> dict:
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.rapport (cod_aff_form VARCHAR, session INTEGER, digest VARCHAR, capture VARCHAR,
        url VARCHAR, confirmes INTEGER, en_position INTEGER, acceptes INTEGER, methode VARCHAR, n_formations INTEGER, source VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE core.rapport_doublette (cod_aff_form VARCHAR, session INTEGER, bac VARCHAR, rang INTEGER,
        libelle VARCHAR, doublette_key VARCHAR, autres BOOLEAN, confirmes INTEGER, classes INTEGER, en_position INTEGER,
        acceptes INTEGER)""")
    con.execute("CREATE OR REPLACE TABLE core.rapport_masque (cod_aff_form VARCHAR, session INTEGER, bac VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE core.rapport_texte (digest VARCHAR, data VARCHAR)")
    con.execute("""CREATE OR REPLACE TABLE core.rapport_audit (digest VARCHAR, session INTEGER, code VARCHAR, methode VARCHAR,
        confirmes INTEGER, sies INTEGER, decision VARCHAR)""")
    if harvest is None or not (harvest / "pdf_index.csv").exists():
        return {"rapports": 0}
    idx = {r["digest"]: r for r in _read(harvest / "pdf_index.csv") if r.get("status") in USABLE}
    syn: dict = {}
    for r in _read(harvest / "synthese.csv"):
        syn.setdefault(r["digest"], []).append(r)
    sies = {(c, s): (v, e) for c, s, v, e in con.execute("""SELECT cod_aff_form, session, nb_voe_pp,
        coalesce(ran_grp1, 0) + coalesce(ran_grp2, 0) + coalesce(ran_grp3, 0) FROM core.formation_year""").fetchall()}
    chosen, audit = {}, []
    for dig, r in idx.items():
        s = _int(r.get("session"))
        rows = syn.get(dig, [])
        codes = [c for c in (r.get("codes") or "").split(";") if c]
        if codes:
            cands = [(c, "code_imprime", [x for x in rows if x["code"] == c]) for c in codes]
        else:                                   # older reports print no code: the link's g_ti_cod, checked below
            ti = _link(r["original"]).get("g_ti_cod")
            cands = [(ti, "g_ti_cod", rows)] if ti else []
        for code, how, rs in cands:
            conf = sum(_int(x["confirmes"]) or 0 for x in rs)
            pos = sum(_int(x["en_position"]) or 0 for x in rs)
            acc = sum(_int(x["acceptes"]) or 0 for x in rs)
            ref = sies.get((code, s))
            ok = bool(rs) and ref is not None and ref[0] == conf
            audit.append((dig, s, code, how, conf, ref[0] if ref else None, "retenu" if ok else "écarté"))
            if not ok:
                continue
            k = (code, s)
            if k not in chosen or r["timestamp"] > chosen[k]["capture"]:
                chosen[k] = {"cod_aff_form": code, "session": s, "digest": dig, "capture": r["timestamp"], "url": r["original"],
                             "confirmes": conf, "en_position": pos, "acceptes": acc, "methode": how, "n_formations": len(cands),
                             "source": "live" if r.get("source") == "live" else "archive"}
    _insert(con, "INSERT INTO core.rapport_audit VALUES (?, ?, ?, ?, ?, ?, ?)", audit)
    keys = ["cod_aff_form", "session", "digest", "capture", "url", "confirmes", "en_position", "acceptes", "methode", "n_formations", "source"]
    _insert(con, f"INSERT INTO core.rapport VALUES ({', '.join('?' * len(keys))})", [[v[k] for k in keys] for v in chosen.values()])
    used = {(v["digest"], v["cod_aff_form"]): v for v in chosen.values()}
    by_dig = {}
    for v in chosen.values():
        by_dig.setdefault(v["digest"], []).append(v)
    dbl, rank = [], {}
    for r in _read(harvest / "doublettes.csv"):
        dig = r["digest"]
        targets = [used[(dig, r["code"])]] if r["code"] and (dig, r["code"]) in used else \
            (by_dig.get(dig, []) if not r["code"] and len(by_dig.get(dig, [])) == 1 else [])
        for v in targets:
            bac = _bac(r["bac"])
            if bac is None:
                continue
            k = (v["cod_aff_form"], v["session"], bac)
            rank[k] = rank.get(k, 0) + 1
            p = J.parse_doublette(r["doublette"].replace("&", " "))
            autres = r["doublette"].strip().lower().startswith("autres")
            dbl.append((v["cod_aff_form"], v["session"], bac, rank[k], r["doublette"], J.doublette_key(*p) if p and bac == "bg" else None,
                        autres, _int(r["confirmes"]), _int(r["classes"]), _int(r["en_position"]), _int(r["acceptes"])))
    _insert(con, "INSERT INTO core.rapport_doublette VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", dbl)
    msk = set()
    for r in _read(harvest / "masked.csv"):
        dig = r["digest"]
        targets = [used[(dig, r["code"])]] if r["code"] and (dig, r["code"]) in used else \
            (by_dig.get(dig, []) if not r["code"] and len(by_dig.get(dig, [])) == 1 else [])
        for v in targets:
            if (b := _bac(r["bac"])):
                msk.add((v["cod_aff_form"], v["session"], b))
    _insert(con, "INSERT INTO core.rapport_masque VALUES (?, ?, ?)", sorted(msk))
    texts = []
    q = harvest / "qualitatif.jsonl.gz"
    if q.exists():
        with gzip.open(q, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d["digest"] in by_dig:
                    eds = d.get("eds") or {}
                    if eds.get("liste"):                # harvested before the parser stopped there: same rule, applied here
                        eds["liste"] = {k: clean_eds_list(v) for k, v in eds["liste"].items() if clean_eds_list(v)}
                    texts.append((d["digest"], json.dumps({k: d.get(k) for k in TEXT_KEYS}, ensure_ascii=False)))
    _insert(con, "INSERT INTO core.rapport_texte VALUES (?, ?)", texts)
    return {"rapports": len(chosen), "doublettes": len(dbl), "textes": len(texts), "ecartes": sum(1 for a in audit if a[-1] != "retenu")}


TEXT_KEYS = ("criteres", "eds", "options_citees", "eliminatoires", "modalites", "algorithme", "conseils")


def _has(con, schema, table) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
                            [schema, table]).fetchone()[0])


def rate(pos, conf):
    return None if not conf or pos is None else round(100 * pos / conf, 1)


def for_formation(con, cod: str, session: int | None = None) -> dict | None:
    """The report block of a formation page: the report of this session when there is one, else the most recent one of
    this code (its session is always shown)."""
    if not _has(con, "core", "rapport"):
        return None
    src_col = "source" if con.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema = 'core'
        AND table_name = 'rapport' AND column_name = 'source'""").fetchone()[0] else "'archive'"   # a warehouse built before the live harvest
    r = con.execute(f"""SELECT session, digest, capture, url, confirmes, en_position, methode, n_formations, {src_col} FROM core.rapport
                       WHERE cod_aff_form = ? ORDER BY (session = ?) DESC, session DESC LIMIT 1""", [cod, session]).fetchone()
    if not r:
        return None
    s, dig, cap, url, conf, pos, how, nf, src = r
    voies = {}
    for bac, rang, lib, dkey, autres, c, cl, p, a in con.execute("""SELECT bac, rang, libelle, doublette_key, autres, confirmes,
            classes, en_position, acceptes FROM core.rapport_doublette WHERE cod_aff_form = ? AND session = ? ORDER BY bac, rang""",
                                                                  [cod, s]).fetchall():
        voies.setdefault(bac, []).append({"libelle": lib, "key": dkey, "autres": autres, "confirmes": c, "classes": cl,
                                          "en_position": p, "acceptes": a, "taux": rate(p, c)})
    masked = [b for (b,) in con.execute("SELECT bac FROM core.rapport_masque WHERE cod_aff_form = ? AND session = ? ORDER BY bac",
                                        [cod, s]).fetchall()]
    t = con.execute("SELECT data FROM core.rapport_texte WHERE digest = ?", [dig]).fetchone()
    textes = json.loads(t[0]) if t else None
    sessions = [x for (x,) in con.execute("SELECT session FROM core.rapport WHERE cod_aff_form = ? ORDER BY session", [cod]).fetchall()]
    live = src == "live"                  # read on the Parcoursup fiche itself: the link is Parcoursup's (until the next campaign)
    return {"session": s, "sessions": sessions, "capture": cap, "source": "live" if live else "archive",
            "archive": url if live else f"https://web.archive.org/web/{cap}/{url}",
            "confirmes": conf, "en_position": pos, "taux_global": rate(pos, conf), "methode": how, "concours": nf > 1,
            "doublettes": voies, "masques": masked, "textes": textes}


def pick(block: dict | None, dkey: str | None) -> dict | None:
    """The student's row in THIS formation's report: its own doublette, else the formation's 'Autres doublettes' (Python twin
    of the page's pickRapport)."""
    if not block or not dkey:
        return None
    rows = block["doublettes"].get("bg") or []
    mine = next((x for x in rows if x["key"] == dkey), None)
    if mine:
        return {**mine, "source": "doublette"}
    other = next((x for x in rows if x["autres"]), None)
    return {**other, "source": "autres"} if other else None
