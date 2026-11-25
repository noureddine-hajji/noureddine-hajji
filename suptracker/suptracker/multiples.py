"""Vœux multiples (audit PR 7, owner 2026-11-25): which formations of the list Parcoursup counts as ONE vœu.

No open data says it: SIES and the cartographie publish one row per formation, and their counts never name a group (an IFSI
row carries its own candidates). The LIVE fiche does: its heading (`h2#libelle-etab-ff`) prints the establishment and its town
on an ordinary fiche, and the NAME OF ITS VŒU MULTIPLE in place of the establishment for a sub-wish of a group Parcoursup fixes
(« Regroupement IFSI Université de Lille », « Réseau ScPo – concours commun », « Concours Geipi Polytech », multi-site schools of
social work). The fiche reader (version 5) keeps that name and the formation line verbatim (data/fiches/identite.csv).

A group = the same name AND the same formation line in the same fiche campaign (Geipi's bac général and bac techno concours
are two vœux), shared by AT LEAST TWO formations: a name printed on one fiche alone is not counted as a group. Formations a
student chooses freely to put together (the same BTS in several lycées) are not fixed by Parcoursup: no fiche names them, so
SupCompass counts them one by one and says the fiche prevails. The number of sub-wishes Parcoursup allows is not read here
(the official calendar does not print it): the page sends the student to parcoursup.gouv.fr. Never a « liste valide ».
"""
from __future__ import annotations

MIN_FORMATIONS = 2


def build(con) -> int:
    """core.voeu_multiple (cod_aff_form, session, nom, formation, n_formations) from core.fiche_identite."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.voeu_multiple (cod_aff_form VARCHAR, session INTEGER, nom VARCHAR,
        formation VARCHAR, n_formations INTEGER)""")
    cols = {c for (c,) in con.execute("""SELECT column_name FROM information_schema.columns WHERE table_schema = 'core'
        AND table_name = 'fiche_identite'""").fetchall()}
    if "voeu_multiple" not in cols:
        return 0
    con.execute(f"""INSERT INTO core.voeu_multiple
        WITH g AS (SELECT cod_aff_form, session, voeu_multiple AS nom, voeu_multiple_formation AS formation
                   FROM core.fiche_identite WHERE voeu_multiple IS NOT NULL AND voeu_multiple_formation IS NOT NULL
                     AND session IS NOT NULL)
        SELECT cod_aff_form, session, nom, formation, count(*) OVER (PARTITION BY session, nom, formation) AS n
        FROM g QUALIFY n >= {MIN_FORMATIONS} ORDER BY cod_aff_form""")
    return con.execute("SELECT count(*) FROM core.voeu_multiple").fetchone()[0]


def _has(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'
        AND table_name = 'voeu_multiple'""").fetchone()[0])


def of_codes(con, cods: list[str]) -> dict:
    """{code: {"nom", "formation", "session", "n_formations"}} for the given formations that are sub-wishes of a group."""
    if not cods or not _has(con):
        return {}
    rows = con.execute("""SELECT cod_aff_form, nom, formation, session, n_formations FROM core.voeu_multiple
        WHERE list_contains(?, cod_aff_form)""", [list(cods)]).fetchall()
    return {c: {"nom": n, "formation": f, "session": s, "n_formations": k} for c, n, f, s, k in rows}


def for_formation(con, cod: str) -> dict | None:
    return of_codes(con, [cod]).get(cod)


def compte(voeux: list[dict]) -> int:
    """The number of Parcoursup vœux a list makes: each group once, every other formation once (twin `vxCompte`)."""
    seen, n = set(), 0
    for v in voeux:
        g = v.get("voeu_multiple")
        key = (g["session"], g["nom"], g["formation"]) if g else None
        if key is None or key not in seen:
            n += 1
        if key is not None:
            seen.add(key)
    return n
