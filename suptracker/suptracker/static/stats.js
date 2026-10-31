"use strict";
// Audience dashboard (#/stats). Reads /api/stats with the owner's token; every number shown is an
// aggregate (see suptracker/analytics.py). One hue per chart, no dual axis, status = icon + text.

const STATS_TOKEN_KEY = "statsToken";
const tokenGet = () => { try { return sessionStorage.getItem(STATS_TOKEN_KEY) || ""; } catch (_) { return ""; } };
const tokenSet = (v) => { try { v ? sessionStorage.setItem(STATS_TOKEN_KEY, v) : sessionStorage.removeItem(STATS_TOKEN_KEY); } catch (_) { /* storage blocked */ } };
const pc = (v, d = 1) => (v == null ? "—" : `${fmt(100 * v, d)} %`);
const ROUTE_LABEL = { home: "Accueil", search: "Recherche", fiche: "Fiche formation", evolution: "Évolution", compare: "Comparateur",
  specialites: "Spécialités", qualite: "Qualité des données", parcours: "Mon parcours", stats: "Audience" };
const SOURCE_LABEL = { direct: "Accès direct / favori", moteur: "Moteur de recherche", parcoursup: "parcoursup.fr", onisep: "Onisep",
  education: "Sites education.gouv", ent: "ENT / Pronote / académies", social: "Réseaux sociaux & messageries", autre: "Autres sites" };
const REASON_LABEL = { utile: "Utile (avis positif)", introuvable: "Ne trouve pas", incomprehensible: "Chiffres difficiles à comprendre",
  manque_info: "Information manquante", erreur_donnees: "Donnée jugée fausse", lent: "Lenteur" };
const PAGE_LABEL = { fiche: "Fiche formation", parcours: "Mon parcours", search: "Résultats de recherche" };

async function statsApi(days) {
  const r = await fetch(`/api/stats?days=${days}`, { headers: { Authorization: `Bearer ${tokenGet()}` }, cache: "no-store" });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* non-JSON */ }
    const e = new Error(msg); e.status = r.status; throw e;
  }
  return r.json();
}

function tokenForm(msg) {
  $view.innerHTML = `<div class="card" style="max-width:520px"><h1>Audience · accès réservé</h1>
    <p class="muted small">Ce tableau de bord est réservé à l'équipe du site. Saisissez le jeton défini dans la variable
    d'environnement <code>SUPTRACKER_STATS_TOKEN</code>. Il reste dans cet onglet uniquement (sessionStorage).</p>
    ${msg ? `<div class="warn">${esc(msg)}</div>` : ""}
    <form id="tokf" class="toolbar"><input id="tok" type="password" autocomplete="off" aria-label="Jeton" style="flex:1;min-width:0;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink)">
    <button class="primary">Ouvrir</button></form></div>`;
  document.getElementById("tokf").onsubmit = (e) => { e.preventDefault(); tokenSet(document.getElementById("tok").value.trim()); viewStats(); };
}

// ---- deltas & tiles ----------------------------------------------------------
function delta(k) {
  if (k.value == null || k.previous == null) return `<span class="muted small">pas de période de comparaison</span>`;
  const isRate = k.unit === "rate";
  const diff = isRate ? 100 * (k.value - k.previous) : k.previous ? 100 * (k.value - k.previous) / k.previous : null;
  if (diff == null) return `<span class="muted small">période précédente : 0</span>`;
  const txt = isRate ? `${diff >= 0 ? "+" : "−"}${fmt(Math.abs(diff), 1)} pt` : `${diff >= 0 ? "+" : "−"}${fmt(Math.abs(diff), 0)} %`;
  if (k.low_n) return `<span class="muted small">${txt} · effectif trop faible pour conclure</span>`;
  if (!k.significant) return `<span class="muted small">${txt} · non significatif (p ajusté = ${fmt(k.p_adj ?? k.p, 2)})</span>`;
  const good = (k.value > k.previous) === (k.good === "up");
  return `<span class="small ${good ? "st-good" : "st-bad"}">${k.value > k.previous ? "▲" : "▼"} ${txt} · ${good ? "amélioration" : "dégradation"} significative</span>`;
}

function tile(k) {
  const v = k.unit === "rate" ? pc(k.value) : fmt(k.value);
  const ci = k.unit === "rate" && k.ci?.[0] != null ? `<div class="muted small">IC 95 % ${pc(k.ci[0], 0)}–${pc(k.ci[1], 0)} · n = ${fmt(k.n)}</div>` : "";
  return `<div class="card kpi"><div class="muted small">${esc(k.name)}</div><div class="big">${v}</div>${ci}<div>${delta(k)}</div></div>`;
}

function rolling(daily, w = 7) {
  return daily.map((_, i) => {
    const win = daily.slice(Math.max(0, i - w + 1), i + 1);
    const z = win.reduce((a, r) => a + r.zero, 0), n = win.reduce((a, r) => a + r.searches, 0);
    return { zero: z, searches: n, rate: n ? z / n : null };
  });
}

// ---- daily small multiples with Parcoursup phases and a crosshair ------------
function dailyChart(id, daily, key, title, { rate = false } = {}) {
  const W = 620, H = 150, L = 40, R = 10, T = 18, B = 22, n = daily.length;
  // rates use a trailing 7-day window: a daily share over a handful of searches is mostly noise
  const vals = rate ? rolling(daily).map((r) => r.rate) : daily.map((d) => d[key]);
  const max = rate ? Math.max(0.05, ...vals.filter((v) => v != null)) : Math.max(4, ...vals);
  const x = (i) => L + (n === 1 ? (W - L - R) / 2 : i * (W - L - R) / (n - 1));
  const y = (v) => T + (H - T - B) * (1 - v / max);
  let g = "";
  // phase bands: consecutive days sharing a Parcoursup phase
  let i0 = 0;
  for (let i = 1; i <= n; i++) {
    if (i === n || daily[i].phase !== daily[i0].phase) {
      if (daily[i0].phase) {
        const xa = x(i0) - (i0 ? (x(1) - x(0)) / 2 : 0), xb = x(i - 1) + (i < n ? (x(1) - x(0)) / 2 : 0);
        g += `<rect class="phase" x="${xa}" y="${T}" width="${Math.max(1, xb - xa)}" height="${H - T - B}"><title>${esc(daily[i0].phase)}</title></rect>`;
        if (xb - xa > 90) g += `<text class="phase-l" x="${xa + 4}" y="${T + 10}">${esc(daily[i0].phase)}</text>`;
      }
      i0 = i;
    }
  }
  for (let k = 0; k <= 2; k++) {
    const v = max * k / 2;
    g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 4}" y="${y(v) + 4}" text-anchor="end">${rate ? pc(v, 0) : fmt(v)}</text>`;
  }
  const step = Math.max(1, Math.ceil(n / 6));
  daily.forEach((d, i) => {
    if ((i % step === 0 && n - 1 - i >= step / 2) || i === n - 1) g += `<text x="${x(i)}" y="${H - 6}" text-anchor="${i === n - 1 ? "end" : i === 0 ? "start" : "middle"}">${d.day.slice(8, 10)}/${d.day.slice(5, 7)}</text>`;
  });
  let path = "", pen = false;
  vals.forEach((v, i) => { if (v == null) { pen = false; return; } path += `${pen ? "L" : "M"}${x(i)},${y(v)}`; pen = true; });
  g += `<path d="${path}" fill="none" stroke="var(--c1)" stroke-width="2" stroke-linejoin="round"/>`;
  const last = vals.length - 1;
  if (vals[last] != null) g += `<circle cx="${x(last)}" cy="${y(vals[last])}" r="4" fill="var(--c1)" stroke="var(--surface)" stroke-width="2"/>`;
  g += `<line class="xh" id="${id}-xh" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/>`;
  g += `<rect id="${id}-hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" tabindex="0" aria-label="${esc(title)} : survolez ou utilisez les flèches pour lire chaque jour"/>`;
  return `<div class="chartbox"><div class="small"><strong>${esc(title)}</strong></div>
    <svg class="chart wide" id="${id}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">${g}</svg></div>`;
}

function bindCrosshair(id, daily, fmtRow) {
  const svg = document.getElementById(id), hit = document.getElementById(`${id}-hit`), xh = document.getElementById(`${id}-xh`);
  if (!svg || !hit) return;
  const tipEl = document.getElementById("ttip");
  const n = daily.length, W = 620, L = 40, R = 10;
  const xOf = (i) => L + (n === 1 ? (W - L - R) / 2 : i * (W - L - R) / (n - 1));
  let cur = n - 1;
  const show = (i, clientX, clientY) => {
    cur = Math.max(0, Math.min(n - 1, i));
    xh.setAttribute("x1", xOf(cur)); xh.setAttribute("x2", xOf(cur)); xh.setAttribute("visibility", "visible");
    const d = daily[cur];
    tipEl.replaceChildren();
    const s = document.createElement("strong"); s.textContent = fmtRow(d); tipEl.append(s);
    const m = document.createElement("div"); m.className = "muted"; m.textContent = new Date(`${d.day}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" }) + (d.phase ? ` · ${d.phase}` : ""); tipEl.append(m);
    const box = svg.getBoundingClientRect();
    tipEl.style.left = `${Math.min(window.innerWidth - 220, (clientX ?? box.left + box.width * xOf(cur) / W) + 12)}px`;
    tipEl.style.top = `${(clientY ?? box.top + 20) + window.scrollY + 12}px`;
    tipEl.hidden = false;
  };
  const hide = () => { xh.setAttribute("visibility", "hidden"); tipEl.hidden = true; };
  hit.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const vx = (e.clientX - box.left) * W / box.width;
    show(Math.round((vx - L) / ((W - L - R) / Math.max(1, n - 1))), e.clientX, e.clientY);
  });
  hit.addEventListener("pointerleave", hide);
  hit.addEventListener("focus", () => show(cur));
  hit.addEventListener("blur", hide);
  hit.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); show(cur + (e.key === "ArrowRight" ? 1 : -1)); }
  });
}

// ---- bars ---------------------------------------------------------------------
function hbars(entries, { total, unit = "", labels = {} } = {}) {
  const max = Math.max(1, ...entries.map(([, v]) => v));
  const sum = total ?? entries.reduce((a, [, v]) => a + v, 0);
  return `<div class="hbars">${entries.map(([k, v]) => `<div class="hbar" title="${esc(labels[k] || k)} : ${fmt(v)}${unit}">
    <span class="hl">${esc(labels[k] || k)}</span>
    <span class="ht"><span class="hf" style="width:${(100 * v / max).toFixed(1)}%"></span></span>
    <span class="hv num">${fmt(v)}${unit}${sum ? ` <span class="muted">· ${pc(v / sum, 0)}</span>` : ""}</span></div>`).join("")}</div>`;
}

function funnelView(f) {
  const top = Math.max(1, f[0].visitors);
  return `<div class="hbars">${f.map((s, i) => `<div class="hbar"><span class="hl">${i + 1} · ${esc(s.stage)}</span>
    <span class="ht"><span class="hf" style="width:${(100 * s.visitors / top).toFixed(1)}%"></span></span>
    <span class="hv num">${fmt(s.visitors)} <span class="muted">· ${pc(s.visitors / top, 0)}${i ? ` · ${f[i - 1].visitors ? pc(s.visitors / f[i - 1].visitors, 0) : "—"} de l'étape ${i}` : ""}</span></span></div>`).join("")}</div>`;
}

function satisfaction(fb) {
  return fb.map((x) => {
    const n = x.up + x.down;
    const ci = x.ci[0] != null ? `<span class="ci" style="left:${(100 * x.ci[0]).toFixed(1)}%;width:${(100 * (x.ci[1] - x.ci[0])).toFixed(1)}%"></span>` : "";
    return `<div class="hbar" title="${esc(PAGE_LABEL[x.page])} : ${x.up} oui / ${x.down} non">
      <span class="hl">${esc(PAGE_LABEL[x.page])}</span>
      <span class="ht">${n ? `<span class="hf" style="width:${(100 * x.share_up).toFixed(1)}%"></span>${ci}` : ""}</span>
      <span class="hv num">${n ? `${pc(x.share_up, 0)} <span class="muted">· n = ${fmt(n)}${x.low_n ? " · n faible" : ""}</span>` : `<span class="muted">aucun avis</span>`}</span></div>`;
  }).join("");
}

const LEVEL = { good: ["st-good", "▲"], bad: ["st-bad", "●"], warn: ["st-warn", "▲"], info: ["muted", "ℹ"] };
function insightList(list) {
  return `<ul class="insights">${list.map((i) => `<li><span class="${LEVEL[i.level][0]}" aria-hidden="true">${LEVEL[i.level][1]}</span>
    <div><strong class="sr">${{ good: "Positif", bad: "À traiter", warn: "Attention", info: "Info" }[i.level]} : </strong>${esc(i.text)}${i.action ? `<div class="muted small">→ ${esc(i.action)}</div>` : ""}</div></li>`).join("")}</ul>`;
}

function queryTable(rows, { zero = false, k }) {
  if (!rows.length) return `<p class="muted small">Aucune requête tapée par au moins ${k} visiteurs-jours sur la période.</p>`;
  return `<table><tr><th>Requête (normalisée)</th><th class="num">Visiteurs-jours</th><th></th></tr>
    ${rows.map((r) => `<tr><td>${esc(r.key)}</td><td class="num">${fmt(r.visitor_days)}</td>
      <td><a href="#/s/${encodeURIComponent(r.key)}">${zero ? "reproduire →" : "voir →"}</a></td></tr>`).join("")}</table>`;
}

function toCsv(d) {
  const lines = [["jour", "phase", "visiteurs", "pages_vues", "recherches", "recherches_sans_resultat"].join(";")];
  d.daily.forEach((r) => lines.push([r.day, r.phase || "", r.visitors, r.pageviews, r.searches, r.zero].join(";")));
  return lines.join("\n");
}

async function viewStats(daysArg) {
  if (!tokenGet()) return tokenForm();
  const days = [7, 30, 90, 180].includes(+daysArg) ? +daysArg : 30;
  let d;
  try { d = await statsApi(days); } catch (e) {
    if (e.status === 401) { tokenSet(""); return tokenForm("Jeton refusé."); }
    if (e.status === 503) { return tokenForm(e.message); }
    throw e;
  }
  const K = d.kpis, q = d.quality;
  const period = `${new Date(d.period.start).toLocaleDateString("fr-FR")} → ${new Date(d.period.end).toLocaleDateString("fr-FR")}`;
  $view.innerHTML = `
  <div class="card"><h1>Audience &amp; qualité d'usage</h1>
    <div class="muted small">${period} · comparée aux ${days} jours précédents · stockage ${esc(d.store.kind)}${d.store.persistent ? "" : " (éphémère)"} · seuil d'anonymat k = ${d.k_anon}</div>
    <div class="toolbar" style="margin-top:8px">${[7, 30, 90, 180].map((n) => `<a class="badge${n === days ? " exact" : ""}" href="#/stats/${n}">${n} jours</a>`).join("")}
      <button id="csv" class="small">Exporter CSV</button><button id="logout" class="small">Fermer la session</button></div></div>
  <div class="card"><h2>Ce qu'il faut retenir</h2>${insightList(d.insights)}</div>
  <div class="kpis">${K.map(tile).join("")}</div>
  <div class="card"><h2>Évolution quotidienne</h2>
    <p class="muted small">Bandes grises : phases du calendrier Parcoursup (dates indicatives). Survolez, ou utilisez le clavier (Tab puis ←/→), pour lire chaque jour.</p>
    ${dailyChart("ch-v", d.daily, "visitors", "Visiteurs uniques par jour")}
    ${dailyChart("ch-s", d.daily, "searches", "Recherches par jour")}
    ${dailyChart("ch-z", d.daily, "zero", "Part des recherches sans résultat (moyenne glissante sur 7 jours)", { rate: true })}
    <details><summary class="small">Voir les données en tableau</summary><div class="scroll"><table>
      <tr><th>Jour</th><th>Phase</th><th class="num">Visiteurs</th><th class="num">Pages vues</th><th class="num">Recherches</th><th class="num">Sans résultat</th></tr>
      ${d.daily.slice().reverse().map((r) => `<tr><td>${r.day}</td><td class="small">${esc(r.phase || "")}</td><td class="num">${fmt(r.visitors)}</td><td class="num">${fmt(r.pageviews)}</td><td class="num">${fmt(r.searches)}</td><td class="num">${fmt(r.zero)}</td></tr>`).join("")}
    </table></div></details></div>
  <div class="charts">
    <div class="card"><h2>Entonnoir élève</h2><p class="muted small">Visiteurs distincts ayant atteint chaque étape. Le clic vers Parcoursup est notre meilleur signal d'utilité.</p>${funnelView(d.funnel)}
      <p class="muted small">« Mon parcours » : ${fmt(d.journey.stage1)} profils analysés, ${fmt(d.journey.stage2)} positionnements détaillés.</p></div>
    <div class="card"><h2>Satisfaction par page</h2><p class="muted small">Part d'avis 👍, avec intervalle de Wilson à 95 % (trait foncé). Moins de 30 avis : à lire avec prudence.</p>
      <div class="hbars">${satisfaction(d.feedback)}</div>
      <h3 style="margin-top:12px">Motifs d'avis</h3>${hbars(Object.entries(d.reasons).filter(([, v]) => v).sort((a, b) => b[1] - a[1]), { labels: REASON_LABEL }) || ""}
      ${Object.values(d.reasons).every((v) => !v) ? `<p class="muted small">Aucun motif sur la période.</p>` : ""}</div>
  </div>
  <div class="card"><h2>Ce que les élèves ne trouvent pas</h2>
    <p class="muted small">Recherches sans aucun résultat, tapées par au moins ${d.k_anon} visiteurs-jours. Chaque ligne est un cas de test à ajouter au gold set de la recherche (scripts/eval_search.py) avant de corriger. ${q.hidden_zero_queries ? `${fmt(q.hidden_zero_queries)} requête(s) plus rares masquée(s) (anonymat).` : ""}</p>
    <div class="scroll">${queryTable(d.zero_queries, { zero: true, k: d.k_anon })}</div></div>
  <div class="charts">
    <div class="card"><h2>Recherches les plus fréquentes</h2><div class="scroll">${queryTable(d.top_queries.slice(0, 15), { k: d.k_anon })}</div></div>
    <div class="card"><h2>Formations les plus consultées</h2><div class="scroll">${d.top_fiches.length ? `<table><tr><th>Formation</th><th class="num">Visiteurs-jours</th></tr>
      ${d.top_fiches.map((f) => `<tr><td><a href="#/f/${esc(f.key)}">${esc(f.etablissement || f.key)}</a><div class="muted small">${esc(f.filiere || "")} · ${esc(f.ville || "")}</div></td><td class="num">${fmt(f.visitor_days)}</td></tr>`).join("")}</table>`
      : `<p class="muted small">Aucune fiche vue par au moins ${d.k_anon} visiteurs-jours.</p>`}</div></div>
  </div>
  <div class="charts">
    <div class="card"><h2>Pages vues par rubrique</h2>${hbars(Object.entries(d.routes).filter(([, v]) => v).sort((a, b) => b[1] - a[1]), { labels: ROUTE_LABEL })}</div>
    <div class="card"><h2>Provenance &amp; appareils</h2>${hbars(Object.entries(d.sources).filter(([, v]) => v).sort((a, b) => b[1] - a[1]), { labels: SOURCE_LABEL })}
      <h3 style="margin-top:12px">Appareils</h3>${hbars(Object.entries(d.devices), { labels: { mobile: "Mobile", tablet: "Tablette", desktop: "Ordinateur" } })}</div>
  </div>
  <div class="card"><h2>Qualité de la mesure</h2><table>
    <tr><td>Requêtes de robots écartées</td><td class="num">${fmt(q.bots_filtered)}</td></tr>
    <tr><td>Refus de mesure respectés (Do Not Track / GPC)</td><td class="num">${fmt(q.opt_out)}</td></tr>
    <tr><td>Événements invalides rejetés</td><td class="num">${fmt(q.invalid)}</td></tr>
    <tr><td>Événements au-delà du quota quotidien par visiteur</td><td class="num">${fmt(q.rate_limited)}</td></tr>
    <tr><td>Erreurs JavaScript (visiteurs-pages distincts)</td><td class="num">${fmt(q.js_errors)}</td></tr>
    <tr><td>Erreurs serveur (5xx)</td><td class="num">${fmt(q.server_errors)}</td></tr>
    <tr><td>Recherches / fiches masquées sous le seuil d'anonymat</td><td class="num">${fmt(q.hidden_queries)} / ${fmt(q.hidden_fiches)}</td></tr>
    </table>${d.store.salt_configured ? "" : `<div class="warn" style="margin-top:8px">SUPTRACKER_ANALYTICS_SALT n'est pas défini : les visiteurs uniques peuvent être surestimés.</div>`}</div>
  <div class="card"><h2>Méthode</h2><p class="small muted">Aucun cookie, aucun identifiant, aucune adresse IP ni user agent n'est enregistré.
    Un visiteur est un pseudonyme quotidien (HMAC du jour, de l'IP et du navigateur) qui change chaque jour : on compte donc des
    <strong>visiteurs-jours</strong>, et deux jours ne peuvent pas être reliés. Seuls des compteurs agrégés par jour sont conservés
    (400 jours). Les recherches sont normalisées, les e-mails, URL et nombres sont masqués, et une requête n'apparaît qu'à partir de
    ${d.k_anon} visiteurs-jours. Les variations sont testées (test exact approché pour les volumes, test z de deux proportions pour
    les taux), avec une correction de Holm pour les six indicateurs testés ensemble ; « non significatif » veut dire que l'écart peut être du bruit. Les intervalles sont des intervalles de Wilson à 95 %.</p></div>
  <div id="ttip" class="ttip" role="status" hidden></div>`;
  bindCrosshair("ch-v", d.daily, (r) => `${fmt(r.visitors)} visiteurs`);
  bindCrosshair("ch-s", d.daily, (r) => `${fmt(r.searches)} recherches`);
  const roll = rolling(d.daily);
  bindCrosshair("ch-z", d.daily, (r) => { const w = roll[d.daily.indexOf(r)]; return w.searches ? `${pc(w.rate)} sans résultat sur 7 jours (${fmt(w.zero)}/${fmt(w.searches)})` : "aucune recherche"; });
  document.getElementById("logout").onclick = () => { tokenSet(""); tokenForm(); };
  document.getElementById("csv").onclick = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([toCsv(d)], { type: "text/csv;charset=utf-8" }));
    a.download = `suptracker-audience-${d.period.start}_${d.period.end}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  $view.dataset.rendered = `stats:${days}`;
}
