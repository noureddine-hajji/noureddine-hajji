"""Sprint "Doublettes": proposal rates by Terminale specialty doublette and by bac route (voie), everywhere a student looks.

What the open data allows (checked on the real warehouse, red team D1):
  - The SIES specialty files publish, per GROUP of formations (e.g. "Licence Sciences juridiques"), NATIONAL, bac général
    only, and per doublette: the candidates (people with at least one vœu in the group; the SIES column is named "voeux"),
    those with at least one proposal and those who accepted. Never per establishment, never per formation.
    Proposal rate of a doublette in a group = candidates with a proposal / candidates, pooled over the campaigns (sums, then
    the ratio).
  - There is no doublette for bac techno or pro. Each formation publishes, per series, its candidates and proposals:
    the per-route ("voie") proposal rate of THIS formation, the sprint-B4 indicator (journey.series_rate_sql).

"Autres doublettes" (owner's rule, 2026-11-08): in a group, a doublette with fewer than 20 candidates over the campaigns
is "rare". The rare doublettes of a group are pooled into one "Autres doublettes" bucket (exact sum of their counts),
shown as an ESTIMATION in place of the student's doublette when that doublette is rare there. A doublette with enough
candidates is never replaced by the bucket.

Never a chance: "parmi les candidats ayant cette doublette, X % ont reçu au moins une proposition dans ce groupe".
"""
from __future__ import annotations

from . import journey as J

THRESHOLD = 20                     # candidates over the campaigns, same rule as the series (journey.MIN_SERIES_CANDIDATES)
# Counting break (found on real data, 2026-11-08): in a few groups the 2023 and 2024 rows count about 2-3x more
# "candidates" while the proposals barely move (Licence L.AS: 96 307 -> 272 454 -> 262 625 -> 103 979 candidates for
# 53 522 -> 55 246 -> 56 058 -> 53 442 proposals): those rows count something else (vœux, most likely). Fixed rule: in
# a group whose proposals are at least BREAK_MIN_PROP every campaign, a campaign with more than BREAK_CAND x the group's
# smallest candidate count while its proposals stay under BREAK_PROP x the smallest is left out of every rate of that
# group (pooled, trend, rare flag, "Autres doublettes"), and the page says so. Small groups are not judged (noise).
BREAK_CAND, BREAK_PROP, BREAK_MIN_PROP = 2.0, 1.5, 2000
VOIES = ("bg", "bt", "bp")


def _has(con, schema: str, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
                            [schema, table]).fetchone()[0])


def label(dkey: str | None) -> str:
    if not dkey:
        return ""
    return " + ".join(J.SPECIALTY_SHORT.get(s, s) for s in dkey.split("+"))


def rate(prop, cand) -> float | None:
    return None if not cand else round(100.0 * (prop or 0) / cand, 1)


# ------------------------------------------------------------------------- build
def build(con) -> int:
    """mart.spe_group: per group of formations (not the national row), doublette and campaign; rare flag per (group, doublette)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS mart")
    if not _has(con, "mart", "spe_filiere"):
        con.execute("""CREATE OR REPLACE TABLE mart.spe_group (type_key VARCHAR, type_label VARCHAR, doublette_key VARCHAR,
            session BIGINT, candidats BIGINT, propositions BIGINT, acceptations BIGINT, rare BOOLEAN)""")
        con.execute("CREATE OR REPLACE TABLE mart.spe_break (type_key VARCHAR, session BIGINT, candidats BIGINT, propositions BIGINT)")
        return 0
    con.execute(f"""
    CREATE OR REPLACE TABLE mart.spe_break AS
    WITH t AS (SELECT type_key, session, sum(candidats) c, sum(propositions) p FROM mart.spe_filiere
               WHERE type_key <> '{J.NATIONAL_TYPE}' AND doublette_key IS NOT NULL GROUP BY 1, 2),
    m AS (SELECT type_key, min(c) mc, min(p) mp FROM t GROUP BY 1)
    SELECT t.type_key, t.session, t.c AS candidats, t.p AS propositions FROM t JOIN m USING (type_key)
    WHERE m.mp >= {BREAK_MIN_PROP} AND t.c > {BREAK_CAND} * m.mc AND t.p < {BREAK_PROP} * m.mp
    ORDER BY 1, 2""")
    con.execute(f"""
    CREATE OR REPLACE TABLE mart.spe_group AS
    WITH g AS (
      SELECT f.type_key, any_value(f.type_label ORDER BY f.session DESC) OVER (PARTITION BY f.type_key) AS type_label,
             f.doublette_key, f.session, f.candidats, f.propositions, f.acceptations
      FROM mart.spe_filiere f ANTI JOIN mart.spe_break b USING (type_key, session)
      WHERE f.type_key <> '{J.NATIONAL_TYPE}' AND f.doublette_key IS NOT NULL)
    SELECT g.*, sum(candidats) OVER (PARTITION BY type_key, doublette_key) < {THRESHOLD} AS rare
    FROM g ORDER BY type_key, doublette_key, session""")
    return con.execute("SELECT count(*) FROM mart.spe_group").fetchone()[0]


# ------------------------------------------------------------------------- serving
def _pack(rows: list[tuple]) -> dict:
    """rows = (session, candidats, propositions, acceptations): pooled figures + per-campaign trend."""
    by = {}
    for s, c, p, a in rows:
        x = by.setdefault(s, [0, 0, 0])
        x[0] += c or 0
        x[1] += p or 0
        x[2] += a or 0
    cand = sum(v[0] for v in by.values())
    prop = sum(v[1] for v in by.values())
    acc = sum(v[2] for v in by.values())
    return {"candidats": cand, "propositions": prop, "acceptations": acc, "taux": rate(prop, cand), "campagnes": len(by),
            "trend": [{"session": s, "candidats": v[0], "taux": rate(v[1], v[0])} for s, v in sorted(by.items())]}


def for_group(con, type_key: str | None) -> dict | None:
    """Every doublette of one group (pooled + trend), the rare ones flagged, the 'Autres doublettes' bucket and all candidates."""
    if not type_key or not _has(con, "mart", "spe_group"):
        return None
    rows = con.execute("""SELECT doublette_key, session, candidats, propositions, acceptations, rare, type_label
                          FROM mart.spe_group WHERE type_key = ? ORDER BY doublette_key, session""", [type_key]).fetchall()
    if not rows:
        return None
    per, rare = {}, {}
    for d, s, c, p, a, r, _lab in rows:
        per.setdefault(d, []).append((s, c, p, a))
        rare[d] = bool(r)
    doubl = []
    for d, rs in per.items():
        x = _pack(rs)
        doubl.append({"key": d, "label": label(d), "rare": rare[d], **x})
    doubl.sort(key=lambda x: (-x["candidats"], x["key"]))
    autres = _pack([r for d, rs in per.items() if rare[d] for r in rs])
    autres["n_doublettes"] = sum(1 for d in per if rare[d])
    breaks = [s for (s,) in con.execute("SELECT session FROM mart.spe_break WHERE type_key = ? ORDER BY 1", [type_key]).fetchall()] \
        if _has(con, "mart", "spe_break") else []
    return {"type_key": type_key, "label": rows[0][6], "seuil": THRESHOLD, "campagnes_ecartees": breaks,
            "tous": _pack([r for rs in per.values() for r in rs]), "autres": autres, "doublettes": doubl}


def pick(group: dict | None, dkey: str | None) -> dict | None:
    """The figure to show for a student's doublette in a group: its own, or the 'Autres doublettes' estimation when rare.
    Python twin of the page's pickDoublette (red team D3/D6)."""
    if not group or not dkey:
        return None
    mine = next((d for d in group["doublettes"] if d["key"] == dkey), None)
    if mine and not mine["rare"]:
        return {"source": "doublette", "key": dkey, "label": mine["label"], "taux": mine["taux"], "candidats": mine["candidats"],
                "trend": mine["trend"]}
    a = group["autres"]
    if not a["candidats"]:
        return None
    return {"source": "autres", "key": dkey, "label": label(dkey), "taux": a["taux"], "candidats": a["candidats"],
            "n_doublettes": a["n_doublettes"], "trend": a["trend"], "estimation": True}


def type_of(con, cod: str, session: int | None = None) -> str | None:
    if not (_has(con, "core", "taxonomy_link") and _has(con, "core", "taxonomy_rule")):
        return None
    r = con.execute("""SELECT r.spe_type_key FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
                       WHERE t.cod_aff_form = ? AND (? IS NULL OR t.session = ?) ORDER BY t.session DESC LIMIT 1""",
                    [cod, session, session]).fetchone()
    return r[0] if r else None


def series(con, cod: str) -> dict:
    """Per-route proposal rate of THIS formation, each campaign of its lineage (the sprint-B4 indicator)."""
    lin = con.execute("""SELECT lineage_id FROM core.lineage WHERE cod_aff_form = ? ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
    where = "l.lineage_id = ?" if lin else "fy.cod_aff_form = ?"
    arg = lin[0] if lin else cod
    cols = ", ".join(f"{J.series_candidates_sql(s)} AS c_{s}, fy.prop_tot_{s} AS p_{s}" for s in VOIES)
    rows = con.execute(f"""SELECT fy.session, {cols} FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)
                           WHERE {where} ORDER BY fy.session""", [arg]).fetchall()
    out = {}
    for i, s in enumerate(VOIES):
        trend = [{"session": r[0], "candidats": r[1 + 2 * i], "taux": rate(r[2 + 2 * i], r[1 + 2 * i])} for r in rows]
        last = trend[-1] if trend else {"candidats": None, "taux": None}
        out[s] = {"label": J.SERIES_LABEL[s], "candidats": last["candidats"], "taux": last["taux"],
                  "fragile": (last["candidats"] or 0) < THRESHOLD, "trend": trend}
    return out


def for_formation(con, cod: str, session: int | None = None) -> dict:
    """The block of the formation page: per route for this formation, per doublette for its group (national)."""
    t = type_of(con, cod, session)
    g = for_group(con, t)
    return {"series": series(con, cod), "groupe": g, "status": "ok" if g else "sans_groupe"}


def autres_by_type(con) -> dict:
    """{type_key: pooled 'Autres doublettes' bucket} for every group (stage 1 of Mon parcours)."""
    if not _has(con, "mart", "spe_group"):
        return {}
    out = {}
    for t, s, c, p, a in con.execute("""SELECT type_key, session, sum(candidats), sum(propositions), sum(acceptations)
                                        FROM mart.spe_group WHERE rare GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
        out.setdefault(t, []).append((s, c, p, a))
    res = {}
    for t, rs in out.items():
        res[t] = _pack(rs)
        res[t]["n_doublettes"] = con.execute("SELECT count(DISTINCT doublette_key) FROM mart.spe_group WHERE type_key = ? AND rare",
                                             [t]).fetchone()[0]
    return res
