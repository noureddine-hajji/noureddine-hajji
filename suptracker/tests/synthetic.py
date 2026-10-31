"""SYNTHETIC raw files that mimic the SIES export layout, for tests only.

Nothing here is real Parcoursup data. The generator deliberately injects the
situations the pipeline must survive: column-name drift between vintages, a
re-coded cod_aff_form, an ambiguous re-coding, a campaign gap, a concours commun
sharing one applicant pool, and low-denominator cohorts.
"""
from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

YEARS = (2022, 2023, 2024, 2025)

ETABS = [
    ("0751234A", "Université Exemple Paris", "Paris", "75", "Paris"),
    ("0691234B", "IUT Exemple Lyon", "Lyon", "69", "Lyon"),
    ("0331234C", "Lycée Exemple Bordeaux", "Bordeaux", "33", "Bordeaux"),
    ("0591234D", "École d'ingénieurs Exemple Lille", "Lille", "59", "Lille"),
    ("0131234E", "Lycée Exemple Marseille", "Marseille", "13", "Aix-Marseille"),
    ("0311234F", "École d'ingénieurs Exemple Toulouse", "Toulouse", "31", "Toulouse"),
    ("0441234G", "École d'ingénieurs Exemple Nantes", "Nantes", "44", "Nantes"),
    ("0671234H", "École d'ingénieurs Exemple Strasbourg", "Strasbourg", "67", "Strasbourg"),
]

TRACKS = [  # fili, form_lib_voe_acc, fil_lib_voe_acc (real SIES taxonomy labels)
    ("BUT", "BUT - Production", "Génie mécanique et productique"),
    ("BUT", "BUT - Service", "Gestion des entreprises et des administrations"),
    ("BTS", "BTS - Services", "Comptabilité et gestion"),
    ("BTS", "BTS - Production", "Systèmes numériques"),
    ("Licence", "Licence - Droit-économie-gestion", "Droit"),
    ("Licence", "Licence - Sciences - technologies - santé", "Mathématiques"),
    ("CPGE", "Classe préparatoire scientifique", "MPSI"),
]
ECG = ("CPGE", "Classe préparatoire économique et commerciale", "ECG - Mathématiques appliquées + ESH")
ECT = ("CPGE", "Classe préparatoire économique et commerciale", "ECT - Option technologique")
AES = ("Licence", "Licence - Droit-économie-gestion", "Administration économique et sociale")
DOUBLETTES = {  # SIES spelling
    "MATHS+SES": "Mathématiques Spécialité,Sciences Economiques et Sociales Spécialité",
    "MATHS+PC": "Mathématiques Spécialité,Physique-Chimie Spécialité",
    "HGGSP+SES": "Sciences Economiques et Sociales Spécialité,Histoire-Géographie, Géopolitique et Sciences politiques",
}
# (voeux, propositions, acceptations) per year, by SIES formation type and doublette key
SPE_PLAN = {
    "CPGE ECG": {"MATHS+SES": (900, 700, 600), "MATHS+PC": (300, 150, 100), "HGGSP+SES": (100, 40, 20)},
    "CPGE S": {"MATHS+SES": (40, 3, 2), "MATHS+PC": (3000, 2400, 2000), "HGGSP+SES": (5, 0, 0)},
    "Licence Pluri Sciences économiques - Gestion":
        {"MATHS+SES": (1500, 1200, 800), "MATHS+PC": (300, 250, 150), "HGGSP+SES": (900, 700, 500)},
    "Licence AES": {"MATHS+SES": (400, 320, 200), "MATHS+PC": (100, 80, 40), "HGGSP+SES": (600, 450, 300)},
    "Licence Sciences juridiques":
        {"MATHS+SES": (500, 350, 250), "MATHS+PC": (500, 300, 200), "HGGSP+SES": (3000, 2000, 1500)},
    "BUT Service": {"MATHS+SES": (800, 450, 300), "MATHS+PC": (300, 150, 80), "HGGSP+SES": (500, 250, 150)},
}
NATIONAL = {"MATHS+SES": (3000, 2900), "MATHS+PC": (3600, 3500), "HGGSP+SES": (3500, 3400)}  # voeux, prop
SPLIT_LABEL = "Bac Série générale avec la spécialité Maths + une spécialité non scientifique"


def _fixed_cohort(sm, ab, b, tb, tbf, bg, bt, bp):
    """Admitted cohort with an exact mention / series profile (identities hold)."""
    neo = sm + ab + b + tb + tbf
    assert bg + bt + bp == neo
    pct = lambda x: round(100.0 * x / neo) if neo else None  # noqa: E731
    return {"acc_tot": neo, "acc_tot_f": neo // 2, "acc_term": neo, "acc_term_f": neo // 2, "acc_neobac": neo,
            "acc_at": 0, "acc_bg": bg, "acc_bt": bt, "acc_bp": bp, "acc_brs": neo // 4, "acc_pp": neo,
            "acc_pc": 0, "acc_aca_orig": neo // 2, "acc_internat": 0, "acc_sansmention": sm, "acc_ab": ab,
            "acc_b": b, "acc_tb": tb, "acc_tbf": tbf, "acc_mention_nonrenseignee": 0,
            "pct_f": 50, "pct_bours": 25, "pct_bg": pct(bg), "pct_bt": pct(bt), "pct_bp": pct(bp),
            "pct_tb": pct(tb), "pct_tbf": pct(tbf), "pct_b": pct(b), "pct_ab": pct(ab), "pct_sansmention": pct(sm),
            "pct_mention_nonrenseignee": 0, "pct_aca_orig": 50, "pct_etab_orig": 10, "pct_neobac": 100}


def _series_mentions(rng: random.Random, c: dict) -> dict:
    """Split the admits with a mention (AB..TBF) across series, within each series' size."""
    m = sum(c.get(k, 0) for k in ("acc_ab", "acc_b", "acc_tb", "acc_tbf"))
    bg = min(c["acc_bg"], rng.randint(max(0, m - c["acc_bt"] - c["acc_bp"]), m))
    bt = min(c["acc_bt"], m - bg)
    bp = m - bg - bt
    return {"acc_bg_mention": bg, "acc_bt_mention": bt, "acc_bp_mention": bp,
            # like SIES: over all néo-bacheliers admitted, not over the bac-général admits
            "pct_bg_mention": round(100.0 * bg / c["acc_neobac"]) if c["acc_neobac"] else None}


def _timing(rng: random.Random, acc_tot: int) -> dict:
    """Cumulative offer timing, as published: counts and SIES-rounded shares of acc_tot."""
    d = rng.randint(0, acc_tot)
    b = rng.randint(d, acc_tot)
    f = rng.randint(b, acc_tot)
    pct = lambda x: round(100.0 * x / acc_tot) if acc_tot else None  # noqa: E731
    return {"acc_debutpp": d, "acc_datebac": b, "acc_finpp": f,
            "pct_acc_debutpp": pct(d), "pct_acc_datebac": pct(b), "pct_acc_finpp": pct(f),
            "nb_voe_pp_internat": 0, "nb_cla_pp_internat": 0}


def _cohort(rng: random.Random, acc_tot: int) -> dict:
    acc_at = rng.randint(0, max(0, acc_tot // 6))
    term = acc_tot - acc_at
    bg = rng.randint(term // 3, term)
    bt = rng.randint(0, term - bg)
    bp = term - bg - bt
    rest = term
    mentions = {}
    for k in ("acc_tbf", "acc_tb", "acc_b", "acc_ab", "acc_mention_nonrenseignee"):
        v = rng.randint(0, rest // 3)
        mentions[k] = v
        rest -= v
    mentions["acc_sansmention"] = rest
    brs = rng.randint(0, term)
    f = rng.randint(0, acc_tot)
    pct = lambda x, d: round(100.0 * x / d) if d else None  # noqa: E731 - SIES rounds to integers
    return {
        # like the real SIES exports: breakdowns add up to acc_neobac, acc_term does not
        "acc_tot": acc_tot, "acc_tot_f": f, "acc_term": max(0, term - rng.randint(0, 3)),
        "acc_term_f": min(f, term), "acc_neobac": term, "acc_at": acc_at, "acc_bg": bg, "acc_bt": bt, "acc_bp": bp,
        "acc_brs": brs, "acc_pp": acc_tot - acc_tot // 10, "acc_pc": acc_tot // 10,
        "acc_aca_orig": rng.randint(0, acc_tot), "acc_internat": 0, **mentions, **_timing(rng, acc_tot),
        "pct_f": pct(f, acc_tot), "pct_bours": pct(brs, term), "pct_bg": pct(bg, term),
        "pct_bt": pct(bt, term), "pct_bp": pct(bp, term),
        "pct_tb": pct(mentions["acc_tb"], term), "pct_tbf": pct(mentions["acc_tbf"], term),
        "pct_b": pct(mentions["acc_b"], term), "pct_ab": pct(mentions["acc_ab"], term),
        "pct_sansmention": pct(mentions["acc_sansmention"], term),
        "pct_mention_nonrenseignee": pct(mentions["acc_mention_nonrenseignee"], term),
        "pct_aca_orig": rng.randint(20, 95), "pct_etab_orig": rng.randint(0, 40),
        "pct_neobac": pct(term, acc_tot),
    }


def _row(rng, year, cod, etab, track, lib_comp="", acc_tot=None, pool=None):
    uai, name, ville, dep, aca = etab
    fili, form, fil = track
    acc_tot = acc_tot if acc_tot is not None else rng.randint(12, 120)
    capa = acc_tot + rng.randint(0, 10)
    if pool:
        voe_tot, voe_tot_f, nb_pp, nb_pc = pool
    else:
        nb_pp = rng.randint(capa * 2, capa * 30)
        nb_pc = rng.randint(0, capa)
        voe_tot, voe_tot_f = nb_pp + nb_pc, rng.randint(0, nb_pp + nb_pc)
    nb_cla = rng.randint(capa, nb_pp)
    row = {
        "session": year, "cod_uai": uai, "cod_aff_form": str(cod), "g_ea_lib_vx": name,
        "contrat_etab": "Public", "dep": dep, "dep_lib": ville, "region_etab_aff": "Région",
        "acad_mies": aca, "ville_etab": ville, "select_form": "formation sélective",
        "fili": fili, "form_lib_voe_acc": form, "fil_lib_voe_acc": fil,
        "lib_for_voe_ins": f"{fil} {lib_comp}".strip(), "lib_comp_voe_ins": lib_comp,
        "detail_forma": None, "capa_fin": capa, "voe_tot": voe_tot, "voe_tot_f": voe_tot_f,
        "nb_voe_pp": nb_pp, "nb_voe_pc": nb_pc, "nb_cla_pp": nb_cla, "nb_cla_pc": 0,
        "prop_tot": min(nb_cla, capa * 3), "ran_grp1": rng.randint(capa, nb_cla),
        "taux_acces_ens": round(rng.uniform(5, 100)), "part_acces_gen": round(rng.uniform(0, 100)),
        "part_acces_tec": round(rng.uniform(0, 100)), "part_acces_pro": round(rng.uniform(0, 100)),
        "g_olocalisation_des_formations": "48.85, 2.35",
        "lien_form_psup": ("https://dossierappel.parcoursup.fr/Candidats/public/fiches/"
                           f"afficherFicheFormation?g_ta_cod={cod}&typeBac=0&originePc=0"),
        **_cohort(rng, acc_tot),
    }
    row.update(_series_mentions(rng, row))
    return row


def make_raw(raw_dir: Path, seed: int = 7) -> dict:
    """Write synthetic raw parquet files; returns the planted scenario for assertions."""
    rng = random.Random(seed)
    raw_dir.mkdir(parents=True, exist_ok=True)
    plan = {"recoded": ("1003", "9003"), "ambiguous": ("1010", "1011"), "gap": "1020",
            "new_2025": "1030", "low_n": "1040", "pool": ["2001", "2002", "2003", "2004"],
            "ecg_elite": "3001", "ecg_open": "3002", "ect": "3003", "ecg_mid": "3006", "aes": "3005",
            "ecogestion": "3007", "pcsi": "3008"}
    stable = []
    cod = 1100
    for e in ETABS[:5]:
        for t in TRACKS:
            stable.append((str(cod), e, t))
            cod += 1
    pools = {y: (900 + y % 100, 400, 880 + y % 100, 20) for y in YEARS}
    for y in YEARS:
        rows = [_row(rng, y, c, e, t) for c, e, t in stable]
        # re-coded in 2024: same UAI + fili + labels, new cod_aff_form
        rows.append(_row(rng, y, "1003" if y < 2024 else "9003", ETABS[0], TRACKS[4],
                         lib_comp="Parcours droit public"))
        # two programmes with identical labels both re-coded in 2024 -> must NOT be linked
        for old, new in (("1010", "9010"), ("1011", "9011")):
            rows.append(_row(rng, y, old if y < 2024 else new, ETABS[1], TRACKS[1]))
        if y != 2023:
            rows.append(_row(rng, y, "1020", ETABS[2], TRACKS[2], lib_comp="Alternance"))
        if y == 2025:
            rows.append(_row(rng, y, "1030", ETABS[3], TRACKS[5]))
        rows.append(_row(rng, y, "1040", ETABS[4], TRACKS[6], acc_tot=6))
        for c, e in zip(plan["pool"], ETABS[3:]):
            rows.append(_row(rng, y, c, e, ("Ecole d'Ingénieur", "Formation d'ingénieur Bac + 5",
                                            "Formation d'ingénieur Bac + 5 - bac général"),
                             lib_comp="Concours Puissance Alpha", pool=pools[y]))
        # journey personas: an elite and an accessible ECG, a mid one, an ECT and an AES licence
        journey = [
            ("3001", ETABS[0], ECG, 5, _fixed_cohort(0, 0, 5, 25, 15, 45, 0, 0), None),
            ("3002", ETABS[1], ECG, 85, _fixed_cohort(15, 20, 8, 2, 0, 40, 5, 0),
             [(SPLIT_LABEL, 120), ("Autres candidats", 300)]),
            ("3006", ETABS[2], ECG, 45, _fixed_cohort(4, 10, 16, 12, 3, 45, 0, 0), None),
            ("3009", ETABS[3], ECG, 20, _fixed_cohort(1, 4, 15, 18, 7, 45, 0, 0), None),
            ("3003", ETABS[3], ECT, 60, _fixed_cohort(15, 15, 8, 2, 0, 0, 40, 0), None),
            ("3005", ETABS[4], AES, 90, _fixed_cohort(60, 50, 20, 5, 1, 120, 12, 4), None),
            ("3007", ETABS[0], ("Licence", "Licence - Droit-économie-gestion", "Economie et gestion"), 80,
             _fixed_cohort(50, 60, 30, 8, 2, 140, 10, 0), None),
            ("3008", ETABS[1], ("CPGE", "Classe préparatoire scientifique", "PCSI"), 40,
             _fixed_cohort(0, 2, 10, 20, 10, 42, 0, 0), None),
        ]
        for c, e, track, taux, cohort, groups in journey:
            r = _row(rng, y, c, e, track)
            r.update(cohort)
            r.update(_timing(rng, cohort["acc_tot"]))
            r.update(_series_mentions(rng, r))
            r.update({"taux_acces_ens": taux, "capa_fin": cohort["acc_tot"] + 2,
                      "lib_grp1": "Tous les candidats", "ran_grp1": 400, "lib_grp2": None, "ran_grp2": None})
            for i, (lib, ran) in enumerate(groups or [], start=1):
                r[f"lib_grp{i}"], r[f"ran_grp{i}"] = lib, ran
            rows.append(r)
        df = pd.DataFrame(rows)
        # synthetic schema drift between vintages
        if y == 2022:
            df.columns = [c.upper() for c in df.columns]
        if y == 2023:
            df = df.rename(columns={"acc_mention_nonrenseignee": "acc_mention_non_renseignee",
                                    "taux_acces_ens": "taux_acces"})
        if y == 2025:
            df = df.rename(columns={"part_acces_gen": "part_terminale_generale_en_position_admis_pp"})
        df.to_parquet(raw_dir / f"parcoursup_{y}.parquet", index=False)
        if y == 2025:  # real exports carry GEOMETRY('OGC:CRS84') points
            import duckdb
            path = raw_dir / f"parcoursup_{y}.parquet"
            duckdb.sql(f"""COPY (SELECT * REPLACE ('POINT (2.35 48.85)'::GEOMETRY AS g_olocalisation_des_formations)
                           FROM read_parquet('{path}')) TO '{path}.tmp' (FORMAT parquet)""")
            Path(f"{path}.tmp").replace(path)

    spe = []
    for y in YEARS:
        for ft, by_d in SPE_PLAN.items():
            for dk, (v, pr, a) in by_d.items():
                spe.append({"annee_du_bac": y, "formation": ft, "doublette": DOUBLETTES[dk],
                            "voeux": v, "propositions_d_admissions": pr, "acceptations": a})
        for dk, (v, pr) in NATIONAL.items():   # deduplicated national row: each candidate accepts once
            spe.append({"annee_du_bac": y, "formation": "Ensemble des bacheliers", "doublette": DOUBLETTES[dk],
                        "voeux": v, "propositions_d_admissions": pr,
                        "acceptations": sum(SPE_PLAN[ft][dk][2] for ft in SPE_PLAN)})
    spe = pd.DataFrame(spe)
    spe[spe.annee_du_bac < 2025].to_parquet(raw_dir / "specialites_2021_2024.parquet", index=False)
    # 2025 layout: level 0 = all bacheliers, 1 = group total, 2 = detailed formations (repeat level 1)
    s25 = spe[spe.annee_du_bac == 2025].rename(columns={"formation": "regroupement_de_formations"})
    nat = s25.regroupement_de_formations == "Ensemble des bacheliers"
    lvl0 = s25[nat].assign(niveau_d_agregation="0", formation="Ensemble des bacheliers")
    lvl1 = s25[~nat].assign(niveau_d_agregation="1", formation="Ensemble regroupement de formations")
    lvl2 = s25[~nat].assign(niveau_d_agregation="2", formation=s25.regroupement_de_formations + " (détail)")
    pd.concat([lvl0, lvl1, lvl2]).to_parquet(raw_dir / "specialites_2025.parquet", index=False)

    fiche = ("https://dossierappel.parcoursup.fr/Candidats/public/fiches/"
             "afficherFicheFormation?g_ta_cod={}&typeBac=0&originePc=0")
    # real ODS values; the cartographie lists several sessions per formation (latest wins)
    carto = [
        {"gta": "1100", "annee": 2025, "etab_gps": "45.75, 4.85", "fiche": fiche.format(1100),
         "app": "", "int": "", "amg": "Enseignement en présentiel"},
        {"gta": "1100", "annee": 2026, "etab_gps": "45.75, 4.85", "fiche": fiche.format(1100),
         "app": "", "int": "Etablissements avec internat pour filles et garçons",
         "amg": "Enseignement en présentiel,Formations avec aménagements pour sportifs haut niveau"},
        {"gta": "1102", "annee": 2026, "etab_gps": None, "fiche": fiche.format(1102),
         "app": "Formations en apprentissage", "int": "",
         "amg": "Enseignement partiellement à distance,Formations avec aménagements pour artistes haut niveau"},
        {"gta": "1103", "annee": 2026, "etab_gps": None, "fiche": fiche.format(1103),
         "app": "", "int": "Etablissements avec internat pour filles", "amg": "Enseignement à distance"},
    ]
    pd.DataFrame(carto).to_parquet(raw_dir / "cartographie.parquet", index=False)
    return plan
