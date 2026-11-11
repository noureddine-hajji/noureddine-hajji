"""Sprint 21, "Je me réoriente ou je reprends mes études" (owner's choices, 2026-11-11).

SIES publishes no access rate for candidates who are not in terminale (reorientation, return to studies, other routes: one
group). It publishes, per formation and campaign, the candidates and the proposals of all candidates and of each bac series of
terminale. The difference is the group outside terminale:
    candidats hors terminale    = (nb_voe_pp + nb_voe_pc) - sum over bg, bt, bp of (nb_voe_pp_s + nb_voe_pc_s)
    propositions hors terminale = prop_tot - (prop_tot_bg + prop_tot_bt + prop_tot_bp)
On the real exports both are >= 0 on every row of 2023-2025 (15 rows of 2022 have more series proposals than all proposals).
In 2025: 22.8 % of these vœux got a proposal, against 33.7 % for the néo-bacheliers.

The "accès estimé hors terminale" is the series rule of "Mon parcours" applied to this group: the official taux d'accès scaled
by how the group's proposal rate compares with all candidates', capped at 100. Always an ESTIMATION, shown with the official rate;
none below MIN_CANDIDATS candidates or when the counts do not hold. No zone (SIES publishes no mention for this group), no Plan B.
The share of admits who are not néo-bacheliers comes from sprint 18's published counts (admis.py).
"""
from __future__ import annotations

from . import admis as ADM
from . import carte as CA

MIN_CANDIDATS = 20
# the block keys a list row carries (the formation page and Mes vœux get the whole block)
LIST_KEYS = ("candidats", "propositions", "acces_estime", "plafonne", "taux_acces_ens", "admis", "admis_autres",
             "part_admis_autres", "autres_majoritaires", "min_candidats")
FIELDS = ("nb_voe_pp", "nb_voe_pc", "prop_tot", "taux_acces_ens", "acc_tot", "acc_neobac", "acc_at",
          *(f"{k}_{s}" for s in ("bg", "bt", "bp") for k in ("nb_voe_pp", "nb_voe_pc", "prop_tot")))


def block(r: dict, session: int | None = None) -> dict:
    """The formation's figures for a candidate outside terminale, from its published counts."""
    z = lambda k: r.get(k) or 0  # noqa: E731
    cand_all = z("nb_voe_pp") + z("nb_voe_pc")
    cand = cand_all - sum(z(f"nb_voe_pp_{s}") + z(f"nb_voe_pc_{s}") for s in ("bg", "bt", "bp"))
    prop = z("prop_tot") - sum(z(f"prop_tot_{s}") for s in ("bg", "bt", "bp"))
    holds = cand >= 0 and 0 <= prop <= cand and r.get("nb_voe_pp") is not None and r.get("prop_tot") is not None
    rate = round(100 * prop / cand, 1) if holds and cand else None
    rate_all = round(100 * z("prop_tot") / cand_all, 1) if cand_all else None
    est, capped = None, False
    taux = r.get("taux_acces_ens")
    if holds and cand >= MIN_CANDIDATS and taux is not None and cand_all and z("prop_tot"):
        raw = taux * (prop / cand) / (z("prop_tot") / cand_all)
        est, capped = round(min(100.0, raw), 1), raw > 100
    tot, neo, at = r.get("acc_tot"), r.get("acc_neobac"), r.get("acc_at")
    part = round(100 * at / tot, 1) if tot and ADM.coherent(tot, neo, at) else None
    return {"session": session if session is not None else r.get("session"), "candidats": cand if holds else None,
            "propositions": prop if holds else None, "taux_proposition": rate, "taux_proposition_tous": rate_all,
            "acces_estime": est, "plafonne": capped, "taux_acces_ens": taux, "admis": tot, "admis_autres": at if part is not None else None,
            "part_admis_autres": part, "autres_majoritaires": ADM.autres_majoritaires(tot, neo, at), "min_candidats": MIN_CANDIDATS}


def _rows(con, where: str, params: list) -> dict:
    cols = ", ".join(FIELDS)
    out = {}
    for row in con.execute(f"SELECT cod_aff_form, session, {cols} FROM core.formation_year WHERE {where}", params).fetchall():
        out[row[0]] = block(dict(zip(FIELDS, row[2:])), row[1])
    return out


def for_formation(con, cod: str, session: int) -> dict | None:
    return _rows(con, "cod_aff_form = ? AND session = ?", [cod, session]).get(cod)


def for_codes(con, cods: list[str]) -> dict:
    """Latest campaign, the given formations (Mes vœux)."""
    if not cods:
        return {}
    return _rows(con, "session = (SELECT max(session) FROM core.formation_year) AND list_contains(?, cod_aff_form)", [list(cods)])


def listing(con, diplome: str, mention: str | None = None) -> dict | None:
    """Every formation of a type of diploma (and mention) of the latest campaign, with its figures. The page sorts it by the
    student's académie, then by name (never by figures); the académie never reaches the server."""
    lay = CA.formations(con, diplome, mention)
    if lay is None:
        return None
    forms = [f for f in lay["formations"] if f.get("stats") is not False]
    blocks = for_codes(con, [f["cod_aff_form"] for f in forms])
    keep = ("cod_aff_form", "etablissement", "formation", "ville", "academie", "payant")
    slim = lambda b: b and {k: b[k] for k in LIST_KEYS}  # noqa: E731 - only what the page reads (5 000 BTS rows)
    rows = [{**{k: f.get(k) for k in keep}, "reorientation": slim(blocks.get(f["cod_aff_form"]))} for f in forms]
    return {"diplome": diplome, "mention": mention, "session": lay["session"], "min_candidats": MIN_CANDIDATS, "formations": rows}
