"""PR 19 (owner, 2026-11-28): « Après le 1er juin », what Parcoursup's answers mean and what to do with them.

Everything a student reads about the answers is READ from official pages, never written by this site:
  * the official calendar PDF (calendrier.py, every version identical): the admission dates, « vous devez répondre dans les
    délais à chaque proposition d'admission reçue », « classez vos vœux en attente », the number of new vœux of the
    complementary phase;
  * service-public.gouv.fr F2861 « Première inscription » (data/aides, fetched by the `suptracker-aides` workflow): what each
    answer of a formation means, read by ONE fixed rule in aides.py (`r_reponses`); a rule that stops matching drops the block
    and says so (« lisez la page officielle »), never a typed fallback.
What this site adds is labelled as its own:
  * per vœu of the student's list, its name and a link to its own page (how far its list was called, « Comprendre l'appel »):
    no depth beside the list, never a rank asked (plan, 2026-11-26: a waiting-list position next to last year's last-called
    rank would make a probability);
  * the complementary phase: the OFFICIAL live list first (Parcoursup, from the date the calendar prints), then the formations
    that ADMITTED in the complementary phase in the latest campaign (published `acc_pc`, the search page's filter), with how
    often that repeats MEASURED on the two latest campaigns (`persistance`): counts and a share, never a promise of places.
"""
from __future__ import annotations

from . import aides as AID
from . import appel as APL
from . import calendrier as CAL

PARCOURSUP = "https://www.parcoursup.gouv.fr/"
STEP = 3                                             # « Je reçois les réponses des formations et je décide »
REGLES = ("repondre_delais", "oui_ouisi", "classez", "complementaire_max")
MAX_IDS = 10


def persistance(con) -> dict | None:
    """Among the formations present in the two latest campaigns: those that admitted in the complementary phase in the first
    (`acc_pc` > 0) and how many did again in the second; the same for those that admitted nobody then. Published admits only;
    an unknown `acc_pc` counts in neither group."""
    years = [r[0] for r in con.execute("SELECT DISTINCT session FROM core.formation_year ORDER BY session").fetchall()]
    if len(years) < 2:
        return None
    a, b = years[-2], years[-1]
    r = con.execute("""
        SELECT count(*) FILTER (WHERE x.acc_pc > 0),
               count(*) FILTER (WHERE x.acc_pc > 0 AND y.acc_pc > 0),
               count(*) FILTER (WHERE x.acc_pc = 0),
               count(*) FILTER (WHERE x.acc_pc = 0 AND y.acc_pc > 0)
        FROM core.formation_year x
        JOIN core.formation_year y ON y.cod_aff_form = x.cod_aff_form AND y.session = ?
        WHERE x.session = ? AND y.acc_pc IS NOT NULL""", [b, a]).fetchone()
    n_b, pc_b = con.execute("SELECT count(*), count(*) FILTER (WHERE acc_pc > 0) FROM core.formation_year WHERE session = ?",
                            [b]).fetchone()
    if not r[0] or not r[2]:
        return None
    return {"avant": a, "apres": b,
            "avec": {"n": r[0], "encore": r[1], "part": round(100 * r[1] / r[0], 1)},
            "sans": {"n": r[2], "puis": r[3], "part": round(100 * r[3] / r[2], 1)},
            "derniere": {"session": b, "formations": n_b, "avec_pc": pc_b}}


def page(con) -> dict:
    """The page's one answer (no parameter): the step-3 dates of the official calendar, its rules, the official meaning of the
    answers (or None), the measured persistence and the official links."""
    cal = CAL.calendar()
    rg = CAL.regles(rules=CAL.REGLES_ADMISSION)
    nat = AID.national(con) or {}
    return {"campagne": cal["campagne"], "lu_le": cal.get("lu_le"), "etape": cal["etapes"].get(STEP) or cal["etapes"].get(str(STEP)),
            "evenements": [e for e in cal["evenements"] if e["etape"] == STEP],
            "regles": {k: rg.get(k) for k in REGLES},
            "reponses": nat.get("reponses"),
            "persistance": persistance(con),
            "liens": {"parcoursup": PARCOURSUP}}


def voeux(con, ids: list[str]) -> dict:
    """Each vœu of the list (codes only): its name in its latest campaign and whether its own page shows how far its list was
    called (appel.for_formation). Nothing else: no depth, no rate, no rank beside the list."""
    out = []
    for cod in ids[:MAX_IDS]:
        r = con.execute("""SELECT session, g_ea_lib_vx, lib_for_voe_ins, ville_etab FROM core.formation_year
                           WHERE cod_aff_form = ? ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
        if not r:
            out.append({"cod_aff_form": cod, "connu": False})
            continue
        out.append({"cod_aff_form": cod, "connu": True, "session": r[0], "etablissement": r[1], "formation": r[2], "ville": r[3],
                    "appel": any(x.get("groupes") for x in APL.for_formation(con, cod))})
    return {"voeux": out}
