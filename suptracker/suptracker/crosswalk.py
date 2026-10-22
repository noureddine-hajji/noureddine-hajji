"""Longitudinal entity resolution of formations across campaigns.

Pass 1  exact_id_match            same (cod_uai, cod_aff_form) in consecutive campaigns
Pass 2  inferred_uai_track_match  cod_aff_form changed: candidates restricted to the same
                                  cod_uai AND macro-filière (fili); scored by token-set
                                  similarity of normalised form_lib_voe_acc / fil_lib_voe_acc
                                  (+ lib_comp_voe_ins). Accepted only if score >= LINK_MIN_SCORE,
                                  the pair is mutually best, and the margin over the runner-up
                                  is >= LINK_MIN_MARGIN. Everything else is logged as ambiguous,
                                  never linked: a missed link shortens a series, a wrong link
                                  conflates two programmes.
Pass 3  exact_id_match (gap)      same (cod_uai, cod_aff_form) separated by one missing campaign.

Links are strictly 1:1 per campaign pair, so lineages are simple chains.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import duckdb
import pandas as pd

from . import config

EXACT = "exact_id_match"
INFERRED = "inferred_uai_track_match"

STOP = {"de", "la", "le", "les", "des", "du", "d", "l", "en", "et", "a", "au", "aux", "pour", "par", "sur"}
SYNONYMS = [
    (r"\bbachelor universitaire de technologie\b", "but"),
    (r"\bdiplome universitaire de technologie\b", "dut"),
    (r"\bbrevet de technicien superieur\b", "bts"),
    (r"\bclasse preparatoire aux grandes ecoles\b", "cpge"),
    (r"\blicence\b", "licence"),
    (r"\bparcours\b", ""),
    (r"\bmention\b", ""),
]


def normalize_label(*parts: str | None) -> frozenset[str]:
    s = " ".join(p for p in parts if isinstance(p, str) and p)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    for pat, rep in SYNONYMS:
        s = re.sub(pat, rep, s)
    return frozenset(t for t in s.split() if t not in STOP and len(t) > 1)


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _secondary(prev: pd.DataFrame, cur: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    links, audit = [], []
    pg = prev.groupby(["cod_uai", "fili"], dropna=False)
    for key, cgrp in cur.groupby(["cod_uai", "fili"], dropna=False):
        if key not in pg.groups or pd.isna(key[0]):
            continue
        pgrp = pg.get_group(key)
        scores = []
        for _, c in cgrp.iterrows():
            for _, p in pgrp.iterrows():
                scores.append((similarity(c.tokens, p.tokens), c.cod_aff_form, p.cod_aff_form))
        best_c: dict[str, list] = defaultdict(list)
        best_p: dict[str, list] = defaultdict(list)
        for s, c, p in scores:
            best_c[c].append((s, p))
            best_p[p].append((s, c))
        for c, lst in best_c.items():
            lst.sort(reverse=True)
            s, p = lst[0]
            runner = lst[1][0] if len(lst) > 1 else 0.0
            p_lst = sorted(best_p[p], reverse=True)
            p_runner = p_lst[1][0] if len(p_lst) > 1 else 0.0
            mutual = p_lst[0][1] == c
            ok = s >= config.LINK_MIN_SCORE and mutual and s - max(runner, p_runner) >= config.LINK_MIN_MARGIN
            rec = {"cod_aff_form_to": c, "cod_aff_form_from": p, "score": round(s, 4),
                   "runner_up": round(max(runner, p_runner), 4), "mutual_best": mutual}
            if ok:
                links.append(rec)
            elif s > 0:
                audit.append({**rec, "reason": "below_threshold" if s < config.LINK_MIN_SCORE
                              else ("not_mutual" if not mutual else "ambiguous_margin")})
    return links, audit


def build_crosswalk(con: duckdb.DuckDBPyConnection) -> None:
    df = con.execute("""SELECT session, cod_uai, cod_aff_form, fili, form_lib_voe_acc,
                               fil_lib_voe_acc, lib_comp_voe_ins FROM core.formation_year""").df()
    df["tokens"] = [normalize_label(a, b, c) for a, b, c in
                    zip(df.form_lib_voe_acc, df.fil_lib_voe_acc, df.lib_comp_voe_ins)]
    years = sorted(df.session.unique())
    by_year = {y: df[df.session == y] for y in years}
    links: list[dict] = []
    audit: list[dict] = []
    linked_fwd: dict[int, set] = defaultdict(set)   # (year) -> cod_aff_form already linked to later year
    linked_bwd: dict[int, set] = defaultdict(set)   # (year) -> cod_aff_form already linked to earlier year

    def add(y0, a0, y1, a1, kind, score):
        links.append({"session_from": y0, "cod_aff_form_from": a0, "session_to": y1,
                      "cod_aff_form_to": a1, "link_type": kind, "score": score})
        linked_fwd[y0].add(a0)
        linked_bwd[y1].add(a1)

    for y0, y1 in zip(years, years[1:]):
        prev, cur = by_year[y0], by_year[y1]
        m = cur.merge(prev, on=["cod_uai", "cod_aff_form"], suffixes=("", "_p"))
        for a in m.cod_aff_form:
            add(y0, a, y1, a, EXACT, 1.0)
        rest_p = prev[~prev.cod_aff_form.isin(linked_fwd[y0])]
        rest_c = cur[~cur.cod_aff_form.isin(linked_bwd[y1])]
        sec, aud = _secondary(rest_p, rest_c)
        for r in sec:
            add(y0, r["cod_aff_form_from"], y1, r["cod_aff_form_to"], INFERRED, r["score"])
        for r in aud:
            audit.append({"session_from": y0, "session_to": y1, **r})

    for y0, y2 in zip(years, years[2:]):
        prev = by_year[y0][~by_year[y0].cod_aff_form.isin(linked_fwd[y0])]
        cur = by_year[y2][~by_year[y2].cod_aff_form.isin(linked_bwd[y2])]
        for a in cur.merge(prev, on=["cod_uai", "cod_aff_form"]).cod_aff_form:
            add(y0, a, y2, a, EXACT, 1.0)

    links_df = pd.DataFrame(links, columns=["session_from", "cod_aff_form_from", "session_to",
                                            "cod_aff_form_to", "link_type", "score"])
    audit_df = pd.DataFrame(audit, columns=["session_from", "session_to", "cod_aff_form_to",
                                            "cod_aff_form_from", "score", "runner_up", "mutual_best", "reason"])

    # Chains: walk back from each node that has no forward link (the chain head).
    nxt = {(r.session_from, r.cod_aff_form_from): (r.session_to, r.cod_aff_form_to, r.link_type)
           for r in links_df.itertuples()}
    prv = {(t[0], t[1]): (k, t[2]) for k, t in nxt.items()}
    rows = []
    for node in zip(df.session, df.cod_aff_form):
        if node in nxt:
            continue
        head = node
        lineage_id = f"{head[1]}@{head[0]}"
        chain, kinds = [head], []
        while chain[-1] in prv:
            p, kind = prv[chain[-1]]
            chain.append(p)
            kinds.append(kind)
        conf = INFERRED if INFERRED in kinds else EXACT
        for i, (s, a) in enumerate(chain):
            rows.append({"session": s, "cod_aff_form": a, "lineage_id": lineage_id,
                         "lineage_head_session": head[0], "lineage_head_cod_aff_form": head[1],
                         "lineage_confidence": conf, "lineage_years": len(chain),
                         "link_to_next": None if i == 0 else kinds[i - 1]})
    lin = pd.DataFrame(rows)
    con.register("_links", links_df)
    con.register("_audit", audit_df)
    con.register("_lin", lin)
    con.execute("CREATE OR REPLACE TABLE core.crosswalk_link AS SELECT * FROM _links")
    con.execute("CREATE OR REPLACE TABLE core.crosswalk_audit AS SELECT * FROM _audit")
    con.execute("CREATE OR REPLACE TABLE core.lineage AS SELECT * FROM _lin")
    for t in ("_links", "_audit", "_lin"):
        con.unregister(t)
    n_nodes = con.execute("SELECT count(*) FROM core.formation_year").fetchone()[0]
    n_lin = con.execute("SELECT count(*) FROM core.lineage").fetchone()[0]
    if n_nodes != n_lin:  # every formation-year must belong to exactly one lineage
        raise RuntimeError(f"lineage covers {n_lin} rows but formation_year has {n_nodes}")


def continuity_report(con: duckdb.DuckDBPyConnection, anchor: int = config.LATEST_YEAR) -> pd.DataFrame:
    """Share of `anchor`-year formations whose lineage reaches each earlier campaign."""
    years = [y for y in config.YEARS if y < anchor]
    cols = ",\n".join(
        f"bool_or(l2.session = {y}) AS in_{y}" for y in years)
    return con.execute(f"""
    WITH a AS (SELECT l.lineage_id, l.lineage_confidence, fy.fili
               FROM core.lineage l JOIN core.formation_year fy USING (session, cod_aff_form)
               WHERE l.session = {anchor}),
    p AS (SELECT a.lineage_id, any_value(a.lineage_confidence) AS conf, any_value(a.fili) AS fili, {cols}
          FROM a JOIN core.lineage l2 USING (lineage_id) GROUP BY a.lineage_id)
    SELECT CASE WHEN grouping(fili) = 1 THEN 'TOTAL' ELSE coalesce(fili, '(non renseignée)') END AS fili, count(*) AS n_{anchor},
      {", ".join(f"round(100.0 * avg(in_{y}::INT), 1) AS pct_linked_{y}" for y in years)},
      round(100.0 * avg(({" AND ".join(f"in_{y}" for y in years) or "TRUE"})::INT), 1) AS pct_full_span,
      round(100.0 * avg((conf = '{EXACT}' AND {" AND ".join(f"in_{y}" for y in years) or "TRUE"})::INT), 1)
        AS pct_full_span_exact,
      round(100.0 * avg((conf = '{INFERRED}')::INT), 1) AS pct_with_inferred_link
    FROM p GROUP BY ROLLUP (fili) ORDER BY grouping(fili) DESC, n_{anchor} DESC
    """).df()
