"""Similar formations' reports (owner's request, 2026-11-10): when a formation's own public report gives no bac général
table by doublette, or no jury texts, the page reads the verified reports of the SIMILAR formations instead.

Similar = same type and same mention: the same SIES `fili` and `fil_lib_voe_acc` (e.g. every "BUT - Gestion des entreprises
et des administrations"), the same session. Two labels group formations that share nothing but a format; they get no similar
formations (GENERIC). Only verified reports count: printed code + confirmed candidates = SIES (`recoupe`). A report shared by a
concours (one PDF for several formations) counts once (by digest).

What is computed, from PUBLISHED counts only:
  * Doublettes (bac général). For a doublette k, P_k = the similar reports whose table has a row for k (a formation's own
    "Autres doublettes" bucket is never pooled: it is that formation's own). Pooled rate of k = sum en_position / sum confirmed
    over P_k; "all bac général" = every row of the same P_k (same reports in the numerator and the denominator). Shown when
    |P_k| >= MIN_REPORTS and the pooled confirmed >= MIN_CANDIDATS.
    The figure for THIS formation is an ESTIMATION: its published bac général proposal rate x (pooled k / pooled all), capped
    at 100. It is the same method as the national group estimate (doublettes.estimate), with the ratio measured in the reports
    of formations of the same diploma and mention instead of the national group. Never a chance.
  * Jury expectations. Per standard Parcoursup field (5 fields, printed labels mapped by fixed keywords), the number of similar
    reports at each published importance (the field's highest importance in that report); the specialties the reports say they
    take into account, with their counts; the options they cite. Counts of reports, never an average or a score. The jury
    texts themselves stay on each formation's own page (the page links them).
Precomputed at build (mart.semblable_dbl, mart.semblable_jury); a formation never reads its own report through this block: the
page uses it only where the own report lacks the part (red team S2).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import doublettes as DBL

MIN_REPORTS = 3          # similar reports, at least, behind any pooled figure
MIN_CANDIDATS = 20       # pooled confirmed candidates of the doublette, same rule as the national "rare" threshold
GENERIC = {"FCIL", "Licence professionnelle"}          # labels that group unrelated formations: no similar formations
IMPORTANCES = ("Essentiel", "Très important", "Important", "Complémentaire")
# the five standard fields of a Parcoursup report, as printed (cells wrapped across lines are mapped by their own words)
CHAMPS = (
    ("resultats", "Résultats académiques", ("résultat",)),
    ("competences", "Compétences académiques, acquis méthodologiques, savoir-faire", ("compétence", "savoir-faire", "savoir- faire")),
    ("savoir_etre", "Savoir-être", ("savoir-être", "savoir être")),
    ("motivation", "Motivation, connaissance de la formation, cohérence du projet", ("motivation", "cohérence du projet", "connaissance de la")),
    ("engagements", "Engagements, activités et centres d'intérêt, réalisations péri ou extra-scolaires",
     ("engagement", "intérêt", "extra", "scolaires")),
)
CHAMP_LABEL = {k: lab for k, lab, _ in CHAMPS}


def champ_of(label: str | None) -> str | None:
    s = " ".join(str(label or "").lower().split())
    for k, _, words in CHAMPS:
        if any(w in s for w in words):
            return k
    return None


def rate(p, c):
    return None if not c else round(100.0 * (p or 0) / c, 1)


def _has(con, schema, table):
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
                            [schema, table]).fetchone()[0])


def _reports(con):
    """(session, fili, filiere, digest, cod) of every verified report, one row per formation it covers."""
    return con.execute("""SELECT r.session, f.fili, f.fil_lib_voe_acc, r.digest, r.cod_aff_form
        FROM core.rapport r JOIN core.formation_year f ON f.cod_aff_form = r.cod_aff_form AND f.session = r.session
        WHERE coalesce(r.recoupe, true) AND f.fil_lib_voe_acc IS NOT NULL AND f.fili IS NOT NULL""").fetchall()


def _texts(con, textes: Path | None):
    """digest -> parsed texts, from the warehouse table or the file beside it."""
    if _has(con, "core", "rapport_texte"):
        rows = con.execute("SELECT digest, data FROM core.rapport_texte").fetchall()
    elif textes is not None and Path(textes).exists():
        import duckdb
        tc = duckdb.connect(str(textes), read_only=True)
        try:
            rows = tc.execute("SELECT digest, data FROM rapport_texte").fetchall()
        finally:
            tc.close()
    else:
        rows = []
    return {d: json.loads(x) for d, x in rows}


def jury_counts(texts: list[dict]) -> dict:
    """The jury aggregate of a list of reports' texts (pure, the red team re-derives it)."""
    champs = {k: {i: 0 for i in IMPORTANCES} for k, _, _ in CHAMPS}
    eds = {"oui": 0, "non": 0, "non_dit": 0, "generale": {}, "autres": {}}
    opts = {}
    for t in texts:
        best = {}
        for c in t.get("criteres") or []:
            k, imp = champ_of(c.get("champ")), c.get("importance")
            if k and imp in IMPORTANCES and (k not in best or IMPORTANCES.index(imp) < IMPORTANCES.index(best[k])):
                best[k] = imp
        for k, imp in best.items():
            champs[k][imp] += 1
        e = t.get("eds") or {}
        pec = str(e.get("pris_en_compte") or "")
        eds["oui" if pec.lower().startswith("oui") else "non" if pec.lower().startswith("non") else "non_dit"] += 1
        for serie, items in (e.get("liste") or {}).items():
            bucket = eds["generale"] if serie == "Série Générale" else eds["autres"].setdefault(serie, {})
            for it in set(items or []):
                bucket[it] = bucket.get(it, 0) + 1
        for k in (t.get("options_citees") or {}):
            opts[k] = opts.get(k, 0) + 1
    return {"n": len(texts), "champs": champs, "eds": eds, "options": opts}


def build(con, textes: Path | None = None) -> dict:
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    con.execute("""CREATE OR REPLACE TABLE mart.semblable_dbl (session INTEGER, fili VARCHAR, filiere VARCHAR, doublette_key VARCHAR,
        n_rapports INTEGER, confirmes INTEGER, en_position INTEGER, tous_confirmes INTEGER, tous_en_position INTEGER)""")
    con.execute("""CREATE OR REPLACE TABLE mart.semblable_jury (session INTEGER, fili VARCHAR, filiere VARCHAR, n_rapports INTEGER,
        data VARCHAR)""")
    if not _has(con, "core", "rapport") or not _has(con, "core", "rapport_doublette"):
        return {"groupes": 0}
    reps = _reports(con)
    by_dig = {}                                  # digest -> (session, fili, filiere): a concours report counts once
    for s, fili, fil, dig, cod in reps:
        if fil in GENERIC:
            continue
        by_dig.setdefault(dig, (s, fili, fil))
    # each report's bac général rows, read once per digest (the first formation it covers carries them)
    rows = {}
    for dig, cod, s, key, autres, c, p in con.execute("""SELECT r.digest, d.cod_aff_form, d.session, d.doublette_key, d.autres,
            d.confirmes, d.en_position FROM core.rapport_doublette d
            JOIN core.rapport r ON r.cod_aff_form = d.cod_aff_form AND r.session = d.session
            WHERE d.bac = 'bg' ORDER BY r.digest, d.cod_aff_form, d.rang""").fetchall():
        first = rows.setdefault(dig, {"cod": cod, "rows": []})
        if first["cod"] == cod:
            first["rows"].append((key, bool(autres), c or 0, p or 0))
    pool = {}
    for dig, (s, fili, fil) in by_dig.items():
        r = rows.get(dig)
        if not r or not r["rows"]:
            continue
        tc, tp = sum(x[2] for x in r["rows"]), sum(x[3] for x in r["rows"])
        for key, autres, c, p in r["rows"]:
            if autres or not key:
                continue
            a = pool.setdefault((s, fili, fil, key), [0, 0, 0, 0, 0])
            a[0] += 1; a[1] += c; a[2] += p; a[3] += tc; a[4] += tp
    dbl = [(s, fi, fl, k, *v) for (s, fi, fl, k), v in sorted(pool.items())]
    if dbl:
        con.executemany("INSERT INTO mart.semblable_dbl VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", dbl)
    texts = _texts(con, textes)
    groups = {}
    for dig, key in by_dig.items():
        if dig in texts:
            groups.setdefault(key, []).append(texts[dig])
    jury = [(s, fi, fl, len(ts), json.dumps(jury_counts(ts), ensure_ascii=False)) for (s, fi, fl), ts in sorted(groups.items())]
    if jury:
        con.executemany("INSERT INTO mart.semblable_jury VALUES (?, ?, ?, ?, ?)", jury)
    return {"doublettes": len(dbl), "jury": len(jury)}


def for_formation(con, cod: str, session: int | None = None) -> dict | None:
    """The similar formations of this one (same session): pooled doublettes, jury counts, and the list of their pages."""
    if not _has(con, "mart", "semblable_dbl"):
        return None
    rec = con.execute("""SELECT session, fili, fil_lib_voe_acc FROM core.formation_year WHERE cod_aff_form = ?
                         ORDER BY (session = ?) DESC, session DESC LIMIT 1""", [cod, session]).fetchone()
    if not rec or rec[2] is None or rec[2] in GENERIC:
        return None
    s, fili, fil = rec
    peers = con.execute("""SELECT DISTINCT f.cod_aff_form, f.g_ea_lib_vx, f.ville_etab, f.acad_mies
        FROM core.rapport r JOIN core.formation_year f ON f.cod_aff_form = r.cod_aff_form AND f.session = r.session
        WHERE r.session = ? AND f.fili = ? AND f.fil_lib_voe_acc = ? AND coalesce(r.recoupe, true) AND r.cod_aff_form <> ?
        ORDER BY f.acad_mies, f.ville_etab, f.g_ea_lib_vx, f.cod_aff_form""", [s, fili, fil, cod]).fetchall()
    dbl = [{"key": k, "label": DBL.label(k), "n_rapports": n, "confirmes": c, "en_position": p, "taux": rate(p, c),
            "tous_confirmes": tc, "tous_en_position": tp, "tous_taux": rate(tp, tc)}
           for k, n, c, p, tc, tp in con.execute("""SELECT doublette_key, n_rapports, confirmes, en_position, tous_confirmes,
               tous_en_position FROM mart.semblable_dbl WHERE session = ? AND fili = ? AND filiere = ?
               ORDER BY confirmes DESC, doublette_key""", [s, fili, fil]).fetchall()
           if n >= MIN_REPORTS and c >= MIN_CANDIDATS]
    j = con.execute("SELECT n_rapports, data FROM mart.semblable_jury WHERE session = ? AND fili = ? AND filiere = ?",
                    [s, fili, fil]).fetchone()
    jury = json.loads(j[1]) if j and j[0] >= MIN_REPORTS else None
    if not dbl and not jury:
        return None
    return {"session": s, "filiere": fil, "fili": fili, "doublettes": dbl, "jury": jury, "champs": CHAMP_LABEL,
            "formations": [{"cod_aff_form": c, "etablissement": e, "ville": v, "academie": a} for c, e, v, a in peers],
            "min_rapports": MIN_REPORTS, "min_candidats": MIN_CANDIDATS}


def pick(sem: dict | None, dkey: str | None) -> dict | None:
    if not sem or not dkey:
        return None
    return next((x for x in sem["doublettes"] if x["key"] == dkey), None)


def estimate(series_bg: dict | None, sem: dict | None, dkey: str | None) -> dict | None:
    """This formation's published bac général proposal rate x (doublette / all bac général) in the similar reports, capped at
    100 (Python twin of the page's estimateSemblable; same shape as doublettes.estimate)."""
    x = pick(sem, dkey)
    if not x or not series_bg or series_bg.get("taux") is None or not x["tous_taux"] or x["taux"] is None:
        return None
    r = x["taux"] / x["tous_taux"]
    trend = [{"session": t["session"], "taux": None if t["taux"] is None else round(min(100.0, t["taux"] * r), 1)}
             for t in series_bg.get("trend", [])]
    return {"taux": round(min(100.0, series_bg["taux"] * r), 1), "base": series_bg["taux"], "ratio": round(r, 3),
            "source": "semblables", "label": x["label"], "n_rapports": x["n_rapports"], "mine": x["taux"],
            "tous": x["tous_taux"], "fragile": bool(series_bg.get("fragile")), "estimation": True, "trend": trend}
