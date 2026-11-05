"use strict";
// SupTracker SIES front-end: hash router + dependency-free SVG charts.

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

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* non-JSON error body */ }
    throw new Error(msg);
  }
  return r.json();
}

// ---- comparator basket (per-viewer convenience only) -----------------------
const basket = {
  get() { try { return JSON.parse(localStorage.getItem("basket") || "[]"); } catch (_) { return []; } },
  set(v) { try { localStorage.setItem("basket", JSON.stringify(v)); } catch (_) { /* storage blocked */ } this.render(); },
  toggle(cod) { const b = this.get(); const i = b.indexOf(cod); i >= 0 ? b.splice(i, 1) : b.length < 6 && b.push(cod); this.set(b); },
  render() { document.getElementById("basket-count").textContent = this.get().length; },
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
  add(cod) { const v = this.get(); if (!v.includes(cod) && v.length < this.MAX) { v.push(cod); this.set(v); } return v.includes(cod); },
  remove(cod) { this.set(this.get().filter((c) => c !== cod)); },
  render() { const el = document.getElementById("voeux-count"); if (el) el.textContent = this.get().length; },
};

// ---- SVG primitives --------------------------------------------------------
const COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

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
    g += `<path d="${d}" fill="none" stroke="${c}" stroke-width="2"/>`;
    s.values.forEach((v, i) => {
      if (v == null) return;
      const hollow = s.hollow?.[i];
      g += `<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="${hollow ? "var(--surface)" : c}" stroke="${c}" stroke-width="2"><title>${esc(s.name)} ${years[i]} : ${fmt(v, 1)}${unit === "%" ? " %" : ""}${hollow ? " (effectif < seuil)" : ""}</title></circle>`;
    });
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
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
    if (r.low_n_flag) g += `<text x="${cx}" y="${y(acc) - 4}" text-anchor="middle">⚠ n&lt;${META.low_n_threshold}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
}

const legend = (items) => `<div class="legend">${items.map((k, i) => `<span><i style="background:${k.color || COLORS[i]}"></i>${esc(k.name)}</span>`).join("")}</div>`;

function benchBar(p) {
  if (!p.n_peers) return `<span class="muted small">pas de pairs</span>`;
  const sx = (v) => 4 + 292 * Math.max(0, Math.min(100, v)) / 100;
  let s = `<rect x="${sx(p.p10)}" y="8" width="${sx(p.p90) - sx(p.p10)}" height="6" fill="var(--range)"/>`
    + `<rect x="${sx(p.p25)}" y="5" width="${Math.max(1, sx(p.p75) - sx(p.p25))}" height="12" fill="var(--box)"/>`
    + `<line x1="${sx(p.p50)}" x2="${sx(p.p50)}" y1="3" y2="19" stroke="var(--ink)" stroke-width="1.5"/>`;
  if (p.value != null) s += `<circle cx="${sx(p.value)}" cy="11" r="5" fill="${p.in_reference ? "var(--c2)" : "var(--surface)"}" stroke="var(--c2)" stroke-width="2"/>`;
  return `<svg viewBox="0 0 300 22" preserveAspectRatio="none" role="img"><title>p10 ${fmt(p.p10, 1)} · p25 ${fmt(p.p25, 1)} · médiane ${fmt(p.p50, 1)} · p75 ${fmt(p.p75, 1)} · p90 ${fmt(p.p90, 1)} (n=${p.n_peers})</title>${s}</svg>`;
}

const lineageBadge = (c) => c === "inferred_uai_track_match"
  ? `<span class="badge inferred" title="Code formation modifié : lien inféré">inféré</span>`
  : `<span class="badge exact" title="Même (cod_uai, cod_aff_form)">exact</span>`;

// ---- views -----------------------------------------------------------------
const INTERP_LABEL = { option: "Option", lieu: "Lieu", sigle: "Reconnu", "corrigé": "Corrigé", "approché": "Mot approché", "ignoré": "Ignoré", uai: "Établissement (UAI)" };
// ---- offer options (cartographie Parcoursup) and offer timing ---------------------------------
const OPT_LABEL = { internat: "Internat", apprentissage: "Apprentissage", distance: "À distance", sport: "Sportifs de haut niveau", art: "Artistes de haut niveau" };
const OPT_ICON = { internat: "🏠", apprentissage: "🛠", distance: "💻", sport: "🏅", art: "🎨" };
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

async function viewSearch(q, rawParams) {
  if (!q) {
    $view.innerHTML = `<div class="card"><h2>Rechercher une formation</h2>
      <p class="muted">Tapez ce que vous cherchez, comme vous le diriez : <em>prépa HEC Lyon</em>, <em>BTS NDRC</em>, <em>IUT informatique Toulouse</em>, <em>sciences po</em>, <em>infirmière Bordeaux</em>, <em>kiné</em>… Les sigles, les fautes de frappe et les villes sont reconnus. Vous pouvez aussi coller l'URL d'une fiche Parcoursup.</p>
      <div class="info">${esc(META.methodology.funnel)}</div></div>`;
    return;
  }
  const P = Object.fromEntries(new URLSearchParams(rawParams || ""));
  const near = store.get("profile", {}).academie || "";
  const qs = new URLSearchParams({ q, offset: P.offset || 0, limit: 40 });
  for (const k of ["fili", "academie", "selective", "options"]) if (P[k]) qs.set(k, P[k]);
  if (near) qs.set("near", near);
  const d = await api(`/api/search?${qs}`);
  if (d.mode === "cod_aff_form" && d.results.length === 1) { location.hash = `#/f/${d.results[0].cod_aff_form}`; return; }
  const go = (patch) => searchHash(q, { fili: P.fili, academie: P.academie, selective: P.selective, options: P.options, ...patch, offset: patch.offset || 0 });
  const activeOpts = (P.options || "").split(",").filter((o) => OPT_LABEL[o]);
  const fromQuery = d.interpretation.filter((i) => i.type === "option").map((i) => i.value);
  const toggleOpt = (o) => { const a = activeOpts.includes(o) ? activeOpts.filter((x) => x !== o) : [...activeOpts, o]; return go({ options: a.join(",") }); };
  const chip = (label, href, active) => `<a class="badge${active ? " exact" : ""}" href="${esc(href)}">${esc(label)}</a>`;
  const facets = d.facets || {};
  const off = +(P.offset || 0);
  $view.innerHTML = `<div class="card">
    <h2>${fmt(d.total)} formation(s)${d.partial ? ` <span class="badge warnb">résultats partiels</span>` : ""}</h2>
    ${d.interpretation.length ? `<div class="legend" aria-label="Interprétation de la recherche">${d.interpretation.map((i) => `<span class="badge">${esc(INTERP_LABEL[i.type] || i.type)} : ${esc(i.value)}</span>`).join("")}</div>` : ""}
    ${d.notes.map((n) => `<div class="info">${esc(n)}</div>`).join("")}
    ${d.total === 0 ? `<p class="muted">Aucune formation ne correspond. Essayez un sigle (BTS, BUT, MPSI…), un intitulé (droit, psychologie…) ou une ville.</p>` : ""}
    ${(facets.fili || []).length > 1 || P.fili ? `<div class="toolbar"><span class="small muted">Type :</span>${chip("Tous", go({ fili: "" }), !P.fili)}${(facets.fili || []).map((f) => chip(`${FILI_LABEL[f.value] || f.value} (${f.count})`, go({ fili: f.value }), P.fili === f.value)).join("")}</div>` : ""}
    ${(facets.options || []).some((o) => o.count || o.active) ? `<div class="toolbar" aria-label="Options de la formation"><span class="small muted">Options :</span>${facets.options.filter((o) => o.count || o.active).map((o) => fromQuery.includes(o.value) && !activeOpts.includes(o.value)
      ? `<span class="badge exact" title="Déduit de votre recherche : retirez le mot pour l'enlever">${OPT_ICON[o.value]} ${esc(OPT_LABEL[o.value])} (${o.count})</span>`
      : chip(`${OPT_ICON[o.value]} ${OPT_LABEL[o.value]} (${o.count})`, toggleOpt(o.value), o.active)).join("")}</div>` : ""}
    ${(facets.academie || []).length > 1 || P.academie || (facets.selectivite || []).length > 1 || P.selective ? `<div class="toolbar">
      ${(facets.academie || []).length > 1 || P.academie ? `<label class="small">Académie <select id="facad"><option value="">Toutes</option>${(facets.academie || []).slice().sort((a, b) => a.value.localeCompare(b.value, "fr")).map((a) => `<option value="${esc(a.value)}" ${P.academie === a.value ? "selected" : ""}>${esc(a.value)} (${a.count})</option>`).join("")}</select></label>` : ""}
      ${(facets.selectivite || []).length > 1 || P.selective ? `<label class="small">Sélectivité <select id="fsel"><option value="">Toutes</option>${(facets.selectivite || []).map((f) => { const v = f.value === "formation sélective" ? "true" : "false"; return `<option value="${v}" ${P.selective === v ? "selected" : ""}>${f.value === "formation sélective" ? "Sélectives" : "Non sélectives"} (${f.count})</option>`; }).join("")}</select></label>` : ""}
    </div>` : ""}
    ${d.results.map((r) => `<div class="result"><div>
        <a href="#/f/${esc(r.cod_aff_form)}"><strong>${esc(r.g_ea_lib_vx)}</strong></a> <span class="muted">· ${esc(r.ville_etab)}${r.acad_mies ? ` (${esc(r.acad_mies)})` : ""}</span><br>
        ${esc(r.fil_lib_voe_acc)} <span class="muted">${esc(r.lib_comp_voe_ins || "")}</span><br>
        <span class="badge">${esc(FILI_LABEL[r.fili] || r.fili)}</span><span class="badge">${r.session}</span>
        <span class="badge">${r.lineage_years} campagne(s)</span>${lineageBadge(r.lineage_confidence)}${offerBadges(r, true)}
        ${r.subwish_flag ? `<span class="badge warnb">sous-vœu</span>` : ""}${r.low_n_flag ? `<span class="badge warnb">n&lt;${META.low_n_threshold}</span>` : ""}
      </div><div class="num"><div class="big">${pct(r.taux_acces_ens)}</div><div class="muted small">taux d'accès</div></div></div>`).join("")}
    ${d.total > off + d.results.length ? `<p><a class="badge exact" href="${esc(go({ offset: off + 40 }))}">Résultats suivants (${fmt(off + d.results.length + 1)}–${fmt(Math.min(d.total, off + 80))}) →</a></p>` : ""}
    ${off ? `<p><a href="${esc(go({ offset: Math.max(0, off - 40) }))}">← Résultats précédents</a></p>` : ""}
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

async function viewFormation(cod, session) {
  const d = await api(`/api/formation/${encodeURIComponent(cod)}${session ? `?session=${session}` : ""}`);
  const r = d.record, inBasket = basket.get().includes(r.cod_aff_form);
  const years = d.history.map((h) => h.session);
  const geo = r.lat != null ? ` · <a href="https://www.openstreetmap.org/?mlat=${r.lat}&mlon=${r.lon}#map=15/${r.lat}/${r.lon}" target="_blank" rel="noopener">carte</a>` : "";
  $view.innerHTML = `
  <div class="card">
    <h1>${esc(r.g_ea_lib_vx)}</h1>
    <div>${esc(r.lib_for_voe_ins)}</div>
    <div class="muted small">${esc(r.ville_etab)} · ${esc(r.acad_mies)} · UAI ${esc(r.cod_uai)} · cod_aff_form ${esc(r.cod_aff_form)} · ${esc(r.contrat_etab)} · ${esc(r.select_form)}</div>
    <div class="toolbar" style="margin-top:8px">
      <label>Session <select id="sess">${years.map((y) => `<option ${y === r.session ? "selected" : ""}>${y}</option>`).join("")}</select></label>
      <button id="bask" class="${inBasket ? "" : "primary"}">${inBasket ? "Retirer du comparateur" : "Ajouter au comparateur"}</button>
      ${voeuButton(r.cod_aff_form)}
      <a href="#/evolution/${encodeURIComponent(r.cod_aff_form)}">Évolution 4 ans →</a>
      <a href="${esc(r.fiche_url)}" data-cod="${esc(r.cod_aff_form)}" target="_blank" rel="noopener">Fiche Parcoursup ↗</a>${geo}
    </div>
  </div>
  ${d.warnings.map((w) => `<div class="warn">⚠ ${esc(w.text)}</div>`).join("")}
  <div class="card"><h2>Indicateurs officiels SIES · ${r.session}</h2>
    <div class="grid3">
      <div><div class="muted small">Taux d'accès (phase principale) ${tip("taux_acces_ens")}</div><div class="big">${pct(r.taux_acces_ens)}</div>${pvLine(d.prevision, "taux_acces_ens")}</div>
      <div><div class="muted small">Part des terminales générales parmi les candidats appelés (PP) ${tip("part_terminale_generale_en_position_admis_pp")}</div><div class="big">${pct(r.part_terminale_generale_en_position_admis_pp)}</div>${pvLine(d.prevision, "part_terminale_generale_en_position_admis_pp")}</div>
      <div><div class="muted small">Admis (cohorte finale)</div><div class="big">${fmt(r.acc_tot)}</div><div class="muted small">capacité ${fmt(r.capa_fin)}</div>${pvLine(d.prevision, "acc_tot")}</div>
    </div></div>
  ${previsionCard(d.prevision)}
  ${offerCard(r)}
  ${timingCard(r, d.history)}
  ${successCard(d.success)}
  ${masterCard(d.master)}
  ${passerellesCard(d.passerelles)}
  ${insertionCard(d.insertion)}
  ${cereqCard(d.cereq)}
  ${metiersCard(d.metiers)}
  ${butCard(d.but)}
  ${lyceeHere(r)}
  <div id="planb"></div>
  <h2 style="font-size:16px">Entonnoir · trois étapes distinctes ${tip("funnel")}</h2>
  <div class="grid3">
    ${stageCard("1 · Candidatures (vœux)", ["voe_tot", "nb_voe_pp", "nb_voe_pc", "voe_tot_f"], r, r.subwish_flag ? "Sous-vœu : effectifs partagés, non additionnables. " + tip("subwish") : "Unité : vœux, pas candidats uniques.")}
    ${stageCard("2 · Classés & proposés", ["nb_cla_pp", "nb_cla_pc", "prop_tot", "ran_grp1"], r)}
    ${stageCard("3 · Admis", ["acc_tot", "acc_pp", "acc_pc", "acc_neobac", "acc_term", "acc_brs"], r)}
  </div>
  <div class="card"><h2>Position dans la filière · ${esc(r.fil_lib_voe_acc)} ${tip("peers")}</h2>
    <div class="legend"><span><i style="background:var(--range)"></i>p10–p90</span><span><i style="background:var(--box)"></i>p25–p75</span><span>│ médiane</span><span><i style="background:var(--c2);border-radius:50%"></i>cette formation (creux = hors référence)</span></div>
    ${d.peers.map((p) => `<div class="bench"><div>${esc(META.peer_metrics[p.metric]?.label || p.metric)}<div class="muted small">${pct(p.value)}</div></div>
      <div>${benchBar(p)}</div>
      <div class="num">${p.peer_percentile != null ? `<strong>P${fmt(p.peer_percentile)}</strong>` : `<span class="muted small">${p.value == null ? "n.d." : "hors réf."}</span>`}
      <div class="muted small">n=${fmt(p.n_peers)}${p.unstable ? " ⚠" : ""}</div></div></div>`).join("")}
  </div>
  <div class="card"><h2>Historique de la lignée ${tip("lineage")}</h2><div class="scroll"><table>
    <tr><th>Session</th><th>cod_aff_form</th><th>Libellé</th><th>Lien vers la campagne suivante</th><th class="num">Admis</th><th class="num">Taux d'accès</th></tr>
    ${d.history.map((h) => `<tr><td><a href="#/f/${esc(h.cod_aff_form)}/${h.session}">${h.session}</a></td><td>${esc(h.cod_aff_form)}</td><td>${esc(h.lib_for_voe_ins)}</td>
      <td>${h.link_to_next ? lineageBadge(h.link_to_next) : `<span class="muted small">—</span>`}</td><td class="num">${fmt(h.acc_tot)}</td><td class="num">${pct(h.taux_acces_ens)}</td></tr>`).join("")}
  </table></div></div>${feedbackBox("fiche")}`;
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
    if (box.isConnected && box.dataset.req === req) box.innerHTML = opts.inline ? `<p class="muted small">Plan B indisponible pour le moment.</p>` : "";
    return;
  }
  if (!box.isConnected || box.dataset.req !== req) return;
  const who = `${{ bg: "bac général", bt: "bac technologique", bp: "bac professionnel" }[serie]}${serie === "bg" ? ` ${esc(prof.spe1 || "MATHS")} + ${esc(prof.spe2 || "SES")}` : ""}, mention ${{ sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien" }[prof.mention] || "assez bien"}${prof.academie ? `, académie de ${esc(prof.academie)}` : ""}`;
  const head = opts.inline
    ? `<h3 class="planb-title">Plan B : la même filière, plus accessible pour vous ${tip("planb")}</h3>`
    : `<h2>Plan B : la même filière, plus accessible pour vous ${tip("planb")}</h2>
    <p class="small muted">Pour ${p ? "votre profil" : "un profil par défaut"} (${who}). <a href="#/parcours">${p ? "Modifier" : "Renseigner le vôtre"} dans « Mon parcours »</a>.</p>`;
  const paidToggle = d.hidden_paid || d.include_paid ? `<label class="small"><input type="checkbox" data-pbpaid ${d.include_paid ? "checked" : ""}> Inclure le privé hors contrat / enseignement supérieur privé (frais de scolarité possibles)${d.hidden_paid ? ` · ${fmt(d.hidden_paid)} masqué(s)` : ""}</label>` : "";
  const W = opts.onPin ? voeux.get() : [];
  let body;
  if (d.status === "deja_accessible") body = `<div class="info">Bonne nouvelle : pour votre profil, cette formation est déjà un vœu de sécurité.</div>`;
  else if (d.status === "non_disponible") body = `<p class="muted small">Plan B indisponible : ${esc(d.reason)}.</p>`;
  else if (!d.alternatives.length) body = `<p class="muted small">Aucune formation de la même filière n'est plus accessible pour votre profil d'après les données 2022–2025.</p>`;
  else {
    body = `<p class="small">Formation visée${d.target.complement ? ` (${esc(d.target.complement)})` : ""} : <span class="badge" style="border-color:${ZONES[d.target.zone].color};color:${ZONES[d.target.zone].color}">${ZONES[d.target.zone].label}</span> · ${d.target.serie === "bg" ? "taux d'accès" : "accès estimé"} ${fmt(d.target.taux_acces_ens)} %</p>
    <div class="scroll"><table><tr><th>Formation</th><th>Zone</th><th class="num">${serie === "bg" ? "Taux d'accès" : "Accès estimé"}</th><th class="num">Votre mention ou moins</th><th class="num">Distance de la formation visée</th>${opts.onPin ? "<th></th>" : ""}</tr>
    ${d.alternatives.map((a) => `<tr><td><a href="#/f/${esc(a.cod_aff_form)}">${esc(a.etablissement)}</a><div class="muted small">${esc(a.complement || a.filiere)} · ${esc(a.ville)}${a.academie ? ` (${esc(a.academie)})` : ""}</div>${a.paid ? '<span class="badge warnb">privé : frais possibles</span>' : ""}${offerBadges(a, true)}</td>
      <td><span class="badge" style="border-color:${ZONES[a.zone].color};color:${ZONES[a.zone].color}">${ZONES[a.zone].label}</span><div class="muted small">${WHY[a.why] || ""}</div></td>
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
  const p = store.get("profile", null) || {};
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
      else note = "ta doublette n'est pas publiée à part (moins de 1 % des inscrits) : ligne de l'ensemble du bac général";
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
  const th = cols.map((g, i) => `<th class="num">${i === 0 ? "Ce diplôme" : g === c.suite ? "Si tu poursuis" : "Tous les sortants"}<div class="muted small">${esc(g.label)}</div></th>`).join("");
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

function offerCard(r) {
  const list = offerList(r);
  if (!r.carto_session && !list.length) return "";
  const src = r.carto_session ? `cartographie Parcoursup ${r.carto_session}` : "libellé SIES";
  return `<div class="card"><h2>Bon à savoir ${tip("offer")}</h2>
    ${list.length ? `<ul class="offer-list">${list.map(([k, t]) => `<li><span aria-hidden="true">${OPT_ICON[k]}</span> ${esc(t)}</li>`).join("")}</ul>`
      : `<p class="muted small">Ni internat, ni apprentissage, ni enseignement à distance, ni aménagement pour sportifs ou artistes de haut niveau ne sont signalés.</p>`}
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
    ${r.low_n_flag ? `<div class="warn">⚠ Seulement ${fmt(r.acc_tot)} admis : ces parts reposent sur très peu d'élèves.</div>` : ""}
    <div class="grid3">${TIMING.map(([k, l]) => `<div><div class="big">${pct(r[k])}</div><div class="muted small">des admis ${r.session} avaient reçu leur proposition ${l}</div></div>`).join("")}</div>
    ${timingBar(r)}
    ${later >= 10 ? `<p class="info">Ne pas avoir de proposition le premier jour n'est pas un refus : en ${r.session}, <strong>${fmt(later)} %</strong> des admis de cette formation ont reçu la leur plus tard, au fil des places libérées.</p>` : `<p class="info">Ici, presque tous les admis (${pct(r.pct_acc_debutpp)}) avaient leur proposition dès l'ouverture : les listes d'attente bougent peu.</p>`}
    ${yrs.length > 1 ? `<div class="scroll"><table><tr><th>Session</th>${TIMING.map(([, l]) => `<th class="num">${esc(l)}</th>`).join("")}<th class="num">Admis</th></tr>
      ${yrs.map((h) => `<tr><td>${h.session}</td>${TIMING.map(([k]) => `<td class="num">${pct(h[k])}</td>`).join("")}<td class="num">${fmt(h.acc_tot)}${h.low_n_flag ? " ⚠" : ""}</td></tr>`).join("")}</table></div>` : ""}
  </div>`;
}

const SERIES = [{ key: "acc_bg", name: "Bac général" }, { key: "acc_bt", name: "Bac techno" }, { key: "acc_bp", name: "Bac pro" }];
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
  ${f.warnings.map((w) => `<div class="warn">⚠ ${esc(w.text)}</div>`).join("")}
  <div class="charts">
    <div class="card"><h3>Taux d'accès &amp; part des terminales générales parmi les candidats appelés (PP) ${tip("taux_acces_ens")}</h3>
      ${legend([{ name: "Taux d'accès" }, { name: "Part des terminales générales parmi les appelés" }])}
      ${lineChart(years, [{ name: "Taux d'accès", values: col("taux_acces_ens") }, { name: "Part term. gén.", values: col("part_terminale_generale_en_position_admis_pp") }])}</div>
    <div class="card"><h3>Admis néo-bacheliers par série de bac ${tip("mentions")}</h3>${legend(SERIES)}${stackedBars(years, SERIES, rows)}</div>
    <div class="card"><h3>Admis par mention au bac ${tip("mentions")}</h3>${legend(MENTIONS)}${stackedBars(years, MENTIONS, rows)}</div>
    <div class="card"><h3>Boursiers, femmes, origine</h3>
      ${legend([{ name: "% boursiers" }, { name: "% femmes" }, { name: "% même académie" }, { name: "% même établissement" }])}
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
    ["Vœux (toutes phases)", (f) => fmt(f.record.voe_tot) + (f.record.subwish_flag ? " ⚠ sous-vœu" : "")],
    ["Classés (PP)", (f) => fmt(f.record.nb_cla_pp)], ["Proposés", (f) => fmt(f.record.prop_tot)],
    ["Admis", (f) => fmt(f.record.acc_tot) + (f.record.low_n_flag ? " ⚠" : "")],
    ["% TB + TBF", (f) => pct(metric(f, "pct_tb_tbf").value)], ["% boursiers", (f) => pct(f.record.pct_bours)],
    ["% femmes", (f) => pct(f.record.pct_f)], ["% bac général", (f) => pct(f.record.pct_bg)],
    ["% même académie", (f) => pct(f.record.pct_aca_orig)],
    ["Proposition dès l'ouverture " + tip("timing"), (f) => (f.record.acc_tot > 0 ? pct(f.record.pct_acc_debutpp) : "—")],
    ["Options", (f) => offerBadges(f.record) || '<span class="muted small">—</span>'], ["Lignée", (f) => lineageBadge(f.record.lineage_confidence) + ` ${f.history.length} camp.`],
  ];
  const series = F.map((f) => { const by = Object.fromEntries(f.history.map((h) => [h.session, h.taux_acces_ens])); return { name: `${f.record.g_ea_lib_vx} · ${f.record.fil_lib_voe_acc}`, values: years.map((y) => by[y] ?? null) }; });
  $view.innerHTML = `<div class="card"><h2>Comparateur</h2><div class="scroll"><table>
    <tr><th></th>${F.map((f) => `<th><a href="#/f/${esc(f.record.cod_aff_form)}">${esc(f.record.g_ea_lib_vx)}</a><div class="small">${esc(f.record.fil_lib_voe_acc)}</div><div class="muted small">${esc(f.record.ville_etab)}${f.record.lib_comp_voe_ins ? " · " + esc(f.record.lib_comp_voe_ins) : ""}</div>
      <button data-rm="${esc(f.record.cod_aff_form)}" class="small">retirer</button></th>`).join("")}</tr>
    ${rowsDef.map(([l, fn]) => `<tr><td>${l}</td>${F.map((f) => `<td>${fn(f)}</td>`).join("")}</tr>`).join("")}
  </table></div></div>
  ${F.flatMap((f) => f.warnings.map((w) => `<div class="warn">⚠ ${esc(f.record.g_ea_lib_vx)} : ${esc(w.text)}</div>`)).join("")}
  <div class="card"><h3>Taux d'accès 2022–2025</h3>${legend(series)}${lineChart(years, series)}</div>`;
  $view.querySelectorAll("[data-rm]").forEach((b) => { b.onclick = () => { basket.toggle(b.dataset.rm); viewCompare(); }; });
}

async function viewSpecialites(session, ftype) {
  const d = await api(`/api/specialites?session=${session || ""}&formation_type=${encodeURIComponent(ftype || "")}`);
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
  const st = (x) => ({ pass: "✓", fail: "✗", upstream_inconsistency: "⚠ incohérence SIES (reproduite à l'identique)" }[x] || "–");
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
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* storage blocked */ } },
};
const pc1 = (v) => (v === null || v === undefined) ? "—" : `${fmt(100 * v, 1)} %`;
const ZONES = {
  securite: { label: "Vœu de sécurité", color: "var(--c3)" },
  cible: { label: "Vœu cible", color: "var(--c1)" },
  ambitieux: { label: "Vœu ambitieux", color: "var(--c2)" },
  hors_profil: { label: "Hors-profil statistique", color: "var(--c6)" },
  indetermine: { label: "Indéterminé", color: "var(--line)" },
  non_ouvert: { label: "Non ouvert à votre série", color: "var(--line)" },
};
const GATES = {
  predilection: { label: "Filière de prédilection", color: "var(--c3)" },
  accessible: { label: "Filière accessible", color: "var(--c1)" },
  atypique: { label: "Atypique / prérequis non alignés", color: "var(--c6)" },
  insuffisant: { label: "Effectif insuffisant", color: "var(--line)" },
};
let JV = null;

function profileForm(p) {
  const opt = (list, val, lab = (x) => x.label, code = (x) => x.code) =>
    list.map((x) => `<option value="${esc(code(x))}" ${code(x) === val ? "selected" : ""}>${esc(lab(x))}</option>`).join("");
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";
  return `<form id="pf" class="toolbar">
    <label>Bac <select name="serie">${opt(JV.series || [{ code: "bg", label: "bac général" }], serie)}</select></label>
    ${serie === "bg" ? `<label>Spécialité 1 <select name="spe1">${opt(JV.specialties, p.spe1, (x) => x.short)}</select></label>
    <label>Spécialité 2 <select name="spe2">${opt(JV.specialties, p.spe2, (x) => x.short)}</select></label>` : ""}
    <label>Mention visée <select name="mention">${opt(JV.mentions, p.mention)}</select></label>
    <label>Académie <select name="academie"><option value="">—</option>${opt(JV.academies.map((a) => ({ code: a, label: a })), p.academie)}</select></label>
    <label><input type="checkbox" name="boursier" ${p.boursier ? "checked" : ""}> Boursier</label>
    ${serie === "bg" && (p.spe1 === "MATHS" || p.spe2 === "MATHS") ? `<label><input type="checkbox" name="maths_expertes" ${p.maths_expertes ? "checked" : ""}> Mathématiques expertes</label>` : ""}
    <div class="lyc-pick"><label for="lyc-q">Mon lycée <span class="muted small">(facultatif, reste dans ton navigateur)</span></label>
      <div class="lyc-row"><input id="lyc-q" type="search" autocomplete="off" placeholder="Nom, ville ou code UAI du lycée" value="${p.lycee ? esc(p.lycee.nom) : ""}" aria-describedby="lyc-help">
      ${p.lycee ? '<button type="button" id="lyc-clear" class="small">Retirer</button>' : ""}</div>
      <div id="lyc-res" class="lyc-res" role="listbox"></div><div id="lyc-help" class="muted small"></div></div>
    <button class="primary">Explorer</button></form>`;
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
  const head = `<h2>Ton lycée, en contexte ${tip("lycee")}</h2>`;
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
    <p class="info small">Ce sont des indicateurs de ton lycée, pas les tiens. Aucune donnée publique ne relie les admissions Parcoursup au lycée d'origine : ton lycée <strong>ne modifie pas</strong> ton positionnement. Seule exception publiée : pour une formation située dans ton lycée (BTS, CPGE), la part d'admis qui en venaient est signalée.</p></div>`;
}
// fiche: the formation is in the student's own lycée (the one lycée effect SIES publishes)
function lyceeHere(r) {
  const p = store.get("profile", null);
  if (!p || !p.lycee || p.lycee.uai !== r.cod_uai) return "";
  return `<div class="info">Cette formation est dans ton lycée${r.pct_etab_orig != null ? ` : ${fmt(r.pct_etab_orig)} % de ses admis en ${esc(r.session)} venaient de ce même lycée (indicateur officiel)` : ""}. ${tip("lycee")}</div>`;
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
  box.innerHTML = `<h2>C'est ton lycée ?</h2><p class="small muted">Choisis-le pour ton profil : il s'affichera en contexte dans « Mon parcours » (il reste dans ton navigateur). Les formations post-bac de ce lycée sont listées plus bas.</p>
    <div class="lyc-res">${hits.map((l) => `<button type="button" data-suggest="${esc(l.uai)}"><strong>${esc(l.nom)}</strong><span class="muted small"> · ${esc(l.commune)}${l.academie ? ` (${esc(l.academie)})` : ""}</span> → Le choisir comme mon lycée</button>`).join("")}</div>`;
  $view.prepend(box);
  box.querySelectorAll("[data-suggest]").forEach((b) => {
    b.onclick = () => {
      const l = LYC.byUai[b.dataset.suggest];
      const prof = store.get("profile", { spe1: "MATHS", spe2: "SES", mention: "ab", academie: "", boursier: false });
      prof.lycee = { uai: l.uai, nom: l.nom, commune: l.commune };
      if (l.academie) prof.academie = l.academie;
      store.set("profile", prof);
      location.hash = "#/parcours";
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
  const pos = serie === "bg" && r.cdf_lo != null ? `<div>ta mention ou moins ${pct0(100 * r.cdf_lo)}–${pct0(100 * r.cdf_hi)} <span class="muted">(tous bacs)</span></div>` : "";
  // the confirmation rate was measured with the bac-général reading of the zone (calibration.zone_of):
  // only comparable for bac général (bac techno and pro use an estimated series access)
  const conf = serie === "bg" && r.zone_confirmed != null ? `<div class="muted">zone confirmée l'année suivante dans ${pct0(100 * r.zone_confirmed)} des cas comparables</div>` : "";
  return `<div>${acc}</div>${pos}${conf}`;
}
function mathsExpertesNote(p, serie) {
  return serie === "bg" && p.maths_expertes && (p.spe1 === "MATHS" || p.spe2 === "MATHS")
    ? `<p class="small muted">Mathématiques expertes : option notée. Les données Parcoursup ne publient pas les options de Terminale, elle ne change donc pas le positionnement ; regarde les attendus de chaque formation sur sa fiche Parcoursup.</p>` : "";
}

function stage1Matrix(s1, show, all) {
  const kept = s1.filieres.filter((f) => show.has(f.gate));
  const rows = all ? kept : kept.slice(0, 15);
  const max = Math.max(0.01, ...rows.map((f) => f.destination_share || 0));
  return `<div class="legend">${Object.entries(GATES).map(([k, g]) => `<label style="cursor:pointer"><input type="checkbox" data-gate="${k}" ${show.has(k) ? "checked" : ""}> <i style="background:${g.color}"></i>${g.label} (${s1.filieres.filter((f) => f.gate === k).length})</label>`).join("")}</div>
  <div class="scroll"><table><tr><th>Filière</th><th>Part de destination</th><th class="num">Part des admis</th><th class="num">Indice</th><th class="num">Taux de proposition</th><th class="num">… tous candidats</th><th></th></tr>
  ${rows.map((f) => `<tr><td><span class="badge" style="border-color:${GATES[f.gate].color};color:${GATES[f.gate].color}">${GATES[f.gate].label}</span><br>${esc(f.label)}<div class="muted small">${fmt(f.candidates)} candidats de la doublette · ${f.years} an(s)</div></td>
    <td style="min-width:130px"><svg viewBox="0 0 100 10" preserveAspectRatio="none" style="width:100%;height:10px;display:block"><rect width="${100 * (f.destination_share || 0) / max}" height="10" fill="${GATES[f.gate].color}"/></svg><span class="small">${pc1(f.destination_share)}</span></td>
    <td class="num">${pc1(f.share)}</td><td class="num">×${fmt(f.lift, 2)}</td><td class="num"><strong>${pc1(f.offer_rate)}</strong></td><td class="num muted">${pc1(f.offer_rate_all)}</td>
    <td>${f.gate === "atypique" || f.gate === "insuffisant" ? "" : f.n_formations ? `<button data-type="${esc(f.type_key)}" data-label="${esc(f.label)}">${fmt(f.n_formations)} établissements →</button>` : '<span class="muted small">pas de correspondance formation par formation</span>'}</td></tr>`).join("")}
  </table></div>
  ${kept.length > 15 ? `<button id="allf">${all ? "Réduire" : `Afficher les ${kept.length} filières`}</button>` : ""}`;
}

function stage1SeriesMatrix(s1, show, all) {
  const kept = s1.filieres.filter((f) => show.has(f.gate));
  const rows = all ? kept : kept.slice(0, 15);
  const max = Math.max(0.01, ...rows.map((f) => f.destination_share || 0));
  const sl = SERIE_SHORT[s1.serie];
  return `<div class="legend">${Object.entries(GATES).map(([k, g]) => `<label style="cursor:pointer"><input type="checkbox" data-gate="${k}" ${show.has(k) ? "checked" : ""}> <i style="background:${g.color}"></i>${g.label} (${s1.filieres.filter((f) => f.gate === k).length})</label>`).join("")}</div>
  <div class="scroll"><table><tr><th>Filière</th><th>Où vont les ${sl} admis</th><th class="num">Part des ${sl} parmi les admis</th><th class="num">Indice</th><th class="num">Accès estimé ${sl} (médiane) ${tip("serie_offer")}</th><th></th></tr>
  ${rows.map((f) => `<tr><td><span class="badge" style="border-color:${GATES[f.gate].color};color:${GATES[f.gate].color}">${GATES[f.gate].label}</span><br>${esc(f.label)}<div class="muted small">${fmt(f.accepted)} ${sl} admis · ${f.years} an(s)</div></td>
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
    const c = ZONES[f.zone].color, hollow = f.uncertain || f.small_cohort;
    if (f.spos && f.spos.width >= 0.01) g += `<line x1="${x(f.taux_acces_ens)}" x2="${x(f.taux_acces_ens)}" y1="${y(f.spos.bounds[0])}" y2="${y(f.spos.bounds[1])}" stroke="${c}" stroke-width="2" opacity=".55"/>`;
    g += `<circle data-i="${i}" cx="${x(f.taux_acces_ens)}" cy="${y(pos(f))}" r="${f.home_academie ? 6 : 4.5}" fill="${hollow ? "var(--surface)" : c}" stroke="${c}" stroke-width="${f.home_academie ? 3 : 1.5}" style="cursor:pointer"><title>${esc(f.etablissement)} — ${esc(f.filiere)}\nTaux d'accès ${fmt(f.taux_acces_ens)} % · avec votre mention ou moins ${f.spos ? `${pc1(f.spos.bounds[0])}–${pc1(f.spos.bounds[1])} des ${SERIE_SHORT[f.serie || "bg"]}` : `${pc1(f.cdf)} (tous bacs)`}\n${ZONES[f.zone].label}${f.uncertain ? " (incertain)" : ""}${f.small_cohort ? " · moins de 10 admis bac général" : ""}</title></circle>`;
  });
  setTimeout(() => document.querySelectorAll("svg.positioning circle[data-i]").forEach((el) => { el.onclick = () => onPick(F[+el.dataset.i]); }));
  return `<svg class="chart positioning" viewBox="0 0 ${W} ${H}" style="max-width:760px" role="img">${g}</svg>`;
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
    dots += `<circle cx="${xs(i)}" cy="${ys(v)}" r="1.6" fill="var(--c1)"/>`;
  });
  return `<svg viewBox="0 0 60 18" style="width:60px;height:18px"><path d="${d}" fill="none" stroke="var(--c1)" stroke-width="1.5"/>${dots}<title>${years.map((y, i) => `${y} : ${vals[i] == null ? "n.d." : (scale === 1 ? pc1(vals[i]) : fmt(vals[i]) + " %")}`).join("\n")}</title></svg>`;
}

async function viewParcours() {
  JV = JV || await api("/api/journey/vocab");
  const p = store.get("profile", { spe1: "MATHS", spe2: "SES", mention: "ab", academie: "", boursier: false });
  const show = new Set(store.get("gates", ["predilection", "accessible"]));
  const allF = store.get("allFilieres", false);
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";   // stored profile: never trusted
  const sq = serie === "bg" ? `spe1=${encodeURIComponent(p.spe1)}&spe2=${encodeURIComponent(p.spe2)}` : `serie=${encodeURIComponent(serie)}`;
  const s1 = serie !== "bg" || p.spe1 !== p.spe2 ? await api(`/api/journey/stage1?${sq}`) : null;
  const drill = store.get("drill", null);
  const s2 = s1 && drill ? await api(`/api/journey/stage2?${sq}&mention=${p.mention}&type=${encodeURIComponent(drill.type)}&academie=${encodeURIComponent(p.academie || "")}`) : null;
  // sprint 10: the positioning answers are served by the CDN, so the page sends the audience count itself
  if (s1) track("journey", { stage: "stage1" });
  if (s2) track("journey", { stage: "stage2" });
  const W = voeux.get();
  const onlyHome = !!p.academie && store.get("onlyHome", false);   // never filter without an académie
  const F = s2 ? s2.formations.filter((f) => f.zone !== "non_ouvert" && (!onlyHome || f.home_academie)) : [];
  const closed = s2 ? s2.formations.filter((f) => f.zone === "non_ouvert").length : 0;
  const mLabel = JV.mentions.find((m) => m.code === p.mention)?.label;
  if (p.lycee) { try { await loadLycees(); } catch (_) { /* the card says the lycée is unavailable */ } }
  $view.innerHTML = `
  <div class="card"><h2>1 · Mon profil</h2>${profileForm(p)}${mathsExpertesNote(p, serie)}
    ${!s1 ? `<div class="warn">Choisissez deux spécialités distinctes.</div>` : serie === "bg"
      ? `<p class="small muted">Doublette ${esc(s1.doublette.replace("+", " + "))} : ${fmt(s1.national.candidates)} candidats bacheliers généraux sur ${s1.national.years} campagnes, ${pc1(s1.national.national_share)} des admis, taux de proposition toutes filières confondues ${pc1(s1.national.offer_rate)}.</p>`
      : `<p class="small muted">${fmt(s1.national.accepted)} ${SERIE_SHORT[serie]} admis sur ${s1.national.years} campagnes, ${pc1(s1.national.national_share)} des néo-bacheliers admis. SIES regroupe toutes les séries ${serie === "bt" ? "technologiques (STMG, STI2D, ST2S…)" : "et spécialités du bac professionnel"} : le site ne peut pas les distinguer. ${tip("serie_offer")}</p>`}</div>
  ${lyceeCard(p)}
  ${s1 ? `<div class="card"><h2>2 · Filières qui recrutent ${serie === "bg" ? "votre doublette" : `les ${SERIE_SHORT[serie]}`} ${tip(serie === "bg" ? "journey_stage1" : "serie_offer")} ${tip("journey_gate")}</h2>${serie === "bg" ? stage1Matrix(s1, show, allF) : stage1SeriesMatrix(s1, show, allF)}</div>` : ""}
  ${s2 ? `<div class="card" id="stage3"><h2>3 · Positionnement : ${esc(drill.label)} ${tip("journey_cdf")} ${tip("journey_zones")}</h2>
    <p class="small muted">Mention visée : ${esc(mLabel)}. ${fmt(F.length)} formations en ${s2.session}, profils cumulés sur 2022–2025. Chaque point est placé parmi les ${SERIE_SHORT[serie]} admis ; le trait vertical montre l'encadrement exact quand les données ne permettent pas d'être plus précis. Les points creux sont incertains (intervalle à 95 %) ou ont moins de 10 ${SERIE_SHORT[serie]} admis${serie !== "bg" ? " ; l'axe horizontal est l'accès estimé pour votre série, pas le taux d'accès officiel" : ""}${p.academie ? " ; les cercles épais sont dans votre académie" : ""}. Cliquez sur un point pour l'ajouter à « Mes vœux ».${closed ? ` ${closed} formation(s) fermées à votre série par leurs groupes d'appel${serie === "bg" ? " ou parce que les bacheliers généraux y représentent moins de 5 % des admis 2022–2025 (ex. CPGE ECT)" : ""} sont exclues.` : ""}</p>
    <div class="toolbar">${p.academie ? `<label><input type="checkbox" id="oh" ${onlyHome ? "checked" : ""}> Seulement l'académie de ${esc(p.academie)}</label>` : ""}</div>
    <div class="legend">${Object.entries(ZONES).map(([k, z]) => `<span><i style="background:${z.color}"></i>${z.label} (${F.filter((f) => f.zone === k).length})</span>`).join("")}</div>
    ${repereNote(s2.calibration)}
    ${scatter(F, (f) => pin(f))}
    <div class="scroll"><table><tr><th>Formation</th><th>Zone</th><th class="num">${serie === "bg" ? "Taux d'accès" : `Accès estimé ${SERIE_SHORT[serie]} ${tip("serie_offer")}`}</th><th class="num">${serie === "bg" ? "Bacs généraux" : serie === "bt" ? "Bacs technos" : "Bacs pros"} admis avec votre mention ou moins ${tip("journey_bg")}</th><th class="num">Mention exacte</th><th class="num">${serie === "bg" ? "Bac général" : `Part ${SERIE_SHORT[serie]}`}</th><th class="num">${p.boursier ? "<strong>Boursiers</strong>" : "Boursiers"}</th><th>Votre groupe d'appel ${tip("journey_groups")}</th>${s2.calibration ? `<th>Repère ${esc(s2.calibration.target)} ${tip("repere")}</th>` : ""}<th>Évolution</th><th></th></tr>
    ${F.slice().sort((a, b) => (pos(b) ?? -1) - (pos(a) ?? -1)).slice(0, 80).map((f) => `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.filiere)} · ${esc(f.ville)}${f.home_academie ? ' · <span class="badge exact">votre académie</span>' : ""}${p.lycee && f.cod_uai === p.lycee.uai ? ` · <span class="badge exact">dans ton lycée${f.pct_etab_orig != null ? ` · ${fmt(f.pct_etab_orig)} % des admis en venaient` : ""}</span>` : ""}${f.non_selective && f.home_academie ? ` · ${fmt(f.pct_aca_orig)} % d'admis de l'académie` : ""}</div>${offerBadges(f, true)}</td>
      <td><span class="badge" style="border-color:${ZONES[f.zone].color};color:${ZONES[f.zone].color}">${ZONES[f.zone].label}</span>${f.uncertain ? ' <span class="badge">incertain</span>' : ""}${f.small_cohort ? ` <span class="badge warnb">n&lt;10 ${serie === "bg" ? "bac G" : serie === "bt" ? "bac techno" : "bac pro"}</span>` : ""}${f.rate_fragile ? ' <span class="badge warnb" title="Moins de 20 candidats de votre série : taux fragile">peu de candidats</span>' : ""}${f.rare_for_serie ? ` <span class="badge warnb" title="Moins de 5 % des admis 2022–2025 viennent de votre série">rare pour les ${SERIE_SHORT[serie]}</span>` : ""}${f.limited_comparability && !f.spos ? ' <span class="badge warnb" title="Moins de 50 % de bacheliers généraux parmi les admis : la distribution des mentions mêle surtout d\'autres séries">comparabilité limitée</span>' : ""}</td>
      <td class="num">${f.taux_acces_ens != null ? `${fmt(f.taux_acces_ens)} %` : "—"}${serie !== "bg" ? `<div class="muted small" title="Estimation. Taux de proposition des candidats de votre série : ${f.serie_proposal_rate != null ? `${fmt(f.serie_proposal_rate)} %` : "—"} ; taux d'accès officiel (tous candidats) : ${fmt(f.taux_acces_all)} %">estim. · tous ${fmt(f.taux_acces_all)} %</div>` : ""}</td><td class="num">${bgCell(f)}</td>
      <td class="num">${pc1(f.exact_share)}</td><td class="num">${pc1(serie === "bg" ? f.pct_bg : f.pct_serie)}</td><td class="num">${pc1(f.pct_boursiers)}</td>
      <td class="small">${f.group && !f.group.ambiguous ? `${esc(f.group.label)}<div class="muted">dernier appelé : rang ${fmt(f.group.last_called_rank)}</div>` : '<span class="muted">non déterminé</span>'}</td>
      ${s2.calibration ? `<td class="small">${repereCell(f, serie)}</td>` : ""}
      <td>${spark(f.trend, "cdf")}${spark(f.trend, "taux_acces_ens", 100)}</td>
      <td><button data-pin="${esc(f.cod_aff_form)}" class="small">${W.includes(f.cod_aff_form) ? "dans mes vœux" : "ajouter à mes vœux"}</button>${PLANB_ZONES.includes(f.zone) ? `<button type="button" data-planb="${esc(f.cod_aff_form)}" class="small planb-btn" aria-expanded="false">Voir un plan B</button>` : ""}</td></tr>`).join("")}
    </table></div>${F.length > 80 ? `<p class="muted small">80 premières formations affichées (toutes figurent sur la matrice).</p>` : ""}
    ${p.boursier ? `<p class="small muted">Boursier : la part de boursiers parmi les admis est affichée à titre d'information. Les taux minimaux de boursiers fixés par les recteurs ne sont pas publiés formation par formation dans ces données ; aucun ajustement n'est appliqué.</p>` : ""}</div>` : ""}
  <div class="card"><h2>4 · Mes vœux</h2><p id="wishlist">${W.length ? `${fmt(W.length)} vœu(x) dans ta liste.` : "Ta liste est vide : ajoute des formations depuis le tableau ou un plan B."} <a href="#/voeux">Voir la lecture de ma liste pour ce profil →</a></p>
    <p class="muted small">La liste est relue pour ton profil actuel à chaque visite (${voeux.MAX} vœux au maximum sur Parcoursup).</p></div>${feedbackBox("parcours")}`;

  function pin(f, rerender = true) {
    if (!voeux.add(f.cod_aff_form)) { alert(`${voeux.MAX} vœux au maximum : retire un vœu dans « Mes vœux » d'abord.`); return; }
    if (rerender) viewParcours();
  }

  const ser = document.querySelector('#pf [name="serie"]');
  if (ser) ser.onchange = () => document.getElementById("pf").requestSubmit();
  // the lycée picked or removed goes through the same submit as "Explorer": edits made in the form
  // before picking it (specialties, mention...) are kept, never replaced by the stored profile
  let lyc = p.lycee || null;
  document.getElementById("pf").onsubmit = (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const np = { serie: fd.get("serie") || "bg", spe1: fd.get("spe1") || p.spe1, spe2: fd.get("spe2") || p.spe2,
      mention: fd.get("mention"), academie: fd.get("academie"), boursier: !!fd.get("boursier"),
      maths_expertes: !!fd.get("maths_expertes"), lycee: lyc };
    if (np.serie !== serie || np.spe1 !== p.spe1 || np.spe2 !== p.spe2) store.set("drill", null);
    if (!np.academie) store.set("onlyHome", false);
    store.set("profile", np); viewParcours();
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
          document.getElementById("pf").requestSubmit();
        };
      });
    };
  }
  const lc = document.getElementById("lyc-clear");
  if (lc) lc.onclick = () => { lyc = null; document.getElementById("pf").requestSubmit(); };
  $view.querySelectorAll("[data-gate]").forEach((el) => { el.onchange = () => { el.checked ? show.add(el.dataset.gate) : show.delete(el.dataset.gate); store.set("gates", [...show]); viewParcours(); }; });
  $view.querySelectorAll("[data-type]").forEach((el) => { el.onclick = async () => { store.set("drill", { type: el.dataset.type, label: el.dataset.label }); await viewParcours(); document.getElementById("stage3")?.scrollIntoView({ behavior: "smooth" }); }; });
  const af = document.getElementById("allf"); if (af) af.onclick = () => { store.set("allFilieres", !allF); viewParcours(); };
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
      const box = row.querySelector(".planb-inline");
      loadPlanB(el.dataset.planb, { box, profile: { ...p, serie }, inline: true, onPin: (a) => {
        pin({ cod_aff_form: a.cod_aff_form }, false);
        const b = box.querySelector(`[data-pbpin="${CSS.escape(a.cod_aff_form)}"]`);
        if (b && voeux.has(a.cod_aff_form)) b.textContent = "dans mes vœux";
        const list = document.getElementById("wishlist");
        if (list) list.innerHTML = `${fmt(voeux.get().length)} vœu(x) dans ta liste. <a href="#/voeux">Voir la lecture de ma liste pour ce profil →</a>`;
      } });
    };
  });
  $view.querySelectorAll("[data-pin]").forEach((el) => { el.onclick = () => pin(F.find((f) => f.cod_aff_form === el.dataset.pin)); });
  const oh = document.getElementById("oh"); if (oh) oh.onchange = () => { store.set("onlyHome", oh.checked); viewParcours(); };
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
  if (fbDone(page)) return `<div class="card feedback small muted">Merci pour ton avis !</div>`;
  return `<div class="card feedback" data-fbpage="${page}"><span>Cette page t'a aidé ?</span>
    <button type="button" data-fb="up" aria-label="Oui, cette page m'a aidé">👍 Oui</button>
    <button type="button" data-fb="down" aria-label="Non, cette page ne m'a pas aidé">👎 Non</button>
    <span class="muted small">Anonyme : aucun texte libre, aucun identifiant.</span></div>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest?.("[data-fb], [data-fbr]");
  const box = b?.closest("[data-fbpage]");
  if (!box) return;
  const page = box.dataset.fbpage;
  try { sessionStorage.setItem(`fb:${page}`, "1"); } catch (_) { /* storage blocked */ }
  if (b.dataset.fb === "up") { track("feedback", { page, vote: "up", reason: "utile" }); box.innerHTML = `<span class="muted small">Merci pour ton avis !</span>`; return; }
  if (b.dataset.fb === "down") {
    track("feedback", { page, vote: "down" });
    box.innerHTML = `<span>Merci. Qu'est-ce qui n'allait pas ?</span> ${FB_REASONS.map(([k, l]) => `<button type="button" class="small" data-fbr="${k}">${esc(l)}</button>`).join(" ")}`;
    return;
  }
  track("feedback", { page, vote: "down", reason: b.dataset.fbr });
  box.innerHTML = `<span class="muted small">Merci, c'est noté : ça nous aide à corriger.</span>`;
});

// ---- Sprint 11: "Mes vœux" (the list read for the CURRENT profile) ----------
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
  aucune_securite: "Aucun vœu de sécurité sûr dans ta liste : ajoute au moins une formation où la cohorte admise ressemble à ton profil et où le taux d'accès est élevé (le bouton « Voir un plan B » en propose).",
  majorite_ambitieuse: "Plus de la moitié des vœux situés sont ambitieux ou hors-profil.",
  hors_profil: "Au moins un vœu est hors-profil : moins de 2 % des admis 2022–2025 avaient ta mention ou moins.",
  non_ouvert: "Au moins un vœu n'est pas ouvert à ta série (groupes d'appel, ou presque aucun admis de ta série) : vérifie la fiche Parcoursup.",
  non_situe: "Certains vœux ne peuvent pas être situés pour ton profil (trop peu de candidats de ta série, formation non rattachée à une filière, ou absente de la dernière campagne).",
  aucune_cible: "Aucun vœu cible pour l'instant.",
  equilibree: "Ta liste combine des vœux de sécurité et des vœux cibles ou ambitieux.",
};
const VX_PLANB = ["ambitieux", "hors_profil", "cible"];
async function viewVoeux() {
  const ids = voeux.get();
  const p = store.get("profile", { spe1: "MATHS", spe2: "SES", mention: "ab", academie: "", boursier: false });
  const serie = ["bg", "bt", "bp"].includes(p.serie) ? p.serie : "bg";   // stored profile: never trusted
  const mention = ["sansmention", "ab", "b", "tb"].includes(p.mention) ? p.mention : "ab";
  const prof = { ...p, serie, mention };
  const who = `${{ bg: "bac général", bt: "bac technologique", bp: "bac professionnel" }[serie]}${serie === "bg" ? ` ${esc(p.spe1 || "MATHS")} + ${esc(p.spe2 || "SES")}` : ""}, mention ${{ sansmention: "sans mention", ab: "assez bien", b: "bien", tb: "très bien" }[mention]}${p.academie ? `, académie de ${esc(p.academie)}` : ""}`;
  const head = `<div class="card"><h1>Mes vœux ${tip("mes_voeux")}</h1>
    <p class="small">Lue pour ton profil actuel : ${who}. <a href="#/parcours">Modifier dans « Mon parcours »</a></p>
    <p class="muted small">Ajoute des formations depuis leur fiche, « Mon parcours » ou un plan B (${voeux.MAX} vœux au maximum sur Parcoursup, hors sous-vœux). Sur Parcoursup, les vœux ne sont pas classés : l'ordre de ta liste ne compte pas.</p></div>`;
  if (!ids.length) {
    $view.innerHTML = `${head}<div class="card"><p class="muted">Ta liste est vide.</p></div>`;
    $view.dataset.rendered = "voeux:0";
    return;
  }
  const qs = new URLSearchParams({ ids: ids.join(","), serie, mention });
  if (serie === "bg") { qs.set("spe1", p.spe1 || "MATHS"); qs.set("spe2", p.spe2 || "SES"); }
  if (p.academie) qs.set("academie", p.academie);
  const marker = `voeux:${qs}`;
  $view.dataset.rendered = marker;
  $view.innerHTML = `${head}<div class="card"><p class="muted small">Lecture de ta liste…</p></div>`;
  let d;
  try { d = await api(`/api/voeux?${qs}`); } catch (e) {
    if ($view.dataset.rendered === marker) $view.innerHTML = `${head}<div class="warn">${esc(e.message)}</div>`;
    return;
  }
  if ($view.dataset.rendered !== marker) return;                       // the user navigated meanwhile
  const L = d.lecture, z = L.zones;
  const zoneBadge = (v) => v.zone && ZONES[v.zone] ? `<span class="badge" style="border-color:${ZONES[v.zone].color};color:${ZONES[v.zone].color}">${ZONES[v.zone].label}</span>${v.uncertain ? ' <span class="badge">incertain</span>' : ""}` : '<span class="badge">non situé</span>';
  const rate = serie === "bg" ? "Taux d'accès" : "Accès estimé pour ta série";
  const legend = [["securite", z.securite], ["cible", z.cible], ["ambitieux", z.ambitieux], ["hors_profil", z.hors_profil], ["non_ouvert", z.non_ouvert]]
    .map(([k, n]) => `<span><i style="background:${ZONES[k].color}"></i>${ZONES[k].label} : <strong>${fmt(n)}</strong></span>`).join("")
    + `<span><i style="background:var(--line)"></i>Non situés : <strong>${fmt(z.indetermine + z.non_situe)}</strong></span>`;
  const rows = d.voeux.map((v) => {
    const name = v.status === "absente" ? `<span class="muted">Formation ${esc(v.cod_aff_form)} absente de la campagne ${d.session}</span>`
      : `<a href="#/f/${esc(v.cod_aff_form)}">${esc(v.etablissement)}</a><div class="muted small">${esc(v.filiere)}${v.complement ? ` · ${esc(v.complement)}` : ""} · ${esc(v.ville)}${v.academie ? ` (${esc(v.academie)})` : ""}${v.home_academie ? ' · <span class="badge exact">ton académie</span>' : ""}</div>`;
    const flags = v.status !== "ok" ? "" : `${v.rate_fragile ? ' <span class="badge warnb">peu de candidats de ta série</span>' : ""}${v.rare_for_serie ? ` <span class="badge warnb">rare pour les ${SERIE_SHORT[serie]}</span>` : ""}${v.small_cohort ? ' <span class="badge warnb">n&lt;10</span>' : ""}`;
    const position = v.bounds ? (v.bounds[1] - v.bounds[0] < 0.005 ? pc1(v.bounds[0]) : `${pc1(v.bounds[0])} – ${pc1(v.bounds[1])}`) : pc1(v.position);
    return `<tr><td>${name}</td><td>${zoneBadge(v)}${flags}</td>
      <td class="num">${v.status === "ok" ? `${fmt(v.taux_acces_ens)} %` : "—"}</td>
      <td class="num">${v.status === "ok" ? position : "—"}</td>
      <td class="num">${v.capa_fin != null ? fmt(v.capa_fin) : "—"}</td>
      <td>${v.status === "ok" && VX_PLANB.includes(v.zone) ? `<button type="button" class="small planb-btn" data-vxplanb="${esc(v.cod_aff_form)}" aria-expanded="false">Voir un plan B</button>` : ""}<button type="button" class="small" data-vxdel="${esc(v.cod_aff_form)}">retirer</button></td></tr>`;
  }).join("");
  $view.innerHTML = `${head}
  <div class="card"><h2>Lecture de ta liste</h2>
    <div class="legend">${legend}</div>
    ${L.messages.map((m) => `<div class="${m.niveau === "warn" ? "warn" : "info"}">${esc(VX_MSG[m.code] || "")}</div>`).join("")}
    <p class="muted small">Ces repères comptent les zones de ta liste, une par vœu. Ils ne disent pas tes chances d'être admis quelque part : les zones décrivent les admis des campagnes passées, et tes vœux ne se combinent pas en une probabilité.</p></div>
  <div class="card"><h2>Mes ${fmt(d.voeux.length)} vœux</h2>
    <div class="scroll"><table><tr><th>Formation</th><th>Zone pour ton profil</th><th class="num">${rate} ${d.session}</th><th class="num">Ta mention ou moins parmi les admis</th><th class="num">Places ${d.session}</th><th></th></tr>
    ${rows}</table></div>
    <p class="muted small">Parts d'admis des campagnes 2022–2025, pas des chances d'admission. ${serie === "bg" ? "Taux d'accès officiel de la dernière campagne." : "Accès estimé pour ta série (taux d'accès officiel × taux de proposition de ta série / taux de proposition de tous), pas un taux officiel."} Vérifie chaque fiche Parcoursup.</p>
    <p class="muted small">Ta liste reste dans ce navigateur. Pour la lire, la page envoie les codes des formations et ton profil, comme « Mon parcours » ; rien n'est enregistré ni compté sur le serveur.</p></div>`;
  $view.querySelectorAll("[data-vxdel]").forEach((el) => { el.onclick = () => { voeux.remove(el.dataset.vxdel); viewVoeux(); }; });
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
      loadPlanB(el.dataset.vxplanb, { box: row.querySelector(".planb-inline"), profile: prof, inline: true, onPin: (a) => {
        if (voeux.add(a.cod_aff_form)) viewVoeux();
        else alert(`${voeux.MAX} vœux au maximum : retire un vœu d'abord.`);
      } });
    };
  });
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
  METIERS = METIERS || await api("/api/metiers");
  const q0 = sessionStorage.getItem("metierQ") || "";
  $view.innerHTML = `<div class="card"><h1>Du métier aux formations ${tip("du_metier_aux_formations")}</h1>
    <p class="small">Cherche un métier : la page montre les diplômes qui y mènent d'après l'Onisep, puis les formations Parcoursup qui les préparent.</p>
    <input id="mq" class="wide" type="search" placeholder="Ex. infirmière, comptable, développeur web…" value="${esc(q0)}" autocomplete="off" aria-label="Métier recherché">
    <p class="muted small">La recherche se fait dans ton navigateur : ce que tu tapes n'est pas envoyé au site. ${fmt(METIERS.rows.length)} métiers des fiches Onisep.</p>
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
      : !rows.length ? `<p class="muted small">Aucune formation de ce diplôme dans ton académie.</p>`
      : `<div class="scroll"><table><tr><th>Formation ${d.session}</th><th class="num">Taux d'accès</th><th class="num">Places</th><th></th></tr>
        ${shown.map((f) => `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a>${f.cod_aff_form === from ? ' <span class="badge exact">la formation que tu regardais</span>' : ""}<div class="muted small">${esc(f.filiere)}${f.complement ? ` · ${esc(f.complement)}` : ""} · ${esc(f.ville)}${f.academie ? ` (${esc(f.academie)})` : ""}</div></td>
          <td class="num">${f.taux_acces_ens != null ? `${fmt(f.taux_acces_ens)} %` : "—"}</td><td class="num">${f.capa_fin != null ? fmt(f.capa_fin) : "—"}</td><td>${voeuButton(f.cod_aff_form)}</td></tr>`).join("")}</table></div>
        ${rows.length > shown.length ? `<p class="muted small">${fmt(shown.length)} formations affichées sur ${fmt(rows.length)}${home && !onlyHome ? " : coche « mon académie seulement » pour resserrer" : ""}.</p>` : ""}`;
    return `<div class="card"><h2><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.libelle)}</a></h2>
      <p class="small">${esc(x.niveau || "niveau non précisé")}${x.acces ? ` · <strong>${esc(MT_ACCES[x.acces])}</strong>` : ""}${x.parcoursup ? ` · ${fmt(x.formations.length)} formation(s) Parcoursup` : ""}</p>${forms}</div>`;
  };
  const status = d.status === "sans_diplome" ? `<div class="info">L'Onisep ne relie aucune fiche diplôme à ce métier.</div>`
    : d.status === "hors_parcoursup" ? `<div class="info">Les diplômes qui mènent à ce métier ne sont pas sur Parcoursup (ils se préparent après un premier diplôme, ou dans une école) : regarde leur fiche Onisep.</div>` : "";
  $view.innerHTML = `<div class="card"><p class="small"><a href="#/metiers">← Autres métiers</a></p>
    <h1>${esc(d.nom)}</h1>
    <p class="small">${d.niveau_acces_min ? `Niveau d'études minimum (Onisep) : ${esc(d.niveau_acces_min)} · ` : ""}<a href="${esc(d.url)}" target="_blank" rel="noopener">Fiche métier Onisep ↗</a></p>
    ${home ? `<label class="small"><input type="checkbox" id="mhome" ${onlyHome ? "checked" : ""}> Mon académie seulement (${esc(home)})</label>` : ""}
    <p class="muted small">Liste nationale : un établissement figure parce qu'il prépare le diplôme, pas parce que ses étudiants exercent ce métier. Ce n'est pas une promesse d'emploi. Les formations sont rangées par académie et par ville, pas par chances d'admission.</p>
    <p class="muted small">Source : Onisep, Idéo (licence ODbL) ; formations Parcoursup ${d.session}.</p></div>
    ${status}${d.diplomes.map(dip).join("")}`;
  const h = document.getElementById("mhome");
  if (h) h.onchange = () => { store.set("metierHome", h.checked); viewMetier(id, from); };
  bindVoeuButton(() => viewMetier(id, from));
}

// ---- router ----------------------------------------------------------------
const ROUTE_NAME = { s: "search", f: "fiche", evolution: "evolution", compare: "compare", specialites: "specialites",
  qualite: "qualite", parcours: "parcours", stats: "stats", glossaire: "glossaire", voeux: "voeux", metiers: "metiers" };
async function route() {
  // Split before decoding: a pasted fiche URL is one %2F-encoded segment.
  const [, a, b, c] = (location.hash.slice(1) || "/").split("/").map(decodeURIComponent);
  trackView(ROUTE_NAME[a] || "home", a === "f" ? b : null);
  // every navigation invalidates the render marker: only the view that sets it again may still be
  // filled by a late async answer (the lycée suggestion of a search, found in review)
  delete $view.dataset.rendered;
  try {
    if (a === "stats") return await viewStats(b);
    if (a === "s") return await viewSearch(b || "", c || "");
    if (a === "f") return await viewFormation(b, c);
    if (a === "evolution") return await viewEvolution(b);
    if (a === "compare") return await viewCompare();
    if (a === "specialites") return await viewSpecialites(b, c);
    if (a === "qualite") return await viewQualite();
    if (a === "parcours") return await viewParcours();
    if (a === "voeux") return await viewVoeux();
    if (a === "metiers") return await viewMetiers(b || "", c || "");
    if (a === "glossaire") return viewGlossaire(b || "");
    return await viewSearch("");
  } catch (e) {
    $view.innerHTML = `<div class="warn">${esc(e.message)}</div>`;
  }
}

document.getElementById("search").onsubmit = (e) => {
  e.preventDefault();
  const q = document.getElementById("q").value.trim();
  if (q) location.hash = `#/s/${encodeURIComponent(q)}`;
};
window.addEventListener("hashchange", route);
(async () => {
  try { META = await api("/api/meta"); } catch (e) { $view.innerHTML = `<div class="warn">${esc(e.message)}</div>`; return; }
  basket.render(); voeux.render(); route();
})();
