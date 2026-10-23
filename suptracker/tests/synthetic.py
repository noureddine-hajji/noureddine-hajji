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

TRACKS = [  # fili, form_lib_voe_acc, fil_lib_voe_acc
    ("BUT", "BUT - Production", "BUT - Génie mécanique et productique"),
    ("BUT", "BUT - Service", "BUT - Gestion des entreprises et des administrations"),
    ("BTS", "BTS - Services", "BTS - Comptabilité et gestion"),
    ("BTS", "BTS - Production", "BTS - Systèmes numériques"),
    ("Licence", "Licence - Droit", "Licence - Droit"),
    ("Licence", "Licence - Sciences", "Licence - Mathématiques"),
    ("CPGE", "CPGE - MPSI", "Classe préparatoire scientifique - MPSI"),
]


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
        "acc_aca_orig": rng.randint(0, acc_tot), "acc_internat": 0, **mentions,
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
    return {
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


def make_raw(raw_dir: Path, seed: int = 7) -> dict:
    """Write synthetic raw parquet files; returns the planted scenario for assertions."""
    rng = random.Random(seed)
    raw_dir.mkdir(parents=True, exist_ok=True)
    plan = {"recoded": ("1003", "9003"), "ambiguous": ("1010", "1011"), "gap": "1020",
            "new_2025": "1030", "low_n": "1040", "pool": ["2001", "2002", "2003", "2004"]}
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
        for d in ("Mathématiques / Physique-Chimie", "SES / HGGSP", "SVT / Physique-Chimie"):
            for ft in ("BUT", "Licence", "CPGE"):
                p = rng.randint(1000, 20000)
                # real SIES layout: proposals and acceptances only, no candidate counts
                spe.append({"annee_du_bac": y, "formation": ft, "doublette": d,
                            "propositions_d_admissions": p, "acceptations": rng.randint(p // 3, p)})
    spe = pd.DataFrame(spe)
    spe[spe.annee_du_bac < 2025].to_parquet(raw_dir / "specialites_2021_2024.parquet", index=False)
    # 2025 layout: level 0 = all bacheliers, 1 = group total, 2 = detailed formations (repeat level 1)
    s25 = spe[spe.annee_du_bac == 2025].rename(columns={"formation": "regroupement_de_formations"})
    lvl1 = s25.assign(niveau_d_agregation="1", formation="Ensemble regroupement de formations")
    lvl2 = s25.assign(niveau_d_agregation="2", formation=s25.regroupement_de_formations + " (détail)")
    lvl0 = (s25.groupby(["annee_du_bac", "doublette"], as_index=False)[["propositions_d_admissions", "acceptations"]]
            .sum().assign(regroupement_de_formations="Ensemble des bacheliers", niveau_d_agregation="0",
                          formation="Ensemble des bacheliers"))
    pd.concat([lvl0, lvl1, lvl2]).to_parquet(raw_dir / "specialites_2025.parquet", index=False)

    pd.DataFrame([{"gta": "1100", "annee": 2025, "etab_gps": "45.75, 4.85",
                   "fiche": "https://dossierappel.parcoursup.fr/Candidats/public/fiches/"
                            "afficherFicheFormation?g_ta_cod=1100&typeBac=0&originePc=0"}]
                 ).to_parquet(raw_dir / "cartographie.parquet", index=False)
    return plan
