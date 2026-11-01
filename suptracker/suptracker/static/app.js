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
      <a href="#/evolution/${encodeURIComponent(r.cod_aff_form)}">Évolution 4 ans →</a>
      <a href="${esc(r.fiche_url)}" data-cod="${esc(r.cod_aff_form)}" target="_blank" rel="noopener">Fiche Parcoursup ↗</a>${geo}
    </div>
  </div>
  ${d.warnings.map((w) => `<div class="warn">⚠ ${esc(w.text)}</div>`).join("")}
  <div class="card"><h2>Indicateurs officiels SIES · ${r.session}</h2>
    <div class="grid3">
      <div><div class="muted small">Taux d'accès (phase principale) ${tip("taux_acces_ens")}</div><div class="big">${pct(r.taux_acces_ens)}</div></div>
      <div><div class="muted small">Part des terminales générales parmi les candidats appelés (PP) ${tip("part_terminale_generale_en_position_admis_pp")}</div><div class="big">${pct(r.part_terminale_generale_en_position_admis_pp)}</div></div>
      <div><div class="muted small">Admis (cohorte finale)</div><div class="big">${fmt(r.acc_tot)}</div><div class="muted small">capacité ${fmt(r.capa_fin)}</div></div>
    </div></div>
  ${offerCard(r)}
  ${timingCard(r, d.history)}
  ${successCard(d.success)}
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
  const W = opts.onPin ? store.get("wishlist", []) : [];
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
      <td class="num">${a.km != null ? `${fmt(a.km)} km` : "—"}</td>${opts.onPin ? `<td><button type="button" class="small" data-pbpin="${esc(a.cod_aff_form)}">${W.some((w) => w.cod_aff_form === a.cod_aff_form) ? "épinglé" : "épingler"}</button></td>` : ""}</tr>`).join("")}</table></div>
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
const suVal = (row, key) => (row && row[key] != null ? `${pc1d(row[key])} %` : row && row.masked && row.masked[key] ? `<span class="muted small">${SU_MASK[row.masked[key]] || "—"}</span>` : "—");
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

function wishAudit(W) {
  const n = (z) => W.filter((w) => w.zone === z).length;
  const msgs = [];
  if (!W.length) return `<p class="muted">Épinglez des formations depuis la matrice ou le tableau (10 vœux au maximum sur Parcoursup).</p>`;
  if (!n("securite")) msgs.push(["warn", "Aucun vœu de sécurité : ajoutez au moins une formation où la cohorte admise ressemble à votre profil et où le taux d'accès est élevé."]);
  if (n("ambitieux") + n("hors_profil") > W.length / 2) msgs.push(["warn", "Plus de la moitié de la liste est ambitieuse ou hors-profil."]);
  if (n("hors_profil")) msgs.push(["warn", `${n("hors_profil")} vœu(x) hors-profil : moins de 2 % des admis avaient votre mention ou moins sur 2022–2025.`]);
  if (!n("cible")) msgs.push(["info", "Aucun vœu cible pour l'instant."]);
  if (!n("ambitieux")) msgs.push(["info", "Aucun vœu ambitieux : la liste peut viser plus haut sans se déséquilibrer."]);
  if (W.length > 10) msgs.push(["warn", "Parcoursup limite la liste à 10 vœux (hors sous-vœux)."]);
  if (!msgs.length) msgs.push(["info", "La liste combine des vœux de sécurité, cibles et ambitieux."]);
  return `<div class="legend">${Object.entries(ZONES).filter(([k]) => !["indetermine", "non_ouvert"].includes(k)).map(([k, z]) => `<span><i style="background:${z.color}"></i>${z.label} : <strong>${n(k)}</strong></span>`).join("")}</div>
    ${msgs.map(([t, m]) => `<div class="${t}">${esc(m)}</div>`).join("")}
    <table><tr><th>Formation</th><th>Zone</th><th class="num">Taux d'accès</th><th class="num">Votre mention ou moins</th><th></th></tr>
    ${W.map((w, i) => `<tr><td>${esc(w.etablissement)}<div class="muted small">${esc(w.filiere)} · ${esc(w.type_label)}</div></td><td><span class="badge" style="border-color:${ZONES[w.zone].color};color:${ZONES[w.zone].color}">${ZONES[w.zone].label}</span>${w.uncertain ? ' <span class="badge">incertain</span>' : ""}</td>
      <td class="num">${fmt(w.taux_acces_ens)} %</td><td class="num">${pc1(w.cdf)}</td><td><button data-unpin="${i}" class="small">retirer</button></td></tr>`).join("")}</table>
    <p class="muted small">Ces indicateurs décrivent les cohortes admises de 2022 à 2025 ; ce ne sont pas des probabilités d'admission individuelles. Les profils ont été enregistrés pour la mention visée au moment de l'épinglage.</p>`;
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
  const W = store.get("wishlist", []);
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
    <p class="small muted">Mention visée : ${esc(mLabel)}. ${fmt(F.length)} formations en ${s2.session}, profils cumulés sur 2022–2025. Chaque point est placé parmi les ${SERIE_SHORT[serie]} admis ; le trait vertical montre l'encadrement exact quand les données ne permettent pas d'être plus précis. Les points creux sont incertains (intervalle à 95 %) ou ont moins de 10 ${SERIE_SHORT[serie]} admis${serie !== "bg" ? " ; l'axe horizontal est l'accès estimé pour votre série, pas le taux d'accès officiel" : ""}${p.academie ? " ; les cercles épais sont dans votre académie" : ""}. Cliquez sur un point pour l'épingler.${closed ? ` ${closed} formation(s) fermées à votre série par leurs groupes d'appel${serie === "bg" ? " ou parce que les bacheliers généraux y représentent moins de 5 % des admis 2022–2025 (ex. CPGE ECT)" : ""} sont exclues.` : ""}</p>
    <div class="toolbar">${p.academie ? `<label><input type="checkbox" id="oh" ${onlyHome ? "checked" : ""}> Seulement l'académie de ${esc(p.academie)}</label>` : ""}</div>
    <div class="legend">${Object.entries(ZONES).map(([k, z]) => `<span><i style="background:${z.color}"></i>${z.label} (${F.filter((f) => f.zone === k).length})</span>`).join("")}</div>
    ${scatter(F, (f) => pin(f))}
    <div class="scroll"><table><tr><th>Formation</th><th>Zone</th><th class="num">${serie === "bg" ? "Taux d'accès" : `Accès estimé ${SERIE_SHORT[serie]} ${tip("serie_offer")}`}</th><th class="num">${serie === "bg" ? "Bacs généraux" : serie === "bt" ? "Bacs technos" : "Bacs pros"} admis avec votre mention ou moins ${tip("journey_bg")}</th><th class="num">Mention exacte</th><th class="num">${serie === "bg" ? "Bac général" : `Part ${SERIE_SHORT[serie]}`}</th><th class="num">${p.boursier ? "<strong>Boursiers</strong>" : "Boursiers"}</th><th>Votre groupe d'appel ${tip("journey_groups")}</th><th>Évolution</th><th></th></tr>
    ${F.slice().sort((a, b) => (pos(b) ?? -1) - (pos(a) ?? -1)).slice(0, 80).map((f) => `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.filiere)} · ${esc(f.ville)}${f.home_academie ? ' · <span class="badge exact">votre académie</span>' : ""}${p.lycee && f.cod_uai === p.lycee.uai ? ` · <span class="badge exact">dans ton lycée${f.pct_etab_orig != null ? ` · ${fmt(f.pct_etab_orig)} % des admis en venaient` : ""}</span>` : ""}${f.non_selective && f.home_academie ? ` · ${fmt(f.pct_aca_orig)} % d'admis de l'académie` : ""}</div>${offerBadges(f, true)}</td>
      <td><span class="badge" style="border-color:${ZONES[f.zone].color};color:${ZONES[f.zone].color}">${ZONES[f.zone].label}</span>${f.uncertain ? ' <span class="badge">incertain</span>' : ""}${f.small_cohort ? ` <span class="badge warnb">n&lt;10 ${serie === "bg" ? "bac G" : serie === "bt" ? "bac techno" : "bac pro"}</span>` : ""}${f.rate_fragile ? ' <span class="badge warnb" title="Moins de 20 candidats de votre série : taux fragile">peu de candidats</span>' : ""}${f.rare_for_serie ? ` <span class="badge warnb" title="Moins de 5 % des admis 2022–2025 viennent de votre série">rare pour les ${SERIE_SHORT[serie]}</span>` : ""}${f.limited_comparability && !f.spos ? ' <span class="badge warnb" title="Moins de 50 % de bacheliers généraux parmi les admis : la distribution des mentions mêle surtout d\'autres séries">comparabilité limitée</span>' : ""}</td>
      <td class="num">${f.taux_acces_ens != null ? `${fmt(f.taux_acces_ens)} %` : "—"}${serie !== "bg" ? `<div class="muted small" title="Estimation. Taux de proposition des candidats de votre série : ${f.serie_proposal_rate != null ? `${fmt(f.serie_proposal_rate)} %` : "—"} ; taux d'accès officiel (tous candidats) : ${fmt(f.taux_acces_all)} %">estim. · tous ${fmt(f.taux_acces_all)} %</div>` : ""}</td><td class="num">${bgCell(f)}</td>
      <td class="num">${pc1(f.exact_share)}</td><td class="num">${pc1(serie === "bg" ? f.pct_bg : f.pct_serie)}</td><td class="num">${pc1(f.pct_boursiers)}</td>
      <td class="small">${f.group && !f.group.ambiguous ? `${esc(f.group.label)}<div class="muted">dernier appelé : rang ${fmt(f.group.last_called_rank)}</div>` : '<span class="muted">non déterminé</span>'}</td>
      <td>${spark(f.trend, "cdf")}${spark(f.trend, "taux_acces_ens", 100)}</td>
      <td><button data-pin="${esc(f.cod_aff_form)}" class="small">${W.some((w) => w.cod_aff_form === f.cod_aff_form) ? "épinglé" : "épingler"}</button>${PLANB_ZONES.includes(f.zone) ? `<button type="button" data-planb="${esc(f.cod_aff_form)}" class="small planb-btn" aria-expanded="false">Voir un plan B</button>` : ""}</td></tr>`).join("")}
    </table></div>${F.length > 80 ? `<p class="muted small">80 premières formations affichées (toutes figurent sur la matrice).</p>` : ""}
    ${p.boursier ? `<p class="small muted">Boursier : la part de boursiers parmi les admis est affichée à titre d'information. Les taux minimaux de boursiers fixés par les recteurs ne sont pas publiés formation par formation dans ces données ; aucun ajustement n'est appliqué.</p>` : ""}</div>` : ""}
  <div class="card"><h2>4 · Ma liste de vœux simulée</h2><div id="wishlist">${wishAudit(W)}</div></div>${feedbackBox("parcours")}`;

  function pin(f, rerender = true) {
    const list = store.get("wishlist", []);
    if (!list.some((w) => w.cod_aff_form === f.cod_aff_form)) {
      list.push({ cod_aff_form: f.cod_aff_form, etablissement: f.etablissement, filiere: f.filiere, type_label: drill.label,
        zone: f.zone, uncertain: f.uncertain, taux_acces_ens: f.taux_acces_ens, cdf: pos(f) });
      store.set("wishlist", list);
    }
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
        pin({ cod_aff_form: a.cod_aff_form, etablissement: a.etablissement, filiere: a.filiere, zone: a.zone,
          uncertain: a.uncertain, taux_acces_ens: a.taux_acces_ens, cdf: a.position }, false);
        const b = box.querySelector(`[data-pbpin="${CSS.escape(a.cod_aff_form)}"]`);
        if (b) b.textContent = "épinglé";
        const list = document.getElementById("wishlist");
        if (list) list.innerHTML = wishAudit(store.get("wishlist", []));
        bindUnpin();
      } });
    };
  });
  $view.querySelectorAll("[data-pin]").forEach((el) => { el.onclick = () => pin(F.find((f) => f.cod_aff_form === el.dataset.pin)); });
  function bindUnpin() { $view.querySelectorAll("[data-unpin]").forEach((el) => { el.onclick = () => { const l = store.get("wishlist", []); l.splice(+el.dataset.unpin, 1); store.set("wishlist", l); viewParcours(); }; }); }
  bindUnpin();
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
      <td>${s.status === "en_ligne" ? '<span class="badge exact">en ligne</span>' : `<span class="badge">prévue${s.sprint ? ` · étape ${esc(s.sprint)}` : ""}</span>`}</td></tr>`).join("")}</table></div></div>`;
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

// ---- router ----------------------------------------------------------------
const ROUTE_NAME = { s: "search", f: "fiche", evolution: "evolution", compare: "compare", specialites: "specialites",
  qualite: "qualite", parcours: "parcours", stats: "stats", glossaire: "glossaire" };
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
  basket.render(); route();
})();
