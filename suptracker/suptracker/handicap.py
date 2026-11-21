"""Disability support and a student to talk to, as each LIVE Parcoursup fiche prints them (sprint 4, owner 2026-11-21).

The fiche's « Contacter et échanger avec l'établissement » tab (read by scripts/fiche_parse.contact, reader version 4) prints:
  * the callout « Sur l'accompagnement pour les situations de handicap »: its sentence (verbatim) and a « Référent handicap »
    line with a contact;
  * the establishment's « Informations supplémentaires »: some paragraphs point to its disability service (text and links);
  * « Echanger avec un étudiant ambassadeur de la formation »: a contact, or « néant ».

Rules:
  * The contact itself is NEVER stored or shown (an address or a phone number may name a person): the page says that the fiche
    gives one and links the fiche. Every text was masked at reading (e-mail addresses, phone numbers).
  * Published texts verbatim, escaped by the page; no rating of the support, never « accessible » or « adapté »: what the fiche
    says, and that the referent is the person to ask.
  * The student is never asked whether they have a disability: the card is the same for everyone (no profile, shared cache).
  * Links: http(s) only, as the fiche prints them, in a paragraph whose text or address speaks of disability.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import grilles as GR
from . import rapports as RP

FICHES = GR.FICHES
YN = {"oui": True, "non": False}


def _links(v) -> list[str]:
    out = []
    for u in v or []:
        if isinstance(u, str) and (u.startswith("https://") or u.startswith("http://")) and not any(ch in u for ch in ' "<>\'`'):
            out.append(u)
    return list(dict.fromkeys(out))


def assemble(src: Path) -> list[tuple]:
    """(code, session, lu_le, url, handicap text, referent, ambassadeur, infos JSON) for each fiche read by reader version 4."""
    etat = {r["cod_aff_form"]: r for r in GR._read(src / "etat.csv")}
    texts = GR.read_texts(src / "textes.csv.gz")
    rows = []
    for r in GR._read(src / "contact.csv"):
        c = r["cod_aff_form"]
        e = etat.get(c) or {}
        if e.get("status") not in ("ok", "sans_grille", "rejetee"):
            continue                                       # a fiche no longer read (gone, failed): nothing shown
        try:
            infos = [{"texte": texts[x["texte_id"]] if x.get("texte_id") else None, "liens": _links(x.get("liens"))}
                     for x in json.loads(r.get("handicap_infos") or "[]")]
        except (KeyError, ValueError, TypeError, AttributeError):
            continue                                       # a missing text: nothing rather than half a card
        infos = [x for x in infos if x["texte"] or x["liens"]]
        h = r.get("handicap_id")
        if h and h not in texts:
            continue
        rows.append((c, GR._int(r.get("session")), e.get("lu_le") or "", e.get("url") or "", texts.get(h) if h else None,
                     YN.get(r.get("referent")), YN.get(r.get("ambassadeur")), json.dumps(infos, ensure_ascii=False)))
    return rows


def build(con, src: Path | None = FICHES) -> dict:
    """core.fiche_handicap: one row per fiche read with the « Contacter » tab (reader version 4)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.fiche_handicap (cod_aff_form VARCHAR, session INTEGER, lu_le VARCHAR, url VARCHAR,
        handicap VARCHAR, referent BOOLEAN, ambassadeur BOOLEAN, infos VARCHAR)""")
    rows = assemble(src) if src is not None and (src / "contact.csv").exists() else []
    RP._insert(con, "INSERT INTO core.fiche_handicap VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return {"fiches": len(rows), "referent": sum(1 for r in rows if r[5]), "ambassadeur": sum(1 for r in rows if r[6]),
            "pages_handicap": sum(1 for r in rows if json.loads(r[7]))}


def for_formation(con, cod: str) -> dict | None:
    """What the fiche says about disability support and a student ambassador, or None (fiche not read with this tab)."""
    if not RP._has(con, "core", "fiche_handicap"):
        return None
    r = con.execute("""SELECT session, lu_le, url, handicap, referent, ambassadeur, infos FROM core.fiche_handicap
                       WHERE cod_aff_form = ?""", [cod]).fetchone()
    if not r:
        return None
    s, lu, url, texte, ref, amb, infos = r
    infos = json.loads(infos or "[]")
    if not texte and ref is None and amb is None and not infos:
        return None
    return {"session": s, "lu_le": f"{lu[:4]}-{lu[4:6]}-{lu[6:8]}" if len(lu) >= 8 else None,
            "url": url if url.startswith("https://") and "parcoursup.fr/" in url.split("?")[0] else None,
            "handicap": texte, "referent": ref, "ambassadeur": amb, "infos": infos}
