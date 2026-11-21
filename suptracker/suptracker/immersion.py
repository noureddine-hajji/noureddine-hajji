"""Immersions, mini-stages and « étudiant d'un jour » as each formation's LIVE Parcoursup fiche speaks of them (sprint 4, owner
2026-11-21: « La formation me plaira-t-elle ? »).

No open data lists immersion days: Onisep's open-day file carries a handful (a remark on 10 events), the establishments' sites
are not read for them. What the fiches say is already harvested (scripts/fiches_grilles.py): 1,400 formations write of
immersions, mini-stages or « cours ouverts » in their own texts (2026-11-21), often to say the jury values them.

Rules:
  * The formation's OWN texts only: its complementary expectations, its advice to candidates, its notice, its jury's criteria
    and the establishment's « Informations supplémentaires » (reader version 4). The national expectations are shared by
    every formation of a mention: never quoted here.
  * A fixed list of words (KEYWORDS, folded: no accent, no case); each matching SENTENCE quoted verbatim (already masked at
    reading), with where it was found; a sentence over MAX_CHARS is cut around the word, the cut marked « … ». Never a date
    computed, never a promise that a day exists this year: the page says to ask the formation and that the fiche prevails.
  * The word alone is no proof of an offer (« immersion linguistique », « stage d'immersion en entreprise »): the sentence is
    shown so the student reads it, never summarised or classified.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from . import grilles as GR
from . import rapports as RP

FICHES = GR.FICHES
MAX_CHARS = 420
KEYWORDS = (
    ("immersion", re.compile(r"\bimmersions?\b")),
    ("d'un jour", re.compile(r"\b(?:etudiant|etudiante|etudiants|etudiantes|lyceen|lyceenne|lyceens|lyceennes|eleve|eleves)"
                             r"(?:\s*\(\s*e\s*\))?\s+d\W?un\s+jour\b")),
    ("cours ouverts", re.compile(r"\bcours\s+ouverts?\b")),
    ("mini-stage", re.compile(r"\bmini\s*-?\s*stages?\b")),
)
SOURCES = (("conseils", "Conseils aux candidats"), ("complementaires", "Attendus de la formation"),
           ("critere", "Ce que le jury examine"), ("infos", "Informations de l'établissement"),
           ("info", "Candidater à la formation"))
LABEL = dict(SOURCES)


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower().replace("’", "'"))
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def matches(s: str) -> list[str]:
    f = fold(s)
    return [k for k, rx in KEYWORDS if rx.search(f)]


def sentences(texte: str) -> list[str]:
    """A published text split into sentences (end punctuation or line break), words untouched."""
    out = []
    for line in (texte or "").splitlines():
        out += [x.strip() for x in re.split(r"(?<=[.!?;])\s+(?=[A-ZÀ-ÖØ-Þ0-9«\"(-])", line) if x.strip()]
    return out


def excerpt(s: str) -> str:
    """The sentence verbatim, or, over MAX_CHARS, the words around the first keyword with « … » where it was cut."""
    if len(s) <= MAX_CHARS:
        return s
    f = fold(s)                     # same length as s for these scripts (one folded char per char): checked below
    pos = min((m.start() for _k, rx in KEYWORDS if (m := rx.search(f))), default=0) if len(f) == len(s) else 0
    a = max(0, pos - MAX_CHARS // 2)
    b = min(len(s), a + MAX_CHARS)
    a = max(0, b - MAX_CHARS)
    if a > 0 and s.find(" ", a) != -1 and s.find(" ", a) < b:
        a = s.find(" ", a) + 1                        # whole words only: the cut moves inwards, never past MAX_CHARS
    if b < len(s) and s.rfind(" ", a, b) > a:
        b = s.rfind(" ", a, b)
    return ("… " if a > 0 else "") + s[a:b].strip() + (" …" if b < len(s) else "")


def quotes(parts: list[tuple[str, str]]) -> list[dict]:
    """[(source, text)] -> each matching sentence once: {source, label, texte, mots}."""
    out, seen = [], set()
    order = {k: i for i, (k, _l) in enumerate(SOURCES)}
    for src, texte in sorted(parts, key=lambda p: order.get(p[0], 99)):
        for s in sentences(texte):
            m = matches(s)
            if not m:
                continue
            q = excerpt(s)
            if q in seen:
                continue
            seen.add(q)
            out.append({"source": src, "label": LABEL[src], "texte": q, "mots": m})
    return out


def assemble(src: Path) -> list[tuple]:
    etat = {r["cod_aff_form"]: r for r in GR._read(src / "etat.csv")}
    texts = GR.read_texts(src / "textes.csv.gz")
    parts: dict[str, list] = {}

    def add(c, kind, tid):
        if tid and tid in texts:
            parts.setdefault(c, []).append((kind, texts[tid]))

    for r in GR._read(src / "attendus.csv"):
        c = r["cod_aff_form"]
        add(c, "complementaires", r.get("complementaires_id"))
        add(c, "conseils", r.get("conseils_id"))
        add(c, "info", r.get("info_id"))
    for r in GR._read(src / "criteres.csv"):
        add(r["cod_aff_form"], "critere", r.get("critere_id"))
        add(r["cod_aff_form"], "critere", r.get("elements_id"))
    for r in GR._read(src / "contact.csv"):
        add(r["cod_aff_form"], "infos", r.get("infos_id"))
    rows = []
    for c, p in parts.items():
        e = etat.get(c) or {}
        if e.get("status") not in ("ok", "sans_grille", "rejetee"):
            continue
        for i, q in enumerate(quotes(p)):
            rows.append((c, i + 1, q["source"], q["texte"], ",".join(q["mots"])))
    return rows


def build(con, src: Path | None = FICHES) -> dict:
    """core.fiche_immersion: one row per quoted sentence (code, rank, source, text, words found)."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.fiche_immersion (cod_aff_form VARCHAR, rang INTEGER, source VARCHAR, texte VARCHAR,
        mots VARCHAR)""")
    rows = assemble(src) if src is not None and (src / "etat.csv").exists() else []
    RP._insert(con, "INSERT INTO core.fiche_immersion VALUES (?, ?, ?, ?, ?)", rows)
    return {"phrases": len(rows), "formations": len({r[0] for r in rows})}


def for_formation(con, cod: str) -> dict | None:
    """The fiche's sentences about immersions and mini-stages, with the fiche's campaign and reading date, or None."""
    if not RP._has(con, "core", "fiche_immersion"):
        return None
    rows = con.execute("SELECT source, texte, mots FROM core.fiche_immersion WHERE cod_aff_form = ? ORDER BY rang", [cod]).fetchall()
    if not rows:
        return None
    g = con.execute("SELECT session, lu_le, url FROM core.fiche_grille WHERE cod_aff_form = ?", [cod]).fetchone() \
        if RP._has(con, "core", "fiche_grille") else None
    s, lu, url = g or (None, "", "")
    lu = lu or ""
    return {"session": s, "lu_le": f"{lu[:4]}-{lu[4:6]}-{lu[6:8]}" if len(lu) >= 8 else None,
            "url": url if (url or "").startswith("https://") and "parcoursup.fr/" in url.split("?")[0] else None,
            "phrases": [{"source": a, "label": LABEL[a], "texte": b, "mots": m.split(",") if m else []} for a, b, m in rows]}
