/* Dedicated war-risk map and underwriting panel. Loads data/risk/*.json only.
   Kept out of app.js so fleet-tracker work on the shared file is not disturbed. */
"use strict";
(function () {
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = window.esc || ((s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
  const fmtUK = window.fmtUK || function (s, withYear) {
    if (!s) return "n/a";
    const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
    if (!m) return String(s);
    const d = `${+m[3]} ${MON[+m[2] - 1]}${withYear ? " " + m[1] : ""}`;
    return m[4] ? `${d} ${m[4]}:${m[5]} UK` : d;
  };

  const R = {};
  let map, layers = { jwc: null, advisory: null, incidents: null };
  let days = 30;

  function incClass(t) {
    t = (t || "").toLowerCase();
    if (/attack|hijack|kidnap|illegal boarding|fired/.test(t)) return "attack";
    if (/advisory|notice|security notification/.test(t)) return "advisory";
    return "watch";
  }
  function daysAgo(s) {
    const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
    if (!m) return 9999;
    const nowUK = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/London" }));
    const t = new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
    return (nowUK - t) / 8.64e7;
  }
  function staleTag(s, afterDays) {
    return daysAgo(s) > afterDays ? ' <span class="stale">stale</span>' : "";
  }
  async function getJSON(p) {
    try {
      const r = await fetch(p + "?v=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw 0;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  function showDetail(html) {
    const el = $("#risk-detail");
    if (el) el.innerHTML = html;
  }
  function levelBadge(lv) {
    if (!lv) return "";
    const k = String(lv).toLowerCase();
    return `<span class="lvl ${esc(k)}">${esc(lv)}</span>`;
  }
  function zoneHtml(p) {
    return `<h3>${esc(p.name)}</h3>
      ${p.threat_level ? `<p>${levelBadge(p.threat_level)} ${esc(p.threat_as_of_note || p.threat_as_of || "")}</p>` : ""}
      <p>${esc(p.meaning || "")}</p>
      ${p.detail ? `<p>${esc(p.detail)}</p>` : ""}
      <p class="hint">${esc(p.circular || p.source || "")}${p.circular && p.source ? " · " + esc(p.source) : ""}</p>
      <p class="hint">The wording of the official circular or advisory prevails over this drawing. Not insurance or routing advice.</p>`;
  }
  function incHtml(it) {
    return `<h3>UKMTO ${esc(it.id != null ? it.id : "")} · ${esc(it.type)}</h3>
      <p><b>${esc(fmtUK(it.when_uk, true))}</b>${it.place ? " · " + esc(it.place) : ""}${it.vessel_type ? " · " + esc(it.vessel_type) : ""}</p>
      <p>${esc(it.details || "No narrative in the feed.")}</p>
      <p class="hint">Contains public sector information licensed under the <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/" target="_blank" rel="noopener">Open Government Licence v3.0</a>. Official source: <a href="https://www.ukmto.org/recent-incidents" target="_blank" rel="noopener">UKMTO recent incidents</a>. This site is not associated with or endorsed by UKMTO or the UK Ministry of Defence.</p>`;
  }

  function buildMap() {
    const el = $("#riskmap");
    if (!el || typeof L === "undefined") {
      if (el) el.innerHTML = `<div class="hint livehold" style="display:flex;align-items:center;justify-content:center;height:100%">The map library failed to load. The lists below still work.</div>`;
      return;
    }
    if (map && map.remove) { try { map.remove(); } catch (e) {} }
    map = L.map(el, { worldCopyJump: true, scrollWheelZoom: true, maxBoundsViscosity: 0.4 }).setView([22, 40], 3);
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
      attribution: 'Tiles &copy; <a href="https://www.esri.com/">Esri</a>',
      maxZoom: 16,
    }).addTo(map);
    map.createPane("paneAdv"); map.getPane("paneAdv").style.zIndex = 350;
    map.createPane("paneJwc"); map.getPane("paneJwc").style.zIndex = 400;
    map.createPane("paneInc"); map.getPane("paneInc").style.zIndex = 650;

    const zones = R.zones || { features: [] };
    layers.advisory = L.geoJSON(zones, {
      pane: "paneAdv",
      filter: (f) => (f.properties || {}).layer === "advisory",
      style: { color: "#f5b041", weight: 1, dashArray: "4 3", fillColor: "#f5b041", fillOpacity: 0.16 },
      onEachFeature: (f, l) => {
        l.on("click", () => showDetail(zoneHtml(f.properties || {})));
        l.bindTooltip((f.properties || {}).name || "", { sticky: true, opacity: 0.9 });
      },
    });
    layers.jwc = L.geoJSON(zones, {
      pane: "paneJwc",
      filter: (f) => (f.properties || {}).layer === "jwc",
      style: { color: "#ff5c5c", weight: 1, fillColor: "#ff5c5c", fillOpacity: 0.28 },
      onEachFeature: (f, l) => {
        l.on("click", () => showDetail(zoneHtml(f.properties || {})));
        l.bindTooltip((f.properties || {}).name || "", { sticky: true, opacity: 0.9 });
      },
    });
    layers.incidents = L.layerGroup();
    applyToggles();
    drawIncidents();
    setTimeout(() => { if (map) map.invalidateSize(); }, 80);
  }

  function filteredIncidents() {
    const all = ((R.incidents || {}).incidents) || [];
    return all.filter((it) => daysAgo(it.when_uk) <= days);
  }

  function drawIncidents() {
    if (!layers.incidents) return;
    layers.incidents.clearLayers();
    const items = filteredIncidents();
    items.forEach((it) => {
      if (it.lat == null || it.lon == null) return;
      const cls = incClass(it.type);
      const icon = L.divIcon({ className: "", html: `<div class="incdot ${cls}"></div>`, iconSize: [12, 12], iconAnchor: [6, 6] });
      const mk = L.marker([it.lat, it.lon], { icon, title: `UKMTO ${it.id || ""} ${it.type || ""}`, pane: "paneInc" });
      mk.on("click", () => showDetail(incHtml(it)));
      mk.addTo(layers.incidents);
    });
    const inc = R.incidents || {};
    const stale = inc.ok === false ? ' <span class="stale">stale</span>' : "";
    const el = $("#risk-inc-count");
    if (el) el.innerHTML = `<b>${items.length}</b> UKMTO incidents in the last ${days} days` +
      (inc.count != null ? ` · ${inc.count} in the stored feed, latest ${esc(fmtUK(inc.as_of, true))}` : "") + stale;
  }

  function applyToggles() {
    if (!map) return;
    [["jwc", "#risk-tog-jwc"], ["advisory", "#risk-tog-adv"], ["incidents", "#risk-tog-inc"]].forEach(([k, sel]) => {
      const on = $(sel) ? $(sel).checked : true;
      if (layers[k]) {
        if (on && !map.hasLayer(layers[k])) layers[k].addTo(map);
        if (!on && map.hasLayer(layers[k])) map.removeLayer(layers[k]);
      }
    });
  }

  function defaultDetail() {
    const z = R.zones || {};
    const a = R.advisories || {};
    const notes = (a.notes || []).map((n) => `<p class="flag">${esc(n)}</p>`).join("");
    showDetail(`<h3>War-risk and conflict zones</h3>
      <p>Red areas are our reading of Joint War Committee circular <b>${esc(z.circular || "JWLA-035")}</b> (${esc(fmtUK(z.circular_date, true))}). Amber areas are naval and industry advisories, with JMIC threat levels as of 8 November 2026. Dots are UKMTO incident reports. Tap a zone or a dot for details.</p>
      <p class="hint">${esc(z.disclaimer || "The wording of the circular prevails over this drawing. JWC does not set premiums.")}</p>
      ${notes}
      <p class="hint">A default 30-day incident window is shown; switch to 90 days above.</p>`);
  }

  function renderUnderwriting() {
    const u = R.underwriting;
    const box = $("#risk-underwriting");
    if (!box) return;
    if (!u) { box.innerHTML = `<p class="hint">Underwriting snapshot failed to load.</p>`; return; }
    const wr = u.war_risk_ap || {};
    const pi = u.pi_renewals || {};
    const wrRows = (wr.rows || []).map((r) => `<tr>
      <td>${esc(r.area)}</td>
      <td>${esc(r.range)}${staleTag(r.as_of, wr.stale_after_days || 21)}</td>
      <td class="hide-s">${esc(fmtUK(r.as_of, true))}</td>
      <td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.source)}</a><span class="src">${esc(r.note || "")}</span></td>
    </tr>`).join("");
    const piRows = (pi.rows || []).map((r) => `<tr>
      <td>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.club)}</a>` : esc(r.club)}</td>
      <td>${esc(r.gi)}</td>
    </tr>`).join("");
    const blk = (obj) => {
      if (!obj) return "";
      const pts = (obj.points || []).map((p) => `<li>${esc(p)}</li>`).join("");
      return `<div class="block"><h3>${esc(obj.title)}</h3>
        <p class="hint">Covers ${esc(fmtUK(obj.as_of, true))}${obj.published ? " · published " + esc(obj.published) : ""} · <a href="${esc(obj.url)}" target="_blank" rel="noopener">${esc(obj.source || "source")}</a></p>
        <ul class="list">${pts}</ul></div>`;
    };
    const links = (u.links || []).map((l) => `<li><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a></li>`).join("");
    box.innerHTML = `
      <p class="disc">${esc(u.disclaimer || "")}</p>
      <div class="block">
        <h3>${esc(wr.title || "War-risk additional premiums")}</h3>
        <p class="hint">News-reported ranges, not a quote. ${esc(wr.unit || "")}.</p>
        <div class="tw"><table class="t">
          <tr><th>Area</th><th>Reported range</th><th class="hide-s">As of</th><th>Source</th></tr>
          ${wrRows}
        </table></div>
      </div>
      <div class="block">
        <h3>${esc(pi.title)}</h3>
        <p class="hint">Snapshot for the ${esc(pi.policy_year)} policy year (from ${esc(fmtUK(pi.inception, true))}). These figures will not move until 2027/28 talks. <a href="${esc(pi.tracker_url)}" target="_blank" rel="noopener">Marsh renewal tracker</a>.</p>
        <div class="tw"><table class="t"><tr><th>Club</th><th>General increase / target</th></tr>${piRows}</table></div>
      </div>
      ${blk(u.iumi)}
      ${blk(u.allianz)}
      ${blk(u.emsa)}
      <div class="block">
        <h3>Official and primary links</h3>
        <ul class="links">${links}</ul>
      </div>`;
  }

  function bind() {
    $$("#risk-days button").forEach((b) => b.onclick = () => {
      $$("#risk-days button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      days = +b.dataset.d || 30;
      drawIncidents();
    });
    ["#risk-tog-jwc", "#risk-tog-adv", "#risk-tog-inc"].forEach((s) => {
      const el = $(s); if (el) el.onchange = applyToggles;
    });
  }

  function metaLines() {
    const inc = R.incidents || {}, adv = R.advisories || {}, z = R.zones || {};
    const incStale = inc.ok === false ? ` <span class="stale">stale</span> last good ${esc(fmtUK(inc.as_of))}; latest attempt failed ${esc(fmtUK(inc.last_fail_uk))}` : "";
    const jwc = (adv.jwc || {});
    const jmic = (adv.jmic || {});
    const marad = (adv.marad || {});
    const j1 = $("#risk-meta-inc");
    if (j1) j1.innerHTML = `Source: <a href="https://www.ukmto.org/recent-incidents" target="_blank" rel="noopener">UKMTO</a>, under the <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/" target="_blank" rel="noopener">Open Government Licence v3.0</a> · latest incident ${esc(fmtUK(inc.as_of, true))} · checked ${esc(fmtUK(inc.fetched_uk))}${incStale}`;
    const j2 = $("#risk-meta-zones");
    if (j2) j2.innerHTML = `Listed areas: our reading of <a href="${esc(z.circular_url || "https://lmalloyds.com/specialist-areas/underwriting/listed-areas/")}" target="_blank" rel="noopener">${esc(z.circular || "JWLA-035")}</a> (${esc(fmtUK(z.circular_date, true))}). LMA page last checked ${esc(fmtUK(jwc.checked_uk))}, latest circular seen ${esc(jwc.latest || z.circular || "")}. JMIC Update ${esc(jmic.snapshot_update)} threat levels as of ${esc(fmtUK(jmic.icod_uk, true))}; latest PDF check ${esc(jmic.latest_update ? "Update " + jmic.latest_update : "n/a")} (${esc(fmtUK(jmic.checked_uk))}). MARAD list: ${esc(marad.source || "dated snapshot")}${marad.ok === false ? ' <span class="stale">feed blocked</span>' : ""}.`;
  }

  async function initRisk() {
    if (!$("#risk")) return;
    const [zones, incidents, underwriting, advisories] = await Promise.all([
      getJSON("data/risk/zones.json"),
      getJSON("data/risk/incidents.json"),
      getJSON("data/risk/underwriting.json"),
      getJSON("data/risk/advisories.json"),
    ]);
    R.zones = zones || { features: [] };
    R.incidents = incidents || {};
    R.underwriting = underwriting;
    R.advisories = advisories || {};
    bind();
    buildMap();
    defaultDetail();
    renderUnderwriting();
    metaLines();
  }

  window.initRisk = initRisk;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initRisk);
  else initRisk();
})();
