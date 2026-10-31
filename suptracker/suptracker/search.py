"""Student-grade formation search.

An in-memory index over the latest campaign of every lineage (about 15k documents),
built once per warehouse. A query goes through five steps:

1. Normalisation, applied identically to documents and queries: accents and case are
   folded, dotted acronyms are collapsed ("I.U.T" -> "iut"), "st"/"ste" become
   "saint"/"sainte", and plurals and feminine forms are lightly stemmed
   ("infirmières" -> "infirmier").
2. Phrases: student phrasings ("sciences po", "prépa HEC", "école d'ingé") become
   single tag tokens. Documents carry the same tags, derived deterministically from
   their official labels (NDRC, GEA, MPSI, hypokhâgne, ...).
3. Place: the longest town / département / académie / region name in the query
   becomes a filter instead of a free-text word.
4. Matching: every remaining term must match (exact, then prefix, then one or two
   typos). Terms are weighted by field (tag > label > establishment > place) and by
   IDF. If nothing matches all terms, the weakest term is dropped and the results are
   flagged as partial.
5. Notes: professions entered through another programme (médecine, kiné,
   sage-femme, ...) return those programmes with an explanation, never a fabricated
   "kiné" formation.

Ranking never uses selectivity or prestige; ties break on the label, then the
establishment name.
"""
from __future__ import annotations

import bisect
import hashlib
from pathlib import Path
import math
import re
import threading
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import duckdb

MAX_QUERY_CHARS = 200
MAX_TERMS = 12

# --------------------------------------------------------------------------- normalisation
STOP = {"de", "la", "le", "les", "des", "du", "d", "l", "en", "et", "a", "au", "aux", "pour", "par",
        "sur", "un", "une", "avec", "dans", "ou", "je", "j", "veux", "voudrais", "faire", "aller",
        "post", "bac", "apres", "the", "of", "in", "or", "and", "to", "for"}
SOFT = {"formation", "ecole", "universite", "lycee", "etude", "cursus", "diplome", "filiere",
        "campus", "site", "institut", "faculte", "fac", "school", "university", "college"}   # boost only
TOKEN_SYNONYMS = {"st": "saint", "ste": "sainte", "inge": "ingenieur", "ingenieurs": "ingenieur",
                  "fac": "universite", "univ": "universite", "psy": "psycho", "eco": "economie",
                  "infos": "informatique", "idf": "ile de france"}


def fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b((?:[a-z]\.){2,}[a-z]?)", lambda m: m.group(1).replace(".", ""), s)  # I.U.T -> iut
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(TOKEN_SYNONYMS.get(t, t) for t in s.split())


def stem(t: str) -> str:
    if len(t) > 5 and t.endswith("ieres"):
        return t[:-5] + "ier"          # infirmieres -> infirmier
    if len(t) > 4 and t.endswith("iere"):
        return t[:-4] + "ier"          # infirmiere -> infirmier
    if len(t) > 4 and t.endswith(("s", "x")) and not t.endswith("ss"):
        return t[:-1]
    return t


def tokens(s: str | None) -> list[str]:
    return [stem(t) for t in fold(s).split()]


# --------------------------------------------------------------------------- phrases & tags
# Query phrases -> tag token (applied on the folded query, longest first).
PHRASES = {
    "sciences po": "t_scpo", "science po": "t_scpo", "sc po": "t_scpo", "iep": "t_scpo",
    "institut d etudes politiques": "t_scpo",
    "prepa hec": "t_ecg", "prepa ecg": "t_ecg", "prepa commerce": "t_ecg", "prepa eco": "t_ecg",
    "prepa ece": "t_ecg", "prepa ecs": "t_ecg", "hec": "t_ecg", "ecg": "t_ecg",
    "prepa litteraire": "t_cpgel", "hypokhagne": "t_cpgel", "khagne": "t_cpgel", "hypokhagnes": "t_cpgel",
    "prepa veto": "t_bcpst", "prepa veterinaire": "t_bcpst", "prepa agro": "t_bcpst", "prepa bio": "t_bcpst",
    "prepa scientifique": "t_cpges", "prepa science": "t_cpges", "prepa": "t_cpge", "cpge": "t_cpge",
    "ecole de commerce": "t_ecom", "ecole commerce": "t_ecom", "business school": "t_ecom",
    "ecole d ingenieur": "t_eing", "ecole ingenieur": "t_eing", "ingenieur post bac": "t_eing",
    "sage femme": "t_maieutique", "sages femmes": "t_maieutique", "maieutique": "t_maieutique",
    "medecine": "t_mmopk", "pharmacie": "t_mmopk", "dentaire": "t_mmopk", "odontologie": "t_mmopk",
    "kine": "t_kine", "kinesitherapie": "t_kine", "kinesitherapeute": "t_kine", "masseur kinesitherapeute": "t_kine",
    "infirmier": "t_ifsi", "infirmiere": "t_ifsi", "ifsi": "t_ifsi", "soins infirmiers": "t_ifsi",
    "info com": "t_infocom", "infocom": "t_infocom",
    "dn made": "t_dnmade", "dnmade": "t_dnmade",
    "veterinaire": "t_veto", "veto": "t_veto",
    "orthophonie": "t_ortho", "orthophoniste": "t_ortho",
    "archi": "t_archi",
    # a few English queries from international students
    "law": "droit", "computer science": "informatique", "business school": "t_ecom", "business": "t_ecom",
    "nursing": "t_ifsi", "nurse": "t_ifsi", "medicine": "t_mmopk", "psychology": "psychologie",
    "engineering": "t_eing", "engineering school": "t_eing", "economics": "economie", "mathematics": "mathematiques", "maths": "mathematiques",
    "math": "mathematiques", "physics": "physique", "chemistry": "chimie", "biology": "biologie",
    "history": "histoire", "philosophy": "philosophie", "sociology": "sociologie", "sport": "t_staps",
}
for _acr in ("ndrc", "mco", "sio", "gpme", "sam", "ciel", "cg", "gea", "tc", "geii", "gmp", "mmi", "rt", "qlio",
             "gaco", "cj", "mlt", "sd", "gb", "gccd", "hse", "mp", "sgm", "gim", "cs", "mpsi", "pcsi", "ptsi",
             "bcpst", "mp2i", "tsi", "ect", "pass", "las", "staps", "aes", "lea", "llcer", "miashs", "mass",
             "dcg", "cmi", "cpes", "cupge", "but", "bts", "iut", "dut", "deust", "bpjeps", "licence"):
    PHRASES.setdefault(_acr, "t_" + _acr)

# Document tags: (tag tokens, field, regex on the folded field). Deterministic, from labels.
TAG_RULES: tuple[tuple[str, str, str], ...] = (
    ("t_ndrc", "fil", r"negociation et digitalisation"),
    ("t_mco", "fil", r"management commercial operationnel"),
    ("t_sio", "fil", r"services informatiques aux organisations"),
    ("t_gpme", "fil", r"gestion de la pme"),
    ("t_sam", "fil", r"support a l action manageriale"),
    ("t_ciel", "fil", r"cybersecurite informatique et reseaux"),
    ("t_cg", "fil", r"^comptabilite et gestion"),
    ("t_gea", "fil", r"gestion des entreprises et des administrations"),
    ("t_tc", "fil", r"techniques de commercialisation"),
    ("t_geii", "fil", r"genie electrique et informatique industrielle"),
    ("t_gmp", "fil", r"genie mecanique et productique"),
    ("t_mmi", "fil", r"metiers du multimedia et de l internet"),
    ("t_rt", "fil", r"reseaux et telecommunications"),
    ("t_qlio", "fil", r"qualite logistique industrielle"),
    ("t_gaco", "fil", r"gestion administrative et commerciale des organisations"),
    ("t_cj", "fil", r"carrieres juridiques"),
    ("t_cs", "fil", r"carrieres sociales"),
    ("t_mlt", "fil", r"management de la logistique et des transports"),
    ("t_sd", "fil", r"science des donnees"),
    ("t_gb", "fil", r"genie biologique"),
    ("t_gccd", "fil", r"genie civil"),
    ("t_hse", "fil", r"hygiene securite environnement"),
    ("t_mp", "fil", r"^mesures physiques"),
    ("t_sgm", "fil", r"science et genie des materiaux"),
    ("t_gim", "fil", r"genie industriel et maintenance"),
    ("t_infocom", "fil", r"^information communication|^information et communication"),
    ("t_mpsi", "fil", r"^mpsi$"), ("t_pcsi", "fil", r"^pcsi$"), ("t_ptsi", "fil", r"^ptsi$"),
    ("t_bcpst", "fil", r"^bcpst"), ("t_mp2i", "fil", r"^mp2i$"), ("t_tsi", "fil", r"^tsi$"),
    ("t_cpge", "fili", r"^cpge$"),
    ("t_ecg", "fil", r"^ecg "), ("t_ect", "fil", r"^ect "),
    ("t_cpges", "form", r"classe preparatoire scientifique"),
    ("t_cpgel", "form", r"classe preparatoire litteraire"),
    ("t_scpo", "fil", r"^sciences po instituts d etudes politiques"),
    ("t_ecom", "fili", r"^ecole de commerce$"),
    ("t_eing", "fili", r"^ecole d ingenieur$"),
    ("t_ifsi", "fili", r"^ifsi$"),
    ("t_pass t_mmopk t_maieutique t_kine", "fili", r"^pass$"),
    ("t_las t_mmopk t_maieutique t_kine", "fili", r"^licence las$"),
    ("t_staps t_kine", "fil", r"sciences et techniques des activites physiques et sportives"),
    ("t_aes", "fil", r"^administration economique et sociale$"),
    ("t_lea", "fil", r"^langues etrangeres appliquees$"),
    ("t_llcer", "fil", r"^langues litteratures et civilisations etrangeres"),
    ("t_miashs t_mass", "fil", r"^mathematiques et informatique appliquees aux sciences humaines"),
    ("t_dcg", "form", r"^dcg$"), ("t_dnmade", "form", r"^dn made$"), ("t_cmi", "form", r"^c m i|cursus master en ingenierie"),
    ("t_cpes", "form", r"^cpes$"), ("t_cupge", "form", r"^cupge"), ("t_deust", "form", r"^deust$"),
    ("t_bpjeps", "form", r"^bpjeps$"),
    ("t_veto", "form", r"ecoles veterinaires"),
    ("t_ortho", "fil", r"orthophoniste"),
    ("t_archi", "fil", r"architecture"),
    ("t_but t_iut t_dut", "fili", r"^but$"), ("t_bts", "fili", r"^bts$"),
    ("t_licence", "fili", r"^licence"),
)

# Professions entered through another programme: explained, never invented.
NOTES = {
    "t_mmopk": ("Médecine, pharmacie, odontologie (dentaire) et maïeutique (sage-femme) ne sont pas des "
                "formations Parcoursup en tant que telles : on y accède après une première année PASS ou "
                "une licence avec option accès santé (L.AS). Ce sont ces formations qui sont affichées."),
    "t_maieutique": ("Les études de sage-femme (maïeutique) se rejoignent après une PASS ou une L.AS : ce sont "
                     "ces formations qui sont affichées."),
    "t_veto": ("Depuis 2021, les quatre écoles nationales vétérinaires recrutent une partie de leurs élèves "
               "directement après le bac (formations affichées). La voie classique reste la prépa BCPST : "
               "chercher « prépa véto »."),
    "t_kine": ("Les instituts de masso-kinésithérapie recrutent après une première année universitaire, "
               "selon l'institut : PASS, L.AS, licence STAPS ou licence de sciences. Ce sont ces formations "
               "qui sont affichées."),
}

# fil = the specific discipline (fil_lib_voe_acc); comp = complements (lib_comp, detail);
# family = the broad family (fili, form_lib) shared by many disciplines ("Droit-économie-gestion").
LANGUAGES = {"anglais", "allemand", "espagnol", "italien", "portugais", "russe", "arabe", "chinois", "japonais",
             "coreen", "hebreu", "polonais", "neerlandais", "grec", "latin", "occitan", "breton", "basque",
             "catalan", "corse", "creole", "turc", "persan", "hindi", "vietnamien", "scandinave", "suedois",
             "norvegien", "danois", "finnois", "roumain", "tcheque", "hongrois", "ukrainien", "signe", "tahitien",
             "berbere", "swahili", "indonesien", "thai", "serbe", "croate", "bulgare", "slovaque", "albanais"}
LANGUAGES_STEM = {stem(w) for w in LANGUAGES}   # index tokens are stemmed ("anglais" -> "anglai")
GENERIC_TAGS = {"t_licence", "t_bts", "t_but", "t_iut", "t_dut", "t_cpge"}   # family words: no literal bonus

FIELD_W = {"tag": 3.0, "fil": 2.6, "etab": 1.6, "loc": 1.4, "comp": 1.3, "family": 1.1}
KIND_W = {"exact": 1.0, "prefix": 0.7, "fuzzy": 0.55}


# --------------------------------------------------------------------------- index
@dataclass
class Index:
    docs: list[dict]
    postings: dict[str, dict[str, set[int]]]            # field -> token -> doc ids
    vocab: dict[str, list[str]]                          # field -> sorted tokens
    df: Counter
    places: dict[str, dict[int, float]]                  # folded place phrase -> doc -> level weight
    label_df: Counter
    by_uai: dict[str, list[int]] = field(default_factory=dict)
    by_cod: dict[str, int] = field(default_factory=dict)
    double: set[int] = field(default_factory=set)


SUMMARY = ("session", "cod_aff_form", "cod_uai", "g_ea_lib_vx", "ville_etab", "acad_mies", "dep_lib",
           "region_etab_aff", "fili", "form_lib_voe_acc", "fil_lib_voe_acc", "lib_for_voe_ins",
           "lib_comp_voe_ins", "detail_forma", "select_form", "acc_tot", "capa_fin", "taux_acces_ens",
           "subwish_flag", "low_n_flag", "lineage_id", "lineage_confidence", "lineage_years")
PUBLIC = tuple(c for c in SUMMARY if c not in ("detail_forma", "dep_lib", "region_etab_aff", "capa_fin"))


def _place_key(s: str | None) -> str:
    s = fold(s)
    s = re.sub(r"\b\d+(er|e|eme)?\b|\barrondissement\b|\bcedex\b", " ", s)
    return " ".join(s.split())


def build_index(con: duckdb.DuckDBPyConnection) -> Index:
    cur = con.cursor()
    cur.execute(f"""
      SELECT {', '.join('fy.' + c if c not in ('lineage_id', 'lineage_confidence', 'lineage_years') else 'l.' + c
                        for c in SUMMARY)}
      FROM core.formation_year fy JOIN core.lineage l USING (session, cod_aff_form)
      QUALIFY row_number() OVER (PARTITION BY l.lineage_id ORDER BY fy.session DESC) = 1""")
    cols = [d[0] for d in cur.description]
    docs = [dict(zip(cols, r)) for r in cur.fetchall()]
    postings: dict[str, dict[str, set[int]]] = {k: defaultdict(set) for k in FIELD_W}
    places: dict[str, dict[int, float]] = defaultdict(dict)
    label_df: Counter = Counter()
    by_uai: dict[str, list[int]] = defaultdict(list)
    double: set[int] = set()          # double licences "X / Y": a single discipline only half-matches
    for i, d in enumerate(docs):
        fil_f = fold(d["fil_lib_voe_acc"])
        for fld, keys in (("fil", ("fil_lib_voe_acc",)), ("family", ("fili", "form_lib_voe_acc")),
                          ("comp", ("lib_comp_voe_ins", "detail_forma"))):
            ftoks = set(tokens(" ".join(str(d[k] or "") for k in keys))) - STOP
            if fld == "comp" and re.search(r"^langues litteratures et civilisations|^langues etrangeres appliquees", fil_f):
                # LLCER / LEA: the language ("Anglais") is the discipline itself, and only the language
                for t in ftoks & LANGUAGES_STEM:
                    postings["fil"][t].add(i)
            for t in ftoks:
                postings[fld][t].add(i)
            if fld != "comp":
                label_df.update(ftoks)
        if "/" in str(d["fil_lib_voe_acc"] or ""):
            double.add(i)
        for t in set(tokens(d["g_ea_lib_vx"])) - STOP:
            postings["etab"][t].add(i)
        for k, lvl in (("ville_etab", 1.0), ("dep_lib", 0.6), ("acad_mies", 0.5), ("region_etab_aff", 0.3)):
            key = _place_key(d[k])
            if key:
                places[key][i] = max(places[key].get(i, 0.0), lvl)
                for t in key.split():
                    postings["loc"][stem(t)].add(i)
        folded = {"fili": fold(d["fili"]), "form": fold(d["form_lib_voe_acc"]), "fil": fold(d["fil_lib_voe_acc"])}
        tags = set()
        for tagstr, fld, rx in TAG_RULES:
            if re.search(rx, folded[fld]):
                tags.update(tagstr.split())
        for t in tags:
            postings["tag"][t].add(i)
        if d["cod_uai"]:
            by_uai[str(d["cod_uai"]).upper()].append(i)
    df: Counter = Counter()
    for fld in postings:
        for t, ids in postings[fld].items():
            df[t] = max(df[t], len(ids))
    vocab = {fld: sorted(p) for fld, p in postings.items()}
    return Index(docs, {k: dict(v) for k, v in postings.items()}, vocab, df, dict(places), label_df,
                 dict(by_uai), {d["cod_aff_form"]: i for i, d in enumerate(docs)}, double)


_CACHE: dict[str, Index] = {}
_LOCK = threading.Lock()


def _db_key(con: duckdb.DuckDBPyConnection) -> str:
    """Identify the warehouse, not the connection object: the API opens a new cursor per
    request, so keying on id(con) would rebuild the index (~2 s) on every search."""
    row = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    if row and row[0]:
        p = Path(row[0])
        return f"{p.resolve()}:{p.stat().st_mtime_ns}"   # a rebuilt warehouse gets a fresh index
    return f"memory:{id(con)}"


def get_index(con: duckdb.DuckDBPyConnection) -> Index:
    key = _db_key(con)
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = build_index(con)
        return _CACHE[key]


# --------------------------------------------------------------------------- query
def _lev(a: str, b: str, cap: int) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        lo = cap + 1
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            lo = min(lo, cur[j])
        if lo > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _correct_to_phrases(idx: Index, q: str) -> tuple[str, list[tuple[str, str]]]:
    """Map an unknown word one typo away from a single-word phrase key onto that key."""
    keys = [k for k in PHRASES if " " not in k and len(k) >= 5]
    out, fixes = [], []
    for t in q.split():
        known = t in PHRASES or any(stem(t) in idx.postings[f] for f in FIELD_W if f != "tag")
        if not known and len(t) >= 5:
            cap = 2 if len(t) >= 8 else 1
            hit = min(((_lev(t, k, cap), k) for k in keys if k[:1] == t[:1]), default=(cap + 1, None))
            if hit[0] <= cap:
                fixes.append((t, hit[1]))
                t = hit[1]
        out.append(t)
    return " ".join(out), fixes


def _phrase_rx(ph: str) -> str:
    # every word may carry a plural "s"/"x" ("écoles d'ingénieurs" -> "ecole d ingenieur")
    return r"\s".join(rf"{re.escape(w)}(?:s|x)?" if len(w) > 2 else re.escape(w) for w in ph.split())


_PHRASE_RX = [(re.compile(rf"(?<= ){_phrase_rx(ph)}(?= )"), PHRASES[ph]) for ph in sorted(PHRASES, key=len, reverse=True)]


def _apply_phrases(q: str, origin: dict[str, list[str]] | None = None) -> str:
    padded = f" {q} "
    for rx, tag in _PHRASE_RX:
        if origin is not None and tag.startswith("t_"):
            for m in rx.finditer(padded):
                origin.setdefault(tag, []).extend(stem(w) for w in m.group(0).split() if len(w) > 2)
        padded = rx.sub(tag, padded)
    return padded.strip()


def _extract_place(idx: Index, toks: list[str]) -> tuple[list[str], str | None, dict[int, float] | None]:
    """Longest n-gram (<= 4 tokens) naming a place. A single word is taken as a place only
    when it names more formations' locations than it appears in programme labels
    ("paris": 1,297 places vs a few labels; a discipline word never wins that test)."""
    for n in range(min(4, len(toks)), 0, -1):
        for i in range(len(toks) - n + 1):
            gram = " ".join(toks[i:i + n])
            if gram.startswith("t_"):
                continue
            if gram not in idx.places:
                # "aix" alone is only a prefix of real places ("aix en provence", "aix les bains"):
                # same test as for exact names, against all the places it prefixes
                pref = sum(len(v) for k, v in idx.places.items() if k.startswith(gram + " ")) if n == 1 and len(gram) >= 3 else 0
                if not pref or idx.label_df.get(stem(gram), 0) >= pref or gram in STOP or gram in SOFT:
                    continue
                ids = {}
                for key, docs in idx.places.items():
                    if key.startswith(gram + " "):
                        for d, w in docs.items():
                            ids[d] = max(ids.get(d, 0.0), w)
                return toks[:i] + toks[i + n:], gram, ids
            if n == 1 and (idx.label_df.get(stem(gram), 0) >= len(idx.places[gram]) or gram in STOP or gram in SOFT):
                continue
            ids = dict(idx.places[gram])
            if n == 1:
                # one word may name several places: "clermont" = Clermont-Ferrand, Clermont (Oise),
                # Clermont-l'Hérault; "aix" = Aix-en-Provence, Aix-les-Bains. Take them all.
                for key, docs in idx.places.items():
                    if key.startswith(gram + " "):
                        for d, w in docs.items():
                            ids[d] = max(ids.get(d, 0.0), w)
            return toks[:i] + toks[i + n:], gram, ids
    return toks, None, None


def _term_matches(idx: Index, t: str, base: set[int] | None = None) -> tuple[dict[int, float], str]:
    """doc -> best weight for one term, and the best match kind. Exact and prefix hits are
    merged (exact weighs more); typo matching is only tried when neither finds anything
    inside the place filter."""
    best: dict[int, float] = {}
    kind_seen = None
    for kind in ("exact", "prefix", "fuzzy"):
        if kind == "fuzzy" and best:
            break
        hits: dict[int, float] = {}
        for fld, w in FIELD_W.items():
            if t.startswith("t_") and fld != "tag":
                continue
            if kind == "exact":
                cands = [t] if t in idx.postings[fld] else []
            elif kind == "prefix":
                if len(t) < 4 or t.startswith("t_"):
                    continue
                v = idx.vocab[fld]
                j = bisect.bisect_left(v, t)
                cands = []
                while j < len(v) and v[j].startswith(t) and len(cands) < 60:
                    cands.append(v[j])
                    j += 1
            else:
                if len(t) < 5 or t.startswith("t_") or fld == "tag":
                    continue
                cap = 2 if len(t) >= 8 else 1
                cands = [v for v in idx.vocab[fld] if v[:1] == t[:1] and _lev(t, v, cap) <= cap][:20]
            for c in cands:
                pen = 1.0 if kind != "fuzzy" else (1.0 if _lev(t, c, 2) <= 1 else 0.8)
                for d in idx.postings[fld][c]:
                    if base is not None and d not in base:
                        continue
                    s = w * KIND_W[kind] * pen * (0.85 if fld == "fil" and d in idx.double else 1.0)
                    if s > hits.get(d, 0):
                        hits[d] = s
        for d, s in hits.items():
            if s > best.get(d, 0):
                best[d] = s
        if hits and kind_seen is None:
            kind_seen = kind
    return best, kind_seen or "none"


def clean_complement(d: dict) -> str | None:
    """lib_comp_voe_ins often repeats the establishment and the family ("Université X - Licence -
    Portail Droit"): keep only what is not already shown."""
    comp = d.get("lib_comp_voe_ins")
    if not comp:
        return comp
    parts = [p.strip() for p in str(comp).split(" - ")]
    drop = {fold(d.get("g_ea_lib_vx")), fold(d.get("fili")), fold(d.get("fil_lib_voe_acc")), "licence", "bts", "but"}
    kept = [p for p in parts if fold(p) not in drop and fold(p) != fold(d.get("form_lib_voe_acc"))]
    return " - ".join(kept) or None


def _tiebreak(cod: str) -> str:
    return hashlib.blake2b(str(cod).encode(), digest_size=8).hexdigest()


def search(con: duckdb.DuckDBPyConnection, q: str, *, fili: str | None = None, academie: str | None = None,
           selective: bool | None = None, near: str | None = None, offset: int = 0, limit: int = 40) -> dict:
    """near: the student's home académie (from their profile). It only breaks ties between
    equally relevant results; it never filters and never outranks a better match."""
    idx = get_index(con)
    q = (q or "")[:MAX_QUERY_CHARS]
    raw = fold(q)
    interp: list[dict] = []
    notes: list[str] = []
    base: set[int] | None = None

    uai = re.fullmatch(r"\s*(\d{7}[a-zA-Z])\s*", q or "")
    if uai:
        base = set(idx.by_uai.get(uai.group(1).upper(), []))
        interp.append({"type": "uai", "value": uai.group(1).upper()})
        terms: list[str] = []
        scores = {d: 1.0 for d in base}
        partial = False
    else:
        corrected, fixes = _correct_to_phrases(idx, raw)
        for a, b in fixes:
            interp.append({"type": "corrigé", "value": f"{a} → {b}"})
        origin: dict[str, list[str]] = {}
        phrased = _apply_phrases(corrected, origin)
        # places are matched on unstemmed words ("paris", "nantes", "tours"), then the rest is stemmed
        toks, place, place_ids = _extract_place(idx, phrased.split())
        toks = [t if t.startswith("t_") else stem(t) for t in toks]
        place_w = place_ids or {}
        if place:
            base = set(place_ids)
            interp.append({"type": "lieu", "value": place})
        # single characters ("1", "a") are noise on their own: they can boost, never require
        required = [t for t in dict.fromkeys(toks) if t not in STOP and t not in SOFT and len(t) > 1][:MAX_TERMS]
        soft = [t for t in toks if t in SOFT or (len(t) == 1 and t.isdigit())]
        generic = [t for t in dict.fromkeys(soft) if t in SOFT]
        if not required and generic:       # "université lyon": the generic word is all we have
            required, soft = generic[:MAX_TERMS], [t for t in soft if t not in SOFT]
        for t in required:
            if t.startswith("t_") and t in NOTES and NOTES[t] not in notes:
                notes.append(NOTES[t])
        n = len(idx.docs)
        per_term = []
        for t in required:
            hits, kind = _term_matches(idx, t, base)
            idf = math.log(1 + n / (1 + len(hits))) if hits else 0.0
            per_term.append((t, hits, kind, idf))
            if t.startswith("t_"):
                interp.append({"type": "sigle", "value": t[2:]})
            elif kind in ("prefix", "fuzzy"):
                interp.append({"type": "approché", "value": t})
        partial = False
        if not per_term:
            scores = {d: place_w.get(d, 1.0) for d in (base if base is not None else set())}
        else:
            matched = [p for p in per_term if p[1]]
            docs = set.intersection(*(set(p[1]) for p in per_term)) if all(p[1] for p in per_term) else set()
            unmatched = len(per_term) - len(matched)
            if not docs and matched and unmatched <= max(1, len(per_term) // 2):
                # relax: drop the terms that match nothing, then the least informative one; never
                # when most of the query is unknown (that would be a confident answer to junk)
                partial = True
                # drop free words before recognised concepts (tags), then the least informative
                pool = matched if len(matched) < len(per_term) else \
                    sorted(matched, key=lambda p: (p[0].startswith("t_"), p[3]), reverse=True)[:-1] or matched
                docs = set.intersection(*(set(p[1]) for p in pool))
                dropped = [p[0] for p in per_term if p not in pool]
                interp.append({"type": "ignoré", "value": ", ".join(d[2:] if d.startswith("t_") else d for d in dropped)})
                per_term = pool
            # a programme whose own label says the word the student typed ("Parcours
            # Kinésithérapie") outranks one that only carries the access tag
            literal: dict[int, float] = defaultdict(float)
            for p in per_term:
                if p[0] in GENERIC_TAGS:
                    continue
                for w in origin.get(p[0], []):
                    for fld in ("fil", "comp", "etab"):
                        for d in idx.postings[fld].get(w, ()):
                            if d in docs:
                                literal[d] = max(literal[d], FIELD_W[fld])
            scores = {}
            for d in docs:
                s = sum(p[1][d] * p[3] for p in per_term) + 1.5 * literal.get(d, 0.0)
                if soft and any(d in idx.postings[f].get(t, ()) for f in ("fil", "family", "etab") for t in soft):
                    s += 0.5
                scores[d] = s + 2.0 * place_w.get(d, 0.0)   # the named town before the rest of its académie
        terms = required

    matched_ids = list(scores)
    tests = {
        "fili": lambda x: not fili or x["fili"] == fili,
        "academie": lambda x: not academie or x["acad_mies"] == academie,
        "selectivite": lambda x: selective is None or (x["select_form"] == "formation sélective") == selective,
    }
    src = {"fili": "fili", "academie": "acad_mies", "selectivite": "select_form"}

    def keep(d: int, skip: str | None = None) -> bool:
        x = idx.docs[d]
        return all(t(x) for k, t in tests.items() if k != skip)

    # disjunctive facets: each dimension is counted with the *other* active filters applied,
    # so every number shown is exactly what a click on it returns
    facets = {k: Counter(idx.docs[d][src[k]] for d in matched_ids if keep(d, skip=k)) for k in tests}

    # Ties between equally relevant results: latest campaign, then the student's académie,
    # then a deterministic hash of the formation code. The hash ignores every attribute
    # (selectivity, size, name): alphabetical order would always favour "A…" establishments
    # and capacity order would systematically favour large, accessible programmes.
    ranked = sorted((d for d in matched_ids if keep(d)),
                    key=lambda d: (-round(scores[d], 6), -(idx.docs[d]["session"] or 0),
                                   0 if near and idx.docs[d]["acad_mies"] == near else 1,
                                   _tiebreak(idx.docs[d]["cod_aff_form"])))
    page = ranked[offset: offset + limit]
    return {
        "mode": "uai" if uai else "text", "query": q, "terms": terms, "interpretation": interp,
        "notes": notes, "partial": partial, "total": len(ranked), "offset": offset, "limit": limit,
        # every value, never a top-N: a dropdown must offer each académie the results contain, and
        # the active selection is always present so the control reflects the filter in force
        "facets": {k: [{"value": v, "count": c} for v, c in cnt.most_common() if v] for k, cnt in facets.items()},
        "results": [{**{k: idx.docs[d][k] for k in PUBLIC},
                     "lib_comp_voe_ins": clean_complement(idx.docs[d])} for d in page],
    }
