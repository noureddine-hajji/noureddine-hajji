"use strict";
// SupCompass front-end: hash router + dependency-free SVG charts.

const $view = document.getElementById("view");
let META = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d });
const pct = (v) => (v === null || v === undefined) ? "—" : `${fmt(v, 1)} %`;
const tip = (key) => {
  const t = META?.methodology?.[key];
  return t ? `<button type="button" class="tip" aria-label="Méthodologie" data-tip="${esc(t)}">i</button>` : "";
};
const label = (f) => META?.fields?.[f]?.label || f;

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

// ---- point 4 of the UI brief: the profile and the zones of "Mes vœux", at the top of every page ----
// The stored profile is never trusted: the same cleaning as "Mes vœux". vxQuery is the ONE query both send, so the bar and
// the page always count the same zones (red team P2). Counts only, never a chance.
function vxProfile(p) {
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";
  const mention = ["sansmention", "ab", "b", "tb"].includes(p.mention) ? p.mention : "ab";
  const jv = typeof JV !== "undefined" ? JV : null;                       // the vocabulary, when "Mon parcours" loaded it
  const codes = jv && jv.voies && jv.voies[serie] ? jv.voies[serie].map((x) => x.code) : null;
  const keep = serie !== "bg" && typeof p.voie === "string" && (!codes || p.voie === "autre" || codes.includes(p.voie));
  return { ...p, serie, mention, voie: keep ? p.voie : null, voie_label: keep ? p.voie_label : null,
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
  const qs = new URLSearchParams({ ids: ids.join(","), serie: prof.serie, mention: prof.mention });
  if (prof.serie === "bg") { qs.set("spe1", prof.spe1 || "MATHS"); qs.set("spe2", prof.spe2 || "SES"); }
  if (prof.academie) qs.set("academie", prof.academie);
  if (prof.serie !== "bg" && typeof prof.voie === "string" && prof.voie) qs.set("voie", prof.voie.slice(0, 120));   // sprint 20
  return qs;
}
const PB_ZONES = ["securite", "cible", "ambitieux"];
const profileBar = {
  key: "", data: null, tab: "home",
  render(tab) {
    if (tab) this.tab = tab;
    const el = document.getElementById("profile-bar");
    if (!el) return;
    const raw = store.get("profile", null);
    profileChip(this.tab, raw);
    if (this.tab === "stats" || this.tab === "liste") { el.hidden = true; return; }   // sprint 22: a shared list is someone else's
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
    let list;
    if (isReo(prof)) {                                                   // sprint 21: no zone for this group, no zone request
      this.key = ""; this.data = null;
      list = `<a class="pb-link" href="#/voeux">Mes vœux : ${ids.length ? `${fmt(ids.length)}, accès estimé hors terminale` : "aucun pour l'instant"}</a>`;
    } else if (!ids.length) { this.key = ""; this.data = null; list = `<a class="pb-link" href="#/voeux">Mes vœux : aucun pour l'instant</a>`; }
    else {
      const k = vxQuery(ids, prof).toString();
      if (this.key !== k) {
        this.key = k; this.data = null;
        api(`/api/voeux?${k}`).then((d) => { if (this.key === k) { this.data = d; this.render(); } })
          .catch(() => { if (this.key === k) { this.data = { error: true }; this.render(); } });
      }
      const d = this.data;
      if (!d) list = `<span class="pb-list muted">Mes vœux : lecture…</span>`;
      else if (d.error || !d.lecture) list = `<a class="pb-link" href="#/voeux">Mes vœux : ${fmt(ids.length)}</a>`;
      else {
        const z = d.lecture.zones, other = (z.hors_profil || 0) + (z.non_ouvert || 0) + (z.indetermine || 0) + (z.non_situe || 0);
        const parts = PB_ZONES.map((k2) => `<span class="pb-zone"><span style="color:${ZONES[k2].color}">${zoneMark(k2)}</span>${fmt(z[k2] || 0)} ${esc(ZONES[k2].label.replace(/^Vœu (de )?/, ""))}</span>`);
        if (other) parts.push(`<span class="pb-zone">${fmt(other)} autre${other > 1 ? "s" : ""}</span>`);
        const alert = d.lecture.messages.some((m) => m.code === "aucune_securite")
          ? `<a class="pb-alert" href="#/voeux">Aucun vœu de sécurité sûr</a>` : "";
        list = `<a class="pb-list" href="#/voeux" aria-label="Mes vœux, zones pour votre profil">Mes vœux : ${parts.join(" · ")}</a>${alert}`;
      }
    }
    el.innerHTML = `<a class="pb-who" href="#/profil" aria-label="Votre profil, le modifier dans Mon profil">${profileLine(prof, prof.serie)}</a>${list}`;
  },
};
// R1 (owner, 2026-11-11): the profile chip of the wide-screen header, read from the same stored profile as the bar (escaped,
// validated by vxProfile); hidden where the profile bar is (stats, a shared list)
const MENTION_SHORT = { sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien" };
function chipLine(p) {
  if (isReo(p)) return REO_LABEL;
  const ser = { bg: "bac général", bt: "bac techno", bp: "bac pro" }[p.serie];
  const what = p.serie === "bg" ? `${esc(p.spe1 || "")} + ${esc(p.spe2 || "")}` : p.voie_label ? esc(p.voie_label) : "";
  return [ser, what, MENTION_SHORT[p.mention]].filter(Boolean).join(" · ");
}
function profileChip(tab, raw) {
  const el = document.getElementById("profile-chip");
  if (!el) return;
  if (tab === "stats" || tab === "liste") { el.hidden = true; return; }
  el.hidden = false;
  const has = !!raw && typeof raw === "object" && !Array.isArray(raw);
  el.classList.toggle("empty", !has);
  el.setAttribute("aria-label", has ? "Votre profil, le modifier" : "Créer mon profil");
  el.innerHTML = has ? `<span>${chipLine(vxProfile(raw))}</span>${ICONS.edit}` : `${ICONS.profile}<span>Créer mon profil</span>`;
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

function lineChart(years, series, { yMax = 100, unit = "%", h = 180 } = {}) {
  const W = 440, H = h, L = 36, R = 10, T = 10, B = 24;
  const P = 24;  // keep end points clear of the y-axis labels and the right edge
  const x = (i) => L + P + (years.length === 1 ? (W - L - R - 2 * P) / 2 : i * (W - L - R - 2 * P) / (years.length - 1));
  const max = yMax ?? Math.max(1, ...series.flatMap((s) => s.values.filter((v) => v != null)));
  const y = (v) => T + (H - T - B) * (1 - v / max);
  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = max * k / 4;
    g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 4}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`;
  }
  years.forEach((yr, i) => { g += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${yr}</text>`; });
  series.forEach((s, si) => {
    const c = s.color || COLORS[si % COLORS.length];
    let d = "", pen = false;
    s.values.forEach((v, i) => {
      if (v == null) { pen = false; return; }          // gaps stay gaps: no interpolation over missing years
      d += `${pen ? "L" : "M"}${x(i)},${y(v)}`; pen = true;
    });
    const dash = seriesDash(s, si);
    g += `<path d="${d}" fill="none" stroke="${c}" stroke-width="2"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
    s.values.forEach((v, i) => {
      if (v == null) return;
      const hollow = s.hollow?.[i];
      g += `<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="${hollow ? "var(--surface)" : c}" stroke="${c}" stroke-width="2"><title>${esc(s.name)} ${years[i]} : ${fmt(v, 1)}${unit === "%" ? " %" : ""}${hollow ? " (effectif < seuil)" : ""}</title></circle>`;
    });
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(chartName(series.map((x) => x.name), years))}">${g}</svg>`;
}

function stackedBars(years, keys, rows, { normalize = true, h = 190 } = {}) {
  const W = 440, H = h, L = 36, R = 10, T = 10, B = 24;
  const n = years.length, slot = (W - L - R) / n, bw = Math.min(46, slot * 0.6);
  const totals = rows.map((r) => r ? keys.reduce((a, k) => a + (r[k.key] || 0), 0) : 0);
  const max = normalize ? 100 : Math.max(1, ...totals);
  const y = (v) => T + (H - T - B) * (1 - v / max);
  let g = "";
  for (let k = 0; k <= 4; k++) { const v = max * k / 4; g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 4}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`; }
  rows.forEach((r, i) => {
    const cx = L + slot * i + slot / 2;
    g += `<text x="${cx}" y="${H - 6}" text-anchor="middle">${years[i]}</text>`;
    if (!r || !totals[i]) { g += `<text x="${cx}" y="${y(max / 2)}" text-anchor="middle">n.d.</text>`; return; }
    let acc = 0;
    keys.forEach((k, ki) => {
      const raw = r[k.key] || 0, v = normalize ? 100 * raw / totals[i] : raw;
      if (v <= 0) return;
      const y0 = y(acc + v), hgt = y(acc) - y(acc + v);
      g += `<rect x="${cx - bw / 2}" y="${y0}" width="${bw}" height="${Math.max(hgt - 1, 0.5)}" fill="${k.color || COLORS[ki]}"><title>${esc(k.name)} ${years[i]} : ${fmt(raw)}${normalize ? ` (${fmt(v, 1)} %)` : ""}</title></rect>`;
      acc += v;
    });
    if (r.low_n_flag) g += `<text x="${cx}" y="${y(acc) - 4}" text-anchor="middle">n&lt;${META.low_n_threshold}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(chartName(keys.map((k) => k.name), years))}${normalize ? ", parts en %" : ""}">${g}</svg>`;
}

const legend = (items) => `<div class="legend">${items.map((k, i) => `<span><i style="background:${k.color || COLORS[i]}"></i>${esc(k.name)}</span>`).join("")}</div>`;
// the legend of a line chart: the same colour AND the same dash as the line
const lineLegend = (items) => `<div class="legend">${items.map((k, i) => `<span><svg class="lg-line" viewBox="0 0 22 8" aria-hidden="true"><line x1="1" y1="4" x2="21" y2="4" stroke="${k.color || COLORS[i]}" stroke-width="2.5"${seriesDash(k, i) ? ` stroke-dasharray="${seriesDash(k, i)}"` : ""}/></svg>${esc(k.name)}</span>`).join("")}</div>`;

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
  : `<span class="badge exact" title="Même (cod_uai, cod_aff_form)">exact</span>`;

// ---- views -----------------------------------------------------------------
const INTERP_LABEL = { option: "Option", lieu: "Lieu", sigle: "Reconnu", "corrigé": "Corrigé", "approché": "Mot approché", "ignoré": "Ignoré", uai: "Établissement (UAI)" };
// ---- offer options (cartographie Parcoursup) and offer timing ---------------------------------
const OPT_LABEL = { internat: "Internat", apprentissage: "Apprentissage", distance: "À distance", sport: "Sportifs de haut niveau", art: "Artistes de haut niveau" };
// small drawn icons (trusted constants, never data): the design guidelines rule out emoji as markers
const ICO = (d) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const ICONS = {
  search: ICO('<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>'),
  job: ICO('<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M9 7.5V5.5h6v2"/>'),
  compass: ICO('<circle cx="12" cy="12" r="8.5"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>'),
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
const FILI_LABEL = { Licence_Las: "Licence L.AS", "Ecole d'Ingénieur": "École d'ingénieurs", "Ecole de Commerce": "École de commerce", "Autre formation": "Autres formations" };

function searchHash(q, params) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null && v !== 0)).toString();
  return `#/s/${encodeURIComponent(q)}${qs ? `/${encodeURIComponent(qs)}` : ""}`;
}

// ---- lot 1 UI: the home page opens on four doors (a formation, a job, where I stand, sprint 21: I am not in terminale) ----
const HOME_EXAMPLES = ["BTS NDRC", "prépa HEC Lyon", "IUT informatique Toulouse", "infirmière Bordeaux", "kiné"];
// R1 (owner, 2026-11-11): "Explorer" is one place with three views of the same offer: the list (search), the map, the jobs
const EXPLORER_VIEWS = [["liste", "Liste", "list"], ["carte", "Carte", "map"], ["metiers", "Métiers", "job"]];
function explorerViews(cur, q = "") {
  const href = { liste: q ? `#/s/${encodeURIComponent(q)}` : "#/", carte: "#/carte", metiers: "#/metiers" };
  return `<nav class="views" aria-label="Explorer : choisir la vue">${EXPLORER_VIEWS.map(([k, label, ico]) =>
    `<a href="${esc(href[k])}"${k === cur ? ' aria-current="true"' : ""}>${ICONS[ico]}${label}</a>`).join("")}</nav>`;
}
// the profile the results are read for, said on the Explorer home (escaped by profileLine); no profile: one call to create it
function homeProfile() {
  const raw = store.get("profile", null);
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return `<div class="card home-profile"><p><strong>Commencez par votre profil.</strong> Votre bac, vos spécialités et votre mention visée : SupCompass lit alors chaque formation pour vous (zone, votre ligne dans le rapport du jury). Une minute, sans compte, gardé dans ce navigateur.</p>
      <a class="btnlink" href="#/profil">Créer mon profil</a></div>`;
  }
  const p = vxProfile(raw);
  return `<div class="card home-profile"><p class="small">Les résultats sont lus pour : <strong>${profileLine(p, p.serie)}</strong></p><a class="btnlink" href="#/profil">Modifier mon profil</a></div>`;
}
function viewHome() {
  const n = voeux.get().length;
  $view.innerHTML = `<section class="hero"><h1>Trouvez votre voie après le bac</h1>
    <p>Les chiffres officiels de Parcoursup 2022–2025, expliqués simplement. Des repères pour choisir, jamais des pronostics.</p></section>
  ${explorerViews("liste")}
  ${homeProfile()}
  <div class="doors">
    <button type="button" class="door" id="door-search"><span class="door-ico" aria-hidden="true">${ICONS.search}</span><strong>Je cherche une formation</strong>
      <span>Un nom, une ville, un sigle : même avec des fautes de frappe.</span></button>
    <a class="door" href="#/metiers"><span class="door-ico" aria-hidden="true">${ICONS.job}</span><strong>Je pars d'un métier</strong>
      <span>Développeur, infirmière, juriste… voyez les formations qui y mènent.</span></a>
    <a class="door" href="#/parcours"><span class="door-ico" aria-hidden="true">${ICONS.compass}</span><strong>Je veux savoir où je me situe</strong>
      <span>Votre bac, vos spécialités, votre mention : voyez où se situaient les admis des années passées.</span></a>
    <a class="door" href="#/reorientation"><span class="door-ico" aria-hidden="true">${ICONS.reorientation}</span><strong>Je me réoriente ou je reprends mes études</strong>
      <span>Vous n'êtes plus en terminale : voyez les formations qui accueillent des candidats comme vous.</span></a>
  </div>
  <p class="home-more small"><a href="#/premiere">En seconde ou en première ? Comparez les doublettes possibles de vos spécialités</a> · <a href="#/calendrier">Calendrier Parcoursup</a> · <a href="#/accompagner">Parents et professeurs</a></p>
  <div class="card"><h2>Idées de recherche</h2>
    <div class="toolbar">${HOME_EXAMPLES.map((e) => `<a class="badge" href="#/s/${encodeURIComponent(e)}">${esc(e)}</a>`).join("")}</div>
    ${n ? `<p><a href="#/voeux">Vous avez ${n} vœu${n > 1 ? "x" : ""} dans votre liste →</a></p>` : ""}</div>`;
  const door = document.getElementById("door-search");
  if (door) door.onclick = () => { const q = document.getElementById("q"); q.scrollIntoView({ block: "center" }); q.focus(); };
  $view.dataset.rendered = "home";
}

// ---- lot 1 UI: search filters are folded under "Filtrer" (open on wide screens); active ones stay visible ----
function searchFilters(P, go, facets, activeOpts, inner) {
  if (!inner.trim()) return "";
  const on = [];
  if (P.fili) on.push([`Type : ${FILI_LABEL[P.fili] || P.fili}`, go({ fili: "" })]);
  if (P.academie) on.push([`Académie : ${P.academie}`, go({ academie: "" })]);
  if (P.selective) on.push([P.selective === "true" ? "Sélectives" : "Non sélectives", go({ selective: "" })]);
  for (const o of activeOpts) on.push([OPT_LABEL[o], go({ options: activeOpts.filter((x) => x !== o).join(",") })]);
  for (const g of FI_GROUPS) {                                        // R3: every ticked advanced option is a removable chip
    const a = (P[g] || "").split(",").filter(Boolean);
    for (const k of a) { const o = fiOptions(g).find((x) => x.key === k); if (o) on.push([`${FI_TITLE[g]} : ${o.label}`, go({ [g]: a.filter((x) => x !== k).join(",") })]); }
  }
  const wide = typeof matchMedia === "function" && matchMedia("(min-width: 721px)").matches;
  const chips = on.length ? `<div class="toolbar active-filters" aria-label="Filtres actifs">${on.map(([l, h]) =>
    `<a class="badge exact" href="${esc(h)}" aria-label="Retirer le filtre ${esc(l)}">${esc(l)} ✕</a>`).join("")}</div>` : "";
  return `${chips}<details class="filters"${wide ? " open" : ""}><summary>${ICONS.filter}Filtrer${on.length ? ` (${on.length} actif${on.length > 1 ? "s" : ""})` : ""}</summary>${inner}</details>`;
}

// ---- lot 3 (Claude design guidelines): the same summary-first, folded-detail format on the four working pages ----
const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 720px)").matches;
const searchPage = () => (narrow() ? 20 : 40);
// zoneTiles: the zone counts of a list read as a summary (one tile per zone, the zone's own colour, never a chance)
function zoneTiles(counts, other) {
  const tile = (k, n) => `<div class="sum-tile">${zonePillHtml(k)}
      <span class="sum-value">${fmt(n)}</span><span class="sum-note">vœu${n > 1 ? "x" : ""}</span></div>`;
  return `<div class="sum-grid">${tile("securite", counts.securite || 0)}${tile("cible", counts.cible || 0)}${tile("ambitieux", counts.ambitieux || 0)}
    <div class="sum-tile"><span class="sum-label">Autres</span><span class="sum-value">${fmt(other)}</span><span class="sum-note">hors-profil, non ouverts ou non situés</span></div></div>`;
}
// profileLine: the stored profile read back in one line (the form folds under it once a profile exists)
function profileLine(p, serie) {
  if (isReo(p)) return [REO_LABEL, p.academie ? `académie de ${esc(p.academie)}` : ""].filter(Boolean).join(" · ");
  const ser = { bg: "bac général", bt: "bac technologique", bp: "bac professionnel" }[serie];
  const men = { sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien" }[p.mention] || "";
  return [ser, serie === "bg" ? `${esc(p.spe1 || "")} + ${esc(p.spe2 || "")}` : p.voie_label ? esc(p.voie_label) : "", men && `mention ${men}`, p.academie ? `académie de ${esc(p.academie)}` : ""]
    .filter(Boolean).join(" · ");
}

// ---- R3 (owner, 2026-11-12): the advanced filters shared by the search and the map -----------------------------------------
// The bands come from /api/meta (filtres.vocab): the search is filtered on the server, the map in the browser, with the SAME limits.
// The zone filter sends the profile with the search (bac, specialties, mention), never stored, never in the audience figures. The
// complementary phase is a fact of a past campaign (admits), never places left this year. Nothing is ever sorted by these values.
const FI_GROUPS = ["zone", "statut", "capacite", "complementaire", "taux"];
const FI_TITLE = { zone: "Zone pour votre profil", statut: "Type d'établissement", capacite: "Capacité", complementaire: "Phase complémentaire", taux: "Taux d'accès officiel" };
const FI_HELP = {
  zone: "Lue pour votre profil (bac, spécialités, mention), comme dans « Mes vœux » : rien n'est enregistré. Des repères, pas des chances.",
  complementaire: "Des admis en phase complémentaire lors de la campagne de la formation : pas une promesse de places cette année.",
  taux: "Le taux d'accès officiel de la formation, tous candidats confondus : un repère, pas vos chances.",
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
function zoneMark(z) {
  const filled = ZONE_FILLED.includes(z);
  return `<svg class="zmark" viewBox="0 0 14 14" aria-hidden="true">${zoneShape(z, 7, 7, filled ? 5.5 : 4.3,
    filled ? 'fill="currentColor"' : 'fill="none" stroke="currentColor" stroke-width="2"')}</svg>`;
}
// a zone pill: filled with the zone's token, its shape, its name
function zonePillHtml(z, uncertain) {
  const zz = ZONES[z];
  if (!zz) return "";
  return `<span class="zone-pill" style="background:${zz.color}">${zoneMark(z)}${esc(zz.label.replace(/^Vœu /, ""))}</span>${uncertain ? ' <span class="badge">incertain</span>' : ""}`;
}
// a zone badge (tables): outlined in the zone's token, its shape, its full name
function zoneBadge(z, uncertain) {
  const zz = ZONES[z];
  if (!zz) return '<span class="badge">non situé</span>';
  return `<span class="badge zbadge" style="--zc:${zz.color}">${zoneMark(z)}${esc(zz.label)}</span>${uncertain ? ' <span class="badge">incertain</span>' : ""}`;
}
// the search query of the profile (terminale only: no zone exists outside terminale, sprint 21)
function fiProfileQuery(qs) {
  const p = bacProfile();
  if (!p) return false;
  const v = vxProfile(p);
  if (v.serie === "bg" && (!v.spe1 || !v.spe2 || v.spe1 === v.spe2)) return false;
  qs.set("serie", v.serie); qs.set("mention", v.mention);
  if (v.serie === "bg") { qs.set("spe1", v.spe1); qs.set("spe2", v.spe2); }
  return true;
}
function searchAdvanced(P, go, d, chip) {
  const f = d.facets || {};
  const sel = (g) => (P[g] || "").split(",").filter(Boolean);
  const toggle = (g, k) => { const a = sel(g); return go({ [g]: (a.includes(k) ? a.filter((x) => x !== k) : [...a, k]).join(",") }); };
  return FI_GROUPS.map((g) => {
    if (g === "zone" && !d.zones_lues) {                               // review: no invitation outside terminale (no zone exists there)
      return isReo(store.get("profile", null)) ? ""
        : !bacProfile() ? `<p class="small"><span class="muted">${FI_TITLE.zone} :</span> <a href="#/profil">créez votre profil pour filtrer par vœux de sécurité, cibles ou ambitieux</a></p>` : "";
    }
    const counts = f[g] || {};
    const opts = fiOptions(g).filter((o) => counts[o.key] || sel(g).includes(o.key));
    if (!opts.length) return "";
    return `<div class="toolbar fi-group" aria-label="${esc(FI_TITLE[g])}"><span class="small muted">${esc(FI_TITLE[g])} :</span>${opts.map((o) =>
      chip(`${o.label} (${fmt(counts[o.key] || 0)})`, toggle(g, o.key), sel(g).includes(o.key))).join("")}</div>${FI_HELP[g] ? `<p class="muted small">${esc(FI_HELP[g])}</p>` : ""}`;
  }).join("");
}

// R4 (owner, 2026-11-12): a search result as a card. When the zones were read for the profile, the zone gives the card its left edge
// and its pill (token + shape + name, never the colour alone). The figure column holds the OFFICIAL access rate of the result's
// campaign; for a bac techno or pro profile, the same stage-2 row's ESTIMATED access for the series follows it (Mon parcours' "Accès
// estimé", said as an estimation, "peu de candidats" below 20 candidates of the series); bac général has no second figure here (the
// doublette figure needs the formation page: R2). Never a chance; every stored string escaped.
function resultCard(r) {
  const z = r.zone && ZONES[r.zone] ? r.zone : null;
  const est = r.estime_serie !== undefined && r.estime_serie !== null
    ? `<div class="rc-est"><strong>${fmt(r.estime_serie)} %</strong><span>accès estimé pour votre bac (estimation)${r.estime_fragile ? ", peu de candidats" : ""}</span></div>` : "";
  return `<article class="result rc${z ? " rc-z" : ""}"${z ? ` style="--zc:${ZONES[z].color}"` : ""}>
    <div class="rc-main">
      <a class="rc-title" href="#/f/${esc(r.cod_aff_form)}">${esc(r.g_ea_lib_vx)}</a>
      <div class="rc-sub">${esc(r.fil_lib_voe_acc)}${r.lib_comp_voe_ins ? ` <span class="muted">${esc(r.lib_comp_voe_ins)}</span>` : ""}</div>
      <div class="rc-meta muted small"><span>${esc(r.ville_etab)}${r.acad_mies ? ` (${esc(r.acad_mies)})` : ""}</span>${r.capa_fin !== undefined && r.capa_fin !== null ? `<span>${ICONS.places}${fmt(r.capa_fin)} places</span>` : ""}<span>campagne ${esc(r.session)} · ${esc(r.lineage_years)} campagne(s)</span></div>
      <div class="rc-badges">${z ? zonePillHtml(z, r.uncertain) : ""}<span class="badge">${esc(FILI_LABEL[r.fili] || r.fili)}</span>${lineageBadge(r.lineage_confidence)}${offerBadges(r, true)}${autresBadge(r)}${r.acc_pc > 0 ? `<span class="badge" title="${esc(FI_HELP.complementaire)}">admis en phase complémentaire ${esc(r.session)}</span>` : ""}${r.subwish_flag ? `<span class="badge warnb">sous-vœu</span>` : ""}${r.low_n_flag ? `<span class="badge warnb">n&lt;${META.low_n_threshold}</span>` : ""}</div>
    </div>
    <div class="rc-fig num"><div class="big">${pct(r.taux_acces_ens)}</div><div class="muted small">taux d'accès officiel</div>${est}</div>
  </article>`;
}

async function viewSearch(q, rawParams) {
  if (!q) return viewHome();
  const P = Object.fromEntries(new URLSearchParams(rawParams || ""));
  const near = store.get("profile", {}).academie || "";
  const PAGE = searchPage();                                          // lot 3: 20 results per page on a phone, 40 on a wide screen
  const qs = new URLSearchParams({ q, offset: P.offset || 0, limit: PAGE, avance: "true" });
  for (const k of ["fili", "academie", "selective", "options", ...FI_GROUPS]) if (P[k]) qs.set(k, P[k]);
  if (near) qs.set("near", near);
  const withProfile = fiProfileQuery(qs);                             // R3: the zones of every result, read for this answer only
  if (!withProfile) { qs.delete("zone"); delete P.zone; }            // review: no zone chip left for a filter not applied
  const d = await api(`/api/search?${qs}`);
  if (d.mode === "cod_aff_form" && d.results.length === 1) { location.hash = `#/f/${d.results[0].cod_aff_form}`; return; }
  const keep = Object.fromEntries(["fili", "academie", "selective", "options", ...FI_GROUPS].map((k) => [k, P[k]]));
  const go = (patch) => searchHash(q, { ...keep, ...patch, offset: patch.offset || 0 });
  const activeOpts = (P.options || "").split(",").filter((o) => OPT_LABEL[o]);
  const fromQuery = d.interpretation.filter((i) => i.type === "option").map((i) => i.value);
  const toggleOpt = (o) => { const a = activeOpts.includes(o) ? activeOpts.filter((x) => x !== o) : [...activeOpts, o]; return go({ options: a.join(",") }); };
  const chip = (label, href, active) => `<a class="badge${active ? " exact" : ""}" href="${esc(href)}">${esc(label)}</a>`;
  const facets = d.facets || {};
  const off = +(P.offset || 0);
  $view.innerHTML = `${explorerViews("liste", q)}<div class="card">
    <h2>${fmt(d.total)} formation(s)${d.partial ? ` <span class="badge warnb">résultats partiels</span>` : ""}</h2>
    ${d.interpretation.length ? `<div class="legend" aria-label="Interprétation de la recherche">${d.interpretation.map((i) => `<span class="badge">${esc(INTERP_LABEL[i.type] || i.type)} : ${esc(i.value)}</span>`).join("")}</div>` : ""}
    ${d.notes.map((n) => `<div class="info">${esc(n)}</div>`).join("")}
    ${d.total === 0 ? `<p class="muted">Aucune formation ne correspond. Essayez un sigle (BTS, BUT, MPSI…), un intitulé (droit, psychologie…) ou une ville.</p>` : ""}
    ${searchFilters(P, go, facets, activeOpts, `
    ${searchAdvanced(P, go, d, chip)}
    ${(facets.fili || []).length > 1 || P.fili ? `<div class="toolbar"><span class="small muted">Type :</span>${chip("Tous", go({ fili: "" }), !P.fili)}${(facets.fili || []).map((f) => chip(`${FILI_LABEL[f.value] || f.value} (${f.count})`, go({ fili: f.value }), P.fili === f.value)).join("")}</div>` : ""}
    ${(facets.options || []).some((o) => o.count || o.active) ? `<div class="toolbar" aria-label="Options de la formation"><span class="small muted">Options :</span>${facets.options.filter((o) => o.count || o.active).map((o) => fromQuery.includes(o.value) && !activeOpts.includes(o.value)
      ? `<span class="badge exact" title="Déduit de votre recherche : retirez le mot pour l'enlever">${esc(OPT_LABEL[o.value])} (${o.count})</span>`
      : chip(`${OPT_LABEL[o.value]} (${o.count})`, toggleOpt(o.value), o.active)).join("")}</div>` : ""}
    ${(facets.academie || []).length > 1 || P.academie || (facets.selectivite || []).length > 1 || P.selective ? `<div class="toolbar">
      ${(facets.academie || []).length > 1 || P.academie ? `<label class="small">Académie <select id="facad"><option value="">Toutes</option>${(facets.academie || []).slice().sort((a, b) => a.value.localeCompare(b.value, "fr")).map((a) => `<option value="${esc(a.value)}" ${P.academie === a.value ? "selected" : ""}>${esc(a.value)} (${a.count})</option>`).join("")}</select></label>` : ""}
      ${(facets.selectivite || []).length > 1 || P.selective ? `<label class="small">Sélectivité <select id="fsel"><option value="">Toutes</option>${(facets.selectivite || []).map((f) => { const v = f.value === "formation sélective" ? "true" : "false"; return `<option value="${v}" ${P.selective === v ? "selected" : ""}>${f.value === "formation sélective" ? "Sélectives" : "Non sélectives"} (${f.count})</option>`; }).join("")}</select></label>` : ""}
    </div>` : ""}
    `)}
    ${d.results.map(resultCard).join("")}
    ${d.total > off + d.results.length ? `<p><a class="badge exact" href="${esc(go({ offset: off + PAGE }))}">Résultats suivants (${fmt(off + d.results.length + 1)}–${fmt(Math.min(d.total, off + d.results.length + PAGE))}) →</a></p>` : ""}
    ${off ? `<p><a href="${esc(go({ offset: Math.max(0, off - PAGE) }))}">← Résultats précédents</a></p>` : ""}
    ${near ? `<p class="muted small">À pertinence égale, les formations de l'académie de ${esc(near)} (votre profil) passent en premier.</p>` : ""}
  </div>${feedbackBox("search")}`;
  $view.dataset.rendered = `s:${q}:${rawParams || ""}`;   // render marker (UI tests wait on it)
  suggestLycee(q, $view.dataset.rendered);
  const fa = document.getElementById("facad"); if (fa) fa.onchange = () => { location.hash = go({ academie: fa.value }); };
  const fs = document.getElementById("fsel"); if (fs) fs.onchange = () => { location.hash = go({ selective: fs.value }); };
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
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Doublette</th><th class="num">Taux d'accès</th><th class="num">Candidats</th><th class="num">Rapports</th></tr>
    ${rows.map((x) => `<tr${x === mine ? ' class="dbl-mine"' : ""}><td>${x === mine ? "Votre doublette : " : ""}${esc(x.label)}</td>
      <td class="num" data-label="Taux d'accès">${pct1(x.taux)}${rateBar(x.taux, "var(--voie-bg)")}</td>
      <td class="num" data-label="Candidats">${fmt(x.en_position)} sur ${fmt(x.confirmes)}</td>
      <td class="num" data-label="Rapports">${fmt(x.n_rapports)}</td></tr>`).join("")}</table></div>
    <p class="muted small">Pour chaque doublette, les rapports des formations semblables qui la détaillent (au moins ${fmt(sem.min_rapports)} rapports et ${fmt(sem.min_candidats)} candidats), additionnés : candidats en position de recevoir une proposition en phase principale sur candidats ayant confirmé le vœu. Ce ne sont pas les chiffres de cette formation, et ce ne sont pas des chances d'admission.${dkey && !mine && est === null ? " Votre doublette n'est détaillée dans aucun ou dans trop peu de ces rapports." : ""}</p>`;
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
function doubletteCard(d, rp, sem) {
  if (!d) return "";
  const prof = bacProfile() || {};
  const own = rapportDoublettes(rp, prof);      // sprint "Rapports publics": this formation's OWN published figures
  const myVoie = ["bg", "bt", "bp"].includes(prof.serie) ? prof.serie : (prof.spe1 ? "bg" : null);
  const last = Object.values(d.series)[0].trend.slice(-1)[0];
  const voies = ["bg", "bt", "bp"].map((s) => { const v = d.series[s];
    return `<tr${s === myVoie ? ' class="dbl-mine"' : ""}><td>${voiePill(s)}${s === myVoie ? ' <span class="estim">votre bac</span>' : ""}</td>
      <td class="num" data-label="Taux de proposition">${pct1(v.taux)}${v.taux !== null && v.taux !== undefined ? rateBar(v.taux, VOIES[s].color) : ""}</td>
      <td class="num" data-label="Candidats">${fmt(v.candidats)}${v.fragile && v.candidats ? ' <span class="badge warnb">peu de candidats</span>' : ""}</td></tr>`; }).join("");
  const dkey0 = profileDkey(prof);
  // where this formation's own report has no bac général table: the similar formations' reports, then the national group
  const semEst = own.hasBg ? null : estimateSemblable(d.series, sem, dkey0);
  const semBlock = own.hasBg ? "" : `${semEst ? `<div class="dbl-est"><p class="small"><strong>Votre doublette dans cette formation : ${pct1(semEst.taux)}</strong> <span class="estim">estimation à partir de ${fmt(semEst.n_rapports)} rapports de formations semblables</span>${rateBar(semEst.taux, "var(--voie-bg)")}</p>
      <p class="muted small">Calcul : taux de proposition des bacheliers généraux de cette formation (${pct1(semEst.base)}${semEst.fragile ? ", peu de candidats" : ""}) × écart de votre doublette dans ${fmt(semEst.n_rapports)} rapports publics ${esc(sem.session)} de formations semblables (${semName(sem)}) : ${pct1(semEst.mine)} contre ${pct1(semEst.tous)} pour tous les bacheliers généraux de ces mêmes rapports. ${rp ? "Le rapport de cette formation ne détaille pas les doublettes" : "Cette formation n'a pas de rapport public vérifié pour cette session"} : ce chiffre suppose que l'écart mesuré dans les formations semblables vaut aussi ici.</p></div>` : ""}${semblablesDoublettes(sem, dkey0, semEst)}`;
  let dbl;
  if (d.status !== "ok") dbl = `<p class="muted small">Pas de donnée par doublette pour ce type de formation : le ministère ne la publie que pour les groupes de formations qu'il suit.</p>`;
  else {
    const g = d.groupe, dkey = profileDkey(prof), mine = pickDoublette(g, dkey);
    const row = (lab, x, color, extra = "", cls = "") => `<tr${cls}><td>${lab}${extra}</td><td class="num" data-label="Taux de proposition">${pct1(x.taux)}${rateBar(x.taux, color)}</td><td class="num" data-label="Candidats">${fmt(x.candidats)}</td></tr>`;
    const top = g.doublettes.filter((x) => !x.rare && x.key !== (mine && mine.source === "doublette" ? dkey : "")).slice(0, 5);
    // the estimate is only shown when this formation's report gives no bac général figure
    const est = own.hasBg || semEst ? null : estimateDoublette(d.series, g, dkey);
    const estBlock = est ? `<div class="dbl-est"><p class="small"><strong>Votre doublette dans cette formation : ${pct1(est.taux)}</strong> <span class="estim">estimation</span>${rateBar(est.taux, "var(--voie-bg)")}</p>
      <p class="muted small">Calcul : taux de proposition des bacheliers généraux de cette formation (${pct1(est.base)}${est.fragile ? ", peu de candidats" : ""}) × écart de ${est.source === "autres" ? "vos « Autres doublettes »" : "votre doublette"} dans le groupe au niveau national (${pct1(est.mine)} contre ${pct1(est.tous)} pour tous les bacheliers généraux). Aucune donnée publique ne donne les doublettes établissement par établissement : ce chiffre suppose que l'écart national vaut aussi ici.</p></div>` : "";
    dbl = `${estBlock}<h4>Détail national du groupe</h4><p class="small">Groupe : <strong>${esc(g.label)}</strong> · ${dblCampagnes(g)}</p>
      <div class="scroll"><table class="stack"><tr class="stack-head"><th>Doublette</th><th class="num">Taux de proposition</th><th class="num">Candidats</th></tr>
      ${mine ? row(`Votre doublette : ${esc(mine.label)}`, mine, "var(--voie-bg)", mine.source === "autres" ? `<div class="estim">peu de candidats avec cette doublette : chiffre des « Autres doublettes » (${fmt(mine.n_doublettes)} doublettes de moins de ${DBL_SEUIL} candidats regroupées), estimation</div>` : "", ' class="dbl-mine"') : ""}
      ${row("Tous les bacheliers généraux du groupe", g.tous, "var(--muted)")}
      ${top.map((x) => row(esc(x.label), x, "var(--voie-bg)")).join("")}
      ${g.autres.candidats ? row(`Autres doublettes <span class="estim">(${fmt(g.autres.n_doublettes)} doublettes de moins de ${DBL_SEUIL} candidats)</span>`, g.autres, "var(--voie-bg)") : ""}
      </table></div>
      ${!dkey ? `<p class="small"><a href="#/profil">Indiquez vos spécialités dans « Mon profil »</a> pour voir votre doublette en premier.</p>` : ""}
      <p class="muted small">${DBL_CAVEAT}</p>`;
  }
  return `<div class="card"><h2>Selon votre bac</h2>
    <h3>Par voie de bac, pour cette formation${last ? ` (campagne ${esc(last.session)})` : ""}</h3>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Voie</th><th class="num">Taux de proposition</th><th class="num">Candidats</th></tr>${voies}</table></div>
    <p class="muted small">Part des candidats de chaque voie ayant reçu une proposition de cette formation (toutes phases). Moins de ${DBL_SEUIL} candidats : chiffre fragile.</p>
    ${own.html}
    <h3>Par doublette de spécialités (bac général)${own.hasBg ? " : le groupe de formations, toute la France" : ""}</h3>${semBlock}${dbl}</div>`;
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
const RP_CAVEAT = "Part des candidats ayant confirmé ce vœu qui ont été en position de recevoir une proposition en phase principale : le taux d'accès de la formation, détaillé par doublette, calculé à partir des effectifs publiés dans son rapport. Seuls y figurent les candidats scolarisés en terminale en France depuis 2020-2021. Ce sont des résultats passés, pas des chances d'admission.";
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
    return `<div class="scroll"><table class="stack"><tr class="stack-head"><th>${voiePill(v)} ${v === "bp" ? "Spécialité" : "Doublette"}</th><th class="num">Taux d'accès</th><th class="num">Candidats</th></tr>
      ${rows.map((x) => { const me = v === "bg" && mine && (mine.source === "doublette" ? x.key === dkey : x.autres) && myVoie === "bg";
        const meV = v === myVoie && mineV && (mineV.source === "voie" ? x.voie === vkey : x.autres);
        const tag = me ? (mine.source === "autres" ? "votre doublette en fait partie" : "votre doublette")
          : meV ? (mineV.source === "autres" ? `votre ${VOIE_WORD[v]} en fait partie` : "votre ligne") : "";
        return `<tr${me || meV ? ' class="dbl-mine"' : ""}><td>${esc(x.libelle)}${tag ? ` <span class="estim">${tag}</span>` : ""}</td>
        <td class="num" data-label="Taux d'accès">${pct1(x.taux)}${x.taux !== null && x.taux !== undefined ? rateBar(x.taux, VOIES[v].color) : ""}</td>
        <td class="num" data-label="Candidats">${fmt(x.en_position)} sur ${fmt(x.confirmes)}</td></tr>`; }).join("")}</table></div>`;
  }).join("");
  if (!blocks) return { html: "", hasBg: false };
  const head = mine && myVoie === "bg" ? `<div class="dbl-est"><p class="small"><strong>Votre doublette dans cette formation : ${pct1(mine.taux)}</strong> <span class="estim">rapport public ${esc(rp.session)}${mine.source === "autres" ? ", ligne « Autres doublettes » de la formation" : ""}</span>${rateBar(mine.taux, "var(--voie-bg)")}</p>
    <p class="muted small">${fmt(mine.en_position)} candidats sur ${fmt(mine.confirmes)} ayant ${mine.source === "autres" ? "une doublette autre que celles détaillées" : "cette doublette"} ont été en position de recevoir une proposition.${mine.source === "autres" ? " La formation ne détaille que ses doublettes les plus fréquentes : la vôtre est comptée avec les autres." : ""}</p></div>` : "";
  const voieRows = vkey !== null || myVoie === "bt" || myVoie === "bp" ? (rp.doublettes[myVoie] || []) : [];
  const headV = !(myVoie === "bt" || myVoie === "bp") ? ""
    : mineV ? `<div class="dbl-est"><p class="small"><strong>Votre ligne dans cette formation : ${pct1(mineV.taux)}</strong> <span class="estim">rapport public ${esc(rp.session)}, ligne « ${esc(mineV.libelle)} »${mineV.source === "autres" ? " de la formation" : ""}</span>${rateBar(mineV.taux, VOIES[myVoie].color)}</p>
    <p class="muted small">${fmt(mineV.en_position)} candidats sur ${fmt(mineV.confirmes)} ${mineV.source === "autres" ? `dont la ${VOIE_WORD[myVoie]} n'est pas détaillée` : `de votre ${VOIE_WORD[myVoie]}`} ont été en position de recevoir une proposition.${mineV.source === "autres" ? ` La formation ne détaille que ses ${VOIE_WORD[myVoie]}s les plus fréquentes : la vôtre est comptée avec les autres.` : ""}</p></div>`
    : (rp.masques || []).includes(myVoie) ? `<p class="small">Pour le ${myVoie === "bt" ? "bac technologique" : "bac professionnel"}, la formation n'a pas publié son tableau (effectifs trop faibles) : pas de ligne pour vous dans ce rapport.</p>`
    : voieRows.length && !vkey ? `<p class="small"><a href="#/profil">Indiquez votre ${myVoie === "bt" ? "série et vos spécialités" : "spécialité de bac pro"}</a> pour voir votre ligne.</p>`
    : voieRows.length ? `<p class="small">Votre ${VOIE_WORD[myVoie]} n'apparaît pas dans les rapports de la session ${esc(rp.session)} : pas de ligne comparable dans ce rapport.</p>` : "";
  const { bg: bgRows = [] } = rp.doublettes;
  return { hasBg: !!bgRows.length, html: `<h3>Dans cette formation, par doublette, série ou spécialité (rapport public ${esc(rp.session)})${rpPending(rp)}</h3>${head}${headV}${blocks}
    <p class="muted small">${RP_CAVEAT}</p><p class="muted small">${rapportSource(rp)}</p>` };
}
// what the jury looks at: its criteria with the published importance, the specialties it takes into account, the options it
// names (quoted, never interpreted), eliminating criteria, method and advice; every text is the jury's own, escaped
// journey.SPECIALTIES, the labels the reports print in their list of specialties taken into account (red team checks equality)
const RP_SPE = {"MATHS": "Mathématiques Spécialité", "PC": "Physique-Chimie Spécialité", "SVT": "Sciences de la vie et de la Terre Spécialité", "SES": "Sciences Economiques et Sociales Spécialité", "HGGSP": "Histoire-Géographie, Géopolitique et Sciences politiques", "LLCER": "Langues, littératures et cultures étrangères et régionales", "HLP": "Humanités, Littérature et Philosophie", "NSI": "Numérique et Sciences Informatiques", "SI": "Sciences de l'ingénieur et sciences physiques", "LLCA": "Littérature et langues et cultures de l'Antiquité", "EPPCS": "Éducation physique, pratiques et culture sportives", "ART": "Art", "BIOECO": "Biologie/Ecologie"};
const RP_IMP = ["Essentiel", "Très important", "Important", "Complémentaire"];
const RP_OPTIONS = { maths_expertes: "Mathématiques expertes", maths_complementaires: "Mathématiques complémentaires", dgemc: "Droit et grands enjeux du monde contemporain",
  langues_anciennes: "Langues anciennes (latin, grec)", lv3: "Troisième langue vivante", option_arts: "Option arts", option_eps: "Option EPS",
  section_euro: "Section européenne ou internationale", certifications: "Certifications" };
const rpText = (t) => esc(t || "").replace(/\n/g, "<br>");
function juryCard(rp) {
  if (!rp || !rp.textes) return "";
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
    return mySpe.includes(String(x).toLowerCase()) ? `<mark>${esc(x)}</mark>` : esc(x); }).join(" · ")}</p>`).join("");
  const edsHtml = eds.pris_en_compte ? `<h3>Les spécialités de terminale</h3>
    <p class="small">La commission dit ${/^oui/i.test(eds.pris_en_compte) ? "<strong>prendre en compte</strong>" : "<strong>ne pas prendre en compte</strong>"} les enseignements de spécialité.${eds.poids ? ` Le poids des résultats dans certaines spécialités, d'après la commission : « ${esc(eds.poids.replace(/\.$/, ""))} ».` : ""}</p>${edsList}` : "";
  const opts = t.options_citees || {};
  const me = prof.maths_expertes && (prof.spe1 === "MATHS" || prof.spe2 === "MATHS");
  const optHtml = Object.keys(opts).length || me ? `<h3>Options et parcours cités par le jury</h3>
    ${me ? `<p class="small">Vous suivez <strong>Mathématiques expertes</strong> : ${opts.maths_expertes ? "le rapport de cette formation la cite (voir ci-dessous)." : "le rapport de cette formation ne la cite pas. Cela ne veut pas dire qu'elle ne compte pas : regardez les attendus de la fiche Parcoursup."}</p>` : ""}
    ${Object.entries(opts).map(([k, quotes]) => `<p class="small"><strong>${esc(RP_OPTIONS[k] || k)}</strong></p>${quotes.map((q) => `<blockquote class="rp-quote">« ${esc(q)} »</blockquote>`).join("")}`).join("")}` : "";
  const fold = (title, txt) => (txt ? `<details class="dip"><summary>${title}</summary><p class="small">${rpText(txt)}</p></details>` : "");
  return `<div class="card"><h2>Ce que regarde le jury · rapport public ${esc(rp.session)}${rpPending(rp)}</h2>
    <p class="small">Ce que la commission d'examen des vœux de cette formation a écrit elle-même dans son rapport public, repris tel quel.${rp.concours ? " Ce rapport est commun à plusieurs formations d'un même concours." : ""}</p>
    ${critHtml}${edsHtml}${optHtml}
    ${fold("Critères éliminatoires", t.eliminatoires)}${fold("Comment les dossiers ont été examinés", t.modalites)}${fold("Traitement algorithmique", t.algorithme)}${fold("Les conseils du jury pour la prochaine session", t.conseils)}
    <p class="muted small">Les critères et leur importance sont ceux que la formation a publiés ; ils peuvent changer d'une session à l'autre. Ils décrivent l'examen des dossiers, pas des chances d'admission.</p>
    <p class="muted small">${rapportSource(rp)}</p></div>`;
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
    ${others.length ? `<details class="dip"><summary>Séries technologiques</summary>${others.map(([serie, items]) => `<p class="small"><strong>${esc(serie)}</strong> : ${Object.entries(items).sort((a, b) => b[1] - a[1]).map(([lab, c]) => `${esc(lab)} (${fmt(c)})`).join(" · ")}</p>`).join("")}</details>` : ""}`;
  const opts = Object.entries(J.options || {}).sort((a, b) => b[1] - a[1]);
  const optHtml = opts.length ? `<h3>Options et parcours cités</h3><ul class="small sem-list">${opts.map(([k, c]) => `<li>${esc(RP_OPTIONS[k] || k)} : citée dans ${fmt(c)} rapport${c > 1 ? "s" : ""} sur ${fmt(n)}</li>`).join("")}</ul>
    <p class="muted small">Une option qu'un rapport ne cite pas peut compter quand même : regardez les attendus de la fiche Parcoursup.</p>` : "";
  const list = sem.formations || [];
  const links = list.length ? `<details class="dip"><summary>Lire les rapports de ces formations (${fmt(list.length)})</summary><ul class="small sem-list">${list.map((f) => `<li><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a> · ${esc(f.ville)}${f.academie ? ` (${esc(f.academie)})` : ""}</li>`).join("")}</ul></details>` : "";
  return `<div class="card"><h2>Ce que regardent les jurys de formations semblables <span class="estim">pas le rapport de cette formation</span></h2>
    <p class="small">${rp ? `Le rapport public ${esc(rp.session)} de cette formation ne donne pas de critères lisibles.` : `Cette formation n'a pas de rapport public vérifié pour la session ${esc(sem.session)}.`} Voici ce que disent ${fmt(n)} rapports publics ${esc(sem.session)} de formations du même diplôme et de la même mention (${semName(sem)}), vérifiés avec les chiffres du ministère. Le jury de cette formation peut avoir d'autres attentes : sa fiche Parcoursup fait foi.</p>
    ${critHtml}${edsHtml}${optHtml}${links}
    <p class="muted small">Des comptes de rapports, jamais une moyenne ni une note : ils décrivent l'examen des dossiers dans des formations semblables, pas des chances d'admission.</p></div>`;
}
// the 4-year curves of the evolution page: each route for this formation, the student's doublette in the group
function doubletteCharts(d, years, sem, rp) {
  if (!d) return "";
  const at = (trend, k) => years.map((y) => { const r = trend.find((x) => x.session === y); return r ? r[k] : null; });
  const series = ["bg", "bt", "bp"].map((s) => ({ name: VOIES[s].label, color: VOIES[s].color, values: at(d.series[s].trend, "taux"),
    hollow: at(d.series[s].trend, "candidats").map((c) => (c || 0) < DBL_SEUIL) }));
  let second = "";
  if (d.status === "ok") {
    const g = d.groupe, mine = pickDoublette(g, profileDkey(bacProfile()));
    const lines = [{ name: "Tous les bacheliers généraux du groupe", color: "var(--c4)", dash: "2 3", values: at(g.tous.trend, "taux") }];
    const dk = profileDkey(bacProfile());
    // the formation page's estimate: none beside a published figure, the similar formations first, then the national group
    const sEst = ownHasBg(rp) ? null : estimateSemblable(d.series, sem, dk);
    const est = ownHasBg(rp) ? null : sEst || estimateDoublette(d.series, g, dk);
    if (mine) lines.unshift({ name: mine.source === "autres" ? "Autres doublettes, groupe national (estimation)" : `Votre doublette : ${mine.label}, groupe national`, color: "var(--c2)", dash: "6 4", values: at(mine.trend, "taux") });
    if (est) lines.unshift({ name: sEst ? `Votre doublette dans cette formation (estimation, ${fmt(sEst.n_rapports)} rapports de formations semblables)` : "Votre doublette dans cette formation (estimation)", color: "var(--c1)", dash: "", values: at(est.trend, "taux") });
    second = `<div class="card"><h3>Votre doublette : cette formation (estimation) et le groupe « ${esc(g.label)} » (national)</h3>${lineLegend(lines)}${lineChart(years, lines)}
      <p class="muted small">${DBL_CAVEAT}</p></div>`;
  }
  return `<div class="card"><h3>Taux de proposition par voie de bac (cette formation)</h3>${lineLegend(series)}${lineChart(years, series)}
    <p class="muted small">Points creux : moins de ${DBL_SEUIL} candidats de la voie cette année-là.</p></div>${second}`;
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
function carteMerge(neutral, stage2, ok) {
  const zones = new Map(((stage2 && stage2.formations) || []).map((f) => [f.cod_aff_form, f.zone]));
  return neutral.map((f) => ({ ...f, zone: ok ? (zones.get(f.cod_aff_form) || null) : null }));
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
  ["select", "Autres", [["oui", "Formations sélectives"], ["non", "Formations non sélectives"]]],
];
const CARTE_DEFAULT = { statut: ["public", "contrat", "prive_app"] };
// R3 (owner, 2026-11-12): the search's capacity, complementary phase and official-rate bands, the same limits (META.filtres)
const CARTE_R3 = ["capacite", "complementaire", "taux"];
const carteGroups = () => [...CARTE_GROUPS, ...CARTE_R3.map((g) => [g, FI_TITLE[g], fiOptions(g).map((o) => [o.key, o.label])])];
// does a formation carry an option of a group (one pure function, re-derived by red team C3)
function carteHas(f, g, o) {
  if (g === "statut") return f.statut === o;
  if (g === "app") return o === "oui" ? !!f.apprentissage : !!f.initiale;   // a formation offering both has both labels
  if (g === "internat") return f.internat === o;
  if (g === "amenag") return o === "presentiel" ? (!f.distance || f.distance === "aucune") : o === "sport" ? !!f.amenag_sport : o === "art" ? !!f.amenag_art : f.distance === o;
  if (g === "select") return f.select_form === (o === "oui" ? "formation sélective" : "formation non sélective");   // unknown: neither
  if (g === "zones") return carteZone(f) === o;
  if (g === "capacite") return filtreBand(f.capa_fin, fiOptions("capacite")) === o;
  if (g === "taux") return filtreBand(f.taux_acces_ens, fiOptions("taux")) === o;
  if (g === "complementaire") return f.acc_pc !== null && f.acc_pc !== undefined && (o === "oui" ? f.acc_pc > 0 : f.acc_pc === 0);   // unknown: neither
  return false;
}
// every filter in one pure function; `skip` leaves one group out (the counts shown next to its options)
function carteFilter(rows, F, skip) {
  const q = (F.q || "").trim().toLowerCase();
  const groups = ["statut", "app", "internat", "amenag", "select", "zones", ...CARTE_R3].filter((g) => g !== skip);
  return rows.filter((f) => groups.every((g) => !(F[g] || []).length || F[g].some((o) => carteHas(f, g, o)))
    && (!F.academie || f.academie === F.academie)
    && (!q || `${f.etablissement} ${f.formation} ${f.ville}`.toLowerCase().includes(q))
    && (!F.autour || (f.lat != null && haversineKm(F.autour.lat, F.autour.lon, f.lat, f.lon) <= F.autour.km)));
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
function carteAppDetail(f) {
  const url = carteFiche(f);
  return `<div class="card carte-sel"><h3>${esc(f.etablissement)}</h3>
    <p class="small">${esc(f.formation)}${carteMentionTail(f)} <span class="badge">en apprentissage</span><br><span class="muted">${esc(f.ville)}${f.academie ? ` · académie de ${esc(f.academie)}` : ""} · ${esc(f.contrat_etab || "")}</span></p>
    <p class="small muted">${CARTE_APP_NOTE}</p>
    <div class="toolbar">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Voir la fiche Parcoursup ↗</a>` : ""}</div></div>`;
}
// the apprenticeship offers attached to an initial formation (same establishment, same diploma): the CFA and its page
function appOffers(list) {
  if (!list || !list.length) return "";
  return `<div class="small"><strong>Aussi en apprentissage</strong> <span class="muted">(pas de statistiques d'admission publiées pour cette voie)</span><ul class="offer-list">${list.map((o) => { const url = carteFiche(o);
    return `<li>${esc(o.etablissement)}${o.ville ? ` · ${esc(o.ville)}` : ""}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">fiche Parcoursup ↗</a>` : ""}</li>`; }).join("")}</ul></div>`;
}
function carteDetail(f, hasProfile) {
  if (!f) return "";
  if (f.stats === false) return carteAppDetail(f);
  const z = carteZone(f);
  return `<div class="card carte-sel"><h3><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a></h3>
    <p class="small">${esc(f.formation)}${carteMentionTail(f)} ${voieBadges(f)}${autresBadge(f)}<br><span class="muted">${esc(f.ville)}${f.academie ? ` · académie de ${esc(f.academie)}` : ""} · ${esc(f.contrat_etab || "")}${f.payant ? " (payant)" : ""}</span></p>
    <p class="small">${hasProfile ? (z === "autre" ? carteZoneBadge(f.zone, "Non situé pour votre profil") : `${zoneBadge(z)} <span class="muted">d'après les admis des campagnes passées</span>`) : `<a href="#/profil">Indiquez votre profil</a> pour voir votre zone.`}
    · taux d'accès ${pct(f.taux_acces_ens)} <span class="muted">(officiel)</span></p>
    ${appOffers(f.offres_app)}
    <div class="toolbar">${voeuButton(f.cod_aff_form)}<a href="#/f/${esc(f.cod_aff_form)}">Voir la fiche →</a></div></div>`;
}
function carteList(rows, hasProfile) {
  const PAGE = searchPage(), start = carteUI.page * PAGE, part = rows.slice(start, start + PAGE);
  return `<div class="carte-list">${part.map((f) => { const z = carteZone(f);
    if (f.stats === false) { const url = carteFiche(f);
      return `<div class="result" data-pick="${esc(f.cod_aff_form)}"><div>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer"><strong>${esc(f.etablissement)}</strong> ↗</a>` : `<strong>${esc(f.etablissement)}</strong>`} <span class="muted">· ${esc(f.ville)}</span>${f.dist != null ? ` <span class="muted small">${fmt(f.dist)} km</span>` : ""}<br>
      <span class="small">${esc(f.formation)}${carteMentionTail(f)}</span><br><span class="badge">en apprentissage</span>${f.lat == null ? ' <span class="badge">non localisée</span>' : ""}</div>
      <div class="num"><div class="big">—</div><div class="muted small">pas de statistiques</div></div></div>`; }
    return `<div class="result" data-pick="${esc(f.cod_aff_form)}"><div><a href="#/f/${esc(f.cod_aff_form)}"><strong>${esc(f.etablissement)}</strong></a> <span class="muted">· ${esc(f.ville)}</span>${f.dist != null ? ` <span class="muted small">${fmt(f.dist)} km</span>` : ""}<br>
      <span class="small">${esc(f.formation)}${carteMentionTail(f)}</span><br>${hasProfile ? `${z === "autre" ? carteZoneBadge(null, CARTE_OTHER.label) : zoneBadge(z)} ` : ""}${voieBadges(f)}${autresBadge(f)}${f.payant ? ' <span class="badge warnb">établissement privé payant</span>' : ""}${f.lat == null ? ' <span class="badge">non localisée</span>' : ""}</div>
      <div class="num"><div class="big">${pct(f.taux_acces_ens)}</div><div class="muted small">taux d'accès</div></div></div>`; }).join("") || `<p class="muted small">Aucune formation ne correspond à ces filtres dans cette partie de la carte.</p>`}</div>
    <div class="toolbar">${carteUI.page ? `<button type="button" data-cpage="-1">← Précédentes</button>` : ""}${rows.length > start + PAGE ? `<button type="button" data-cpage="1">Suivantes (${fmt(start + PAGE + 1)}–${fmt(Math.min(rows.length, start + 2 * PAGE))}) →</button>` : ""}</div>`;
}
// Leaflet (static/vendor/leaflet, BSD-2) is loaded by this page only, never by the page shell
function carteLeaflet() {
  if (window.L) return Promise.resolve();
  const load = (tag, attrs) => new Promise((ok, ko) => { const el = document.createElement(tag); Object.assign(el, attrs); el.onload = ok; el.onerror = ko; document.head.appendChild(el); });
  return Promise.all([load("link", { rel: "stylesheet", href: "/static/vendor/leaflet/leaflet.css" }), load("script", { src: "/static/vendor/leaflet/leaflet.js" })]);
}
async function viewCarte(dArg, mArg) {
  const FAC = await api("/api/carte");
  // "#/carte/t/<type_key>" comes from Mon parcours: its most frequent type of diploma
  if (dArg === "t") { const d = FAC.types[mArg]; location.replace(`#/carte/${encodeURIComponent(d || "")}`); return; }
  const known = (d) => FAC.diplomes.find((x) => x.label === d);
  const D = known(dArg) || known(store.get("carteDiplome", null)) || known("BUT") || FAC.diplomes[0];   // stored value never trusted
  const mention = D.mentions.some((m) => m.label === mArg) ? mArg : "";
  store.set("carteDiplome", D.label);
  const P = bacProfile();                                                // sprint 21: no zone outside terminale
  const serie = P && ["bg", "bt", "bp"].includes(P.serie) ? P.serie : "bg";
  const ok = P && (serie !== "bg" || (P.spe1 && P.spe2 && P.spe1 !== P.spe2)) && ["sm", "ab", "b", "tb"].includes(P.mention);
  const sq = !ok ? "" : serie === "bg" ? `spe1=${encodeURIComponent(P.spe1)}&spe2=${encodeURIComponent(P.spe2)}` : `serie=${encodeURIComponent(serie)}`;
  const dq = `diplome=${encodeURIComponent(D.label)}${mention ? `&mention=${encodeURIComponent(mention)}` : ""}`;
  const [L0, Z] = await Promise.all([api(`/api/carte/formations?${dq}`),
    ok ? api(`/api/carte/zones?${dq}&${sq}&mention_bac=${P.mention}`).catch(() => null) : null, carteLeaflet().catch(() => null)]);
  if (!/^#\/carte(\/|$)/.test(location.hash)) return;        // the visitor left while the map loaded (navigation race)
  if (Z) track("journey", { stage: "stage2" });
  const rows = carteMerge(L0.formations, Z && { formations: Object.entries(Z.zones).map(([cod_aff_form, zone]) => ({ cod_aff_form, zone })) }, ok);
  const F = { ...CARTE_DEFAULT, ...(store.get("carteFiltres2", {}) || {}) };
  for (const [g, , opts] of carteGroups()) F[g] = Array.isArray(F[g]) ? F[g].filter((o) => opts.some(([k]) => k === o)) : [];
  F.zones = ok && Array.isArray(F.zones) ? F.zones.filter((z) => [...CARTE_ZONES, "autre"].includes(z)) : [];
  const towns = [...new Set(rows.filter((f) => f.lat != null).map((f) => f.ville))].sort((a, b) => a.localeCompare(b, "fr"));
  const acads = [...new Set(rows.map((f) => f.academie).filter(Boolean))].sort((a, b) => a.localeCompare(b, "fr"));
  const town = (name) => { const xs = rows.filter((f) => f.ville === name && f.lat != null); return xs.length ? { lat: xs[0].lat, lon: xs[0].lon } : null; };
  const goTo = (d, m) => { carteUI.sel = null; carteUI.bounds = null; location.hash = `#/carte/${encodeURIComponent(d)}${m ? `/${encodeURIComponent(m)}` : ""}`; };
  $view.innerHTML = `${explorerViews("carte")}<div class="card"><h1>Carte des formations</h1>
    <p class="small">${!ok && isReo(store.get("profile", null)) ? `Les formations sont placées sans zone. ${REO_NO_ZONE} <a href="#/reorientation">Voir l'accès estimé hors terminale</a>.` : ok ? "Chaque formation est placée et colorée selon votre zone, calculée comme dans « Où je me situe » à partir des admis des campagnes passées : ce ne sont pas des chances d'admission." : `Les formations sont placées sans zone. <a href="#/profil">Indiquez votre bac, vos spécialités et votre mention</a> pour les colorer selon votre zone.`}</p>
    <div class="carte-pick"><label class="small">Type de diplôme <select id="cdip">${FAC.diplomes.map((d) => `<option value="${esc(d.label)}" ${d.label === D.label ? "selected" : ""}>${esc(d.label)} (${fmt(d.n)})</option>`).join("")}</select></label>
    <label class="small">Mention <select id="cmen"><option value="">Toutes les mentions (${fmt(D.n)})</option>${D.mentions.map((m) => `<option value="${esc(m.label)}" ${m.label === mention ? "selected" : ""}>${esc(m.label)} (${fmt(m.n)})</option>`).join("")}</select></label></div></div>
  <div class="carte-layout">
    <details class="filters carte-filters"${narrow() ? "" : " open"}><summary>${ICONS.filter}Filtrer</summary><div class="filter-grid" id="cfilters"></div></details>
    <div class="carte-main">
      <div class="legend" id="carte-legend"></div>
      <div class="carte-box"><div id="carte-osm" class="carte-osm"></div></div>
      <p class="muted small">Fond de carte OpenStreetMap : votre navigateur demande les images de la carte aux serveurs d'OpenStreetMap, qui voient votre adresse IP. Votre profil et vos filtres ne leur sont pas envoyés.</p>
      <p class="muted small" id="carte-count"></p>
      <div id="carte-sel"></div>
      <div class="card"><h2>Formations de la carte</h2><div id="carte-items"></div>
      <p class="muted small">Liste triée par nom${F.autour ? ", puis par distance" : ""}, jamais par chances. Carte : ${CARTE_ATTRIB}. Données : SIES / MESR, session ${esc(L0.session)}${L0.offre_apprentissage ? ` ; apprentissage : cartographie Parcoursup ${esc(L0.offre_apprentissage)}` : ""}.</p></div>
    </div></div>`;
  $view.dataset.rendered = "carte";
  const box = document.getElementById("carte-osm");
  if (!window.L) { box.innerHTML = `<div class="warn">La carte n'a pas pu être chargée ; la liste reste disponible.</div>`; }
  else {
    if (carteUI.map) { carteUI.map.remove(); carteUI.map = null; }
    carteUI.map = L.map(box, { zoomControl: true }).fitBounds([[41.3, -5.2], [51.1, 9.6]]);   // metropolitan France on any screen
    L.tileLayer(CARTE_TILES, { maxZoom: 18, attribution: CARTE_ATTRIB }).addTo(carteUI.map);
    carteUI.layer = L.layerGroup().addTo(carteUI.map);
    if (carteUI.type === D.label + mention && carteUI.bounds) carteUI.map.fitBounds(carteUI.bounds);
    carteUI.map.on("moveend", () => { carteUI.bounds = carteUI.map.getBounds(); carteUI.page = 0; draw(); });
  }
  carteUI.type = D.label + mention;
  const inView = (f) => !carteUI.map || (f.lat != null && carteUI.map.getBounds().contains([f.lat, f.lon]));
  // the filter panel: Parcoursup's groups, each option with its count among the formations the OTHER filters keep
  function panel() {
    const box2 = (g, o, label) => { const n = carteFilter(rows, F, g).filter((f) => carteHas(f, g, o)).length;
      return `<label class="small"><input type="checkbox" data-g="${g}" data-o="${o}" ${(F[g] || []).includes(o) ? "checked" : ""}> ${label} <span class="muted">${fmt(n)}</span></label>`; };
    const zoneLabel = (z) => `<i class="lg-${z}" style="background:${carteColor(z)}"></i>${esc(carteLabel(z))}`;
    document.getElementById("cfilters").innerHTML = `
      <label class="small">Nom, ville <input id="cq" type="search" value="${esc(F.q || "")}" placeholder="ex. Lyon, IUT"></label>
      <label class="small">Académie <select id="cacad"><option value="">Toutes</option>${acads.map((a) => `<option ${F.academie === a ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label>
      <label class="small">Autour de <input id="ctown" list="ctowns" value="${esc((F.autour && F.autour.ville) || "")}" placeholder="une ville"></label><datalist id="ctowns">${towns.map((v) => `<option value="${esc(v)}">`).join("")}</datalist>
      <label class="small">Rayon <select id="ckm">${[10, 25, 50, 100, 200].map((k) => `<option value="${k}" ${(F.autour && F.autour.km) === k ? "selected" : ""}>${k} km</option>`).join("")}</select></label>
      ${ok ? `<fieldset class="small"><legend>Votre zone</legend>${[...CARTE_ZONES, "autre"].map((z) => box2("zones", z, zoneLabel(z))).join("")}</fieldset>` : ""}
      ${carteGroups().map(([g, title, opts]) => `<fieldset class="small"><legend>${esc(title)}</legend>${opts.map(([o, label]) => box2(g, o, esc(label))).join("")}
        ${g === "statut" ? `<p class="muted small">Les établissements privés payants ne sont montrés que si vous cochez leur case.</p>` : ""}</fieldset>`).join("")}
      <p class="muted small">Formations en apprentissage : offre ${esc(L0.offre_apprentissage || "")} de la cartographie Parcoursup. Les statistiques officielles ne les couvrent plus depuis 2022 : elles n'ont ni zone, ni taux d'accès. Votre ville n'est jamais envoyée au site : le rayon est calculé dans votre navigateur.</p>`;
    document.getElementById("cq").oninput = (e) => { F.q = e.target.value; save(false); };
    document.getElementById("cacad").onchange = (e) => { F.academie = e.target.value || ""; save(); };
    const setTown = () => { const v = document.getElementById("ctown").value, t = town(v), km = Number(document.getElementById("ckm").value);
      F.autour = t ? { ...t, km, ville: v } : null;
      if (t && carteUI.map) carteUI.map.setView([t.lat, t.lon], km <= 10 ? 11 : km <= 25 ? 10 : km <= 50 ? 9 : km <= 100 ? 8 : 7);
      save(); };
    document.getElementById("ctown").onchange = setTown;
    document.getElementById("ckm").onchange = setTown;
    document.querySelectorAll("[data-g]").forEach((el) => { el.onchange = () => {
      const g = el.dataset.g; F[g] = [...document.querySelectorAll(`[data-g="${g}"]:checked`)].map((x) => x.dataset.o); save(); }; });
  }
  function draw() {
    const kept = carteFilter(rows, F);
    kept.forEach((f) => { f.dist = F.autour && f.lat != null ? Math.round(haversineKm(F.autour.lat, F.autour.lon, f.lat, f.lon)) : null; });
    const listed = kept.filter((f) => inView(f) || f.lat == null)
      .sort((a, b) => (F.autour ? (a.dist ?? 1e9) - (b.dist ?? 1e9) : 0) || a.etablissement.localeCompare(b.etablissement, "fr"));
    const counts = {}; kept.forEach((f) => { const z = carteZone(f); counts[z] = (counts[z] || 0) + 1; });
    document.getElementById("carte-count").innerHTML = `${fmt(kept.length)} formation${kept.length > 1 ? "s" : ""} correspondant à vos critères · ${fmt(listed.length)} dans la partie visible de la carte`;
    document.getElementById("carte-legend").innerHTML = ok ? [...CARTE_ZONES, "autre"].map((z) => `<span><i class="lg-${z}" style="background:${carteColor(z)}"></i>${esc(carteLabel(z))}${z !== "autre" ? ` (${CARTE_SHAPE[z]})` : ""} : ${fmt(counts[z] || 0)}</span>`).join("") : `<span><i class="lg-autre" style="background:var(--muted)"></i>Formation (sans profil, pas de zone)</span>`;
    if (carteUI.map) {
      carteUI.layer.clearLayers();
      const map = carteUI.map, pts = kept.filter((f) => f.lat != null).map((f) => { const p = map.latLngToLayerPoint([f.lat, f.lon]); return { x: p.x, y: p.y, f }; });
      // from zoom 16 every formation is drawn on its own (several in one building would never split otherwise)
      for (const g of (map.getZoom() >= 16 ? pts.map((p) => [p]) : carteClusters(pts, map.getZoom() >= 13 ? 20 : 52))) {
        if (g.length === 1) {
          const f = g[0].f;
          L.marker([f.lat, f.lon], { icon: L.divIcon({ className: "carte-pin", html: carteMarker(f), iconSize: [18, 18] }), keyboard: true, title: `${f.etablissement}, ${carteLabel(carteZone(f))}` })
            .on("click", () => { carteUI.sel = f.cod_aff_form; showSel(); }).addTo(carteUI.layer);
        } else {
          const lat = g.reduce((a, p) => a + p.f.lat, 0) / g.length, lon = g.reduce((a, p) => a + p.f.lon, 0) / g.length, ring = carteRing(g);
          L.marker([lat, lon], { icon: L.divIcon({ className: "carte-pin", html: ring.html, iconSize: [ring.size, ring.size] }), keyboard: true, title: `${g.length} formations` })
            .on("click", () => map.setView([lat, lon], Math.min(map.getZoom() + 2, 18))).addTo(carteUI.layer);
        }
      }
    }
    showSel();
    document.getElementById("carte-items").innerHTML = carteList(listed, ok);
    bindVoeuButton(draw);
    document.querySelectorAll("[data-cpage]").forEach((b) => { b.onclick = () => { carteUI.page = Math.max(0, carteUI.page + Number(b.dataset.cpage)); draw(); }; });
    document.querySelectorAll("[data-pick]").forEach((el) => { el.onclick = (e) => { if (e.target.closest("a,button")) return; carteUI.sel = el.dataset.pick; showSel(true); }; });
  }
  function showSel(focus) {
    const f = rows.find((x) => x.cod_aff_form === carteUI.sel);
    document.getElementById("carte-sel").innerHTML = carteDetail(f, ok);
    bindVoeuButton(draw);
    if (focus && f && f.lat != null && carteUI.map) carteUI.map.setView([f.lat, f.lon], Math.max(carteUI.map.getZoom(), 12));
    if (focus) document.getElementById("carte-sel").scrollIntoView({ block: "nearest" });
  }
  function save(repanel = true) { store.set("carteFiltres2", F); carteUI.page = 0; if (repanel) panel(); draw(); }
  document.getElementById("cdip").onchange = (e) => goTo(e.target.value, "");
  document.getElementById("cmen").onchange = (e) => goTo(D.label, e.target.value);
  panel();
  draw();
}

// ---- lot 2 (Claude design guidelines): the summary comes before the detail; details live in tabs ----
// summaryBand: four figures read at a glance (official access rate, the student's zone, admits, jobs); every tile opens its tab.
// The zone tile is filled by the Plan B answer (same profile, same zone as « Mon parcours »); without a stored profile it asks for one.
const fmt2 = (x) => Number(x).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
// who the admits are (owner, 2026-11-10): the PUBLISHED counts of néo-bacheliers and other admits (admis.py on the server);
// the bar is drawn only when they add up to the published total; the label in lists comes from the server's fixed rule
const AUTRES_LABEL = "Majorité d'admis hors néo-bacheliers";
const autresBadge = (x) => (x && x.autres_majoritaires ? ` <span class="badge autres" title="Plus d'admis déjà bacheliers ou venus d'un autre parcours (réorientation, reprise d'études…) que de néo-bacheliers, sur au moins 10 admis">${AUTRES_LABEL}</span>` : "");
function admisBar(a) {
  if (!a) return "";
  const head = `<strong>Qui sont les admis ${esc(a.session)} ?</strong>`;
  const note = `<p class="muted small">Néo-bacheliers : ils passaient le bac l'année de leur admission. Autres admis : ils avaient déjà le bac ou venaient d'un autre parcours (réorientation, reprise d'études…) ; le SIES ne les détaille pas. Les mentions et les séries de bac publiées ne concernent que les néo-bacheliers.</p>`;
  if (!a.coherent) return `<div class="adm"><p class="small">${head} ${fmt(a.admis_neobac)} néo-bacheliers et ${fmt(a.admis_autres)} autres admis publiés, pour ${fmt(a.admis)} admis : les deux effectifs ne font pas exactement le total publié, la répartition n'est pas dessinée.</p>${note}</div>`;
  const w = (n) => (100 * n / a.admis).toFixed(2);
  return `<div class="adm"><p class="small">${head}${autresBadge(a)}</p>
    <div class="adm-bar" role="img" aria-label="${fmt(a.admis_neobac)} néo-bacheliers et ${fmt(a.admis_autres)} autres admis sur ${fmt(a.admis)} admis"><span class="neo" style="width:${w(a.admis_neobac)}%"></span><span class="autres" style="width:${w(a.admis_autres)}%"></span></div>
    <p class="small"><span class="adm-key neo"></span>${fmt(a.admis_neobac)} néo-bacheliers${a.pct_neobac != null ? ` (${pct(a.pct_neobac)} des admis)` : ""} · <span class="adm-key autres"></span>${fmt(a.admis_autres)} autres admis</p>${note}</div>`;
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
      return x ? { kind: "publie", taux: x.taux, what: x.source === "autres" ? "votre doublette, ligne « Autres doublettes »" : x.libelle,
        source: "rapport", session: rp.session, recoupe: rp.recoupe !== false, en_position: x.en_position, confirmes: x.confirmes }
        : { kind: "aucun", what: "votre doublette", why: `pas de ligne dans le rapport ${rp.session}` };
    }
    const sem = estimateSemblable(series, d.semblables, dkey);
    if (sem && estAt(sem) !== null) return { kind: "estimation", taux: estAt(sem), what: sem.label, source: "semblables", n_rapports: sem.n_rapports };
    const nat = dbl && dbl.status === "ok" ? estimateDoublette(series, dbl.groupe, dkey) : null;
    if (nat && estAt(nat) !== null) return { kind: "estimation", taux: estAt(nat), what: nat.source === "autres" ? "votre doublette, « Autres doublettes »" : nat.label, source: "national" };
    return route();
  }
  const v = pickVoie(rp, serie, prof.voie || null);
  if (v) return { kind: "publie", taux: v.taux, what: v.source === "autres" ? `votre ${VOIE_WORD[serie]}, ligne « ${v.libelle} »` : `votre ligne « ${v.libelle} »`,
    source: "rapport", session: rp.session, recoupe: rp.recoupe !== false, en_position: v.en_position, confirmes: v.confirmes };
  return route();
}
const PR_SOURCE = {
  rapport: (pr) => `publié · rapport du jury ${esc(pr.session)}${pr.recoupe ? "" : ", pas encore recoupé"} · ${fmt(pr.en_position)} sur ${fmt(pr.confirmes)} candidats`,
  semblables: (pr) => `estimation · rapports de ${fmt(pr.n_rapports)} formations semblables`,
  national: () => "estimation · écart national de votre doublette",
  voie: (pr) => `taux de proposition de cette formation (effectifs publiés)${pr.fragile ? ` · peu de candidats (${fmt(pr.candidats)})` : ""}`,
};
function profileRateTile(pr) {
  const tile = (value, note) => `<button type="button" class="sum-tile sum-profil" data-goto="admission">
      <span class="sum-label">Pour votre profil</span><span class="sum-value">${value}</span><span class="sum-note">${note}</span></button>`;
  const link = (note) => `<a class="sum-tile" href="#/profil"><span class="sum-label">Pour votre profil</span><span class="sum-value">—</span><span class="sum-note">${note}</span></a>`;
  if (!pr) return link("créez votre profil dans « Mon profil » : votre zone et votre doublette ou votre ligne");
  if (pr.kind === "incomplet") return link("indiquez vos deux spécialités dans « Mon profil »");
  if (pr.kind === "aucun" || pr.taux === null || pr.taux === undefined) return tile("—", `${esc(pr.what)} · ${esc(pr.why || "pas de chiffre")}`);
  return tile(pct1(pr.taux), `${esc(pr.what)} · ${PR_SOURCE[pr.source](pr)}`);
}
function summaryBand(r, d) {
  const prof = store.get("profile", null);
  const pr = profileRate(d, bacProfile());
  const jobs = d.metiers && d.metiers.status === "ok" ? d.metiers.metiers.length : null;
  const tile = (tab, label, value, note, extra = "") => `<button type="button" class="sum-tile" data-goto="${tab}"${extra}>
      <span class="sum-label">${label}</span><span class="sum-value">${value}</span><span class="sum-note">${note}</span></button>`;
  return `<section class="card summary" aria-label="L'essentiel en 30 secondes"><h2>L'essentiel</h2>
    <div class="sum-grid">
      ${tile("admission", `Taux d'accès ${r.session}`, pct(r.taux_acces_ens), "officiel, tous candidats, phase principale")}
      ${isReo(prof) ? "" : profileRateTile(pr)}
      ${isReo(prof) ? tile("admission", "Accès estimé hors terminale", pct1(d.reorientation && d.reorientation.acces_estime), reoWhy(d.reorientation, "estimation, pas une zone : calcul dans « Plus de chiffres sur l'admission »"))
        : prof ? tile("admission", "Votre zone", '<span class="muted">…</span>', "selon votre profil, d'après les admis passés", ' id="sum-zone"') : ""}
      ${tile("admission", `Admis ${r.session}`, fmt(r.acc_tot), r.capa_fin != null ? `pour ${fmt(r.capa_fin)} places` : "places non publiées")}
      ${tile("emploi", "Métiers visés", jobs != null ? fmt(jobs) : "—", jobs != null ? "d'après la fiche Onisep du diplôme" : "pas de fiche Onisep pour ce diplôme")}
    </div>
    ${admisBar(d.admis)}
    ${d.jury_tab ? `<p class="small sum-jury"><button type="button" class="linkish" data-goto="jury">${d.jury_tab.kind === "own" ? `Ce que regarde le jury : son rapport public ${esc(d.jury_tab.session)}` : "Ce que regardent les jurys de formations semblables (pas de rapport pour celle-ci)"} →</button></p>` : ""}
    <p class="muted small">Des résultats des campagnes passées, pas des chances d'admission.</p></section>`;
}
function fillZoneTile(target) {
  const el = document.getElementById("sum-zone");
  if (!el) return;
  const z = target && ZONES[target.zone];
  el.querySelector(".sum-value").innerHTML = z ? zonePillHtml(target.zone) : "—";
  if (target && target.uncertain) el.querySelector(".sum-note").textContent = "lecture incertaine : peu de données";
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
    bar.querySelectorAll("[role=tab]").forEach((b) => {
      const on = b.dataset.tabKey === k;
      b.setAttribute("aria-selected", String(on));
      const panel = document.getElementById(b.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
    });
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
    t.onclick = () => { if (bar.querySelector(`[data-tab-key="${t.dataset.goto}"]`)) { open(t.dataset.goto); bar.scrollIntoView({ block: "start" }); } };
  });
}

async function viewFormation(cod, session) {
  const d = await api(`/api/formation/${encodeURIComponent(cod)}${session ? `?session=${session}` : ""}`);
  const r = d.record, inBasket = basket.get().includes(r.cod_aff_form);
  const years = d.history.map((h) => h.session);
  const geo = r.lat != null ? ` · <a href="https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lon}#map=15/${r.lat}/${r.lon}" target="_blank" rel="noopener">carte</a>` : "";
  // sprint 19: the jury tab is rendered once; the summary links to it (own report first, else the similar formations' reports)
  const juryHtml = juryCard(d.rapport) || semblablesJuryCard(d.semblables, d.rapport);
  d.jury_tab = !juryHtml ? null : juryCard(d.rapport) ? { kind: "own", session: d.rapport.session } : { kind: "semblables" };
  $view.innerHTML = `
  <div class="card fhead">
    <h1>${esc(r.g_ea_lib_vx)}</h1>
    <div>${esc(r.lib_for_voe_ins)}${d.apprentissage && d.apprentissage.length ? ` ${voieBadges({ initiale: r.apprentissage !== true, apprentissage: true })}` : ""}</div>
    <div class="muted small">${esc(r.ville_etab)} · ${esc(r.acad_mies)} · ${esc(r.contrat_etab)} · ${esc(r.select_form)} · n° Parcoursup ${esc(r.cod_aff_form)}</div>
    <div class="toolbar" style="margin-top:8px">
      ${voeuButton(r.cod_aff_form)}
      <button id="bask" class="${inBasket ? "" : "primary"}">${inBasket ? "Retirer du comparateur" : "Comparer"}</button>
    </div>
  </div>
  ${d.warnings.map((w) => `<div class="warn">${ICONS.warn} ${esc(w.text)}</div>`).join("")}
  ${summaryBand(r, d)}
  <p class="small fhead-links"><label>Session <select id="sess">${years.map((y) => `<option ${y === r.session ? "selected" : ""}>${y}</option>`).join("")}</select></label>
      · <a href="#/evolution/${encodeURIComponent(r.cod_aff_form)}">Évolution 4 ans →</a>
      · <a href="${esc(r.fiche_url)}" data-cod="${esc(r.cod_aff_form)}" target="_blank" rel="noopener">Fiche Parcoursup ↗</a>${geo}</p>
  ${tabbed("fiche", [
    ["admission", "Y entrer", `
  <div class="card"><h2>Indicateurs officiels SIES · ${r.session}</h2>
    <div class="grid3">
      <div><div class="muted small">Taux d'accès (phase principale) ${tip("taux_acces_ens")}</div><div class="big">${pct(r.taux_acces_ens)}</div>${pvLine(d.prevision, "taux_acces_ens")}</div>
      <div><div class="muted small">Part des terminales générales parmi les candidats appelés (PP) ${tip("part_terminale_generale_en_position_admis_pp")}</div><div class="big">${pct(r.part_terminale_generale_en_position_admis_pp)}</div>${pvLine(d.prevision, "part_terminale_generale_en_position_admis_pp")}</div>
      <div><div class="muted small">Admis (cohorte finale)</div><div class="big">${fmt(r.acc_tot)}</div><div class="muted small">capacité ${fmt(r.capa_fin)}</div>${pvLine(d.prevision, "acc_tot")}</div>
    </div></div>
  ${doubletteCard(d.doublettes, d.rapport, d.semblables)}
  ${appelCard(d.appel)}
  <div id="planb"></div>
  ${offerCard(r, d.apprentissage)}
  <details class="more-card"><summary><strong>Plus de chiffres sur l'admission</strong> <span class="muted small">prévision, calendrier des propositions, lycées d'origine, étapes de la sélection, comparaison avec la filière, candidats hors terminale</span></summary>
  ${previsionCard(d.prevision)}
  ${reoCard(d.reorientation)}
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
    ["reussite", "Réussir et poursuivre", `
  ${successCard(d.success)}
  ${masterCard(d.master)}
  ${passerellesCard(d.passerelles)}
  ${licenceMasterCard(d.licence_master)}
  ${butCard(d.but)}`],
    ["emploi", "Emploi et métiers", `
  ${insertionCard(d.insertion)}
  ${cereqCard(d.cereq)}
  ${metiersCard(d.metiers)}`],
    ["historique", "Historique", `
  <div class="card"><h2>Historique de la lignée ${tip("lineage")}</h2><p class="muted small">Code de l'établissement (UAI) : ${esc(r.cod_uai)}</p><div class="scroll"><table>
    <tr><th>Session</th><th>cod_aff_form</th><th>Libellé</th><th>Lien vers la campagne suivante</th><th class="num">Admis</th><th class="num">Taux d'accès</th></tr>
    ${d.history.map((h) => `<tr><td><a href="#/f/${esc(h.cod_aff_form)}/${h.session}">${h.session}</a></td><td>${esc(h.cod_aff_form)}</td><td>${esc(h.lib_for_voe_ins)}</td>
      <td>${h.link_to_next ? lineageBadge(h.link_to_next) : `<span class="muted small">—</span>`}</td><td class="num">${fmt(h.acc_tot)}</td><td class="num">${pct(h.taux_acces_ens)}</td></tr>`).join("")}
  </table></div></div>`],
  ])}${feedbackBox("fiche")}`;
  bindTabs("fiche");
  document.getElementById("sess").onchange = (e) => { location.hash = `#/f/${r.cod_aff_form}/${e.target.value}`; };
  loadPlanB(r.cod_aff_form);
  document.getElementById("bask").onclick = () => { basket.toggle(r.cod_aff_form); viewFormation(cod, session); };
  bindVoeuButton(() => viewFormation(cod, session));
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
  const qs = new URLSearchParams({ serie, mention: prof.mention || "ab" });
  if (serie === "bg") { qs.set("spe1", prof.spe1 || "MATHS"); qs.set("spe2", prof.spe2 || "SES"); }
  if (prof.academie) qs.set("academie", prof.academie);
  if (includePaid) qs.set("include_paid", "true");
  // every request stamps its box: only the latest request made for a box still on the page may
  // fill it (a late answer for formation A, or for a superseded toggle, is dropped)
  const req = String(++planbSeq);
  box.dataset.req = req;
  if (opts.inline) box.innerHTML = `<p class="muted small">Recherche d'un plan B…</p>`;
  let d;
  try { d = await api(`/api/planb/${encodeURIComponent(cod)}?${qs}`); } catch (e) {
    if (box.isConnected && box.dataset.req === req) {
      box.innerHTML = opts.inline ? `<p class="muted small">Plan B indisponible pour le moment.</p>` : "";
      if (!opts.inline && p) fillZoneTile(null);                      // no zone tile left on "…"
    }
    return;
  }
  if (!box.isConnected || box.dataset.req !== req) return;
  if (!opts.inline && p) fillZoneTile(d.target);
  const who = `${{ bg: "bac général", bt: "bac technologique", bp: "bac professionnel" }[serie]}${serie === "bg" ? ` ${esc(prof.spe1 || "MATHS")} + ${esc(prof.spe2 || "SES")}` : ""}, mention ${{ sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien" }[prof.mention] || "assez bien"}${prof.academie ? `, académie de ${esc(prof.academie)}` : ""}`;
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
    body = `<p class="small">Formation visée${d.target.complement ? ` (${esc(d.target.complement)})` : ""} : ${zoneBadge(d.target.zone)} · ${d.target.serie === "bg" ? "taux d'accès" : "accès estimé"} ${fmt(d.target.taux_acces_ens)} %</p>
    <div class="scroll"><table><tr><th>Formation</th><th>Zone</th><th class="num">${serie === "bg" ? "Taux d'accès" : "Accès estimé"}</th><th class="num">Votre mention ou moins</th><th class="num">Distance de la formation visée</th>${opts.onPin ? "<th></th>" : ""}</tr>
    ${d.alternatives.map((a) => `<tr><td><a href="#/f/${esc(a.cod_aff_form)}">${esc(a.etablissement)}</a><div class="muted small">${esc(a.complement || a.filiere)} · ${esc(a.ville)}${a.academie ? ` (${esc(a.academie)})` : ""}</div>${a.paid ? '<span class="badge warnb">privé : frais possibles</span>' : ""}${offerBadges(a, true)}</td>
      <td>${zoneBadge(a.zone)}<div class="muted small">${WHY[a.why] || ""}</div></td>
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
    <p class="small"><strong>${esc(s.etab_label)}</strong> · ${esc(s.discipline_label)}. Chiffres de <strong>tous les néo-bacheliers inscrits en L1</strong> de cette grande discipline dans l'université, pas seulement de cette licence.${small ? ' <span class="badge warnb">petit effectif</span>' : ""}</p>
    <div class="scroll"><table><tr><th>Indicateur · fiabilité ${tip("fiabilite")}</th><th class="num">Cette université</th><th class="num">Attendu vu le profil des inscrits ${tip("success")}</th><th class="num">France, même discipline</th></tr>${rows}</table></div>
    ${bars}
    <p class="muted small">Source : SIES (ministère de l'Enseignement supérieur), tableaux par établissement et discipline. Résultats de cohortes passées, pas des chances de réussite ; l'écart au taux attendu ne classe pas les universités.</p></div>`;
}

// ---- Sprint 6: success beyond licence (BUT per university; master per university x discipline) ----
// The student's profile stays in the browser: the page picks the national rows that match it.
const MENTION_ROW = { sansmention: "passable1", ab: "ab", b: "b", tb: "tb" };
const MENTION_TXT = { passable1: "passable (1er groupe)", ab: "assez bien", b: "bien", tb: "très bien" };
const SERIE_TXT = { bg: "bac général", bt: "bac technologique", bp: "bac professionnel" };
function profileRows(rows, kind) {
  // kind "but": rows of BUT Tableau 1 (dim serie|mention); kind "chaine": the 2017 L1 cohort (dim bac|mention)
  const p = bacProfile() || {};
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";   // stored profile: never trusted
  const men = MENTION_ROW[p.mention] || "ab";
  const sdim = kind === "but" ? "serie" : "bac";
  const pick = (dim, code) => (rows || []).find((r) => r.dim === dim && r.code === code);
  let s = pick(sdim, serie), sLabel = SERIE_TXT[serie], note = "";
  const code = (x) => typeof x === "string" && /^[A-Z]{2,7}$/.test(x);     // journey.SPECIALTIES codes
  if (kind === "but" && serie === "bg") {
    if (code(p.spe1) && code(p.spe2) && p.spe1 !== p.spe2) {
      const d = pick("serie", `bg:${[p.spe1, p.spe2].sort().join("+")}`);
      if (d) { s = d; sLabel = `bac général ${esc(p.spe1)} + ${esc(p.spe2)}`; }
      else note = "votre doublette n'est pas publiée à part (moins de 1 % des inscrits) : ligne de l'ensemble du bac général";
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
    <p class="muted small">Deux lignes séparées : le SIES ne croise pas la série et la mention.${pr.note ? ` ${esc(pr.note)}.` : ""}</p>` : "";
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
    <p class="small"><strong>${esc(b.etab_label)}</strong> · toutes spécialités de BUT. Chiffres de <strong>tous les néo-bacheliers inscrits en 1re année de BUT</strong> dans l'université : le SIES ne les publie ni par IUT, ni par spécialité.${R && R.small ? ' <span class="badge warnb">petit effectif</span>' : ""}</p>
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
    <p class="muted small">Une cohorte suivie de bout en bout (pas une multiplication de taux). Lignes séparées : le SIES ne croise pas le type de bac et la mention.</p>` : "";
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
    <p class="muted small">Ce sont des parts des inscrits en L1, pas des réorientés. Le détail publié n'est pas complet : les autres réorientés suivent des formations que le SIES ne détaille pas.</p>`;
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
    <p class="muted small">Admis : des personnes ; vœux : des candidatures additionnées sur les parcours, pas des personnes. Emploi salarié à 18 mois : parmi les diplômés qui ont quitté les études (InserSup, promotion ${esc(x.annee_insertion)}). Les métiers visés sont ceux de la fiche nationale Onisep du master, pas de cette université. Pour ces métiers, on donne l'écart entre la note la plus basse et la plus haute, jamais une moyenne, et le nombre de métiers selon la projection 2030 ; un métier exposé à l'IA est plus souvent transformé que remplacé, et la complémentarité humaine est une estimation adaptée. Un repère n'apparaît que si les deux écarts ne se chevauchent pas. Ce sont des résultats passés et des projections, pas des chances d'admission ou d'emploi. Sources : SIES (MonMaster, InserSup), Onisep (Idéo, licence ODbL), OIT 2025, O*NET, Dares / France Stratégie.</p></div>`;
}

// ---- Prévision n+1: calibrated ranges of every published indicator with a history (never a probability) ----
const PV_GROUPS = [["acces", "Accès et candidats appelés"], ["volumes", "Volumes : vœux, classés, admis"], ["admis", "Profil des admis"]];
const pvVal = (i, v) => (v == null ? "—" : i.kind === "taux" ? `${fmt(v, 1)}\u00a0%` : fmt(v));
const pvRange = (i) => `${pvVal(i, i.lo)} à ${pvVal(i, i.hi)}`;
const pvCov = (i) => (i.coverage == null ? "non testée" : `${fmt(100 * i.coverage, 0)}\u00a0% dans la fourchette en ${i.holdout_year}`);
function pvLine(p, key) {
  const i = p && p.indicators.find((x) => x.indicator === key);
  if (!i) return "";
  return `<div class="small">Prévision ${esc(p.target)} : <strong class="nowrap">${pvRange(i)}</strong> ${tip("prevision")}${i.fragile ? ' <span class="muted">(fourchette moins fiable)</span>' : ""}</div>`;
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
    ${PV_GROUPS.map((g, k) => block(g, k === 0)).join("")}
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
    <div class="scroll"><table><tr><th></th>${th}</tr>${rows}</table></div>
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
    <p class="muted small">${INS_NOTE} Après un BUT, la plupart des diplômés poursuivent leurs études : ces taux portent sur ceux qui sont partis travailler. Source : InserSup (SIES).</p>`;
}

function offerCard(r, app) {
  const list = offerList(r);
  if (!r.carto_session && !list.length && !(app && app.length)) return "";
  const src = r.carto_session ? `cartographie Parcoursup ${r.carto_session}` : "libellé SIES";
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
const MENTIONS = [{ key: "acc_tbf", name: "TB félicitations" }, { key: "acc_tb", name: "Très bien" }, { key: "acc_b", name: "Bien" },
  { key: "acc_ab", name: "Assez bien" }, { key: "acc_sansmention", name: "Sans mention" }, { key: "acc_mention_non_renseignee", name: "Non renseignée" }];

async function viewEvolution(cod) {
  const f = await api(`/api/formation/${encodeURIComponent(cod)}`);
  const lin = await api(`/api/lineage/${encodeURIComponent(f.record.lineage_id)}`);
  const years = META.years, by = Object.fromEntries(lin.years.map((r) => [r.session, r]));
  const rows = years.map((y) => by[y] || null), col = (k) => rows.map((r) => r ? r[k] : null);
  const hollow = rows.map((r) => r ? r.low_n_flag : false);
  $view.innerHTML = `
  <div class="card"><h1>Évolution de la cohorte 2022–2025</h1>
    <div><a href="#/f/${esc(f.record.cod_aff_form)}">${esc(f.record.g_ea_lib_vx)}</a> · ${esc(f.record.lib_for_voe_ins)}</div>
    <div class="muted small">Lignée ${esc(lin.lineage_id)} · ${lineageBadge(f.record.lineage_confidence)}
    ${lin.missing_years.length ? ` · absente en ${lin.missing_years.join(", ")} (aucune interpolation)` : ""}</div></div>
  ${f.warnings.map((w) => `<div class="warn">${ICONS.warn} ${esc(w.text)}</div>`).join("")}
  <div class="charts">
    <div class="card"><h3>Taux d'accès &amp; part des terminales générales parmi les candidats appelés (PP) ${tip("taux_acces_ens")}</h3>
      ${lineLegend([{ name: "Taux d'accès" }, { name: "Part des terminales générales parmi les appelés" }])}
      ${lineChart(years, [{ name: "Taux d'accès", values: col("taux_acces_ens") }, { name: "Part term. gén.", values: col("part_terminale_generale_en_position_admis_pp") }])}</div>
    <div class="card"><h3>Admis néo-bacheliers par série de bac ${tip("mentions")}</h3>${legend(SERIES)}${stackedBars(years, SERIES, rows)}</div>
    ${doubletteCharts(f.doublettes, years, f.semblables, f.rapport)}
    <div class="card"><h3>Admis par mention au bac ${tip("mentions")}</h3>${legend(MENTIONS)}${stackedBars(years, MENTIONS, rows)}</div>
    <div class="card"><h3>Boursiers, femmes, origine</h3>
      ${lineLegend([{ name: "% boursiers" }, { name: "% femmes" }, { name: "% même académie" }, { name: "% même établissement" }])}
      ${lineChart(years, ["pct_bours", "pct_f", "pct_aca_orig", "pct_etab_orig"].map((k) => ({ name: label(k), values: col(k), hollow })))}
      <p class="muted small">Points creux : moins de ${META.low_n_threshold} admis. ${tip("low_n")}</p></div>
    <div class="card"><h3>Effectifs (trois étapes, non ratio-ables) ${tip("funnel")}</h3><div class="scroll"><table>
      <tr><th></th>${years.map((y) => `<th class="num">${y}</th>`).join("")}</tr>
      ${["voe_tot", "nb_voe_pp", "nb_cla_pp", "prop_tot", "acc_tot", "acc_neobac", "acc_term", "acc_brs", "capa_fin"].map((k) => `<tr><td>${esc(label(k))}</td>${col(k).map((v) => `<td class="num">${fmt(v)}</td>`).join("")}</tr>`).join("")}
    </table></div></div>
  </div>`;
}

async function viewCompare() {
  const ids = basket.get();
  if (!ids.length) { $view.innerHTML = `<div class="card"><h2>Comparateur</h2><p class="muted">Ajoutez des formations depuis leur fiche (jusqu'à 6).</p></div>`; return; }
  const d = await api(`/api/compare?ids=${ids.map(encodeURIComponent).join(",")}`);
  const F = d.formations, years = META.years;
  const metric = (f, m) => f.peers.find((p) => p.metric === m) || {};
  const rowsDef = [
    ["Session", (f) => f.record.session], ["Filière", (f) => esc(f.record.fil_lib_voe_acc)],
    ["Taux d'accès (PP) " + tip("taux_acces_ens"), (f) => pct(f.record.taux_acces_ens)],
    ["… percentile filière", (f) => metric(f, "taux_acces_ens").peer_percentile != null ? "P" + fmt(metric(f, "taux_acces_ens").peer_percentile) : "—"],
    ["Part des term. générales parmi les appelés (PP) " + tip("part_terminale_generale_en_position_admis_pp"), (f) => pct(f.record.part_terminale_generale_en_position_admis_pp)],
    ["Vœux (toutes phases)", (f) => fmt(f.record.voe_tot) + (f.record.subwish_flag ? ' <span class="badge warnb">sous-vœu</span>' : "")],
    ["Classés (PP)", (f) => fmt(f.record.nb_cla_pp)], ["Proposés", (f) => fmt(f.record.prop_tot)],
    ["Admis", (f) => fmt(f.record.acc_tot) + (f.record.low_n_flag ? ` <span class="badge warnb">n&lt;${META.low_n_threshold}</span>` : "")],
    ["Néo-bacheliers / autres admis", (f) => admisCell(f.admis)],
    ["% TB + TBF", (f) => pct(metric(f, "pct_tb_tbf").value)], ["% boursiers", (f) => pct(f.record.pct_bours)],
    ["% femmes", (f) => pct(f.record.pct_f)], ["% bac général", (f) => pct(f.record.pct_bg)],
    ["% même académie", (f) => pct(f.record.pct_aca_orig)],
    ["Proposition dès l'ouverture " + tip("timing"), (f) => (f.record.acc_tot > 0 ? pct(f.record.pct_acc_debutpp) : "—")],
    ["Options", (f) => offerBadges(f.record) || '<span class="muted small">—</span>'], ["Lignée", (f) => lineageBadge(f.record.lineage_confidence) + ` ${f.history.length} camp.`],
  ];
  const series = F.map((f) => { const by = Object.fromEntries(f.history.map((h) => [h.session, h.taux_acces_ens])); return { name: `${f.record.g_ea_lib_vx} · ${f.record.fil_lib_voe_acc}`, values: years.map((y) => by[y] ?? null) }; });
  $view.innerHTML = `<div class="card"><h2>Comparateur</h2><p class="muted small">${narrow() && F.length > 1 ? "Faites glisser le tableau pour voir les autres formations ; la première colonne reste en place." : ""}</p><div class="scroll"><table class="cmp">
    <tr><th></th>${F.map((f) => `<th><a href="#/f/${esc(f.record.cod_aff_form)}">${esc(f.record.g_ea_lib_vx)}</a><div class="small">${esc(f.record.fil_lib_voe_acc)}</div><div class="muted small">${esc(f.record.ville_etab)}${f.record.lib_comp_voe_ins ? " · " + esc(f.record.lib_comp_voe_ins) : ""}</div>
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
  $view.innerHTML = `<div class="card"><h2>Doublettes de spécialités des admis</h2>
    <p class="muted small">Source : SIES, propositions d'admission des terminales générales selon leurs enseignements de spécialité, agrégées au niveau national par type de formation (pas par formation). SIES publie les propositions et les acceptations, sans nombre de candidats. Le tableau montre donc la composition des admis (acceptations) par doublette : c'est une répartition, pas un taux d'accès.</p>
    <div class="toolbar"><label>Session <select id="ss">${META.years.map((y) => `<option ${y === d.session ? "selected" : ""}>${y}</option>`).join("")}</select></label>
      <label>Type de formation <select id="st" style="max-width:100%">${d.formation_types.map((t) => `<option ${t === d.formation_type ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label></div>
    <p class="small">${fmt(d.totals.n_accepte)} acceptations · ${fmt(d.totals.n_proposition)} propositions</p>
    <div class="scroll"><table><tr><th>Doublette</th><th>Part des admis</th><th class="num">Acceptations</th><th class="num">Propositions</th></tr>
    ${d.rows.map((r) => `<tr><td>${esc(r.doublette)}</td>
      <td style="min-width:140px"><svg viewBox="0 0 100 10" preserveAspectRatio="none" style="width:100%;height:10px;display:block"><rect width="${100 * (r.pct_acceptations || 0) / max}" height="10" fill="var(--c1)"/></svg><span class="small">${pct(r.pct_acceptations)}</span></td>
      <td class="num">${fmt(r.n_accepte)}</td><td class="num">${fmt(r.n_proposition)}</td></tr>`).join("") || `<tr><td class="muted">Pas de données pour cette session.</td></tr>`}
    </table></div></div>`;
  document.getElementById("ss").onchange = (e) => { location.hash = `#/specialites/${e.target.value}/${encodeURIComponent(d.formation_type || "")}`; };
  document.getElementById("st").onchange = (e) => { location.hash = `#/specialites/${d.session}/${encodeURIComponent(e.target.value)}`; };
}

function verificationCard(v) {
  if (!v) return `<div class="card"><h2>Vérification SIES</h2><p class="muted">Aucun rapport publié pour ce build.</p></div>`;
  const st = (x) => ({ pass: "✓", fail: "✗", upstream_inconsistency: "incohérence SIES (reproduite à l'identique)" }[x] || "–");
  return `<div class="card"><h2>Vérification SIES : ${esc(v.overall)}</h2>
    <p class="muted small">Rapport du ${esc(v.generated_at)}. Identités comptables par campagne (« diag » = contrôle diagnostique du dénominateur).</p>
    <div class="scroll"><table><tr><th>Contrôle</th><th>Session</th><th class="num">Évaluables</th><th class="num">Écarts</th><th class="num">% ok</th><th>Statut</th></tr>
    ${v.identities.map((r) => `<tr><td>${esc(r.check)}${r.primary ? "" : ` <span class="badge">diag</span>`}</td><td>${r.session}</td><td class="num">${fmt(r.n_evaluable)}</td><td class="num">${fmt(r.n_violations)}</td><td class="num">${r.pct_ok ?? "—"}</td><td>${st(r.status)}</td></tr>`).join("")}
    ${(v.taux_raw || []).map((r) => `<tr><td>taux_acces_ens = fichier SIES brut</td><td>${r.session}</td><td class="num">${fmt(r.n_upstream)}</td><td class="num">${fmt(r.n_mismatch)}</td><td></td><td>${st(r.status)}</td></tr>`).join("")}
    ${(v.taux_live || []).map((r) => `<tr><td>taux_acces_ens = API SIES en direct (échantillon)</td><td>${r.session}</td><td class="num">${fmt(r.n_sampled)}</td><td class="num">${fmt(r.n_mismatch)}</td><td></td><td>${st(r.status)}</td></tr>`).join("")}
    </table></div></div>`;
}

async function viewQualite() {
  const c = await api("/api/continuity");
  let v = null, pr = null;
  try { v = await api("/api/verification"); } catch (_) { /* no report published */ }
  try { pr = await api("/api/journey/persona"); } catch (_) { /* no persona report */ }
  const cols = c.rows.length ? Object.keys(c.rows[0]) : [];
  const audit = META.schema_audit.filter((a) => a.status !== "keyword");
  const personaCard = pr ? `<div class="card"><h2>Calibration du parcours : ${esc(pr.overall)}</h2>
    <p class="muted small">Persona : Mathématiques + SES, mention Assez bien. Rapport du ${esc(pr.generated_at)}.</p>
    <table>${pr.checks.map((c) => `<tr><td>${esc(c.check)}</td><td>${c.ok ? "✓" : "✗"}</td></tr>`).join("")}</table></div>` : "";
  $view.innerHTML = verificationCard(v) + personaCard + `<div class="card"><h2>Continuité longitudinale (ancre ${c.anchor}) ${tip("lineage")}</h2><div class="scroll"><table>
    <tr>${cols.map((k) => `<th class="${k === "fili" ? "" : "num"}">${esc(k)}</th>`).join("")}</tr>
    ${c.rows.map((r) => `<tr>${cols.map((k) => `<td class="${k === "fili" ? "" : "num"}">${esc(r[k])}</td>`).join("")}</tr>`).join("")}</table></div></div>
  <div class="card"><h2>Harmonisation des schémas</h2><p class="muted small">Champs canoniques alimentés par un alias, ou absents d'un millésime (laissés à NULL, jamais imputés).</p>
    <div class="scroll"><table><tr><th>Session</th><th>Champ canonique</th><th>Colonne amont</th><th>Statut</th></tr>
    ${audit.map((a) => `<tr><td>${a.session ?? ""}</td><td>${esc(a.canonical)}</td><td>${esc(a.upstream ?? "—")}</td><td>${esc(a.status)}</td></tr>`).join("")}</table></div>
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
  atypique: { label: "Atypique / prérequis non alignés", color: "var(--c5)" },
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
        <span>Réorientation, reprise d'études : le SIES ne publie ni mention ni série pour vous. SupCompass affiche un accès estimé, sans zone.</span></label>
      <a class="pf-opt" href="#/premiere"><strong>En seconde ou en première</strong>
        <span>Pas encore de doublette ni de mention : comparez les doublettes possibles de vos spécialités.</span></a>
    </div></section>`;
  const acad = field(`<label>Votre académie <select name="academie"><option value="">Pas indiquée</option>${opt(JV.academies.map((a) => ({ code: a, label: a })), p.academie)}</select></label>`,
    "Pour une licence très demandée, le recteur fixe une part maximale de candidats venant d'une autre académie : votre académie compte. Elle sert aussi à montrer d'abord les formations proches de vous.");
  if (reo) {
    return `<form id="pf">${sit}<section class="card"><h2>2 · Où vous êtes</h2>${acad}</section>${saved ? "" : PF_SAVE}</form>`;
  }
  const bac = `<section class="card"><h2>2 · Votre bac</h2>
    ${field(`<label>Votre bac <select name="serie">${opt(JV.series || [{ code: "bg", label: "bac général" }], serie)}</select></label>`,
      "Chaque formation publie la part de ses admis venant du bac général, technologique ou professionnel.")}
    ${serie !== "bg" && JV.voies && (JV.voies[serie] || []).length ? field(`<label>${serie === "bt" ? "Série et spécialités" : "Spécialité de bac pro"} <select name="voie"><option value="">Pas indiqué</option>${opt(JV.voies[serie], p.voie)}<option value="autre" ${p.voie === "autre" ? "selected" : ""}>${serie === "bt" ? "Autre série ou autres spécialités" : "Autre spécialité"}</option></select></label>`,
      `Les rapports des jurys publient une ligne par ${serie === "bt" ? "série technologique et ses spécialités" : "spécialité de bac pro"} : la fiche de chaque formation vous montre la vôtre quand elle existe.`) : ""}
    ${serie === "bg" ? field(`<div class="pf-ctl"><span>Vos deux spécialités de terminale</span><div class="pf-pair"><select name="spe1" aria-label="Spécialité 1">${opt(JV.specialties, p.spe1, (x) => x.short)}</select>
      <select name="spe2" aria-label="Spécialité 2">${p.spe2 === p.spe1 ? '<option value="" selected>Choisissez</option>' : ""}${opt(JV.specialties.filter((x) => x.code !== p.spe1), p.spe2, (x) => x.short)}</select></div></div>`,
      `${p.spe2 === p.spe1 ? '<span class="warn">Votre profil a deux fois la même spécialité : choisissez la deuxième. Vos zones ne sont pas lues avant.</span> ' : ""}En terminale, vous gardez deux des trois spécialités de première, deux spécialités différentes : une seule peut être artistique. C'est votre doublette. Les rapports des jurys publient le taux d'accès de chaque doublette : la fiche de chaque formation affiche celui de la vôtre quand il existe, sinon une estimation dite comme telle.`) : ""}
    ${serie === "bg" && (p.spe1 === "MATHS" || p.spe2 === "MATHS") ? field(`<label class="pf-check"><span><input type="checkbox" name="maths_expertes" ${p.maths_expertes ? "checked" : ""}> Mathématiques expertes</span></label>`,
      "Notée pour vous : les données publiques ne détaillent pas les options de terminale, elle ne change donc aucun chiffre. Regardez les attendus sur la fiche Parcoursup.") : ""}
  </section>`;
  const mention = `<section class="card"><h2>3 · Votre mention visée</h2>
    ${field(`<label>Mention au bac <select name="mention">${opt(JV.mentions, p.mention)}</select></label>`,
      "Les admis de chaque formation sont publiés par mention. C'est elle qui situe chaque formation pour vous : <strong>vœu de sécurité</strong>, <strong>cible</strong> ou <strong>ambitieux</strong>. Choisissez celle que vos moyennes actuelles laissent attendre, ni plus ni moins.")}
  </section>`;
  const where = `<section class="card"><h2>4 · Où vous êtes</h2>
    ${acad}
    ${field(`<div class="pf-ctl lyc-pick"><label for="lyc-q">Votre lycée (facultatif)</label>
      <div class="lyc-row"><input id="lyc-q" type="search" autocomplete="off" placeholder="Nom, ville ou code UAI du lycée" value="${p.lycee ? esc(p.lycee.nom) : ""}" aria-describedby="lyc-help">
      ${p.lycee ? '<button type="button" id="lyc-clear" class="small">Retirer</button>' : ""}</div>
      <div id="lyc-res" class="lyc-res" role="listbox"></div><div id="lyc-help" class="muted small"></div></div>`,
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
  return `<div class="card">${head}<p class="small"><strong>${esc(l.nom)}</strong> · ${esc(l.commune)}${l.academie ? ` · académie de ${esc(l.academie)}` : ""}</p>
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
    <div class="lyc-res">${hits.map((l) => `<button type="button" data-suggest="${esc(l.uai)}"><strong>${esc(l.nom)}</strong><span class="muted small"> · ${esc(l.commune)}${l.academie ? ` (${esc(l.academie)})` : ""}</span> → Le choisir comme mon lycée</button>`).join("")}</div>`;
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
    ? `${pct1(f.autres.taux)}${rateBar(f.autres.taux, "var(--voie-bg)")}<div class="estim">Autres doublettes (estimation : ${fmt(f.autres.n_doublettes)} doublettes de moins de ${DBL_SEUIL} candidats)</div>`
    : `<strong>${pc1(f.offer_rate)}</strong>${f.offer_rate !== null && f.offer_rate !== undefined ? rateBar(100 * f.offer_rate, "var(--voie-bg)") : ""}`);
  return `<div class="legend">${Object.entries(GATES).map(([k, g]) => `<label style="cursor:pointer"><input type="checkbox" data-gate="${k}" ${show.has(k) ? "checked" : ""}> <i style="background:${g.color}"></i>${g.label} (${s1.filieres.filter((f) => f.gate === k).length})</label>`).join("")}</div>
  ${allRare ? `<div class="info">Votre doublette est rare : moins de ${DBL_SEUIL} candidats dans chaque filière sur 2022–2025. Les taux affichés sont ceux des « Autres doublettes » de chaque filière (doublettes rares regroupées) : une estimation.</div>`
    : fewOnly ? `<div class="info">Peu de candidats ont votre doublette : moins de ${fmt(GATE_MIN)} dans chaque filière sur 2022–2025, les filières sont donc affichées quand même. Là où ils sont moins de ${DBL_SEUIL}, le taux affiché est celui des « Autres doublettes » (estimation).</div>` : ""}
  <div class="scroll"><table class="stack"><tr class="stack-head"><th>Filière</th><th class="num">Taux de proposition de votre doublette</th><th class="num">… tous les bacheliers généraux</th><th>Part de destination</th><th class="num">Part des admis</th><th class="num">Indice</th><th></th></tr>
  ${rows.map((f) => `<tr><td><span class="badge gbadge" style="--zc:${GATES[f.gate].color}">${GATES[f.gate].label}</span><br>${esc(f.label)}<div class="muted small">${fmt(f.candidates)} candidats de la doublette · ${f.years} an(s)</div></td>
    <td class="num" data-label="Taux de proposition de votre doublette">${rate(f)}</td><td class="num muted" data-label="Tous les bacheliers généraux">${pc1(f.offer_rate_all)}</td>
    <td data-label="Part de destination" style="min-width:130px"><svg viewBox="0 0 100 10" preserveAspectRatio="none" style="width:100%;height:10px;display:block"><rect width="${100 * (f.destination_share || 0) / max}" height="10" fill="${GATES[f.gate].color}"/></svg><span class="small">${pc1(f.destination_share)}</span></td>
    <td class="num" data-label="Part des admis">${pc1(f.share)}</td><td class="num" data-label="Indice">×${fmt(f.lift, 2)}</td>
    <td class="acts">${f.gate === "atypique" || f.gate === "insuffisant" ? "" : f.n_formations ? `<button data-type="${esc(f.type_key)}" data-label="${esc(f.label)}">${fmt(f.n_formations)} établissements →</button>` : '<span class="muted small">pas de correspondance formation par formation</span>'}</td></tr>`).join("")}
  </table></div>
  <p class="muted small">Taux de proposition : parmi les candidats ayant votre doublette et au moins un vœu dans cette filière (toute la France, 2022–2025), part ayant reçu au moins une proposition. Pas des chances d'admission.</p>
  ${kept.length > 15 ? `<button id="allf">${all ? "Réduire" : `Afficher les ${kept.length} filières`}</button>` : ""}`;
}

function stage1SeriesMatrix(s1, show, all) {
  const kept = s1.filieres.filter((f) => show.has(f.gate));
  const rows = all ? kept : kept.slice(0, 15);
  const max = Math.max(0.01, ...rows.map((f) => f.destination_share || 0));
  const sl = SERIE_SHORT[s1.serie];
  return `<div class="legend">${Object.entries(GATES).map(([k, g]) => `<label style="cursor:pointer"><input type="checkbox" data-gate="${k}" ${show.has(k) ? "checked" : ""}> <i style="background:${g.color}"></i>${g.label} (${s1.filieres.filter((f) => f.gate === k).length})</label>`).join("")}</div>
  <div class="scroll"><table><tr><th>Filière</th><th>Où vont les ${sl} admis</th><th class="num">Part des ${sl} parmi les admis</th><th class="num">Indice</th><th class="num">Accès estimé ${sl} (médiane) ${tip("serie_offer")}</th><th></th></tr>
  ${rows.map((f) => `<tr><td><span class="badge gbadge" style="--zc:${GATES[f.gate].color}">${GATES[f.gate].label}</span><br>${esc(f.label)}<div class="muted small">${fmt(f.accepted)} ${sl} admis · ${f.years} an(s)</div></td>
    <td style="min-width:130px"><svg viewBox="0 0 100 10" preserveAspectRatio="none" style="width:100%;height:10px;display:block"><rect width="${100 * (f.destination_share || 0) / max}" height="10" fill="${GATES[f.gate].color}"/></svg><span class="small">${pc1(f.destination_share)}</span></td>
    <td class="num">${pc1(f.share)}</td><td class="num">×${fmt(f.lift, 2)}</td><td class="num"><strong>${f.access_median != null ? `${fmt(f.access_median)} %` : "—"}</strong></td>
    <td>${f.gate === "atypique" || f.gate === "insuffisant" ? "" : f.n_formations ? `<button data-type="${esc(f.type_key)}" data-label="${esc(f.label)}">${fmt(f.n_formations)} établissements →</button>` : ""}</td></tr>`).join("")}
  </table></div>
  ${kept.length > 15 ? `<button id="allf">${all ? "Réduire" : `Afficher les ${kept.length} filières`}</button>` : ""}`;
}

// A3 / B4: position among admits of the student's series when it can be bounded, else all néo-bacheliers
const SERIE_SHORT = { bg: "bacs généraux", bt: "bacs technos", bp: "bacs pros" };
const pos = (f) => (f.spos ? f.spos.cdf_used : f.cdf);
// rows of "Mon parcours" that get a "Voir un plan B" button: a plan B is only proposed when the
// target is not already a safe choice, and is most useful for the selective ones
const PLANB_ZONES = ["ambitieux", "hors_profil"];
function bgCell(f) {
  if (!f.spos) {
    return `${pc1(f.cdf)}<div class="muted small">tous bacs · [${pc1(f.cdf_ci[0])} ; ${pc1(f.cdf_ci[1])}] · n=${fmt(f.n_known)}</div>`;
  }
  const b = f.spos, exact = b.width < 0.005;
  return `<strong>${exact ? pc1(b.bounds[0]) : `${pc1(b.bounds[0])} – ${pc1(b.bounds[1])}`}</strong>
    <div class="muted small" title="${exact ? "Valeur exacte" : "Encadrement exact : toute répartition compatible avec les chiffres publiés tombe dans cet intervalle"} ; marge d'échantillonnage ${pc1(b.ci[0])} – ${pc1(b.ci[1])}${Math.abs((f.cdf ?? 0) - b.cdf_used) >= 0.005 ? ` ; tous bacs confondus : ${pc1(f.cdf)}` : ""}">marge ${fmt(100 * b.ci[0], 0)}–${fmt(100 * b.ci[1], 0)} % · ${fmt(b.n)} ${{ bg: "bac G", bt: "bac techno", bp: "bac pro" }[f.serie || "bg"]}</div>`;
}

function scatter(F, onPick) {
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
  g += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">${se === "bg" ? "Taux d'accès officiel (phase principale, %)" : `Accès estimé pour les ${SERIE_SHORT[se]} (%)`}</text>`;
  g += `<text transform="translate(12 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Part des ${SERIE_SHORT[se]} admis avec votre mention ou moins</text>`;
  F.forEach((f, i) => {
    if (f.taux_acces_ens == null || pos(f) == null) return;
    // R4 (review): the three zones are filled shapes (paler when uncertain or under 10 admits), every other reading an empty ring
    const c = ZONES[f.zone].color, filled = ZONE_FILLED.includes(f.zone), weak = f.uncertain || f.small_cohort;
    if (f.spos && f.spos.width >= 0.01) g += `<line x1="${x(f.taux_acces_ens)}" x2="${x(f.taux_acces_ens)}" y1="${y(f.spos.bounds[0])}" y2="${y(f.spos.bounds[1])}" stroke="${c}" stroke-width="2" opacity=".55"/>`;
    g += zoneShape(f.zone, x(f.taux_acces_ens), y(pos(f)), f.home_academie ? 6 : 4.5, `data-i="${i}" fill="${filled ? c : "var(--surface)"}"${filled && weak ? ' fill-opacity=".35"' : ""} stroke="${c}" stroke-width="${filled ? (f.home_academie ? 3 : 1.5) : 2}" style="cursor:pointer"`).replace(/\/>$/, () => `><title>${esc(f.etablissement)} — ${esc(f.filiere)}\nTaux d'accès ${fmt(f.taux_acces_ens)} % · avec votre mention ou moins ${f.spos ? `${pc1(f.spos.bounds[0])}–${pc1(f.spos.bounds[1])} des ${SERIE_SHORT[f.serie || "bg"]}` : `${pc1(f.cdf)} (tous bacs)`}\n${ZONES[f.zone].label}${f.uncertain ? " (incertain)" : ""}${f.small_cohort ? " · moins de 10 admis bac général" : ""}</title></${f.zone === "cible" ? "rect" : f.zone === "ambitieux" ? "path" : "circle"}>`);
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
  const s2 = s1 && drill ? await api(`/api/journey/stage2?${sq}&mention=${p.mention}&type=${encodeURIComponent(drill.type)}&academie=${encodeURIComponent(p.academie || "")}`) : null;
  if ($view.dataset.rendered !== mk) return;
  // sprint 10: the positioning answers are served by the CDN, so the page sends the audience count itself
  if (s1) track("journey", { stage: "stage1" });
  if (s2) track("journey", { stage: "stage2" });
  const W = voeux.get();
  const onlyHome = !!p.academie && store.get("onlyHome", false);   // never filter without an académie
  const F = s2 ? s2.formations.filter((f) => f.zone !== "non_ouvert" && (!onlyHome || f.home_academie)) : [];
  const closed = s2 ? s2.formations.filter((f) => f.zone === "non_ouvert").length : 0;
  const mLabel = JV.mentions.find((m) => m.code === p.mention)?.label;
  if (p.lycee) { try { await loadLycees(); } catch (_) { /* the card says the lycée is unavailable */ } }
  if ($view.dataset.rendered !== mk) return;
  $view.dataset.rendered = "parcours";
  $view.innerHTML = `<div class="card"><h1>Où je me situe</h1><p class="small">Les filières qui recrutent votre profil, puis chaque formation située parmi ses admis des années passées. Des repères, pas des chances d'admission.</p></div>
  <div class="card"><h2>1 · Mon profil</h2>${hasProfile ? `<p class="home-profile"><span>Lu pour : <strong>${profileLine(p, serie)}</strong></span><a class="btnlink" href="#/profil">Modifier mon profil</a></p>`
      : `<p class="home-profile"><span>Exemple avec un bac général Mathématiques + SES, mention assez bien : <strong>créez votre profil</strong> pour lire ces chiffres pour vous.</span><a class="btnlink" href="#/profil">Créer mon profil</a></p>`}${mathsExpertesNote(p, serie)}
    ${!s1 ? `<div class="warn">Vos deux spécialités sont identiques : <a href="#/profil">choisissez deux spécialités distinctes dans « Mon profil »</a>.</div>` : serie === "bg"
      ? `<p class="small muted">Doublette ${esc(s1.doublette.replace("+", " + "))} : ${fmt(s1.national.candidates)} candidats bacheliers généraux sur ${s1.national.years} campagnes, ${pc1(s1.national.national_share)} des admis, taux de proposition toutes filières confondues ${pc1(s1.national.offer_rate)}.</p>`
      : `<p class="small muted">${fmt(s1.national.accepted)} ${SERIE_SHORT[serie]} admis sur ${s1.national.years} campagnes, ${pc1(s1.national.national_share)} des néo-bacheliers admis. SIES regroupe toutes les séries ${serie === "bt" ? "technologiques (STMG, STI2D, ST2S…)" : "et spécialités du bac professionnel"} : le site ne peut pas les distinguer. ${tip("serie_offer")}</p>
        <p class="small">Une part faible veut dire « rare », pas « fermé ». Votre ligne publiée dans le rapport du jury de chaque formation s'affiche sur sa fiche et dans « Mes vœux »${p.voie ? "" : ` : indiquez votre ${serie === "bt" ? "série et vos spécialités" : "spécialité de bac pro"} dans <a href="#/profil">« Mon profil »</a>`}.${serie === "bp" ? ` Beaucoup de BTS se préparent aussi en apprentissage : <a href="#/carte/${encodeURIComponent("BTS - BTSA - BTSM")}">voir les offres sur la carte</a> (filtre « Apprentissage »).` : ""}</p>`}</div>
  ${lyceeCard(p)}
  ${s1 ? `<div class="card"><h2>2 · Filières qui recrutent ${serie === "bg" ? "votre doublette" : `les ${SERIE_SHORT[serie]}`} ${tip(serie === "bg" ? "journey_stage1" : "serie_offer")} ${tip("journey_gate")}</h2>${serie === "bg" ? stage1Matrix(s1, show, allF) : stage1SeriesMatrix(s1, show, allF)}</div>` : ""}
  ${s2 ? `<div class="card" id="stage3"><h2>3 · Positionnement : ${esc(drill.label)} ${tip("journey_cdf")} ${tip("journey_zones")}</h2>
    <p class="small muted">Mention visée : ${esc(mLabel)}. ${fmt(F.length)} formations en ${s2.session}, profils cumulés sur 2022–2025. Chaque point est placé parmi les ${SERIE_SHORT[serie]} admis ; le trait vertical montre l'encadrement exact quand les données ne permettent pas d'être plus précis. Les formes pâles sont incertaines (intervalle à 95 %) ou ont moins de 10 ${SERIE_SHORT[serie]} admis ; un anneau vide est hors des trois zones${serie !== "bg" ? " ; l'axe horizontal est l'accès estimé pour votre série, pas le taux d'accès officiel" : ""}${p.academie ? " ; les cercles épais sont dans votre académie" : ""}. Cliquez sur un point pour l'ajouter à « Mes vœux ».${closed ? ` ${closed} formation(s) fermées à votre série par leurs groupes d'appel${serie === "bg" ? " ou parce que les bacheliers généraux y représentent moins de 5 % des admis 2022–2025 (ex. CPGE ECT)" : ""} sont exclues.` : ""}</p>
    <div class="toolbar">${p.academie ? `<label><input type="checkbox" id="oh" ${onlyHome ? "checked" : ""}> Seulement l'académie de ${esc(p.academie)}</label>` : ""}<a href="#/carte/t/${encodeURIComponent(drill.type)}">Voir ces formations sur la carte →</a></div>
    <div class="legend">${Object.entries(ZONES).map(([k, z]) => `<span style="color:${z.color}">${zoneMark(k)}<span class="lg-text">${z.label} (${F.filter((f) => f.zone === k).length})</span></span>`).join("")}</div>
    ${repereNote(s2.calibration)}
    ${scatter(F, (f) => pin(f))}
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th>Zone</th><th class="num">${serie === "bg" ? "Taux d'accès" : `Accès estimé ${SERIE_SHORT[serie]} ${tip("serie_offer")}`}</th><th class="num">${serie === "bg" ? "Bacs généraux" : serie === "bt" ? "Bacs technos" : "Bacs pros"} admis avec votre mention ou moins ${tip("journey_bg")}</th><th class="num">Mention exacte</th><th class="num">${serie === "bg" ? "Bac général" : `Part ${SERIE_SHORT[serie]}`}</th><th class="num">${p.boursier ? "<strong>Boursiers</strong>" : "Boursiers"}</th><th>Votre groupe d'appel ${tip("journey_groups")}</th>${s2.calibration ? `<th>Repère ${esc(s2.calibration.target)} ${tip("repere")}</th>` : ""}<th>Évolution</th><th></th></tr>
    ${F.slice().sort((a, b) => (pos(b) ?? -1) - (pos(a) ?? -1)).slice(0, allPos ? 80 : 20).map((f) => `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.filiere)} · ${esc(f.ville)}${f.home_academie ? ' · <span class="badge exact">votre académie</span>' : ""}${p.lycee && f.cod_uai === p.lycee.uai ? ` · <span class="badge exact">dans votre lycée${f.pct_etab_orig != null ? ` · ${fmt(f.pct_etab_orig)} % des admis en venaient` : ""}</span>` : ""}${f.non_selective && f.home_academie ? ` · ${fmt(f.pct_aca_orig)} % d'admis de l'académie` : ""}</div>${offerBadges(f, true)}</td>
      <td data-label="Zone">${zoneBadge(f.zone, f.uncertain)}${f.small_cohort ? ` <span class="badge warnb">n&lt;10 ${serie === "bg" ? "bac G" : serie === "bt" ? "bac techno" : "bac pro"}</span>` : ""}${f.rate_fragile ? ' <span class="badge warnb" title="Moins de 20 candidats de votre série : taux fragile">peu de candidats</span>' : ""}${f.rare_for_serie ? ` <span class="badge warnb" title="Moins de 5 % des admis 2022–2025 viennent de votre série">rare pour les ${SERIE_SHORT[serie]}</span>` : ""}${f.limited_comparability && !f.spos ? ' <span class="badge warnb" title="Moins de 50 % de bacheliers généraux parmi les admis : la distribution des mentions mêle surtout d\'autres séries">comparabilité limitée</span>' : ""}</td>
      <td class="num" data-label="${serie === "bg" ? "Taux d'accès" : "Accès estimé"}">${f.taux_acces_ens != null ? `${fmt(f.taux_acces_ens)} %` : "—"}${serie !== "bg" ? `<div class="muted small" title="Estimation. Taux de proposition des candidats de votre série : ${f.serie_proposal_rate != null ? `${fmt(f.serie_proposal_rate)} %` : "—"} ; taux d'accès officiel (tous candidats) : ${fmt(f.taux_acces_all)} %">estim. · tous ${fmt(f.taux_acces_all)} %</div>` : ""}</td><td class="num" data-label="Admis avec votre mention ou moins">${bgCell(f)}</td>
      <td class="num" data-label="Mention exacte">${pc1(f.exact_share)}</td><td class="num" data-label="${serie === "bg" ? "Bac général" : "Part de votre série"}">${pc1(serie === "bg" ? f.pct_bg : f.pct_serie)}</td><td class="num" data-label="Boursiers">${pc1(f.pct_boursiers)}</td>
      <td class="small" data-label="Groupe d'appel">${f.group && !f.group.ambiguous ? `${esc(f.group.label)}<div class="muted">dernier appelé : rang ${fmt(f.group.last_called_rank)}</div>` : '<span class="muted">non déterminé</span>'}</td>
      ${s2.calibration ? `<td class="small" data-label="Repère">${repereCell(f, serie)}</td>` : ""}
      <td data-label="Évolution">${spark(f.trend, "cdf")}${spark(f.trend, "taux_acces_ens", 100)}</td>
      <td class="acts"><button data-pin="${esc(f.cod_aff_form)}" class="small">${W.includes(f.cod_aff_form) ? "dans mes vœux" : "ajouter à mes vœux"}</button>${PLANB_ZONES.includes(f.zone) ? `<button type="button" data-planb="${esc(f.cod_aff_form)}" class="small planb-btn" aria-expanded="false">Voir un plan B</button>` : ""}</td></tr>`).join("")}
    </table></div>${F.length > 20 ? `<p><button type="button" id="allpos">${allPos ? "Afficher les 20 premières" : `Afficher ${F.length > 80 ? "les 80 premières" : `les ${fmt(F.length)}`} formations`}</button></p>` : ""}
    ${F.length > (allPos ? 80 : 20) ? `<p class="muted small">${allPos ? 80 : 20} premières formations affichées (toutes figurent sur la matrice).</p>` : ""}
    ${p.boursier ? `<p class="small muted">Boursier : la part de boursiers parmi les admis est affichée à titre d'information. Les taux minimaux de boursiers fixés par les recteurs ne sont pas publiés formation par formation dans ces données ; aucun ajustement n'est appliqué.</p>` : ""}</div>` : ""}
  <div class="card"><h2>4 · Mes vœux</h2><p id="wishlist">${W.length ? `${fmt(W.length)} vœu(x) dans votre liste.` : "Votre liste est vide : ajoutez des formations depuis le tableau ou un plan B."} <a href="#/voeux">Voir la lecture de ma liste pour ce profil →</a></p>
    <p class="muted small">La liste est relue pour votre profil actuel à chaque visite (${voeux.MAX} vœux au maximum sur Parcoursup).</p></div>${feedbackBox("parcours")}`;

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
      : `<li><strong>Fiche d'une formation</strong>votre zone et votre ${serie === "bg" ? "doublette" : "ligne"} dans le rapport du jury, à côté du taux officiel</li>
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
        <li>Une liste partagée avec un adulte n'inclut votre profil que si vous cochez la case prévue (jamais votre académie ni votre lycée).</li>
      </ul>
      ${has ? (confirmErase ? `<p class="toolbar"><span class="small">Effacer votre profil de ce navigateur ? Votre liste de vœux est gardée.</span><button type="button" id="pf-erase-yes">Oui, effacer</button><button type="button" id="pf-erase-no">Annuler</button></p>`
        : `<p><button type="button" id="pf-erase">Effacer mon profil</button></p>`) : ""}</div>
    </div>`;
    $view.dataset.rendered = "profil";
    bind(p, serie, has, raw);
    if (focusName) { const el = document.querySelector(`#pf [name="${focusName}"]${focusName === "statut" ? ":checked" : ""}`); if (el) el.focus(); }
  };
  const bind = (p, serie, has, raw) => {
    const form = document.getElementById("pf");
    // the lycée picked or removed goes through the same submit: edits made in the form before picking it are kept
    let lyc = p.lycee || null;
    form.onchange = (e) => {
      const name = e.target.name || "";
      if (!name || name === "lyc-q") return;
      if (name === "statut") return setSituation(e.target.value, has, raw, new FormData(form), p, serie, lyc, form);
      if (has) { form.requestSubmit(); return; }
      draft = { ...(draft || {}), ...readForm(new FormData(form), p, serie, lyc, form, null) }; draw(name);   // no profile yet: nothing stored before "Enregistrer"
    };
    form.onsubmit = (e) => {
      e.preventDefault();
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
    if (ey) ey.onclick = () => { confirmErase = false; justSaved = false; store.set("profile", null); store.set("drill", null); draw(); };
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
    serie: fd.get("serie") || "bg", spe1: fd.get("spe1") || p.spe1 || "MATHS",
    spe2: fd.get("spe2") ? spe2Of(fd.get("spe1") || p.spe1 || "MATHS", fd.get("spe2"), p.spe1) : (p.spe2 || "SES"),   // distinct before it is saved
    mention: fd.get("mention") || p.mention, academie: fd.get("academie") || "", boursier: !!fd.get("boursier"),
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
    document.getElementById("gl-list").innerHTML = hits.length ? hits.map((g) => `<div class="gl-item" id="g-${esc(g.key)}"><h3>${esc(g.terme)}</h3><p>${esc(g.definition)}</p>${g.methode && META.methodology[g.methode] ? `<details><summary class="small">Méthode détaillée</summary><p class="small muted">${esc(META.methodology[g.methode])}</p></details>` : ""}</div>`).join("")
      : `<p class="muted">Aucun terme ne correspond.</p>`;
  };
  $view.innerHTML = `<div class="card"><h2>Glossaire</h2>
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
function vxVoieCell(v, prof) {
  const r = v.rapport;
  return `<td class="num" data-label="Votre ligne, rapport du jury">${v.status !== "ok" ? "—" : r ? `${pct1(r.taux)}<div class="estim">${fmt(r.en_position)} sur ${fmt(r.confirmes)} · rapport public ${esc(r.session)} de la formation${r.source === "autres" ? `, ligne « ${esc(r.libelle)} »` : ""}${r.recoupe === false ? `, pas encore recoupé avec les chiffres de ${esc(r.session)}` : ""}</div>` : prof.voie ? '<span class="muted small">pas de ligne publiée</span>' : '<a class="small" href="#/profil">indiquez votre série</a>'}</td>`;
}
function voeuButton(cod) {
  const inV = voeux.has(cod), full = !inV && voeux.get().length >= voeux.MAX;
  return `<button type="button" data-voeu="${esc(cod)}" ${full ? `disabled title="${voeux.MAX} vœux au maximum sur Parcoursup"` : ""}>${inV ? "Retirer de mes vœux" : full ? "Mes vœux : liste pleine" : "Ajouter à mes vœux"}</button>`;
}
function bindVoeuButton(after) {
  $view.querySelectorAll("[data-voeu]").forEach((el) => {
    el.onclick = () => { voeux.has(el.dataset.voeu) ? voeux.remove(el.dataset.voeu) : voeux.add(el.dataset.voeu); after(); };
  });
}
// messages: one fixed rule each, read from the server's counts (voeux.read_list); never a combined chance
const VX_MSG = {
  aucune_securite: "Aucun vœu de sécurité sûr dans votre liste : ajoutez au moins une formation où la cohorte admise ressemble à votre profil et où le taux d'accès est élevé. La carte « Compléter ma liste » ci-dessous en propose dans les filières de vos vœux.",
  majorite_ambitieuse: "Plus de la moitié des vœux situés sont ambitieux ou hors-profil.",
  hors_profil: "Au moins un vœu est hors-profil : moins de 2 % des admis 2022–2025 avaient votre mention ou moins.",
  non_ouvert: "Au moins un vœu n'est pas ouvert à votre série (groupes d'appel, ou presque aucun admis de votre série) : vérifiez la fiche Parcoursup.",
  non_situe: "Certains vœux ne peuvent pas être situés pour votre profil (trop peu de candidats de votre série, formation non rattachée à une filière, ou absente de la dernière campagne).",
  aucune_cible: "Aucun vœu cible pour l'instant.",
  equilibree: "Votre liste combine des vœux de sécurité et des vœux cibles ou ambitieux.",
};
const VX_PLANB = ["ambitieux", "hors_profil", "cible"];
async function viewVoeux() {
  const ids = voeux.get();
  const p = store.get("profile", { spe1: "MATHS", spe2: "SES", mention: "ab", academie: "", boursier: false });
  const prof = vxProfile(p);                                             // stored profile: never trusted
  if (isReo(prof)) return viewVoeuxReo(ids, prof);                      // sprint 21: no zone, no Plan B, no "Compléter"
  const { serie, mention } = prof;
  const who = `${{ bg: "bac général", bt: "bac technologique", bp: "bac professionnel" }[serie]}${serie === "bg" ? ` ${esc(p.spe1 || "MATHS")} + ${esc(p.spe2 || "SES")}` : prof.voie_label ? `, ${esc(prof.voie_label)}` : ""}, mention ${{ sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien" }[mention]}${p.academie ? `, académie de ${esc(p.academie)}` : ""}`;
  const head = `<div class="card"><h1>Mes vœux ${tip("mes_voeux")}</h1>
    <p class="small">Lue pour votre profil actuel : ${who}. <a href="#/profil">Modifier dans « Mon profil »</a></p><p class="print-only small">Liste lue sur SupCompass le ${esc(frDate(localIso()))}. Chiffres officiels Parcoursup 2022–2025 : des parts d'admis, pas des chances d'admission.</p></div>`;
  const howto = `<p class="muted small">Ajoutez des formations depuis leur fiche, « Où je me situe » ou un plan B (${voeux.MAX} vœux au maximum sur Parcoursup, hors sous-vœux). Sur Parcoursup, les vœux ne sont pas classés : l'ordre de votre liste ne compte pas.</p>`;
  if (!ids.length) {
    $view.innerHTML = `${head}<div class="card"><p class="muted">Votre liste est vide.</p>${howto}</div>`;
    $view.dataset.rendered = "voeux:0";
    return;
  }
  const qs = vxQuery(ids, prof);                                        // the profile bar sends the same query
  const marker = `voeux:${qs}`;
  $view.dataset.rendered = marker;
  $view.innerHTML = `${head}<div class="card"><p class="muted small">Lecture de votre liste…</p></div>`;
  let d;
  try { d = await api(`/api/voeux?${qs}`); } catch (e) {
    if ($view.dataset.rendered === marker) $view.innerHTML = `${head}<div class="warn">${esc(e.message)}</div>`;
    return;
  }
  if ($view.dataset.rendered !== marker) return;                       // the user navigated meanwhile
  const L = d.lecture, z = L.zones;
  const rate = serie === "bg" ? "Taux d'accès" : "Accès estimé pour votre série";
  const rows = d.voeux.map((v) => {
    const name = v.status === "absente" ? `<span class="muted">Formation ${esc(v.cod_aff_form)} absente de la campagne ${d.session}</span>`
      : `<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a><div class="muted small">${esc(v.filiere)}${v.complement ? ` · ${esc(v.complement)}` : ""} · ${esc(v.ville)}${v.academie ? ` (${esc(v.academie)})` : ""}${v.home_academie ? ' · <span class="badge exact">votre académie</span>' : ""}</div>`;
    const flags = v.status !== "ok" ? "" : `${v.rate_fragile ? ' <span class="badge warnb">peu de candidats de votre série</span>' : ""}${v.rare_for_serie ? ` <span class="badge warnb">rare pour les ${SERIE_SHORT[serie]}</span>` : ""}${v.small_cohort ? ' <span class="badge warnb">n&lt;10</span>' : ""}${autresBadge(v)}`;
    const position = v.bounds ? (v.bounds[1] - v.bounds[0] < 0.005 ? pc1(v.bounds[0]) : `${pc1(v.bounds[0])} – ${pc1(v.bounds[1])}`) : pc1(v.position);
    return `<tr><td>${name}</td><td data-label="Zone">${zoneBadge(v.zone, v.uncertain)}${flags}</td>
      <td class="num" data-label="${rate}">${v.status === "ok" ? `${fmt(v.taux_acces_ens)} %` : "—"}</td>
      <td class="num" data-label="Votre mention ou moins">${v.status === "ok" ? position : "—"}</td>
      <td class="num" data-label="Places">${v.capa_fin != null ? fmt(v.capa_fin) : "—"}</td>
      ${serie === "bg" ? `<td class="num" data-label="Votre doublette, cette formation">${v.rapport ? `${pct1(v.rapport.taux)}<div class="estim">rapport public ${esc(v.rapport.session)} de la formation${v.rapport.source === "autres" ? ", Autres doublettes" : ""}${v.rapport.recoupe === false ? `, pas encore recoupé avec les chiffres de ${esc(v.rapport.session)}` : ""}</div>` : v.semblable ? `${pct1(v.semblable.taux)}<div class="estim">estimation · ${fmt(v.semblable.n_rapports)} rapports de formations semblables</div>` : v.doublette ? (v.doublette.formation ? `${pct1(v.doublette.formation.taux)}<div class="estim">estimation · groupe national ${pct1(v.doublette.taux)}${v.doublette.source === "autres" ? " (Autres doublettes)" : ""}</div>` : `${pct1(v.doublette.taux)}<div class="estim">groupe national${v.doublette.source === "autres" ? ", Autres doublettes" : ""}</div>`) : "—"}</td>` : vxVoieCell(v, prof)}
      <td class="acts">${v.status === "ok" && VX_PLANB.includes(v.zone) ? `<button type="button" class="small planb-btn" data-vxplanb="${esc(v.cod_aff_form)}" aria-expanded="false">Voir un plan B</button>` : ""}<button type="button" class="small" data-vxdel="${esc(v.cod_aff_form)}">retirer</button></td></tr>`;
  }).join("");
  $view.innerHTML = `${head}
  <section class="card summary" aria-label="Lecture de votre liste"><h2>Lecture de votre liste</h2>
    ${zoneTiles(z, z.hors_profil + z.non_ouvert + z.indetermine + z.non_situe)}
    ${L.messages.map((m) => `<div class="${m.niveau === "warn" ? "warn" : "info"}">${esc(VX_MSG[m.code] || "")}</div>`).join("")}
    <p class="muted small">Ces repères comptent les zones de votre liste, une par vœu. Ils ne disent pas vos chances d'être admis quelque part : les zones décrivent les admis des campagnes passées, et vos vœux ne se combinent pas en une probabilité.</p></section>
  <div class="card"><h2>Mes ${fmt(d.voeux.length)} vœux</h2>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th>Zone pour votre profil</th><th class="num">${rate} ${d.session}</th><th class="num">Votre mention ou moins parmi les admis</th><th class="num">Places ${d.session}</th>${serie === "bg" ? '<th class="num">Taux de proposition de votre doublette (cette formation, estimation)</th>' : '<th class="num">Votre ligne dans le rapport du jury (cette formation)</th>'}<th></th></tr>
    ${rows}</table></div>
    <p class="muted small">Parts d'admis des campagnes 2022–2025, pas des chances d'admission. ${serie === "bg" ? "Taux d'accès officiel de la dernière campagne." : "Accès estimé pour votre série (taux d'accès officiel × taux de proposition de votre série / taux de proposition de tous), pas un taux officiel."} Vérifiez chaque fiche Parcoursup.${serie === "bg" ? " Votre doublette : le rapport public de la formation quand il la détaille ; sinon une estimation (son taux des bacheliers généraux × l'écart de votre doublette dans les rapports des formations semblables, ou à défaut dans son groupe au niveau national)." : " Votre ligne : la part des candidats de votre série et spécialités (ou de votre spécialité de bac pro) ayant confirmé ce vœu qui ont été en position de recevoir une proposition, d'après le rapport public de la formation ; seuls les candidats scolarisés en terminale en France y figurent."}</p>
    <p class="muted small">Votre liste reste dans ce navigateur. Pour la lire, la page envoie les codes des formations et votre profil, comme « Où je me situe » ; rien n'en est enregistré sur le serveur. Le site compte seulement, sans savoir de quelle formation il s'agit, qu'un vœu a été ajouté (mesure d'audience anonyme, désactivée si votre navigateur demande de ne pas être suivi).</p>${howto}</div>${shareCard(ids, !!store.get("profile", null))}${feedbackBox("voeux")}`;
  if (L.messages.some((m) => m.code === "aucune_securite")) {
    $view.insertAdjacentHTML("beforeend", '<section class="card" id="vx-completer" aria-live="polite"><p class="muted small">Recherche de vœux de sécurité dans les filières de votre liste…</p></section>');
    loadCompleter(qs, marker, rate, false);
  }
  $view.querySelectorAll("[data-vxdel]").forEach((el) => { el.onclick = () => { voeux.remove(el.dataset.vxdel); viewVoeux(); }; });
  bindShare(ids, store.get("profile", null) ? prof : null);             // sprint 22: never a default profile (review)
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

// "Compléter ma liste" (owner, 2026-11-10): with no sure safety in the list, safety vœux of the same filières, read by the
// server with Plan B's rules (same programme, a solid reading, 2 per establishment, académie then distance, paid private
// institutions only on request and flagged). Zones of past admitted cohorts: never a chance.
let vxCompleterSeq = 0;
async function loadCompleter(qs, marker, rate, paid) {
  const box = () => document.getElementById("vx-completer");
  // Codex (PR #44): the paid toggle can fire twice before the first answer; only the LATEST request may draw the card
  const req = String(++vxCompleterSeq);
  if (box()) box().dataset.req = req;
  const current = () => $view.dataset.rendered === marker && box() && box().dataset.req === req;
  const q = new URLSearchParams(qs);
  q.set("paid", paid ? "1" : "0");
  let d;
  try { d = await api(`/api/voeux/completer?${q}`); } catch (e) {
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
      return `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${f.complement ? `${esc(f.complement)} · ` : ""}${esc(f.ville)}${f.academie ? ` (${esc(f.academie)})` : ""}${f.paid ? ' · <span class="badge warnb">privé payant</span>' : ""}</div></td>
        <td data-label="Zone"><span class="badge" style="border-color:${ZONES.securite.color};color:${ZONES.securite.color}">${ZONES.securite.label}</span></td>
        <td class="num" data-label="${rate}">${fmt(f.taux_acces_ens)} %</td>
        <td class="num" data-label="Votre mention ou moins">${pos}</td>
        <td class="num" data-label="Distance au plus proche de vos vœux">${f.km != null ? `${fmt(f.km)} km` : "—"}</td>
        <td class="acts"><button type="button" class="small" data-vxadd="${esc(f.cod_aff_form)}"${full ? " disabled" : ""}>ajouter à mes vœux</button></td></tr>`;
    }).join("");
    return `<h3>${title}</h3><div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th>Zone pour votre profil</th><th class="num">${rate} ${d.session}</th><th class="num">Votre mention ou moins parmi les admis</th><th class="num">Distance</th><th></th></tr>${rows}</table></div>`;
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
  if (cb) cb.onchange = () => loadCompleter(qs, marker, rate, cb.checked);
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
      : `<div class="scroll"><table><tr><th>Formation ${d.session}</th><th class="num">Taux d'accès</th><th class="num">Places</th><th></th></tr>
        ${shown.map((f) => `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a>${f.cod_aff_form === from ? ' <span class="badge exact">la formation que vous regardiez</span>' : ""}<div class="muted small">${esc(f.filiere)}${f.complement ? ` · ${esc(f.complement)}` : ""} · ${esc(f.ville)}${f.academie ? ` (${esc(f.academie)})` : ""}</div></td>
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
  const word = { debutants_insuffisants: "Recrute au-delà des débutants", debutants_nombreux: "Entrée plus disputée", incertain: "Pas de conclusion" };
  // fixed rule (sprint 16): every family read agrees, else no conclusion
  const r2030 = !read.length ? null : read.every((x) => x === read[0]) ? word[read[0]] : word.incertain;
  const n2030 = !read.length ? "pas de projection pour ce métier" : read.every((x) => x === read[0]) ? "projection Dares, sous hypothèses"
    : "les familles du métier ne concordent pas";
  const iaSpan = d.ia && d.ia.min != null ? (d.ia.min === d.ia.max ? fmt2(d.ia.min) : `${fmt2(d.ia.min)} à ${fmt2(d.ia.max)}`) : null;
  const tile = (tab, label, value, note) => `<button type="button" class="sum-tile" data-goto="${tab}"><span class="sum-label">${label}</span><span class="sum-value">${value}</span><span class="sum-note">${note}</span></button>`;
  const summary = `<section class="card summary" aria-label="L'essentiel en 30 secondes"><h2>L'essentiel</h2><div class="sum-grid">
      ${tile("formations", "Niveau minimum", d.niveau_acces_min ? esc(d.niveau_acces_min) : "—", "d'après l'Onisep")}
      ${tile("formations", "Diplômes", fmt(d.diplomes.length), nForm ? `${fmt(nForm)} formation(s) Parcoursup` : "aucune formation Parcoursup")}
      ${tile("avenir", "Emploi d'ici 2030", r2030 ? `<span class="text">${esc(r2030)}</span>` : "—", n2030)}
      ${tile("avenir", "Tâches exposées à l'IA", iaSpan || "—", iaSpan ? "note OIT sur 1, pas un risque de perte d'emploi" : "pas de note OIT")}
    </div></section>`;
  $view.innerHTML = `<div class="card"><p class="small"><a href="#/metiers">← Autres métiers</a></p>
    <h1>${esc(d.nom)}</h1>
    <p class="small">${d.niveau_acces_min ? `Niveau d'études minimum (Onisep) : ${esc(d.niveau_acces_min)} · ` : ""}<a href="${esc(d.url)}" target="_blank" rel="noopener">Fiche métier Onisep ↗</a></p>
    </div>
    ${summary}${tabbed("metier", [
      ["formations", "Diplômes et formations", `${status}
    ${home ? `<label class="small"><input type="checkbox" id="mhome" ${onlyHome ? "checked" : ""}> Mon académie seulement (${esc(home)})</label>` : ""}
    <p class="muted small">Liste nationale : un établissement figure parce qu'il prépare le diplôme, pas parce que ses étudiants exercent ce métier. Ce n'est pas une promesse d'emploi. Les formations sont rangées par académie et par ville, pas par chances d'admission.</p>
    ${d.diplomes.map(dip).join("")}
    <p class="muted small">Source : Onisep, Idéo (licence ODbL) ; formations Parcoursup ${d.session}.</p>`],
      ["avenir", "Avenir du métier", `${emploi2030Card(d.emploi2030)}${bmoCard(d.bmo)}${iaCard(d.ia)}${codesCard(d.codes)}`],
    ])}`;
  bindTabs("metier");
  const h = document.getElementById("mhome");
  if (h) h.onchange = () => { store.set("metierHome", h.checked); viewMetier(id, from); };
  bindVoeuButton(() => viewMetier(id, from));
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
      <td>${i.gradient ? esc(IA_GRADIENT[i.gradient] || i.gradient) : '<span class="muted">pas de note OIT</span>'}</td><td class="num">${score(i.score)}</td>
      <td class="num">${theta(i)}</td></tr>`).join("");
  const range = ia.min === null || ia.min === undefined ? ""
    : ia.min === ia.max ? `<p class="small">Note moyenne des tâches : ${score(ia.min)} sur 1.</p>`
    : `<p class="small">Selon le code ISCO, la note moyenne des tâches va de ${score(ia.min)} à ${score(ia.max)} sur 1.</p>`;
  const tagText = { Oui: "liée à la transition numérique", Non: "non liée à la transition numérique" };
  const tags = (ia.tags || []).length ? `<p class="small">France Travail : ${ia.tags.map((t) => `fiche ROME ${esc(t.rome)} ${t.transition_numerique ? esc(tagText[t.transition_numerique] || "") : "non renseignée pour la transition numérique"}`).join(" ; ")}.</p>` : "";
  return `<div class="card"><h2>L'IA générative et les tâches de ce métier</h2>
    <p class="muted small">L'OIT a noté chaque tâche des métiers de la classification internationale ISCO-08 selon la part que l'IA générative pourrait en faire. C'est un potentiel technique des tâches, pas une prévision de pertes d'emplois ni un risque pour vous : un métier exposé est plus souvent transformé que remplacé.</p>
    ${range}
    ${rows ? `<div class="scroll"><table><tr><th>ISCO-08</th><th>Groupe de base</th><th>Classement OIT</th><th class="num">Note moyenne des tâches</th><th class="num">Complémentarité humaine</th></tr>${rows}</table></div>` : ""}
    ${ia.theta_min === null || ia.theta_min === undefined ? "" : `<p class="small">Complémentarité humaine (méthode du FMI, estimation adaptée) : de ${score(ia.theta_min)} à ${score(ia.theta_max)} sur 1 selon le code et la profession américaine. Plus elle est haute, plus le métier a des traits qui font de l'IA un outil d'appui plutôt qu'un remplaçant (contact humain, responsabilité, conditions physiques, décisions lourdes, travail peu routinier, longue formation).</p>`}
    ${tags}
    <p class="muted small">Le classement de l'OIT tient compte de la note moyenne et de l'écart entre les tâches : deux notes proches peuvent avoir deux classements différents. Les codes ISCO viennent des intitulés de profession (voir les codes officiels plus bas) ; on ne fait pas la moyenne entre eux. La complémentarité humaine reprend la méthode du FMI (Pizzinelli et al., 2023) sur les données américaines O*NET 31.0 : c'est une estimation adaptée (fiabilité C), pas le score publié par le FMI ; elle passe par les tables officielles O*NET et BLS (O*NET-SOC 2019, SOC 2018, SOC 2010, ISCO-08). Elle n'est jamais combinée avec la note de l'OIT. Sources : OIT, Gmyrek, Berg et al. (2025), « Generative AI and Jobs: A Refined Global Index of Occupational Exposure », CC BY 4.0 ; France Travail, étiquettes des fiches ROME (octobre 2026) ; O*NET 31.0 (U.S. Department of Labor, CC BY 4.0) ; BLS, tables de passage SOC et ISCO-08.</p></div>`;
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
  return `<div class="card">${head}${codes.map(one).join("")}
    <p class="muted small">Sources : Onisep (codes ROME de la fiche métier) ; Dares (passages ROME → FAP-2021 et FAP-2009, intitulés de profession) ; Insee (codification ISCO-08 des intitulés) ; France Travail (appellations du ROME, pour les métiers sans code Onisep). Licence Ouverte.</p></div>`;
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
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Session</th><th class="num">Candidats</th><th class="num">Classés</th><th>Rang du dernier appelé</th><th class="num">Part des classés appelés</th><th class="num">Places</th></tr>
      ${ok.map((r) => `<tr><td data-label="Session">${esc(r.session)}</td><td class="num" data-label="Candidats">${fmt(r.candidats)}</td><td class="num" data-label="Classés">${fmt(r.classes)}</td>
        <td data-label="Rang du dernier appelé">${r.groupes.map((g) => `${esc(g.label || "Groupe")} : ${fmt(g.rang)}`).join("<br>")}</td>
        <td class="num" data-label="Part des classés appelés">${r.toute_la_liste ? "toute la liste" : pct(r.profondeur)}</td><td class="num" data-label="Places">${fmt(r.places)}</td></tr>`).join("")}</table></div>
    <p class="muted small">${APPEL_NOTE} Part des classés appelés : somme des rangs des derniers appelés de chaque groupe, divisée par le nombre de classés (calcul à partir des effectifs publiés). <a href="#/comprendre">Comprendre l'appel →</a></p></div>`;
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
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Type de diplôme</th><th class="num">Formations</th><th class="num">Part des classés appelés (médiane)</th><th class="num">Formations ayant appelé toute leur liste</th></tr>
      ${ts.map((t) => `<tr><td data-label="Type de diplôme">${esc(t.diplome)}</td><td class="num" data-label="Formations">${fmt(t.n)}</td>
        <td class="num" data-label="Part des classés appelés (médiane)">${pct(t.profondeur_mediane)}</td><td class="num" data-label="Formations ayant appelé toute leur liste">${pct(t.part_toute_la_liste)}</td></tr>`).join("")}</table></div>
    <p class="muted small">Médiane sur les formations du type, calculée à partir des effectifs publiés (rangs des derniers appelés et candidats classés). Types d'au moins 20 formations.</p></div>
  <div class="card"><h2>Quand arrivent les propositions ?</h2>
    ${bts && bts.calendrier[0] != null ? `<p class="info">Une liste qui bouge lentement les premiers jours est normale : dans la moitié des BTS, ${pct(bts.calendrier[0])} au plus des futurs admis avaient leur proposition dès l'ouverture ; ${pct(bts.calendrier[1])} l'avaient avant les résultats du bac.</p>` : ""}
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Type de diplôme</th><th class="num">Dès l'ouverture</th><th class="num">Avant les résultats du bac</th><th class="num">Avant la fin de la phase principale</th></tr>
      ${ts.map((t) => `<tr><td data-label="Type de diplôme">${esc(t.diplome)}</td>${t.calendrier.map((v, i) => `<td class="num" data-label="${["Dès l'ouverture", "Avant les résultats du bac", "Avant la fin de la phase principale"][i]}">${pct(v)}</td>`).join("")}</tr>`).join("")}</table></div>
    <p class="muted small">Part des admis qui avaient déjà reçu leur proposition à chaque étape, publiée pour chaque formation ; médiane sur les formations du type qui ont des admis.</p></div>`;
  $view.dataset.rendered = "comprendre";
}
// the selectivity matrix: official access rate x share of néo-bachelier admits with "Bien" or better; the quadrant lines
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
// formations of a campaign: nearly all have fewer than 10 néo-bachelier admits, so one person would move the share a lot)
function selWhy(f, d) {
  if (f.raison === "aucun_admis") return `aucun admis en ${esc(d.session)}`;
  if (f.raison === "peu_neobac") return `${fmt(f.admis_neobac)} admis néo-bachelier${f.admis_neobac > 1 ? "s" : ""} sur ${fmt(f.admis)} admis`;
  return f.raison === "sans_taux" ? "taux d'accès non publié" : "mentions des admis non publiées";
}
function selApart(d) {
  const n = d.non_placees.length;
  if (!n) return "";
  const parts = [["peu_neobac", `moins de ${fmt(d.min_admis)} admis néo-bacheliers`], ["aucun_admis", "aucun admis"], ["sans_taux", "taux d'accès non publié"], ["sans_mentions", "mentions non publiées"]]
    .filter(([k]) => d.raisons[k]).map(([k, t]) => `${fmt(d.raisons[k])} : ${t}`).join(" · ");
  const row = (f) => `<tr><td data-label="Formation"><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.formation)} · ${esc(f.ville)}</div><div class="small">Non placée : ${selWhy(f, d)}</div></td>
    <td class="num" data-label="Taux d'accès">${pct(f.taux_acces_ens)}</td><td class="num" data-label="Candidats par place">${fmt(f.candidats_par_place, 1)}</td></tr>`;
  return `<details class="card" id="sel-apart"><summary><strong>Non placées sur le graphique</strong> · ${fmt(n)} formation${n > 1 ? "s" : ""} <span class="muted small">(${parts})</span></summary>
    <p class="small">La part des mentions n'est publiée que pour les admis néo-bacheliers (les élèves qui viennent d'obtenir leur bac). Avec moins de ${fmt(d.min_admis)} néo-bacheliers admis, une seule personne déplace beaucoup ce chiffre : la formation n'est pas placée, mais son taux d'accès officiel reste indiqué ici. Les autres admis ne sont pas des néo-bacheliers (réorientation, reprise d'études…) ; leurs mentions ne sont pas publiées.</p>
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
    <p class="small">Un taux d'accès bas peut venir de nombreux candidats pour les places, ou d'admissions très exigeantes. Chaque formation est placée selon son <strong>taux d'accès officiel</strong> et la <strong>part de ses admis néo-bacheliers avec une mention Bien ou mieux</strong>.</p>
    <div class="carte-pick"><label class="small">Type de diplôme <select id="sdip">${FAC.diplomes.map((x) => `<option value="${esc(x.label)}" ${x.label === D.label ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>
    <label class="small">Mention <select id="smen"><option value="">Toutes les mentions</option>${D.mentions.map((m) => `<option value="${esc(m.label)}" ${m.label === mention ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label></div></div>
  <div class="card"><div class="scroll">${d.formations.length ? selPlot(d, null) : `<p class="muted">Aucune formation placée.</p>`}</div>
    <p class="muted small">Lignes pointillées : médianes de la sélection (taux d'accès ${pct(d.mediane_taux)}, mention Bien ou mieux ${pct(d.mediane_bien)}). Les quatre zones décrivent une position, pas une cause ni des chances d'admission. Données : SIES / MESR, session ${esc(d.session)}.</p></div>
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
const REO_NO_ZONE = "Le SIES ne publie ni mention ni série pour les candidats qui ne sont pas en terminale : aucune zone (sécurité, cible, ambitieux) ne peut être lue pour eux.";
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
  return `${pct1(b.acces_estime)}<div class="estim">estimation${b.plafonne ? ", plafonnée à 100 %" : ""} · ${fmt(b.propositions)} propositions pour ${fmt(b.candidats)} candidats hors terminale${b.propositions === 0 ? " : rare cette année-là, pas forcément fermé" : ""}</div>`;
}
// the formation page's folded card: the published counts, the estimate and its method (review: never a figure without them)
function reoCard(b) {
  if (!b) return "";
  return `<div class="card"><h2>Candidats qui ne sont plus en terminale · ${esc(b.session)}</h2>
    <p class="small">Réorientation, reprise d'études ou autre parcours : le SIES les compte ensemble, comme « autres candidats ».</p>
    <div class="small">${b.candidats != null ? `${fmt(b.propositions)} propositions pour ${fmt(b.candidats)} candidats hors terminale (${pct1(b.taux_proposition)}), contre ${pct1(b.taux_proposition_tous)} pour l'ensemble des candidats.` : "Effectifs publiés incohérents : pas de lecture pour cette campagne."}</div>
    <div class="small">Accès estimé hors terminale : ${reoCell(b)}</div>
    <p class="muted small">${REO_METHOD} ${REO_NO_ZONE}</p></div>`;
}
const reoAutres = (b) => (b && b.part_admis_autres != null ? `${pct1(b.part_admis_autres)}<div class="estim">${fmt(b.admis_autres)} sur ${fmt(b.admis)} admis</div>` : "—");
const REO_METHOD = "Accès estimé hors terminale = taux d'accès officiel × (part des candidats hors terminale qui ont reçu une proposition ÷ part de tous les candidats qui en ont reçu une), plafonné à 100 %. C'est une estimation à partir des effectifs publiés (phase principale et phase complémentaire), pas un taux officiel ni une chance d'admission.";
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
    const row = (f) => { const b = f.reorientation; return `<tr><td data-label="Formation"><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.formation)} · ${esc(f.ville)}${f.academie ? ` (${esc(f.academie)})` : ""}${f.payant ? ' · <span class="badge warnb">privé, frais de scolarité</span>' : ""}</div>${b ? autresBadge(b) : ""}</td>
      <td class="num" data-label="Accès estimé hors terminale">${reoCell(b)}</td>
      <td class="num" data-label="Taux d'accès officiel, tous candidats">${pct(b && b.taux_acces_ens)}</td>
      <td class="num" data-label="Admis hors néo-bacheliers">${reoAutres(b)}</td>
      <td class="acts" data-label="Mes vœux">${voeuButton(f.cod_aff_form)}</td></tr>`; };
    $view.innerHTML = `<div class="card"><h1>Je me réoriente ou je reprends mes études</h1>
      <p>Vous n'êtes plus en terminale : réorientation, reprise d'études, ou un autre parcours. Le SIES compte ces candidats ensemble et ne publie pas de taux d'accès pour eux. Cette page l'estime pour chaque formation à partir des candidats et des propositions publiés.</p>
      <p class="small">${REO_NO_ZONE} Les chiffres ci-dessous sont des parts de candidats des campagnes passées, pas des chances d'admission.</p>
      <div class="toolbar">${mine ? `<span class="badge exact">Votre situation : ${REO_LABEL}</span><button type="button" id="reo-back" class="small">Je suis en terminale</button>`
        : `<button type="button" id="reo-me">C'est ma situation</button><span class="muted small">« Où je me situe », la fiche des formations et « Mes vœux » afficheront alors l'accès estimé hors terminale, sans zone.</span>`}</div></div>
    <div class="card"><div class="carte-pick"><label class="small">Type de diplôme <select id="rdip">${FAC.diplomes.map((x) => `<option value="${esc(x.label)}" ${x.label === D.label ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>
      <label class="small">Mention <select id="rmen"><option value="">Toutes les mentions</option>${D.mentions.map((m) => `<option value="${esc(m.label)}" ${m.label === mention ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label>
      <label class="small">Votre académie <select id="racad"><option value="">—</option>${JV.academies.map((a) => `<option value="${esc(a)}" ${a === home ? "selected" : ""}>${esc(a)}</option>`).join("")}</select></label></div>
      <div class="toolbar">${home ? `<label class="small"><input type="checkbox" id="rhome" ${onlyHome ? "checked" : ""}> Seulement l'académie de ${esc(home)}</label>` : ""}
        <label class="small"><input type="checkbox" id="raut" ${onlyAutres ? "checked" : ""}> Seulement les formations où les admis hors néo-bacheliers sont majoritaires</label></div>
      <p class="small">${fmt(d.formations.length)} formation${d.formations.length > 1 ? "s" : ""} en ${esc(d.session)} · ${fmt(nEst)} avec un accès estimé hors terminale · ${fmt(nAut)} où les admis hors néo-bacheliers sont majoritaires. Ordre : ${home ? `l'académie de ${esc(home)} d'abord, puis ` : ""}le nom de l'établissement, jamais les chiffres.</p></div>
    <div class="card"><h2>Formations ${esc(D.label)}${mention ? ` · ${esc(mention)}` : ""}</h2>
      ${rows.length ? `<div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th class="num">Accès estimé hors terminale ${d.session}</th><th class="num">Taux d'accès officiel, tous candidats</th><th class="num">Admis hors néo-bacheliers</th><th></th></tr>
      ${rows.slice(0, shown).map(row).join("")}</table></div>` : `<p class="muted">Aucune formation pour ces filtres.</p>`}
      ${rows.length > shown ? `<p><button type="button" id="rmore">Afficher ${fmt(Math.min(searchPage(), rows.length - shown))} de plus (${fmt(shown)} sur ${fmt(rows.length)})</button></p>` : ""}
      <p class="muted small">${REO_METHOD} Pas d'estimation sous ${d.min_candidats} candidats hors terminale.</p>
      <p class="muted small">Admis hors néo-bacheliers : admis qui avaient déjà le bac ou venaient d'un autre parcours, effectifs publiés ; le SIES ne les détaille pas.</p></div>
    ${feedbackBox("reorientation")}`;
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
    <p class="small">Lue pour votre situation : ${REO_LABEL}${prof.academie ? `, académie de ${esc(prof.academie)}` : ""}. <a href="#/reorientation">Modifier dans « Je me réoriente »</a></p><p class="print-only small">Liste lue sur SupCompass le ${esc(frDate(localIso()))}. Chiffres officiels Parcoursup 2022–2025 : des parts d'admis, pas des chances d'admission.</p></div>`;
  const howto = `<p class="muted small">Ajoutez des formations depuis leur fiche ou depuis « Je me réoriente » (${voeux.MAX} vœux au maximum sur Parcoursup, hors sous-vœux).</p>`;
  if (!ids.length) {
    $view.innerHTML = `${head}<div class="card"><p class="muted">Votre liste est vide.</p>${howto}</div>`;
    $view.dataset.rendered = "voeux:0";
    return;
  }
  const qs = new URLSearchParams({ ids: ids.join(",") });
  const marker = `voeux:reo:${qs}`;
  $view.dataset.rendered = marker;
  $view.innerHTML = `${head}<div class="card"><p class="muted small">Lecture de votre liste…</p></div>`;
  let d;
  try { d = await api(`/api/reorientation/voeux?${qs}`); } catch (e) {
    if ($view.dataset.rendered === marker) $view.innerHTML = `${head}<div class="warn">${esc(e.message)}</div>`;
    return;
  }
  if ($view.dataset.rendered !== marker) return;
  const ok = d.voeux.filter((v) => v.status === "ok"), nEst = ok.filter((v) => v.reorientation && v.reorientation.acces_estime != null).length;
  const rows = d.voeux.map((v) => {
    const name = v.status !== "ok" ? `<span class="muted">Formation ${esc(v.cod_aff_form)} absente de la campagne ${esc(d.session)}</span>`
      : `<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a><div class="muted small">${esc(v.formation)} · ${esc(v.ville)}${v.academie ? ` (${esc(v.academie)})` : ""}</div>${v.reorientation ? autresBadge(v.reorientation) : ""}`;
    const b = v.status === "ok" ? v.reorientation : null;
    return `<tr><td data-label="Formation">${name}</td>
      <td class="num" data-label="Accès estimé hors terminale">${v.status === "ok" ? reoCell(b) : "—"}</td>
      <td class="num" data-label="Taux d'accès officiel, tous candidats">${pct(b && b.taux_acces_ens)}</td>
      <td class="num" data-label="Admis hors néo-bacheliers">${reoAutres(b)}</td>
      <td class="acts" data-label="Mes vœux"><button type="button" class="small" data-vxdel="${esc(v.cod_aff_form)}">Retirer</button></td></tr>`;
  }).join("");
  $view.innerHTML = `${head}
  <section class="card summary" aria-label="Lecture de votre liste"><h2>Lecture de votre liste</h2>
    <p>${fmt(d.voeux.length)} vœu${d.voeux.length > 1 ? "x" : ""} · ${fmt(nEst)} avec un accès estimé hors terminale.</p>
    <p class="small">${REO_NO_ZONE} Les repères de zones, le plan B et « Compléter ma liste » reposent sur ces zones : ils ne sont pas proposés. Vos vœux ne se combinent pas en une chance d'admission.</p></section>
  <div class="card"><h2>Mes ${fmt(d.voeux.length)} vœux</h2>
    <div class="scroll"><table class="stack"><tr class="stack-head"><th>Formation</th><th class="num">Accès estimé hors terminale ${esc(d.session)}</th><th class="num">Taux d'accès officiel, tous candidats</th><th class="num">Admis hors néo-bacheliers</th><th></th></tr>
    ${rows}</table></div>
    <p class="muted small">${REO_METHOD} Pas d'estimation sous ${d.min_candidats} candidats hors terminale.</p>
    <p class="muted small">Votre liste reste dans ce navigateur. Pour la lire, la page envoie seulement les codes des formations ; rien n'en est enregistré sur le serveur.</p>${howto}</div>${shareCard(ids, !!store.get("profile", null))}${feedbackBox("voeux")}`;
  $view.querySelectorAll("[data-vxdel]").forEach((el) => { el.onclick = () => { voeux.remove(el.dataset.vxdel); viewVoeux(); }; });
  bindShare(ids, store.get("profile", null) ? prof : null);             // sprint 22: never a default profile (review)
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
const CAL_LINKS = { voeux: "#/voeux", fin_voeux: "#/voeux", admission: "#/comprendre", carte: "#/carte" };
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
    <div class="toolbar no-print">${nOk ? `<a class="btnlink" href="/api/calendrier.ics">Ajouter ces dates à mon agenda (.ics)</a>` : ""}<button type="button" id="cal-print">Imprimer</button></div>
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
    <li><a href="#/premiere">En seconde ou en première</a> : les filières où l'on trouve les doublettes de spécialités possibles.</li>
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
    <p>Choisissez trois spécialités de première. En terminale, vous en garderez deux : cela fait trois doublettes possibles. Pour chacune, voici les filières où l'on trouvait cette doublette parmi les admis bacheliers généraux de 2022 à 2025.</p>
    <form id="prem" class="toolbar">${[0, 1, 2].map(sel).join("")}</form>
    <p class="small">Ce sont des parts d'admis des années passées, pas un conseil de spécialités ni une chance d'admission. Beaucoup de filières admettent des doublettes très variées : les attendus de chaque formation, sur sa fiche Parcoursup, et l'avis de votre professeur principal comptent davantage.</p></div>`;
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
    $view.innerHTML = `${intro}<div class="card"><p class="muted small">Lecture des doublettes…</p></div>`;
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
    $view.innerHTML = `${intro}<div class="card"><h2>Trois doublettes possibles</h2>
      <ul class="small">${pairs.map((p, i) => `<li><strong>${esc(p.map(name).join(" + "))}</strong> : ${res[i] && !res[i].error ? `${fmt(res[i].national.accepted)} admis sur ${fmt(res[i].national.years)} campagnes, ${pc1(res[i].national.national_share)} de tous les admis bacheliers généraux` : res[i] && res[i].error === "indisponible" ? "lecture impossible pour le moment, réessayez" : "absente des données 2022–2025"}</li>`).join("")}</ul>
      <div class="scroll"><table class="stack"><tr class="stack-head"><th>Filière</th>${pairs.map((p) => `<th class="num">${esc(p.map(name).join(" + "))}</th>`).join("")}</tr>
      ${rows.slice(0, all ? rows.length : PREM_ROWS).map((r) => `<tr><td data-label="Filière">${esc(r.label)}</td>${r.cells.map(cell).join("")}</tr>`).join("")}</table></div>
      ${rows.length > PREM_ROWS ? `<p><button type="button" id="prem-all">${all ? `Afficher les ${PREM_ROWS} premières` : `Afficher les ${fmt(rows.length)} filières`}</button></p>` : ""}
      <p class="muted small">Ordre : les filières où vont le plus souvent les bacheliers ayant l'une de ces doublettes. Chaque case dit, parmi les admis bacheliers généraux de la filière, la part qui avait cette doublette (2022–2025, campagnes au comptage rompu exclues).</p>
      <p class="small"><a href="#/specialites">Toutes les doublettes par type de formation</a> · En terminale : <a href="#/profil">Mon profil</a></p></div>`;
    const b = document.getElementById("prem-all");
    if (b) b.onclick = () => { store.set("premiereAll", !all); viewPremiere(); };
    bindForm();
  }
}

// a shared list: "#/liste/<codes>[/<profile>]"; codes validated like the stored list; the profile only if the student joined it
const SHARE_KEYS = { s: "serie", a: "spe1", b: "spe2", m: "mention", t: "statut" };
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
  if (!["bg", "bt", "bp"].includes(p.serie) || !["sansmention", "ab", "b", "tb"].includes(p.mention)) return null;   // never a default
  const codes = JV && JV.specialties ? new Set(JV.specialties.map((x) => x.code)) : null;
  if (p.serie === "bg" && (!codes || !codes.has(p.spe1) || !codes.has(p.spe2) || p.spe1 === p.spe2)) return null;
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
  }
  return `${base}/${q.toString()}`;
}
function shareCard(ids, withProfile) {
  return `<section class="card no-print" id="vx-share"><h2>Partager ou imprimer ma liste</h2>
    <p class="small">Envoyez ce lien à un parent ou à votre professeur principal : il verra la même liste. Le lien contient seulement les numéros des formations, et votre profil si vous cochez la case. Le lien lui-même n'est jamais envoyé au serveur, et rien n'est enregistré.</p>
    ${withProfile ? `<label class="small"><input type="checkbox" id="share-prof"> Joindre mon profil (bac, spécialités, mention ; jamais l'académie ni le lycée)</label>` : ""}
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
    const done = () => { msg.textContent = "Lien copié."; };
    const manual = () => { url.focus(); url.select(); msg.textContent = "Copiez le lien sélectionné."; };
    try { navigator.clipboard.writeText(url.value).then(done, manual); } catch (_) { manual(); }
  };
  document.getElementById("share-print").onclick = () => window.print();
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
    : `Lue pour le profil joint : ${profileLine(prof, prof.serie)}.`;
  const head = `<div class="card"><h1>Liste partagée</h1><p class="small">${who}</p>
    <p class="print-only small">Liste lue sur SupCompass le ${esc(frDate(localIso()))}. Chiffres officiels Parcoursup 2022–2025 : des parts d'admis, pas des chances d'admission.</p></div>`;
  if (!ids.length) { $view.innerHTML = `${head}<div class="card"><p class="muted">Ce lien ne contient aucune formation valide.</p></div>`; return; }
  $view.innerHTML = `${head}<div class="card"><p class="muted small">Lecture de la liste…</p></div>`;
  const zoned = prof && !isReo(prof);
  let d;
  try { d = await api(zoned ? `/api/voeux?${vxQuery(ids, prof)}` : `/api/reorientation/voeux?${new URLSearchParams({ ids: ids.join(",") })}`); } catch (e) {
    if ($view.dataset.rendered === marker) $view.innerHTML = `${head}<div class="warn">${esc(e.message)}</div>`;
    return;
  }
  if ($view.dataset.rendered !== marker) return;
  const rows = d.voeux.map((v) => {
    const name = v.status !== "ok" ? `<span class="muted">Formation ${esc(v.cod_aff_form)} absente de la campagne ${esc(d.session)}</span>`
      : `<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a><div class="muted small">${esc(v.filiere || v.formation || "")} · ${esc(v.ville)}${v.academie ? ` (${esc(v.academie)})` : ""}</div>`;
    const b = v.reorientation;
    const third = zoned ? `<td data-label="Zone pour ce profil">${v.status === "ok" && v.zone && ZONES[v.zone] ? zoneBadge(v.zone) : "—"}</td>`
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

// ---- lot 1 UI: the current tab is marked (aria-current) in both menus; "Plus" opens the other pages ----
// R1 (owner, 2026-11-11): the tabs follow the student's journey. Explorer ("home") holds the list, the map, the jobs and every
// formation page; "Mon profil" holds the profile, "Où je me situe", "Je me réoriente" and the seconde/première page.
const TAB_OF = { s: "home", f: "home", evolution: "home", parcours: "profil", profil: "profil", metiers: "home", voeux: "voeux",
  carte: "home", compare: "compare", specialites: "specialites", qualite: "qualite", glossaire: "glossaire", stats: "stats",
  comprendre: "comprendre", selectivite: "selectivite", reorientation: "profil",
  calendrier: "calendrier", accompagner: "accompagner", premiere: "profil", liste: "liste" };
const COMP_TABS = ["compare", "comprendre", "selectivite", "specialites", "qualite", "glossaire"];   // "Comprendre" on a wide screen
const MORE_TABS = [...COMP_TABS, "accompagner"];                                                      // "Plus" on a phone
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
const ROUTE_NAME = { s: "search", f: "fiche", evolution: "evolution", compare: "compare", specialites: "specialites",
  qualite: "qualite", parcours: "parcours", stats: "stats", glossaire: "glossaire", voeux: "voeux", metiers: "metiers", carte: "carte",
  comprendre: "comprendre", selectivite: "selectivite", reorientation: "reorientation",
  calendrier: "calendrier", accompagner: "accompagner", premiere: "premiere", liste: "liste", profil: "profil" };
// Sprint 17: a formation or job opened at its indexable address (/formation/<code>, /metier/<id>) is the same view as its
// hash route; once the visitor navigates inside the app, the address goes back to "/#/…" so links stay the usual ones.
function pathRoute(pathname, hash) {
  if (hash && hash !== "#") return null;
  const f = /^\/formation\/(\d{1,9})\/?$/.exec(pathname);
  if (f) return `/f/${f[1]}`;
  const m = /^\/metier\/(MET\.\d{1,6})\/?$/.exec(pathname);
  if (m) return `/metiers/${m[1]}`;
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
async function route() {
  if (location.pathname !== "/" && location.hash && location.hash !== "#") history.replaceState(null, "", "/" + location.hash);
  if (!pathRoute(location.pathname, location.hash)) document.title = "SupCompass — Parcoursup 2022–2025, les vrais chiffres";
  // Split before decoding: a pasted fiche URL is one %2F-encoded segment.
  const [, a, b, c] = (pathRoute(location.pathname, location.hash) || location.hash.slice(1) || "/").split("/").map(safeDecode);
  trackView(ROUTE_NAME[a] || "home", a === "f" ? b : null);
  // every navigation invalidates the render marker: only the view that sets it again may still be
  // filled by a late async answer (the lycée suggestion of a search, found in review)
  delete $view.dataset.rendered;
  markTab(TAB_OF[a] || "home");
  profileBar.render(TAB_OF[a] || "home");
  try {
    if (a === "stats") return await viewStats(b);
    if (a === "s") return await viewSearch(b || "", c || "");
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
    if (a === "reorientation") return await viewReorientation(b || "", c || "");
    if (a === "calendrier") return await viewCalendrier();
    if (a === "accompagner") return viewAccompagner();
    if (a === "premiere") return await viewPremiere();
    if (a === "liste") return await viewListe(b || "", c || "");
    if (a === "metiers") return await viewMetiers(b || "", c || "");
    if (a === "glossaire") return viewGlossaire(b || "");
    return await viewSearch("");
  } catch (e) {
    showError(e);
  }
}

document.getElementById("search").onsubmit = (e) => {
  e.preventDefault();
  const q = document.getElementById("q").value.trim();
  if (q) location.hash = `#/s/${encodeURIComponent(q)}`;
};
window.addEventListener("hashchange", route);
(async () => {
  try { META = await api("/api/meta"); } catch (e) { showError(e); return; }
  basket.render(); voeux.render(); route();
})();
