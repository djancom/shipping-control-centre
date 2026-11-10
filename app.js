/* Shipping Control Centre: reads data/*.json written by fetch.py (GitHub Actions). Plain JS, no build step. */
"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const D = {};
const FILES = ["status", "markets", "portwatch", "baltic", "drewry", "bunkers", "weather", "storms", "worldbank", "news", "derived", "ais", "fleet-positions"];
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const COL = { green: "#2ecc71", amber: "#f5b041", red: "#ff5c5c" };
const WORD = { green: "Green", amber: "Amber", red: "Red" };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n, dp = 1) => n == null || isNaN(n) ? "n/a" : Number(n).toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const pct = (n, dp = 1) => { if (n == null || isNaN(n)) return '<span class="hint">n/a</span>'; const c = n > 0 ? "up" : n < 0 ? "dn" : ""; return `<span class="${c}">${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(dp)}%</span>`; };
const pctS = (s) => { if (!s) return '<span class="hint">n/a</span>'; const n = parseFloat(String(s).replace("%", "")); return pct(n, 2); };
const money = (n) => "$" + Math.round(n).toLocaleString("en-GB");
// UK time strings arrive as "YYYY-MM-DD HH:MM" (already Europe/London) or "YYYY-MM-DD"
function fmtUK(s, withYear) {
  if (!s) return "n/a";
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
  if (!m) { const mm = String(s).match(/^(\d{4})M(\d{2})$/); return mm ? MON[+mm[2] - 1] + " " + mm[1] : String(s); }
  const d = `${+m[3]} ${MON[+m[2] - 1]}${withYear ? " " + m[1] : ""}`;
  return m[4] ? `${d} ${m[4]}:${m[5]} UK` : d;
}
function ageHours(s) { // approximate, treats UK string as local of viewer's UK clock
  const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}))?/); if (!m) return null;
  const nowUK = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/London" }));
  const t = new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
  return (nowUK - t) / 3.6e6;
}
const ROUTES = [
  { o: "Shanghai", d: "Rotterdam", main: 10546, alt: 13866, mainName: "Suez", altName: "Cape of Good Hope", eu: true, mainCps: ["malacca", "bab", "suez", "gib", "dover"], altCps: ["malacca", "cape", "dover"] },
  { o: "Immingham", d: "Qingdao", main: 10925, alt: 14245, mainName: "Suez", altName: "Cape of Good Hope", eu: false, mainCps: ["dover", "gib", "suez", "bab", "malacca"], altCps: ["dover", "cape", "malacca"] },
  { o: "Constanta", d: "Qingdao", main: 8535, alt: 15079, mainName: "Suez", altName: "Cape of Good Hope", eu: true, mainCps: ["bosporus", "suez", "bab", "malacca"], altCps: ["bosporus", "gib", "cape", "malacca"] },
  { o: "New Orleans", d: "Qingdao", main: 9997, alt: 13942, mainName: "Panama", altName: "Suez (east-about)", eu: false, mainCps: ["panama"], altCps: ["gib", "suez", "bab", "malacca"] },
  { o: "Ras Tanura", d: "Rotterdam", main: 6500, alt: 11283, mainName: "Suez", altName: "Cape of Good Hope", eu: true, mainCps: ["hormuz", "bab", "suez", "gib", "dover"], altCps: ["hormuz", "cape", "dover"] },
];
const REFS = [
  ["IMO: GHG emissions and the Net-Zero Framework", "https://www.imo.org/en/MediaCentre/HotTopics/Pages/Cutting-GHG-emissions.aspx"],
  ["EU ETS for maritime transport", "https://climate.ec.europa.eu/eu-action/transport-decarbonisation/reducing-emissions-shipping-sector_en"],
  ["FuelEU Maritime", "https://transport.ec.europa.eu/transport-modes/maritime/decarbonising-maritime-transport-fueleu-maritime_en"],
  ["UK Maritime and Coastguard Agency notices", "https://www.gov.uk/government/organisations/maritime-and-coastguard-agency"],
  ["UK Department for Transport: maritime", "https://www.gov.uk/transport/maritime-and-shipping"],
  ["UK sanctions list (OFSI / FCDO)", "https://www.gov.uk/government/publications/the-uk-sanctions-list"],
  ["EU sanctions map", "https://www.sanctionsmap.eu/"],
  ["US OFAC recent actions", "https://ofac.treasury.gov/recent-actions"],
  ["International Group of P&I Clubs: circulars", "https://www.igpandi.org/"],
  ["Judiciary: Commercial Court judgments", "https://www.judiciary.uk/courts-and-tribunals/business-and-property-courts/commercial-court/"],
  ["GAFTA contracts and arbitration", "https://www.gafta.com/"],
  ["UK plant health import rules (APHA)", "https://www.gov.uk/guidance/import-plants-and-plant-products-from-non-eu-countries-to-great-britain"],
  ["UKMTO advisories", "https://www.ukmto.org/"],
  ["JMIC (Joint Maritime Information Center) advisories", "https://www.ukmto.org/partner-products/jmic-products"],
  ["ICC IMB Piracy Reporting Centre", "https://www.icc-ccs.org/piracy-reporting-centre"],
  ["Lloyd's Joint War Committee listed areas", "https://www.lmalloyds.com/lma/jointwar"],
];
const ZOOM = { world: "0 -8 1000 352", europe: "420 20 220 120", mideast: "560 90 160 110", asia: "700 60 300 200", americas: "100 40 330 260" };
let SEL = new URLSearchParams(location.search).get("cp") || "hormuz", charts = {}, geo = null;

async function getJSON(p) { try { const r = await fetch(p + "?v=" + Date.now(), { cache: "no-store" }); if (!r.ok) throw 0; return await r.json(); } catch (e) { return null; } }

async function main() {
  const res = await Promise.all([getJSON("static/geo.json"), getJSON("fleets.json")].concat(FILES.map((f) => getJSON("data/" + f + ".json"))));
  geo = res[0]; D.fleetsFile = res[1] || {}; FILES.forEach((f, i) => (D[f] = res[i + 2] || {}));
  if (!geo || !geo.cps.some((c) => c.id === SEL)) SEL = "hormuz";
  const st = D.status || {}; const src = st.sources || {};
  const bad = Object.values(src).filter((s) => !s.ok).length;
  $("#runline").innerHTML = `Free public data · data last updated ${esc(fmtUK(st.run_uk))} (${esc(st.runner || "")}) · ` + (bad ? `<span class="stale">${bad} source${bad > 1 ? "s" : ""} stale</span>` : `<span class="okb">all sources OK</span>`);
  safe(metas); safe(ticker); safe(map); safe(detail); safe(kpis); safe(changed); safe(cptable); safe(energy); safe(bunkers); safe(freight);
  safe(equities); safe(route); safe(agri); safe(fert); safe(weather); safe(storms); safe(intel); safe(fx); safe(news); safe(sources); safe(live);
}
function safe(f) { try { f(); } catch (e) { console.error(f.name, e); } }

function metas() {
  const src = (D.status || {}).sources || {};
  $$(".meta[data-src]").forEach((el) => {
    const k = el.dataset.src; const s = src[k] || {}; const d = D[k] || {};
    if (k === "derived") { el.innerHTML = `Computed from the data on this page at ${esc(fmtUK(d.as_of))}.`; return; }
    const asof = d.as_of ? (String(d.as_of).length > 10 ? fmtUK(d.as_of) : fmtUK(d.as_of, true)) : "n/a";
    const staleTag = s.ok === false ? ` <span class="stale">stale</span> last good ${esc(fmtUK(s.last_ok_uk))}; latest attempt failed ${esc(fmtUK(s.last_fail_uk))}` : "";
    const srcName = (k === "ais" || k === "fleet-positions") ? "AISstream.io" : (d.source || s.label || k);
    el.innerHTML = `Source: <a href="${esc(s.url || "#")}" target="_blank" rel="noopener">${esc(srcName)}</a> · data as of ${esc(asof)} · checked ${esc(fmtUK(s.last_ok_uk || s.last_fail_uk))}${staleTag}`;
  });
}
const Q = (k) => ((D.markets || {}).q || {})[k];
function qStale(q) { if (!q) return ""; return (q.stale ? ' <span class="stale">stale</span>' : "") + (q.alt ? ` <span class="hint" title="${esc(q.alt)}">via ${esc(q.alt.split(" ")[0])}</span>` : ""); }

function ticker() {
  const items = [];
  const add = (lab, val, ch) => items.push(`<span><b>${lab}</b>${val} ${ch || ""}</span>`);
  [["BZ=F", "Brent", 2], ["CL=F", "WTI", 2], ["HO=F", "ULSD", 3], ["NG=F", "HH gas", 3]].forEach(([k, l, dp]) => { const q = Q(k); if (q) add(l, "$" + num(q.last, dp), pct(q.d)); });
  const b = D.baltic || {}; if (b.bdi) add("BDI", num(b.bdi.last, 0), pctS(b.bdi.d));
  const w = D.drewry || {}; if (w.composite) add("WCI", "$" + num(w.composite, 0), w.ww != null ? pct(w.ww, 0) : "");
  const r = ((D.bunkers || {}).hubs || {}).Rotterdam; if (r) add("RTM VLSFO", "$" + num(r.vlsfo[0], 1), "");
  [["ZW=F", "Wheat", 2], ["ZC=F", "Corn", 2], ["ZS=F", "Soy", 2], ["GBPUSD=X", "GBP/USD", 4], ["EURUSD=X", "EUR/USD", 4]].forEach(([k, l, dp]) => { const q = Q(k); if (q) add(l, num(q.last, dp), pct(q.d)); });
  if (b.eua) add("EUA", "€" + num(b.eua.last, 2), pctS(b.eua.d));
  $("#ticker").innerHTML = items.join("");
}

function cpStatus(id) { return ((D.derived || {}).status || {})[id] || "green"; }
function aisInfo(id) {
  const a = D.ais || {}; const src = ((D.status || {}).sources || {}).ais || {};
  const stale = src.ok === false;
  if (!a.cp) return { state: "none", stale };
  const row = id ? a.cp[id] : null;
  const tot = Object.values(a.cp).reduce((s, r) => s + ((r && r.vessels) || 0), 0);
  const wait = Object.values(a.cp).reduce((s, r) => s + ((r && r.waiting) || 0), 0);
  const reported = Object.values(a.cp).filter((r) => r && r.vessels > 0).length;
  const areas = Object.keys(a.cp).length;
  return { state: "ok", vessels: row ? row.vessels : null, waiting: row ? row.waiting : null,
    stale, as_of: a.as_of, seconds: a.seconds || 60, note: a.note, tot, wait, reported, areas };
}
function aisWhen(info) {
  return `${info.seconds || 60}s sample, ${fmtUK(info.as_of)}` + (info.stale ? ' <span class="stale">stale</span>' : "");
}
function px(lon, lat) { return [(lon + 180) / 360 * 1000, (75 - lat) / 360 * 1000]; }

function map() {
  const svg = $("#svgmap"); const pw = (D.portwatch || {}).cp || {};
  const maxW = Math.max(...Object.values(pw).map((c) => c.w || 0), 1);
  let h = "";
  for (let lon = -180; lon <= 180; lon += 30) { const [x] = px(lon, 0); h += `<line class="grat" x1="${x}" y1="-8" x2="${x}" y2="344"/>`; }
  for (let lat = -45; lat <= 75; lat += 30) { const [, y] = px(0, lat); h += `<line class="grat" x1="0" y1="${y}" x2="1000" y2="${y}"/>`; }
  h += `<path class="land" d="${geo.land}"/>`;
  geo.lanes.forEach((l) => { const c = pw[l.via] || {}; const w = 1.2 + 6 * Math.sqrt((c.w || 0) / maxW);
    h += `<path class="lane" data-cp="${l.via}" d="${l.d}" stroke="${COL[cpStatus(l.via)]}" stroke-width="${w.toFixed(2)}"><title>${esc(l.name)}: ${num(c.w)} transits/day at ${esc(c.name || l.via)} (7-day avg to ${esc(fmtUK(c.last_date))})</title></path>`; });
  const st = D.storms || {};
  (st.gdacs || []).forEach((s) => { if (s.lat == null) return; const [x, y] = px(s.lon, s.lat); if (y < -8 || y > 344) return;
    h += `<g class="storm"><text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central" font-size="15">🌀</text><text x="${x + 9}" y="${y - 8}" font-size="8" fill="#9fd3ff">${/^[A-Za-z]/.test(s.name || "") ? esc(s.name.replace(/-\d+$/, "")) : ""}</text><title>${esc(s.name)}: ${esc(s.sev || "")} (GDACS ${esc(s.level)}), as of ${esc(fmtUK(s.to))}</title></g>`; });
  geo.cps.forEach((c) => { const s = cpStatus(c.id); const on = c.id === SEL; const ai = aisInfo(c.id);
    const aisLab = ai.state === "ok" ? `, ${ai.vessels} ships in area now` : (ai.state === "none" ? ", AIS: no data" : "");
    h += `<g class="cp" data-cp="${c.id}" tabindex="0" role="button" aria-label="${esc(c.name)} ${WORD[s]}${esc(aisLab)}">` +
      (s === "red" ? `<circle class="pulse" cx="${c.x}" cy="${c.y}" r="8" fill="${COL.red}"/>` : "") +
      `<circle cx="${c.x}" cy="${c.y}" r="22" fill="transparent"/>` +
      `<circle class="mk" cx="${c.x}" cy="${c.y}" r="${on ? 9 : 7}" fill="${COL[s]}" stroke="${on ? "#fff" : "#0d1620"}" stroke-width="${on ? 3 : 2}"/>` +
      (ai.state === "ok" ? `<text class="aisn" x="${c.x}" y="${c.y - 13}" text-anchor="middle" font-size="9" stroke-width="3">${ai.vessels}</text>` : "") +
      `<text class="lbl" x="${c.x + c.lx * 0.8}" y="${c.y + c.ly * 0.8}" text-anchor="${c.anchor}" font-size="12" stroke-width="3.5">${esc(c.short)}</text></g>`; });
  svg.innerHTML = h;
  svg.querySelectorAll("[data-cp]").forEach((g) => { g.addEventListener("click", () => select(g.dataset.cp)); g.addEventListener("keydown", (e) => { if (e.key === "Enter") select(g.dataset.cp); }); });
  $$("#zoom button").forEach((b) => b.onclick = () => { $$("#zoom button").forEach((x) => x.classList.remove("on")); b.classList.add("on"); setZoom(b.dataset.z); });
  setZoom("world");
}
function setZoom(z) {
  const svg = $("#svgmap"); const narrow = window.innerWidth < 640;
  const box = narrow && z === "world" ? "235 15 650 315" : ZOOM[z]; svg.setAttribute("viewBox", box);
  const vb = box.split(" ").map(Number); const k = (vb[2] / 1000) * (narrow ? 1.7 : 1); // scale labels/markers for zoom and small screens
  svg.querySelectorAll(".cp .mk").forEach((m) => { const on = m.parentNode.dataset.cp === SEL; m.setAttribute("r", ((on ? 9 : 7) * Math.max(k, 0.32)).toFixed(2)); m.setAttribute("stroke-width", ((on ? 3 : 2) * Math.max(k, 0.32)).toFixed(2)); });
  svg.querySelectorAll(".cp .lbl").forEach((t) => { t.setAttribute("font-size", (12 * Math.max(k, 0.3)).toFixed(2)); t.setAttribute("stroke-width", (3.5 * Math.max(k, 0.3)).toFixed(2)); });
  svg.querySelectorAll(".cp .aisn").forEach((t) => { t.setAttribute("font-size", (9 * Math.max(k, 0.3)).toFixed(2)); t.setAttribute("stroke-width", (3 * Math.max(k, 0.3)).toFixed(2)); });
  svg.querySelectorAll(".cp .pulse").forEach((t) => t.setAttribute("r", (8 * Math.max(k, 0.32)).toFixed(2)));
  svg.querySelectorAll(".lane").forEach((l) => { if (!l.dataset.w) l.dataset.w = l.getAttribute("stroke-width"); l.setAttribute("stroke-width", (l.dataset.w * Math.max(k, 0.35)).toFixed(2)); });
  svg.querySelectorAll(".storm text").forEach((t) => { if (!t.dataset.fs) t.dataset.fs = t.getAttribute("font-size"); t.setAttribute("font-size", (t.dataset.fs * Math.max(k, 0.35)).toFixed(2)); });
}
function select(id) {
  SEL = id; const z = ($("#zoom button.on") || {}).dataset; map(); if (z) { $$("#zoom button").forEach((x) => x.classList.toggle("on", x.dataset.z === z.z)); setZoom(z.z); }
  detail(); cptable();
  if (window.innerWidth < 1100) $("#detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

function aisRow() {
  const ai = aisInfo(SEL);
  if (ai.state !== "ok") return `<dt>Ships in area now</dt><dd>AIS: no data</dd>`;
  const zero = ai.vessels === 0 ? ` <span class="hint">No vessels reported in this window. Coverage is terrestrial-heavy, so some areas — especially farther from the coast — often show low or zero counts.</span>` : "";
  return `<dt>Ships in area now</dt><dd><b>${num(ai.vessels, 0)}</b> (${num(ai.waiting, 0)} waiting/slow)<div class="hint">${aisWhen(ai)}. Counts are vessels reporting in that window, not a full census.</div>${zero}</dd>`;
}
function detail() {
  const sel = $("#cpsel");
  if (!sel.options.length) { sel.innerHTML = geo.cps.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join(""); sel.onchange = () => select(sel.value); }
  sel.value = SEL;
  const g = geo.cps.find((c) => c.id === SEL); const c = ((D.portwatch || {}).cp || {})[SEL] || {}; const s = cpStatus(SEL);
  const n = ((D.news || {}).cp || {})[SEL] || {}; const wx = ((D.weather || {}).points || {})[g.wx];
  $("#d-name").textContent = g.name;
  const r = (a, b) => (a && b ? pct((a / b - 1) * 100) : "n/a");
  let h = `<dl class="props">
    <dt>Status</dt><dd><span class="b ${s}">${WORD[s]}</span> ${n.flag ? `<span class="hint">headline flag: ${n.flag === "attacks" ? "attack reported" : "warning / diversion"}</span>` : ""}</dd>
    <dt>Transits, 7-day avg</dt><dd><b>${num(c.w)}</b> per day, to ${esc(fmtUK(c.last_date, true))}</dd>
    <dt>vs prior 7 days</dt><dd>${num(c.pw)} (${r(c.w, c.pw)})</dd>
    <dt>vs same week 2025</dt><dd>${num(c.yo)} (${r(c.w, c.yo)})</dd>
    <dt>30-day avg</dt><dd>${num(c.m30)} per day</dd>
    <dt>Latest day</dt><dd>${c.lastday ?? "n/a"} transits</dd>
    <dt>Mix, per day</dt><dd>${c.mix ? `${num(c.mix[0])} tanker · ${num(c.mix[1])} dry bulk · ${num(c.mix[2])} container · ${num(c.mix[3])} general cargo` : "n/a"}</dd>
    <dt>Capacity</dt><dd>${c.cap ? num(c.cap / 1e6, 2) + "m dwt per day" : "n/a"}</dd>
    <dt>What transits</dt><dd>${esc(g.what)}</dd>
    ${aisRow()}
  </dl>
  <h3>Weekly avg daily transits, 26 weeks</h3><div class="chartbox mini"><canvas id="cpchart"></canvas></div>`;
  if (wx) h += `<h3>Sea state, ${esc(g.wx)}</h3><div class="hint">` + wx.dates.map((d, i) => `${fmtUK(d)}: ${wx.wave[i] == null ? "wave n/a" : num(wx.wave[i]) + " m"}, gust ${Math.round(wx.gust[i])} kn`).join(" · ") + `</div>`;
  if (n.why && n.why.length) h += n.why.map((i) => `<div class="flag ${n.flag === "attacks" ? "red" : ""}">Flag trigger: <a href="${esc(i.l)}" target="_blank" rel="noopener">${esc(i.t)}</a> <span class="hint">${esc(i.s)}, ${esc(fmtUK(i.d))}</span></div>`).join("");
  h += `<h3>Latest dated reports</h3><ul class="news">` + (n.items || []).slice(0, 5).map(li).join("") + `</ul>`;
  $("#d-body").innerHTML = h;
  if (window.Chart && c.wk) {
    if (charts.cp) charts.cp.destroy();
    charts.cp = new Chart($("#cpchart"), { type: "bar", data: { labels: c.wkl.map((d) => fmtUK(d)), datasets: [{ data: c.wk, backgroundColor: c.wk.map((_, i) => i === c.wk.length - 1 ? COL[s] : "#3a5674") }] },
      options: baseOpts({ legend: false, ticks: 6 }) });
  }
}
function li(i) { return `<li><a href="${esc(i.l)}" target="_blank" rel="noopener">${esc(i.t)}</a><span class="m">${esc(i.s)} · ${esc(fmtUK(i.d))}</span></li>`; }
function baseOpts({ legend = true, ticks = 6, fmt } = {}) {
  return { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
    plugins: { legend: { display: legend, labels: { color: "#aab8c6", boxWidth: 10, font: { size: 11 } } }, tooltip: { callbacks: fmt ? { label: (c) => `${c.dataset.label || ""}: ${fmt(c.parsed.y)}` } : {} } },
    scales: { x: { ticks: { color: "#7d90a3", maxTicksLimit: ticks, maxRotation: 0, font: { size: 10 } }, grid: { color: "#1a2633" } },
              y: { ticks: { color: "#7d90a3", font: { size: 10 }, callback: fmt || undefined }, grid: { color: "#1a2633" } } } };
}

function kpis() {
  const b = D.baltic || {}, w = D.drewry || {}, k = [];
  const q = (s, lab, pre, dp) => { const x = Q(s); if (x) k.push([pre + num(x.last, dp), lab, `${pct(x.d)} day · ${pct(x.ytd)} YTD · ${fmtUK(x.time_uk)}${qStale(x)}`]); };
  q("BZ=F", "Brent, $/bbl", "$", 2); q("CL=F", "WTI, $/bbl", "$", 2);
  if (b.bdi) k.push([num(b.bdi.last, 0), "Baltic Dry Index", `${pctS(b.bdi.d)} day · ${pctS(b.bdi.y)} y/y · ${fmtUK(b.bdi.date)}`]);
  if (w.composite) k.push(["$" + num(w.composite, 0), "Drewry WCI /40ft", `${w.ww != null ? pct(w.ww, 0) : ""} w/w · ${w.yoy != null ? pct(w.yoy, 0) : ""} y/y · ${fmtUK(w.as_of)}`]);
  const r = ((D.bunkers || {}).hubs || {}).Rotterdam; if (r) k.push(["$" + num(r.vlsfo[0], 1), "Rotterdam VLSFO /t", `${esc(r.vlsfo[1] || "")} · ${fmtUK(r.date_iso)}`]);
  q("ZW=F", "Wheat, ¢/bu", "", 2); q("ZS=F", "Soybeans, ¢/bu", "", 2); q("GBPUSD=X", "GBP/USD", "", 4);
  if (b.eua) k.push(["€" + num(b.eua.last, 2), "EU carbon (EUA) /t", `${pctS(b.eua.d)} day · ${fmtUK(b.eua.date)}`]);
  const ai = aisInfo();
  if (ai.state === "ok") k.push([num(ai.tot, 0), "Ships in chokepoint areas", `${num(ai.wait, 0)} waiting/slow · ${ai.reported} of ${ai.areas} areas · ${aisWhen(ai)}`]);
  else k.push(["—", "Ships in chokepoint areas", "AIS: no data"]);
  $("#kpis").innerHTML = k.map(([v, l, d]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join("");
}

function changed() {
  const d = D.derived || {};
  $("#since").textContent = d.since ? `Compared with ${fmtUK(d.since)} (latest snapshot at least 20 hours old)` : "";
  const ch = d.changes || [];
  $("#chg").innerHTML = "<tr><th>Item</th><th class='n'>Then</th><th class='n'>Now</th><th class='n'>Change</th></tr>" +
    (ch.length ? ch.map((c) => c.status ? `<tr><td>${esc(c.k)}</td><td class="n"><span class="b ${c.frm}">${WORD[c.frm]}</span></td><td class="n"><span class="b ${c.to}">${WORD[c.to]}</span></td><td class="n">status</td></tr>`
      : `<tr><td>${esc(c.k)}</td><td class="n">${num(c.frm, c.frm < 10 ? 4 : 2)}</td><td class="n">${num(c.to, c.to < 10 ? 4 : 2)}</td><td class="n">${pct(c.pct, 2)}</td></tr>`).join("")
      : `<tr><td colspan="4" class="hint">No changes yet: the comparison builds up as hourly snapshots accumulate.</td></tr>`);
  const qs = (D.markets || {}).q || {};
  const mv = Object.entries(qs).filter(([k, v]) => v.grp !== "fx" && v.d != null && !v.stale).sort((a, b) => Math.abs(b[1].d) - Math.abs(a[1].d)).slice(0, 8);
  $("#movers").innerHTML = "<tr><th>Instrument</th><th class='n'>Last</th><th class='n'>Day</th><th class='n hide-s'>Time</th></tr>" +
    mv.map(([k, v]) => `<tr><td>${esc(v.name)}</td><td class="n">${num(v.last, v.last < 10 ? 3 : 2)}</td><td class="n">${pct(v.d, 2)}</td><td class="n hide-s">${esc(fmtUK(v.time_uk))}</td></tr>`).join("");
  $("#fresh").innerHTML = (d.new_headlines || []).map(li).join("") || "<li class='hint'>None in the last 20 hours.</li>";
}

function cptable() {
  const pw = (D.portwatch || {}).cp || {}, nw = (D.news || {}).cp || {};
  $("#cptable").innerHTML = "<tr><th>Chokepoint</th><th>Status</th><th class='n'>Per day</th><th class='n'>vs prior wk</th><th class='n'>vs yr ago</th><th class='n hide-s'>Tanker</th><th class='n hide-s'>Bulk</th><th class='n hide-s'>Container</th><th>Latest dated report</th></tr>" +
    geo.cps.map((g) => { const c = pw[g.id] || {}; const s = cpStatus(g.id); const it = ((nw[g.id] || {}).items || [])[0];
      return `<tr class="click ${g.id === SEL ? "sel" : ""}" data-cp="${g.id}"><td>${esc(g.name)}</td><td><span class="b ${s}">${WORD[s]}</span></td><td class="n">${num(c.w)}</td><td class="n">${c.pw ? pct((c.w / c.pw - 1) * 100) : "n/a"}</td><td class="n">${c.yo ? pct((c.w / c.yo - 1) * 100) : "n/a"}</td><td class="n hide-s">${c.mix ? num(c.mix[0]) : ""}</td><td class="n hide-s">${c.mix ? num(c.mix[1]) : ""}</td><td class="n hide-s">${c.mix ? num(c.mix[2]) : ""}</td><td>${it ? `<a href="${esc(it.l)}" target="_blank" rel="noopener">${esc(it.t)}</a> <span class="hint">${esc(it.s)}, ${esc(fmtUK(it.d))}</span>` : ""}</td></tr>`; }).join("");
  $$("#cptable tr.click").forEach((tr) => tr.onclick = () => { select(tr.dataset.cp); });
}

function lineChart(key, el, series, opts) {
  if (!window.Chart) return; if (charts[key]) charts[key].destroy();
  const palette = ["#4cc2ff", "#f5b041", "#36d399", "#c792ea"];
  const dates = Array.from(new Set(series.flatMap((s) => s.data.map((p) => p[0])))).sort();
  const ds = series.map((s, i) => { const m = Object.fromEntries(s.data); return { label: s.label, data: dates.map((d) => m[d] ?? null), borderColor: palette[i], backgroundColor: palette[i], borderWidth: 1.6, pointRadius: 0, spanGaps: true, tension: 0.15 }; });
  charts[key] = new Chart(el, { type: "line", data: { labels: dates.map((d) => fmtUK(d)), datasets: ds }, options: baseOpts(opts) });
}

function energy() {
  const draw = (v) => {
    const sets = v === "crude" ? [["BZ=F", "Brent $/bbl"], ["CL=F", "WTI $/bbl"]] : v === "ulsd" ? [["HO=F", "ULSD NY Harbor $/gal"]] : [["NG=F", "Henry Hub $/MMBtu"]];
    lineChart("e", $("#echart"), sets.filter(([k]) => Q(k)).map(([k, l]) => ({ label: l, data: Q(k).hist.slice(-95) })), { fmt: (x) => "$" + x.toFixed(v === "crude" ? 0 : 2) });
  };
  segs("#eseg", draw); draw("crude");
  $("#etable").innerHTML = "<tr><th>Energy future</th><th>Unit</th><th class='n'>Last</th><th class='n'>Day</th><th class='n'>1M</th><th class='n'>YTD</th><th class='n hide-s'>Time</th></tr>" +
    ["BZ=F", "CL=F", "HO=F", "NG=F"].map((k) => { const q = Q(k); return q ? `<tr><td>${esc(q.name)}${qStale(q)}</td><td>${esc(q.unit)}</td><td class="n">${num(q.last, q.last < 10 ? 3 : 2)}</td><td class="n">${pct(q.d, 2)}</td><td class="n">${pct(q.m1)}</td><td class="n">${pct(q.ytd)}</td><td class="n hide-s">${esc(fmtUK(q.time_uk))}</td></tr>` : ""; }).join("");
}
function segs(sel, fn) { $$(sel + " button").forEach((b) => b.onclick = () => { $$(sel + " button").forEach((x) => x.classList.remove("on")); b.classList.add("on"); fn(b.dataset.v); }); }

const HUBS = ["Rotterdam", "Singapore", "Fujairah", "Houston", "Hong Kong", "Santos", "New York", "LA / Long Beach", "Global 20 Ports Average", "EMEA Average"];
function bunkers() {
  const hb = (D.bunkers || {}).hubs || {};
  const cell = (v) => v && v[0] != null ? `$${num(v[0], 2)} <span class="${String(v[1]).startsWith("-") ? "dn" : "up"}">${/\d/.test(v[1] || "") ? esc(v[1]) : ""}</span>` : "n/a";
  $("#btable").innerHTML = "<tr><th>Hub</th><th class='n'>VLSFO</th><th class='n'>HSFO</th><th class='n'>MGO</th><th class='n hide-s'>Date</th></tr>" +
    HUBS.filter((h) => hb[h]).map((h) => `<tr><td><a href="${esc(hb[h].href)}" target="_blank" rel="noopener">${esc(h)}</a></td><td class="n">${cell(hb[h].vlsfo)}</td><td class="n">${cell(hb[h].hsfo)}</td><td class="n">${cell(hb[h].mgo)}</td><td class="n hide-s">${esc(fmtUK(hb[h].date_iso))}</td></tr>`).join("");
}

function freight() {
  const b = D.baltic || {}, w = D.drewry || {}, sg = b.seg || {};
  const row = (n, p, d) => `<tr><td>${n}</td><td class="n">${p}</td><td class="n">${d}</td></tr>`;
  $("#baltic").innerHTML = "<tr><th>Index</th><th class='n'>Points</th><th class='n'>Day</th></tr>" + (b.bdi ? row("Baltic Dry (BDI)", num(b.bdi.last, 0), pctS(b.bdi.d)) : "") +
    [["capesize", "Capesize"], ["panamax", "Panamax (grain, coal)"], ["supramax", "Supramax"], ["handysize", "Handysize"]].map(([k, n]) => sg[k] ? row(n, num(sg[k].points, 0), pct(sg[k].d, 1)) : row(n, '<span class="hint">not in free summary</span>', "")).join("");
  $("#wci").innerHTML = "<tr><th>Route</th><th class='n'>$/40ft</th><th class='n'>w/w</th></tr>" + (w.composite ? row("Composite", "$" + num(w.composite, 0), w.ww != null ? pct(w.ww, 0) : "") : "") +
    Object.entries(w.routes || {}).map(([k, v]) => row(esc(k), "$" + num(v.usd, 0), pct(v.ww, 0))).join("");
  $("#freightnote").innerHTML = [b.bdi ? `BDI ${pctS(b.bdi.m1)} over 1 month, ${pctS(b.bdi.y)} year on year.` : "", w.outlook ? esc(w.outlook) : "", "Time-charter hire in $/day by size is not available free."].join(" ");
}
function equities() {
  $("#eqtable").innerHTML = "<tr><th>Name</th><th>Ccy</th><th class='n'>Last</th><th class='n'>Day</th><th class='n'>1M</th><th class='n'>YTD</th><th class='n hide-s'>Time</th></tr>" +
    Object.entries((D.markets || {}).q || {}).filter(([k, v]) => v.grp === "equity").map(([k, q]) => `<tr><td>${esc(q.name)}${qStale(q)}</td><td>${esc(q.unit)}</td><td class="n">${num(q.last, 2)}</td><td class="n">${pct(q.d, 2)}</td><td class="n">${pct(q.m1)}</td><td class="n">${pct(q.ytd)}</td><td class="n hide-s">${esc(fmtUK(q.time_uk))}</td></tr>`).join("");
}

function route() {
  const hb = (D.bunkers || {}).hubs || {};
  const fuels = [["Rotterdam", "rtm"], ["Singapore", "sin"], ["Fujairah", "fuj"], ["Houston", "hou"], ["Global 20 Ports Average", "g20"]].filter(([h]) => hb[h] && hb[h].vlsfo[0]);
  $("#r-route").innerHTML = ROUTES.map((r, i) => `<option value="${i}">${r.o} → ${r.d}</option>`).join("");
  $("#r-fuel").innerHTML = fuels.map(([h]) => `<option value="${esc(h)}">${esc(h)} VLSFO $${num(hb[h].vlsfo[0], 2)}/t (${esc(fmtUK(hb[h].date_iso))})</option>`).join("") || `<option value="">No bunker data</option>`;
  const eua = ((D.baltic || {}).eua || {}).last; const eurusd = (Q("EURUSD=X") || {}).last;
  const calc = () => {
    const r = ROUTES[+$("#r-route").value || 0]; const fp = ((hb[$("#r-fuel").value] || {}).vlsfo || [0])[0];
    const sp = Math.max(1, parseFloat($("#r-speed").value) || 12.5), cn = Math.max(0, parseFloat($("#r-cons").value) || 0), hr = Math.max(0, parseFloat($("#r-hire").value) || 0);
    const wr = Math.max(0, parseFloat($("#r-wr").value) || 0) / 100, hv = Math.max(0, parseFloat($("#r-hv").value) || 0) * 1e6;
    const redSea = (ids) => ids.some((x) => x === "bab" || x === "suez");
    const f = (nm, ids) => { const days = nm / (sp * 24), t = days * cn, co2 = t * 3.151, ets = r.eu && eua && eurusd ? co2 * 0.5 * eua * eurusd : 0;
      const fuel = t * fp, hire = days * hr, war = redSea(ids) || ids.includes("hormuz") ? wr * hv : 0; return { days, t, co2, ets, fuel, hire, war, total: fuel + ets + hire + war }; };
    const A = f(r.main, r.mainCps), B = f(r.alt, r.altCps);
    const worst = (ids) => { for (const k of ["red", "amber", "green"]) { const hit = ids.filter((id) => cpStatus(id) === k); if (hit.length) return `<span class="b ${k}">${WORD[k]}</span> ${hit.map((id) => geo.cps.find((c) => c.id === id).short).join(", ")}`; } return ""; };
    const n0 = (n) => Math.round(n).toLocaleString("en-GB");
    const rw = (l, a, b, fm) => `<tr><td>${l}</td><td class="n">${fm(a)}</td><td class="n">${fm(b)}</td><td class="n">${b - a >= 0 ? "+" : "−"}${fm(Math.abs(b - a))}</td></tr>`;
    $("#rtable").innerHTML = `<tr><th>Measure</th><th class="n">Via ${r.mainName}</th><th class="n">Via ${r.altName}</th><th class="n">Difference</th></tr>` +
      rw("Distance, nm", r.main, r.alt, n0) + rw("Days at sea", A.days, B.days, (n) => n.toFixed(1)) + rw("Fuel burned, t", A.t, B.t, n0) + rw("Fuel cost", A.fuel, B.fuel, money) +
      rw("CO2, t", A.co2, B.co2, n0) + rw("EU ETS cost", A.ets, B.ets, money) + rw("Hire cost", A.hire, B.hire, money) + rw("War-risk premium", A.war, B.war, money) + rw("<b>Total of the above</b>", A.total, B.total, (n) => "<b>" + money(n) + "</b>") +
      `<tr><td>Chokepoint status</td><td class="n">${worst(r.mainCps)}</td><td class="n">${worst(r.altCps)}</td><td></td></tr>`;
    $("#rnote").innerHTML = `Distances: searoute model (Eurostat maritime network), Arctic routes excluded. CO2 at 3.151 t per t VLSFO (IMO factor). EU ETS: 50% of emissions on voyages into or out of the EU, 100% phase-in for 2026, at €${eua ? num(eua, 2) : "n/a"}/t (${esc(fmtUK(((D.baltic || {}).eua || {}).date))}) and EUR/USD ${eurusd ? num(eurusd, 4) : "n/a"}; UK and non-EU legs carry no EU ETS cost here. War-risk premium is applied once to routes through Bab el-Mandeb, Suez or Hormuz using your own figure. Excludes canal tolls, port costs and FuelEU Maritime. Defaults are a generic bulk carrier; enter your own ship's figures.`;
  };
  ["#r-route", "#r-fuel", "#r-speed", "#r-cons", "#r-hire", "#r-wr", "#r-hv"].forEach((s) => { $(s).oninput = calc; $(s).onchange = calc; });
  calc();
}

function agri() {
  const G = { grains: [["ZW=F", "Wheat SRW"], ["KE=F", "Wheat HRW"], ["ZC=F", "Corn"], ["ZR=F", "Rough rice"]], oilseeds: [["ZS=F", "Soybeans"], ["ZM=F", "Soy meal"], ["ZL=F", "Soy oil"]], softs: [["SB=F", "Sugar"], ["KC=F", "Coffee"], ["CC=F", "Cocoa"], ["CT=F", "Cotton"]] };
  const draw = (v) => lineChart("a", $("#achart"), G[v].filter(([k]) => Q(k)).map(([k, l]) => { const h = Q(k).hist; const b = h[0][1]; return { label: l, data: h.map(([d, x]) => [d, +(x / b * 100).toFixed(1)]) }; }), { fmt: (x) => x.toFixed(0) });
  segs("#aseg", draw); draw("grains");
  $("#atable").innerHTML = "<tr><th>Commodity</th><th>Unit</th><th class='n'>Last</th><th class='n'>Day</th><th class='n'>1M</th><th class='n'>YTD</th><th class='n hide-s'>Time</th></tr>" +
    Object.entries((D.markets || {}).q || {}).filter(([k, v]) => v.grp === "agri").map(([k, q]) => `<tr><td>${esc(q.name)}${qStale(q)}</td><td>${esc(q.unit)}</td><td class="n">${num(q.last, 2)}</td><td class="n">${pct(q.d, 2)}</td><td class="n">${pct(q.m1)}</td><td class="n">${pct(q.ytd)}</td><td class="n hide-s">${esc(fmtUK(q.time_uk))}</td></tr>`).join("");
}
function fert() {
  const s = (D.worldbank || {}).series || {};
  const order = ["DAP", "Urea", "Potassium chloride", "TSP", "Phosphate rock", "Wheat, US HRW", "Maize", "Soybeans", "Rice, Thai 5%", "Natural gas, Europe"];
  $("#ftable").innerHTML = "<tr><th>Series</th><th class='n'>Latest</th><th class='n'>Prev</th><th class='n'>y/y</th></tr>" +
    order.filter((k) => s[k]).map((k) => { const v = s[k]; return `<tr><td>${esc(v.label)} <span class="hint">${esc(v.unit)}, ${esc(fmtUK(v.month))}</span></td><td class="n">${num(v.last, 1)}</td><td class="n">${num(v.prev, 1)}</td><td class="n">${pct((v.last / v.yago - 1) * 100)}</td></tr>`; }).join("");
}
function weather() {
  const p = (D.weather || {}).points || {}; const ks = Object.keys(p); if (!ks.length) return;
  const dates = p[ks[0]].dates;
  $("#wtable").innerHTML = "<tr><th>Location</th>" + dates.map((d) => `<th class="n">${esc(fmtUK(d))}</th>`).join("") + "</tr>" +
    ks.map((k) => `<tr><td>${esc(k)}</td>` + p[k].dates.map((d, i) => { const w = p[k].wave[i], g = p[k].gust[i]; const hl = (g >= 34 || (w != null && w >= 4)) ? " hl" : "";
      return `<td class="n${hl}">${w == null ? "n/a" : num(w, 1) + " m"} · ${Math.round(g)} kn</td>`; }).join("") + "</tr>").join("");
}
function storms() {
  const s = D.storms || {}; const L = [];
  (s.gdacs || []).forEach((x) => L.push(`<li><b>${esc(x.name)}</b> <span class="b ${x.level === "Red" ? "red" : x.level === "Orange" ? "amber" : "green"}">${esc(x.level)}</span> ${esc(x.sev || "")}${x.countries ? " · near " + esc(x.countries) : ""} · ${num(x.lat, 1)}°, ${num(x.lon, 1)}° · as of ${esc(fmtUK(x.to))} <a href="${esc(x.link)}" target="_blank" rel="noopener">GDACS</a></li>`));
  (s.nhc || []).forEach((x) => L.push(`<li><b>${esc(x.name)}</b> (${esc(x.cls)}, ${esc(x.kt)} kt) at ${esc(x.pos)}, moving ${esc(x.dir)}° at ${esc(x.spd)} kt · NHC/CPHC advisory ${esc(fmtUK(x.updated_uk))}</li>`));
  $("#stormlist").innerHTML = L.join("") || "<li class='hint'>No active tropical cyclones in GDACS or NHC feeds.</li>";
}
function intel() {
  const tabs = (D.news || {}).tabs || {};
  const draw = (v) => {
    $("#tablist").innerHTML = (tabs[v] || []).map(li).join("") || "<li class='hint'>No dated items found in the last three weeks.</li>";
    $("#tabextra").innerHTML = v === "law" ? `<h3>Primary sources: IMO, EU ETS / FuelEU, MCA, DfT, sanctions, P&amp;I, courts, GAFTA, plant health</h3><ul class="news two">` + REFS.map(([t, u]) => `<li><a href="${u}" target="_blank" rel="noopener">${esc(t)}</a><span class="m">${esc(new URL(u).hostname)}</span></li>`).join("") + "</ul>"
      : v === "ports" ? `<p class="note">Headlines naming Felixstowe, Southampton, Rotterdam, Antwerp-Bruges, Immingham, Liverpool or Hamburg with strike, congestion, closure or delay terms, last three weeks. Live berth and congestion counts are not available free.</p>`
      : v === "risk" ? `<p class="note">The <a href="#risk">war-risk and conflict map</a> sits above this list, with JWC listed areas, naval advisories and recent UKMTO incidents. Official warnings: <a href="https://www.ukmto.org/" target="_blank" rel="noopener">UKMTO</a>. For IMB piracy reports use their <a href="https://icc-ccs.org/map/" target="_blank" rel="noopener">live map</a> (we do not copy that data).</p>` : "";
  };
  segs("#tseg", draw); draw("risk");
}
function fx() {
  const k = [];
  ["GBPUSD=X", "EURUSD=X", "GBPEUR=X"].forEach((s) => { const q = Q(s); if (q) k.push(`<div class="kpi"><div class="l">${esc(q.name)}</div><div class="v">${num(q.last, 4)}</div><div class="d">${pct(q.d, 2)} day · ${esc(fmtUK(q.time_uk))}${qStale(q)}</div></div>`); });
  const e = (D.baltic || {}).eua; if (e) k.push(`<div class="kpi"><div class="l">EU carbon (EUA) /t</div><div class="v">€${num(e.last, 2)}</div><div class="d">${pctS(e.d)} day · ${pctS(e.y)} y/y · ${esc(fmtUK(e.date))}</div></div>`);
  $("#fxk").innerHTML = k.join("");
  lineChart("fx", $("#fxchart"), [["GBPUSD=X", "GBP/USD"], ["EURUSD=X", "EUR/USD"]].filter(([s]) => Q(s)).map(([s, l]) => ({ label: l, data: Q(s).hist.slice(-95) })), { fmt: (x) => x.toFixed(3) });
}
function news() { $("#feed").innerHTML = ((D.news || {}).feed || []).map(li).join(""); }
function sources() {
  const src = (D.status || {}).sources || {};
  $("#srctable").innerHTML = "<tr><th>Data</th><th>Source</th><th>Status</th><th class='n'>Data as of</th><th class='n'>Last success</th><th class='hide-s'>Note</th></tr>" +
    Object.entries(src).map(([k, s]) => `<tr><td>${esc(s.label)}</td><td><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(new URL(s.url).hostname)}</a></td><td>${s.ok ? '<span class="okb">OK</span>' : '<span class="stale">stale</span>'}</td><td class="n">${esc(String(s.as_of || "").length > 10 ? fmtUK(s.as_of) : fmtUK(s.as_of, true))}</td><td class="n">${esc(fmtUK(s.last_ok_uk))}</td><td class="hide-s hint">${k === "markets" ? esc("Served by: " + ((D.markets || {}).used || []).join(", ") + ". ") : ""}${s.ok ? "" : esc((s.error || "").slice(0, 120))}</td></tr>`).join("");
}
// Live ship traffic: VesselFinder embed for "All traffic" (official aismap.js uses document.write,
// so we build the same iframe URL ourselves to allow recentring). "Fleet" is our Leaflet map of
// last-known positions from the hourly AISstream sample — the VesselFinder widget cannot be
// filtered by company.
const LIVE = { world: [20, 0, 3], suez: [30.0, 32.55, 9], bab: [12.6, 43.35, 9], hormuz: [26.4, 56.4, 8], malacca: [2.6, 101.2, 7], panama: [9.1, -79.7, 9],
  gib: [35.95, -5.5, 9], dover: [51.0, 1.45, 9], bosporus: [41.12, 29.06, 11], cape: [-34.4, 18.4, 7] };
const LIVE_ORDER = ["world", "suez", "bab", "hormuz", "malacca", "panama", "gib", "dover", "bosporus", "cape"];
let liveView = "all", fleetSel = "borchard", fleetMap = null, fleetLayer = null;
function liveSrc(id) {
  const rec = LIVE[id] || LIVE.world; const [lat, lon, zoom] = rec; const el = $("#livewrap"); const h = Math.max(400, Math.round(el.clientHeight || 450));
  // VesselFinder's widest zoom is 3. Keep World at 3; only tighten chokepoint zooms on a narrow phone.
  const z = (id === "world") ? 3 : Math.max(3, zoom - (window.innerWidth < 640 ? 1 : 0));
  const q = { zoom: z, lat, lon, width: "100%", height: h, names: "false", track: "false", fleet: "false", fleet_name: "false",
    fleet_hide_old_positions: "false", clicktoact: "true", store_pos: "false", ra: location.href };
  return "https://www.vesselfinder.com/aismap?" + Object.entries(q).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");
}
function fleetList() { return ((D.fleetsFile || {}).fleets) || []; }
function fleetById(id) { return fleetList().find((f) => f.id === id) || fleetList()[0] || null; }
function coverageLine(f) {
  if (!f) return "";
  const n = (f.ships || []).length, m = (f.ships || []).filter((s) => s.mmsi).length;
  const exp = f.expected;
  let cov;
  if (exp && n >= exp) cov = `${n} listed` + (n > exp ? ` (official operated fleet is about ${exp}; some may have left the fleet)` : ` of ${exp}`);
  else if (exp) cov = `About ${n} of ~${exp} ships listed`;
  else cov = `${n} ships listed` + (f.expected_note ? `. ${f.expected_note}` : "");
  cov += ` · ${m} with an MMSI, so they can be looked up on AIS`;
  if (f.note) cov += `. ${f.note}`;
  return cov;
}
function isStalePos(row) {
  const hours = (D["fleet-positions"] || {}).stale_after_hours || 6;
  const age = ageHours(row && row.seen_uk);
  return age == null || age > hours;
}
function showAllTraffic(id) {
  fleetMap = null; fleetLayer = null;
  const w = $("#livewrap");
  w.innerHTML = `<iframe name="vesselfinder" title="Live ship traffic map (VesselFinder)" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" src="${esc(liveSrc(id || "world"))}"></iframe>`;
  $("#livenote").innerHTML = `Live map provided by VesselFinder (third-party embed). World is the default, at the widest zoom the widget allows (level 3). Tap or click the map to activate it, then zoom or drag; positions come from VesselFinder's AIS network and are not stored by this site. <a href="https://www.vesselfinder.com" target="_blank" rel="noopener">vesselfinder.com</a>`;
}

function xyToLatLng(x, y) { return [75 - y / 1000 * 360, x / 1000 * 360 - 180]; }
function landPolygons() {
  const d = (geo && geo.land) || "";
  const group = L.layerGroup();
  const style = { color: "#2a3c50", weight: 0.6, fillColor: "#1c2a38", fillOpacity: 1, interactive: false };
  let ring = [], cmd = "";
  const tokens = d.match(/[MLZ]|-?\d+(?:\.\d+)?/g) || [];
  for (let i = 0; i < tokens.length; ) {
    const t = tokens[i];
    if (t === "M" || t === "L" || t === "Z") { cmd = t; i++; if (cmd === "Z") { if (ring.length > 2) L.polygon(ring, style).addTo(group); ring = []; } continue; }
    const x = parseFloat(tokens[i]), y = parseFloat(tokens[i + 1]); i += 2;
    if (!isFinite(x) || !isFinite(y)) continue;
    if (cmd === "M") { if (ring.length > 2) L.polygon(ring, style).addTo(group); ring = [xyToLatLng(x, y)]; cmd = "L"; }
    else ring.push(xyToLatLng(x, y));
  }
  if (ring.length > 2) L.polygon(ring, style).addTo(group);
  return group;
}
function showFleet(id) {
  const f = fleetById(id); if (!f) { $("#livewrap").innerHTML = `<div class="hint livehold">No fleets.json loaded.</div>`; return; }
  fleetSel = f.id;
  $("#fleetsel").value = f.id;
  $("#fleetcov").textContent = coverageLine(f);
  const pos = ((D["fleet-positions"] || {}).ships) || {};
  const src = ((D.status || {}).sources || {})["fleet-positions"] || {};
  const asof = (D["fleet-positions"] || {}).as_of;
  const seenRun = new Set((D["fleet-positions"] || {}).seen || []);
  const rows = (f.ships || []).map((s) => {
    const m = s.mmsi ? String(s.mmsi) : "";
    const p = (m && pos[m]) || (s.imo && Object.values(pos).find((x) => String(x.imo || "") === String(s.imo))) || null;
    const heard = !!(p && p.lat != null && p.lon != null);
    const thisRun = !!(m && seenRun.has(m));
    return { ship: s, pos: p, heard, thisRun, stale: heard && isStalePos(p) };
  });
  rows.sort((a, b) => (b.thisRun - a.thisRun) || (b.heard - a.heard) || String(a.ship.name || "").localeCompare(String(b.ship.name || "")));
  const onMap = rows.filter((r) => r.heard);
  const notSeen = rows.filter((r) => !r.thisRun);
  $("#fleetstats").innerHTML = onMap.length
    ? `<b>${onMap.length}</b> of ${rows.length} ships have a last-known position · <b>${rows.filter((r) => r.thisRun).length}</b> heard in the latest sample · ${esc(fmtUK(asof) || "no sample yet")}` + (src.ok === false ? ' <span class="stale">stale</span>' : "")
    : `No last-known positions yet for this fleet. The hourly refresh plots ships after it has heard them on AISstream. ${esc(fmtUK(asof) || "")}`;
  const dest = (p) => (p && p.destination) ? esc(p.destination) : "n/a";
  const spd = (p) => (p && p.sog != null && !isNaN(p.sog)) ? num(p.sog, 1) + " kn" : "n/a";
  $("#fleettable").innerHTML = "<tr><th>Ship</th><th>Status</th><th class='n'>Speed</th><th>Destination</th><th class='n'>Last seen</th><th class='hide-s'>IMO / MMSI</th></tr>" +
    rows.map((r) => {
      const s = r.ship, p = r.pos;
      const st = !s.mmsi ? "No MMSI yet" : r.thisRun ? "Heard this sample" : r.heard ? (r.stale ? "Stale last-known" : "Last-known, not this sample") : "Not seen";
      return `<tr class="${r.heard ? "click" : ""}" data-mmsi="${esc(s.mmsi || "")}"><td>${esc(s.name || "Unnamed")}</td><td>${esc(st)}</td><td class="n">${r.heard ? spd(p) : "—"}</td><td>${r.heard ? dest(p) : "—"}</td><td class="n">${r.heard ? esc(fmtUK(p.seen_uk)) : "—"}${r.stale ? ' <span class="stale">stale</span>' : ""}</td><td class="hide-s hint">${esc(s.imo || "—")} / ${esc(s.mmsi || "—")}</td></tr>`;
    }).join("");
  // Leaflet map of last-known positions only
  if (typeof L === "undefined") {
    $("#livewrap").innerHTML = `<div class="hint livehold">The map library failed to load, but the ship list is below.</div>`;
    $("#livenote").innerHTML = fleetNote();
    return;
  }
  $("#livewrap").innerHTML = `<div id="fmap" role="img" aria-label="Last-known positions of the selected fleet"></div>`;
  if (fleetMap && fleetMap.remove) { try { fleetMap.remove(); } catch (e) {} }
  fleetMap = L.map("fmap", { worldCopyJump: true, scrollWheelZoom: true, minZoom: 1, maxZoom: 8, attributionControl: true }).setView([20, 0], 2);
  fleetMap.getContainer().style.background = "#0d1620";
  // Use this site's own land outlines (same geo.json as the chokepoint map) so the
  // basemap needs no tile API key. Projection on that file is x=(lon+180)/360*1000, y=(75-lat)/360*1000.
  landPolygons().addTo(fleetMap);
  L.control.attribution({ prefix: false }).addAttribution("Land outlines from this site's world map").addTo(fleetMap);
  fleetLayer = L.layerGroup().addTo(fleetMap);
  const pts = [];
  onMap.forEach((r) => {
    const p = r.pos;
    const icon = L.divIcon({ className: "", html: `<div class="fleetdot${r.stale ? " stale" : ""}"></div>`, iconSize: [14, 14], iconAnchor: [7, 7] });
    const mk = L.marker([p.lat, p.lon], { icon, title: r.ship.name || "" });
    mk.bindPopup(`<b>${esc(r.ship.name || "Unnamed")}</b>Speed ${spd(p)} · dest ${dest(p)}<br>Last seen ${esc(fmtUK(p.seen_uk))}${r.stale ? ' <span class="stale">stale</span>' : ""}`);
    mk.addTo(fleetLayer);
    pts.push([p.lat, p.lon]);
  });
  if (pts.length) {
    const b = L.latLngBounds(pts);
    fleetMap.fitBounds(b.pad(0.25), { maxZoom: 8, padding: [24, 24] });
  }
  setTimeout(() => { if (fleetMap) fleetMap.invalidateSize(); }, 50);
  $("#fleettable").querySelectorAll("tr[data-mmsi]").forEach((tr) => {
    tr.onclick = () => {
      const m = tr.getAttribute("data-mmsi"); const p = m && pos[m];
      if (!p || p.lat == null || !fleetMap) return;
      fleetMap.setView([p.lat, p.lon], Math.max(fleetMap.getZoom(), 7));
    };
  });
  $("#livenote").innerHTML = fleetNote();
}
function fleetNote() {
  const d = D["fleet-positions"] || {};
  return `This is our map of the selected fleet's last-known positions, from a free AISstream terrestrial sample (typically within about 200 km of a shore station), not a live feed. ${esc(d.note || "Ships far offshore, or silent during the sample window, may be missing or stale.")} The list is not a complete census — see the coverage line above. Add ships by editing <code>fleets.json</code> (README). All traffic (VesselFinder) is a separate view and cannot be filtered by company.`;
}
function fillFleetSelect(filter) {
  const q = (filter || "").trim().toLowerCase();
  const sel = $("#fleetsel");
  const items = fleetList().filter((f) => {
    if (!q) return true;
    const blob = [f.name, f.id, ...(f.aliases || [])].join(" ").toLowerCase();
    return blob.includes(q);
  });
  sel.innerHTML = (items.length ? items : fleetList()).map((f) => `<option value="${esc(f.id)}">${esc(f.name)}</option>`).join("") || `<option value="">No fleets</option>`;
  if (items.some((f) => f.id === fleetSel)) sel.value = fleetSel;
  else if (items[0]) fleetSel = items[0].id, sel.value = fleetSel;
}
function live() {
  const sel = $("#livesel");
  const cpName = (id) => id === "world" ? "World" : ((geo.cps.find((c) => c.id === id) || { name: id }).name);
  sel.innerHTML = LIVE_ORDER.map((id) => `<option value="${id}">${esc(cpName(id))}</option>`).join("");
  sel.value = "world";
  fillFleetSelect("");
  if (fleetById("borchard")) { fleetSel = "borchard"; $("#fleetsel").value = "borchard"; }
  const setView = (v) => {
    liveView = v;
    $("#allcontrols").hidden = v !== "all";
    $("#fleetcontrols").hidden = v !== "fleet";
    $("#fleetpanel").hidden = v !== "fleet";
    const meta = document.querySelector('#live .meta[data-src="fleet-positions"]');
    if (meta) meta.hidden = v !== "fleet";
    if (v === "all") showAllTraffic(sel.value || "world");
    else showFleet(fleetSel);
  };
  segs("#liveview", setView);
  sel.onchange = () => { if (liveView === "all") showAllTraffic(sel.value); };
  $("#fleetsel").onchange = () => { fleetSel = $("#fleetsel").value; if (liveView === "fleet") showFleet(fleetSel); };
  $("#fleetq").oninput = () => { fillFleetSelect($("#fleetq").value); if (liveView === "fleet") showFleet($("#fleetsel").value); };
  setView("all");
}
document.addEventListener("DOMContentLoaded", main);
