"""Sprint R3 (owner, 2026-11-12): the advanced filters shared by the search and the map.

One definition of every band, served to the page (`vocab`, in /api/meta) so the search (filtered here) and the map (filtered in
the browser) cut at the same values:

* capacité: the published number of places of the formation's own campaign (`capa_fin`), four bands;
* phase complémentaire: did the formation ADMIT candidates in the complementary phase of its own campaign (`acc_pc` > 0)? Admits
  of a past campaign, never places left this year (the page says so);
* statut: public, private under contract, fee-charging private (Plan B's rule, `carte.statut_of`);
* taux d'accès: the OFFICIAL rate of the campaign (`taux_acces_ens`), four bands; a formation without a published rate is in none;
* zone: the zone of "Mon parcours" for the profile sent with the search (`journey.stage2` on each formation's own type, `only`
  its codes, latest campaign), as Mes vœux reads it. The profile is used for this answer only: nothing is stored, the search's
  audience event never carries it, the answer is no-store. Every result set gets its zones (review: a limit made a zone filter
  silently empty on broad searches; the cost grows with the number of types, about 1.5-2.5 s for the broadest queries, and the
  answers are kept in a small in-process cache so paging and ticking reuse them).

The list is never sorted by these values (never by chances): the search keeps its relevance order, the map its own.
"""
from __future__ import annotations

from collections import OrderedDict

from . import carte as CA
from . import journey as J

CAPACITE = (("moins20", "Moins de 20 places", None, 20), ("20a49", "20 à 49 places", 20, 50),
            ("50a99", "50 à 99 places", 50, 100), ("100plus", "100 places et plus", 100, None))
TAUX = (("moins30", "Moins de 30 %", None, 30), ("30a59", "De 30 à 59 %", 30, 60),
        ("60a89", "De 60 à 89 %", 60, 90), ("90plus", "90 % et plus", 90, None))
COMPLEMENTAIRE = (("oui", "A admis des candidats en phase complémentaire"), ("non", "Aucun admis en phase complémentaire"))
STATUT = (("public", "Publics"), ("contrat", "Privés sous contrat avec l'État / EESC"), ("prive", "Privés (payants)"))
ZONE = (("securite", "Vœux de sécurité"), ("cible", "Vœux cibles"), ("ambitieux", "Vœux ambitieux"),
        ("autre", "Autres (hors-profil, indéterminés, non situés)"))
ZONE_KEYS = ("securite", "cible", "ambitieux")
GROUPS = ("statut", "capacite", "complementaire", "taux", "zone")
_CACHE: OrderedDict = OrderedDict()   # (warehouse, campaign, profile, type, codes) -> stage-2 zones; a few hundred entries at most
CACHE_SIZE = 256


def vocab() -> dict:
    """What the page reads: every option of every group, the bands with their limits (the map cuts with the same ones)."""
    band = lambda b: [{"key": k, "label": lab, "min": lo, "max": hi} for k, lab, lo, hi in b]  # noqa: E731
    pair = lambda b: [{"key": k, "label": lab} for k, lab in b]  # noqa: E731
    return {"capacite": band(CAPACITE), "taux": band(TAUX), "complementaire": pair(COMPLEMENTAIRE),
            "statut": pair(STATUT), "zone": pair(ZONE)}


def band(value, bands) -> str | None:
    """The band of a value: lower limit included, upper limit excluded; no value, no band."""
    if value is None:
        return None
    for key, _, lo, hi in bands:
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return key
    return None


def parse(raw: str | None, group: str) -> tuple[str, ...]:
    """A comma-separated list of the group's keys; an unknown key is an error (never silently dropped)."""
    keys = {"capacite": [b[0] for b in CAPACITE], "taux": [b[0] for b in TAUX], "complementaire": [b[0] for b in COMPLEMENTAIRE],
            "statut": [b[0] for b in STATUT], "zone": [b[0] for b in ZONE]}[group]
    out = tuple(dict.fromkeys(x for x in (raw or "").split(",") if x))
    bad = [x for x in out if x not in keys]
    if bad:
        raise ValueError(f"filtre {group} inconnu : {', '.join(bad)}")
    return out


def attributes(con, results: list[dict]) -> dict:
    """{(code, session): (capa_fin, acc_pc, contrat_etab)} of the results' own campaigns."""
    keys = sorted({(r["cod_aff_form"], r["session"]) for r in results})
    if not keys:
        return {}
    rows = con.execute("""SELECT fy.cod_aff_form, fy.session, fy.capa_fin, fy.acc_pc, fy.contrat_etab
        FROM core.formation_year fy JOIN (SELECT unnest(?) AS c, unnest(?) AS s) k ON fy.cod_aff_form = k.c AND fy.session = k.s""",
                       [[k[0] for k in keys], [k[1] for k in keys]]).fetchall()
    return {(c, s): (cap, pc, ct) for c, s, cap, pc, ct in rows}


def zones(con, results: list[dict], serie: str, dkey: str | None, mention: str, moyenne: float | None = None) -> dict:
    """{(code, latest campaign): (zone, uncertain, estimate, fragile)} for the results of the latest campaign (keyed WITH the campaign: a result of an
    older campaign may share the code and must never take this zone): the stage-2 row of each formation's own type, `only` its
    codes (the zone of Mon parcours, Mes vœux and the map). Results of an older campaign, or without a type, get none.
    R4: for a bac techno or pro profile, the same row's ESTIMATED access for the series (`taux_acces_ens` x series proposal rate /
    all proposal rate, capped: the "Accès estimé" of Mon parcours) and its "peu de candidats" flag ride along; none for bac général
    (the row's rate there is the official one)."""
    latest = con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]
    codes = sorted({r["cod_aff_form"] for r in results if r["session"] == latest})
    if not codes:
        return {}
    by_type: dict = {}
    for c, tk in con.execute("""SELECT t.cod_aff_form, r.spe_type_key FROM core.taxonomy_link t JOIN core.taxonomy_rule r USING (rule_id)
                                WHERE t.session = ? AND t.cod_aff_form IN (SELECT unnest(?))""", [latest, codes]).fetchall():
        if tk:
            by_type.setdefault(tk, []).append(c)
    db = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()[0]
    out = {}
    for tk, cods in by_type.items():
        key = (db, latest, serie, dkey, mention, moyenne, tk, tuple(sorted(cods)))
        if key in _CACHE:
            _CACHE.move_to_end(key)
        else:                              # no row limit: a type is read whole for its listed codes
            _CACHE[key] = {f["cod_aff_form"]: (f["zone"], bool(f.get("uncertain")),
                                               f.get("taux_acces_ens") if serie != "bg" else None, bool(f.get("rate_fragile")))
                           for f in J.stage2(con, dkey, mention, tk, None, limit=10 ** 6, serie=serie, only=cods, moyenne=moyenne)["formations"]}
            while len(_CACHE) > CACHE_SIZE:
                _CACHE.popitem(last=False)
        for c, z in _CACHE[key].items():
            out[(c, latest)] = z
    return out


def tags(r: dict, attrs: dict, zoned: dict | None) -> dict:
    """The value of every group for one result (a NEW dict: search results are shared index documents)."""
    cap, pc, contrat = attrs.get((r["cod_aff_form"], r["session"]), (None, None, None))
    z = zoned.get((r["cod_aff_form"], r["session"])) if zoned is not None else None
    zone = None if zoned is None else (z[0] if z and z[0] in ZONE_KEYS else "autre")
    return {"capacite": band(cap, CAPACITE), "taux": band(r.get("taux_acces_ens"), TAUX),
            "complementaire": None if pc is None else ("oui" if pc > 0 else "non"),
            "statut": CA.statut_of(contrat) if contrat else None, "zone": zone,
            "_capa": cap, "_acc_pc": pc, "_zone": z[0] if z else None, "_uncertain": bool(z and z[1]),
            "_estime": z[2] if z else None, "_fragile": bool(z and z[3])}


def apply(rows: list[dict], active: dict[str, tuple[str, ...]], base: dict) -> tuple[list[dict], dict]:
    """rows: [{"r": result, "t": tags}] in relevance order. `active`: the ticked options per group (an empty group keeps all);
    `base`: the search's own filters {"fili", "academie", "selectivite"} -> value or None.
    Returns the kept rows (same order) and the facets: every group counted with the OTHER groups applied (a count is exactly
    what a click on it returns), the search's own facets included."""
    src = {"fili": "fili", "academie": "acad_mies", "selectivite": "select_form"}

    def ok(x, skip=None):
        for g, opts in active.items():
            if g != skip and opts and x["t"][g] not in opts:
                return False
        for g, v in base.items():
            if g != skip and v is not None and x["r"].get(src[g]) != v:
                return False
        return True

    kept = [x for x in rows if ok(x)]
    facets = {}
    for g in GROUPS:
        cnt: dict = {}
        for x in rows:
            if ok(x, skip=g) and x["t"][g] is not None:
                cnt[x["t"][g]] = cnt.get(x["t"][g], 0) + 1
        facets[g] = cnt
    for g, col in src.items():
        cnt = {}
        for x in rows:
            if ok(x, skip=g) and x["r"].get(col):
                cnt[x["r"][col]] = cnt.get(x["r"][col], 0) + 1
        facets[g] = cnt
    return kept, facets
