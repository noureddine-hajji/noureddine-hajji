"""Financer ses études (sprint F, owner 2026-11-15): the student aids as the OFFICIAL pages state them, in the cost tab.

Every amount, condition and link comes from the official pages fetched by the `suptracker-aides` workflow into data/aides/
(service-public.gouv.fr, etudiant.gouv.fr, cvec.etudiant.gouv.fr; Légifrance refuses robots, service-public cites its decree),
read by ONE fixed rule per item anchored on the page's wording (`read`). A rule that does not match leaves its item out and is
listed in `audit`: the card never shows a typed amount. The page's "Vérifié le" date is shown with each item.

  * bourse sur critères sociaux: the 8 échelons and their annual amounts (paid in 10 monthly instalments), the overseas
    majoration (applied when the formation is overseas), the simulator and the online file (DSE) the official page links;
  * aide au mérite (bourse + mention Très bien), aide à la mobilité Parcoursup (lycée scholarship + a vœu accepted outside the
    académie of residence): amounts and conditions verbatim. The student's mention and académie are compared IN THE BROWSER;
  * droits d'inscription and CVEC: boursiers are exempt (official sentences). The boursier's year (`annuel_boursier`) drops
    the CVEC and, only for a PUBLIC establishment whose fiche fee is a national rate of the year (a national university
    tariff of the official table, or 0), the fee as well; any other fee is kept and said to be the establishment's own;
  * formations sanitaires et sociales (IFSI, EFTS): their bourses are managed by the Regions (official sentence), so the Crous
    table is replaced by that statement and the regions' page;
  * a private establishment: the bourse needs an establishment "habilité à recevoir des boursiers" (official condition): said.
Never the student's échelon (it needs the family's income: the official simulator does it), never a promise, never a budget.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DIR = Path(__file__).resolve().parents[1] / "data" / "aides"
SANITAIRE_SOCIAL = ("IFSI", "EFTS")
OUTRE_MER = ("97", "98")
EURO = r"(\d{1,3}(?: \d{3})*|\d+)\s*€"

PAGES = {
    "bourse": "https://www.service-public.gouv.fr/particuliers/vosdroits/F12214",
    "merite": "https://www.service-public.gouv.fr/particuliers/vosdroits/F1010",
    "mobilite": "https://www.service-public.gouv.fr/particuliers/vosdroits/F34643",
    "droits": "https://www.service-public.gouv.fr/particuliers/vosdroits/F2865",
    "cvec": "https://cvec.etudiant.gouv.fr/",
    "repas": "https://www.etudiant.gouv.fr/fr/comment-beneficier-du-repas-crous-1-eu-3123",
    "regions": "https://www.etudiant.gouv.fr/fr/aides-des-regions-et-des-outre-mer-2006",
    "mobilite_mesr": "https://www.etudiant.gouv.fr/fr/aide-la-mobilite-parcoursup-1447",
    "logement": "https://www.service-public.gouv.fr/particuliers/vosdroits/F1563",
    # lot 1, PR 12: how a working professional enters an IFSI (formation professionnelle continue, outside Parcoursup)
    "ifsi_fpc": "https://www.parcoursup.gouv.fr/trouver-une-formation/zoom-sur-des-formations-en-sante-pass-las-et-ifsi/les-formations-en-soins-1652",
    # PR 18 (owner, 2026-11-28): the apprentice's contract and minimum pay, as the official page states them
    "apprenti": "https://www.service-public.gouv.fr/particuliers/vosdroits/F2918",
}
ECHELONS = ("0 bis", "1", "2", "3", "4", "5", "6", "7")


def _file(url: str, ext: str = ".txt") -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[-1])[:140] + ext


def _euros(s: str) -> int:
    return int(s.replace(" ", ""))


def _verifie(text: str) -> str | None:
    m = re.search(r"^Vérifié le (\d{1,2} \w+ \d{4}) - Service Public", text, flags=re.M)
    return m.group(1).lstrip("0") if m else None


def _link(links: list, label: str) -> str | None:
    """The URL an official page gives to a link whose text starts with `label` (https on an official host only)."""
    for text, url in links:
        if text.startswith(label) and re.match(r"https://(www\.)?[a-z.-]+\.(gouv\.fr|fr)/", url):
            return url
    return None


def _lines(text: str) -> list[str]:
    return [x.strip() for x in text.splitlines() if x.strip()]


def r_bourse(text: str, links: list) -> dict | None:
    """The table "Montant <année> de la bourse selon l'échelon": 8 échelons, increasing amounts, in the page's order."""
    L = _lines(text)
    head = next((i for i, x in enumerate(L) if re.match(r"^Tableau - Montant (\d{4}-\d{4}) de la bourse selon l'échelon", x)), None)
    if head is None:
        return None
    annee = re.match(r"^Tableau - Montant (\d{4}-\d{4})", L[head]).group(1)
    rows, i = [], head + 1
    while i < len(L) and len(rows) < len(ECHELONS):
        if L[i] == ECHELONS[len(rows)] and i + 1 < len(L) and re.fullmatch(EURO, L[i + 1]):
            rows.append({"echelon": L[i], "annuel": _euros(re.fullmatch(EURO, L[i + 1]).group(1))})
            i += 2
            continue
        i += 1
        if i > head + 30:
            break
    if len(rows) != len(ECHELONS) or any(a["annuel"] >= b["annuel"] for a, b in zip(rows, rows[1:])):
        return None
    mens = re.search(r"La bourse est versée à l'étudiant en (\d+) mensualités", text)
    om = re.search(r"les montants annuels indiqués sont majorés de " + EURO, text)
    dem = re.search(r"vous devez saisir votre demande entre (le 1 ?er \w+ et le \d{1,2} \w+ \d{4})", text)
    sim, dse = _link(links, "Étudiant : calculer votre droit à bourse"), _link(links, "Mes services étudiant : constituer son Dossier Social")
    if not (mens and om and sim and dse):
        return None
    n = int(mens.group(1))
    for r in rows:
        r["mensuel"] = round(r["annuel"] / n, 2)
    return {"annee": annee, "echelons": rows, "mensualites": n, "outre_mer": _euros(om.group(1)),
            "demande": dem.group(1).replace("1 er", "1er") if dem else None,
            "condition_etab": "L'établissement est un établissement d'enseignement public ou privé habilité à recevoir des boursiers"
            if "L'établissement est un établissement d'enseignement public ou privé habilité à recevoir des boursiers" in text else None,
            "liens": {"simulateur": sim, "dse": dse}, "verifie": _verifie(text), "source": PAGES["bourse"]}


def r_merite(text: str, links: list) -> dict | None:
    m = re.search(r"Le montant annuel de l'aide est de " + EURO, text)
    v = re.search(r"versée de \w+ à \w+ en (\d+) mensualités de " + EURO, text)
    conds = re.search(r"remplissez les 3 conditions suivantes :\n(.+)\n(.+)\n(.+)\n", text)
    if not (m and v and conds):
        return None
    montant, n, par = _euros(m.group(1)), int(v.group(1)), _euros(v.group(2))
    if n * par != montant:
        return None
    return {"montant": montant, "mensualites": n, "par_mois": par, "conditions": [conds.group(k) for k in (1, 2, 3)],
            "verifie": _verifie(text), "source": PAGES["merite"]}


def r_mobilite(text: str, links: list) -> dict | None:
    a = re.search(r"Son montant est de " + EURO, text)
    b = re.search(r"Le montant de l'aide est de " + EURO, text)
    conds = re.search(r"remplir toutes les conditions suivantes :\n(.+)\n(.+)\n(.+)\n", text)
    per = re.search(r"demande d'aide à la mobilité en ligne (à partir du 1 ?er \w+ \d{4} et jusqu'au \d{1,2} \w+ \d{4})", text)
    lien = _link(links, "Mes services étudiant : demande d’aide à la mobilité Parcoursup")
    if not (a and b and conds and lien) or a.group(1) != b.group(1):
        return None
    return {"montant": _euros(a.group(1)), "conditions": [conds.group(k) for k in (1, 2, 3)],
            "periode": per.group(1).replace("1 er", "1er") if per else None, "lien": lien,
            "verifie": _verifie(text), "source": PAGES["mobilite"]}


IDF_ACADEMIES = ("Créteil", "Paris", "Versailles")        # the Île-de-France academic region (the complement's condition)


def r_mobilite_mesr(text: str, links: list) -> dict | None:
    """The ministry's own page: the same 500 € (cross-check) and the complement for bac pro boursiers of Île-de-France."""
    a = re.search(r"Il s'agit d'une aide financière de " + EURO + r" pour les futurs étudiants qui bénéficient d'une bourse de lycée", text)
    c = re.search(r"^Un complément de " + r"(\d{1,3}(?: \d{3})*|\d+)\s*€" + r" peut être accordé aux lycéens boursiers titulaires d’un baccalauréat "
                  r"professionnel résidant en Île-de-France[^\n]*", text, flags=re.M)
    if not a:
        return None
    return {"montant": _euros(a.group(1)), "complement_bp_idf": _euros(c.group(1)) if c else None,
            "complement_texte": c.group(0).replace(" ,", ",") if c else None, "academies_idf": list(IDF_ACADEMIES),
            "source": PAGES["mobilite_mesr"]}


def r_droits(text: str, links: list) -> dict | None:
    """The year's national tariffs (every amount of the official tables "Montant des droits d'inscription ...") and the
    boursiers' exemption sentence."""
    y = re.search(r"^Frais d'inscription pour l'année (\d{4}-\d{4})$", text, flags=re.M)
    ex = "Si vous êtes boursier du gouvernement français ou pupille de la nation, vous êtes exonérés des droits d'inscription."
    if not y or ex not in text:
        return None
    tarifs, inside = set(), False
    for x in _lines(text):
        if x.startswith("Tableau - Montant des droits d'inscription"):
            inside = True
            continue
        if inside and x.startswith("Tableau - ") and "droits d'inscription" not in x:
            inside = False
        if x in ("Transfert d'inscription", "Règlement", "Exonération des droits d'inscription"):
            inside = False                     # the next section of the page: the tables are over
        if inside:
            m = re.fullmatch(EURO, x)
            if m:
                tarifs.add(_euros(m.group(1)))
    if not tarifs:
        return None
    bts = "L'inscription dans un BTS public ne donne pas lieu au paiement de droits d'inscription." in text
    return {"annee": y.group(1), "tarifs": sorted(tarifs), "exoneration": ex, "bts_public_gratuit": bts,
            "verifie": _verifie(text), "source": PAGES["droits"]}


def r_cvec(text: str, links: list) -> dict | None:
    m = re.search(r"L'acquittement est actuellement possible pour l'année universitaire (\d{4}-\d{4})\. Elle est de " + EURO, text)
    ex = re.search(r"^Les boursiers ou bénéficiaires d'une allocation annuelle[^\n]*", text, flags=re.M)
    lien = _link(links, "Demander mon exonération")
    if not (m and ex):
        return None
    return {"annee": m.group(1), "montant": _euros(m.group(2)), "exoneration": ex.group(0), "lien": lien or PAGES["cvec"],
            "source": PAGES["cvec"]}


def r_repas(text: str, links: list) -> dict | None:
    m = re.search(r"À partir du (\d{1,2} \w+ \d{4}), l[’']Etat propose un repas à tarif très social à tous les étudiants, à hauteur de "
                  + EURO, text)
    if not m:
        return None
    return {"depuis": m.group(1), "prix": _euros(m.group(2)), "source": PAGES["repas"]}


def r_regions(text: str, links: list) -> dict | None:
    s = "Les dossiers concernant les aides pour les formations sanitaires et sociales sont gérés par les régions."
    return {"texte": s, "source": PAGES["regions"]} if s in text else None


def r_logement(text: str, links: list) -> dict | None:
    sim = _link(links, "Calculer son droit à une aide personnelle au logement")
    if not sim or "aide personnelle au logement" not in text:
        return None
    return {"simulateur": sim, "verifie": _verifie(text), "source": PAGES["logement"]}


def r_ifsi_fpc(text: str, links: list) -> dict | None:
    """The page's own sentence on the continuing-education route into an IFSI, verbatim (one sentence naming both
    « formation professionnelle continue » and « hors Parcoursup »); never rewritten, never a condition of our own."""
    for line in _lines(text):
        m = re.search(r"[^.!?]*formation professionnelle continue[^.!?]*hors Parcoursup[^.!?]*[.!?]", re.sub(r"\s+", " ", line))
        if m:
            return {"texte": m.group(0).strip(), "source": PAGES["ifsi_fpc"]}
    return None


# PR 18 (owner, 2026-11-28): the apprentice's minimum pay QUOTED from the official table, never computed. The table « Rémunération
# brute mensuelle minimale d'un apprenti »: 4 age columns, then each contract year and its 4 cells, verbatim (format only: the page's
# « : titleContent » glossary markers dropped, spaces inside brackets closed). Fixed checks: 3 years in order, every cell names the
# Smic, the percentages rise with the year in the first three columns and never fall with the age. The contract: the page's own two
# sentences (a work contract; the alternation with the employer the apprentice signed with). Links: the page's own.
APPRENTI_AGES = re.compile(r"^(?:\d{2} à \d{2} ans|\d{2}-\d{2} ans|\d{2} ans et plus)$")
APPRENTI_ANNEE = re.compile(r"^(\d) (?:re|e) année$")
APPRENTI_NOTES = (r"^Les jeunes apprentis de moins de 16 ans\b", r"^L'apprenti préparant une licence professionnelle\b",
                  r"^Ces montants peuvent être majorés\b")
APPRENTI_CONTRAT = (r"^Le contrat d'apprentissage est un contrat de travail\b[^.]*\.",
                    r"^L'apprentissage repose sur le principe de l'alternance\b[^.]*signé son contrat de travail\.")


def _clean(s: str) -> str:
    s = re.sub(r"\s*:\s*titleContent\b", "", s)
    s = re.sub(r"\b(\d) (re|e) (année|cycle)\b", r"\1\2 \3", s)      # the page's superscripts, read as « 2 e année »
    s = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", s))
    return re.sub(r"\s+", " ", s).strip()


def _pcts(cell: str) -> list[int]:
    return [int(x) for x in re.findall(r"(\d{1,3}) % du (?:Smic|salaire)", cell)]


def r_apprenti(text: str, links: list) -> dict | None:
    L = _lines(text)
    head = next((i for i, x in enumerate(L) if x.startswith("Tableau - Rémunération brute mensuelle minimale d'un apprenti")), None)
    if head is None:
        return None
    ages = []
    i = head + 1
    while i < len(L) and APPRENTI_AGES.match(L[i]):
        ages.append(L[i])
        i += 1
    if len(ages) != 4:
        return None
    annees = []
    while i < len(L) and len(annees) < 3:
        m = APPRENTI_ANNEE.match(L[i])
        if not m or int(m.group(1)) != len(annees) + 1:
            return None
        cells, i = [], i + 1
        # a line naming a percentage starts a cell; a line without one continues the cell above (the 26-and-over cell prints
        # « 100 % du Smic », then « Salaire le + élevé entre le Smic … »)
        while i < len(L) and not APPRENTI_ANNEE.match(L[i]) and "Smic" in L[i] and len(cells) <= len(ages):
            if _pcts(L[i]) or not cells:
                cells.append([_clean(L[i])])
            else:
                cells[-1].append(_clean(L[i]))
            i += 1
        if len(cells) != len(ages):
            return None
        annees.append({"annee": f"{m.group(1)}{'re' if m.group(1) == '1' else 'e'} année", "cellules": cells})            # each cell: its printed lines
    if len(annees) != 3:
        return None
    pct = [[_pcts(c[0])[0] for c in a["cellules"]] for a in annees]
    for col in range(3):                      # the first three columns rise with the year
        if not pct[0][col] < pct[1][col] < pct[2][col]:
            return None
    if any(row[j] > row[j + 1] for row in pct for j in range(len(row) - 1)):
        return None                           # never less for an older apprentice
    notes = [_clean(x) for x in L[i:i + 12] for pat in APPRENTI_NOTES if re.match(pat, x)]
    contrat = []
    for pat in APPRENTI_CONTRAT:
        m = next((re.match(pat, x) for x in L if re.match(pat, x)), None)
        if not m:
            return None
        contrat.append(_clean(m.group(0)))
    return {"titre": "Rémunération brute mensuelle minimale d'un apprenti", "ages": ages, "annees": annees, "notes": notes,
            "contrat": contrat, "entreprises": _link(links, "Trouver une entreprise qui recrute en alternance"),
            "simulateur": _link(links, "Estimer le salaire d'un salarié en contrat d'apprentissage"),
            "verifie": _verifie(text), "source": PAGES["apprenti"]}


# Items whose official host refuses robots (lot 1, PR 12, owner 2026-11-26): their page is never fetched around that refusal (no
# copy, no other host); the item stays out and its card hidden until the page is read (the fetcher keeps asking it, or the owner
# commits it). A WAITING item whose page exists is read by its rule like any other: a page that no longer matches is said.
EN_ATTENTE = {"ifsi_fpc": "parcoursup.gouv.fr refuse les robots : la carte attend la page officielle"}

RULES = {"bourse": r_bourse, "merite": r_merite, "mobilite": r_mobilite, "mobilite_mesr": r_mobilite_mesr, "droits": r_droits, "cvec": r_cvec,
         "repas": r_repas, "regions": r_regions, "logement": r_logement, "ifsi_fpc": r_ifsi_fpc,
         "apprenti": r_apprenti}


def read(d: Path = DIR) -> dict:
    """Every item read from its official page by its rule; `audit` names the items whose page is missing or did not match."""
    out, audit = {}, []
    for key, rule in RULES.items():
        f = d / _file(PAGES[key])
        if not f.exists():
            out[key] = None
            audit.append(f"{key}: waiting ({EN_ATTENTE[key]})" if key in EN_ATTENTE else f"{key}: page not fetched")
            continue
        lf = d / _file(PAGES[key], ".links.json")
        links = json.loads(lf.read_text()) if lf.exists() else []
        try:
            out[key] = rule(f.read_text(), links)
        except Exception as e:  # noqa: BLE001  (a changed page leaves the item out, said in the audit)
            out[key] = None
            audit.append(f"{key}: {type(e).__name__}")
            continue
        if out[key] is None:
            audit.append(f"{key}: the rule no longer matches the official page")
    log = d / "fetch_log.json"
    out["lu_le"] = max((r.get("fetched", "")[:10] for r in json.loads(log.read_text()) if r.get("status") == 200), default=None) \
        if log.exists() else None
    out["audit"] = audit
    return out


def build(con, d: Path = DIR) -> dict:
    """core.aides: the items read (one JSON value; a few kilobytes)."""
    data = read(d) if d.exists() else {"audit": ["data/aides missing"]}
    con.execute("CREATE OR REPLACE TABLE core.aides (data VARCHAR)")
    con.execute("INSERT INTO core.aides VALUES (?)", [json.dumps(data, ensure_ascii=False)])
    return {"items": sum(1 for k in RULES if data.get(k)), "audit": data.get("audit", [])}


def national(con) -> dict | None:
    try:
        r = con.execute("SELECT data FROM core.aides").fetchone()
    except Exception:  # noqa: BLE001  (a warehouse built before sprint F)
        return None
    return json.loads(r[0]) if r else None


def droits_exoneres(statut: str, frais: int | None, tarifs: list) -> bool | None:
    """The fixed rule: a boursier pays no fee when the establishment is PUBLIC and the fiche's yearly fee is 0 or a national
    tariff of the official table; None (unknown) otherwise: the fee may be the establishment's own."""
    if frais is None or statut != "public":
        return None
    return True if frais == 0 or frais in set(tarifs or ()) else None


def for_formation(con, cod: str, vie: dict | None) -> dict | None:
    """The aids block of one formation: the national items, adapted to its place (overseas majoration, sanitary-social
    route, public or private establishment) and its fees (`vie`, the cost card already computed)."""
    A = national(con)
    if not A or not any(A.get(k) for k in RULES):
        return None
    f = con.execute("""SELECT fili, contrat_etab, dep, acad_mies FROM core.formation_year WHERE cod_aff_form = ?
        ORDER BY session DESC LIMIT 1""", [cod]).fetchone()
    if not f:
        return None
    fili, contrat, dep, acad = f
    from .carte import statut_of
    statut = statut_of(contrat)
    out = {k: A.get(k) for k in ("merite", "mobilite", "cvec", "repas", "logement", "droits")}
    mm = A.get("mobilite_mesr")
    if out["mobilite"] and mm and mm["montant"] == out["mobilite"]["montant"] and mm.get("complement_bp_idf"):
        out["mobilite"] = {**out["mobilite"], "complement_bp_idf": mm["complement_bp_idf"], "complement_texte": mm["complement_texte"],
                           "academies_idf": mm["academies_idf"], "complement_source": mm["source"]}
    out.update({"statut": statut, "academie": acad, "lu_le": A.get("lu_le"), "sanitaire_social": None, "bourse": None,
                "outre_mer": bool(dep and str(dep).startswith(OUTRE_MER)), "droits_exoneres": None, "annuel_boursier": None})
    out["ifsi_fpc"] = A.get("ifsi_fpc") if fili == "IFSI" else None       # lot 1, PR 12: the official route for professionals
    if fili in SANITAIRE_SOCIAL:
        out["sanitaire_social"] = A.get("regions")      # the Region, not the Crous: no Crous table
    elif A.get("bourse"):
        b = dict(A["bourse"])
        if out["outre_mer"]:
            maj = b["outre_mer"]
            b["echelons"] = [{**e, "annuel": e["annuel"] + maj, "mensuel": round((e["annuel"] + maj) / b["mensualites"], 2)}
                             for e in b["echelons"]]
            b["majoree"] = maj
        out["bourse"] = b
    fr = (vie or {}).get("frais") or {}
    an = (vie or {}).get("annuel")
    if A.get("droits"):
        out["droits_exoneres"] = droits_exoneres(statut, fr.get("montant"), A["droits"]["tarifs"])
    m = (vie or {}).get("mensuel")
    if an and m and A.get("cvec"):
        from .vie import MOIS_PAR_AN, _arrondi
        frais = 0 if out["droits_exoneres"] else an["frais"]          # the CVEC is never counted: boursiers are exempt
        out["annuel_boursier"] = {"min": _arrondi(MOIS_PAR_AN * m["min"] + frais), "max": _arrondi(MOIS_PAR_AN * m["max"] + frais),
                                  "frais": frais, "frais_gardes": not out["droits_exoneres"]}
    return out
