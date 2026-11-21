"""Reading of a Parcoursup formation fiche (afficherFicheFormation): the jury's evaluation grid and the expectations.

Owner's request, 2026-11-13: the weight (%) of each field of the evaluation grid (global view), each criterion with the
elements evaluated and its importance (detailed view), the national expectations and the formation's complementary ones.

What the fiche prints (checked on 9 live fiches of every kind, data/rapports/live/fiches_live/, 2026-11-13):
  * global grid: `table#table-analyse-cddt-onglet2`, one row per field (`th` = field, `td` = "50 %") and a last row
    "Au total" = 100 %; 4 or 5 fields (a formation may leave one out); a one-field grid (Geipi Polytech: "Résultats
    scolaires 100 %") prints no "Au total" row;
  * a formation that examines no application (apprenticeship) prints a notice under "Candidater à la formation" instead
    of a grid: kept verbatim (`info`); an error page ("Oups...", "Mise à jour de données") is not a fiche;
  * detailed grid: one `table.table-forme-notation-cgev` per field, in the global grid's order, its caption naming the
    field and its weight ("Vos résultats scolaires ... comptent pour 50%"); each row: criterion (`th`), elements evaluated
    (`td`), importance (`p.psup-rating-text` = Complémentaire / Important / Très important / Essentiel and "n sur 4");
  * "Les attendus nationaux" (every fiche) and "Les attendus complémentaires" (some licences, PASS): headings followed by
    free text; "Conseils aux candidats": a callout;
  * the campaign the grid serves: "Les formations analysent les candidatures en avril-mai 2026".

Rules: the texts are kept VERBATIM (whitespace normalised), never summarised or rated; e-mail addresses and phone numbers
are masked (a fiche's free texts name people: the site stores none); a fiche whose global grid does not add up to 100, whose
detailed tables do not match the global fields and weights, or whose importance labels and "n sur 4" disagree is rejected
(`ok` false with the reason), never half read. Stdlib only (the harvest runs with few dependencies); red team
redteam_grilles.py re-reads the same pages with BeautifulSoup.
"""
from __future__ import annotations

import html
import re

IMPORTANCE = {"Complémentaire": 1, "Important": 2, "Très important": 3, "Essentiel": 4}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)")
MASK_EMAIL, MASK_PHONE = "[adresse sur la fiche Parcoursup]", "[numéro sur la fiche Parcoursup]"
SESSION = re.compile(r"analysent les candidatures en [^.]*?(20\d\d)")
# sprint 3 (2026-11-21): 7,735 fiches read « ok » (apprenticeship offers SIES does not publish) print no « analysent les
# candidatures » line: the campaign is then read on the capacity line the fiche prints for it (« 359 places en 2026 »)
SESSION_ALT = re.compile(r"\b\d[\d\s]*\s+places?\s+en\s+(20\d\d)\b")
VERSION = 4          # 2 (2026-11-14): one-field grids without "Au total", the "Candidater" notice, error pages are not fiches
#                      3 (2026-11-15): the identity badges (State label, establishment, grants) and the tuition fees
#                      4 (2026-11-21, sprints 3-4): the « Contacter » tab (disability support, student ambassador, the
#                        establishment's « Informations supplémentaires ») and the campaign read from the capacity line


def text(fragment: str) -> str:
    """Visible text of an HTML fragment: line breaks kept for <br>, <p>, <li>; tags removed; whitespace normalised."""
    s = re.sub(r"<!--.*?-->", "", fragment, flags=re.S)
    s = re.sub(r"<li[^>]*>", "\n- ", s)
    s = re.sub(r"</li>", "", s)                                   # the next <li> starts its own line
    s = re.sub(r"<(?:br|/p|/ul|/div|/h\d)[^>]*>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif out and not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def mask(s: str | None) -> str | None:
    if s is None:
        return None
    return PHONE.sub(MASK_PHONE, EMAIL.sub(MASK_EMAIL, s))


def _section(page: str, heading: str) -> str | None:
    """The free text right after a heading (h3/h4) up to the end of its block (next button, heading or column)."""
    m = re.search(rf"<h[34][^>]*>\s*{re.escape(heading)}\s*</h[34]>(.*?)(?=<div class=\"fr-col|<h[2-4][\s>]|<button)", page, re.S)
    if not m:
        return None
    t = text(m.group(1))
    return t or None


def badges(page: str) -> dict:
    """The fiche's identity card (`div#header-ff-liste-badges`, owner 2026-11-15): the establishment's status badge, whether the
    formation opens the right to grants, and the State label(s): Parcoursup's own image code (`labellisation/DL_xx.svg`)
    with the badge printed next to it ("Diplôme national de licence contrôlé par l'Etat"). A fiche with no label prints
    none (kept as an empty list, never guessed)."""
    out = {"etab_type": None, "bourses": None, "labels": []}
    m = re.search(r'<div id="header-ff-liste-badges">(.*?)(?=<div class="psup-rating|<div id="ff-|<h2|<h3)', page, re.S)
    if not m:
        return out
    b = m.group(1)
    e = re.search(r'<span id="badge-type-contrat"[^>]*>(.*?)</span>', b, re.S)
    out["etab_type"] = text(e.group(1)) or None if e else None
    spans = [text(x) for x in re.findall(r'<span[^>]*\bfr-badge\b[^>]*>(.*?)</span>', b, re.S)]
    for x in spans:
        if re.fullmatch(r"Formation ouvrant droit aux bourses", x):
            out["bourses"] = True
        elif re.fullmatch(r"Formation n.ouvrant pas droit aux bourses", x):
            out["bourses"] = False
    for code, lab in re.findall(r'labellisation/([A-Za-z0-9_]+)\.svg".*?<span[^>]*\bfr-badge\b[^>]*>(.*?)</span>', b, re.S):
        out["labels"].append({"code": code, "texte": text(lab)})
    return out


def frais(page: str) -> list[dict]:
    """The tuition-fee callout ("Frais de scolarité", sometimes "... au titre de la double inscription en Licence"): each
    printed line as (heading, text), VERBATIM (the amounts are free text: "178 euros + 800 euros de frais spécifiques",
    "Aucun frais - les frais sont à la charge de l'employeur"). The callout's own title is the first line's context."""
    # the callout's title is an h4 or an h5 and its lines h5 or h6, depending on the fiche's layout (both seen on live fiches)
    m = re.search(r'<h([45]) class="fr-callout__title">\s*(Frais de scolarit[^<]*?)\s*</h\1>(.*?)(?=<div class="fr-alert|<div class="fr-accordions|<h3[\s>]|<section)',
                  page, re.S)
    if not m:
        return []
    titre = text(m.group(2))
    rows = [{"titre": titre, "rubrique": text(a), "texte": mask(text(c))}
            for _h, a, c in re.findall(r"<h([56])[^>]*>(.*?)</h\1>\s*<p[^>]*>(.*?)</p>", m.group(3), re.S)]
    return [r for r in rows if r["rubrique"]]


def _fold(s: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(ch))


NEANT = re.compile(r"(?:néant|neant|aucun|aucune|non renseigné|non communiqué|-)\.?", re.I)


def contact(page: str) -> dict:
    """The « Contacter et échanger avec l'établissement » tab (version 4, sprint 4, owner 2026-11-21), what it prints for a
    candidate in a situation of disability and to meet a student. Read on the 9 saved live fiches:
      * the callout « Sur l'accompagnement pour les situations de handicap » (h4 or h5): its sentences verbatim, and whether a
        « Référent handicap : » line gives a contact. The contact itself is NEVER kept (an address names a person): only
        that one is printed on the fiche (True), that the line says « néant » (False), or that there is no such line (None);
      * « Informations supplémentaires » (the establishment's free text, h4 or h5), masked: kept whole (the immersion days
        are read from it), and each of its paragraphs whose text or links speak of disability, with its http(s) links;
      * « Echanger avec un étudiant ambassadeur de la formation »: whether a contact is given (« Contact : néant » = False).
    Texts are masked (e-mail addresses, phone numbers), like everything read."""
    out = {"handicap": None, "referent": None, "infos": None, "handicap_infos": [], "ambassadeur": None}
    m = re.search(r'<h([456]) class="fr-callout__title">\s*Sur l.accompagnement pour les situations de handicap\s*</h\1>(.*?)</div>',
                  page, re.S)
    if m:
        lines = [text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", m.group(2), re.S)]
        ref = [x for x in lines if re.match(r"Référent handicap\s*:", x)]
        out["handicap"] = mask("\n".join(x for x in lines if x and x not in ref)) or None
        if ref:
            rest = re.sub(r"^Référent handicap\s*:\s*", "", ref[0]).strip()
            out["referent"] = bool(rest) and not NEANT.fullmatch(rest)
    i = re.search(r"<h[45][^>]*>\s*Informations supplémentaires\s*</h[45]>(.*?)(?=</div>)", page, re.S)
    if i:
        out["infos"] = mask(text(i.group(1))) or None
        for p in re.findall(r"<p[^>]*>(.*?)</p>", i.group(1), re.S):
            links = re.findall(r"""href=["'](https?://[^"'\s<>]+)["']""", p)
            t = mask(text(p))
            if "handicap" in _fold(f"{t} {' '.join(links)}"):
                out["handicap_infos"].append({"texte": t, "liens": list(dict.fromkeys(links))})
    a = re.search(r"Echanger avec un étudiant ambassadeur de la formation.{0,1500}?<p>\s*Contact\s*:\s*(.*?)</p>", page, re.S)
    if a:
        v = text(a.group(1)).strip()
        out["ambassadeur"] = bool(v) and not NEANT.fullmatch(v)
    return out


def parse(page: str) -> dict:
    out = {"ok": False, "reason": "", "session": None, "champs": [], "criteres": [], "attendus_nationaux": None,
           "attendus_complementaires": None, "conseils": None, "info": None, "badges": None, "frais": [], "contact": None}
    t = re.search(r"<title>(.*?)</title>", page, re.S)
    if not t or not text(t.group(1)).startswith("Fiche formation"):
        out["reason"] = "pas une fiche"          # "Oups..." or "Mise à jour de données": an error page, read again later
        return out
    s = SESSION.search(text(page)) or SESSION_ALT.search(text(page))
    out["session"] = int(s.group(1)) if s else None
    out["badges"] = badges(page)          # read on every fiche, grid or not (version 3)
    out["frais"] = frais(page)
    out["contact"] = contact(page)        # version 4: read on every fiche, grid or not
    out["attendus_nationaux"] = mask(_section(page, "Les attendus nationaux"))
    out["attendus_complementaires"] = mask(_section(page, "Les attendus complémentaires"))
    # the notice under "Candidater à la formation" (e.g. an apprenticeship formation that examines no application)
    n = re.search(r"<h3[^>]*>\s*Candidater à la formation\s*</h3>\s*<div class=\"fr-alert[^\"]*\">(.*?)</div>", page, re.S)
    out["info"] = (mask(text(n.group(1))) or None) if n else None
    c = re.search(r"<h[45] class=\"fr-callout__title\">\s*Conseils aux candidats\s*</h[45]>\s*(.*?)</div>\s*</div>", page, re.S)
    out["conseils"] = mask(text(c.group(1))) if c else None
    g = re.search(r'<table id="table-analyse-cddt-onglet2".*?</table>', page, re.S)
    if not g:
        out["reason"] = "pas de grille"
        return out
    rows = [(text(a), text(b)) for a, b in re.findall(r"<th scope=\"row\"[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", g.group(0), re.S)]
    total = [r for r in rows if r[0] == "Au total"]
    champs = [r for r in rows if r[0] != "Au total"]
    pct = lambda v: int(m.group(1)) if (m := re.fullmatch(r"(\d{1,3})\s*%", v)) else None  # noqa: E731
    # "Au total" is printed when the grid has several fields: when present it must say 100 (a one-field grid has none)
    if not champs or len(total) > 1 or (len(champs) > 1 and not total) or any(pct(v) is None for _c, v in champs) \
            or (total and pct(total[0][1]) != 100):
        out["reason"] = "grille illisible"
        return out
    out["champs"] = [{"rang": i + 1, "champ": c, "poids": pct(v)} for i, (c, v) in enumerate(champs)]
    if sum(x["poids"] for x in out["champs"]) != 100:
        out["reason"] = f"poids additionnés {sum(x['poids'] for x in out['champs'])} %, pas 100 %"
        return out
    tables = re.findall(r'<table class="table-forme-notation-cgev[^"]*">\s*<caption[^>]*>(.*?)</caption>(.*?)</table>', page, re.S)
    if len(tables) != len(champs):
        out["reason"] = f"{len(tables)} tableaux détaillés pour {len(champs)} champs"
        return out
    for i, (cap, body) in enumerate(tables):
        cap_t = text(cap)
        w = re.search(r"compte(?:nt)? pour (\d{1,3})\s*%", cap_t)
        if not w or int(w.group(1)) != out["champs"][i]["poids"]:
            out["reason"] = f"tableau {i + 1} : poids « {cap_t} » ≠ {out['champs'][i]['poids']} %"
            return out
        out["champs"][i]["intitule"] = cap_t
        tb = re.search(r"<tbody>(.*?)</tbody>", body, re.S)
        for j, tr in enumerate(re.findall(r"<tr>(.*?)</tr>", tb.group(1) if tb else "", re.S)):
            th = re.search(r"<th scope=\"row\"[^>]*>(.*?)</th>", tr, re.S)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            lab = re.search(r'<p class="psup-rating-text">(.*?)</p>', tr, re.S)
            sur = re.search(r'title="([1-4]) sur 4"', tr)
            if not th or not tds or not lab or not sur:
                out["reason"] = f"tableau {i + 1}, ligne {j + 1} illisible"
                return out
            label = text(lab.group(1))
            if IMPORTANCE.get(label) != int(sur.group(1)):
                out["reason"] = f"importance « {label} » ≠ {sur.group(1)} sur 4"
                return out
            out["criteres"].append({"champ_rang": i + 1, "rang": j + 1, "critere": mask(text(th.group(1))),
                                    "elements": mask(text(tds[0])), "importance": int(sur.group(1)), "importance_label": label})
    out["ok"] = True
    return out
