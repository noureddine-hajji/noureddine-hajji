"""« Préparer mon projet de formation motivé » (sprint 1 of the 2026-2027 plan, owner 2026-11-20).

For each vœu of the student's list, the page shows what the formation itself publishes on its LIVE Parcoursup fiche
(grilles.py): its expectations (« attendus » nationaux and complémentaires), what its jury examines (each criterion with its
field, the field's weight and the importance the fiche prints), and its advice to candidates. Nothing else:

  * Published texts only, verbatim and escaped by the page; the criteria are only REORDERED, from the most important to the
    least (importance as printed, then the fiche's own order): never merged, scored, summed or rewritten.
  * The site never writes the project for the student: no model text, no generated sentence. The page offers a checklist of the
    criteria and a draft that stay in the browser (localStorage), never sent to the server.
  * The character counter shows Parcoursup's usual limit (LIMITE: 1,500 characters, spaces included, « pour la majorité des
    formations » per Parcoursup's and Onisep's own guidance), and says that the limit shown on Parcoursup for each vœu prevails.
  * A formation whose fiche could not be read says so and links its Parcoursup fiche (an https parcoursup.fr address only).

The answer is the same for everyone (one formation code, no profile): shared-cached like /api/formation.
"""
from __future__ import annotations

from . import grilles as GR

LIMITE = 1500                      # characters, spaces included: the usual limit of the field on Parcoursup (each vœu's own prevails)


def lignes(texte: str | None) -> list[str]:
    """A published text split on its own line breaks, empty lines dropped (display only: words untouched)."""
    return [x.strip() for x in (texte or "").splitlines() if x.strip()]


def criteres(champs: list[dict]) -> list[dict]:
    """Every criterion of the detailed grid with its field, from the most important to the least (importance as printed,
    then the fiche's own order of fields and criteria)."""
    flat = []
    for x in sorted(champs, key=lambda c: c["rang"]):
        for i, k in enumerate(x["criteres"]):
            flat.append({"champ": x["champ"], "poids": x["poids"], "critere": k["critere"], "elements": k["elements"],
                         "importance": k["importance"], "importance_label": k["importance_label"], "_o": (x["rang"], i)})
    flat.sort(key=lambda k: (-k["importance"], k["_o"]))
    for k in flat:
        del k["_o"]
    return flat


def _fiche_url(url: str | None) -> str | None:
    return url if url and url.startswith("https://") and "parcoursup.fr/" in url.split("?")[0] else None


def for_formation(con, cod: str) -> dict | None:
    """What the page needs for one vœu, or None when the formation is unknown."""
    r = con.execute("""SELECT g_ea_lib_vx, lib_for_voe_ins, ville_etab FROM core.formation_year WHERE cod_aff_form = ?
                       ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
    if not r:
        return None
    url = None
    if _has_table(con, "cartographie"):
        u = con.execute("SELECT fiche_url FROM core.cartographie WHERE cod_aff_form = ? ORDER BY carto_session DESC LIMIT 1",
                        [cod]).fetchone()
        url = _fiche_url(u[0]) if u else None
    g = GR.for_formation(con, cod)
    fiche = None
    if g:
        url = _fiche_url(g.get("url")) or url
        fiche = {"session": g["session"], "lu_le": g["lu_le"], "grille": g["grille"],
                 "attendus": lignes(g.get("nationaux")), "complementaires": lignes(g.get("complementaires")),
                 "conseils": lignes(g.get("conseils")), "info": lignes(g.get("info")),
                 "criteres": criteres(g.get("champs") or [])}
    return {"cod": cod, "etablissement": r[0], "formation": r[1], "ville": r[2], "limite": LIMITE, "fiche": fiche, "fiche_url": url}


def _has_table(con, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = ?",
                            [table]).fetchone()[0])
