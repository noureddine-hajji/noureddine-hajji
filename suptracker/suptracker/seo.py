"""Sprint 17: SupCompass can be found by a search engine.

The app is a single page whose views live after a `#`, which search engines do not index: every formation and job
was invisible. This module serves, for each one, a real page at a clean address:

  /formation/<code>   one Parcoursup formation (latest campaign record)
  /metier/<MET.id>    one Onisep job

Each page is the normal app shell with, already inside `<main id="view">`, a short server-rendered summary (the same
official figures the app shows, never recomputed) plus a <title>, a meta description, a canonical address, Open Graph
tags and schema.org JSON-LD. When the script loads, the app replaces that summary with the full page, so a visitor
sees the usual app and a crawler sees real content.

Rules (red team G1-G10):
  - official indicators as published (`taux_acces_ens`, admits, places), the same caveat as the app: past campaigns,
    never a chance of admission;
  - every stored string is escaped in HTML, in attributes and in JSON-LD (`</` cannot close the script);
  - only formations of the latest campaign and jobs are listed in the sitemap and indexable; an older formation page
    is served with `noindex` (it no longer recruits under that code);
  - a preview deployment is never indexed (`noindex` on every page, `Disallow: /` in robots.txt);
  - the site says it is independent: not affiliated with Parcoursup or the ministry.
"""
from __future__ import annotations

import html
import json
import os
import re

SITE = "SupCompass"
TAGLINE = "Les chiffres officiels de l'orientation post-bac, expliqués"     # sprint Q1 (owner, 2026-11-13); legal.TAGLINE
INDEPENDENT = "SupCompass est un site indépendant, non affilié à Parcoursup ni au ministère de l'Enseignement supérieur."
CAVEAT = "Des résultats des campagnes passées, pas des chances d'admission."
ROBOTS_OFF = ("/api/search", "/api/voeux", "/api/e", "/api/stats", "/api/contact")
COD = re.compile(r"^\d{1,9}$")
MAX_RELATED = 12


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def num(x) -> str:
    """French thousands separator (narrow no-break space) as the app's toLocaleString."""
    if x is None:
        return "—"
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    if isinstance(x, int):
        return f"{x:,}".replace(",", " ")
    return f"{x:.1f}".replace(".", ",")


def pct(x) -> str:
    return "—" if x is None else f"{num(round(x) if abs(x - round(x)) < 1e-9 else x)} %"


def json_ld(obj: dict) -> str:
    """JSON for a <script> block: '<', '>' and '&' escaped so a stored string can never close the script."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def is_preview() -> bool:
    return os.environ.get("VERCEL_ENV") == "preview"


def base_url(host: str | None, scheme: str = "https") -> str:
    """Canonical origin: the production domain Vercel declares, else the host that asked."""
    prod = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
    if prod:
        return "https://" + prod.strip().rstrip("/").removeprefix("https://").removeprefix("http://")
    host = (host or "localhost").split(",")[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d{1,5})?", host):
        host = "localhost"
    return f"{scheme}://{host}"


# ------------------------------------------------------------------------- data
def latest_session(con) -> int:
    return con.execute("SELECT max(session) FROM core.formation_year").fetchone()[0]


def formation(con, cod: str) -> dict | None:
    """The latest record of one formation, with the jobs of its Onisep sheet and related formations."""
    if not COD.match(cod or ""):
        return None
    cur = con.execute("""SELECT session, cod_aff_form, g_ea_lib_vx, lib_for_voe_ins, fil_lib_voe_acc, lib_comp_voe_ins, fili,
                                ville_etab, acad_mies, contrat_etab, select_form, taux_acces_ens, acc_tot, capa_fin
                         FROM core.formation_year WHERE cod_aff_form = ? ORDER BY session DESC LIMIT 1""", [cod])
    r = cur.fetchone()
    if r is None:
        return None
    rec = dict(zip([d[0] for d in cur.description], r))
    last = latest_session(con)
    rec["indexable"] = rec["session"] == last
    rec["metiers"] = []
    has = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'core'").fetchall()}
    if {"onisep_link", "onisep_formation_metier", "onisep_metier"} <= has:
        rec["metiers"] = [dict(id=i, nom=n) for i, n in con.execute(
            """SELECT DISTINCT m.met_id, m.nom FROM core.onisep_link l JOIN core.onisep_formation_metier fm USING (for_id)
               JOIN core.onisep_metier m USING (met_id) WHERE l.cod_aff_form = ? AND l.session = ? ORDER BY m.nom, m.met_id LIMIT 30""",
            [cod, rec["session"]]).fetchall()]
    rec["related"] = [dict(cod=c, etab=e, ville=v, label=lb) for c, e, v, lb in con.execute(
        """SELECT cod_aff_form, g_ea_lib_vx, ville_etab, lib_for_voe_ins FROM core.formation_year
           WHERE session = ? AND fil_lib_voe_acc = ? AND acad_mies = ? AND cod_aff_form <> ?
           ORDER BY ville_etab, g_ea_lib_vx, cod_aff_form LIMIT ?""",
        [last, rec["fil_lib_voe_acc"], rec["acad_mies"], cod, MAX_RELATED]).fetchall()]
    return rec


def sitemap_entries(con) -> list[str]:
    """Paths to index: every formation of the latest campaign, every job."""
    last = latest_session(con)
    paths = [f"/formation/{c}" for (c,) in con.execute(
        "SELECT DISTINCT cod_aff_form FROM core.formation_year WHERE session = ? ORDER BY 1", [last]).fetchall()]
    has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'onisep_metier'").fetchone()[0]
    if has:
        paths += [f"/metier/{m}" for (m,) in con.execute("SELECT met_id FROM core.onisep_metier ORDER BY 1").fetchall()]
    from . import legal                                   # sprint Q1: the trust and compliance pages are indexable too
    return paths + [f"/{s}" for s in legal.SLUGS]


# ------------------------------------------------------------------------- rendering
def head_tags(title: str, description: str, canonical: str, indexable: bool, ld: dict | None) -> str:
    robots = "index, follow" if indexable and not is_preview() else "noindex, follow"
    out = [f"<title>{esc(title)}</title>",
           f'<meta name="description" content="{esc(description)}">',
           f'<link rel="canonical" href="{esc(canonical)}">',
           f'<meta name="robots" content="{robots}">',
           f'<meta property="og:site_name" content="{SITE}">',
           f'<meta property="og:title" content="{esc(title)}">',
           f'<meta property="og:description" content="{esc(description)}">',
           f'<meta property="og:url" content="{esc(canonical)}">',
           '<meta property="og:locale" content="fr_FR">', '<meta property="og:type" content="website">']
    if ld:
        out.append(f'<script type="application/ld+json">{json_ld(ld)}</script>')
    return "\n".join(out)


def formation_title(r: dict) -> str:
    return f"{r['lib_for_voe_ins'] or r['fil_lib_voe_acc']} à {r['ville_etab']} ({r['g_ea_lib_vx']}) : taux d'accès {r['session']} | {SITE}"


def formation_description(r: dict) -> str:
    """The official figures and the caveat first (a search engine shows about 160 characters), the full label after."""
    places = f" pour {num(r['capa_fin'])} places" if r.get("capa_fin") is not None else ""
    rate = f"taux d'accès {r['session']} de {pct(r['taux_acces_ens'])} (indicateur officiel)" if r.get("taux_acces_ens") is not None \
        else f"taux d'accès {r['session']} non publié"
    s = (f"{r['g_ea_lib_vx']} ({r['ville_etab']}) : {rate}, {num(r['acc_tot'])} admis{places}. Ce ne sont pas des chances d'admission. "
         f"{r['lib_for_voe_ins']}.")
    return s if len(s) <= 300 else s[:299].rstrip() + "…"


def formation_body(r: dict) -> str:
    tile = lambda label, value, note: (f'<div class="sum-tile"><span class="sum-label">{label}</span>'
                                       f'<span class="sum-value">{value}</span><span class="sum-note">{note}</span></div>')
    places = f"pour {esc(num(r['capa_fin']))} places" if r.get("capa_fin") is not None else "places non publiées"
    jobs = "".join(f'<li><a href="/metier/{esc(m["id"])}">{esc(m["nom"])}</a></li>' for m in r["metiers"])
    rel = "".join(f'<li><a href="/formation/{esc(x["cod"])}">{esc(x["etab"])} · {esc(x["label"])}</a> · {esc(x["ville"])}</li>' for x in r["related"])
    return f"""<article class="seo" data-seo="formation">
<div class="card"><h1>{esc(r['g_ea_lib_vx'])}</h1><div>{esc(r['lib_for_voe_ins'])}</div>
<div class="muted small">{esc(r['ville_etab'])} · {esc(r['acad_mies'])} · {esc(r['contrat_etab'])} · {esc(r['select_form'])} · n° Parcoursup {esc(r['cod_aff_form'])}</div>
<p><a href="/#/f/{esc(r['cod_aff_form'])}">Voir la fiche complète</a></p></div>
<section class="card summary" aria-label="L'essentiel"><h2>L'essentiel · campagne {esc(r['session'])}</h2><div class="sum-grid">
{tile(f"Taux d'accès {esc(r['session'])}", esc(pct(r['taux_acces_ens'])), "indicateur officiel, phase principale")}
{tile(f"Admis {esc(r['session'])}", esc(num(r['acc_tot'])), places)}
</div><p class="muted small">{CAVEAT}</p></section>
{f'<section class="card"><h2>Métiers visés par ce diplôme</h2><p class="muted small">Liste nationale de la fiche Onisep du diplôme, pas une promesse d’emploi.</p><ul>{jobs}</ul></section>' if jobs else ""}
{f'<section class="card"><h2>{esc(r["fil_lib_voe_acc"])} : autres formations de l’académie de {esc(r["acad_mies"])}</h2><ul>{rel}</ul></section>' if rel else ""}
</article>"""


def formation_ld(r: dict, url: str) -> dict:
    return {"@context": "https://schema.org", "@type": "EducationalOccupationalProgram", "name": r["lib_for_voe_ins"], "url": url,
            "provider": {"@type": "CollegeOrUniversity", "name": r["g_ea_lib_vx"],
                         "address": {"@type": "PostalAddress", "addressLocality": r["ville_etab"], "addressCountry": "FR"}}}


def metier_title(d: dict) -> str:
    return f"{d['nom']} : diplômes et formations pour y accéder | {SITE}"


def metier_description(d: dict) -> str:
    # a formation linked to several diploma sheets of the job counts once (Codex): the job page's own distinct count
    n_f = d.get("n_formations")
    if n_f is None:
        n_f = len({f["cod_aff_form"] for x in d.get("diplomes") or [] for f in (x.get("formations") or [])})
    lvl = f"Niveau d'études minimum : {d['niveau_acces_min']}. " if d.get("niveau_acces_min") else ""
    return (f"{d['nom']} : {lvl}{num(len(d.get('diplomes') or []))} diplôme(s) d'après l'Onisep, {num(n_f)} formation(s) Parcoursup "
            f"pour s'y préparer. Liste nationale, pas une promesse d'emploi.")


def metier_body(d: dict) -> str:
    items = "".join(
        f'<li>{esc(x.get("libelle"))}<span class="muted small"> · {esc(x.get("niveau") or "niveau non précisé")}'
        f'{" · " + esc(num(len(x.get("formations") or []))) + " formation(s) Parcoursup" if x.get("parcoursup") else " · hors Parcoursup"}</span>'
        + ("<ul>" + "".join(f'<li><a href="/formation/{esc(f["cod_aff_form"])}">{esc(f["etablissement"])}</a> · {esc(f.get("ville"))}</li>'
                            for f in (x.get("formations") or [])[:MAX_RELATED]) + "</ul>" if x.get("parcoursup") and x.get("formations") else "")
        + "</li>" for x in d.get("diplomes") or [])
    lvl = f'<p class="small">Niveau d’études minimum (Onisep) : {esc(d["niveau_acces_min"])}</p>' if d.get("niveau_acces_min") else ""
    return f"""<article class="seo" data-seo="metier">
<div class="card"><h1>{esc(d['nom'])}</h1>{lvl}
<p><a href="/#/metiers/{esc(d['id'])}">Voir la page complète</a></p></div>
<section class="card"><h2>Diplômes et formations</h2>
<p class="muted small">Liste nationale : un établissement figure parce qu’il prépare le diplôme, pas parce que ses étudiants exercent ce métier. Ce n’est pas une promesse d’emploi.</p>
<ul>{items}</ul><p class="muted small">Source : Onisep, Idéo (licence ODbL).</p></section>
</article>"""


def metier_ld(d: dict, url: str) -> dict:
    return {"@context": "https://schema.org", "@type": "Occupation", "name": d["nom"], "url": url,
            "occupationLocation": {"@type": "Country", "name": "France"}}


def page(shell: str, head: str, body: str) -> str:
    """The app shell with the page's head tags (replacing the default title) and its content inside <main id="view">."""
    shell = re.sub(r"<title>.*?</title>", lambda _m: head, shell, count=1, flags=re.S)
    # R8: the shell's own <main> tag (whatever its attributes); a shell without it is an error, never a page without content
    out, n = re.subn(r'(<main id="view"[^>]*>)(</main>)', lambda m: m.group(1) + body + m.group(2), shell, count=1)
    if n != 1:
        raise RuntimeError("the app shell has no empty <main id=\"view\">")
    return out


def home_head(canonical: str) -> str:
    return head_tags(f"{SITE} — {TAGLINE}",
                     "Taux d'accès, admis, profils des admis, réussite, poursuite d'études et métiers de chaque formation Parcoursup, "
                     "à partir des données officielles 2022–2025, expliqués simplement. Des résultats des campagnes passées, "
                     "pas des chances d'admission.",
                     canonical, True, {"@context": "https://schema.org", "@type": "WebSite", "name": SITE, "url": canonical})


def not_found_body(what: str) -> str:
    return f'<div class="card"><h1>Page introuvable</h1><p>{esc(what)}</p><p><a href="/">Retour à l’accueil</a></p></div>'


def robots(base: str) -> str:
    if is_preview():
        return "User-agent: *\nDisallow: /\n"
    # the data the pages render from (/api/meta, /api/formation, /api/metier…) stays allowed: a crawler that renders the app
    # must be able to load it (Codex); only routes that record an event, hold a personal list or are private are kept off
    return ("User-agent: *\n" + "".join(f"Disallow: {p}\n" for p in ROBOTS_OFF) + f"Allow: /\nSitemap: {base}/sitemap.xml\n")


def sitemap(base: str, paths: list[str]) -> str:
    urls = "".join(f"<url><loc>{esc(base + p)}</loc></url>" for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'
