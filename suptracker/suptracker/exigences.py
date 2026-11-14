"""What each Parcoursup fiche WRITES about specialties, and what it writes about setting a file aside (owner, 2026-11-14).

The owner asked whether a pair of specialties (Maths + SES in a scientific CPGE...) is accepted by each formation's jury, and
for its elimination criteria. Data check (24,826 fiches read by the grids harvest, 2026-11-14):
  * only ~140 formations write that a specialty or an option MUST have been followed (9 of 124 MPSI fiches); most fiches only
    say what the jury reads (31 MPSI grids rate physics results "Essentiel", many add "selon la situation du candidat");
  * the wording is free: "obligatoire", "indispensable", "il faut avoir suivi", alternatives ("spécialité ou option maths
    complémentaires", "soit ... soit ..."), negations ("nullement obligatoire", "n'est pas un prérequis"), and many sentences
    where the strong word is about a LEVEL ("un bon niveau en physique est requis"), not a choice of specialty;
  * so this module never says "accepted" or "refused": it QUOTES the sentences, verbatim, and marks with fixed rules the ones
    that write a specialty requirement. The rules are measured against a hand-labelled set (GOLD), at build, and the page
    prints that measure. The only factual answer to "is my pair taken here" stays the published counts (own report line,
    similar formations, national group), shown beside.

Rules (fixed, on a normalised copy of the text of the SAME length, so every index points into the original):
  * a sentence is about specialties when it names one: specialty names (physique-chimie, SVT, SES, HGGSP, HLP, LLCER, LLCA,
    NSI, SI, biologie-écologie, EPPCS, arts) or the options (maths expertes, maths complémentaires); "mathématiques" alone only
    with a specialty word in the sentence (maths are also a common-core subject). Short codes ("SI", "SES") must be written in
    capitals (they are French words) and not inside a capitalised sentence; a name right after "licence", "BUT", "parcours"...
    is the formation's name, not a specialty; "condition physique" is not physics;
  * mentions joined by "ou", "/", "et/ou", "," are ALTERNATIVES (one group): a group is met when the student has one of them;
  * each group reads its class from the words around it (after it first, then before it): a negation ("non obligatoire",
    "n'est pas un prérequis", "nullement", "sans qu'elle soit indispensable"...) = non exigée (conseillée when advice words
    are there too); a requirement word with a CHOICE word in the sentence (spécialité, avoir suivi, le suivi de, option, EDS...)
    or written right after the name ("Physique-chimie obligatoire") = exigée, unless the strong word is about a level
    ("niveau", "compétences", "résultats"... before the name); advice words = conseillée; else citée;
  * the year: "en première" / "en terminale" / both, read around the group.
Elimination sentences: a fixed list of words ("éliminatoire", "ne sera pas classé", "non recevable"...), negations out
("n'est pas éliminatoire", "aucun seuil"), quoted verbatim, never counted or scored.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

GOLD = Path(__file__).resolve().parents[1] / "data" / "exigences_gold.csv"

SPE_LABELS = {
    "MATHS": "Mathématiques", "PC": "Physique-chimie", "SVT": "SVT", "SES": "SES", "HGGSP": "HGGSP", "HLP": "HLP",
    "LLCER": "LLCER", "LLCA": "LLCA", "NSI": "NSI", "SI": "Sciences de l'ingénieur", "BIOECO": "Biologie-écologie",
    "EPPCS": "EPPCS", "ART": "Arts", "MATHS_EXP": "option Maths expertes", "MATHS_COMP": "option Maths complémentaires",
}
OPTIONS = ("MATHS_EXP", "MATHS_COMP")


def _c(ch: str) -> str:
    if ch in "’‘`´":
        return "'"
    a = unicodedata.normalize("NFKD", ch.lower()).encode("ascii", "ignore").decode()
    return a[:1] if a else " "


def norm(s: str) -> str:
    """Lower case, no accents, one character per character: indexes in the result are indexes in `s`."""
    return "".join(_c(ch) for ch in s)


SPE = [
    ("MATHS_EXP", r"math(?:ematique)?s?\.? expertes?"),
    ("MATHS_COMP", r"math(?:ematique)?s?\.? complementaires?"),
    ("PC", r"physique[- ]?(?:et )?[- ]?chimie|sciences?[- ]physiques?|\bspe(?:cialite)?s?\.? (?:en )?physique|\bphysique\b"),
    ("SVT", r"\bsvt\b|sciences? de la vie(?: et de la terre)?"),
    ("SES", r"\bses\b|sciences? economiques?(?: et sociales?)?"),
    ("HGGSP", r"\bhggsp\b|geopolitique"),
    ("HLP", r"\bhlp\b|humanites"),
    ("LLCER", r"\bllcer?\b|langues?,? litteratures? et cultures? etrangeres"),
    ("LLCA", r"\bllca\b|cultures? de l'antiquite"),
    ("NSI", r"\bnsi\b|numerique et sciences? (?:de l')?informatiques?"),
    ("SI", r"sciences? (?:de l'|pour l')ingenieur|\bsii?\b"),
    ("BIOECO", r"biologie[- /]?(?:et )?ecologie"),
    ("EPPCS", r"\beppcs\b|education physique,? pratiques"),
    ("ART", r"arts? plastiques|cinema[- ]audiovisuel|histoire des arts|arts du cirque|specialite (?:arts?|musique|theatre|danse)"),
    ("MATHS", r"\bmath(?:ematique)?s?\b"),
]
SPE_RE = [(k, re.compile(p)) for k, p in SPE]
SHORT = {"SI", "SES", "SVT", "NSI", "HLP", "LLCE", "LLCER", "LLCA"}
NAMEOF = re.compile(r"(?:licence|mention|parcours|portail|\bbut|\bbts|master|\bl1|filiere|cursus|formation|departement|cpge|"
                    r"classe|bachelor|diplome|dut|\blas)s?\s+(?:en |de |d'|des )?(?:[\w'-]+ (?:et |- )?){0,3}$")
NOT_PHYSICS = re.compile(r"(?:preparation|condition|aptitude|activites?|education|contre-indication|culture|sante|epreuves?|"
                         r"exercice|pratique|aisance) $")
CONTEXT = re.compile(r"\bspe\b|\bspe\.|specialite|doublette|\beds\b|enseignements? de spe|\boption")

NEG = re.compile(
    r"(?:nullement|aucunement|pas forcement|pas necessairement|pas du tout|sans (?:qu'(?:elle|il|elles|ils) (?:n')?\w+ |etre )|"
    r"meme si)[^.;]{0,60}(?:obligatoire|indispensable|exige|requis|necessaire|prerequis|garde|suivi)"
    r"|\b(?:non|pas|ni|aucune?)\b(?: forcement| necessairement| obligatoirement| un| de| le| la| une| d'| du| des| est| sont|"
    r" soit| soient| etre| attendu)*\s*(?:obligatoire|indispensable|exige|requis|necessaire|prerequis|pre-requis|pre requis|"
    r"imperati|eliminatoire|discriminant|bloquant)"
    r"|ne (?:sont|soit|soient|est|sera|seront|constitue|constituent)\s+(?:pas|en aucun cas)\s+(?:\w+\s+){0,2}"
    r"(?:obligatoire|indispensable|exige|requis|necessaire|prerequis|pre-requis|eliminatoire|discriminant|bloquant)"
    r"|n'est pas (?:\w+\s+){0,2}(?:obligatoire|indispensable|exige|requis|necessaire|un prerequis|eliminatoire)"
    r"|(?:obligatoire|indispensable|exige|requis|necessaire)s?\)? ?(?:n'est|ne sont) pas|ni necessaire")
STRONG = re.compile(
    r"(?<!optionnelles ou )(?<!facultatives ou )obligatoire|indispensable|\b(?:est|sont|seront?|il est) (?:\w+ )?exigee?s?\b"
    r"|\bexigeons\b|\bexige(?:ons)? (?:la|les|une|un|des) (?:spe|option|enseignement)|\brequise?s?\b|imperati|sine qua non"
    r"|\bnecessaire d'avoir|\bnecessaire de (?:suivre|prendre|choisir|conserver|garder|faire|maintenir)"
    r"|(?:est|sont) (?:donc |tres |absolument |vraiment )?necessaires?"
    r"|specialites? (?:\w+ )?(?:necessaires?|obligatoires?|requises?|exigees?|indispensables?)"
    r"|(?:est|sont) (?:un |des )?pre-?requis|doi(?:t|vent) (?:avoir )?(?:suivi|choisi|pris|fait|etre combinee?)"
    r"|il faut (?:avoir )?(?:suivi|choisi|pris|fait|conserver|garder)|reservee?s? aux|uniquement (?:ouvert|accessible)e?s? aux"
    r"|\bessentielle\b|seule?s? (?:les )?(?:candidat|eleve|dossier)s? (?:ayant|qui ont)|n'est pas suffisante?")
SOFT = re.compile(r"conseill|recommand|souhait|apprecie|privilegi|preferen|\batout|un plus|valoris|bonus|bienvenu|favoris|"
                  r"encourag|utile")
CHOICE = re.compile(
    r"\ble suivi d|\bchoix d|presence d|\bspe\b|\bspe\.|specialite|\beds\b|\boption|enseignements? de spe"
    r"|(?:avoir|ayant|aient|ont) (?:\w+ )?(?:suivi|choisi|pris|garde|conserve|fait)"
    r"|\b(?:suivre|choisir|prendre|garder|conserver|maintenir) (?:la |les |l'|le |une |un |des )?"
    r"(?:spe|specialite|enseignements? de spe|option|math|physique|sciences|svt|ses|nsi)|doublette|triplette")
DIRECT = re.compile(r"^\W{0,3}(?:\)|\(|,|\s|est|sont|donc|en premiere|en terminale|et en terminale|en 1ere|en tle)*\s*\(?"
                    r"(?:obligatoire|indispensable|requise?|exigee?|necessaire)")
HEAD = re.compile(r"(?:travail|niveau|appetence|interet|competences?|connaissances?|bases?|socle|maitrise|resultats|aisance|"
                  r"aptitudes?|notions|preparation|condition|qualites|outils|acquis|bagage|formation scientifique|serieux|"
                  r"de les expliquer|d'expliquer|de justifier)[^.;\u2014]{0,45}$")
HEADN = re.compile(r"(?:niveau|competences?|connaissances?|resultats|maitrise|aptitudes?|bases?|socle|notions|appetence|interet|"
                   r"travail|outils|disciplines scientifiques)\b[^.;\u2014]{0,140}$")
LEVEL_ONLY = re.compile(r"^\s*\(?(?:obligatoire|obligatoirement|indispensable)\)(?!\s*et)")
CHOSEN = re.compile(r"(?:specialite|\bspe|\beds|option)s?\W{0,3}(?:de |d'|en |\w+ )?$|le suivi d|avoir suivi|choix d|presence d")
PREREQ = re.compile(r"pre-?requis necessaires? \(")
JOIN = re.compile(r"\s*(?:\)|\()?\s*(?:,|/|ou|ou bien|voire|et/ou|\+?\s*ou)\s*(?:la |le |les |l'|en |de |d'|du |l'option |option |"
                  r"spe(?:cialite)?s?\.? |enseignement de spe(?:cialite)? )*\s*")
COND = re.compile(r"\b(?:lorsque|lorsqu'|quand|si|en cas d'|dans le cas d[eu']?)\s*(?:la |le |les |l'|une |un |de la |des )?(?:\w+ ){0,3}$")
STOP = re.compile(r",|;|\bmais\b|\bet (?:il|elle|ils|elles|c'|ce)\b|\bcar\b")
YEAR1 = re.compile(r"\b(?:premiere|1ere|1re|1°)")
YEART = re.compile(r"\b(?:terminale|tle|tale)s?\b")
SPLIT = re.compile(r"(?<=[.!?;:])\s+|\n+|\s+-\s+|\s*[•¤]\s*|(?<=\))\s+(?=[A-ZÉ])")

ELIM = re.compile(
    r"eliminatoire|\belimine|ne (?:sera|seront|pourra|pourront) pas (?:etre )?(?:retenu|examine|classe|etudie|admis|recevable)"
    r"|non recevable|irrecevable|pas recevable|ne sont pas (?:retenu|examine|classe|etudie)|seront (?:systematiquement )?ecarte"
    r"|sera (?:systematiquement )?ecarte|(?:dossiers?|candidatures?|voeux?) (?:\w+ )?(?:sera|seront|est|sont) refuse"
    r"|note minimale|moyenne minimale|minimum de \d|au moins \d+ ?/ ?20|seuil (?:de|minimum)")
ELIM_NEG = re.compile(r"(?:n'est|ne sont|ne seront|ne sera|n'a|n'ont) (?:\w+ )?(?:pas|jamais|en aucun cas) (?:\w+ )?"
                      r"(?:eliminatoire|discriminant)|pas eliminatoire|non eliminatoire|aucun(?:e)? (?:seuil|note|critere) "
                      r"(?:\w+ )?eliminatoire|pas de seuils?|aucun seuil|sans seuil|ne sont pas forcement eliminatoire")


def sentences(t: str | None) -> list[str]:
    return [s.strip() for s in SPLIT.split(t or "") if s and s.strip()]


def mentions(s: str) -> tuple[list[tuple[int, int, str]], str]:
    ns = norm(s)
    taken = [False] * len(ns)
    letters = [ch for ch in s if ch.isalpha()]
    capital = bool(letters) and sum(ch.isupper() for ch in letters) > 0.5 * len(letters)
    out = []
    for k, rx in SPE_RE:
        for m in rx.finditer(ns):
            a, b = m.start(), m.end()
            if any(taken[a:b]):
                continue
            raw = s[a:b]
            if len(raw) <= 5 and raw.strip(".").upper() in SHORT and (raw != raw.upper() or capital):
                continue                                  # "si", "ses": French words; a capitalised sentence
            nm = NAMEOF.search(ns[max(0, a - 45):a])
            if nm and not re.search(r"specialite|\bspe\b|option|enseignement", nm.group(0)):
                continue                                  # "licence Physique-Chimie": the formation's name
            if k == "PC" and ns[a:b] == "physique" and NOT_PHYSICS.search(ns[max(0, a - 30):a]):
                continue
            if k == "PC" and ns[b:b + 14] == " pour la sante":
                continue                                  # "physique-chimie pour la santé": the ST2S specialty
            for i in range(a, b):
                taken[i] = True
            out.append((a, b, k))
    return sorted(out), ns


def _strong(seg: str) -> bool:
    return any(not HEAD.search(seg[:m.start()]) for m in STRONG.finditer(seg))


def _classify(seg: str, ns: str) -> str:
    if NEG.search(seg):
        return "conseillee" if SOFT.search(seg) else "non_exigee"
    if DIRECT.match(seg):
        return "exigee"                                   # "Spé maths obligatoire", "Physique-chimie (indispensable)"
    if _strong(seg):
        return "exigee" if CHOICE.search(ns) else "citee"
    if SOFT.search(seg):
        return "conseillee"
    return "citee"


def _year(seg: str) -> str | None:
    """premiere / terminale / les_deux; "première et/ou terminale" (either year) reads as "l_une" (not checkable)."""
    a, b = YEAR1.search(seg), YEART.search(seg)
    if a and b:
        mid = seg[min(a.end(), b.end()):max(a.start(), b.start())]
        return "l_une" if re.search(r"\bou\b|/ou", mid) else "les_deux"
    return "premiere" if a else "terminale" if b else None


def statements(s: str) -> list[dict]:
    """The specialty groups a sentence names, each with its class (exigee / conseillee / non_exigee / citee) and year."""
    ms, ns = mentions(s)
    if not ms:
        return []
    if not (CONTEXT.search(ns) or any(k != "MATHS" for _a, _b, k in ms)):
        return []
    groups: list[list] = []
    for i, (a, b, k) in enumerate(ms):
        if groups and JOIN.fullmatch(ns[ms[i - 1][1]:a]):
            groups[-1][2].append(k)
            groups[-1][1] = b
        else:
            groups.append([a, b, [k]])
    out = []
    for i, (a, b, ks) in enumerate(groups):
        prev_end = groups[i - 1][1] if i else 0
        next_start = groups[i + 1][0] if i + 1 < len(groups) else len(ns)
        fwd = ns[b:min(next_start, b + 80)]
        back = ns[max(prev_end, a - (160 if not i else 80)):a]
        cf, cb = _classify(fwd, ns), _classify(back, ns)
        st = STOP.search(fwd)
        near = _classify(fwd[:min(st.start() if st else 45, 45)], ns)
        if near != "citee":
            c = near                                      # the words right after the name: "l'option maths expertes est un plus"
        elif PREREQ.search(back) and cf != "non_exigee":
            c = "exigee"
        elif cf in ("exigee", "non_exigee"):
            c = cf
        elif cb in ("exigee", "non_exigee"):
            c = cb
        elif "conseillee" in (cf, cb):
            c = "conseillee"
        else:
            c = "citee"
        before = ns[max(0, a - 160):a]
        if c == "exigee" and HEADN.search(before) and not CHOSEN.search(before) and not LEVEL_ONLY.match(fwd):
            c = "citee"                                   # "un bon niveau en physique est requis": a level, not a choice
        if c == "exigee" and COND.search(ns[max(0, a - 40):a]):
            c = "citee"                                   # "lorsque la spécialité SVT est suivie, celle-ci doit...": a condition
        out.append({"spe": sorted(set(ks)), "classe": c, "annee": _year(fwd) or _year(back) or _year(ns[max(0, a - 80):a])})
    return out


def requirement(s: str) -> bool:
    """Does the sentence write that a specialty (or an option, or one of several) must have been followed?"""
    return any(x["classe"] == "exigee" for x in statements(s))


def elimination(s: str) -> bool:
    ns = norm(s)
    return bool(ELIM.search(ns)) and not ELIM_NEG.search(ns)


def read_gold(path: Path = GOLD) -> list[tuple[str, bool]]:
    if not path.exists():
        return []
    return [(r["phrase"], r["exige"] == "1") for r in csv.DictReader(open(path, encoding="utf-8"))]


def measure(gold: list[tuple[str, bool]] | None = None) -> dict:
    """Precision and recall of `requirement` on the hand-labelled sentences (every sentence of the 2026-11-14 harvest that
    names a specialty AND carries a requirement word, labelled by reading: does it write that a specialty, an option or one
    of several must have been followed?)."""
    gold = read_gold() if gold is None else gold
    tp = fp = fn = 0
    for s, g in gold:
        p = requirement(s)
        tp += p and g
        fp += p and not g
        fn += g and not p
    return {"n": len(gold), "positifs": tp + fn, "lus_exiges": tp + fp, "justes": tp,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None, "rappel": round(tp / (tp + fn), 3) if tp + fn else None}


# ---- build and serving -------------------------------------------------------------------------------------------------------
SOURCES = (("complementaires", "Attendus de la formation"), ("conseils", "Conseils aux candidats"), ("info", "Candidater"))


def _phrases(text: str | None, src: str, champ: str | None = None, critere: str | None = None, importance: int | None = None):
    for s in sentences(text):
        st = statements(s)
        el = elimination(s)
        if not st and not el:
            continue
        ms, _ns = mentions(s) if st else ([], "")
        yield {"src": src, "champ": champ, "critere": critere, "importance": importance, "texte": s,
               "groupes": st, "marques": [[a, b, k] for a, b, k in ms], "ecarter": el}


def read_formation(g: dict, texts: dict) -> list[dict]:
    """Every sentence of one fiche (grilles.assemble row, texts by id) that names a specialty or writes about setting a file
    aside, in the fiche's order: its own expectations, the advice, the notice, then the grid's criteria."""
    out = []
    for key, _label in SOURCES:
        out += list(_phrases(texts.get(g.get(key)), key))
    for ch in g.get("champs") or []:
        for k in ch["criteres"]:
            lab = texts.get(k["critere"]) or ""
            out += list(_phrases(lab, "critere", ch["champ"], lab, k["importance"]))
            out += list(_phrases(texts.get(k["elements"]), "critere", ch["champ"], lab, k["importance"]))
    seen, uniq = set(), []
    for p in out:                                         # one sentence once per fiche (a text repeated in two places)
        if p["texte"] not in seen:
            seen.add(p["texte"])
            uniq.append(p)
    return uniq


def required_groups(phrases: list[dict]) -> list[dict]:
    """The groups the fiche writes as required, each once: {spe: [alternatives], annee}."""
    seen, out = set(), []
    for p in phrases:
        for x in p["groupes"]:
            if x["classe"] == "exigee":
                key = (tuple(x["spe"]), x["annee"])
                if key not in seen:
                    seen.add(key)
                    out.append({"spe": x["spe"], "annee": x["annee"]})
    return out


def build(con, textes: Path | None = None, src: Path | None = None) -> dict:
    """core.fiche_exigence (the groups each fiche writes as required, JSON: what the lists read), core.exigence_mesure (the
    rules measured against GOLD, at build), and the quoted sentences per formation (exigence_data) in the texts file beside
    the warehouse (`textes`), like the grids; without that file (tests) they stay in core."""
    import json

    from . import grilles as GR
    src = GR.FICHES if src is None else src
    con.execute("CREATE SCHEMA IF NOT EXISTS core")
    con.execute("CREATE OR REPLACE TABLE core.fiche_exigence (cod_aff_form VARCHAR, session INTEGER, exige VARCHAR)")
    m = measure()
    con.execute("""CREATE OR REPLACE TABLE core.exigence_mesure (n INTEGER, positifs INTEGER, lus_exiges INTEGER, justes INTEGER,
        precision DOUBLE, rappel DOUBLE)""")
    con.execute("INSERT INTO core.exigence_mesure VALUES (?, ?, ?, ?, ?, ?)",
                [m["n"], m["positifs"], m["lus_exiges"], m["justes"], m["precision"], m["rappel"]])
    con.execute("DROP TABLE IF EXISTS core.exigence_data")
    rows, used, _audit = GR.assemble(src) if src is not None and (src / "etat.csv").exists() else ([], {}, [])
    data, req = [], []
    for g in rows:
        ph = read_formation(g, used)
        if not ph:
            continue
        data.append((g["cod_aff_form"], json.dumps(ph, ensure_ascii=False)))
        r = required_groups(ph)
        if r:
            req.append((g["cod_aff_form"], g["session"], json.dumps(r, ensure_ascii=False)))
    from . import rapports as RP
    RP._insert(con, "INSERT INTO core.fiche_exigence VALUES (?, ?, ?)", req)

    def write(c, prefix):
        c.execute(f"CREATE OR REPLACE TABLE {prefix}exigence_data (cod_aff_form VARCHAR, data VARCHAR)")
        RP._insert(c, f"INSERT INTO {prefix}exigence_data VALUES (?, ?)", data)

    if textes is None or not textes.exists():
        write(con, "core.")
    else:
        import duckdb
        tc = duckdb.connect(str(textes))
        try:
            write(tc, "")
            tc.execute("CHECKPOINT")
        finally:
            tc.close()
    return {"fiches": len(data), "exigences": len(req), "mesure": m}


def mesure(con) -> dict | None:
    from . import rapports as RP
    if not RP._has(con, "core", "exigence_mesure"):
        return None
    r = con.execute("SELECT n, positifs, lus_exiges, justes, precision, rappel FROM core.exigence_mesure").fetchone()
    return dict(zip(("n", "positifs", "lus_exiges", "justes", "precision", "rappel"), r)) if r and r[0] else None


def _side(con):
    from . import rapports as RP
    if RP._has(con, "core", "exigence_data"):
        return con, "core."
    db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    f = RP.textes_path(Path(db[0])) if db and db[0] else None
    if f is None or not f.exists():
        return None, ""
    c = RP._texts_con(str(f), f.stat().st_mtime_ns).cursor()
    n = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'exigence_data'").fetchone()[0]
    return (c, "") if n else (None, "")


def for_formation(con, cod: str) -> dict | None:
    """The fiche's sentences about specialties and about setting a file aside, quoted, with the groups it writes as
    required and the measure of the rules; None when the fiche was not read or names no specialty."""
    import json
    c, prefix = _side(con)
    if c is None:
        return None
    r = c.execute(f"SELECT data FROM {prefix}exigence_data WHERE cod_aff_form = ?", [cod]).fetchone()
    if not r:
        return None
    ph = json.loads(r[0])
    return {"phrases": ph, "exige": required_groups(ph), "mesure": mesure(con)}


def listing(con) -> dict:
    """What the lists read (search, map, Mes vœux, the specialties page): per formation, the groups its fiche writes as
    required, with its type and establishment (latest SIES campaign); per type, how many fiches were read. No parameter:
    the student's pair stays in the browser, which reads the groups itself (page twin `exigeManque`)."""
    import json

    from . import rapports as RP
    out = {"mesure": mesure(con), "formations": {}, "lues": {}}
    if not RP._has(con, "core", "fiche_exigence"):
        return out
    last = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    for cod, exige, t, e in con.execute("""SELECT x.cod_aff_form, x.exige, f.fil_lib_voe_acc, f.g_ea_lib_vx FROM core.fiche_exigence x
            LEFT JOIN core.formation_year f ON f.cod_aff_form = x.cod_aff_form AND f.session = ? ORDER BY x.cod_aff_form""",
                                        [last]).fetchall():
        out["formations"][cod] = {"exige": json.loads(exige), "type": t, "etab": e}
    if RP._has(con, "core", "fiche_grille"):
        out["lues"] = dict(con.execute("""SELECT f.fil_lib_voe_acc, count(*) FROM core.fiche_grille g JOIN core.formation_year f
            ON f.cod_aff_form = g.cod_aff_form AND f.session = ? GROUP BY 1""", [last]).fetchall())
    return out


def missing(groups: list[dict], pair: tuple[str, str], maths_expertes: bool = False) -> list[dict]:
    """The required groups a terminale pair does NOT meet (page twin `exigeManque`). A group is met when the pair holds one of
    its specialties; Maths expertes is read from the profile (only with Maths); Maths complémentaires is unknown (met when the
    pair has Maths: it is the option of those who dropped them); a group written for première only is never read (the profile
    holds the terminale pair). Never a refusal: what the page then says is "à lire"."""
    out = []
    for g in groups:
        if g.get("annee") in ("premiere", "l_une"):
            continue
        vals = []
        for k in g["spe"]:
            if k == "MATHS_EXP":
                vals.append(bool(maths_expertes) and "MATHS" in pair)
            elif k == "MATHS_COMP":
                vals.append(True if "MATHS" in pair else None)
            else:
                vals.append(k in pair)
        if True in vals or None in vals:
            continue
        out.append(g)
    return out
