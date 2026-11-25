"""Harvest of the evaluation grids and expectations from the LIVE Parcoursup fiches (owner, 2026-11-13).

Run by the `suptracker-rapports` workflow, mode "grilles" (by hand, and every day after the reports' "live" mode). Each fiche
of the latest SIES campaign and cartographie session (rapports_live.codes) is read, its grid parsed by fiche_parse.parse,
and stored in data/fiches/:
  * etat.csv      one row per code: status (ok / sans_grille / rejetee / retry / failed / hors_campagne: a formation of the
                  last SIES campaign the current cartographie no longer offers, its fiche gone), when it was read, the campaign the
                  grid serves (the fiche's "analysent les candidatures en avril-mai 2026"), the reason of a rejection;
  * champs.csv    the global grid: one row per field (rank, field, weight %, the detailed table's caption as a text id);
  * criteres.csv  the detailed grid: one row per criterion (field rank, rank, criterion and elements as text ids, importance 1-4);
  * attendus.csv  one row per code: national and complementary expectations, advice to candidates (text ids);
  * textes.csv.gz the texts, each stored ONCE under its digest (id), gzip members appended (a national text is shared by
                  every formation of a mention; the history stays small);
  * identite.csv  one row per code (reader version 3, owner 2026-11-15): the establishment's status badge, the grants badge
                  (oui / non / empty when not printed) and the State label(s) as Parcoursup prints them (image code + text);
  * frais.csv     the tuition-fee lines (rank, callout title, heading, text id), verbatim;
  * contact.csv   one row per code (reader version 4, sprint 4, owner 2026-11-21): the disability callout's text id, whether a
                  disability referent's contact is printed (oui / non / empty: no such line; the contact itself is never kept),
                  whether a student ambassador is (same), the « Informations supplémentaires » text id and its paragraphs
                  speaking of disability (JSON: text id, http(s) links).
A fiche is read again when its last reading is older than REFRESH_DAYS (the grids change with each campaign: the 2027 fiches open
in December). Closed site (three fiches answer 404 / "indisponible"): nothing is written. Polite: one request at a time, paced,
the shared generic User-Agent.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from fiche_parse import VERSION, parse  # noqa: E402
from rapports_harvest import UA, write  # noqa: E402
from rapports_live import FICHE, FICHE_HOSTS, codes  # noqa: E402
from rapports_harvest import call  # noqa: E402

REFRESH_DAYS = 20
ETAT_COLS = ["cod_aff_form", "status", "lu_le", "session", "raison", "url", "version"]
CHAMP_COLS = ["cod_aff_form", "session", "rang", "champ", "poids", "intitule_id"]
CRIT_COLS = ["cod_aff_form", "session", "champ_rang", "rang", "critere_id", "elements_id", "importance"]
ATT_COLS = ["cod_aff_form", "session", "nationaux_id", "complementaires_id", "conseils_id", "info_id"]
ID_COLS = ["cod_aff_form", "session", "etab_type", "bourses", "labels_codes", "labels_textes"]
FRAIS_COLS = ["cod_aff_form", "session", "rang", "titre", "rubrique", "texte_id"]
CONTACT_COLS = ["cod_aff_form", "session", "handicap_id", "referent", "ambassadeur", "infos_id", "handicap_infos"]


def is_fiche(resp) -> bool:
    """A real fiche: an answer 200 whose title is "Fiche formation". The report harvest's closed-site test (the words
    "indisponible" / "maintenance" anywhere and no report link) took 1,607 real fiches for a closed site: a fiche may
    print "internat indisponible" (harvest of 2026-11-15)."""
    return resp is not None and resp.status_code == 200 and bool(
        re.search(r"<title>\s*Fiche formation", resp.text[:5000] if resp.text else ""))


def fetch_fiche(http, cod: str, pause: float):
    """The fiche of a formation from the first host that serves one (url, response); (None, last response) if none does
    (an error page, a maintenance page, a 404)."""
    last = None
    for h in FICHE_HOSTS:
        url = FICHE.replace("dossier.parcoursup.fr", h).format(cod=cod)
        resp = call(http, url, pause=pause)
        if is_fiche(resp):
            return url, resp
        last = resp
    return None, last


def carto_codes(db: str) -> set[str] | None:
    """The codes of the latest cartographie session (the formations Parcoursup offers now); None when unknown."""
    try:
        import duckdb
        con = duckdb.connect(db, read_only=True)
        try:
            return {c for (c,) in con.execute("""SELECT cod_aff_form FROM core.cartographie
                WHERE carto_session = (SELECT max(carto_session) FROM core.cartographie)""").fetchall()}
        finally:
            con.close()
    except Exception:  # noqa: BLE001  (no warehouse: every code counts as offered)
        return None


def newest_session(rows: list[dict], probed: list) -> int | None:
    """The newest campaign known: the stored readings' and the probe fiches' just read (None when none prints one)."""
    years = [int(r["session"]) for r in rows if str(r.get("session") or "").isdigit()] + [y for y in probed if y]
    return max(years) if years else None


def older_campaign(r: dict, newest: int | None) -> bool:
    """A fiche read for a campaign older than the newest one the site shows: read again first (its grid is last year's)."""
    return (newest is not None and r["status"] in ("ok", "sans_grille", "rejetee")
            and str(r.get("session") or "").isdigit() and int(r["session"]) < newest)


def clean_contact(r: dict) -> dict:
    """A stored contact row without any link carrying contact information (Codex, PR #98): rows an older reader wrote are cleaned
    at the next run, before anything is saved again."""
    from fiche_parse import personal_link
    try:
        infos = json.loads(r.get("handicap_infos") or "[]")
    except ValueError:
        infos = []
    for x in infos:
        x["liens"] = [u for u in x.get("liens") or [] if isinstance(u, str) and not personal_link(u)]
    return dict(r, handicap_infos=json.dumps(infos, ensure_ascii=False))


def tid(t: str | None) -> str:
    return "" if not t else hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


def read_rows(path: Path) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8"))) if path.exists() else []


def known_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return {r["id"] for r in csv.DictReader(f)}


def append_texts(path: Path, rows: list[dict]) -> None:
    """One gzip member per run (append-only): a reader concatenates the members."""
    if not rows:
        return
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["id", "texte"])
    if not path.exists():
        w.writeheader()
    w.writerows(rows)
    with open(path, "ab") as f:
        f.write(gzip.compress(buf.getvalue().encode("utf-8"), mtime=0))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def harvest(http, db: str, out: Path, budget_s: float, pause: float = 1.0, refresh_days: int = REFRESH_DAYS) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    order = codes(db)
    etat = {r["cod_aff_form"]: r for r in read_rows(out / "etat.csv")}
    for c in order:
        etat.setdefault(c, {"cod_aff_form": c, "status": "todo", "lu_le": "", "session": "", "raison": "", "url": "", "version": ""})
    champs = {}
    for r in read_rows(out / "champs.csv"):
        champs.setdefault(r["cod_aff_form"], []).append(r)
    crits = {}
    for r in read_rows(out / "criteres.csv"):
        crits.setdefault(r["cod_aff_form"], []).append(r)
    atts = {r["cod_aff_form"]: r for r in read_rows(out / "attendus.csv")}
    idents = {r["cod_aff_form"]: r for r in read_rows(out / "identite.csv")}
    fees = {}
    for r in read_rows(out / "frais.csv"):
        fees.setdefault(r["cod_aff_form"], []).append(r)
    contacts = {r["cod_aff_form"]: clean_contact(r) for r in read_rows(out / "contact.csv")}
    ids = known_ids(out / "textes.csv.gz")
    new_texts: list[dict] = []
    old = (datetime.now(timezone.utc) - timedelta(days=refresh_days)).strftime("%Y%m%d%H%M%S")
    # first the fiches never read, then those an older reader read (a new reader may read them, and version 3 reads the
    # identity badges and the fees of EVERY fiche, grid or not)
    offered = carto_codes(db)
    yesterday = (datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y%m%d%H%M%S")
    # is the site open? three fiches first (no write at all when closed); their campaign also tells whether Parcoursup has
    # switched to the next one (sprint 3: the 2027 fiches open in December, read before the 20-day refresh comes round)
    probe = [c for c in order if etat[c]["status"] == "ok"][:3] or order[:3]
    probed = [fetch_fiche(http, c, pause) for c in probe]
    if probe and all(u is None for u, _r in probed):
        return {"status": "closed", "checked_at": _now(), "todo": sum(etat[c]["status"] in ("todo", "retry") for c in order)}
    newest = newest_session([etat[c] for c in order], [parse(r.text)["session"] for u, r in probed if u is not None])
    first = [etat[c] for c in order if etat[c]["status"] in ("todo", "retry")]
    # a new campaign on the site: every fiche still read for an older one comes next, oldest reading first (one read again
    # within 12 hours that still shows the older campaign waits for the next day, like a failed one)
    first += sorted((etat[c] for c in order if older_campaign(etat[c], newest) and etat[c]["lu_le"] < yesterday),
                    key=lambda r: r["lu_le"])
    first += [etat[c] for c in order if etat[c]["status"] in ("ok", "sans_grille", "rejetee") and etat[c].get("version") != str(VERSION)
              and not (older_campaign(etat[c], newest) and etat[c]["lu_le"] < yesterday)]
    # a fiche that did not answer is asked again at every run (at most twice a day), right after the new ones: most were
    # real fiches the old closed-site test refused (2026-11-15)
    first += [etat[c] for c in order if etat[c]["status"] == "failed" and etat[c]["lu_le"] < yesterday]
    seen = {id(r) for r in first}
    again = sorted((etat[c] for c in order if etat[c]["status"] in ("ok", "sans_grille", "rejetee", "failed", "hors_campagne")
                    and etat[c]["lu_le"] < old and id(etat[c]) not in seen),
                   key=lambda r: r["lu_le"])
    queue = first + again

    def text_id(t: str | None) -> str:
        i = tid(t)
        if i and i not in ids:
            ids.add(i)
            new_texts.append({"id": i, "texte": t})
        return i

    n = 0
    for r in queue:
        if time.time() - t0 > budget_s:
            break
        c = r["cod_aff_form"]
        url, resp = fetch_fiche(http, c, pause)
        r["lu_le"] = _now()
        p = parse(resp.text) if url is not None else None
        if url is None or p["reason"] == "pas une fiche":   # an error page: like a failed read, the stored grid is kept
            r["raison"] = "pas une fiche" if url is not None else f"fiche {resp.status_code if resp is not None else 'none'}"
            if offered is not None and c not in offered:
                # a formation of the last SIES campaign that the current cartographie no longer offers: not a failure
                r["status"] = "hors_campagne"
            else:
                r["status"] = "retry" if r["status"] == "todo" else "failed"
            continue
        r["version"] = str(VERSION)
        r["url"], r["session"] = url, p["session"] or ""
        champs.pop(c, None)
        crits.pop(c, None)
        atts[c] = {"cod_aff_form": c, "session": p["session"] or "", "nationaux_id": text_id(p["attendus_nationaux"]),
                   "complementaires_id": text_id(p["attendus_complementaires"]), "conseils_id": text_id(p["conseils"]),
                   "info_id": text_id(p.get("info"))}
        bd = p.get("badges") or {}
        idents[c] = {"cod_aff_form": c, "session": p["session"] or "", "etab_type": bd.get("etab_type") or "",
                     "bourses": {True: "oui", False: "non"}.get(bd.get("bourses"), ""),
                     "labels_codes": "|".join(x["code"] for x in bd.get("labels", [])),
                     "labels_textes": "|".join(x["texte"].replace("|", "/") for x in bd.get("labels", []))}
        fees[c] = [{"cod_aff_form": c, "session": p["session"] or "", "rang": i + 1, "titre": x["titre"], "rubrique": x["rubrique"],
                    "texte_id": text_id(x["texte"])} for i, x in enumerate(p.get("frais") or [])]
        ct = p.get("contact") or {}
        yn = {True: "oui", False: "non"}
        contacts[c] = {"cod_aff_form": c, "session": p["session"] or "", "handicap_id": text_id(ct.get("handicap")),
                       "referent": yn.get(ct.get("referent"), ""), "ambassadeur": yn.get(ct.get("ambassadeur"), ""),
                       "infos_id": text_id(ct.get("infos")),
                       "handicap_infos": json.dumps([{"texte_id": text_id(x["texte"]), "liens": x["liens"]}
                                                     for x in ct.get("handicap_infos") or []], ensure_ascii=False)}
        if not p["ok"]:
            r["status"] = "sans_grille" if p["reason"] == "pas de grille" else "rejetee"
            r["raison"] = p["reason"]
        else:
            r["status"], r["raison"] = "ok", ""
            champs[c] = [{"cod_aff_form": c, "session": p["session"] or "", "rang": x["rang"], "champ": x["champ"], "poids": x["poids"],
                          "intitule_id": text_id(x.get("intitule"))} for x in p["champs"]]
            crits[c] = [{"cod_aff_form": c, "session": p["session"] or "", "champ_rang": k["champ_rang"], "rang": k["rang"],
                         "critere_id": text_id(k["critere"]), "elements_id": text_id(k["elements"]), "importance": k["importance"]}
                        for k in p["criteres"]]
        n += 1
        if n % 500 == 0:
            print(f"{n} fiches lues, {time.time() - t0:.0f} s", flush=True)
            _save(out, etat, champs, crits, atts, new_texts, idents, fees, contacts)
            new_texts = []
    _save(out, etat, champs, crits, atts, new_texts, idents, fees, contacts)
    by: dict = {}
    for r in etat.values():
        by[r["status"]] = by.get(r["status"], 0) + 1
    res = {"status": "open", "checked_at": _now(), "lues": n, "total": len(etat), "by_status": by}
    (out / "last_run.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def _save(out: Path, etat: dict, champs: dict, crits: dict, atts: dict, new_texts: list, idents: dict | None = None,
          fees: dict | None = None, contacts: dict | None = None) -> None:
    key = lambda c: (len(c), c)  # noqa: E731  numeric order of the codes
    append_texts(out / "textes.csv.gz", new_texts)
    write(out / "etat.csv", ETAT_COLS, [etat[c] for c in sorted(etat, key=key)])
    write(out / "champs.csv", CHAMP_COLS, [x for c in sorted(champs, key=key) for x in champs[c]])
    write(out / "criteres.csv", CRIT_COLS, [x for c in sorted(crits, key=key) for x in crits[c]])
    write(out / "attendus.csv", ATT_COLS, [atts[c] for c in sorted(atts, key=key)])
    if idents is not None:
        write(out / "identite.csv", ID_COLS, [idents[c] for c in sorted(idents, key=key)])
    if fees is not None:
        write(out / "frais.csv", FRAIS_COLS, [x for c in sorted(fees, key=key) for x in fees[c]])
    if contacts:
        write(out / "contact.csv", CONTACT_COLS, [contacts[c] for c in sorted(contacts, key=key)])


def sample(http, out: Path, per_status: int = 6, pause: float = 1.0, codes: list | None = None) -> dict:
    """Design material: a few fiches of each status the reader could not use (sans_grille, rejetee), or the fiches of the
    given codes (`codes`, status "code"), saved MASKED (e-mail addresses and phone numbers replaced, as in what is read) under
    data/fiches/echantillon/<status>_<code>.html."""
    from fiche_parse import mask
    etat = read_rows(out / "etat.csv")
    dest = out / "echantillon"
    dest.mkdir(parents=True, exist_ok=True)
    picked: dict = {}
    if codes:
        picked["code"] = [str(c) for c in codes if str(c).isdigit()][:40]
    for r in etat if not codes else []:
        if r["status"] in ("sans_grille", "rejetee") and len(picked.setdefault(r["status"], [])) < per_status:
            picked[r["status"]].append(r["cod_aff_form"])
    saved = []
    for st, cods in picked.items():
        for c in cods:
            url, resp = fetch_fiche(http, c, pause)
            if url is not None:
                (dest / f"{st}_{c}.html").write_text(mask(resp.text), encoding="utf-8")
                saved.append(f"{st}_{c}")
    return {"saved": saved}


def main(db: str, out: str, budget_min: float) -> None:
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as http:
        res = harvest(http, db, Path(out), budget_min * 60)
    print(json.dumps(res), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "--echantillon":
        with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": UA}) as http:
            req = Path(sys.argv[3]) if len(sys.argv) > 3 else None
            codes = json.loads(req.read_text(encoding="utf-8")).get("codes") if req and req.exists() else None
            print(json.dumps(sample(http, Path(sys.argv[2]), codes=codes)), flush=True)
    else:
        main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 300)
