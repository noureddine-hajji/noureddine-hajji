"""Sprint 14 follow-up: short-term context, France Travail's "Besoins en main-d'œuvre" survey (BMO) 2026 and 2025.

What BMO is: the employers' declared hiring INTENTIONS for the year (a "projet de recrutement"), not job offers, not
hires, not jobs created; "difficile" is the employer's own expectation. It says nothing about 2030 (sprint 14's
projections do) nor about AI.

What we read: the owner's workbook keeps France Travail's open-data base at its finest level (job × employment area
× local committee, sheets Bassins_2026 / Bassins_2025, with "*" where France Travail masks a value below 5). The France
totals are re-summed HERE from those cells, not taken from the workbook's own France sheet (red team B1 compares
both). Masked cells count as 0, so every total is a FLOOR ("au moins"): about 2.24 million published 2026 projects
against the ~2.3 million France Travail announces. A share (difficult, seasonal) is published-cells over
published-cells; its maximal error if every masked cell were 4 is computed per job and a share is flagged "fragile"
beyond 5 points.

The 217 job codes are FAP-2021 at the 228 level, labels identical to the Dares nomenclature: a job reaches them
through its official FAP-2021 families (sprint 13), every family shown when it depends on the qualification of the
post. The workbook's FAP -> ISCO "expert" crosswalk and its tension classes are not used. 2025 is kept in the table
but not compared on the page: in 2026 France Travail splits areas into local committees, more cells are masked, so the
2026 floors fall for that reason alone.
"""
from __future__ import annotations

from pathlib import Path

from . import config

SOURCE_GLOB = "BMO_*.xlsx"
SHEETS = {2026: "Bassins_2026", 2025: "Bassins_2025"}
MASK_MAX = 4                      # France Travail masks values below 5
FRAGILE_POINTS = 5.0


def source_path(data_dir: Path | None = None) -> Path | None:
    files = sorted((data_dir or config.DATA_DIR / "sources").glob(SOURCE_GLOB))
    return files[-1] if files else None


def read_year(path: Path, year: int):
    """Per BMO code: published sums and masked-cell counts of projects, difficult and seasonal projects."""
    import pandas as pd
    df = pd.read_excel(path, sheet_name=SHEETS[year], header=2, dtype=str)
    cols = {"projets": f"Projets {year}", "difficiles": f"dont difficiles {year}", "saisonniers": f"dont saisonniers {year}"}
    out = pd.DataFrame({"code": df["Code métier BMO"].str.strip(), "libelle": df["Métier BMO"].str.strip()})
    for k, c in cols.items():
        v = df[c].str.strip()
        out[k] = pd.to_numeric(v.where(v != "*"), errors="coerce").fillna(0)
        out[f"masques_{k}"] = (v == "*").astype(int)
    out["cellules"] = 1
    g = out.groupby(["code", "libelle"], as_index=False).sum(numeric_only=True)
    g.insert(0, "annee", year)
    return g


def share_bounds(part: float, whole: float, masked_part: int, masked_whole: int) -> tuple[float | None, float | None, float | None]:
    """(share, low, high): published share and its extremes if each masked cell held between 0 and MASK_MAX."""
    if not whole:
        return None, None, None
    s = part / whole
    lo = part / (whole + MASK_MAX * masked_whole)
    hi = min(1.0, (part + MASK_MAX * masked_part) / whole)
    return s, lo, hi


def build(con, path: Path | None = None) -> dict:
    """core.bmo_metier (one row per code and year); without the workbook the table exists and stays empty."""
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("""CREATE OR REPLACE TABLE core.bmo_metier (annee INTEGER, code VARCHAR, libelle VARCHAR, projets DOUBLE,
        masques_projets INTEGER, difficiles DOUBLE, masques_difficiles INTEGER, saisonniers DOUBLE, masques_saisonniers INTEGER,
        cellules INTEGER)""")
    if path is None or not Path(path).exists():
        return {"codes": 0}
    import pandas as pd
    frame = pd.concat([read_year(Path(path), y) for y in SHEETS], ignore_index=True)
    frame = frame[["annee", "code", "libelle", "projets", "masques_projets", "difficiles", "masques_difficiles",
                   "saisonniers", "masques_saisonniers", "cellules"]]
    con.register("_bmo", frame)
    con.execute("INSERT INTO core.bmo_metier SELECT * FROM _bmo")
    con.unregister("_bmo")
    return {"codes": int(frame[frame.annee == 2026].code.nunique()), "projets_2026": float(frame[frame.annee == 2026].projets.sum())}


# ------------------------------------------------------------------------- serving
def _has(con) -> bool:
    return bool(con.execute("""SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core'
                               AND table_name = 'bmo_metier'""").fetchone()[0])


def national(con, year: int = 2026) -> dict | None:
    r = con.execute("""SELECT sum(projets), sum(difficiles), sum(saisonniers) FROM core.bmo_metier WHERE annee = ?""", [year]).fetchone()
    if not r or not r[0]:
        return None
    return {"projets": r[0], "part_difficile": r[1] / r[0], "part_saisonniere": r[2] / r[0]}


def for_codes(con, codes: list[dict]) -> dict | None:
    """BMO rows of the job's FAP-2021 families (sprint 13 answer), one per FAP-228 code."""
    if not codes or not _has(con):
        return None
    fams = {}
    for c in codes:
        for f in c.get("fap2021", []):
            r = con.execute("SELECT fap228, lib228 FROM core.nomen_fap2021 WHERE fap341 = ?", [f["code"]]).fetchone()
            if not r:
                continue
            e = fams.setdefault(r[0], {"code": r[0], "q": set(), "origine": set()})
            e["q"] |= set(f["qualifications"]["codes"])
            e["origine"].add(c.get("origine", "onisep"))
    if not fams:
        return None
    rows = {}
    for year, code, lib, p, mp, d, md, s, ms in con.execute(
            f"""SELECT annee, code, libelle, projets, masques_projets, difficiles, masques_difficiles, saisonniers, masques_saisonniers
                FROM core.bmo_metier WHERE code IN ({", ".join("?" * len(fams))})""", list(fams)).fetchall():
        rows[(code, year)] = (lib, p, mp, d, md, s, ms)
    out = []
    for code, e in sorted(fams.items()):
        cur, prev = rows.get((code, 2026)), rows.get((code, 2025))
        base = {"code": code, "toutes_qualifications": len(e["q"]) == 10, "origine": sorted(e["origine"])}
        if not cur:
            out.append({**base, "absent": True})
            continue
        lib, p, mp, d, md, s, ms = cur
        sd, lod, hid = share_bounds(d, p, md, mp)
        ss, los, his = share_bounds(s, p, ms, mp)
        marge = None if sd is None else max(sd - lod, hid - sd) * 100
        out.append({**base, "absent": False, "libelle": lib, "projets": p, "cellules_masquees": mp,
                    "part_difficile": sd, "part_saisonniere": ss, "marge_points": marge,
                    "fragile": marge is not None and marge > FRAGILE_POINTS,
                    "projets_2025": prev[1] if prev else None})
    return {"annee": 2026, "familles": out, "national": national(con, 2026)}
