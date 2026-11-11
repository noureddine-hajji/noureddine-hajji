"""Sprint 22: the OFFICIAL Parcoursup campaign calendar (owner's go, 2026-11-11).

The calendar is a PDF published on parcoursup.gouv.fr. That host is blocked in the development sandbox, so the
`suptracker-calendrier` workflow fetches it (every published version) into data/calendrier/ with its extracted text
(`scripts/calendrier_fetch.py`). This module reads the dates from that text with one fixed rule per step, each anchored on the
official wording (the step names are the official headings or dated lines). A date is served only if:
  * every fetched version of the document prints it identically (the first version of the 2027 PDF says "samedi 10 juin 2027"
    in a heading where the later ones say "samedi 10 juillet": headings are not read, and a disagreement drops the date);
  * its printed weekday is the true weekday of that date (10 June 2027 is a Thursday).
A step whose date cannot be read is listed as "date à vérifier sur parcoursup.gouv.fr", never guessed. The step names are the
official ones; what to do on SupCompass at each step is this site's own text, kept apart. The official calendar fait foi.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

DIR = Path(__file__).resolve().parents[1] / "data" / "calendrier"
CAMPAGNE = 2027
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre")
_D = r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+(1er|\d{1,2})\s+(" + "|".join(MONTHS) + r")"
_Y = r"\s+(\d{4})"

# (key, step 1-3, official name, pattern on the folded text: groups = weekday, day, month[, year] (and a second date for a range))
RULES = (
    ("carte", 1, "Ouverture de la carte des formations 2027 sur parcoursup.gouv.fr",
     _D + _Y + r"\s*[-—–]\s*ouverture de la carte"),
    ("voeux", 2, "Je m'inscris pour formuler mes vœux",
     r"du\s+" + _D + r"\s+au\s+" + _D + _Y),
    ("fin_voeux", 2, "Dernier jour pour formuler vos vœux",
     _D + _Y + r"\s*[-—–]\s*dernier jour pour formuler"),
    ("confirmation", 2, "Dernier jour pour compléter votre dossier et confirmer vos vœux",
     _D + _Y + r"\s*[-—–]\s*dernier jour pour completer"),
    ("admission", 3, "Début de la phase d'admission principale",
     _D + _Y + r"\s*[-—–]\s*debut de la phase d.admission principale"),
    ("classement", 3, "Classez vos vœux en attente",
     r"e ?ntre le\s+" + _D + r"\s+et le\s+" + _D + _Y + r"\s+inclus\s*:\s*classez vos voeux en attente"),
    ("complementaire", 3, "Début de la phase complémentaire",
     _D + _Y + r"\s*[-—–]\s*debut de la phase complementaire"),
    ("fin_principale", 3, "Fin de la phase principale",
     _D + _Y + r"\s*[-—–]\s*fin de la phase principale"),
    ("fin_complementaire", 3, "Fin de la phase complémentaire",
     _D + _Y + r"\s*[-—–]\s*fin de la phase complementaire"),
)
STEPS = {1: "Je m'informe et découvre les formations", 2: "Je m'inscris, je formule mes vœux et je finalise mon dossier",
         3: "Je reçois les réponses des formations et je décide"}
# what this site offers at each step: SupCompass's own text, never presented as official
SUR_SUPCOMPASS = {
    "carte": "Vérifiez sur parcoursup.gouv.fr que les formations repérées ici existent toujours en 2027 : les chiffres de SupCompass sont ceux des campagnes 2022 à 2025.",
    "voeux": "Construisez votre liste dans « Mes vœux » (10 vœux au plus), relisez-la pour votre profil et partagez-la avec un adulte qui vous accompagne.",
    "fin_voeux": "Après cette date, aucun nouveau vœu en phase principale (sauf en apprentissage) : vérifiez que votre liste contient des vœux de sécurité.",
    "confirmation": "SupCompass ne remplace pas votre dossier : chaque vœu se confirme sur Parcoursup.",
    "admission": "Les réponses arrivent au fur et à mesure. « Comprendre l'appel » montre jusqu'où les listes ont été appelées les années passées, sans jamais prédire votre rang.",
    "classement": "Ce classement se fait sur Parcoursup ; vos vœux sur SupCompass ne sont pas classés.",
    "complementaire": "La phase complémentaire permet de formuler jusqu'à 10 nouveaux vœux dans des formations qui ont encore des places.",
    "fin_principale": "Pensez à répondre aux propositions dans les délais affichés sur Parcoursup.",
    "fin_complementaire": "Fin de la procédure Parcoursup 2027.",
}


def _fold_keep_dash(s: str) -> str:
    """Accents and case off, œ → oe, ’ → ', every run of spaces one space (the PDF text wraps lines); the dashes are kept."""
    s = s.replace("—", " — ").replace("–", " – ").replace("\u2019", "'").replace("œ", "oe").replace("Œ", "OE")
    out = []
    for ch in unicodedata.normalize("NFKD", s):
        if ch in "—–":
            out.append(ch)
        elif ord(ch) < 128:
            out.append(ch)
    return " ".join("".join(out).lower().split())


def _date(wd: str, day: str, month: str, year: str) -> tuple[date | None, bool]:
    try:
        d = date(int(year), MONTHS.index(month) + 1, 1 if day == "1er" else int(day))
    except ValueError:                                  # "31 février": an impossible date leaves the step unverified (Codex)
        return None, False
    return d, WEEKDAYS[d.weekday()] == wd


def parse(text: str) -> dict:
    """key -> {"debut": date, "fin": date|None, "jour_ok": bool} for every rule found in ONE version of the document."""
    t = _fold_keep_dash(text)
    out = {}
    for key, _, _, pat in RULES:
        m = re.search(pat, t)
        if not m:
            continue
        g = m.groups()
        if len(g) == 4:
            d, ok = _date(*g)
            out[key] = {"debut": d, "fin": None, "jour_ok": ok}
        else:                                           # a range: the year is printed once, at its end
            d1, ok1 = _date(g[0], g[1], g[2], g[6])
            d2, ok2 = _date(g[3], g[4], g[5], g[6])
            out[key] = {"debut": d1, "fin": d2, "jour_ok": ok1 and ok2 and d1 is not None and d2 is not None and d1 <= d2}
    return out


def versions(base: Path = DIR) -> list[dict]:
    """The fetched official documents (fetch_log.json), each with its text."""
    try:
        log = json.loads((base / "fetch_log.json").read_text())
    except (OSError, ValueError):
        return []
    out = []
    for row in log:
        f = row.get("file")
        if row.get("status") != 200 or not f or not f.endswith(".pdf"):
            continue
        p = base / f"{f}.txt"
        if p.exists():
            out.append({"url": row["url"], "fetched": row.get("fetched"), "sha256": row.get("sha256"), "text": p.read_text()})
    return out


def calendar(base: Path = DIR) -> dict:
    """The served calendar: every rule, with its date only when all versions agree and the weekday is right."""
    vs = versions(base)
    parsed = [parse(v["text"]) for v in vs]
    events = []
    for key, step, name, _ in RULES:
        found = [p.get(key) for p in parsed]
        ok = bool(vs) and all(f is not None for f in found) and all(f["jour_ok"] for f in found) \
            and len({(f["debut"], f["fin"]) for f in found}) == 1
        e = {"key": key, "etape": step, "libelle": name, "sur_supcompass": SUR_SUPCOMPASS[key],
             "debut": found[0]["debut"].isoformat() if ok else None, "fin": found[0]["fin"].isoformat() if ok and found[0]["fin"] else None,
             "verifie": ok}
        events.append(e)
    fetched = max((v["fetched"] for v in vs if v.get("fetched")), default=None)
    return {"campagne": CAMPAGNE, "etapes": STEPS, "evenements": events, "lu_le": fetched[:10] if fetched else None,
            "sources": [{"url": v["url"], "sha256": v["sha256"]} for v in vs], "n_versions": len(vs)}


def _ics_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold_line(line: str) -> list[str]:
    """RFC 5545: lines of at most 75 octets, continuation lines start with a space."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > (75 if not out else 74):
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return [out[0]] + [" " + x for x in out[1:]]


def ics(cal: dict) -> str:
    """All-day events for the verified dates only; DTSTAMP is the fetch date (the file is the same for every visitor)."""
    stamp = (cal.get("lu_le") or "2026-01-01").replace("-", "") + "T000000Z"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SupCompass//Calendrier Parcoursup//FR", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:Parcoursup {cal['campagne']}"]
    for e in cal["evenements"]:
        if not e["verifie"]:
            continue
        d1 = date.fromisoformat(e["debut"])
        d2 = date.fromisoformat(e["fin"] or e["debut"])
        end = date.fromordinal(d2.toordinal() + 1)          # DTEND of an all-day event is exclusive
        desc = f"{e['libelle']} (calendrier officiel Parcoursup {cal['campagne']}, parcoursup.gouv.fr). {e['sur_supcompass']}"
        for ln in ("BEGIN:VEVENT", f"UID:parcoursup-{cal['campagne']}-{e['key']}@supcompass", f"DTSTAMP:{stamp}",
                   f"DTSTART;VALUE=DATE:{d1:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}",
                   f"SUMMARY:{_ics_text('Parcoursup ' + str(cal['campagne']) + ' : ' + e['libelle'])}",
                   f"DESCRIPTION:{_ics_text(desc)}", "END:VEVENT"):
            lines.extend(_fold_line(ln))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
