import importlib
import itertools
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from suptracker import build as build_mod  # noqa: E402
from suptracker import journey as J  # noqa: E402
from synthetic import DOUBLETTES, SPLIT_LABEL, make_raw  # noqa: E402

persona = importlib.import_module("verify_persona")


@pytest.fixture(scope="module")
def wh(tmp_path_factory):
    d = tmp_path_factory.mktemp("journey")
    plan = make_raw(d / "raw")
    db = build_mod.build(d / "raw", d / "w.duckdb")
    con = duckdb.connect(str(db), read_only=True)
    yield con, plan, db
    con.close()


def test_parse_every_specialty_pair_in_sies_spelling():
    for a, b in itertools.combinations(J.SPECIALTIES, 2):
        assert J.parse_doublette(f"{J.SPECIALTIES[a]},{J.SPECIALTIES[b]}") == tuple(sorted((a, b)))
        assert J.parse_doublette(f"{J.SPECIALTIES[b]},{J.SPECIALTIES[a]}") == tuple(sorted((a, b)))
    assert J.parse_doublette("Mathématiques Spécialité") is None
    assert J.parse_doublette("Mathématiques / Physique-Chimie") is None
    assert J.doublette_key("ses", "maths") == "MATHS+SES"


def test_type_key_normalises_vintage_spellings():
    assert J.type_key("Licence\xa0-\xa0Droit-économie-gestion") == J.type_key("Licence - Droit-economie-gestion")
    assert J.type_key("Licence Sciences de l'éducation") == J.type_key("Licence Sciences de l éducation")


@pytest.mark.parametrize("label,spe,expected", [
    ("Tous les candidats", ("MATHS", "SES"), True),
    ("Tous les candidats sauf les Bac technologiques et Bac professionnels", ("MATHS", "SES"), True),
    ("Bacheliers technologiques toutes séries", ("MATHS", "SES"), False),
    ("Voie d'accès CEP", ("MATHS", "SES"), False),
    ("Toutes les filles", ("MATHS", "SES"), None),
    (SPLIT_LABEL, ("MATHS", "SES"), True),
    (SPLIT_LABEL, ("MATHS", "PC"), False),
    (SPLIT_LABEL, ("HGGSP", "SES"), False),
    ("Bac général avec spécialités Maths et Physique-Chimie", ("MATHS", "PC"), True),
    ("Bac général - spécialité Maths ou NSI", ("NSI", "PC"), True),
])
def test_group_label_parser(label, spe, expected):
    assert J.group_applies(label, spe) is expected


def test_student_group_resolution():
    row = {"lib_grp1": SPLIT_LABEL, "ran_grp1": 120, "lib_grp2": "Autres candidats", "ran_grp2": 300}
    g = J.student_group(row, ("MATHS", "SES"))
    assert (g["group"], g["last_called_rank"], g["specialty_split"]) == (1, 120, True)
    g = J.student_group(row, ("MATHS", "PC"))       # residual group when the split one excludes you
    assert (g["group"], g["last_called_rank"]) == (2, 300)
    g = J.student_group({"lib_grp1": "Toutes les filles", "ran_grp1": 5, "lib_grp2": "Tous les garcons",
                         "ran_grp2": 9}, ("MATHS", "SES"), sex="M")
    assert g["group"] == 2


def test_wilson_interval():
    lo, hi = J.wilson(0, 10)
    assert lo == 0 and abs(hi - 0.2775) < 1e-3
    lo, hi = J.wilson(10, 10)
    assert hi == 1 and abs(lo - 0.7225) < 1e-3
    lo, hi = J.wilson(50, 100)
    assert lo < 0.5 < hi and abs((lo + hi) / 2 - 0.5) < 1e-9
    assert J.wilson(0, 0) == (None, None)


def test_zone_rules_and_uncertainty():
    assert J.classify_zone(80, 0.01, 0.0, 0.03)["zone"] == "hors_profil"
    assert J.classify_zone(20, 0.9, 0.85, 0.95)["zone"] == "ambitieux"
    assert J.classify_zone(60, 0.10, 0.08, 0.12)["zone"] == "ambitieux"
    assert J.classify_zone(85, 0.8, 0.75, 0.85) == {"zone": "securite", "uncertain": False}
    assert J.classify_zone(50, 0.4, 0.35, 0.45) == {"zone": "cible", "uncertain": False}
    assert J.classify_zone(85, 0.55, 0.40, 0.70) == {"zone": "securite", "uncertain": True}
    # interval crosses 15 % but the zone is decided by the access rate: not uncertain
    assert J.classify_zone(20, 0.2, 0.1, 0.3) == {"zone": "ambitieux", "uncertain": False}


def test_taxonomy_link(wh):
    con, plan, _ = wh
    got = dict(con.execute("""SELECT t.cod_aff_form, r.spe_type FROM core.taxonomy_link t
        JOIN core.taxonomy_rule r USING (rule_id) WHERE t.session = 2025""").fetchall())
    assert got[plan["ecg_elite"]] == "CPGE ECG" and got[plan["ect"]] == "CPGE ECG"
    assert got[plan["pcsi"]] == "CPGE S" and got[plan["aes"]] == "Licence AES"
    assert got[plan["ecogestion"]] == "Licence Pluri Sciences économiques - Gestion"
    q = dict(con.execute("SELECT spe_type, min(quality) FROM core.taxonomy_rule GROUP BY 1").fetchall())
    assert q["CPGE ECG"] == "approx"   # the ECT/ENS branch is an approximate mapping


def test_stage1_metrics_and_gates(wh):
    con, _, _ = wh
    s1 = J.stage1(con, "MATHS+SES")
    by = {f["label"]: f for f in s1["filieres"]}
    ecg = by["CPGE ECG"]
    assert ecg["candidates"] == 4 * 900 and ecg["offered"] == 4 * 700 and ecg["accepted"] == 4 * 600
    assert abs(ecg["offer_rate"] - 700 / 900) < 1e-12
    assert abs(ecg["share"] - 600 / 720) < 1e-12
    nat_share = 2152 / (2152 + 2570 + 2470)
    assert abs(ecg["lift"] - (600 / 720) / nat_share) < 1e-9
    assert abs(ecg["destination_share"] - 600 / 2152) < 1e-12
    assert abs(ecg["relative_offer"] - (700 / 900) / (890 / 1300)) < 1e-9
    assert {k: by[k]["gate"] for k in by} == {
        "CPGE ECG": "predilection", "CPGE S": "atypique", "Licence Pluri Sciences économiques - Gestion":
        "predilection", "Licence AES": "accessible", "Licence Sciences juridiques": "accessible",
        "BUT Service": "predilection"}
    assert s1["national"]["candidates"] == 4 * 3000 and s1["national"]["accepted"] == 4 * 2152
    assert [t["session"] for t in ecg["trend"]] == [2022, 2023, 2024, 2025]


def test_stage2_zones(wh):
    con, plan, _ = wh
    F = {f["cod_aff_form"]: f for f in J.stage2(con, "MATHS+SES", "ab", J.type_key("CPGE ECG"), "Paris")["formations"]}
    assert F[plan["ecg_elite"]]["zone"] == "hors_profil" and F[plan["ecg_elite"]]["cdf"] == 0
    assert F[plan["ecg_open"]]["zone"] == "securite"
    assert abs(F[plan["ecg_open"]]["cdf"] - 35 / 45) < 1e-12 and F[plan["ecg_open"]]["years"] == 4
    assert F[plan["ecg_mid"]]["zone"] == "cible"
    assert F[plan["ect"]]["zone"] == "non_ouvert" and F[plan["ect"]]["open_to_general"] is False
    g = F[plan["ecg_open"]]["group"]
    assert g["label"] == SPLIT_LABEL and g["last_called_rank"] == 120
    g_pc = {f["cod_aff_form"]: f for f in J.stage2(con, "MATHS+PC", "ab", J.type_key("CPGE ECG"))["formations"]}
    assert g_pc[plan["ecg_open"]]["group"]["last_called_rank"] == 300
    assert F[plan["ecg_elite"]]["home_academie"] is True       # ETABS[0] is in académie de Paris
    with pytest.raises(ValueError):
        J.stage2(con, "MATHS+SES", "tbf", J.type_key("CPGE ECG"))


def test_persona_verification_passes_on_fixture(wh):
    con, _, _ = wh
    rep = persona.run(con)
    assert rep.passed, [c for c in rep.checks if not c["ok"]]


def test_journey_api(wh, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SUPTRACKER_DB", str(wh[2]))
    from suptracker import api
    api._con.cache_clear()
    c = TestClient(api.app)
    v = c.get("/api/journey/vocab").json()
    assert len(v["specialties"]) == 13 and v["zone_rules"]["hors_profil_cdf"] == 0.02
    s1 = c.get("/api/journey/stage1", params={"spe1": "ses", "spe2": "maths"}).json()
    assert s1["doublette"] == "MATHS+SES" and s1["filieres"]
    ecg = next(f for f in s1["filieres"] if f["label"] == "CPGE ECG")
    s2 = c.get("/api/journey/stage2", params={"spe1": "maths", "spe2": "ses", "mention": "ab",
                                              "type": ecg["type_key"]}).json()
    assert s2["formations"] and all("prob" not in k for k in s2["formations"][0])
    assert c.get("/api/journey/stage1", params={"spe1": "maths", "spe2": "maths"}).status_code == 422
    assert c.get("/api/journey/stage1", params={"spe1": "art", "spe2": "llca"}).status_code == 404
