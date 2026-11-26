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
  * `voeu_multiple` (audit PR 7): the vœu multiple the formation's fiche names, shared with at least one other formation
    (multiples.py); `n_voeux` counts each such group once.
Never « votre liste est valide »: SupCompass does not see the Parcoursup file; every vœu is confirmed on Parcoursup.
The answer carries the student's list: no shared cache, no audience event (like /api/voeux).
"""
from __future__ import annotations

import re

from . import jpo as JPO
from . import multiples as MU

MAX_IDS = 10
COMMUN = re.compile(r"\bconcours communs?\b")


def concours(labels: str) -> str | None:
    """The common entrance exam the labels name (its official name), « Concours commun » when only those words are printed."""
    c = JPO.concours_of(labels or "")
    if c:
        return c[1]
    return "Concours commun" if COMMUN.search(JPO.fold(labels or "")) else None


def carte_session(con) -> int | None:
    """The LATEST cartographie session (the formations Parcoursup offers now), None without the table."""
    has_carto = bool(con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'
                                    AND table_name = 'cartographie'""").fetchone()[0])
    return con.execute("SELECT max(carto_session) FROM core.cartographie").fetchone()[0] if has_carto else None


def dans_carte(con, cod: str, session: int | None) -> bool | None:
    """Is the code in that cartographie session? None when no session is known (never « absente » by default)."""
    if session is None:
        return None
    return bool(con.execute("SELECT count(*) FROM core.cartographie WHERE cod_aff_form = ? AND carto_session = ?",
                            [cod, session]).fetchone()[0])


def presence(con, cod: str) -> dict:
    """lot 1, PR 12: the formation page says what « Avant de confirmer » says (one rule): absent from the latest map =
    « vérifiez sur Parcoursup qu'elle existe toujours », never « fermée »."""
    s = carte_session(con)
    return {"session": s, "dans": dans_carte(con, cod, s)}


def absentes(con) -> dict:
    """lot 1, PR 12: the latest SIES campaign's formations absent from the latest cartographie session (the search card
    says it, as « Avant de confirmer » does); sorted codes, no parameter. No map = no code (never « absente » by default)."""
    s = carte_session(con)
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    if s is None:
        return {"carte_session": None, "session": latest, "codes": []}
    codes = [r[0] for r in con.execute("""SELECT DISTINCT f.cod_aff_form FROM core.formation_year f WHERE f.session = ?
        AND NOT EXISTS (SELECT 1 FROM core.cartographie k WHERE k.cod_aff_form = f.cod_aff_form AND k.carto_session = ?)
        ORDER BY 1""", [latest, s]).fetchall()]
    return {"carte_session": s, "session": latest, "codes": codes}


def verifier(con, ids: list[str]) -> dict:
    """{"session", "carte_session", "voeux": [{cod_aff_form, connu, dans_carte, concours, apprentissage}]} in the list's order."""
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    carte = carte_session(con)
    out = []
    groupes = MU.of_codes(con, ids)
    for cod in ids:
        r = con.execute("""SELECT session, concat_ws(' ', lib_for_voe_ins, lib_comp_voe_ins, detail_forma), apprentissage
                           FROM core.formation_year WHERE cod_aff_form = ? ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
        dans = dans_carte(con, cod, carte)
        out.append({"cod_aff_form": cod, "connu": r is not None, "session": r[0] if r else None, "dans_carte": dans,
                    "concours": concours(r[1]) if r else None, "apprentissage": bool(r[2]) if r else False,
                    "voeu_multiple": groupes.get(cod)})
    # audit PR 7: the sub-wishes of one vœu multiple the fiches name count once (multiples.py)
    return {"session": latest, "carte_session": carte, "voeux": out, "n_voeux": MU.compte(out)}
