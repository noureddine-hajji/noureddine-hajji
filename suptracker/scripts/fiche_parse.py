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
VERSION = 2          # 2 (2026-11-14): one-field grids without "Au total", the "Candidater" notice, error pages are not fiches


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


def parse(page: str) -> dict:
    out = {"ok": False, "reason": "", "session": None, "champs": [], "criteres": [], "attendus_nationaux": None,
           "attendus_complementaires": None, "conseils": None, "info": None}
    t = re.search(r"<title>(.*?)</title>", page, re.S)
    if not t or not text(t.group(1)).startswith("Fiche formation"):
        out["reason"] = "pas une fiche"          # "Oups..." or "Mise à jour de données": an error page, read again later
        return out
    s = SESSION.search(text(page))
    out["session"] = int(s.group(1)) if s else None
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
