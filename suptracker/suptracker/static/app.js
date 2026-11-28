"use strict";
// SupCompass front-end: hash router + dependency-free SVG charts.

const $view = document.getElementById("view");
let META = null;
const HOME_TITLE = "SupCompass — Les chiffres officiels de l'orientation post-bac, expliqués";   // sprint Q1 (owner): legal.TAGLINE

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// lot 1, PR 10: two académie labels come unaccented from the official files; the page prints them accented, the value (filters,
// profile, requests) stays the published one
const ACAD_LABEL = { Besancon: "Besançon", Etranger: "Étranger" };
const acadLabel = (a) => (a && ACAD_LABEL[a]) || a;
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d });
const pct = (v) => (v === null || v === undefined) ? "—" : `${fmt(v, 1)} %`;
const tip = (key) => {
  const t = META?.methodology?.[key];
  return t ? `<button type="button" class="tip" aria-label="Méthodologie : ${esc(t)}" data-tip="${esc(t)}">i</button>` : "";
};
const label = (f) => META?.fields?.[f]?.label || f;

// ---- sprint Q4 (owner, 2026-11-13): plain language. ONE "estimation" label for every figure the site computes, with the same
// short explanation everywhere (the detail says which calculation); zones explained in words from their own rules (ZONE_RULES);
// an "Et maintenant ?" block on the pages where a student decides; a page of human help (#/info/aide, aide.py).
// Red team scripts/redteam_langage.py (LA1-LA8).
const ESTIM_DEF = "Estimation : un chiffre calculé par SupCompass à partir de chiffres officiels publiés. Ce n'est pas un chiffre officiel, ni une chance d'admission.";
// block: a line under the figure (div); plain: inside a button (a summary tile), where a second button cannot sit
function estimTag(detail, block, plain) {
  const t = block ? "div" : "span";
  const tipBtn = plain ? "" : `<button type="button" class="tip" aria-label="${esc(ESTIM_DEF)}" data-tip="${esc(ESTIM_DEF)}">i</button>`;
  return `<${t} class="estim"><span class="estim-tag">estimation</span>${tipBtn}${detail ? ` · ${detail}` : ""}</${t}>`;
}
// what each zone means, in words, from the zone rules themselves (journey.py constants, mirrored in ZONE_RULES)
function zoneHelp(z) {
  const R = ZONE_RULES, sur100 = (x) => Math.round(x * 100);
  return {
    securite_large: `Une sécurité encore plus solide : taux d'accès d'au moins ${R.large_access} %. Même dans la lecture la moins favorable, au moins ${sur100(R.large_cdf_lo)} admis sur 100 avaient un niveau au bac égal ou inférieur au vôtre.`,
    securite: `La plupart des candidats ont été appelés (taux d'accès d'au moins ${R.securite_access} %) et au moins ${sur100(R.securite_cdf)} admis sur 100 avaient un niveau au bac égal ou inférieur au vôtre.`,
    cible: "Entre sécurité et ambitieux : des admis des années passées avaient un niveau proche du vôtre.",
    ambitieux: `Peu de candidats ont été appelés (taux d'accès sous ${R.ambitieux_access} %), ou moins de ${sur100(R.ambitieux_cdf)} admis sur 100 avaient un niveau au bac égal ou inférieur au vôtre.`,
    hors_profil: `Presque aucun admis (moins de ${sur100(R.hors_profil_cdf)} sur 100) n'avait un niveau au bac égal ou inférieur au vôtre.`,
  }[z] || "";
}
const ZONE_NOT_CHANCE = "Votre niveau, c'est votre mention, ou votre moyenne si vous l'avez indiquée. Une zone décrit les admis des années passées : ce n'est jamais une chance d'admission.";
// owner, 2026-11-19: the rate a zone is read on
const ZONE_AXIS = "Le taux lu est celui de vos deux spécialités quand le rapport public de la formation le publie, pour au moins 20 candidats. Sinon, c'est le taux d'accès officiel.";
// what the zone was read on, said beside it when it is the student's pair rate (journey.pick_pair), never a figure of our own
function zoneAxisNote(f) {
  const s = f && f.taux_zone_source;
  if (!s) return "";
  const what = s.source === "autres" ? "la ligne « Autres paires de spécialités »" : "vos deux spécialités";
  return `<div class="muted small zaxis">lue sur ${what} : ${pct1(s.taux)} (rapport public ${esc(s.session)})</div>`;
}
function zoneLegend() {
  return `<details class="zone-legend"><summary>Que veulent dire les zones ?</summary><ul>${["securite", "cible", "ambitieux", "hors_profil"].map((z) =>
    `<li>${zonePillHtml(z)} ${esc(zoneHelp(z))}</li>`).join("")}<li>${zonePillHtml("securite", false, true)} ${esc(zoneHelp("securite_large"))}</li></ul><p class="small muted">${esc(ZONE_AXIS)}</p><p class="small muted">${esc(ZONE_NOT_CHANCE)}</p></details>`;
}
// "Et maintenant ?": a few next actions, always ending with a person to talk to. Links only (no figure, no ranking).
const AIDE_STEP = { href: "#/info/aide", text: "En parler à quelqu'un : professeur principal, psychologue de l'Éducation nationale, CIO, Mon orientation en ligne" };
const NEXT_STEPS = {
  apresjuin: [{ href: "#/calendrier", text: "Noter les dates de Parcoursup" },
    { href: "#/voeux", text: "Revoir votre liste Mes vœux" }],
  formation: [{ href: "#/voeux", text: "Voir votre liste Mes vœux et l'équilibre de ses zones" },
    { href: "#/guide", text: "Construire une liste équilibrée, avec au moins un vœu de sécurité" }],
  parcours: [{ href: "#/guide", text: "Choisir des vœux dans plusieurs zones, avec au moins un vœu de sécurité" },
    { href: "#/carte", text: "Voir ces formations sur la carte, près de chez vous" }],
  voeux: [{ href: "#/guide", text: "Vérifier votre liste étape par étape, puis la partager avec un adulte" },
    { href: "#/calendrier", text: "Noter les dates de Parcoursup" },
    { href: "https://www.parcoursup.gouv.fr/contenus/les-solutions-si-vous-n-avez-pas-recu-de-proposition-d-admission-3456", text: "Sans proposition en juillet : la phase complémentaire, puis la commission d'accès (CAES)" }],
  reorientation: [{ href: "#/voeux", text: "Garder vos formations dans Mes vœux" },
    { href: "#/calendrier", text: "Noter les dates de Parcoursup" }],
  metier: [{ href: "#/metiers", text: "Comparer avec d'autres métiers" },
    { href: "#/carte", text: "Voir les formations sur la carte" }],
  observatoire: [{ href: "#/carte", text: "Chercher une formation, avec son taux d'accès officiel" },
    { href: "#/selectivite", text: "Voir la vraie sélectivité d'un type de formation" }],
  premiere: [{ href: "#/specialites", text: "Voir quelles spécialités ont les admis de chaque type de formation" },
    { href: "#/calendrier", text: "Noter les dates de Parcoursup" }],
};
const NEXT_KINDS = Object.keys(NEXT_STEPS);
function nextSteps(kind, extra) {
  const items = [...(extra || []), ...(NEXT_STEPS[kind] || []), AIDE_STEP];
  return `<section class="card next-steps" aria-labelledby="next-${kind}"><h2 id="next-${kind}">Et maintenant ?</h2><ul>${items.map((x) =>
    `<li><a href="${esc(x.href)}"${/^https:/.test(x.href) ? ' target="_blank" rel="noopener"' : ""}>${esc(x.text)}${/^https:/.test(x.href) ? " ↗" : ""}</a></li>`).join("")}</ul></section>`;
}

// A FastAPI validation error carries a LIST of objects: shown raw, the page read "[object Object]" (product audit, 2026-11-10)
function apiErrorText(detail) {
  if (typeof detail === "string" && detail) return detail;
  return "La page n'a pas pu être chargée (demande refusée par le serveur). Rechargez-la ou revenez à l'accueil.";
}
async function api(path) {
  const r = await fetch(path);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* non-JSON error body */ }
    throw new Error(apiErrorText(msg));
  }
  return r.json();
}

// ---- comparator basket (per-viewer convenience only) -----------------------
const basket = {
  get() { try { return JSON.parse(localStorage.getItem("basket") || "[]"); } catch (_) { return []; } },
  set(v) { try { localStorage.setItem("basket", JSON.stringify(v)); } catch (_) { /* storage blocked */ } this.render(); },
  toggle(cod) { const b = this.get(); const i = b.indexOf(cod); i >= 0 ? b.splice(i, 1) : b.length < 6 && b.push(cod); this.set(b); },
  render() { const n = this.get().length; document.querySelectorAll('[data-count="basket"]').forEach((el) => { el.textContent = n; el.hidden = n === 0 && !!el.closest(".tabbar"); }); },
};

// ---- sprint 11 "Mes vœux": the list stays in this browser (codes only) ------
const voeux = {
  MAX: 10,
  // stored data is never trusted: codes only, digits, deduplicated, at most 10. The pre-sprint-11 list of
  // "Mon parcours" ("wishlist", with zones frozen at pinning time) is migrated once, codes only.
  get() {
    let v;
    try { v = JSON.parse(localStorage.getItem("voeux")); } catch (_) { v = null; }
    if (!Array.isArray(v)) {
      try { v = (JSON.parse(localStorage.getItem("wishlist")) || []).map((w) => w && w.cod_aff_form); } catch (_) { v = []; }
      if (!Array.isArray(v)) v = [];
    }
    return [...new Set(v.filter((c) => typeof c === "string" && /^\d{1,9}$/.test(c)))].slice(0, this.MAX);
  },
  set(v) { try { localStorage.setItem("voeux", JSON.stringify(v)); } catch (_) { /* storage blocked */ } this.render(); },
  has(cod) { return this.get().includes(cod); },
  add(cod) { const v = this.get(); if (!v.includes(cod) && v.length < this.MAX) { v.push(cod); this.set(v); track("action", { a: "voeu" }); } return v.includes(cod); },   // sprint 18: counted, never which formation
  remove(cod) { this.set(this.get().filter((c) => c !== cod)); },
  render() { const n = this.get().length; document.querySelectorAll('[data-count="voeux"]').forEach((el) => { el.textContent = n; el.hidden = n === 0 && !!el.closest(".tabbar"); }); profileBar.render(); },
};

// ---- PR 18 (owner, 2026-11-28): « Mes vœux en apprentissage », a SEPARATE list in this browser (codes only) ----
// The apprenticeship offers of the latest map publish no admission statistics: no zone, no rate, never counted among the main
// list's zones, never a safety. Same cleaning as the main list; its own cap (Parcoursup: « 10 vœux supplémentaires pour des
// formations en apprentissage », the official calendar's sentence, printed by the page). Not counted by the audience measure.
const voeuxApp = {
  MAX: 10,
  get() {
    let v;
    try { v = JSON.parse(localStorage.getItem("voeuxApp")); } catch (_) { v = null; }
    if (!Array.isArray(v)) v = [];
    return [...new Set(v.filter((c) => typeof c === "string" && /^\d{1,9}$/.test(c)))].slice(0, this.MAX);
  },
  set(v) { try { localStorage.setItem("voeuxApp", JSON.stringify(v)); } catch (_) { /* storage blocked */ } },
  has(cod) { return this.get().includes(cod); },
  add(cod) { const v = this.get(); if (!v.includes(cod) && v.length < this.MAX) { v.push(cod); this.set(v); } return v.includes(cod); },
  remove(cod) { this.set(this.get().filter((c) => c !== cod)); },
};
function appVoeuLabel(cod) {
  const inV = voeuxApp.has(cod), full = !inV && voeuxApp.get().length >= voeuxApp.MAX;
  return { inV, full, text: inV ? "Retirer de mes vœux en apprentissage" : full ? "Vœux en apprentissage : liste pleine" : "Ajouter à mes vœux en apprentissage" };
}
function appVoeuButton(cod) {
  const l = appVoeuLabel(cod);
  return `<button type="button" class="small" data-appvoeu="${esc(cod)}" aria-pressed="${l.inV}"${l.full ? ` disabled title="${voeuxApp.MAX} vœux en apprentissage au maximum dans cette liste"` : ""}>${l.text}</button>`;
}
// one delegated handler: the button lives in cards drawn by several pages (search, map, formation page)
document.addEventListener("click", (e) => {
  const b = e.target && e.target.closest ? e.target.closest("[data-appvoeu]") : null;
  if (!b || b.disabled) return;
  const cod = b.dataset.appvoeu;
  if (!/^\d{1,9}$/.test(cod || "")) return;
  voeuxApp.has(cod) ? voeuxApp.remove(cod) : voeuxApp.add(cod);
  document.querySelectorAll("[data-appvoeu]").forEach((x) => {
    const l = appVoeuLabel(x.dataset.appvoeu);
    x.textContent = l.text; x.setAttribute("aria-pressed", String(l.inV)); x.disabled = l.full;
    if (l.full) x.title = `${voeuxApp.MAX} vœux en apprentissage au maximum dans cette liste`; else x.removeAttribute("title");
  });
});

// ---- point 4 of the UI brief: the profile and the zones of "Mes vœux", at the top of every page ----
// The stored profile is never trusted: the same cleaning as "Mes vœux". vxQuery is the ONE query both send, so the bar and
// the page always count the same zones (red team P2). Counts only, never a chance.
// Sprint R5 (owner, 2026-11-12): six bands (rattrapage 8-10 and TB félicitations added) and an optional average ("moyenne
// visée", 8 to 20) that places the student INSIDE the band: twin of journey.BANDS / band_of. "Sans mention" spans 8-12 (the
// rattrapage is published with it), centred on 11. An average always sets its band (the average wins over a stale mention).
const MENTION_CODES = ["rattrapage", "sansmention", "ab", "b", "tb", "tbf"];
const BANDS = { sansmention: [8, 12, 11], ab: [12, 14, 13], b: [14, 16, 15], tb: [16, 18, 17], tbf: [18, 20, 19] };
const BAND_SIGMA = 1;
function validMoyenne(v) {
  if (v === null || v === undefined || v === "") return null;
  const x = typeof v === "number" ? v : Number(String(v).trim().replace(",", "."));
  return Number.isFinite(x) && x >= 8 && x <= 20 ? Math.round(x * 10) / 10 : null;
}
function bandOf(g) {                                                    // the profile's band of an average (rattrapage below 10)
  if (g < 10) return "rattrapage";
  if (g < 12) return "sansmention";
  return ["ab", "b", "tb"].find((m) => g >= BANDS[m][0] && g < BANDS[m][1]) || "tbf";
}
// R6 (owner, 2026-11-12): the average never leaves the browser. A query carries the BAND only ("rattrapage" is read in the
// "sans mention" band, which SIES publishes with it); the page reads the zones inside the band itself (`relire`, below), from
// the counts every answer carries. The answers stay the same for every student of a band, so they stay shared-cached.
function bandParam(p) { return p.mention === "rattrapage" ? "sansmention" : p.mention; }
function mentionParams(qs, p) {
  qs.set("mention", bandParam(p));
  return qs;
}
// the average the page reads with: the profile's own, else the top of 8-10 for a rattrapage (journey.RATTRAPAGE_TOP), else none
function localAverage(p) {
  return p.moyenne !== null && p.moyenne !== undefined ? p.moyenne : p.mention === "rattrapage" ? 10 : null;
}
const moyenneText = (m) => `${fmt(m, 1)}/20`;
// R5 (review): the band and the average in words, from the VALIDATED profile (a stale stored mention never shows)
function mentionWords(p) {
  const v = vxProfile(p);
  const m = v.mention === "rattrapage" ? "bac au rattrapage" : `mention ${MENTION_SHORT[v.mention]}`;
  return v.moyenne !== null ? `${m}, moyenne visée ${moyenneText(v.moyenne)}` : m;
}
function vxProfile(p) {
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";
  const moyenne = validMoyenne(p.moyenne);
  const mention = moyenne !== null ? bandOf(moyenne) : MENTION_CODES.includes(p.mention) ? p.mention : "ab";
  const jv = typeof JV !== "undefined" ? JV : null;                       // the vocabulary, when "Mon parcours" loaded it
  const codes = jv && jv.voies && jv.voies[serie] ? jv.voies[serie].map((x) => x.code) : null;
  const keep = serie !== "bg" && typeof p.voie === "string" && (!codes || p.voie === "autre" || codes.includes(p.voie));
  return { ...p, serie, mention, moyenne, voie: keep ? p.voie : null, voie_label: keep ? p.voie_label : null,
    statut: p.statut === "reorientation" ? "reorientation" : "terminale" };
}
// sprint 21: "Je ne suis plus en terminale" (reorientation, return to studies). No zone exists for this group: SIES publishes
// no mention and no series for it, so the pages show the estimated access outside terminale instead, never a zone or a Plan B.
const REO_LABEL = "Je ne suis plus en terminale";
const isReo = (p) => !!p && typeof p === "object" && p.statut === "reorientation";
// the stored profile of a student in terminale, or null: every page that reads the bac, the specialties or the mention goes
// through it, so a student who is not in terminale never gets a zone, a doublette or a series read from stale fields (review)
function bacProfile() {
  const p = store.get("profile", null);
  return p && typeof p === "object" && !Array.isArray(p) && !isReo(p) ? p : null;
}
function vxQuery(ids, prof) {
  const qs = mentionParams(new URLSearchParams({ ids: ids.join(","), serie: prof.serie }), prof);
  if (prof.serie === "bg") { qs.set("spe1", prof.spe1 || "MATHS"); qs.set("spe2", prof.spe2 || "SES"); }
  if (prof.academie) qs.set("academie", prof.academie);
  if (prof.serie !== "bg" && typeof prof.voie === "string" && prof.voie) qs.set("voie", prof.voie.slice(0, 120));   // sprint 20
  return qs;
}
// ---- R6: the zone read in the browser, twin of journey.stage2 for an average (journey.zone_reading, series_position, wilson,
// classify_zone; the uniform reading that makes a zone uncertain), of planb.plan_b, of voeux.read_list and voeux.completer.
// The server's own reading with `moyenne` stays the reference the red team compares every twin with (redteam_lecture.py).
const ZONE_RULES = { hors_profil_cdf: 0.02, ambitieux_access: 30.0, ambitieux_cdf: 0.15, securite_access: 70.0, securite_cdf: 0.50, large_access: 85.0, large_cdf_lo: 0.60 };
const MIN_BOUNDS_N = 10;                                                // journey.MIN_BG_FOR_BOUNDS
const ZONE_RANK = { hors_profil: 0, ambitieux: 1, cible: 2, securite: 3 };
const SAME_ZONE_ACCESS_GAIN = 15.0, MAX_PER_ETABLISSEMENT = 2, POS_EPS = 1e-9;          // planb.py (POS_EPS: equal positions up to float noise)
const VX_SITUATED = ["securite", "cible", "ambitieux", "hors_profil"];
function wilsonCI(k, n) {
  const z = 1.959964;
  if (!n) return [null, null];
  const p = k / n, den = 1 + z * z / n;
  const centre = (p + z * z / (2 * n)) / den, half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den;
  return [k === 0 ? 0 : Math.max(0, centre - half), k === n ? 1 : Math.min(1, centre + half)];
}
function zoneOf(taux, cdf) {
  const z = ZONE_RULES;
  if (cdf < z.hors_profil_cdf) return "hors_profil";
  if (taux < z.ambitieux_access || cdf < z.ambitieux_cdf) return "ambitieux";
  if (taux >= z.securite_access && cdf >= z.securite_cdf) return "securite";
  return "cible";
}
const isNum = (v) => v !== null && v !== undefined;
function classifyZone(taux, cdf, lo, hi) {
  if (!isNum(cdf) || !isNum(taux)) return { zone: "indetermine", uncertain: true };
  const zone = zoneOf(taux, cdf);
  const probes = [lo, hi].filter(isNum);
  if (isNum(lo) && isNum(hi)) for (const c of [ZONE_RULES.hors_profil_cdf, ZONE_RULES.ambitieux_cdf, ZONE_RULES.securite_cdf]) if (lo <= c && c <= hi) probes.push(c);
  return { zone, uncertain: probes.some((v) => zoneOf(taux, v) !== zone) };
}
// journey.is_large (owner, 2026-11-19): « sécurité large », a nuance of a SURE sécurité, read on the LOWER bound of the share
function isLarge(zone, uncertain, taux, ciLo) {
  return zone === "securite" && !uncertain && isNum(taux) && isNum(ciLo) && taux >= ZONE_RULES.large_access && ciLo >= ZONE_RULES.large_cdf_lo;
}
// series_position: each campaign's bounds of the band, mixed with the band below by w (a campaign without the band below is
// left out when it mixes), summed in the same order
function seriesPos(s, w, cdfAll) {
  let klo = 0, khi = 0, g = 0, used = 0;
  for (const [b0, b1, p0, p1, gc] of s || []) {
    let lo = b0, hi = b1;
    if (w < 1) {
      if (p0 === null || p0 === undefined) continue;
      lo = (1 - w) * p0 + w * b0; hi = (1 - w) * p1 + w * b1;
    }
    klo += lo; khi += hi; g += gc; used += 1;
  }
  if (g < MIN_BOUNDS_N) return null;
  const lo = klo / g, hi = khi / g, proj = cdfAll === null ? null : Math.min(Math.max(cdfAll, lo), hi);
  return { bounds: [lo, hi], ci: [wilsonCI(klo, g)[0], wilsonCI(khi, g)[1]], width: hi - lo, n: g, campaigns: used,
    cdf_used: proj !== null ? proj : (lo + hi) / 2, projected: cdfAll !== null && !(lo <= cdfAll && cdfAll <= hi) };
}
// the reading of one formation for an average g in band `band` (w: normal curve, wu: uniform spread); bg: a bac général reading
// (the « sécurité large » nuance is read for the bac général only, as journey.stage2 does)
function lire(L, taux, band, g, bg) {
  const w = withinBand(g, band), wu = withinBand(g, band, "uniforme");
  const at = (ww) => {
    const k = L.kt - (1 - ww) * L.kb, cdf = L.n ? k / L.n : null, [lo, hi] = wilsonCI(k, L.n), sp = seriesPos(L.s, ww, cdf);
    return { k, cdf, lo, hi, sp, cz: sp ? sp.cdf_used : cdf, ciz: sp ? sp.ci : [lo, hi] };
  };
  const r = at(w);
  let { zone, uncertain } = L.ferme ? { zone: "non_ouvert", uncertain: false } : classifyZone(taux, r.cz, r.ciz[0], r.ciz[1]);
  let loU = r.ciz[0];
  if (wu !== w && zone !== "non_ouvert" && zone !== "indetermine" && !uncertain) {
    const u = at(wu);
    uncertain = classifyZone(taux, u.cz, u.ciz[0], u.ciz[1]).zone !== zone;      // R5: the within-band hypothesis decides
    loU = u.ciz[0];
  }
  if (L.fragile && zone !== "non_ouvert") { zone = "indetermine"; uncertain = true; }
  const large = !!bg && isLarge(zone, uncertain, taux, r.ciz[0]) && isLarge(zone, uncertain, taux, loU);   // both hypotheses, like « incertain »
  const n = L.n;
  return { ...r, w, wu, zone, uncertain, large,
    position: !n ? null : { normale: r.k / n, uniforme: (L.kt - (1 - wu) * L.kb) / n, bornes: [(L.kt - L.kb) / n, L.kt / n] } };
}
// owner, 2026-11-19: the rate the zone is read on: the student's pair rate when the formation's own report publishes it (the
// server's taux_zone), else the official one (journey.stage2, planb._tz)
const tauxZone = (f) => (isNum(f.taux_zone) ? f.taux_zone : f.taux_acces_ens);
// a stage-2 row (Mon parcours, the map), read for the average
function relire(f, band, g) {
  if (!f || !f.lec || g === null) return f;
  const r = lire(f.lec, tauxZone(f), band, g, f.serie === "bg");
  return { ...f, zone: r.zone, uncertain: r.uncertain, large: r.large, cdf: r.cdf, cdf_ci: [r.lo, r.hi], spos: r.sp, position: r.position,
    trend: Array.isArray(f.trend) ? f.trend.map((t) => (isNum(t.kt) ? { ...t, cdf: t.n ? (t.kt - (1 - r.w) * t.kb) / t.n : null } : t)) : f.trend,
    // calibration.attach(continuous): the share's ranges and the zone's stability were measured on the band's reading
    repere: f.repere ? { ...f.repere, cdf_hat: null, cdf_lo: null, cdf_hi: null, zone_confirmed: null, zone_n: null, continu: true } : f.repere };
}
// a Plan B / Mes vœux view (planb._view): the position is the series reading when it exists, else the all-series share
function relireVue(v, band, g) {
  if (!v || !v.lec || g === null) return v;
  const r = lire(v.lec, tauxZone(v), band, g, v.serie === "bg");
  return { ...v, zone: r.zone, uncertain: r.uncertain, large: r.large, position: r.sp ? r.sp.cdf_used : r.cdf, bounds: r.sp ? r.sp.bounds : null,
    _pm: r.position };
}
// the profile's reading: the band sent, the average kept (null = no average: the answer is used as it came)
function lectureOf(p) { const v = vxProfile(p); return { band: bandParam(v), g: localAverage(v), given: v.moyenne }; }
function stage2Local(d, p) {
  const { band, g, given } = lectureOf(p);
  if (!d || g === null) return d;
  return { ...d, moyenne: given, formations: (d.formations || []).map((f) => relire(f, band, g)) };
}
// voeux.read_list: fixed rules over the zones, counts only
function readList(vx) {
  const z = vx.map((v) => v.zone), cnt = (k) => z.filter((x) => x === k).length;
  const n = {};
  for (const k of [...VX_SITUATED, "indetermine", "non_ouvert"]) n[k] = cnt(k);
  n.non_situe = vx.filter((v) => v.status !== "ok").length;
  const sure = vx.filter((v) => v.zone === "securite" && !v.uncertain).length;
  const large = vx.filter((v) => v.zone === "securite" && !v.uncertain && v.large).length;
  const sureBg = vx.filter((v) => v.zone === "securite" && !v.uncertain && v.serie === "bg").length;
  const situated = VX_SITUATED.reduce((a, k) => a + n[k], 0);
  const msgs = [];
  if (vx.length) {
    if (!sure) msgs.push(["warn", "aucune_securite"]);
    if (situated && n.ambitieux + n.hors_profil > situated / 2) msgs.push(["warn", "majorite_ambitieuse"]);
    if (n.hors_profil) msgs.push(["warn", "hors_profil"]);
    if (n.non_ouvert) msgs.push(["warn", "non_ouvert"]);
    if (n.indetermine + n.non_situe) msgs.push(["info", "non_situe"]);
    if (situated && !n.cible) msgs.push(["info", "aucune_cible"]);
    if (!msgs.length) msgs.push(["info", "equilibree"]);
    if (sureBg && !large) msgs.push(["info", "aucune_securite_large"]);
  }
  return { n: vx.length, zones: n, securite_sure: sure, securite_large: large, situes: situated, messages: msgs.map(([niveau, code]) => ({ niveau, code })) };
}
function voeuxLocal(d, p) {
  const { band, g, given } = lectureOf(p);
  if (!d || !Array.isArray(d.voeux) || g === null) return d;
  const vx = d.voeux.map((v) => {
    if (v.status !== "ok" || !v.lec) return v;
    const r = relireVue(v, band, g);
    const { _pm, ...rest } = r;
    return { ...rest, position_moyenne: _pm };
  });
  return { ...d, moyenne: given, voeux: vx, lecture: readList(vx) };
}
// planb.usable / why_better / the order and the caps, over a pool answer
function pbUsable(f) {
  return f.zone in ZONE_RANK && !f.rate_fragile && !f.small_cohort && isNum(f.taux_acces_ens) && isNum(f.position);
}
function whyBetter(t, c) {
  const zt = ZONE_RANK[t.zone], zc = ZONE_RANK[c.zone];
  if (zt === undefined) return null;
  if (zc > zt && !c.uncertain) return "zone";
  if (zc >= zt && tauxZone(c) >= (tauxZone(t) || 0) + SAME_ZONE_ACCESS_GAIN && (c.position || 0) >= (t.position || 0) - POS_EPS) return "acces";
  return null;
}
// the order of planb.plan_b and voeux.completer: the student's académie first, then the distance, (Plan B: the better zone),
// then the attribute-neutral tie-break computed by the server
function pbOrder(academie, withZone) {
  const key = (c) => [academie && c.academie === academie ? 0 : 1, isNum(c.dist) ? c.dist : Infinity, withZone ? -ZONE_RANK[c.zone] : 0, c.tb];
  return (a, b) => {
    const x = key(a), y = key(b);
    for (let i = 0; i < x.length; i++) if (x[i] < y[i]) return -1; else if (x[i] > y[i]) return 1;
    return 0;
  };
}
function capPerEtab(pool, limit) {
  const out = [], per = new Map();
  for (const c of pool) {
    const k = JSON.stringify([c.etablissement, c.ville]);
    if ((per.get(k) || 0) >= MAX_PER_ETABLISSEMENT) continue;
    per.set(k, (per.get(k) || 0) + 1);
    out.push(c);
    if (out.length >= limit) break;
  }
  return out;
}
const POOL_KEYS = ["lec", "dist", "tb", "_pm"];
const unpool = (v) => Object.fromEntries(Object.entries(v).filter(([k]) => !POOL_KEYS.includes(k)));
function planBLocal(d, p, academie) {
  if (!d || d.status !== "pool") return d;
  const { band, g, given } = lectureOf(p);
  const { candidates, limit, ...base } = d;
  const t = relireVue(d.target, band, g);
  const head = { ...base, moyenne: given, target: unpool(t) };
  if (!(t.zone in ZONE_RANK)) return { ...head, status: "non_disponible", alternatives: [],
    reason: `la formation visée ne peut pas être située pour votre profil (${t.zone.replace(/_/g, " ")})` };
  if (t.zone === "securite" && !t.uncertain) return { ...head, status: "deja_accessible", alternatives: [],
    reason: "la formation visée est déjà un vœu de sécurité pour votre profil" };
  const pool = [];
  let hidden = 0;
  for (const c0 of candidates || []) {
    const c = relireVue(c0, band, g);
    if (!pbUsable(c)) continue;
    const why = whyBetter(t, c);
    if (why && c.paid && !d.include_paid) { hidden += 1; continue; }
    if (why) pool.push({ ...c, why });
  }
  pool.sort(pbOrder(academie, true));
  const out = capPerEtab(pool, limit).map(unpool);
  return { ...head, status: out.length ? "ok" : "aucune", alternatives: out, n_candidates: pool.length, hidden_paid: hidden,
    reason: out.length ? null : "aucune formation de la même filière n'est plus accessible pour votre profil" };
}
function completerLocal(d, p, academie) {
  if (!d || !d.pool) return d;
  const { band, g } = lectureOf(p);
  let hidden = 0;
  const filieres = (d.filieres || []).map((fl) => {
    const pool = [];
    for (const c0 of fl.candidates || []) {
      const c = relireVue(c0, band, g);
      if (!pbUsable(c) || c.zone !== "securite" || c.uncertain) continue;
      if (c.paid && !d.include_paid) { hidden += 1; continue; }
      pool.push({ ...c, why: "securite" });
    }
    pool.sort(pbOrder(academie, false));
    const { candidates, ...rest } = fl;
    return { ...rest, n_candidates: pool.length, formations: capPerEtab(pool, d.per_filiere).map(unpool) };
  });
  const { pool, ...base } = d;
  return { ...base, filieres, hidden_paid: hidden };
}
// the map: the zones read here from the answer's `lectures` (asked only when the profile has an average)
function carteZonesLocal(z, p) {
  const { band, g } = lectureOf(p);
  if (!z || g === null || !z.lectures) return z;
  const zones = {}, larges = [], bg = vxProfile(p).serie === "bg";
  for (const [cod, x] of Object.entries(z.lectures)) {
    const r = lire(x.lec, tauxZone(x), band, g, bg);
    zones[cod] = r.zone;
    if (r.large) larges.push(cod);
  }
  return { zones, larges: larges.sort() };
}
const PB_ZONES = ["securite", "cible", "ambitieux"];
const profileBar = {
  key: "", data: null, tab: "home", open: false,
  render(tab) {
    if (tab) this.tab = tab;
    const el = document.getElementById("profile-bar");
    if (!el) return;
    const raw = store.get("profile", null);
    profileChip(this.tab, raw);
    if (this.tab === "stats" || this.tab === "liste") { el.hidden = true; return; }   // sprint 22: a shared list is someone else's
    if (this.tab === "accueil" && !hasStoredProfile(raw)) { el.hidden = true; return; }  // Q5: the hero carries the one call
    el.hidden = false;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      this.key = ""; this.data = null;
      const has = voeux.get().length > 0;
      el.innerHTML = has ? `<span class="pb-who">Pas encore de profil : les zones de vos vœux ne peuvent pas être lues.</span><a class="pb-link" href="#/profil">Créer mon profil</a>`
        : `<a class="pb-link" href="#/profil">Pas encore de profil : créer le mien (1 minute, il reste dans ce navigateur)</a>`;
      return;
    }
    const prof = vxProfile(raw);
    const ids = voeux.get();
    let list, short = "";
    if (isReo(prof)) {                                                   // sprint 21: no zone for this group, no zone request
      this.key = ""; this.data = null;
      list = `<a class="pb-link" href="#/voeux">Mes vœux : ${ids.length ? `${fmt(ids.length)}, accès estimé hors terminale` : "aucun pour l'instant"}</a>`;
    } else if (!ids.length) { this.key = ""; this.data = null; list = `<a class="pb-link" href="#/voeux">Mes vœux : aucun pour l'instant</a>`; }
    else {
      const k = vxQuery(ids, prof).toString();
      if (this.key !== k) {
        this.key = k; this.data = null;
        // R6 (review): the band-only answer is kept RAW and read for the CURRENT profile at every render: an average edited
        // inside its band, or rattrapage <-> sans mention, sends the same query but must change the zones counted here
        // sprint Vitesse: the request itself is kept, so Mes vœux and the guide read the SAME answer instead of asking again
        (this.req = api(`/api/voeux?${k}`)).then((d) => { if (this.key === k) { this.data = d; this.render(); } })
          .catch(() => { if (this.key === k) { this.req = null; this.data = { error: true }; this.render(); } });   // a failure is asked again
      }
      const d = this.data && !this.data.error ? voeuxLocal(this.data, prof) : this.data;
      if (!d) list = `<span class="pb-list muted">Mes vœux : lecture…</span>`;
      else if (d.error || !d.lecture) list = `<a class="pb-link" href="#/voeux">Mes vœux : ${fmt(ids.length)}</a>`;
      else {
        const z = d.lecture.zones, other = (z.hors_profil || 0) + (z.non_ouvert || 0) + (z.indetermine || 0) + (z.non_situe || 0);
        const parts = PB_ZONES.map((k2) => `<span class="pb-zone"><span style="color:${ZONES[k2].color}">${zoneMark(k2)}</span>${fmt(z[k2] || 0)} ${esc(ZONES[k2].label.replace(/^Vœu (de )?/, ""))}</span>`);
        if (other) parts.push(`<span class="pb-zone">${fmt(other)} autre${other > 1 ? "s" : ""}</span>`);
        const alert = d.lecture.messages.some((m) => m.code === "aucune_securite")
          ? `<a class="pb-alert" href="#/voeux">Aucun vœu de sécurité sûr</a>` : "";
        // WCAG 2.5.3 (axe, 2026-11-19): the accessible name CONTAINS the visible text; the explanation is hidden text, never an aria-label
        list = `<a class="pb-list" href="#/voeux">Mes vœux : ${parts.join('<span class="pb-sep"> · </span>')}<span class="sr-only"> (zones pour votre profil)</span></a>${alert}`;
        // owner, 2026-11-22: on a phone the bar folds to one line, the counts by their marks (each zone's name read aloud) and a "!"
        short = PB_ZONES.map((k2) => `<span class="pb-c"><span style="color:${ZONES[k2].color}">${zoneMark(k2)}</span>${fmt(z[k2] || 0)}<span class="sr-only"> ${esc(ZONES[k2].label.replace(/^Vœu (de )?/, ""))}</span></span>`).join("")
          + (alert ? `<span class="pb-bang">!<span class="sr-only"> aucun vœu de sécurité sûr</span></span>` : "");
      }
    }
    const full = `<a class="pb-who" href="#/profil"><span class="sr-only">Votre profil : </span>${profileLine(prof, prof.serie)}<span class="sr-only"> (le modifier dans Mon profil)</span></a><span class="pb-row">${list}</span>`;
    // Codex: the toggle is redrawn below; a keyboard user who had it focused keeps the focus on the new one
    const hadFocus = typeof document !== "undefined" && el.contains && el.contains(document.activeElement)
      && !!document.activeElement.closest && !!document.activeElement.closest(".pb-toggle");
    if (el.classList) el.classList.toggle("pb-open", !!this.open);
    el.innerHTML = `<button type="button" class="pb-toggle" aria-expanded="${this.open ? "true" : "false"}" aria-controls="pb-full"><span class="pb-short">${profileLine(prof, prof.serie)}</span>${short}<span class="pb-chev" aria-hidden="true"></span><span class="sr-only"> : détail du profil et de mes vœux</span></button><div class="pb-full" id="pb-full">${full}</div>`;
    const tog = el.querySelector ? el.querySelector(".pb-toggle") : null;
    if (tog) {
      tog.addEventListener("click", () => { this.open = !this.open; this.render(); });
      if (hadFocus) tog.focus();
    }
  },
};
// R1 (owner, 2026-11-11): the profile chip of the wide-screen header, read from the same stored profile as the bar (escaped,
// validated by vxProfile); hidden where the profile bar is (stats, a shared list)
const MENTION_SHORT = { rattrapage: "rattrapage", sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien", tbf: "très bien félicitations" };
function chipLine(p) {
  if (isReo(p)) return REO_LABEL;
  const ser = { bg: "bac général", bt: "bac techno", bp: "bac pro" }[p.serie];
  const what = p.serie === "bg" ? `${esc(speName(p.spe1))} + ${esc(speName(p.spe2))}` : p.voie_label ? esc(p.voie_label) : "";
  return [ser, what, p.moyenne !== null && p.moyenne !== undefined ? moyenneText(p.moyenne) : MENTION_SHORT[p.mention]].filter(Boolean).join(" · ");
}
function profileChip(tab, raw) {
  const el = document.getElementById("profile-chip");
  if (!el) return;
  if (tab === "stats" || tab === "liste") { el.hidden = true; return; }
  el.hidden = false;
  const has = !!raw && typeof raw === "object" && !Array.isArray(raw);
  el.classList.toggle("empty", !has);
  el.removeAttribute("aria-label");                               // WCAG 2.5.3: the name is the visible text + hidden words
  el.innerHTML = has ? `<span class="sr-only">Votre profil : </span><span>${chipLine(vxProfile(raw))}</span><span class="sr-only"> (le modifier)</span>${ICONS.edit}`
    : `${ICONS.profile}<span>Créer mon profil</span>`;
}

// ---- SVG primitives --------------------------------------------------------
// R4 (owner, 2026-11-12): colour carries a meaning only for the zones (--zone-*), the bac routes (--voie-*) and the accent. Every other
// series is drawn with the neutral data ramp (--c1 darkest .. --c6 lightest, hue-biased like the page's neutrals) and, on a line chart,
// told apart by its dash pattern too (the legend draws the same dash): never a zone's colour on a chart that is not about zones.
const COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];
const DASHES = ["", "6 4", "2 3", "8 3 2 3", "4 2", "1 3"];
const seriesDash = (s, i) => (s.dash !== undefined ? s.dash : s.color ? "" : DASHES[i % DASHES.length]);   // own colour: solid, unless it says
// every chart has an accessible name: its series and its years (role="img" alone is announced as an unnamed image)
const chartName = (names, years) => `Graphique : ${names.filter(Boolean).join(", ")}${years && years.length ? ` (${years[0]}–${years[years.length - 1]})` : ""}`;

const PHONE_CHART = () => typeof narrow === "function" && narrow();   // a phone draws taller charts (bigger text once scaled)
function lineChart(years, series, { yMax = 100, unit = "%", h = PHONE_CHART() ? 230 : 180, band = null, ranges = [] } = {}) {
  const W = 440, H = h, L = unit === "%" ? 48 : 36, R = 10, T = 10, B = 24;
  const P = 24;  // keep end points clear of the y-axis labels and the right edge
  const x = (i) => L + P + (years.length === 1 ? (W - L - R - 2 * P) / 2 : i * (W - L - R - 2 * P) / (years.length - 1));
  const max = yMax ?? Math.max(1, ...series.flatMap((s) => s.values.filter((v) => v != null)), ...ranges.map((r) => r.hi));
  const y = (v) => T + (H - T - B) * (1 - v / max);
  let g = "", tags = "";                                     // tags: the student's word at the end of their line, drawn last
  for (let k = 0; k <= 4; k++) {
    const v = max * k / 4;
    g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 4}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}${unit === "%" ? " %" : ""}</text>`;
  }
  years.forEach((yr, i) => { g += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${yr}</text>`; });
  // a context band under the lines ({name, values: [{lo, hi} | null per year]}): one shape per run of years with both bounds
  if (band) {
    const runs = [];
    let cur = [];
    band.values.forEach((b, i) => { if (b && b.lo != null && b.hi != null) cur.push([i, b]); else { if (cur.length) runs.push(cur); cur = []; } });
    if (cur.length) runs.push(cur);
    runs.forEach((rn) => {
      const tip = `<title>${esc(band.name)} : ${rn.map(([i, b]) => `${years[i]} ${fmt(b.lo, 0)}–${fmt(b.hi, 0)}${unit === "%" ? " %" : ""}`).join(", ")}</title>`;
      g += rn.length === 1 ? `<rect class="evo-band" x="${x(rn[0][0]) - 7}" y="${y(rn[0][1].hi)}" width="14" height="${Math.max(1, y(rn[0][1].lo) - y(rn[0][1].hi))}">${tip}</rect>`
        : `<polygon class="evo-band" points="${rn.map(([i, b]) => `${x(i)},${y(b.hi)}`).concat(rn.slice().reverse().map(([i, b]) => `${x(i)},${y(b.lo)}`)).join(" ")}">${tip}</polygon>`;
    });
  }
  // a range for a year (a forecast): a dashed box from lo to hi
  ranges.forEach((r) => {
    g += `<rect class="evo-range" x="${x(r.i) - 9}" y="${y(r.hi)}" width="18" height="${Math.max(2, y(r.lo) - y(r.hi))}"><title>${esc(r.name)} : ${fmt(r.lo, 0)}–${fmt(r.hi, 0)}${unit === "%" ? " %" : ""}</title></rect>`;
  });
  series.forEach((s, si) => {
    const c = s.color || COLORS[si % COLORS.length];
    const lastI = s.values.reduce((k, v, i) => (v == null ? k : i), -1);
    if (s.tag && lastI >= 0) {
      // the word runs leftwards from the last point: keep it clear of every other line over that stretch (its points and segments)
      const step = lastI > 0 ? x(lastI) - x(lastI - 1) : 1;
      const yAt = (o, back) => { const a = o.values[lastI], b = lastI > 0 ? o.values[lastI - 1] : null, t = Math.min(1, back / step);
        return a == null ? null : y(b == null ? a : a + (b - a) * t); };
      const py = y(s.values[lastI]), others = series.filter((o) => o !== s).flatMap((o) => [0, 25, 50].map((bk) => yAt(o, bk))).filter((v) => v != null);
      const free = (ty) => ty - 11 > 0 && ty < H - B && others.every((oy) => Math.abs(oy - (ty - 5)) > 11);   // inside the svg, clear of other lines
      const ty = [py - 10, py + 20, py - 26, py + 34].find(free);
      tags += ty !== undefined ? `<text class="mine-lbl" x="${x(lastI) + 8}" y="${ty}" text-anchor="end">${esc(s.tag)}</text>`
        : `<text class="mine-lbl" x="${x(lastI) - 9}" y="${py - 7}" text-anchor="end">${esc(s.tag)}</text>`;
    }
    let d = "", pen = false;
    s.values.forEach((v, i) => {
      if (v == null) { pen = false; return; }          // gaps stay gaps: no interpolation over missing years
      d += `${pen ? "L" : "M"}${x(i)},${y(v)}`; pen = true;
    });
    const dash = seriesDash(s, si), sw = s.mine ? 3.5 : 2;          // the student's own curve is drawn heavier (s.mine)
    g += `<path d="${d}" fill="none" stroke="${c}" stroke-width="${sw}"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
    s.values.forEach((v, i) => {
      if (v == null) return;
      const hollow = s.hollow?.[i], fill = hollow ? "var(--surface)" : c;
      const tip = `<title>${esc(s.name)} ${years[i]} : ${fmt(v, 1)}${unit === "%" ? " %" : ""}${hollow ? " (effectif < seuil)" : ""}${s.notes?.[i] ? ` · ${esc(s.notes[i])}` : ""}</title>`;
      // a published point of a series that mixes published and estimated years is a square (markKey says so under the chart)
      g += s.marks?.[i] === "pub" ? `<rect class="mk-pub" x="${x(i) - 6}" y="${y(v) - 6}" width="12" height="12" fill="${fill}" stroke="${c}" stroke-width="2">${tip}</rect>`
        : s.marks?.[i] === "est" ? `<path class="mk-est" d="M${x(i)},${y(v) - 8}L${x(i) + 8},${y(v)}L${x(i)},${y(v) + 8}L${x(i) - 8},${y(v)}Z" fill="${fill}" stroke="${c}" stroke-width="2">${tip}</path>`
        : `<circle cx="${x(i)}" cy="${y(v)}" r="${s.mine ? 5 : 4}" fill="${fill}" stroke="${c}" stroke-width="2">${tip}</circle>`;
    });
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(chartName(series.map((x) => x.name), years))}">${g}${tags}</svg>`;
}

function stackedBars(years, keys, rows, { normalize = true, h = PHONE_CHART() ? 240 : 190 } = {}) {
  const W = 440, H = h, L = normalize ? 48 : 36, R = 10, T = 10, B = 24;
  const n = years.length, slot = (W - L - R) / n, bw = Math.min(46, slot * 0.6);
  const totals = rows.map((r) => r ? keys.reduce((a, k) => a + (r[k.key] || 0), 0) : 0);
  const max = normalize ? 100 : Math.max(1, ...totals);
  const y = (v) => T + (H - T - B) * (1 - v / max);
  let g = "";
  for (let k = 0; k <= 4; k++) { const v = max * k / 4; g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 4}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}${normalize ? " %" : ""}</text>`; }
  rows.forEach((r, i) => {
    const cx = L + slot * i + slot / 2;
    g += `<text x="${cx}" y="${H - 6}" text-anchor="middle">${years[i]}</text>`;
    if (!r || !totals[i]) { g += `<text x="${cx}" y="${y(max / 2)}" text-anchor="middle">n.d.</text>`; return; }
    let acc = 0;
    keys.map((k, ki) => [k, ki]).reverse().forEach(([k, ki]) => {          // the first key on top: the legend reads top to bottom
      const raw = r[k.key] || 0, v = normalize ? 100 * raw / totals[i] : raw;
      if (v <= 0) return;
      const y0 = y(acc + v), hgt = y(acc) - y(acc + v);
      g += `<rect x="${cx - bw / 2}" y="${y0}" width="${bw}" height="${Math.max(hgt - 1, 0.5)}" fill="${k.color || COLORS[ki]}" stroke="var(--edge)" stroke-width="1"><title>${esc(k.name)} ${years[i]} : ${fmt(raw)}${normalize ? ` (${fmt(v, 1)} %)` : ""}</title></rect>`;
      if (normalize && v >= 12) {
        const my = (y0 + y(acc)) / 2;
        g += `<rect class="seg-chip" x="${cx - 19}" y="${my - 9}" width="38" height="18"/><text class="seg-lbl" x="${cx}" y="${my + 4.5}" text-anchor="middle">${fmt(v, 0)} %</text>`;
      }
      acc += v;
    });
    if (r.low_n_flag) g += `<text x="${cx}" y="${y(acc) - 4}" text-anchor="middle">n&lt;${META.low_n_threshold}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(chartName(keys.map((k) => k.name), years))}${normalize ? ", parts en %" : ""}">${g}</svg>`;
}

const legend = (items) => `<div class="legend">${items.map((k, i) => `<span><i style="background:${k.color || COLORS[i]}"></i>${esc(k.name)}</span>`).join("")}</div>`;
// the legend of a line chart: the same colour AND the same dash as the line
const lineLegend = (items) => `<div class="legend">${items.map((k, i) => `<span${k.mine ? ' class="lg-mine"' : ""}><svg class="lg-line" viewBox="0 0 22 8" aria-hidden="true"><line x1="1" y1="4" x2="21" y2="4" stroke="${k.color || COLORS[i]}" stroke-width="2.5"${seriesDash(k, i) ? ` stroke-dasharray="${seriesDash(k, i)}"` : ""}/></svg>${esc(k.name)}</span>`).join("")}</div>`;

// the key of a line whose years mix the formation's own report (square) and an estimation (diamond): words + the two marks
const markKey = (c) => `<p class="muted small mk-key"><svg viewBox="0 0 12 12" aria-hidden="true"><rect x="1.5" y="1.5" width="9" height="9" fill="${c}" stroke="${c}" stroke-width="2"/></svg> carré : chiffre publié par le rapport public de la formation cette année-là · <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6,1L11,6L6,11L1,6Z" fill="${c}" stroke="${c}" stroke-width="1.5"/></svg> losange : estimation</p>`;

function benchBar(p) {
  if (!p.n_peers) return `<span class="muted small">pas de pairs</span>`;
  const sx = (v) => 4 + 292 * Math.max(0, Math.min(100, v)) / 100;
  let s = `<rect x="${sx(p.p10)}" y="8" width="${sx(p.p90) - sx(p.p10)}" height="6" fill="var(--range)"/>`
    + `<rect x="${sx(p.p25)}" y="5" width="${Math.max(1, sx(p.p75) - sx(p.p25))}" height="12" fill="var(--box)"/>`
    + `<line x1="${sx(p.p50)}" x2="${sx(p.p50)}" y1="3" y2="19" stroke="var(--ink)" stroke-width="1.5"/>`;
  if (p.value != null) s += `<circle cx="${sx(p.value)}" cy="11" r="5" fill="${p.in_reference ? "var(--ink)" : "var(--surface)"}" stroke="var(--ink)" stroke-width="2"/>`;
  return `<svg viewBox="0 0 300 22" preserveAspectRatio="none" role="img"><title>p10 ${fmt(p.p10, 1)} · p25 ${fmt(p.p25, 1)} · médiane ${fmt(p.p50, 1)} · p75 ${fmt(p.p75, 1)} · p90 ${fmt(p.p90, 1)} (n=${p.n_peers})</title>${s}</svg>`;
}

const lineageBadge = (c) => c === "inferred_uai_track_match"
  ? `<span class="badge inferred" title="Code formation modifié : lien inféré">inféré</span>`
  : `<span class="badge exact" title="Même établissement et même code Parcoursup">exact</span>`;

// ---- views -----------------------------------------------------------------
const INTERP_LABEL = { option: "Option", lieu: "Lieu", sigle: "Mot compris", "corrigé": "Corrigé", "approché": "Mot approché", "ignoré": "Ignoré", uai: "Établissement (UAI)" };
// ---- offer options (cartographie Parcoursup) and offer timing ---------------------------------
const OPT_LABEL = { internat: "Internat", apprentissage: "Apprentissage", distance: "À distance", sport: "Sportifs de haut niveau", art: "Artistes de haut niveau" };
// small drawn icons (trusted constants, never data): the design guidelines rule out emoji as markers
const ICO = (d) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const ICONS = {
  search: ICO('<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>'),
  job: ICO('<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M9 7.5V5.5h6v2"/>'),
  compass: ICO('<circle cx="12" cy="12" r="8.5"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>'),
  check: ICO('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
  reorientation: ICO('<path d="M4 17h9a4 4 0 0 0 0-8H7"/><path d="M10 6L7 9l3 3"/>'),
  profile: ICO('<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1-4 4-6 7-6s6 2 7 6"/>'),
  warn: ICO('<path d="M12 4l9 16H3z"/><path d="M12 10v4.5M12 17.5v.5"/>'),
  filter: ICO('<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>'),
  places: ICO('<rect x="4" y="9" width="16" height="8" rx="2"/><path d="M7 17v3M17 17v3M7 9V6.5A1.5 1.5 0 0 1 8.5 5h7A1.5 1.5 0 0 1 17 6.5V9"/>'),
  edit: ICO('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>'),
  list: ICO('<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>'),
  map: ICO('<path d="M9 4.5l-5 2v13l5-2 6 2 5-2v-13l-5 2z"/><path d="M9 4.5v13M15 6.5v13"/>'),
  internat: ICO('<path d="M4 11l8-6 8 6"/><path d="M6 10v9h12v-9"/>'),
  apprentissage: ICO('<path d="M14.5 6.5a4 4 0 0 0 5 5l-8.5 8.5a2.1 2.1 0 0 1-3-3z"/>'),
  distance: ICO('<rect x="3.5" y="5" width="17" height="11" rx="1.5"/><path d="M8 20h8M12 16v4"/>'),
  sport: ICO('<circle cx="12" cy="14" r="5.5"/><path d="M8.5 3.5l3.5 5 3.5-5"/>'),
  art: ICO('<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.5 0 2-1 1.5-2.2-.6-1.4.4-2.8 1.9-2.8H18a3.5 3.5 0 0 0 3.5-3.5c0-4.9-4.3-8.5-9.5-8.5z"/><circle cx="8" cy="11" r="1"/><circle cx="12" cy="8" r="1"/><circle cx="16" cy="11" r="1"/>'),
};
const OPT_ICON = { internat: ICONS.internat, apprentissage: ICONS.apprentissage, distance: ICONS.distance, sport: ICONS.sport, art: ICONS.art };
const INTERNAT_LABEL = { mixte: "Internat filles et garçons", filles: "Internat filles", garcons: "Internat garçons", oui: "Internat" };
function offerList(r) {
  const out = [];
  if (INTERNAT_LABEL[r.internat]) out.push(["internat", INTERNAT_LABEL[r.internat]]);
  if (r.apprentissage === true) out.push(["apprentissage", "En apprentissage"]);
  if (r.distance === "partielle") out.push(["distance", "Enseignement partiellement à distance"]);
  if (r.distance === "totale") out.push(["distance", "Enseignement à distance"]);
  if (r.amenag_sport === true) out.push(["sport", "Aménagements pour sportifs de haut niveau"]);
  if (r.amenag_art === true) out.push(["art", "Aménagements pour artistes de haut niveau"]);
  return out;
}
// compact (search results): sport / art arrangements are declared by ~40 % of formations, so they
// would be noise in a result list; they stay on the fiche
const offerBadges = (r, compact = false) => offerList(r).filter(([k]) => !compact || !["sport", "art"].includes(k)).map(([k, t]) => `<span class="badge offer" title="${esc(t)}"><span aria-hidden="true">${OPT_ICON[k]}</span> ${esc(k === "distance" ? t.replace("Enseignement ", "") : OPT_LABEL[k])}</span>`).join("");


// ---- Sprint R7 (owner, 2026-11-12): "Construire ma liste", the five steps of the site in one place ----
// Everything it reads stays in this browser: the profile, the list and two flags (a formation page opened, the list shared).
// The list is read with the profile bar's own query, with the average the browser keeps (R6). Counts and facts, never a chance;
// the progress is never sent (the page view is counted like any other page, nothing more).
const GUIDE_STEPS = [
  { key: "profil", titre: "Mon profil", href: "#/profil" },
  { key: "explorer", titre: "Explorer les formations", href: "#/" },
  { key: "voeux", titre: "Ajouter des vœux", href: "#/voeux" },
  { key: "securite", titre: "Garder au moins un vœu de sécurité sûr", href: "#/voeux" },
  { key: "partager", titre: "Partager ma liste", href: "#/voeux" },
];
const GUIDE_STATUT = { fait: "Fait", a_faire: "À faire", en_attente: "Plus tard", lecture: "Lecture…", indisponible: "Lecture impossible", sans_objet: "Sans objet" };
// a profile the site can read: a situation outside terminale, or a bac, a mention (or an average) and, for bac général, two
// different specialties (the same rules as "Mon profil")
function profileReady(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  if (isReo(raw)) return true;
  if (!["bg", "bt", "bp"].includes(raw.serie)) return false;
  if (!MENTION_CODES.includes(raw.mention) && validMoyenne(raw.moyenne) === null) return false;
  return raw.serie !== "bg" || (typeof raw.spe1 === "string" && typeof raw.spe2 === "string" && !!raw.spe1 && !!raw.spe2 && raw.spe1 !== raw.spe2);
}
// the state of each step. lecture: the list's reading (voeux.read_list), null while it is read, undefined when it could not be
function guideState(raw, ids, lecture, flags) {
  const ready = profileReady(raw), reo = ready && isReo(raw), n = ids.length;
  const st = {
    profil: ready ? "fait" : "a_faire",
    explorer: flags.vu || n > 0 ? "fait" : "a_faire",
    voeux: n > 0 ? "fait" : "a_faire",
    securite: reo ? "sans_objet" : !ready || !n ? "en_attente" : lecture === null ? "lecture" : lecture === undefined ? "indisponible"
      : lecture.securite_sure > 0 ? "fait" : "a_faire",
    partager: !n ? "en_attente" : flags.partage ? "fait" : "a_faire",
  };
  const steps = GUIDE_STEPS.map((x) => ({ ...x, href: x.key === "securite" && reo ? "#/reorientation" : x.href, statut: st[x.key] }));
  const next = steps.find((x) => x.statut === "a_faire") || null;
  return { steps, next: next ? next.key : null, faites: steps.filter((x) => x.statut === "fait" || x.statut === "sans_objet").length };
}
function guideFlags() { return { vu: store.get("guideVu", false) === true, partage: store.get("guidePartage", false) === true }; }
function guideHtml(G, c) {
  const st = Object.fromEntries(G.steps.map((x) => [x.key, x.statut]));
  const safety = { fait: `${fmt(c.sure)} vœu${c.sure > 1 ? "x" : ""} de sécurité sûr${c.sure > 1 ? "s" : ""} dans votre liste.`,
    a_faire: "Aucun vœu de sécurité sûr dans votre liste pour l'instant.", lecture: "Lecture de votre liste…",
    indisponible: "Votre liste n'a pas pu être lue pour le moment.", en_attente: "Après votre profil et vos premiers vœux." }[st.securite] || "";
  const body = {
    profil: `<p>Votre bac, vos spécialités et votre mention visée, ou votre situation si vous n'êtes plus en terminale. SupCompass lit ensuite chaque formation pour vous. Votre profil reste dans ce navigateur.</p>${c.profLine ? `<p class="small">Votre profil : <strong>${c.profLine}</strong></p>` : ""}
      <a class="btnlink" href="#/profil">${st.profil === "fait" ? "Modifier mon profil" : "Créer mon profil"}</a>`,
    explorer: `<p>Cherchez une formation par son nom, sa ville ou un métier, ou parcourez la carte. Ouvrez la page d'une formation pour voir ses chiffres officiels et ce que regarde le jury.</p>
      <div class="toolbar"><a class="btnlink" href="#/">Rechercher</a><a class="btnlink" href="#/carte">La carte</a><a class="btnlink" href="#/metiers">Par métier</a></div>`,
    voeux: `<p>Sur la page d'une formation, choisissez « Ajouter à mes vœux ». Parcoursup accepte jusqu'à ${voeux.MAX} vœux (hors sous-vœux), et ils ne sont pas classés : l'ordre de votre liste ne compte pas.</p>
      <p class="small">${c.n ? `${fmt(c.n)} formation${c.n > 1 ? "s" : ""} dans votre liste (les sous-vœux d'un même vœu multiple comptent pour un seul vœu).` : "Votre liste est vide pour l'instant."}</p><a class="btnlink" href="#/voeux">Voir mes vœux</a>`,
    securite: c.reo
      ? `<p>Hors terminale, aucune zone n'est publiée : les chiffres officiels ne donnent ni mention ni série pour ces candidats. Comparez plutôt l'accès estimé hors terminale des formations.</p><a class="btnlink" href="#/reorientation">Je me réoriente</a>`
      : `<p>Un vœu de sécurité sûr est une formation où, les années passées, le taux d'accès atteignait au moins 70 % et au moins la moitié des admis avaient votre mention ou moins, sans incertitude. Si votre liste n'en a pas, « Compléter ma liste » (dans Mes vœux) en propose dans les mêmes filières.</p>
      <p class="small">${safety}</p><a class="btnlink" href="#/voeux">Lire ma liste</a>`,
    partager: `<p>Envoyez le lien de votre liste à un parent ou à votre professeur principal, ou imprimez-la. Le lien contient seulement les numéros des formations, et votre profil si vous cochez la case.</p><a class="btnlink" href="#/voeux">Partager depuis Mes vœux</a>`,
  };
  const next = G.steps.find((x) => x.key === G.next);
  return `<div class="card"><h1>Construire ma liste</h1>
    <p>Cinq étapes, dans l'ordre qui vous convient. Votre avancée reste dans ce navigateur : rien n'est envoyé pour la suivre.</p>
    <div class="guide-progress" role="progressbar" aria-label="Étapes faites" aria-valuemin="0" aria-valuemax="5" aria-valuenow="${G.faites}"><span style="width:${G.faites * 20}%"></span></div>
    <p class="small">${fmt(G.faites)} étape${G.faites > 1 ? "s" : ""} sur 5.</p>
    ${next ? `<a class="btnlink primary" href="${esc(next.href)}">Continuer : ${esc(next.titre)}</a>`
      : G.faites === GUIDE_STEPS.length ? `<p class="small">Toutes les étapes sont faites. Relisez chaque fiche sur Parcoursup avant de formuler vos vœux.</p>`
      : `<p class="small">${st.securite === "indisponible" ? "Votre liste n'a pas pu être lue pour le moment : rouvrez cette page un peu plus tard." : "Lecture de votre liste…"}</p>`}</div>
  <ol class="guide">${G.steps.map((x, i) => `<li class="card guide-step${x.key === G.next ? " next" : ""}">
    <div class="guide-head"><span class="guide-num" aria-hidden="true">${x.statut === "fait" ? ICONS.check : i + 1}</span><h2>${esc(x.titre)}</h2><span class="badge">${GUIDE_STATUT[x.statut]}</span></div>
    ${body[x.key]}</li>`).join("")}</ol>
  <p class="muted small">Des repères tirés des admis des campagnes 2022–2025, pas des chances d'admission. La fiche Parcoursup de chaque formation fait foi. <a href="#/info/nos-chiffres">Nos chiffres et ceux de Parcoursup</a></p>`;
}
let guideSeq = 0;
async function viewGuide() {
  const raw = store.get("profile", null), ids = voeux.get(), flags = guideFlags();
  const ready = profileReady(raw), reo = ready && isReo(raw), prof = ready ? vxProfile(raw) : null;
  const gmk = `guide:${++guideSeq}`;                                   // Codex: one token per visit, never the list alone
  $view.dataset.rendered = gmk;                                      // before any await (navigation race)
  const draw = (lecture) => {
    $view.innerHTML = guideHtml(guideState(raw, ids, lecture, flags),
      { n: ids.length, reo, profLine: prof ? profileLine(prof, prof.serie) : "", sure: lecture ? lecture.securite_sure : 0 });
  };
  draw(null);
  if (!ready || reo || !ids.length) return;                            // nothing to read: no request
  const k = vxQuery(ids, prof).toString();                               // the profile bar's own query
  // the bar's raw answer (same query), read here for this profile: never its reading of another average
  let d = profileBar.key === k && profileBar.data && profileBar.data.lecture ? voeuxLocal(profileBar.data, prof) : null;
  if (!d) { try { d = voeuxLocal(await (profileBar.key === k && profileBar.req ? profileBar.req : api(`/api/voeux?${k}`)), prof); } catch (_) { d = null; } }
  if ($view.dataset.rendered !== gmk) return;
  draw(d && d.lecture ? d.lecture : undefined);
}
// the home card: where the student stands (no request: the reading of the list is only on the guide's own page)
function guideCard() {
  // style B (owner, 2026-11-19): the five steps as a line of stops, each with its status read in this browser only
  const G = guideState(store.get("profile", null), voeux.get(), null, guideFlags());
  const label = (x) => (x.statut === "lecture" ? "À lire dans Mes vœux" : GUIDE_STATUT[x.statut] || "");
  return `<section class="card guide-card" aria-labelledby="gc-h"><h2 id="gc-h">Construire ma liste en 5 étapes</h2>
    <ol class="trajet">${G.steps.map((x) => `<li class="tj-${x.statut}${x.key === G.next ? " tj-next" : ""}"><a href="${esc(x.href)}"${x.key === G.next ? ' aria-current="step"' : ""}><span class="tj-dot" aria-hidden="true"></span>
      <span><strong>${esc(x.titre)}</strong><br><span class="small">${esc(label(x))}</span></span></a></li>`).join("")}</ol>
    <p class="small">${G.faites ? `${fmt(G.faites)} étape${G.faites > 1 ? "s" : ""} sur 5 faite${G.faites > 1 ? "s" : ""}.` : "Aucune étape faite pour l'instant."} Le site pas à pas, à votre rythme.</p>
    <a class="btnlink" href="#/guide">${G.faites ? "Reprendre les étapes" : "Suivre les étapes"}</a></section>`;
}

// ---- Sprint 1 (owner, 2026-11-20): « Préparer mon projet de formation motivé » ----
// For each vœu of the list, what the formation publishes on its own Parcoursup fiche (/api/projet/<code>, projet.py):
// its expectations, what its jury examines from the most important to the least, its advice, verbatim and escaped.
// The site never writes the project: the student ticks the criteria the draft covers and writes the draft; both stay in this
// browser (store "projet", read back through projetLoad, never trusted) and are NEVER sent to the server.
const PROJET_MAX = 20000;                                  // a draft longer than this is cut before it is kept
const projetCount = (t) => [...String(t || "")].length;    // characters as a person counts them (an emoji is one)
function projetLoad() {
  const raw = store.get("projet", null), out = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [k, v] of Object.entries(raw)) {
    if (!/^\d{1,9}$/.test(k) || !v || typeof v !== "object" || Array.isArray(v)) continue;
    const coches = Array.isArray(v.coches) ? [...new Set(v.coches.filter((i) => Number.isInteger(i) && i >= 0 && i < 200))].sort((a, b) => a - b) : [];
    const brouillon = typeof v.brouillon === "string" ? v.brouillon.slice(0, PROJET_MAX) : "";
    if (coches.length || brouillon) out[k] = { coches, brouillon };
  }
  return out;
}
function projetSave(cod, entry) {
  const all = projetLoad();
  if (entry && (entry.coches.length || entry.brouillon)) all[cod] = entry; else delete all[cod];
  store.set("projet", all);
}
function projetCounter(n, limite) {
  return `${fmt(n)} caractère${n > 1 ? "s" : ""} sur ${fmt(limite)}, espaces compris.`;
}
function projetOver(n, limite) {
  return n > limite ? `Votre brouillon dépasse ${fmt(limite)} caractères. Raccourcissez-le, ou vérifiez sur Parcoursup la limite de ce vœu.` : "";
}
function projetCard(d, saved, open) {
  const cod = String(d.cod), f = d.fiche, coches = new Set(saved.coches || []), brouillon = saved.brouillon || "";
  const list = (xs) => `<ul>${xs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  const link = d.fiche_url ? ` <a href="${esc(d.fiche_url)}" target="_blank" rel="noopener">Voir la fiche sur Parcoursup ↗</a>` : "";
  const body = !f ? `<p class="muted">Nous n'avons pas pu lire la fiche Parcoursup de cette formation. Ses attentes et ses critères y sont publiés.${link}</p>`
    : `${f.attendus.length ? `<h3>Ce que la formation attend</h3>${list(f.attendus)}` : ""}
      ${f.complementaires.length ? `<h3>Ce qu'elle attend en plus</h3>${list(f.complementaires)}` : ""}
      ${f.criteres.length ? `<h3>Ce que son jury regarde, du plus important au moins important</h3>
        <p class="small">Cochez un point quand votre projet en parle. Vos coches restent dans ce navigateur.</p>
        <ul class="pj-crit">${f.criteres.map((k, i) => `<li><label><input type="checkbox" data-pj="${esc(cod)}" data-i="${i}"${coches.has(i) ? " checked" : ""}>
          <span><strong>${esc(k.importance_label)}</strong> · ${esc(k.champ)} (${fmt(k.poids)} % de l'examen) : ${esc(k.critere)}${k.elements ? `<br><span class="small">${esc(k.elements)}</span>` : ""}</span></label></li>`).join("")}</ul>`
        : `<p class="small">La fiche ne publie pas le détail des critères du jury.</p>`}
      ${f.conseils.length ? `<h3>Les conseils de la formation</h3>${f.conseils.map((x) => `<p>${esc(x)}</p>`).join("")}` : ""}
      ${f.info.length ? f.info.map((x) => `<p class="small">${esc(x)}</p>`).join("") : ""}
      <p class="muted small">D'après la fiche Parcoursup ${esc(f.session)}${f.lu_le ? `, lue le ${esc(frDate(f.lu_le))}` : ""}. La fiche fait foi.${link}</p>`;
  const n = projetCount(brouillon);
  return `<details class="card projet" id="pj-${esc(cod)}"${open ? " open" : ""}>
    <summary><h2>${esc(d.etablissement)}</h2><span class="small">${esc(d.formation)}${d.ville ? ` · ${esc(d.ville)}` : ""}</span></summary>
    ${body}
    <h3>Mon brouillon</h3>
    <label for="pj-txt-${esc(cod)}" class="small">Écrivez ici votre projet pour cette formation. Il reste dans ce navigateur : il n'est jamais envoyé.</label>
    <textarea id="pj-txt-${esc(cod)}" data-pjt="${esc(cod)}" data-limite="${esc(d.limite)}" rows="8">${esc(brouillon)}</textarea>
    <p class="small" id="pj-n-${esc(cod)}">${projetCounter(n, d.limite)}</p>
    <p class="warn" id="pj-over-${esc(cod)}" role="status"${n > d.limite ? "" : " hidden"}>${esc(projetOver(n, d.limite))}</p>
    <p class="small">Parcoursup limite le plus souvent ce texte à ${fmt(d.limite)} caractères, espaces compris. La limite affichée pour chaque vœu sur Parcoursup fait foi.</p>
    <p><button type="button" data-pjdel="${esc(cod)}">Effacer ce brouillon et ces coches</button></p></details>`;
}
let projetSeq = 0;
async function viewProjet(cod) {
  const ids = voeux.get(), mk = `projet:${++projetSeq}`;
  $view.dataset.rendered = mk;                                        // before any await (navigation race)
  const head = `<h1>Préparer mes projets de formation motivés</h1>
    <p>Pour chaque vœu, voici ce que la formation dit attendre et ce que son jury regarde. Appuyez-vous dessus pour écrire votre projet avec vos propres mots.</p>
    <p class="small">Le site n'écrit pas votre projet à votre place. Ce que vous cochez et écrivez ici reste dans ce navigateur : rien n'est envoyé.</p>`;
  if (!ids.length) {
    $view.innerHTML = `${head}<div class="card"><p>Votre liste de vœux est vide : ajoutez d'abord des formations.</p><a class="btnlink" href="#/carte">Chercher des formations</a></div>`;
    return;
  }
  $view.innerHTML = `${head}<p class="muted">Chargement des fiches…</p>`;
  const res = await Promise.all(ids.map((c) => api(`/api/projet/${encodeURIComponent(c)}`).catch(() => null)));
  if ($view.dataset.rendered !== mk) return;
  const saved = projetLoad(), open = cod && ids.includes(cod) ? cod : ids[0];
  $view.innerHTML = `${head}${res.map((d, i) => d ? projetCard(d, saved[String(d.cod)] || {}, String(d.cod) === open)
    : `<div class="card"><p class="muted">Impossible de charger la fiche de la formation ${esc(ids[i])} pour l'instant.</p></div>`).join("")}
    <p><a href="#/voeux">Retour à mes vœux</a></p>`;
  const entry = (c) => { const e = projetLoad()[c]; return e ? { coches: [...e.coches], brouillon: e.brouillon } : { coches: [], brouillon: "" }; };
  $view.querySelectorAll("textarea[data-pjt]").forEach((t) => {
    t.oninput = () => {
      const c = t.dataset.pjt, lim = Number(t.dataset.limite), e = entry(c);
      e.brouillon = t.value.slice(0, PROJET_MAX);
      projetSave(c, e);
      const n = projetCount(t.value), over = document.getElementById(`pj-over-${c}`);
      document.getElementById(`pj-n-${c}`).textContent = projetCounter(n, lim);
      if (over) { const msg = projetOver(n, lim); over.hidden = !msg; if (over.textContent !== msg) over.textContent = msg; }
    };
  });
  $view.querySelectorAll("input[data-pj]").forEach((b) => {
    b.onchange = () => {
      const c = b.dataset.pj, i = Number(b.dataset.i), e = entry(c), s2 = new Set(e.coches);
      if (b.checked) s2.add(i); else s2.delete(i);
      e.coches = [...s2].sort((x, y) => x - y);
      projetSave(c, e);
    };
  });
  $view.querySelectorAll("button[data-pjdel]").forEach((b) => {
    b.onclick = () => {
      const c = b.dataset.pjdel;
      projetSave(c, null);
      const card = document.getElementById(`pj-${c}`);
      card.querySelectorAll("input[data-pj]").forEach((x) => { x.checked = false; });
      const t = card.querySelector("textarea[data-pjt]");
      t.value = "";
      t.oninput();
    };
  });
}

// ---- lot 1 UI: the home page opens on four doors (a formation, a job, where I stand, sprint 21: I am not in terminale) ----
const HOME_EXAMPLES = ["BTS NDRC", "prépa HEC Lyon", "IUT informatique Toulouse", "infirmière Bordeaux", "kiné"];
// R1 (owner, 2026-11-11): "Explorer" is one place with three views of the same offer: the list (search), the map, the jobs
// owner, 2026-11-15: the list and the map are one view ("Formations": search bar, list and map); jobs are the other view
const EXPLORER_VIEWS = [["carte", "Formations", "map"], ["metiers", "Métiers", "job"]];
function explorerViews(cur) {
  const href = { carte: "#/carte", metiers: "#/metiers" };
  return `<nav class="views" aria-label="Explorer : choisir la vue">${EXPLORER_VIEWS.map(([k, label, ico]) =>
    `<a href="${esc(href[k])}"${k === cur ? ' aria-current="true"' : ""}>${ICONS[ico]}${label}</a>`).join("")}</nav>`;
}
// sprint Q5 (owner, 2026-11-13): the home has ONE primary action, in the hero, right under the title: no profile -> create it;
// a profile -> where I stand. Every other call on the home is a secondary button or a link (red team redteam_mobile.py MB1).
const hasStoredProfile = (raw) => !!raw && typeof raw === "object" && !Array.isArray(raw);
function homeCta() {
  const has = hasStoredProfile(store.get("profile", null));
  const [href, label, note] = has ? ["#/parcours", "Voir où je me situe", "Les formations lues pour votre profil, d'après les admis des années passées."]
    : ["#/profil", "Créer mon profil", "1 minute, sans compte : votre bac, vos spécialités et votre mention. Il reste dans ce navigateur."];
  return `<div class="hero-cta"><a class="btnlink primary" href="${href}">${label}</a><p class="small">${note} <a href="#/carte">Ou cherchez directement une formation</a></p></div>`;
}
// audit PR 6 (2026-11-24): the « Je me réoriente » door was below the first screen (841 px on a 768 px laptop, two screens on a
// phone): the hero names it in one line, a LINK (the hero keeps ONE primary action); a student already outside terminale is
// sent there by « Voir où je me situe », so the line is not repeated for them
function homeReo() {
  if (isReo(store.get("profile", null))) return "";
  return `<p class="hero-reo small">Vous n'êtes plus en terminale ? <a href="#/reorientation">Je me réoriente ou je reprends mes études</a></p>`;
}
// the profile the results are read for, said on the Explorer home (escaped by profileLine); no profile: the hero carries the call
function homeProfile() {
  const raw = store.get("profile", null);
  if (!hasStoredProfile(raw)) return "";
  const p = vxProfile(raw);
  return `<p class="home-profile small">Les résultats sont lus pour : <strong>${profileLine(p, p.serie)}</strong> · <a href="#/profil">Modifier mon profil</a></p>`;
}
function viewHome() {
  const n = voeux.get().length;
  $view.innerHTML = `<section class="hero"><h1>Trouvez votre voie après le bac</h1>
    <p>Les chiffres officiels de Parcoursup 2022–2025, expliqués simplement. Des repères pour choisir, jamais des pronostics.</p>
    ${homeCta()}${homeReo()}</section>
  ${homeProfile()}
  ${guideCard()}
  <div class="doors">
    <a class="door" href="#/carte"><span class="door-ico" aria-hidden="true">${ICONS.search}</span><strong>Je cherche une formation</strong>
      <span>Un mot-clé, une ville, une région : la liste et la carte, avec des filtres.</span></a>
    <a class="door" href="#/metiers"><span class="door-ico" aria-hidden="true">${ICONS.job}</span><strong>Je pars d'un métier</strong>
      <span>Développeur, infirmière, juriste… voyez les formations qui y mènent.</span></a>
    <a class="door" href="#/parcours"><span class="door-ico" aria-hidden="true">${ICONS.compass}</span><strong>Je veux savoir où je me situe</strong>
      <span>Votre bac, vos spécialités, votre mention : voyez où se situaient les admis des années passées.</span></a>
    <a class="door" href="#/reorientation"><span class="door-ico" aria-hidden="true">${ICONS.reorientation}</span><strong>Je me réoriente ou je reprends mes études</strong>
      <span>Vous n'êtes plus en terminale : voyez les formations qui accueillent des candidats comme vous.</span></a>
  </div>
  <p class="home-more small"><a href="#/premiere">En seconde ou en première ? Comparez les paires possibles de vos spécialités</a> · <a href="#/calendrier">Calendrier Parcoursup</a> · <a href="#/accompagner">Parents et professeurs</a></p>
  <div class="card"><h2>Idées de recherche</h2>
    <div class="toolbar">${HOME_EXAMPLES.map((e) => `<a class="badge" href="#/s/${encodeURIComponent(e)}">${esc(e)}</a>`).join("")}</div>
    ${n ? `<p><a href="#/voeux">Vous avez ${n} formation${n > 1 ? "s" : ""} dans votre liste →</a></p>` : ""}</div>`;
  $view.dataset.rendered = "home";
}


// ---- lot 3 (Claude design guidelines): the same summary-first, folded-detail format on the four working pages ----
const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 720px)").matches;
const searchPage = () => (narrow() ? 20 : 40);
// owner, 2026-11-15: the search list's cards carry three figures, the bac lines and the actions: 10 per page on a phone
const cartePage = () => (narrow() ? 10 : 40);
// zoneTiles: the zone counts of a list read as a summary (one tile per zone, the zone's own colour, never a chance)
// audit PR 8: a list holding sub-wishes of one vœu multiple counts its tiles in formations (they are not that many vœux)
function zoneTiles(counts, other, large, unit = "vœu") {
  const word = (n) => (unit === "formation" ? `formation${n > 1 ? "s" : ""}` : `vœu${n > 1 ? "x" : ""}`);
  const tile = (k, n, note) => `<div class="sum-tile">${zonePillHtml(k)}
      <span class="sum-value">${fmt(n)}</span><span class="sum-note">${word(n)}${note || ""}</span></div>`;
  const lg = large > 0 && counts.securite ? `, dont ${fmt(large)} « sécurité large »` : "";   // none (or not read): the information says so
  return `<div class="sum-grid">${tile("securite", counts.securite || 0, lg)}${tile("cible", counts.cible || 0)}${tile("ambitieux", counts.ambitieux || 0)}
    <div class="sum-tile"><span class="sum-label">Autres</span><span class="sum-value">${fmt(other)}</span><span class="sum-note">hors-profil, non ouverts ou non situés</span></div></div>`;
}
// profileLine: the stored profile read back in one line (the form folds under it once a profile exists)
function profileLine(p, serie) {
  if (isReo(p)) return [REO_LABEL, p.academie ? `académie de ${esc(acadLabel(p.academie))}` : ""].filter(Boolean).join(" · ");
  const ser = { bg: "bac général", bt: "bac technologique", bp: "bac professionnel" }[serie];
  const men = p.mention === "rattrapage" ? "bac au rattrapage" : MENTION_SHORT[p.mention] ? `mention ${MENTION_SHORT[p.mention]}` : "";
  const moy = validMoyenne(p.moyenne);
  return [ser, serie === "bg" ? `${esc(speName(p.spe1))} + ${esc(speName(p.spe2))}` : p.voie_label ? esc(p.voie_label) : "", men, moy !== null ? `moyenne ${moyenneText(moy)}` : "", p.academie ? `académie de ${esc(acadLabel(p.academie))}` : ""]
    .filter(Boolean).join(" · ");
}

// ---- R3 (owner, 2026-11-12): the advanced filters shared by the search and the map -----------------------------------------
// The bands come from /api/meta (filtres.vocab): the search is filtered on the server, the map in the browser, with the SAME limits.
// The zone filter sends the profile with the search (bac, specialties, mention), never stored, never in the audience figures. The
// complementary phase is a fact of a past campaign (admits), never places left this year. Nothing is ever sorted by these values.
const FI_TITLE = { zone: "Zone pour votre profil", statut: "Type d'établissement", capacite: "Capacité", complementaire: "Phase complémentaire", taux: "Taux d'accès officiel" };
const FI_HELP = {
  zone: "Lue pour votre profil (bac, spécialités, mention), comme dans « Mes vœux » : rien n'est enregistré. Des repères, pas des chances.",
  complementaire: "Des admis en phase complémentaire lors de la campagne de la formation : pas une promesse de places cette année.",
  taux: "Le taux d'accès officiel de la formation, tous candidats confondus : un repère, pas vos chances.",
  robn: "Cinq niveaux parmi les formations Parcoursup, de très exposée à très robuste, sur les métiers visés et leur diversité : une estimation du modèle de SupCompass. Ni une chance d'admission, ni une promesse d'emploi.",
};
const fiOptions = (g) => ((typeof META !== "undefined" && META && META.filtres && META.filtres[g]) || []);
// the band of a value: lower limit included, upper limit excluded (twin of filtres.band)
function filtreBand(v, bands) {
  if (v === null || v === undefined) return null;
  const b = (bands || []).find((x) => (x.min === null || x.min === undefined || v >= x.min) && (x.max === null || x.max === undefined || v < x.max));
  return b ? b.key : null;
}
// R4: a zone is drawn with its colour token AND its shape, the map's (rond = sécurité, carré = cible, triangle = ambitieux, an empty
// ring for every other reading), and always beside its name: never the colour or the shape alone. One shape helper for the map
// markers, the "Où je me situe" chart, the pills, the badges and the result cards.
function zoneShape(z, cx, cy, r, attrs) {
  return z === "cible" ? `<rect x="${cx - r * 0.85}" y="${cy - r * 0.85}" width="${r * 1.7}" height="${r * 1.7}" ${attrs}/>`
    : z === "ambitieux" ? `<path d="M${cx},${cy - r * 1.05}L${cx + r * 1.05},${cy + r * 0.85}L${cx - r * 1.05},${cy + r * 0.85}Z" ${attrs}/>`
      : `<circle cx="${cx}" cy="${cy}" r="${r}" ${attrs}/>`;
}
const ZONE_FILLED = ["securite", "cible", "ambitieux"];
function zoneMark(z, large) {
  const filled = ZONE_FILLED.includes(z);
  // owner, 2026-11-19: a « sécurité large » is the sécurité circle inside a ring (shape + name, never the colour alone)
  if (large && z === "securite") return `<svg class="zmark" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="3.6" fill="currentColor"/><circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>`;
  return `<svg class="zmark" viewBox="0 0 14 14" aria-hidden="true">${zoneShape(z, 7, 7, filled ? 5.5 : 4.3,
    filled ? 'fill="currentColor"' : 'fill="none" stroke="currentColor" stroke-width="2"')}</svg>`;
}
// the « sécurité large » nuance: only on a sure sécurité, never on an uncertain one
const isLargeShown = (z, uncertain, large) => !!large && z === "securite" && !uncertain;
// a zone pill: filled with the zone's token, its shape, its name
function zonePillHtml(z, uncertain, large) {
  const zz = ZONES[z];
  if (!zz) return "";
  const L = isLargeShown(z, uncertain, large), h = zoneHelp(L ? "securite_large" : z);
  return `<span class="zone-pill" style="background:${zz.color}"${h ? ` title="${esc(h)}"` : ""}>${zoneMark(z, L)}${esc(zz.label.replace(/^Vœu /, ""))}${L ? " large" : ""}</span>${uncertain ? ' <span class="badge">incertain</span>' : ""}`;
}
// a zone badge (tables): outlined in the zone's token, its shape, its full name
function zoneBadge(z, uncertain, large) {
  const zz = ZONES[z];
  if (!zz) return '<span class="badge">non situé</span>';
  const L = isLargeShown(z, uncertain, large), h = zoneHelp(L ? "securite_large" : z);
  return `<span class="badge zbadge" style="--zc:${zz.color}"${h ? ` title="${esc(h)}"` : ""}>${zoneMark(z, L)}${esc(zz.label)}${L ? " large" : ""}</span>${uncertain ? ' <span class="badge">incertain</span>' : ""}`;
}


// owner, 2026-11-16: a shared search opens the search page with its parameters (checked there)
function viewRecherche(raw) {
  carteUI.pendingShare = raw || "";
  location.replace("#/carte");
}
// owner, 2026-11-15: the list search and the map are ONE page ("Rechercher une formation"); an old "#/s/<mots>" link (search ideas,
// a shared link) opens it with its keyword
async function viewSearch(q) {
  if (!q) return viewHome();
  carteUI.pendingQ = q;
  location.replace("#/carte");
}

function stageCard(title, keys, rec, note) {
  return `<div class="card stage"><h3>${title}</h3>${keys.map((k) => `<div class="kv"><span>${esc(label(k))}</span><strong>${fmt(rec[k])}</strong></div>`).join("")}
    ${note ? `<p class="muted small">${note}</p>` : ""}</div>`;
}

// ---- Sprint "Doublettes": proposal rates by bac route (THIS formation) and by doublette (its group, national) ----
// A doublette exists for the bac général only; techno and pro are routes ("voies"), each with its own colour token,
// never a zone's or the accent, always shown with its name. Rates: candidates with at least one proposal / candidates.
// A doublette with fewer than DBL_SEUIL candidates in a group is replaced by that group's "Autres doublettes" bucket,
// flagged as an estimation (doublettes.pick has the same rule). The profile picks the row here: it is never sent.
const VOIES = { bg: { label: "Bac général", color: "var(--voie-bg)" }, bt: { label: "Bac techno", color: "var(--voie-bt)" },
  bp: { label: "Bac pro", color: "var(--voie-bp)" } };
const DBL_SEUIL = 20;
const GATE_MIN = 100;   // journey.GATE_RULES["min_candidates"] (red team D8 checks they agree)
const pct1 = (v) => (v === null || v === undefined ? "—" : `${fmt(v, 1)} %`);
const voiePill = (s) => `<span class="voie-pill" style="color:${VOIES[s].color}">${VOIES[s].label}</span>`;
const rateBar = (taux, color) => `<span class="dbl-bar" aria-hidden="true"><i style="width:${Math.max(0, Math.min(100, Number(taux) || 0))}%;background:${color}"></i></span>`;
function profileDkey(p) {
  if (!p || isReo(p) || (p.serie && p.serie !== "bg") || typeof p.spe1 !== "string" || typeof p.spe2 !== "string" || p.spe1 === p.spe2) return null;
  return [p.spe1.toUpperCase(), p.spe2.toUpperCase()].sort().join("+");
}
function pickDoublette(g, dkey) {
  if (!g || !dkey) return null;
  const mine = g.doublettes.find((d) => d.key === dkey);
  if (mine && !mine.rare) return { source: "doublette", key: dkey, label: mine.label, taux: mine.taux, candidats: mine.candidats, trend: mine.trend };
  if (!g.autres || !g.autres.candidats) return null;
  return { source: "autres", key: dkey, label: mine ? mine.label : dkey, taux: g.autres.taux, candidats: g.autres.candidats,
    n_doublettes: g.autres.n_doublettes, trend: g.autres.trend, estimation: true };
}
// per-formation estimate (owner's request): no open data crosses doublette x establishment, so this formation's published bac
// général proposal rate is scaled by the doublette's ratio in its group (pooled), capped at 100: always an "estimation"
function estimateDoublette(series, g, dkey) {
  // the route figures of /api/formation (not a stage-2 row: redteam_scale S4 watches stage-2 field reads by name)
  const p = pickDoublette(g, dkey), { bg } = series || {};
  if (!p || !bg || bg.taux === null || bg.taux === undefined || p.taux === null || p.taux === undefined || !g.tous.taux) return null;
  const r = p.taux / g.tous.taux;
  const cap = (x) => (x === null || x === undefined ? null : Math.round(Math.min(100, x * r) * 10) / 10);
  return { taux: cap(bg.taux), base: bg.taux, ratio: Math.round(r * 1000) / 1000, source: p.source, label: p.label, fragile: !!bg.fragile,
    estimation: true, trend: bg.trend.map((t) => ({ session: t.session, taux: cap(t.taux) })), mine: p.taux, tous: g.tous.taux };
}
// owner's request (2026-11-10): where this formation's own report has no bac général table, the ratio comes from the verified
// reports of its similar formations (same diploma, same mention), pooled over the reports that detail the doublette (twin of
// semblables.estimate): this formation's bac général rate x (doublette / all bac général of the same reports), capped at 100
function estimateSemblable(series, sem, dkey) {
  const x = sem && dkey ? (sem.doublettes || []).find((r) => r.key === dkey) : null, { bg } = series || {};
  if (!x || !bg || bg.taux === null || bg.taux === undefined || x.taux === null || x.taux === undefined || !x.tous_taux) return null;
  const r = x.taux / x.tous_taux;
  const cap = (v) => (v === null || v === undefined ? null : Math.round(Math.min(100, v * r) * 10) / 10);
  return { taux: cap(bg.taux), base: bg.taux, ratio: Math.round(r * 1000) / 1000, source: "semblables", label: x.label,
    n_rapports: x.n_rapports, mine: x.taux, tous: x.tous_taux, fragile: !!bg.fragile, estimation: true,
    trend: bg.trend.map((t) => ({ session: t.session, taux: cap(t.taux) })) };
}
const ownHasBg = (rp) => { const { bg: rows = [] } = (rp && rp.doublettes) || {}; return !!rows.length; };
const semName = (sem) => `${esc(sem.fili === "Licence_Las" ? "L.AS" : sem.fili)} ${esc(sem.filiere)}`;
function semblablesDoublettes(sem, dkey, est) {
  if (!sem || !(sem.doublettes || []).length) return "";
  const mine = dkey ? sem.doublettes.find((x) => x.key === dkey) : null;
  const rows = [mine, ...sem.doublettes.filter((x) => x !== mine).slice(0, 6)].filter(Boolean);
  return `<h4>Dans les formations semblables (${semName(sem)}, rapports publics ${esc(sem.session)})</h4>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Spécialités</th><th class="num">Taux d'accès</th><th class="num">Candidats</th><th class="num">Rapports</th></tr>
    ${rows.map((x) => `<tr${x === mine ? ' class="dbl-mine"' : ""}><td>${x === mine ? "Vos spécialités : " : ""}${esc(x.label)}</td>
      <td class="num" data-label="Taux d'accès">${pct1(x.taux)}${rateBar(x.taux, "var(--voie-bg)")}</td>
      <td class="num" data-label="Candidats">${fmt(x.en_position)} sur ${fmt(x.confirmes)}</td>
      <td class="num" data-label="Rapports">${fmt(x.n_rapports)}</td></tr>`).join("")}</table></div>
    <p class="muted small">Pour chaque paire de spécialités, les rapports des formations semblables qui la détaillent (au moins ${fmt(sem.min_rapports)} rapports et ${fmt(sem.min_candidats)} candidats), additionnés : candidats classés assez haut pour recevoir une proposition en phase principale, sur les candidats ayant confirmé le vœu. Ce ne sont pas les chiffres de cette formation, et ce ne sont pas des chances d'admission.${dkey && !mine && est === null ? " Vos deux spécialités ne sont détaillées dans aucun ou dans trop peu de ces rapports." : ""}</p>`;
}
// Codex (PR #37): the pooled figures say which campaigns they cumulate; a group with a counting break (doublettes.BREAK_*)
// names the left-out campaigns and why, next to the figures
function dblCampagnes(g) {
  const kept = [...new Set((g.tous.trend || []).map((t) => t.session))].sort();
  const out = (g.campagnes_ecartees || []).slice().sort();
  const span = kept.length ? (out.length ? kept.join(", ") : `${kept[0]}–${kept[kept.length - 1]}`) : "2022–2025";
  return `campagnes ${span} cumulées${out.length ? ` · ${out.join(" et ")} ${out.length > 1 ? "écartées" : "écartée"} : rupture de comptage dans les données publiées (candidats multipliés par 2 ou 3 sans hausse des propositions), ces campagnes ne sont dans aucun chiffre de ce bloc ni dans l'estimation` : ""}`;
}
const DBL_CAVEAT = "Parmi les candidats ayant fait au moins un vœu dans ce groupe de formations (toute la France), part ayant reçu au moins une proposition. Chiffre national du groupe, pas propre à cet établissement. Ce sont des résultats passés, pas des chances d'admission.";
// lot 1, PR 11: the card opens on THE figure for the profile, the one L'essentiel shows (profileRate, same rules, same order);
// the other rates of the formation by bac route are folded under a summary saying what they are for (comparing), never removed
function profileLead(pr) {
  if (!pr || pr.taux === null || pr.taux === undefined || !PR_SOURCE[pr.source]) return "";
  return `<div class="pr-lead"><p class="small"><span class="sum-label">Pour votre profil</span> <strong class="pr-lead-v">${pct1(pr.taux)}</strong></p>
    <p class="muted small">${esc(pr.what)} · ${PR_SOURCE[pr.source](pr)}. Le même chiffre que dans « L'essentiel ». Les chiffres repliés ci-dessous comptent d'autres candidats (tout votre bac, toutes les phases) : ils servent à comparer.</p></div>`;
}
function doubletteCard(d, rp, sem, pr) {
  if (!d) return "";
  const lead = profileLead(pr);
  const prof = bacProfile() || {};
  const own = rapportDoublettes(rp, prof);      // sprint "Rapports publics": this formation's OWN published figures
  const myVoie = ["bg", "bt", "bp"].includes(prof.serie) ? prof.serie : (prof.spe1 ? "bg" : null);
  const last = Object.values(d.series)[0].trend.slice(-1)[0];
  // PR 2 of the audit: on the latest campaign's page, the search card's « taux d'accès de ce bac » first, under the same name;
  // the ministry's proposal rate (every phase, every candidate of the route) second, named for what it is
  const acc = d.acces || null;
  const voies = ["bg", "bt", "bp"].map((s) => { const v = d.series[s];
    return `<tr${s === myVoie ? ' class="dbl-mine"' : ""}><td>${voiePill(s)}${s === myVoie ? ' <span class="estim">votre bac</span>' : ""}</td>
      ${acc ? `<td class="num" data-label="Taux d'accès de ce bac">${bacAccesHtml(acc[s])}</td>` : ""}
      <td class="num" data-label="${acc ? "Propositions reçues, toutes phases" : "Taux de proposition"}">${pct1(v.taux)}${v.taux !== null && v.taux !== undefined ? rateBar(v.taux, VOIES[s].color) : ""}</td>
      <td class="num" data-label="Candidats">${fmt(v.candidats)}${v.fragile && v.candidats ? ' <span class="badge warnb">peu de candidats</span>' : ""}</td></tr>`; }).join("");
  const dkey0 = profileDkey(prof);
  // where this formation's own report has no bac général table: the similar formations' reports, then the national group
  const semEst = own.hasBg ? null : estimateSemblable(d.series, sem, dkey0);
  const semBlock = own.hasBg ? "" : `${semEst ? `<div class="dbl-est"><p class="small"><strong>Vos deux spécialités dans cette formation : ${pct1(semEst.taux)}</strong> ${estimTag(`à partir de ${fmt(semEst.n_rapports)} rapports de formations semblables`)}${rateBar(semEst.taux, "var(--voie-bg)")}</p>
      <p class="muted small">Calcul : taux de proposition des bacheliers généraux de cette formation (${pct1(semEst.base)}${semEst.fragile ? ", peu de candidats" : ""}) × écart de vos deux spécialités dans ${fmt(semEst.n_rapports)} rapports publics ${esc(sem.session)} de formations semblables (${semName(sem)}) : ${pct1(semEst.mine)} contre ${pct1(semEst.tous)} pour tous les bacheliers généraux de ces mêmes rapports. ${rp ? "Le rapport de cette formation ne détaille pas les paires de spécialités" : "Cette formation n'a pas de rapport public vérifié pour cette session"} : ce chiffre suppose que l'écart mesuré dans les formations semblables vaut aussi ici.</p></div>` : ""}${semblablesDoublettes(sem, dkey0, semEst)}`;
  let dbl;
  if (d.status !== "ok") dbl = `<p class="muted small">Pas de donnée par paire de spécialités pour ce type de formation : le ministère ne la publie que pour les groupes de formations qu'il suit.</p>`;
  else {
    const g = d.groupe, dkey = profileDkey(prof), mine = pickDoublette(g, dkey);
    const row = (lab, x, color, extra = "", cls = "") => `<tr${cls}><td>${lab}${extra}</td><td class="num" data-label="Taux de proposition">${pct1(x.taux)}${rateBar(x.taux, color)}</td><td class="num" data-label="Candidats">${fmt(x.candidats)}</td></tr>`;
    const top = g.doublettes.filter((x) => !x.rare && x.key !== (mine && mine.source === "doublette" ? dkey : "")).slice(0, 5);
    // the estimate is only shown when this formation's report gives no bac général figure
    const est = own.hasBg || semEst ? null : estimateDoublette(d.series, g, dkey);
    const estBlock = est ? `<div class="dbl-est"><p class="small"><strong>Vos deux spécialités dans cette formation : ${pct1(est.taux)}</strong> ${estimTag()}${rateBar(est.taux, "var(--voie-bg)")}</p>
      <p class="muted small">Calcul : taux de proposition des bacheliers généraux de cette formation (${pct1(est.base)}${est.fragile ? ", peu de candidats" : ""}) × écart de ${est.source === "autres" ? "vos « Autres paires de spécialités »" : "vos deux spécialités"} dans le groupe au niveau national (${pct1(est.mine)} contre ${pct1(est.tous)} pour tous les bacheliers généraux). Aucune donnée publique ne donne les paires de spécialités établissement par établissement : ce chiffre suppose que l'écart national vaut aussi ici.</p></div>` : "";
    dbl = `${estBlock}<h4>Détail national du groupe</h4><p class="small">Groupe de formations du ministère : « <strong>${esc(g.label)}</strong> » · ${dblCampagnes(g)}</p>
      <div class="scroll"><table class="stack"><tr class="stack-head"><th>Spécialités</th><th class="num">Taux de proposition</th><th class="num">Candidats</th></tr>
      ${mine ? row(`Vos spécialités : ${esc(mine.label)}`, mine, "var(--voie-bg)", mine.source === "autres" ? estimTag(`peu de candidats ont vos deux spécialités : chiffre des « Autres paires de spécialités » (${fmt(mine.n_doublettes)} paires de moins de ${DBL_SEUIL} candidats regroupées)`, true) : "", ' class="dbl-mine"') : ""}
      ${row("Tous les bacheliers généraux du groupe", g.tous, "var(--muted)")}
      ${top.map((x) => row(esc(x.label), x, "var(--voie-bg)")).join("")}
      ${g.autres.candidats ? row(`Autres paires de spécialités <span class="estim">(${fmt(g.autres.n_doublettes)} paires de moins de ${DBL_SEUIL} candidats)</span>`, g.autres, "var(--voie-bg)") : ""}
      </table></div>
      ${!dkey ? `<p class="small"><a href="#/profil">Indiquez vos spécialités dans « Mon profil »</a> pour voir vos deux spécialités en premier.</p>` : ""}
      <p class="muted small">${DBL_CAVEAT}</p>`;
  }
  const voiesBlock = `<h3>Par voie de bac, pour cette formation${last ? ` (campagne ${esc(last.session)})` : ""}</h3>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Voie</th>${acc ? `<th class="num">Taux d'accès de ce bac</th><th class="num">Propositions reçues, toutes phases</th>` : '<th class="num">Taux de proposition</th>'}<th class="num">Candidats</th></tr>${voies}</table></div>
    ${acc ? `<p class="muted small"><strong>Taux d'accès de ce bac</strong> : le chiffre de la carte de recherche, la part des candidats de ce bac classés assez haut pour recevoir une proposition en phase principale, d'après le rapport du jury (candidats de terminale en France) ; * = pas de rapport, estimation du site. <strong>Propositions reçues</strong> : la part de tous les candidats de ce bac ayant reçu une proposition, toutes phases (chiffre du ministère). Moins de ${DBL_SEUIL} candidats : chiffre fragile.</p>`
    : `<p class="muted small">Part des candidats de chaque voie ayant reçu une proposition de cette formation (toutes phases). Moins de ${DBL_SEUIL} candidats : chiffre fragile.</p>`}`;
  return `<div class="card"><h2>Selon votre bac</h2>
    ${lead}
    ${lead ? `<details class="more-card"><summary>Les chiffres de chaque voie de bac, pour comparer</summary>${voiesBlock}</details>` : voiesBlock}
    ${own.html}
    ${own.hasBg
    // the formation's own report already gives the student's figure: the national group detail is folded (2026-11-23, phone
    // page length, red team X7), never removed
    ? `<details class="more-card"><summary>Le même détail pour tout le groupe de formations, en France</summary>
    <h3>Par paire de spécialités (bac général) : le groupe de formations, toute la France</h3>${semBlock}${dbl}</details>`
    : `<h3>Par paire de spécialités (bac général)</h3>${semBlock}${dbl}`}</div>`;
}
// ---- Sprint "Rapports publics": the formation's own report (archived PDF, checked against SIES) ----
const RP_VOIE = { bg: "Bac général", bt: "Bac technologique", bp: "Bac professionnel" };
// the student's row in THIS formation's report: their doublette, else the formation's own "Autres doublettes"
// (twin of rapports.pick)
function pickRapport(rp, dkey) {
  if (!rp || !dkey) return null;
  const { bg: rows = [] } = rp.doublettes || {};      // destructured: redteam_scale S4 watches stage-2 field reads by name
  const mine = rows.find((x) => x.key === dkey);
  if (mine) return { ...mine, source: "doublette" };
  if (rows.some((x) => x.key == null && !x.autres)) return null;     // a pair label no rule knows may be the student's (arts)
  const other = rows.find((x) => x.autres);
  return other ? { ...other, source: "autres" } : null;
}
// sprint 20: the bac techno / pro student's own row (series and specialties, or bac pro specialty), else the formation's own
// bucket ("Autres doublettes" / "Autres spécialités"); twin of voies.pick_voie
function pickVoie(rp, bac, key) {
  if (!rp || !["bt", "bp"].includes(bac) || !key) return null;
  const rows = (rp.doublettes || {})[bac] || [];
  if (rows.some((x) => x.voie == null && !x.autres)) return null;          // a label no rule knows: never claim the bucket
  const mine = rows.find((x) => x.voie === key);
  if (mine) return { ...mine, source: "voie" };
  const known = (rp.voie_keys || {})[bac];
  if (key !== "autre" && Array.isArray(known) && !known.includes(key)) return null;   // not printed that session (renamed, older)
  const other = rows.find((x) => x.autres);
  return other ? { ...other, source: "autres" } : null;
}
const VOIE_WORD = { bt: "série", bp: "spécialité" };
const RP_CAVEAT = "Part des candidats ayant confirmé ce vœu qui ont été classés assez haut pour recevoir une proposition en phase principale : le taux d'accès de la formation, détaillé par paire de spécialités, calculé à partir des effectifs publiés dans son rapport. Seuls y figurent les candidats scolarisés en terminale en France depuis 2020-2021. Ce sont des résultats passés, pas des chances d'admission.";
// a report SIES has not published the figures of yet (owner's choice: shown, with this mark)
const rpPending = (rp) => (rp && rp.recoupe === false ? ` <span class="badge warnb">pas encore recoupé avec les chiffres de ${esc(rp.session)}</span>` : "");
function rapportSource(rp) {
  const d = String(rp.capture || "");
  const when = d.length >= 8 ? `${d.slice(6, 8)}/${d.slice(4, 6)}/${d.slice(0, 4)}` : "";
  const where = rp.source === "live" ? `lu le ${esc(when)} sur la fiche Parcoursup de la formation` : `copie archivée le ${esc(when)} par l'Internet Archive`;
  return `Source : rapport public Parcoursup de la session ${esc(rp.session)} (commission d'examen des vœux de la formation), ${where} : <a href="${esc(rp.archive)}" target="_blank" rel="noopener">voir le rapport ↗</a>. ${rp.recoupe === false ? `Pas encore recoupé avec les chiffres de ${esc(rp.session)} : le ministère ne les a pas encore publiés ; le rapport sera vérifié dès leur publication.` : "Ses candidats confirmés égalent ceux publiés par le ministère pour cette formation."}`;
}
function rapportDoublettes(rp, prof) {
  if (!rp || !rp.doublettes) return { html: "", hasBg: false };
  const dkey = profileDkey(prof), mine = pickRapport(rp, dkey);
  const myVoie = ["bg", "bt", "bp"].includes(prof.serie) ? prof.serie : (prof.spe1 ? "bg" : null);
  const vkey = myVoie === "bt" || myVoie === "bp" ? prof.voie || null : null, mineV = pickVoie(rp, myVoie, vkey);
  const blocks = ["bg", "bt", "bp"].map((v) => {
    const rows = rp.doublettes[v] || [];
    if (!rows.length) return (rp.masques || []).includes(v) && (v === "bg" || v !== myVoie) ? `<p class="small">${voiePill(v)} <span class="muted">chiffres non publiés par la formation (effectifs trop faibles)</span></p>` : "";
    return `<div class="scroll"><table class="stack"><tr class="stack-head"><th>${voiePill(v)} ${v === "bp" ? "Spécialité" : "Spécialités"}</th><th class="num">Taux d'accès</th><th class="num">Candidats</th></tr>
      ${rows.map((x) => { const me = v === "bg" && mine && (mine.source === "doublette" ? x.key === dkey : x.autres) && myVoie === "bg";
        const meV = v === myVoie && mineV && (mineV.source === "voie" ? x.voie === vkey : x.autres);
        const tag = me ? (mine.source === "autres" ? "vos deux spécialités en font partie" : "vos deux spécialités")
          : meV ? (mineV.source === "autres" ? `votre ${VOIE_WORD[v]} en fait partie` : "votre bac") : "";
        return `<tr${me || meV ? ' class="dbl-mine"' : ""}><td>${esc(rpLabel(x.libelle))}${tag ? ` <span class="estim">${tag}</span>` : ""}</td>
        <td class="num" data-label="Taux d'accès">${pct1(x.taux)}${x.taux !== null && x.taux !== undefined ? rateBar(x.taux, VOIES[v].color) : ""}</td>
        <td class="num" data-label="Candidats">${fmt(x.en_position)} sur ${fmt(x.confirmes)}</td></tr>`; }).join("")}</table></div>`;
  }).join("");
  if (!blocks) return { html: "", hasBg: false };
  const head = mine && myVoie === "bg" ? `<div class="dbl-est"><p class="small"><strong>Vos deux spécialités dans cette formation : ${pct1(mine.taux)}</strong> <span class="estim">rapport public ${esc(rp.session)}${mine.source === "autres" ? ", ligne « Autres paires de spécialités » de la formation" : ""}</span>${rateBar(mine.taux, "var(--voie-bg)")}</p>
    <p class="muted small">${fmt(mine.en_position)} candidats sur ${fmt(mine.confirmes)} ayant ${mine.source === "autres" ? "une paire de spécialités autre que celles détaillées" : "cette paire de spécialités"} ont été classés assez haut pour recevoir une proposition.${mine.source === "autres" ? " La formation ne détaille que ses paires de spécialités les plus fréquentes : la vôtre est comptée avec les autres." : ""}</p></div>` : "";
  const voieRows = vkey !== null || myVoie === "bt" || myVoie === "bp" ? (rp.doublettes[myVoie] || []) : [];
  const headV = !(myVoie === "bt" || myVoie === "bp") ? ""
    : mineV ? `<div class="dbl-est"><p class="small"><strong>Votre bac dans cette formation : ${pct1(mineV.taux)}</strong> <span class="estim">rapport public ${esc(rp.session)}, ligne « ${esc(rpLabel(mineV.libelle))} »${mineV.source === "autres" ? " de la formation" : ""}</span>${rateBar(mineV.taux, VOIES[myVoie].color)}</p>
    <p class="muted small">${fmt(mineV.en_position)} candidats sur ${fmt(mineV.confirmes)} ${mineV.source === "autres" ? `dont la ${VOIE_WORD[myVoie]} n'est pas détaillée` : `de votre ${VOIE_WORD[myVoie]}`} ont été classés assez haut pour recevoir une proposition.${mineV.source === "autres" ? ` La formation ne détaille que ses ${VOIE_WORD[myVoie]}s les plus fréquentes : la vôtre est comptée avec les autres.` : ""}</p></div>`
    : (rp.masques || []).includes(myVoie) ? `<p class="small">Pour le ${myVoie === "bt" ? "bac technologique" : "bac professionnel"}, la formation n'a pas publié son tableau (effectifs trop faibles) : pas de ligne pour vous dans ce rapport.</p>`
    : voieRows.length && !vkey ? `<p class="small"><a href="#/profil">Indiquez votre ${myVoie === "bt" ? "série et vos spécialités" : "spécialité de bac pro"}</a> pour voir le chiffre de votre bac.</p>`
    : voieRows.length ? `<p class="small">Votre ${VOIE_WORD[myVoie]} n'apparaît pas dans les rapports de la session ${esc(rp.session)} : pas de ligne comparable dans ce rapport.</p>` : "";
  const { bg: bgRows = [] } = rp.doublettes;
  return { hasBg: !!bgRows.length, html: `<h3>Dans cette formation, par paire de spécialités, série ou spécialité (rapport public ${esc(rp.session)})${rpPending(rp)}</h3>${head}${headV}${blocks}
    <p class="muted small">${RP_CAVEAT}</p><p class="muted small">${rapportSource(rp)}</p>` };
}
// what the jury looks at: its criteria with the published importance, the specialties it takes into account, the options it
// names (quoted, never interpreted), eliminating criteria, method and advice; every text is the jury's own, escaped
// journey.SPECIALTIES, the labels the reports print in their list of specialties taken into account (red team checks equality)
// PR 3 of the audit (2026-11-23): what a student reads never shows a raw code or a report's internal label.
// The specialty codes by their short names (the vocabulary's `short`, red team LA9 checks the two agree); a report's printed
// bucket « Autres doublettes » reads « Autres paires de spécialités » (Q4: no « doublette »), and bac techno STMG's « Msgn/ X »
// (Management, sciences de gestion et numérique, enseignement X) reads « Management (X) ». Display only: every rule reads the keys.
const SPE_SHORT = {"MATHS": "Mathématiques", "PC": "Physique-Chimie", "SVT": "SVT", "SES": "SES", "HGGSP": "HGGSP", "LLCER": "LLCER", "HLP": "HLP", "NSI": "NSI", "SI": "Sciences de l'ingénieur", "LLCA": "LLCA", "EPPCS": "EPPCS", "ART": "Arts", "BIOECO": "Biologie-écologie"};
const speName = (c) => SPE_SHORT[c] || String(c ?? "");
const rpLabel = (x) => String(x ?? "").replace(/^Autres doublettes$/i, "Autres paires de spécialités").replace(/Msgn\/\s*([^&·]+?)(?=\s*(?:&|·|$))/g, "Management ($1)");
const RP_SPE = {"MATHS": "Mathématiques Spécialité", "PC": "Physique-Chimie Spécialité", "SVT": "Sciences de la vie et de la Terre Spécialité", "SES": "Sciences Economiques et Sociales Spécialité", "HGGSP": "Histoire-Géographie, Géopolitique et Sciences politiques", "LLCER": "Langues, littératures et cultures étrangères et régionales", "HLP": "Humanités, Littérature et Philosophie", "NSI": "Numérique et Sciences Informatiques", "SI": "Sciences de l'ingénieur et sciences physiques", "LLCA": "Littérature et langues et cultures de l'Antiquité", "EPPCS": "Éducation physique, pratiques et culture sportives", "ART": "Art", "BIOECO": "Biologie/Ecologie"};
const RP_IMP = ["Essentiel", "Très important", "Important", "Complémentaire"];
const RP_OPTIONS = { maths_expertes: "Mathématiques expertes", maths_complementaires: "Mathématiques complémentaires", dgemc: "Droit et grands enjeux du monde contemporain",
  langues_anciennes: "Langues anciennes (latin, grec)", lv3: "Troisième langue vivante", option_arts: "Option arts", option_eps: "Option EPS",
  section_euro: "Section européenne ou internationale", certifications: "Certifications" };
const rpText = (t) => esc(t || "").replace(/\n/g, "<br>");
function juryParts(rp) {
  const t = rp.textes, prof = bacProfile() || {};
  const crit = (t.criteres || []).filter((c) => c.critere || c.elements);
  const champs = [...new Set(crit.map((c) => c.champ))];
  const impCls = (i) => { const k = RP_IMP.indexOf(i); return k < 0 ? "" : ` imp${k}`; };
  const critHtml = champs.length ? `<h3>Ses critères et leur importance</h3><div class="scroll"><table class="stack"><tr class="stack-head"><th>Critère</th><th>Ce qui est regardé</th><th>Importance</th></tr>
    ${champs.map((ch) => `<tr class="rp-champ"><td colspan="3"><strong>${esc(ch)}</strong></td></tr>${crit.filter((c) => c.champ === ch).map((c) => `<tr><td data-label="Critère">${esc(c.critere)}</td><td data-label="Ce qui est regardé">${esc(c.elements)}</td><td data-label="Importance">${c.importance ? `<span class="rp-imp${impCls(c.importance)}">${esc(c.importance)}</span>` : ""}</td></tr>`).join("")}`).join("")}
    </table></div>` : "";
  const eds = t.eds || {};
  const mySpe = [prof.spe1, prof.spe2].filter((x) => typeof x === "string" && RP_SPE[x]).map((x) => RP_SPE[x].toLowerCase());
  const edsList = Object.entries(eds.liste || {}).map(([serie, items]) => `<p class="small"><strong>${esc(serie)}</strong> : ${items.map((x) => {
    return mySpe.includes(String(x).toLowerCase()) ? `<mark>${esc(rpLabel(x))}</mark>` : esc(rpLabel(x)); }).join(" · ")}</p>`).join("");
  const edsHtml = eds.pris_en_compte ? `<h3>Les spécialités de terminale</h3>
    <p class="small">La commission dit ${/^oui/i.test(eds.pris_en_compte) ? "<strong>prendre en compte</strong>" : "<strong>ne pas prendre en compte</strong>"} les enseignements de spécialité.${eds.poids ? ` Le poids des résultats dans certaines spécialités, d'après la commission : « ${esc(eds.poids.replace(/\.$/, ""))} ».` : ""}</p>${edsList}` : "";
  const opts = t.options_citees || {};
  const me = prof.maths_expertes && (prof.spe1 === "MATHS" || prof.spe2 === "MATHS");
  const optHtml = Object.keys(opts).length || me ? `<h3>Options et parcours cités par le jury</h3>
    ${me ? `<p class="small">Vous suivez <strong>Mathématiques expertes</strong> : ${opts.maths_expertes ? "le rapport de cette formation la cite (voir ci-dessous)." : "le rapport de cette formation ne la cite pas. Cela ne veut pas dire qu'elle ne compte pas : regardez les attendus de la fiche Parcoursup."}</p>` : ""}
    ${Object.entries(opts).map(([k, quotes]) => `<p class="small"><strong>${esc(RP_OPTIONS[k] || k)}</strong></p>${quotes.map((q) => `<blockquote class="rp-quote">« ${esc(q)} »</blockquote>`).join("")}`).join("")}` : "";
  const fold = (title, txt) => (txt ? `<details class="dip"><summary>${title}</summary><p class="small">${rpText(txt)}</p></details>` : "");
  return { critHtml, edsHtml, optHtml, elim: fold("Critères éliminatoires", t.eliminatoires), modal: fold("Comment les dossiers ont été examinés", t.modalites),
    algo: fold("Traitement algorithmique", t.algorithme), conseils: fold("Les conseils du jury pour la prochaine session", t.conseils) };
}
function juryCard(rp) {
  if (!rp || !rp.textes) return "";
  const P = juryParts(rp);
  return `<div class="card"><h2>Ce que regarde le jury · rapport public ${esc(rp.session)}${rpPending(rp)}</h2>
    <p class="small">Ce que la commission d'examen des vœux de cette formation a écrit elle-même dans son rapport public, repris tel quel.${rp.concours ? " Ce rapport est commun à plusieurs formations d'un même concours." : ""}</p>
    ${P.critHtml}${P.edsHtml}${P.optHtml}
    ${P.elim}${P.modal}${P.algo}${P.conseils}
    <p class="muted small">Les critères et leur importance sont ceux que la formation a publiés ; ils peuvent changer d'une session à l'autre. Ils décrivent l'examen des dossiers, pas des chances d'admission.</p>
    <p class="muted small">${rapportSource(rp)}</p></div>`;
}
// owner's request (2026-11-13): the evaluation grid and the expected skills the LIVE Parcoursup fiche publishes for its own
// campaign (grilles.py): the weight of each field (global view), each criterion with what is read and its importance (detailed
// view), the national and the formation's own expectations, the advice. Published values, verbatim and escaped; never a score
// or a chance; the fiche fait foi.
const GR_IMP = { 4: "Essentiel", 3: "Très important", 2: "Important", 1: "Complémentaire" };
function ficheText(t) {
  const out = [];
  let list = [];
  const flush = () => { if (list.length) { out.push(`<ul class="small gr-list">${list.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`); list = []; } };
  for (const ln of String(t || "").split("\n")) {
    if (/^- /.test(ln)) { list.push(ln.slice(2)); continue; }
    flush();
    if (ln.trim()) out.push(`<p class="small">${esc(ln)}</p>`);
  }
  flush();
  return out.join("");
}
function grilleImp(n) {
  const lab = GR_IMP[n];
  if (!lab) return "";
  return `<span class="gr-imp"><span class="rp-imp imp${4 - n}">${esc(lab)}</span> <span class="gr-dots" aria-hidden="true">${[1, 2, 3, 4].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span></span>`;
}
const grilleHas = (g) => !!(g && (g.grille || g.nationaux || g.complementaires || g.info));
function grilleParts(g) {
  const lu = g.lu_le ? new Date(`${g.lu_le}T12:00:00Z`).toLocaleDateString("fr-FR") : null;
  const camp = g.session ? ` pour la campagne ${esc(g.session)}` : "";
  const champs = g.grille ? g.champs || [] : [];
  const global = champs.length ? `<h3>Vue d'ensemble : le poids de chaque partie du dossier</h3>
    <ul class="gr-global">${champs.map((c) => `<li><span class="gr-lab">${esc(c.champ)}</span>${rateBar(c.poids, "var(--ink)")}<strong class="num">${fmt(c.poids)} %</strong></li>`).join("")}</ul>
    <p class="muted small">Les parts additionnées font 100 %. C'est la formation qui les a fixées.</p>` : "";
  const detail = champs.length ? `<h3>Vue détaillée : les critères et leur importance</h3>
    ${champs.map((c) => `<details class="dip gr-champ"><summary><span><strong>${esc(c.champ)}</strong> · ${fmt(c.poids)} % · ${fmt(c.criteres.length)} critère${c.criteres.length > 1 ? "s" : ""}</span></summary>
      <div class="scroll"><table class="stack"><tr class="stack-head"><th>Critère</th><th>Ce qui est regardé</th><th>Importance</th></tr>
      ${c.criteres.map((k) => `<tr><td data-label="Critère">${esc(k.critere)}</td><td data-label="Ce qui est regardé">${esc(k.elements || "")}</td><td data-label="Importance">${grilleImp(k.importance)}</td></tr>`).join("")}
      </table></div></details>`).join("")}
    <p class="muted small">L'importance va de « Complémentaire » (1 sur 4) à « Essentiel » (4 sur 4), comme sur la fiche.</p>` : "";
  const fold = (title, t, open) => (t ? `<details class="dip gr-txt"${open ? " open" : ""}><summary>${title}</summary>${ficheText(t)}</details>` : "");
  return { camp, champs, info: g.info ? `<div class="gr-info">${ficheText(g.info)}</div>` : "", global, detail,
    attendus: `${fold("Les attendus nationaux", g.nationaux, !champs.length)}${fold("Les attendus de cette formation", g.complementaires, false)}`,
    conseils: fold("Les conseils de la formation", g.conseils, false),
    source: `Lu${lu ? ` le ${esc(lu)}` : ""} sur ${g.url ? `<a href="${esc(g.url)}" target="_blank" rel="noopener">la fiche Parcoursup ↗</a>` : "la fiche Parcoursup"}.` };
}
function grilleCard(g) {
  if (!grilleHas(g)) return "";
  const P = grilleParts(g);
  return `<div class="card gr-card"><h2>Comment votre dossier sera examiné · fiche Parcoursup${g.session ? ` ${esc(g.session)}` : ""}</h2>
    <p class="small">Voici ce que la formation publie sur sa fiche Parcoursup${P.camp}, repris tel quel.${g.grille ? "" : " Elle ne publie pas de grille d'examen."}</p>
    ${P.info}${P.global}${P.detail}
    ${P.attendus}${P.conseils}
    <p class="muted small">La grille peut changer d'une campagne à l'autre : la fiche Parcoursup fait foi. Elle décrit l'examen des dossiers, pas des chances d'admission.</p>
    <p class="muted small">${P.source}</p></div>`;
}
// owner, 2026-11-18: ONE card when the formation has both its fiche (the coming campaign) and its jury's report (the past
// session): each subject said once. The fiche comes first and prevails: its grid replaces the report's criteria, its advice the
// report's; the report adds only what the fiche does not publish (specialties taken into account, options cited, eliminating
// criteria, how the files were examined, the algorithm), each part labelled with its session. Texts verbatim and escaped.
function juryMerged(g, rp) {
  const G = grilleParts(g), R = juryParts(rp), grid = G.champs.length > 0;
  const fiche = `fiche Parcoursup${g.session ? ` ${esc(g.session)}` : ""}`, rapport = `rapport du jury ${esc(rp.session)}`;
  const crit = grid ? `${G.global}${G.detail}${R.critHtml ? `<p class="muted small">Le ${rapport} décrivait aussi ses critères : la grille de la ${fiche}, plus récente, les remplace.</p>` : ""}`
    : R.critHtml ? `${R.critHtml}<p class="muted small">Critères du ${rapport} : la ${fiche} ne publie pas de grille d'examen.</p>` : "";
  const fromReport = R.edsHtml || R.optHtml || R.elim || R.modal || R.algo;
  return `<div class="card gr-card jury-merged"><h2>Comment votre dossier est examiné</h2>
    <p class="small">Deux sources, reprises telles quelles : la <strong>${fiche}</strong>${G.camp}, la plus récente, qui fait foi, et le <strong>${rapport}</strong> de la session passée${rpPending(rp)}. Chaque sujet n'est montré qu'une fois ; quand les deux en parlent, c'est la fiche qui est retenue.${rp.concours ? " Ce rapport est commun à plusieurs formations d'un même concours." : ""}</p>
    ${G.info}${crit}
    ${G.attendus}
    ${fromReport ? `<h3>Ce que le ${rapport} ajoute</h3>${R.edsHtml}${R.optHtml}${R.elim}${R.modal}${R.algo}` : ""}
    ${G.conseils || R.conseils}
    <p class="muted small">Les critères peuvent changer d'une campagne à l'autre : la fiche Parcoursup fait foi. Ils décrivent l'examen des dossiers, pas des chances d'admission.</p>
    <p class="muted small">Fiche : ${G.source}</p><p class="muted small">${rapportSource(rp)}</p></div>`;
}
// owner's request (2026-11-10): no readable jury texts in this formation's own report, so the counts of what the commissions of
// its similar formations published (same diploma, same mention), never their average, never this formation's own criteria
const SEM_CRIT_N = 8;
function semblablesJuryCard(sem, rp) {
  if (!sem || !sem.jury) return "";
  const J = sem.jury, n = J.n, prof = bacProfile() || {};
  const champs = Object.keys(sem.champs || {});
  const cell = (k, i) => `<td class="num" data-label="${esc(i)}">${fmt(J.champs[k][i] || 0)}</td>`;
  const critHtml = `<h3>L'importance donnée à chaque critère</h3><div class="scroll"><table class="stack"><tr class="stack-head"><th>Critère</th>${RP_IMP.map((i) => `<th class="num">${esc(i)}</th>`).join("")}<th class="num">Non noté</th></tr>
    ${champs.map((k) => { const noted = RP_IMP.reduce((a, i) => a + (J.champs[k][i] || 0), 0);
      return `<tr><td>${esc(sem.champs[k])}</td>${RP_IMP.map((i) => cell(k, i)).join("")}<td class="num" data-label="Non noté">${fmt(n - noted)}</td></tr>`; }).join("")}
    </table></div><p class="muted small">Nombre de rapports, sur ${fmt(n)}, qui donnent à ce critère cette importance (la plus haute, quand un rapport en note plusieurs lignes). « Non noté » : le rapport ne note pas ce critère.</p>`;
  const mySpe = [prof.spe1, prof.spe2].filter((x) => typeof x === "string" && RP_SPE[x]).map((x) => RP_SPE[x].toLowerCase());
  const spe = Object.entries(J.eds.generale || {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const speLine = ([lab, c]) => `<li>${mySpe.includes(lab.toLowerCase()) ? `<mark>${esc(lab)}</mark>` : esc(lab)} : ${fmt(c)} rapport${c > 1 ? "s" : ""} sur ${fmt(n)}</li>`;
  const others = Object.entries(J.eds.autres || {}).sort((a, b) => a[0].localeCompare(b[0]));
  const edsHtml = `<h3>Les spécialités de terminale</h3>
    <p class="small">${fmt(J.eds.oui)} rapport${J.eds.oui > 1 ? "s" : ""} sur ${fmt(n)} disent prendre en compte les enseignements de spécialité, ${fmt(J.eds.non)} disent ne pas les prendre en compte${J.eds.non_dit ? `, ${fmt(J.eds.non_dit)} ne le disent pas` : ""}.</p>
    ${spe.length ? `<p class="small">Spécialités de la série générale citées :</p><ul class="small sem-list">${spe.slice(0, SEM_CRIT_N).map(speLine).join("")}</ul>
      ${spe.length > SEM_CRIT_N ? `<details class="dip"><summary>Les ${fmt(spe.length - SEM_CRIT_N)} autres spécialités citées</summary><ul class="small sem-list">${spe.slice(SEM_CRIT_N).map(speLine).join("")}</ul></details>` : ""}` : ""}
    ${others.length ? `<details class="dip"><summary>Séries technologiques</summary>${others.map(([serie, items]) => `<p class="small"><strong>${esc(serie)}</strong> : ${Object.entries(items).sort((a, b) => b[1] - a[1]).map(([lab, c]) => `${esc(rpLabel(lab))} (${fmt(c)})`).join(" · ")}</p>`).join("")}</details>` : ""}`;
  const opts = Object.entries(J.options || {}).sort((a, b) => b[1] - a[1]);
  const optHtml = opts.length ? `<h3>Options et parcours cités</h3><ul class="small sem-list">${opts.map(([k, c]) => `<li>${esc(RP_OPTIONS[k] || k)} : citée dans ${fmt(c)} rapport${c > 1 ? "s" : ""} sur ${fmt(n)}</li>`).join("")}</ul>
    <p class="muted small">Une option qu'un rapport ne cite pas peut compter quand même : regardez les attendus de la fiche Parcoursup.</p>` : "";
  const list = sem.formations || [];
  const links = list.length ? `<details class="dip"><summary>Lire les rapports de ces formations (${fmt(list.length)})</summary><ul class="small sem-list">${list.map((f) => `<li><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a> · ${esc(f.ville)}${f.academie ? ` (${esc(acadLabel(f.academie))})` : ""}</li>`).join("")}</ul></details>` : "";
  return `<div class="card"><h2>Ce que regardent les jurys de formations semblables <span class="estim">pas le rapport de cette formation</span></h2>
    <p class="small">${rp ? `Le rapport public ${esc(rp.session)} de cette formation ne donne pas de critères lisibles.` : `Cette formation n'a pas de rapport public vérifié pour la session ${esc(sem.session)}.`} Voici ce que disent ${fmt(n)} rapports publics ${esc(sem.session)} de formations du même diplôme et de la même mention (${semName(sem)}), vérifiés avec les chiffres du ministère. Le jury de cette formation peut avoir d'autres attentes : sa fiche Parcoursup fait foi.</p>
    ${critHtml}${edsHtml}${optHtml}${links}
    <p class="muted small">Des comptes de rapports, jamais une moyenne ni une note : ils décrivent l'examen des dossiers dans des formations semblables, pas des chances d'admission.</p></div>`;
}
// the 4-year curves of the evolution page: each route for this formation, the student's doublette in the group
// owner, 2026-11-22: the student's pair, year by year: the formation's OWN report of that campaign (its bac général table: the pair's
// line, else its « Autres » line; a table without either = no point, never an estimate), else the formation page's estimate
// (similar formations first, then the national group). A published figure replaces the estimate THAT year, never beside it.
function pairByYear(rps, years, dk) {
  return years.map((y) => {
    const rp = (rps || []).find((x) => x.session === y);
    if (!dk || !rp || !ownHasBg(rp)) return null;
    const r = pickRapport(rp, dk);
    return r ? { ...r, session: y } : { absent: true, session: y };
  });
}
function doubletteCharts(d, years, sem, rps, part) {
  if (!d) return "";
  const at = (trend, k) => years.map((y) => { const r = trend.find((x) => x.session === y); return r ? r[k] : null; });
  const bp0 = bacProfile(), myRoute = bp0 && bp0.serie;
  const series = ["bg", "bt", "bp"].map((s, i) => ({ name: `${VOIES[s].label}${myRoute === s ? " (votre bac)" : ""}`, color: VOIES[s].color, dash: ["", "6 4", "2 3"][i],
    mine: myRoute === s, tag: myRoute === s ? "votre bac" : "", values: at(d.series[s].trend, "taux"), hollow: at(d.series[s].trend, "candidats").map((c) => (c || 0) < DBL_SEUIL) }));
  let second = "";
  const dk = profileDkey(bp0), g = d.status === "ok" ? d.groupe : null, own = pairByYear(rps, years, dk);
  if (!dk && !(myRoute && myRoute !== "bg") && g) {                 // no pair yet: a short prompt, not a chart of the group alone
    second = `<div class="card"><h2>Vos deux spécialités, année par année</h2><p class="small"><a href="#/profil">Indiquez vos deux spécialités dans «\u00a0Mon profil\u00a0»</a> pour voir, année par année, la part des candidats qui les avaient et ont reçu une proposition ici.</p></div>`;
  } else if ((g || own.some(Boolean)) && !(myRoute && myRoute !== "bg")) {   // pairs of specialties exist for the bac général only
    const lines = g ? [{ name: "Tous les bacheliers généraux du groupe", color: EVO.ref, dash: "4 3", values: at(g.tous.trend, "taux") }] : [];
    const mine = g ? pickDoublette(g, dk) : null;
    // the formation page's estimate, for the years the formation's own report does not cover
    const sEst = estimateSemblable(d.series, sem, dk);
    const est = sEst || (g ? estimateDoublette(d.series, g, dk) : null);
    if (mine) lines.unshift({ name: mine.source === "autres" ? "Autres paires de spécialités, groupe national (estimation)" : `Vos spécialités : ${mine.label}, groupe national`, color: EVO.k2, dash: "6 4", values: at(mine.trend, "taux") });
    const estAt = est ? at(est.trend, "taux") : years.map(() => null);
    const vals = own.map((o, i) => (o ? (o.absent ? null : o.taux) : estAt[i]));
    const marks = own.map((o) => (o && !o.absent ? "pub" : "est"));
    const notes = own.map((o, i) => (o ? (o.absent ? "" : `publié : ${fmt(o.en_position)} classés assez haut pour recevoir une proposition sur ${fmt(o.confirmes)} confirmés${o.source === "autres" ? ", ligne « Autres paires de spécialités » du rapport" : ""}`)
      : estAt[i] != null ? "estimation" : ""));
    const pubYears = own.filter((o) => o && !o.absent).map((o) => o.session), absentYears = own.filter((o) => o && o.absent).map((o) => o.session);
    const yl = (a) => (a.length > 1 ? `${a.slice(0, -1).join(", ")} et ${a[a.length - 1]}` : `${a[0]}`);   // « 2024 et 2025 »
    if (vals.some((v) => v != null)) {
      lines.unshift({ name: "Vos deux spécialités dans cette formation", color: EVO.k1, dash: "", mine: true, tag: "vous", values: vals, marks,
        hollow: own.map((o) => !!o && !o.absent && (o.confirmes || 0) < DBL_SEUIL), notes });
    }
    const said = [
      pubYears.length ? `En ${yl(pubYears)} : chiffre du rapport public de la formation. C'est la part de ses candidats confirmés avec vos deux spécialités classés assez haut pour recevoir une proposition. Le rapport ne compte que les élèves de terminale en France.` : "",
      absentYears.length ? `En ${yl(absentYears)}, le rapport de la formation ne détaille pas votre paire ni ses « Autres paires » : pas de point cette année-là.` : "",
      est && vals.some((v, i) => v != null && marks[i] === "est") ? `Les autres années : ${estimTag(sEst ? `taux de proposition des bacheliers généraux de la formation × ce que donnent vos spécialités dans ${fmt(sEst.n_rapports)} rapports de formations semblables` : "taux de proposition des bacheliers généraux de la formation × ce que donnent vos spécialités dans le groupe national")}.` : "",
    ].filter(Boolean).map((t) => `<p class="small">${t}</p>`).join("");
    second = `<div class="card"><h2>Vos deux spécialités, année par année</h2><p class="small chart-cap">Part des candidats ayant reçu une proposition, cette formation${g ? ` et le groupe «\u00a0${esc(g.label)}\u00a0» (national)` : ""}. Des résultats passés, pas une chance.</p>${lineLegend(lines)}${lineChart(years, lines)}
      ${vals.some((v) => v != null) ? markKey(EVO.k1) : ""}${said ? `<details class="dip"><summary>Comment lire cette courbe</summary>${said}<p class="muted small">${DBL_CAVEAT}</p></details>` : `<p class="muted small">${DBL_CAVEAT}</p>`}</div>`;
  }
  const voies = `<div class="card"><h2>Taux de proposition par voie de bac (cette formation)</h2>${lineLegend(series)}${lineChart(years, series)}
    <p class="muted small">Points creux : moins de ${DBL_SEUIL} candidats de la voie cette année-là. Une voie à peu de candidats est rare, pas fermée. Des taux passés, pas une chance.</p></div>`;
  return part === "paire" ? second : part === "voies" ? voies : voies + second;
}

// ---- Sprint "Carte": the formations of one filière on an OpenStreetMap map, coloured by the student's zone ----
// The zones are those of "Mon parcours" (the same /api/journey/stage2 rows), never recomputed here; without a profile the
// points are neutral. The map is OpenStreetMap (owner's choice, 2026-11-08) drawn by Leaflet, self-hosted and loaded by this
// page only. The "around a town" filter runs here: no position is ever sent to the site.
const CARTE_ZONES = ["securite", "cible", "ambitieux"];
const CARTE_SHAPE = { securite: "rond", cible: "carré", ambitieux: "triangle" };   // the shape doubles the colour
const CARTE_OTHER = { label: "Autre ou non situé", color: "var(--zone-autre)" };
const CARTE_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";             // one place to change the tile provider
const CARTE_ATTRIB = "© les contributeurs d'OpenStreetMap";
const carteUI = { sel: null, page: 0, map: null, layer: null, type: null };
function haversineKm(a, b, c, d) {
  const r = Math.PI / 180, x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(x));
}
const carteZone = (f) => (CARTE_ZONES.includes(f.zone) ? f.zone : "autre");
const carteLabel = (z) => (z === "autre" ? CARTE_OTHER.label : ZONES[z].label);
// R4: a map formation outside the three zones: its own reading when it has one (hors-profil...), else the "autre" badge (a ring)
const carteZoneBadge = (zone, fallback) => (zone && ZONES[zone] ? zoneBadge(zone)
  : `<span class="badge zbadge" style="--zc:var(--zone-autre)">${zoneMark("autre")}${esc(fallback)}</span>`);
const carteColor = (z) => (z === "autre" ? CARTE_OTHER.color : ZONES[z].color);
// the zone of each formation is the one of "Mon parcours" (stage 2 rows), as is; none without a profile (red team C1)
// sprint Q3: the map layer arrives as rows of values under key templates (carte.couche); this twin of carte.dec rebuilds
// exactly the objects /api/carte/formations served (red team VT1 compares them). An object = [-(1 + template), values...]
const CARTE_TOUS = "*";
const CARTE_DETAIL_KEYS = ["bacs", "majo", "offres_app", "fiche", "reo"];      // carte.DETAIL_KEYS
function coucheDec(v, K, S, top) {
  if (Array.isArray(v)) {
    if (v.length && Number.isInteger(v[0]) && v[0] < 0) {
      const cols = K.kinds[-1 - v[0]], o = {};
      for (let i = 0; i < cols.length; i++) {
        const x = v[i + 1];
        o[cols[i]] = top && K.dict.has(cols[i]) && Number.isInteger(x) ? S[x] : coucheDec(x, K, S, false);
      }
      return o;
    }
    return v.map((x) => coucheDec(x, K, S, false));
  }
  return v;
}
function coucheDecode(P) {
  const K = { kinds: P.kinds, dict: new Set(P.dict_keys) };
  return { session: P.session, offre_apprentissage: P.offre_apprentissage, rows: P.rows.map((r) => coucheDec(r, K, P.strings, true)) };
}
// the cards' keys (rates per bac, most represented line, apprenticeship offers, Parcoursup page) come in a second answer: they
// are added to the SAME row objects (the cached layer then holds whole formations, as /api/carte/formations served them)
function coucheDetails(C, D) {
  const by = new Map(C.rows.map((f) => [f.cod_aff_form, f]));
  D.rows.forEach((x) => { const f = by.get(x.cod_aff_form); if (f) Object.assign(f, x); });
  C.details = true;
  return C;
}
// audit PR 8: the same as coucheDetails(C, coucheDecode(P)), in slices of CARTE_SLICE rows with a pause between them (the
// page stays responsive while 21,000 cards' details are decoded on a phone)
const CARTE_SLICE = 1500;
async function coucheDetailsParts(C, P) {
  const K = { kinds: P.kinds, dict: new Set(P.dict_keys) };
  const by = new Map(C.rows.map((f) => [f.cod_aff_form, f]));
  for (let i = 0; i < P.rows.length; i += CARTE_SLICE) {
    if (i) await new Promise((r) => setTimeout(r, 0));
    for (const r of P.rows.slice(i, i + CARTE_SLICE)) {
      const x = coucheDec(r, K, P.strings, true), f = by.get(x.cod_aff_form);
      if (f) Object.assign(f, x);
    }
  }
  C.details = true;
  return C;
}
// audit PR 8: the zones are written ON the layer's own rows (copying its 21,000 formations blocked a phone ~0.25 s at every
// visit); each visit writes zone and large again for every row, so nothing read for an earlier profile stays
function carteMerge(neutral, stage2, ok) {
  const zones = new Map(((stage2 && stage2.formations) || []).map((f) => [f.cod_aff_form, f.zone]));
  neutral.forEach((f) => { f.zone = ok ? (zones.get(f.cod_aff_form) || null) : null; f.large = false; });
  return neutral;
}
// the filter groups, inspired by the Parcoursup map: each group is a list of ticked options; an empty group keeps all.
// "prive" (fee-charging private institutions) is never ticked by default (Plan B's rule); "prive_app" is a private establishment
// outside State contract offering APPRENTICESHIP, free for the apprentice (Code du travail, art. L6211-1): ticked by default
const CARTE_GROUPS = [
  ["statut", "Types d'établissement", [["public", "Publics"], ["contrat", "Privés sous contrat avec l'État / EESC"], ["prive_app", "Privés hors contrat, en apprentissage (gratuit pour l'apprenti)"], ["prive", "Privés (payants)"]]],
  ["app", "Apprentissage", [["non", "Formations hors apprentissage"], ["oui", "Formations en apprentissage"]]],
  ["internat", "Internat", [["mixte", "Internat filles et garçons"], ["filles", "Internat pour filles"], ["garcons", "Internat pour garçons"]]],
  ["amenag", "Aménagements", [["presentiel", "Enseignement en présentiel"], ["partielle", "Enseignement partiellement à distance"], ["totale", "Enseignement entièrement à distance"],
    ["sport", "Aménagements pour sportifs de haut niveau"], ["art", "Aménagements pour artistes confirmés"]]],
  ["select", "Sélectivité", [["oui", "Formations sélectives"], ["non", "Formations non sélectives"]]],
];
const CARTE_DEFAULT = { statut: ["public", "contrat", "prive_app"] };
// owner, 2026-11-15: ONE search page (list + map), the Parcoursup way. The keyword goes to the search engine (/api/search/codes:
// acronyms, places, typos, in its relevance order); the place (région, département, académie, a town and a radius) and every
// filter are matched HERE, in the browser: the place is never sent.
const REGION_NOM = { "Ile-de-France": "Île-de-France", "Centre": "Centre-Val de Loire", "Grand-Est": "Grand Est", "Nouvelle Aquitaine": "Nouvelle-Aquitaine",
  "Pays-de-la-Loire": "Pays de la Loire", "Réunion": "La Réunion" };
const regionNom = (r) => REGION_NOM[r] || r;
// the places the bar offers, one label each: the profile's town first, then regions, départements, académies, the formations' towns
function carteLieux(rows, home) {
  const out = new Map(), regions = new Set(), deps = new Map(), acads = new Set(), towns = new Map();
  if (home) out.set(`Ma ville : ${villeLabel(home)}`, { t: "ville", v: villeLabel(home), lat: home.lat, lon: home.lon });
  rows.forEach((f) => {
    if (f.region) regions.add(f.region);
    if (f.dep && f.dep_lib) deps.set(f.dep, f.dep_lib);
    if (f.academie) acads.add(f.academie);
    if (f.ville && f.lat != null && !towns.has(f.ville)) towns.set(f.ville, { lat: f.lat, lon: f.lon });
  });
  [...regions].sort((a, b) => FR_COLL.compare(regionNom(a), regionNom(b))).forEach((r) => out.set(`${regionNom(r)} (région)`, { t: "region", v: r }));
  [...deps].sort((a, b) => a[0].localeCompare(b[0], "fr", { numeric: true })).forEach(([c, n]) => out.set(`${n} (${c})`, { t: "dep", v: c }));
  [...acads].sort(FR_COLL.compare).forEach((a) => out.set(`Académie de ${a}`, { t: "acad", v: a }));
  [...towns].sort((a, b) => FR_COLL.compare(a[0], b[0])).forEach(([t, x]) => { if (!out.has(t)) out.set(t, { t: "ville", v: t, lat: x.lat, lon: x.lon }); });
  return out;
}
// a typed place: its exact label, else the same words without accents or case, with or without "(région)" / the code; a code alone
function carteLieu(lieux, txt) {
  const s = String(txt || "").trim();
  if (!s) return null;
  if (lieux.has(s)) return lieux.get(s);
  const k = foldText(s);
  for (const [label, x] of lieux) {
    if (foldText(label) === k || foldText(label.replace(/ \((?:région|[0-9][0-9AB]?[0-9]?)\)$/, "")) === k || (x.t === "dep" && x.v === s.toUpperCase())) return x;
  }
  return null;
}
// owner, 2026-11-16: a search shared as a link (#/recherche/<parameters>). Everything travels after "#" (never sent to a server,
// nothing stored by the site): the words, the place TYPED (never the profile's town), the radius, the types, the mentions and the
// filter groups that differ from their default (never the zones: they belong to the reader's own profile). Every value is checked
// when the link is opened (unknown or malformed = dropped, never a default invented).
const CARTE_KMS = [10, 25, 50, 100, 200];
const MA_VILLE = "Ma ville : ";
function carteShareLink(F, sel) {
  const qs = new URLSearchParams();
  if (F.q) qs.set("q", F.q);
  const lt = F.lieuTxt || "";
  if ((F.lieu || F.autour) && lt && !lt.startsWith(MA_VILLE)) { qs.set("lieu", lt); if (F.autour) qs.set("km", String(F.autour.km)); }
  sel.d.forEach((d) => { qs.append("d", d); (sel.m[d] || []).forEach((m) => qs.append("m", `${d}::${m}`)); });
  for (const [gr] of carteGroups()) {
    if (JSON.stringify(F[gr] || []) !== JSON.stringify(CARTE_DEFAULT[gr] || [])) qs.set(`f_${gr}`, (F[gr] || []).join(","));
  }
  return `#/recherche/${encodeURIComponent(qs.toString())}`;
}
// the shared parameters, checked: words and place cut to their fields' sizes, the radius one of the offered values, types and
// mentions through carteSelection (published labels only), each group's options among its own keys
function carteShareRead(raw, FAC) {
  let qs;
  try { qs = new URLSearchParams(String(raw || "")); } catch (_) { return null; }
  const lieuTxt = (qs.get("lieu") || "").slice(0, 120);
  // no prototype: a type named "__proto__", "constructor" or "toString" is an ordinary unknown key, dropped by carteSelection (Codex)
  const m = Object.create(null);
  qs.getAll("m").forEach((x) => { const i = x.indexOf("::"); if (i > 0) { const d = x.slice(0, i); (m[d] = Array.isArray(m[d]) ? m[d] : []).push(x.slice(i + 2)); } });
  const F = {};
  for (const [gr, , opts] of carteGroups()) {
    if (!qs.has(`f_${gr}`)) continue;
    const keys = opts.map(([k]) => k);
    F[gr] = [...new Set(qs.get(`f_${gr}`).split(",").filter((k) => keys.includes(k)))];
  }
  return { q: (qs.get("q") || "").trim().slice(0, 200), lieuTxt: lieuTxt.startsWith(MA_VILLE) ? "" : lieuTxt,
    km: CARTE_KMS.includes(Number(qs.get("km"))) ? Number(qs.get("km")) : 25, sel: carteSelection(FAC, "", "", { d: qs.getAll("d"), m }), F };
}
const carteInLieu = (f, L) => !L || (L.t === "region" ? f.region === L.v : L.t === "dep" ? f.dep === L.v : L.t === "acad" ? f.academie === L.v : true);
// an apprenticeship offer is not in the search engine's index (no SIES statistics): it is kept when its own name has every word
const kwWords = (q) => foldText(q).split(/[^a-z0-9]+/).filter((w) => w.length > 1);
// R3 (owner, 2026-11-12): the search's capacity, complementary phase and official-rate bands, the same limits (META.filtres)
const CARTE_R3 = ["capacite", "complementaire", "taux"];
// owner, 2026-11-16: the académie list of the two earlier search pages stays a filter of its own (the place field reads it too)
const CARTE_ACADS = [];                    // filled from the layer by the search page
// owner, 2026-11-22: the robustesse 2035 is READ as one of five levels among the Parcoursup formations (the best 10 %, the next
// 20 %, the 40 % in the middle, then 20 % and 10 %), never as a score: when the three scenarios disagree, the levels between them
// are all said (« entre … et … ») and marked on the gauge. The score and the filière repère stay in « Détail du calcul ».
const ECHELLE = [
  ["tres_robuste", "Très robuste", "parmi les 10 % de formations les plus robustes"],
  ["robuste", "Robuste", "parmi les 20 % de formations suivantes"],
  ["moyenne", "Dans la moyenne", "parmi les 40 % de formations du milieu"],
  ["plus_exposee", "Plus exposée", "parmi les 20 % de formations plus exposées aux changements"],
  ["tres_exposee", "Très exposée", "parmi les 10 % de formations les plus exposées aux changements"],
];
const echIdx = (k) => ECHELLE.findIndex((e) => e[0] === k);
// the levels of a formation as [first, last] indices (best first), or null for none / an unknown key
function echelleSpan(niv) {
  const ix = (Array.isArray(niv) ? niv : []).map(echIdx);
  if (!ix.length || ix.some((i) => i < 0)) return null;
  return [Math.min(...ix), Math.max(...ix)];
}
function echelleWords(niv) {
  const sp = echelleSpan(niv);
  if (!sp) return "";
  return sp[0] === sp[1] ? ECHELLE[sp[0]][1] : `Entre « ${ECHELLE[sp[0]][1].toLowerCase()} » et « ${ECHELLE[sp[1]][1].toLowerCase()} »`;
}
function echelleNote(niv) {
  const sp = echelleSpan(niv);
  return !sp ? "" : sp[0] === sp[1] ? ECHELLE[sp[0]][2] : "selon le scénario retenu";
}
// five cells from « très exposée » (left) to « très robuste » (right), the formation's levels filled; its name is ALWAYS written
// beside it (the gauge alone never carries the meaning)
function echelleJauge(niv) {
  const sp = echelleSpan(niv);
  if (!sp) return "";
  const cells = [4, 3, 2, 1, 0].map((i) => `<i class="ech-c${i >= sp[0] && i <= sp[1] ? " on" : ""}"></i>`).join("");
  // the five cells never split across lines (a narrow tile wraps the two words around them, never the gauge: 2026-11-23)
  return `<span class="ech" aria-hidden="true"><span class="ech-end">exposée</span><span class="ech-cells">${cells}</span><span class="ech-end">robuste</span></span>`;
}
// owner, 2026-11-18: the robustesse 2035 repères of each formation (the two the formation page shows, read from the lists'
// payload /api/reconnaissance: no request of its own, nothing sent); "sans" = no repère (not ranked, or no estimate). A FILTER only:
// the list is never sorted by a repère, and a repère is never merged with the zone
// owner, 2026-11-27: the filter « Robustesse 2035 dans sa filière » is gone from the page (the repère stays in the payload and in
// « Détail du calcul »): only the five levels the pages show (a formation between two levels carries both)
const CARTE_ROB = [
  ["robn", "Robustesse 2035", [...ECHELLE.map(([k, lab]) => [k, lab]), ["sans", "Pas de niveau"]]],
];
// the repères are usable only when the payload carried at least one level (robDecode's `ok`): never filter on an empty payload
const robReady = () => !!(RECO && RECO.rob && RECO.rob.ok);
const robLevel = (cod, k) => (k === "robn" ? ((RECO && RECO.rob && RECO.rob.echelle[cod]) || ["sans"])
  : (RECO && RECO.rob && RECO.rob.filiere[cod]) || "sans");
// owner, 2026-11-27: « Ce que regarde le jury ». The five fields of the fiche's evaluation grid (jury.CHAMPS, same order as the
// layer's `jury` weights), each with three levels whose cut points are MEASURED on the fiches' grids (META.jury, jury.cuts: never
// typed here). Published weights only: a filter, never a sort, a score or a chance
const JURY_KEYS = ["res", "eng", "mot", "se", "met"];
const JURY_LEVELS = [["peu", "Peu", 1], ["moyen", "Moyen", 2], ["beaucoup", "Beaucoup", 3]];
const JURY_HELP = "Le poids que le jury de la formation donne à chaque critère, publié sur sa fiche Parcoursup (la fiche fait foi). Les niveaux comparent ce poids à celui des autres formations : ni une note, ni une chance.";
const juryMeta = () => ((typeof META !== "undefined" && META && META.jury && META.jury.champs) || []);
// the level of a published weight: lower limit included, upper limit excluded (twin of jury.level)
const juryLevel = (v, c) => (v === null || v === undefined || !Array.isArray(c) ? null : v < c[0] ? "peu" : v < c[1] ? "moyen" : "beaucoup");
const juryGroups = () => juryMeta().filter((c) => JURY_KEYS.includes(c.key))
  .map((c) => [`jury_${c.key}`, `Jury : ${c.titre}`, JURY_LEVELS.map(([o, w]) => [o, `${w} : ${c.labels[o]}`])]);
const juryCuts = (g) => { const c = juryMeta().find((x) => `jury_${x.key}` === g); return c ? c.cuts : null; };
const carteGroups = () => [CARTE_GROUPS[0], ["acad", "Académie", CARTE_ACADS.map((a) => [a, acadLabel(a)])], ...CARTE_GROUPS.slice(1),
  ...CARTE_R3.map((g) => [g, FI_TITLE[g], fiOptions(g).map((o) => [o.key, o.label])]), ...CARTE_ROB, ...juryGroups()];
// does a formation carry an option of a group (one pure function, re-derived by red team C3)
function carteHas(f, g, o) {
  if (g === "statut") return f.statut === o;
  if (g === "acad") return f.academie === o;
  if (g === "app") return o === "oui" ? !!f.apprentissage : !!f.initiale;   // a formation offering both has both labels
  if (g === "internat") return f.internat === o;
  if (g === "amenag") return o === "presentiel" ? (!f.distance || f.distance === "aucune") : o === "sport" ? !!f.amenag_sport : o === "art" ? !!f.amenag_art : f.distance === o;
  if (g === "select") return f.select_form === (o === "oui" ? "formation sélective" : "formation non sélective");   // unknown: neither
  if (g === "zones") return carteZone(f) === o;
  if (g === "capacite") return filtreBand(f.capa_fin, fiOptions("capacite")) === o;
  if (g === "taux") return filtreBand(f.taux_acces_ens, fiOptions("taux")) === o;
  if (g.startsWith("jury_")) return Array.isArray(f.jury) && juryLevel(f.jury[JURY_KEYS.indexOf(g.slice(5))], juryCuts(g)) === o;   // no grid: no level
  if (g === "robn") return !robReady() || robLevel(f.cod_aff_form, g).includes(o);   // a formation between two levels: both
  if (g === "complementaire") return f.acc_pc !== null && f.acc_pc !== undefined && (o === "oui" ? f.acc_pc > 0 : f.acc_pc === 0);   // unknown: neither
  return false;
}
// every filter in one pure function; `skip` leaves one group out (the counts shown next to its options)
const CARTE_FGROUPS = ["statut", "acad", "app", "internat", "amenag", "select", "zones", ...CARTE_R3, "robn", ...JURY_KEYS.map((k) => `jury_${k}`)];
// owner, 2026-11-27: the formations a ticked jury level leaves out only because their fiche publishes no verified grid (said)
function carteNoGrid(rows, F, kw) {
  const jg = JURY_KEYS.map((k) => `jury_${k}`).filter((g) => (F[g] || []).length);
  if (!jg.length) return 0;
  const G = { ...F };
  jg.forEach((g) => { G[g] = []; });
  return carteFilter(rows, G, undefined, kw).filter((f) => !Array.isArray(f.jury)).length;
}
// sprint Vitesse (owner, 2026-11-16): an apprenticeship offer's folded name is computed once per name, not at every count
const carteFolded = new Map();
function carteText(f) {
  const raw = `${f.etablissement} ${f.formation} ${f.ville}`, x = carteFolded.get(f.cod_aff_form);
  if (x && x[0] === raw) return x[1];
  const t = foldText(raw).replace(/[^a-z0-9]+/g, " ");   // punctuation as the engine folds it (« l'internet » -> « l internet »)
  carteFolded.set(f.cod_aff_form, [raw, t]);
  return t;
}
// audit PR 4 (2026-11-24): an apprenticeship offer listed apart is matched on its name: every word of the keyword (kw.terms, from
// the engine: the typed word, or for an acronym « MCO » its label « management commercial operationnel ») must be in it; a keyword
// that only named apprenticeship keeps every offer. An acronym's alternatives come padded (« sio » is a whole word, never inside
// « profession »); a free word matches anywhere, as before
const carteOfferMatch = (f, kw) => kw.terms.length ? kw.terms.every((alts) => alts.some((a) => ` ${carteText(f)} `.includes(a))) : kw.app;
// Codex (PR #111): the internat values the engine's « internat » option keeps (search.OPTIONS), applied by the page to every row
const KW_INTERNAT = ["mixte", "filles", "garcons", "oui"];
// what every group shares: the place, the keyword and the radius
const carteCommon = (f, F, kw) => carteInLieu(f, F.lieu)
  && (!kw || kw.codes.has(f.cod_aff_form) || (f.stats === false && carteOfferMatch(f, kw)))
  && (!kw || !kw.app || !!f.apprentissage)
  && (!kw || !kw.internat || KW_INTERNAT.includes(f.internat))
  && (!F.autour || (f.lat != null && haversineKm(F.autour.lat, F.autour.lon, f.lat, f.lon) <= F.autour.km));
// audit PR 4: the paid private formations the other criteria keep, hidden only because their box is unticked (none when the
// statut group is empty, which shows everything, or already has the box)
function carteHiddenPaid(rows, F, kw) {
  if (!(F.statut || []).length || F.statut.includes("prive")) return 0;
  return carteFilter(rows.filter((f) => f.statut === "prive"), { ...F, statut: [] }, undefined, kw).length;
}
// the filter groups (and the zone filter) that differ from their default, by their titles
function carteActive(F) {
  const out = carteGroups().filter(([gr]) => JSON.stringify(F[gr] || []) !== JSON.stringify(CARTE_DEFAULT[gr] || [])).map(([, title]) => title);
  return (F.zones || []).length ? ["Votre zone", ...out] : out;
}
const carteRestored = (F) => carteActive(F);
function carteFilter(rows, F, skip, kw) {
  const groups = CARTE_FGROUPS.filter((g) => g !== skip && (F[g] || []).length);
  return rows.filter((f) => groups.every((g) => F[g].some((o) => carteHas(f, g, o))) && carteCommon(f, F, kw));
}
// sprint Vitesse: every option's count in ONE pass, equal to carteFilter(rows, F, g, kw) counted option by option (red team VT9):
// a formation every ticked group keeps counts in every group; one that a single group leaves out counts in that group only
function carteFacets(rows, F, kw, opts) {
  const n = {}, active = CARTE_FGROUPS.filter((g) => (F[g] || []).length);
  Object.keys(opts).forEach((g) => { n[g] = new Map(opts[g].map((o) => [o, 0])); });
  for (const f of rows) {
    let miss = null, k = 0;
    for (const g of active) if (!F[g].some((o) => carteHas(f, g, o))) { miss = g; if (++k > 1) break; }
    if (k > 1 || !carteCommon(f, F, kw)) continue;
    for (const g in opts) {
      if (k === 1 && g !== miss) continue;
      const m = n[g];
      for (const o of opts[g]) if (carteHas(f, g, o)) m.set(o, m.get(o) + 1);
    }
  }
  return n;
}
// one formation: its zone's colour AND shape, its name and zone in the label (an SVG icon, so it scales with the page)
function carteMarker(f) {
  const z = carteZone(f), col = carteColor(z);
  const shape = z === "autre" ? zoneShape(z, 9, 9, 5.8, `fill="var(--surface)" stroke="${col}" stroke-width="2.5"`)     // a ring, never a disc (review)
    : zoneShape(z, 9, 9, z === "ambitieux" ? 7.2 : 6.8, `fill="${col}" stroke="var(--surface)" stroke-width="1.5"`);
  return `<svg viewBox="0 0 18 18" width="18" height="18" role="img" aria-label="${esc(f.etablissement)}, ${esc(carteLabel(z))}${f.apprentissage ? ", en apprentissage" : ""}">${shape}</svg>`;
}
// points closer than a cell on screen are drawn as one group: a ring split by zone, with its count
function carteClusters(pts, cell) {
  const grid = new Map();
  for (const p of pts) {
    const k = `${Math.floor(p.x / cell)}:${Math.floor(p.y / cell)}`;
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k).push(p);
  }
  return [...grid.values()];
}
function carteRing(group) {
  const n = group.length, r = 13 + Math.min(9, 3 * Math.log10(n)), size = 2 * r + 8, c = 2 * Math.PI * r, o = size / 2;
  const counts = {}; group.forEach((p) => { const z = carteZone(p.f); counts[z] = (counts[z] || 0) + 1; });
  let off = 0;
  const arcs = [...CARTE_ZONES, "autre"].filter((z) => counts[z]).map((z) => {
    const len = c * counts[z] / n;
    const a = `<circle cx="${o}" cy="${o}" r="${r}" fill="none" stroke="${carteColor(z)}" stroke-width="6" stroke-dasharray="${len} ${c - len}" stroke-dashoffset="${-off}" transform="rotate(-90 ${o} ${o})"/>`;
    off += len; return a;
  }).join("");
  const label = Object.entries(counts).map(([z, k]) => `${k} ${z === "autre" ? "autres" : ZONES[z].label.replace(/^Vœu /, "")}`).join(", ");
  return { size, html: `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="${n} formations : ${esc(label)}. Zoomer"><circle cx="${o}" cy="${o}" r="${r}" fill="var(--surface)"/>${arcs}
    <text x="${o}" y="${o}" text-anchor="middle" dominant-baseline="central" font-size="12" font-weight="700" fill="var(--ink)">${n}</text></svg>` };
}
// the mention when the formation's own label does not already say it (CPGE "ECG", BTS options...)
const carteMentionTail = (f) => (f.mention && !String(f.formation || "").toLowerCase().includes(String(f.mention).toLowerCase()) ? ` · ${esc(f.mention)}` : "");
// an apprenticeship offer listed by the Parcoursup cartographie: no statistics are published, so no zone, no rate, no vœu here
const CARTE_APP_NOTE = "Aucune statistique d'admission n'est publiée pour les formations en apprentissage : ni zone, ni taux d'accès. Il faut aussi trouver un employeur ; la formation est gratuite pour l'apprenti.";
// the two routes a formation offers (owner, 2026-11-09): both labels when initial training and apprenticeship coexist
const voieBadges = (f) => (f.initiale && f.apprentissage ? '<span class="badge">formation initiale</span> <span class="badge">apprentissage</span>' : f.apprentissage ? '<span class="badge">en apprentissage</span>' : "");
const carteFiche = (f) => (f.fiche && /^https:\/\/dossierappel\.parcoursup\.fr\//.test(f.fiche) ? f.fiche : null);
// owner, 2026-11-21: the parcours a BUT apprenticeship offer opens, as the cartographie lists them (often only some of the
// IUT's parcours); each name quoted, since a parcours name may hold a comma
const appParcours = (o) => (o && Array.isArray(o.parcours) && o.parcours.length
  ? `parcours ${o.parcours.map((x) => `« ${esc(x)} »`).join(", ")}` : "");
// the apprenticeship offers attached to an initial formation (same establishment, same diploma): the CFA and its page
function appOffers(list) {
  if (!list || !list.length) return "";
  return `<div class="small"><strong>Aussi en apprentissage</strong> <span class="muted">(pas de statistiques d'admission publiées pour cette voie)</span><ul class="offer-list">${list.map((o) => { const url = carteFiche(o);
    return `<li>${esc(o.etablissement)}${o.ville ? ` · ${esc(o.ville)}` : ""}${appParcours(o) ? ` · ${appParcours(o)}` : ""}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">fiche Parcoursup ↗</a>` : ""}${/^\d{1,9}$/.test(o.cod_aff_form || "") ? ` ${appVoeuButton(o.cod_aff_form)}` : ""}</li>`; }).join("")}</ul></div>`;
}
// R9 (owner, 2026-11-12): three figures per formation, always in the same place: the OFFICIAL access rate; the figure for the
// student's doublette (or bac techno / pro line), the one Mes vœux and the formation page show (voeux.figures, read per page of
// the list); where the student's average or mention stands among the formation's nouveau bachelier admits, a RANGE read here from
// the published counts (journey.stage2's `lec`), never an access rate or a chance: SIES publishes no access rate by mention.
// PR 2 of the audit (2026-11-23): « admis avec votre mention ou moins » has ONE meaning on every page (search card, Mes vœux,
// Où je me situe): the reading the zone uses with no average (the band's top, w = 1): the series' exact bounds when the formation
// publishes enough for them (journey.series_cdf_bounds), else the all-bacs share. Twin of the server's planb._view.
function mentionShareOf(L) {
  if (!L || !L.n) return null;
  const cdf = L.kt / L.n, sp = seriesPos(L.s, 1, cdf);
  return sp ? { lo: sp.bounds[0], hi: sp.bounds[1], serie: true } : { lo: cdf, hi: cdf, serie: false };
}
const mentionShareTxt = (lo, hi) => (hi - lo < 0.005 ? pc1(lo) : `${pc1(lo)} – ${pc1(hi)}`);
// who the share counts: the student's own bac when the bounds are read, else every bac
const mentionWho = (serieRead, serie) => (serieRead ? `${{ bg: "bacs généraux", bt: "bacs technos", bp: "bacs pros" }[serie || "bg"]} admis` : "tous bacs");
function cartePosition(L, taux, band, g) {
  if (!L || !L.n) return null;
  if (g !== null && g !== undefined) {
    const p = lire(L, taux, band, g).position;
    return p ? { lo: Math.min(p.normale, p.uniforme), hi: Math.max(p.normale, p.uniforme), moyenne: true } : null;
  }
  const m = mentionShareOf(L);
  return m && { ...m, moyenne: false };
}
function cartePosFigure(pos, compact, serie) {
  if (!pos) return '<span class="muted small">non publié</span>';
  if (pos.moyenne) return `${mentionShareTxt(pos.lo, pos.hi)}${estimTag(compact ? "" : "des admis nouveaux bacheliers avaient une moyenne plus basse que la vôtre", true)}`;
  return `${mentionShareTxt(pos.lo, pos.hi)} <span class="muted small">(${mentionWho(pos.serie, serie)})</span>`;
}
// ctx: { ok, prof, serie, chiffres: Map(code -> voeux.figures answer, or null while it loads), lec: {code: lec}, band, g, session }
// R10 (owner, 2026-11-13): the card reads like Parcoursup's, compact: statut, selectivity and zone first; the access rate of
// each bac route (the formation's report, else the site's estimation, said); the most represented line among the admits;
// the two figures for the profile; then the actions (vœu, comparateur, fiche).
const STATUT_LABEL = { public: "Public", contrat: "Privé sous contrat", prive: "Privé hors contrat (payant)", prive_app: "Privé, en apprentissage" };
// PR 2 of the audit (2026-11-23): ONE rendering of « taux d'accès de ce bac » (carte.bac_lines: the formation's own report, else
// the site's estimation starred, a masked table « non publié »), shared by the search card and the formation page
function bacAccesHtml(x) {
  x = x || {};
  const v = x.masque ? '<span class="muted">non publié</span>' : x.taux === null || x.taux === undefined ? '<span class="muted">—</span>'
    : `${pct1(x.taux)}${x.source === "estimation" ? '<sup class="est" aria-hidden="true">*</sup>' : ""}${x.fragile ? ' <span class="muted small">(peu de candidats)</span>' : ""}`;
  const sr = x.source === "estimation" && !x.masque && x.taux !== null && x.taux !== undefined ? '<span class="sr-only"> (estimation)</span>' : "";
  return `<strong>${v}</strong>${sr}`;
}
function carteBacs(f) {
  // sprint Q3: a formation's rates per bac arrive with the cards' answer, just after the list (never shown as missing)
  if (f.bacs === undefined && f.stats !== false) return '<p class="cbacs-wait small muted">Taux d\'accès par bac : chargement…</p>';
  if (!f.bacs) return "";
  const cell = (b) => `<li class="cb cb-${b}"><span class="cb-k">${{ bg: "Bac général", bt: "Bac techno", bp: "Bac pro" }[b]}</span> ${bacAccesHtml(f.bacs[b])}</li>`;
  return `<ul class="cbacs" aria-label="Taux d'accès par bac">${["bg", "bt", "bp"].map(cell).join("")}</ul>`;
}
// lot 1, PR 11: a result card fits one phone screen: the rates per bac route and the most represented line among the admits
// are folded under one summary (the profile's own figures and the official rate stay in sight), never removed
function carteJump(n) {
  const st = document.getElementById("sr-status");
  if (st) st.textContent = `Résultats : ${fmt(n)} formation${n > 1 ? "s" : ""} correspondant à vos critères`;
  const el = document.getElementById("carte-count");
  if (el && narrow()) el.scrollIntoView({ block: "start" });
}
// lot 1, PR 13 (Léa read « Mot compris : licence » as « only licence was understood »): every typed word the search used is
// said, the recognised ones (acronyms, places, corrections) first, then « Mots cherchés » for the plain words; with a keyword
// around a town, the order is said in words
function kwChips(kw, autour) {
  const seen = new Set(kw.interp.map((i) => foldText(i.value)));
  const plain = (kw.terms || []).filter((g) => g.length === 1 && !g[0].startsWith(" ")).map((g) => g[0]).filter((w) => ![...seen].some((v) => v.split(" ").includes(w)));
  const chips = [...kw.interp.map((i) => `<span class="badge">${esc(INTERP_LABEL[i.type] || i.type)} : ${esc(i.value)}</span>`),
    plain.length ? `<span class="badge">Mots cherchés : ${esc(plain.map((w) => String(kw.q || "").split(/\s+/).find((t) => foldText(t).replace(/[^a-z0-9]/g, "") === w) || w).join(", "))}</span>` : ""].join("");
  const ordre = autour ? '<span class="small muted">Les formations dont le nom contient le plus de vos mots d\'abord, puis les plus proches.</span>' : "";
  return chips || ordre ? `<div class="toolbar"><span class="small muted">Recherche comprise :</span>${chips}${ordre}</div>` : "";
}
// owner, 2026-11-27: the weights the jury gives to the five fields, as the fiche publishes them (never a score)
function carteJury(f) {
  if (!Array.isArray(f.jury)) return "";
  const names = juryMeta().length ? Object.fromEntries(juryMeta().map((c) => [c.key, c.titre])) : {};
  const parts = JURY_KEYS.map((k, i) => `${esc(names[k] || k)} ${fmt(f.jury[i])} %`).filter((x, i) => names[JURY_KEYS[i]]);
  return parts.length ? `<p class="cjury small"><span class="muted">Ce que regarde le jury (fiche Parcoursup, la fiche fait foi) :</span> ${parts.join(" · ")}</p>` : "";
}
// Codex (PR #125): an apprenticeship offer listed apart is kept or left out by the jury filter too: its card shows the same
// published weights, folded alone (never the admission figures such an offer does not have)
const carteJuryMore = (f) => (carteJury(f) ? `<details class="cc-more"><summary class="small">Ce que regarde le jury</summary>${carteJury(f)}</details>` : "");
function carteMore(f, reo) {
  const app = appOffers(f.offres_app), jury = carteJury(f);
  const inner = `${reo ? "" : `${carteBacs(f)}${carteMajo(f)}`}${jury}${app}`;
  const what = [reo ? "" : "Taux d'accès par bac et profil des admis", jury ? (reo ? "Ce que regarde le jury" : "ce que regarde le jury") : "", app ? (reo && !jury ? "Aussi en apprentissage" : "aussi en apprentissage") : ""].filter(Boolean).join(" · ");
  return inner ? `<details class="cc-more"><summary class="small">${what}</summary>${inner}</details>` : "";
}
function carteMajo(f) {
  const m = f.majo;
  if (!m) return "";
  return `<p class="cmajo small"><span class="muted">Le plus représenté chez les admis :</span> <strong>${esc(rpLabel(m.libelle))}</strong> <span class="muted">(${esc({ bg: "bac général", bt: "bac techno", bp: "bac pro" }[m.bac] || "")}${m.exaequo ? ", ex æquo" : ""})</span></p>`;
}
// audit PR 6 (2026-11-24): outside terminale the card shows the estimated access outside terminale (reorientation.latest, the
// same block and the same cell as « Je me réoriente » and Mes vœux), never the rates per bac nor « Indiquez votre profil »
function carteReo(f) {
  if (f.reo === undefined) return '<p class="cbacs-wait small muted">Accès estimé hors terminale : chargement…</p>';
  if (f.reo === false) return '<p class="small muted">Accès estimé hors terminale : indisponible pour le moment. Rechargez la page plus tard.</p>';
  return `<div class="cfigs"><div class="cf cf-reo"><span class="cf-k">Accès estimé hors terminale</span><span class="cf-v">${reoCell(f.reo && { ...f.reo, taux_acces_ens: f.taux_acces_ens })}</span></div></div>`;
}
function carteFigures(f, ctx) {
  if (f.stats === false) return "";
  if (ctx.reo) return carteReo(f);
  if (!ctx.ok) return `<p class="small muted"><a href="#/profil">Indiquez votre profil</a> : votre zone, le chiffre de vos deux spécialités et votre moyenne parmi les admis.</p>`;
  const ch = ctx.chiffres.get(f.cod_aff_form);
  // bac techno / pro: the student's line is picked HERE (pickVoie): the series or specialty is sent only to /api/voeux
  const pv = ch && ch.voies ? pickVoie(ch.voies, ctx.serie, ctx.prof.voie || null) : null;
  const second = ch === undefined || ch === null ? '<span class="muted">…</span>'
    : ctx.serie === "bg" ? dblFigure(ch) : voieFigure(pv ? { ...pv, session: ch.voies.session, recoupe: ch.voies.recoupe } : null, ctx.prof);
  const pos = cartePosition((ctx.lec || {})[f.cod_aff_form], f.taux_acces_ens, ctx.band, ctx.g);
  return `<div class="cfigs">
    <div class="cf" data-cfig="${esc(f.cod_aff_form)}"><span class="cf-k">${ctx.serie === "bg" ? "Vos deux spécialités" : "Votre bac dans le rapport"}</span><span class="cf-v">${second}</span></div>
    <div class="cf"><span class="cf-k">${ctx.g !== null && ctx.g !== undefined ? "Admis sous votre moyenne" : "Admis avec votre mention ou moins"}</span><span class="cf-v">${cartePosFigure(pos, ctx.compact, ctx.serie)}</span></div></div>`;
}
function compareButton(cod) {
  const inB = basket.get().includes(cod), full = !inB && basket.get().length >= 6;
  return `<button type="button" class="btn-sec" data-cmp="${esc(cod)}" ${full ? 'disabled title="6 formations au plus dans le comparateur"' : ""} aria-pressed="${inB}">${inB ? "Retirer du comparateur" : full ? "Comparateur plein" : "Comparer"}</button>`;
}
function carteCard(f, ctx, pinned) {
  const z = carteZone(f), zc = ctx.ok && z !== "autre" ? ZONES[z].color : null;
  const url = f.stats === false ? carteFiche(f) : null;
  const title = f.stats === false ? (url ? `<a class="rc-title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(f.etablissement)} ↗</a>` : `<span class="rc-title">${esc(f.etablissement)}</span>`)
    : `<a class="rc-title" href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a>`;
  const sel = f.select_form === "formation sélective" ? '<span class="badge sel">Sélective</span>' : f.select_form === "formation non sélective" ? '<span class="badge">Non sélective</span>' : "";
  return `<div class="result rc carte-rc${zc ? " rc-z" : ""}${pinned ? " carte-pinned" : ""}"${zc ? ` style="--zc:${zc}"` : ""} role="listitem" data-pick="${esc(f.cod_aff_form)}" data-rdip="${esc(f.diplome || "")}" data-groupe="${esc(f.groupe || "")}"${carteUI.sel === f.cod_aff_form ? ' aria-current="true"' : ""}>
    <div class="rc-badges"><span class="badge statut st-${esc(f.statut || "")}">${esc(STATUT_LABEL[f.statut] || f.contrat_etab || "")}</span>${sel}${f.stats === false ? "" : recoBadge(f.cod_aff_form) + tensionBadge(f.cod_aff_form) + absBadge(f.cod_aff_form)}${f.stats === false ? '<span class="badge">en apprentissage</span>' : `${ctx.ok ? (z === "autre" ? carteZoneBadge(null, CARTE_OTHER.label) : zoneBadge(z, false, f.large)) : ""}${voieBadges(f)}${autresBadge(f)}`}${f.lat == null ? '<span class="badge">non localisée</span>' : ""}</div>
    <div class="rc-main">${title}
      <div class="rc-sub">${esc(f.formation)}${carteMentionTail(f)}</div>${f.stats === false && appParcours(f) ? `<div class="small">En apprentissage : ${appParcours(f)}</div>` : ""}
      <div class="rc-meta muted small"><span>${esc(f.ville)}${f.academie ? ` (${esc(acadLabel(f.academie))})` : ""}</span>${f.dist != null ? `<span>${fmt(f.dist)} km</span>` : ""}${f.capa_fin != null ? `<span>${ICONS.places}${fmt(f.capa_fin)} places</span>` : ""}</div>
    </div>
    ${f.stats === false ? `<p class="small muted">Pas de statistiques d'admission publiées pour l'apprentissage <button type="button" class="tip" aria-label="${esc(CARTE_APP_NOTE)}" data-tip="${esc(CARTE_APP_NOTE)}">i</button></p>${robCardLine(f.cod_aff_form)}${carteJuryMore(f)}` : `<div class="crates"><div class="cofficiel"><span class="cf-k">Taux d'accès ${esc(ctx.session)}</span> <strong class="cf-big">${pct(f.taux_acces_ens)}</strong> <span class="muted small">officiel</span></div></div>
    ${carteMore(f, ctx.reo)}
    ${carteFigures(f, { ...ctx, compact: true })}
    ${robCardLine(f.cod_aff_form)}`}
    <div class="toolbar ctools">${f.stats === false ? appVoeuButton(f.cod_aff_form) : `${voeuButton(f.cod_aff_form)}${compareButton(f.cod_aff_form)}<a href="#/f/${esc(f.cod_aff_form)}">Fiche →</a>`}${pinned ? '<button type="button" class="btn-sec" data-unpin>Fermer</button>' : ""}</div>
  </div>`;
}
// the two robustesse repères on a result card, in words, apart from the zone and the rates (never one mark); nothing when unknown
function robCardLine(cod) {
  const R = RECO && RECO.rob;
  const w = R && R.echelle && echelleWords(R.echelle[cod]);                         // owner, 2026-11-22: the level, a known one only
  if (!w) return "";
  // owner, 2026-11-20: an apprenticeship offer SIES does not publish carries the repères of its DIPLOMA (the same for every
  // formation of that diploma), said in words; never a figure of the establishment
  const dip = R.herite && R.herite[cod] ? " Repères du diplôme : les mêmes pour toutes les formations qui y préparent."
    : R.voisine && R.voisine[cod] ? " Repère emprunté à la formation voisine, à laquelle celle-ci mène directement."
    // owner, 2026-11-20: an offer read through the RNCP certification of the same title says so (a less sure link)
    : R.certification && R.certification[cod] ? " Métiers lus par les codes de la certification du même intitulé (France Compétences) : lien moins sûr." : "";
  return `<p class="small rc-rob">Robustesse 2035 des métiers visés ${estimTag("", false, true)} : <strong>${esc(w)}</strong> ${echelleJauge(R.echelle[cod])}${dip ? `<br>${esc(dip.trim())}` : ""}</p>`;
}
// audit PR 8: an element of the search page is written again only when its content changes (each rewrite of an unchanged
// line made a new « largest paint » seconds later, and the browser laid it out again for nothing)
function setHtml(el, html) {
  if (!el || el.__html === html) return;
  el.__html = html;
  el.innerHTML = html;
}
function carteList(rows, ctx, empty) {
  const PAGE = cartePage(), start = carteUI.page * PAGE, part = rows.slice(start, start + PAGE);
  return `<div class="carte-list" role="list">${part.map((f) => carteCard(f, ctx, false)).join("") || `<p class="muted small">${esc(empty || "Aucune formation ne correspond à ces filtres dans cette partie de la carte.")}</p>`}</div>
    <div class="toolbar">${carteUI.page ? `<button type="button" data-cpage="-1">← Précédentes</button>` : ""}${rows.length > start + PAGE ? `<button type="button" data-cpage="1">Suivantes (${fmt(start + PAGE + 1)}–${fmt(Math.min(rows.length, start + 2 * PAGE))}) →</button>` : ""}</div>`;
}
// R9/R10: several types of diploma and mention groups at once. sel = { d: [diploma, ...], m: { diploma: [group, ...] } };
// an EMPTY list keeps everything (owner, 2026-11-13: unticking every diploma shows every formation, as on Parcoursup).
// Only known labels are kept: a stored value is never trusted.
function carteSelection(FAC, dArg, mArg, stored) {
  const known = (d) => FAC.diplomes.find((x) => x.label === d);
  if (dArg && known(dArg)) {
    const g = known(dArg).mentions.find((x) => x.label === mArg || (x.variantes || []).includes(mArg));
    return { d: [dArg], m: { [dArg]: g ? [g.label] : [] } };
  }
  const d = [...new Set((stored && Array.isArray(stored.d) ? stored.d : []).filter((x) => typeof x === "string" && known(x)))];
  const m = {};
  for (const x of d) { const ok = known(x).mentions.map((g) => g.label); m[x] = [...new Set((((stored && stored.m) || {})[x] || []).filter((g) => ok.includes(g)))]; }
  return { d, m };
}
// the stored profile's académie, only when the layer knows it (a stored profile is never trusted), else "" (nothing sent)
function carteNear(acads) {
  const p = store.get("profile", null), a = p && typeof p === "object" && typeof p.academie === "string" ? p.academie : "";
  return a && acads.includes(a) ? a : "";
}
const carteSortName = (f) => String(f.etablissement || "").replace(/^[^\p{L}\p{N}]+/u, "");
// sprint Vitesse: one collator for every French sort of the search page (the same order as localeCompare(…, "fr"))
const FR_COLL = new Intl.Collator("fr");
// the rank of every name in that order, computed once per layer: equal names (for the collator) share their rank, so sorting
// by rank gives exactly the collator's order (red team VT9)
function carteNameRank(C) {
  if (!C.nameRank) {
    const names = [...new Set(C.rows.map(carteSortName))].sort(FR_COLL.compare), r = new Map();
    let k = -1;
    names.forEach((n, i) => { if (i === 0 || FR_COLL.compare(names[i - 1], n) !== 0) k++; r.set(n, k); });
    C.nameRank = r;
  }
  return C.nameRank;
}
const foldText = (x) => String(x || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const carteHash = (sel) => (sel.d.length === 1 && (sel.m[sel.d[0]] || []).length <= 1
  ? `#/carte/${encodeURIComponent(sel.d[0])}${(sel.m[sel.d[0]] || []).length ? `/${encodeURIComponent(sel.m[sel.d[0]][0])}` : ""}` : "#/carte");
// owner, 2026-11-21: a double licence is listed under each of its two disciplines (carte.groupes_of: groupe + groupe2)
const carteGroupes = (f) => (f.groupe2 ? [f.groupe, f.groupe2] : [f.groupe]);
const carteKeep = (f, sel) => !sel.d.length || (sel.d.includes(f.diplome) && (!(sel.m[f.diplome] || []).length || carteGroupes(f).some((g) => sel.m[f.diplome].includes(g))));
// Leaflet (static/vendor/leaflet, BSD-2) is loaded by this page only, never by the page shell
// audit PR 4: loaded ONCE. Two openings of the page close together (leave and come back during a search) both saw no window.L and
// loaded Leaflet twice; the second copy did not recognise the first one's objects. A failed load may be tried again.
function carteLeaflet() {
  if (window.L) return Promise.resolve();
  const load = (tag, attrs) => new Promise((ok, ko) => { const el = document.createElement(tag); Object.assign(el, attrs); el.onload = ok; el.onerror = ko; document.head.appendChild(el); });
  carteUI.leafletP = carteUI.leafletP || Promise.all([load("link", { rel: "stylesheet", href: "/static/vendor/leaflet/leaflet.css" }),
    load("script", { src: "/static/vendor/leaflet/leaflet.js" })]).catch((e) => { carteUI.leafletP = null; throw e; });
  return carteUI.leafletP;
}
async function viewCarte(dArg, mArg) {
  // sprint Q3: the layer is asked at once, beside the types of diploma (it does not depend on them)
  carteUI.cache = carteUI.cache || new Map();
  const cached = (key, make) => {
    if (!carteUI.cache.has(key)) carteUI.cache.set(key, make().catch((e) => { carteUI.cache.delete(key); throw e; }));
    return carteUI.cache.get(key);
  };
  const loadCouche = () => cached("couche", () => api("/api/carte/couche").then(coucheDecode));
  loadCouche().catch(() => {});
  const recoP = recoLoad();                                          // V1: the State-label badges of the cards, beside the layer
  // R10: the page's heading and a loading line at once, BEFORE the first answer (a cold server takes ~3 s: the page must
  // never be without its heading meanwhile, WCAG 2.4.6; red team A4 on a fresh server)
  const fresh = $view.dataset.rendered !== "carte";                  // audit PR 4: entering the page (not a re-render of it)
  if ($view.dataset.rendered !== "carte") $view.innerHTML = `${explorerViews("carte")}<div class="card carte-head"><h1>Rechercher une formation</h1><p class="small muted" role="status">Chargement des formations…</p><p class="cs-wait">La liste rassemble toutes les formations de Parcoursup, avec la carte et les filtres. Sur un téléphone ou une connexion lente, il faut parfois quelques secondes.</p></div>`;
  document.title = "Rechercher une formation — SupCompass";       // the tab already names the page while it loads (R8 rule)
  const FAC = await api("/api/carte");
  // "#/carte/t/<type_key>" comes from Mon parcours: its most frequent type of diploma
  if (dArg === "t") { const d = FAC.types[mArg]; location.replace(`#/carte/${encodeURIComponent(d || "")}`); return; }
  // a shared search (#/recherche/...): its types and mentions now, its words, place and groups once the layer is read
  const shareRaw = carteUI.pendingShare;
  carteUI.pendingShare = null;
  const sel = shareRaw != null ? carteShareRead(shareRaw, FAC).sel : carteSelection(FAC, dArg, mArg, store.get("carteSel", null));
  store.set("carteSel", sel);
  const P = bacProfile();                                                // sprint 21: no zone outside terminale
  const serie = P && ["bg", "bt", "bp"].includes(P.serie) ? P.serie : "bg";
  // R5: the profile's own codes ("sm" was never a profile value: a sans-mention student got no zone on the map)
  const VP = P ? vxProfile(P) : null;
  const ok = P && (serie !== "bg" || (P.spe1 && P.spe2 && P.spe1 !== P.spe2)) && MENTION_CODES.includes(VP && VP.mention);
  const sq = !ok ? "" : serie === "bg" ? `spe1=${encodeURIComponent(P.spe1)}&spe2=${encodeURIComponent(P.spe2)}` : `serie=${encodeURIComponent(serie)}`;
  const { band, g } = ok ? lectureOf(P) : { band: null, g: null };
  const seq = (carteUI.seq = (carteUI.seq || 0) + 1);
  carteUI.chiffres = carteUI.sq === sq && carteUI.chiffres ? carteUI.chiffres : new Map();
  carteUI.sq = sq;
  // one answer per type of diploma (cacheable), the mention groups are kept in the browser; zones always with their reading
  // ingredients (`lec`): the page reads the zone with the average it keeps and the position among the admits
  // R10: the neutral layer first (list and map at once), the zones after: with every diploma the zones take the longest
  // sprint Q3: the whole layer in ONE compact answer (cached by the browser and the CDN), decoded once; the selected diplomas
  // are kept in the browser. Zones: one answer for every diploma when nothing is ticked, else one per ticked diploma
  // audit PR 8: decoded in slices between which the page answers (one 0.5 s task on a phone before), same result as
  // coucheDetails(C, coucheDecode(D)) (red team VT12)
  const loadDetails = (C) => cached("couche-details", () => api("/api/carte/couche?partie=details").then((D) => coucheDetailsParts(C, D)));
  const loadZ = (d) => (ok ? cached(`z|${d}|${sq}|${bandParam(VP)}`, () => api(`/api/carte/zones?diplome=${encodeURIComponent(d)}&${sq}&mention_bac=${encodeURIComponent(bandParam(VP))}&lecture=true`)).catch(() => null) : Promise.resolve(null));
  // R10: no diploma ticked = every diploma
  const tous = !sel.d.length;
  const dips = tous ? FAC.diplomes.map((d) => d.label) : sel.d;
  const coucheP = loadCouche();
  // sprint Vitesse: the zones are asked at once, beside the layer: the server's reading (seconds for a new profile) runs while
  // the layer downloads; the cards' details wait for the zones instead (below)
  const zonesP = Promise.all(tous ? [loadZ(CARTE_TOUS)] : dips.map(loadZ));
  let zonesEarly;                                 // audit PR 8: set as soon as the zones are here (read before the first draw if so)
  zonesP.then((zs) => { zonesEarly = zs; }, () => {});
  // sprint Vitesse: the badges are awaited with the layer (the cards need them), no longer before the page's heading
  const [C] = await Promise.all([coucheP, carteLeaflet().catch(() => null), recoP.catch(() => null), absLoad()]);
  if (!/^#\/carte(\/|$)/.test(location.hash) || seq !== carteUI.seq) return;        // the visitor left while the map loaded
  const lec = {};
  let zonesReady = false;
  const keep = new Set(dips);
  let rows = carteMerge(tous ? C.rows : C.rows.filter((f) => keep.has(f.diplome)), null, ok);
  let lastCards = null;                           // the list the cards were last drawn from (drawCards)
  // the zones, read with the average the page keeps, land on the same rows when they come (navigation race checked)
  const applyZones = (zs) => {
    const zone = {}, larges = new Set();
    zs.forEach((Zraw) => {
      if (!Zraw) return;
      const Z = carteZonesLocal(Zraw, VP);
      Object.assign(zone, Z.zones);
      (Z.larges || []).forEach((c) => larges.add(c));
      Object.entries(Zraw.lectures || {}).forEach(([c, x]) => { lec[c] = x.lec; });
    });
    rows.forEach((f) => { f.zone = ok ? (zone[f.cod_aff_form] || null) : null; f.large = ok && f.zone === "securite" && larges.has(f.cod_aff_form); });
    zonesReady = true;
    return zs.some(Boolean);
  };
  const session = C.session, offre = C.offre_apprentissage;
  const ctx = { ok, prof: P || {}, serie, chiffres: carteUI.chiffres, lec, band, g, session, reo: isReo(store.get("profile", null)) };
  CARTE_ACADS.splice(0, CARTE_ACADS.length, ...[...new Set(C.rows.map((f) => f.academie).filter(Boolean))].sort(FR_COLL.compare));
  const F = { ...CARTE_DEFAULT, ...(store.get("carteFiltres2", {}) || {}) };
  for (const [gr, , opts] of carteGroups()) F[gr] = Array.isArray(F[gr]) ? F[gr].filter((o) => opts.some(([k]) => k === o)) : [];
  F.zones = ok && Array.isArray(F.zones) ? F.zones.filter((z) => [...CARTE_ZONES, "autre"].includes(z)) : [];
  if (F.academie && !F.lieu) { F.lieu = { t: "acad", v: String(F.academie) }; F.lieuTxt = `Académie de ${F.academie}`; }
  delete F.academie;
  F.q = typeof F.q === "string" ? F.q.slice(0, 200) : "";
  // audit PR 4 (2026-11-24): filters kept from a previous visit are hidden in folded dropdowns (a zone filter kept gave 0 results):
  // on entering the page, the groups that differ from their default are named once, with a reset, until a filter is changed
  if (fresh) carteUI.restored = shareRaw != null ? [] : carteRestored(F);
  F.lieu = F.lieu && ["region", "dep", "acad"].includes(F.lieu.t) && typeof F.lieu.v === "string" ? { t: F.lieu.t, v: F.lieu.v } : null;
  F.autour = F.autour && Number.isFinite(F.autour.lat) && Number.isFinite(F.autour.lon) && Number.isFinite(F.autour.km) ? F.autour : null;
  F.lieuTxt = typeof F.lieuTxt === "string" ? F.lieuTxt.slice(0, 120) : (F.autour && F.autour.ville) || "";
  // an old "#/s/<words>" link: its words become the keyword, saved at once (a rebuild re-reads the stored filters: Codex)
  if (carteUI.pendingQ != null) { F.q = carteUI.pendingQ.slice(0, 200); F.lieu = null; F.autour = null; F.lieuTxt = ""; carteUI.pendingQ = null; store.set("carteFiltres2", F); }
  const share = shareRaw != null ? carteShareRead(shareRaw, FAC) : null;   // CARTE_ACADS is filled: the académies are checked too
  if (share) {
    for (const [gr] of carteGroups()) F[gr] = gr in share.F ? share.F[gr] : [...(CARTE_DEFAULT[gr] || [])];
    Object.assign(F, { zones: [], q: share.q, lieu: null, autour: null, lieuTxt: share.lieuTxt });
  }
  // the keyword's codes, in the engine's relevance order (one answer per keyword, kept for the visit; a failure keeps the list whole)
  // owner, 2026-11-16: the académie of the stored profile (one the layer knows) goes with the keyword: the engine puts its
  // formations first among EQUALLY relevant ones only. Never the place typed, a filter or « Je me réoriente »'s own académie.
  const near = carteNear(CARTE_ACADS);
  const kwQuery = (q) => { const qs = new URLSearchParams({ q }); if (near) qs.set("near", near); return qs; };
  const kwLoad = (q) => cached(`kw|${q}|${near}`, () => api(`/api/search/codes?${kwQuery(q)}`).then((d) => ({ q, codes: new Set(d.codes),
    rank: new Map(d.codes.map((c, i) => [c, i])), words: kwWords(q),
    // lot 1, PR 13: how many typed words each formation's names carry (api.words_matched); « tous vos mots » before the distance
    mots: new Map(Array.isArray(d.mots) && d.mots.length === d.codes.length ? d.codes.map((c, i) => [c, d.mots[i]]) : []),
    terms: Array.isArray(d.terms) ? d.terms : kwWords(q).map((w) => [w]), app: !!d.apprentissage, internat: !!d.internat, interp: d.interpretation || [], notes: d.notes || [] })));
  carteUI.kw = F.q ? await kwLoad(F.q).catch(() => null) : null;
  if (!/^#\/carte(\/|$)/.test(location.hash) || seq !== carteUI.seq) return;
  const reselect = () => { store.set("carteSel", sel); carteUI.sel = null; carteUI.page = 0; history.replaceState(null, "", carteHash(sel)); viewCarte("", ""); };
  const home = villeDepart(), lieux = carteLieux(C.rows, home);          // the place list: every formation, whatever the type ticked
  if (share) {                                     // the shared place, read in this browser like a typed one; unknown = said
    const L = share.lieuTxt ? carteLieu(lieux, share.lieuTxt) : null;
    if (L && L.t === "ville") F.autour = { lat: L.lat, lon: L.lon, km: share.km, ville: share.lieuTxt };
    else if (L) F.lieu = { t: L.t, v: L.v };
    carteUI.lieuBad = share.lieuTxt && !L ? share.lieuTxt : "";
    if (!L) F.lieuTxt = "";
    carteUI.fit = true;
    store.set("carteFiltres2", F);
  }
  $view.innerHTML = `${explorerViews("carte")}<div class="card carte-head"><h1>Rechercher une formation</h1>
    <form id="cs-form" class="cs-bar" role="search" aria-label="Rechercher une formation">
      <label class="cs-field cs-q"><span>Formation, établissement, mot-clé</span><input id="cs-q" type="search" autocomplete="off" value="${esc(F.q || "")}" placeholder="ex. BTS NDRC, IUT informatique, kiné"></label>
      <label class="cs-field cs-lieu"><span>Ville, département, région</span><input id="cs-lieu" type="search" list="cs-lieux" autocomplete="off" value="${esc(F.lieuTxt || "")}" placeholder="ex. Lyon, Nord (59), Bretagne"></label>
      <datalist id="cs-lieux"></datalist>
      <label class="cs-field cs-km"${F.autour ? "" : " hidden"}><span>Rayon</span><select id="cs-km">${[10, 25, 50, 100, 200].map((k) => `<option value="${k}" ${(F.autour ? F.autour.km : 25) === k ? "selected" : ""}>${k} km</option>`).join("")}</select></label>
      <button type="submit" class="cs-go">${ICONS.search}Rechercher</button>
    </form>
    <p class="small cs-help">${home ? `<button type="button" class="linkish" id="chome">Autour de ma ville : ${esc(villeLabel(home))}</button> · ` : '<a href="#/profil">Votre ville dans Mon profil</a> : chercher autour de chez vous. '}Le lieu reste dans votre navigateur.</p>
    <div id="cs-status" class="cs-status" role="status"></div>
    <details class="dd-fold" id="dd-fold"${!narrow() || carteUI.fold ? " open" : ""}><summary>${ICONS.filter}Filtrer <span id="dd-fold-n"></span></summary><div class="dd-bar" id="cfilters"></div></details>
    <p class="small">${!ok && isReo(store.get("profile", null)) ? `Les formations sont placées sans zone. ${REO_NO_ZONE} <a href="#/reorientation">Voir l'accès estimé hors terminale</a>.` : ok ? "Chaque formation est placée et colorée selon votre zone, calculée comme dans « Où je me situe » à partir des admis des campagnes passées : ce ne sont pas des chances d'admission." : `Les formations sont placées sans zone. <a href="#/profil">Indiquez votre bac, vos spécialités et votre mention</a> pour les colorer selon votre zone.`}</p></div>
  <div class="carte-layout carte-layout2">
    <section class="carte-results card" aria-labelledby="carte-h2"><h2 id="carte-h2">Formations trouvées</h2>
      <p class="muted small" id="carte-count"></p>
      <div id="carte-sel" aria-live="off"></div>
      <div id="carte-items"></div>
      <p class="muted small">Liste : les formations avec des chiffres publiés d'abord, puis${F.autour ? " par distance," : ""} par pertinence de votre recherche s'il y a un mot-clé, puis par nom, jamais par chances. Taux d'accès : officiel (Parcoursup). Par bac : calculé à partir des effectifs publiés dans le rapport du jury de la formation (candidats de terminale en France) ; * = pas de rapport, accès estimé par le site à partir des propositions publiées. Le plus représenté chez les admis : la ligne du rapport (paire de spécialités, série ou spécialité) qui compte le plus d'admis, pour le bac qui en compte le plus. Vos deux spécialités : rapport public du jury de la formation, sinon estimation. Votre moyenne parmi les admis : une fourchette estimée à partir des mentions publiées, pas une chance d'admission (aucun taux d'accès par moyenne n'est publié). Carte : ${CARTE_ATTRIB}. Données : ministère de l'Enseignement supérieur (SIES), session ${esc(session)}${offre ? ` ; apprentissage : cartographie Parcoursup ${esc(offre)}` : ""}.</p>
    </section>
    <div class="carte-mapcol">
      <div class="legend" id="carte-legend"></div>
      <div class="carte-box"><div id="carte-osm" class="carte-osm"></div></div>
      <p class="muted small">Fond de carte OpenStreetMap : votre navigateur demande les images de la carte aux serveurs d'OpenStreetMap, qui voient votre adresse IP. Votre profil et vos filtres ne leur sont pas envoyés.</p>
    </div>
  </div>
  <section class="card cs-share-card" aria-labelledby="cs-share-h">
    <h2 id="cs-share-h">Partager cette recherche</h2>
    <p class="small muted">Un lien vers ces résultats, pour un parent, un professeur ou un ami : vos mots, le lieu tapé et vos filtres.</p>
    <button type="button" class="btn-sec" id="cs-share">Copier le lien de cette recherche</button>
    <div id="cs-share-out" class="cs-share" hidden></div>
  </section>`;
  $view.dataset.rendered = "carte";
  const box = document.getElementById("carte-osm");
  if (!window.L) { box.innerHTML = `<div class="warn">La carte n'a pas pu être chargée ; la liste reste disponible.</div>`; }
  else {
    if (carteUI.map) { carteUI.map.remove(); carteUI.map = null; }
    carteUI.map = L.map(box, { zoomControl: true }).fitBounds([[41.3, -5.2], [51.1, 9.6]]);   // metropolitan France on any screen
    L.tileLayer(CARTE_TILES, { maxZoom: 18, attribution: CARTE_ATTRIB }).addTo(carteUI.map);
    carteUI.layer = L.layerGroup().addTo(carteUI.map);
    const type = JSON.stringify(sel);
    // audit PR 4: a map left during its animated zoom saved NaN bounds, and fitBounds threw « Bounds are not valid. » on the way
    // back: the whole page showed that error. Only valid bounds are kept and restored.
    // kept as plain numbers: a LatLngBounds made by an earlier copy of Leaflet is not one for the copy loaded now (instanceof fails,
    // it is rebuilt empty and fitBounds throws the same error)
    if (carteUI.type === type && Array.isArray(carteUI.bounds) && carteUI.bounds.flat().every(Number.isFinite)) carteUI.map.fitBounds(carteUI.bounds);
    carteUI.type = type;
    const map = carteUI.map;
    map.on("moveend", () => {
      if (map !== carteUI.map || seq !== carteUI.seq || $view.dataset.rendered !== "carte") return;   // a map the page left
      const bb = map.getBounds();
      if (bb.isValid()) { const sw = bb.getSouthWest(), ne = bb.getNorthEast(); carteUI.bounds = [[sw.lat, sw.lng], [ne.lat, ne.lng]]; }
      carteUI.page = 0; draw();
    });
  }
  const shown = () => rows.filter((f) => carteKeep(f, sel));
  // the filter panel: Parcoursup's groups, each option with its count among the formations the OTHER filters keep
  // the filters, one dropdown per group (owner, 2026-11-15), each option with its count among the formations the OTHER filters
  // keep; one dropdown open at a time, kept open while its boxes are ticked
  function panel() {
    if (seq !== carteUI.seq || $view.dataset.rendered !== "carte" || !document.getElementById("cfilters")) return;
    const base = shown(), kw = carteUI.kw, bar = document.getElementById("cfilters");
    const facetOpts = Object.fromEntries(carteGroups().map(([gr, , opts]) => [gr, opts.map(([o]) => o)]));
    if (ok) facetOpts.zones = [...CARTE_ZONES, "autre"];
    const facets = carteFacets(base, F, kw, facetOpts);
    const box2 = (gr, o, label) => { const n = facets[gr].get(o);
      return `<label><input type="checkbox" data-g="${gr}" data-o="${o}" ${(F[gr] || []).includes(o) ? "checked" : ""}> <span>${label}</span> <span class="muted">${fmt(n)}</span></label>`; };
    const zoneLabel = (z) => `<i class="lg-${z}" style="background:${carteColor(z)}"></i>${esc(carteLabel(z))}`;
    const dd = (key, title, n, body, on = n > 0) => `<details class="dd${on ? " on" : ""}" data-dd="${key}"${carteUI.open === key ? " open" : ""}><summary>${esc(title)}${n ? ` <span class="dd-n">${fmt(n)}</span>` : ""}</summary><div class="dd-panel">${body}</div></details>`;
    const clear = (gr) => ((F[gr] || []).length ? `<button type="button" class="linkish" data-clear="${gr}">Tout décocher (tout afficher)</button>` : "");
    // types and mentions counted like the other groups: among every formation the keyword, the place and the other filters keep
    // (the zone filter aside: the zones are read for the ticked types only); with a keyword or a place, an empty type is not offered
    const pool = carteFilter(C.rows, F, "zones", kw), narrowed = !!(kw || F.lieu || F.autour);
    const nDip = new Map(), nMen = new Map();
    pool.forEach((f) => { nDip.set(f.diplome, (nDip.get(f.diplome) || 0) + 1); carteGroupes(f).forEach((g) => { const k = `${f.diplome}\u0000${g}`; nMen.set(k, (nMen.get(k) || 0) + 1); }); });
    const offered = (n, ticked) => !narrowed || n > 0 || ticked;
    const dips = dd("dips", "Type de formation", sel.d.length, `${sel.d.length ? '<button type="button" class="linkish" data-clear-dips>Tout décocher (tous les types)</button>' : '<p class="muted small">Aucun coché : tous les types.</p>'}
      ${FAC.diplomes.filter((d) => offered(nDip.get(d.label) || 0, sel.d.includes(d.label))).map((d) => `<label><input type="checkbox" data-dip="${esc(d.label)}" ${sel.d.includes(d.label) ? "checked" : ""}> <span>${esc(d.label)}</span> <span class="muted">${fmt(nDip.get(d.label) || 0)}</span></label>`).join("") || '<p class="muted small">Aucun type ne correspond à la recherche.</p>'}`);
    const menDips = sel.d.map((d) => FAC.diplomes.find((x) => x.label === d)).filter((D) => D && D.mentions.length > 1);
    const mens = menDips.length ? dd("mens", "Mention ou spécialité", sel.d.reduce((a, d) => a + (sel.m[d] || []).length, 0), menDips.map((D) => `<fieldset class="dd-group"><legend>${esc(D.label)}</legend>
      ${D.mentions.length > 12 ? `<input type="search" class="cmen-q" data-for="${esc(D.label)}" placeholder="Chercher une mention" aria-label="Chercher une mention de ${esc(D.label)}">` : ""}
      ${D.mentions.filter((m) => offered(nMen.get(`${D.label}\u0000${m.label}`) || 0, (sel.m[D.label] || []).includes(m.label))).map((m) => `<label data-men-label="${esc(foldText(m.label))}"><input type="checkbox" data-men="${esc(m.label)}" data-mdip="${esc(D.label)}" ${(sel.m[D.label] || []).includes(m.label) ? "checked" : ""}> <span>${esc(m.label)}</span> <span class="muted">${fmt(nMen.get(`${D.label}\u0000${m.label}`) || 0)}</span></label>`).join("")}</fieldset>`).join("")) : "";
    // a group is marked (and its ticked count shown) only when it differs from its default (statut: paid unticked)
    const moved = (gr) => JSON.stringify(F[gr] || []) !== JSON.stringify(CARTE_DEFAULT[gr] || []);
    const robOk = robReady();
    const groups = carteGroups().filter(([gr]) => (robOk || !gr.startsWith("rob")) && !gr.startsWith("jury_")).map(([gr, title, opts]) => dd(gr, title, moved(gr) ? (F[gr] || []).length : 0, `${clear(gr)}${opts.map(([o, label]) => box2(gr, o, esc(label))).join("")}
      ${gr === "statut" ? `<p class="muted small">Les établissements privés payants ne sont montrés que si vous cochez leur case.</p>` : ""}${FI_HELP[gr] ? `<p class="muted small">${esc(FI_HELP[gr])}</p>` : ""}${gr.startsWith("rob") ? `<p class="small">${estimTag("modèle de SupCompass")} <a href="#/info/robustesse">Comment on calcule la robustesse</a></p>` : ""}`, moved(gr)));
    // owner, 2026-11-27: « Ce que regarde le jury », the five fields in ONE dropdown, each level drawn as gradation bars (1 to 3)
    const jg = juryGroups(), jn = jg.reduce((a, [gr]) => a + (moved(gr) ? (F[gr] || []).length : 0), 0), noGrid = carteNoGrid(base, F, kw);
    const bars = (w) => `<span class="jbars" aria-hidden="true">${[1, 2, 3].map((i) => `<i${i <= w ? ' class="on"' : ""}></i>`).join("")}</span>`;
    const jbox = (gr, o, label, w) => { const nn = facets[gr].get(o);
      return `<label class="jlev"><input type="checkbox" data-g="${gr}" data-o="${o}" ${(F[gr] || []).includes(o) ? "checked" : ""}> ${bars(w)}<span>${esc(label)}</span> <span class="muted">${fmt(nn)}</span></label>`; };
    const jury = jg.length ? dd("jury", "Ce que regarde le jury", jn, `${jn ? '<button type="button" class="linkish" data-clear-jury>Tout décocher (tout afficher)</button>' : ""}
      <p class="muted small">${esc(JURY_HELP)}</p>
      ${jg.map(([gr, title, opts]) => `<fieldset class="dd-group jury-row"><legend>${esc(title.replace(/^Jury : /, ""))}</legend>${opts.map(([o, label], i) => jbox(gr, o, label, JURY_LEVELS[i][2])).join("")}</fieldset>`).join("")}
      ${noGrid ? `<p class="muted small">${fmt(noGrid)} formation${noGrid > 1 ? "s" : ""} sans grille publiée sur leur fiche ${noGrid > 1 ? "ne sont" : "n'est"} pas retenue${noGrid > 1 ? "s" : ""}.</p>` : ""}`, jn > 0) : "";
    const zones = ok ? dd("zones", "Votre zone", (F.zones || []).length, `${clear("zones")}${[...CARTE_ZONES, "autre"].map((z) => box2("zones", z, zoneLabel(z))).join("")}<p class="muted small">${esc(FI_HELP.zone)}</p>`) : "";
    // the count of active groups, said on the "Filtrer" fold that hides the dropdowns on a phone
    const active = [sel.d.length, menDips.length && sel.d.some((d) => (sel.m[d] || []).length), (F.zones || []).length,
      ...carteGroups().map(([gr]) => moved(gr))].filter(Boolean).length;
    const changed = active > 0;
    document.getElementById("dd-fold-n").textContent = active ? `(${active} actif${active > 1 ? "s" : ""})` : "";
    bar.innerHTML = `${dips}${mens}${groups[0]}${zones}${groups.slice(1).join("")}${jury}${changed ? '<button type="button" class="linkish dd-reset" id="dd-reset">Réinitialiser les filtres</button>' : ""}
      <p class="muted small dd-note">Les offres en apprentissage listées à part viennent de la cartographie Parcoursup ${esc(offre || "")}. Les statistiques officielles ne les couvrent plus depuis 2022 : elles n'ont ni zone, ni taux d'accès.</p>`;
    bar.querySelectorAll("details.dd").forEach((d) => d.addEventListener("toggle", () => {
      if (d.open) { carteUI.open = d.dataset.dd; bar.querySelectorAll("details.dd[open]").forEach((o) => { if (o !== d) o.open = false; }); }
      else if (carteUI.open === d.dataset.dd) carteUI.open = null;
    }));
    bar.querySelectorAll("[data-clear]").forEach((b) => { b.onclick = () => { F[b.dataset.clear] = []; save(); }; });
    bar.querySelectorAll("[data-clear-jury]").forEach((b) => { b.onclick = () => { juryGroups().forEach(([gr]) => { F[gr] = []; }); save(); }; });
    bar.querySelectorAll("[data-g]").forEach((el) => { el.onchange = () => {
      const gr = el.dataset.g; F[gr] = [...bar.querySelectorAll(`[data-g="${gr}"]:checked`)].map((x) => x.dataset.o);
      carteUI.focus = `[data-g="${gr}"][data-o="${el.dataset.o}"]`; save(); }; });
    bar.querySelectorAll("[data-clear-dips]").forEach((b) => { b.onclick = () => { sel.d = []; sel.m = {}; reselect(); }; });
    bar.querySelectorAll("[data-dip]").forEach((el) => { el.onchange = () => {
      const picked = [...bar.querySelectorAll("[data-dip]:checked")].map((x) => x.dataset.dip);
      sel.d = FAC.diplomes.map((d) => d.label).filter((d) => picked.includes(d));
      sel.m = Object.fromEntries(sel.d.map((d) => [d, sel.m[d] || []]));
      reselect(); }; });
    bar.querySelectorAll("[data-men]").forEach((el) => { el.onchange = () => {
      const d = el.dataset.mdip;
      sel.m[d] = [...bar.querySelectorAll("[data-men]:checked")].filter((x) => x.dataset.mdip === d).map((x) => x.dataset.men);
      carteUI.focus = null; store.set("carteSel", sel); history.replaceState(null, "", carteHash(sel)); carteUI.page = 0; panel(); draw(); }; });
    bar.querySelectorAll(".cmen-q").forEach((el) => { el.oninput = () => {
      const q = foldText(el.value.trim());
      el.closest("fieldset").querySelectorAll("[data-men-label]").forEach((lab) => { lab.hidden = !!q && !lab.dataset.menLabel.includes(q); }); }; });
    const rs = document.getElementById("dd-reset");
    if (rs) rs.onclick = resetFilters;
    if (carteUI.focus) { const el = bar.querySelector(carteUI.focus); if (el) el.focus(); carteUI.focus = null; }
  }
  // the figures for the student's doublette or line: one request per page of the list, kept for the profile
  function figures(list) {
    if (!ok) return;
    const want = list.filter((f) => f.stats !== false && !ctx.chiffres.has(f.cod_aff_form)).map((f) => f.cod_aff_form).slice(0, 40);
    if (!want.length) return;
    want.forEach((c) => ctx.chiffres.set(c, null));
    api(`/api/carte/chiffres?codes=${want.join(",")}&${sq}`).then((r) => {
      Object.entries(r.chiffres || {}).forEach(([c, x]) => ctx.chiffres.set(c, x));
      if (seq === carteUI.seq && $view.dataset.rendered === "carte") drawCards();
    }).catch(() => want.forEach((c) => ctx.chiffres.delete(c)));
  }
  function draw(fetch = true) {
    // audit PR 4: the map's moveend (an animated zoom ending) or a late answer may land after the visitor left the page or
    // opened it again: never draw into elements that are gone (the testers' « Cannot set properties of null »)
    if (seq !== carteUI.seq || $view.dataset.rendered !== "carte" || !document.getElementById("cs-status")) return;
    const kw = carteUI.kw, kept = carteFilter(shown(), F, undefined, kw), vb = carteUI.map && carteUI.map.getBounds();
    const inView = (f) => !vb || !vb.isValid() || (f.lat != null && vb.contains([f.lat, f.lon]));
    const rank = carteNameRank(C), sortName = new Map(kept.map((f) => [f, carteSortName(f)]));
    const byName = (a, b) => { const x = rank.get(sortName.get(a)), y = rank.get(sortName.get(b));
      return x !== undefined && y !== undefined ? x - y : FR_COLL.compare(sortName.get(a), sortName.get(b)); };
    kept.forEach((f) => { f.dist = F.autour && f.lat != null ? Math.round(haversineKm(F.autour.lat, F.autour.lon, f.lat, f.lon)) : null; });
    const listed = kept.filter((f) => inView(f) || f.lat == null)
      // R10: formations with published figures first, then the apprenticeship offers; then distance (around a town), then the
      // name without its leading punctuation ("(CFA …)" sorted with C). Never by a figure.
      // lot 1, PR 13 (owner): with a keyword, the formations whose names carry more of the typed words come first, BEFORE the
      // distance; then the distance, the engine's relevance, the name
      .sort((a, b) => (a.stats === false) - (b.stats === false) || (kw ? (kw.mots.get(b.cod_aff_form) ?? 0) - (kw.mots.get(a.cod_aff_form) ?? 0) : 0)
        || (F.autour ? (a.dist ?? 1e9) - (b.dist ?? 1e9) : 0)
        || (kw ? (kw.rank.get(a.cod_aff_form) ?? 1e9) - (kw.rank.get(b.cod_aff_form) ?? 1e9) : 0)
        || byName(a, b));
    // audit PR 4 (owner, 2026-11-23): the paid private establishments stay unticked by default (Plan B's rule), and the list SAYS how
    // many of them the other criteria would show, with a button that ticks their box
    const noGridN = carteNoGrid(shown(), F, kw);   // owner, 2026-11-27: what the jury filter leaves out for want of a grid, said
    const paid = carteHiddenPaid(shown(), F, kw), showPaid = () => { F.statut = [...new Set([...F.statut, "prive"])]; save(); };
    setHtml(document.getElementById("cs-status"), [
      kw ? kwChips(kw, F.autour) : "",
      kw ? kw.notes.map((n) => `<div class="info">${esc(n)}</div>`).join("") : "",
      carteUI.kwErr ? `<p class="warn small">La recherche par mot-clé n'a pas abouti : ${esc(carteUI.kwErr)}. La liste montre toutes les formations.</p>` : "",
      carteUI.lieuBad ? `<p class="warn small">Lieu non reconnu : « ${esc(carteUI.lieuBad)} ». Choisissez une ville, un département, une académie ou une région dans la liste.</p>` : "",
      noGridN ? `<p class="small muted cs-nogrid">${fmt(noGridN)} formation${noGridN > 1 ? "s" : ""} sans grille publiée sur leur fiche ${noGridN > 1 ? "ne sont" : "n'est"} pas retenue${noGridN > 1 ? "s" : ""} par le filtre « Ce que regarde le jury ».</p>` : "",
      (carteUI.restored || []).length ? `<p class="small cs-restored">Filtres gardés de votre dernière visite : ${esc(carteUI.restored.join(", "))}. <button type="button" class="linkish" data-reset-filters>Réinitialiser les filtres</button></p>` : "",
      // audit PR 8: nothing kept but paid formations hidden = say THAT, never « aucune formation ne correspond » beside them
      !kept.length && paid ? `<p class="info cs-paid-only">Les ${fmt(paid)} formation${paid > 1 ? "s" : ""} qui correspond${paid > 1 ? "ent" : ""} à votre recherche ${paid > 1 ? "sont" : "est"} dans des établissements privés payants, masqués par défaut. <button type="button" class="linkish" data-show-paid>Les afficher</button></p>`
      : !kept.length && (kw || F.lieu || F.autour || carteActive(F).length) ? `<p class="muted">Aucune formation ne correspond.${carteActive(F).length ? ` Filtres actifs : ${esc(carteActive(F).join(", "))}. <button type="button" class="linkish" data-reset-filters>Réinitialiser les filtres</button>` : ""} Essayez un sigle (BTS, BUT, MPSI…), un intitulé (droit, psychologie…) ou un autre lieu.</p>` : "",
    ].join(""));
    document.querySelectorAll("#cs-status [data-reset-filters]").forEach((b) => { b.onclick = resetFilters; });
    document.querySelectorAll("#cs-status [data-show-paid]").forEach((b) => { b.onclick = showPaid; });
    if (carteUI.fit && carteUI.map) {
      carteUI.fit = false;
      const pts = kept.filter((f) => f.lat != null).map((f) => [f.lat, f.lon]);
      if (F.autour) { carteUI.map.setView([F.autour.lat, F.autour.lon], F.autour.km <= 10 ? 11 : F.autour.km <= 25 ? 10 : F.autour.km <= 50 ? 9 : F.autour.km <= 100 ? 8 : 7); return; }
      if ((kw || F.lieu) && pts.length) { carteUI.map.fitBounds(pts, { maxZoom: 12, padding: [24, 24] }); return; }   // moveend draws again
    }
    const counts = {}; kept.forEach((f) => { const z = carteZone(f); counts[z] = (counts[z] || 0) + 1; });
    setHtml(document.getElementById("carte-count"), `${fmt(kept.length)} formation${kept.length > 1 ? "s" : ""} correspondant à vos critères · ${fmt(listed.length)} dans la partie visible de la carte${paid
      ? `<br><span class="cs-paid">${fmt(paid)} formation${paid > 1 ? "s" : ""} d'établissements privés payants ${paid > 1 ? "masquées" : "masquée"} — <button type="button" class="linkish" id="cs-paid" data-show-paid>les afficher</button></span>` : ""}`);
    document.querySelectorAll("[data-show-paid]").forEach((pb) => { pb.onclick = showPaid; });
    setHtml(document.getElementById("carte-legend"), ok && !zonesReady ? '<span class="muted">Zones en cours de chargement…</span>' : ok ? [...CARTE_ZONES, "autre"].map((z) => `<span><i class="lg-${z}" style="background:${carteColor(z)}"></i>${esc(carteLabel(z))}${z !== "autre" ? ` (${CARTE_SHAPE[z]})` : ""} : ${fmt(counts[z] || 0)}</span>`).join("") : `<span><i class="lg-autre" style="background:var(--muted)"></i>Formation (sans profil, pas de zone)</span>`);
    if (carteUI.map) {
      carteUI.layer.clearLayers();
      const map = carteUI.map, pts = kept.filter((f) => f.lat != null).map((f) => { const p = map.latLngToLayerPoint([f.lat, f.lon]); return { x: p.x, y: p.y, f }; });
      // from zoom 16 every formation is drawn on its own (several in one building would never split otherwise)
      for (const gp of (map.getZoom() >= 16 ? pts.map((p) => [p]) : carteClusters(pts, map.getZoom() >= 13 ? 20 : 52))) {
        if (gp.length === 1) {
          const f = gp[0].f;
          L.marker([f.lat, f.lon], { icon: L.divIcon({ className: "carte-pin", html: carteMarker(f), iconSize: [18, 18] }), keyboard: true, title: `${f.etablissement}, ${carteLabel(carteZone(f))}` })
            .on("click", () => { carteUI.sel = f.cod_aff_form; showSel(true); }).addTo(carteUI.layer);
        } else {
          const lat = gp.reduce((a, p) => a + p.f.lat, 0) / gp.length, lon = gp.reduce((a, p) => a + p.f.lon, 0) / gp.length, ring = carteRing(gp);
          L.marker([lat, lon], { icon: L.divIcon({ className: "carte-pin", html: ring.html, iconSize: [ring.size, ring.size] }), keyboard: true, title: `${gp.length} formations` })
            .on("click", () => map.setView([lat, lon], Math.min(map.getZoom() + 2, 18))).addTo(carteUI.layer);
        }
      }
    }
    lastCards = { listed, empty: !kept.length && paid
      ? `Aucune formation publique ou privée sous contrat ne correspond : les ${fmt(paid)} trouvée${paid > 1 ? "s" : ""} ${paid > 1 ? "sont" : "est"} dans des établissements privés payants (voir ci-dessus).` : null };
    drawCards();
    // lot 1, PR 11: after « Rechercher » the page goes down to the results on a phone (the first one was about two screens
    // lower: Yanis), and the count is said in the status line; the focus stays in the search field
    if (carteUI.jump) { carteUI.jump = false; carteJump(kept.length); }
    if (fetch) figures(listed.slice(carteUI.page * cartePage(), (carteUI.page + 1) * cartePage()).concat(rows.filter((f) => f.cod_aff_form === carteUI.sel)));
  }
  // audit PR 8: the cards alone, drawn again from the last list (the cards' details or the profile figures arrived): no filter
  // count, sort or map marker is redone for an answer that changes none of them (each full draw blocked a phone ~0.3 s)
  function drawCards() {
    if (!lastCards || seq !== carteUI.seq || $view.dataset.rendered !== "carte" || !document.getElementById("carte-items")) return;
    showSel();
    document.getElementById("carte-items").innerHTML = carteList(lastCards.listed, ctx, lastCards.empty);
    bindCarte();
    document.querySelectorAll("[data-cpage]").forEach((b) => { b.onclick = () => { carteUI.page = Math.max(0, carteUI.page + Number(b.dataset.cpage)); draw(); }; });
    document.querySelectorAll("[data-pick]").forEach((el) => { el.onclick = (e) => { if (e.target.closest("a,button")) return; carteUI.sel = el.dataset.pick; showSel(false); }; });
  }
  // R10: a formation chosen on the MAP is pinned at the top of the list (its card, with a close button); one chosen in the
  // list is only marked there. Its figures are asked whatever chose it (Codex, R9).
  function showSel(fromMap) {
    const f = rows.find((x) => x.cod_aff_form === carteUI.sel);
    if (fromMap !== undefined) carteUI.pin = !!fromMap;
    document.getElementById("carte-sel").innerHTML = f && carteUI.pin ? carteCard(f, ctx, true) : "";
    bindCarte();
    document.querySelectorAll(".carte-rc").forEach((el) => el.toggleAttribute("aria-current", el.dataset.pick === carteUI.sel));
    if (f) figures([f]);          // a marker's formation may be on no loaded page of the list (Codex): its figures too
    if (fromMap && f) document.getElementById("carte-sel").scrollIntoView({ block: "nearest" });
  }
  function bindCarte() {
    bindVoeuButton(draw);
    $view.querySelectorAll("[data-cmp]").forEach((b) => { b.onclick = () => { basket.toggle(b.dataset.cmp); draw(false); }; });
    $view.querySelectorAll("[data-unpin]").forEach((b) => { b.onclick = () => { carteUI.sel = null; carteUI.pin = false; showSel(); }; });
  }
  function save(repanel = true) { carteUI.restored = []; store.set("carteFiltres2", F); carteUI.page = 0; if (repanel) panel(); draw(); }
  const resetFilters = () => { for (const [gr] of carteGroups()) F[gr] = [...(CARTE_DEFAULT[gr] || [])]; F.zones = []; carteUI.open = null; carteUI.restored = [];
    store.set("carteFiltres2", F); sel.d = []; sel.m = {}; reselect(); };
  const form = document.getElementById("cs-form"), qEl = document.getElementById("cs-q"), lieuEl = document.getElementById("cs-lieu");
  document.getElementById("dd-fold").addEventListener("toggle", (e) => { if (narrow()) carteUI.fold = e.target.open; });
  const kmEl = document.getElementById("cs-km"), kmBox = form.querySelector(".cs-km");
  async function doSearch() {
    const q = qEl.value.trim().slice(0, 200), lt = lieuEl.value.trim(), L = carteLieu(lieux, lt);
    F.q = q;
    F.lieuTxt = L ? lt : "";
    F.lieu = L && L.t !== "ville" ? { t: L.t, v: L.v } : null;
    F.autour = L && L.t === "ville" ? { lat: L.lat, lon: L.lon, km: Number(kmEl.value) || 25, ville: lt } : null;
    carteUI.lieuBad = lt && !L ? lt : "";
    // one token per submission: a slower answer to an earlier keyword never overwrites the latest one (Codex)
    const mine = carteUI.kwTok = (carteUI.kwTok || 0) + 1;
    let kw = null, err = "";
    try { kw = q ? await kwLoad(q) : null; } catch (e) { err = apiErrorText(e); }
    if (mine !== carteUI.kwTok || seq !== carteUI.seq || $view.dataset.rendered !== "carte") return;
    carteUI.kw = kw; carteUI.kwErr = err;
    carteUI.fit = true;
    save();
    if (q) suggestLycee(q, "carte");
  }
  form.onsubmit = (e) => { e.preventDefault(); carteUI.kwErr = ""; carteUI.jump = true; doSearch(); };
  // audit PR 8: the place suggestions (thousands of towns) are written when the field is first used, not with the page
  // (their HTML was parsed in the page's first long task on a phone); same list, same order (red team VT13)
  const fillLieux = () => { const dl = document.getElementById("cs-lieux"); if (dl && !dl.options.length) dl.innerHTML = [...lieux.keys()].map((l) => `<option value="${esc(l)}">`).join(""); };
  lieuEl.addEventListener("focus", fillLieux, { once: true });
  lieuEl.oninput = () => { fillLieux(); const L = carteLieu(lieux, lieuEl.value); kmBox.hidden = !(L && L.t === "ville"); };
  kmEl.onchange = () => { if (F.autour) { F.autour = { ...F.autour, km: Number(kmEl.value) || 25 }; carteUI.fit = true; save(false); } };
  // the shared link: copied when the browser allows it, else shown selected (never sent anywhere by the site)
  document.getElementById("cs-share").onclick = async () => {
    const link = `${location.origin}/${carteShareLink(F, sel)}`, out = document.getElementById("cs-share-out");
    const said = `Le lien contient vos mots, le lieu tapé et vos filtres${(F.lieuTxt || "").startsWith(MA_VILLE) ? " (pas « Ma ville », qui reste dans votre profil)" : ""} : jamais votre profil ni vos zones. Il ouvre cette recherche sans rien envoyer au site.`;
    let copied = false;
    try { await navigator.clipboard.writeText(link); copied = true; } catch (_) { copied = false; }
    out.hidden = false;
    out.innerHTML = `<p class="small" role="status">${copied ? "Lien copié." : "Copiez ce lien :"} ${esc(said)}</p>
      <input type="text" readonly class="cs-share-link" aria-label="Lien de cette recherche" value="${esc(link)}">`;
    const inp = out.querySelector("input"); inp.focus(); inp.select();
  };
  const ch = document.getElementById("chome");
  if (ch) ch.onclick = () => { lieuEl.value = `Ma ville : ${villeLabel(home)}`; kmBox.hidden = false; doSearch(); };
  if (!carteUI.ddBound) {                         // one dropdown open at a time: a click elsewhere or Escape closes it
    carteUI.ddBound = true;
    document.addEventListener("click", (e) => {
      if (!e.target.isConnected) return;          // a ticked box re-drew its own dropdown: it stays open
      document.querySelectorAll("details.dd[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      const d = document.querySelector("details.dd[open]");
      if (d) { d.open = false; d.querySelector("summary").focus(); }
    });
  }
  // audit PR 8: zones already here (a cached answer, a quick server) are read before the first draw: one full draw, not two
  const early = ok && zonesEarly !== undefined;
  if (early && applyZones(zonesEarly)) track("journey", { stage: "stage2" });
  panel();
  draw();
  // sprint Q3: the cards' keys after the list (one cached answer); a failure leaves the rates out, never "chargement…" forever
  // sprint Vitesse: with a profile, after the zones (a slow phone line shares its bandwidth: the zones come first)
  if (!C.details) (ok ? zonesP.catch(() => null) : Promise.resolve()).then(() => loadDetails(C)).then(() => {
    if (seq !== carteUI.seq || $view.dataset.rendered !== "carte") return;
    // the drawn rows ARE the layer's rows (carteMerge writes on them): coucheDetails filled them, only the cards change
    drawCards();
  }, () => {
    // Codex (PR #116): the estimate outside terminale too: « indisponible », never « chargement… » forever
    rows.forEach((f) => { if (f.bacs === undefined) f.bacs = null; if (f.reo === undefined) f.reo = false; });
    drawCards();
  });
  if (ok && !early) zonesP.then((zs) => {
    if (seq !== carteUI.seq || $view.dataset.rendered !== "carte") return;
    if (applyZones(zs)) track("journey", { stage: "stage2" });
    panel(); draw();          // a saved zone filter reveals its cards only now: fetch their figures (cached codes are skipped; Codex)
  });
}
// ---- lot 2 (Claude design guidelines): the summary comes before the detail; details live in tabs ----
// summaryBand: four figures read at a glance (official access rate, the student's zone, admits, jobs); every tile opens its tab.
// The zone tile is filled by the Plan B answer (same profile, same zone as « Mon parcours »); without a stored profile it asks for one.
const fmt2 = (x) => Number(x).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
// who the admits are (owner, 2026-11-10): the PUBLISHED counts of nouveaux bacheliers and other admits (admis.py on the server);
// the bar is drawn only when they add up to the published total; the label in lists comes from the server's fixed rule
const AUTRES_LABEL = "Majorité d'admis hors nouveaux bacheliers";
const autresBadge = (x) => (x && x.autres_majoritaires ? ` <span class="badge autres" title="Plus d'admis déjà bacheliers ou venus d'un autre parcours (réorientation, reprise d'études…) que de nouveaux bacheliers, sur au moins 10 admis">${AUTRES_LABEL}</span>` : "");
function admisBar(a) {
  if (!a) return "";
  const head = `<strong>Qui sont les admis ${esc(a.session)} ?</strong>`;
  // sprint Q5: the definitions are folded (the summary stays short on a phone); the text is unchanged
  const note = `<details class="adm-more"><summary class="small">Nouveaux bacheliers, autres admis : que veulent dire ces mots ?</summary><p class="muted small">Nouveaux bacheliers : ils passaient le bac l'année de leur admission. Autres admis : ils avaient déjà le bac ou venaient d'un autre parcours (réorientation, reprise d'études…) ; le ministère ne les détaille pas. Les mentions et les séries de bac publiées ne concernent que les nouveaux bacheliers.</p></details>`;
  if (!a.coherent) return `<div class="adm"><p class="small">${head} ${fmt(a.admis_neobac)} nouveaux bacheliers et ${fmt(a.admis_autres)} autres admis publiés, pour ${fmt(a.admis)} admis : les deux effectifs ne font pas exactement le total publié, la répartition n'est pas dessinée.</p>${note}</div>`;
  const w = (n) => (100 * n / a.admis).toFixed(2);
  return `<div class="adm"><p class="small">${head}${autresBadge(a)}</p>
    <div class="adm-bar" role="img" aria-label="${fmt(a.admis_neobac)} nouveaux bacheliers et ${fmt(a.admis_autres)} autres admis sur ${fmt(a.admis)} admis"><span class="neo" style="width:${w(a.admis_neobac)}%"></span><span class="autres" style="width:${w(a.admis_autres)}%"></span></div>
    <p class="small"><span class="adm-key neo"></span>${fmt(a.admis_neobac)} nouveaux bacheliers${a.pct_neobac != null ? ` (${pct(a.pct_neobac)} des admis)` : ""} · <span class="adm-key autres"></span>${fmt(a.admis_autres)} autres admis</p>${note}</div>`;
}
const admisCell = (a) => (!a ? "—" : `${fmt(a.admis_neobac)} / ${fmt(a.admis_autres)}${a.coherent ? "" : ` <span class="muted small">(total publié ${fmt(a.admis)})</span>`}${autresBadge(a)}`);
// R2 (owner, 2026-11-11): ONE sourced figure for the profile beside the official access rate (inside the lot 2 summary section).
// It is a figure the "Selon votre bac" card shows for the same profile, chosen by the same rules (a published figure replaces an
// estimate, never beside it), for the page's own campaign:
//   bac général: this formation's own report row (the doublette, else its "Autres doublettes" line) when the report has a bac
//     général table; else the similar formations' estimate; else the national group's estimate; else (no doublette figure)
//     the card's "votre bac" row, the formation's bac général proposal rate from published counts;
//   bac techno / pro: the student's line of the report (pickVoie); else the card's "votre bac" row (the proposal rate of the
//     student's route in this formation, "peu de candidats" below 20, as on the card) — review: never the latest campaign's
//     estimate on an older page, never a figure the card does not show;
//   outside terminale: the estimated access (sprint 21), in its own tile.
// Never a chance: a past rate of candidates like the student, with its source and, for a report row, its counts.
function profileRate(d, prof) {
  if (!prof || isReo(prof)) return null;
  const serie = ["bg", "bt", "bp"].includes(prof.serie) ? prof.serie : "bg";
  const rp = d.rapport, dbl = d.doublettes;
  const series = dbl && dbl.series;
  // Codex (PR #54): the series and estimates carry every campaign of the lineage, their top-level figure is the LATEST one;
  // the tile reads the entry of the page's own campaign, beside the official rate of that campaign
  const session = d.record && d.record.session;
  const at = (trend) => (trend || []).find((t) => t.session === session) || null;
  const route = () => {                                       // the card's "votre bac" row, for the page's campaign
    const v = series && series[serie] && at(series[serie].trend);
    return v && v.taux !== null && v.taux !== undefined
      ? { kind: "serie", taux: v.taux, what: RP_VOIE[serie], source: "voie", fragile: (v.candidats || 0) < DBL_SEUIL, candidats: v.candidats }
      : { kind: "aucun", what: RP_VOIE[serie], why: `pas de chiffre publié pour votre bac en ${session}` };
  };
  const estAt = (e) => { const t = e && at(e.trend); return t && t.taux !== null && t.taux !== undefined ? t.taux : null; };
  if (serie === "bg") {
    const dkey = profileDkey(prof);
    if (!dkey) return { kind: "incomplet" };                   // review: no doublette without two distinct specialties
    if (ownHasBg(rp)) {
      const x = pickRapport(rp, dkey);
      return x ? { kind: "publie", taux: x.taux, what: x.source === "autres" ? "vos deux spécialités, ligne « Autres paires de spécialités »" : rpLabel(x.libelle),
        source: "rapport", session: rp.session, recoupe: rp.recoupe !== false, en_position: x.en_position, confirmes: x.confirmes }
        : { kind: "aucun", what: "vos deux spécialités", why: `pas de ligne dans le rapport ${rp.session}` };
    }
    const sem = estimateSemblable(series, d.semblables, dkey);
    if (sem && estAt(sem) !== null) return { kind: "estimation", taux: estAt(sem), what: sem.label, source: "semblables", n_rapports: sem.n_rapports };
    const nat = dbl && dbl.status === "ok" ? estimateDoublette(series, dbl.groupe, dkey) : null;
    if (nat && estAt(nat) !== null) return { kind: "estimation", taux: estAt(nat), what: nat.source === "autres" ? "vos deux spécialités, « Autres paires de spécialités »" : nat.label, source: "national" };
    return route();
  }
  const v = pickVoie(rp, serie, prof.voie || null);
  // lot 1, PR 10: the report's label as a student reads it (rpLabel: « Msgn/ X » is « Management (X) »; Yanis read it raw here)
  if (v) return { kind: "publie", taux: v.taux, what: v.source === "autres" ? `votre ${VOIE_WORD[serie]}, ligne « ${rpLabel(v.libelle)} »` : `votre bac, ligne « ${rpLabel(v.libelle)} »`,
    source: "rapport", session: rp.session, recoupe: rp.recoupe !== false, en_position: v.en_position, confirmes: v.confirmes };
  return route();
}
const PR_SOURCE = {
  rapport: (pr) => `publié · rapport du jury ${esc(pr.session)}${pr.recoupe ? "" : ", pas encore recoupé"} · ${fmt(pr.en_position)} sur ${fmt(pr.confirmes)} candidats`,
  semblables: (pr) => estimTag(`rapports de ${fmt(pr.n_rapports)} formations semblables`, false, true),
  national: () => estimTag("écart national de vos deux spécialités", false, true),
  voie: (pr) => `taux de proposition de cette formation (effectifs publiés)${pr.fragile ? ` · peu de candidats (${fmt(pr.candidats)})` : ""}`,
};
// owner, 2026-11-18: the profile's figure is the second half of ONE access cell (accesTile), beside the official rate
function profileRateTile(pr) {
  const tile = (value, note) => `<button type="button" class="sum-part sum-profil" data-goto="admission">
      <span class="sum-label">Pour votre profil</span><span class="sum-value">${value}</span><span class="sum-note">${note}</span></button>`;
  const link = (note) => `<a class="sum-part sum-profil" href="#/profil"><span class="sum-label">Pour votre profil</span><span class="sum-value">—</span><span class="sum-note">${note}</span></a>`;
  if (!pr) return link("créez votre profil dans « Mon profil » : votre zone et le chiffre de votre bac");
  if (pr.kind === "incomplet") return link("indiquez vos deux spécialités dans « Mon profil »");
  if (pr.kind === "aucun" || pr.taux === null || pr.taux === undefined) return tile("—", `${esc(pr.what)} · ${esc(pr.why || "pas de chiffre")}`);
  return tile(pct1(pr.taux), `${esc(pr.what)} · ${PR_SOURCE[pr.source](pr)}`);
}
// owner, 2026-11-18: the official access rate and the profile's figure in ONE cell, with one short sentence saying what each is
// (outside terminale the second half is the estimated access of sprint 21); never a chance
const ACCES_EXPLAIN = "Officiel : la part de tous les candidats qui ont reçu une proposition.";
function accesTile(r, d, prof, pr) {
  const off = `<button type="button" class="sum-part" data-goto="admission"><span class="sum-label">Taux d'accès ${r.session}</span><span class="sum-value">${pct(r.taux_acces_ens)}</span><span class="sum-note">officiel, tous candidats, phase principale</span></button>`;
  const reo = isReo(prof);
  const second = reo ? `<button type="button" class="sum-part" data-goto="admission"><span class="sum-label">Accès estimé hors terminale</span><span class="sum-value">${pct1(d.reorientation && d.reorientation.acces_estime)}</span><span class="sum-note">${reoWhy(d.reorientation, "estimation, pas une zone : calcul en tête de l'onglet « Y entrer »")}</span></button>`
    : profileRateTile(pr);
  const why = reo ? "Hors terminale : une estimation pour les candidats qui ne sont pas en terminale."
    : "Pour votre profil : le même taux, pour les candidats qui ont votre bac ou vos deux spécialités.";
  return `<div class="sum-tile sum-acces">${off}${second}<p class="sum-explain">${ACCES_EXPLAIN} ${why}</p></div>`;   // « pas des chances » closes the summary (its own last line)
}
// owner, 2026-11-18: the robustesse 2035 of the formation in L'essentiel: its score (median of the three scenarios) and its two
// repères (within its filière, among all formations), always an estimation of the model; the detail stays in « Emploi et métiers »
function formationRobTile(rb) {
  const s = rb && rb.score, niv = rb && rb.echelle && rb.echelle.niveaux;
  // owner, 2026-11-20: a formation that leads directly to a scored one borrows its block, said in words
  const vois = rb && rb.voisine ? "emprunté à la formation voisine ; " : "";
  const words = s ? echelleWords(niv) : "";
  const note = !rb ? "pas d'estimation pour cette formation" : rb.absent ? esc((ROBF_ABSENT[rb.absent] || {}).court || "pas d'estimation pour cette formation")
    : !s ? "données insuffisantes pour une estimation sûre"
    : !words ? `pas de niveau pour cette formation ${estimTag("", false, true)}`
    : `${echelleJauge(niv)}<span class="sr-only">Sur une échelle de cinq niveaux, de très exposée à très robuste. </span>${esc(vois)}${esc(echelleNote(niv))} ${estimTag("", false, true)}`;
  return `<button type="button" class="sum-tile sum-rob" data-goto="emploi" data-goto-card="robustesse"><span class="sum-label">Robustesse 2035</span><span class="sum-value sum-words">${words ? esc(words) : "—"}</span><span class="sum-note">${note}</span></button>`;
}
function summaryBand(r, d) {
  const prof = store.get("profile", null);
  const pr = profileRate(d, bacProfile());
  const jobs = d.metiers && d.metiers.status === "ok" ? d.metiers.metiers.length : null;
  const tile = (tab, label, value, note, extra = "") => `<button type="button" class="sum-tile" data-goto="${tab}"${extra}>
      <span class="sum-label">${label}</span><span class="sum-value">${value}</span><span class="sum-note">${note}</span></button>`;
  return `<section class="card summary" aria-label="L'essentiel en 30 secondes"><h2>L'essentiel</h2>
    <div class="sum-grid">
      ${accesTile(r, d, prof, pr)}
      ${!isReo(prof) && prof ? tile("admission", "Votre zone", '<span class="muted">…</span>', "selon votre profil, d'après les admis passés", ' id="sum-zone"') : ""}
      ${tile("admission", `Admis ${r.session}`, fmt(r.acc_tot), r.capa_fin != null ? `pour ${fmt(r.capa_fin)} places${d.tension ? ` · ${fmt(d.tension.par_place)} vœux par place${d.tension.libelle ? ` <span class="badge tension">${esc(d.tension.libelle)}</span>` : ""}` : ""}` : "places non publiées")}
      ${formationRobTile(d.robustesse)}
      ${tile("emploi", "Métiers visés", jobs != null ? fmt(jobs) : "—", jobs != null ? "d'après la fiche Onisep du diplôme" : "pas de fiche Onisep pour ce diplôme")}
    </div>
    ${prof && !isReo(prof) ? zoneLegend() : ""}
    ${admisBar(d.admis)}
    ${d.jury_tab ? `<p class="small sum-jury"><button type="button" class="linkish" data-goto="jury">${d.jury_tab.kind === "both" ? `Comment votre dossier est examiné : la fiche Parcoursup${d.jury_tab.session ? ` ${esc(d.jury_tab.session)}` : ""} et le rapport du jury ${esc(d.jury_tab.rapport)}` : d.jury_tab.kind === "own" ? `Ce que regarde le jury : son rapport public ${esc(d.jury_tab.session)}` : d.jury_tab.kind === "grille" ? `Comment votre dossier sera examiné : la grille de la fiche Parcoursup${d.jury_tab.session ? ` ${esc(d.jury_tab.session)}` : ""}` : "Ce que regardent les jurys de formations semblables (pas de rapport pour celle-ci)"} →</button></p>` : ""}
    ${d.apprenti && d.apprenti.propose ? `<p class="small sum-app"><button type="button" class="linkish" data-goto="cout" data-goto-card="app-card">${d.apprenti.sies_apprentissage ? "Cette formation se fait en apprentissage" : "Cette formation se fait aussi en apprentissage"} : formation gratuite et salaire →</button></p>` : ""}
    ${jpoLine(d.jpo)}
    ${d.vie && d.vie.lat != null && villeDepart() ? `<p class="small sum-dist"><button type="button" class="linkish" data-goto="cout">À ${fmt(Math.round(haversineKm(villeDepart().lat, villeDepart().lon, d.vie.lat, d.vie.lon)))} km de ${esc(villeLabel(villeDepart()))} à vol d'oiseau : loyer et transports →</button></p>` : ""}
    <p class="muted small">Des résultats des campagnes passées, pas des chances d'admission.</p></section>`;
}
// sprint V2: how many vœux the formation received for each place, placed among its type (tension.py): demand, never a chance
function tensionCard(t, session) {
  if (!t) return "";
  return `<div class="card"><h2>Combien de candidats pour une place ?</h2>
    <p><strong>${fmt(t.voeux)} vœux</strong> en phase principale ${esc(session)} pour <strong>${fmt(t.places)} places</strong> : ${fmt(t.par_place)} vœux par place ${estimTag("vœux ÷ places, deux chiffres publiés")}${t.libelle ? ` <span class="badge tension">${esc(t.libelle)}</span>` : ""}</p>
    ${t.explication ? `<p class="small">${esc(t.explication)} Comparaison avec les ${fmt(t.n_type)} formations du même type de la campagne.</p>` : `<p class="small muted">Comparée aux ${fmt(t.n_type)} formations du même type de la campagne, la demande n'est pas parmi les plus fortes.</p>`}
    <p class="small muted">${esc(t.prudence)}</p></div>`;
}
function fillZoneTile(target) {
  const el = document.getElementById("sum-zone");
  if (!el) return;
  const z = target && ZONES[target.zone];
  el.querySelector(".sum-value").innerHTML = z ? zonePillHtml(target.zone, false, target.large && !target.uncertain) : "—";
  if (target && target.uncertain) el.querySelector(".sum-note").textContent = "lecture incertaine : peu de données";
  else if (target && target.taux_zone_source) el.querySelector(".sum-note").textContent = target.taux_zone_source.source === "autres"
    ? "lue sur la ligne « Autres paires de spécialités » du rapport" : "lue sur le taux de vos deux spécialités (rapport public)";
}
// tabbed: one tab per non-empty group; the first is open; a tile with data-goto opens its tab
function tabbed(id, groups) {
  const kept = groups.filter(([, , html]) => html.replace(/<div id="planb"><\/div>/, "x").trim());
  return `<div class="tabs" role="tablist" aria-label="Sections" data-tabs="${id}">${kept.map(([k, label], n) =>
      `<button type="button" role="tab" id="tab-${id}-${k}" aria-controls="panel-${id}-${k}" aria-selected="${n === 0}" data-tab-key="${k}">${label}</button>`).join("")}</div>
    ${kept.map(([k, , html], n) => `<div class="tabpanel" role="tabpanel" id="panel-${id}-${k}" aria-labelledby="tab-${id}-${k}"${n ? " hidden" : ""}>${html}</div>`).join("")}`;
}
function bindTabs(id) {
  const bar = document.querySelector(`[data-tabs="${id}"]`);
  if (!bar) return;
  const open = (k) => {
    let shown = null;
    bar.querySelectorAll("[role=tab]").forEach((b) => {
      const on = b.dataset.tabKey === k;
      b.setAttribute("aria-selected", String(on));
      const panel = document.getElementById(b.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
      if (panel && on) shown = panel;
    });
    // sprint Q5: the tab bar is sticky; a tab chosen down a long panel shows the new panel from its start, under the bar
    if (shown && bar.getBoundingClientRect().top <= 1) window.scrollBy(0, shown.getBoundingClientRect().top - bar.offsetHeight);
    if (id === "fiche") track("action", { a: "onglet", tab: k });   // sprint 18: which tab of a formation page, never which formation
  };
  bar.querySelectorAll("[role=tab]").forEach((b) => { b.onclick = () => open(b.dataset.tabKey); });
  bar.onkeydown = (e) => {
    if (!["ArrowRight", "ArrowLeft"].includes(e.key)) return;
    const tabs = [...bar.querySelectorAll("[role=tab]")], i = tabs.findIndex((b) => b.getAttribute("aria-selected") === "true");
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    open(next.dataset.tabKey); next.focus();
  };
  document.querySelectorAll("[data-goto]").forEach((t) => {
    t.onclick = () => {
      if (!bar.querySelector(`[data-tab-key="${t.dataset.goto}"]`)) return;
      open(t.dataset.goto);
      // audit PR 5: a link about one card lands ON that card (the apprenticeship card was 5.8 phone screens below its link),
      // under the sticky tab bar; else the tab's start
      const card = t.dataset.gotoCard && document.getElementById(t.dataset.gotoCard);
      if (card && !card.closest("[hidden]")) window.scrollBy(0, card.getBoundingClientRect().top - bar.offsetHeight - 8);
      else bar.scrollIntoView({ block: "start" });
    };
  });
}

// sprint V1 « Étudier là-bas » (owner, 2026-11-15): the State label the LIVE Parcoursup fiche prints, as ONE badge
// (reconnaissance.py: the label verbatim beside it, the fiche fait foi), and what a year there costs (vie.py): the local rent
// of a 20 m² studio (Carte des loyers 2025) and the Crous residences, the national items of the OVE survey (2023), the fiche's
// tuition fees verbatim. Ranges, each line with its source; always an estimation, never a promise or a family's budget.
// lot 1, PR 12: the latest campaign's formations absent from the latest Parcoursup map (liste.absentes, the rule of « Avant
// de confirmer »): the search card and the formation page say « vérifiez qu'elle existe toujours », never « fermée »
let ABS = null, ABS_P = null;
function absLoad() {
  if (!ABS_P) ABS_P = api("/api/carte/absentes").then((d) => { ABS = { session: d.carte_session, codes: new Set(d.codes || []) }; return ABS; })
    .catch(() => { ABS_P = null; return null; });
  return ABS_P;
}
const absenteText = (session) => `Absente de la carte des formations Parcoursup ${session} : vérifiez sur Parcoursup qu'elle existe toujours.`;
function absBadge(cod) {
  return ABS && ABS.session && ABS.codes.has(String(cod)) ? `<span class="badge warnb" title="${esc(absenteText(ABS.session))}">absente de la carte ${esc(ABS.session)}</span>` : "";
}
let RECO = null, RECO_P = null;
function recoLoad() {
  if (RECO) return Promise.resolve(RECO);
  if (!RECO_P) {
    RECO_P = api("/api/reconnaissance").then((d) => {
      const cat = {};
      for (const [k, v] of Object.entries(d.codes || {})) for (const c of String(v).split(",")) if (c) cat[c] = k;
      const ens = (x) => new Set(String(x || "").split(",").filter(Boolean));
      const t = d.tension || {};
      RECO = { cat, sans: ens(d.sans_bourse), frais: d.frais || {}, lib: d.categories || {}, exp: d.explications || {},
        // sprint V2: the formations of strong demand (tension.py) and those that can be done as an apprentice (apprentissage.py)
        tres: ens(t.tres), tresLib: t.libelle || "Forte demande", tresExp: t.explication || "", app: ens(d.apprentissage),
        // owner, 2026-11-17: both robustesse repères of every formation (robustesse_formation.compact), for Mes vœux
        rob: robDecode(d.robustesse) };
      return RECO;
    }).catch(() => { RECO_P = null; return null; });
  }
  return RECO_P;
}
function robDecode(r) {
  const out = { filiere: {}, national: {}, raison: {}, apres: {}, herite: {}, voisine: {}, certification: {} };
  for (const k of Object.keys(out)) {
    for (const [lv, codes] of Object.entries((r || {})[k] || {})) for (const c of String(codes).split(",")) if (c) out[k][c] = lv;
  }
  // owner, 2026-11-22: the five-level scale, a code listed under EACH of its levels (between two: both), known keys only
  out.echelle = {};
  for (const [lv, codes] of Object.entries((r || {}).echelle || {})) {
    if (echIdx(lv) < 0) continue;
    for (const c of String(codes).split(",")) if (c) (out.echelle[c] = out.echelle[c] || []).push(lv);
  }
  // Codex (PR #84): an empty payload (tables or sidecar missing) decodes to empty maps: usable only with at least one level
  out.ok = Object.keys(out.filiere).length > 0 || Object.keys(out.national).length > 0 || Object.keys(out.echelle).length > 0;
  return out;
}
// Mes vœux (owner, 2026-11-17): each vœu's zone for the profile and its two robustesse repères SIDE BY SIDE, never merged into
// one mark: the zone speaks of admission, the repères of the jobs after it. Nothing is sorted by either.
const ROB_WORD = { haut: "parmi les 20 % les plus robustes", moyen: "dans la moyenne", bas: "parmi les 20 % les moins robustes" };
const ROB_RAISON = { memes_debouches: "non classée : mêmes métiers que sa filière", trop_peu: "trop peu de formations comparables" };
function robVoeuxCard(rows, zoneOf) {
  const R = RECO && RECO.rob;
  if (!R || !rows.length) return "";
  const cell = (cod, k) => {
    const lv = R[k][cod];
    if (lv) return `<span class="rob-lv rob-${esc(lv)}">${esc(ROB_WORD[lv] || "")}</span>${k === "national" && R.apres[cod] ? `<div class="muted small">${R.apres[cod] === "master" ? "métiers après un master" : "métiers après d'autres études"}</div>` : ""}`;
    if (k === "filiere" && R.raison[cod]) return `<span class="muted small">${esc(ROB_RAISON[R.raison[cod]] || "")}</span>`;
    return '<span class="muted small">pas d\'estimation</span>';
  };
  const any = rows.some((v) => R.echelle[v.cod_aff_form]);
  if (!any) return "";
  const zcol = typeof zoneOf === "function";
  // owner, 2026-11-22: one level per vœu (the five-level scale), the filière repère stays on the formation's page
  const level = (cod) => (R.echelle[cod] ? `<strong>${esc(echelleWords(R.echelle[cod]))}</strong> ${echelleJauge(R.echelle[cod])}${R.apres[cod] ? `<div class="muted small">${R.apres[cod] === "master" ? "métiers après un master" : "métiers après d'autres études"}</div>` : ""}`
    : cell(cod, "national"));
  const body = rows.map((v) => `<tr><td data-label="Formation">${v.status === "absente" ? `<span class="muted">Formation ${esc(v.cod_aff_form)}</span>` : `<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement || v.cod_aff_form)}</a><div class="muted small">${esc(v.filiere || v.formation || "")}${v.complement ? ` · ${esc(v.complement)}` : ""}</div>`}</td>
      ${zcol ? `<td data-label="Zone pour votre profil">${zoneOf(v)}</td>` : ""}
      <td data-label="Robustesse 2035">${level(v.cod_aff_form)}</td></tr>`).join("");
  return `<section class="card" id="vx-robustesse"><h2>Admission et avenir des métiers, côte à côte</h2>
    <p class="small">${zcol ? "Pour chaque vœu, la zone dit où se situe votre profil parmi les admis. " : ""}La robustesse 2035 dit, en cinq niveaux parmi les formations Parcoursup, si les métiers auxquels mène la formation devraient garder de la valeur entre 2030 et 2035. ${zcol ? "Les deux ne sont jamais réunis en une seule note." : ""} ${estimTag("modèle de SupCompass")}</p>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th>${zcol ? "<th>Zone pour votre profil</th>" : ""}<th>Robustesse 2035</th></tr>${body}</table></div>
    <p class="muted small">Ce ne sont ni des chances d'admission, ni des promesses d'emploi. L'ordre de la liste ne dépend d'aucun de ces repères. <a href="#/info/robustesse">Comment on calcule la robustesse</a></p></section>`;
}
function recoPill(k, lib, exp) {
  if (!k || !lib) return "";
  const icon = k === "aucun" || k === "autre" ? "" : ICONS.check;
  return `<span class="badge reco reco-${esc(k)}" title="${esc(exp || "")}">${icon}${esc(lib)}</span>`;
}
function recoBadge(cod) {                                            // the lists: nothing when the fiche was not read yet
  const k = RECO && RECO.cat[cod];
  return k ? recoPill(k, RECO.lib[k], RECO.exp[k]) : "";
}
// sprint V2: the lists say when a formation receives many vœux for its places (a fact about demand, never a chance) and when
// it can also be done as an apprentice; both are lookups by code, every string escaped
function tensionBadge(cod) {
  return RECO && RECO.tres && RECO.tres.has(cod) ? `<span class="badge tension" title="${esc(RECO.tresExp)}">${esc(RECO.tresLib)}</span>` : "";
}
function appBadge(cod) {
  return RECO && RECO.app && RECO.app.has(cod) ? '<span class="badge app" title="Cette formation se fait aussi en apprentissage : formation gratuite et salaire.">aussi en apprentissage</span>' : "";
}
function recoCard(rc) {
  if (!rc) return "";
  const lab = rc.labels.length
    ? `<p class="small">La fiche Parcoursup affiche : ${rc.labels.map((t) => `« ${esc(t)} »`).join(", ")}.</p>`
    : rc.source === "intitule" ? `<p class="small">La fiche n'affiche pas de label de l'État ; l'intitulé de la formation sur Parcoursup indique un titre professionnel.</p>` : "";
  const brs = rc.bourses === true ? "La formation ouvre droit aux bourses de l'enseignement supérieur."
    : rc.bourses === false ? "La fiche indique que la formation n'ouvre pas droit aux bourses." : "";
  return `<div class="card reco-card"><h2>Ce diplôme est-il reconnu par l'État ?</h2>
    <p>${recoPill(rc.categorie, rc.libelle, rc.explication)}</p>
    <p>${esc(rc.explication)}</p>${lab}${brs ? `<p class="small">${esc(brs)}</p>` : ""}
    <p class="muted small">Lu sur la fiche Parcoursup${rc.session ? ` de la campagne ${esc(rc.session)}` : ""}. La fiche fait foi.</p></div>`;
}
// owner, 2026-11-16: the establishment's open days (jpo.py). Dates of the season as Onisep lists them, checked on the establishment's
// own site; none this season = a PERIOD from the past seasons (« aux alentours de mi-janvier »), never a day; passed dates said
const jpoUrl = (u) => (typeof u === "string" && /^https:\/\/[^\s"'<>]+$/.test(u) ? u : null);
function jpoNext(j) {
  const today = localIso();
  return ((j && j.dates) || []).find((e) => (e.fin || e.date) >= today) || null;
}
function jpoWhen(e) {
  return e.fin ? `du ${frDate(e.date)} au ${frDate(e.fin)}` : frDate(e.date);
}
function jpoLine(j) {
  if (!j) return "";
  const n = jpoNext(j), dates = j.dates || [];
  const who = j.universite ? ` (${esc(j.universite.nom)})` : "";
  const txt = n ? `Portes ouvertes${who} : ${esc(jpoWhen(n))}${n.source === "site" ? " (site de l'établissement, à vérifier)" : ""}`
    : dates.length ? `Portes ouvertes${who} ${esc(j.saison.annees)} : déjà passées`
    : j.environ ? `Portes ouvertes${who} : ${esc(j.environ.texte)}, d'après les années passées`
    : "";
  return txt ? `<p class="small sum-jpo"><button type="button" class="linkish" data-goto="admission">${txt} →</button></p>` : "";
}
// where an open day was read, in words (one wording for the formation page, « ma liste » and « près de chez moi », PR 16)
function jpoSrc(e) {
  const fiche = e.fiche && e.source !== "fiche" && e.source !== "fiche_site" ? ", aussi sur la fiche Parcoursup de la formation" : "";
  return e.source === "onisep_site" ? `Onisep, date retrouvée sur le site de l'établissement${fiche}`
    : e.source === "onisep" ? `Onisep${fiche}`
    : e.source === "fiche" ? "fiche Parcoursup de la formation"
    : e.source === "fiche_site" ? "fiche Parcoursup de la formation, date retrouvée sur le site de l'établissement"
    : `lue sur le site de l'établissement${e.lu_le ? ` le ${esc(frDate(e.lu_le))}` : ""}, à vérifier${jpoUrl(e.site) ? ` (<a href="${esc(jpoUrl(e.site))}" target="_blank" rel="noopener">page lue ↗</a>)` : ""}`;
}
function jpoCard(j) {
  if (!j) return "";
  const today = localIso(), dates = j.dates || [];
  const noms = [...new Set((j.etablissements || []).map((e) => e.nom).filter(Boolean))];
  const src = jpoSrc;
  const li = (e) => {
    const past = (e.fin || e.date) < today;
    return `<li class="${past ? "muted" : ""}"><strong>${esc(jpoWhen(e))}</strong>${e.heures ? `, de ${esc(e.heures)}` : ""}${e.virtuel ? ", en ligne" : ""}${e.remarque ? ` (${esc(e.remarque)})` : ""}${past ? " · passée" : ""}
      <span class="small muted"> · ${src(e)}${e.source !== "site" && jpoUrl(e.voir) ? ` · <a href="${esc(jpoUrl(e.voir))}" target="_blank" rel="noopener">détails ↗</a>` : ""}</span></li>`;
  };
  // owner, 2026-11-18: the sessions on site and the online ones (webinars, virtual visits: « en virtuel » on Onisep) apart
  const surPlace = dates.filter((e) => !e.virtuel), enLigne = dates.filter((e) => e.virtuel);
  const body = dates.length ? `${surPlace.length ? `${enLigne.length ? "<h3>Sur place</h3>" : ""}<ul class="jpo-list">${surPlace.map(li).join("")}</ul>` : ""}
    ${enLigne.length ? `<h3>En ligne (webinaires, visites virtuelles)</h3><ul class="jpo-list">${enLigne.map(li).join("")}</ul>` : ""}`
    : j.environ ? `<p>Aucune date n'est encore annoncée pour ${esc(j.saison.annees)}. Les années passées (${esc(j.environ.annees.join(", "))}), elles ont eu lieu <strong>${esc(j.environ.texte)}</strong>.</p>
      <p class="small">C'est une période, pas une date : à confirmer sur le site de l'établissement.</p>`
    : `<p class="muted">Aucune date n'est publiée pour l'instant, ni par l'Onisep ni sur le site de l'établissement.</p>`;
  const links = (j.etablissements || []).filter((e) => jpoUrl(e.onisep_url))
    .map((e) => `<a href="${esc(jpoUrl(e.onisep_url))}" target="_blank" rel="noopener">fiche Onisep${noms.length > 1 && e.nom ? ` (${esc(e.nom)})` : ""} ↗</a>`);
  const sites = (j.sites_verifies || []).filter((x) => jpoUrl(x.url));
  return `<div class="card" id="jpo"><h2>Portes ouvertes et webinaires</h2>
    ${j.universite ? `<p>Aucune date propre à cette formation n'est publiée. Voici les portes ouvertes de son université : <strong>${esc(j.universite.nom)}</strong>.</p>`
      : noms.length ? `<p class="small">Établissement : ${noms.map(esc).join(" ; ")}. Les portes ouvertes concernent tout l'établissement.</p>` : ""}
    ${body}
    ${jpoConcours(j.concours, today)}
    <p class="muted small">Dates retenues entre le ${esc(frDate(j.saison.debut))} et le ${esc(frDate(j.saison.fin))}. Source : Onisep, Idéo-Structures (licence ODbL)${links.length ? ` · ${links.join(" · ")}` : ""}${dates.some((e) => e.fiche) ? ", et la fiche Parcoursup de la formation" : ""}.${sites.length ? ` Site de l'établissement consulté le ${esc(frDate(sites[0].checked))}.` : ""} Vérifiez la date sur le site de l'établissement avant de vous déplacer.</p></div>`;
}
// sprint 4 (owner, 2026-11-21): « La formation me plaira-t-elle ? ». What the fiche's OWN texts say of immersions and mini-stages
// (immersion.py: sentences verbatim, with where they were found), and whether it gives a student ambassador's contact
// (handicap.py: never the contact itself). Never a date computed, never a promise that a day exists: ask the formation.
const ficheLink = (u) => (typeof u === "string" && /^https:\/\/[a-z0-9.-]*parcoursup\.fr\/[^\s"'<>]*$/.test(u) ? u : null);
function ficheCredit(x) {
  return `Lu sur la fiche Parcoursup${x.session ? ` de la campagne ${esc(x.session)}` : ""}${x.lu_le ? `, le ${esc(frDate(x.lu_le))}` : ""}. La fiche fait foi.`;
}
function decouvrirCard(im, ha) {
  const ph = (im && im.phrases) || [];
  const amb = ha && ha.ambassadeur === true;
  if (!ph.length && !amb) return "";
  const q = (x) => `<li><blockquote class="imm-q">« ${esc(x.texte)} »</blockquote><span class="small muted">${esc(x.label)}</span></li>`;
  const shown = ph.slice(0, 2), rest = ph.slice(2);
  const src = im || ha;
  const url = ficheLink(src.url);
  return `<div class="card" id="decouvrir"><h2>Découvrir la formation de l'intérieur</h2>
    ${ph.length ? `<h3>Immersions et mini-stages</h3>
    <p class="small">Voici ce que la fiche de la formation en dit, mot pour mot.</p>
    <ul class="imm-list">${shown.map(q).join("")}</ul>
    ${rest.length ? `<details><summary class="small">${rest.length === 1 ? "Une autre phrase de la fiche" : `${rest.length} autres phrases de la fiche`}</summary><ul class="imm-list">${rest.map(q).join("")}</ul></details>` : ""}
    <p class="small">Pour savoir s'il y en a cette année et comment s'inscrire, contactez la formation : ses coordonnées sont sur sa fiche Parcoursup.</p>` : ""}
    ${amb ? `<h3>Parler à un étudiant</h3><p class="small">La fiche donne le contact d'un étudiant ambassadeur de la formation. Il peut vous dire comment se passent les cours et la vie sur place.</p>` : ""}
    <p class="muted small">${ficheCredit(src)}${url ? ` <a href="${esc(url)}" target="_blank" rel="noopener">Ouvrir la fiche ↗</a>` : ""}</p></div>`;
}
// sprint 4 (owner, 2026-11-21): « Serai-je accompagné ? ». What the fiche prints about disability support (handicap.py): its
// sentence verbatim, whether it names a disability referent (the contact stays on the fiche: an address may name a person),
// the establishment's own pages on disability. The site never asks the student about a disability: the card is the same for all.
function handicapCard(ha) {
  if (!ha || (!ha.handicap && ha.referent == null && !(ha.infos || []).length)) return "";
  const url = ficheLink(ha.url);
  const ref = ha.referent === true
    ? `<p>La fiche donne le contact d'un <strong>référent handicap</strong>. C'est la personne à qui parler de vos besoins, avant ou après votre admission.</p>`
    : ha.referent === false ? `<p>La fiche n'indique pas de référent handicap. Les coordonnées de l'établissement sont sur la fiche : vous pouvez lui poser vos questions.</p>` : "";
  const web = (u) => (typeof u === "string" && /^https?:\/\/[^\s"'<>]+$/.test(u) ? u : null);
  const lien = (u) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace(/^https?:\/\//, "").slice(0, 60))}${u.length > 68 ? "…" : ""} ↗</a>`;
  const infos = (ha.infos || []).map((x) => {
    const ls = (x.liens || []).map(web).filter(Boolean);
    const t = x.texte && !/^https?:\/\/\S+$/.test(x.texte) ? `« ${esc(x.texte)} »` : "";
    return t || ls.length ? `<li>${t}${ls.length ? ` ${ls.map(lien).join(" ")}` : ""}</li>` : "";
  }).join("");
  return `<div class="card" id="handicap"><h2>Situation de handicap&nbsp;: être accompagné</h2>
    ${ha.handicap ? `<blockquote class="imm-q">« ${esc(ha.handicap)} »</blockquote>` : ""}
    ${ref}
    ${infos ? `<p class="small">L'établissement donne aussi ces informations :</p><ul class="small imm-list">${infos}</ul>` : ""}
    <p class="small">Le contact est sur la fiche Parcoursup, dans l'onglet « Contacter et échanger avec l'établissement ».${url ? ` <a href="${esc(url)}" target="_blank" rel="noopener">Ouvrir la fiche ↗</a>` : ""}</p>
    <p class="muted small">SupCompass ne vous demande jamais si vous êtes en situation de handicap : cette carte est la même pour tous. ${ficheCredit(ha)}</p></div>`;
}
// owner, 2026-11-18: a formation recruited through a concours: the concours's own webinars and information days, read on its
// OFFICIAL site (jpo.CONCOURS), each with the page read and its day, « à vérifier »; no site read = no link, never a guess
const JPO_KIND = { en_ligne: "en ligne (webinaire)", information: "journée ou réunion d'information" };
function jpoConcours(k, today) {
  if (!k) return "";
  const site = jpoUrl(k.site);
  const li = (e) => `<li class="${e.passee ? "muted" : ""}"><strong>${esc(frDate(e.date))}</strong>, ${esc(JPO_KIND[e.kind] || "")}${e.passee ? " · passée" : ""}
      <span class="small muted"> · lue sur le site du concours le ${esc(frDate(e.lu_le))}, à vérifier${jpoUrl(e.url) ? ` (<a href="${esc(jpoUrl(e.url))}" target="_blank" rel="noopener">page lue ↗</a>)` : ""}</span></li>`;
  return `<h3>Le ${esc(k.nom)}</h3>
    <p class="small">Cette formation recrute par le ${esc(k.nom)}, commun à plusieurs écoles : il organise aussi ses propres webinaires et journées d'information.</p>
    ${(k.dates || []).length ? `<ul class="jpo-list">${k.dates.map(li).join("")}</ul>`
      : `<p class="small muted">Aucune date de webinaire ou de journée d'information n'a été trouvée pour l'instant${site ? " sur le site officiel du concours" : ""}.</p>`}
    ${site ? `<p class="small"><a href="${esc(site)}" target="_blank" rel="noopener">Site officiel du ${esc(k.nom)} ↗</a>${k.lu_le ? ` <span class="muted">(consulté le ${esc(frDate(k.lu_le))})</span>` : ""}</p>` : ""}`;
}
// PR 16 (owner, 2026-11-27): « Portes ouvertes et webinaires de ma liste ». The formation page's blocks (jpo.for_list = for_formation
// for each code), coming dates only, ONE line per establishment, day and kind with the formations of the list it concerns; the
// concours's sessions once; an .ics file of the same dates. The list's codes only are sent (no-store, no audience event).
const JPO_KIND_LINE = (e) => (e.virtuel ? "en ligne" : "sur place");
const JPO_LISTE_FIRST = 5;        // the next five dates shown, the others folded (a phone page stays short: X7)
function jpoListeEvents(L, today) {
  const ev = new Map();
  for (const f of L.formations || []) {
    const j = f.jpo;
    if (!j) continue;
    for (const e of j.dates || []) {
      if ((e.fin || e.date) < today) continue;
      const k = `${e.uai}|${e.date}|${e.virtuel ? 1 : 0}`;
      if (!ev.has(k)) ev.set(k, { e, nom: (j.universite && j.universite.nom) || e.nom || f.etablissement || "l'établissement", universite: !!j.universite, forms: [] });
      ev.get(k).forms.push(f);
    }
  }
  return [...ev.values()].sort((a, b) => (a.e.date < b.e.date ? -1 : a.e.date > b.e.date ? 1 : a.nom < b.nom ? -1 : 1));
}
function jpoListeCard(L, ids) {
  const today = localIso(), evs = jpoListeEvents(L, today), fs = L.formations || [];
  const withDate = fs.filter((f) => f.jpo && (f.jpo.dates || []).some((e) => (e.fin || e.date) >= today));
  const without = fs.filter((f) => !withDate.includes(f));
  const fname = (f) => `<a href="#/f/${esc(f.cod_aff_form)}">${esc(f.formation || f.cod_aff_form)}</a>${f.etablissement ? ` <span class="muted">(${esc(f.etablissement)})</span>` : ""}`;
  const line = (x) => `<li><strong>${esc(jpoWhen(x.e))}</strong>, ${JPO_KIND_LINE(x.e)}${x.e.heures ? `, de ${esc(x.e.heures)}` : ""}${x.e.remarque ? ` (${esc(x.e.remarque)})` : ""} · ${esc(x.nom)}${x.universite ? " (portes ouvertes de l'université)" : ""}
      <br><span class="small">Pour : ${x.forms.map(fname).join(" ; ")}</span>
      <br><span class="small muted">${jpoSrc(x.e)}${x.e.source !== "site" && jpoUrl(x.e.voir) ? ` · <a href="${esc(jpoUrl(x.e.voir))}" target="_blank" rel="noopener">détails ↗</a>` : ""}</span></li>`;
  const conc = Object.values(L.concours || {});
  const coming = conc.reduce((n, k) => n + (k.dates || []).filter((e) => e.date >= today).length, 0);
  const sans = without.map((f) => {
    const env = f.jpo && f.jpo.environ;
    return `<li>${fname(f)} : ${env ? `aucune date annoncée ; les années passées, <strong>${esc(env.texte)}</strong> (une période, à confirmer)` : (f.jpo && (f.jpo.dates || []).length ? "portes ouvertes déjà passées cette saison" : "aucune date publiée pour l'instant")}</li>`;
  }).join("");
  const q = new URLSearchParams({ ids: ids.join(",") });
  return `<section class="card" id="vx-jpo"><h2>Portes ouvertes et webinaires de ma liste</h2>
    <p>${fmt(withDate.length)} formation${withDate.length > 1 ? "s" : ""} de votre liste sur ${fmt(fs.length)} ${withDate.length > 1 ? "ont" : "a"} une date à venir cette saison (${esc(L.saison.annees)}).</p>
    ${evs.length ? `<ul class="jpo-list">${evs.slice(0, JPO_LISTE_FIRST).map(line).join("")}</ul>` : ""}
    ${evs.length > JPO_LISTE_FIRST ? `<details><summary class="small">Voir les ${fmt(evs.length - JPO_LISTE_FIRST)} autres dates</summary><ul class="jpo-list">${evs.slice(JPO_LISTE_FIRST).map(line).join("")}</ul></details>` : ""}
    ${sans ? `<details${evs.length ? "" : " open"}><summary class="small">Sans date à venir (${fmt(without.length)})</summary><ul class="small">${sans}</ul></details>` : ""}
    ${conc.map((k) => `${jpoConcours(k, today)}<p class="small">Formations de votre liste concernées : ${k.formations.map((c) => fname(fs.find((f) => f.cod_aff_form === c) || { cod_aff_form: c })).join(" ; ")}.</p>`).join("")}
    <div class="toolbar no-print">${evs.length || coming ? `<a class="btnlink" href="/api/jpo/liste.ics?${q}" download>Ajouter ces dates à mon agenda (.ics)</a>` : ""}<a href="#/portes-ouvertes">Toutes les portes ouvertes près de chez moi</a></div>
    <p class="muted small">Sources : Onisep, Idéo-Structures (licence ODbL), la fiche Parcoursup de la formation, le site de l'établissement et celui du concours. Vérifiez la date sur le site de l'établissement avant de vous déplacer. Pour lire ces dates, la page envoie seulement les codes des formations de votre liste ; rien n'en est enregistré.</p></section>`;
}
async function loadJpoListe(ids, marker) {
  const box = $view.querySelector("#vx-jpo");
  let L;
  try {
    L = await api(`/api/jpo/liste?${new URLSearchParams({ ids: ids.join(",") })}`);
  } catch (e) {
    if ($view.dataset.rendered === marker && box && box.isConnected) box.remove();
    return;
  }
  if ($view.dataset.rendered !== marker || !box || !box.isConnected) return;   // the student left or changed the list meanwhile
  box.outerHTML = jpoListeCard(L, ids);
}

// PR 16 (owner, 2026-11-27): « Portes ouvertes et webinaires près de chez moi ». Every open day of the season (jpo.agenda, built
// at build: one event per establishment, day and kind, the formations it concerns), read once; the town is the one entered in
// « Mon profil » and NEVER sent (the distance is computed here); an online session is shown whatever the distance; the list is
// sorted by date, then distance, never by a figure; the coverage printed is the one measured at build.
const PO_KM = [20, 50, 100, 200, 0];
const PO_PAGE = 40;
const poUI = { km: 50, type: "tous", periode: "avenir", q: "", n: PO_PAGE };
function poKeep(x, A, home, F, today) {
  if (F.periode === "avenir" && (x.fin || x.date) < today) return false;
  if (F.type === "place" && x.virtuel) return false;
  if (F.type === "ligne" && !x.virtuel) return false;
  if (F.q) {
    const q = foldText(F.q);
    if (!x.formations.some((c) => foldText(((A.formations[c] || [])[0]) || "").includes(q)) && !foldText(x.nom || "").includes(q)) return false;
  }
  if (!x.virtuel && home && F.km) {
    const near = poNearest(x, home);
    if (!near || near.km > F.km) return false;
  }
  return true;
}
// the nearest place of the formations an event concerns (Codex, PR 16: a university's day concerns campuses in other towns)
function poNearest(x, home) {
  const lieux = (x.lieux && x.lieux.length) ? x.lieux : (x.lat != null ? [[x.lat, x.lon, x.ville]] : []);
  let best = null;
  for (const [lat, lon, ville] of lieux) {
    const km = haversineKm(home.lat, home.lon, lat, lon);
    if (!best || km < best.km) best = { km, ville };
  }
  return best;
}
// the concours's sessions under the same filters (Codex, PR 16): period, type (a « journée d'information » is not online), formation
const poConcQ = (k, F) => !F.q || foldText(k.nom || "").includes(foldText(F.q)) || (k.libelles || []).some((l) => foldText(l).includes(foldText(F.q)));
function poConcKeep(k, F, today) {
  if (!poConcQ(k, F)) return [];
  return (k.dates || []).filter((e) => !(F.periode === "avenir" && e.date < today) && !(F.type === "place" && e.kind === "en_ligne")
    && !(F.type === "ligne" && e.kind !== "en_ligne"));
}
// PR 19 (owner, 2026-11-28): « Après le 1er juin ». The answers' meaning and the deadlines are QUOTED from official pages (the
// calendar PDF's sentences, service-public's « Première inscription » read by aides.r_reponses); what SupCompass adds is said as
// its own. Per vœu only its name and a link to its own page (how far its list was called): never a rank asked, no depth beside
// the list. The complementary phase: the official live list first, then the formations that admitted in it in the latest
// campaign (the search page's filter) with how often that repeated, measured (counts, never a promise of places).
const AJ_PC_SEARCH = `#/recherche/${encodeURIComponent("f_complementaire=oui")}`;
const AJ_SANS_PROPOSITION = "https://www.parcoursup.gouv.fr/contenus/les-solutions-si-vous-n-avez-pas-recu-de-proposition-d-admission-3456";
// the calendar prints the year once, at the range's end (« Entre le vendredi 4 juin et le lundi 7 juin 2027 inclus »)
const ajDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
function ajQuote(t) { return `<blockquote class="quote">« ${esc(t)} »</blockquote>`; }
function ajReponses(R) {
  if (!R || !(R.items || []).length) {
    return `<p class="warn">La page officielle qui explique les réponses n'a pas pu être lue ici. Lisez-la sur <a href="https://www.service-public.gouv.fr/particuliers/vosdroits/F2861" target="_blank" rel="noopener">service-public.gouv.fr ↗</a>.</p>`;
  }
  return `<dl class="aj-rep">${R.items.map((x) => `<div><dt>${esc(x.reponse)}</dt><dd>${(x.texte || []).map((t) => `<p>${esc(t)}</p>`).join("")}</dd></div>`).join("")}</dl>
    ${(R.notes || []).map((t) => `<p class="small">${esc(t)}</p>`).join("")}
    <p class="muted small">Citation de la page officielle « ${esc(R.titre || "Première inscription")} » de service-public.gouv.fr${R.verifie ? `, vérifiée le ${esc(R.verifie)}` : ""}. <a href="${esc(/^https:\/\/www\.service-public\.gouv\.fr\//.test(R.source || "") ? R.source : "https://www.service-public.gouv.fr/particuliers/vosdroits/F2861")}" target="_blank" rel="noopener">Lire la page ↗</a> En cas de différence, Parcoursup fait foi.</p>`;
}
function ajPersistance(P) {
  if (!P) return "";
  return `<p class="small">Pour préparer : <a href="${AJ_PC_SEARCH}">les ${fmt(P.derniere.avec_pc)} formations</a> (sur ${fmt(P.derniere.formations)}) qui ont admis des candidats en phase complémentaire en ${esc(P.derniere.session)}.</p>
    <p class="small">Parmi les formations qui en avaient admis en ${esc(P.avant)}, <strong>${fmt(P.avec.part, 1)} %</strong> (${fmt(P.avec.encore)} sur ${fmt(P.avec.n)}) en ont encore admis en ${esc(P.apres)}. Parmi les autres, ${fmt(P.sans.part, 1)} % (${fmt(P.sans.puis)} sur ${fmt(P.sans.n)}).${estimTag("calcul de SupCompass à partir des admis publiés par le ministère", true)}</p>
    <p class="muted small">Ce sont des admis des années passées, pas des places cette année : seule la liste de Parcoursup dit où il reste des places.</p>`;
}
async function viewApresJuin() {
  const marker = "apres-juin";
  $view.dataset.rendered = marker;
  $view.innerHTML = `<div class="card"><h1>Après le 1er juin : les réponses des formations</h1><p class="muted small">Chargement…</p></div>`;
  const ids = voeux.get();
  const [d, L] = await Promise.all([api("/api/apres-juin"), ids.length ? api(`/api/apres-juin/voeux?ids=${ids.join(",")}`).catch(() => null) : null]);
  if ($view.dataset.rendered !== marker) return;
  const today = localIso(), g = d.regles || {};
  const ev = (k) => (d.evenements || []).find((e) => e.key === k);
  const when = (e) => (!e || !e.verifie ? "date à vérifier sur parcoursup.gouv.fr" : e.fin ? `du ${frDate(e.debut)} au ${frDate(e.fin)}` : frDate(e.debut));
  const STATE = { passe: "passé", en_cours: "en cours", a_venir: "à venir", inconnu: "date à vérifier" };
  const dates = (d.evenements || []).map((e) => `<li class="cal-item cal-${calState(e, today)}"><div class="cal-when"><strong>${esc(when(e))}</strong> <span class="badge">${STATE[calState(e, today)]}</span></div><div class="cal-what aj-what">${esc(e.libelle)}</div></li>`).join("");
  const quotes = [g.oui_ouisi ? "Consultez dans votre dossier, au fur et à mesure, les propositions d'admission (Oui ou Oui-si) des formations que vous avez demandées." : "",
    g.repondre_delais ? "Faites votre choix : vous devez répondre dans les délais à chaque proposition d'admission reçue." : "",
    g.classez && ev("classement") && ev("classement").verifie ? `Entre le ${ajDay(ev("classement").debut)} et le ${frDate(ev("classement").fin)} inclus : classez vos vœux en attente.` : ""].filter(Boolean);
  const comp = ev("complementaire");
  const vx = L && (L.voeux || []).length ? `<ul class="aj-voeux">${L.voeux.map((v) => v.connu
    ? `<li><a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a> <span class="muted small">${esc(v.formation)}${v.ville ? ` · ${esc(v.ville)}` : ""}</span><br><span class="small">${v.appel ? `Sur sa fiche, onglet « Y entrer » : jusqu'où sa liste a été appelée en ${esc(v.session)}.` : "Sa fiche ne publie pas jusqu'où sa liste a été appelée."}</span></li>`
    : `<li class="muted small">Formation ${esc(v.cod_aff_form)} : introuvable dans les chiffres publiés.</li>`).join("")}</ul>`
    : `<p class="small">Votre liste est vide. <a href="#/voeux">Ouvrir Mes vœux</a></p>`;
  $view.innerHTML = `<div class="card"><h1>Après le 1er juin : les réponses des formations</h1>
    <p>Du 1er juin à septembre, les formations répondent à vos vœux sur Parcoursup. Cette page rassemble ce que disent les pages officielles, et ce que SupCompass peut ajouter.</p>
    <p class="muted small">SupCompass ne voit pas votre dossier Parcoursup. Il ne vous demande jamais votre rang. Parcoursup fait foi.</p></div>
  <section class="card"><h2>Les dates</h2><ol class="cal-list">${dates}</ol>
    ${quotes.length ? `<h3>Ce que dit le calendrier officiel</h3>${quotes.map(ajQuote).join("")}` : ""}
    <p class="muted small">Source : calendrier officiel Parcoursup ${esc(d.campagne - 1)}-${esc(d.campagne)}${d.lu_le ? `, lu le ${esc(frDate(d.lu_le))}` : ""}. <a href="#/calendrier">Tout le calendrier</a></p></section>
  <section class="card"><h2>Ce que veulent dire les réponses</h2>${ajReponses(d.reponses)}</section>
  <section class="card"><h2>Vos vœux</h2>
    <p class="small">Une formation appelle ses candidats dans l'ordre de son classement, au fil des places libérées. Sa fiche montre jusqu'où sa liste a été appelée les années passées. <a href="#/comprendre">Comprendre l'appel</a></p>
    ${vx}
    <p class="muted small">Ce n'est pas une prévision : SupCompass ne compare jamais ces chiffres à votre place sur une liste d'attente.</p></section>
  <section class="card"><h2>La phase complémentaire</h2>
    <p>${comp && comp.verifie ? `À partir du ${esc(frDate(comp.debut))}` : "Pendant la phase complémentaire"}, la liste officielle des formations qui ont encore des places est sur Parcoursup.${g.complementaire_max ? ` Vous pouvez y formuler jusqu'à ${fmt(g.complementaire_max)} nouveaux vœux.` : " Le nombre de nouveaux vœux possibles est sur parcoursup.gouv.fr."}</p>
    <p><a href="${esc(d.liens.parcoursup)}" target="_blank" rel="noopener">Parcoursup ↗</a> · <a href="${AJ_SANS_PROPOSITION}" target="_blank" rel="noopener">Sans proposition : les solutions officielles ↗</a></p>
    ${ajPersistance(d.persistance)}</section>
  ${nextSteps("apresjuin")}`;
}
async function viewPortesOuvertes() {
  const marker = "portes-ouvertes";
  $view.dataset.rendered = marker;
  $view.innerHTML = `<div class="card"><h1>Portes ouvertes et webinaires près de chez moi</h1><p class="muted small">Chargement des dates…</p></div>`;
  const A = await api("/api/jpo/agenda");
  if ($view.dataset.rendered !== marker) return;
  const home = villeDepart(), today = localIso();
  const evs = A.evenements || [];
  const pctCov = A.n_formations ? Math.round(1000 * A.n_avec_date / A.n_formations) / 10 : 0;
  const form = (c) => { const f = A.formations[c] || [];
    return f[1] === false ? `${esc(f[0] || c)}${/apprentissage/i.test(f[0] || "") ? "" : ' <span class="muted">(en apprentissage)</span>'}` : `<a href="#/f/${esc(c)}">${esc(f[0] || c)}</a>`; };
  const row = (x) => {
    const near = !x.virtuel && home ? poNearest(x, home) : null, km = near ? Math.round(near.km) : null;
    const past = (x.fin || x.date) < today;
    const shown = x.formations.slice(0, 3), rest = x.formations.slice(3);
    return `<li class="${past ? "muted" : ""}"><strong>${esc(jpoWhen(x))}</strong> <span class="badge">${JPO_KIND_LINE(x)}</span>${past ? " · passée" : ""}${x.heures ? `, de ${esc(x.heures)}` : ""}${x.remarque ? ` (${esc(x.remarque)})` : ""}
      <br>${esc(x.nom || "")}${x.universite ? " (portes ouvertes de l'université)" : ""}${near && near.ville ? ` · ${esc(near.ville)}` : x.ville ? ` · ${esc(x.ville)}` : ""}${km != null ? ` · ${fmt(km)} km de chez vous` : ""}
      <br><span class="small">Pour : ${shown.map(form).join(" ; ")}${rest.length ? ` <details class="po-more"><summary class="small">et ${fmt(rest.length)} autre${rest.length > 1 ? "s" : ""}</summary>${rest.map(form).join(" ; ")}</details>` : ""}</span>
      <br><span class="small muted">${jpoSrc(x)}${x.source !== "site" && jpoUrl(x.voir) ? ` · <a href="${esc(jpoUrl(x.voir))}" target="_blank" rel="noopener">détails ↗</a>` : ""}</span></li>`;
  };
  const conc = Object.values(A.concours || {}).filter((k) => (k.dates || []).length || jpoUrl(k.site));
  const draw = () => {
    if ($view.dataset.rendered !== marker) return;
    const kept = evs.filter((x) => poKeep(x, A, home, poUI, today))
      .map((x) => ({ x, km: !x.virtuel && home ? (poNearest(x, home) || {}).km ?? null : null }))
      .sort((a, b) => (a.x.date < b.x.date ? -1 : a.x.date > b.x.date ? 1 : (a.km ?? 1e9) - (b.km ?? 1e9) || (a.x.nom < b.x.nom ? -1 : 1)));
    const list = document.getElementById("po-list");
    if (!list) return;
    list.innerHTML = kept.length ? `<p class="small" role="status">${fmt(kept.length)} journée${kept.length > 1 ? "s" : ""} correspondant à vos critères.</p><ul class="jpo-list">${kept.slice(0, poUI.n).map((k) => row(k.x)).join("")}</ul>${kept.length > poUI.n ? '<button type="button" id="po-more">Voir les suivantes</button>' : ""}`
      : '<p class="muted" role="status">Aucune date ne correspond. Élargissez la distance ou la période.</p>';
    const more = document.getElementById("po-more");
    if (more) more.onclick = () => { poUI.n += PO_PAGE; draw(); };
    const cbox = document.getElementById("po-conc");
    if (cbox) {
      const shown = conc.map((k) => ({ k, dates: poConcKeep(k, poUI, today) })).filter((c) => c.dates.length || (!(c.k.dates || []).length && poConcQ(c.k, poUI)));   // no date at all: its site, as before
      cbox.innerHTML = shown.length ? shown.map(({ k, dates }) => `${jpoConcours({ ...k, dates: dates.map((e) => ({ ...e, passee: e.date < today })) }, today)}<p class="small">${fmt(k.formations.length)} formation${k.formations.length > 1 ? "s" : ""} recrute${k.formations.length > 1 ? "nt" : ""} par ce concours.</p>`).join("")
        : '<p class="muted small">Aucune session de concours ne correspond à vos critères.</p>';
    }
  };
  const sel = (id, label, opts, v) => `<label class="po-f">${label} <select id="${id}">${opts.map(([k, t]) => `<option value="${k}"${String(k) === String(v) ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
  $view.innerHTML = `<div class="card"><h1>Portes ouvertes et webinaires près de chez moi</h1>
    <p>${home ? `Autour de <strong>${esc(villeLabel(home))}</strong>, la ville de <a href="#/profil">Mon profil</a>.` : `Indiquez votre ville dans <a href="#/profil">Mon profil</a> pour voir les plus proches : en attendant, toutes les dates sont listées.`} Les sessions en ligne sont montrées quelle que soit la distance.</p>
    <div class="toolbar po-filters no-print">${home ? sel("po-km", "Distance", PO_KM.map((k) => [k, k ? `${k} km` : "Toute la France"]), poUI.km) : ""}
      ${sel("po-type", "Type", [["tous", "Sur place et en ligne"], ["place", "Sur place"], ["ligne", "En ligne"]], poUI.type)}
      ${sel("po-periode", "Période", [["avenir", "À venir"], ["saison", `Toute la saison ${A.saison ? A.saison.annees : ""}`]], poUI.periode)}
      <label class="po-f">Formation <input type="search" id="po-q" value="${esc(poUI.q)}" placeholder="BTS, licence, infirmier…" autocomplete="off"></label></div>
    <p class="muted small">${A.n_formations ? `Une date est publiée pour ${fmt(A.n_avec_date)} formations sur ${fmt(A.n_formations)} (${String(pctCov).replace(".", ",")} %) cette saison. Les autres n'en ont pas encore annoncé.` : "Les dates ne sont pas encore disponibles."} Votre ville reste dans ce navigateur : la distance, à vol d'oiseau, est calculée ici.</p></div>
  <section class="card"><h2>Les journées</h2><div id="po-list"></div>
    <p class="muted small">Une ligne par établissement, jour et type. Une université sans date propre à une formation montre les siennes. Sources : Onisep, Idéo-Structures (licence ODbL), la fiche Parcoursup de la formation et le site de l'établissement${A.aujourdhui ? `, lus au plus tard le ${esc(frDate(A.aujourdhui))}` : ""}. Vérifiez la date sur le site de l'établissement avant de vous déplacer.</p></section>
  ${conc.length ? `<section class="card"><h2>Concours : webinaires et journées d'information</h2><div id="po-conc"></div><p class="muted small">Les mêmes critères de type, de période et de formation s'appliquent ; un concours vaut pour toute la France.</p></section>` : ""}`;
  const bind = (id, key, num) => { const el = document.getElementById(id); if (el) el.onchange = el.oninput = () => { poUI[key] = num ? Number(el.value) : el.value; poUI.n = PO_PAGE; draw(); }; };
  bind("po-km", "km", true); bind("po-type", "type"); bind("po-periode", "periode"); bind("po-q", "q");
  draw();
}
const euros = (x) => `${fmt(x)} €`;
const eurosRange = (a, b) => (a === b ? euros(a) : `${fmt(a)} à ${fmt(b)} €`);
// audit PR 7: a fiche that writes its fees in words (no plain sum) is never a dash: the tile says where to read them
const fraisALire = (fr) => !!(fr && (fr.montant === null || fr.montant === undefined) && (fr.lignes || []).length);
// a bare number ("9000") is in euros: the fiche says « sauf indication contraire les sommes indiquées sont en euros »
const fraisTexte = (t) => (/^\s*\d{1,3}(?:[\s\u00a0\u202f.]\d{3})*\s*$|^\s*\d+\s*$/.test(t || "") ? `${fmt(Number(String(t).replace(/\D/g, "")))} €` : t || "");
function coutFraisValue(fr) {
  if (fr && fr.montant !== null && fr.montant !== undefined) return `${euros(fr.montant)} par an`;
  return fraisALire(fr) ? "À lire ci-dessous" : "—";
}
function coutFraisNote(fr) {
  if (!fr) return "fiche pas encore lue";
  if (fraisALire(fr)) return "la fiche les écrit en toutes lettres";
  if (fr.montant === null || fr.montant === undefined) return "aucun montant sur la fiche";
  return "selon la fiche Parcoursup";
}
// lot 1, PR 12: a fee « pour la formation continue » says whom it concerns (Sarah read « 9 000 € » as hers); our own words,
// never an amount, an age or a condition (the audit PR 6 rule for adults): the formation says which tariff applies
const FC_RE = /formation continue/i;
const FC_NOTE = "Formation continue : ces frais concernent les personnes inscrites au titre de la formation professionnelle, pas les élèves de terminale. Si vous reprenez vos études, demandez à la formation lequel de ses tarifs s'applique à vous. Un conseiller en évolution professionnelle peut vous aider à chercher un financement.";
const fcNote = (fr) => (fr && (fr.lignes || []).some((l) => FC_RE.test(`${l.rubrique} ${l.texte}`))
  ? `<p class="small fc-note">${FC_NOTE} <a href="#/info/aide">Se faire aider</a></p>` : "");
function coutCard(v, r) {
  if (!v) return `<div class="card"><h2>Combien coûte une année ici ?</h2><p class="muted small">Pas encore de données sur le coût de la vie pour cette formation.</p></div>`;
  const fr = v.frais, m = v.mensuel, an = v.annuel, lo = v.loyer;
  const tiles = `<div class="sum-grid cout-tiles">
    <div class="sum-tile"><span class="sum-label">Par mois sur place</span><span class="sum-value">${m ? eurosRange(m.min, m.max) : "—"}</span><span class="sum-note">${m ? `logement, courses, transports… ${estimTag("loyer local + moyennes nationales")}` : "loyer de la commune non publié"}</span></div>
    <div class="sum-tile"><span class="sum-label">Frais de la formation</span><span class="sum-value">${coutFraisValue(fr)}</span><span class="sum-note">${coutFraisNote(fr)}</span></div>
    <div class="sum-tile"><span class="sum-label">Sur une année (${esc(v.mois)} mois)</span><span class="sum-value">${an ? eurosRange(an.min, an.max) : "—"}</span><span class="sum-note">${an ? `vie sur place, frais${an.cvec ? " et CVEC" : ""} ${estimTag("somme des lignes ci-dessous")}` : m && fraisALire(fr) ? "les frais sont à lire sur la fiche : pas de total" : "il manque une partie du calcul"}</span></div>
  </div>`;
  const fraisHtml = fr ? `<h3>${esc(fr.titre || "Frais de scolarité")}</h3>
    <ul class="small cout-frais">${fr.lignes.map((l) => `<li><strong>${esc(l.rubrique)}</strong> : ${esc(fraisTexte(l.texte))}</li>`).join("")}${fr.cvec ? `<li>${esc(v.cvec.texte)} <a href="${esc(v.cvec.url)}" target="_blank" rel="noopener">En savoir plus ↗</a></li>` : ""}</ul>
    ${fcNote(fr)}
    <p class="muted small">Recopié de la fiche Parcoursup, qui fait foi.</p>` : "";
  const loyerRow = lo ? `<tr><td>Loyer d'un studio de ${esc(v.studio_m2)} m² ${lo.maille ? '<span class="badge warnb" title="Peu d\'annonces dans cette commune : le loyer est estimé à partir des communes voisines.">peu d\'annonces</span>' : ""}</td>
      <td class="num" data-label="Par mois">${eurosRange(lo.min, lo.max)}</td>
      <td data-label="D'où vient ce chiffre" class="small">Loyer des annonces à ${esc(lo.commune)} : ${fmt(lo.bas_m2)} à ${fmt(lo.haut_m2)} € le m² charges comprises (${fmt(lo.m2)} € en moyenne), carte des loyers 2025 ${estimTag("× " + v.studio_m2 + " m²")}</td></tr>`
    : `<tr><td>Loyer</td><td class="num" data-label="Par mois">—</td><td data-label="D'où vient ce chiffre" class="small">Pas de loyer publié pour cette commune.</td></tr>`;
  const posteRow = (p) => `<tr><td>${esc(p.poste)}${p.inclus === "selon" ? ' <span class="badge">selon votre situation</span>' : ""}</td>
      <td class="num" data-label="Par mois">${euros(p.montant)}</td>
      <td data-label="D'où vient ce chiffre" class="small">Moyenne nationale de l'enquête 2023 chez les ${fmt(p.part)} % d'étudiants qui ont cette dépense${p.inclus === "selon" ? " ; comptée seulement dans le haut de la fourchette" : ""}</td></tr>`;
  const table = `<h3>Vivre à ${esc(v.commune || "")}, chaque mois</h3>
    <div class="scroll"><table class="stack cout-table"><tr class="stack-head"><th>Poste</th><th class="num">Par mois</th><th>D'où vient ce chiffre</th></tr>
    ${loyerRow}${v.postes.map(posteRow).join("")}
    ${m ? `<tr class="cout-total"><td><strong>Total</strong></td><td class="num" data-label="Par mois"><strong>${eurosRange(m.min, m.max)}</strong></td><td data-label="D'où vient ce chiffre" class="small">Bas : loyer bas + les ${fmt(m.courants)} € de dépenses courantes. Haut : loyer haut + toutes les lignes ${estimTag("total")}</td></tr>` : ""}
    </table></div>
    <p class="muted small">Seul le loyer est propre à la commune. Les autres lignes sont des moyennes nationales (${esc(v.sources.ove.titre)}), pas les prix de cette ville.</p>`;
  const crous = v.crous.length ? `<h3>Se loger au Crous</h3>
    <p class="small">${fmt(v.crous_n)} résidence${v.crous_n > 1 ? "s" : ""} Crous à moins de 10 km. Les places sont attribuées sur dossier social étudiant.${v.crous_loyers ? ` Loyers écrits par le Crous dans ce rayon : ${eurosRange(Math.round(v.crous_loyers.min), Math.round(v.crous_loyers.max))} par mois (${fmt(v.crous_loyers.n)} résidence${v.crous_loyers.n > 1 ? "s" : ""} les indiquent).` : ""}</p>
    <ul class="small">${v.crous.map((c) => `<li><strong>${esc(c.nom)}</strong> · ${esc(Number(c.km).toLocaleString("fr-FR", { maximumFractionDigits: 1 }))} km${c.loyer_min ? ` · ${eurosRange(c.loyer_min, c.loyer_max)} par mois${c.loyer_date ? ` (prix écrits par le Crous au ${esc(c.loyer_date)})` : " (prix écrits par le Crous)"}` : " · loyer non indiqué"}${c.url ? ` · <a href="${esc(c.url)}" target="_blank" rel="noopener">Demander un logement ↗</a>` : ""}</li>`).join("")}</ul>`
    : `<h3>Se loger au Crous</h3><p class="small muted">Aucune résidence Crous recensée à moins de 10 km.</p>`;
  const repas = `<p class="small">${esc(v.repas_ru.texte)}${v.resto_n ? ` ${fmt(v.resto_n)} lieu${v.resto_n > 1 ? "x" : ""} de restauration du Crous à moins de 2 km.` : ""}</p>`;
  const aides = `<p class="small">Bourse, aides, exonérations : voir « Financer vos études » ci-dessous.</p>`;   // sprint F
  return `<div class="card cout-card"><h2>Combien coûte une année ici ?</h2>
    <p class="muted small">Des ordres de grandeur pour préparer votre budget, pas un devis. Chaque ligne dit d'où vient son chiffre.</p>
    ${tiles}${distanceBlock(v)}${fraisHtml}${table}${crous}${repas}${aides}
    <p class="muted small">Sources : <a href="${esc(v.sources.loyers.url)}" target="_blank" rel="noopener">${esc(v.sources.loyers.titre)} ↗</a> ; <a href="${esc(v.sources.ove.url)}" target="_blank" rel="noopener">${esc(v.sources.ove.titre)} ↗</a> ; Crous (résidences et restaurants) ; fiche Parcoursup.</p></div>`;
}

// sprint F: financing one's studies (aides.py): every amount, condition and link read from the official pages (service-public,
// etudiant.gouv.fr, CVEC), with their "vérifié le" date; the student's mention and académie are compared HERE, never sent; never
// the student's échelon (the official simulator needs the family's income), never a promise
const euroMois = (x) => `${Number(x).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} €`;
function aidesHint(a) {
  const p = bacProfile(), hints = [];
  if (p && (p.mention === "tb" || p.mention === "tbf") && a.merite) hints.push(`Votre profil indique une mention très bien : c'est l'une des conditions de l'aide au mérite.`);
  if (p && p.academie && a.academie && a.mobilite) {
    hints.push(p.academie === a.academie ? `Cette formation est dans votre académie (${esc(acadLabel(a.academie))}) : l'aide à la mobilité Parcoursup ne s'applique pas à ce vœu.`
      : `Cette formation est dans l'académie de ${esc(acadLabel(a.academie))}, pas la vôtre (${esc(acadLabel(p.academie))}) : si vous avez une bourse de lycée, l'aide à la mobilité Parcoursup peut vous concerner.`);
  }
  const m = a.mobilite, idf = (m && m.academies_idf) || [];
  if (p && m && m.complement_bp_idf && p.serie === "bp" && idf.includes(p.academie) && a.academie && !idf.includes(a.academie))
    hints.push(`Bac pro, académie d'Île-de-France, formation hors d'Île-de-France : avec une bourse de lycée, un complément de ${euros(m.complement_bp_idf)} peut s'ajouter à l'aide à la mobilité.`);
  return hints.length ? `<ul class="small aides-hints">${hints.map((h) => `<li>${h}</li>`).join("")}</ul><p class="muted small">Comparé dans ce navigateur avec votre profil : rien n'est envoyé au site.</p>` : "";
}
function aidesCard(a, v) {
  if (!a) return "";
  const b = a.bourse, ab = a.annuel_boursier, fr = v && v.frais, src = [];
  const verif = (x) => x && x.verifie ? ` (vérifié le ${esc(x.verifie)})` : "";
  const lien = (url, texte) => /^https:\/\/[a-z0-9.-]+\.gouv\.fr\//.test(url || "") ? `<a href="${esc(url)}" target="_blank" rel="noopener">${texte} ↗</a>` : "";   // official hosts only
  // lot 1, PR 12 (Sarah): outside terminale the two aids tied to the lycée and the year's bac are folded, never removed
  const reo = isReo(store.get("profile", null));
  const lyc = `${a.merite ? `<div class="sum-tile"><span class="sum-label">Aide au mérite</span><span class="sum-value">+ ${euros(a.merite.par_mois)} par mois</span><span class="sum-note">boursiers avec la mention très bien</span></div>` : ""}${a.mobilite ? `<div class="sum-tile"><span class="sum-label">Aide à la mobilité Parcoursup</span><span class="sum-value">${euros(a.mobilite.montant)}</span><span class="sum-note">une fois, pour une formation hors de votre académie</span></div>` : ""}`;
  const tiles = `<div class="sum-grid cout-tiles">
    <div class="sum-tile"><span class="sum-label">Une année ici avec une bourse</span><span class="sum-value">${ab ? eurosRange(ab.min, ab.max) : "—"}</span><span class="sum-note">${ab ? `sans la CVEC${ab.frais_gardes ? "" : " ni les frais d'inscription"} ${estimTag("même calcul que ci-dessus, sans ce dont les boursiers sont exonérés ; la bourse n'est pas déduite")}` : "il manque une partie du calcul"}</span></div>
    <div class="sum-tile"><span class="sum-label">Bourse sur critères sociaux</span><span class="sum-value">${b ? `${euroMois(b.echelons[0].mensuel)} à ${euroMois(b.echelons[b.echelons.length - 1].mensuel)}` : "—"}</span><span class="sum-note">${b ? `par mois sur ${esc(b.mensualites)} mois, selon l'échelon` : a.sanitaire_social ? "gérée par la Région pour cette formation" : "non lue"}</span></div>
    ${reo ? "" : lyc}
  </div>${reo && lyc ? `<details class="more-card"><summary>Aides liées au lycée et au bac de l'année (aide au mérite, aide à la mobilité Parcoursup)</summary><div class="sum-grid cout-tiles">${lyc}</div></details>` : ""}`;
  let bourse = "";
  if (a.sanitaire_social) {
    bourse = `<h3>La bourse pour cette formation</h3><p class="small">${esc(a.sanitaire_social.texte)} ${lien(a.sanitaire_social.source, "Trouver l'aide de votre Région")}</p>`;
    src.push(lien(a.sanitaire_social.source, "Étudiant.gouv : aides des régions"));
  } else if (b) {
    bourse = `<h3>La bourse sur critères sociaux</h3>
      <p class="small">Elle compte ${esc(b.echelons.length)} échelons. Votre échelon dépend des revenus de votre famille : le simulateur officiel le calcule, pas ce site.${b.majoree ? ` Cette formation est en outre-mer : chaque montant compte les ${euros(b.majoree)} de plus par an prévus pour l'outre-mer.` : ""}</p>
      <details class="dip"><summary>Voir les montants des ${esc(b.echelons.length)} échelons</summary>
      <div class="scroll"><table class="stack aides-table"><tr class="stack-head"><th>Échelon</th><th class="num">Par an</th><th class="num">Par mois</th></tr>
      ${b.echelons.map((e) => `<tr><td>Échelon ${esc(e.echelon)}</td><td class="num" data-label="Par an">${euros(e.annuel)}</td><td class="num" data-label="Par mois">${euroMois(e.mensuel)}</td></tr>`).join("")}</table></div></details>
      ${a.statut !== "public" && b.condition_etab ? `<p class="small">Établissement privé : la bourse est versée seulement si l'établissement est habilité à recevoir des boursiers. Demandez-le-lui.</p>` : ""}
      <p class="small">${lien(b.liens.simulateur, "Calculer votre droit à la bourse")} · ${lien(b.liens.dse, "Faire la demande (dossier social étudiant)")}</p>
      ${b.demande ? `<p class="muted small">Pour l'année ${esc(b.annee)}, la demande se faisait entre ${esc(b.demande)}.</p>` : ""}`;
    src.push(lien(b.source, "Service-public : bourse sur critères sociaux") + verif(b));
  }
  let frais = "";
  if (a.droits || a.cvec) {
    const items = [];
    if (fr && fr.montant !== null && fr.montant !== undefined) {
      if (a.droits_exoneres) items.push(fr.montant ? `Les frais d'inscription de la fiche (${euros(fr.montant)}) sont un tarif national ${esc(a.droits.annee)} d'un établissement public : les boursiers ne les paient pas.` : "Cette formation ne demande pas de frais d'inscription.");
      else if (a.statut === "public") items.push(`Les frais de la fiche (${euros(fr.montant)}) ne sont pas un tarif national ${a.droits ? esc(a.droits.annee) : ""} : demandez à l'établissement s'ils sont supprimés pour les boursiers.`);
      else items.push(`Les frais de cet établissement privé (${euros(fr.montant)} par an) sont les siens : demandez-lui s'il les réduit pour les boursiers.`);
    }
    if (a.droits) items.push(`${esc(a.droits.exoneration)}`);
    if (a.cvec) items.push(`La CVEC (${euros(a.cvec.montant)} en ${esc(a.cvec.annee)}) : les boursiers ne la paient pas, mais doivent demander leur attestation. ${lien(a.cvec.lien, "Demander l'exonération")}`);
    frais = `<h3>Les frais quand on est boursier</h3><ul class="small">${items.map((x) => `<li>${x}</li>`).join("")}</ul>`;
    if (a.droits) src.push(lien(a.droits.source, "Service-public : frais d'inscription") + verif(a.droits));
    if (a.cvec) src.push(lien(a.cvec.source, "CVEC"));
  }
  const merite = a.merite ? `<h3>L'aide au mérite : ${euros(a.merite.montant)} par an</h3>
    <p class="small">Versée en ${esc(a.merite.mensualites)} fois ${euros(a.merite.par_mois)}, en plus de la bourse. Les conditions officielles :</p>
    <ul class="small">${a.merite.conditions.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : "";
  if (a.merite) src.push(lien(a.merite.source, "Service-public : aide au mérite") + verif(a.merite));
  const mobilite = a.mobilite ? `<h3>L'aide à la mobilité Parcoursup : ${euros(a.mobilite.montant)}</h3>
    <p class="small">Versée une fois. Les conditions officielles :</p>
    <ul class="small">${a.mobilite.conditions.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
    ${a.mobilite.complement_texte ? `<p class="small">${esc(a.mobilite.complement_texte)}</p>` : ""}
    <p class="small">${lien(a.mobilite.lien, "Faire la demande")}${a.mobilite.periode ? ` <span class="muted">(pour la rentrée 2026 : ${esc(a.mobilite.periode)})</span>` : ""}</p>` : "";
  if (a.mobilite) src.push(lien(a.mobilite.source, "Service-public : aide à la mobilité Parcoursup") + verif(a.mobilite));
  if (a.mobilite && a.mobilite.complement_source) src.push(lien(a.mobilite.complement_source, "Étudiant.gouv : aide à la mobilité Parcoursup"));
  const logement = a.logement ? `<h3>Se loger</h3><p class="small">L'aide au logement de la CAF (APL) dépend de votre loyer et de vos ressources : ${lien(a.logement.simulateur, "calculer votre droit")}.</p>` : "";
  if (a.logement) src.push(lien(a.logement.source, "Service-public : aide au logement étudiant") + verif(a.logement));
  const annee = (b && b.annee) || (a.cvec && a.cvec.annee) || "";
  return `<div class="card aides-card"><h2>Financer vos études</h2>
    <p class="muted small">Montants et conditions de l'année ${esc(annee)}, les derniers fixés par l'État. Ceux de votre rentrée seront publiés au printemps. Rien n'est garanti : chaque aide se demande.</p>
    ${tiles}${aidesHint(a)}${bourse}${frais}${merite}${mobilite}${logement}
    <p class="muted small">Sources officielles${a.lu_le ? `, lues le ${esc(new Date(`${a.lu_le}T12:00:00Z`).toLocaleDateString("fr-FR"))}` : ""} : ${src.filter(Boolean).join(" ; ")}. Les textes officiels font foi.</p></div>`;
}

// sprint V2: the distance from the student's town, computed HERE (the town is never sent): the commune list (API Géo) is
// loaded once, searched in the browser, and the chosen town is kept in this browser only (store "villeDepart")
let COMMUNES = null, COMMUNES_P = null;
function communesLoad() {
  if (COMMUNES) return Promise.resolve(COMMUNES);
  if (!COMMUNES_P) COMMUNES_P = api("/api/communes").then((d) => { COMMUNES = (d.communes || []).map((c) => ({ nom: c[0], dep: c[1], lat: c[2], lon: c[3], cle: foldTxt(c[0]) })); return COMMUNES; })
    .catch(() => { COMMUNES_P = null; return null; });
  return COMMUNES_P;
}
const foldTxt = (x) => String(x || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/œ/g, "oe").replace(/æ/g, "ae").toLowerCase().replace(/[’'`-]/g, " ").replace(/\s+/g, " ").trim();
const villeLabel = (c) => `${c.nom} (${c.dep})`;
function villeDepart() {
  const v = store.get("villeDepart", null);           // never trusted: a name, a department and two finite coordinates
  return v && typeof v.nom === "string" && typeof v.dep === "string" && Number.isFinite(v.lat) && Number.isFinite(v.lon)
    && Math.abs(v.lat) <= 90 && Math.abs(v.lon) <= 180 ? { nom: v.nom.slice(0, 80), dep: v.dep.slice(0, 3), lat: v.lat, lon: v.lon } : null;
}
function distanceText(from, lat, lon) {
  const km = haversineKm(from.lat, from.lon, lat, lon);
  if (km < 1) return `Vous êtes dans la même commune ou presque (moins de 1 km à vol d'oiseau depuis le centre de ${esc(villeLabel(from))}).`;
  return `<strong>${fmt(Math.round(km))} km</strong> à vol d'oiseau depuis le centre de ${esc(villeLabel(from))} ${estimTag("distance en ligne droite entre les centres des communes ; la route est plus longue")}.${km > 50 ? " À cette distance, la plupart des étudiants se logent sur place : le loyer ci-dessous compte." : " À cette distance, des allers-retours sont souvent possibles : regardez les transports."}`;
}
// owner, 2026-11-18: a round trip between the student's town and the formation, « à titre d'information ». The town never leaves
// the browser: /api/transports has no parameter (official TGV fares and stations, median fuel prices, the fixed hypotheses of the
// car estimate, transports.py) and everything is computed here. Ranges only; no figure where no price is public.
let TRANSPORTS_P = null;
const trLoad = () => (TRANSPORTS_P = TRANSPORTS_P || api("/api/transports").catch(() => { TRANSPORTS_P = null; return null; }));
// owner, 2026-11-18 (« au plus proche »): each fuel's median in the student's DEPARTMENT when published (enough stations,
// transports.MIN_STATIONS_DEP), else its national median; `dep` lists the fuels read in the department
const TR_FUEL_NAMES = { gazole: "gazole", e10: "SP95-E10", sp95: "SP95" };
function trFuel(T, dep) {
  const D = (T.carburant_dep || {})[String(dep || "").toUpperCase()] || {}, fuel = {}, local = [];
  for (const [k, x] of Object.entries(T.carburant || {})) {
    const d = D[k] && Number.isFinite(D[k].prix) ? D[k] : null;
    fuel[k] = d || x;
    if (d) local.push(k);
  }
  return { fuel, local, all: Object.keys(fuel) };
}
// the sea or a border between two points (Codex, PR #86: two islands less than 100 km apart are still two islands): each land
// with roads is named by its coordinates (the continent, whose box also takes the nearest foreign towns; Corsica; French Guiana;
// New Caledonia's main island, a band along its axis; Réunion; Martinique; Guadeloupe's Basse-Terre and Grande-Terre, joined by
// bridges; Mayotte's Grande-Terre; Tahiti); every other place (Marie-Galante, Les Saintes, Petite-Terre, Moorea, the other islands,
// formations abroad) is "autre" and gets NO car estimate, even next door: a road between them is never assumed
function trLand(lat, lon) {
  if (lat >= 41.3 && lat <= 43.1 && lon >= 8.45 && lon <= 9.65) return "corse";
  if (lat >= 42.3 && lat <= 51.2 && lon >= -5.3 && lon <= 8.35) return "continent";
  if (lat >= 2 && lat <= 6 && lon >= -55 && lon <= -51) return "guyane";
  const ax = 163.95 - 166.95, ay = -20.05 + 22.45, px = lon - 166.95, py = lat + 22.45, t = (px * ax + py * ay) / (ax * ax + ay * ay);
  if (t >= -0.05 && t <= 1.05 && Math.hypot(px - t * ax, py - t * ay) <= 0.42) return "grande-terre";
  if (lat >= -21.4 && lat <= -20.85 && lon >= 55.2 && lon <= 55.85) return "reunion";
  if (lat >= 14.38 && lat <= 14.9 && lon >= -61.25 && lon <= -60.8) return "martinique";
  if ((lat >= 15.94 && lat <= 16.52 && lon >= -61.82 && lon <= -61.55) || (lat >= 16.18 && lat <= 16.52 && lon > -61.55 && lon <= -61.17)) return "guadeloupe";
  if (lat >= -13.02 && lat <= -12.62 && lon >= 44.98 && lon <= 45.25) return "mayotte";
  if (lat >= -17.9 && lat <= -17.48 && lon >= -149.65 && lon <= -149.1) return "tahiti";
  return "autre";
}
const trSea = (home, lat, lon) => { const a = trLand(home.lat, home.lon); return a !== trLand(lat, lon) || a === "autre"; };
// the car: road = crow-fly x detour range, fuel = the lowest and highest median of the fuels read, round trip; time one way
function trCar(km, H, fuel) {
  const prices = Object.values(fuel || {}).map((x) => x.prix).filter((x) => Number.isFinite(x));
  if (!prices.length || !(km > 0)) return null;
  const road = [km * H.detour[0], km * H.detour[1]];
  const cost = [2 * road[0] * H.conso_l_100km[0] / 100 * Math.min(...prices), 2 * road[1] * H.conso_l_100km[1] / 100 * Math.max(...prices)];
  const minutes = [road[0] / H.vitesse_kmh[1] * 60, road[1] / H.vitesse_kmh[0] * 60];
  return { road, cost, minutes, pmin: Math.min(...prices), pmax: Math.max(...prices) };
}
// the fare stations within `maxKm` of a point, nearest first
function trNear(stations, lat, lon, maxKm) {
  return (stations || []).map(([uic, nom, la, lo]) => ({ uic, nom, km: haversineKm(lat, lon, la, lo) })).filter((x) => x.km <= maxKm)
    .sort((x, y) => x.km - y.km);
}
// the TGV: every fare station within H.gare_km of the town and of the formation (a city has several), the pair with the lowest
// published normal fare; the published range x 2 (round trip), and the pupil-student-apprentice range where the SNCF publishes it
function trTrain(T, home, lat, lon) {
  const H = T.hypotheses, A = trNear(T.stations, home.lat, home.lon, H.gare_km), B = trNear(T.stations, lat, lon, H.gare_km);
  if (!A.length || !B.length) return { none: `pas de gare TGV à moins de ${H.gare_km} km ${!A.length ? "de votre ville" : "de la formation"}` };
  if (A.some((x) => B.some((y) => y.uic === x.uic))) return { none: "la même gare TGV dessert votre ville et la formation" };
  let best = null;
  for (const a of A) for (const b of B) {
    const od = T.od[[a.uic, b.uic].sort().join("-")];
    if (od && (!best || od[0] < best.od[0] || (od[0] === best.od[0] && a.km + b.km < best.a.km + best.b.km))) best = { a, b, od };
  }
  if (!best) return { none: `pas de prix TGV publié entre les gares proches (${A[0].nom}, ${B[0].nom})` };
  const { a, b, od } = best;
  return { a, b, price: [2 * od[0], 2 * od[1]], carriers: od[2], etudiant: od.length > 4 ? [2 * od[3], 2 * od[4]] : null };
}
const trEuros = (x) => `${fmt(x[0] === x[1] ? Math.round(x[0]) : Math.floor(x[0]))}${x[0] === x[1] ? "" : ` à ${fmt(Math.ceil(x[1]))}`} €`;
const trHours = (m) => { const h = Math.floor(m / 60), mn = Math.round(m % 60); return mn === 60 ? `${h + 1} h` : h ? `${h} h${mn ? ` ${String(mn).padStart(2, "0")}` : ""}` : `${mn} min`; };
// audit PR 7: two ends that print the same ("6 à 6 km") are one value
const trRange = (a, b, unit = "") => (a === b ? `${a}${unit}` : `${a} à ${b}${unit}`);
const trFr = (x, d = 2) => Number(x).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const TR_LINKS = { sncf: "https://www.sncf-connect.com/" };
function transportsHtml(T, home, lat, lon) {
  const H = T.hypotheses, km = haversineKm(home.lat, home.lon, lat, lon);
  if (km < 1) return `<p class="small">Vous êtes dans la même commune, ou presque : pas de trajet longue distance à estimer.</p>`;
  const sea = trSea(home, lat, lon), F = trFuel(T, home.dep);
  const car = sea ? null : trCar(km, H, F.fuel), tr = trTrain(T, home, lat, lon);
  const fuelDate = Object.values(T.carburant || {}).map((x) => x.date).sort().pop();
  const names = (ks) => ks.map((k) => TR_FUEL_NAMES[k] || k).join(", ");
  const fuelWhere = !F.local.length ? "prix médians en France"
    : F.local.length === F.all.length ? `prix médians des stations de votre département (${esc(home.dep)})`
    : `prix médians des stations de votre département (${esc(home.dep)}) ; en France pour le ${esc(names(F.all.filter((k) => !F.local.includes(k))))}, trop peu de stations le vendent près de chez vous`;
  const link = (k, txt) => `<a href="${esc(TR_LINKS[k])}" target="_blank" rel="noopener">${esc(txt)} ↗</a>`;
  const row = (mode, prix, duree, comment) => `<tr><td>${mode}</td><td class="num" data-label="Aller-retour">${prix}</td><td data-label="Durée (aller)">${duree}</td><td data-label="D'où vient le chiffre" class="small">${comment}</td></tr>`;
  const rows = [
    car ? row("Voiture", trEuros(car.cost), trRange(trHours(car.minutes[0]), trHours(car.minutes[1])),
      `${estimTag("", false, true)} carburant seul : ${trRange(fmt(Math.round(car.road[0])), fmt(Math.round(car.road[1])), " km")} de route (${trFr(H.detour[0], 1)} à ${trFr(H.detour[1], 1)} fois la distance à vol d'oiseau), ${fmt(H.conso_l_100km[0])} à ${fmt(H.conso_l_100km[1])} litres aux 100 km, ${trRange(trFr(car.pmin, 2), trFr(car.pmax, 2), " €")} le litre (${esc(names(F.all))} : ${fuelWhere}, sur les 30 jours avant le ${esc(frDate(fuelDate || ""))}). Péages et parking non compris.`)
      : row("Voiture", "—", "—", sea ? "la mer ou une frontière sépare votre ville et la formation : pas d'estimation en voiture." : "prix des carburants pas encore lus"),
    tr.price ? row(`Train (${tr.carriers.map(esc).join(", ")})`, trEuros(tr.price), `voir ${link("sncf", "SNCF Connect")}`,
      `fourchette plein tarif, 2de classe, publiée par la SNCF entre les gares de ${esc(tr.a.nom)} et ${esc(tr.b.nom)}.${tr.etudiant ? ` Au « Tarif Élève - Étudiant - Apprenti » publié par la SNCF : <strong>${trEuros(tr.etudiant)}</strong> l'aller-retour.` : ""} Avec une carte Avantage, c'est souvent moins cher.`)
      : row("Train", "—", `voir ${link("sncf", "SNCF Connect")}`, `${esc(tr.none)}${sea ? "." : " : un TER ou un trajet avec changement reste possible."}`),
  ];
  // owner, 2026-11-18: no carpooling or bus line (no public price, nothing to say); a ferry only where Corsica or two islands are concerned
  const la = trLand(home.lat, home.lon), lb = trLand(lat, lon);
  if (sea && (la === "corse" || lb === "corse" || (la !== "continent" && lb !== "continent")))
    rows.push(row("Bateau", "pas de prix public", "—", "comparez sur les sites des compagnies maritimes, au départ des ports les plus proches."));
  if (km >= H.avion_km || sea) rows.push(row("Avion", "pas de prix public", "—", `${sea && km < H.avion_km ? "pour traverser la mer" : "au-delà de 500 km"}, comparez aussi sur les sites des compagnies aériennes, sans oublier le trajet jusqu'aux aéroports.`));
  return `<p class="small">De ${esc(villeLabel(home))} à la formation : <strong>${fmt(Math.round(km))} km</strong> à vol d'oiseau. Des fourchettes à titre d'information, pas des prix garantis.</p>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Mode</th><th class="num">Aller-retour</th><th>Durée (aller)</th><th>D'où vient le chiffre</th></tr>${rows.join("")}</table></div>
    <p class="muted small">Sources : SNCF, « Tarifs TGV INOUI et OUIGO » et « Gares de voyageurs » (licence ODbL) ; ministère de l'Économie, « Prix des carburants » (Licence Ouverte)${T.lu_le && T.lu_le.tarifs_tgv ? `, lus le ${esc(frDate(T.lu_le.tarifs_tgv))}` : ""}. Votre ville reste dans ce navigateur : elle n'est jamais envoyée.</p>`;
}
function transportsCard(v) {
  if (!v || v.lat == null || v.lon == null) return "";
  return `<div class="card" id="transports"><h2>Venir depuis chez vous : le trajet</h2>
    <div id="transports-body">${villeDepart() ? '<p class="muted small">Chargement des tarifs…</p>' : 'Indiquez votre ville dans <a href="#/profil">Mon profil</a> : le coût et la durée d\'un aller-retour jusqu\'ici s\'afficheront ici.'}</div></div>`;
}
async function fillTransports(v) {
  const home = villeDepart();
  if (!home || !v || v.lat == null) return;
  const el = document.getElementById("transports-body");
  const T = await trLoad();
  if (!el || el !== document.getElementById("transports-body")) return;          // the student left the page
  const ready = T && T.hypotheses && ((T.stations || []).length || Object.keys(T.carburant || {}).length);
  el.innerHTML = ready ? transportsHtml(T, home, v.lat, v.lon) : '<p class="muted small">Les tarifs ne sont pas encore disponibles.</p>';
}
function distanceBlock(v) {
  // owner, 2026-11-15: the town is entered ONCE, in "Mon profil"; here it is only read (no input on the formation page)
  if (!v || v.lat == null || v.lon == null) return "";
  const from = villeDepart();
  return `<p class="small dist-line">${from ? distanceText(from, v.lat, v.lon) : 'Indiquez votre ville dans <a href="#/profil">Mon profil</a> : la distance jusqu\'ici s\'affichera sur chaque fiche, sur la carte et dans Mes vœux.'}</p>`;
}
// the town field of "Mon profil": the communes (API Géo) are searched HERE; the town is kept in this browser only, never sent
function villeField() {
  const from = villeDepart();
  return `<div class="pf-field"><div class="pf-ctl"><label for="pf-ville">Votre ville (facultatif)</label>
    <div class="dist-row"><input id="pf-ville" list="pf-communes" autocomplete="off" placeholder="ex. Arras (62)" value="${from ? esc(villeLabel(from)) : ""}">${from ? '<button type="button" id="pf-ville-clear" class="small">Retirer</button>' : ""}</div><datalist id="pf-communes"></datalist>
    <p class="small" id="pf-ville-out" aria-live="polite">${from ? `Ville enregistrée : ${esc(villeLabel(from))}.` : ""}</p></div>
    <p class="pf-why">Sert à calculer la distance jusqu'à chaque formation : sur sa fiche, sur la carte et dans Mes vœux. Les communes sont cherchées dans ce navigateur : votre ville n'est jamais envoyée au site.</p></div>`;
}
function bindVille(redraw) {
  const input = document.getElementById("pf-ville");
  if (!input) return;
  const out = document.getElementById("pf-ville-out"), list = document.getElementById("pf-communes");
  const clear = document.getElementById("pf-ville-clear");
  if (clear) clear.onclick = () => { store.set("villeDepart", null); redraw(); };
  input.addEventListener("focus", () => { communesLoad(); }, { once: true });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });   // never submits the profile form
  input.addEventListener("input", async () => {
    const C = await communesLoad();
    if (!C || !input.isConnected) return;
    const q = foldTxt(input.value.replace(/\s*\(\w{1,3}\)\s*$/, ""));
    const exact = C.find((c) => villeLabel(c) === input.value.trim());
    if (exact) {
      store.set("villeDepart", { nom: exact.nom, dep: exact.dep, lat: exact.lat, lon: exact.lon });
      out.textContent = `Ville enregistrée : ${villeLabel(exact)}.`;
      return;
    }
    if (q.length < 2) { list.innerHTML = ""; return; }
    const hits = C.filter((c) => c.cle.startsWith(q)).slice(0, 30);
    list.innerHTML = hits.map((c) => `<option value="${esc(villeLabel(c))}">`).join("");
    out.textContent = hits.length ? "Choisissez votre commune dans la liste." : "Aucune commune de ce nom.";
  });
}
// the distance from the student's town to a formation, for a list row (Mes vœux): "" without a town or coordinates
function kmFromHome(lat, lon) {
  const from = villeDepart();
  if (!from || lat == null || lon == null || !Number.isFinite(Number(lat)) || !Number.isFinite(Number(lon))) return "";
  return `${fmt(Math.round(haversineKm(from.lat, from.lon, Number(lat), Number(lon))))} km de chez vous`;
}
// sprint V2: doing the formation as an apprentice (apprentissage.py): free tuition and a salary, the CFA that teach it here,
// where to find a company; official links only, never a computed salary
function apprentiCard(a) {
  if (!a || !a.propose) return "";
  const offres = (a.offres || []).length ? `<p class="small">${a.offres.length > 1 ? "Ces établissements la proposent" : "Cet établissement la propose"} en apprentissage (pas de statistiques d'admission publiées pour cette voie) :</p>
    <ul class="small">${a.offres.map((o) => { const url = carteFiche(o);
      return `<li>${esc(o.etablissement)}${o.ville ? ` · ${esc(o.ville)}` : ""}${appParcours(o) ? ` · ${appParcours(o)}` : ""}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">sa fiche Parcoursup ↗</a>` : ""}${/^\d{1,9}$/.test(o.cod_aff_form || "") ? ` ${appVoeuButton(o.cod_aff_form)}` : ""}</li>`; }).join("")}</ul>` : "";
  return `<div class="card app-card" id="app-card"><h2>Et en apprentissage ?</h2>
    <ul class="small">
      <li><strong>Pas de frais de formation</strong> : la formation d'un apprenti est gratuite pour lui (Code du travail, article L6211-1).</li>
      <li><strong>Un salaire</strong> : un pourcentage du Smic qui dépend de votre âge et de l'année de formation. <a href="${esc(a.liens.salaire)}" target="_blank" rel="noopener">Calculer votre salaire d'apprenti ↗</a></li>
      <li><strong>Il faut un employeur</strong> : on signe un contrat d'apprentissage avec une entreprise, puis on alterne cours et travail. <a href="${esc(a.liens.entreprises)}" target="_blank" rel="noopener">Trouver une entreprise qui recrute des apprentis (La bonne alternance) ↗</a></li>
    </ul>${appOfficiel(a.officiel, false)}
    ${a.sies_apprentissage ? '<p class="small">Cette formation est elle-même proposée en apprentissage.</p>' : ""}${offres}
    <p class="muted small">Pour en savoir plus sur le salaire et les droits de l'apprenti : <a href="${esc(a.liens.guide)}" target="_blank" rel="noopener">guide officiel de La bonne alternance ↗</a>. Une formation en apprentissage a sa propre fiche Parcoursup : vérifiez-la.</p></div>`;
}
// PR 18 (owner, 2026-11-28): the contract and the minimum pay AS service-public.gouv.fr PRINTS THEM (aides.r_apprenti): the
// page's own sentences and table cells, its « Vérifié le » date and links. A quote, never a salary computed for the student.
const SP_HOST = /^https:\/\/www\.service-public\.gouv\.fr\//;
function appOfficiel(o, open) {
  if (!o || !Array.isArray(o.ages) || !Array.isArray(o.annees) || !SP_HOST.test(o.source || "")) return "";
  const link = (u, t) => (SP_HOST.test(u || "") ? ` <a href="${esc(u)}" target="_blank" rel="noopener">${esc(t)} ↗</a>` : "");
  const years = o.annees.map((r) => `<div class="app-annee"><p class="small"><strong>${esc(r.annee)}</strong></p><ul class="small">${r.cellules.map((c, j) => `<li><strong>${esc(o.ages[j] || "")}</strong> : ${c.map((x) => esc(x)).join("<br>")}</li>`).join("")}</ul></div>`).join("");
  return `<details class="app-officiel"${open ? " open" : ""}><summary>Le contrat et le salaire minimum, d'après service-public.gouv.fr</summary>
    <div class="grille-officielle">
    ${(o.contrat || []).map((x) => `<p class="small">« ${esc(x)} »</p>`).join("")}
    <p class="small"><strong>${esc(o.titre)}</strong>, selon l'âge de l'apprenti et l'année du contrat :</p>
    <div class="app-grille">${years}</div>
    ${(o.notes || []).map((x) => `<p class="small">« ${esc(x)} »</p>`).join("")}
    <p class="muted small">Citation de la page officielle${o.verifie ? `, vérifiée le ${esc(o.verifie)} par service-public.gouv.fr` : ""} :${link(o.source, "Contrat d'apprentissage")}. Ce sont des minimums bruts publiés : SupCompass ne calcule pas votre salaire.${link(o.simulateur, "Estimer le salaire d'un apprenti")}${link(o.entreprises, "Trouver une entreprise qui recrute en alternance")}</p></div></details>`;
}
function apprentiInsertionCard(a) {
  const n = a && a.national;
  if (!n || !n.voies.length) return "";
  return `<div class="card"><h2>Après ce BTS : en apprentissage ou en lycée ?</h2>
    <p class="small">Dans toute la France, pour ce BTS (${esc(n.voies[0].annee)}). Chaque établissement publie ses propres taux ; on montre le taux du milieu des établissements qui le publient ${estimTag("médiane des établissements, pas un taux national")}.</p>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Voie</th><th class="num">En emploi 6 mois après la sortie</th><th class="num">Poursuivent leurs études</th><th class="num">Établissements</th></tr>
    ${n.voies.map((v) => `<tr><td>${esc(v.libelle)}</td>
      <td class="num" data-label="En emploi 6 mois après la sortie">${fmt(v.emploi_med)} % <span class="muted small">(la moitié des établissements entre ${fmt(v.emploi_q1)} et ${fmt(v.emploi_q3)} %)</span></td>
      <td class="num" data-label="Poursuivent leurs études">${v.poursuite_med !== null && v.poursuite_med !== undefined ? `${fmt(v.poursuite_med)} %` : "—"}</td>
      <td class="num" data-label="Établissements">${fmt(v.n_emploi)} sur ${fmt(v.n_etab)}</td></tr>`).join("")}</table></div>
    <p class="muted small">Le taux d'emploi compte les jeunes qui ont quitté les études ; les petits effectifs ne sont pas publiés. Source : Inserjeunes (ministère de l'Éducation nationale), sortants de dernière année. Ce sont des résultats passés, pas une promesse d'emploi.</p></div>`;
}

async function viewFormation(cod, session, refresh) {
  // the page is never without its heading while the fiche loads (~4 s on a cold server, red team A4); the server's own summary
  // of an indexable page ([data-seo]) is kept as it is: showError relies on it (Codex). An in-place refresh (« Comparer »,
  // « Ajouter à mes vœux ») keeps the fiche on screen until the new one is ready (Codex, PR #88)
  if (!refresh && !$view.querySelector("[data-seo]")) {
    $view.innerHTML = `<div class="card fhead"><h1>Fiche formation</h1><p class="small muted" role="status">Chargement de la fiche…</p></div>`;
    document.title = "Fiche formation — SupCompass";               // the tab names the page while it loads (R8 rule)
  }
  const d = await api(`/api/formation/${encodeURIComponent(cod)}${session ? `?session=${session}` : ""}`);
  if (d.doublettes && d.bacs) d.doublettes = { ...d.doublettes, acces: d.bacs };   // « Selon votre bac » prints the card's figure (PR 2)
  store.set("guideVu", true);                                         // R7: step 2 of "Construire ma liste" (this browser only)
  const r = d.record, inBasket = basket.get().includes(r.cod_aff_form);
  const years = d.history.map((h) => h.session);
  // lot 1, PR 12: outside terminale the estimate that concerns the student comes first in « Y entrer », before « Selon votre bac »
  // (Sarah found it as the last block of the folded part); in terminale it stays folded, where it was
  const reoFirst = isReo(store.get("profile", null)) && !!d.reorientation;
  const geo = r.lat != null ? ` · <a href="https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lon}#map=15/${r.lat}/${r.lon}" target="_blank" rel="noopener">carte</a>` : "";
  // sprint 19: the jury tab is rendered once; the summary links to it (own report first, else the similar formations' reports)
  // the fiche's grid first (the campaign it serves), then the jury's own report, else the similar formations' reports
  // owner, 2026-11-18: the fiche and the jury's own report in ONE card (juryMerged), the fiche first and prevailing
  const both = grilleHas(d.grille) && !!(d.rapport && d.rapport.textes);
  const grHtml = both ? juryMerged(d.grille, d.rapport) : grilleCard(d.grille);
  const repHtml = both ? "" : juryCard(d.rapport) || semblablesJuryCard(d.semblables, d.rapport);
  const juryHtml = grHtml + repHtml;
  d.jury_tab = !juryHtml ? null : both ? { kind: "both", session: d.grille.session, rapport: d.rapport.session }
    : juryCard(d.rapport) ? { kind: "own", session: d.rapport.session }
    : grHtml ? { kind: "grille", session: d.grille.session } : { kind: "semblables" };
  $view.innerHTML = `
  <div class="card fhead">
    <h1>${esc(r.g_ea_lib_vx)}</h1>
    <div class="fhead-lib">${esc(r.lib_for_voe_ins)}${d.complement ? `<span class="fhead-parcours"> · ${esc(d.complement)}</span>` : ""}${d.apprentissage && d.apprentissage.length ? ` ${voieBadges({ initiale: r.apprentissage !== true, apprentissage: true })}` : ""}</div>
    ${d.reconnaissance ? `<div class="fhead-reco">${recoPill(d.reconnaissance.categorie, d.reconnaissance.libelle, d.reconnaissance.explication)}</div>` : ""}
    <div class="muted small">${esc(r.ville_etab)} · ${esc(acadLabel(r.acad_mies))} · ${esc(r.contrat_etab)} · ${esc(r.select_form)} · n° Parcoursup ${esc(r.cod_aff_form)}</div>
    <div class="toolbar" style="margin-top:8px">
      ${voeuButton(r.cod_aff_form, true)}
      <button id="bask">${inBasket ? "Retirer du comparateur" : "Comparer"}</button>
    </div>${vmNote(d.voeu_multiple)}
  </div>
  ${d.warnings.map((w) => `<div class="warn">${ICONS.warn} ${esc(w.text)}</div>`).join("")}
  ${d.carte && d.carte.dans === false && d.carte.session ? `<div class="warn">${ICONS.warn} ${esc(absenteText(d.carte.session))}</div>` : ""}
  ${summaryBand(r, d)}
  <p class="small fhead-links"><label>Session <select id="sess">${years.map((y) => `<option ${y === r.session ? "selected" : ""}>${y}</option>`).join("")}</select></label>
      · <a href="#/evolution/${encodeURIComponent(r.cod_aff_form)}">Évolution 4 ans →</a>
      · <a href="${esc(r.fiche_url)}" data-cod="${esc(r.cod_aff_form)}" target="_blank" rel="noopener">Fiche Parcoursup ↗</a>${geo}</p>
  ${tabbed("fiche", [
    ["admission", "Y entrer", `
  ${jpoCard(d.jpo)}
  ${decouvrirCard(d.immersion, d.handicap)}
  <div class="card"><h2>Chiffres officiels du ministère · ${r.session}</h2>
    <div class="grid3">
      <div><div class="muted small">Taux d'accès (phase principale) ${tip("taux_acces_ens")}</div><div class="big">${pct(r.taux_acces_ens)}</div>${pvLine(d.prevision, "taux_acces_ens")}</div>
      <div><div class="muted small">Parmi les candidats appelés, part des élèves de terminale générale (phase principale) ${tip("part_terminale_generale_en_position_admis_pp")}</div><div class="big">${pct(r.part_terminale_generale_en_position_admis_pp)}</div>${pvLine(d.prevision, "part_terminale_generale_en_position_admis_pp")}</div>
      <div><div class="muted small">Admis (toute la campagne)</div><div class="big">${fmt(r.acc_tot)}</div><div class="muted small">capacité ${fmt(r.capa_fin)}</div>${pvLine(d.prevision, "acc_tot")}</div>
    </div></div>
  ${reoFirst ? reoCard(d.reorientation) + ifsiFpcCard(d.aides) : ""}
  ${doubletteCard(d.doublettes, d.rapport, d.semblables, profileRate(d, bacProfile()))}
  ${appelCard(d.appel)}
  <div id="planb"></div>
  ${offerCard(r, d.apprentissage)}
  <details class="more-card"><summary><strong>Plus de chiffres sur l'admission</strong> <span class="muted small">candidats par place, votre moyenne parmi les admis, prévision, calendrier des propositions, lycées d'origine, étapes de la sélection, comparaison avec la filière, candidats hors terminale</span></summary>
  ${tensionCard(d.tension, r.session)}
  ${isReo(store.get("profile", null)) ? "" : moyenneCard(r)}
  ${previsionCard(d.prevision)}
  ${reoFirst ? "" : reoCard(d.reorientation) + ifsiFpcCard(d.aides)}
  ${timingCard(r, d.history)}
  ${lyceeHere(r)}
  <div class="card"><h2>Entonnoir · trois étapes distinctes ${tip("funnel")}</h2>
  <div class="grid3">
    ${stageCard("1 · Candidatures (vœux)", ["voe_tot", "nb_voe_pp", "nb_voe_pc", "voe_tot_f"], r, r.subwish_flag ? "Sous-vœu : effectifs partagés, non additionnables. " + tip("subwish") : "Unité : vœux, pas candidats uniques.")}
    ${stageCard("2 · Classés & proposés", ["nb_cla_pp", "nb_cla_pc", "prop_tot", "ran_grp1"], r)}
    ${stageCard("3 · Admis", ["acc_tot", "acc_pp", "acc_pc", "acc_neobac", "acc_term", "acc_brs"], r)}
  </div>
  </div>
  <div class="card"><h2>Position dans la filière · ${esc(r.fil_lib_voe_acc)} ${tip("peers")}</h2>
    <div class="legend"><span><i style="background:var(--range)"></i>p10–p90</span><span><i style="background:var(--box)"></i>p25–p75</span><span>│ médiane</span><span><i style="background:var(--ink);border-radius:50%"></i>cette formation (creux = hors référence)</span></div>
    ${d.peers.map((p) => `<div class="bench"><div>${esc(META.peer_metrics[p.metric]?.label || p.metric)}<div class="muted small">${pct(p.value)}</div></div>
      <div>${benchBar(p)}</div>
      <div class="num">${p.peer_percentile != null ? `<strong>P${fmt(p.peer_percentile)}</strong>` : `<span class="muted small">${p.value == null ? "n.d." : "hors réf."}</span>`}
      <div class="muted small">n=${fmt(p.n_peers)}${p.unstable ? " instable" : ""}</div></div></div>`).join("")}
  </div>
  </details>
`],
    ["jury", "Ce que regarde le jury", juryHtml],
    ["cout", "Combien ça coûte", coutCard(d.vie, r) + transportsCard(d.vie) + aidesCard(d.aides, d.vie) + apprentiCard(d.apprenti)],
    ["reussite", "Réussir et poursuivre", `
  ${recoCard(d.reconnaissance)}
  ${handicapCard(d.handicap)}
  ${successCard(d.success)}
  ${masterCard(d.master)}
  ${passerellesCard(d.passerelles)}
  ${licenceMasterCard(d.licence_master)}
  ${butCard(d.but)}`],
    // audit PR 5: the jobs first (Onisep), then the published insertion, then the robustesse model (its detail folded)
    ["emploi", "Emploi et métiers", `
  ${metiersCard(d.metiers)}
  ${insertionCard(d.insertion)}
  ${apprentiInsertionCard(d.apprenti)}
  ${cereqCard(d.cereq)}
  ${formationRobustesseCard(d.robustesse, { ins: d.insertion, but: d.but && d.but.insertion })}`],
    ["historique", "Historique", `
  <div class="card"><h2>Historique de la lignée ${tip("lineage")}</h2><p class="muted small">Code de l'établissement (UAI) : ${esc(r.cod_uai)}</p><div class="scroll"><table>
    <tr><th>Session</th><th>Code Parcoursup</th><th>Libellé</th><th>Lien vers la campagne suivante</th><th class="num">Admis</th><th class="num">Taux d'accès</th></tr>
    ${d.history.map((h) => `<tr><td><a href="#/f/${esc(h.cod_aff_form)}/${h.session}">${h.session}</a></td><td>${esc(h.cod_aff_form)}</td><td>${esc(h.lib_for_voe_ins)}</td>
      <td>${h.link_to_next ? lineageBadge(h.link_to_next) : `<span class="muted small">—</span>`}</td><td class="num">${fmt(h.acc_tot)}</td><td class="num">${pct(h.taux_acces_ens)}</td></tr>`).join("")}
  </table></div></div>`],
  ])}${nextSteps("formation", /^https:\/\//.test(r.fiche_url || "") ? [{ href: r.fiche_url, text: "Lire les attendus et les critères du jury sur la fiche Parcoursup : c'est elle qui fait foi" }] : [])}${feedbackBox("fiche")}${reportLink(r.cod_aff_form)}`;
  bindTabs("fiche");
  fillTransports(d.vie);
  document.getElementById("sess").onchange = (e) => { location.hash = `#/f/${r.cod_aff_form}/${e.target.value}`; };
  loadPlanB(r.cod_aff_form);
  // an in-place refresh: the fiche stays on screen; a failed reload says so above it, never a blank page (Codex, PR #88)
  const refreshFiche = () => viewFormation(cod, session, true).catch((e) => {
    $view.querySelectorAll(":scope > .warn").forEach((w) => w.remove());
    $view.insertAdjacentHTML("afterbegin", `<div class="warn">${esc(e.message)}</div>`);
  });
  document.getElementById("bask").onclick = () => { basket.toggle(r.cod_aff_form); refreshFiche(); };
  bindVoeuButton(refreshFiche);
}

// ---- Plan B: same programme elsewhere, more accessible for the student's profile -------------
// Rendered in two places: the fiche (#planb card) and, inline, under an ambitious row of
// "Mon parcours" (opts.box, opts.profile, opts.inline, opts.onPin).
const WHY = { zone: "zone plus favorable", acces: "nettement plus accessible" };
let planbSeq = 0;
async function loadPlanB(cod, opts = {}) {
  const box = opts.box || document.getElementById("planb");
  if (!box) return;
  const includePaid = !!opts.includePaid;
  const p = opts.profile || store.get("profile", null);
  if (isReo(p)) {                                                     // sprint 21: Plan B compares zones, none exists outside terminale
    box.innerHTML = `${opts.inline ? "" : '<div class="card"><h2>Plan B</h2>'}<p class="muted small">${REO_NO_ZONE} Le plan B compare des zones : il n'est pas proposé. Comparez plutôt l'accès estimé hors terminale des formations dans « <a href="#/reorientation">Je me réoriente</a> ».</p>${opts.inline ? "" : "</div>"}`;
    return;
  }
  const prof = p || { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", academie: "" };
  const serie = ["bg", "bt", "bp"].includes(prof.serie) ? prof.serie : "bg";
  const qs = mentionParams(new URLSearchParams({ serie }), vxProfile({ mention: "ab", ...prof }));
  if (serie === "bg") { qs.set("spe1", prof.spe1 || "MATHS"); qs.set("spe2", prof.spe2 || "SES"); }
  if (prof.academie) qs.set("academie", prof.academie);
  if (includePaid) qs.set("include_paid", "true");
  const pbProf = vxProfile({ mention: "ab", ...prof }), local = lectureOf(pbProf).g !== null;
  if (local) qs.set("pool", "true");                                  // R6: the candidates, read here with the average kept
  // every request stamps its box: only the latest request made for a box still on the page may
  // fill it (a late answer for formation A, or for a superseded toggle, is dropped)
  const req = String(++planbSeq);
  box.dataset.req = req;
  if (opts.inline) box.innerHTML = `<p class="muted small">Recherche d'un plan B…</p>`;
  let d;
  try { d = await api(`/api/planb/${encodeURIComponent(cod)}?${qs}`); if (local) d = planBLocal(d, pbProf, prof.academie || null); } catch (e) {
    if (box.isConnected && box.dataset.req === req) {
      box.innerHTML = opts.inline ? `<p class="muted small">Plan B indisponible pour le moment.</p>` : "";
      if (!opts.inline && p) fillZoneTile(null);                      // no zone tile left on "…"
    }
    return;
  }
  if (!box.isConnected || box.dataset.req !== req) return;
  if (!opts.inline && p) fillZoneTile(d.target);
  const who = `${{ bg: "bac général", bt: "bac technologique", bp: "bac professionnel" }[serie]}${serie === "bg" ? ` ${esc(speName(prof.spe1 || "MATHS"))} + ${esc(speName(prof.spe2 || "SES"))}` : ""}, ${mentionWords({ mention: "ab", ...prof })}${prof.academie ? `, académie de ${esc(acadLabel(prof.academie))}` : ""}`;
  const head = opts.inline
    ? `<h3 class="planb-title">Plan B : la même filière, plus accessible pour vous ${tip("planb")}</h3>`
    : `<h2>Plan B : la même filière, plus accessible pour vous ${tip("planb")}</h2>
    <p class="small muted">Pour ${p ? "votre profil" : "un profil par défaut"} (${who}). <a href="#/profil">${p ? "Modifier" : "Renseigner le vôtre"} dans « Mon profil »</a>.</p>`;
  const paidToggle = d.hidden_paid || d.include_paid ? `<label class="small"><input type="checkbox" data-pbpaid ${d.include_paid ? "checked" : ""}> Inclure le privé hors contrat / enseignement supérieur privé (frais de scolarité possibles)${d.hidden_paid ? ` · ${fmt(d.hidden_paid)} masqué(s)` : ""}</label>` : "";
  const W = opts.onPin ? voeux.get() : [];
  let body;
  if (d.status === "deja_accessible") body = `<div class="info">Bonne nouvelle : pour votre profil, cette formation est déjà un vœu de sécurité.</div>`;
  else if (d.status === "non_disponible") body = `<p class="muted small">Plan B indisponible : ${esc(d.reason)}.</p>`;
  else if (!d.alternatives.length) body = `<p class="muted small">Aucune formation de la même filière n'est plus accessible pour votre profil d'après les données 2022–2025.</p>`;
  else {
    body = `<p class="small">Formation visée${d.target.complement ? ` (${esc(d.target.complement)})` : ""} : ${zoneBadge(d.target.zone, false, d.target.large && !d.target.uncertain)} · ${d.target.serie === "bg" ? "taux d'accès" : "accès estimé"} ${fmt(d.target.taux_acces_ens)} %</p>
    <div class="scroll"><table><tr><th>Formation</th><th>Zone</th><th class="num">${serie === "bg" ? "Taux d'accès" : "Accès estimé"}</th><th class="num">${d.moyenne !== null && d.moyenne !== undefined ? "Sous votre moyenne (estimation)" : "Votre mention ou moins"}</th><th class="num">Distance de la formation visée</th>${opts.onPin ? '<th><span class="sr-only">Actions</span></th>' : ""}</tr>
    ${d.alternatives.map((a) => `<tr><td><a href="#/f/${esc(a.cod_aff_form)}">${esc(a.etablissement)}</a><div class="muted small">${esc(a.complement || a.filiere)} · ${esc(a.ville)}${a.academie ? ` (${esc(acadLabel(a.academie))})` : ""}</div>${a.paid ? '<span class="badge warnb">privé : frais possibles</span>' : ""}${offerBadges(a, true)}</td>
      <td>${zoneBadge(a.zone, false, a.large && !a.uncertain)}${zoneAxisNote(a)}<div class="muted small">${WHY[a.why] || ""}</div></td>
      <td class="num">${fmt(a.taux_acces_ens)} %</td>
      <td class="num">${a.bounds ? (a.bounds[1] - a.bounds[0] < 0.005 ? pc1(a.bounds[0]) : `${pc1(a.bounds[0])} – ${pc1(a.bounds[1])}`) : pc1(a.position)}</td>
      <td class="num">${a.km != null ? `${fmt(a.km)} km` : "—"}</td>${opts.onPin ? `<td><button type="button" class="small" data-pbpin="${esc(a.cod_aff_form)}">${W.includes(a.cod_aff_form) ? "dans mes vœux" : "ajouter à mes vœux"}</button></td>` : ""}</tr>`).join("")}</table></div>
    <p class="muted small">Parts d'admis des campagnes passées, pas des chances d'admission. Vérifiez chaque fiche Parcoursup.</p>`;
  }
  box.innerHTML = `${opts.inline ? "" : '<div class="card">'}${head}${body}${paidToggle ? `<div class="toolbar">${paidToggle}</div>` : ""}${opts.inline ? "" : "</div>"}`;
  const t = box.querySelector("[data-pbpaid]");
  if (t) t.onchange = () => loadPlanB(cod, { ...opts, box, includePaid: t.checked });
  if (opts.onPin) {
    box.querySelectorAll("[data-pbpin]").forEach((el) => {
      el.onclick = () => { const a = d.alternatives.find((x) => x.cod_aff_form === el.dataset.pbpin); if (a) opts.onPin(a); };
    });
  }
}

// ---- B1: success in licence, per university x broad discipline (SIES, not per formation) -----
const SU_KINDS = [["passage", "Passage en L2 en un an", "entrés en L1 en"], ["reussite3", "Licence obtenue en 3 ans", "entrés en L1 en"],
  ["reussite34", "Licence obtenue en 3 ou 4 ans", "entrés en L1 en"]];
const SU_MASK = { ns: "petit effectif, non publié", nd: "non disponible", na: "—", vide: "—", texte: "—", type: "—" };
const SU_DEVENIR = [["taux", "passage en L2", "s-pass"], ["taux_redoublement", "redoublement", "s-red"],
  ["taux_reorientation", "réorientation", "s-reo"], ["taux_sortie", "sortie de l'enseignement supérieur", "s-out"]];
const pc1d = (v) => `${Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`;
const suVal = (row, key) => (row && row[key] != null ? `${pc1d(row[key])}\u00a0%` : row && row.masked && row.masked[key] ? `<span class="muted small">${SU_MASK[row.masked[key]] || "—"}</span>` : "—");
function suBar(row) {
  if (!row || SU_DEVENIR.some(([k]) => row[k] == null)) return "";
  return `<div class="sbar" role="img" aria-label="${SU_DEVENIR.map(([k, l]) => `${l} ${fmt(row[k], 1)} %`).join(", ")}">${SU_DEVENIR.map(([k, l, c]) => `<span class="${c}" style="width:${Math.max(0, Math.min(100, row[k]))}%" title="${l} : ${fmt(row[k], 1)} %"></span>`).join("")}</div>`;
}
// Reliability of one link of the evidence chain (graded server-side by fixed rules: evidence.py)
const FIAB_LABEL = { A: "solide", B: "à nuancer", C: "fragile" };
function fiabBadge(m) {
  if (!m || !m.fiabilite) return '<span class="muted small">—</span>';
  const g = ["A", "B", "C"].includes(m.fiabilite) ? m.fiabilite : "C";
  return `<span class="badge fiab fiab-${g}" title="${esc((m.raisons || []).join(" ; "))}">${g} · ${FIAB_LABEL[g]}</span>`;
}
function successCard(s) {
  if (!s) return "";
  const head = `<h2>Réussite en licence ${tip("success")}</h2>`;
  if (!s.kinds || !Object.keys(s.kinds).length) {
    return `<div class="card">${head}<p class="small muted">${s.etab_label ? `${esc(s.etab_label)} : ` : ""}${esc(s.reason || "non publié")}.</p></div>`;
  }
  const P = s.kinds.passage, N = s.national.passage;
  const small = Object.values(s.kinds).some((k) => k.small);
  const rows = SU_KINDS.map(([k, label, when]) => {
    const u = s.kinds[k], n = s.national[k];
    if (!u && !n) return "";
    const coh = (u || n).cohort;
    const exp = u && u.taux_simule != null && u.va != null
      ? `${pc1d(u.taux_simule)} %<div class="muted small">écart ${u.va > 0 ? "+" : ""}${pc1d(u.va)} pt</div>` : `<span class="muted small">—</span>`;
    return `<tr><td>${label}<div class="muted small">${when} ${esc(coh)}${u && u.inscrits != null ? ` · ${fmt(u.inscrits)} inscrits` : ""}</div><div class="fiab-row">${fiabBadge(u && u.maillon)}</div></td>
      <td class="num"><strong>${suVal(u, "taux")}</strong></td><td class="num">${exp}</td><td class="num">${suVal(n, "taux")}</td></tr>`;
  }).join("");
  const bars = P && suBar(P) ? `<div class="su-devenir"><div class="small">Un an après l'entrée en L1 (inscrits en ${esc(P.cohort)})</div>
      <div class="su-line"><span class="small muted">Université</span>${suBar(P)}</div>
      ${N && suBar(N) ? `<div class="su-line"><span class="small muted">France</span>${suBar(N)}</div>` : ""}
      <div class="legend"><span class="muted">Université :</span>${SU_DEVENIR.map(([k, l, c]) => `<span><i class="${c}"></i>${l} ${pc1d(P[k])} %</span>`).join("")}${N ? `<span class="muted">France : ${SU_DEVENIR.map(([k]) => `${pc1d(N[k])} %`).join(" · ")}</span>` : ""}</div></div>` : "";
  return `<div class="card">${head}
    <p class="small"><strong>${esc(s.etab_label)}</strong> · ${esc(s.discipline_label)}. Chiffres de <strong>tous les nouveaux bacheliers inscrits en L1</strong> de cette grande discipline dans l'université, pas seulement de cette licence.${small ? ' <span class="badge warnb">petit effectif</span>' : ""}</p>
    <div class="scroll"><table><tr><th>Indicateur · fiabilité ${tip("fiabilite")}</th><th class="num">Cette université</th><th class="num">Attendu vu le profil des inscrits ${tip("success")}</th><th class="num">France, même discipline</th></tr>${rows}</table></div>
    ${bars}
    <p class="muted small">Source : SIES (ministère de l'Enseignement supérieur), tableaux par établissement et discipline. Résultats de cohortes passées, pas des chances de réussite ; l'écart au taux attendu ne classe pas les universités.</p></div>`;
}

// ---- Sprint 6: success beyond licence (BUT per university; master per university x discipline) ----
// The student's profile stays in the browser: the page picks the national rows that match it.
const MENTION_ROW = { rattrapage: "passable2", sansmention: "passable1", ab: "ab", b: "b", tb: "tb", tbf: "tb" };   // R5: TBF is counted in "très bien" there
const MENTION_TXT = { passable1: "passable (1er groupe)", passable2: "passable (2nd groupe, rattrapage)", ab: "assez bien", b: "bien", tb: "très bien" };
const SERIE_TXT = { bg: "bac général", bt: "bac technologique", bp: "bac professionnel" };
function profileRows(rows, kind) {
  // kind "but": rows of BUT Tableau 1 (dim serie|mention); kind "chaine": the 2017 L1 cohort (dim bac|mention)
  const p = bacProfile() || {};
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";   // stored profile: never trusted
  const men = MENTION_ROW[vxProfile({ mention: "ab", ...p }).mention] || "ab";
  const sdim = kind === "but" ? "serie" : "bac";
  const pick = (dim, code) => (rows || []).find((r) => r.dim === dim && r.code === code);
  let s = pick(sdim, serie), sLabel = SERIE_TXT[serie], note = "";
  const code = (x) => typeof x === "string" && /^[A-Z]{2,7}$/.test(x);     // journey.SPECIALTIES codes
  if (kind === "but" && serie === "bg") {
    if (code(p.spe1) && code(p.spe2) && p.spe1 !== p.spe2) {
      const d = pick("serie", `bg:${[p.spe1, p.spe2].sort().join("+")}`);
      if (d) { s = d; sLabel = `bac général ${esc(speName(p.spe1))} + ${esc(speName(p.spe2))}`; }
      else note = "vos deux spécialités ne sont pas publiées à part (moins de 1 % des inscrits) : ligne de l'ensemble du bac général";
    }
  }
  return { serie: s, serieLabel: sLabel, mention: pick("mention", men), mentionLabel: `mention ${MENTION_TXT[men]}`,
    ensemble: pick("ensemble", "ensemble"), note };
}
const statusCard = (title, x, more, src) => `<div class="card"><h2>${title}</h2><p class="small muted">${x.etab_label ? `${esc(x.etab_label)} : ` : ""}${esc(x.reason || "non publié")}.</p>${more}
  <p class="muted small">Source : SIES (ministère de l'Enseignement supérieur), Note Flash ${src}. Résultats de cohortes passées, pas des chances de réussite.</p></div>`;
const expCell = (u) => (u && u.taux_simule != null && u.va != null
  ? `${pc1d(u.taux_simule)}\u00a0%<div class="muted small">écart ${u.va > 0 ? "+" : ""}${pc1d(u.va)}\u00a0pt</div>` : `<span class="muted small">—</span>`);
function butCard(b) {
  if (!b) return "";
  const head = `Réussite en BUT ${tip("but")}`;
  const R = b.kinds && b.kinds.reussite3, P = b.kinds && b.kinds.poursuite, NR = b.national.reussite3, NP = b.national.poursuite;
  const pr = profileRows(b.profil, "but");
  const prof = [[pr.serieLabel, pr.serie], [pr.mentionLabel, pr.mention]].filter(([, r]) => r)
    .map(([l, r]) => `<tr><td>${l}</td><td class="num">${suVal(r, "passage2")}</td><td class="num"><strong>${suVal(r, "taux")}</strong></td></tr>`).join("");
  const spe = b.specialite ? `<p class="small">En France, en <strong>${esc(b.specialite.label)}</strong> : <strong>${suVal(b.specialite, "taux")}</strong> des inscrits ont obtenu leur BUT en 3 ans (passage en 2e année : ${suVal(b.specialite, "passage2")} ; entrés en ${esc(b.specialite.cohort)}).</p>` : "";
  const profBox = prof ? `<h3 class="small">Selon le profil de bac, en France (toutes spécialités, entrés en ${esc((pr.serie || pr.mention).cohort)})</h3>
    <div class="scroll"><table><tr><th>Profil</th><th class="num">Passage en 2e année</th><th class="num">BUT en 3 ans</th></tr>${prof}</table></div>
    <p class="muted small">Deux lignes séparées : le ministère ne croise pas la série et la mention.${pr.note ? ` ${esc(pr.note)}.` : ""}</p>` : "";
  if (!R && !P) return statusCard(head, b, `${spe}${profBox}`, "2025-26");
  const rows = [];
  if (R) rows.push(`<tr><td>BUT obtenu en 3 ans<div class="muted small">entrés en ${esc(R.cohort)}${R.inscrits != null ? ` · ${fmt(R.inscrits)} inscrits` : ""}</div><div class="fiab-row">${fiabBadge(R.maillon)}</div></td>
      <td class="num"><strong>${suVal(R, "taux")}</strong></td><td class="num">${expCell(R)}</td><td class="num">${suVal(NR, "taux")}</td></tr>`);
  if (P) rows.push(`<tr><td>Poursuite d'études l'année suivante<div class="muted small">diplômés en 3 ans${P.n_diplomes != null ? ` · ${fmt(P.n_diplomes)} diplômés` : ""}</div><div class="fiab-row">${fiabBadge(P.maillon)}</div></td>
      <td class="num"><strong>${suVal(P, "taux_poursuite")}</strong></td><td class="num"><span class="muted small">—</span></td><td class="num">${suVal(NP, "taux_poursuite")}</td></tr>`);
  const MB = b.masters_but3, mbu = MB && MB.universite;
  const but3 = MB ? `<p class="small">Passerelle vers le master : en ${esc(MB.session)}, ${mbu ? `les masters de l'université ont admis <strong>${fmt(mbu.n_accept_but3)}</strong> titulaires d'un BUT (${pcs(mbu.part_but3)} de leurs admis) ; ` : ""}en France, ${pcs(MB.france.part_but3)} des admis en master venaient d'un BUT (MonMaster).</p>` : "";
  const after = P && P.taux_master != null ? `<p class="small">Après le BUT, parmi les diplômés de l'université : master ${suVal(P, "taux_master")}, école de commerce ${suVal(P, "taux_commerce")}, école d'ingénieurs ${suVal(P, "taux_ingenieur")}${NP ? ` <span class="muted">(France : ${suVal(NP, "taux_master")}, ${suVal(NP, "taux_commerce")}, ${suVal(NP, "taux_ingenieur")})</span>` : ""}.</p>` : "";
  return `<div class="card"><h2>${head}</h2>
    <p class="small"><strong>${esc(b.etab_label)}</strong> · toutes spécialités de BUT. Chiffres de <strong>tous les nouveaux bacheliers inscrits en 1re année de BUT</strong> dans l'université : le ministère ne les publie ni par IUT, ni par spécialité.${R && R.small ? ' <span class="badge warnb">petit effectif</span>' : ""}</p>
    <div class="scroll"><table><tr><th>Indicateur · fiabilité ${tip("fiabilite")}</th><th class="num">Cette université</th><th class="num">Attendu vu le profil des inscrits ${tip("but")}</th><th class="num">France</th></tr>${rows.join("")}</table></div>
    ${after}${but3}${butInsertion(b.insertion)}${spe}${profBox}
    <p class="muted small">Source : SIES (ministère de l'Enseignement supérieur), Note Flash 2025-26. Résultats de cohortes passées, pas des chances de réussite ; l'écart au taux attendu ne classe pas les universités.</p></div>`;
}
const M2_DEVENIR = [["taux", "passage en M2", "s-pass"], ["taux_redoublement", "redoublement en M1", "s-red"],
  ["reo", "réorientation", "s-reo"], ["taux_sortie", "sortie", "s-out"]];
function m2Parts(r) {
  // the four published reorientation shares are added up for the bar (the table keeps them apart)
  const reo = ["taux_reo_univ", "taux_reo_ingenieur", "taux_reo_management", "taux_reo_autres"];
  if (!r || reo.some((k) => r[k] == null) || r.taux == null || r.taux_redoublement == null || r.taux_sortie == null) return null;
  return { taux: r.taux, taux_redoublement: r.taux_redoublement, reo: reo.reduce((a, k) => a + r[k], 0), taux_sortie: r.taux_sortie };
}
function m2Bar(r) {
  const x = m2Parts(r);
  if (!x) return "";
  return `<div class="sbar" role="img" aria-label="${M2_DEVENIR.map(([k, l]) => `${l} ${fmt(x[k], 1)} %`).join(", ")}">${M2_DEVENIR.map(([k, l, c]) => `<span class="${c}" style="width:${Math.max(0, Math.min(100, x[k]))}%" title="${l} : ${fmt(x[k], 1)} %"></span>`).join("")}</div>`;
}
const M_KINDS = [["passage_m2", "Passage en M2 en un an", "entrés en M1 en"], ["reussite23", "Master obtenu en 2 ou 3 ans", "entrés en M1 en"]];
function masterCard(m) {
  if (!m) return "";
  const head = `Et après la licence : le master ${tip("master")}`;
  const pr = profileRows(m.chaine, "chaine");
  const chain = [[pr.serieLabel, pr.serie], [pr.mentionLabel, pr.mention], ["tous les bacheliers", pr.ensemble]].filter(([, r]) => r)
    .map(([l, r]) => `<tr><td>${l}</td><td class="num">${suVal(r, "licence34")}</td><td class="num">${suVal(r, "passage_master")}</td><td class="num"><strong>${suVal(r, "master567")}</strong></td></tr>`).join("");
  const chainBox = chain ? `<h3 class="small">Le parcours complet, en France : bacheliers ${esc((pr.ensemble || pr.serie).cohort)} entrés en L1 ${tip("master")}</h3>
    <div class="scroll"><table><tr><th>Profil</th><th class="num">Licence en 3 ou 4 ans</th><th class="num">Entrée en master</th><th class="num">Master en 5 à 7 ans</th></tr>${chain}</table></div>
    <p class="muted small">Une cohorte suivie de bout en bout (pas une multiplication de taux). Lignes séparées : le ministère ne croise pas le type de bac et la mention.</p>` : "";
  const pl = (m.poursuite_lg || []).filter((r) => r.code === (m.discipline || "toutes")).sort((a, b) => a.cohort - b.cohort);
  const plBox = pl.length ? `<p class="small">En France, ${m.discipline ? `en ${esc(m.discipline_label)}` : "toutes disciplines"}, part des diplômés de licence inscrits en master l'année suivante : ${pl.map((r) => `<span class="nowrap">${esc(r.cohort)} <strong>${suVal(r, "taux")}</strong></span>`).join(" · ")}.</p>` : "";
  if (!m.kinds || !Object.keys(m.kinds).length) return statusCard(head, m, `${plBox}${chainBox}`, "2025-30");
  const rows = M_KINDS.map(([k, label, when]) => {
    const u = m.kinds[k], n = m.national[k];
    if (!u && !n) return "";
    return `<tr><td>${label}<div class="muted small">${when} ${esc((u || n).cohort)}${u && u.inscrits != null ? ` · ${fmt(u.inscrits)} inscrits` : ""}</div><div class="fiab-row">${fiabBadge(u && u.maillon)}</div></td>
      <td class="num"><strong>${suVal(u, "taux")}</strong></td><td class="num">${expCell(u)}</td><td class="num">${suVal(n, "taux")}</td></tr>`;
  }).join("");
  const P = m.kinds.passage_m2, N = m.national.passage_m2, x = m2Parts(P), xn = m2Parts(N);
  const bars = x ? `<div class="su-devenir"><div class="small">Un an après l'entrée en M1 (inscrits en ${esc(P.cohort)})</div>
      <div class="su-line"><span class="small muted">Université</span>${m2Bar(P)}</div>
      ${xn ? `<div class="su-line"><span class="small muted">France</span>${m2Bar(N)}</div>` : ""}
      <div class="legend"><span class="muted">Université :</span>${M2_DEVENIR.map(([k, l, c]) => `<span><i class="${c}"></i>${l} ${pc1d(x[k])} %</span>`).join("")}${xn ? `<span class="muted">France : ${M2_DEVENIR.map(([k]) => `${pc1d(xn[k])} %`).join(" · ")}</span>` : ""}</div></div>` : "";
  return `<div class="card"><h2>${head}</h2>
    <p class="small"><strong>${esc(m.etab_label)}</strong> · ${esc(m.discipline_label)}. Chiffres de <strong>tous les étudiants entrés en M1</strong> de cette grande discipline dans l'université, d'où qu'ils viennent : ce ne sont pas les diplômés de cette licence.${Object.values(m.kinds).some((k) => k.small) ? ' <span class="badge warnb">petit effectif</span>' : ""}</p>
    <div class="scroll"><table><tr><th>Indicateur · fiabilité ${tip("fiabilite")}</th><th class="num">Cette université</th><th class="num">Attendu vu le profil des inscrits ${tip("master")}</th><th class="num">France, même discipline</th></tr>${rows}</table></div>
    ${bars}${plBox}${chainBox}
    <p class="muted small">Source : SIES (ministère de l'Enseignement supérieur), Note Flash 2025-30. Résultats de cohortes passées, pas des chances de réussite ; l'écart au taux attendu ne classe pas les universités.</p></div>`;
}

// ---- Sprint 7: gateways (reorientation after L1, the university's masters on MonMaster) ----
const REO_LINES = [["taux_hors_univ", "hors de l'université", 0], ["taux_sts_app", "BTS en apprentissage", 1], ["taux_sts", "BTS hors apprentissage", 1],
  ["taux_cpge", "classe préparatoire (CPGE)", 1], ["taux_commerce", "école de commerce", 1], ["taux_ingenieur", "école d'ingénieurs", 1],
  ["taux_univ", "à l'université, hors licence", 0], ["taux_but", "BUT", 1], ["taux_infirmier", "diplôme d'État d'infirmier", 1]];
const ORIG_LABEL = { lg3: "L3 de licence générale", but3: "BUT (3e année)", lp3: "licence professionnelle", master: "déjà en master",
  autre: "autre formation", noninscri: "non inscrits l'année d'avant" };
const pcs = (v) => (v == null ? "—" : `${pc1d(v)}\u00a0%`);
function reoTable(r, n) {
  const rows = REO_LINES.map(([k, l, sub]) => `<tr><td${sub ? ' class="sub"' : ""}>${sub ? "dont " : ""}${l}</td><td class="num">${suVal(r, k)}</td><td class="num">${suVal(n, k)}</td></tr>`).join("");
  return `<div class="scroll"><table><tr><th>Sur 100 inscrits en L1 · fiabilité ${tip("fiabilite")}</th><th class="num">Cette université</th><th class="num">France, même discipline</th></tr>
    <tr><td><strong>Se réorientent l'année suivante</strong><div class="muted small">entrés en L1 en ${esc(r.cohort)}${r.inscrits != null ? ` · ${fmt(r.inscrits)} inscrits` : ""}</div><div class="fiab-row">${fiabBadge(r.maillon)}</div></td>
      <td class="num"><strong>${suVal(r, "taux_reorientation")}</strong></td><td class="num">${suVal(n, "taux_reorientation")}</td></tr>${rows}</table></div>
    <p class="muted small">Ce sont des parts des inscrits en L1, pas des réorientés. Le détail publié n'est pas complet : les autres réorientés suivent des formations que le ministère ne détaille pas.</p>`;
}
function mastersBox(p) {
  const m = p.masters, f = p.masters_france;
  if (!m) return `<p class="small muted">MonMaster ne recense pas de master de cette université dans cette grande discipline.</p>`;
  const orig = Object.keys(ORIG_LABEL).filter((o) => m.parts_origine[o] != null && m.origines[o] > 0)
    .map((o) => `<span class="nowrap">${ORIG_LABEL[o]} ${pcs(m.parts_origine[o])}</span>`).join(" · ");
  const ment = (m.mentions || []).map((x) => `<tr><td>${esc(x.mention)}</td><td class="num">${fmt(x.n_can)}</td><td class="num"><strong>${fmt(x.n_accept)}</strong></td><td class="num">${fmt(x.n_accept_etab)}</td></tr>`).join("");
  return `<p class="small">En ${esc(m.session)}, ${fmt(m.n_offres)} formations de master (${fmt(m.n_mentions)} mentions) : <strong>${fmt(m.n_accept)} admis</strong> pour ${fmt(m.n_can)} candidatures (des vœux : une même personne postule à plusieurs masters).</p>
    <p class="small"><strong>${pcs(m.part_etab)}</strong> des admis étaient déjà inscrits dans cette université${f ? ` <span class="muted">(France, même discipline : ${pcs(f.part_etab)})</span>` : ""}. ${fiabBadge(m.maillon)}</p>
    <p class="small">D'où venaient les admis : ${orig}.</p>
    ${ment ? `<div class="scroll"><table><tr><th>Mention (les plus grandes)</th><th class="num">Vœux</th><th class="num">Admis</th><th class="num">Déjà à l'univ.</th></tr>${ment}</table></div>` : ""}
    ${p.meef ? `<p class="small muted">Masters de l'enseignement (MEEF) de l'université, ouverts à toutes les licences : ${fmt(p.meef.n_accept)} admis en ${esc(p.meef.session)}.</p>` : ""}
    <p class="muted small">Parts calculées à partir des effectifs publiés par MonMaster. Ce sont des admis passés, pas des chances d'admission.</p>`;
}
function passerellesCard(p) {
  if (!p) return "";
  const head = `Passerelles : changer de voie, entrer en master ${tip("passerelles")}`;
  if (p.status !== "ok") return statusCard(head, p, "", "2025-29 et MonMaster");
  const r = p.reorientation, n = p.reorientation_france;
  return `<div class="card"><h2>${head}</h2>
    <p class="small"><strong>${esc(p.etab_label)}</strong> · ${esc(p.discipline_label)}. Chiffres de toute la grande discipline dans l'université, pas seulement de cette licence.</p>
    <h3 class="small">Après la L1 : ceux qui changent de voie</h3>
    ${r ? reoTable(r, n) : `<p class="small muted">Non publié pour cette université et cette discipline.</p>`}
    <h3 class="small">Après la licence : les masters de l'université dans cette discipline (MonMaster)</h3>
    ${mastersBox(p)}
    <p class="muted small">Sources : SIES (ministère de l'Enseignement supérieur), Note Flash 2025-29 (réorientations) et MonMaster (candidatures et admissions en master). Résultats passés, pas des chances de réussite ou d'admission.</p></div>`;
}

// ---- Sprint 16: de la licence au master, chaque master côte à côte (MonMaster, InserSup, Onisep, sprints 13-15) ----
// Per master mention of the university in this discipline: admits (people) and vœux, insertion at 18 months among the
// LEAVERS, the jobs of its national Onisep sheet with the RANGES of their ILO score and θ and COUNTS per 2030 reading;
// landmarks only when two ranges are disjoint; never an average, never a single score, never a chance.
const LM_REPERE = {
  ia_plus_bas: "Les métiers visés par ce master sont tous moins exposés à l'IA générative (OIT) que les débouchés directs de la licence.",
  ia_plus_haut: "Les métiers visés par ce master sont tous plus exposés à l'IA générative (OIT) que les débouchés directs de la licence.",
  complementarite_plus_haute: "Les métiers visés par ce master ont tous une complémentarité humaine plus haute que les débouchés directs de la licence.",
  complementarite_plus_basse: "Les métiers visés par ce master ont tous une complémentarité humaine plus basse que les débouchés directs de la licence.",
};
function licenceMasterCard(x) {
  if (!x) return "";
  const head = `De la licence au master : chaque master côte à côte ${tip("licence_master")}`;
  if (x.status !== "ok") return `<div class="card"><h2>${head}</h2><p class="small muted">${esc(x.reason || "")}</p></div>`;
  const two = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const span = (lo, hi) => (lo === null || lo === undefined ? "—" : two(lo) === two(hi) ? two(lo) : `${two(lo)} à ${two(hi)}`);
  const c2030 = (c) => {
    if (!c) return "—";
    const parts = [[c.insuffisants, "où les débutants ne suffiraient pas"], [c.nombreux, "où les débutants seraient nombreux"], [c.incertain, "incertains"], [c.non_lu, "sans projection"]]
      .filter(([n]) => n > 0).map(([n, l]) => `${fmt(n)} ${l}`);
    return parts.join(" · ") || "—";
  };
  const row = (m) => {
    const j = m.metiers, ins = m.insertion;
    const jobs = j ? `<details><summary>${fmt(j.n_metiers)} métier${j.n_metiers > 1 ? "s" : ""}</summary><div class="small">${j.metiers.map((e) => `<a href="#/metiers/${esc(e.id)}">${esc(e.nom)}</a>`).join(" · ")}</div></details>${m.onisep && m.onisep.regle === "orthographe" ? '<div class="muted small">fiche Onisep reliée malgré une orthographe différente</div>' : ""}`
      : '<span class="muted">métiers non documentés</span>';
    const emploi = ins ? `${ins.taux_emploi === null || ins.taux_emploi === undefined ? '<span class="muted">taux non publié</span>' : pct(ins.taux_emploi)}<div class="muted small">${fmt(ins.sortants)} sortants${ins.regroupe ? ", promotions regroupées" : ""}</div>` : '<span class="muted">non publié</span>';
    const rep = (m.reperes || []).map((r) => `<div class="small">${esc(LM_REPERE[r] || "")}</div>`).join("");
    return `<tr><td><strong>${esc(m.mention)}</strong>${rep}</td><td class="num" data-label="Admis">${fmt(m.n_accept)}<div class="muted small">${fmt(m.n_can)} vœux</div></td>
      <td class="num" data-label="Emploi salarié à 18 mois">${emploi}</td><td data-label="Métiers visés">${jobs}</td>
      <td class="num" data-label="IA générative (OIT)">${j ? span(j.ilo_min, j.ilo_max) : "—"}</td>
      <td class="num" data-label="Complémentarité humaine">${j ? span(j.theta_min, j.theta_max) : "—"}</td>
      <td class="small" data-label="Emploi d'ici 2030">${j ? c2030(j.classes_2030) : "—"}</td></tr>`;
  };
  const lic = x.licence;
  const licLine = lic ? `<p class="small">Débouchés directs de cette licence (fiche Onisep) : ${fmt(lic.n_metiers)} métier${lic.n_metiers > 1 ? "s" : ""}, exposition des tâches à l'IA générative de ${span(lic.ilo_min, lic.ilo_max)}, complémentarité humaine de ${span(lic.theta_min, lic.theta_max)}.</p>` : "";
  return `<div class="card"><h2>${head}</h2>
    <p class="small"><strong>${esc(x.etab_label)}</strong> · ${esc(x.discipline_label)} · masters de l'université dans cette discipline (MonMaster ${esc(x.session)}).</p>
    ${licLine}
    <div class="scroll"><table class="lm"><tr class="lm-head"><th>Master (mention)</th><th class="num">Admis</th><th class="num">Emploi salarié à 18 mois</th><th>Métiers visés</th>
      <th class="num">IA générative (OIT)</th><th class="num">Complémentarité humaine</th><th>Emploi d'ici 2030 (nombre de métiers)</th></tr>
      ${x.mentions.map(row).join("")}</table></div>
    <p class="muted small">Admis : des personnes ; vœux : des candidatures additionnées sur les parcours, pas des personnes. Emploi salarié à 18 mois : parmi les diplômés qui ont quitté les études (InserSup, promotion ${esc(x.annee_insertion)}). Les métiers visés sont ceux de la fiche nationale Onisep du master, pas de cette université. Pour ces métiers, on donne l'écart entre la note la plus basse et la plus haute, jamais une moyenne, et le nombre de métiers selon la projection 2030 ; un métier exposé à l'IA est plus souvent transformé que remplacé, et la complémentarité humaine est une estimation adaptée. Un repère n'apparaît que si les deux écarts ne se chevauchent pas. Ce sont des résultats passés et des projections, pas des chances d'admission ou d'emploi. Sources : ministère de l'Enseignement supérieur (MonMaster, InserSup), Onisep (Idéo, licence ODbL), OIT 2025, O*NET (ministère du Travail des États-Unis), Dares / France Stratégie.</p></div>`;
}

// ---- Prévision n+1: calibrated ranges of every published indicator with a history (never a probability) ----
const PV_GROUPS = [["acces", "Accès et candidats appelés"], ["volumes", "Volumes : vœux, classés, admis"], ["admis", "Profil des admis"]];
const pvVal = (i, v) => (v == null ? "—" : i.kind === "taux" ? `${fmt(v, 1)}\u00a0%` : fmt(v));
const pvRange = (i) => `${pvVal(i, i.lo)} à ${pvVal(i, i.hi)}`;
const pvCov = (i) => (i.coverage == null ? "non testée" : `${fmt(100 * i.coverage, 0)}\u00a0% dans la fourchette en ${i.holdout_year}`);
function pvLine(p, key) {
  const i = p && p.indicators.find((x) => x.indicator === key);
  if (!i) return "";
  // lot 1, PR 11: folded under the published figure (testers read « 8 – 39,5 % » beside it as a competing figure); never removed
  return `<details class="pv-fold small"><summary>Prévision ${esc(p.target)}</summary><strong class="nowrap">${pvRange(i)}</strong> ${tip("prevision")}${i.fragile ? ' <span class="muted">(fourchette moins fiable)</span>' : ""}</details>`;
}
function previsionCard(p) {
  if (!p || !p.indicators.length) return "";
  p.indicators.forEach((i) => { i.holdout_year = p.holdout; });
  const block = ([g, title], open) => {
    const its = p.indicators.filter((i) => i.group === g);
    if (!its.length) return "";
    const rows = its.map((i) => `<tr><td>${esc(label(i.indicator))}</td><td class="num">${pvVal(i, i.last)}</td>
      <td class="num"><strong class="nowrap">${pvRange(i)}</strong></td>
      <td class="small">${pvCov(i)}${i.fragile ? " · <strong>moins fiable</strong>" : ""}</td></tr>`).join("");
    return `<details ${open ? "open" : ""}><summary><strong>${esc(title)}</strong> (${its.length})</summary><div class="scroll"><table>
      <tr><th>Indicateur</th><th class="num">${esc(p.last_session)} publié</th><th class="num">${esc(p.target)} estimé (fourchette à ${fmt(100 * p.level, 0)}\u00a0%)</th><th>Testé sur ${esc(p.holdout)}</th></tr>${rows}</table></div></details>`;
  };
  return `<div class="card"><h2>Prévision ${esc(p.target)} ${tip("prevision")}</h2>
    <p class="small">Fourchettes estimées pour la campagne ${esc(p.target)} à partir des campagnes passées de cette formation. La méthode a été réglée sur ${esc(p.calibration)} puis testée sur ${esc(p.holdout)} sans l'avoir vue : la dernière colonne dit combien de vraies valeurs ${esc(p.holdout)} sont tombées dans leur fourchette (objectif ${fmt(100 * p.level, 0)}\u00a0%).</p>
    ${PV_GROUPS.map((g) => block(g, false)).join("")}
    <p class="muted small">Ce sont des estimations, pas des chiffres officiels, et jamais des chances d'admission. Chaque fourchette est calculée séparément. Les petites formations ont des fourchettes plus larges.</p></div>`;
}

// ---- Sprint 8 follow-up: the jobs a diploma leads to (Onisep Idéo, national, by diploma) ----
const ON_ACCES = { direct: "accessible avec ce diplôme", poursuite: "après une poursuite d'études" };
function metiersCard(m) {
  if (!m) return "";
  const head = `Les métiers visés ${tip("metiers")}`;
  if (m.status !== "ok") return `<div class="card"><h2>${head}</h2><p class="small muted">L'Onisep ne publie pas de fiche pour ce diplôme : pas de liste de métiers.</p></div>`;
  const dips = m.diplomes.map((d) => `<a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.libelle)}</a>`).join(", ");
  const li = m.metiers.map((j) => `<li><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.nom)}</a> <a class="small" href="#/metiers/${esc(j.id)}/${esc(m.cod || "")}" title="Les formations qui préparent à ce métier">formations</a>${j.acces ? ` <span class="muted small">· ${esc(ON_ACCES[j.acces])}${j.acces === "poursuite" && j.niveau_acces_min ? ` (${esc(j.niveau_acces_min)})` : ""}</span>` : ""}</li>`).join("");
  return `<div class="card"><h2>${head}</h2>
    <p class="small">D'après la fiche Onisep du diplôme : ${dips}.${m.diplomes.length > 1 ? " Ce diplôme a plusieurs options ou parcours : métiers de toutes ses fiches." : ""}</p>
    <ul class="small">${li}</ul>
    <p class="muted small">Liste nationale du diplôme, pas propre à cet établissement. Le niveau d'accès vient de la fiche métier de l'Onisep. Ce n'est pas une promesse d'emploi.</p>
    <p class="muted small">Source : Onisep, Idéo (licence ODbL).</p></div>`;
}

// ---- Sprint 8 follow-up: does the job match the training? (Céreq Génération 2017, national, by highest diploma) ----
const CQ_ROWS = [   // [horizon, indicator, label, denominator]
  ["a6ans", "correspondance_ok", "Emploi en lien avec la formation, 6 ans après", "parmi ceux en emploi, déclaré par eux"],
  ["a3ans", "correspondance_ok", "Emploi en lien avec la formation, 3 ans après", "parmi ceux en emploi, déclaré par eux"],
  ["a3ans", "competence_ok", "Employés à leur niveau de compétence, 3 ans après", "parmi ceux en emploi, déclaré par eux"],
  ["a6ans", "taux_emploi", "En emploi, 6 ans après", "parmi tous les sortants"],
  ["a6ans", "taux_edi", "Emploi à durée indéterminée (CDI, fonctionnaire, à son compte)", "parmi ceux en emploi, 6 ans après"],
  ["a6ans", "pos_cadres", "Cadres", "parmi ceux en emploi, 6 ans après"],
  ["a6ans", "pos_prof_int", "Professions intermédiaires", "parmi ceux en emploi, 6 ans après"],
  ["a6ans", "revenu_travail", "Revenu mensuel médian (net, primes incluses)", "ceux en emploi, 6 ans après"],
];
const cqVal = (g, h, k) => {
  const v = g && g.valeurs && g.valeurs[h] ? g.valeurs[h][k] : null;
  return v == null ? '<span class="muted small">—</span>' : k === "revenu_travail" ? `${fmt(v)}\u00a0€` : `${fmt(v)}\u00a0%`;
};
const CQ_RULE = {
  bts_inconnu: "La spécialité de ce BTS (industrielle ou tertiaire) n'est pas connue : chiffres de l'ensemble des bac+2.",
  licence_sans_discipline: "La discipline de cette licence n'est pas connue : chiffres de toutes les licences.",
  cpge_scientifique: "Chiffres des diplômés d'écoles d'ingénieurs, où entrent la plupart des élèves de cette classe.",
  cpge_economique: "Chiffres des diplômés d'écoles de commerce, où entrent la plupart des élèves de cette classe.",
};
function cereqCard(c) {
  if (!c) return "";
  const head = `Le métier correspond-il à la formation ? ${tip("cereq")}`;
  if (c.status !== "ok") {
    return c.regle === "but_absent_de_la_generation_2017" ? `<div class="card"><h2>${head}</h2><p class="small muted">Pas de chiffre : le BUT a été créé en 2021, il n'existait pas pour les jeunes sortis d'études en 2017 qu'interroge le Céreq.</p></div>` : "";
  }
  const cols = [c.groupe, c.suite, c.ensemble].filter(Boolean);
  const note = CQ_RULE[c.regle] ? " " + esc(CQ_RULE[c.regle]) : "";
  const th = cols.map((g, i) => `<th class="num">${i === 0 ? "Ce diplôme" : g === c.suite ? "Si vous poursuivez" : "Tous les sortants"}<div class="muted small">${esc(g.label)}</div></th>`).join("");
  const rows = CQ_ROWS.map(([h, k, l, den]) => `<tr><td>${esc(l)}<div class="muted small">${esc(den)}</div></td>${cols.map((g) => `<td class="num">${cqVal(g, h, k)}</td>`).join("")}</tr>`).join("");
  return `<div class="card"><h2>${head}</h2>
    <p class="small">Jeunes sortis d'études en ${esc(c.generation)} <strong>dont c'est le plus haut diplôme</strong>, France entière, interrogés en ${esc(c.enquetes[3])} et ${esc(c.enquetes[6])} (enquête Génération du Céreq).${note}</p>
    <div class="scroll"><table><tr><th><span class="sr-only">Indicateur</span></th>${th}</tr>${rows}</table></div>
    <p class="muted small">Ce ne sont pas les élèves de cette formation : quelqu'un qui poursuit ses études rejoint un autre groupe. Le lien entre la formation et l'emploi est déclaré par les jeunes en emploi. Ce sont des résultats passés, pas des chances d'emploi.</p>
    <p class="muted small">Source : Céreq, enquête Génération 2017, chiffres clés par diplôme.</p></div>`;
}

// ---- Sprint 8: insertion (BTS: Inserjeunes, this establishment; licence: InserSup, the university's masters) ----
const H = 18;   // the horizon served: the latest one published for every recent class
const isv = (r, k) => (r && r[k] != null ? `${pc1d(r[k])}\u00a0%` : r && r.masked && r.masked[k] === "nd" ? '<span class="muted small">masqué</span>' : '<span class="muted small">—</span>');
const promoTxt = (r) => (r ? `diplômés ${esc(String(r.promo || "").replace(",", " et "))}${r.pooled ? " (deux promotions réunies : moins de 20 sortants)" : ""}` : "");
function insRow(label, r) {
  if (!r) return "";
  return `<tr><td>${label}<div class="muted small">${promoTxt(r)}${r[`nb_sortants_${H}`] != null ? ` · ${fmt(r[`nb_sortants_${H}`])} sortis des études` : ""}</div>${r.maillon ? `<div class="fiab-row">${fiabBadge(r.maillon)}</div>` : ""}</td>
    <td class="num"><strong>${isv(r, `tx_sortants_en_emploi_sal_fr_${H}`)}</strong></td><td class="num">${isv(r, `tx_sortants_en_emploi_stable_${H}`)}</td></tr>`;
}
const INS_HEAD = `<tr><th>Diplômés · fiabilité ${tip("fiabilite")}</th><th class="num">En emploi salarié en France, ${H} mois après</th><th class="num">Emploi stable, parmi ceux en emploi salarié</th></tr>`;
const INS_NOTE = `Taux parmi les diplômés qui ont quitté les études (ceux qui continuent ne sont pas comptés). L'emploi stable est une part de ceux qui ont un emploi salarié, pas de tous les diplômés sortis. Emploi salarié en France seulement. Ce sont des résultats de promotions passées, pas des chances d'emploi.`;
function insertionCard(x) {
  if (!x) return "";
  const head = `Insertion professionnelle ${tip("insertion")}`;
  if (x.rows) {                     // BTS (Inserjeunes)
    if (!x.rows.length) return `<div class="card"><h2>${head}</h2><p class="small muted">${esc(x.reason || "non publié")}.</p>
      <p class="muted small">Source : Inserjeunes (ministère de l'Éducation nationale, DEPP).</p></div>`;
    const dupB = {}; x.rows.forEach((r) => { dupB[r.libelle_formation] = (dupB[r.libelle_formation] || 0) + 1; });
    const rows = x.rows.map((r) => `<tr><td>${esc(r.libelle_formation)}<div class="muted small">${esc(r.voie)}${dupB[r.libelle_formation] > 1 ? ` · code de formation ${esc(r.code)}` : ""}</div></td>
      <td class="num">${isv(r, "taux_poursuite")}</td><td class="num"><strong>${isv(r, "taux_emploi_6")}</strong></td><td class="num">${isv(r, "taux_emploi_12")}</td><td class="num">${isv(r, "taux_emploi_24")}</td></tr>`).join("");
    return `<div class="card"><h2>${head}</h2>
      <p class="small">Dans <strong>cet établissement</strong>, élèves de dernière année de ce BTS (${esc(String(x.annee || "").replace("cumul", "sortis en"))}).${x.status === "options" ? " Le BTS a plusieurs options, publiées séparément : chacune garde ses propres chiffres." : ""}</p>
      <div class="scroll"><table><tr><th>Formation</th><th class="num">Poursuivent leurs études</th><th class="num">En emploi 6 mois après</th><th class="num">12 mois</th><th class="num">24 mois</th></tr>${rows}</table></div>
      <p class="muted small">Les taux d'emploi portent sur ceux qui ont quitté les études ; la poursuite d'études, sur tous les élèves de dernière année. Emploi salarié en France. Les petits effectifs sont masqués par le ministère, qui ne publie pas les effectifs. Ce sont des résultats passés, pas des chances d'emploi.</p>
      <p class="muted small">Source : Inserjeunes (ministère de l'Éducation nationale, DEPP).</p></div>`;
  }
  if (x.status !== "ok") return `<div class="card"><h2>${head}</h2><p class="small muted">${x.etab_label ? `${esc(x.etab_label)} : ` : ""}${esc(x.reason || "non publié")}.</p></div>`;
  // a diploma published in several parts (sectors, sites) keeps each part, named by its sector
  const twice = (arr, k) => { const c = {}; arr.forEach((r) => { c[r[k]] = (c[r[k]] || 0) + 1; }); return (r) => c[r[k]] > 1; };
  const dupM = twice(x.masters, "libelle");
  const ms = x.masters.slice(0, 10).map((m) => insRow(`Master ${esc(m.libelle)}${dupM(m) ? ` <span class="muted small">(${esc(m.sectdis_lib)})</span>` : ""}`, m)).join("");
  const more = x.masters.length > 10 ? `<p class="muted small">… et ${fmt(x.masters.length - 10)} autres masters de cette discipline.</p>` : "";
  const old = x.anciens ? `<p class="muted small">${fmt(x.anciens)} ancien${x.anciens > 1 ? "s" : ""} diplôme${x.anciens > 1 ? "s" : ""} sans promotion ${esc(x.annee)} (fermé${x.anciens > 1 ? "s" : ""} ou renommé${x.anciens > 1 ? "s" : ""}, par exemple avant une fusion d'universités) non affiché${x.anciens > 1 ? "s" : ""}.</p>` : "";
  const parts = (x.en_parties || []).length ? `<p class="muted small">Publiés en plusieurs parties pour la dernière promotion, donc sans chiffre unique : ${x.en_parties.map((l) => `master ${esc(l)}`).join(", ")}.</p>` : "";
  return `<div class="card"><h2>${head}</h2>
    <p class="small">Après un master de <strong>${esc(x.etab_label)}</strong> en ${esc(x.discipline_label)} : chaque master avec ses propres chiffres (le ministère ne publie pas de taux par discipline).</p>
    <div class="scroll"><table>${INS_HEAD}${ms}
      ${insRow("<strong>Tous les masters de l'université</strong>", x.total)}${insRow("<strong>Tous les masters, France</strong>", x.france)}</table></div>${more}${parts}${old}
    <p class="muted small">${INS_NOTE}</p>
    <p class="muted small">Source : InserSup (ministère de l'Enseignement supérieur, SIES).</p></div>`;
}
function butInsertion(i) {
  if (!i || !(i.specialite || i.total || i.france)) return "";
  return `<h3 class="small">Insertion après le BUT ${tip("insertion")}</h3><div class="scroll"><table>${INS_HEAD}
    ${insRow("Cette spécialité dans l'université", i.specialite)}${insRow("Tous les BUT de l'université", i.total)}
    ${insRow("Cette spécialité, France", i.france_specialite)}${insRow("Tous les BUT, France", i.france)}</table></div>
    <p class="muted small">${INS_NOTE} Après un BUT, la plupart des diplômés poursuivent leurs études : ces taux portent sur ceux qui sont partis travailler. Source : InserSup (ministère de l'Enseignement supérieur).</p>`;
}

function offerCard(r, app) {
  const list = offerList(r);
  if (!r.carto_session && !list.length && !(app && app.length)) return "";
  const src = r.carto_session ? `cartographie Parcoursup ${r.carto_session}` : "libellé du ministère";
  return `<div class="card"><h2>Bon à savoir ${tip("offer")}</h2>
    ${list.length ? `<ul class="offer-list">${list.map(([k, t]) => `<li><span aria-hidden="true">${OPT_ICON[k]}</span> ${esc(t)}</li>`).join("")}</ul>`
      : app && app.length ? "" : `<p class="muted small">Ni internat, ni apprentissage, ni enseignement à distance, ni aménagement pour sportifs ou artistes de haut niveau ne sont signalés.</p>`}
    ${appOffers(app)}
    ${INTERNAT_LABEL[r.internat] ? `<p class="small muted">${r.acc_internat != null ? `${fmt(r.acc_internat)} admis logés à l'internat en ${r.session}${r.nb_voe_pp_internat ? ` (${fmt(r.nb_voe_pp_internat)} candidatures avec demande d'internat)` : ""}. ` : ""}L'internat de l'établissement ne garantit pas une place : elle se demande avec le vœu.</p>` : ""}
    <p class="small muted">Source : ${esc(src)}. Ces informations décrivent l'offre telle qu'elle est publiée aujourd'hui ; vérifiez-les sur la fiche Parcoursup.</p></div>`;
}

// Offer timing: the three published shares are cumulative milestones of the main phase.
const TIMING = [["pct_acc_debutpp", "à l'ouverture de la phase principale"], ["pct_acc_datebac", "avant les résultats du bac"], ["pct_acc_finpp", "avant la fin de la phase principale"]];
function timingBar(r) {
  const v = TIMING.map(([k]) => r[k]);
  if (v.some((x) => x == null)) return "";
  const cuts = [0, ...v.map((x) => Math.max(0, Math.min(100, x))), 100];
  const cls = ["t1", "t2", "t3", "t4"];
  const lab = ["dès l'ouverture", "entre l'ouverture et le bac", "après le bac, avant la fin de la phase principale", "après la fin de la phase principale (phase complémentaire, désistements tardifs)"];
  let segs = "";
  for (let i = 0; i < 4; i++) {
    const w = Math.max(0, cuts[i + 1] - cuts[i]);
    if (w > 0) segs += `<span class="tseg ${cls[i]}" style="width:${w}%" title="${fmt(w)} % des admis : proposition ${lab[i]}"></span>`;
  }
  return `<div class="tbar" role="img" aria-label="${TIMING.map(([k, l]) => `${fmt(r[k])} % ${l}`).join(", ")}">${segs}</div>
    <div class="legend"><span><i class="tseg t1"></i>dès l'ouverture</span><span><i class="tseg t2"></i>avant le bac</span><span><i class="tseg t3"></i>avant la fin de la phase principale</span><span><i class="tseg t4"></i>après la phase principale</span></div>`;
}
function timingCard(r, history) {
  // SIES publishes 0 % shares for cohorts with no admits: nothing can be said about their timing
  if (r.pct_acc_debutpp == null || !(r.acc_tot > 0)) return "";
  const later = 100 - r.pct_acc_debutpp;
  const yrs = history.filter((h) => h.pct_acc_debutpp != null && h.acc_tot > 0);
  return `<div class="card"><h2>Quand arrivent les propositions ? ${tip("timing")}</h2>
    ${r.low_n_flag ? `<div class="warn">${ICONS.warn} Seulement ${fmt(r.acc_tot)} admis : ces parts reposent sur très peu d'élèves.</div>` : ""}
    <div class="grid3">${TIMING.map(([k, l]) => `<div><div class="big">${pct(r[k])}</div><div class="muted small">des admis ${r.session} avaient reçu leur proposition ${l}</div></div>`).join("")}</div>
    ${timingBar(r)}
    ${later >= 10 ? `<p class="info">Ne pas avoir de proposition le premier jour n'est pas un refus : en ${r.session}, <strong>${fmt(later)} %</strong> des admis de cette formation ont reçu la leur plus tard, au fil des places libérées.</p>` : `<p class="info">Ici, presque tous les admis (${pct(r.pct_acc_debutpp)}) avaient leur proposition dès l'ouverture : les listes d'attente bougent peu.</p>`}
    ${yrs.length > 1 ? `<div class="scroll"><table><tr><th>Session</th>${TIMING.map(([, l]) => `<th class="num">${esc(l)}</th>`).join("")}<th class="num">Admis</th></tr>
      ${yrs.map((h) => `<tr><td>${h.session}</td>${TIMING.map(([k]) => `<td class="num">${pct(h[k])}</td>`).join("")}<td class="num">${fmt(h.acc_tot)}${h.low_n_flag ? ` <span class="badge warnb">n&lt;${META.low_n_threshold}</span>` : ""}</td></tr>`).join("")}</table></div>` : ""}
  </div>`;
}

const SERIES = [{ key: "acc_bg", name: "Bac général", color: "var(--voie-bg)" }, { key: "acc_bt", name: "Bac techno", color: "var(--voie-bt)" },
  { key: "acc_bp", name: "Bac pro", color: "var(--voie-bp)" }];
// owner, 2026-11-22: the evolution charts are coloured (the grey ramp was unreadable): k1-k3 + the neutral reference k4, each line
// also with its own dash; mentions on a sequential ramp (m1 = TB félicitations, darkest) and the unknown ones in a neutral grey
const EVO = { k1: "var(--k1)", k2: "var(--k2)", k3: "var(--k3)", ref: "var(--k4)" };
const MENTIONS = [{ key: "acc_tbf", name: "TB félicitations", color: "var(--m1)" }, { key: "acc_tb", name: "Très bien", color: "var(--m2)" },
  { key: "acc_b", name: "Bien", color: "var(--m3)" }, { key: "acc_ab", name: "Assez bien", color: "var(--m4)" },
  { key: "acc_sansmention", name: "Sans mention", color: "var(--m5)" }, { key: "acc_mention_non_renseignee", name: "Non renseignée", color: "var(--c5)" }];
// owner, 2026-11-22: year by year, the share of the nouveau bachelier admits (mention known) whose mention is the student's or lower
// (published counts), the share strictly below, and with an average the estimate below it (positionMoyenne, R5: the curve centred
// in the band; the uniform spread gives the other end, in the tooltip). Shares of admits, never a chance: SIES publishes no marks
// and no candidates by mention. All bacs: mentions are not published by series. The average never leaves the browser (R6).
function mentionYears(rows, vp) {
  const band = vp.mention === "rattrapage" ? "sansmention" : vp.mention, g = vp.moyenne;
  return rows.map((r) => {
    const counts = r ? Object.fromEntries(LADDER.map((m) => [m, r[`acc_${m}`] || 0])) : null;
    const n = counts ? LADDER.reduce((a, m) => a + counts[m], 0) : 0;
    if (!n) return null;
    let below = 0;
    for (const m of LADDER) { if (m === band) break; below += counts[m]; }
    const pm = g !== null && g !== undefined ? positionMoyenne(counts, g) : null;
    return { n, below: 100 * below / n, upto: 100 * (below + counts[band]) / n,
      moy: pm ? 100 * pm.normale : null, moyRange: pm ? [100 * Math.min(pm.normale, pm.uniforme), 100 * Math.max(pm.normale, pm.uniforme)] : null };
  });
}
// owner, 2026-11-22 (« lance les 6 propositions »): the context of each campaign (/api/lineage `contexte`, evolution.py)
const bandKey = (txt) => `<p class="muted small mk-key"><svg viewBox="0 0 16 10" aria-hidden="true"><rect class="evo-band" x="0" y="1" width="16" height="8"/></svg> ${txt}</p>`;
const rangeKey = (txt) => `<p class="muted small mk-key"><svg viewBox="0 0 12 12" aria-hidden="true"><rect class="evo-range" x="2" y="1" width="8" height="10"/></svg> ${txt}</p>`;
// 1 + 6: the official access rate, the middle half of the same filière behind it, and the next campaign's range (prevision.py)
function accesEvolutionCard(years, rows, ctx, prev) {
  const col = (k) => rows.map((r) => (r ? r[k] : null));
  const pv = prev && prev.indicators ? prev.indicators.find((i) => i.indicator === "taux_acces_ens") : null;
  const xs = pv && !years.includes(prev.target) ? [...years, prev.target] : years, pad = (a) => xs.map((_, i) => (i < a.length ? a[i] : null));
  const lines = [{ name: "Taux d'accès", color: EVO.k1, dash: "", values: pad(col("taux_acces_ens")) },
    { name: "Part des bacs généraux parmi les appelés", color: EVO.k3, dash: "6 4", values: pad(col("part_terminale_generale_en_position_admis_pp")) }];
  const byYear = (y) => (ctx || []).find((c) => c.session === y);
  const band = { name: "La moitié des formations de la même filière", values: xs.map((y) => { const f = (byYear(y) || {}).filiere; return f && f.p25 != null ? { lo: f.p25, hi: f.p75 } : null; }) };
  // the caption names the campaign the count comes from (Codex, PR #107): the latest one WITH a band, not always the last year
  const lastC = (ctx || []).filter((c) => c.filiere && c.filiere.p25 != null).pop(), lastF = lastC ? lastC.filiere : null;
  const ranges = pv && pv.lo != null && pv.hi != null ? [{ i: xs.indexOf(prev.target), lo: pv.lo, hi: pv.hi, name: `Fourchette ${prev.target} (prévision)` }] : [];
  return `<div class="card"><h2>Taux d'accès, et part des bacs généraux parmi les appelés ${tip("taux_acces_ens")}</h2>
    ${lineLegend(lines)}${lineChart(xs, lines, { band: band.values.some(Boolean) ? band : null, ranges })}
    ${band.values.some(Boolean) ? bandKey(`la moitié des formations «\u00a0${esc(lastF ? lastF.libelle : "")}\u00a0» ont un taux d'accès dans cette bande (${fmt(lastF ? lastF.n : 0)} formations en ${esc(lastC ? lastC.session : "")}).`) : ""}
    ${ranges.length ? rangeKey(`fourchette ${esc(prev.target)} du taux d'accès ${estimTag("prévision", false, true)} : ${fmt(pv.lo, 0)} à ${fmt(pv.hi, 0)} %. Testée sur ${esc(prev.holdout)}, ${fmt(100 * pv.coverage, 0)} % des vraies valeurs tombaient dans leur fourchette${pv.fragile ? " : moins fiable" : ""}. Pas une chance.`) : ""}</div>`;
}
// 2: bac techno / pro, year by year: the line of the student's bac in the formation's own report of that campaign (pickVoie),
// else the formation's published proposal rate of the route; a report without the student's line = no point that year
function voieYears(rps, years, bac, key) {
  return years.map((y) => {
    const rp = (rps || []).find((x) => x.session === y), rows = rp ? ((rp.doublettes || {})[bac] || []) : [];
    if (!key || !rows.length) return null;
    const r = pickVoie(rp, bac, key);
    return r ? { ...r, session: y } : { absent: true, session: y };
  });
}
function voieEvolutionCard(d, years, rps) {
  const p = bacProfile(), vp = p ? vxProfile(p) : null;
  if (!vp || !["bt", "bp"].includes(p.serie) || !d || !d.series || !d.series[vp.serie]) return "";
  const trend = d.series[vp.serie].trend || [], route = years.map((y) => trend.find((t) => t.session === y) || null);
  const own = voieYears(rps, years, vp.serie, vp.voie);
  const vals = own.map((o, i) => (o ? (o.absent ? null : o.taux) : route[i] ? route[i].taux : null));
  if (!vals.some((v) => v != null)) return "";
  const lines = [{ name: `${VOIES[vp.serie].label} : votre bac dans cette formation`, color: EVO.k1, dash: "", mine: true, tag: "vous", values: vals,
    marks: own.map((o) => (o && !o.absent ? "pub" : null)),
    hollow: own.map((o, i) => (o && !o.absent ? (o.confirmes || 0) < DBL_SEUIL : !!route[i] && (route[i].candidats || 0) < DBL_SEUIL)),
    notes: own.map((o, i) => (o ? (o.absent ? "" : `rapport public : ${fmt(o.en_position)} classés assez haut sur ${fmt(o.confirmes)} confirmés${o.source === "autres" ? ", ligne « Autres » du rapport" : ""}`)
      : route[i] && route[i].taux != null ? `taux de proposition de la voie : ${fmt(route[i].candidats)} candidats` : "")) }];
  const pub = own.filter((o) => o && !o.absent).map((o) => o.session), absent = own.filter((o) => o && o.absent).map((o) => o.session);
  return `<div class="card"><h2>Votre bac, année par année</h2>
    <p class="small chart-cap">Part des candidats de votre voie qui ont reçu une proposition ici. Des résultats passés, pas une chance.</p>
    ${lineLegend(lines)}${lineChart(years, lines)}
    ${pub.length ? `<p class="muted small mk-key"><svg viewBox="0 0 12 12" aria-hidden="true"><rect x="1.5" y="1.5" width="9" height="9" fill="${EVO.k1}" stroke="${EVO.k1}" stroke-width="2"/></svg> carré : ligne de votre bac dans le rapport public de la formation · <svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="${EVO.k1}" stroke="${EVO.k1}" stroke-width="2"/></svg> rond : taux de proposition de votre voie, calculé avec les effectifs publiés</p>` : ""}
    ${pub.length ? `<p class="small">Le rapport ne compte que les élèves de terminale en France, classés assez haut pour une proposition. Le taux de votre voie compte tous ses candidats. Les deux chiffres peuvent donc différer.</p>` : ""}
    ${absent.length ? `<p class="small">En ${absent.join(", ")}, le rapport de la formation ne donne pas de ligne pour votre bac : pas de point.</p>` : ""}
    ${!vp.voie ? `<p class="small"><a href="#/profil">Indiquez votre ${esc(VOIE_WORD[vp.serie])} dans «\u00a0Mon profil\u00a0»</a> pour lire la ligne de votre bac dans les rapports publics.</p>` : ""}
    <p class="muted small">Points creux : moins de ${DBL_SEUIL} candidats. Une voie à peu de candidats est rare, pas fermée.</p></div>`;
}
// 3: vœux per place (tension.py's ratio), against the median and the « Forte demande » threshold of the same type
function demandeEvolutionCard(years, ctx, prudence) {
  const at = (f) => years.map((y) => { const c = (ctx || []).find((x) => x.session === y); return c ? f(c.demande) : null; });
  const vals = at((d) => d.par_place);
  if (!vals.some((v) => v != null)) return "";
  const lines = [{ name: "Cette formation", color: EVO.k1, dash: "", values: vals,
    notes: at((d) => (d.par_place != null ? `${fmt(d.voeux)} vœux pour ${fmt(d.places)} places` : "")) },
    { name: "Médiane des formations du même type", color: EVO.ref, dash: "4 3", values: at((d) => d.type_p50) }];
  const p90 = at((d) => d.type_p90), li = p90.reduce((k, v, i) => (v == null ? k : i), -1);
  const top = Math.max(1, ...lines.flatMap((l) => l.values.filter((v) => v != null)));
  const step = [1, 2, 3, 4, 5, 10, 15, 20, 25, 50, 100].find((st) => 4 * st >= top * 1.05) || Math.ceil(top / 4);   // round axis ticks
  return `<div class="card"><h2>Combien de vœux pour une place ?</h2>
    <p class="small chart-cap">Vœux reçus en phase principale, divisés par les places ${estimTag("vœux ÷ places, deux chiffres publiés", false, true)}.</p>
    ${lineLegend(lines)}${lineChart(years, lines, { yMax: 4 * step, unit: "" })}
    ${li >= 0 ? `<p class="small">«\u00a0Forte demande\u00a0» commence à ${fmt(p90[li], 1)} vœux par place en ${esc(years[li])} (les 10 % des formations du même type les plus demandées).</p>` : ""}
    <p class="muted small">${esc(prudence || "")}</p></div>`;
}
// 4: how far the list was called (appel.py's capped depth), campaign by campaign
function appelEvolutionCard(years, ctx) {
  const at = (f) => years.map((y) => { const c = (ctx || []).find((x) => x.session === y); return c ? f(c.appel) : null; });
  const vals = at((a) => a.profondeur);
  if (!vals.some((v) => v != null)) return "";
  const lines = [{ name: "Part des candidats classés qui ont reçu une proposition", color: EVO.k1, dash: "", values: vals,
    notes: at((a) => (a.profondeur == null ? "" : a.toute_la_liste ? `toute la liste des ${fmt(a.classes)} classés` : `sur ${fmt(a.classes)} classés`)) }];
  const whole = years.filter((_, i) => { const c = (ctx || []).find((x) => x.session === years[i]); return c && c.appel.toute_la_liste; });
  return `<div class="card"><h2>Jusqu'où la liste a\u2011t\u2011elle été appelée ?</h2>
    <p class="small chart-cap">Part des candidats classés par le jury qui ont reçu une proposition en phase principale.</p>
    ${lineLegend(lines)}${lineChart(years, lines)}
    ${whole.length ? `<p class="small">Toute la liste a été appelée en ${whole.join(", ")}.</p>` : ""}
    <p class="muted small">${APPEL_NOTE} Calcul : somme des rangs des derniers appelés, divisée par le nombre de classés.</p></div>`;
}
// 5: when the offers came: the three published cumulative shares of the admits (zero-admit campaigns left out)
function timingEvolutionCard(years, rows) {
  const ok = rows.map((r) => !!r && r.acc_tot > 0 && r.pct_acc_debutpp != null);
  if (!ok.some(Boolean)) return "";
  const lines = TIMING.map(([k, l], i) => ({ name: `Proposition reçue ${l}`, color: [EVO.k1, EVO.k3, EVO.ref][i], dash: ["", "6 4", "4 3"][i],
    values: rows.map((r, j) => (ok[j] ? r[k] : null)), hollow: rows.map((r, j) => ok[j] && !!r.low_n_flag) }));
  return `<div class="card"><h2>Quand arrivent les propositions ? ${tip("timing")}</h2>
    <p class="small chart-cap">Part des admis qui avaient déjà reçu leur proposition à chaque date.</p>
    ${lineLegend(lines)}${lineChart(years, lines)}
    <p class="muted small">Ne pas avoir de proposition le premier jour n'est pas un refus : des places se libèrent pendant toute la phase. Points creux : peu d'admis.</p></div>`;
}
function mentionEvolutionCard(years, rows) {
  const raw = store.get("profile", null);
  if (isReo(raw)) return "";
  const p = bacProfile(), known = !!p && (validMoyenne(p.moyenne) !== null || MENTION_CODES.includes(p.mention));   // never vxProfile's default band
  const vp = known ? vxProfile(p) : null;
  const head = `<h2>Vous parmi les admis : leur mention au bac, comparée à la vôtre</h2>`;
  if (!vp) return `<div class="card">${head}<p class="small"><a href="#/profil">${p ? "Indiquez votre mention visée dans « Mon profil »" : "Créez votre profil"}</a> pour voir, année par année, la part des admis dont la mention était la vôtre ou plus basse.</p></div>`;
  const band = vp.mention === "rattrapage" ? "sansmention" : vp.mention, M = MENTION_SHORT[band];
  const ys = mentionYears(rows, vp), small = ys.map((x) => !!x && x.n < 20);
  const withAvg = vp.moyenne !== null;
  const lines = [{ name: `Mention «\u00a0${M}\u00a0» ou moins`, color: withAvg ? EVO.k3 : EVO.k1, dash: withAvg ? "6 4" : "", mine: !withAvg, tag: withAvg ? "" : "vous", values: ys.map((x) => (x ? x.upto : null)), hollow: small }];
  if (band !== "sansmention") lines.push({ name: `Mention plus basse que «\u00a0${M}\u00a0»`, color: EVO.ref, dash: "4 3", values: ys.map((x) => (x ? x.below : null)), hollow: small });
  if (vp.moyenne !== null) {
    lines.unshift({ name: `Note en dessous de ${moyenneText(vp.moyenne)} (estimation)`, color: EVO.k1, dash: "", mine: true, tag: "vous", marks: ys.map(() => "est"), values: ys.map((x) => (x ? x.moy : null)), hollow: small,
      notes: ys.map((x) => (x ? `estimation : entre ${pc1(x.moyRange[0] / 100)} et ${pc1(x.moyRange[1] / 100)} selon la répartition des notes dans la mention` : "")) });
  }
  const li = ys.reduce((k, x, i) => (x ? i : k), -1), last = li >= 0 ? ys[li] : null;
  const sentence = last ? `<p>En ${esc(years[li])}, ${last.moy !== null ? `environ <strong>${fmt(last.moy, 0)} %</strong> des ${fmt(last.n)} admis nouveaux bacheliers dont la mention est connue avaient une note en dessous de ${moyenneText(vp.moyenne)} (estimation), et ${fmt(last.upto, 0)} %` : `<strong>${fmt(last.upto, 0)} %</strong> des ${fmt(last.n)} admis nouveaux bacheliers dont la mention est connue`} avaient « ${esc(M)} » ou moins${band === "sansmention" && vp.mention === "rattrapage" ? " (le bac au rattrapage est compté avec « sans mention »)" : ""}.${last.n < 20 ? ` <span class="badge warnb">peu d'admis (${fmt(last.n)}) : repère fragile</span>` : ""}</p>` : "";
  return `<div class="card">${head}${sentence}
    <p class="small chart-cap">Part des admis nouveaux bacheliers, mention connue. Des parts d'admis, pas une chance.</p>
    ${lineLegend(lines)}${lineChart(years, lines)}
    ${vp.moyenne !== null ? estimTag(`losanges : votre moyenne placée dans votre mention`, true) : ""}
    <details class="dip"><summary>Comment lire cette courbe</summary>
    <p class="small">Plus la part est haute, plus les admis de la formation avaient une mention comme la vôtre ou plus basse.</p>
    ${vp.moyenne !== null ? `<p class="small">La courbe en tirets place votre moyenne de ${moyenneText(vp.moyenne)} à l'intérieur de votre mention. Le ministère ne publie pas les notes : c'est une estimation.</p>` : ""}
    <p class="muted small">Calculé avec les nombres d'admis publiés par mention, tous bacs confondus : les mentions ne sont pas publiées par série. Points creux : moins de 20 admis dont la mention est connue. Des parts d'admis, pas des chances d'admission.</p></details></div>`;
}

// one plain sentence under the title: the official access rate of the first and the latest campaign with one (published figures)
function evoTakeaway(years, rates) {
  const idx = rates.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0);
  if (idx.length < 2) return "";
  const a = idx[0], b = idx[idx.length - 1];
  return `<p>Taux d'accès officiel : <strong>${fmt(rates[a], 0)} %</strong> en ${esc(years[a])}, <strong>${fmt(rates[b], 0)} %</strong> en ${esc(years[b])}.</p>`;
}
// the latest campaign's split by bac route, in words (the thin slices of the bars are read here, not by their colour)
function seriesWords(years, rows) {
  const i = rows.reduce((k, r, j) => (r && SERIES.reduce((a, s) => a + (r[s.key] || 0), 0) ? j : k), -1);
  if (i < 0) return "";
  const r = rows[i], n = SERIES.reduce((a, s) => a + (r[s.key] || 0), 0);
  return `<p class="small">En ${esc(years[i])} : ${SERIES.map((s) => `${esc(s.name.toLowerCase())} ${fmt(100 * (r[s.key] || 0) / n, 0)} %`).join(", ")}.</p>`;
}
async function viewEvolution(cod) {
  const f = await api(`/api/formation/${encodeURIComponent(cod)}`);
  const lin = await api(`/api/lineage/${encodeURIComponent(f.record.lineage_id)}`);
  const years = META.years, by = Object.fromEntries(lin.years.map((r) => [r.session, r]));
  const rows = years.map((y) => by[y] || null), col = (k) => rows.map((r) => r ? r[k] : null);
  const hollow = rows.map((r) => r ? r.low_n_flag : false);
  const socialLines = [["pct_bours", EVO.k1, ""], ["pct_f", EVO.k2, "6 4"], ["pct_aca_orig", EVO.k3, "2 3"], ["pct_etab_orig", EVO.ref, "8 3 2 3"]]
    .map(([k, color, dash]) => ({ name: label(k), color, dash, values: col(k), hollow }));
  $view.innerHTML = `
  <div class="card"><h1>Évolution de la cohorte 2022–2025</h1>
    <div><a href="#/f/${esc(f.record.cod_aff_form)}">${esc(f.record.g_ea_lib_vx)}</a> · ${esc(f.record.lib_for_voe_ins)}</div>
    ${evoTakeaway(years, col("taux_acces_ens"))}
    <div class="muted small">${f.record.lineage_confidence === "inferred_uai_track_match" ? "La même formation suivie d'une année à l'autre : son code a changé, le lien est déduit" : "La même formation, avec le même code, chaque année"}
    ${lin.missing_years.length ? ` · absente en ${lin.missing_years.join(", ")} (aucune interpolation)` : ""}</div></div>
  ${f.warnings.map((w) => `<div class="warn">${ICONS.warn} ${esc(w.text)}</div>`).join("")}
  <div class="charts">
    ${doubletteCharts(f.doublettes, years, f.semblables, lin.rapports, "paire")}
    ${voieEvolutionCard(f.doublettes, years, lin.rapports)}
    ${mentionEvolutionCard(years, rows)}
    ${accesEvolutionCard(years, rows, lin.contexte, f.prevision)}
    ${doubletteCharts(f.doublettes, years, f.semblables, lin.rapports, "voies")}
    ${demandeEvolutionCard(years, lin.contexte, lin.prudence)}
    ${appelEvolutionCard(years, lin.contexte)}
    ${timingEvolutionCard(years, rows)}
    <div class="card"><h2>Admis par mention au bac ${tip("mentions")}</h2>${legend(MENTIONS)}${stackedBars(years, MENTIONS, rows)}</div>
    <div class="card"><h2>Admis nouveaux bacheliers par série de bac ${tip("mentions")}</h2>${legend(SERIES)}${stackedBars(years, SERIES, rows)}${seriesWords(years, rows)}</div>
    <div class="card"><h2>Boursiers, femmes, origine</h2>
      ${lineLegend(socialLines)}${lineChart(years, socialLines)}
      <p class="muted small">Points creux : moins de ${META.low_n_threshold} admis. ${tip("low_n")}</p></div>
    <div class="card evo-wide"><h2>Combien de candidats à chaque étape ${tip("funnel")}</h2><div class="scroll"><table>
      <tr><th><span class="sr-only">Effectif</span></th>${years.map((y) => `<th class="num">${y}</th>`).join("")}</tr>
      ${["voe_tot", "nb_voe_pp", "nb_cla_pp", "prop_tot", "acc_tot", "acc_neobac", "acc_term", "acc_brs", "capa_fin"].filter((k) => col(k).some((v) => v != null) && !(k === "voe_tot" && col(k).every((v, i) => v === col("nb_voe_pp")[i]))).map((k) => `<tr><td>${esc(label(k).replace(" (PP)", " (phase principale)"))}</td>${col(k).map((v) => `<td class="num">${fmt(v)}</td>`).join("")}</tr>`).join("")}
    </table></div></div>
  </div>`;
}

async function viewCompare() {
  const ids = basket.get();
  if (!ids.length) { $view.innerHTML = `<div class="card"><h1>Comparateur</h1><p class="muted">Ajoutez des formations depuis leur fiche (jusqu'à 6).</p></div>`; return; }
  const d = await api(`/api/compare?ids=${ids.map(encodeURIComponent).join(",")}`);
  const F = d.formations, years = META.years;
  const metric = (f, m) => f.peers.find((p) => p.metric === m) || {};
  const rowsDef = [
    ["Session", (f) => f.record.session], ["Filière", (f) => esc(f.record.fil_lib_voe_acc)],
    ["Taux d'accès (phase principale) " + tip("taux_acces_ens"), (f) => pct(f.record.taux_acces_ens)],
    ["… percentile filière", (f) => metric(f, "taux_acces_ens").peer_percentile != null ? "P" + fmt(metric(f, "taux_acces_ens").peer_percentile) : "—"],
    ["Parmi les candidats appelés, part des élèves de terminale générale (phase principale) " + tip("part_terminale_generale_en_position_admis_pp"), (f) => pct(f.record.part_terminale_generale_en_position_admis_pp)],
    ["Vœux (toutes phases)", (f) => fmt(f.record.voe_tot) + (f.record.subwish_flag ? ' <span class="badge warnb">sous-vœu</span>' : "")],
    ["Classés (phase principale)", (f) => fmt(f.record.nb_cla_pp)], ["Proposés", (f) => fmt(f.record.prop_tot)],
    ["Admis", (f) => fmt(f.record.acc_tot) + (f.record.low_n_flag ? ` <span class="badge warnb">n&lt;${META.low_n_threshold}</span>` : "")],
    ["Nouveaux bacheliers / autres admis", (f) => admisCell(f.admis)],
    ["% TB + TBF", (f) => pct(metric(f, "pct_tb_tbf").value)], ["% boursiers", (f) => pct(f.record.pct_bours)],
    ["% femmes", (f) => pct(f.record.pct_f)], ["% bac général", (f) => pct(f.record.pct_bg)],
    ["% même académie", (f) => pct(f.record.pct_aca_orig)],
    ["Proposition dès l'ouverture " + tip("timing"), (f) => (f.record.acc_tot > 0 ? pct(f.record.pct_acc_debutpp) : "—")],
    ["Reconnaissance par l'État", (f) => (f.reconnaissance ? recoPill(f.reconnaissance.categorie, f.reconnaissance.libelle, f.reconnaissance.explication) : '<span class="muted small">fiche pas encore lue</span>')],
    ["Frais de scolarité par an", (f) => (f.vie && f.vie.frais ? (f.vie.frais.montant !== null && f.vie.frais.montant !== undefined ? euros(f.vie.frais.montant) : '<span class="muted small">voir la fiche</span>') : "—")],
    ["Vœux par place " + estimTag("vœux ÷ places"), (f) => (f.tension ? `${fmt(f.tension.par_place)}${f.tension.libelle ? ` <span class="badge tension">${esc(f.tension.libelle)}</span>` : ""}` : "—")],
    ["Aussi en apprentissage", (f) => (f.apprenti && f.apprenti.propose ? "oui" : "non")],
    ["Vivre sur place, par mois " + estimTag("loyer local + moyennes nationales"), (f) => (f.vie && f.vie.mensuel ? eurosRange(f.vie.mensuel.min, f.vie.mensuel.max) : "—")],
    ["Options", (f) => offerBadges(f.record) || '<span class="muted small">—</span>'], ["Lignée", (f) => lineageBadge(f.record.lineage_confidence) + ` ${f.history.length} camp.`],
  ];
  const series = F.map((f) => { const by = Object.fromEntries(f.history.map((h) => [h.session, h.taux_acces_ens])); return { name: `${f.record.g_ea_lib_vx} · ${f.record.fil_lib_voe_acc}`, values: years.map((y) => by[y] ?? null) }; });
  $view.innerHTML = `<div class="card"><h1>Comparateur</h1><p class="muted small">${narrow() && F.length > 1 ? "Faites glisser le tableau pour voir les autres formations ; la première colonne reste en place." : ""}</p><div class="scroll"><table class="cmp">
    <tr><th><span class="sr-only">Indicateur</span></th>${F.map((f) => `<th><a href="#/f/${esc(f.record.cod_aff_form)}">${esc(f.record.g_ea_lib_vx)}</a><div class="small">${esc(f.record.fil_lib_voe_acc)}</div><div class="muted small">${esc(f.record.ville_etab)}${f.record.lib_comp_voe_ins ? " · " + esc(f.record.lib_comp_voe_ins) : ""}</div>
      <button data-rm="${esc(f.record.cod_aff_form)}" class="small">retirer</button></th>`).join("")}</tr>
    ${rowsDef.map(([l, fn]) => `<tr><td>${l}</td>${F.map((f) => `<td>${fn(f)}</td>`).join("")}</tr>`).join("")}
  </table></div></div>
  ${F.flatMap((f) => f.warnings.map((w) => `<div class="warn">${ICONS.warn} ${esc(f.record.g_ea_lib_vx)} : ${esc(w.text)}</div>`)).join("")}
  <div class="card"><h3>Taux d'accès 2022–2025</h3>${lineLegend(series)}${lineChart(years, series)}</div>`;
  $view.querySelectorAll("[data-rm]").forEach((b) => { b.onclick = () => { basket.toggle(b.dataset.rm); viewCompare(); }; });
}

async function viewSpecialites(session, ftype) {
  // product audit (2026-11-10): an empty "session=" is a 422 for the API, and the page showed "[object Object]"
  const sq = new URLSearchParams();
  if (/^\d{4}$/.test(String(session || ""))) sq.set("session", session);
  if (ftype) sq.set("formation_type", ftype);
  const d = await api(`/api/specialites${sq.toString() ? `?${sq}` : ""}`);
  const max = Math.max(1, ...d.rows.map((r) => r.pct_acceptations || 0));
  $view.innerHTML = `<div class="card"><h1>Spécialités des admis, par paire</h1>
    <p class="muted small">Source : ministère de l'Enseignement supérieur (SIES), propositions d'admission des terminales générales selon leurs enseignements de spécialité, agrégées au niveau national par type de formation (pas par formation). Le ministère publie les propositions et les acceptations, sans nombre de candidats. Le tableau montre donc la composition des admis (acceptations) par paire de spécialités : c'est une répartition, pas un taux d'accès.</p>
    <div class="toolbar"><label>Session <select id="ss">${META.years.map((y) => `<option ${y === d.session ? "selected" : ""}>${y}</option>`).join("")}</select></label>
      <label>Type de formation <select id="st" style="max-width:100%">${d.formation_types.map((t) => `<option ${t === d.formation_type ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label></div>
    <p class="small">${fmt(d.totals.n_accepte)} acceptations · ${fmt(d.totals.n_proposition)} propositions</p>
    <div class="scroll"><table><tr><th>Spécialités</th><th>Part des admis</th><th class="num">Acceptations</th><th class="num">Propositions</th></tr>
    ${d.rows.map((r) => `<tr><td>${esc(r.doublette)}</td>
      <td style="min-width:140px"><svg viewBox="0 0 100 10" preserveAspectRatio="none" style="width:100%;height:10px;display:block"><rect width="${100 * (r.pct_acceptations || 0) / max}" height="10" fill="var(--c1)"/></svg><span class="small">${pct(r.pct_acceptations)}</span></td>
      <td class="num">${fmt(r.n_accepte)}</td><td class="num">${fmt(r.n_proposition)}</td></tr>`).join("") || `<tr><td class="muted">Pas de données pour cette session.</td></tr>`}
    </table></div></div>`;
  document.getElementById("ss").onchange = (e) => { location.hash = `#/specialites/${e.target.value}/${encodeURIComponent(d.formation_type || "")}`; };
  document.getElementById("st").onchange = (e) => { location.hash = `#/specialites/${d.session}/${encodeURIComponent(e.target.value)}`; };
}

// lot 1, PR 10: the quality page in French (a teacher read English check codes there); the raw names stay in a folded list
const QUAL_CHECK = {
  series_eq_acc_neobac: "Bacs général + techno + pro = admis nouveaux bacheliers",
  mentions_eq_acc_neobac: "Mentions = admis nouveaux bacheliers",
  series_plus_at_eq_acc_tot: "Bacs + autres admis = tous les admis",
  mention_by_series_eq_acc_neobac: "Mentions par bac = admis nouveaux bacheliers",
  series_eq_acc_term: "Bacs = admis venant de terminale (contrôle du dénominateur)",
  mentions_eq_acc_term: "Mentions = admis venant de terminale (contrôle du dénominateur)",
};
const QUAL_STATUS = { PASS: "réussie", FAIL: "en échec" };
function qualCol(k) {
  if (k === "fili") return "Filière";
  let m = /^n_(\d{4})$/.exec(k); if (m) return `Formations ${m[1]}`;
  m = /^pct_linked_(\d{4})$/.exec(k); if (m) return `% reliées à ${m[1]}`;
  return { pct_full_span: "% suivies sur toutes les campagnes", pct_full_span_exact: "% suivies, lien exact", pct_with_inferred_link: "% avec un lien déduit" }[k] || k;
}
function verificationCard(v) {
  if (!v) return `<div class="card"><h2>Vérification des chiffres officiels</h2><p class="muted">Aucun rapport publié pour ce build.</p></div>`;
  const st = (x) => ({ pass: "✓", fail: "✗", upstream_inconsistency: "incohérence du fichier officiel (reproduite à l'identique)" }[x] || "–");
  return `<div class="card"><h2>Vérification des chiffres officiels : ${esc(QUAL_STATUS[v.overall] || v.overall)}</h2>
    <p class="muted small">Rapport du ${esc(v.generated_at)}. Les totaux publiés doivent se recouper, campagne par campagne (« contrôle » = un recoupement qui vérifie seulement le dénominateur).</p>
    <div class="scroll"><table><tr><th>Contrôle</th><th>Session</th><th class="num">Évaluables</th><th class="num">Écarts</th><th class="num">% ok</th><th>Statut</th></tr>
    ${v.identities.map((r) => `<tr><td>${esc(QUAL_CHECK[r.check] || r.check)}${r.primary ? "" : ` <span class="badge">contrôle</span>`}</td><td>${r.session}</td><td class="num">${fmt(r.n_evaluable)}</td><td class="num">${fmt(r.n_violations)}</td><td class="num">${r.pct_ok ?? "—"}</td><td>${st(r.status)}</td></tr>`).join("")}
    ${(v.taux_raw || []).map((r) => `<tr><td>Taux d'accès = fichier officiel brut</td><td>${r.session}</td><td class="num">${fmt(r.n_upstream)}</td><td class="num">${fmt(r.n_mismatch)}</td><td></td><td>${st(r.status)}</td></tr>`).join("")}
    ${(v.taux_live || []).map((r) => `<tr><td>Taux d'accès = site officiel en direct (échantillon)</td><td>${r.session}</td><td class="num">${fmt(r.n_sampled)}</td><td class="num">${fmt(r.n_mismatch)}</td><td></td><td>${st(r.status)}</td></tr>`).join("")}
    </table></div></div>`;
}

async function viewQualite() {
  const c = await api("/api/continuity");
  let v = null, pr = null;
  try { v = await api("/api/verification"); } catch (_) { /* no report published */ }
  try { pr = await api("/api/journey/persona"); } catch (_) { /* no persona report */ }
  const cols = c.rows.length ? Object.keys(c.rows[0]) : [];
  const audit = META.schema_audit.filter((a) => a.status !== "keyword");
  const personaCard = pr ? `<div class="card"><h2>Calibration de « Où je me situe » : ${esc(QUAL_STATUS[pr.overall] || pr.overall)}</h2>
    <p class="muted small">Un profil type (Mathématiques + SES, mention assez bien) relu à chaque mise à jour : ${fmt(pr.checks.filter((c) => c.ok).length)} contrôles réussis sur ${fmt(pr.checks.length)}. Rapport du ${esc(pr.generated_at)}.</p>
    <details class="more-card"><summary>Voir la liste des contrôles (noms techniques)</summary><table>${pr.checks.map((c) => `<tr><td>${esc(c.check)}</td><td>${c.ok ? "✓" : "✗"}</td></tr>`).join("")}</table></details></div>` : "";
  $view.innerHTML = `<div class="card"><h1>Qualité des données</h1><p class="muted small">Les contrôles faits à chaque mise à jour des chiffres officiels.</p></div>` + verificationCard(v) + personaCard + `<div class="card"><h2>Formations suivies d'une année à l'autre (référence ${c.anchor}) ${tip("lineage")}</h2><div class="scroll"><table>
    <tr>${cols.map((k) => `<th class="${k === "fili" ? "" : "num"}">${esc(qualCol(k))}</th>`).join("")}</tr>
    ${c.rows.map((r) => `<tr>${cols.map((k) => `<td class="${k === "fili" ? "" : "num"}">${esc(r[k])}</td>`).join("")}</tr>`).join("")}</table></div></div>
  <div class="card"><h2>Harmonisation des fichiers</h2><p class="muted small">D'une année à l'autre, le ministère renomme parfois une colonne ou n'en publie pas : la colonne est alors reliée à son nouveau nom, ou laissée vide (jamais devinée).</p>
    <details class="more-card"><summary>Voir les colonnes concernées (noms techniques)</summary><div class="scroll"><table><tr><th>Session</th><th>Champ canonique</th><th>Colonne amont</th><th>Statut</th></tr>
    ${audit.map((a) => `<tr><td>${a.session ?? ""}</td><td>${esc(a.canonical)}</td><td>${esc(a.upstream ?? "—")}</td><td>${esc(a.status)}</td></tr>`).join("")}</table></div></details>
    <p class="muted small">Construit le ${esc(META.built_at)}.</p></div>`;
}


// ---- student positioning journey -------------------------------------------
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (_) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* storage blocked */ } if (k === "profile") profileBar.render(); },
};
const pc1 = (v) => (v === null || v === undefined) ? "—" : `${fmt(100 * v, 1)} %`;
const ZONES = {
  securite: { label: "Vœu de sécurité", color: "var(--zone-securite)" },
  cible: { label: "Vœu cible", color: "var(--zone-cible)" },
  ambitieux: { label: "Vœu ambitieux", color: "var(--zone-ambitieux)" },
  hors_profil: { label: "Hors-profil statistique", color: "var(--zone-autre)" },
  indetermine: { label: "Indéterminé", color: "var(--zone-autre)" },
  non_ouvert: { label: "Non ouvert à votre série", color: "var(--zone-autre)" },
};
const GATES = {
  predilection: { label: "Filière de prédilection", color: "var(--c1)" },
  accessible: { label: "Filière accessible", color: "var(--c3)" },
  atypique: { label: "Peu courant avec vos spécialités", color: "var(--c5)" },
  insuffisant: { label: "Effectif insuffisant", color: "var(--line)" },
};
let JV = null;

// sprint 20: the route choice is kept only while the bac stays the same (a new bac clears it)
function voieFromForm(fd, serie, label) {
  const keep = fd.get("serie") === serie && !!fd.get("voie");
  return { voie: keep ? fd.get("voie") : null, voie_label: keep ? label : null };
}
// R1 (owner, 2026-11-11): "Mon profil" is the one place the profile is edited. The situation comes first; every field says what
// it is used for, in the student's words (no column name). Only the fields of the chosen situation are drawn.
const PF_SAVE = `<div class="card pf-saved"><button class="primary">Enregistrer mon profil</button><span class="small muted">Vérifiez chaque champ : rien n'est lu pour vous avant l'enregistrement.</span></div>`;
// owner, 2026-11-12: in terminale a student keeps two DIFFERENT specialties of the three of première, and only one can be
// artistic (the vocabulary has a single Arts code): the second list never offers the first choice. What the form shows is what is
// stored (Codex): a pair read from the form is made distinct BEFORE it is saved (`spe2Of`: picking the second specialty as the
// first swaps them), and a stored identical pair (an older profile) stays visibly invalid, "Choisissez", until the student picks.
function spe2Of(spe1, spe2, prev) {
  if (spe2 && spe2 !== spe1) return spe2;
  if (prev && prev !== spe1) return prev;                              // the former first specialty takes the second place
  const list = (typeof JV !== "undefined" && JV && JV.specialties) || [];
  return (list.find((x) => x.code !== spe1) || {}).code || spe2;
}
function profileForm(p, saved) {
  const opt = (list, val, lab = (x) => x.label, code = (x) => x.code) =>
    list.map((x) => `<option value="${esc(code(x))}" ${code(x) === val ? "selected" : ""}>${esc(lab(x))}</option>`).join("");
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";
  const reo = isReo(p);
  const field = (ctl, why) => `<div class="pf-field">${ctl}<p class="pf-why">${why}</p></div>`;
  const sit = `<section class="card"><h2>1 · Votre situation</h2>
    <div class="pf-sit" role="radiogroup" aria-label="Votre situation">
      <label class="pf-opt"><strong><input type="radio" name="statut" value="terminale" ${reo ? "" : "checked"}> En terminale</strong>
        <span>Vous passez le bac cette année : chaque formation se lit avec votre bac, vos spécialités et votre mention (vœu de sécurité, cible ou ambitieux).</span></label>
      <label class="pf-opt"><strong><input type="radio" name="statut" value="reorientation" ${reo ? "checked" : ""}> ${REO_LABEL}</strong>
        <span>Réorientation, reprise d'études : le ministère ne publie ni mention ni série pour vous. SupCompass affiche un accès estimé, sans zone.</span></label>
      <a class="pf-opt" href="#/premiere"><strong>En seconde ou en première</strong>
        <span>Pas encore de spécialités de terminale ni de mention : comparez les paires possibles de vos spécialités.</span></a>
    </div></section>`;
  const acad = field(`<label>Votre académie <select name="academie"><option value="">Pas indiquée</option>${opt(JV.academies.map((a) => ({ code: a, label: acadLabel(a) })), p.academie)}</select></label>`,
    "Pour une licence très demandée, le recteur fixe une part maximale de candidats venant d'une autre académie : votre académie compte. Elle sert aussi à montrer d'abord les formations proches de vous.");
  if (reo) {
    return `<form id="pf">${sit}<section class="card"><h2>2 · Où vous êtes</h2>${acad}${villeField()}</section>${saved ? "" : PF_SAVE}</form>`;
  }
  const bac = `<section class="card"><h2>2 · Votre bac</h2>
    ${field(`<label>Votre bac <select name="serie">${opt(JV.series || [{ code: "bg", label: "bac général" }], serie)}</select></label>`,
      "Chaque formation publie la part de ses admis venant du bac général, technologique ou professionnel.")}
    ${serie !== "bg" && JV.voies && (JV.voies[serie] || []).length ? field(`<label>${serie === "bt" ? "Série et spécialités" : "Spécialité de bac pro"} <select name="voie"><option value="">Pas indiqué</option>${opt(JV.voies[serie], p.voie)}<option value="autre" ${p.voie === "autre" ? "selected" : ""}>${serie === "bt" ? "Autre série ou autres spécialités" : "Autre spécialité"}</option></select></label>`,
      `Les rapports des jurys publient une ligne par ${serie === "bt" ? "série technologique et ses spécialités" : "spécialité de bac pro"} : la fiche de chaque formation vous montre la vôtre quand elle existe.`) : ""}
    ${serie === "bg" ? field(`<div class="pf-ctl"><span>Vos deux spécialités de terminale</span><div class="pf-pair"><select name="spe1" aria-label="Spécialité 1">${opt(JV.specialties, p.spe1, (x) => x.short)}</select>
      <select name="spe2" aria-label="Spécialité 2">${p.spe2 === p.spe1 ? '<option value="" selected>Choisissez</option>' : ""}${opt(JV.specialties.filter((x) => x.code !== p.spe1), p.spe2, (x) => x.short)}</select></div></div>`,
      `${p.spe2 === p.spe1 ? '<span class="warn">Votre profil a deux fois la même spécialité : choisissez la deuxième. Vos zones ne sont pas lues avant.</span> ' : ""}En terminale, vous gardez deux des trois spécialités de première, deux spécialités différentes : une seule peut être artistique. C'est votre paire de spécialités (on dit aussi « doublette »). Les rapports des jurys publient le taux d'accès de chaque paire : la fiche de chaque formation affiche celui de la vôtre quand il existe, sinon une estimation dite comme telle.`) : ""}
    ${serie === "bg" && (p.spe1 === "MATHS" || p.spe2 === "MATHS") ? field(`<label class="pf-check"><span><input type="checkbox" name="maths_expertes" ${p.maths_expertes ? "checked" : ""}> Mathématiques expertes</span></label>`,
      "Notée pour vous : les données publiques ne détaillent pas les options de terminale, elle ne change donc aucun chiffre. Regardez les attendus sur la fiche Parcoursup.") : ""}
  </section>`;
  // R5: the band and, optionally, the average that places the student inside it (an average sets the band: the list follows it)
  const moy = validMoyenne(p.moyenne);
  const mlab = (m) => `${m.label}${m.min !== undefined && m.code !== "rattrapage" ? ` (${fmt(m.min)} à ${fmt(m.max)})` : ""}`;
  const mention = `<section class="card"><h2>3 · Votre niveau visé au bac</h2>
    ${field(`<label>Mention au bac <select name="mention"${moy !== null ? " disabled" : ""}>${opt(JV.mentions, moy !== null ? bandOf(moy) : p.mention, mlab)}</select></label>`,
      "Les admis de chaque formation sont publiés par mention. C'est elle qui situe chaque formation pour vous : <strong>vœu de sécurité</strong>, <strong>cible</strong> ou <strong>ambitieux</strong>. Choisissez celle que vos moyennes actuelles laissent attendre, ni plus ni moins. Le bac au rattrapage est publié avec « sans mention » : il se lit en bas de cette tranche.")}
    ${field(`<label>Votre moyenne visée (facultatif) <input type="text" inputmode="decimal" name="moyenne" autocomplete="off" placeholder="par exemple 13,4" value="${moy !== null ? esc(String(moy).replace(".", ",")) : ""}" aria-describedby="pf-moy-help"></label>`,
      `<span id="pf-moy-help">Entre 8 et 20. Elle place votre profil <strong>dans</strong> sa mention : 12,1 et 13,9 sont deux « assez bien » très différents. Les notes des admis ne sont pas publiées, seulement leurs mentions : la position dans la mention est une <strong>estimation</strong> (une courbe centrée au milieu de la mention, 13 pour « assez bien », et une répartition égale donnent les deux bornes de la fourchette). Jamais une chance d'admission.${moy !== null ? ` Mention déduite : <strong>${esc((JV.mentions.find((m) => m.code === bandOf(moy)) || {}).label || "")}</strong>.` : ""}</span>`)}
  </section>`;
  const where = `<section class="card"><h2>4 · Où vous êtes</h2>
    ${acad}
    ${villeField()}
    ${field(`<div class="pf-ctl lyc-pick"><label for="lyc-q">Votre lycée (facultatif)</label>
      <div class="lyc-row"><input id="lyc-q" type="search" autocomplete="off" placeholder="Nom, ville ou code UAI du lycée" value="${p.lycee ? esc(p.lycee.nom) : ""}" aria-describedby="lyc-help">
      ${p.lycee ? '<button type="button" id="lyc-clear" class="small">Retirer</button>' : ""}</div>
      <div id="lyc-res" class="lyc-res" role="listbox" aria-label="Lycées trouvés"></div><div id="lyc-help" class="muted small"></div></div>`,
      "Pour le contexte seulement : aucune donnée publique ne relie les admissions au lycée d'origine, il ne change donc pas vos zones. La liste des lycées est cherchée dans ce navigateur : votre lycée n'est jamais envoyé.")}
    ${field(`<label class="pf-check"><span><input type="checkbox" name="boursier" ${p.boursier ? "checked" : ""}> Je suis boursier ou boursière</span></label>`,
      "La part de boursiers parmi les admis s'affiche à titre d'information. Les taux minimaux de boursiers fixés par les recteurs ne sont pas publiés formation par formation.")}
  </section>`;
  return `<form id="pf">${sit}${bac}${mention}${where}${saved ? "" : PF_SAVE}</form>`;
}

// ---- Sprint 4: the student's lycée, as context only ------------------------------------------
// The whole list is loaded once and searched here, so the chosen lycée never reaches the server.
let LYC = null;
async function loadLycees() {
  if (LYC) return LYC;
  const d = await api("/api/lycees");
  const byUai = {};
  for (const r of d.rows) {
    const o = Object.fromEntries(d.fields.map((f, i) => [f, r[i]]));
    o.ival = (d.ival[o.uai] || []).map((v) => Object.fromEntries(d.ival_fields.map((f, i) => [f, v[i]])));
    o.key = lycFold(`${o.nom} ${o.commune} ${o.uai}`);
    byUai[o.uai] = o;
  }
  LYC = { byUai, list: Object.values(byUai) };
  return LYC;
}
const lycFold = (x) => String(x || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
function lycSearch(q) {
  const words = lycFold(q).split(" ").filter(Boolean);
  if (!LYC || !words.length) return [];
  return LYC.list.filter((l) => words.every((w) => l.key.includes(w))).slice(0, 8);
}
const LYC_TYPE = { LEGT: "lycées généraux et technologiques", LPO: "lycées polyvalents", LP: "lycées professionnels" };
const GRADE_TEXT = { A: "au moins 100 élèves présents au bac, session récente", B: "moins de 100 élèves présents au bac, ou session ancienne", C: "moins de 30 élèves présents au bac" };
const sgn = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${fmt(v)}`);
function lyceeCard(p) {
  if (!p.lycee) return "";
  const l = LYC && LYC.byUai[p.lycee.uai];
  const head = `<h2>Votre lycée, en contexte ${tip("lycee")}</h2>`;
  if (!l) return `<div class="card">${head}<p class="muted small">Ce lycée n'apparaît plus dans les données publiques les plus récentes.</p></div>`;
  const sect = l.secteur === "public" ? "publics" : "privés sous contrat";
  const ref = l.ips_etab != null ? `<p><strong>Indice de position sociale : ${fmt(l.ips_etab, 1)}</strong>
      <span class="muted small"> · moyenne des ${esc(LYC_TYPE[l.type] || "lycées")} ${sect} : ${l.ips_academique != null ? `académie ${fmt(l.ips_academique, 1)}` : ""}${l.ips_national != null ? `, France ${fmt(l.ips_national, 1)}` : ""} (rentrée ${esc(l.rentree)})</span></p>` : "";
  const iv = l.ival.length ? `<div class="scroll"><table><tr><th>Bac · fiabilité ${tip("fiabilite")}</th><th class="num">Réussite</th><th class="num">Mentions</th><th class="num">Accès 2nde → bac</th></tr>
      ${l.ival.map((v) => `<tr><td>${esc(v.session)}<div class="muted small">${fmt(v.presents_total)} présents</div><div class="fiab-row">${fiabBadge({ fiabilite: v.fiabilite, raisons: [GRADE_TEXT[v.fiabilite] || ""] })}</div></td>
        <td class="num">${pct(v.taux_reu_total)}<div class="muted small">valeur ajoutée ${sgn(v.va_reu_total)}</div></td>
        <td class="num">${pct(v.taux_men_total)}<div class="muted small">valeur ajoutée ${sgn(v.va_men_total)}</div></td>
        <td class="num">${pct(v.taux_acces_2nde)}<div class="muted small">valeur ajoutée ${sgn(v.va_acces_2nde)}</div></td></tr>`).join("")}</table></div>` : `<p class="muted small">Pas d'indicateurs de résultats publiés (lycée professionnel ou effectifs trop faibles).</p>`;
  return `<div class="card">${head}<p class="small"><strong>${esc(l.nom)}</strong> · ${esc(l.commune)}${l.academie ? ` · académie de ${esc(acadLabel(l.academie))}` : ""}</p>
    ${ref}${iv}
    <p class="info small">Ce sont des indicateurs de votre lycée, pas les vôtres. Aucune donnée publique ne relie les admissions Parcoursup au lycée d'origine : votre lycée <strong>ne modifie pas</strong> votre positionnement. Seule exception publiée : pour une formation située dans votre lycée (BTS, CPGE), la part d'admis qui en venaient est signalée.</p></div>`;
}
// fiche: the formation is in the student's own lycée (the one lycée effect SIES publishes)
function lyceeHere(r) {
  const p = store.get("profile", null);
  if (!p || !p.lycee || p.lycee.uai !== r.cod_uai) return "";
  return `<div class="info">Cette formation est dans votre lycée${r.pct_etab_orig != null ? ` : ${fmt(r.pct_etab_orig)} % de ses admis en ${esc(r.session)} venaient de ce même lycée (indicateur officiel)` : ""}. ${tip("lycee")}</div>`;
}
// A search that names a lycée ("lycée valbonne") is often a student looking for THEIR lycée, not for
// the formations it hosts: offer to set it as the profile's lycée. Matching runs in the browser on
// the full list, so the lycée still never reaches the server.
async function suggestLycee(q, marker) {
  const words = lycFold(q).split(" ");
  if (!words.some((w) => w.startsWith("lyc"))) return;
  try { await loadLycees(); } catch (_) { return; }
  if ($view.dataset.rendered !== marker) return;                       // the user navigated meanwhile
  const rest = words.filter((w) => w && !w.startsWith("lyc")).join(" ");
  const hits = rest ? lycSearch(rest).slice(0, 3) : [];
  if (!hits.length) return;
  const box = document.createElement("div");
  box.className = "card lyc-suggest";
  box.innerHTML = `<h2>C'est votre lycée ?</h2><p class="small muted">Choisissez-le pour votre profil : il s'affichera en contexte dans « Mon profil » (il reste dans votre navigateur). Les formations post-bac de ce lycée sont listées plus bas.</p>
    <div class="lyc-res">${hits.map((l) => `<button type="button" data-suggest="${esc(l.uai)}"><strong>${esc(l.nom)}</strong><span class="muted small"> · ${esc(l.commune)}${l.academie ? ` (${esc(acadLabel(l.academie))})` : ""}</span> → Le choisir comme mon lycée</button>`).join("")}</div>`;
  $view.querySelectorAll(".lyc-suggest").forEach((x) => x.remove());   // the search page stays: one suggestion at a time
  $view.prepend(box);
  box.querySelectorAll("[data-suggest]").forEach((b) => {
    b.onclick = () => {
      const l = LYC.byUai[b.dataset.suggest];
      const raw = store.get("profile", null);
      const lyc = { uai: l.uai, nom: l.nom, commune: l.commune };
      // R1 review: with a profile, the lycée joins it; without one, it only pre-fills "Mon profil" (no bac field invented)
      if (raw && typeof raw === "object" && !Array.isArray(raw)) store.set("profile", { ...raw, lycee: lyc, ...(l.academie ? { academie: l.academie } : {}) });
      else store.set("profilDraft", { lycee: lyc, academie: l.academie || "" });
      location.hash = "#/profil";
    };
  });
}
// ---- Sprint 5: the next-campaign "repère" (calibrated ranges, back-tested, never a probability) ----
const pct0 = (v) => `${Math.round(v)} %`;
function repereNote(cal) {
  if (!cal) return "";
  const c = cal.coverage || {};
  const cv = (m) => (c[m] ? `${Math.round(100 * c[m].coverage)} %` : "—");
  return `<p class="small muted">Repère ${esc(cal.target)} : fourchettes à ${Math.round(100 * cal.level)} %, réglées sur 2023-2024 et testées sur ${esc(cal.holdout)} sans l'avoir vu : ${cv("taux")} des taux d'accès et ${cv("cdf")} des parts d'admis tombaient dans leur fourchette. Ce ne sont pas des chances d'admission. ${tip("repere")}</p>`;
}
function repereCell(f, serie) {
  const r = f.repere;
  if (!r) return '<span class="muted">—</span>';
  const acc = r.taux_lo != null ? `accès ${pct0(r.taux_lo)}–${pct0(r.taux_hi)}${serie !== "bg" ? " <span class=\"muted\">(tous candidats)</span>" : ""}` : "";
  const pos = serie === "bg" && r.cdf_lo != null ? `<div>votre mention ou moins ${pct0(100 * r.cdf_lo)}–${pct0(100 * r.cdf_hi)} <span class="muted">(tous bacs)</span></div>` : "";
  // the confirmation rate was measured with the bac-général reading of the zone (calibration.zone_of):
  // only comparable for bac général (bac techno and pro use an estimated series access)
  const conf = serie === "bg" && r.zone_confirmed != null ? `<div class="muted">zone confirmée l'année suivante dans ${pct0(100 * r.zone_confirmed)} des cas comparables</div>` : "";
  return `<div>${acc}</div>${pos}${conf}`;
}
function mathsExpertesNote(p, serie) {
  return serie === "bg" && p.maths_expertes && (p.spe1 === "MATHS" || p.spe2 === "MATHS")
    ? `<p class="small muted">Mathématiques expertes : option notée. Les données Parcoursup ne publient pas les options de Terminale, elle ne change donc pas le positionnement ; regardez les attendus de chaque formation sur sa fiche Parcoursup.</p>` : "";
}

function stage1Matrix(s1, show, all) {
  // sprint "Doublettes": when EVERY filière is "insuffisant" (< 100 candidates of the doublette, hidden by default), the view is
  // empty whatever the filters, so those filières are shown anyway; a filter that hides filières which exist stays honoured (Codex).
  // The note says which case it is from the rows' own `rare` flags (< 20 candidates), never from the gate.
  const fewOnly = s1.filieres.length > 0 && s1.filieres.every((f) => f.gate === "insuffisant") && !show.has("insuffisant");
  const allRare = fewOnly && s1.filieres.every((f) => f.rare);
  const kept = fewOnly ? s1.filieres.filter((f) => f.gate === "insuffisant").sort((a, b) => (b.candidates || 0) - (a.candidates || 0) || ((b.autres && b.autres.candidats) || 0) - ((a.autres && a.autres.candidats) || 0))
    : s1.filieres.filter((f) => show.has(f.gate));
  const rows = all ? kept : kept.slice(0, 15);
  const max = Math.max(0.01, ...rows.map((f) => f.destination_share || 0));
  // sprint "Doublettes": the proposal rate of the student's doublette comes first; a doublette with fewer than DBL_SEUIL
  // candidates in a filière shows that filière's "Autres doublettes" bucket, flagged as an estimation
  const rate = (f) => (f.rare && f.autres
    ? `${pct1(f.autres.taux)}${rateBar(f.autres.taux, "var(--voie-bg)")}${estimTag(`« Autres paires de spécialités » : ${fmt(f.autres.n_doublettes)} paires de moins de ${DBL_SEUIL} candidats`, true)}`
    : `<strong>${pc1(f.offer_rate)}</strong>${f.offer_rate !== null && f.offer_rate !== undefined ? rateBar(100 * f.offer_rate, "var(--voie-bg)") : ""}`);
  return `<div class="legend">${Object.entries(GATES).map(([k, g]) => `<label style="cursor:pointer"><input type="checkbox" data-gate="${k}" ${show.has(k) ? "checked" : ""}> <i style="background:${g.color}"></i>${g.label} (${s1.filieres.filter((f) => f.gate === k).length})</label>`).join("")}</div>
  ${allRare ? `<div class="info">Votre paire de spécialités est rare : moins de ${DBL_SEUIL} candidats dans chaque filière sur 2022–2025. Les taux affichés sont ceux des « Autres paires de spécialités » de chaque filière (paires rares regroupées) : une estimation.</div>`
    : fewOnly ? `<div class="info">Peu de candidats ont vos deux spécialités : moins de ${fmt(GATE_MIN)} dans chaque filière sur 2022–2025, les filières sont donc affichées quand même. Là où ils sont moins de ${DBL_SEUIL}, le taux affiché est celui des « Autres paires de spécialités » (estimation).</div>` : ""}
  <div class="scroll"><table class="stack"><tr class="stack-head"><th>Filière</th><th class="num">Taux de proposition pour vos deux spécialités</th><th class="num">… tous les bacheliers généraux</th><th>Où vont les admis ayant vos spécialités</th><th class="num">Part des admis</th><th class="num">Par rapport à la moyenne</th><th><span class="sr-only">Actions</span></th></tr>
  ${rows.map((f) => `<tr><td><span class="badge gbadge" style="--zc:${GATES[f.gate].color}">${GATES[f.gate].label}</span><br>${esc(f.label)}<div class="muted small">${fmt(f.candidates)} candidats avec ces deux spécialités · ${f.years} campagne${f.years > 1 ? "s" : ""}</div></td>
    <td class="num" data-label="Taux de proposition pour vos deux spécialités">${rate(f)}</td><td class="num muted" data-label="Tous les bacheliers généraux">${pc1(f.offer_rate_all)}</td>
    <td data-label="Où vont les admis ayant vos spécialités" style="min-width:130px"><svg viewBox="0 0 100 10" preserveAspectRatio="none" style="width:100%;height:10px;display:block"><rect width="${100 * (f.destination_share || 0) / max}" height="10" fill="${GATES[f.gate].color}"/></svg><span class="small">${pc1(f.destination_share)}</span></td>
    <td class="num" data-label="Part des admis">${pc1(f.share)}</td><td class="num" data-label="Par rapport à la moyenne">${fmt(f.lift, 2)} fois la moyenne</td>
    <td class="acts">${f.gate === "atypique" || f.gate === "insuffisant" ? "" : f.n_formations ? `<button data-type="${esc(f.type_key)}" data-label="${esc(f.label)}">${fmt(f.n_formations)} établissements →</button>` : '<span class="muted small">pas de correspondance formation par formation</span>'}</td></tr>`).join("")}
  </table></div>
  <p class="muted small">Taux de proposition : parmi les candidats ayant vos deux spécialités et au moins un vœu dans cette filière (toute la France, 2022–2025), part ayant reçu au moins une proposition. Pas des chances d'admission.</p>
  ${kept.length > 15 ? `<button id="allf">${all ? "Réduire" : `Afficher les ${kept.length} filières`}</button>` : ""}`;
}

function stage1SeriesMatrix(s1, show, all) {
  const kept = s1.filieres.filter((f) => show.has(f.gate));
  const rows = all ? kept : kept.slice(0, 15);
  const max = Math.max(0.01, ...rows.map((f) => f.destination_share || 0));
  const sl = SERIE_SHORT[s1.serie];
  return `<div class="legend">${Object.entries(GATES).map(([k, g]) => `<label style="cursor:pointer"><input type="checkbox" data-gate="${k}" ${show.has(k) ? "checked" : ""}> <i style="background:${g.color}"></i>${g.label} (${s1.filieres.filter((f) => f.gate === k).length})</label>`).join("")}</div>
  <div class="scroll"><table><tr><th>Filière</th><th>Où vont les ${sl} admis</th><th class="num">Part des ${sl} parmi les admis</th><th class="num">Par rapport à la moyenne</th><th class="num">Accès estimé ${sl} (médiane) ${tip("serie_offer")}</th><th><span class="sr-only">Actions</span></th></tr>
  ${rows.map((f) => `<tr><td><span class="badge gbadge" style="--zc:${GATES[f.gate].color}">${GATES[f.gate].label}</span><br>${esc(f.label)}<div class="muted small">${fmt(f.accepted)} ${sl} admis · ${f.years} campagne${f.years > 1 ? "s" : ""}</div></td>
    <td style="min-width:130px"><svg viewBox="0 0 100 10" preserveAspectRatio="none" style="width:100%;height:10px;display:block"><rect width="${100 * (f.destination_share || 0) / max}" height="10" fill="${GATES[f.gate].color}"/></svg><span class="small">${pc1(f.destination_share)}</span></td>
    <td class="num">${pc1(f.share)}</td><td class="num">${fmt(f.lift, 2)} fois la moyenne</td><td class="num"><strong>${f.access_median != null ? `${fmt(f.access_median)} %` : "—"}</strong></td>
    <td>${f.gate === "atypique" || f.gate === "insuffisant" ? "" : f.n_formations ? `<button data-type="${esc(f.type_key)}" data-label="${esc(f.label)}">${fmt(f.n_formations)} établissements →</button>` : ""}</td></tr>`).join("")}
  </table></div>
  ${kept.length > 15 ? `<button id="allf">${all ? "Réduire" : `Afficher les ${kept.length} filières`}</button>` : ""}`;
}

// A3 / B4: position among admits of the student's series when it can be bounded, else all nouveaux bacheliers
const SERIE_SHORT = { bg: "bacs généraux", bt: "bacs technos", bp: "bacs pros" };
const pos = (f) => (f.spos ? f.spos.cdf_used : f.cdf);
// rows of "Mon parcours" that get a "Voir un plan B" button: a plan B is only proposed when the
// target is not already a safe choice, and is most useful for the selective ones
const PLANB_ZONES = ["ambitieux", "hors_profil"];
// R5: twin of journey.within (normal curve centred on the band's middle, sigma 1, truncated; or uniform).
// R6: the zones are now read here, so erf must match Python's math.erf to ~1e-15 (it was Abramowitz-Stegun, 1.5e-7): the
// Maclaurin series up to |x| = 3 (the band needs |x| <= 2.2), the continued fraction of erfc beyond
function erf(x) {
  const ax = Math.abs(x);
  if (ax > 6) return x > 0 ? 1 : -1;
  if (ax <= 3) {
    let term = x, sum = x;
    for (let n = 1; n < 200; n++) {
      term *= -x * x / n;
      const add = term / (2 * n + 1);
      sum += add;
      if (Math.abs(add) < 1e-17 * Math.abs(sum)) break;
    }
    return 2 / Math.sqrt(Math.PI) * sum;
  }
  let f = 0;                                                            // erfc(x) = exp(-x²)/sqrt(pi) / (x + 1/2/(x + 1/(x + 3/2/(x + ...))))
  for (let k = 60; k >= 1; k--) f = (k / 2) / (ax + f);
  const erfc = Math.exp(-ax * ax) / Math.sqrt(Math.PI) / (ax + f);
  return x > 0 ? 1 - erfc : erfc - 1;
}
function withinBand(g, m, model) {
  const [lo, hi, mid] = BANDS[m], x = Math.min(Math.max(g, lo), hi);
  if (model === "uniforme") return (x - lo) / (hi - lo);
  const phi = (z) => 0.5 * (1 + erf(z / Math.SQRT2)), a = phi((lo - mid) / BAND_SIGMA), b = phi((hi - mid) / BAND_SIGMA);
  return (phi((x - mid) / BAND_SIGMA) - a) / (b - a);
}
const LADDER = ["sansmention", "ab", "b", "tb", "tbf"];
// the share of a formation's nouveau bachelier admits (known mention) below an average: the published share of the bands below,
// plus the band's own share times the within-band fraction; the hard bounds are the band's bottom and top (published)
function positionMoyenne(counts, g) {
  const n = LADDER.reduce((a, m) => a + (counts[m] || 0), 0);
  if (!n || g === null || g === undefined) return null;
  const band = g < 12 ? "sansmention" : bandOf(g);
  let below = 0;
  for (const m of LADDER) { if (m === band) break; below += counts[m] || 0; }
  const k = counts[band] || 0;
  return { n, band, normale: (below + withinBand(g, band) * k) / n, uniforme: (below + withinBand(g, band, "uniforme") * k) / n,
    bornes: [below / n, (below + k) / n] };
}
function moyenneChart(counts, g) {
  const n = LADDER.reduce((a, m) => a + (counts[m] || 0), 0);
  const W = 440, H = 210, L = 40, R = 12, T = 12, B = 34;
  const x = (v) => L + (W - L - R) * (v - 8) / 12, y = (v) => T + (H - T - B) * (1 - v);
  let gr = "";
  for (let k = 0; k <= 4; k++) gr += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(k / 4)}" y2="${y(k / 4)}"/><text x="${L - 4}" y="${y(k / 4) + 4}" text-anchor="end">${k * 25} %</text>`;
  [8, 10, 12, 14, 16, 18, 20].forEach((v) => { gr += `<text x="${x(v)}" y="${H - B + 14}" text-anchor="middle">${v}</text>`; });
  [["sans mention", 10], ["AB", 13], ["B", 15], ["TB", 17], ["TBF", 19]].forEach(([t, v]) => { gr += `<text x="${x(v)}" y="${H - 4}" text-anchor="middle">${t}</text>`; });
  [12, 14, 16, 18].forEach((v) => { gr += `<line class="grid" x1="${x(v)}" x2="${x(v)}" y1="${T}" y2="${H - B}"/>`; });
  const curve = (model) => {
    let d = "";
    for (let v = 8; v <= 20.0001; v += 0.1) { const pm = positionMoyenne(counts, Math.min(v, 20)); d += `${d ? "L" : "M"}${x(v).toFixed(1)},${y(pm.normale * (model === "normale") + pm.uniforme * (model === "uniforme")).toFixed(1)}`; }
    return d;
  };
  gr += `<path d="${curve("uniforme")}" fill="none" stroke="var(--c3)" stroke-width="2" stroke-dasharray="6 4"/>`;
  gr += `<path d="${curve("normale")}" fill="none" stroke="var(--c1)" stroke-width="2"/>`;
  let cum = 0;                                                         // the published points: the share below each band's top
  gr += `<circle cx="${x(8)}" cy="${y(0)}" r="3.5" fill="var(--ink)"/>`;
  LADDER.forEach((m) => { cum += counts[m] || 0; const v = BANDS[m][1]; gr += `<circle cx="${x(v)}" cy="${y(cum / n)}" r="3.5" fill="var(--ink)"><title>${fmt(100 * cum / n, 1)} % des admis avec « ${esc(MENTION_SHORT[m])} » ou moins (publié)</title></circle>`; });
  if (g !== null && g !== undefined) {
    const pm = positionMoyenne(counts, g), a = Math.min(pm.normale, pm.uniforme), b = Math.max(pm.normale, pm.uniforme);
    gr += `<line x1="${x(g)}" x2="${x(g)}" y1="${T}" y2="${H - B}" stroke="var(--ink)" stroke-width="1.5"/>`;
    gr += `<rect x="${x(g) - 5}" y="${y(b)}" width="10" height="${Math.max(2, y(a) - y(b))}" fill="var(--ink)" opacity=".35"/>`;
  }
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`Graphique : part des admis nouveaux bacheliers sous chaque note de 8 à 20, estimation dans chaque mention${g !== null && g !== undefined ? `, votre moyenne ${fmt(g, 1)}` : ""}`)}">${gr}</svg>`;
}
function moyenneCard(r) {
  const counts = Object.fromEntries(LADDER.map((m) => [m, r[`acc_${m}`] || 0]));
  const n = LADDER.reduce((a, m) => a + counts[m], 0);
  if (!n) return "";
  const p = bacProfile(), vp = p ? vxProfile(p) : null, g = vp ? vp.moyenne : null;
  const pm = g !== null ? positionMoyenne(counts, g) : null;
  const a = pm && Math.min(pm.normale, pm.uniforme), b = pm && Math.max(pm.normale, pm.uniforme);
  const head = pm ? `<p>Avec <strong>${moyenneText(g)}</strong>, ${Math.abs(b - a) < 0.0005 ? `<strong>${pc1(a)}</strong>` : `entre <strong>${pc1(a)}</strong> et <strong>${pc1(b)}</strong>`} des ${fmt(n)} admis nouveaux bacheliers ${esc(r.session)} dont la mention est connue avaient, selon cette estimation, une note au bac en dessous de la vôtre.${n < 20 ? ` <span class="badge warnb">peu d'admis (${fmt(n)}) : repère fragile</span>` : ""}</p>
      <p class="small">Ce qui est publié : ${pc1(pm.bornes[0])} avaient une mention plus basse que « ${esc(MENTION_SHORT[pm.band])} », ${pc1(pm.bornes[1])} avaient « ${esc(MENTION_SHORT[pm.band])} » ou moins. Votre position dans la mention est estimée entre ces deux chiffres.${g < 10 ? " Le bac au rattrapage est compté avec « sans mention » : il se lit en bas de cette mention." : ""}</p>`
    : `<p class="small">${p ? `<a href="#/profil">Indiquez votre moyenne visée dans « Mon profil »</a>` : `<a href="#/profil">Créez votre profil et indiquez votre moyenne visée</a>`} pour vous placer sur cette courbe, à l'intérieur de votre mention.</p>`;
  return `<div class="card"><h2>Votre moyenne parmi les admis ${esc(r.session)}</h2>${head}
    ${lineLegend([{ name: "estimation : courbe centrée au milieu de chaque mention", color: "var(--c1)", dash: "" }, { name: "estimation : répartition égale dans la mention", color: "var(--c3)", dash: "6 4" }])}
    ${moyenneChart(counts, g)}
    <p class="muted small">Les points sont publiés (part des admis avec chaque mention ou moins) ; entre deux points, les notes ne sont pas publiées et les deux courbes donnent la fourchette. Tous bacs confondus : les mentions ne sont pas publiées par série. Des repères, pas des chances d'admission.</p></div>`;
}
// R5: the range of the two within-band hypotheses (all bacs: mentions are not published by series), said as an estimation
// R5: the range of the two within-band hypotheses (all bacs: mentions are not published by series), said as an estimation.
// « Où je me situe » prints it under the bac général cell (PR 11 removed it with Mes vœux's column; red team OU7 since)
function moyRange(pos) {
  if (!pos) return "";
  const a = Math.min(pos.normale, pos.uniforme), b = Math.max(pos.normale, pos.uniforme);
  return estimTag(`dans la mention : ${Math.abs(b - a) < 0.005 ? pc1(a) : `${pc1(a)} – ${pc1(b)}`} (tous bacs)`, true);
}
function bgCell(f) {
  if (!f.spos) {
    return `${pc1(f.cdf)}<div class="muted small">tous bacs · [${pc1(f.cdf_ci[0])} ; ${pc1(f.cdf_ci[1])}] · n=${fmt(f.n_known)}</div>`;
  }
  const b = f.spos, exact = b.width < 0.005;
  return `<strong>${exact ? pc1(b.bounds[0]) : `${pc1(b.bounds[0])} – ${pc1(b.bounds[1])}`}</strong>
    <div class="muted small" title="${exact ? "Valeur exacte" : "Encadrement exact : toute répartition compatible avec les chiffres publiés tombe dans cet intervalle"} ; marge d'échantillonnage ${pc1(b.ci[0])} – ${pc1(b.ci[1])}${Math.abs((f.cdf ?? 0) - b.cdf_used) >= 0.005 ? ` ; tous bacs confondus : ${pc1(f.cdf)}` : ""}">marge ${fmt(100 * b.ci[0], 0)}–${fmt(100 * b.ci[1], 0)} % · ${fmt(b.n)} ${{ bg: "bac G", bt: "bac techno", bp: "bac pro" }[f.serie || "bg"]}</div>`;
}

function scatter(F, onPick) {
  const avg = vxProfile(store.get("profile", {}) || {}).moyenne !== null;   // R5 (review): the student's own average, never the rattrapage's implicit 10
  const W = 640, H = 420, L = 46, R = 14, T = 14, B = 40, Z = JV.zone_rules;
  const x = (v) => L + (W - L - R) * v / 100, y = (v) => T + (H - T - B) * (1 - v);
  const rect = (x0, x1, y0, y1, c) => `<rect x="${x(x0)}" y="${y(y1)}" width="${x(x1) - x(x0)}" height="${y(y0) - y(y1)}" fill="${c}" opacity=".10"/>`;
  let g = rect(0, 100, 0, 1, ZONES.cible.color)
    + rect(0, Z.ambitieux_access, Z.hors_profil_cdf, 1, ZONES.ambitieux.color)
    + rect(0, 100, Z.hors_profil_cdf, Z.ambitieux_cdf, ZONES.ambitieux.color)
    + rect(Z.securite_access, 100, Z.securite_cdf, 1, ZONES.securite.color)
    + rect(0, 100, 0, Z.hors_profil_cdf, ZONES.hors_profil.color);
  for (let k = 0; k <= 4; k++) {
    g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(k / 4)}" y2="${y(k / 4)}"/><text x="${L - 6}" y="${y(k / 4) + 4}" text-anchor="end">${k * 25} %</text>`;
    g += `<text x="${x(k * 25)}" y="${H - B + 16}" text-anchor="middle">${k * 25}</text>`;
  }
  const se = (F[0] && F[0].serie) || "bg";
  // owner, 2026-11-19 (Codex): the x axis is the rate the zone is read on, so a point always sits in the region of its own zone
  g += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">${se === "bg" ? (F.some((f) => f.taux_zone_source) ? "Taux d'accès de votre paire de spécialités, sinon officiel (%)" : "Taux d'accès officiel (phase principale, %)") : `Accès estimé pour les ${SERIE_SHORT[se]} (%)`}</text>`;
  g += `<text transform="translate(12 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Part des ${SERIE_SHORT[se]} admis ${avg ? "sous votre moyenne (estim.)" : "avec votre mention ou moins"}</text>`;
  F.forEach((f, i) => {
    const tx = tauxZone(f);
    if (tx == null || pos(f) == null) return;
    // R4 (review): the three zones are filled shapes (paler when uncertain or under 10 admits), every other reading an empty ring
    const c = ZONES[f.zone].color, filled = ZONE_FILLED.includes(f.zone), weak = f.uncertain || f.small_cohort;
    if (f.spos && f.spos.width >= 0.01) g += `<line x1="${x(tx)}" x2="${x(tx)}" y1="${y(f.spos.bounds[0])}" y2="${y(f.spos.bounds[1])}" stroke="${c}" stroke-width="2" opacity=".55"/>`;
    g += zoneShape(f.zone, x(tx), y(pos(f)), f.home_academie ? 6 : 4.5, `data-i="${i}" fill="${filled ? c : "var(--surface)"}"${filled && weak ? ' fill-opacity=".35"' : ""} stroke="${c}" stroke-width="${filled ? (f.home_academie ? 3 : 1.5) : 2}" style="cursor:pointer"`).replace(/\/>$/, () => `><title>${esc(f.etablissement)} — ${esc(f.filiere)}\nTaux d'accès ${fmt(f.taux_acces_ens)} %${f.taux_zone_source ? ` · ${f.taux_zone_source.source === "autres" ? "ligne « autres paires »" : "votre paire"} ${pct1(f.taux_zone_source.taux)}` : ""} · ${f.position && avg ? "sous votre moyenne (estim.)" : "avec votre mention ou moins"} ${f.spos ? `${pc1(f.spos.bounds[0])}–${pc1(f.spos.bounds[1])} des ${SERIE_SHORT[f.serie || "bg"]}` : `${pc1(f.cdf)} (tous bacs)`}\n${ZONES[f.zone].label}${f.uncertain ? " (incertain)" : ""}${f.small_cohort ? " · moins de 10 admis bac général" : ""}</title></${f.zone === "cible" ? "rect" : f.zone === "ambitieux" ? "path" : "circle"}>`);
  });
  setTimeout(() => document.querySelectorAll("svg.positioning [data-i]").forEach((el) => { el.onclick = () => onPick(F[+el.dataset.i]); }));
  return `<svg class="chart positioning" viewBox="0 0 ${W} ${H}" style="max-width:760px" role="img" aria-label="Où je me situe : chaque formation selon son taux d'accès et la part des admis avec votre mention ou moins, sa forme et sa couleur donnent sa zone">${g}</svg>`;
}

function spark(trend, key, scale = 1) {
  // One slot per campaign (2022-2025): missing campaigns and null values break the line,
  // never interpolated, consistent with the evolution charts.
  const years = META.years, by = Object.fromEntries(trend.map((t) => [t.session, t[key]]));
  const vals = years.map((y) => (by[y] === undefined ? null : by[y]));
  if (vals.filter((v) => v != null).length < 1) return "";
  const xs = (i) => 3 + i * 54 / Math.max(1, years.length - 1), ys = (v) => 16 - 14 * Math.min(1, v / scale);
  let d = "", pen = false, dots = "";
  vals.forEach((v, i) => {
    if (v == null) { pen = false; return; }
    d += `${pen ? "L" : "M"}${xs(i)},${ys(v)}`; pen = true;
    dots += `<circle cx="${xs(i)}" cy="${ys(v)}" r="1.6" fill="var(--ink)"/>`;
  });
  return `<svg viewBox="0 0 60 18" style="width:60px;height:18px"><path d="${d}" fill="none" stroke="var(--ink)" stroke-width="1.5"/>${dots}<title>${years.map((y, i) => `${y} : ${vals[i] == null ? "n.d." : (scale === 1 ? pc1(vals[i]) : fmt(vals[i]) + " %")}`).join("\n")}</title></svg>`;
}

async function viewParcours() {
  if (isReo(store.get("profile", null))) return viewReorientation("", "");   // sprint 21: no positioning by bac outside terminale
  const mk = "parcours:loading";                                     // R1 review: a late answer never draws over another page
  $view.dataset.rendered = mk;
  JV = JV || await api("/api/journey/vocab");
  if ($view.dataset.rendered !== mk) return;
  const hasProfile = !!store.get("profile", null);                   // lot 3: a stored profile folds the form under one line
  const p = store.get("profile", { spe1: "MATHS", spe2: "SES", mention: "ab", academie: "", boursier: false });
  const show = new Set(store.get("gates", ["predilection", "accessible"]));
  const allF = store.get("allFilieres", false);
  const allPos = store.get("allPositions", false);                    // lot 3: 20 rows first, the rest on request
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";   // stored profile: never trusted
  const sq = serie === "bg" ? `spe1=${encodeURIComponent(p.spe1)}&spe2=${encodeURIComponent(p.spe2)}` : `serie=${encodeURIComponent(serie)}`;
  const s1 = serie !== "bg" || p.spe1 !== p.spe2 ? await api(`/api/journey/stage1?${sq}`) : null;
  if ($view.dataset.rendered !== mk) return;
  const drill = store.get("drill", null);
  const s2 = s1 && drill ? stage2Local(await api(`/api/journey/stage2?${sq}&${mentionParams(new URLSearchParams(), vxProfile(p))}&type=${encodeURIComponent(drill.type)}&academie=${encodeURIComponent(p.academie || "")}`), p) : null;
  if ($view.dataset.rendered !== mk) return;
  // sprint 10: the positioning answers are served by the CDN, so the page sends the audience count itself
  if (s1) track("journey", { stage: "stage1" });
  if (s2) track("journey", { stage: "stage2" });
  const W = voeux.get();
  const onlyHome = !!p.academie && store.get("onlyHome", false);   // never filter without an académie
  const F = s2 ? s2.formations.filter((f) => f.zone !== "non_ouvert" && (!onlyHome || f.home_academie)) : [];
  const closed = s2 ? s2.formations.filter((f) => f.zone === "non_ouvert").length : 0;
  const vp = vxProfile(p);                                           // R5: the band set by the average, when there is one
  const mLabel = `${JV.mentions.find((m) => m.code === vp.mention)?.label || ""}${vp.moyenne !== null ? `, moyenne visée ${moyenneText(vp.moyenne)}` : ""}`;
  if (p.lycee) { try { await loadLycees(); } catch (_) { /* the card says the lycée is unavailable */ } }
  if ($view.dataset.rendered !== mk) return;
  $view.dataset.rendered = "parcours";
  $view.innerHTML = `<div class="card"><h1>Où je me situe</h1><p class="small">Les filières qui recrutent votre profil, puis chaque formation située parmi ses admis des années passées. Des repères, pas des chances d'admission.</p></div>
  <div class="card"><h2>1 · Mon profil</h2>${hasProfile ? `<p class="home-profile"><span>Lu pour : <strong>${profileLine(vp, serie)}</strong></span><a class="btnlink" href="#/profil">Modifier mon profil</a></p>`
      : `<p class="home-profile"><span>Exemple avec un bac général Mathématiques + SES, mention assez bien : <strong>créez votre profil</strong> pour lire ces chiffres pour vous.</span><a class="btnlink" href="#/profil">Créer mon profil</a></p>`}${mathsExpertesNote(p, serie)}
    ${!s1 ? `<div class="warn">Vos deux spécialités sont identiques : <a href="#/profil">choisissez deux spécialités distinctes dans « Mon profil »</a>.</div>` : serie === "bg"
      ? `<p class="small muted">Spécialités ${esc(s1.doublette.split("+").map(speName).join(" + "))} : ${fmt(s1.national.candidates)} candidats bacheliers généraux sur ${s1.national.years} campagnes, ${pc1(s1.national.national_share)} des admis, taux de proposition toutes filières confondues ${pc1(s1.national.offer_rate)}.</p>`
      : `<p class="small muted">${fmt(s1.national.accepted)} ${SERIE_SHORT[serie]} admis sur ${s1.national.years} campagnes, ${pc1(s1.national.national_share)} des nouveaux bacheliers admis. Le ministère regroupe toutes les séries ${serie === "bt" ? "technologiques (STMG, STI2D, ST2S…)" : "et spécialités du bac professionnel"} : le site ne peut pas les distinguer. ${tip("serie_offer")}</p>
        <p class="small">Une part faible veut dire « rare », pas « fermé ». Le chiffre de votre bac publié dans le rapport du jury de chaque formation s'affiche sur sa fiche et dans « Mes vœux »${p.voie ? "" : ` : indiquez votre ${serie === "bt" ? "série et vos spécialités" : "spécialité de bac pro"} dans <a href="#/profil">« Mon profil »</a>`}.${serie === "bp" ? ` Beaucoup de BTS se préparent aussi en apprentissage : <a href="#/carte/${encodeURIComponent("BTS - BTSA - BTSM")}">voir les offres sur la carte</a> (filtre « Apprentissage »).` : ""}</p>`}</div>
  ${lyceeCard(p)}
  ${s1 ? `<div class="card"><h2>2 · Filières qui recrutent ${serie === "bg" ? "vos deux spécialités" : `les ${SERIE_SHORT[serie]}`} ${tip(serie === "bg" ? "journey_stage1" : "serie_offer")} ${tip("journey_gate")}</h2>${serie === "bg" ? stage1Matrix(s1, show, allF) : stage1SeriesMatrix(s1, show, allF)}</div>` : ""}
  ${s2 ? `<div class="card" id="stage3"><h2>3 · Positionnement : ${esc(drill.label)} ${tip("journey_cdf")} ${tip("journey_zones")}</h2>
    <p class="small muted">Mention visée : ${esc(mLabel)}. ${fmt(F.length)} formations en ${s2.session}, profils cumulés sur 2022–2025. Chaque point est placé parmi les ${SERIE_SHORT[serie]} admis ; le trait vertical montre l'encadrement exact quand les données ne permettent pas d'être plus précis. Les formes pâles sont incertaines (intervalle à 95 %) ou ont moins de 10 ${SERIE_SHORT[serie]} admis ; un anneau vide est hors des trois zones${serie !== "bg" ? " ; l'axe horizontal est l'accès estimé pour votre série, pas le taux d'accès officiel" : ""}${p.academie ? " ; les cercles épais sont dans votre académie" : ""}. Cliquez sur un point pour l'ajouter à « Mes vœux ».${closed ? ` ${closed} formation(s) fermées à votre série par leurs groupes d'appel${serie === "bg" ? " ou parce que les bacheliers généraux y représentent moins de 5 % des admis 2022–2025 (ex. CPGE ECT)" : ""} sont exclues.` : ""}</p>
    <div class="toolbar">${p.academie ? `<label><input type="checkbox" id="oh" ${onlyHome ? "checked" : ""}> Seulement l'académie de ${esc(acadLabel(p.academie))}</label>` : ""}<a href="#/carte/t/${encodeURIComponent(drill.type)}">Voir ces formations sur la carte →</a></div>
    <div class="legend">${Object.entries(ZONES).map(([k, z]) => `<span style="color:${z.color}">${zoneMark(k)}<span class="lg-text">${z.label} (${F.filter((f) => f.zone === k).length})</span></span>`).join("")}</div>
    ${zoneLegend()}
    ${repereNote(s2.calibration)}
    ${scatter(F, (f) => pin(f))}
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th>Zone</th><th class="num">${serie === "bg" ? "Taux d'accès" : `Accès estimé ${SERIE_SHORT[serie]} ${tip("serie_offer")}`}</th><th class="num">${serie === "bg" ? "Bacs généraux" : serie === "bt" ? "Bacs technos" : "Bacs pros"} admis ${vp.moyenne !== null ? "sous votre moyenne (estimation)" : "avec votre mention ou moins"} ${tip("journey_bg")}</th><th class="num">Mention exacte</th><th class="num">${serie === "bg" ? "Bac général" : `Part ${SERIE_SHORT[serie]}`}</th><th class="num">${p.boursier ? "<strong>Boursiers</strong>" : "Boursiers"}</th><th>Votre groupe d'appel ${tip("journey_groups")}</th>${s2.calibration ? `<th>Repère ${esc(s2.calibration.target)} ${tip("repere")}</th>` : ""}<th>Évolution</th><th><span class="sr-only">Actions</span></th></tr>
    ${F.slice().sort((a, b) => (pos(b) ?? -1) - (pos(a) ?? -1)).slice(0, allPos ? 80 : 20).map((f) => `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.filiere)} · ${esc(f.ville)}${f.home_academie ? ' · <span class="badge exact">votre académie</span>' : ""}${p.lycee && f.cod_uai === p.lycee.uai ? ` · <span class="badge exact">dans votre lycée${f.pct_etab_orig != null ? ` · ${fmt(f.pct_etab_orig)} % des admis en venaient` : ""}</span>` : ""}${f.non_selective && f.home_academie ? ` · ${fmt(f.pct_aca_orig)} % d'admis de l'académie` : ""}</div>${offerBadges(f, true)}</td>
      <td data-label="Zone">${zoneBadge(f.zone, f.uncertain, f.large)}${zoneAxisNote(f)}${f.small_cohort ? ` <span class="badge warnb">moins de 10 admis ${serie === "bg" ? "en bac général" : serie === "bt" ? "en bac techno" : "en bac pro"}</span>` : ""}${f.rate_fragile ? ' <span class="badge warnb" title="Moins de 20 candidats de votre série : taux fragile">peu de candidats</span>' : ""}${f.rare_for_serie ? ` <span class="badge warnb" title="Moins de 5 % des admis 2022–2025 viennent de votre série">rare pour les ${SERIE_SHORT[serie]}</span>` : ""}${f.limited_comparability && !f.spos ? ' <span class="badge warnb" title="Moins de 50 % de bacheliers généraux parmi les admis : la distribution des mentions mêle surtout d\'autres séries">comparabilité limitée</span>' : ""}</td>
      <td class="num" data-label="${serie === "bg" ? "Taux d'accès" : "Accès estimé"}">${f.taux_acces_ens != null ? `${fmt(f.taux_acces_ens)} %` : "—"}${serie !== "bg" ? `<div class="muted small" title="Estimation. Taux de proposition des candidats de votre série : ${f.serie_proposal_rate != null ? `${fmt(f.serie_proposal_rate)} %` : "—"} ; taux d'accès officiel (tous candidats) : ${fmt(f.taux_acces_all)} %">${estimTag(`officiel tous candidats ${fmt(f.taux_acces_all)} %`)}</div>` : ""}</td><td class="num" data-label="${vp.moyenne !== null ? "Admis sous votre moyenne (estimation)" : "Admis avec votre mention ou moins"}">${bgCell(f)}${moyRange(f.position)}</td>
      <td class="num" data-label="Mention exacte">${pc1(f.exact_share)}</td><td class="num" data-label="${serie === "bg" ? "Bac général" : "Part de votre série"}">${pc1(serie === "bg" ? f.pct_bg : f.pct_serie)}</td><td class="num" data-label="Boursiers">${pc1(f.pct_boursiers)}</td>
      <td class="small" data-label="Groupe d'appel">${f.group && !f.group.ambiguous ? `${esc(f.group.label)}<div class="muted">dernier appelé : rang ${fmt(f.group.last_called_rank)}</div>` : '<span class="muted">non déterminé</span>'}</td>
      ${s2.calibration ? `<td class="small" data-label="Repère">${repereCell(f, serie)}</td>` : ""}
      <td data-label="Évolution">${spark(f.trend, "cdf")}${spark(f.trend, "taux_acces_ens", 100)}</td>
      <td class="acts"><button data-pin="${esc(f.cod_aff_form)}" class="small">${W.includes(f.cod_aff_form) ? "dans mes vœux" : "ajouter à mes vœux"}</button>${PLANB_ZONES.includes(f.zone) ? `<button type="button" data-planb="${esc(f.cod_aff_form)}" class="small planb-btn" aria-expanded="false">Voir un plan B</button>` : ""}</td></tr>`).join("")}
    </table></div>${F.length > 20 ? `<p><button type="button" id="allpos">${allPos ? "Afficher les 20 premières" : `Afficher ${F.length > 80 ? "les 80 premières" : `les ${fmt(F.length)}`} formations`}</button></p>` : ""}
    ${F.length > (allPos ? 80 : 20) ? `<p class="muted small">${allPos ? 80 : 20} premières formations affichées (toutes figurent sur la matrice).</p>` : ""}
    ${p.boursier ? `<p class="small muted">Boursier : la part de boursiers parmi les admis est affichée à titre d'information. Les taux minimaux de boursiers fixés par les recteurs ne sont pas publiés formation par formation dans ces données ; aucun ajustement n'est appliqué.</p>` : ""}</div>` : ""}
  <div class="card"><h2>4 · Mes vœux</h2><p id="wishlist">${W.length ? `${fmt(W.length)} vœu(x) dans votre liste.` : "Votre liste est vide : ajoutez des formations depuis le tableau ou un plan B."} <a href="#/voeux">Voir la lecture de ma liste pour ce profil →</a></p>
    <p class="muted small">La liste est relue pour votre profil actuel à chaque visite (${voeux.MAX} vœux au maximum sur Parcoursup).</p></div>${nextSteps("parcours")}${feedbackBox("parcours")}`;

  function pin(f, rerender = true) {
    if (!voeux.add(f.cod_aff_form)) { alert(`${voeux.MAX} vœux au maximum : retirez un vœu dans « Mes vœux » d'abord.`); return; }
    if (rerender) viewParcours();
  }

  $view.querySelectorAll("[data-gate]").forEach((el) => { el.onchange = () => { el.checked ? show.add(el.dataset.gate) : show.delete(el.dataset.gate); store.set("gates", [...show]); viewParcours(); }; });
  $view.querySelectorAll("[data-type]").forEach((el) => { el.onclick = async () => { store.set("drill", { type: el.dataset.type, label: el.dataset.label }); await viewParcours(); document.getElementById("stage3")?.scrollIntoView({ behavior: "smooth" }); }; });
  const af = document.getElementById("allf"); if (af) af.onclick = () => { store.set("allFilieres", !allF); viewParcours(); };
  const ap = document.getElementById("allpos"); if (ap) ap.onclick = () => { store.set("allPositions", !allPos); viewParcours(); };
  // "Voir un plan B": the same programme elsewhere, more accessible, opened under the row
  $view.querySelectorAll("[data-planb]").forEach((el) => {
    el.onclick = () => {
      const tr = el.closest("tr");
      const open = tr.nextElementSibling?.classList.contains("planb-row") ? tr.nextElementSibling : null;
      if (open) { open.remove(); el.textContent = "Voir un plan B"; el.setAttribute("aria-expanded", "false"); return; }
      const row = document.createElement("tr");
      row.className = "planb-row";
      row.innerHTML = `<td colspan="${tr.children.length}"><div class="planb-inline" aria-live="polite"></div></td>`;
      tr.after(row);
      el.textContent = "Masquer le plan B";
      el.setAttribute("aria-expanded", "true");
      track("action", { a: "planb" });
      const box = row.querySelector(".planb-inline");
      loadPlanB(el.dataset.planb, { box, profile: { ...p, serie }, inline: true, onPin: (a) => {
        pin({ cod_aff_form: a.cod_aff_form }, false);
        const b = box.querySelector(`[data-pbpin="${CSS.escape(a.cod_aff_form)}"]`);
        if (b && voeux.has(a.cod_aff_form)) b.textContent = "dans mes vœux";
        const list = document.getElementById("wishlist");
        if (list) list.innerHTML = `${fmt(voeux.get().length)} vœu(x) dans votre liste. <a href="#/voeux">Voir la lecture de ma liste pour ce profil →</a>`;
      } });
    };
  });
  $view.querySelectorAll("[data-pin]").forEach((el) => { el.onclick = () => pin(F.find((f) => f.cod_aff_form === el.dataset.pin)); });
  const oh = document.getElementById("oh"); if (oh) oh.onchange = () => { store.set("onlyHome", oh.checked); viewParcours(); };
}

// ---- R1 (owner, 2026-11-11): "Mon profil", the one place the profile is edited, every field explained -------------------
// The first save is explicit (nothing is read for the student before it); once a profile exists, each change is saved at once.
// The profile stays in this browser: zones are read by sending the bac, specialties, mention and académie (no-store answers, no
// audience figure carries them); the lycée is searched here and never sent. Same validation as everywhere (vxProfile).
const PF_DEFAULT = { serie: "bg", spe1: "MATHS", spe2: "SES", mention: "ab", academie: "", boursier: false, statut: "terminale" };
async function viewProfil() {
  $view.dataset.rendered = "profil:loading";                           // marker before the first await (navigation races)
  JV = JV || await api("/api/journey/vocab");
  if ($view.dataset.rendered !== "profil:loading") return;
  let draft = null, justSaved = false, confirmErase = false;
  const sugg = store.get("profilDraft", null);                        // the lycée picked from a search, before any profile (review)
  if (sugg) {
    store.set("profilDraft", null);
    const l = sugg.lycee;
    if (l && typeof l === "object" && ["uai", "nom", "commune"].every((k) => typeof l[k] === "string"))
      draft = { lycee: { uai: l.uai, nom: l.nom, commune: l.commune }, academie: JV.academies.includes(sugg.academie) ? sugg.academie : "" };
  }
  const draw = (focusName) => {
    const raw = store.get("profile", null);
    const has = !!raw && typeof raw === "object" && !Array.isArray(raw);
    const p = has ? vxProfile(raw) : { ...PF_DEFAULT, ...(draft || {}) };
    const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";
    const uses = isReo(p) ? `<li><strong>Je me réoriente</strong>l'accès estimé hors terminale de chaque formation, sans zone</li>
        <li><strong>Fiche d'une formation</strong>l'accès estimé pour les candidats qui ne sont pas en terminale</li>
        <li><strong>Mes vœux</strong>votre liste relue avec cet accès estimé</li>
        <li><strong>Explorer</strong>les formations de votre académie d'abord</li>`
      : `<li><strong>Fiche d'une formation</strong>votre zone et le chiffre de ${serie === "bg" ? "votre paire de spécialités" : "votre bac"} dans le rapport du jury, à côté du taux officiel</li>
        <li><strong>Carte des formations</strong>chaque formation colorée selon votre zone</li>
        <li><strong>Mes vœux</strong>votre liste comptée en vœux de sécurité, cibles et ambitieux</li>
        <li><strong>Où je me situe</strong>les filières qui recrutent votre profil, formation par formation</li>`;
    $view.innerHTML = `<div class="pf-page">
    <div class="card"><h1>Mon profil</h1>
      <p>SupCompass lit les chiffres officiels de Parcoursup pour vous : vos réponses servent à placer chaque formation par rapport aux admis des années passées. Ce sont des repères, jamais des chances d'admission.</p>
      ${has ? `<p class="info">Profil ${justSaved ? "enregistré" : "en place"} : <strong>${profileLine(p, serie)}</strong>. Chaque modification est enregistrée aussitôt.</p>`
        : `<p class="info">Pas encore de profil : les pages affichent des chiffres généraux. Remplissez les champs ci-dessous puis enregistrez.</p>`}</div>
    ${profileForm(p, has)}
    ${has ? `<div class="card"><h2>Ce que votre profil change</h2><ul class="pf-uses">${uses}</ul>
      <p class="toolbar">${isReo(p) ? '<a class="btnlink" href="#/reorientation">Voir les formations</a>' : '<a class="btnlink" href="#/parcours">Où je me situe</a><a class="btnlink" href="#/">Explorer les formations</a>'}<a class="btnlink" href="#/voeux">Mes vœux</a></p></div>` : ""}
    <div class="card"><h2>Ce que devient votre profil</h2>
      <ul class="small">
        <li>Il reste dans ce navigateur : pas de compte, pas d'adresse e-mail.</li>
        <li>Pour lire vos zones, la page envoie votre bac, vos spécialités, votre mention et votre académie. Le serveur ne les enregistre pas et aucune mesure d'audience ne les contient.</li>
        <li>Votre lycée n'est jamais envoyé : la liste des lycées est cherchée dans ce navigateur.</li>
        <li>Votre ville n'est jamais envoyée : les distances sont calculées dans ce navigateur.</li>
        <li>Une liste partagée avec un adulte n'inclut votre profil que si vous cochez la case prévue (jamais votre académie ni votre lycée).</li>
        <li>Le lien « Transférer sur mon autre appareil » contient votre profil, moyenne comprise : il est pour vous seul.</li>
      </ul>
      ${has ? (confirmErase ? `<p class="toolbar"><span class="small">Effacer votre profil de ce navigateur ? Votre liste de vœux est gardée.</span><button type="button" id="pf-erase-yes">Oui, effacer</button><button type="button" id="pf-erase-no">Annuler</button></p>`
        : `<p><button type="button" id="pf-erase">Effacer mon profil</button></p>`) : ""}</div>
    ${has ? transferCard() : ""}
    </div>`;
    $view.dataset.rendered = "profil";
    bind(p, serie, has, raw);
    if (has) bindTransfer();
    bindVille(() => draw());
    if (focusName) { const el = document.querySelector(`#pf [name="${focusName}"]${focusName === "statut" ? ":checked" : ""}`); if (el) el.focus(); }
  };
  const bind = (p, serie, has, raw) => {
    const form = document.getElementById("pf");
    // the lycée picked or removed goes through the same submit: edits made in the form before picking it are kept
    let lyc = p.lycee || null;
    // R5: an average outside 8-20 (or not a number) is said, never saved nor silently dropped
    const badMoyenne = () => {
      const el = form.querySelector('[name="moyenne"]');
      if (!el || !el.value.trim() || validMoyenne(el.value) !== null) { if (el) el.removeAttribute("aria-invalid"); return false; }
      const help = document.getElementById("pf-moy-help");
      if (help) help.innerHTML = '<span class="warn">Moyenne non reconnue : indiquez un nombre entre 8 et 20 (par exemple 13,4), ou laissez vide.</span>';
      el.setAttribute("aria-invalid", "true");                         // R8: the error is tied to its field
      el.focus();
      return true;
    };
    form.onchange = (e) => {
      const name = e.target.name || "";
      if (!name || name === "lyc-q") return;
      const act = () => {
        if (name === "moyenne" && badMoyenne()) return;
        if (name === "statut") return setSituation(e.target.value, has, raw, new FormData(form), p, serie, lyc, form);
        if (has) { form.requestSubmit(); return; }
        draft = { ...(draft || {}), ...readForm(new FormData(form), p, serie, lyc, form, null) }; draw(name);   // no profile yet: nothing stored before "Enregistrer"
      };
      // audit PR 8: a change fired by the field LOSING focus (typed, then a tap elsewhere) is dispatched inside the browser's blur:
      // redrawing the page there threw « Failed to set the 'innerHTML' property … moved in a 'blur' event handler » (testers, twice).
      // Redraw once the blur is over, and only if the form is still the page's (a tap on « Enregistrer » has drawn it already).
      if (document.activeElement === e.target) act();
      else setTimeout(() => { if (form.isConnected) act(); }, 0);
    };
    form.onsubmit = (e) => {
      e.preventDefault();
      if (badMoyenne()) return;
      const np = readForm(new FormData(e.target), p, serie, lyc, e.target, has ? raw : null);
      if (np.serie !== serie || np.spe1 !== p.spe1 || np.spe2 !== p.spe2) store.set("drill", null);
      if (!np.academie) store.set("onlyHome", false);
      justSaved = !has; draft = null;
      store.set("profile", np); draw(e.submitter ? null : document.activeElement && document.activeElement.name);
    };
    const lq = document.getElementById("lyc-q"), lres = document.getElementById("lyc-res"), lhelp = document.getElementById("lyc-help");
    if (lq) {
      lq.onfocus = () => { loadLycees().catch(() => { lhelp.textContent = "Liste des lycées indisponible pour le moment."; }); };
      lq.oninput = async () => {
        try { await loadLycees(); } catch (_) { return; }
        if (lq !== document.getElementById("lyc-q")) return;      // the page was redrawn meanwhile
        const hits = lycSearch(lq.value);
        lres.innerHTML = hits.map((l) => `<button type="button" role="option" data-lyc="${esc(l.uai)}">${esc(l.nom)}<span class="muted small"> · ${esc(l.commune)}</span></button>`).join("");
        lres.querySelectorAll("[data-lyc]").forEach((b) => {
          b.onclick = () => {
            const l = LYC.byUai[b.dataset.lyc];
            lyc = { uai: l.uai, nom: l.nom, commune: l.commune };
            const sel = document.querySelector('#pf [name="academie"]');
            if (sel && l.academie && JV.academies.includes(l.academie)) sel.value = l.academie;   // académie follows the lycée
            if (has) document.getElementById("pf").requestSubmit();
            else { draft = { ...(draft || {}), ...readForm(new FormData(form), p, serie, lyc, form, null) }; draw(); }
          };
        });
      };
    }
    if (lq) lq.onkeydown = (e) => { if (e.key === "Enter") e.preventDefault(); };   // Enter picks nothing and saves nothing (review)
    const lc = document.getElementById("lyc-clear");
    if (lc) lc.onclick = () => {
      lyc = null;
      if (has) document.getElementById("pf").requestSubmit();
      else { draft = { ...(draft || {}), ...readForm(new FormData(form), p, serie, null, form, null), lycee: null }; draw(); }   // no profile yet: still a draft (review)
    };
    const er = document.getElementById("pf-erase");
    if (er) er.onclick = () => { confirmErase = true; draw(); document.getElementById("pf-erase-no")?.focus(); };
    const ey = document.getElementById("pf-erase-yes");
    if (ey) ey.onclick = () => { confirmErase = false; justSaved = false; store.set("profile", null); store.set("drill", null); store.set("villeDepart", null); draw(); };
    const en = document.getElementById("pf-erase-no");
    if (en) en.onclick = () => { confirmErase = false; draw(); };
  };
  // terminale <-> not in terminale: the bac fields the student entered are kept; going back to terminale with none asks for them
  // (the defaults are shown, never stored before "Enregistrer"): the same rule as "Je me réoriente" (sprint 21)
  const setSituation = (st, has, raw, fd, p, serie, lyc, form) => {
    if (!has) {                                                       // no profile yet: the switch is part of the draft (review)
      const asTerminale = { get: (k) => (k === "statut" ? "terminale" : fd.get(k)) };
      draft = st === "reorientation" ? { ...readForm(asTerminale, p, serie, lyc, form, null), statut: "reorientation" }
        : { ...(draft || {}), academie: fd.get("academie") || "", statut: "terminale" };
    } else if (st === "reorientation") store.set("profile", { ...raw, statut: "reorientation" });
    else if (raw.serie || raw.spe1 || raw.voie) store.set("profile", { ...raw, statut: "terminale" });
    else {                                                            // no bac field was ever entered: ask for them, keep the rest
      const keep = Object.fromEntries(["academie", "lycee", "boursier"].filter((k) => raw[k] != null).map((k) => [k, raw[k]]));
      store.set("profile", null); draft = { ...keep, statut: "terminale" };
    }
    justSaved = false; draw("statut");
  };
  draw();
}
// one reading of the form for both the first save and later changes; a field the situation does not draw keeps its stored value.
// Outside terminale only the académie is read and the STORED fields are kept as they are (raw): no bac field is ever invented.
function readForm(fd, p, serie, lyc, form, raw) {
  const vsel = form.querySelector('[name="voie"]');
  const reo = fd.get("statut") === "reorientation";
  if (reo) return { ...(raw || {}), academie: fd.get("academie") || "", statut: "reorientation" };
  return { ...voieFromForm(fd, serie, vsel ? vsel.selectedOptions[0].textContent : null),
    // R5: an average sets the band (the list is disabled then); a blank or invalid average is dropped, never invented
    ...((m) => (m !== null ? { moyenne: m, mention: bandOf(m) } : { moyenne: null, mention: fd.get("mention") || p.mention }))(validMoyenne(fd.get("moyenne"))),
    serie: fd.get("serie") || "bg", spe1: fd.get("spe1") || p.spe1 || "MATHS",
    spe2: fd.get("spe2") ? spe2Of(fd.get("spe1") || p.spe1 || "MATHS", fd.get("spe2"), p.spe1) : (p.spe2 || "SES"),   // distinct before it is saved
    academie: fd.get("academie") || "", boursier: !!fd.get("boursier"),
    maths_expertes: form.querySelector('[name="maths_expertes"]') ? !!fd.get("maths_expertes") : !!(raw ? raw.maths_expertes : p.maths_expertes), lycee: lyc, statut: fd.get("statut") === "reorientation" ? "reorientation" : "terminale" };
}

// ---- A5 glossary (V1) and the source register ---------------------------------------------
const ACCESS_LABEL = { ods: "téléchargée automatiquement", owner_upload: "fichier déposé (site du producteur fermé aux robots)", planned: "prévue" };
function viewGlossaire(q) {
  const G = (META && META.glossary) || [], S = (META && META.sources) || [];
  const norm = (x) => String(x || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const draw = (term) => {
    const t = norm(term);
    const hits = G.filter((g) => !t || norm(g.terme).includes(t) || norm(g.definition).includes(t));
    document.getElementById("gl-list").innerHTML = hits.length ? hits.map((g) => `<div class="gl-item" id="g-${esc(g.key)}"><h2>${esc(g.terme)}</h2><p>${esc(g.definition)}</p>${g.methode && META.methodology[g.methode] ? `<details><summary class="small">Méthode détaillée</summary><p class="small muted">${esc(META.methodology[g.methode])}</p></details>` : ""}</div>`).join("")
      : `<p class="muted">Aucun terme ne correspond.</p>`;
  };
  $view.innerHTML = `<div class="card"><h1>Glossaire</h1>
    <p class="small muted">Les mots de Parcoursup et des statistiques du site, expliqués simplement.</p>
    <input id="gl-q" type="search" placeholder="Chercher un mot (vœu, mention, taux d'accès…)" aria-label="Chercher dans le glossaire" value="${esc(q)}" class="gl-q">
    <div id="gl-list"></div></div>
  <div class="card"><h2>Sources des données</h2>
    <p class="small muted">Chaque chiffre du site vient d'une de ces sources publiques. Les sources « prévues » arriveront dans les prochaines étapes du parcours.</p>
    <div class="scroll"><table><tr><th>Source</th><th>Producteur</th><th>Précision</th><th>Statut</th></tr>
    ${S.map((s) => `<tr><td>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)} ↗</a>` : esc(s.title)}<div class="muted small">${esc(ACCESS_LABEL[s.access] || "")}</div></td>
      <td>${esc(s.producer)}</td><td>${esc(s.granularity)}</td>
      <td>${s.status === "en_ligne" ? '<span class="badge exact">en ligne</span>' : `<span class="badge">${s.status === "depose" ? "déposée, pas encore intégrée" : "prévue"}${s.sprint ? ` · étape ${esc(s.sprint)}` : ""}</span>${s.status === "depose" && s.role ? `<div class="muted small">${esc(s.role)}</div>` : ""}`}</td></tr>`).join("")}</table></div></div>`;
  const inp = document.getElementById("gl-q");
  inp.oninput = () => draw(inp.value);
  draw(q);
}

// ---- audience measurement (no cookie, no identifier: see /#/stats → Méthode) ---------
const PRIVACY_OFF = navigator.doNotTrack === "1" || window.doNotTrack === "1" || navigator.globalPrivacyControl === true;
function track(t, props = {}) {
  if (PRIVACY_OFF) return;
  try {
    const body = JSON.stringify({ t, ...props });
    if (!(navigator.sendBeacon && navigator.sendBeacon("/api/e", new Blob([body], { type: "application/json" })))) {
      fetch("/api/e", { method: "POST", body, keepalive: true, headers: { "Content-Type": "application/json" } }).catch(() => {});
    }
  } catch (_) { /* measurement is best effort */ }
}
let firstView = true;
function trackView(routeName, cod) {
  const w = window.innerWidth || 1024;
  const p = { route: routeName, device: w < 768 ? "mobile" : w < 1100 ? "tablet" : "desktop" };
  if (routeName === "fiche") { if (!/^\d{1,9}$/.test(cod || "")) return; p.cod = cod; }
  if (firstView) {
    p.first = true;
    try { const h = document.referrer ? new URL(document.referrer).hostname : ""; if (h && h !== location.hostname) p.ref = h; } catch (_) { /* bad referrer */ }
    firstView = false;
  }
  track("view", p);
}
let jsErrors = 0;
const onJsError = () => { if (jsErrors++ < 3) track("jserr", { route: ROUTE_NAME[(location.hash.split("/")[1] || "")] || "home" }); };
window.addEventListener("error", onJsError);
window.addEventListener("unhandledrejection", onJsError);
document.addEventListener("click", (e) => {
  const a = e.target.closest?.('a[href*="parcoursup.fr"]');
  if (a) track("out", a.dataset.cod ? { cod: a.dataset.cod } : {});
});

const FB_REASONS = [["introuvable", "Je ne trouve pas ce que je cherche"], ["incomprehensible", "Les chiffres sont difficiles à comprendre"],
  ["manque_info", "Il manque une information"], ["erreur_donnees", "Une donnée me semble fausse"], ["lent", "C'est lent"]];
const fbDone = (page) => { try { return sessionStorage.getItem(`fb:${page}`); } catch (_) { return null; } };
function feedbackBox(page) {
  if (PRIVACY_OFF) return "";
  if (fbDone(page)) return `<div class="card feedback small muted">Merci pour votre avis !</div>`;
  return `<div class="card feedback" data-fbpage="${page}"><span>Cette page vous a aidé ?</span>
    <button type="button" data-fb="up" aria-label="Oui, cette page m'a aidé">Oui</button>
    <button type="button" data-fb="down" aria-label="Non, cette page ne m'a pas aidé">Non</button>
    <span class="muted small">Anonyme : aucun texte libre, aucun identifiant.</span></div>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest?.("[data-fb], [data-fbr]");
  const box = b?.closest("[data-fbpage]");
  if (!box) return;
  const page = box.dataset.fbpage;
  try { sessionStorage.setItem(`fb:${page}`, "1"); } catch (_) { /* storage blocked */ }
  if (b.dataset.fb === "up") { track("feedback", { page, vote: "up", reason: "utile" }); box.innerHTML = `<span class="muted small">Merci pour votre avis !</span>`; return; }
  if (b.dataset.fb === "down") {
    track("feedback", { page, vote: "down" });
    box.innerHTML = `<span>Merci. Qu'est-ce qui n'allait pas ?</span> ${FB_REASONS.map(([k, l]) => `<button type="button" class="small" data-fbr="${k}">${esc(l)}</button>`).join(" ")}`;
    return;
  }
  track("feedback", { page, vote: "down", reason: b.dataset.fbr });
  box.innerHTML = `<span class="muted small">Merci, c'est noté : ça nous aide à corriger.</span>`;
});

// ---- Sprint 11: "Mes vœux" (the list read for the CURRENT profile) ----------
// sprint 20: the student's row of each vœu's report (bac techno and pro), with its source; never a chance
// R9: ONE rendering of the figure for the student's doublette (Mes vœux and the map's list read the same voeux.figures answer)
function dblFigure(v) {
  return v.rapport ? `${pct1(v.rapport.taux)}<div class="estim">rapport public ${esc(v.rapport.session)} de la formation${v.rapport.source === "autres" ? ", autres paires de spécialités" : ""}${v.rapport.recoupe === false ? `, pas encore recoupé avec les chiffres de ${esc(v.rapport.session)}` : ""}</div>` : v.semblable ? `${pct1(v.semblable.taux)}${estimTag(`${fmt(v.semblable.n_rapports)} rapports de formations semblables`, true)}` : v.doublette ? (v.doublette.formation ? `${pct1(v.doublette.formation.taux)}${estimTag(`groupe national ${pct1(v.doublette.taux)}${v.doublette.source === "autres" ? " (autres paires de spécialités)" : ""}`, true)}` : `${pct1(v.doublette.taux)}<div class="estim">groupe national${v.doublette.source === "autres" ? ", autres paires de spécialités" : ""}</div>`) : "—";
}
// ... and of the student's line in the report for bac techno / pro
function voieFigure(r, prof) {
  return r ? `${pct1(r.taux)}<div class="estim">${fmt(r.en_position)} sur ${fmt(r.confirmes)} · rapport public ${esc(r.session)} de la formation${r.source === "autres" ? `, ligne « ${esc(rpLabel(r.libelle))} »` : ""}${r.recoupe === false ? `, pas encore recoupé avec les chiffres de ${esc(r.session)}` : ""}</div>` : prof.voie ? '<span class="muted small">pas de ligne publiée</span>' : '<a class="small" href="#/profil">indiquez votre série</a>';
}
// lot 1, PR 11: ONE figure for the student's bac in Mes vœux: the report's line (published), else the estimated access the zone
// reads (taux d'accès officiel x the series' proposal ratio), said; never both side by side (the audit's 34 % beside 31,2 %)
function vxVoieFigure(v, prof) {
  if (v.status !== "ok") return "—";
  if (v.rapport || !isNum(v.taux_acces_ens)) return voieFigure(v.rapport, prof);
  return `${pct1(v.taux_acces_ens)}${estimTag(`accès estimé pour votre série, sans ligne publiée dans un rapport du jury${v.rate_fragile ? " · peu de candidats de votre série" : ""}`, true)}`;
}
function vxVoieCell(v, prof) {
  return `<td class="num" data-label="Pour votre bac, cette formation">${vxVoieFigure(v, prof)}</td>`;
}
// lot 1, PR 11: « Admis sous votre moyenne » / « Admis avec votre mention ou moins » in Mes vœux = the search card's figure
// (cartePosFigure over the same reading: the average's position range, else the mention share), never another range
function vxPos(v, withAverage) {
  if (withAverage) {
    const p = v.position_moyenne;
    return p ? { lo: Math.min(p.normale, p.uniforme), hi: Math.max(p.normale, p.uniforme), moyenne: true } : null;
  }
  if (v.bounds) return { lo: v.bounds[0], hi: v.bounds[1], serie: true, moyenne: false };
  return isNum(v.position) ? { lo: v.position, hi: v.position, serie: false, moyenne: false } : null;
}
// primary (sprint Q5): the formation page's one main action is adding the formation to Mes vœux
function voeuButton(cod, primary) {
  const inV = voeux.has(cod), full = !inV && voeux.get().length >= voeux.MAX;
  return `<button type="button" data-voeu="${esc(cod)}"${primary && !inV && !full ? ' class="primary"' : ""} ${full ? `disabled title="${voeux.MAX} vœux au maximum sur Parcoursup"` : ""}>${inV ? "Retirer de mes vœux" : full ? "Mes vœux : liste pleine" : "Ajouter à mes vœux"}</button>`;
}
function bindVoeuButton(after) {
  $view.querySelectorAll("[data-voeu]").forEach((el) => {
    el.onclick = () => { voeux.has(el.dataset.voeu) ? voeux.remove(el.dataset.voeu) : voeux.add(el.dataset.voeu); after(); };
  });
}
// messages: one fixed rule each, read from the server's counts (voeux.read_list); never a combined chance
const VX_MSG = {
  aucune_securite: "Aucun vœu de sécurité sûr dans votre liste : ajoutez au moins une formation où la cohorte admise ressemble à votre profil et où le taux d'accès est élevé. La carte « Compléter ma liste », juste en dessous, en propose dans les filières de vos vœux.",
  majorite_ambitieuse: "Plus de la moitié des vœux situés sont ambitieux ou hors-profil.",
  hors_profil: "Au moins un vœu est hors-profil : moins de 2 % des admis 2022–2025 avaient votre mention ou moins.",
  non_ouvert: "Au moins un vœu n'est pas ouvert à votre série (groupes d'appel, ou presque aucun admis de votre série) : vérifiez la fiche Parcoursup.",
  non_situe: "Certains vœux ne peuvent pas être situés pour votre profil (trop peu de candidats de votre série, formation non rattachée à une filière, ou absente de la dernière campagne).",
  aucune_cible: "Aucun vœu cible pour l'instant.",
  equilibree: "Votre liste combine des vœux de sécurité et des vœux cibles ou ambitieux.",
  aucune_securite_large: `Aucun de vos vœux de sécurité n'est une « sécurité large ». Pour un vœu de secours très solide, ajoutez une formation au taux d'accès d'au moins ${ZONE_RULES.large_access} % où la plupart des admis avaient votre niveau ou moins.`,
};
const VX_PLANB = ["ambitieux", "hors_profil", "cible"];
async function viewVoeux() {
  const ids = voeux.get();
  const p = store.get("profile", { spe1: "MATHS", spe2: "SES", mention: "ab", academie: "", boursier: false });
  const prof = vxProfile(p);                                             // stored profile: never trusted
  if (isReo(prof)) return viewVoeuxReo(ids, prof);                      // sprint 21: no zone, no Plan B, no "Compléter"
  const { serie, mention } = prof;
  const who = `${{ bg: "bac général", bt: "bac technologique", bp: "bac professionnel" }[serie]}${serie === "bg" ? ` ${esc(speName(p.spe1 || "MATHS"))} + ${esc(speName(p.spe2 || "SES"))}` : prof.voie_label ? `, ${esc(prof.voie_label)}` : ""}, ${mentionWords(p)}${p.academie ? `, académie de ${esc(acadLabel(p.academie))}` : ""}`;
  const head = `<div class="card"><h1>Mes vœux ${tip("mes_voeux")}</h1>
    <p class="small">Lue pour votre profil actuel : ${who}. <a href="#/profil">Modifier dans « Mon profil »</a></p><p class="small no-print"><a href="#/guide">Construire ma liste : les 5 étapes</a> · <a href="#/projet">Préparer mes projets de formation motivés</a></p><p class="print-only small">Liste lue sur SupCompass le ${esc(frDate(localIso()))}. Chiffres officiels Parcoursup 2022–2025 : des parts d'admis, pas des chances d'admission.</p></div>`;
  const howto = `<p class="muted small">Ajoutez des formations depuis leur fiche, « Où je me situe » ou un plan B (${voeux.MAX} vœux au maximum sur Parcoursup, hors sous-vœux). Sur Parcoursup, les vœux ne sont pas classés : l'ordre de votre liste ne compte pas.</p>`;
  if (!ids.length) {
    $view.innerHTML = `${head}<div class="card"><p class="muted">Votre liste est vide.</p>${howto}</div>${APP_SECTION}${transferCard()}`;
    $view.dataset.rendered = "voeux:0";
    loadAppVoeux("voeux:0");
    bindTransfer();                                                     // Codex (PR 18): an apprenticeship-only list travels too
    return;
  }
  const qs = vxQuery(ids, prof);                                        // the profile bar sends the same query
  const marker = `voeux:${qs}`;
  $view.dataset.rendered = marker;
  $view.innerHTML = `${head}<div class="card"><p class="muted small">Lecture de votre liste…</p></div>`;
  let d;
  const recoP = recoLoad();                                          // V1: the State-label badge of each vœu
  // sprint Vitesse: the profile bar sent this very query a moment ago: its answer is read here, never asked twice
  const req = profileBar.key === qs.toString() && profileBar.req ? profileBar.req : api(`/api/voeux?${qs}`);
  try { d = voeuxLocal(await req, prof); } catch (e) {
    if ($view.dataset.rendered === marker) $view.innerHTML = `${head}<div class="warn">${esc(e.message)}</div>`;
    return;
  }
  await recoP;
  if ($view.dataset.rendered !== marker) return;                       // the user navigated meanwhile
  const L = d.lecture, z = L.zones;
  const rate = serie === "bg" ? "Taux d'accès" : "Accès estimé pour votre série";    // the Compléter table's own column (its figure)
  const avg = d.moyenne !== null && d.moyenne !== undefined;
  const posHead = avg ? "Admis sous votre moyenne" : "Admis avec votre mention ou moins";
  const rows = d.voeux.map((v) => {
    const name = v.status === "absente" ? `<span class="muted">Formation ${esc(v.cod_aff_form)} absente de la campagne ${d.session}</span>`
      : `<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a><div class="muted small">${esc(v.filiere)}${v.complement ? ` · ${esc(v.complement)}` : ""} · ${esc(v.ville)}${v.academie ? ` (${esc(acadLabel(v.academie))})` : ""}${v.home_academie ? ' · <span class="badge exact">votre académie</span>' : ""}${kmFromHome(v.lat, v.lon) ? ` · ${esc(kmFromHome(v.lat, v.lon))}` : ""}</div>${recoBadge(v.cod_aff_form)}${tensionBadge(v.cod_aff_form)}${appBadge(v.cod_aff_form)}`;
    const flags = v.status !== "ok" ? "" : `${v.rate_fragile ? ' <span class="badge warnb">peu de candidats de votre série</span>' : ""}${v.rare_for_serie ? ` <span class="badge warnb">rare pour les ${SERIE_SHORT[serie]}</span>` : ""}${v.small_cohort ? ' <span class="badge warnb">moins de 10 admis de votre bac</span>' : ""}${autresBadge(v)}`;
    return `<tr><td>${name}</td><td data-label="Zone">${zoneBadge(v.zone, v.uncertain, v.large)}${v.status === "ok" ? zoneAxisNote(v) : ""}${flags}</td>
      <td class="num" data-label="Taux d'accès officiel">${v.status === "ok" && isNum(serie === "bg" ? v.taux_acces_ens : v.taux_acces_all) ? `${fmt(serie === "bg" ? v.taux_acces_ens : v.taux_acces_all)} %` : "—"}</td>
      <td class="num" data-label="${posHead}">${v.status === "ok" ? cartePosFigure(vxPos(v, avg), false, serie) : "—"}</td>
      <td class="num" data-label="Places">${v.capa_fin != null ? fmt(v.capa_fin) : "—"}</td>
      ${serie === "bg" ? `<td class="num" data-label="Vos deux spécialités, cette formation">${dblFigure(v)}</td>` : vxVoieCell(v, prof)}
      <td class="acts">${v.status === "ok" && VX_PLANB.includes(v.zone) ? `<button type="button" class="small planb-btn" data-vxplanb="${esc(v.cod_aff_form)}" aria-expanded="false">Voir un plan B</button>` : ""}<button type="button" class="small" data-vxdel="${esc(v.cod_aff_form)}">retirer</button></td></tr>`;
  }).join("");
  $view.innerHTML = `${head}
  <section class="card summary" aria-label="Lecture de votre liste"><h2>Lecture de votre liste</h2>
    ${zoneTiles(z, z.hors_profil + z.non_ouvert + z.indetermine + z.non_situe, L.securite_large, vxCompte(d.voeux) === d.voeux.length ? "vœu" : "formation")}
    ${zoneLegend()}
    ${L.messages.map((m) => `<div class="${m.niveau === "warn" ? "warn" : "info"}${m.code === "aucune_securite" ? " vx-alert" : ""}">${esc(VX_MSG[m.code] || "")}</div>`).join("")}
    <p class="muted small">Ces repères comptent les zones de votre liste, une par formation. Ils ne disent pas vos chances d'être admis quelque part : les zones décrivent les admis des campagnes passées, et vos vœux ne se combinent pas en une probabilité.</p></section>
  <div class="card"><h2>${vxTitre(d.voeux)}</h2>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th>Zone pour votre profil</th><th class="num">Taux d'accès officiel ${d.session}</th><th class="num">${posHead}</th><th class="num">Places ${d.session}</th>${serie === "bg" ? '<th class="num">Vos deux spécialités (cette formation)</th>' : '<th class="num">Pour votre bac (cette formation)</th>'}<th><span class="sr-only">Actions</span></th></tr>
    ${rows}</table></div>
    <p class="muted small">Parts d'admis des campagnes 2022–2025, pas des chances d'admission. Taux d'accès officiel de la dernière campagne, tous candidats. Vérifiez chaque fiche Parcoursup.${serie === "bg" ? " Vos deux spécialités : le rapport public de la formation quand il les détaille ; sinon une estimation (son taux des bacheliers généraux × l'écart de vos deux spécialités dans les rapports des formations semblables, ou à défaut dans son groupe au niveau national)." : " Pour votre bac : la part des candidats de votre série et spécialités (ou de votre spécialité de bac pro) ayant confirmé ce vœu qui ont été classés assez haut pour recevoir une proposition, d'après le rapport public de la formation (seuls les candidats scolarisés en terminale en France y figurent) ; sans rapport, une estimation : le taux d'accès officiel × le taux de proposition de votre série / celui de tous les candidats. Jamais les deux à la fois."}</p>
    <p class="muted small">Votre liste reste dans ce navigateur. Pour la lire, la page envoie les codes des formations et votre profil, comme « Où je me situe », sauf votre moyenne : elle reste dans ce navigateur, qui la place lui-même dans votre mention ; rien n'en est enregistré sur le serveur. Le site compte seulement, sans savoir de quelle formation il s'agit, qu'un vœu a été ajouté (mesure d'audience anonyme, désactivée si votre navigateur demande de ne pas être suivi).</p>${howto}</div>${APP_SECTION}<section class="card" id="vx-verifier"><p class="muted small">Vérification de votre liste…</p></section><section class="card" id="vx-jpo"><p class="muted small">Portes ouvertes de votre liste…</p></section>${robVoeuxCard(d.voeux, (v) => (v.status === "ok" ? zoneBadge(v.zone, v.uncertain, v.large) : "—"))}${shareCard(ids, !!store.get("profile", null))}${transferCard()}${nextSteps("voeux")}${feedbackBox("voeux")}`;
  if (L.messages.some((m) => m.code === "aucune_securite")) {
    // audit PR 5: right under the « aucune sécurité » alert (it was below the whole list, out of sight on a phone)
    $view.querySelector("section.summary").insertAdjacentHTML("afterend", '<section class="card" id="vx-completer" aria-live="polite"><p class="muted small">Recherche de vœux de sécurité dans les filières de votre liste…</p></section>');
    loadCompleter(qs, marker, rate, false, prof);
  }
  loadVerifier(ids, marker, { noms: Object.fromEntries(d.voeux.filter((v) => v.status !== "absente").map((v) => [v.cod_aff_form, v.etablissement])),
    securite: L.messages.some((m) => m.code === "aucune_securite") ? "aucune" : "ok" });
  loadJpoListe(ids, marker);
  loadAppVoeux(marker);                                                 // PR 18: the separate apprenticeship list
  $view.querySelectorAll("[data-vxdel]").forEach((el) => { el.onclick = () => { voeux.remove(el.dataset.vxdel); viewVoeux(); }; });
  bindShare(ids, store.get("profile", null) ? prof : null);             // sprint 22: never a default profile (review)
  bindTransfer();                                                       // PR 17: the same person, on another device
  $view.querySelectorAll("[data-vxplanb]").forEach((el) => {
    el.onclick = () => {
      const tr = el.closest("tr");
      const open = tr.nextElementSibling && tr.nextElementSibling.classList.contains("planb-row");
      if (open) { tr.nextElementSibling.remove(); el.textContent = "Voir un plan B"; el.setAttribute("aria-expanded", "false"); return; }
      const row = document.createElement("tr");
      row.className = "planb-row";
      row.innerHTML = `<td colspan="${tr.children.length}"><div class="planb-inline" aria-live="polite"></div></td>`;
      tr.after(row);
      el.textContent = "Masquer le plan B";
      el.setAttribute("aria-expanded", "true");
      track("action", { a: "planb" });
      loadPlanB(el.dataset.vxplanb, { box: row.querySelector(".planb-inline"), profile: prof, inline: true, onPin: (a) => {
        if (voeux.add(a.cod_aff_form)) viewVoeux();
        else alert(`${voeux.MAX} vœux au maximum : retirez un vœu d'abord.`);
      } });
    };
  });
}

// ---- PR 18 (owner, 2026-11-28): « Mes vœux en apprentissage » ----
// The separate list (voeuxApp) read by /api/apprentissage/voeux (codes only, no-store, no event): each offer with its Parcoursup
// page and the initial formation of the same establishment, NO zone and NO rate (none is published), never a safety; Parcoursup's
// own rules from the official calendar (« 10 vœux supplémentaires », still possible after the last day), the contract and the
// minimum pay quoted from service-public.gouv.fr.
const APP_SECTION = '<section class="card" id="vx-app" aria-live="polite"></section>';
async function loadAppVoeux(marker) {
  const box = () => document.getElementById("vx-app");
  const ids = voeuxApp.get();
  if (!box()) return;
  if (!ids.length) {
    box().innerHTML = `<h2>Mes vœux en apprentissage</h2><p class="muted small">Aucune formation en apprentissage dans cette liste à part. Ajoutez-en depuis la recherche (filtre « Apprentissage ») ou depuis la carte « Et en apprentissage ? » d'une fiche formation.</p>`;
    return;
  }
  box().innerHTML = '<h2>Mes vœux en apprentissage</h2><p class="muted small">Lecture de vos vœux en apprentissage…</p>';
  let d, cal;
  try {
    [d, cal] = await Promise.all([api(`/api/apprentissage/voeux?${new URLSearchParams({ ids: ids.join(",") })}`), api("/api/calendrier").catch(() => null)]);
  } catch (e) {
    if ($view.dataset.rendered === marker && box()) box().innerHTML = `<h2>Mes vœux en apprentissage</h2><div class="warn">${esc(e.message)}</div>`;
    return;
  }
  if ($view.dataset.rendered !== marker || !box()) return;              // the student left meanwhile
  box().innerHTML = appVoeuxCard(d, cal);
  box().querySelectorAll("[data-appdel]").forEach((el) => { el.onclick = () => { voeuxApp.remove(el.dataset.appdel); transferRefresh(); loadAppVoeux(marker); }; });
}
function appVoeuxCard(d, cal) {
  const R = (cal && cal.regles) || {}, n = d.voeux.length;
  const max = Number.isInteger(R.apprentissage_max) ? R.apprentissage_max : null;
  const fin = listeDate(cal, "fin_voeux");
  const rule = max !== null ? `Le calendrier officiel le dit : en plus de vos vœux, « il est également possible d'ajouter ${fmt(max)} vœux supplémentaires pour des formations en apprentissage ».${R.apprentissage_apres ? ` Pour ces formations, vous pouvez encore formuler des vœux après le dernier jour des autres vœux${fin ? ` (${esc(frDate(fin))})` : ""}.` : ""}`
    : "Le nombre de vœux en apprentissage permis par Parcoursup n'a pas pu être lu : vérifiez-le sur parcoursup.gouv.fr.";
  const rows = d.voeux.map((v) => {
    if (v.status !== "ok") return `<tr><td data-label="Formation"><span class="muted">Formation ${esc(v.cod_aff_form)} absente de la carte des formations ${esc(d.carte_session || "")} : vérifiez sur Parcoursup qu'elle existe toujours.</span></td><td data-label="Même formation sans apprentissage">—</td><td class="acts"><button type="button" class="small" data-appdel="${esc(v.cod_aff_form)}">retirer</button></td></tr>`;
    const url = carteFiche(v), km = kmFromHome(v.lat, v.lon);
    const ini = (v.rattachee || []).filter((x) => /^\d{1,9}$/.test(x.cod_aff_form || ""));
    return `<tr><td data-label="Formation">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(v.etablissement)} ↗</a>` : esc(v.etablissement)}
        <div class="muted small">${esc(v.formation)}${appParcours(v) ? ` · ${appParcours(v)}` : ""} · ${esc(v.ville)}${v.academie ? ` (${esc(acadLabel(v.academie))})` : ""}${km ? ` · ${esc(km)}` : ""}</div><span class="badge">en apprentissage</span></td>
      <td data-label="Même formation sans apprentissage">${ini.length ? ini.map((x) => `<a href="#/f/${esc(x.cod_aff_form)}">${esc(x.etablissement || x.formation || "Fiche de la formation")}</a>`).join("<br>") : '<span class="muted small">Aucune ici</span>'}</td>
      <td class="acts"><button type="button" class="small" data-appdel="${esc(v.cod_aff_form)}">retirer</button></td></tr>`;
  }).join("");
  return `<h2>Mes vœux en apprentissage (${fmt(n)})</h2>
    <p class="small">${rule}</p>
    <p class="small">Ces offres ne publient aucune statistique d'admission. Elles n'ont donc ni zone ni taux, et ne comptent jamais comme vœu de sécurité dans la lecture de votre liste. Pour entrer en formation, il faut aussi signer un contrat d'apprentissage avec un employeur.</p>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation en apprentissage</th><th>Même formation sans apprentissage</th><th><span class="sr-only">Actions</span></th></tr>${rows}</table></div>
    <p class="muted small">Chaque offre a sa propre fiche Parcoursup : elle fait foi. Cette liste reste dans ce navigateur. Pour la lire, la page envoie seulement les codes de ces offres, et rien n'en est enregistré.</p>
    ${appOfficiel(d.officiel, false)}
    <p class="small"><a href="${esc(d.liens.entreprises)}" target="_blank" rel="noopener">Trouver une entreprise qui recrute des apprentis (La bonne alternance) ↗</a></p>`;
}

// ---- sprint 5 (owner, 2026-11-21): « Vérifier et confirmer ma liste » ----
// Before the Parcoursup deadlines, what SupCompass can check on the list (liste.py, /api/liste/verifier: the list's codes only,
// no-store, no event) and the rules and dates of the OFFICIAL calendar (/api/calendrier: `regles` and the dated steps, each served
// only when every version of the PDF agrees). Never « votre liste est valide »: SupCompass does not see the Parcoursup file.
function listeDate(cal, key) {
  const e = cal && (cal.evenements || []).find((x) => x.key === key);
  return e && e.verifie && typeof e.debut === "string" && /^\d{4}-\d{2}-\d{2}$/.test(e.debut) ? e.debut : null;
}
function listeJours(iso, today) {
  const d = Math.round((Date.parse(`${iso}T12:00:00`) - Date.parse(`${today}T12:00:00`)) / 86400000);
  return d > 1 ? `dans ${fmt(d)} jours` : d === 1 ? "demain" : d === 0 ? "aujourd'hui" : "date passée";
}
// audit PR 7 (2026-11-25): the vœu multiple a fiche names (multiples.py). Its sub-wishes count ONCE among the vœux; the key is
// the name AND the formation line of the same fiche campaign (twin of multiples.compte)
const vmKey = (g) => (g && typeof g.nom === "string" && typeof g.formation === "string" ? `${g.session}|${g.nom}|${g.formation}` : null);
function vxCompte(voeux) {
  const seen = new Set();
  let n = 0;
  for (const v of voeux || []) {
    const k = vmKey(v.voeu_multiple);
    if (k === null || !seen.has(k)) n += 1;
    if (k !== null) seen.add(k);
  }
  return n;
}
// audit PR 8: ONE wording of a list's size, everywhere a page counts it (reading, heading, « Avant de confirmer »): the
// formations, then the Parcoursup vœux they make when some are sub-wishes of the same vœu multiple
function vxCompteTxt(n, nVx) {
  return nVx === n ? `${fmt(n)} vœu${n > 1 ? "x" : ""}` : `${fmt(n)} formations, soit ${fmt(nVx)} vœu${nVx > 1 ? "x" : ""} sur Parcoursup`;
}
function vxTitre(voeux) {
  const n = (voeux || []).length, nVx = vxCompte(voeux);
  return nVx === n ? `Mes ${fmt(n)} vœu${n > 1 ? "x" : ""}` : `Mes ${fmt(n)} formations (${fmt(nVx)} vœu${nVx > 1 ? "x" : ""} sur Parcoursup)`;
}
function vmNote(g) {
  if (!vmKey(g)) return "";
  return `<p class="small vm-note">Sur Parcoursup, cette formation est un sous-vœu du vœu multiple «&nbsp;${esc(g.nom)}&nbsp;» (${fmt(g.n_formations)} formations, nom écrit sur sa fiche) : avec les autres formations de ce vœu, elle compte pour un seul vœu.</p>`;
}
function verifierCard(ids, f, cal, opts) {
  if (!f || !Array.isArray(f.voeux)) return "";
  const R = (cal && cal.regles) || {}, noms = opts.noms || {}, today = opts.today || localIso();
  const nom = (c) => `« ${esc(noms[c] || `formation ${c}`)} »`;
  const ok = '<span class="vf-st vf-ok">Fait</span>', look = '<span class="vf-st vf-look">À vérifier</span>', info = '<span class="vf-st vf-info">À savoir</span>';
  const li = (st, html) => `<li>${st}<div>${html}</div></li>`;
  const items = [];
  const n = f.voeux.length, app = f.voeux.filter((v) => v.apprentissage), nApp = vxCompte(app);
  const nVx = vxCompte(f.voeux), nSco = vxCompte(f.voeux.filter((v) => !v.apprentissage));
  const max = Number.isInteger(R.voeux_max) ? R.voeux_max : null, maxApp = Number.isInteger(R.apprentissage_max) ? R.apprentissage_max : null;
  const compte = vxCompteTxt(n, nVx);
  items.push(li(max !== null && nSco <= max ? ok : info, `Votre liste compte ${compte}${nApp ? `, dont ${fmt(nApp)} en apprentissage` : ""}. ${max !== null
    ? `Parcoursup accepte jusqu'à ${fmt(max)} vœux, sans les classer.` : "Vérifiez le nombre de vœux permis sur parcoursup.gouv.fr."}${maxApp !== null
    ? ` Vous pouvez ajouter jusqu'à ${fmt(maxApp)} vœux en apprentissage en plus.` : ""}`));
  // the vœux multiples the fiches name: one line per group of the list, its formations named
  const vms = [];
  for (const v of f.voeux) {
    const k = vmKey(v.voeu_multiple);
    if (k === null) continue;
    const g = vms.find((x) => x.k === k);
    if (g) g.v.push(v); else vms.push({ k, g: v.voeu_multiple, v: [v] });
  }
  for (const x of vms) {
    items.push(li(info, x.v.length > 1
      ? `${x.v.map((v) => nom(v.cod_aff_form)).join(", ")}&nbsp;: sous-vœux du même vœu multiple «&nbsp;${esc(x.g.nom)}&nbsp;» (nom écrit sur leurs fiches Parcoursup). Ensemble, ils comptent pour un seul vœu. Parcoursup limite aussi le nombre de sous-vœux&nbsp;: vérifiez sur parcoursup.gouv.fr.`
      : `${nom(x.v[0].cod_aff_form)}&nbsp;: sous-vœu du vœu multiple «&nbsp;${esc(x.g.nom)}&nbsp;» (${fmt(x.g.n_formations)} formations, nom écrit sur sa fiche Parcoursup). Les autres formations de ce vœu compteraient avec elle pour un seul vœu.`));
  }
  const conc = f.voeux.filter((v) => typeof v.concours === "string" && v.concours && vmKey(v.voeu_multiple) === null);
  if (conc.length) {
    // Codex (PR #99): formations of DIFFERENT concours never share a vœu: one line per NAMED concours; « Concours commun » names
    // no concours, so each of those formations stands alone
    const groups = [];
    for (const v of conc) {
      const g = v.concours !== "Concours commun" && groups.find((x) => x.nom === v.concours);
      if (g) g.v.push(v); else groups.push({ nom: v.concours, v: [v] });
    }
    for (const g of groups) {
      const k = g.v.length > 1;
      items.push(li(look, `${g.v.map((v) => nom(v.cod_aff_form)).join(", ")} (${esc(g.nom)})&nbsp;: ${k
        ? "ces formations recrutent par le même concours. Sur Parcoursup, elles peuvent compter comme sous-vœux d'un même vœu. Vérifiez sur leurs fiches."
        : "cette formation recrute par un concours commun. Sur Parcoursup, elle peut compter comme sous-vœu d'un vœu multiple. Vérifiez sur sa fiche."}`));
    }
  } else if (R.sous_voeux === true && !vms.length) {
    items.push(li(info, "Pour certaines formations, Parcoursup permet aussi des sous-vœux. La fiche de chaque formation le précise."));
  }
  const gone = f.voeux.filter((v) => v.dans_carte === false);
  if (gone.length) {
    items.push(li(look, `${gone.map((v) => nom(v.cod_aff_form)).join(", ")}&nbsp;: absente${gone.length > 1 ? "s" : ""} de la carte des formations Parcoursup ${esc(f.carte_session || "")}. Vérifiez sur Parcoursup qu'${gone.length > 1 ? "elles existent" : "elle existe"} toujours.`));
  } else if (f.carte_session) {
    items.push(li(ok, `Tous vos vœux figurent dans la carte des formations Parcoursup ${esc(f.carte_session)}.`));
  }
  if (opts.securite === "aucune") items.push(li(look, "Aucun vœu de votre liste n'est une sécurité sûre pour votre profil. Voyez « Compléter ma liste » sur cette page."));
  else if (opts.securite === "ok") items.push(li(ok, "Votre liste contient au moins une sécurité sûre pour votre profil."));
  const P = projetLoad(), nDraft = ids.filter((c) => P[c] && P[c].brouillon).length;
  const unit = nVx === n ? ["vœu", "vœux"] : ["formation", "formations"];   // audit PR 7: a list with sub-wishes counts formations here
  items.push(li(nDraft === n ? ok : look, `${fmt(nDraft)} ${unit[nDraft > 1 ? 1 : 0]} sur ${fmt(n)} ${nDraft > 1 ? "ont" : "a"} un brouillon de projet de formation motivé. <a href="#/projet">Préparer mes projets</a>`));
  const fin = listeDate(cal, "fin_voeux"), conf = listeDate(cal, "confirmation");
  const jour = (iso) => frDate(iso).replace(/^(\S+) 1 /, "$1 1er ");          // « jeudi 1er avril », as the calendar prints it
  const when = (iso) => (iso ? `<strong>${esc(jour(iso))}</strong> (${esc(listeJours(iso, today))})` : "date à vérifier sur parcoursup.gouv.fr");
  items.push(li(info, `Dernier jour pour formuler vos vœux&nbsp;: ${when(fin)}.${R.apprentissage_apres === true ? " En apprentissage, vous pourrez encore en formuler ensuite." : ""}`));
  items.push(li(info, `Dernier jour pour compléter votre dossier et confirmer vos vœux&nbsp;: ${when(conf)}. Un vœu se confirme sur Parcoursup, pas ici.${fin || conf ? ' <a href="/api/calendrier.ics">Ajouter ces dates à mon agenda</a>' : ""}`));
  return `<section class="card" id="vx-verifier"><h2>Avant de confirmer sur Parcoursup</h2>
    <ul class="vf-list">${items.join("")}</ul>
    <p class="muted small">SupCompass ne voit pas votre dossier Parcoursup&nbsp;: ces repères ne remplacent pas la confirmation de chaque vœu. Règles et dates lues sur le calendrier officiel Parcoursup${cal && cal.campagne ? ` ${esc(cal.campagne)}` : ""}, qui fait foi.</p></section>`;
}
async function loadVerifier(ids, marker, opts) {
  const box = $view.querySelector("#vx-verifier");
  let f, cal;
  try {
    [f, cal] = await Promise.all([api(`/api/liste/verifier?${new URLSearchParams({ ids: ids.join(",") })}`), api("/api/calendrier").catch(() => null)]);
  } catch (e) {
    if ($view.dataset.rendered === marker && box && box.isConnected) box.remove();
    return;
  }
  if ($view.dataset.rendered !== marker || !box || !box.isConnected) return;   // the student left or changed the list meanwhile
  box.outerHTML = verifierCard(ids, f, cal, opts);
}

// "Compléter ma liste" (owner, 2026-11-10): with no sure safety in the list, safety vœux of the same filières, read by the
// server with Plan B's rules (same programme, a solid reading, 2 per establishment, académie then distance, paid private
// institutions only on request and flagged). Zones of past admitted cohorts: never a chance.
let vxCompleterSeq = 0;
async function loadCompleter(qs, marker, rate, paid, prof) {
  const box = () => document.getElementById("vx-completer");
  // Codex (PR #44): the paid toggle can fire twice before the first answer; only the LATEST request may draw the card
  const req = String(++vxCompleterSeq);
  if (box()) box().dataset.req = req;
  const current = () => $view.dataset.rendered === marker && box() && box().dataset.req === req;
  const q = new URLSearchParams(qs);
  q.set("paid", paid ? "1" : "0");
  const local = lectureOf(prof).g !== null;                            // R6: the page read the list itself: every candidate, read here
  if (local) q.set("pool", "true");
  let d;
  try { d = await api(`/api/voeux/completer?${q}`); if (local) d = completerLocal(d, prof, prof.academie || null); } catch (e) {
    if (current()) box().innerHTML = `<p class="muted small">Suggestions indisponibles pour le moment.</p>`;
    return;
  }
  if (!current()) return;                     // the user navigated, changed the list or toggled again meanwhile
  if (!d.needed) { box().remove(); return; }
  const full = voeux.get().length >= voeux.MAX;
  const groups = d.filieres.map((g) => {
    const title = `${g.fili ? `${esc(g.fili)} · ` : ""}${esc(g.filiere)}`;
    if (!g.formations.length) return `<h3>${title}</h3><p class="muted small">Aucune formation de cette filière n'est en zone sécurité sans incertitude pour votre profil, d'après les admis des campagnes passées.</p>`;
    const rows = g.formations.map((f) => {
      const pos = f.bounds ? (f.bounds[1] - f.bounds[0] < 0.005 ? pc1(f.bounds[0]) : `${pc1(f.bounds[0])} – ${pc1(f.bounds[1])}`) : pc1(f.position);
      return `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${f.complement ? `${esc(f.complement)} · ` : ""}${esc(f.ville)}${f.academie ? ` (${esc(acadLabel(f.academie))})` : ""}${f.paid ? ' · <span class="badge warnb">privé payant</span>' : ""}</div></td>
        <td data-label="Zone">${zoneBadge("securite", false, f.large)}</td>
        <td class="num" data-label="${rate}">${fmt(f.taux_acces_ens)} %</td>
        <td class="num" data-label="Votre position parmi les admis">${pos}</td>
        <td class="num" data-label="Distance au plus proche de vos vœux">${f.km != null ? `${fmt(f.km)} km` : "—"}</td>
        <td class="acts"><button type="button" class="small" data-vxadd="${esc(f.cod_aff_form)}"${full ? " disabled" : ""}>ajouter à mes vœux</button></td></tr>`;
    }).join("");
    return `<h3>${title}</h3><div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th>Zone pour votre profil</th><th class="num">${rate} ${d.session}</th><th class="num">Votre position parmi les admis</th><th class="num">Distance</th><th><span class="sr-only">Actions</span></th></tr>${rows}</table></div>`;
  }).join("");
  const paidBox = d.include_paid || d.hidden_paid ? `<label class="small"><input type="checkbox" id="vx-paid"${d.include_paid ? " checked" : ""}> Montrer aussi les établissements privés payants${d.include_paid ? "" : ` (${fmt(d.hidden_paid)} écartés)`}</label>` : "";
  box().innerHTML = `<h2>Compléter ma liste : des vœux de sécurité possibles</h2>
    <p class="small">Dans les filières de vos vœux, des formations où votre profil se situe en zone sécurité sans incertitude : la cohorte admise ressemble à votre profil et le taux d'accès est élevé.</p>
    ${groups}${paidBox}
    <p class="muted small">Ce sont des repères tirés des admis des campagnes 2022–2025, pas des chances d'admission ; vérifiez chaque fiche Parcoursup. Mêmes règles que le plan B : une lecture solide seulement, deux formations au plus par établissement, votre académie d'abord, puis la distance au plus proche de vos vœux de la filière.${full ? ` Votre liste compte déjà ${voeux.MAX} vœux : retirez-en un pour en ajouter un autre.` : ""}</p>`;
  box().querySelectorAll("[data-vxadd]").forEach((el) => {
    el.onclick = () => { if (voeux.add(el.dataset.vxadd)) viewVoeux(); };
  });
  const cb = document.getElementById("vx-paid");
  if (cb) cb.onchange = () => loadCompleter(qs, marker, rate, cb.checked, prof);
}

// ---- Sprint 12: "Du métier aux formations" (the jobs card read backwards; the catalogue is searched here) ----
// The search is a pure function (the red team runs it with Node on real queries): every word of the query must
// start a word of one of the job's labels (name, masculine / feminine forms, synonyms), accents and case aside.
const mfold = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
function metierMatch(q, nom, labels) {
  // every word found: 10 + bonuses; otherwise the number of words found (a close match, ranked below):
  // "développeur web" still shows "développeur informatique" when no job has both words
  const words = mfold(q).split(" ").filter((w) => w.length > 1);
  if (!words.length) return 0;
  let best = 0;
  [nom, ...(labels || [])].forEach((lab, i) => {
    const lw = mfold(lab).split(" ");
    const found = words.filter((w) => lw.some((x) => x.startsWith(w))).length;
    const first = lw.some((x) => x.startsWith(words[0])) ? 0.5 : 0;   // a close match keeping the first word typed comes first
    const score = found === words.length ? 10 + (i === 0 ? 2 : 0) + (lw[0].startsWith(words[0]) ? 1 : 0) : found + first;
    if (score > best) best = score;
  });
  return best;
}
let METIERS = null;
const MT_ACCES = { direct: "accessible avec ce diplôme", poursuite: "après une poursuite d'études" };
async function viewMetiers(id, from = "") {
  if (id) return viewMetier(id, /^\d{1,9}$/.test(from) ? from : "");
  if (!METIERS) {
    // first visit: the catalogue may arrive after the user went elsewhere (Codex): only this view may still be filled
    $view.dataset.rendered = "metiers:loading";
    const cat = await api("/api/metiers");
    METIERS = METIERS || cat;
    if ($view.dataset.rendered !== "metiers:loading") return;
  }
  let q0 = "";
  try { q0 = sessionStorage.getItem("metierQ") || ""; } catch (_) { /* storage blocked: start empty (Codex) */ }
  $view.innerHTML = `${explorerViews("metiers")}<div class="card"><h1>Du métier aux formations ${tip("du_metier_aux_formations")}</h1>
    <p class="small">Cherchez un métier : la page montre les diplômes qui y mènent d'après l'Onisep, puis les formations Parcoursup qui les préparent.</p>
    <input id="mq" class="wide" type="search" placeholder="Ex. infirmière, comptable, développeur web…" value="${esc(q0)}" autocomplete="off" aria-label="Métier recherché">
    <p class="muted small">La recherche se fait dans votre navigateur : ce que vous tapez n'est pas envoyé au site. ${fmt(METIERS.rows.length)} métiers des fiches Onisep.</p>
    <div id="mres"></div></div>`;
  $view.dataset.rendered = "metiers";
  const box = document.getElementById("mres"), input = document.getElementById("mq");
  const run = () => {
    const q = input.value;
    try { sessionStorage.setItem("metierQ", q); } catch (_) { /* storage blocked */ }
    const hits = METIERS.rows.map((r) => [metierMatch(q, r[1], r[5]), r]).filter(([s]) => s > 0)
      .sort((a, b) => b[0] - a[0] || a[1][1].length - b[1][1].length || a[1][1].localeCompare(b[1][1], "fr")).slice(0, 30);
    const close = hits.length && hits[0][0] < 10;               // no job has every word: closest ones, said so
    box.innerHTML = !mfold(q) ? "" : !hits.length ? `<p class="muted">Aucun métier trouvé.</p>`
      : `${close ? `<p class="muted small">Aucun métier ne contient tous ces mots : voici les plus proches.</p>` : ""}<ul class="small">${hits.filter(([sc]) => close || sc >= 10).map(([, r]) => `<li><a href="#/metiers/${esc(r[0])}">${esc(r[1])}</a> <span class="muted">· ${r[4] ? `${fmt(r[4])} formation(s) Parcoursup` : r[3] ? "diplômes hors Parcoursup (écoles, ou après un premier diplôme)" : "aucun diplôme relié par l'Onisep"}${r[2] ? ` · niveau minimum ${esc(r[2])}` : ""}</span></li>`).join("")}</ul>`;
  };
  input.oninput = run;
  run();
  input.focus();
}
// owner, 2026-11-14: the route from the bac to the job (parcours.py), inside the Sprint 12 block (red team M6 reads it whole).
// Entries are GROUPS of Parcoursup formations (a diploma, a programme), ranked by their places in the latest campaign; the first
// ones that gather 80 % of them are open, the others folded. Places are a proxy: no open data counts who reached a job by which
// route. A job that needs no higher studies says so and links the Onisep sheet of its diploma (outside Parcoursup).
const PA_HOW = { direct: "le diplôme se prépare directement sur Parcoursup", graphe: "chaîne des poursuites d'études de l'Onisep",
  regle: "voie d'accès officielle de ce type de diplôme", nom: "voie d'accès officielle, d'après le nom du métier", voisin: "voie d'un métier proche (Onisep)" };
function paRoute(r, d) {
  const e = r.entree_info || {};
  const steps = (r.etapes || []).map((s) => `<span class="pa-step">${esc(s.libelle)}${s.niveau ? ` <span class="muted">(${esc(s.niveau)})</span>` : ""}</span>`);
  // the entry's own formations, exactly the group its count and places count (Codex: a search on its label found only part)
  const prof = store.get("profile", {}) || {};
  const home = typeof prof.academie === "string" ? prof.academie : "";
  const rows = (r.formations || []).slice().sort((a, b) => (b[3] === home) - (a[3] === home));
  const list = rows.length ? `<details class="dip pa-forms"><summary>Voir ${rows.length < e.n_formations ? `${fmt(rows.length)} des ${fmt(e.n_formations)}` : `les ${fmt(rows.length)}`} formation${rows.length > 1 ? "s" : ""}${home ? ` (votre académie d'abord)` : ""}</summary>
    <ul class="small pa-flist">${rows.map(([cod, etab, ville, acad, places, lib]) => `<li><a href="#/f/${esc(cod)}">${esc(etab)}</a>${lib ? ` · ${esc(lib)}` : ""} · ${esc(ville || "")}${acad ? ` (${esc(acadLabel(acad))})` : ""}${places != null ? ` · ${fmt(places)} places` : ""}</li>`).join("")}</ul></details>` : "";
  return `<li class="pa-route"><div class="pa-chain"><strong class="pa-entry">${esc(e.libelle || "")}</strong>${steps.length ? ` <span aria-hidden="true">→</span> ${steps.join(' <span aria-hidden="true">→</span> ')}` : ""}</div>
    <div class="muted small">${fmt(e.n_formations)} formation${e.n_formations > 1 ? "s" : ""} sur Parcoursup ${esc(d.session)} · ${fmt(e.places)} places · ${esc(PA_HOW[r.comment] || "")}</div>${list}</li>`;
}
function parcoursCard(p, d) {
  if (!p) return "";
  const main = (p.routes || []).filter((r) => r.principale), rest = (p.routes || []).filter((r) => !r.principale);
  const PA_CIBLES = 3;                                                 // the first diplomas, the others counted
  const allC = p.cibles || [];
  const cibles = allC.slice(0, PA_CIBLES).map((c) => `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.libelle)} ↗</a>${c.niveau ? ` <span class="muted">(${esc(c.niveau)})</span>` : ""}`).join(" · ")
    + (allC.length > PA_CIBLES ? ` et ${fmt(allC.length - PA_CIBLES)} autre${allC.length - PA_CIBLES > 1 ? "s" : ""} (liste plus bas)` : "");
  let head;
  if (p.statut === "sans_postbac") {
    head = `<div class="info"><p><strong>Ce métier ne demande pas d'études après le bac.</strong> Il s'apprend avec un diplôme comme : ${cibles || "voir la fiche Onisep du métier"}. Ces diplômes se préparent hors de Parcoursup (lycée professionnel, apprentissage, CFA).</p></div>`;
  } else if (p.statut === "hors_parcoursup") {
    head = `<div class="info"><p><strong>Pas de voie Parcoursup identifiée pour ce métier.</strong> On y accède le plus souvent par un concours, un doctorat ou une école recrutant après un premier diplôme.${cibles ? ` Diplômes cités par l'Onisep : ${cibles}.` : ""}</p></div>`;
  } else {
    head = `<p class="small">Les études commencent sur Parcoursup par une de ces voies, puis passent par les étapes indiquées.${cibles ? ` Diplôme visé : ${cibles}.` : ""}</p>`;
  }
  const voisins = (p.voisins || []).length ? `<p class="small muted">L'Onisep ne relie aucun diplôme à ce métier : ces voies sont celles de métiers proches (${p.voisins.map((v) => `<a href="#/metier/${esc(v.id)}">${esc(v.nom || v.id)}</a>`).join(", ")}).</p>` : "";
  const routes = main.length ? `${p.statut === "sans_postbac" ? `<h3>Pour aller plus loin après le bac</h3>` : `<h3>Les voies principales</h3>`}<ul class="pa-list">${main.map((r) => paRoute(r, d)).join("")}</ul>` : "";
  const more = rest.length ? `<details class="dip"><summary>Autres voies (${fmt(rest.length)})</summary><ul class="pa-list">${rest.map((r) => paRoute(r, d)).join("")}</ul></details>` : "";
  const regles = (p.regles || []).map((g) => `<li>${esc(g.texte)}</li>`).join("");
  const acces = p.acces ? `<details class="dip"><summary>Ce que dit l'Onisep sur l'accès au métier</summary>${p.acces.split("\n").map((x) => `<p class="small">${esc(x)}</p>`).join("")}<p class="muted small">Source : Onisep, Idéo (licence ODbL).</p></details>` : "";
  const m = p.mesure;
  return `<div class="card pa-card"><h2>Le chemin vers ce métier</h2>${head}${voisins}${routes}${more}
    ${regles ? `<ul class="small pa-rules">${regles}</ul>` : ""}${acces}
    ${(p.routes || []).length ? `<p class="muted small">Les voies sont rangées par nombre de places sur Parcoursup ${esc(d.session)} : les premières regroupent 80 % des places. Ce n'est pas le nombre de personnes qui exercent ce métier après chaque voie, que personne ne publie.${m && m.couverture != null ? ` Une voie Parcoursup est trouvée pour ${fmt(100 * m.couverture)} % des ${fmt(m.a_besoin)} métiers qui demandent des études supérieures.` : ""}</p>` : ""}</div>`;
}
async function viewMetier(id, from = "") {
  const marker = `metier:${id}:${from}`;
  $view.dataset.rendered = marker;
  let d;
  try { d = await api(`/api/metier/${encodeURIComponent(id)}`); } catch (e) {
    if ($view.dataset.rendered === marker) $view.innerHTML = `<div class="warn">${esc(e.message)}</div>`;
    return;
  }
  if ($view.dataset.rendered !== marker) return;                       // the user navigated meanwhile
  const p = store.get("profile", {}) || {};
  const home = typeof p.academie === "string" ? p.academie : "";
  const onlyHome = !!home && store.get("metierHome", false);           // the académie stays in the browser
  const dip = (x) => {
    // the formation the student came from is always shown, first (its page links here), whatever the filter or the cap
    const mine = x.formations.filter((f) => f.cod_aff_form === from);
    const rest = (onlyHome ? x.formations.filter((f) => f.academie === home) : x.formations).filter((f) => f.cod_aff_form !== from);
    const rows = [...mine, ...rest];
    const shown = rows.slice(0, 40 + mine.length);
    const forms = !x.parcoursup ? `<p class="muted small">Diplôme hors Parcoursup (il se prépare après un premier diplôme, ou dans une école) : pas de formation listée ici.</p>`
      : !rows.length ? `<p class="muted small">Aucune formation de ce diplôme dans votre académie.</p>`
      : `<div class="scroll"><table><tr><th>Formation ${d.session}</th><th class="num">Taux d'accès</th><th class="num">Places</th><th><span class="sr-only">Actions</span></th></tr>
        ${shown.map((f) => `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a>${f.cod_aff_form === from ? ' <span class="badge exact">la formation que vous regardiez</span>' : ""}<div class="muted small">${esc(f.filiere)}${f.complement ? ` · ${esc(f.complement)}` : ""} · ${esc(f.ville)}${f.academie ? ` (${esc(acadLabel(f.academie))})` : ""}</div></td>
          <td class="num">${f.taux_acces_ens != null ? `${fmt(f.taux_acces_ens)} %` : "—"}</td><td class="num">${f.capa_fin != null ? fmt(f.capa_fin) : "—"}</td><td>${voeuButton(f.cod_aff_form)}</td></tr>`).join("")}</table></div>
        ${rows.length > shown.length ? `<p class="muted small">${fmt(shown.length)} formations affichées sur ${fmt(rows.length)}${home && !onlyHome ? " : cochez « mon académie seulement » pour resserrer" : ""}.</p>` : ""}`;
    // lot 2: one folded block per diploma (open when it holds the formation the student came from)
    const open = !!mine.length || d.diplomes.length === 1;
    return `<details class="dip"${open ? " open" : ""}><summary><span class="dip-title">${esc(x.libelle)}</span>
      <span class="muted small">${esc(x.niveau || "niveau non précisé")}${x.parcoursup ? ` · ${fmt(x.formations.length)} formation(s) Parcoursup` : " · hors Parcoursup"}</span></summary>
      <p class="small"><a href="${esc(x.url)}" target="_blank" rel="noopener">Fiche diplôme Onisep ↗</a>${x.acces ? ` · <strong>${esc(MT_ACCES[x.acces])}</strong>` : ""}</p>${forms}</details>`;
  };
  const status = d.status === "sans_diplome" ? `<div class="info">L'Onisep ne relie aucune fiche diplôme à ce métier.</div>`
    : d.status === "hors_parcoursup" ? `<div class="info">Les diplômes qui mènent à ce métier ne sont pas sur Parcoursup (ils se préparent après un premier diplôme, ou dans une école) : regardez leur fiche Onisep.</div>` : "";
  const nForm = d.n_formations;                                       // distinct formations (one may prepare several diplomas)
  const read = (d.emploi2030 || []).filter((f) => !f.absent && f.lecture).map((f) => f.lecture);
  const word = { debutants_insuffisants: "Recrute au-delà des débutants", debutants_nombreux: "Entrée plus disputée", incertain: "Prévisions divergentes" };   // lot 1, PR 10: « Pas de conclusion » read as nothing known (Sarah)
  // fixed rule (sprint 16): every family read agrees, else no conclusion
  const r2030 = !read.length ? null : read.every((x) => x === read[0]) ? word[read[0]] : word.incertain;
  const n2030 = !read.length ? "pas de projection pour ce métier" : read.every((x) => x === read[0]) ? "projection Dares, sous hypothèses"
    : "les projections pour ce métier ne s'accordent pas";
  const iaSpan = d.ia && d.ia.min != null ? (d.ia.min === d.ia.max ? fmt2(d.ia.min) : `${fmt2(d.ia.min)} à ${fmt2(d.ia.max)}`) : null;
  const tile = (tab, label, value, note) => `<button type="button" class="sum-tile" data-goto="${tab}"><span class="sum-label">${label}</span><span class="sum-value">${value}</span><span class="sum-note">${note}</span></button>`;
  const summary = `<section class="card summary" aria-label="L'essentiel en 30 secondes"><h2>L'essentiel</h2><div class="sum-grid">
      ${tile("formations", "Niveau minimum", d.niveau_acces_min ? esc(d.niveau_acces_min) : "—", "d'après l'Onisep")}
      ${tile("formations", "Diplômes", fmt(d.diplomes.length), nForm ? `${fmt(nForm)} formation(s) Parcoursup` : "aucune formation Parcoursup")}
      ${tile("avenir", "Emploi d'ici 2030", r2030 ? `<span class="text">${esc(r2030)}</span>` : "—", n2030)}
      ${tile("avenir", "Tâches exposées à l'IA", iaSpan || "—", iaSpan ? "note de 0 à 1 des tâches (Organisation internationale du travail), pas un risque de perte d'emploi" : "pas de note pour ce métier")}
      ${robustesseTile(d.robustesse)}
    </div></section>`;
  $view.innerHTML = `<div class="card"><p class="small"><a href="#/metiers">← Autres métiers</a></p>
    <h1>${esc(d.nom)}</h1>
    <p class="small">${d.niveau_acces_min ? `Niveau d'études minimum (Onisep) : ${esc(d.niveau_acces_min)} · ` : ""}<a href="${esc(d.url)}" target="_blank" rel="noopener">Fiche métier Onisep ↗</a></p>
    </div>
    ${summary}${tabbed("metier", [
      ["formations", "Diplômes et formations", `${parcoursCard(d.parcours, d)}${status}
    ${home ? `<label class="small"><input type="checkbox" id="mhome" ${onlyHome ? "checked" : ""}> Mon académie seulement (${esc(acadLabel(home))})</label>` : ""}
    <p class="muted small">Liste nationale : un établissement figure parce qu'il prépare le diplôme, pas parce que ses étudiants exercent ce métier. Ce n'est pas une promesse d'emploi. Les formations sont rangées par académie et par ville, pas par chances d'admission.</p>
    ${d.diplomes.map(dip).join("")}
    <p class="muted small">Source : Onisep, Idéo (licence ODbL) ; formations Parcoursup ${d.session}.</p>`],
      ["avenir", "Avenir du métier", `${robustesseCard(d.robustesse)}${emploi2030Card(d.emploi2030)}${bmoCard(d.bmo)}${iaCard(d.ia)}${codesCard(d.codes)}`],
    ])}${nextSteps("metier", /^https:\/\//.test(d.url || "") ? [{ href: d.url, text: "Lire la fiche du métier sur le site de l'Onisep" }] : [])}`;
  bindTabs("metier");
  const h = document.getElementById("mhome");
  if (h) h.onchange = () => { store.set("metierHome", h.checked); viewMetier(id, from); };
  bindVoeuButton(() => viewMetier(id, from));
}

// ---- Robustesse 2035 (owner's PRD, 2026-11-16): an ESTIMATION OF THE MODEL per job (robustesse.py), never a forecast for a
// person, a promise or a chance. The median of three scenarios, the range under it, the components, the confidence and
// « D'où vient ce chiffre ? » (sources, dates, model version). Fixed wording only (no free text), no alarming word.
const ROB_REGIME = {
  peu_expose: "peu exposé à l'IA générative : peu de ses tâches pourraient être faites par l'IA",
  surtout_augmente: "exposé à l'IA générative, mais l'IA y sert surtout à aider le travail plutôt qu'à le faire à la place",
  surtout_substituable: "exposé à l'IA générative, et l'IA y fait souvent la tâche à la place : ses tâches vont évoluer",
  mixte: "exposé à l'IA générative, l'IA y aide le travail autant qu'elle fait des tâches à la place",
};
const ROB_SCEN = { S1: "IA accélérée", S2: "Central", S3: "Transition rapide (bas-carbone)" };
const ROB_CONF = { haute: "confiance haute", moyenne: "confiance moyenne", faible: "données insuffisantes" };
const robNum = (x) => (x === null || x === undefined ? "—" : Number(x).toLocaleString("fr-FR", { maximumFractionDigits: 0 }));
// owner, 2026-11-17: the scores form a tight bell, so the page leads with a repère in three levels and three plain facts;
// the score, the scenarios and the components stay in « Détail du calcul ».
const ROB_REPERE = {
  haut: "Parmi les 20 % de métiers les plus robustes",
  moyen: "Dans la moyenne des métiers",
  bas: "Parmi les 20 % de métiers les moins robustes",
};
function robFaits(c) {
  const out = [];
  if (c.cedefop_taux != null) out.push(`D'ici 2035 : environ ${robNum(Math.max(0, c.cedefop_taux * 100))} postes à pourvoir pour 100 emplois actuels, départs à la retraite compris (Cedefop).`);
  if (c.augmentation != null) out.push(`IA générative : dans ${robNum(c.augmentation * 10)} usages sur 10, elle aide le travail plutôt qu'elle ne le fait à la place (Anthropic Economic Index).`);
  if (c.tension != null) out.push(`En 2026 : ${robNum(c.tension / 10)} recrutements sur 10 sont jugés difficiles par les employeurs (France Travail, BMO).`);
  return out;
}
function robustesseTile(r) {
  if (!r) return "";
  const q = r.repere;
  return `<button type="button" class="sum-tile" data-goto="avenir"><span class="sum-label">Robustesse 2035</span>
    <span class="sum-value">${q ? `<span class="text">${esc(ROB_REPERE[q.niveau] || "")}</span>` : "—"}</span>
    <span class="sum-note">${q ? estimTag("", false, true) : "données insuffisantes"}</span></button>`;
}
function robustesseCard(r) {
  if (!r) return "";
  const s = r.score, c = r.composantes || {}, k = r.confiance || {};
  const q = r.repere, faits = robFaits(c);
  const head = (s && q ? `<p><strong>${esc(ROB_REPERE[q.niveau] || "")}</strong> ${estimTag("place du métier parmi ceux que le modèle peut estimer")}</p>`
    : `<p class="muted">Données insuffisantes pour une estimation sûre : nous préférons ne pas situer ce métier.</p>`)
    + (faits.length ? `<ul class="rob-faits">${faits.map((x) => `<li>${x}</li>`).join("")}</ul>` : "");
  const score = s ? `<p>Score : <strong>${robNum(s.median)}</strong> sur 100, médiane des trois scénarios. Selon le scénario, de <strong>${robNum(s.min)}</strong> (le moins favorable) à <strong>${robNum(s.max)}</strong> (le plus favorable)${s.dependance_scenario ? ' · <span class="badge">dépend du scénario</span>' : ""}.</p>
      ${q ? `<p class="small">Repère : les 20 % de métiers aux scores les plus hauts (${robNum(q.seuil_haut)} ou plus) et les 20 % aux scores les plus bas (${robNum(q.seuil_bas)} ou moins), parmi ${robNum(q.n_metiers)} métiers estimés. Les scores sont proches les uns des autres : un ou deux points d'écart ne veulent rien dire.</p>` : ""}` : "";
  const phrase = r.regime_ia ? `<p>Ce métier est ${esc(ROB_REGIME[r.regime_ia] || "")}.</p>` : "";
  const scen = s && r.scenarios ? `<div class="scroll"><table><tr><th>Scénario</th><th class="num">Score</th></tr>
      ${["S1", "S2", "S3"].map((x) => `<tr><td>${esc(ROB_SCEN[x])}</td><td class="num" data-label="Score">${robNum(r.scenarios[x])}</td></tr>`).join("")}</table></div>` : "";
  const comp = `<div class="scroll"><table><tr><th>Ce qui compte</th><th class="num">Sur 100</th></tr>
      <tr><td>Résistance à l'IA (35 %) : exposition des tâches ${c.exposition != null ? fmt2(c.exposition) : "—"} sur 1, part d'usage où l'IA aide plutôt qu'elle ne remplace ${c.augmentation != null ? `${robNum(c.augmentation * 100)} %` : "—"}</td><td class="num" data-label="Sur 100">${robNum(c.ia)}</td></tr>
      <tr><td>Demande d'ici 2035 (25 %)</td><td class="num" data-label="Sur 100">${robNum(c.demande)}</td></tr>
      <tr><td class="small">· Postes à pourvoir 2024-2035, Cedefop (50 %)${c.cedefop_taux != null ? ` : ${robNum(c.cedefop_taux * 100)} % de l'emploi actuel` : ""}</td><td class="num" data-label="Sur 100">${robNum(c.cedefop)}</td></tr>
      <tr><td class="small">· Postes à pourvoir 2019-2030, Métiers 2030 (30 %)${c.m2030_taux != null ? ` : ${robNum(c.m2030_taux * 100)} % de l'emploi de 2019` : ""}</td><td class="num" data-label="Sur 100">${robNum(c.m2030)}</td></tr>
      <tr><td class="small">· Recrutements jugés difficiles en 2026, BMO (20 %)</td><td class="num" data-label="Sur 100">${robNum(c.tension)}</td></tr></table></div>`;
  const conf = `<p class="small"><strong>${esc(ROB_CONF[k.niveau] || "")}</strong>${k.valeur != null ? ` (${fmt2(k.valeur)} sur 1, la plus faible de quatre mesures : fraîcheur des sources ${fmt2(k.fraicheur)}, liens observés ${fmt2(k.donnees_observees)}, accord des sources ${fmt2(k.accord_sources)}, couverture ${fmt2(k.couverture)})` : ""}.</p>`;
  const o = r.ocde || {};
  const ocde = o.rang_oit != null && o.rang_ocde != null ? `<p class="small">Contrôle avec une autre mesure, celle de l'OCDE (2026). Selon l'OIT, ce métier est plus exposé à l'IA que ${robNum(o.rang_oit * 100)} % des métiers mesurés. Selon l'OCDE, plus exposé que ${robNum(o.rang_ocde * 100)} %. Les deux mesures ne comptent pas la même chose : seul l'écart entre ces deux places est lu. Au-delà de 15 points, la confiance baisse.</p>` : "";
  // owner, 2026-11-17: the observed use of AI (Anthropic Economic Index, share of the conversations) is a second cross-check of
  // the OIT exposure, by rank only; it never enters the score
  const u = r.usage || {};
  const usage = u.rang_oit != null && u.rang_usage != null ? `<p class="small">Contrôle avec l'usage réel de l'IA (Anthropic Economic Index, mai 2026). Selon l'OIT, ce métier est plus exposé que ${robNum(u.rang_oit * 100)} % des métiers mesurés. Ses tâches reviennent dans plus de conversations avec l'IA que celles de ${robNum(u.rang_usage * 100)} % des métiers. Seul l'écart entre ces deux places est lu : au-delà de 15 points, la confiance baisse. Ce chiffre n'entre pas dans le score.</p>` : "";
  const v = r.esco || {}, pc = (x) => (x * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 });
  const esco = v.part_verte != null ? `<p class="small">Contrôle « transition écologique » : selon ESCO (Commission européenne), ${pc(v.part_verte)} % des compétences de ce métier sont « vertes »${v.mediane != null ? ` (médiane de tous les métiers : ${pc(v.mediane)} %)` : ""}. Ce chiffre n'entre pas dans le score. Le scénario bas-carbone vient de « Les métiers en 2030 ».</p>` : "";
  const eu = (r.isco || []).some((i) => i.cedefop_croissance_source === "UE27");
  const src = `<details class="more-card"><summary>D'où vient ce chiffre ?</summary>
      <ul class="small">${(r.sources_detail || []).map((x) => `<li>${esc(x.libelle)}</li>`).join("")}</ul>
      ${eu ? `<p class="small">Pour un ou plusieurs groupes de ce métier, la croissance est la moyenne européenne : les chiffres français du Cedefop sont faussés par un changement de méthode de l'enquête Emploi en 2021.</p>` : ""}
      <p class="small">Calcul : par métier, la résistance à l'IA (exposition × part où l'IA remplace) et la demande (Cedefop, Métiers 2030, BMO), ramenées sur 100 avec des bornes fixes, pondérées 35 et 25. Trois scénarios : IA accélérée (exposition augmentée comme dans le scénario « +1 niveau cognitif » de l'OCDE, sinon × 1,25 ; aide × 0,8), central, transition rapide (variante bas-carbone de Métiers 2030). Version du modèle ${esc(r.model_version)}. <a href="#/info/robustesse">Comment on calcule la robustesse</a></p></details>`;
  return `<div class="card" id="robustesse"><h2>Robustesse 2035</h2>
    <p class="muted small">Une estimation du modèle de SupCompass : ce métier gardera-t-il de la valeur sur le marché du travail entre 2030 et 2035 ? Ce n'est ni une prévision pour une personne, ni une promesse.</p>
    ${head}${phrase}<details class="more-card"><summary>Détail du calcul</summary>${score}${scen}${comp}${conf}${ocde}${usage}${esco}</details>${src}</div>`;
}

// ---- Robustesse 2035 per FORMATION (owner, 2026-11-17): built on the per-job model (robustesse_formation.py), an ESTIMATION
// OF THE MODEL, never a chance of a job or a promise. The page leads with a repère among the formations of the SAME filière
// scored with the same terms (none when they share their outlets), three plain facts, « avec ce diplôme seul » apart, the gain
// through a master for a licence, the skills (RNCP x ROME 4.0) and the RNCP blocks verbatim; the score in « Détail du calcul ».
const ROBF_REPERE = {
  haut: "Parmi les 20 % de formations les plus robustes de sa filière",
  moyen: "Dans la moyenne des formations de sa filière",
  bas: "Parmi les 20 % de formations les moins robustes de sa filière",
};
const ROBF_REPERE_NATIONAL = {
  haut: "Parmi les 20 % de formations les plus robustes, toutes filières confondues",
  moyen: "Dans la moyenne de toutes les formations",
  bas: "Parmi les 20 % de formations les moins robustes, toutes filières confondues",
};
const ROBF_APRES = {
  master: "Les métiers comptés sont ceux des masters : ils arrivent après la licence et un master (bac+5).",
  autres: "Les métiers comptés arrivent souvent après d'autres études (bac+5 et plus) : la comparaison avec un diplôme court est donc à lire avec prudence.",
};
const ROBF_METHODE = {
  direct: "les métiers de la fiche Onisep du diplôme",
  poursuite: "les métiers des masters de la même université et de la même discipline, pesés par leurs admis (MonMaster)",
  famille: "les métiers auxquels cette formation mène, souvent après d'autres études (lien moins sûr)",
  certification: "les métiers des codes de la certification RNCP du même intitulé (France Compétences ; lien moins sûr)",
};
const ROBF_VOISINE = {
  cmi_licence: "le Cursus Master en Ingénierie s'appuie sur la licence de même mention du même établissement",
  mise_a_niveau_bts_mhr: "cette année de mise à niveau prépare l'entrée en BTS Management en hôtellerie-restauration",
};
const ROBF_LIEN = { onisep: "lien donné par la fiche Onisep du diplôme", titre: "fiche du titre national du diplôme", certification: "fiche RNCP du même intitulé" };
const robJobs = (j) => `${robNum(j.n)} métier${j.n > 1 ? "s" : ""}${j.n_notes < j.n ? ` (${robNum(j.n_notes)} estimé${j.n_notes > 1 ? "s" : ""})` : ""} : ${robNum(j.n_haut)} parmi les 20 % de métiers les plus robustes, ${robNum(j.n_bas)} parmi les 20 % les moins robustes`;
function robfFaits(r) {
  const out = [], m = r.metiers || {}, c = r.competences, k = r.rncp || {};
  if (m.n) out.push(`Débouchés : ${robJobs(m)}. On regarde ${ROBF_METHODE[r.methode] || ""}.`);
  if (c && c.n) out.push(`Compétences : ${robNum(c.part_portable * 100)} sur 100 sont transférables d'un métier à l'autre (France Travail). ${robNum(c.numeriques)} touchent au numérique, ${robNum(c.ecologiques)} à la transition écologique.`);
  if (r.master && r.master.n_admis) out.push(`Après la licence : ${robNum(r.master.n_masters)} master${r.master.n_masters > 1 ? "s" : ""} de cette université dans la même discipline, ${robNum(r.master.n_admis)} admis la dernière session.`);
  // owner, 2026-11-18: too few documented masters to score the licence through them: said, the licence scored on its own jobs
  if (r.master && r.master.insuffisant) out.push(`Les masters de cette université décrits par l'Onisep ne mènent qu'à ${robNum((r.master.apres_master || {}).n)} métier${(r.master.apres_master || {}).n > 1 ? "s" : ""} : c'est trop peu pour juger la licence par ses masters. Elle est donc notée sur les métiers de la licence seule.`);
  if (k.fiche) out.push(k.apprentissage ? "Pratique : le diplôme peut se préparer en apprentissage (expérience en entreprise), selon sa fiche RNCP." : "Pratique : la fiche RNCP du diplôme ne cite pas l'apprentissage parmi ses voies d'accès.");
  return out;
}
// owner, 2026-11-18: the PUBLISHED insertion of a BTS (Inserjeunes, this establishment) or a BUT (InserSup) shown BESIDE the
// robustesse, in its own block, never in the score (the BTS is measured at 6 months, the BUT among the few who leave): each value
// as published with its denominator, a masked one said, the options of a BTS each on its own line (never averaged)
const robPc = (v) => (v == null ? '<span class="muted">non publié</span>' : `<strong>${pc1d(v)}\u00a0%</strong>`);
function robInsPublie(ins, but) {
  let body = "";
  if (ins && ins.rows && ins.rows.length) {
    const many = ins.rows.length > 1;
    body = `<p class="small">Ce BTS dans cet établissement (Inserjeunes, ${esc(String(ins.annee || "").replace("cumul", "sortis en"))})${many ? ", chaque option à part" : ""} :</p>
      <ul class="small">${ins.rows.map((r) => `<li>${many ? `${esc(r.libelle_formation)} : ` : ""}en emploi 6 mois après, ${robPc(r.taux_emploi_6)} des élèves qui ont quitté les études ; poursuivent leurs études, ${robPc(r.taux_poursuite)} des élèves de dernière année.</li>`).join("")}</ul>`;
  } else if (but && (but.specialite || but.total || but.france_specialite)) {
    const [lab, x] = but.specialite ? ["Cette spécialité dans l'université", but.specialite] : but.total ? ["Tous les BUT de l'université", but.total] : ["Cette spécialité, en France", but.france_specialite];
    body = `<p class="small">${esc(lab)} (InserSup, ${promoTxt(x)}) : en emploi salarié en France ${H} mois après, ${robPc(x[`tx_sortants_en_emploi_sal_fr_${H}`])} des diplômés qui ont quitté les études ; en emploi stable, ${robPc(x[`tx_sortants_en_emploi_stable_${H}`])} de ceux en emploi salarié. La plupart des diplômés de BUT poursuivent leurs études : ils ne sont pas comptés.</p>`;
  }
  if (!body) return "";
  return `<div class="rob-pub"><h3>À côté : l'insertion publiée</h3>${body}
    <p class="muted small">Ces chiffres publiés restent à côté de la robustesse, jamais dedans : ils décrivent des promotions passées, quelques mois après le diplôme, alors que la robustesse porte sur les métiers entre 2030 et 2035. Ce ne sont pas des chances d'emploi. Le détail est dans la carte « Insertion professionnelle »${ins && ins.rows && ins.rows.length ? " plus bas" : ", onglet « Réussir et poursuivre »"}.</p></div>`;
}
// owner, 2026-11-20: a formation left without a block on purpose says why (robustesse_formation.ABSENT_RULES), never a figure
const ROBF_ABSENT = {
  bachelor_ecole_ingenieur: {
    court: "pas d'estimation : Onisep ne publie pas les métiers de ce bachelor",
    long: "Pas d'estimation pour ce bachelor. Onisep ne publie pas les métiers auxquels il mène. Le diplôme d'ingénieur de l'école est un autre diplôme, en cinq ans après le bac. Nous ne lui empruntons pas sa note : le passage en cycle ingénieur n'est pas automatique.",
  },
};
function formationRobustesseCard(r, pub) {
  if (!r) return "";
  if (r.absent) {
    const a = ROBF_ABSENT[r.absent];
    return a ? `<div class="card" id="robustesse"><h2>Robustesse 2035 de la formation</h2><p class="muted">${esc(a.long)}</p>
      <p class="small"><a href="#/info/robustesse">Comment on calcule la robustesse</a></p></div>` : "";
  }
  const s = r.score, q = r.repere, cp = r.composantes || {}, k = r.confiance || {}, faits = robfFaits(r);
  const fil = q && q.filiere ? ` (${esc(q.filiere.replace("_", " "))})` : "";
  const head = !s ? `<p class="muted">Données insuffisantes pour une estimation sûre : nous préférons ne pas situer cette formation.</p>`
    : r.voisine ? ""
    : q && q.niveau ? `<p><strong>${esc(ROBF_REPERE[q.niveau] || "")}</strong>${fil} ${estimTag(`parmi ${robNum(q.n_formations)} formations comparables`)}</p>`
    : q && q.raison === "memes_debouches" ? `<p>Les formations de cette filière${fil} mènent aux mêmes métiers : nous ne les classons pas entre elles. ${estimTag("")}</p>`
    : `<p>Trop peu de formations comparables dans cette filière${fil} pour situer celle-ci. ${estimTag("")}</p>`;
  // owner, 2026-11-17: a second repère among EVERY formation, on the terms all of them have (their jobs and the diversity)
  const qn = r.repere_national;
  // owner, 2026-11-20: a borrowed block names its neighbour and why, before anything else
  const v = r.voisine;
  const vois = v ? `<p class="small warn">Repère emprunté à la formation voisine${v.libelle ? ` « ${esc(v.libelle)} »` : ""}${v.code ? ` (<a href="#/f/${esc(v.code)}">voir sa fiche</a>)` : ""}. ${ROBF_VOISINE[v.regle] ? `Pourquoi : ${esc(ROBF_VOISINE[v.regle])}. ` : ""}Cette formation n'a pas de métiers propres dans les sources ; la confiance est abaissée et elle n'est pas classée dans sa filière.</p>` : "";
  const nat = s && qn && qn.niveau ? `<p><strong>${esc(ROBF_REPERE_NATIONAL[qn.niveau] || "")}</strong> ${estimTag(`parmi ${robNum(qn.n_formations)} formations, sur les métiers visés et leur diversité`)}${qn.apres_etudes ? `<br><span class="small">${esc(ROBF_APRES[qn.apres_etudes] || "")}</span>` : ""}</p>` : "";
  // owner, 2026-11-22: the level first (five levels among the Parcoursup formations); the repères go into « Détail du calcul »
  const niv = r.echelle && r.echelle.niveaux, ew = s ? echelleWords(niv) : "";
  const lvl = !s ? head : ew ? `<p class="rob-lvl"><strong>${esc(ew)}</strong> ${echelleJauge(niv)} ${estimTag(`parmi ${robNum(r.echelle.n_formations)} formations Parcoursup, sur les métiers visés et leur diversité`)}<br><span class="small">${esc(echelleNote(niv))}${(qn && qn.apres_etudes) ? ` · ${esc(ROBF_APRES[qn.apres_etudes] || "")}` : ""}</span></p>`
    : head;
  const list = (faits.length ? `<ul class="rob-faits">${faits.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "");
  const seul = r.diplome_seul && r.diplome_seul.n ? `<h3>Avec ce diplôme seul</h3><p class="small">${esc(robJobs(r.diplome_seul))}${r.diplome_seul.mediane != null ? ` (score médian de ces métiers : ${robNum(r.diplome_seul.mediane)} sur 100)` : ""}. Ce sont les métiers de la fiche Onisep du diplôme, sans études de plus.</p>` : "";
  const am = r.master && r.master.apres_master;
  const gain = am && am.n ? `<h3>Après un master de l'université</h3><p class="small">${esc(robJobs(am))}${am.mediane != null ? ` (score médian : ${robNum(am.mediane)} sur 100${r.diplome_seul && r.diplome_seul.mediane != null ? `, contre ${robNum(r.diplome_seul.mediane)} avec la licence seule` : ""})` : ""}.${cp.insertion != null ? ` Emploi stable 18 mois après ces masters : ${robNum(cp.insertion)} % des diplômés salariés, ${r.master.insertion_masters > 1 ? `moyenne des ${robNum(r.master.insertion_masters)} masters publiés pesés par leurs admis` : "chiffre du seul master publié"} (InserSup ; ${estimTag("", false, true)}).` : ""}</p>` : "";
  const princ = (m) => (m.principaux || []).length ? `<h3>Principaux métiers visés</h3><ul class="small">${m.principaux.map((j) => `<li><a href="#/metier/${esc(j.id)}">${esc(j.nom || j.id)}</a>${j.repere ? ` <span class="muted">· ${esc({ haut: "parmi les plus robustes", moyen: "dans la moyenne", bas: "parmi les moins robustes" }[j.repere] || "")}</span>` : ""}</li>`).join("")}</ul>` : "";
  const rn = r.rncp || {};
  const num = /^RNCP\d+$/.test(rn.fiche || "") ? rn.fiche.slice(4) : null;
  const blocs = (rn.blocs || []).length ? `<details class="more-card"><summary>Les blocs de compétences du diplôme (RNCP)</summary><ul class="small">${rn.blocs.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
      <p class="muted small">Tels que les publie France Compétences${rn.intitule ? ` pour « ${esc(rn.intitule)} »` : ""} (${esc(ROBF_LIEN[rn.lien] || "")})${num ? ` · <a href="https://www.francecompetences.fr/recherche/rncp/${num}/" target="_blank" rel="noopener">fiche RNCP ${esc(num)} ↗</a>` : ""}.</p></details>` : "";
  const score = s ? `<p>Score : <strong>${robNum(s.median)}</strong> sur 100, médiane des trois scénarios. Selon le scénario, de <strong>${robNum(s.min)}</strong> à <strong>${robNum(s.max)}</strong>${s.dependance_scenario ? ' · <span class="badge">dépend du scénario</span>' : ""}. Un ou deux points d'écart ne veulent rien dire.</p>${r.score_national != null ? `<p class="small">Sur la base commune à toutes les formations (métiers visés et diversité) : <strong>${robNum(r.score_national)}</strong> sur 100.</p>` : ""}` : "";
  const scen = s && r.scenarios ? `<div class="scroll"><table><tr><th>Scénario</th><th class="num">Score</th></tr>
      ${["S1", "S2", "S3"].map((x) => `<tr><td>${esc(ROB_SCEN[x])}</td><td class="num" data-label="Score">${robNum(r.scenarios[x])}</td></tr>`).join("")}</table></div>` : "";
  const row = (lab, v) => `<tr><td>${lab}</td><td class="num" data-label="Sur 100">${v == null ? "—" : robNum(v)}</td></tr>`;
  const comp = `<div class="scroll"><table><tr><th>Ce qui compte</th><th class="num">Sur 100</th></tr>
      ${row("Robustesse des métiers visés (60 %)", cp.metiers)}${row("Insertion après le diplôme de sortie (10 %)", cp.insertion)}
      ${row("Diversité des débouchés (15 %)", cp.diversite)}${row("Compétences transférables (15 %)", cp.competences)}</table></div>
      <p class="small">Une ligne « — » n'est pas publiée pour cette formation : le score se calcule sur les autres lignes, et la couverture baisse.</p>`;
  const conf = `<p class="small"><strong>${esc(ROB_CONF[k.niveau] || "")}</strong>${k.valeur != null ? ` (${fmt2(k.valeur)} sur 1, la plus faible de quatre mesures : fraîcheur des sources ${fmt2(k.fraicheur)}, liens observés ${fmt2(k.donnees_observees)}, accord des sources ${fmt2(k.accord_sources)}, couverture ${fmt2(k.couverture)})` : ""}.</p>`;
  const src = `<details class="more-card"><summary>D'où vient ce chiffre ?</summary>
      <p class="small">Chaque métier visé a sa robustesse 2035 (voir sa page : résistance à l'IA générative et demande d'ici 2035). Pour la formation, on pèse ces métiers (60 %), l'insertion publiée après le diplôme de sortie (10 % ; le BTS, mesuré à 6 mois, reste à part), la diversité des débouchés entre les grands groupes de métiers (15 %) et la part de compétences transférables (15 %). Les compétences viennent de la fiche RNCP du diplôme (France Compétences : codes ROME visés) et du référentiel ROME 4.0 de France Travail : une compétence est transférable quand France Travail la classe « transverse » ou qu'au moins 20 fiches métiers la partagent. Le premier repère compare la formation aux formations de la même filière calculées avec les mêmes éléments. Le second la compare à toutes les formations, sur les seuls éléments que toutes ont : les métiers visés et leur diversité. Version du modèle ${esc(r.model_version)}. <a href="#/info/robustesse">Comment on calcule la robustesse</a></p>
      <p class="muted small">Sources : Onisep, Idéo (licence ODbL) ; France Compétences, RNCP (Licence Ouverte) ; France Travail, ROME 4.0 (Licence Ouverte) ; MonMaster et InserSup (MESR) ; et les sources de la robustesse des métiers (OIT, Anthropic Economic Index, Cedefop, Dares, France Travail).</p></details>`;
  return `<div class="card" id="robustesse"><h2>Robustesse 2035 de la formation</h2>
    <p class="muted small">Une estimation du modèle de SupCompass : les métiers auxquels mène cette formation et les compétences qu'elle développe garderont-ils de la valeur entre 2030 et 2035 ? Ce n'est ni une prévision pour une personne, ni une promesse d'emploi.</p>
    ${vois}${lvl}${list}${robInsPublie(pub && pub.ins, pub && pub.but)}${seul}${gain}${princ(r.metiers || {})}${blocs}<details class="more-card"><summary>Détail du calcul</summary>${head}${nat}${score}${scen}${comp}${conf}</details>${src}</div>`;
}

// ---- Sprint 15: l'IA générative et les tâches du métier (OIT 2025, France Travail) -----
// Published ILO exposure per ISCO code (gradient and mean task score), every code of the job shown with its title count;
// the RANGE of the means, never an average, never combined with the 2030 figures; a potential of tasks, not job losses.
const IA_GRADIENT = {
  "Not Exposed": "non exposé", "Minimal Exposure": "exposition minimale",
  "Exposed: Gradient 1": "exposé, gradient 1 sur 4", "Exposed: Gradient 2": "exposé, gradient 2 sur 4",
  "Exposed: Gradient 3": "exposé, gradient 3 sur 4", "Exposed: Gradient 4": "exposé, gradient 4 sur 4",
};
function iaCard(ia) {
  if (!ia || ((!ia.isco || !ia.isco.length) && (!ia.tags || !ia.tags.length))) return "";
  const score = (x) => (x === null || x === undefined ? "—" : Number(x).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  // θ: the range over the code's US occupations (O*NET), never an average; a code without one says so
  const span = (lo, hi) => (score(lo) === score(hi) ? score(lo) : `${score(lo)} à ${score(hi)}`);
  const theta = (i) => (i.theta_min === null || i.theta_min === undefined ? '<span class="muted">non calculée</span>'
    : `${span(i.theta_min, i.theta_max)}<div class="muted small">${fmt(i.n_onet)} profession${i.n_onet > 1 ? "s" : ""} US</div>`);
  const rows = (ia.isco || []).map((i) => `<tr><td>${esc(i.code)}</td><td>${esc(i.libelle || "")}<div class="muted small">${fmt(i.n_intitules)} intitulé${i.n_intitules > 1 ? "s" : ""} de profession</div></td>
      <td>${i.gradient ? esc(IA_GRADIENT[i.gradient] || i.gradient) : '<span class="muted">pas de note pour ce code</span>'}</td><td class="num">${score(i.score)}</td>
      <td class="num">${theta(i)}</td></tr>`).join("");
  const range = ia.min === null || ia.min === undefined ? ""
    : ia.min === ia.max ? `<p class="small">Note moyenne des tâches : ${score(ia.min)} sur 1.</p>`
    : `<p class="small">Selon les intitulés de ce métier, la note moyenne des tâches va de ${score(ia.min)} à ${score(ia.max)} sur 1.</p>`;
  const tagText = { Oui: "liée à la transition numérique", Non: "non liée à la transition numérique" };
  const tags = (ia.tags || []).length ? `<p class="small">France Travail : ${ia.tags.map((t) => `fiche ROME ${esc(t.rome)} ${t.transition_numerique ? esc(tagText[t.transition_numerique] || "") : "non renseignée pour la transition numérique"}`).join(" ; ")}.</p>` : "";
  // lot 1, PR 10: the codes (ISCO-08, O*NET) and the method are folded under « Détail du calcul et sources », never removed
  return `<div class="card"><h2>L'IA générative et les tâches de ce métier</h2>
    <p class="muted small">L'Organisation internationale du travail (OIT) a noté chaque tâche de chaque métier selon la part que l'IA générative pourrait en faire. C'est un potentiel technique des tâches, pas une prévision de pertes d'emplois ni un risque pour vous : un métier exposé est plus souvent transformé que remplacé.</p>
    ${range}
    ${ia.theta_min === null || ia.theta_min === undefined ? "" : `<p class="small">Complémentarité humaine (méthode du FMI, estimation adaptée) : de ${score(ia.theta_min)} à ${score(ia.theta_max)} sur 1 selon le code et la profession américaine. Plus elle est haute, plus le métier a des traits qui font de l'IA un outil d'appui plutôt qu'un remplaçant (contact humain, responsabilité, conditions physiques, décisions lourdes, travail peu routinier, longue formation).</p>`}
    ${tags}
    <details class="more-card"><summary>Détail du calcul et sources</summary>
    ${rows ? `<div class="scroll"><table><tr><th>ISCO-08</th><th>Groupe de base</th><th>Classement OIT</th><th class="num">Note moyenne des tâches</th><th class="num">Complémentarité humaine</th></tr>${rows}</table></div>` : ""}
    <p class="muted small">Le classement de l'OIT tient compte de la note moyenne et de l'écart entre les tâches : deux notes proches peuvent avoir deux classements différents. Les codes ISCO viennent des intitulés de profession (voir les codes officiels plus bas) ; on ne fait pas la moyenne entre eux. La complémentarité humaine reprend la méthode du FMI (Pizzinelli et al., 2023) sur les données américaines O*NET 31.0 : c'est une estimation adaptée (fiabilité C), pas le score publié par le FMI ; elle passe par les tables officielles O*NET et BLS (O*NET-SOC 2019, SOC 2018, SOC 2010, ISCO-08). Elle n'est jamais combinée avec la note de l'OIT. Sources : OIT, Gmyrek, Berg et al. (2025), « Generative AI and Jobs: A Refined Global Index of Occupational Exposure », CC BY 4.0 ; France Travail, étiquettes des fiches ROME (octobre 2026) ; O*NET 31.0 (U.S. Department of Labor, CC BY 4.0) ; BLS, tables de passage SOC et ISCO-08.</p></details></div>`;
}

// ---- Sprint 14 follow-up: les recrutements prévus en 2026 (enquête BMO de France Travail) -----
// Employers' hiring INTENTIONS for one year: published cells summed (masked values below 5 count as 0, so totals are
// floors: "au moins"); a share is flagged fragile when masked cells could move it by more than 5 points.
function bmoCard(b) {
  if (!b || !Array.isArray(b.familles) || !b.familles.length) return "";
  const n = b.national || {};
  const pct = (x) => (x === null || x === undefined ? "—" : `${fmt(x * 100)} %`);
  const one = (f) => {
    if (f.absent) return `<h3>${esc(f.code)}</h3><p class="small muted">Pas de chiffre BMO pour cette famille.</p>`;
    // no 2025 comparison: in 2026 France Travail splits areas into local committees, so more cells are masked and
    // the 2026 floors are lower for that reason alone (a drop would be partly an artefact)
    return `<h3>${esc(f.code)} · ${esc(f.libelle || "")}</h3>
      ${f.toutes_qualifications ? "" : `<p class="small muted">Une des familles possibles selon la qualification du poste.</p>`}
      <div class="scroll"><table>
        <tr><td>Recrutements envisagés en 2026, en France</td><td class="num">au moins ${fmt(f.projets)}</td></tr>
        <tr><td>dont jugés difficiles par les employeurs</td><td class="num">${pct(f.part_difficile)}${f.fragile ? ' <span class="badge">fragile</span>' : ""} <span class="muted small">(tous métiers : ${pct(n.part_difficile)})</span></td></tr>
        <tr><td>dont saisonniers</td><td class="num">${pct(f.part_saisonniere)} <span class="muted small">(tous métiers : ${pct(n.part_saisonniere)})</span></td></tr>
      </table></div>`;
  };
  return `<div class="card"><h2>Les recrutements prévus en 2026</h2>
    <p class="muted small">Intentions d'embauche déclarées par les employeurs pour cette année (enquête BMO) : ce ne sont ni des offres d'emploi ni des embauches, et cela ne dit rien de l'emploi en 2030. Les chiffres sont ceux de toute la famille de métiers.</p>
    ${b.familles.map(one).join("")}
    <p class="muted small">France Travail masque les valeurs inférieures à 5 : elles comptent pour 0, d'où « au moins ». Une part est « fragile » quand ces valeurs masquées pourraient la déplacer de plus de 5 points. Source : France Travail, enquête Besoins en main-d'œuvre 2026 et 2025, sommes des bassins d'emploi publiés. Licence Ouverte.</p></div>`;
}

// ---- Sprint 14: l'emploi du métier d'ici 2030 (Dares / France Stratégie) -----------
// Published figures per job family (thousands), never a chance or a promise; the imbalance is shown as the range of
// the 5 published scenarios and read with a fixed rule on its sign; no figure beyond 2030 (none is published).
const M2030_LECTURE = {
  debutants_insuffisants: "Dans les 5 scénarios, les jeunes débutants ne suffiraient pas à pourvoir les postes : le métier devrait aussi recruter d'autres profils (reconversions, mobilités).",
  debutants_nombreux: "Dans les 5 scénarios, il y aurait plus de jeunes débutants que de postes à pourvoir : l'entrée dans le métier pourrait être plus disputée.",
  incertain: "Selon les scénarios, l'écart change de sens : on ne peut pas conclure.",
};
function kPeople(k, signed = false) {
  if (k === null || k === undefined) return "—";
  if (Math.abs(k) < 0.5) return "moins de 500";
  const v = fmt(Math.round(Math.abs(k)) * 1000);
  return signed ? `${k < 0 ? "−" : "+"}${v}` : `${k < 0 ? "−" : ""}${v}`;
}
function emploi2030Card(fams) {
  if (!Array.isArray(fams) || !fams.length) return "";
  const one = (f) => {
    const head = `<h3>${esc(f.fap87)} · ${esc(f.libelle || "")}</h3>`;
    if (f.absent) return `${head}<p class="small muted">Pas de chiffre : ${esc(f.raison || "")}.</p>`;
    const m = f.milliers || {}, p = f.parts || {}, d = f.desequilibre || {};
    const pct = (x) => (x === null || x === undefined ? "" : ` (${fmt(x * 100)} % des emplois de 2019)`);
    return `${head}
      ${f.calcule ? `<p class="small warn">Le classeur ne publie ces familles qu'ensemble, au sein de leur domaine : chiffres calculés (domaine moins les familles publiées).</p>` : ""}
      ${f.origine && f.origine.some((o) => o !== "onisep") ? `<p class="small muted">Famille trouvée à partir d'un code ROME retrouvé par le nom du métier (moins sûr, voir les codes officiels plus bas).</p>` : ""}
      <p class="small">${kPeople(m.emploi_2019)} emplois en 2019${f.toutes_qualifications ? "" : " · une des familles possibles selon la qualification du poste"}.</p>
      <div class="scroll"><table>
        <tr><td>Postes à pourvoir entre 2019 et 2030</td><td class="num">${kPeople(m.postes)}${pct(p.postes)}</td></tr>
        <tr><td class="muted small">dont départs en fin de carrière</td><td class="num small">${kPeople(m.departs)}</td></tr>
        <tr><td class="muted small">dont créations nettes d'emploi</td><td class="num small">${kPeople(m.creations, true)}</td></tr>
        <tr><td>Jeunes débutants attendus</td><td class="num">${kPeople(m.debutants)}</td></tr>
        <tr><td>Écart postes − débutants, selon les 5 scénarios</td><td class="num">de ${kPeople(d.min, true)} à ${kPeople(d.max, true)} <span class="muted small">(référence ${kPeople(d.reference, true)})</span></td></tr>
      </table></div>
      ${f.lecture ? `<p class="small">${M2030_LECTURE[f.lecture]}</p>` : ""}`;
  };
  return `<div class="card"><h2>L'emploi dans ce métier d'ici 2030</h2>
    <p class="muted small">Projection de la Dares et de France Stratégie par famille de métiers, sous hypothèses : ce n'est ni une prévision ni une promesse. Les chiffres sont ceux de toute la famille, pas seulement de ce métier.${fams.length > 1 ? " Ce métier relève de plusieurs familles selon la qualification du poste : chacune a ses chiffres." : ""}</p>
    ${fams.map(one).join("")}
    <p class="muted small">Aucune projection officielle par métier n'existe au-delà de 2030 : pas de chiffre pour 2035. Source : Dares et France Stratégie, « Les métiers en 2030 » (2022), projections 2019-2030, scénario de référence et 4 variantes. Licence Ouverte.</p></div>`;
}

// ---- Sprint 13: les codes officiels du métier (ROME -> FAP -> ISCO-08) --------
// Codes, not figures: every family a ROME code can lead to is listed with the qualification it applies to,
// none is picked for the student; ISCO codes come with the number of job titles behind them, never a share.
function qualifText(q) {
  if (!q || q.toutes) return "toutes qualifications";
  if (!q.libelles) return "selon la qualification du poste";
  return `pour : ${q.libelles.map(esc).join(", ")}`;
}
function codesCard(codes) {
  if (!Array.isArray(codes)) return "";
  const head = `<h2>Les codes officiels de ce métier</h2>
    <p class="muted small">Ils relient ce métier aux statistiques de l'emploi (projections à 2030, exposition à l'IA : prochaines étapes). Ce sont des codes, pas des chiffres sur l'emploi.</p>`;
  if (!codes.length) return `<div class="card">${head}<p class="small">L'Onisep ne donne pas de code ROME pour ce métier : il n'est pas encore relié aux statistiques de l'emploi.</p></div>`;
  const one = (c) => {
    if (!c.connu) return `<h3>Code ROME ${esc(c.rome)}</h3><p class="small">Ce code n'est pas dans les tables de passage de la Dares.</p>`;
    const fam = (xs, sub) => xs.length ? `<ul class="small">${xs.map((f) => `<li><strong>${esc(f.code)}</strong> ${esc(f.libelle || "")}${sub(f)} · <span class="muted">${qualifText(f.qualifications)}</span></li>`).join("")}</ul>`
      : `<p class="small muted">Aucune famille dans la table de la Dares.</p>`;
    const full = c.isco.filter((i) => i.precision === 4), part = c.isco.filter((i) => i.precision < 4);
    const isco = !c.isco.length ? `<p class="small muted">Aucun code ISCO-08 trouvé par les intitulés de profession.</p>`
      : `${full.length ? `<div class="scroll"><table><tr><th>ISCO-08</th><th>Groupe de base</th><th class="num">Intitulés de profession</th></tr>
        ${full.map((i) => `<tr><td>${esc(i.code)}</td><td>${esc(i.libelle || "")}<div class="muted small">${qualifText(i.qualifications)}</div></td><td class="num">${fmt(i.n_intitules)}</td></tr>`).join("")}</table></div>` : ""}
        ${part.length ? `<p class="small muted">Codes partiels (l'intitulé ne permet pas d'aller jusqu'au groupe de base) : ${part.map((i) => `${esc(i.code.slice(0, i.precision))}${"x".repeat(4 - i.precision)} (${fmt(i.n_intitules)} intitulé${i.n_intitules > 1 ? "s" : ""})`).join(", ")}.</p>` : ""}`;
    // a code found from the job's name (the Onisep sheet gives none): said so, with the method's check in counts
    const how = { intitule_dares: "un intitulé de profession de la Dares", appellation_rome: "une appellation du ROME (France Travail)" };
    const k = c.controle || {};
    const found = c.origine === "analogie" ? `<p class="small warn">Code choisi par analogie avec un métier voisin, la fiche Onisep ne donnant pas de code ROME : ${esc(c.motif || "")}.</p>`
      : c.origine && c.origine !== "onisep" ? `<p class="small warn">Code retrouvé par le nom du métier, identique à ${how[c.origine] || "un intitulé"} : la fiche Onisep ne donne pas de code ROME. C'est moins sûr qu'un code donné par l'Onisep${k.n_metiers ? ` : sur ${fmt(k.n_metiers)} métiers dont l'Onisep donne le code, cette méthode retrouve un bon code pour ${fmt(k.n_ok)}` : ""}.</p>` : "";
    return `<h3>Fiche ROME ${esc(c.rome)} · ${esc(c.intitule || "")}</h3>${found}
      <p class="small"><strong>Famille professionnelle FAP-2021</strong> (Dares, table officielle code à code)</p>
      ${fam(c.fap2021, (f) => f.fap86 ? ` <span class="muted">(${esc(f.fap86)} ${esc(f.libelle86 || "")})</span>` : "")}
      <p class="small"><strong>Famille FAP-2009</strong>, celle des projections « Les métiers en 2030 » (Dares, table officielle code à code)</p>
      ${fam(c.fap2009, (f) => f.libelle87 ? ` <span class="muted">(${esc(f.fap87)} ${esc(f.libelle87)})</span>` : "")}
      <p class="small"><strong>Codes ISCO-08 possibles</strong> (classification internationale du BIT), retrouvés par les intitulés de profession : la Dares relie l'intitulé au code ROME, l'Insee le code en ISCO. Le nombre d'intitulés n'est pas une part des emplois.</p>
      ${isco}`;
  };
  // lot 1, PR 10: the families and codes (FAP, ISCO-08) are folded, never removed: the testers read them as jargon
  return `<div class="card">${head}<details class="more-card"><summary>Voir les familles et les codes officiels</summary>${codes.map(one).join("")}
    <p class="muted small">Sources : Onisep (codes ROME de la fiche métier) ; Dares (passages ROME → FAP-2021 et FAP-2009, intitulés de profession) ; Insee (codification ISCO-08 des intitulés) ; France Travail (appellations du ROME, pour les métiers sans code Onisep). Licence Ouverte.</p></details></div>`;
}

// ---- Comprendre l'appel and the selectivity matrix (owner's request, 2026-11-09) ----
// SupCompass prepares the choice of vœux: the student has no rank yet, and none is asked. Every figure is published (SIES)
// or computed from published counts and says so; never a chance of admission.
const APPEL_NOTE = "Des campagnes passées, pas des chances d'admission : vous n'avez pas encore de rang, ces chiffres montrent comment la liste a été appelée.";
// how far the list of one formation was called, campaign by campaign (the calling groups split the candidates: their
// last-called ranks add up to the candidates called)
function appelCard(rows) {
  const ok = (rows || []).filter((r) => r.groupes && r.groupes.length);
  if (!ok.length) return "";
  const last = ok[ok.length - 1], called = last.groupes.reduce((a, g) => a + g.rang, 0);
  const lead = last.toute_la_liste
    ? `En ${esc(last.session)}, <strong>toute la liste</strong> des ${fmt(last.classes)} candidats classés a reçu une proposition`
    : last.profondeur != null ? `En ${esc(last.session)}, <strong>${pct(last.profondeur)}</strong> des ${fmt(last.classes)} candidats classés ont reçu une proposition` : "";
  const places = last.places && called > last.places ? `, pour ${fmt(last.places)} places : la liste descend bien au-delà du nombre de places, car beaucoup de candidats choisissent une autre formation` : "";
  return `<div class="card"><h2>Jusqu'où la liste a-t-elle été appelée ?</h2>
    <p class="small">Le jury classe les candidats ; les propositions partent dans l'ordre du classement, au fil des places libérées. Le rang du dernier appelé de chaque groupe d'appel est publié.</p>
    ${lead ? `<p class="info">${lead}${places}.</p>` : ""}
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Session</th><th class="num">Candidats</th><th class="num">Classés</th><th>Rang du dernier appelé</th><th class="num">Jusqu'où la liste a été appelée</th><th class="num">Places</th></tr>
      ${ok.map((r) => `<tr><td data-label="Session">${esc(r.session)}</td><td class="num" data-label="Candidats">${fmt(r.candidats)}</td><td class="num" data-label="Classés">${fmt(r.classes)}</td>
        <td data-label="Rang du dernier appelé">${r.groupes.map((g) => `${esc(g.label || "Groupe")} : <span class="nowrap">rang ${fmt(g.rang)}</span>`).join("<br>")}</td>
        <td class="num" data-label="Jusqu'où la liste a été appelée">${r.toute_la_liste ? "toute la liste" : pct(r.profondeur)}</td><td class="num" data-label="Places">${fmt(r.places)}</td></tr>`).join("")}</table></div>
    <p class="muted small">${APPEL_NOTE} Jusqu'où la liste a été appelée : somme des rangs des derniers appelés de chaque groupe, divisée par le nombre de classés (calcul à partir des effectifs publiés). <a href="#/comprendre">Comprendre l'appel →</a></p></div>`;
}
async function viewComprendre() {
  const d = await api("/api/comprendre");
  if (!/^#\/comprendre/.test(location.hash)) return;
  const ts = d.types.filter((t) => t.n >= 20);
  const bts = d.types.find((t) => t.diplome === "BTS - BTSA - BTSM");
  $view.innerHTML = `<div class="card"><h1>Comprendre l'appel</h1>
    <p>Avant de choisir vos vœux, trois chiffres à ne pas confondre :</p>
    <ul class="offer-list">
      <li><strong>Le taux d'accès</strong> : la part des candidats qui ont reçu une proposition. Un taux bas peut venir du grand nombre de candidats pour les places, pas seulement du niveau demandé (voir la <a href="#/selectivite">vraie sélectivité</a>).</li>
      <li><strong>Le rang du dernier appelé</strong> : chaque formation classe ses candidats ; les propositions partent dans l'ordre du classement, au fil des places libérées. Le rang du dernier candidat appelé l'an passé est publié pour chaque groupe d'appel.</li>
      <li><strong>La position en liste d'attente</strong> : elle n'existera qu'après vos vœux, pendant la phase d'admission, et elle avance chaque jour au fil des désistements.</li>
    </ul>
    <p class="muted small">${APPEL_NOTE}</p></div>
  <div class="card"><h2>Jusqu'où les listes ont été appelées, par type de diplôme (${esc(d.session)})</h2>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Type de diplôme</th><th class="num">Formations</th><th class="num">Jusqu'où la liste a été appelée (médiane)</th><th class="num">Formations ayant appelé toute leur liste</th></tr>
      ${ts.map((t) => `<tr><td data-label="Type de diplôme">${esc(t.diplome)}</td><td class="num" data-label="Formations">${fmt(t.n)}</td>
        <td class="num" data-label="Jusqu'où la liste a été appelée (médiane)">${pct(t.profondeur_mediane)}</td><td class="num" data-label="Formations ayant appelé toute leur liste">${pct(t.part_toute_la_liste)}</td></tr>`).join("")}</table></div>
    <p class="muted small">Médiane sur les formations du type, calculée à partir des effectifs publiés (rangs des derniers appelés et candidats classés). Types d'au moins 20 formations.</p></div>
  <div class="card"><h2>Quand arrivent les propositions ?</h2>
    ${bts && bts.calendrier[0] != null ? `<p class="info">Une liste qui bouge lentement les premiers jours est normale : dans la moitié des BTS, ${pct(bts.calendrier[0])} au plus des futurs admis avaient leur proposition dès l'ouverture ; ${pct(bts.calendrier[1])} l'avaient avant les résultats du bac.</p>` : ""}
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Type de diplôme</th><th class="num">Dès l'ouverture</th><th class="num">Avant les résultats du bac</th><th class="num">Avant la fin de la phase principale</th></tr>
      ${ts.map((t) => `<tr><td data-label="Type de diplôme">${esc(t.diplome)}</td>${t.calendrier.map((v, i) => `<td class="num" data-label="${["Dès l'ouverture", "Avant les résultats du bac", "Avant la fin de la phase principale"][i]}">${pct(v)}</td>`).join("")}</tr>`).join("")}</table></div>
    <p class="muted small">Part des admis qui avaient déjà reçu leur proposition à chaque étape, publiée pour chaque formation ; médiane sur les formations du type qui ont des admis.</p></div>`;
  $view.dataset.rendered = "comprendre";
}
// ---- Observatoire (owner, 2026-11-19): three national overviews of the published figures, read for nobody ----
// Vœux par place = the vœux / the places SUMMED over a type (vœux, never people); the access rate is the MEDIAN of the
// official rates (never recomputed); the same-académie share counts nouveau bachelier admits (people) only. Never a chance: the
// académies and the types are ranked, never the formations. Île-de-France's three académies are ONE bubble on the map (their
// centres are a few km apart: `ile_de_france`, summed by the server), each keeps its row in the table.
const OBS_DEFAULT = ["BTS - BTSA - BTSM", "Licence", "BUT", "Écoles d'ingénieurs", "CPGE scientifique"];
const OBS_MAX = 5;
// five series at most, each with its own dash AND a shade of the ramp that keeps 3:1 on the card (--c5/--c6 are too light)
const OBS_SERIES = [["var(--c1)", ""], ["var(--c2)", "6 4"], ["var(--c3)", "2 3"], ["var(--c4)", "8 3 2 3"], ["var(--c2)", "12 3 2 3 2 3"]];   // reviewer: five distinct dashes (the fifth was dotted like the third)
const obsUI = { types: null, type: null };
const obsArrow = (a, b, f) => `${f(a)} → ${f(b)}`;
// four classes from the quartiles of the values shown (fixed rule): radius AND shade, never the shade alone
function obsClasses(values) {
  const v = values.filter((x) => x != null).sort((a, b) => a - b);
  if (!v.length) return { cuts: [], of: () => 0 };
  const q = (p) => v[Math.min(v.length - 1, Math.floor(p * v.length))];
  const cuts = [q(0.25), q(0.5), q(0.75)];
  return { cuts, of: (x) => cuts.filter((c) => x >= c).length };
}
const OBS_R = [6, 8, 10.5, 13], OBS_FILL = ["var(--c5)", "var(--c4)", "var(--c2)", "var(--c1)"];
// a light silhouette of metropolitan France and Corsica (coarse coastline and borders, [lat, lon]): a landmark only, never data
const OBS_FRANCE = [[[51.05, 2.37], [50.7, 3.2], [50.3, 4.1], [50.14, 4.83], [49.8, 4.9], [49.52, 5.8], [49.1, 6.7], [48.97, 8.23], [48.58, 7.8],
  [47.59, 7.59], [47.0, 6.9], [46.4, 6.1], [46.2, 6.1], [45.83, 6.86], [45.1, 7.0], [44.1, 7.7], [43.78, 7.5], [43.55, 7.0], [43.1, 5.9], [43.3, 5.37],
  [43.45, 4.6], [43.4, 3.7], [43.0, 3.05], [42.5, 3.13], [42.45, 2.4], [42.7, 1.8], [42.8, 0.6], [43.0, -0.8], [43.37, -1.78], [44.0, -1.4],
  [44.66, -1.25], [45.6, -1.2], [46.15, -1.15], [46.5, -1.8], [47.27, -2.2], [47.5, -3.1], [47.85, -4.3], [48.4, -4.79], [48.75, -3.5],
  [48.65, -2.0], [48.64, -1.5], [49.7, -1.9], [49.65, -1.3], [49.3, -0.3], [49.5, 0.1], [49.93, 1.08], [50.2, 1.6], [50.73, 1.6], [50.95, 1.85]],
  [[43.0, 9.4], [42.7, 9.45], [42.0, 9.55], [41.4, 9.2], [41.6, 8.8], [42.0, 8.6], [42.5, 8.65], [42.97, 9.35]]];
function obsMap(d, typ) {
  const dem = d.demande[typ] || {}, idf = d.ile_de_france, idfRow = idf.demande[typ];
  const pts = d.academies.filter((a) => a.metropole && !idf.academies.includes(a.cle) && dem[a.cle] && dem[a.cle].voeux_par_place != null)
    .map((a) => ({ name: a.academie, lat: a.lat, lon: a.lon, v: dem[a.cle].voeux_par_place }));
  if (idfRow && idfRow.voeux_par_place != null) {
    const ia = d.academies.filter((a) => idf.academies.includes(a.cle) && a.lat != null);
    if (ia.length) pts.push({ name: "Île-de-France (Paris, Créteil, Versailles)", lat: ia.reduce((s, a) => s + a.lat, 0) / ia.length,
      lon: ia.reduce((s, a) => s + a.lon, 0) / ia.length, v: idfRow.voeux_par_place });
  }
  const cls = obsClasses(pts.map((p) => p.v));
  const X = (lon) => 16 + (lon + 5.2) * 0.688 * 32, Y = (lat) => 16 + (51.3 - lat) * 32;
  const land = OBS_FRANCE.map((ring) => `<path class="obs-land" d="${ring.map(([la, lo], i) => `${i ? "L" : "M"}${X(lo).toFixed(1)},${Y(la).toFixed(1)}`).join("")}Z"/>`).join("");
  const named = new Set([...pts].sort((a, b) => b.v - a.v).filter((_, i, a) => i < 3 || i >= a.length - 3).map((p) => p.name));
  const dots = pts.sort((a, b) => a.v - b.v).map((p) => { const k = cls.of(p.v);
    return `<circle cx="${X(p.lon).toFixed(1)}" cy="${Y(p.lat).toFixed(1)}" r="${OBS_R[k]}" fill="${OBS_FILL[k]}" stroke="var(--surface)" stroke-width="1.5"><title>${esc(p.name)} : ${fmt(p.v, 1)} vœux par place</title></circle>`; }).join("")
    + pts.filter((p) => named.has(p.name)).map((p) => { const left = p.lon > 5.5;
      return `<text class="obs-name" x="${(X(p.lon) + (left ? -16 : 16)).toFixed(1)}" y="${(Y(p.lat) + 4).toFixed(1)}" text-anchor="${left ? "end" : "start"}">${esc(p.name.startsWith("Île-de-France") ? "Île-de-France" : p.name)} ${fmt(p.v, 1)}</text>`; }).join("");
  const bounds = cls.cuts.length ? [`moins de ${fmt(cls.cuts[0], 1)}`, `${fmt(cls.cuts[0], 1)} à ${fmt(cls.cuts[1], 1)}`, `${fmt(cls.cuts[1], 1)} à ${fmt(cls.cuts[2], 1)}`, `${fmt(cls.cuts[2], 1)} et plus`] : [];
  return `<svg class="obs-map" viewBox="0 0 360 340" role="img" aria-label="Carte des académies de métropole : vœux par place, ${esc(typ)}, campagne ${esc(d.session)}">${land}${dots}</svg>
    <div class="legend obs-legend">${bounds.map((b, k) => `<span><svg viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="${OBS_R[k]}" fill="${OBS_FILL[k]}"/></svg>${b}</span>`).join("")}<span class="muted">vœux par place</span></div>`;
}
function obsDemande(d) {
  const typ = obsUI.type, dem = d.demande[typ] || {};
  const rows = d.academies.map((a) => ({ a, x: dem[a.cle] })).filter((r) => r.x);
  const known = rows.filter((r) => r.x.voeux_par_place != null).sort((p, q) => q.x.voeux_par_place - p.x.voeux_par_place);
  const apart = d.academies.filter((a) => !a.metropole && dem[a.cle]);
  const hi = known[0], lo = known[known.length - 1];
  const line = (r) => `<tr><td data-label="Académie">${esc(acadLabel(r.a.academie))}</td><td class="num" data-label="Vœux par place">${r.x.voeux_par_place == null ? "trop peu de formations" : fmt(r.x.voeux_par_place, 1)}</td>
    <td class="num" data-label="Vœux">${fmt(r.x.voeux)}</td><td class="num" data-label="Places">${fmt(r.x.places)}</td><td class="num" data-label="Formations">${fmt(r.x.formations)}</td></tr>`;
  return `${hi && lo && hi !== lo ? `<p>De <strong>${fmt(lo.x.voeux_par_place, 1)}</strong> vœux par place (${esc(acadLabel(lo.a.academie))}) à <strong>${fmt(hi.x.voeux_par_place, 1)}</strong> (${esc(acadLabel(hi.a.academie))}).</p>` : ""}
    ${obsMap(d, typ)}
    ${apart.length ? `<p class="small">Pas sur la carte (outre-mer, étranger) : ${apart.map((a) => `${esc(acadLabel(a.academie))} ${dem[a.cle].voeux_par_place == null ? "(trop peu de formations)" : fmt(dem[a.cle].voeux_par_place, 1)}`).join(" · ")}.</p>` : ""}
    <details><summary>Toutes les académies (${fmt(rows.length)})</summary>
      <div class="scroll"><table class="stack"><tr class="stack-head"><th>Académie</th><th class="num">Vœux par place</th><th class="num">Vœux</th><th class="num">Places</th><th class="num">Formations</th></tr>
      ${[...known, ...rows.filter((r) => r.x.voeux_par_place == null)].map(line).join("")}</table></div></details>`;
}
function obsTrend(d) {
  const sel = d.tendances.filter((t) => obsUI.types.includes(t.diplome));
  const series = sel.map((t, i) => ({ name: t.diplome, color: OBS_SERIES[i][0], dash: OBS_SERIES[i][1], values: t.serie.map((x) => x.voeux_par_place) }));
  const max = Math.max(1, ...series.flatMap((x) => x.values.filter((v) => v != null)));
  return lineChart(d.sessions, series, { yMax: 4 * Math.ceil(max / 4), unit: "" }) + lineLegend(series);
}
// ---- Observatoire: who the admits are (owner, 2026-11-19). Published counts summed by the server over coherent rows; the
// rows of types under d.seuils.type formations are folded; the girls' share among the vœux sits beside the admits' (vœux, not
// people); bac routes keep their --voie-* token AND their name; mentions use the neutral ramp. Never a chance or a requirement.
// the OBS_SHOWN types with the most formations are shown (in the section's own order), the others folded: a fixed rule, never a figure
const OBS_SHOWN = 10;
function obsSplit(rows, d, line) {
  const top = new Set([...rows].sort((a, b) => b.formations - a.formations || a.diplome.localeCompare(b.diplome, "fr")).slice(0, OBS_SHOWN).map((r) => r.diplome));
  const big = rows.filter((r) => top.has(r.diplome)), small = rows.filter((r) => !top.has(r.diplome));
  return `<ul class="obs-bars">${big.map(line).join("")}</ul>`
    + (small.length ? `<details><summary>Les autres types de formation (${fmt(small.length)})</summary><ul class="obs-bars">${small.map(line).join("")}</ul></details>` : "");
}
const obsKnown = (rows, key) => rows.filter((r) => r.diplome !== OBS_TOUS && key(r) != null);
const OBS_TOUS = "Toutes les formations";
function obsFilles(d) {
  const rows = obsKnown(d.filles, (r) => r.part_admis), tous = d.filles.find((r) => r.diplome === d.tous);
  const big = rows.filter((r) => r.formations >= d.seuils.type);   // the gap is read on the types followed elsewhere on the page
  const gap = big.length ? Math.max(...big.map((r) => Math.abs(r.part_admis - r.part_voeux))) : null;
  const line = (r) => `<li><span class="obs-lab">${esc(r.diplome)}</span><span class="obs-dumb" aria-hidden="true"><i class="obs-mid"></i><i class="obs-v" style="left:${r.part_voeux}%"></i><i class="obs-a" style="left:${r.part_admis}%"></i></span><span class="obs-val"><strong>${pct(r.part_admis)}</strong><span class="small muted">vœux ${pct(r.part_voeux)}</span></span></li>`;
  return `<section class="card" aria-labelledby="obs-f"><h2 id="obs-f">Filles et garçons (${esc(d.session)})</h2>
    ${tous && tous.part_admis != null ? `<p>Les filles font <strong>${pct(tous.part_admis)}</strong> des admis (${fmt(tous.admises)} sur ${fmt(tous.admis)}).</p>` : ""}
    <div class="legend obs-key"><span><i class="obs-v-key"></i>parmi les vœux</span><span><i class="obs-a-key"></i>parmi les admis</span><span class="muted">trait : 50 %</span></div>
    ${obsSplit(rows, d, line)}
    ${gap != null ? `<p class="small">Dans les types d'au moins ${fmt(d.seuils.type)} formations, la part de filles parmi les admis est à ${fmt(gap, 1)} points au plus de leur part parmi les vœux.</p>` : ""}
    <p class="muted small">Filles parmi tous les admis, et vœux de filles parmi tous les vœux confirmés : des vœux, pas des personnes. Calcul sur les effectifs publiés, additionnés par type.</p></section>`;
}
function obsBacs(d) {
  const rows = obsKnown(d.bacs, (r) => r.part_general), tous = d.bacs.find((r) => r.diplome === d.tous);
  const seg = (r) => [["general", "bg"], ["techno", "bt"], ["pro", "bp"]].map(([k, v]) => `<i style="width:${r[`part_${k}`]}%;background:var(--voie-${v})"></i>`).join("");
  const line = (r) => `<li><span class="obs-lab">${esc(r.diplome)}</span><span class="obs-stack" aria-hidden="true">${seg(r)}</span><span class="obs-val"><strong>${pct(r.part_techno)} · ${pct(r.part_pro)}</strong><span class="sr-only">bac techno, bac pro ; bac général ${pct(r.part_general)}</span></span></li>`;
  return `<section class="card" aria-labelledby="obs-b"><h2 id="obs-b">Bac général, techno ou pro : le bac des admis (${esc(d.session)})</h2>
    ${tous && tous.part_techno != null ? `<p>Parmi les admis nouveaux bacheliers, <strong>${pct(tous.part_techno)}</strong> ont un bac techno et <strong>${pct(tous.part_pro)}</strong> un bac pro.</p>` : ""}
    <div class="legend obs-key"><span><i style="background:var(--voie-bg)"></i>bac général</span><span><i style="background:var(--voie-bt)"></i>bac techno</span><span><i style="background:var(--voie-bp)"></i>bac pro</span><span class="muted">à droite : techno · pro</span></div>
    ${obsSplit(rows, d, line)}
    <p class="small">Une part faible veut dire « rare », jamais « fermé ». Chaque fiche formation donne aussi le chiffre de votre bac, dans « Y entrer ».</p>
    <p class="muted small">Admis nouveaux bacheliers seulement (ceux qui viennent d'avoir leur bac), calcul sur les effectifs publiés, additionnés par type.</p></section>`;
}
const OBS_MENTIONS = [["sansmention", "sans mention", "var(--c6)"], ["ab", "assez bien", "var(--c5)"], ["b", "bien", "var(--c4)"], ["tb", "très bien", "var(--c2)"], ["tbf", "félicitations", "var(--c1)"]];
function obsMentions(d) {
  const rows = d.mentions.filter((r) => r.diplome !== d.tous && r.lecture), tous = d.mentions.find((r) => r.diplome === d.tous);
  const line = (r) => `<li><span class="obs-lab">${esc(r.diplome)}</span><span class="obs-stack" aria-hidden="true">${OBS_MENTIONS.map(([k, , c]) => `<i style="width:${r.lecture.parts[k]}%;background:${c}"></i>`).join("")}</span><span class="obs-val"><strong>${r.avant.tb_plus == null ? "" : `${pct(r.avant.tb_plus)} → `}${pct(r.lecture.tb_plus)}</strong><span class="sr-only">très bien ou plus${r.avant.tb_plus == null ? "" : `, ${esc(d.mentions_avant)} puis ${esc(d.session)}`} ; ${OBS_MENTIONS.map(([k, lab]) => `${lab} ${pct(r.lecture.parts[k])}`).join(", ")}</span></span></li>`;
  return `<section class="card" aria-labelledby="obs-m"><h2 id="obs-m">Les mentions au bac des admis (${esc(d.mentions_avant)} → ${esc(d.session)})</h2>
    ${tous && tous.lecture ? `<p><strong>${pct(tous.lecture.tb_plus)}</strong> des admis nouveaux bacheliers avaient « très bien » ou « très bien avec félicitations » en ${esc(d.session)}${tous.avant.tb_plus != null ? ` (${pct(tous.avant.tb_plus)} en ${esc(d.mentions_avant)})` : ""}.</p>` : ""}
    <div class="legend obs-key">${OBS_MENTIONS.map(([, lab, c]) => `<span><i style="background:${c}"></i>${lab}</span>`).join("")}<span class="muted">à droite : très bien ou plus, ${esc(d.mentions_avant)} → ${esc(d.session)}</span></div>
    ${obsSplit(rows, d, line)}
    <p class="small">Une mention fréquente chez les admis ne dit pas qu'elle est exigée : ce sont les admis passés, ni le niveau demandé ni vos chances.</p>
    <p class="muted small">Admis nouveaux bacheliers seulement. Les mentions ne sont pas publiées par série de bac. Calcul sur les effectifs publiés, additionnés par type ; le nombre de formations d'un type change d'une année à l'autre.</p></section>`;
}
async function viewObservatoire() {
  // owner, 2026-11-20: opened at /observatoire, the server's summary ([data-seo]) stays until the page replaces it
  if (!$view.querySelector("[data-seo]")) $view.innerHTML = `<div class="card"><h1>Observatoire des formations</h1><p class="muted">Chargement des chiffres…</p></div>`;
  const d = await api("/api/observatoire");
  // still on this page: the hash route, or the indexable address /observatoire (no hash yet)
  if (!/^#\/observatoire/.test(location.hash) && !(!location.hash.slice(1) && /^\/observatoire\/?$/.test(location.pathname))) return;
  const first = d.sessions[0], last = d.session, T = d.tendances;
  if (!obsUI.types) obsUI.types = OBS_DEFAULT.filter((t) => T.some((x) => x.diplome === t));
  const types = [d.tous, ...T.map((t) => t.diplome), ...Object.keys(d.demande).filter((k) => k !== d.tous && !T.some((t) => t.diplome === k)).sort((a, b) => a.localeCompare(b, "fr"))]
    .filter((k) => d.demande[k] && Object.values(d.demande[k]).some((x) => x.voeux_par_place != null));
  if (!types.includes(obsUI.type)) obsUI.type = types.includes("BUT") ? "BUT" : types[0];
  const up = T.filter((t) => t.serie[t.serie.length - 1].voeux_par_place > t.serie[0].voeux_par_place).length;
  const tous = d.proximite.find((p) => p.diplome === d.tous);
  const prox = d.proximite.filter((p) => p.diplome !== d.tous && p.part_meme_academie != null);
  const bar = (p) => `<li><span class="obs-lab">${esc(p.diplome)}</span><span class="obs-bar" aria-hidden="true"><i style="width:${Math.max(0, Math.min(100, p.part_meme_academie))}%"></i></span><strong>${pct(p.part_meme_academie)}</strong></li>`;
  const big = prox.filter((p) => p.formations >= d.seuils.type), small = prox.filter((p) => p.formations < d.seuils.type);
  const noProx = d.proximite.filter((p) => p.part_meme_academie == null).length;
  $view.innerHTML = `<section class="hero obs-hero"><h1>Observatoire des formations</h1>
      <p>Six regards sur toutes les formations, à partir des chiffres publiés par le ministère (SIES) pour les campagnes ${esc(first)} à ${esc(last)}.</p>
      <p class="small">Ces chiffres décrivent les années passées pour l'ensemble des candidats. Ce ne sont pas vos chances.</p></section>
    <section class="card" aria-labelledby="obs-t"><h2 id="obs-t">Les vœux par place, de ${esc(first)} à ${esc(last)}</h2>
      <p>Les vœux par place ont augmenté dans <strong>${fmt(up)}</strong> types de formation sur ${fmt(T.length)}.</p>
      <div id="obs-trend">${obsTrend(d)}</div>
      <details class="obs-choose"><summary>Choisir les types du graphique (${OBS_MAX} au plus)</summary>
      <div class="obs-pills" role="group" aria-label="Types de formation sur le graphique (${OBS_MAX} au plus)">${T.map((t) =>
        `<button type="button" data-obs-type="${esc(t.diplome)}" aria-pressed="${obsUI.types.includes(t.diplome)}">${esc(t.diplome)}</button>`).join("")}</div>
      <p class="small muted" id="obs-max" hidden>${OBS_MAX} types au plus sur le graphique : retirez-en un d'abord.</p></details>
      <details><summary>Le tableau de tous les types (${fmt(T.length)})</summary>
      <div class="scroll"><table class="stack"><tr class="stack-head"><th>Type de formation</th><th class="num">Formations</th><th class="num">Vœux par place</th><th class="num">Taux d'accès médian</th></tr>
      ${T.map((t) => { const a = t.serie[0], b = t.serie[t.serie.length - 1];
        return `<tr><td data-label="Type de formation">${esc(t.diplome)}</td><td class="num" data-label="Formations">${obsArrow(a.formations, b.formations, fmt)}</td>
        <td class="num" data-label="Vœux par place">${obsArrow(a.voeux_par_place, b.voeux_par_place, (v) => fmt(v, 1))}</td><td class="num" data-label="Taux d'accès médian">${obsArrow(a.taux_median, b.taux_median, pct)}</td></tr>`; }).join("")}</table></div></details>
      <p class="muted small">Vœux par place : les vœux de la phase principale divisés par les places, additionnés sur toutes les formations du type. Ce sont des vœux, pas des personnes. ${esc(d.prudence)}</p>
      <p class="muted small">Taux d'accès médian : la moitié des formations du type ont un taux d'accès officiel plus haut, l'autre moitié plus bas. Le nombre de formations change d'une année à l'autre. Types d'au moins ${fmt(d.seuils.type)} formations chaque année.</p></section>
    <section class="card" aria-labelledby="obs-d"><h2 id="obs-d">Où la demande est la plus forte (${esc(last)})</h2>
      <label class="obs-select">Type de formation <select id="obs-type">${types.map((k) => `<option value="${esc(k)}"${k === obsUI.type ? " selected" : ""}>${esc(k)}</option>`).join("")}</select></label>
      <div id="obs-dem">${obsDemande(d)}</div>
      <p class="muted small">Vœux par place de chaque académie : vœux et places additionnés sur ses formations du type. Pas de chiffre sous ${fmt(d.seuils.academie_formations)} formations ou ${fmt(d.seuils.academie_places)} places. Une demande forte ne dit pas qu'une formation est difficile : regardez son taux d'accès.</p></section>
    <section class="card" aria-labelledby="obs-p"><h2 id="obs-p">Rester près de chez soi ou partir loin (${esc(last)})</h2>
      ${tous && tous.part_meme_academie != null ? `<p><strong>${pct(tous.part_meme_academie)}</strong> des admis nouveaux bacheliers venaient de l'académie de leur formation (${fmt(tous.meme_academie)} sur ${fmt(tous.admis_neobac)}).</p>` : ""}
      <ul class="obs-bars">${big.map(bar).join("")}</ul>
      ${small.length ? `<details><summary>Les types de moins de ${fmt(d.seuils.type)} formations (${fmt(small.length)})</summary><ul class="obs-bars">${small.map(bar).join("")}</ul></details>` : ""}
      <p class="muted small">Part des admis nouveaux bacheliers (ceux qui viennent d'avoir leur bac) qui venaient de la même académie que la formation, calculée sur les effectifs publiés. Elle n'est pas publiée pour les autres admis. ${noProx ? `${fmt(noProx)} type${noProx > 1 ? "s ont" : " a"} moins de ${fmt(d.seuils.min_neobac)} admis nouveaux bacheliers ou moins de ${fmt(d.seuils.proximite_formations)} formations : pas de chiffre.` : ""}</p></section>
    ${obsFilles(d)}
    ${obsBacs(d)}
    ${obsMentions(d)}
    ${nextSteps("observatoire")}`;
  $view.dataset.rendered = "observatoire";
  $view.querySelectorAll("[data-obs-type]").forEach((b) => { b.onclick = () => {
    const t = b.dataset.obsType, on = obsUI.types.includes(t);
    const note = document.getElementById("obs-max");
    if (!on && obsUI.types.length >= OBS_MAX) { if (note) note.hidden = false; return; }
    if (note) note.hidden = true;
    obsUI.types = on ? obsUI.types.filter((x) => x !== t) : [...obsUI.types, t];
    b.setAttribute("aria-pressed", String(!on));
    const box = document.getElementById("obs-trend");
    if (box) box.innerHTML = obsTrend(d);
  }; });
  const s = document.getElementById("obs-type");
  if (s) s.onchange = () => { obsUI.type = s.value; const box = document.getElementById("obs-dem"); if (box) box.innerHTML = obsDemande(d); };
}
// the selectivity matrix: official access rate x share of nouveau bachelier admits with "Bien" or better; the quadrant lines
// are the medians of the selection (fixed rule); names describe a position, never a cause or a chance
const SEL_Q = ["Plus accessible", "Très demandée", "Admis souvent mentionnés", "Très sélective"];
const SEL_Q_HELP = { "Plus accessible": "taux d'accès élevé, admis moins souvent mentionnés que la médiane", "Très demandée": "taux d'accès bas, admis moins souvent mentionnés : beaucoup de candidats pour les places",
  "Admis souvent mentionnés": "taux d'accès élevé, admis souvent mentionnés : peu de candidats, mais de bons dossiers", "Très sélective": "taux d'accès bas et admis souvent mentionnés" };
function selPlot(d, sel) {
  const W = 640, H = 420, L = 48, B = 40, T = 12, R = 28, x = (v) => L + (W - L - R) * v / 100, y = (v) => H - B - (H - B - T) * v / 100;
  const ticks = [0, 25, 50, 75, 100];
  const dots = d.formations.map((f) => `<circle class="sel-dot${f.cod_aff_form === sel ? " on" : ""}" data-pick="${esc(f.cod_aff_form)}" cx="${x(f.taux_acces_ens).toFixed(1)}" cy="${y(f.part_bien_plus).toFixed(1)}" r="${f.cod_aff_form === sel ? 6 : 3.5}"><title>${esc(f.etablissement)} — ${esc(f.formation)} : taux d'accès ${pct(f.taux_acces_ens)}, admis avec mention Bien ou mieux ${pct(f.part_bien_plus)}</title></circle>`).join("");
  const mx = x(d.mediane_taux), my = y(d.mediane_bien);
  return `<svg class="sel-plot" viewBox="0 0 ${W} ${H}" role="img" aria-label="Formations placées selon leur taux d'accès et la part de leurs admis avec mention Bien ou mieux">
    ${ticks.map((t) => `<line x1="${x(t)}" y1="${y(0)}" x2="${x(t)}" y2="${y(100)}" class="sel-grid"/><text x="${x(t)}" y="${H - B + 16}" text-anchor="middle" class="sel-tick">${t} %</text>
      <line x1="${x(0)}" y1="${y(t)}" x2="${x(100)}" y2="${y(t)}" class="sel-grid"/><text x="${L - 6}" y="${y(t) + 4}" text-anchor="end" class="sel-tick">${t} %</text>`).join("")}
    <line x1="${mx}" y1="${y(0)}" x2="${mx}" y2="${y(100)}" class="sel-med"/><line x1="${x(0)}" y1="${my}" x2="${x(100)}" y2="${my}" class="sel-med"/>
    <text x="${x(99)}" y="${y(3)}" text-anchor="end" class="sel-q">Plus accessible</text><text x="${x(1)}" y="${y(3)}" class="sel-q">Très demandée</text>
    <text x="${x(99)}" y="${y(96)}" text-anchor="end" class="sel-q">Admis souvent mentionnés</text><text x="${x(1)}" y="${y(96)}" class="sel-q">Très sélective</text>
    ${dots}
    <text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" class="sel-axis">Taux d'accès officiel</text>
    <text x="12" y="${(T + H - B) / 2}" text-anchor="middle" transform="rotate(-90 12 ${(T + H - B) / 2})" class="sel-axis">Admis avec mention Bien ou mieux</text></svg>`;
}
// the formations the matrix cannot place are NAMED with their reason and their published counts (a quarter of the
// formations of a campaign: nearly all have fewer than 10 nouveau bachelier admits, so one person would move the share a lot)
function selWhy(f, d) {
  if (f.raison === "aucun_admis") return `aucun admis en ${esc(d.session)}`;
  if (f.raison === "peu_neobac") return `${fmt(f.admis_neobac)} admis ${f.admis_neobac > 1 ? "nouveaux bacheliers" : "nouveau bachelier"} sur ${fmt(f.admis)} admis`;
  return f.raison === "sans_taux" ? "taux d'accès non publié" : "mentions des admis non publiées";
}
function selApart(d) {
  const n = d.non_placees.length;
  if (!n) return "";
  const parts = [["peu_neobac", `moins de ${fmt(d.min_admis)} admis nouveaux bacheliers`], ["aucun_admis", "aucun admis"], ["sans_taux", "taux d'accès non publié"], ["sans_mentions", "mentions non publiées"]]
    .filter(([k]) => d.raisons[k]).map(([k, t]) => `${fmt(d.raisons[k])} : ${t}`).join(" · ");
  const row = (f) => `<tr><td data-label="Formation"><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.formation)} · ${esc(f.ville)}</div><div class="small">Non placée : ${selWhy(f, d)}</div></td>
    <td class="num" data-label="Taux d'accès">${pct(f.taux_acces_ens)}</td><td class="num" data-label="Candidats par place">${fmt(f.candidats_par_place, 1)}</td></tr>`;
  return `<details class="card" id="sel-apart"><summary><strong>Non placées sur le graphique</strong> · ${fmt(n)} formation${n > 1 ? "s" : ""} <span class="muted small">(${parts})</span></summary>
    <p class="small">La part des mentions n'est publiée que pour les admis nouveaux bacheliers (les élèves qui viennent d'obtenir leur bac). Avec moins de ${fmt(d.min_admis)} nouveaux bacheliers admis, une seule personne déplace beaucoup ce chiffre : la formation n'est pas placée, mais son taux d'accès officiel reste indiqué ici. Les autres admis ne sont pas des nouveaux bacheliers (réorientation, reprise d'études…) ; leurs mentions ne sont pas publiées.</p>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th class="num">Taux d'accès</th><th class="num">Candidats par place</th></tr>${d.non_placees.slice(0, 40).map(row).join("")}</table></div>
    ${n > 40 ? `<p class="muted small">40 premières sur ${fmt(n)} (ordre alphabétique) ; choisissez une mention pour réduire la liste.</p>` : ""}</details>`;
}
async function viewSelectivite(dArg, mArg) {
  const FAC = await api("/api/carte");
  const known = (lab) => FAC.diplomes.find((x) => x.label === lab);
  const D = known(dArg) || known("BUT") || FAC.diplomes[0];
  const mention = D.mentions.some((m) => m.label === mArg) ? mArg : "";
  const d = await api(`/api/selectivite?diplome=${encodeURIComponent(D.label)}${mention ? `&mention=${encodeURIComponent(mention)}` : ""}`);
  if (!/^#\/selectivite/.test(location.hash)) return;
  const by = Object.fromEntries(SEL_Q.map((q) => [q, d.formations.filter((f) => f.quadrant === q)]));
  const goTo = (lab, m) => { location.hash = `#/selectivite/${encodeURIComponent(lab)}${m ? `/${encodeURIComponent(m)}` : ""}`; };
  const row = (f) => `<tr><td data-label="Formation"><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.formation)} · ${esc(f.ville)}</div></td>
    <td class="num" data-label="Taux d'accès">${pct(f.taux_acces_ens)}</td><td class="num" data-label="Mention Bien ou mieux">${pct(f.part_bien_plus)}</td><td class="num" data-label="Candidats par place">${fmt(f.candidats_par_place, 1)}</td></tr>`;
  $view.innerHTML = `<div class="card"><h1>Vraie sélectivité</h1>
    <p class="small">Un taux d'accès bas peut venir de nombreux candidats pour les places, ou d'admissions très exigeantes. Chaque formation est placée selon son <strong>taux d'accès officiel</strong> et la <strong>part de ses admis nouveaux bacheliers avec une mention Bien ou mieux</strong>.</p>
    <div class="carte-pick"><label class="small">Type de diplôme <select id="sdip">${FAC.diplomes.map((x) => `<option value="${esc(x.label)}" ${x.label === D.label ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>
    <label class="small">Mention <select id="smen"><option value="">Toutes les mentions</option>${D.mentions.map((m) => `<option value="${esc(m.label)}" ${m.label === mention ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label></div></div>
  <div class="card"><div class="scroll">${d.formations.length ? selPlot(d, null) : `<p class="muted">Aucune formation placée.</p>`}</div>
    <p class="muted small">Lignes pointillées : médianes de la sélection (taux d'accès ${pct(d.mediane_taux)}, mention Bien ou mieux ${pct(d.mediane_bien)}). Les quatre zones décrivent une position, pas une cause ni des chances d'admission. Données : ministère de l'Enseignement supérieur (SIES), session ${esc(d.session)}.</p></div>
  ${SEL_Q.map((q) => `<details class="card"${q === "Très demandée" ? " open" : ""}><summary><strong>${esc(q)}</strong> · ${fmt(by[q].length)} formation${by[q].length > 1 ? "s" : ""} <span class="muted small">(${esc(SEL_Q_HELP[q])})</span></summary>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th class="num">Taux d'accès</th><th class="num">Mention Bien ou mieux</th><th class="num">Candidats par place</th></tr>${by[q].slice(0, 40).map(row).join("")}</table></div>
    ${by[q].length > 40 ? `<p class="muted small">40 premières sur ${fmt(by[q].length)} (ordre alphabétique) ; choisissez une mention pour réduire la liste.</p>` : ""}</details>`).join("")}
  ${selApart(d)}
  <p class="muted small">Candidats par place : vœux confirmés divisés par les places, un ordre de grandeur (un même élève fait plusieurs vœux).</p>`;
  $view.dataset.rendered = "selectivite";
  document.getElementById("sdip").onchange = (e) => goTo(e.target.value, "");
  document.getElementById("smen").onchange = (e) => goTo(D.label, e.target.value);
  document.querySelectorAll(".sel-dot").forEach((c) => { c.onclick = () => { location.hash = `#/f/${encodeURIComponent(c.dataset.pick)}`; }; });
}

// ---- sprint 21: "Je me réoriente ou je reprends mes études" (owner's choices, 2026-11-11) ----
// The group outside terminale (reorientation, return to studies, other routes) has no published access rate: the server derives
// its candidates and proposals from the published counts and scales the official rate (reorientation.py). Always an estimation,
// never a zone, never a Plan B; the list is sorted by the student's académie, then by name, never by figures.
const REO_NO_ZONE = "Pour ces candidats, le ministère ne publie ni la mention ni la série du bac : aucune zone (sécurité, cible, ambitieux) ne peut donc être lue.";
function reoWhy(b, ok) {
  if (!b) return "pas de chiffres pour cette formation";
  if (b.acces_estime != null) return b.plafonne ? `${ok} (plafonnée à 100 %)` : ok;
  if (b.candidats == null) return "effectifs publiés incohérents : pas d'estimation";
  if (b.candidats < b.min_candidats) return `moins de ${b.min_candidats} candidats hors terminale (${b.candidats}) : pas d'estimation`;
  if (b.taux_acces_ens == null) return "taux d'accès non publié : pas d'estimation";
  return "aucune proposition publiée : pas d'estimation";
}
function reoCell(b) {
  if (!b || b.acces_estime == null) return `—<div class="estim">${esc(reoWhy(b, ""))}</div>`;
  return `${pct1(b.acces_estime)}${estimTag(`${b.plafonne ? "plafonnée à 100 % · " : ""}${fmt(b.propositions)} propositions pour ${fmt(b.candidats)} candidats hors terminale${b.propositions === 0 ? " : rare cette année-là, pas forcément fermé" : ""}`, true)}`;
}
// audit PR 6 (2026-11-24): an adult who goes back to studies: the public services that help (aide.ADULTES through META.reprise,
// the same list as the help page), folded so the list of formations stays near the top; official links only, every string escaped
function reoAdultesCard() {
  const R = typeof META !== "undefined" && META && META.reprise;
  if (!R || !Array.isArray(R.services) || !R.services.length) return "";
  const svc = (s) => `<li class="reo-svc"><strong>${esc(s.titre)}</strong><div class="small">${esc(s.pour)} ${esc(s.comment)}</div>
    <div class="small">${(s.liens || []).filter((x) => /^https:\/\//.test(String(x.url || ""))).map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.texte)}</a>`).join(" · ")}</div></li>`;
  return `<details class="card reo-adultes"><summary><h2>Se faire accompagner pour reprendre des études</h2></summary>
    <p class="small">${esc(R.intro)}</p><ul class="reo-svcs">${R.services.map(svc).join("")}</ul>
    <p class="muted small">Pages officielles lues le ${esc(R.verifie)}. <a href="#/info/aide">Tous les services qui aident à choisir</a></p></details>`;
}
// the formation page's folded card: the published counts, the estimate and its method (review: never a figure without them)
// lot 1, PR 12: an IFSI page tells a working professional the official route (formation professionnelle continue, outside
// Parcoursup): the official page's own sentence, quoted (aides.r_ifsi_fpc), its link (.gouv.fr only); never a condition of ours
function ifsiFpcCard(a) {
  const x = a && a.ifsi_fpc;
  if (!x || !/^https:\/\/www\.parcoursup\.gouv\.fr\//.test(x.source || "")) return "";
  return `<div class="card"><h2>Vous travaillez déjà dans le soin ?</h2>
    <blockquote class="small">« ${esc(x.texte)} »</blockquote>
    <p class="small"><a href="${esc(x.source)}" target="_blank" rel="noopener">Lire la page officielle de Parcoursup ↗</a> · <a href="#/info/aide">Se faire aider</a></p>
    <p class="muted small">Phrase recopiée de la page officielle, qui fait foi. Les dates et les épreuves sont données par chaque institut.</p></div>`;
}
function reoCard(b) {
  if (!b) return "";
  return `<div class="card"><h2>Candidats qui ne sont plus en terminale · ${esc(b.session)}</h2>
    <p class="small">Réorientation, reprise d'études ou autre parcours : le ministère les compte ensemble, comme « autres candidats ».</p>
    <div class="pr-lead"><span class="sum-label">Accès estimé hors terminale</span><div class="pr-lead-v">${reoCell(b)}</div></div>
    <p class="muted small">${b.candidats != null ? `Calculé à partir des effectifs publiés : ${fmt(b.propositions)} propositions pour ${fmt(b.candidats)} candidats hors terminale (${pct1(b.taux_proposition)} d'entre eux ont reçu une proposition), contre ${pct1(b.taux_proposition_tous)} pour l'ensemble des candidats.` : "Effectifs publiés incohérents : pas de lecture pour cette campagne."}</p>
    <p class="muted small">${REO_METHOD} ${REO_NO_ZONE}</p></div>`;
}
const reoAutres = (b) => (b && b.part_admis_autres != null ? `${pct1(b.part_admis_autres)}<div class="estim">${fmt(b.admis_autres)} sur ${fmt(b.admis)} admis</div>` : "—");
// audit PR 6 (2026-11-24): short sentences (<= 30 words; the formula was one 32-word sentence)
const REO_METHOD = "Accès estimé hors terminale : le taux d'accès officiel, ajusté par les propositions reçues. On le multiplie par la part des candidats hors terminale qui ont reçu une proposition, puis on le divise par la même part pour tous les candidats. Le résultat est plafonné à 100 %. C'est une estimation faite avec les chiffres publiés des deux phases : pas un taux officiel ni une chance d'admission.";
function reoSort(rows, home) {
  const by = (x) => `${x.etablissement || ""} ${x.formation || ""}`;
  return rows.slice().sort((a, b) => (home ? (b.academie === home) - (a.academie === home) : 0)
    || by(a).localeCompare(by(b), "fr", { sensitivity: "base" }) || String(a.cod_aff_form).localeCompare(String(b.cod_aff_form)));
}
async function viewReorientation(dArg, mArg) {
  const first = `reorientation-load:${location.hash}`;                 // set before any await (review: a late answer for a
  $view.dataset.rendered = first;                                        // page left meanwhile must never draw)
  const [FAC, V] = await Promise.all([api("/api/carte"), JV ? Promise.resolve(JV) : api("/api/journey/vocab")]);
  if ($view.dataset.rendered !== first) return;
  JV = V;
  const known = (lab) => FAC.diplomes.find((x) => x.label === lab);
  const D = known(dArg) || known("Licence") || FAC.diplomes[0];
  const mention = D.mentions.some((m) => m.label === mArg) ? mArg : "";
  const qs = new URLSearchParams({ diplome: D.label });
  if (mention) qs.set("mention", mention);
  const marker = `reorientation:${qs}`;
  $view.dataset.rendered = marker;
  const d = await api(`/api/reorientation?${qs}`);
  if ($view.dataset.rendered !== marker) return;                       // the user navigated meanwhile
  const goTo = (lab, m) => { location.hash = `#/reorientation/${encodeURIComponent(lab)}${m ? `/${encodeURIComponent(m)}` : ""}`; };
  const acads = [...new Set(d.formations.map((f) => f.academie).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fr"));
  let shown = searchPage(), onlyHome = false, onlyAutres = false;
  const draw = () => {
    const raw = store.get("profile", null);
    const prof = raw && typeof raw === "object" && !Array.isArray(raw) ? vxProfile(raw) : null;
    const mine = isReo(prof);
    const acad = prof && prof.academie ? prof.academie : store.get("reoAcademie", "");   // no profile: kept apart (review)
    const home = typeof acad === "string" && JV.academies.includes(acad) ? acad : "";
    const rows = reoSort(d.formations.filter((f) => (!onlyHome || !home || f.academie === home) && (!onlyAutres || (f.reorientation && f.reorientation.autres_majoritaires))), home);
    const nEst = d.formations.filter((f) => f.reorientation && f.reorientation.acces_estime != null).length;
    const nAut = d.formations.filter((f) => f.reorientation && f.reorientation.autres_majoritaires).length;
    const row = (f) => { const b = f.reorientation; return `<tr><td data-label="Formation"><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.formation)} · ${esc(f.ville)}${f.academie ? ` (${esc(acadLabel(f.academie))})` : ""}${f.payant ? ' · <span class="badge warnb">privé, frais de scolarité</span>' : ""}</div>${b ? autresBadge(b) : ""}</td>
      <td class="num" data-label="Accès estimé hors terminale">${reoCell(b)}</td>
      <td class="num" data-label="Taux d'accès officiel, tous candidats">${pct(b && b.taux_acces_ens)}</td>
      <td class="num" data-label="Admis hors nouveaux bacheliers">${reoAutres(b)}</td>
      <td class="acts" data-label="Mes vœux">${voeuButton(f.cod_aff_form)}</td></tr>`; };
    $view.innerHTML = `<div class="card"><h1>Je me réoriente ou je reprends mes études</h1>
      <p>Vous n'êtes plus en terminale : réorientation, reprise d'études, ou un autre parcours. Le ministère compte ces candidats ensemble et ne publie pas de taux d'accès pour eux. Cette page calcule une estimation pour chaque formation, avec les chiffres publiés.</p>
      <p class="small">${REO_NO_ZONE} Les chiffres ci-dessous sont des parts de candidats des campagnes passées, pas des chances d'admission.</p>
      <div class="toolbar">${mine ? `<span class="badge exact">Votre situation : ${REO_LABEL}</span><button type="button" id="reo-back" class="small">Je suis en terminale</button>`
        : `<button type="button" id="reo-me">C'est ma situation</button><span class="muted small">« Où je me situe », la fiche des formations et « Mes vœux » afficheront alors l'accès estimé hors terminale, sans zone.</span>`}</div></div>
    ${reoAdultesCard()}
    <div class="card"><div class="carte-pick"><label class="small">Type de diplôme <select id="rdip">${FAC.diplomes.map((x) => `<option value="${esc(x.label)}" ${x.label === D.label ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>
      <label class="small">Mention <select id="rmen"><option value="">Toutes les mentions</option>${D.mentions.map((m) => `<option value="${esc(m.label)}" ${m.label === mention ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label>
      <label class="small">Votre académie <select id="racad"><option value="">—</option>${JV.academies.map((a) => `<option value="${esc(a)}" ${a === home ? "selected" : ""}>${esc(acadLabel(a))}</option>`).join("")}</select></label></div>
      <div class="toolbar">${home ? `<label class="small"><input type="checkbox" id="rhome" ${onlyHome ? "checked" : ""}> Seulement l'académie de ${esc(acadLabel(home))}</label>` : ""}
        <label class="small"><input type="checkbox" id="raut" ${onlyAutres ? "checked" : ""}> Seulement les formations où les admis hors nouveaux bacheliers sont majoritaires</label></div>
      <p class="small">${fmt(d.formations.length)} formation${d.formations.length > 1 ? "s" : ""} en ${esc(d.session)} · ${fmt(nEst)} avec un accès estimé hors terminale · ${fmt(nAut)} où les admis hors nouveaux bacheliers sont majoritaires. Ordre : ${home ? `l'académie de ${esc(acadLabel(home))} d'abord, puis ` : ""}le nom de l'établissement, jamais les chiffres.</p></div>
    <div class="card"><h2>Formations ${esc(D.label)}${mention ? ` · ${esc(mention)}` : ""}</h2>
      ${rows.length ? `<div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th class="num">Accès estimé hors terminale ${d.session}</th><th class="num">Taux d'accès officiel, tous candidats</th><th class="num">Admis hors nouveaux bacheliers</th><th><span class="sr-only">Actions</span></th></tr>
      ${rows.slice(0, shown).map(row).join("")}</table></div>` : `<p class="muted">Aucune formation pour ces filtres.</p>`}
      ${rows.length > shown ? `<p><button type="button" id="rmore">Afficher ${fmt(Math.min(searchPage(), rows.length - shown))} de plus (${fmt(shown)} sur ${fmt(rows.length)})</button></p>` : ""}
      <p class="muted small">${REO_METHOD} Pas d'estimation sous ${d.min_candidats} candidats hors terminale.</p>
      <p class="muted small">Admis hors nouveaux bacheliers : les admis qui n'ont pas passé le bac l'année de leur admission. Le ministère publie leur nombre, sans détail.</p></div>
    ${nextSteps("reorientation")}${feedbackBox("reorientation")}`;
    $view.dataset.rendered = marker;
    document.getElementById("rdip").onchange = (e) => goTo(e.target.value, "");
    document.getElementById("rmen").onchange = (e) => goTo(D.label, e.target.value);
    document.getElementById("racad").onchange = (e) => {
      const p0 = store.get("profile", null);
      if (p0 && typeof p0 === "object" && !Array.isArray(p0)) store.set("profile", { ...p0, academie: e.target.value });
      else store.set("reoAcademie", e.target.value);                 // never a profile without a bac or a status
      draw();
    };
    const h = document.getElementById("rhome");
    if (h) h.onchange = () => { onlyHome = h.checked; shown = searchPage(); draw(); };
    document.getElementById("raut").onchange = (e) => { onlyAutres = e.target.checked; shown = searchPage(); draw(); };
    const more = document.getElementById("rmore");
    if (more) more.onclick = () => { shown += searchPage(); draw(); };
    const setStatut = (st) => {
      const raw0 = store.get("profile", null);
      const p0 = raw0 && typeof raw0 === "object" && !Array.isArray(raw0) ? raw0 : null;
      const a0 = store.get("reoAcademie", "");
      if (st === "reorientation") store.set("profile", { ...(p0 || (typeof a0 === "string" && a0 ? { academie: a0 } : {})), statut: st });
      else if (p0 && p0.serie) store.set("profile", { ...p0, statut: st });   // the bac fields the student had entered
      else store.set("profile", null);                                  // none: "Mon parcours" asks for them, never invents them
    };
    const me = document.getElementById("reo-me");
    if (me) me.onclick = () => { setStatut("reorientation"); draw(); };
    const back = document.getElementById("reo-back");
    if (back) back.onclick = () => {
      setStatut("terminale");
      // opened from "Mon parcours" the address is already #/parcours: no hashchange, so draw it here (Codex, PR #51)
      if (location.hash === "#/parcours") viewParcours(); else location.hash = "#/parcours";
    };
    bindVoeuButton(draw);
  };
  draw();
}
// Mes vœux outside terminale: the estimated access of each vœu, no zone tiles, no alert, no Plan B, no "Compléter ma liste"
async function viewVoeuxReo(ids, prof) {
  const head = `<div class="card"><h1>Mes vœux ${tip("mes_voeux")}</h1>
    <p class="small">Lue pour votre situation : ${REO_LABEL}${prof.academie ? `, académie de ${esc(acadLabel(prof.academie))}` : ""}. <a href="#/reorientation">Modifier dans « Je me réoriente »</a></p><p class="print-only small">Liste lue sur SupCompass le ${esc(frDate(localIso()))}. Chiffres officiels Parcoursup 2022–2025 : des parts d'admis, pas des chances d'admission.</p></div>`;
  const howto = `<p class="muted small">Ajoutez des formations depuis leur fiche ou depuis « Je me réoriente » (${voeux.MAX} vœux au maximum sur Parcoursup, hors sous-vœux).</p>`;
  if (!ids.length) {
    $view.innerHTML = `${head}<div class="card"><p class="muted">Votre liste est vide.</p>${howto}</div>${APP_SECTION}${transferCard()}`;
    $view.dataset.rendered = "voeux:0";
    loadAppVoeux("voeux:0");
    bindTransfer();                                                     // Codex (PR 18): an apprenticeship-only list travels too
    return;
  }
  const qs = new URLSearchParams({ ids: ids.join(",") });
  const marker = `voeux:reo:${qs}`;
  $view.dataset.rendered = marker;
  $view.innerHTML = `${head}<div class="card"><p class="muted small">Lecture de votre liste…</p></div>`;
  let d;
  const recoP = recoLoad();                                          // the robustesse repères of each vœu (owner, 2026-11-17)
  try { d = await api(`/api/reorientation/voeux?${qs}`); } catch (e) {
    if ($view.dataset.rendered === marker) $view.innerHTML = `${head}<div class="warn">${esc(e.message)}</div>`;
    return;
  }
  await recoP;
  if ($view.dataset.rendered !== marker) return;
  const ok = d.voeux.filter((v) => v.status === "ok"), nEst = ok.filter((v) => v.reorientation && v.reorientation.acces_estime != null).length;
  const rows = d.voeux.map((v) => {
    const name = v.status !== "ok" ? `<span class="muted">Formation ${esc(v.cod_aff_form)} absente de la campagne ${esc(d.session)}</span>`
      : `<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a><div class="muted small">${esc(v.formation)} · ${esc(v.ville)}${v.academie ? ` (${esc(acadLabel(v.academie))})` : ""}</div>${v.reorientation ? autresBadge(v.reorientation) : ""}`;
    const b = v.status === "ok" ? v.reorientation : null;
    return `<tr><td data-label="Formation">${name}</td>
      <td class="num" data-label="Accès estimé hors terminale">${v.status === "ok" ? reoCell(b) : "—"}</td>
      <td class="num" data-label="Taux d'accès officiel, tous candidats">${pct(b && b.taux_acces_ens)}</td>
      <td class="num" data-label="Admis hors nouveaux bacheliers">${reoAutres(b)}</td>
      <td class="acts" data-label="Mes vœux"><button type="button" class="small" data-vxdel="${esc(v.cod_aff_form)}">Retirer</button></td></tr>`;
  }).join("");
  $view.innerHTML = `${head}
  <section class="card summary" aria-label="Lecture de votre liste"><h2>Lecture de votre liste</h2>
    <p>${vxCompteTxt(d.voeux.length, vxCompte(d.voeux))} · ${fmt(nEst)} formation${nEst > 1 ? "s" : ""} avec un accès estimé hors terminale.</p>
    <p class="small">${REO_NO_ZONE} Les repères de zones, le plan B et « Compléter ma liste » reposent sur ces zones : ils ne sont pas proposés. Vos vœux ne se combinent pas en une chance d'admission.</p></section>
  <div class="card"><h2>${vxTitre(d.voeux)}</h2>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th class="num">Accès estimé hors terminale ${esc(d.session)}</th><th class="num">Taux d'accès officiel, tous candidats</th><th class="num">Admis hors nouveaux bacheliers</th><th><span class="sr-only">Actions</span></th></tr>
    ${rows}</table></div>
    <p class="muted small">${REO_METHOD} Pas d'estimation sous ${d.min_candidats} candidats hors terminale.</p>
    <p class="muted small">Votre liste reste dans ce navigateur. Pour la lire, la page envoie seulement les codes des formations ; rien n'en est enregistré sur le serveur.</p>${howto}</div>${APP_SECTION}<section class="card" id="vx-verifier"><p class="muted small">Vérification de votre liste…</p></section><section class="card" id="vx-jpo"><p class="muted small">Portes ouvertes de votre liste…</p></section>${robVoeuxCard(d.voeux)}${shareCard(ids, !!store.get("profile", null))}${transferCard()}${nextSteps("voeux")}${feedbackBox("voeux")}`;
  loadVerifier(ids, marker, { noms: Object.fromEntries(d.voeux.filter((v) => v.status === "ok").map((v) => [v.cod_aff_form, v.etablissement])), securite: null });
  loadJpoListe(ids, marker);
  loadAppVoeux(marker);                                                 // PR 18: the separate apprenticeship list
  $view.querySelectorAll("[data-vxdel]").forEach((el) => { el.onclick = () => { voeux.remove(el.dataset.vxdel); viewVoeux(); }; });
  bindShare(ids, store.get("profile", null) ? prof : null);             // sprint 22: never a default profile (review)
  bindTransfer();                                                       // PR 17: the same person, on another device
}

// ---- sprint 22: accompaniment (owner's go, 2026-11-11): the official calendar, a page for the adults who help, an entry for
// seconde and première, and a list a student can share or print. Nothing is stored on the server: a shared list is a link that
// carries the formation codes (and, only if the student ticks the box, the profile) in the part of the address after "#",
// which the browser never sends to a server.
const pad2 = (n) => String(n).padStart(2, "0");
// Parcoursup's dates are Paris dates: a student in Nouméa or Papeete must not read a deadline as past while it is still open (review)
const localIso = (t = new Date()) => {
  try { return new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" }).format(t); }
  catch (_) { return `${t.getFullYear()}-${pad2(t.getMonth() + 1)}-${pad2(t.getDate())}`; }
};
const frDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const daysBetween = (a, b) => Math.round((new Date(`${b}T12:00:00`) - new Date(`${a}T12:00:00`)) / 86400000);
const CAL_LINKS = { voeux: "#/voeux", fin_voeux: "#/voeux", admission: "#/comprendre", classement: "#/apres-juin", complementaire: "#/apres-juin", carte: "#/carte" };
function calState(e, today) {
  if (!e.verifie) return "inconnu";
  const end = e.fin || e.debut;
  if (end < today) return "passe";
  if (e.debut <= today) return "en_cours";
  return "a_venir";
}
async function viewCalendrier() {
  const marker = "calendrier";
  $view.dataset.rendered = marker;
  const d = await api("/api/calendrier");
  if ($view.dataset.rendered !== marker) return;
  const today = localIso();
  const next = d.evenements.find((e) => ["en_cours", "a_venir"].includes(calState(e, today)));
  const when = (e) => (!e.verifie ? `<span class="muted">date à vérifier sur parcoursup.gouv.fr</span>`
    : e.fin ? `du ${esc(frDate(e.debut))} au ${esc(frDate(e.fin))}` : esc(frDate(e.debut)));
  const STATE = { passe: "passé", en_cours: "en cours", a_venir: "à venir", inconnu: "date à vérifier" };
  const item = (e) => {
    const st = calState(e, today);
    return `<li class="cal-item cal-${st}"${next && e.key === next.key ? ' aria-current="step"' : ""}>
      <div class="cal-when"><strong>${when(e)}</strong> <span class="badge">${STATE[st]}</span></div>
      <div class="cal-what">${esc(e.libelle)}</div>
      <p class="small muted">Sur SupCompass : ${esc(e.sur_supcompass)}${CAL_LINKS[e.key] ? ` <a href="${CAL_LINKS[e.key]}">Y aller</a>` : ""}</p></li>`;
  };
  const steps = Object.keys(d.etapes).map(Number).sort((a, b) => a - b);
  const nOk = d.evenements.filter((e) => e.verifie).length;
  const head = !nOk ? "Les dates officielles n'ont pas pu être lues : vérifiez-les sur parcoursup.gouv.fr."
    : next ? (next.debut <= today ? `En ce moment : <strong>${esc(next.libelle)}</strong>.`
    : `Prochaine étape dans ${fmt(daysBetween(today, next.debut))} jour${daysBetween(today, next.debut) > 1 ? "s" : ""} : <strong>${esc(next.libelle)}</strong>, ${esc(frDate(next.debut))}.`)
    : nOk === d.evenements.length ? "La campagne Parcoursup " + esc(d.campagne) + " est terminée."
    : "Certaines dates n'ont pas pu être lues : vérifiez-les sur parcoursup.gouv.fr.";
  $view.innerHTML = `<div class="card"><h1>Calendrier Parcoursup ${esc(d.campagne)}</h1>
    <p>${head}</p>
    <div class="toolbar no-print">${nOk ? `<a class="btnlink" href="/api/calendrier.ics">Ajouter ces dates à mon agenda (.ics)</a>` : ""}<button type="button" id="cal-print">Imprimer</button><a href="#/portes-ouvertes">Portes ouvertes et webinaires près de chez moi</a><a href="#/apres-juin">Après le 1er juin : les réponses</a></div>
    <p class="muted small">Source : calendrier officiel Parcoursup ${esc(d.campagne - 1)}-${esc(d.campagne)} publié sur parcoursup.gouv.fr${d.lu_le ? `, lu le ${esc(frDate(d.lu_le))}` : ""}. Une date n'est affichée que si toutes les versions du document la donnent à l'identique. En cas de différence, le calendrier officiel fait foi.</p></div>
  ${steps.map((k) => `<section class="card"><h2>Étape ${k} · ${esc(d.etapes[k])}</h2><ol class="cal-list">${d.evenements.filter((e) => e.etape === k).map(item).join("")}</ol></section>`).join("")}`;
  const pr = document.getElementById("cal-print");
  if (pr) pr.onclick = () => window.print();
}

// the page for the adults who help a student (parents, professeur principal): what the figures mean and what they do not say
function viewAccompagner() {
  $view.innerHTML = `<div class="card"><h1>Accompagner un élève</h1>
    <p>Cette page s'adresse aux parents, aux professeurs principaux et à tout adulte qui aide un élève à préparer ses vœux Parcoursup. Elle explique ce que montre SupCompass, et surtout ce qu'il ne montre pas.</p>
    <div class="toolbar no-print"><button type="button" id="acc-print">Imprimer cette page</button></div></div>
  <section class="card"><h2>Ce que montre SupCompass</h2><ul>
    <li>Les chiffres officiels des campagnes Parcoursup 2022 à 2025, publiés par le ministère (SIES), formation par formation : candidats, propositions, admis, taux d'accès.</li>
    <li>Pour un profil (bac, spécialités, mention), une <strong>zone</strong> : sécurité, cible ou ambitieux. Elle dit où se situaient les admis des années passées par rapport à ce profil. <strong>Ce n'est jamais une chance d'admission</strong> : le jury lit tout le dossier, et chaque année est différente.</li>
    <li>Quand il existe, le rapport public du jury de la formation : ce que les jurys ont regardé, et les résultats publiés par type de bac.</li>
    <li>Des repères après la formation (réussite, poursuite d'études, insertion, métiers), toujours avec leur source.</li></ul></section>
  <section class="card"><h2>Ce que SupCompass ne fait pas</h2><ul>
    <li>Il ne dit jamais si un élève sera admis, et ne classe pas les formations.</li>
    <li>Il ne connaît ni les notes, ni le dossier, ni le rang de l'élève : aucune page ne les demande.</li>
    <li>Il ne remplace ni le professeur principal, ni le psychologue de l'Éducation nationale, ni la fiche de la formation sur Parcoursup, qui fait foi.</li>
    <li>Il ne crée pas de compte : la liste de vœux reste dans le navigateur de l'élève.</li></ul></section>
  <section class="card"><h2>Avec une classe</h2>
    <p>Pour une séance d'une heure en salle informatique ou avec les téléphones des élèves, suivez le <a href="#/kit">kit pour une séance en classe</a> : le déroulé minute par minute et une fiche à imprimer pour les élèves.</p></section>
  <section class="card"><h2>Regarder la liste de l'élève avec lui</h2>
    <ol><li>Dans « Mes vœux », l'élève touche « Copier le lien » et vous l'envoie. Le lien contient les numéros des formations ; son profil seulement s'il coche la case.</li>
    <li>En ouvrant le lien, vous voyez la même liste, lue pour son profil s'il l'a joint. Vous pouvez aussi l'imprimer.</li>
    <li>Ensemble, regardez au moins ces points : la liste contient-elle un ou plusieurs vœux de sécurité ? Chaque formation a-t-elle été lue sur sa fiche Parcoursup (attendus, frais, lieu) ? Les dates du <a href="#/calendrier">calendrier</a> sont-elles notées ?</li></ol></section>
  <section class="card"><h2>Questions utiles pour la conversation</h2><ul>
    <li>Qu'est-ce qui attire l'élève dans cette formation : le contenu, le métier visé, la ville ?</li>
    <li>Que disent les attendus de la formation, sur sa fiche Parcoursup, et le rapport du jury quand il existe ?</li>
    <li>Si la réponse est « non » ou « en attente » partout, quelle formation de la liste reste un bon choix ?</li>
    <li>Le coût (logement, transport, frais d'un établissement privé) a-t-il été regardé ?</li></ul>
    <p class="small muted">Aucune de ces questions n'appelle une « bonne » réponse : elles servent à préparer les vœux, pas à les juger.</p></section>
  <section class="card"><h2>Pages utiles</h2><ul>
    <li><a href="#/calendrier">Calendrier Parcoursup</a> : les dates officielles, à ajouter à un agenda.</li>
    <li><a href="#/premiere">En seconde ou en première</a> : les filières où l'on trouve les paires de spécialités possibles.</li>
    <li><a href="#/reorientation">Je me réoriente ou je reprends mes études</a> : pour un élève qui n'est plus en terminale.</li>
    <li><a href="#/glossaire">Glossaire</a> : le sens de chaque mot et de chaque chiffre.</li></ul></section>`;
  $view.dataset.rendered = "accompagner";
  const pr = document.getElementById("acc-print");
  if (pr) pr.onclick = () => window.print();
}

// seconde and première: three specialties of première give three possible doublettes of terminale; for each, the filières where
// the bac général admits of 2022-2025 had it (the composition of the admits, never a piece of advice or a chance)
const PREM_ROWS = 12;
let premiereSeq = 0;
function premiereDoublettes(spes) {
  const s = [...new Set(spes.filter(Boolean))];
  if (s.length !== 3) return [];
  return [[s[0], s[1]], [s[0], s[2]], [s[1], s[2]]];
}
async function viewPremiere() {
  const first = `premiere-load:${++premiereSeq}`;
  $view.dataset.rendered = first;                                       // before any await (review: navigation race)
  JV = JV || await api("/api/journey/vocab");
  if ($view.dataset.rendered !== first) return;
  const codes = new Set(JV.specialties.map((x) => x.code));
  const stored = store.get("premiere", []);
  const spes = Array.isArray(stored) ? stored.filter((c) => typeof c === "string" && codes.has(c)).slice(0, 3) : [];
  const name = (c) => (JV.specialties.find((x) => x.code === c) || {}).short || c;
  const sel = (i) => `<label>Spécialité ${i + 1} <select name="p${i}"><option value="">—</option>${JV.specialties.map((x) => `<option value="${esc(x.code)}" ${spes[i] === x.code ? "selected" : ""}>${esc(x.short)}</option>`).join("")}</select></label>`;
  const pairs = premiereDoublettes(spes);
  const marker = `premiere:${pairs.map((p) => p.join("+")).join(",")}`;
  $view.dataset.rendered = marker;
  const intro = `<div class="card"><h1>En seconde ou en première</h1>
    <p>Choisissez trois spécialités de première. En terminale, vous en garderez deux : cela fait trois paires possibles. Pour chacune, voici les filières où l'on trouvait cette paire parmi les admis bacheliers généraux de 2022 à 2025.</p>
    <form id="prem" class="toolbar">${[0, 1, 2].map(sel).join("")}</form>
    <p class="small">Ce sont des parts d'admis des années passées, pas un conseil de spécialités ni une chance d'admission. Beaucoup de filières admettent des paires de spécialités très variées : les attendus de chaque formation, sur sa fiche Parcoursup, et l'avis de votre professeur principal comptent davantage.</p></div>`;
  const bindForm = () => {
    document.getElementById("prem").onchange = () => {
      const f = new FormData(document.getElementById("prem"));
      store.set("premiere", [0, 1, 2].map((i) => f.get(`p${i}`) || ""));
      viewPremiere();
    };
  };
  if (!pairs.length) {
    $view.innerHTML = `${intro}<div class="card"><p class="muted">Choisissez trois spécialités différentes.</p></div>`;
    bindForm();
  } else {
    $view.innerHTML = `${intro}<div class="card"><p class="muted small">Lecture des paires de spécialités…</p></div>`;
    bindForm();                                                          // a choice made while loading is never lost
    // 404 = the doublette is absent from the data; any other failure is said as such (review)
    const res = await Promise.all(pairs.map(([a, b]) => api(`/api/journey/stage1?spe1=${encodeURIComponent(a)}&spe2=${encodeURIComponent(b)}`)
      .catch((e) => ({ error: /absente/i.test(e.message) ? "absente" : "indisponible" }))));
    if ($view.dataset.rendered !== marker) return;
    const by = new Map();
    res.forEach((r, i) => (r && !r.error ? r.filieres : []).forEach((f) => {
      const row = by.get(f.type_key) || { label: f.label, cells: [null, null, null], dest: 0 };
      row.cells[i] = f;
      row.dest = Math.max(row.dest, f.destination_share || 0);
      by.set(f.type_key, row);
    }));
    const all = store.get("premiereAll", false);
    const rows = [...by.values()].sort((a, b) => b.dest - a.dest || a.label.localeCompare(b.label, "fr"));
    const cell = (f, i) => `<td class="num" data-label="${esc(pairs[i].map(name).join(" + "))}">${!f ? "—"
      : `${pc1(f.share)}<div class="estim">des admis bacheliers généraux${f.rare ? " · rare (moins de 20 candidats)" : ""}</div>`}</td>`;
    $view.innerHTML = `${intro}<div class="card"><h2>Trois paires possibles</h2>
      <ul class="small">${pairs.map((p, i) => `<li><strong>${esc(p.map(name).join(" + "))}</strong> : ${res[i] && !res[i].error ? `${fmt(res[i].national.accepted)} admis sur ${fmt(res[i].national.years)} campagnes, ${pc1(res[i].national.national_share)} de tous les admis bacheliers généraux` : res[i] && res[i].error === "indisponible" ? "lecture impossible pour le moment, réessayez" : "absente des données 2022–2025"}</li>`).join("")}</ul>
      <div class="scroll"><table class="stack"><tr class="stack-head"><th>Filière</th>${pairs.map((p) => `<th class="num">${esc(p.map(name).join(" + "))}</th>`).join("")}</tr>
      ${rows.slice(0, all ? rows.length : PREM_ROWS).map((r) => `<tr><td data-label="Filière">${esc(r.label)}</td>${r.cells.map(cell).join("")}</tr>`).join("")}</table></div>
      ${rows.length > PREM_ROWS ? `<p><button type="button" id="prem-all">${all ? `Afficher les ${PREM_ROWS} premières` : `Afficher les ${fmt(rows.length)} filières`}</button></p>` : ""}
      <p class="muted small">Ordre : les filières où vont le plus souvent les bacheliers ayant l'une de ces paires. Chaque case dit, parmi les admis bacheliers généraux de la filière, la part qui avait cette paire (2022–2025, campagnes au comptage rompu exclues).</p>
      <p class="small"><a href="#/specialites">Toutes les paires de spécialités par type de formation</a> · En terminale : <a href="#/profil">Mon profil</a></p></div>${nextSteps("premiere")}`;
    const b = document.getElementById("prem-all");
    if (b) b.onclick = () => { store.set("premiereAll", !all); viewPremiere(); };
    bindForm();
  }
}

// a shared list: "#/liste/<codes>[/<profile>]"; codes validated like the stored list; the profile only if the student joined it
// lot 1, PR 11: v = the bac techno / pro route (validated by vxProfile against the vocabulary), so the reader sees the same bac
const SHARE_KEYS = { s: "serie", a: "spe1", b: "spe2", m: "mention", t: "statut", v: "voie" };
function shareCodes(raw) {
  const out = [];
  for (const c0 of String(raw || "").split(",")) { const c = c0.trim(); if (/^\d{1,9}$/.test(c) && !out.includes(c) && out.length < voeux.MAX) out.push(c); }
  return out;
}
function shareProfile(raw) {
  if (!raw) return null;
  const q = new URLSearchParams(raw), p = {};
  for (const [k, f] of Object.entries(SHARE_KEYS)) { const v = q.get(k); if (v && v.length <= 60) p[f] = v; }
  if (p.statut === "r") return vxProfile({ statut: "reorientation" });   // outside terminale: no bac is read (sprint 21)
  if (!["bg", "bt", "bp"].includes(p.serie) || !MENTION_CODES.includes(p.mention)) return null;   // never a default; the average is never shared
  const codes = JV && JV.specialties ? new Set(JV.specialties.map((x) => x.code)) : null;
  if (p.serie === "bg" && (!codes || !codes.has(p.spe1) || !codes.has(p.spe2) || p.spe1 === p.spe2)) return null;
  if (p.serie === "bg") delete p.voie;
  const route = p.voie && JV && JV.voies && (JV.voies[p.serie] || []).find((x) => x.code === p.voie);
  if (p.voie && !route) delete p.voie;                                  // an unknown route is dropped, never guessed
  if (route) p.voie_label = route.label;
  return vxProfile(p);
}
function shareLink(ids, prof) {
  const base = `${location.origin}${location.pathname === "/" ? "/" : location.pathname}#/liste/${ids.join(",")}`;
  if (!prof) return base;
  const q = new URLSearchParams();
  if (isReo(prof)) q.set("t", "r");
  else {
    q.set("s", prof.serie); q.set("m", prof.mention);
    if (prof.serie === "bg") { q.set("a", prof.spe1 || "MATHS"); q.set("b", prof.spe2 || "SES"); }
    else if (prof.voie && prof.voie !== "autre") q.set("v", prof.voie);      // « autre » (not in the list) never travels
  }
  return `${base}/${q.toString()}`;
}
function shareCard(ids, withProfile) {
  return `<section class="card no-print" id="vx-share"><h2>Partager ou imprimer ma liste</h2>
    <p class="small">Envoyez ce lien ${isReo(store.get("profile", null)) ? "à un proche ou au conseiller qui vous accompagne" : "à un parent ou à votre professeur principal"} : il verra la même liste. Le lien contient seulement les numéros des formations, et votre profil si vous cochez la case. Le lien lui-même n'est jamais envoyé au serveur, et rien n'est enregistré.</p>
    ${withProfile ? `<label class="small"><input type="checkbox" id="share-prof"> Joindre mon profil (bac, spécialités ou voie, mention ; jamais la moyenne, l'académie ni le lycée : les zones y sont lues avec la mention seule)</label>` : ""}
    <div class="share-row"><input id="share-url" type="text" readonly aria-label="Lien de ma liste" value="${esc(shareLink(ids, null))}">
      <button type="button" id="share-copy">Copier le lien</button><button type="button" id="share-print">Imprimer</button></div>
    <p class="small muted" id="share-msg" aria-live="polite"></p>
    <p class="small"><a href="#/accompagner">Ce que l'adulte qui vous accompagne trouvera sur SupCompass</a></p></section>`;
}
function bindShare(ids, prof) {
  const box = document.getElementById("share-prof"), url = document.getElementById("share-url"), msg = document.getElementById("share-msg");
  if (!url) return;
  const refresh = () => { url.value = shareLink(ids, box && box.checked ? prof : null); };
  refresh();
  if (box) box.onchange = refresh;
  document.getElementById("share-copy").onclick = () => {
    refresh();
    store.set("guidePartage", true);                                  // R7: step 5 of "Construire ma liste" (this browser only)
    const done = () => { msg.textContent = "Lien copié."; };
    const manual = () => { url.focus(); url.select(); msg.textContent = "Copiez le lien sélectionné."; };
    try { navigator.clipboard.writeText(url.value).then(done, manual); } catch (_) { manual(); }
  };
  document.getElementById("share-print").onclick = () => { store.set("guidePartage", true); window.print(); };
}
async function viewListe(rawCodes, rawProfile) {
  const ids = shareCodes(rawCodes);
  const marker = `liste:${ids.join(",")}:${rawProfile || ""}`;
  $view.dataset.rendered = marker;                                      // before any await (review: navigation race)
  JV = JV || await api("/api/journey/vocab").catch(() => null);
  if ($view.dataset.rendered !== marker) return;
  const prof = shareProfile(rawProfile);
  const who = !prof && rawProfile ? "Le profil joint n'a pas pu être lu : les zones ne sont pas lues, seuls les chiffres officiels s'affichent."
    : !prof ? "Aucun profil n'a été joint : les zones ne sont pas lues, seuls les chiffres officiels s'affichent."
    : `Lue pour le profil joint : ${profileLine(prof, prof.serie)}.${isReo(prof) ? "" : " Les zones sont lues avec la mention seule : le lien ne contient jamais la moyenne, elles peuvent donc différer de celles de l'élève."}`;
  const head = `<div class="card"><h1>Liste partagée</h1><p class="small">${who}</p>
    <p class="print-only small">Liste lue sur SupCompass le ${esc(frDate(localIso()))}. Chiffres officiels Parcoursup 2022–2025 : des parts d'admis, pas des chances d'admission.</p></div>`;
  if (!ids.length) { $view.innerHTML = `${head}<div class="card"><p class="muted">Ce lien ne contient aucune formation valide.</p></div>`; return; }
  $view.innerHTML = `${head}<div class="card"><p class="muted small">Lecture de la liste…</p></div>`;
  const zoned = prof && !isReo(prof);
  let d;
  try { d = zoned ? voeuxLocal(await api(`/api/voeux?${vxQuery(ids, prof)}`), prof) : await api(`/api/reorientation/voeux?${new URLSearchParams({ ids: ids.join(",") })}`); } catch (e) {
    if ($view.dataset.rendered === marker) $view.innerHTML = `${head}<div class="warn">${esc(e.message)}</div>`;
    return;
  }
  if ($view.dataset.rendered !== marker) return;
  const rows = d.voeux.map((v) => {
    const name = v.status !== "ok" ? `<span class="muted">Formation ${esc(v.cod_aff_form)} absente de la campagne ${esc(d.session)}</span>`
      : `<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a><div class="muted small">${esc(v.filiere || v.formation || "")} · ${esc(v.ville)}${v.academie ? ` (${esc(acadLabel(v.academie))})` : ""}</div>`;
    const b = v.reorientation;
    const third = zoned ? `<td data-label="Zone pour ce profil">${v.status === "ok" && v.zone && ZONES[v.zone] ? zoneBadge(v.zone, v.uncertain, v.large) : "—"}</td>`
      : isReo(prof) ? `<td class="num" data-label="Accès estimé hors terminale">${v.status === "ok" ? reoCell(b) : "—"}</td>` : "";
    const rate = v.status !== "ok" ? null : zoned ? (prof.serie === "bg" ? v.taux_acces_ens : v.taux_acces_all) : b && b.taux_acces_ens;
    return `<tr><td data-label="Formation">${name}</td>${third}<td class="num" data-label="Taux d'accès officiel ${esc(d.session)}">${pct(rate)}</td></tr>`;
  }).join("");
  const mine = voeux.get(), fresh = ids.filter((c) => !mine.includes(c)), room = voeux.MAX - mine.length;
  $view.innerHTML = `${head}<div class="card"><h2>${fmt(d.voeux.length)} formation${d.voeux.length > 1 ? "s" : ""}</h2>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th>${zoned ? "<th>Zone pour ce profil</th>" : isReo(prof) ? `<th class="num">Accès estimé hors terminale</th>` : ""}<th class="num">Taux d'accès officiel ${esc(d.session)}</th></tr>${rows}</table></div>
    <p class="muted small">Des parts d'admis des campagnes passées, pas des chances d'admission. Les vœux Parcoursup ne sont pas classés : l'ordre de la liste ne veut rien dire.</p>
    <div class="toolbar no-print">${fresh.length && room <= 0 ? `<span class="small muted">Votre liste contient déjà ${voeux.MAX} vœux : retirez-en un pour en ajouter.</span>` : fresh.length ? `<button type="button" id="liste-add">Ajouter ${fmt(Math.min(fresh.length, Math.max(room, 0)))} formation${Math.min(fresh.length, Math.max(room, 0)) > 1 ? "s" : ""} à ma liste</button>` : `<span class="small muted">Toutes ces formations sont déjà dans votre liste.</span>`}
      <button type="button" id="liste-print">Imprimer</button></div>
    ${fresh.length && room < fresh.length ? `<p class="small muted no-print">Votre liste en contient déjà ${fmt(mine.length)} : ${voeux.MAX} vœux au maximum, ${fmt(fresh.length - Math.max(room, 0))} formation${fresh.length - Math.max(room, 0) > 1 ? "s" : ""} ne seront pas ajoutée${fresh.length - Math.max(room, 0) > 1 ? "s" : ""}.</p>` : ""}
    <p class="small muted no-print" id="liste-msg" aria-live="polite"></p></div>`;
  const add = document.getElementById("liste-add");
  if (add) add.onclick = () => {                    // adds the missing codes, never replaces the student's own list or profile
    let n = 0;
    for (const c of fresh) if (voeux.add(c)) n++;
    voeux.render();
    add.disabled = true;
    document.getElementById("liste-msg").innerHTML = `${fmt(n)} formation${n > 1 ? "s" : ""} ajoutée${n > 1 ? "s" : ""}. <a href="#/voeux">Voir ma liste</a>`;
  };
  document.getElementById("liste-print").onclick = () => window.print();
}

// ---- PR 17 (owner, 2026-11-27): « Transférer sur mon autre appareil ». The SAME person moves her list and her profile: the link
// carries the list's codes and the profile, the average INCLUDED (the owner's exception to « a shared list never carries the
// average »), never the académie, the lycée, the town, the « boursier » box or the drafts. Everything after "#": never sent to a
// server, nothing stored. The other device replaces its list and profile only after a second click; its académie, lycée and town stay.
const TRANSFER_KEYS = { s: "serie", a: "spe1", b: "spe2", m: "mention", n: "moyenne", t: "statut", v: "voie", x: "maths_expertes" };
const TRANSFER_MAX = 600;                                               // a longer link is not read
function transferLink(ids, prof, app) {
  const q = new URLSearchParams();
  if (ids.length) q.set("l", ids.join(","));
  if (app && app.length) q.set("p", app.join(","));                    // PR 18: the separate apprenticeship list
  if (prof) {
    if (isReo(prof)) q.set("t", "r");
    else {
      const p = vxProfile(prof);
      q.set("s", p.serie); q.set("m", p.mention);
      if (p.moyenne !== null) q.set("n", String(p.moyenne));
      if (p.serie === "bg") {
        if (p.spe1 && p.spe2) { q.set("a", p.spe1); q.set("b", p.spe2); }   // never a default pair (R2)
        if (p.maths_expertes) q.set("x", "1");
      } else if (p.voie && p.voie !== "autre") q.set("v", p.voie);         // « autre » (not in the list) never travels
    }
  }
  return `${location.origin}${location.pathname === "/" ? "/" : location.pathname}#/transfert/${q.toString()}`;
}
function transferRead(raw) {
  const s = String(raw || "");
  if (!s || s.length > TRANSFER_MAX) return null;
  const q = new URLSearchParams(s), p = {}, notes = [];
  for (const [k, f] of Object.entries(TRANSFER_KEYS)) { const v = q.get(k); if (v && v.length <= 60) p[f] = v; }
  const ids = shareCodes(q.get("l") || ""), app = shareCodes(q.get("p") || "");
  let prof = null;
  if (p.statut === "r") prof = vxProfile({ statut: "reorientation" });
  else if (["bg", "bt", "bp"].includes(p.serie) && (MENTION_CODES.includes(p.mention) || validMoyenne(p.moyenne) !== null)) {
    const out = { serie: p.serie, statut: "terminale" };
    if (MENTION_CODES.includes(p.mention)) out.mention = p.mention;
    if (p.moyenne !== undefined) {
      const m = validMoyenne(p.moyenne);
      if (m !== null) out.moyenne = m; else notes.push("La moyenne du lien n'a pas pu être lue : elle n'est pas reprise.");
    }
    if (p.serie === "bg") {
      const codes = JV && JV.specialties ? new Set(JV.specialties.map((x) => x.code)) : null;
      if (!(codes && codes.has(p.spe1) && codes.has(p.spe2) && p.spe1 !== p.spe2)) {
        // no pair, no bac général profile (Codex): the pages would read it with a default pair the student never chose
        notes.push("Les spécialités du lien n'ont pas pu être vérifiées : le profil n'est pas repris. Indiquez-le dans « Mon profil ».");
        return ids.length || app.length ? { ids, app, prof: null, notes } : null;
      }
      out.spe1 = p.spe1; out.spe2 = p.spe2;
      out.maths_expertes = p.maths_expertes === "1";
    } else if (p.voie) {
      const route = JV && JV.voies && (JV.voies[p.serie] || []).find((x) => x.code === p.voie);
      if (route) { out.voie = route.code; out.voie_label = route.label; }
      else notes.push("La voie du bac du lien n'a pas pu être lue : choisissez-la dans « Mon profil ».");
    }
    prof = vxProfile(out);                                              // an average always sets its band (R5)
  } else if (Object.keys(p).length) notes.push("Le profil du lien n'a pas pu être lu : il n'est pas repris.");
  return ids.length || app.length || prof ? { ids, app, prof, notes } : null;
}
// what the other device keeps of its own profile: the académie, the lycée, the « boursier » box (never in the link)
function transferProfile(prof, local) {
  const l = local && typeof local === "object" && !Array.isArray(local) ? local : {};
  const keep = {};
  for (const k of ["academie", "lycee", "boursier"]) if (l[k] !== undefined && l[k] !== null && l[k] !== "") keep[k] = l[k];
  return { ...prof, ...keep };
}
function transferApply(t, mode) {
  const app = t.app || [];
  if (mode === "add") {
    let n = 0;
    for (const c of t.ids) if (voeux.add(c)) n++;
    for (const c of app) if (voeuxApp.add(c)) n++;
    return { list: n, profile: false };
  }
  voeux.set(t.ids.slice(0, voeux.MAX));
  voeuxApp.set(app.slice(0, voeuxApp.MAX));
  if (t.prof) store.set("profile", transferProfile(t.prof, store.get("profile", null)));
  voeux.render();
  return { list: t.ids.length + app.length, profile: !!t.prof };
}
let qrLoad = null;
function loadQr() {                                                     // static/vendor/qrcode (MIT), loaded on demand only
  qrLoad = qrLoad || new Promise((ok, ko) => {
    if (typeof qrcode === "function") { ok(); return; }
    const el = document.createElement("script");
    el.src = "/static/vendor/qrcode/qrcode.js"; el.onload = () => ok(); el.onerror = () => { qrLoad = null; ko(new Error("QR code indisponible")); };
    document.head.appendChild(el);
  });
  return qrLoad;
}
function qrMatrix(text) {                                               // rows of 0/1, error correction M (red team TF3 re-encodes it)
  const qr = qrcode(0, "M");
  qr.addData(text, "Byte");
  qr.make();
  const n = qr.getModuleCount(), rows = [];
  for (let r = 0; r < n; r++) { const row = []; for (let c = 0; c < n; c++) row.push(qr.isDark(r, c) ? 1 : 0); rows.push(row); }
  return rows;
}
function qrSvg(text, label) {                                           // black on white whatever the theme: a phone must read it
  const m = qrMatrix(text), n = m.length, q = 4;
  let d = "";
  m.forEach((row, r) => row.forEach((v, c) => { if (v) d += `M${c + q} ${r + q}h1v1h-1z`; }));
  return `<svg class="qr" viewBox="0 0 ${n + 2 * q} ${n + 2 * q}" role="img" aria-label="${esc(label)}" shape-rendering="crispEdges"><rect class="qr-bg" width="100%" height="100%"/><path class="qr-ink" d="${d}"/></svg>`;
}
function transferCard() {
  const ids = voeux.get(), app = voeuxApp.get(), prof = store.get("profile", null);
  if (!ids.length && !app.length && !prof) return "";
  const hasProf = !!prof && typeof prof === "object" && !Array.isArray(prof);
  const what = [ids.length ? `vos ${fmt(ids.length)} formation${ids.length > 1 ? "s" : ""}` : "", app.length ? `vos ${fmt(app.length)} vœu${app.length > 1 ? "x" : ""} en apprentissage` : "", hasProf ? (isReo(prof) ? "votre situation" : "votre profil, moyenne comprise") : ""].filter(Boolean).join(" et ");
  return `<section class="card no-print" id="vx-transfer"><h2>Transférer sur mon autre appareil</h2>
    <p class="small">Pour retrouver votre liste et votre profil sur votre téléphone ou sur un autre ordinateur, ouvrez ce lien sur l'autre appareil, ou scannez le QR code avec lui. Le lien contient ${what}. Il ne contient ni votre académie, ni votre lycée, ni votre ville : indiquez-les à nouveau dans « Mon profil ».</p>
    <p class="small"><strong>Ce lien est pour vous seul</strong>${hasProf && !isReo(prof) ? " : il contient votre moyenne" : ""}. Pour montrer votre liste à un proche, utilisez plutôt « Partager ou imprimer ma liste ».</p>
    <div class="share-row"><input id="tr-url" type="text" readonly aria-label="Lien de transfert vers mon autre appareil" value="">
      <button type="button" id="tr-copy">Copier le lien</button><button type="button" id="tr-qr">Afficher le QR code</button></div>
    <div id="tr-qrbox" class="qr-box"></div>
    <p class="small muted" id="tr-msg" aria-live="polite"></p>
    <p class="small muted">Le lien n'est jamais envoyé au serveur : tout se passe après le « # », dans vos navigateurs, et rien n'est enregistré. Vos brouillons de projets motivés restent sur cet appareil.</p></section>`;
}
// the transfer link of the lists and profile as they are NOW (Codex, PR 18: a removal on the page must not travel back); a QR code
// drawn for an older link is removed and can be drawn again
function transferRefresh() {
  const url = document.getElementById("tr-url");
  if (!url) return;
  const prof = store.get("profile", null);
  const link = transferLink(voeux.get(), prof && typeof prof === "object" && !Array.isArray(prof) ? prof : null, voeuxApp.get());
  if (url.value === link) return;
  url.value = link;
  const box = document.getElementById("tr-qrbox"), btn = document.getElementById("tr-qr");
  if (box) box.innerHTML = "";
  if (btn) btn.disabled = false;
}
function bindTransfer() {
  const url = document.getElementById("tr-url"), msg = document.getElementById("tr-msg");
  if (!url) return;
  transferRefresh();
  document.getElementById("tr-copy").onclick = () => {
    transferRefresh();                                                  // Codex (PR 18): the lists as they are now
    const done = () => { msg.textContent = "Lien copié : ouvrez-le sur votre autre appareil."; };
    const manual = () => { url.focus(); url.select(); msg.textContent = "Copiez le lien sélectionné."; };
    try { navigator.clipboard.writeText(url.value).then(done, manual); } catch (_) { manual(); }
  };
  const btn = document.getElementById("tr-qr"), box = document.getElementById("tr-qrbox");
  btn.onclick = async () => {
    transferRefresh();
    btn.disabled = true;
    try {
      await loadQr();
      if (!box.isConnected) return;                                     // the student left the page meanwhile
      box.innerHTML = `${qrSvg(url.value, "QR code du lien de transfert")}<p class="small muted">Scannez-le avec l'appareil photo de votre téléphone.</p>`;
    } catch (e) { if (box.isConnected) msg.textContent = "Le QR code n'a pas pu s'afficher : copiez le lien."; btn.disabled = false; }
  };
}
async function viewTransfert(raw) {
  const marker = `transfert:${raw}`;
  $view.dataset.rendered = marker;                                      // before any await (navigation races)
  $view.innerHTML = `<div class="card"><h1>Transfert depuis un autre appareil</h1><p class="muted small">Lecture du lien…</p></div>`;
  if (!JV) JV = await api("/api/journey/vocab").catch(() => null);      // the vocabulary validates the link's pair and route
  if ($view.dataset.rendered !== marker) return;                        // the student left meanwhile
  const t = transferRead(raw);
  const head = `<div class="card"><h1>Transfert depuis un autre appareil</h1>`;
  if (!t) { $view.innerHTML = `${head}<p class="warn">Ce lien ne contient ni formation ni profil lisible. Copiez-le à nouveau depuis « Mes vœux » sur votre autre appareil.</p></div>`; return; }
  const mine = voeux.get(), mineApp = voeuxApp.get(), local = store.get("profile", null), hasLocal = !!local && typeof local === "object" && !Array.isArray(local);
  const nApp = (x) => (x.length ? ` et ${fmt(x.length)} vœu${x.length > 1 ? "x" : ""} en apprentissage` : "");
  const line = (p) => (p ? profileLine(p, p.serie) : "aucun profil");
  const notes = t.notes.map((n) => `<p class="warn small">${esc(n)}</p>`).join("");
  const replaces = mine.length || mineApp.length || hasLocal;
  const draw = (step, done) => {
    if ($view.dataset.rendered !== marker) return;
    $view.innerHTML = `${head}
      <p>Ce lien vient de votre autre appareil. Il contient ${t.ids.length ? `<strong>${fmt(t.ids.length)} formation${t.ids.length > 1 ? "s" : ""}</strong>` : "aucune formation"}${nApp(t.app)}, et ${t.prof ? `ce profil : <strong>${line(t.prof)}</strong>` : "aucun profil"}.</p>
      ${notes}
      <p class="small">Sur cet appareil : ${fmt(mine.length)} formation${mine.length > 1 ? "s" : ""}${nApp(mineApp)}, et ${hasLocal ? `ce profil : ${line(vxProfile(local))}` : "aucun profil"}.${hasLocal && local.academie ? " Votre académie, votre lycée et votre ville restent ceux de cet appareil." : ""}</p>
      ${done ? `<p class="info" role="status">${done}</p><p class="toolbar"><a class="btnlink" href="#/voeux">Voir ma liste</a><a href="#/profil">Vérifier mon profil</a></p>`
        : step === "confirm" ? `<p class="toolbar"><span class="small">Remplacer la liste${t.prof ? " et le profil" : ""} de cet appareil par ceux du lien ?</span><button type="button" id="tf-yes">Oui, remplacer</button><button type="button" id="tf-no">Annuler</button></p>`
        : `<p class="toolbar"><button type="button" id="tf-install">${replaces ? "Remplacer par le contenu du lien" : "Installer sur cet appareil"}</button>${(t.ids.length || t.app.length) && (mine.length || mineApp.length || hasLocal) ? '<button type="button" id="tf-add">Ajouter seulement les formations à ma liste</button>' : ""}</p>`}
      <p class="small muted">Rien n'a été envoyé au serveur : le contenu du lien est lu dans ce navigateur. Après l'installation, il est retiré de la barre d'adresse.</p></div>`;
    const finish = (r) => {
      try { history.replaceState(history.state, "", "#/transfert"); } catch (_) { /* old browser */ }
      draw(null, `${fmt(r.list)} formation${r.list > 1 ? "s" : ""} ${r.profile ? "et votre profil " : ""}${r.list > 1 || r.profile ? "sont" : "est"} maintenant sur cet appareil.`);
    };
    const inst = document.getElementById("tf-install");
    if (inst) inst.onclick = () => { if (replaces) { draw("confirm"); document.getElementById("tf-no")?.focus(); } else finish(transferApply(t, "replace")); };
    const yes = document.getElementById("tf-yes");
    if (yes) yes.onclick = () => finish(transferApply(t, "replace"));
    const no = document.getElementById("tf-no");
    if (no) no.onclick = () => draw();
    const add = document.getElementById("tf-add");
    if (add) add.onclick = () => finish(transferApply(t, "add"));
  };
  draw();
}

// ---- PR 17 (owner, 2026-11-27): the teacher's kit for a one-hour class session. Our own words, no figure; the site's address as a
// QR code (drawn in the browser); the students' sheet prints on its own page. Nothing is asked about a student.
const KIT_STEPS = [
  ["5 min", "Présenter le site", "SupCompass lit les chiffres officiels de Parcoursup. Il montre où se situaient les admis des années passées : des repères, jamais des chances d'admission. Il ne crée pas de compte."],
  ["10 min", "Créer son profil", "Chaque élève ouvre « Mon profil » et indique son bac, ses deux spécialités ou sa voie, et sa mention visée. La moyenne est facultative et reste dans son navigateur."],
  ["15 min", "Explorer et choisir", "Les élèves cherchent des formations par mot, par ville ou sur la carte. Ils en ajoutent trois à cinq à « Mes vœux » et ouvrent la fiche de chacune."],
  ["10 min", "Lire sa liste", "Dans « Mes vœux », chacun regarde ses zones. La liste contient-elle au moins un vœu de sécurité ? La carte « Avant de confirmer » rappelle les dates à ne pas manquer."],
  ["10 min", "Préparer la suite", "Chacun note les portes ouvertes de sa liste et les ajoute à son agenda. Il repère les attendus de chaque formation pour son projet motivé."],
  ["5 min", "Emporter sa liste", "Rien n'est enregistré sur un serveur. Pour retrouver sa liste chez soi, l'élève utilise « Transférer sur mon autre appareil ». Pour la montrer à sa famille, « Partager ou imprimer ma liste »."],
];
const KIT_CHECK = ["Mon profil est rempli", "Ma liste contient au moins un vœu de sécurité", "J'ai ouvert la fiche Parcoursup de chaque formation",
  "J'ai noté les portes ouvertes de ma liste", "J'ai transféré ma liste sur mon téléphone ou je l'ai partagée"];
async function viewKit() {
  const marker = "kit";
  $view.dataset.rendered = marker;
  const site = `${location.origin}/`;
  $view.innerHTML = `<div class="card"><h1>Kit pour une séance en classe</h1>
    <p>Ce kit propose une séance d'une heure pour aider une classe à préparer ses vœux Parcoursup avec SupCompass. Il suffit d'une salle informatique ou des téléphones des élèves, et d'un vidéoprojecteur pour vous.</p>
    <div class="toolbar no-print"><button type="button" id="kit-print">Imprimer le déroulé et la fiche élève</button><a href="#/accompagner">Accompagner un élève</a></div></div>
  <section class="card"><h2>Le déroulé, minute par minute</h2><ol class="kit-steps">${KIT_STEPS.map(([d, t, x]) => `<li><strong>${esc(d)} · ${esc(t)}</strong><br>${esc(x)}</li>`).join("")}</ol></section>
  <section class="card"><h2>Points de vigilance</h2><ul>
    <li>Une zone n'est jamais une chance d'admission : le jury lit tout le dossier, et chaque année est différente.</li>
    <li>La fiche de la formation sur Parcoursup fait foi, comme le <a href="#/calendrier">calendrier officiel</a>.</li>
    <li>Un élève qui n'est plus en terminale passe par « <a href="#/reorientation">Je me réoriente</a> » : le site ne lui montre pas de zone.</li>
    <li>Aucune page ne demande de nom, de note ou de rang. Ne demandez pas aux élèves de vous les donner sur le site.</li></ul></section>
  <section class="card kit-sheet"><h2>Fiche élève</h2>
    <p>Ouvrez SupCompass sur votre téléphone ou votre ordinateur : <strong>${esc(site)}</strong></p>
    <div id="kit-qr" class="qr-box" aria-live="polite"></div>
    <ol>${KIT_STEPS.slice(1).map(([, t, x]) => `<li><strong>${esc(t)}</strong> : ${esc(x)}</li>`).join("")}</ol>
    <h3>Avant de partir</h3><ul class="kit-check">${KIT_CHECK.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <p class="small">Des parts d'admis des campagnes passées, pas des chances d'admission. La fiche de chaque formation sur Parcoursup fait foi.</p></section>`;
  document.getElementById("kit-print").onclick = () => window.print();
  try {
    await loadQr();
    const box = document.getElementById("kit-qr");
    if ($view.dataset.rendered === marker && box) box.innerHTML = qrSvg(site, "QR code de l'adresse de SupCompass");
  } catch (_) { /* the address is printed in words anyway */ }
}

// ---- sprint Q1 (owner, 2026-11-13): trust and compliance pages and the contact form ----
// The five pages (À propos, Contact, Mentions légales, Confidentialité, Accessibilité) come from legal.py, the same HTML as their
// server page (/a-propos…). The contact form sends only what it shows; a message that was not stored is said, never a fake success.
const INFO_SLUGS = ["a-propos", "contact", "mentions-legales", "confidentialite", "accessibilite", "aide", "nos-chiffres", "robustesse"];   // "aide": sprint Q4; "nos-chiffres": owner, 2026-11-16; "robustesse": owner, 2026-11-17
const CONTACT_TYPES = [["erreur", "Une erreur dans un chiffre ou un texte"], ["question", "Une question sur le site"],
  ["suggestion", "Une suggestion"], ["autre", "Autre chose"]];
const CONTACT_MAX = 1000, CONTACT_MIN = 10;
const reportLink = (cod) => `<p class="report-link small"><a href="#/info/contact/${esc(cod)}">Signaler une erreur sur cette page</a></p>`;
async function viewInfo(slug, code) {
  if (!INFO_SLUGS.includes(slug)) slug = "a-propos";
  const kept = $view.querySelector(`[data-seo="${slug}"]`);
  if (!kept) {
    const p = await api(`/api/page/${slug}`);
    $view.innerHTML = `<article class="card legal" data-seo="${esc(slug)}">${p.html}</article>`;
  }
  $view.dataset.rendered = "info";
  if (slug === "aide" && isReo(store.get("profile", null))) aideAdultesFirst();
  if (slug === "contact") contactForm(/^\d{1,9}$/.test(code) ? code : "");
}
// lot 1, PR 12 (Sarah: « le ton est lycéen, l'aide commence par le professeur principal »): outside terminale the help page
// opens on the adults' services (same page, same text, only the order changes; the server page stays the same for everyone)
function aideAdultesFirst() {
  const art = $view.querySelector("article.legal"), h = art && art.querySelector("#aide-adultes"), first = art && art.querySelector("section.aide-service");
  if (!h || !first || h.dataset.moved) return;
  const parts = [h];
  for (let n = h.nextElementSibling; n && !n.matches("p.muted.small:last-child"); n = n.nextElementSibling) {
    if (n.matches("p.muted.small") && /Pages officielles lues/.test(n.textContent)) { parts.push(n); break; }
    parts.push(n);
  }
  for (const n of parts) first.before(n);
  h.dataset.moved = "1";
  first.insertAdjacentHTML("beforebegin", '<h2 id="aide-lycee">Les services pour les lycéens et leurs familles</h2>');
}
function contactForm(code) {
  const box = document.getElementById("contact-form");
  if (!box) return;
  const page = code ? `/formation/${code}` : "";
  box.innerHTML = `<form id="cform" class="cform" novalidate>
    ${code ? `<p class="small">Formation concernée : <a href="#/f/${esc(code)}">n° ${esc(code)}</a></p>` : ""}
    <fieldset><legend>Sujet de votre message</legend>
      ${CONTACT_TYPES.map(([k, l], i) => `<label class="radio"><input type="radio" name="type" value="${k}"${(code ? k === "erreur" : i === 0) ? " checked" : ""}> ${esc(l)}</label>`).join("")}
    </fieldset>
    <label for="cmsg">Votre message <span class="muted small">(${CONTACT_MIN} à ${CONTACT_MAX} caractères)</span></label>
    <textarea id="cmsg" name="message" rows="6" maxlength="${CONTACT_MAX}" required aria-describedby="cmsg-n cmsg-help"></textarea>
    <p id="cmsg-help" class="muted small">Pour une erreur, dites quel chiffre ou quel texte, et ce que vous attendiez. N'écrivez pas d'information personnelle (nom, numéro de dossier).</p>
    <p id="cmsg-n" class="muted small" aria-live="polite">0 / ${CONTACT_MAX}</p>
    <label for="cmail">Votre adresse e-mail, si vous souhaitez une réponse <span class="muted small">(facultatif)</span></label>
    <input id="cmail" name="email" type="email" maxlength="120" autocomplete="email" aria-describedby="cmail-help">
    <p id="cmail-help" class="muted small">Elle sert seulement à vous répondre et elle est supprimée avec le message, au bout de 12 mois. Moins de 15 ans : demandez l'accord d'un parent.</p>
    <div class="hp" aria-hidden="true"><label for="csite">Ne pas remplir</label><input id="csite" name="site" type="text" tabindex="-1" autocomplete="off"></div>
    <button type="submit" class="primary">Envoyer</button>
    <p id="cform-msg" role="status" class="small"></p>
  </form>`;
  const f = document.getElementById("cform"), msg = document.getElementById("cmsg"), n = document.getElementById("cmsg-n"), out = document.getElementById("cform-msg");
  msg.oninput = () => { n.textContent = `${msg.value.length} / ${CONTACT_MAX}`; };
  const mark = (field) => {
    f.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    const target = field === "message" ? msg : field === "email" ? document.getElementById("cmail") : null;
    if (target) { target.setAttribute("aria-invalid", "true"); target.focus(); }
  };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const body = { type: (f.querySelector("[name=type]:checked") || {}).value || "", message: msg.value,
      email: document.getElementById("cmail").value.trim(), site: document.getElementById("csite").value };
    if (page) { body.page = page; body.code = code; }
    if (msg.value.trim().length < CONTACT_MIN) { mark("message"); out.className = "small warn"; out.textContent = `Votre message est trop court (au moins ${CONTACT_MIN} caractères).`; return; }
    const btn = f.querySelector("button[type=submit]");
    btn.disabled = true; out.className = "small muted"; out.textContent = "Envoi en cours…";
    let r = null, d = {};
    try { r = await fetch("/api/contact", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); d = await r.json().catch(() => ({})); }
    catch (_) { r = null; }
    btn.disabled = false;
    if (r && r.status === 201 && d.ok) {
      f.reset(); n.textContent = `0 / ${CONTACT_MAX}`; mark(null);
      out.className = "small ok"; out.textContent = "Message envoyé. Merci : il sera lu et, si vous avez laissé une adresse, vous recevrez une réponse.";
      return;
    }
    mark(r && r.status === 422 ? d.field : null);
    out.className = "small warn";
    out.textContent = r ? `Message non envoyé. ${apiErrorText(d.detail)}` : "Message non envoyé : pas de connexion. Vérifiez votre réseau et réessayez.";
  };
}

// ---- lot 1 UI: the current tab is marked (aria-current) in both menus; "Plus" opens the other pages ----
// R1 (owner, 2026-11-11): the tabs follow the student's journey. Explorer ("home") holds the list, the map, the jobs and every
// formation page; "Mon profil" holds the profile, "Où je me situe", "Je me réoriente" and the seconde/première page.
const TAB_OF = { info: "info", s: "home", recherche: "home", f: "home", evolution: "home", parcours: "profil", profil: "profil", metiers: "home", voeux: "voeux",
  carte: "home", compare: "compare", specialites: "specialites", qualite: "qualite", glossaire: "glossaire", stats: "stats",
  comprendre: "comprendre", selectivite: "selectivite", observatoire: "observatoire", reorientation: "profil",
  calendrier: "calendrier", accompagner: "accompagner", premiere: "profil", liste: "liste", guide: "voeux", projet: "voeux",
  "portes-ouvertes": "calendrier", transfert: "voeux", kit: "accompagner", "apres-juin": "calendrier" };
const COMP_TABS = ["compare", "comprendre", "selectivite", "observatoire", "specialites", "qualite", "glossaire"];   // "Comprendre" on a wide screen
const MORE_TABS = [...COMP_TABS, "accompagner", "aide"];                                                   // "Plus" on a phone
function markTab(tab) {
  document.querySelectorAll("[data-tab]").forEach((el) => {
    if (el.dataset.tab === tab) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
  for (const [b, m, tabs] of [["more-btn", "more-menu", MORE_TABS], ["comp-btn", "comp-menu", COMP_TABS]]) {
    const btn = document.getElementById(b), menu = document.getElementById(m);
    if (btn) { btn.classList.toggle("current", tabs.includes(tab)); btn.setAttribute("aria-expanded", "false"); }
    if (menu) menu.hidden = true;
  }
}
// both menus open on a click, close on Escape (focus back on their button) and on a click elsewhere
for (const [b, m] of [["more-btn", "more-menu"], ["comp-btn", "comp-menu"]]) {
  const btn = document.getElementById(b), menu = document.getElementById(m);
  if (!btn || !menu) continue;
  btn.onclick = (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; btn.setAttribute("aria-expanded", String(!menu.hidden)); };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); btn.focus(); } });
  document.addEventListener("click", (e) => { if (!menu.hidden && (!menu.contains(e.target) || e.target.closest("a"))) { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); } });
}

// ---- router ----------------------------------------------------------------
const ROUTE_NAME = { info: "info", s: "search", recherche: "search", f: "fiche", evolution: "evolution", compare: "compare", specialites: "specialites",
  qualite: "qualite", parcours: "parcours", stats: "stats", glossaire: "glossaire", voeux: "voeux", metiers: "metiers", carte: "carte",
  comprendre: "comprendre", selectivite: "selectivite", observatoire: "observatoire", reorientation: "reorientation",
  calendrier: "calendrier", accompagner: "accompagner", premiere: "premiere", liste: "liste", profil: "profil", guide: "guide", projet: "projet",
  "portes-ouvertes": "portesouvertes", transfert: "transfert", kit: "kit", "apres-juin": "apresjuin" };
// Sprint 17: a formation or job opened at its indexable address (/formation/<code>, /metier/<id>) is the same view as its
// hash route; once the visitor navigates inside the app, the address goes back to "/#/…" so links stay the usual ones.
function pathRoute(pathname, hash) {
  if (hash && hash !== "#") return null;
  const f = /^\/formation\/(\d{1,9})\/?$/.exec(pathname);
  if (f) return `/f/${f[1]}`;
  const m = /^\/metier\/(MET\.\d{1,6})\/?$/.exec(pathname);
  if (m) return `/metiers/${m[1]}`;
  if (/^\/observatoire\/?$/.test(pathname)) return "/observatoire";                     // owner, 2026-11-20: indexable
  const i = /^\/(a-propos|contact|mentions-legales|confidentialite|accessibilite|aide|nos-chiffres|robustesse)\/?$/.exec(pathname);   // sprint Q1, Q4
  if (i) return `/info/${i[1]}`;
  return null;
}
// Sprint 17 (Codex): when the app cannot load its data (a crawler that may not fetch /api/, a network error), the
// server-rendered summary of an indexable page stays readable: the error is shown above it, never in its place.
function showError(e) {
  const kept = $view.querySelector("[data-seo]");
  const warn = `<div class="warn">${esc(e.message)}</div>`;
  if (kept) { $view.querySelectorAll(":scope > .warn").forEach((w) => w.remove()); kept.insertAdjacentHTML("beforebegin", warn); }
  else $view.innerHTML = warn;
}
// a link cut by a messenger ("%E0%A4%A") must not break the router: the segment is kept as it is (sprint 22 review)
function safeDecode(x) { try { return decodeURIComponent(x); } catch (_) { return x; } }
// ---- R8 (owner, 2026-11-12): accessibility of the single-page app (WCAG 2.1 AA) ----
// After each navigation: the tab title names the page (2.4.2), a polite status line says which page opened (4.1.3), and the
// keyboard focus moves to the page's heading (2.4.3), never on the first load. <main> itself is no live region (it would read
// whole pages aloud). Every horizontally scrolling table can be reached and scrolled with the keyboard (2.1.1).
let a11yFirst = true;
function a11yAfterRoute() {
  if (routeBackTo !== null) window.scrollTo(0, routeBackTo);       // back / forward: where the student was (U9)
  const h = $view.querySelector("h1");
  const name = h ? h.textContent.replace(/\s+/g, " ").trim() : "";
  document.title = name ? `${name} — SupCompass` : HOME_TITLE;
  if (a11yFirst) { a11yFirst = false; return; }
  const st = document.getElementById("sr-status");
  if (st) st.textContent = name ? `Page : ${name}` : "Page chargée";
  const target = h || $view;
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}
function a11yScrollRegions(root) {
  root.querySelectorAll(".scroll:not([tabindex])").forEach((el) => {
    const box = el.closest(".card, section, details"), head = box && box.querySelector("h1, h2, h3, summary");
    el.setAttribute("tabindex", "0");
    el.setAttribute("role", "region");
    const base = head ? `Tableau : ${head.textContent.replace(/\s+/g, " ").trim().slice(0, 80)}` : "Tableau";
    let name = base, k = 1;                                              // every region of the page has its own name
    while (root.querySelector(`.scroll[aria-label="${CSS.escape(name)}"]`)) name = `${base} (${++k})`;
    el.setAttribute("aria-label", name);
  });
}
if (typeof MutationObserver !== "undefined") new MutationObserver(() => a11yScrollRegions($view)).observe($view, { childList: true, subtree: true });
// the skip link focuses <main> (its "#view" target would otherwise be read as a route)
document.querySelector(".skip")?.addEventListener("click", (e) => { e.preventDefault(); $view.focus(); });
// a tooltip can be dismissed with Escape (1.4.13), and comes back when the pointer or the focus leaves it
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.querySelectorAll(".tip:hover, .tip:focus").forEach((t) => t.classList.add("tip-off"));
});
document.addEventListener("focusout", (e) => { if (e.target.classList && e.target.classList.contains("tip")) e.target.classList.remove("tip-off"); });
document.addEventListener("mouseout", (e) => { if (e.target.classList && e.target.classList.contains("tip")) e.target.classList.remove("tip-off"); });

// each navigation gets its own number: a route that finishes after the student has left it (a slow
// answer) must not move the focus, announce a page or show an error over the current one (Codex)
let routeSeq = 0;
// scroll (audit, 2026-11-23): the page is one document, so a new route kept the previous page's scroll position (Mes vœux
// opened 3,400 px down, « Je me réoriente » under its own title). Each history entry now remembers its own position in its
// state: a NEW entry (a link, a typed address) opens at the top; back / forward, or the same page drawn again, returns to
// where the student was. Red team U9.
if ("scrollRestoration" in history) history.scrollRestoration = "manual";
const savedY = () => (history.state && Number.isFinite(history.state.y) ? history.state.y : null);
let scrollSave = 0, routeBackTo = null;   // routeBackTo: restored by a11yAfterRoute, which only the route still current reaches
window.addEventListener("scroll", () => {
  clearTimeout(scrollSave);
  scrollSave = setTimeout(() => { try { history.replaceState({ ...(history.state || {}), y: Math.round(window.scrollY) }, ""); } catch (e) { /* ignore */ } }, 100);
}, { passive: true });
async function route() {
  const seq = ++routeSeq;
  if (location.pathname !== "/" && location.hash && location.hash !== "#") history.replaceState(null, "", "/" + location.hash);
  const backTo = savedY();
  clearTimeout(scrollSave);
  routeBackTo = backTo;
  if (backTo === null) window.scrollTo(0, 0);
  if (!pathRoute(location.pathname, location.hash)) document.title = HOME_TITLE;
  // Split before decoding: a pasted fiche URL is one %2F-encoded segment.
  const [, a, b, c] = (pathRoute(location.pathname, location.hash) || location.hash.slice(1) || "/").split("/").map(safeDecode);
  trackView(ROUTE_NAME[a] || "home", a === "f" ? b : null);
  // every navigation invalidates the render marker: only the view that sets it again may still be
  // filled by a late async answer (the lycée suggestion of a search, found in review)
  delete $view.dataset.rendered;
  markTab(a === "info" && b === "aide" ? "aide" : TAB_OF[a] || "home");                  // Q4: the help page has its own menu link
  profileBar.render(!a && !pathRoute(location.pathname, location.hash) ? "accueil" : TAB_OF[a] || "home");   // Q5: the home itself
  try {
    await routeView(a, b, c);
  } catch (e) {
    if (seq === routeSeq) showError(e);
  }
  if (seq === routeSeq) a11yAfterRoute();
}
async function routeView(a, b, c) {
  {
    if (a === "stats") return await viewStats(b);
    if (a === "s") return await viewSearch(b || "", c || "");
    if (a === "recherche") return viewRecherche(b || "");
    if (a === "f") return await viewFormation(b, c);
    if (a === "evolution") return await viewEvolution(b);
    if (a === "compare") return await viewCompare();
    if (a === "specialites") return await viewSpecialites(b, c);
    if (a === "qualite") return await viewQualite();
    if (a === "parcours") return await viewParcours();
    if (a === "profil") return await viewProfil();
    if (a === "voeux") return await viewVoeux();
    if (a === "carte") return await viewCarte(b || "", c || "");
    if (a === "comprendre") return await viewComprendre();
    if (a === "selectivite") return await viewSelectivite(b || "", c || "");
    if (a === "observatoire") return await viewObservatoire();
    if (a === "reorientation") return await viewReorientation(b || "", c || "");
    if (a === "calendrier") return await viewCalendrier();
    if (a === "accompagner") return viewAccompagner();
    if (a === "premiere") return await viewPremiere();
    if (a === "liste") return await viewListe(b || "", c || "");
    if (a === "transfert") return await viewTransfert(b || "");
    if (a === "kit") return await viewKit();
    if (a === "guide") return await viewGuide();
    if (a === "projet") return await viewProjet(b || "");
    if (a === "portes-ouvertes") return await viewPortesOuvertes();
    if (a === "apres-juin") return await viewApresJuin();
    if (a === "metiers") return await viewMetiers(b || "", c || "");
    if (a === "glossaire") return viewGlossaire(b || "");
    if (a === "info") return await viewInfo(b || "", c || "");
    return await viewSearch("");
  }
}

window.addEventListener("hashchange", route);
(async () => {
  try { META = await api("/api/meta"); } catch (e) { showError(e); return; }
  basket.render(); voeux.render(); route();
})();
