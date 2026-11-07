"""Red team of the Céreq card (does the job match the training? Génération 2017, national, by highest diploma).

    python scripts/redteam_cereq.py [--db data/suptracker.duckdb] [--real]

The workbook is re-read independently, its identities are re-checked, the link of every formation of the
latest campaign is re-derived with the red team's own rules, the API and the page are checked, and a
mutation test seeds bugs (wrong NSF digits, industrial/tertiary swapped, BUT given the old DUT figures,
licence discipline ignored, horizons swapped, a neighbouring column read, UI wording and escaping...)
that must each be caught.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suptracker import cereq as CQ  # noqa: E402
from suptracker.insertion import bts_key  # noqa: E402

APP_JS = ROOT / "suptracker" / "static" / "app.js"
CHECKS = []
REF_IND = ("eff_pond_g1", "pct_col", "taux_emploi", "part_chomage", "part_autre", "taux_chomage", "taux_edi", "part_tps_partiel",
           "revenu_travail", "pos_cadres", "pos_prof_int", "pos_emp_ouv_q", "pos_emp_ouv_nq", "pos_autres",
           "correspondance_ok", "competence_ok")
HIERARCHY = {100: (200, 300, 400, 500), 300: (310, 320, 330, 340), 400: (410, 420, 430, 440), 500: (510, 520, 530),
             **{g + 1: (g + 2, g + 3) for g in (310, 320, 330, 410, 430, 440, 510, 520, 530)}}
# the red team's own reading of the link rules
REF_TABLE = {"lsh": (442, 512), "sci": (443, 513), None: (441, 511)}
REF_DOMAIN = {"droit": "lsh", "eco": "lsh", "alsh": "lsh", "sciences": "sci", "staps": "sci"}
KNOWN_BTS = {   # real BTS titles -> the group a careful reader expects (NSF of the diploma)
    "Management Commercial Opérationnel": 413, "Gestion de la PME": 413, "Comptabilité et gestion": 413,
    "Electrotechnique": 412, "Conception et Réalisation de Systèmes Automatiques": 412, "Travaux publics": 412,
    "Collaborateur juriste notarial": 413, "Tourisme": 413,
}


def check(name):
    def deco(fn):
        fn.check_name = name
        CHECKS.append(fn)
        return fn
    return deco


def ref_nsf(code):
    """Independent: an 11-character MEFSTAT11 carries the NSF field in positions 7-9, an 8-character CFD in 4-6."""
    if not code:
        return None
    m = re.fullmatch(r"\d{6}(\d{3})\d{2}", code) or re.fullmatch(r"\d{3}(\d{3})\d{2}", code)
    return int(m.group(1)) if m else None


def ref_side(n):
    return None if n is None else "ind" if 200 <= n <= 255 else "ter" if 300 <= n <= 345 else None


def ref_group(fili, prog, disc, nsfs):
    p = (prog or "").strip().lower()
    if fili == "BTS":
        sides = {ref_side(n) for n in nsfs}
        side = next(iter(sides)) if len(sides) == 1 else None
        return {"ind": 412, "ter": 413}.get(side, 411), None
    if fili in ("Licence", "Licence_Las"):
        return REF_TABLE[REF_DOMAIN.get(disc)]
    if fili in ("IFSI", "EFTS"):
        return 420, None
    if fili == "Ecole d'Ingénieur":
        return 523, None
    if fili == "Ecole de Commerce":
        return 522, None
    if fili == "CPGE":
        if re.match(r"(pcsi|mpsi|ptsi|bcpst|tsi|mp2i|tb|tpc)\b", p):
            return 523, None
        if re.match(r"(ecg|ect)\b", p):
            return 522, None
    return None, None


def ref_read(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = {}
    for sheet in wb.sheetnames:
        m = re.fullmatch(r"Données_(\d)ans", sheet)
        if not m:
            continue
        rows = list(wb[sheet].iter_rows(values_only=True))
        idx = {name: i for i, name in enumerate(rows[0])}
        for r in rows[1:]:
            if r[idx["Code"]] is None:
                continue
            out[(int(m.group(1)), int(r[idx["Code"]]))] = {k: (float(r[idx[k]]) if k in idx and isinstance(r[idx[k]], (int, float)) else None)
                                                         for k in REF_IND}
    wb.close()
    return out


class Ctx:
    def __init__(self, db: Path, real: bool, source: Path | None = None):
        self.db, self.real = db, real
        self.source = source or CQ.source_path()
        src = duckdb.connect(str(db), read_only=True)
        self.stored = {(r[0], r[1]): dict(zip(REF_IND, r[2:])) for r in
                       src.execute(f"SELECT horizon, code, {', '.join(REF_IND)} FROM core.cereq_diplome").fetchall()}
        self.links = {r[0]: r[1:] for r in src.execute("SELECT cod_aff_form, fili, programme, discipline, nsf, code, code_suite, regle FROM core.cereq_link").fetchall()}
        latest = src.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
        self.forms = src.execute("SELECT cod_aff_form, fili, fil_lib_voe_acc FROM core.formation_year WHERE session = ?", [latest]).fetchall()
        self.ij = src.execute("SELECT DISTINCT libelle_formation, code FROM core.inserjeunes_bts").fetchall()
        self.disc = dict(src.execute("SELECT cod_aff_form, arg_max(discipline, session) FROM core.licence_success_link GROUP BY 1").fetchall())
        # a small working copy for the mutation runs (rebuilt per mutant)
        self.work = duckdb.connect()
        self.work.execute("CREATE SCHEMA core")
        for t, sql in (("formation_year", "SELECT session, cod_aff_form, fili, fil_lib_voe_acc FROM core.formation_year"),
                       ("inserjeunes_bts", "SELECT libelle_formation, code FROM core.inserjeunes_bts"),
                       ("licence_success_link", "SELECT session, cod_aff_form, discipline FROM core.licence_success_link")):
            df = src.execute(sql).df()
            self.work.register("_t", df)
            self.work.execute(f"CREATE TABLE core.{t} AS SELECT * FROM _t")
            self.work.unregister("_t")
        src.close()

    def ref_links(self):
        nsf = {}
        for lib, code in self.ij:
            n = ref_nsf(code)
            if n is not None:
                nsf.setdefault(bts_key(lib), set()).add(n)
        def fields(prog):
            k = bts_key(prog)
            if k in nsf:
                return nsf[k]
            out = set()
            for kk, v in nsf.items():          # a BTS published option by option: its options' fields
                if kk.startswith(k + " option"):
                    out |= v
            return out
        return {cod: ref_group(fili, prog, self.disc.get(cod), fields(prog) if fili == "BTS" else set())
                for cod, fili, prog in self.forms}


# ---------------------------------------------------------------- checks
@check("C1 the workbook is re-read cell by cell (both horizons): stored values = published, nothing invented, nothing lost")
def c1(c: Ctx):
    if not c.source:
        return False, "no Céreq workbook in data/sources"
    ref = ref_read(c.source)
    diff = [(k, i) for k in set(ref) | set(c.stored) for i in REF_IND
            if (ref.get(k) or {}).get(i) != (c.stored.get(k) or {}).get(i)]
    return not diff and len(ref) > 0, f"{len(ref)} rows x {len(REF_IND)} indicators, {len(diff)} differ {sorted(diff)[:3]}"


@check("C2 identities: every group adds up to its parent (±1), every distribution to 100 (±2), unemployment rate = unemployed / active")
def c2(c: Ctx):
    bad = []
    for h in (3, 6):
        n = lambda code: c.stored[(h, code)]["eff_pond_g1"]  # noqa: E731
        for parent, kids in HIERARCHY.items():
            if abs(n(parent) - sum(n(k) for k in kids)) > 1:
                bad.append(("sum", h, parent))
        for code in {k for hh, k in c.stored if hh == h}:
            r = c.stored[(h, code)]
            for parts in (("taux_emploi", "part_chomage", "part_autre"),
                          ("pos_cadres", "pos_prof_int", "pos_emp_ouv_q", "pos_emp_ouv_nq", "pos_autres")):
                if abs(sum(r[p] for p in parts) - 100) > 2:
                    bad.append(("partition", h, code, parts[0]))
            if abs(100 * r["part_chomage"] / (r["taux_emploi"] + r["part_chomage"]) - r["taux_chomage"]) > 1.5:
                bad.append(("chomage", h, code))
            if not 0 <= r["correspondance_ok"] <= 100:
                bad.append(("bounds", h, code))
        if (h, 100) not in c.stored:
            bad.append(("no total", h))
    has_comp = [h for h in (3, 6) if c.stored.get((h, 100), {}).get("competence_ok") is not None]
    return not bad and has_comp == [3], f"{len(bad)} broken {bad[:3]}; competence published at {has_comp} years only"


@check("C3 link: every formation of the latest campaign re-derived (BTS field from its official code, licence discipline, CPGE track, BUT none)")
def c3(c: Ctx):
    want = c.ref_links()
    got = {cod: (v[4], v[5]) for cod, v in c.links.items()}
    bad = [(cod, got.get(cod), w) for cod, w in want.items() if got.get(cod) != w]
    extra = set(got) - set(want)
    # truth table on real titles (when present in the campaign)
    titles = {}
    for cod, fili, prog in c.forms:
        if fili == "BTS":
            titles.setdefault(prog, got.get(cod, (None,))[0])
    truth = [(t, titles[t], g) for t, g in KNOWN_BTS.items() if t in titles and titles[t] != g]
    stats = Counter(v[6] for v in c.links.values())
    bts = [v for v in c.links.values() if v[0] == "BTS"]
    known = sum(1 for v in bts if v[4] in (412, 413)) / len(bts) if bts else 1
    cover_ok = known >= 0.70 if c.real else True
    but_none = all(v[4] is None for v in c.links.values() if v[0] == "BUT")
    return (not bad and not extra and not truth and cover_ok and but_none,
            f"{len(want)} formations, {len(bad)} differ {bad[:2]}; truth {truth[:2]}; BTS with a known field {known:.0%}; {dict(stats)}")


@check("C4 API: the group's values are the stored ones, the reference is all leavers, 'si vous poursuivez' only for licences")
def c4(c: Ctx):
    con = duckdb.connect(str(c.db), read_only=True)
    bad, n = [], 0
    by_rule = {}
    for cod, v in c.links.items():
        by_rule.setdefault(v[6], []).append(cod)
    for rule, cods in by_rule.items():
        for cod in cods[:25]:
            b = CQ.for_formation(con, cod)
            n += 1
            code, suite = c.links[cod][4], c.links[cod][5]
            if code is None:
                if not b or b["status"] != "sans_correspondance":
                    bad.append((cod, "status"))
                continue
            if b["groupe"]["code"] != code or b["ensemble"]["code"] != 100 or (b["suite"] or {}).get("code") != suite:
                bad.append((cod, "codes"))
            for g in (b["groupe"], b["ensemble"], b["suite"]):
                if not g:
                    continue
                for h in (3, 6):
                    vals = g["valeurs"][f"a{h}ans"]
                    if any(vals[k] != c.stored[(h, g["code"])][k] for k in REF_IND):
                        bad.append((cod, g["code"], h))
            if suite and c.links[cod][0] not in ("Licence", "Licence_Las"):
                bad.append((cod, "suite outside licence"))
    con.close()
    return not bad and n > 0, f"{n} pages, {len(bad)} wrong {bad[:3]}"


def ui(js: str) -> tuple[bool, str]:
    i = js.index("// ---- Sprint 8 follow-up: does the job match")
    blk = js[i: js.index("// ---- Sprint 8: insertion", i)]
    code = re.sub(r"(?m)^\s*//.*$", "", blk)
    safe = ("esc(", "cqVal(", "fmt(", "tip(")
    raw = [m for m in re.findall(r"\$\{((?:(?!\$\{)[^}])*)\}", code)
           if re.search(r"\b(?:label|regle|generation|enquetes|l|den)\b", m) and not m.lstrip().startswith(safe)
           and not re.fullmatch(r"\s*(head|th|rows|note|i === 0.*)\s*", m)]
    words = all(w in code for w in ("dont c'est le plus haut diplôme", "Ce ne sont pas les élèves de cette formation",
                                    "déclaré par les jeunes en emploi", "pas des chances", "parmi ceux en emploi",
                                    "parmi tous les sortants", "le BUT a été créé en 2021"))
    summed = re.findall(r"pos_cadres[^\n]*\+[^\n]*pos_prof_int|pos_prof_int[^\n]*\+[^\n]*pos_cadres", code)
    wired = "${cereqCard(d.cereq)}" in js
    ok = not raw and words and not summed and wired
    return ok, f"unescaped {raw[:3]}; wording {words}; published shares summed {summed[:1]}; wired {wired}"


@check("C5 page: stored strings escaped, denominators and caveats stated (highest diploma, not this formation, declared), shares never summed")
def c5(c: Ctx):
    return ui(APP_JS.read_text())


UI_MUTANTS = [
    ("unescaped group label", '<div class="muted small">${esc(g.label)}</div></th>', '<div class="muted small">${g.label}</div></th>'),
    ("'not this formation' caveat dropped", "Ce ne sont pas les élèves de cette formation : quelqu'un qui poursuit ses études rejoint un autre groupe. ", ""),
    ("denominator of the employment rate dropped", '"En emploi, 6 ans après", "parmi tous les sortants"', '"En emploi, 6 ans après", "parmi ceux en emploi"'),
    ("cadres and intermediate professions summed", '["a6ans", "pos_cadres", "Cadres", "parmi ceux en emploi, 6 ans après"],',
     '["a6ans", "pos_cadres", "Cadres", "parmi ceux en emploi, 6 ans après"], // v = pos_cadres + pos_prof_int\n  ["a6ans", "cadres_pi", "Cadres", "x"],'),
    ("card not wired", "${cereqCard(d.cereq)}", ""),
]


@check("C6 mutation test: wrong NSF digits, sides swapped, BUT given DUT figures, discipline ignored, horizons swapped, neighbour column, UI bugs")
def c6(c: Ctx):
    missed = []
    js = APP_JS.read_text()
    for name, old, new in UI_MUTANTS:
        if old not in js or ui(js.replace(old, new, 1))[0]:
            missed.append(name)
    want = c.ref_links()
    saved = {k: getattr(CQ, k) for k in ("nsf_of", "nsf_side", "group_of", "read", "INDICATORS")}

    def links_after():
        CQ.build_links(c.work)
        return {r[0]: (r[1], r[2]) for r in c.work.execute("SELECT cod_aff_form, code, code_suite FROM core.cereq_link").fetchall()}

    def swapped_side(n):
        s = saved["nsf_side"](n)
        return {"industrielle": "tertiaire", "tertiaire": "industrielle"}.get(s, s)

    def but_dut(fili, prog, disc, nsf):
        return (411, None, "x") if fili == "BUT" else saved["group_of"](fili, prog, disc, nsf)

    def no_disc(fili, prog, disc, nsf):
        return saved["group_of"](fili, prog, None, nsf)

    link_mutants = [
        ("NSF read at digits 4-6 of a MEFSTAT11", lambda: setattr(CQ, "nsf_of", lambda code: int(code[3:6]) if code and code[3:6].isdigit() else None)),
        ("industrial and tertiary swapped", lambda: setattr(CQ, "nsf_side", swapped_side)),
        ("BUT given the old DUT (bac+2) figures", lambda: setattr(CQ, "group_of", but_dut)),
        ("licence discipline ignored", lambda: setattr(CQ, "group_of", no_disc)),
    ]
    for name, apply in link_mutants:
        try:
            apply()
            caught = links_after() != want
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            for k, v in saved.items():
                setattr(CQ, k, v)
        if not caught:
            missed.append(name)

    def read_swapped(path):
        recs = saved["read"](path)
        for r in recs:
            r["horizon"] = 9 - r["horizon"]           # 3 <-> 6
        return recs

    def read_neighbour(path):
        recs = saved["read"](path)
        for r in recs:
            r["correspondance_ok"] = r["competence_ok"] if r["horizon"] == 3 else r["taux_edi"]
        return recs

    def read_zero(path):
        recs = saved["read"](path)
        for r in recs:
            r["competence_ok"] = r["competence_ok"] if r["competence_ok"] is not None else 0.0
        return recs

    for name, fn in (("horizons swapped", read_swapped), ("neighbouring column read", read_neighbour),
                     ("unpublished value stored as 0", read_zero)):
        try:
            CQ.read = fn
            stored = {(r["horizon"], r["code"]): {k: r[k] for k in REF_IND} for r in CQ.read(c.source)}
            ref = ref_read(c.source)
            caught = stored != ref
        except Exception:  # noqa: BLE001
            caught = True
        finally:
            CQ.read = saved["read"]
        if not caught:
            missed.append(name)
    CQ.build_links(c.work)
    n = len(UI_MUTANTS) + len(link_mutants) + 3
    return not missed, f"{n - len(missed)}/{n} mutants caught" + (f"; missed {missed}" if missed else "")


def run(db: Path, real: bool = False, source: Path | None = None) -> list[dict]:
    c = Ctx(db, real, source)
    out = []
    for fn in CHECKS:
        try:
            ok, detail = fn(c)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"crashed: {type(e).__name__}: {e}"
        out.append({"check": fn.check_name, "ok": bool(ok), "detail": detail})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "suptracker.duckdb")
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.db, a.real)
    for r in res:
        print(("PASS " if r["ok"] else "FAIL ") + r["check"])
        print("       " + r["detail"])
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} checks passed")
    return 0 if n == len(res) else 1


if __name__ == "__main__":
    sys.exit(main())
