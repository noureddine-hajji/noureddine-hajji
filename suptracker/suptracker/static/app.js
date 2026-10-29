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
async function viewSearch(q) {
  if (!q) {
    $view.innerHTML = `<div class="card"><h2>Rechercher une formation</h2>
      <p class="muted">Saisir le nom d'un établissement, une ville, un code UAI (ex. <code>0751234A</code>), une filière, ou coller l'URL d'une fiche Parcoursup (<code>…afficherFicheFormation?g_ta_cod=…</code>).</p>
      <div class="info">${esc(META.methodology.funnel)}</div></div>`;
    return;
  }
  const d = await api(`/api/search?q=${encodeURIComponent(q)}`);
  if (d.mode === "cod_aff_form" && d.results.length === 1) { location.hash = `#/f/${d.results[0].cod_aff_form}`; return; }
  $view.innerHTML = `<div class="card"><h2>${d.results.length} résultat(s) <span class="muted small">(${esc(d.mode)})</span></h2>
    ${d.results.map((r) => `<div class="result"><div>
        <a href="#/f/${esc(r.cod_aff_form)}"><strong>${esc(r.g_ea_lib_vx)}</strong></a> <span class="muted">· ${esc(r.ville_etab)}</span><br>
        ${esc(r.fil_lib_voe_acc)} <span class="muted">${esc(r.lib_comp_voe_ins || "")}</span><br>
        <span class="badge">${esc(r.fili)}</span><span class="badge">UAI ${esc(r.cod_uai)}</span><span class="badge">${r.session}</span>
        <span class="badge">${r.lineage_years} campagne(s)</span>${lineageBadge(r.lineage_confidence)}
        ${r.subwish_flag ? `<span class="badge warnb">sous-vœu</span>` : ""}${r.low_n_flag ? `<span class="badge warnb">n&lt;${META.low_n_threshold}</span>` : ""}
      </div><div class="num"><div class="big">${pct(r.taux_acces_ens)}</div><div class="muted small">taux d'accès</div></div></div>`).join("") || `<p class="muted">Aucune formation.</p>`}</div>`;
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
      <a href="${esc(r.fiche_url)}" target="_blank" rel="noopener">Fiche Parcoursup ↗</a>${geo}
    </div>
  </div>
  ${d.warnings.map((w) => `<div class="warn">⚠ ${esc(w.text)}</div>`).join("")}
  <div class="card"><h2>Indicateurs officiels SIES · ${r.session}</h2>
    <div class="grid3">
      <div><div class="muted small">Taux d'accès (phase principale) ${tip("taux_acces_ens")}</div><div class="big">${pct(r.taux_acces_ens)}</div></div>
      <div><div class="muted small">Terminales générales en position d'admis (PP) ${tip("part_terminale_generale_en_position_admis_pp")}</div><div class="big">${pct(r.part_terminale_generale_en_position_admis_pp)}</div></div>
      <div><div class="muted small">Admis (cohorte finale)</div><div class="big">${fmt(r.acc_tot)}</div><div class="muted small">capacité ${fmt(r.capa_fin)}</div></div>
    </div></div>
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
  </table></div></div>`;
  document.getElementById("sess").onchange = (e) => { location.hash = `#/f/${r.cod_aff_form}/${e.target.value}`; };
  document.getElementById("bask").onclick = () => { basket.toggle(r.cod_aff_form); viewFormation(cod, session); };
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
    <div class="card"><h3>Taux d'accès &amp; terminales générales en position d'admis (PP) ${tip("taux_acces_ens")}</h3>
      ${legend([{ name: "Taux d'accès" }, { name: "Part term. générales en position d'admis" }])}
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
    ["Term. générales en position d'admis (PP) " + tip("part_terminale_generale_en_position_admis_pp"), (f) => pct(f.record.part_terminale_generale_en_position_admis_pp)],
    ["Vœux (toutes phases)", (f) => fmt(f.record.voe_tot) + (f.record.subwish_flag ? " ⚠ sous-vœu" : "")],
    ["Classés (PP)", (f) => fmt(f.record.nb_cla_pp)], ["Proposés", (f) => fmt(f.record.prop_tot)],
    ["Admis", (f) => fmt(f.record.acc_tot) + (f.record.low_n_flag ? " ⚠" : "")],
    ["% TB + TBF", (f) => pct(metric(f, "pct_tb_tbf").value)], ["% boursiers", (f) => pct(f.record.pct_bours)],
    ["% femmes", (f) => pct(f.record.pct_f)], ["% bac général", (f) => pct(f.record.pct_bg)],
    ["% même académie", (f) => pct(f.record.pct_aca_orig)], ["Lignée", (f) => lineageBadge(f.record.lineage_confidence) + ` ${f.history.length} camp.`],
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
  non_ouvert: { label: "Non ouvert au bac général (ou < 5 % d'admis bac G)", color: "var(--line)" },
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
  return `<form id="pf" class="toolbar">
    <label>Spécialité 1 <select name="spe1">${opt(JV.specialties, p.spe1, (x) => x.short)}</select></label>
    <label>Spécialité 2 <select name="spe2">${opt(JV.specialties, p.spe2, (x) => x.short)}</select></label>
    <label>Mention visée <select name="mention">${opt(JV.mentions, p.mention)}</select></label>
    <label>Académie <select name="academie"><option value="">—</option>${opt(JV.academies.map((a) => ({ code: a, label: a })), p.academie)}</select></label>
    <label><input type="checkbox" name="boursier" ${p.boursier ? "checked" : ""}> Boursier</label>
    <button class="primary">Explorer</button></form>`;
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
  g += `<text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">Taux d'accès officiel (phase principale, %)</text>`;
  g += `<text transform="translate(12 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Part des admis avec votre mention ou moins</text>`;
  F.forEach((f, i) => {
    if (f.taux_acces_ens == null || f.cdf == null) return;
    const c = ZONES[f.zone].color, hollow = f.uncertain || f.small_cohort;
    g += `<circle data-i="${i}" cx="${x(f.taux_acces_ens)}" cy="${y(f.cdf)}" r="${f.home_academie ? 6 : 4.5}" fill="${hollow ? "var(--surface)" : c}" stroke="${c}" stroke-width="${f.home_academie ? 3 : 1.5}" style="cursor:pointer"><title>${esc(f.etablissement)} — ${esc(f.filiere)}\nTaux d'accès ${fmt(f.taux_acces_ens)} % · avec votre mention ou moins ${pc1(f.cdf)} [${pc1(f.cdf_ci[0])} ; ${pc1(f.cdf_ci[1])}]\n${ZONES[f.zone].label}${f.uncertain ? " (incertain)" : ""}${f.small_cohort ? " · moins de 10 admis bac général" : ""}</title></circle>`;
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
  const s1 = p.spe1 !== p.spe2 ? await api(`/api/journey/stage1?spe1=${p.spe1}&spe2=${p.spe2}`) : null;
  const drill = store.get("drill", null);
  const s2 = s1 && drill ? await api(`/api/journey/stage2?spe1=${p.spe1}&spe2=${p.spe2}&mention=${p.mention}&type=${encodeURIComponent(drill.type)}&academie=${encodeURIComponent(p.academie || "")}`) : null;
  const W = store.get("wishlist", []);
  const onlyHome = !!p.academie && store.get("onlyHome", false);   // never filter without an académie
  const F = s2 ? s2.formations.filter((f) => f.zone !== "non_ouvert" && (!onlyHome || f.home_academie)) : [];
  const closed = s2 ? s2.formations.filter((f) => f.zone === "non_ouvert").length : 0;
  const mLabel = JV.mentions.find((m) => m.code === p.mention)?.label;
  $view.innerHTML = `
  <div class="card"><h2>1 · Mon profil</h2>${profileForm(p)}
    ${s1 ? `<p class="small muted">Doublette ${esc(s1.doublette.replace("+", " + "))} : ${fmt(s1.national.candidates)} candidats bacheliers généraux sur ${s1.national.years} campagnes, ${pc1(s1.national.national_share)} des admis, taux de proposition toutes filières confondues ${pc1(s1.national.offer_rate)}.</p>` : `<div class="warn">Choisissez deux spécialités distinctes.</div>`}</div>
  ${s1 ? `<div class="card"><h2>2 · Filières qui recrutent votre doublette ${tip("journey_stage1")} ${tip("journey_gate")}</h2>${stage1Matrix(s1, show, allF)}</div>` : ""}
  ${s2 ? `<div class="card" id="stage3"><h2>3 · Positionnement : ${esc(drill.label)} ${tip("journey_cdf")} ${tip("journey_zones")}</h2>
    <p class="small muted">Mention visée : ${esc(mLabel)}. ${fmt(F.length)} formations en ${s2.session}, profils cumulés sur 2022–2025. Les points creux sont incertains (intervalle à 95 %) ou ont moins de 10 admis en bac général${p.academie ? " ; les cercles épais sont dans votre académie" : ""}. Cliquez sur un point pour l'épingler.${closed ? ` ${closed} formation(s) fermées aux bacheliers généraux, par leurs groupes d'appel ou parce qu'ils représentent moins de 5 % des admis 2022–2025 (ex. CPGE ECT), sont exclues.` : ""}</p>
    <div class="toolbar">${p.academie ? `<label><input type="checkbox" id="oh" ${onlyHome ? "checked" : ""}> Seulement l'académie de ${esc(p.academie)}</label>` : ""}</div>
    <div class="legend">${Object.entries(ZONES).map(([k, z]) => `<span><i style="background:${z.color}"></i>${z.label} (${F.filter((f) => f.zone === k).length})</span>`).join("")}</div>
    ${scatter(F, (f) => pin(f))}
    <div class="scroll"><table><tr><th>Formation</th><th>Zone</th><th class="num">Taux d'accès</th><th class="num">Votre mention ou moins [IC 95 %]</th><th class="num">Mention exacte</th><th class="num">Bac général</th><th class="num">${p.boursier ? "<strong>Boursiers</strong>" : "Boursiers"}</th><th>Votre groupe d'appel ${tip("journey_groups")}</th><th>Évolution</th><th></th></tr>
    ${F.slice().sort((a, b) => (b.cdf ?? -1) - (a.cdf ?? -1)).slice(0, 80).map((f) => `<tr><td><a href="#/f/${esc(f.cod_aff_form)}">${esc(f.etablissement)}</a><div class="muted small">${esc(f.filiere)} · ${esc(f.ville)}${f.home_academie ? ' · <span class="badge exact">votre académie</span>' : ""}${f.non_selective && f.home_academie ? ` · ${fmt(f.pct_aca_orig)} % d'admis de l'académie` : ""}</div></td>
      <td><span class="badge" style="border-color:${ZONES[f.zone].color};color:${ZONES[f.zone].color}">${ZONES[f.zone].label}</span>${f.uncertain ? ' <span class="badge">incertain</span>' : ""}${f.small_cohort ? ' <span class="badge warnb">n&lt;10 bac G</span>' : ""}${f.limited_comparability ? ' <span class="badge warnb" title="Moins de 50 % de bacheliers généraux parmi les admis : la distribution des mentions mêle surtout d\'autres séries">comparabilité limitée</span>' : ""}</td>
      <td class="num">${fmt(f.taux_acces_ens)} %</td><td class="num">${pc1(f.cdf)}<div class="muted small">[${pc1(f.cdf_ci[0])} ; ${pc1(f.cdf_ci[1])}] · n=${fmt(f.n_known)}</div></td>
      <td class="num">${pc1(f.exact_share)}</td><td class="num">${pc1(f.pct_bg)}</td><td class="num">${pc1(f.pct_boursiers)}</td>
      <td class="small">${f.group && !f.group.ambiguous ? `${esc(f.group.label)}<div class="muted">dernier appelé : rang ${fmt(f.group.last_called_rank)}</div>` : '<span class="muted">non déterminé</span>'}</td>
      <td>${spark(f.trend, "cdf")}${spark(f.trend, "taux_acces_ens", 100)}</td>
      <td><button data-pin="${esc(f.cod_aff_form)}" class="small">${W.some((w) => w.cod_aff_form === f.cod_aff_form) ? "épinglé" : "épingler"}</button></td></tr>`).join("")}
    </table></div>${F.length > 80 ? `<p class="muted small">80 premières formations affichées (toutes figurent sur la matrice).</p>` : ""}
    ${p.boursier ? `<p class="small muted">Boursier : la part de boursiers parmi les admis est affichée à titre d'information. Les taux minimaux de boursiers fixés par les recteurs ne sont pas publiés formation par formation dans ces données ; aucun ajustement n'est appliqué.</p>` : ""}</div>` : ""}
  <div class="card"><h2>4 · Ma liste de vœux simulée</h2>${wishAudit(W)}</div>`;

  function pin(f) {
    const list = store.get("wishlist", []);
    if (!list.some((w) => w.cod_aff_form === f.cod_aff_form)) {
      list.push({ cod_aff_form: f.cod_aff_form, etablissement: f.etablissement, filiere: f.filiere, type_label: drill.label,
        zone: f.zone, uncertain: f.uncertain, taux_acces_ens: f.taux_acces_ens, cdf: f.cdf });
      store.set("wishlist", list);
    }
    viewParcours();
  }
  document.getElementById("pf").onsubmit = (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const np = { spe1: fd.get("spe1"), spe2: fd.get("spe2"), mention: fd.get("mention"), academie: fd.get("academie"), boursier: !!fd.get("boursier") };
    if (np.spe1 !== p.spe1 || np.spe2 !== p.spe2) store.set("drill", null);
    if (!np.academie) store.set("onlyHome", false);
    store.set("profile", np); viewParcours();
  };
  $view.querySelectorAll("[data-gate]").forEach((el) => { el.onchange = () => { el.checked ? show.add(el.dataset.gate) : show.delete(el.dataset.gate); store.set("gates", [...show]); viewParcours(); }; });
  $view.querySelectorAll("[data-type]").forEach((el) => { el.onclick = async () => { store.set("drill", { type: el.dataset.type, label: el.dataset.label }); await viewParcours(); document.getElementById("stage3")?.scrollIntoView({ behavior: "smooth" }); }; });
  const af = document.getElementById("allf"); if (af) af.onclick = () => { store.set("allFilieres", !allF); viewParcours(); };
  $view.querySelectorAll("[data-pin]").forEach((el) => { el.onclick = () => pin(F.find((f) => f.cod_aff_form === el.dataset.pin)); });
  $view.querySelectorAll("[data-unpin]").forEach((el) => { el.onclick = () => { const l = store.get("wishlist", []); l.splice(+el.dataset.unpin, 1); store.set("wishlist", l); viewParcours(); }; });
  const oh = document.getElementById("oh"); if (oh) oh.onchange = () => { store.set("onlyHome", oh.checked); viewParcours(); };
}

// ---- router ----------------------------------------------------------------
async function route() {
  // Split before decoding: a pasted fiche URL is one %2F-encoded segment.
  const [, a, b, c] = (location.hash.slice(1) || "/").split("/").map(decodeURIComponent);
  try {
    if (a === "s") return await viewSearch(b || "");
    if (a === "f") return await viewFormation(b, c);
    if (a === "evolution") return await viewEvolution(b);
    if (a === "compare") return await viewCompare();
    if (a === "specialites") return await viewSpecialites(b, c);
    if (a === "qualite") return await viewQualite();
    if (a === "parcours") return await viewParcours();
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
