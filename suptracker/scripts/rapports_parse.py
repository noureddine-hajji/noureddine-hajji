"""Parse a Parcoursup public report PDF ("rapport public des commissions d'examen des vœux").

Two tables are read, with pdfplumber's table extraction (cells, not text lines: names span several lines):
  * "Synthèse des candidatures, classements et admissions": per calling group, places, candidates who confirmed the
    vœu, ranked, "en position de recevoir une proposition", accepted. Used to CHECK the report against SIES
    (confirmed = nb_voe_pp, en position = ran_grp of the group).
  * "Suivi des candidats par choix d'enseignements de spécialité": per bac type and doublette (or "Autres doublettes"),
    the same four counts. A bac type whose cell says "ne sont pas statistiquement significatives" is recorded as masked.
Counts are kept as published; the rate (en position / confirmé) is computed later, never stored as published.
"""
from __future__ import annotations

import io
import re

SESSION_RE = re.compile(r"Rapport public Parcoursup session (\d{4})")
CODE_RE = re.compile(r"\((\d+)\)\s*$")
MASK_RE = re.compile(r"statistiquement significatives", re.I)


def _clean(x) -> str:
    return re.sub(r"\s+", " ", x or "").strip()


def _int(x):
    x = _clean(x).replace(" ", "").replace(" ", "")
    return int(x) if re.fullmatch(r"\d+", x) else None


def _kind(header: list) -> str | None:
    h = " ".join(_clean(c) for c in header if c)
    if "EDS 1 & EDS 2" in h or "Spécialité" in h and "Type de bac" in h:
        return "doublette"
    if "places proposées" in h and "Groupe" in h:
        return "synthese"
    return None


def _is_header(row: list) -> bool:
    return any("Nombre de" in _clean(c) or _clean(c).startswith("Formation d") for c in row if c)


def _is_title(row: list) -> bool:
    cells = [_clean(c) for c in row if _clean(c)]
    return len(cells) == 1 and not re.search(r"\d+$", cells[0]) and not _is_header(row)


def parse(content: bytes) -> dict:
    import pdfplumber
    out = {"session": None, "codes": [], "synthese": [], "doublettes": [], "masked": [], "pages": 0, "criteres": [],
           "pages_vides": 0, "fin": False}
    last_kind = None
    texts = []
    crit_carry = ""
    carry = {"formation": "", "jury": "", "bac": "", "groupe": ""}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        out["pages"] = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            texts.append(text)
            out["pages_vides"] += not text.strip()
            if out["session"] is None and (m := SESSION_RE.search(text)):
                out["session"] = int(m.group(1))
            for t in page.extract_tables():
                t = [r for r in t if any(_clean(c) for c in r)]      # a repeated header can follow an empty row
                if not t:
                    continue
                # the examination criteria (champ, critère, éléments, degré d'importance), cut across pages too
                if _clean(t[0][0]).startswith("Champs d") or last_kind == "criteres" and len(t[0]) == 4 and not _is_header(t[0]):
                    last_kind = "criteres"
                    for r in t[1:] if _clean(t[0][0]).startswith("Champs d") else t:
                        r = [_clean(c) for c in list(r) + [None] * (4 - len(r))]
                        crit_carry = r[0] or crit_carry
                        if r[1] or r[2] or r[3]:
                            out["criteres"].append({"champ": crit_carry, "critere": r[1], "elements": r[2], "importance": r[3]})
                    continue
                # some reports put the table title in a first merged row: the header is then the second row
                hi = 1 if len(t) > 1 and _is_title(t[0]) else 0
                if _is_header(t[hi]):
                    k = _kind(t[hi])
                    last_kind = k             # another table (sex, bac type, profile...) stops any continuation
                    if k is None:
                        continue
                    rows = t[hi + 1:]
                elif _is_title(t[0]):
                    last_kind = None
                    continue
                else:
                    # a fragment without header continues the table cut by the page break
                    if last_kind is None:
                        continue
                    k, rows = last_kind, t
                for r in rows:
                    if _is_header(r):
                        continue
                    r = list(r) + [None] * (8 - len(r))
                    if _clean(r[0]):
                        carry["formation"] = _clean(r[0])
                        if (m := CODE_RE.search(carry["formation"])) and m.group(1) not in out["codes"]:
                            out["codes"].append(m.group(1))
                    if _clean(r[1]):
                        carry["jury"] = _clean(r[1])
                    code = (CODE_RE.search(carry["formation"]) or [None, None])[1]
                    if k == "synthese":
                        if _clean(r[2]):
                            carry["groupe"] = _clean(r[2])
                        nums = [_int(v) for v in r[3:8]]
                        if all(v is None for v in nums):
                            continue
                        out["synthese"].append({"code": code, "jury": carry["jury"], "groupe": carry["groupe"],
                                                "places": nums[0], "confirmes": nums[1], "classes": nums[2],
                                                "en_position": nums[3], "acceptes": nums[4]})
                    else:
                        if _clean(r[2]):
                            carry["bac"] = _clean(r[2])
                        label = _clean(r[3])
                        if MASK_RE.search(label):
                            out["masked"].append({"code": code, "jury": carry["jury"], "bac": carry["bac"]})
                            continue
                        nums = [_int(v) for v in r[4:8]]
                        if not label or all(v is None for v in nums):
                            continue
                        out["doublettes"].append({"code": code, "jury": carry["jury"], "bac": carry["bac"], "doublette": label,
                                                  "confirmes": nums[0], "classes": nums[1], "en_position": nums[2],
                                                  "acceptes": nums[3]})
    out["fin"] = bool(re.search(r"Signature\s*:", "\n".join(texts[-2:])))   # the report's last section: nothing lost after it
    crit_text = "\n".join(f"{c['critere']} : {c['elements']} ({c['importance']})." for c in out["criteres"])
    out.update(qualitative("\n".join(texts), crit_text))
    return out


# --------------------------------------------------------------------------- the jury's own texts (qualitative sections)
H_EDS = "Prenez-vous en compte les enseignements de spécialité"
SECTIONS = [("eliminatoires", r"Critères éliminatoires"), ("modalites", r"Les modalités d['’]examen des v(?:œ|oe)ux"),
            ("algorithme", r"Avez-vous eu recours à un traitement algorithmique \?"),
            ("conseils", r"Nos conseils aux candidats pour la prochaine session"), ("fin", r"Signature\s*:")]
# options and specific courses a jury may name; only reported as QUOTED excerpts, never interpreted
OPTIONS = {"maths_expertes": r"math[ée]matiques?\s+expert|maths?\s+expert",
           "maths_complementaires": r"math[ée]matiques?\s+compl[ée]mentaire|maths?\s+compl[ée]mentaire",
           "dgemc": r"droit et grands enjeux|\bDGEMC\b",
           "langues_anciennes": r"\blatin\b|\bgrec\b|langues? et cultures? de l['’]antiquit|\bLCA\b",
           "lv3": r"\bLV ?3\b|\bLVC\b|langue vivante [Cc]\b|troisi[èe]me langue",
           "option_arts": r"option (?:facultative )?(?:arts|musique|th[ée][âa]tre|cin[ée]ma|danse|histoire des arts)",
           "option_eps": r"option (?:facultative )?(?:EPS|[ée]ducation physique)",
           "section_euro": r"section europ[ée]enne|section internationale|\bDNL\b|bachibac|abibac|esabac",
           "certifications": r"\bPIX\b|\bTOEIC\b|\bTOEFL\b|\bIELTS\b|\bcambridge\b|\bDELF\b|\bDELE\b|certification"}


def clean_eds_list(items: list) -> list:
    """The specialties a jury lists, up to the first line that is not one (the next section's title or question,
    a long sentence): what follows is another section of the report, never a specialty."""
    out = []
    for x in items:
        x = str(x).strip()
        if not x or "?" in x or len(x) > 90 or re.match(r"(?i)(crit[èe]res?|vous avez|pr[ée]ciser|non,|oui,)", x):
            break
        out.append(x)
    return out


def _section(text: str, start: str, ends: list[str]) -> str:
    m = list(re.finditer(start, text))
    if not m:
        return ""
    a = m[-1].end()                     # the title is often printed twice (page title, then section title)
    b = min([x.start() for e in ends for x in [re.search(e, text[a:])] if x] or [len(text) - a]) + a
    body = re.sub(r"\s*=== PAGE ===\s*", "\n", text[a:b])
    return re.sub(r"[ \t]+", " ", body).strip()


def qualitative(text: str, crit_text: str = "") -> dict:
    q = {}
    pats = [p for _, p in SECTIONS]
    for i, (name, pat) in enumerate(SECTIONS[:-1]):
        q[name] = _section(text, pat, pats[i + 1:] + [r"Les critères utilisés en", r"Rapport public Parcoursup session"])[:4000]
    if q.get("eliminatoires"):
        q["eliminatoires"] = re.sub(r"^Préciser les critères quantitatifs.*?candidatures\s*", "", q["eliminatoires"], flags=re.S).strip()
    q["algorithme"] = q.get("algorithme", "")[:1500]
    # EDS: taken into account? their weight? which ones, per series (as printed)
    eds = {"pris_en_compte": None, "poids": "", "liste": {}}
    m = re.search(H_EDS + r".*?\?\s*(.+?)\n", text, re.S)
    if m:
        eds["pris_en_compte"] = m.group(1).strip().rstrip(".")
        blk = _section(text, re.escape(H_EDS), [r"Critères éliminatoires", pats[1], r"Les modalités"])
        if (w := re.search(r"Le poids dans l'examen des candidatures donné aux résultats académiques dans certains EDS\s*:\s*(.+?)\n", blk)):
            eds["poids"] = w.group(1).strip()
        serie = None
        for line in blk.split("\n")[1:]:
            line = line.strip()
            if re.match(r"^Série\s+\S", line):
                serie = line; eds["liste"].setdefault(serie, [])
            elif serie and line and not line.startswith(("Quels sont", "Le poids", "Est ")):
                eds["liste"][serie].append(re.sub(r"\s*\(EDS\)\s*$", "", line))
    eds["liste"] = {k: clean_eds_list(v) for k, v in eds["liste"].items() if clean_eds_list(v)}
    q["eds"] = eds
    # options named anywhere in the jury's texts and criteria: keep the sentence, verbatim
    corpus = "\n".join([crit_text, q.get("modalites", ""), q.get("conseils", ""), q.get("eliminatoires", "")])
    found = {}
    for k, pat in OPTIONS.items():
        hits = []
        for sent in re.split(r"(?<=[.;!?])\s+|\n", corpus):
            if re.search(pat, sent, re.I) and len(hits) < 3:
                hits.append(sent.strip()[:400])
        if hits:
            found[k] = hits
    q["options_citees"] = found
    return q


if __name__ == "__main__":
    import json
    import sys
    for p in sys.argv[1:]:
        r = parse(open(p, "rb").read())
        print(p, json.dumps({k: (v if k in ("session", "codes", "pages") else len(v)) for k, v in r.items()
                             if k not in ("eds", "options_citees", "modalites", "conseils", "eliminatoires", "algorithme")}))
        print("   eds", json.dumps(r["eds"], ensure_ascii=False)[:300])
        print("   options", json.dumps(r["options_citees"], ensure_ascii=False)[:300])
        for k in ("eliminatoires", "modalites", "algorithme", "conseils"):
            print("  ", k, len(r[k]), repr(r[k][:120]))
        print("   criteres", r["criteres"][:2])
