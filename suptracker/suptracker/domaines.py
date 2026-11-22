"""Owner, 2026-11-21: the search filter groups the professional titles (the cartographie's « FP - … » offers, type « Formation
professionnelle ») by their OFFICIAL domain instead of one entry per title (134 entries, 76 with one or two formations).

The domain is the NSF code (nomenclature des spécialités de formation) printed by the RNCP fiches (France Compétences export,
data/rncp, fetched by the suptracker-rncp workflow) of the SAME title (`robustesse_formation.cert_title` / `cert_key`, format only,
never fuzzy). One fixed rule, read at build into core.fp_domaine:
  - the ACTIVE fiches of the title, else all its fiches (a title keeps its domain when its fiche expires);
  - their NSF groups (3 digits, the letter suffix « 312t » dropped): ONE group = that group;
  - several groups of ONE sub-domain (2 digits: 230, 232, 233) = the sub-domain's own plurivalent code (« 230 : Spécialités
    pluritechnologiques génie civil, construction, bois »), when the export prints it;
  - otherwise no domain: « plusieurs domaines » (groups of several sub-domains) or « sans fiche » (no fiche, or no NSF code).
Labels are the export's own (« 312 : Commerce, vente » shown « Commerce, vente »). Each formation keeps its own title; only the
filter's group changes. Never a figure."""
from __future__ import annotations

import re
from pathlib import Path

from . import robustesse_formation as RF

DIR = RF.DIR
SEVERAL, NONE = "Autres titres : plusieurs domaines", "Autres titres : domaine non publié"
TYPE = "Formation professionnelle"


def read(path: Path) -> tuple[dict, dict, dict]:
    """({fiche: (title key, active)}, {fiche: {NSF codes}}, {3-digit code: label})."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        fiches = {r["Numero_Fiche"]: (RF.cert_key(r["Intitule"]), r["Actif"] == "ACTIVE") for r in RF._csv(z, "_Standard_")}
        nsf: dict = {}
        labels: dict = {}
        for r in RF._csv(z, "_Nsf_"):
            code = (r.get("Nsf_Code") or "").strip()
            if not code:
                continue
            nsf.setdefault(r["Numero_Fiche"], set()).add(code)
            if re.fullmatch(r"\d{3}", code):
                labels[code] = re.sub(r"^\s*\d{3}\s*:\s*", "", r.get("Nsf_Intitule") or "").strip()
    return fiches, nsf, labels


def domain(key: str | None, by_key: dict, fiches: dict, nsf: dict, labels: dict) -> tuple[str | None, str | None, str]:
    """(NSF code, label, rule) of a title key: rule « nsf », « nsf_plurivalent », « plusieurs_domaines » or « sans_fiche »."""
    fs = by_key.get(key or "", [])
    use = [f for f in fs if fiches[f][1]] or fs
    groups = {c[:3] for f in use for c in nsf.get(f, ()) if re.match(r"\d{3}", c)}
    if not groups:
        return None, None, "sans_fiche"
    if len(groups) == 1:
        g = next(iter(groups))
        return (g, labels[g], "nsf") if labels.get(g) else (None, None, "sans_fiche")
    subs = {g[:2] for g in groups}
    if len(subs) == 1 and labels.get(next(iter(subs)) + "0"):
        g = next(iter(subs)) + "0"
        return g, labels[g], "nsf_plurivalent"
    return None, None, "plusieurs_domaines"


def build(con, path: Path | None = None) -> int:
    """core.fp_domaine (mention, nsf, domaine, regle) for every « FP - … » mention of the latest cartographie session."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("CREATE OR REPLACE TABLE core.fp_domaine (mention VARCHAR, nsf VARCHAR, domaine VARCHAR, regle VARCHAR)")
    path = path or DIR / RF.RNCP_ZIP
    has = con.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema = 'core'
                         AND table_name = 'cartographie' AND column_name = 'mention_lib'""").fetchone()[0]
    if not path.exists() or not has:
        return 0
    fiches, nsf, labels = read(path)
    by_key: dict = {}
    for f, (k, _) in fiches.items():
        by_key.setdefault(k, []).append(f)
    mentions = sorted({m for (m,) in con.execute("""SELECT DISTINCT mention_lib FROM core.cartographie
            WHERE carto_session = (SELECT max(carto_session) FROM core.cartographie) AND mention_lib IS NOT NULL""").fetchall()
                       if RF.cert_title(m)})
    rows = []
    for m in mentions:
        code, label, rule = domain(RF.cert_title(m), by_key, fiches, nsf, labels)
        rows.append((m, code, label or (SEVERAL if rule == "plusieurs_domaines" else NONE), rule))
    if rows:
        con.executemany("INSERT INTO core.fp_domaine VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def groups(con) -> dict:
    """{mention: domain label} from core.fp_domaine (empty when the table is absent)."""
    if not con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'
                          AND table_name = 'fp_domaine'""").fetchone()[0]:
        return {}
    return {" ".join(m.split()): d for m, d in con.execute("SELECT mention, domaine FROM core.fp_domaine").fetchall()}
