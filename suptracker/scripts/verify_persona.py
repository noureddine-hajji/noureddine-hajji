"""Calibration & verification of the profile -> programme journey on a persona.

Persona: doublette Mathématiques + SES, expected mention Assez bien.

Stage 1   CPGE ECG, Licence économie-gestion, AES, Droit and BUT Service (GEA/TC) pass the
          gate (prédilection or accessible); CPGE S, the type that contains MPSI and
          PCSI, is atypique. The national baseline equals the deduplicated
          "Ensemble des bacheliers" row, recomputed here straight from core.specialites.
Stage 2   CPGE ECG is stratified: its most selective classes sit in ambitieux /
          hors-profil, the accessible ones in cible / sécurité, and the selective half has
          a lower CDF than the accessible half. Licence économie-gestion is mostly cible /
          sécurité.
Maths     For every formation of the checked types: CDF recomputed independently from
          core.formation_year; 0 <= CDF <= 1; Wilson interval brackets it; exact-mention
          share <= CDF; CDF monotone in the mention ladder; zone recomputed from the rules.
No ecological inference: Stage-2 indicators are identical for two different doublettes
          (only the calling group may differ), so Stage 2 never multiplies the national
          doublette table into establishment figures; no output field is a probability.

    python scripts/verify_persona.py --db data/suptracker.duckdb --out data/verification [--strict]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from suptracker import config  # noqa: E402
from suptracker import journey as J  # noqa: E402

PERSONA = {"doublette": "MATHS+SES", "mention": "ab"}
MUST_PASS = ["CPGE ECG", "Licence Pluri Sciences économiques - Gestion", "Licence AES",
             "Licence Sciences juridiques", "BUT Service"]
MUST_FILTER = ["CPGE S"]
STRATIFY = "CPGE ECG"
MOSTLY_ACCESSIBLE = "Licence Pluri Sciences économiques - Gestion"


class Report:
    def __init__(self):
        self.checks: list[dict] = []

    def check(self, name: str, ok: bool, detail="") -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return ok

    @property
    def passed(self) -> bool:
        return all(c["ok"] for c in self.checks)


def _independent_cdf(con, cod: str, mention: str) -> tuple[float, float]:
    """Pooled lineage CDF recomputed without going through journey.stage2."""
    upto = J.MENTIONS[: J.MENTIONS.index(mention) + 1]
    k_expr = " + ".join(f"coalesce(acc_{m}, 0)" for m in upto)
    n_expr = " + ".join(f"coalesce(acc_{m}, 0)" for m in J.MENTIONS)
    k, n = con.execute(f"""
      SELECT sum({k_expr}), sum({n_expr}) FROM core.formation_year
      WHERE (session, cod_aff_form) IN (
        SELECT (session, cod_aff_form) FROM core.lineage WHERE lineage_id =
          (SELECT lineage_id FROM core.lineage WHERE cod_aff_form = ?
           AND session = (SELECT max(session) FROM core.formation_year)))""", [cod]).fetchone()
    return float(k or 0), float(n or 0)


def run(con, persona=PERSONA) -> Report:
    rep = Report()
    d, m = persona["doublette"], persona["mention"]
    s1 = J.stage1(con, d)
    by = {f["type_key"]: f for f in s1["filieres"]}

    # ---- Stage 1
    for t in MUST_PASS:
        f = by.get(J.type_key(t))
        rep.check(f"stage1 gate passes: {t}", f is not None and f["gate"] in ("predilection", "accessible"),
                  f and {k: f[k] for k in ("gate", "share", "lift", "offer_rate")})
    for t in MUST_FILTER:
        f = by.get(J.type_key(t))
        rep.check(f"stage1 filtered: {t}", f is not None and f["gate"] == "atypique",
                  f and {k: f[k] for k in ("gate", "share", "lift")})
    cs = con.execute("""SELECT fil_lib_voe_acc, count(*) FROM core.taxonomy_link t JOIN core.taxonomy_rule r
                        USING (rule_id) JOIN core.formation_year fy USING (session, cod_aff_form)
                        WHERE r.spe_type = 'CPGE S' AND fy.fil_lib_voe_acc IN ('MPSI', 'PCSI')
                        GROUP BY 1""").fetchall()
    rep.check("taxonomy: MPSI and PCSI belong to the filtered CPGE S type", len(cs) == 2, dict(cs))
    raw = con.execute("""SELECT sum(s.n_voeux), sum(s.n_accepte) FROM core.specialites s
        JOIN core.spe_doublette d USING (doublette)
        WHERE d.doublette_key = ? AND coalesce(s.aggregation_level, '0') = '0'
          AND s.formation_type = 'Ensemble des bacheliers'""", [d]).fetchone()
    nat = s1["national"]
    rep.check("stage1 national baseline = deduplicated 'Ensemble des bacheliers' row",
              raw[0] == nat["candidates"] and raw[1] == nat["accepted"], {"raw": raw, "api": nat})
    shares_ok = all(0 <= (f["share"] or 0) <= 1 and 0 <= (f["offer_rate"] or 0) <= 1 for f in s1["filieres"])
    rep.check("stage1 shares and offer rates within [0, 1]", shares_ok)

    # ---- Stage 2
    def s2(t, dk=d, mm=m):
        return J.stage2(con, dk, mm, J.type_key(t))["formations"]

    ecg = [f for f in s2(STRATIFY) if f["zone"] != "non_ouvert" and f["taux_acces_ens"] is not None]
    if rep.check(f"stage2 {STRATIFY}: formations found", len(ecg) >= 4, len(ecg)):
        by_sel = sorted(ecg, key=lambda f: f["taux_acces_ens"])
        half = len(by_sel) // 2
        sel, acc = by_sel[:half], by_sel[half:]
        med_sel = statistics.median(f["cdf"] for f in sel if f["cdf"] is not None)
        med_acc = statistics.median(f["cdf"] for f in acc if f["cdf"] is not None)
        rep.check(f"stage2 {STRATIFY}: selective half has a lower CDF than the accessible half",
                  med_sel < med_acc, {"median_cdf_selective": med_sel, "median_cdf_accessible": med_acc})
        top = by_sel[: max(1, len(by_sel) // 10)]
        rep.check(f"stage2 {STRATIFY}: most selective decile is ambitieux / hors-profil",
                  all(f["zone"] in ("ambitieux", "hors_profil") for f in top),
                  [(f["etablissement"], f["taux_acces_ens"], f["zone"]) for f in top[:5]])
        rep.check(f"stage2 {STRATIFY}: some classes are cible / sécurité",
                  any(f["zone"] in ("cible", "securite") for f in ecg))
    eg = [f for f in s2(MOSTLY_ACCESSIBLE) if f["zone"] != "non_ouvert"]
    frac = sum(f["zone"] in ("cible", "securite") for f in eg) / len(eg) if eg else 0
    rep.check(f"stage2 {MOSTLY_ACCESSIBLE}: majority cible / sécurité", frac > 0.5, round(frac, 3))

    # ---- maths invariants (every formation of the checked types)
    bad = []
    for t in MUST_PASS:
        rows = {f["cod_aff_form"]: f for f in s2(t)}
        ladder = {mm: {f["cod_aff_form"]: f["cdf"] for f in s2(t, mm=mm)} for mm in J.MENTIONS[:4]}
        for cod, f in rows.items():
            k, n = _independent_cdf(con, cod, m)
            ref = k / n if n else None
            lo, hi = f["cdf_ci"]
            probs = []
            if (ref is None) != (f["cdf"] is None) or (ref is not None and abs(ref - f["cdf"]) > 1e-12):
                probs.append(f"cdf {f['cdf']} != independent {ref}")
            if f["cdf"] is not None:
                if not 0 <= f["cdf"] <= 1:
                    probs.append("cdf outside [0,1]")
                if not (lo - 1e-12 <= f["cdf"] <= hi + 1e-12):
                    probs.append("Wilson interval does not bracket cdf")
                if f["exact_share"] is not None and f["exact_share"] > f["cdf"] + 1e-12:
                    probs.append("exact share > cdf")
                seq = [ladder[mm].get(cod) for mm in J.MENTIONS[:4]]
                if any(a is not None and b is not None and a > b + 1e-12 for a, b in zip(seq, seq[1:])):
                    probs.append(f"cdf not monotone in mention: {seq}")
                if f["zone"] != "non_ouvert":
                    expect = J.classify_zone(f["taux_acces_ens"], f["cdf"], lo, hi)["zone"]
                    if expect != f["zone"]:
                        probs.append(f"zone {f['zone']} != rules {expect}")
            if probs:
                bad.append({"cod_aff_form": cod, "type": t, "problems": probs})
    rep.check("maths invariants on every formation of the checked types", not bad, bad[:10])

    # ---- no ecological inference
    keys = ("cdf", "cdf_ci", "exact_share", "taux_acces_ens", "pct_bg", "pct_boursiers", "zone")
    a = {f["cod_aff_form"]: tuple(json.dumps(f[k]) for k in keys) for f in s2(STRATIFY)}
    b = {f["cod_aff_form"]: tuple(json.dumps(f[k]) for k in keys) for f in s2(STRATIFY, dk="HGGSP+LLCER")}
    rep.check("stage2 indicators do not depend on the national doublette table", a == b)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    fields = set(walk(s1)) | set(walk(J.stage2(con, d, m, J.type_key(STRATIFY))))
    rep.check("no output field is an admission probability", not any("prob" in k.lower() for k in fields),
              sorted(k for k in fields if "prob" in k.lower()))
    return rep


def render(rep: Report) -> str:
    L = [f"# Persona verification: Mathématiques + SES, mention Assez bien ({rep.generated_at})", "",
         "| check | result | detail |", "|---|---|---|"]
    for c in rep.checks:
        det = json.dumps(c["detail"], ensure_ascii=False, default=str)
        L.append(f"| {c['check']} | {'pass' if c['ok'] else 'FAIL'} | {det[:300]} |")
    L += ["", f"**Overall: {'PASS' if rep.passed else 'FAIL'}**", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--out", type=Path, default=config.DB_PATH.parent / "verification")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    con = duckdb.connect(str(a.db), read_only=True)
    rep = run(con)
    rep.generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "persona.json").write_text(json.dumps(
        {"generated_at": rep.generated_at, "persona": PERSONA, "overall": "PASS" if rep.passed else "FAIL",
         "checks": rep.checks}, indent=2, ensure_ascii=False, default=str))
    md = render(rep)
    (a.out / "persona.md").write_text(md)
    print(md)
    return 1 if a.strict and not rep.passed else 0


if __name__ == "__main__":
    sys.exit(main())
