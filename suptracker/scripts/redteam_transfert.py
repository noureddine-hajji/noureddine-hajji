"""Red team: « Transférer sur mon autre appareil » and the teacher's kit for a class session (owner, 2026-11-27, PR 17).

    python scripts/redteam_transfert.py [--db data/suptracker.duckdb] [--real] [--browser]

  TF1 round trip (Node twins): transferRead(transferLink(list, profile)) gives back the list and the profile, the AVERAGE included
      (the owner's exception), never the académie, the lycée, the town or the « boursier » box; no default pair is invented
  TF2 hostile links against an independent oracle: length cap, codes cleaned (digits, deduplicated, at most 10), an unreadable
      average / pair / route dropped and SAID, a mention read from the average, an unreadable profile never defaulted, no raw text
  TF3 the QR code: the vendored encoder's matrix equals the Python `qrcode` package's (same version, level M, byte mode), for the
      mask the encoder chose, which is also the package's own best mask
  TF4 installing: « replace » keeps this device's académie, lycée and « boursier », replaces the list (at most 10); « add » merges
      the codes and never touches the profile; the page asks a second click before replacing anything, and clears the link
  TF5 the kit: our own words, vouvoiement, no chance, sentences of at most 30 words, no figure, internal links only, the address
      as a QR code, the students' sheet on its own printed page
  TF6 privacy and credits: the privacy page says what the link carries and that it is not sent; the legal page credits the MIT
      library; the vendored file is the published one with its licence; the cards say « pour vous seul » and what is left out
  TF7 browser: sender card (Mes vœux and Mon profil) and QR, receiver install (empty device) and replace after confirmation
      (device with data), the hash cleared, no request carrying the payload, the kit page, 0 JS error, no horizontal scroll
  TF8 wiring and docs
  TF9 mutation test
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
CHECKS = []

import nodefile  # noqa: E402
import redteam_robustesse as RB  # noqa: E402

top = RB.top
HOSTILE = '<img src=x onerror=alert(1)>'
VENDOR = ROOT / "suptracker" / "static" / "vendor" / "qrcode" / "qrcode.js"
SPECS = ["MATHS", "PC", "SVT", "SES", "HGGSP", "LLCER", "HLP", "NSI", "SI", "LLCA", "EPPCS", "ART", "BIOECO"]
VOIES = {"bt": [{"code": "stmg_merc", "label": "STMG, Mercatique"}, {"code": "sti2d_ee", "label": "STI2D, Énergies et environnement"}],
         "bp": [{"code": "bp_mcv", "label": "Métiers du commerce et de la vente"}]}
MENTIONS = ["rattrapage", "sansmention", "ab", "b", "tb", "tbf"]
ORIGIN = "https://supcompass.example"


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


class Ctx:
    def __init__(self, db: Path, real: bool, browser: bool):
        self.db, self.real, self.browser = Path(db), real, browser
        self.js = (ROOT / "suptracker" / "static" / "app.js").read_text()
        self.css = (ROOT / "suptracker" / "static" / "style.css").read_text()


# ------------------------------------------------------------------ the Node harness
NAMES = ("MENTION_CODES", "BANDS", "validMoyenne", "bandOf", "vxProfile", "isReo", "shareCodes", "TRANSFER_KEYS", "TRANSFER_MAX",
         "transferLink", "transferRead", "transferProfile", "transferApply", "qrMatrix", "KIT_STEPS", "KIT_CHECK")
STUB = r"""
const location = { origin: "%s", pathname: "/" };
const fmt = (x) => String(x);
const track = () => {};
const profileBar = { render() {} };
const document = { querySelectorAll: () => [] };
const _ls = {}; const localStorage = { getItem: (k) => (k in _ls ? _ls[k] : null), setItem: (k, v) => { _ls[k] = String(v); }, removeItem: (k) => { delete _ls[k]; } };
const store = { get: (k, d) => { try { const v = JSON.parse(localStorage.getItem(k)); return v === null ? d : v; } catch (_) { return d; } },
  set: (k, v) => localStorage.setItem(k, JSON.stringify(v)) };
let JV = null;
const voeux = { MAX: 10,
  get() { let v; try { v = JSON.parse(localStorage.getItem("voeux")); } catch (_) { v = null; } if (!Array.isArray(v)) v = [];
    return [...new Set(v.filter((c) => typeof c === "string" && /^\d{1,9}$/.test(c)))].slice(0, this.MAX); },
  set(v) { localStorage.setItem("voeux", JSON.stringify(v)); },
  add(cod) { const v = this.get(); if (!v.includes(cod) && v.length < this.MAX) { v.push(cod); this.set(v); } return v.includes(cod); },
  render() {} };
const qrcode = require(%s);
""" % (ORIGIN, json.dumps(str(VENDOR)))


def harness(c: Ctx, prog: str, data, js: str | None = None):
    js = js if js is not None else c.js
    parts = [top(js, n) for n in NAMES]
    if not all(parts):
        raise RuntimeError(f"missing from app.js: {[n for n, p in zip(NAMES, parts) if not p]}")
    return RB.node(STUB + "\n".join(parts) + "\n" + prog, data)


# ------------------------------------------------------------------ the independent oracle (the rules written again, in Python)
def valid_moyenne(v):
    if v is None or v == "":
        return None
    try:
        x = float(str(v).strip().replace(",", "."))
    except ValueError:
        return None
    if x != x or not 8 <= x <= 20:
        return None
    return round(x * 10) / 10 if abs(x * 10 - round(x * 10)) != 0.5 else int(x * 10 + 0.5) / 10   # JS Math.round: half up


def band_of(g):
    if g < 10:
        return "rattrapage"
    if g < 12:
        return "sansmention"
    for m, (lo, hi) in (("ab", (12, 14)), ("b", (14, 16)), ("tb", (16, 18))):
        if lo <= g < hi:
            return m
    return "tbf"


def clean_codes(raw):
    out = []
    for c in str(raw or "").split(","):
        c = c.strip()
        if re.fullmatch(r"\d{1,9}", c) and c not in out and len(out) < 10:
            out.append(c)
    return out


def own_read(raw: str):
    """Expected (ids, profile key fields, number of notes) or None."""
    if not raw or len(raw) > 600:
        return None
    q = {}
    for k, v in parse_qsl(raw, keep_blank_values=True):
        q.setdefault(k, v)                                              # URLSearchParams.get = the first value
    keys = {"s": "serie", "a": "spe1", "b": "spe2", "m": "mention", "n": "moyenne", "t": "statut", "v": "voie", "x": "maths_expertes"}
    p = {f: q[k] for k, f in keys.items() if q.get(k) and len(q[k]) <= 60}
    ids = clean_codes(q.get("l", ""))
    notes, prof = 0, None
    if p.get("statut") == "r":
        prof = {"statut": "reorientation"}
    elif p.get("serie") in ("bg", "bt", "bp") and (p.get("mention") in MENTIONS or valid_moyenne(p.get("moyenne")) is not None):
        prof = {"serie": p["serie"], "statut": "terminale", "moyenne": None}
        m = valid_moyenne(p.get("moyenne"))
        if "moyenne" in p:
            if m is None:
                notes += 1
            else:
                prof["moyenne"] = m
        prof["mention"] = band_of(m) if m is not None else (p["mention"] if p.get("mention") in MENTIONS else "ab")
        if p["serie"] == "bg":
            if p.get("spe1") in SPECS and p.get("spe2") in SPECS and p["spe1"] != p["spe2"]:
                prof["spe1"], prof["spe2"] = p["spe1"], p["spe2"]
                prof["maths_expertes"] = p.get("maths_expertes") == "1"
            else:                                                       # no pair: no profile (Codex), the note said
                notes += 1
                prof = None
        elif p.get("voie"):
            if any(r["code"] == p["voie"] for r in VOIES.get(p["serie"], [])):
                prof["voie"] = p["voie"]
            else:
                notes += 1
    elif p:
        notes += 1
    if not ids and not prof:
        return None
    return {"ids": ids, "prof": prof, "notes": notes}


ADD_ONLY = "${t.ids.length && (mine.length || hasLocal) ? '<button type=\"button\" id=\"tf-add\">"


def shape(prof):
    """The fields the oracle speaks about, from a profile the page read."""
    if prof is None:
        return None
    if prof.get("statut") == "reorientation":
        return {"statut": "reorientation"}
    out = {k: prof.get(k) for k in ("serie", "statut", "moyenne", "mention")}
    if prof.get("serie") == "bg":
        if prof.get("spe1"):
            out["spe1"], out["spe2"] = prof["spe1"], prof.get("spe2")
        out["maths_expertes"] = bool(prof.get("maths_expertes"))
    elif prof.get("voie"):
        out["voie"] = prof["voie"]
    return out


READ_PROG = r"""
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
JV = D.jv;
const out = { links: [], reads: [] };
for (const [ids, prof] of D.pairs) { const l = transferLink(ids, prof); out.links.push(l); const t = transferRead(l.split("#/transfert/")[1]); out.reads.push(t); }
out.raw = D.raws.map((r) => transferRead(r));
process.stdout.write(JSON.stringify(out));"""

JV = {"specialties": [{"code": s} for s in SPECS], "voies": VOIES}
LOCAL = {"academie": "Lyon", "lycee": {"uai": "0690026D", "nom": "Lycée du Parc", "commune": "Lyon"}, "boursier": True}
PAIRS = [
    (["10", "100", "10001"], {"serie": "bg", "spe1": "MATHS", "spe2": "PC", "mention": "b", "moyenne": 14.6, "maths_expertes": True, **LOCAL}),
    (["10"], {"serie": "bg", "spe1": "SES", "spe2": "HGGSP", "mention": "tb", **LOCAL}),
    ([], {"serie": "bt", "mention": "ab", "voie": "stmg_merc", "voie_label": "STMG, Mercatique", "moyenne": 12.0, **LOCAL}),
    (["5", "6"], {"serie": "bp", "mention": "sansmention", "voie": "autre", "voie_label": "Autre", **LOCAL}),
    (["7"], {"statut": "reorientation", "academie": "Lyon"}),
    (["8", "9"], None),
    (["11"], {"serie": "bg", "mention": "ab", "moyenne": 9.4}),             # no pair stored: none is invented
    (["12"], {"serie": "bg", "spe1": "MATHS", "spe2": "PC", "mention": "rattrapage", "moyenne": 19.95}),
]


def expected_pair(ids, prof):
    """What the other device must read from the link of (ids, prof)."""
    if prof is None:
        return {"ids": ids, "prof": None}
    if prof.get("statut") == "reorientation":
        return {"ids": ids, "prof": {"statut": "reorientation"}}
    m = valid_moyenne(prof.get("moyenne"))
    out = {"serie": prof["serie"], "statut": "terminale", "moyenne": m, "mention": band_of(m) if m is not None else prof["mention"]}
    if prof["serie"] == "bg":
        if not (prof.get("spe1") and prof.get("spe2")):
            return {"ids": ids, "prof": None}                         # never installed with a default pair (Codex)
        out["spe1"], out["spe2"] = prof["spe1"], prof["spe2"]
        out["maths_expertes"] = bool(prof.get("maths_expertes"))
    elif prof.get("voie") and prof["voie"] != "autre":
        out["voie"] = prof["voie"]
    return {"ids": ids, "prof": out}


RAWS = [
    "",
    "l=" + ",".join(str(i) for i in range(1, 300)),                     # too long a link
    "l=1,2,2,abc,3,4,5,6,7,8,9,10,11,12",                                 # cleaned, at most 10
    "l=1&s=bg&m=b&n=abc&a=MATHS&b=PC",                                    # unreadable average: dropped and said
    "l=1&s=bg&m=b&n=25&a=MATHS&b=PC",
    "l=1&s=bg&m=b&n=7.9&a=MATHS&b=PC",
    "l=1&s=bg&m=zz&n=16.4&a=MATHS&b=PC",                                  # the mention read from the average
    "l=1&s=bg&m=zz&a=MATHS&b=PC",                                         # no readable mention, no average: no profile
    "l=1&s=bg&m=b&a=MATHS&b=MATHS",                                       # the same specialty twice
    "l=1&s=bg&m=b&a=" + "%3Cimg%20src%3Dx%3E" + "&b=PC",
    "l=1&s=bt&m=b&v=" + "%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E",
    "l=1&s=bt&m=b&v=stmg_merc",
    "s=xx&m=b",
    "t=r&s=bg&m=b&n=15",
    "l=1&s=bg&m=b&n=14,56&a=MATHS&b=PC&academie=Lyon&lycee=0690026D",      # a comma average; unknown keys ignored
    "l=&s=&m=",
    "foo=bar",
    "l=1&s=bg&m=b&x=1&a=SES&b=SVT",
]


@check("TF1 round trip: the list and the profile come back, the average included; never the académie, the lycée, the town or « boursier »")
def tf1(c: Ctx):
    o = harness(c, READ_PROG, {"jv": JV, "pairs": PAIRS, "raws": []})
    if o is None:
        return True, "node absent: not run"
    bad = []
    for (ids, prof), link, got in zip(PAIRS, o["links"], o["reads"]):
        want = expected_pair(ids, prof)
        if not link.startswith(ORIGIN + "/#/transfert/"):
            bad.append(("link prefix", link[:60]))
        for word in ("academie", "Lyon", "lycee", "0690026D", "Parc", "boursier", "ville"):
            if word in link:
                bad.append(("the link carries", word, link))
        # a link the page wrote reads without a note, except a bac général stored with no pair (said: none is invented)
        notes = 1 if prof and prof.get("serie") == "bg" and not (prof.get("spe1") and prof.get("spe2")) else 0
        if got is not None and len(got["notes"]) != notes:
            bad.append(("notes on a link the page wrote", ids, got["notes"]))
        if got is None or got["ids"] != want["ids"] or shape(got["prof"]) != want["prof"]:
            bad.append(("round trip", ids, prof and prof.get("serie"), got and shape(got["prof"]), want["prof"]))
    return not bad, f"{len(PAIRS)} lists and profiles; problems {bad[:4]}"


@check("TF2 hostile links against an independent oracle: cap, codes cleaned, unreadable parts dropped and said, nothing defaulted or echoed")
def tf2(c: Ctx):
    o = harness(c, READ_PROG, {"jv": JV, "pairs": [], "raws": RAWS})
    if o is None:
        return True, "node absent: not run"
    bad = []
    for raw, got in zip(RAWS, o["raw"]):
        want = own_read(raw)
        if (got is None) != (want is None):
            bad.append(("read or not", raw[:50], got is None))
            continue
        if got is None:
            continue
        if got["ids"] != want["ids"] or shape(got["prof"]) != want["prof"] or len(got["notes"]) != want["notes"]:
            bad.append((raw[:60], got["ids"], shape(got["prof"]), len(got["notes"]), want))
        if "<img" in json.dumps(got) or "onerror" in json.dumps(got):
            bad.append(("raw text kept", raw[:60]))
    return not bad, f"{len(RAWS)} links; problems {bad[:4]}"


# ------------------------------------------------------------------ TF3
QR_TEXTS = [ORIGIN + "/", ORIGIN + "/#/transfert/l=10%2C100%2C10001&s=bg&m=b&n=14.6&a=MATHS&b=PC",
            ORIGIN + "/#/transfert/l=" + "%2C".join(str(100000000 + i) for i in range(10)) + "&s=bt&m=tbf&n=19.5&v=sti2d_ee",
            "http://127.0.0.1:8765/", "A"]
QR_PROG = r"""
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(D.texts.map((t) => qrMatrix(t))));"""


def py_qr(text: str, version: int, mask):
    import qrcode
    from qrcode.util import MODE_8BIT_BYTE, QRData
    q = qrcode.QRCode(version=version, error_correction=qrcode.constants.ERROR_CORRECT_M, mask_pattern=mask, border=0)
    q.add_data(QRData(text.encode("ascii"), mode=MODE_8BIT_BYTE))
    q.make(fit=False)
    return [[1 if x else 0 for x in row] for row in q.modules]


@check("TF3 the QR code: the vendored encoder's matrix = the Python qrcode package's (smallest version, level M, byte mode)")
def tf3(c: Ctx, js: str | None = None):
    try:
        import qrcode  # noqa: F401
    except ImportError:
        return False, "the Python package qrcode is missing (requirements-pipeline.txt)"
    o = harness(c, QR_PROG, {"texts": QR_TEXTS}, js)
    if o is None:
        return True, "node absent: not run"
    bad = []
    for text, m in zip(QR_TEXTS, o):
        n = len(m)
        v = (n - 17) // 4
        if n != 17 + 4 * v or not 1 <= v <= 40:
            bad.append(("size", text[:30], n))
            continue
        masks = [k for k in range(8) if py_qr(text, v, k) == m]
        if len(masks) != 1:
            bad.append(("no mask of the package gives the same matrix (level, mode or data differ)", text[:40], v))
            continue
        # the mask is the encoder's own choice (both libraries score the 8 masks, with slightly different penalties: any mask
        # reads the same); the version, the level and the data must be exactly the package's
        import qrcode as Q
        auto = Q.QRCode(error_correction=Q.constants.ERROR_CORRECT_M, border=0)
        from qrcode.util import MODE_8BIT_BYTE, QRData
        auto.add_data(QRData(text.encode("ascii"), mode=MODE_8BIT_BYTE))
        auto.make(fit=True)
        if auto.version != v:
            bad.append(("not the smallest version", text[:40], v, auto.version))
    return not bad, f"{len(QR_TEXTS)} texts, versions {[(len(m) - 17) // 4 for m in o]}; problems {bad[:3]}"


# ------------------------------------------------------------------ TF4
APPLY_PROG = r"""
const D = JSON.parse(require('fs').readFileSync(0, 'utf8'));
JV = D.jv;
const res = [];
for (const k of D.cases) {
  for (const x of Object.keys(_ls)) delete _ls[x];
  if (k.list) localStorage.setItem("voeux", JSON.stringify(k.list));
  if (k.local) localStorage.setItem("profile", JSON.stringify(k.local));
  const t = transferRead(k.raw);
  const r = transferApply(t, k.mode);
  res.push({ r, list: voeux.get(), profile: store.get("profile", null) });
}
process.stdout.write(JSON.stringify(res));"""


@check("TF4 installing: replace keeps this device's académie, lycée and « boursier »; add never touches the profile; a second click; the link cleared")
def tf4(c: Ctx, js: str | None = None):
    js = js if js is not None else c.js
    raw = "l=10%2C100&s=bg&m=b&n=14.6&a=MATHS&b=PC"
    many = "l=" + "%2C".join(str(i) for i in range(20, 30))
    cases = [
        {"raw": raw, "mode": "replace", "list": ["1", "2", "3"], "local": {"serie": "bt", "mention": "ab", **LOCAL}},
        {"raw": raw, "mode": "replace"},
        {"raw": raw, "mode": "add", "list": ["1", "10"], "local": {"serie": "bt", "mention": "ab", **LOCAL}},
        {"raw": many, "mode": "add", "list": ["1", "2", "3"]},
        {"raw": "l=10", "mode": "replace", "list": ["1"], "local": {"serie": "bt", "mention": "ab", **LOCAL}},
    ]
    o = harness(c, APPLY_PROG, {"jv": JV, "cases": cases}, js)
    if o is None:
        return True, "node absent: not run"
    bad = []
    a, b, d, e, f = o
    if a["list"] != ["10", "100"] or shape(a["profile"]) != {"serie": "bg", "statut": "terminale", "moyenne": 14.6, "mention": "b", "spe1": "MATHS",
                                                             "spe2": "PC", "maths_expertes": False} \
            or a["profile"].get("academie") != "Lyon" or (a["profile"].get("lycee") or {}).get("uai") != "0690026D" or a["profile"].get("boursier") is not True:
        bad.append(("replace", a))
    if b["list"] != ["10", "100"] or (b["profile"] or {}).get("academie") or (b["profile"] or {}).get("moyenne") != 14.6:
        bad.append(("install on an empty device", b))
    if d["list"] != ["1", "10", "100"] or (d["profile"] or {}).get("serie") != "bt" or d["r"]["profile"]:
        bad.append(("add touches the profile or the list order", d))
    if len(e["list"]) != 10 or e["list"][:3] != ["1", "2", "3"]:
        bad.append(("add beyond ten", e["list"]))
    if f["list"] != ["10"] or (f["profile"] or {}).get("serie") != "bt":
        bad.append(("a link without a profile replaced this device's profile", f))
    view = top(js, "viewTransfert")
    if 'if (replaces) { draw("confirm");' not in view or 'id="tf-yes"' not in view or "finish(transferApply(t, \"replace\"))" not in view:
        bad.append("replacing does not ask a second click")
    if ADD_ONLY.replace('\\"', '"') not in view:
        bad.append("« ajouter seulement les formations » hidden when this device has a profile but no list (Codex)")
    if 'history.replaceState(history.state, "", "#/transfert")' not in view:
        bad.append("the link stays in the address bar after the install")
    if re.search(r"\bapi\(", view.replace('api("/api/journey/vocab")', "")):
        bad.append("the receiving page sends something besides the vocabulary request")
    return not bad, f"{len(cases)} installs; problems {bad[:3]}"


# ------------------------------------------------------------------ TF5
KIT_PROG = r"""process.stdout.write(JSON.stringify({ steps: KIT_STEPS, check: KIT_CHECK }));"""
TU = re.compile(r"\b(tu|ton|ta|tes|toi|t'|te)\b", re.I)


def sentences(text: str):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


@check("TF5 the kit: own words, vouvoiement, no chance, sentences <= 30 words, no figure, internal links, the address as a QR code, the sheet printed apart")
def tf5(c: Ctx, js: str | None = None):
    js = js if js is not None else c.js
    o = harness(c, KIT_PROG, {}, js)
    if o is None:
        return True, "node absent: not run"
    view = top(js, "viewKit")
    text = " . ".join(x for s in o["steps"] for x in s) + " . " + " . ".join(o["check"])
    tpl = re.search(r"\$view\.innerHTML = `([\s\S]*?)`;\n", view)
    visible = re.sub(r"</?(?:h\d|li|p|div|section|button|ol|ul|br)\b[^>]*>", " . ", tpl.group(1) if tpl else "")   # blocks end a sentence
    visible = re.sub(r"<[^>]+>|\$\{[^}]*\}", " ", visible)
    words = visible + " " + text
    bad = []
    if TU.search(re.sub(r"\bt'", "", words)) and TU.search(words).group(0).lower() != "t'":
        bad.append(("tutoiement", TU.search(words).group(0)))
    for m in re.finditer(r"chances?", words):
        ctx = words[max(0, m.start() - 40): m.end()]
        if not re.search(r"jamais|pas des|n'est jamais", ctx):
            bad.append(("a chance not denied", ctx))
    long = [s for s in sentences(re.sub(r"\s+", " ", words)) if len(s.split()) > 30]
    if long:
        bad.append(("a sentence over 30 words", long[0][:80]))
    figures = re.findall(r"\b\d+\b", " ".join(x for s in o["steps"] for x in s[1:]) + " ".join(o["check"]))
    if figures:
        bad.append(("a figure in the kit", figures[:3]))
    if [s[0] for s in o["steps"]] != ["5 min", "10 min", "15 min", "10 min", "10 min", "5 min"]:
        bad.append(("not one hour", [s[0] for s in o["steps"]]))
    for need in ("Mon profil", "Mes vœux", "sécurité", "portes ouvertes", "Transférer sur mon autre appareil", "Partager ou imprimer ma liste"):
        if need.lower() not in text.lower():
            bad.append(("a step missing", need))
    hrefs = re.findall(r'href="([^"]+)"', view)
    if any(not h.startswith("#/") for h in hrefs):
        bad.append(("an external link", hrefs))
    if 'qrSvg(site, "QR code de l\'adresse de SupCompass")' not in view or "const site = `${location.origin}/`;" not in view:
        bad.append("the address as a QR code")
    if 'id="kit-print"' not in view or "window.print()" not in view or ".kit-sheet { break-before: page;" not in c.css:
        bad.append("the students' sheet on its own printed page")
    if re.search(r"\bapi\(", view):
        bad.append("the kit sends a request")
    return not bad, f"{len(o['steps'])} steps, {len(o['check'])} checks; problems {bad[:3]}"


# ------------------------------------------------------------------ TF6
@check("TF6 privacy and credits: the privacy page, the legal credit, the vendored file and its licence, the cards' warnings")
def tf6(c: Ctx, js: str | None = None):
    js = js if js is not None else c.js
    bad = []
    src = re.sub(r"\s+", " ", (ROOT / "suptracker" / "legal.py").read_text())
    if "Transférer sur mon autre appareil" not in src or "moyenne comprise, jamais votre académie, votre lycée ni votre ville" not in src \
            or "il n'est pas envoyé au site et sert à vous seul" not in src:
        bad.append("the privacy page does not say what the transfer link carries")
    if "qrcode-generator de Kazuhiko Arase (licence MIT)" not in src:
        bad.append("the legal page does not credit the QR library")
    lic = (VENDOR.parent / "LICENSE")
    if not lic.exists() or "MIT License" not in lic.read_text() or "Kazuhiko Arase" not in lic.read_text():
        bad.append("the vendored library's licence")
    digest = hashlib.sha256(VENDOR.read_bytes()).hexdigest()
    if digest != VENDOR_SHA:
        bad.append(("the vendored file is not the published 1.4.4", digest[:16]))
    if re.search(r"\beval\(|new Function|document\.write", VENDOR.read_text()):
        bad.append("the vendored library evaluates code")
    card = top(js, "transferCard")
    if "Ce lien est pour vous seul" not in card or "ni votre académie, ni votre lycée, ni votre ville" not in card \
            or "jamais envoyé au serveur" not in card or "Partager ou imprimer ma liste" not in card:
        bad.append("the sender card's warnings")
    prof = top(js, "viewProfil")
    if "Le lien « Transférer sur mon autre appareil » contient votre profil, moyenne comprise : il est pour vous seul." not in prof:
        bad.append("Mon profil does not say it")
    load = top(js, "loadQr")
    if 'el.src = "/static/vendor/qrcode/qrcode.js"' not in load:
        bad.append("the library is not loaded from the site itself")
    return not bad, f"vendor sha256 {digest[:12]}…; problems {bad}"


# ------------------------------------------------------------------ TF7
BROWSER = r"""
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[process.argv.length - 2], codes = JSON.parse(process.argv[process.argv.length - 1]);
  const b = await chromium.launch(); const errs = []; const out = {}; const reqs = [];
  const watch = (p, n) => { p.on('pageerror', (e) => errs.push(n + ': ' + e.message)); p.on('request', (r) => reqs.push(r.url())); };
  for (const [n, vp] of [['wide', { width: 1280, height: 900 }], ['phone', { width: 390, height: 844 }]]) {
    const ctx = await b.newContext({ viewport: vp }); const p = await ctx.newPage(); watch(p, n);
    await p.goto(base + '/');
    await p.evaluate((c) => { localStorage.setItem('voeux', JSON.stringify(c));
      localStorage.setItem('profile', JSON.stringify({ serie: 'bg', spe1: 'MATHS', spe2: 'PC', mention: 'b', moyenne: 14.6, academie: 'Lyon', statut: 'terminale' })); }, codes);
    await p.goto(base + '/#/voeux'); await p.waitForSelector('#tr-url', { timeout: 90000 });
    const link = await p.inputValue('#tr-url');
    await p.click('#tr-qr'); await p.waitForSelector('#tr-qrbox svg', { timeout: 30000 }).catch(() => {});
    const qr = await p.evaluate(() => !!document.querySelector('#tr-qrbox svg path'));
    const scroll1 = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    await p.goto(base + '/#/profil'); await p.waitForSelector('#pf', { timeout: 60000 });
    const inProfil = await p.evaluate(() => !!document.getElementById('tr-url') && document.getElementById('tr-url').value.length > 0);
    // a fresh device: installed at once
    const c2 = await b.newContext({ viewport: vp }); const q = await c2.newPage(); watch(q, n + '-new');
    await q.goto(link); await q.waitForSelector('#tf-install', { timeout: 60000 });
    await q.click('#tf-install'); await q.waitForSelector('.info[role=status]', { timeout: 10000 }).catch(() => {});
    const fresh = await q.evaluate(() => ({ v: localStorage.getItem('voeux'), p: JSON.parse(localStorage.getItem('profile') || 'null'), h: location.hash }));
    // a device with its own data: a second click, its académie kept
    const c3 = await b.newContext({ viewport: vp }); const r = await c3.newPage(); watch(r, n + '-busy');
    await r.goto(base + '/');
    await r.evaluate(() => { localStorage.setItem('voeux', JSON.stringify(['1'])); localStorage.setItem('profile', JSON.stringify({ serie: 'bt', mention: 'ab', academie: 'Nantes', statut: 'terminale' })); });
    await r.goto(link); await r.waitForSelector('#tf-install', { timeout: 60000 });
    await r.click('#tf-install');
    const asked = await r.evaluate(() => !!document.getElementById('tf-yes') && JSON.parse(localStorage.getItem('voeux'))[0] === '1');
    await r.click('#tf-yes'); await r.waitForSelector('.info[role=status]', { timeout: 10000 }).catch(() => {});
    const busy = await r.evaluate(() => ({ v: localStorage.getItem('voeux'), p: JSON.parse(localStorage.getItem('profile') || 'null'), h: location.hash }));
    const scroll2 = await r.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    await r.goto(base + '/#/kit'); await r.waitForSelector('#kit-qr svg', { timeout: 30000 }).catch(() => {});
    const kit = await r.evaluate(() => ({ h1: (document.querySelector('h1') || {}).textContent || '', qr: !!document.querySelector('#kit-qr svg path'),
      scroll: document.documentElement.scrollWidth > document.documentElement.clientWidth }));
    out[n] = { link, qr, inProfil, fresh, asked, busy, kit, scroll: scroll1 || scroll2 };
    await ctx.close(); await c2.close(); await c3.close();
  }
  out.errs = errs; out.leak = reqs.filter((u) => /14\.6|moyenne|transfert|MATHS%2CPC|n=14/.test(u) && !/vendor\/qrcode/.test(u));
  out.vendor = reqs.filter((u) => /qrcode\.js/.test(u)).map((u) => new URL(u).pathname);
  process.stdout.write(JSON.stringify(out)); await b.close();
})();
"""


@check("TF7 browser: sender card and QR, install on a fresh device, replace after a second click, link cleared, nothing sent, the kit, 0 JS error")
def tf7(c: Ctx):
    if not c.browser:
        return True, "skipped (run with --browser or --real)"
    exe = shutil.which("node")
    if not exe or nodefile.run([exe, "-e", "require('playwright')"], capture_output=True, cwd=str(ROOT)).returncode:
        return True, "skipped (node or playwright not installed)"
    import duckdb
    con = duckdb.connect(str(c.db), read_only=True)
    codes = [r[0] for r in con.execute("""SELECT cod_aff_form FROM core.formation_year WHERE session = (SELECT max(session)
        FROM core.formation_year) ORDER BY cod_aff_form LIMIT 3""").fetchall()]
    con.close()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "SUPTRACKER_ANALYTICS_DIR": tempfile.mkdtemp(), "SUPTRACKER_DB": str(c.db)}
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "suptracker.api:app", "--port", str(port)], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(8)
        r = nodefile.run([exe, "-e", BROWSER, f"http://127.0.0.1:{port}", json.dumps(codes)], capture_output=True, text=True,
                         timeout=600, cwd=str(ROOT))
    finally:
        srv.terminate()
    if r.returncode:
        return False, r.stderr[-500:]
    o = json.loads(r.stdout)
    bad = []
    for n in ("wide", "phone"):
        x = o[n]
        if "#/transfert/" not in x["link"] or "n=14.6" not in x["link"] or "Lyon" in x["link"] or not x["qr"] or not x["inProfil"]:
            bad.append((n, "the sender side", x["link"][-60:], x["qr"], x["inProfil"]))
        f = x["fresh"]
        if json.loads(f["v"] or "[]") != codes or (f["p"] or {}).get("moyenne") != 14.6 or f["h"] != "#/transfert":
            bad.append((n, "install on a fresh device", f))
        bz = x["busy"]
        if not x["asked"] or json.loads(bz["v"] or "[]") != codes or (bz["p"] or {}).get("academie") != "Nantes" or (bz["p"] or {}).get("serie") != "bg" \
                or bz["h"] != "#/transfert":
            bad.append((n, "replace after a second click", x["asked"], bz))
        if "Kit pour une séance en classe" not in x["kit"]["h1"] or not x["kit"]["qr"] or x["kit"]["scroll"] or x["scroll"]:
            bad.append((n, "the kit or a horizontal scroll", x["kit"], x["scroll"]))
    if o["leak"]:
        bad.append(("a request carries the link's content", o["leak"][:2]))
    if any(v != "/static/vendor/qrcode/qrcode.js" for v in o["vendor"]) or not o["vendor"]:
        bad.append(("the QR library's origin", o["vendor"]))
    if o["errs"]:
        bad.append(("JS errors", o["errs"][:2]))
    return not bad, f"codes {codes}; problems {bad}"


# ------------------------------------------------------------------ TF8
@check("TF8 wiring and docs: routes, tabs, audience names, both Mes vœux views, Mon profil, the adults' page, nightly suite, tests, docs")
def tf8(c: Ctx):
    js, bad = c.js, []
    if 'if (a === "transfert") return await viewTransfert(b || "");' not in js or 'if (a === "kit") return await viewKit();' not in js:
        bad.append("routes")
    if 'transfert: "voeux", kit: "accompagner" };' not in js or 'transfert: "transfert", kit: "kit" };' not in js:
        bad.append("tab or audience name")
    if js.count("${transferCard()}${nextSteps(\"voeux\")}") != 2 or js.count("  bindTransfer();") != 2:
        bad.append("the card in both Mes vœux views")
    if "${has ? transferCard() : \"\"}" not in top(js, "viewProfil") or "if (has) bindTransfer();" not in top(js, "viewProfil"):
        bad.append("the card in Mon profil")
    if '<a href="#/kit">kit pour une séance en classe</a>' not in top(js, "viewAccompagner"):
        bad.append("the adults' page links the kit")
    from suptracker import analytics as AN
    if "transfert" not in AN.ROUTES or "kit" not in AN.ROUTES:
        bad.append("closed audience routes")
    if '"transfert": ("TF7",)' not in (ROOT / "scripts" / "browser_nightly.py").read_text():
        bad.append("nightly suite")
    if not (ROOT / "tests" / "test_transfert.py").exists() or '"tests/test_transfert.py"' not in (ROOT / "tests" / "durations.json").read_text():
        bad.append("test file / CI duration")
    if not re.search(r"^qrcode==", (ROOT / "requirements-pipeline.txt").read_text(), re.M):
        bad.append("the Python qrcode package in requirements-pipeline.txt")
    if "qrcode" in (ROOT / "requirements.txt").read_text():
        bad.append("the oracle package shipped to Vercel")
    if "## Transférer ma liste sur un autre appareil et kit pour la classe (owner, 2026-11-27, PR 17)" not in (ROOT / "README.md").read_text():
        bad.append("README section")
    if "**Transfert vers un autre appareil et kit enseignant (owner, 2026-11-27, PR 17).**" not in (REPO / "CLAUDE.md").read_text():
        bad.append("CLAUDE.md rule")
    return not bad, f"problems {bad}"


# ------------------------------------------------------------------ TF9
MUTANTS = [
    ("TF1", "the académie in the link", '    if (isReo(prof)) q.set("t", "r");\n    else {', '    if (prof.academie) q.set("c", prof.academie);\n    if (isReo(prof)) q.set("t", "r");\n    else {'),
    ("TF1", "the average left out", '      if (p.moyenne !== null) q.set("n", String(p.moyenne));\n', ""),
    ("TF1", "a default pair invented", '        if (p.spe1 && p.spe2) { q.set("a", p.spe1); q.set("b", p.spe2); }', '        q.set("a", p.spe1 || "MATHS"); q.set("b", p.spe2 || "SES");'),
    ("TF1", "« autre » travels", '      } else if (p.voie && p.voie !== "autre") q.set("v", p.voie);         // « autre »', '      } else if (p.voie) q.set("v", p.voie);         // « autre »'),
    ("TF2", "an unreadable average kept", "      if (m !== null) out.moyenne = m; else notes.push(", "      out.moyenne = Number(p.moyenne); if (m === null) notes.push("),
    ("TF2", "the codes not cleaned", '  const ids = shareCodes(q.get("l") || "");', '  const ids = (q.get("l") || "").split(",").filter(Boolean);'),
    ("TF2", "no length cap", "  if (!s || s.length > TRANSFER_MAX) return null;", "  if (!s) return null;"),
    ("TF2", "a default mention", '  else if (["bg", "bt", "bp"].includes(p.serie) && (MENTION_CODES.includes(p.mention) || validMoyenne(p.moyenne) !== null)) {',
     '  else if (["bg", "bt", "bp"].includes(p.serie)) {'),
    ("TF2", "an unread route said nothing", '      else notes.push("La voie du bac du lien n\'a pas pu être lue : choisissez-la dans « Mon profil ».");\n', ""),
    ("TF3", "level L", '  const qr = qrcode(0, "M");', '  const qr = qrcode(0, "L");'),
    ("TF2", "a pairless bac général profile installed", '        return ids.length ? { ids, prof: null, notes } : null;\n      }\n      out.spe1 = p.spe1;',
     '      } else {\n      out.spe1 = p.spe1; }'),
    ("TF4", "add-only hidden for a profile without a list", "${t.ids.length && (mine.length || hasLocal) ? '<button", "${t.ids.length && mine.length ? '<button"),
    ("TF4", "this device's académie lost", '  for (const k of ["academie", "lycee", "boursier"])', '  for (const k of [])'),
    ("TF4", "add replaces the profile", "    for (const c of t.ids) if (voeux.add(c)) n++;\n    return { list: n, profile: false };",
     "    for (const c of t.ids) if (voeux.add(c)) n++;\n    if (t.prof) store.set(\"profile\", t.prof);\n    return { list: n, profile: false };"),
    ("TF4", "a link without a profile erases this one", '  if (t.prof) store.set("profile", transferProfile(t.prof, store.get("profile", null)));',
     '  store.set("profile", t.prof ? transferProfile(t.prof, store.get("profile", null)) : null);'),
    ("TF4", "no second click", '    if (inst) inst.onclick = () => { if (replaces) { draw("confirm");', '    if (inst) inst.onclick = () => { if (false) { draw("confirm");'),
    ("TF4", "the link kept in the address bar", '      try { history.replaceState(history.state, "", "#/transfert"); } catch (_) { /* old browser */ }\n', ""),
    ("TF5", "a chance promised", '"SupCompass lit les chiffres officiels de Parcoursup. Il montre où se situaient les admis des années passées : des repères, jamais des chances d\'admission. Il ne crée pas de compte."',
     '"SupCompass lit les chiffres officiels de Parcoursup. Il donne vos chances d\'admission. Il ne crée pas de compte."'),
    ("TF5", "tutoiement", '"Mon profil est rempli"', '"Ton profil est rempli"'),
    ("TF6", "the warning dropped", "<strong>Ce lien est pour vous seul</strong>", "<strong>Ce lien</strong>"),
]


@check("TF9 mutation test: every seeded bug is caught by TF1-TF6")
def tf9(c: Ctx):
    by = {fn.check_name.split()[0]: fn for fn in CHECKS}
    base = [k for k in ("TF1", "TF2", "TF3", "TF4", "TF5", "TF6") if not by[k](c)[0]]
    if base:
        return False, f"the unmutated code fails {base}"
    missed = []
    for target, name, old, new in MUTANTS:
        if c.js.count(old) != 1:
            missed.append(f"{name} (anchor {c.js.count(old)})")
            continue
        m = copy.copy(c)
        m.js = c.js.replace(old, new, 1)
        try:
            ok = by[target](m)[0]
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            missed.append(name)
    return not missed, f"{len(MUTANTS) - len(missed)}/{len(MUTANTS)} caught; missed {missed}"


VENDOR_SHA = "18ae399f81182bc9de916e9c77b195df20cc58d6f2d55a62b085a299f1bf1780"   # sha256 of qrcode.js in the npm tarball qrcode-generator 1.4.4


def run(db: Path, real: bool = False, browser: bool = False, checks: set | None = None) -> list[dict]:
    c = Ctx(db, real, browser)
    out = []
    for fn in CHECKS:
        if checks and fn.check_name.split()[0] not in checks:
            continue
        t0 = time.time()
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": f"{detail} ({time.time() - t0:.1f} s)"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "suptracker.duckdb"))
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--browser", action="store_true")
    a = ap.parse_args(argv)
    res = run(Path(a.db), a.real, a.browser or a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"] + "\n       " + str(r["detail"])[:1500])
    print(f"\n{sum(r['ok'] for r in res)}/{len(res)} checks passed")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
