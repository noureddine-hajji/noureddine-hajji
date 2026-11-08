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
    out = {"session": None, "codes": [], "synthese": [], "doublettes": [], "masked": [], "pages": 0}
    last_kind = None
    carry = {"formation": "", "jury": "", "bac": "", "groupe": ""}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        out["pages"] = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            if out["session"] is None and (m := SESSION_RE.search(text)):
                out["session"] = int(m.group(1))
            for t in page.extract_tables():
                t = [r for r in t if any(_clean(c) for c in r)]      # a repeated header can follow an empty row
                if not t:
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
    return out


if __name__ == "__main__":
    import json
    import sys
    for p in sys.argv[1:]:
        r = parse(open(p, "rb").read())
        print(p, json.dumps({k: (v if k in ("session", "codes", "pages") else len(v)) for k, v in r.items()}))
