"""« Vérifier et confirmer ma liste » (sprint 5, owner 2026-11-21): what SupCompass can check on the student's list before the
Parcoursup deadlines, and nothing it cannot.

The rules come from the OFFICIAL calendar (calendrier.regles: « jusqu'à 10 vœux », « 10 vœux supplémentaires pour des formations
en apprentissage », sous-vœux for some formations, apprenticeship vœux still possible after the confirmation day) and its dates
(the last day to formulate, the last day to confirm). Per vœu, three facts the open data hold:
  * `dans_carte`: the code is in the LATEST cartographie session (the formations Parcoursup offers now); absent = « vérifiez
    qu'elle existe toujours », never « fermée »;
  * `concours`: the common entrance exam its Parcoursup labels NAME (jpo.concours_of: Puissance Alpha, Avenir, Geipi Polytech,
    SESAME, Advance, ACCÈS), else « Concours commun » when the words are printed: it may be a sub-wish of a multiple wish on
    Parcoursup. « Préparation aux concours » is not an exam (harmonize's broad `subwish_label_flag` is not used), and the
    count-based pools of `subwish_pool_flag` are a deduction: SupCompass cannot know how Parcoursup groups a vœu multiple;
  * `apprentissage`: the SIES row is an apprenticeship formation (counted apart: « 10 vœux supplémentaires »).
Never « votre liste est valide »: SupCompass does not see the Parcoursup file; every vœu is confirmed on Parcoursup.
The answer carries the student's list: no shared cache, no audience event (like /api/voeux).
"""
from __future__ import annotations

import re

from . import jpo as JPO

MAX_IDS = 10
COMMUN = re.compile(r"\bconcours communs?\b")


def concours(labels: str) -> str | None:
    """The common entrance exam the labels name (its official name), « Concours commun » when only those words are printed."""
    c = JPO.concours_of(labels or "")
    if c:
        return c[1]
    return "Concours commun" if COMMUN.search(JPO.fold(labels or "")) else None


def verifier(con, ids: list[str]) -> dict:
    """{"session", "carte_session", "voeux": [{cod_aff_form, connu, dans_carte, concours, apprentissage}]} in the list's order."""
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    has_carto = bool(con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'
                                    AND table_name = 'cartographie'""").fetchone()[0])
    carte_session = con.execute("SELECT max(carto_session) FROM core.cartographie").fetchone()[0] if has_carto else None
    out = []
    for cod in ids:
        r = con.execute("""SELECT session, concat_ws(' ', lib_for_voe_ins, lib_comp_voe_ins, detail_forma), apprentissage
                           FROM core.formation_year WHERE cod_aff_form = ? ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
        dans = None
        if has_carto and carte_session is not None:
            dans = bool(con.execute("SELECT count(*) FROM core.cartographie WHERE cod_aff_form = ? AND carto_session = ?",
                                    [cod, carte_session]).fetchone()[0])
        out.append({"cod_aff_form": cod, "connu": r is not None, "session": r[0] if r else None, "dans_carte": dans,
                    "concours": concours(r[1]) if r else None, "apprentissage": bool(r[2]) if r else False})
    return {"session": latest, "carte_session": carte_session, "voeux": out}
