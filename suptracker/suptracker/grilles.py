"""Evaluation grids and expected skills of each formation, read on its LIVE Parcoursup fiche (owner, 2026-11-13).

The harvest (scripts/fiches_grilles.py, workflow mode "grilles") stores in data/fiches/ what each fiche publishes:
  * the GLOBAL grid: the fields the jury examines (Résultats scolaires, Méthodes de travail, Savoir-être, Motivation,
    Engagement et activités) with their weight in % (they add up to 100);
  * the DETAILED grid: per field, each criterion, the elements it reads and its importance (Complémentaire 1, Important 2,
    Très important 3, Essentiel 4, as the fiche prints it);
  * the national expectations ("attendus nationaux"), the formation's complementary ones, the advice to candidates;
  * the notice under "Candidater à la formation" (`info`), e.g. an apprenticeship formation that examines no application.

Rules:
  * Published values only, verbatim: no weight or importance is recomputed, merged, averaged or turned into a score;
    never a chance. The grid is the one the fiche publishes for ITS campaign (the fiche's "analysent les candidatures en
    avril-mai 2026"); the page says which and that the fiche fait foi.
  * The build checks again what the harvest checked (weights add up to 100, every field has its criteria, importance 1-4,
    every text id resolves): a formation that fails is left out whole, never half shown.
  * Texts are stored once by id in the texts file beside the warehouse (`rapports.textes_path`): the national expectations
    are shared by every formation of a mention. E-mail addresses and phone numbers were masked at reading (fiche_parse).
"""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from . import rapports as RP

FICHES = Path(__file__).resolve().parents[1] / "data" / "fiches"
IMPORTANCE = {1: "Complémentaire", 2: "Important", 3: "Très important", 4: "Essentiel"}
FIELDS = ("Résultats scolaires", "Méthodes de travail", "Savoir-être", "Motivation", "Engagement et activités")


def _read(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def read_texts(path: Path) -> dict:
    """textes.csv.gz: gzip members appended by each run (one header, in the first member)."""
    if not path.exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return {r["id"]: r["texte"] for r in csv.DictReader(f)}


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def assemble(src: Path) -> tuple[list[dict], dict, list[tuple]]:
    """(formations kept, texts they use, audit rows). Each formation: its grid with text ids, checked again."""
    etat = {r["cod_aff_form"]: r for r in _read(src / "etat.csv")}
    texts = read_texts(src / "textes.csv.gz")
    champs, crits = {}, {}
    for r in _read(src / "champs.csv"):
        champs.setdefault(r["cod_aff_form"], []).append(r)
    for r in _read(src / "criteres.csv"):
        crits.setdefault(r["cod_aff_form"], []).append(r)
    atts = {r["cod_aff_form"]: r for r in _read(src / "attendus.csv")}
    out, used, audit = [], {}, []

    def tx(i):
        if not i:
            return None
        if i not in texts:
            raise KeyError(i)
        used[i] = texts[i]
        return i

    for c, e in etat.items():
        st = e.get("status")
        if st not in ("ok", "sans_grille", "rejetee"):
            continue
        a = atts.get(c) or {}
        try:
            g = {"cod_aff_form": c, "session": _int(e.get("session")), "lu_le": e.get("lu_le") or "", "url": e.get("url") or "",
                 "nationaux": tx(a.get("nationaux_id")), "complementaires": tx(a.get("complementaires_id")),
                 "conseils": tx(a.get("conseils_id")), "info": tx(a.get("info_id")), "champs": [], "grille": st == "ok"}
            if st == "ok":
                ch = sorted(champs.get(c, []), key=lambda r: _int(r["rang"]) or 0)
                cr = crits.get(c, [])
                poids = [_int(r["poids"]) for r in ch]
                if not ch or None in poids or sum(poids) != 100 or [_int(r["rang"]) for r in ch] != list(range(1, len(ch) + 1)):
                    raise ValueError("poids")
                for r in ch:
                    k = sorted((x for x in cr if _int(x["champ_rang"]) == _int(r["rang"])), key=lambda x: _int(x["rang"]) or 0)
                    if not k or any(_int(x["importance"]) not in IMPORTANCE for x in k):
                        raise ValueError("critères")
                    g["champs"].append({"rang": _int(r["rang"]), "champ": r["champ"], "poids": _int(r["poids"]),
                                        "intitule": tx(r.get("intitule_id")),
                                        "criteres": [{"critere": tx(x["critere_id"]), "elements": tx(x["elements_id"]),
                                                      "importance": _int(x["importance"])} for x in k]})
                if sum(len(x["criteres"]) for x in g["champs"]) != len(cr):
                    raise ValueError("critères hors champ")
            if not g["grille"] and not (g["nationaux"] or g["complementaires"] or g["info"]):
                audit.append((c, st, "rien à montrer"))
                continue
        except (KeyError, ValueError) as err:
            audit.append((c, st, f"écartée : {err}"))
            continue
        audit.append((c, st, "retenue"))
        out.append(g)
    return out, used, audit


def build(con, textes: Path | None = None, src: Path | None = FICHES) -> dict:
    """core.fiche_grille (one row per formation: session, reading date, link, grid or not), core.fiche_champ (field weights,
    for later reading in SQL), core.fiche_audit. The grids as JSON with text ids (grille_data) and the texts (grille_texte) go
    to `textes`, the file beside the warehouse written by rapports.build first: 10 MB of JSON would push the warehouse over its
    95 MB budget (measured 2026-11-14 at half the harvest). Without that file (tests), both stay in core."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.fiche_grille (cod_aff_form VARCHAR, session INTEGER, lu_le VARCHAR, url VARCHAR,
        grille BOOLEAN)""")
    con.execute("CREATE OR REPLACE TABLE core.fiche_champ (cod_aff_form VARCHAR, rang INTEGER, champ VARCHAR, poids INTEGER)")
    con.execute("CREATE OR REPLACE TABLE core.fiche_audit (cod_aff_form VARCHAR, status VARCHAR, decision VARCHAR)")
    for t in ("grille_texte", "grille_data"):
        con.execute(f"DROP TABLE IF EXISTS core.{t}")
    rows, used, audit = assemble(src) if src is not None and (src / "etat.csv").exists() else ([], {}, [])
    RP._insert(con, "INSERT INTO core.fiche_audit VALUES (?, ?, ?)", audit)
    RP._insert(con, "INSERT INTO core.fiche_grille VALUES (?, ?, ?, ?, ?)",
               [(g["cod_aff_form"], g["session"], g["lu_le"], g["url"], g["grille"]) for g in rows])
    RP._insert(con, "INSERT INTO core.fiche_champ VALUES (?, ?, ?, ?)",
               [(g["cod_aff_form"], x["rang"], x["champ"], x["poids"]) for g in rows for x in g["champs"]])
    data = [(g["cod_aff_form"], json.dumps({k: g[k] for k in ("nationaux", "complementaires", "conseils", "info", "champs")},
                                           ensure_ascii=False)) for g in rows]
    tx = sorted(used.items())

    def write(c, prefix):
        c.execute(f"CREATE OR REPLACE TABLE {prefix}grille_texte (id VARCHAR, texte VARCHAR)")
        c.execute(f"CREATE OR REPLACE TABLE {prefix}grille_data (cod_aff_form VARCHAR, data VARCHAR)")
        RP._insert(c, f"INSERT INTO {prefix}grille_texte VALUES (?, ?)", tx)
        RP._insert(c, f"INSERT INTO {prefix}grille_data VALUES (?, ?)", data)

    if textes is None or not textes.exists():
        write(con, "core.")
    else:
        import duckdb
        tc = duckdb.connect(str(textes))
        try:
            write(tc, "")
            tc.execute("CHECKPOINT")
        finally:
            tc.close()
    return {"fiches": len(rows), "grilles": sum(g["grille"] for g in rows), "textes": len(tx),
            "ecartees": sum(1 for a in audit if a[2].startswith("écartée"))}


def _side(con):
    """The cursor that holds grille_texte / grille_data: the warehouse itself (tests), else the file beside it."""
    if RP._has(con, "core", "grille_texte"):
        return con, "core."
    db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    f = RP.textes_path(Path(db[0])) if db and db[0] else None
    if f is None or not f.exists():
        return None, ""
    c = RP._texts_con(str(f), f.stat().st_mtime_ns).cursor()
    n = c.execute("""SELECT count(*) FROM information_schema.tables WHERE table_name IN ('grille_texte', 'grille_data')""").fetchone()[0]
    return (c, "") if n == 2 else (None, "")


def _texts(c, prefix: str, ids: set) -> dict:
    ids = sorted(i for i in ids if i)
    if not ids:
        return {}
    return dict(c.execute(f"SELECT id, texte FROM {prefix}grille_texte WHERE id IN ({', '.join('?' * len(ids))})", ids).fetchall())


def for_formation(con, cod: str) -> dict | None:
    """The fiche's grid and expectations with their texts, or None (no fiche read, or nothing usable)."""
    if not RP._has(con, "core", "fiche_grille"):
        return None
    r = con.execute("SELECT session, lu_le, url, grille FROM core.fiche_grille WHERE cod_aff_form = ?", [cod]).fetchone()
    if not r:
        return None
    s, lu, url, grille = r
    c, prefix = _side(con)
    if c is None:
        return None
    dr = c.execute(f"SELECT data FROM {prefix}grille_data WHERE cod_aff_form = ?", [cod]).fetchone()
    if not dr:
        return None                                   # the side file is from another build: nothing rather than a guess
    d = json.loads(dr[0])
    ids = {d.get("nationaux"), d.get("complementaires"), d.get("conseils"), d.get("info")}
    for x in d["champs"]:
        ids.add(x.get("intitule"))
        for k in x["criteres"]:
            ids.update((k["critere"], k["elements"]))
    t = _texts(c, prefix, ids)
    if any(i and i not in t for i in ids):
        return None                                   # a missing text: nothing rather than half a grid
    return {"session": s, "lu_le": f"{lu[:4]}-{lu[4:6]}-{lu[6:8]}" if len(lu) >= 8 else None,
            "url": url if url.startswith("https://") and "parcoursup.fr/" in url else None, "grille": bool(grille),
            "nationaux": t.get(d.get("nationaux")), "complementaires": t.get(d.get("complementaires")),
            "conseils": t.get(d.get("conseils")), "info": t.get(d.get("info")),
            "champs": [{"rang": x["rang"], "champ": x["champ"], "poids": x["poids"], "intitule": t.get(x.get("intitule")),
                        "criteres": [{"critere": t[k["critere"]], "elements": t.get(k["elements"]), "importance": k["importance"],
                                      "importance_label": IMPORTANCE[k["importance"]]} for k in x["criteres"]]}
                       for x in d["champs"]]}
