/* Weather overlays for our own Leaflet maps (risk map, fleet map). Free, no key:
   - data/wxgrid.json: Open-Meteo wind & waves on a coarse ocean grid (written by the hourly Action)
   - RainViewer public radar tiles (personal/educational use, attribution required) */
"use strict";
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const fmt = (s) => { const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/); return m ? `${+m[3]} ${MON[+m[2] - 1]} ${m[4]}:${m[5]} UK` : "n/a"; };
  let gridDoc = null, gridP = null, rainP = null;
  function loadGrid() {
    if (!gridP) gridP = fetch("data/wxgrid.json?v=" + Date.now(), { cache: "no-store" }).then((r) => r.ok ? r.json() : null).catch(() => null).then((d) => (gridDoc = d));
    return gridP;
  }
  function waveCol(h) { return h == null ? "#0000" : h < 1 ? "#1f6f8b" : h < 2 ? "#2a9d8f" : h < 3 ? "#e9c46a" : h < 4.5 ? "#f4a261" : h < 6 ? "#e76f51" : "#c1121f"; }
  function windCol(k) { return k == null ? "#ccc" : k < 11 ? "#cfefff" : k < 22 ? "#9fe0ff" : k < 34 ? "#ffd166" : k < 48 ? "#ff8c42" : "#ff3b3b"; }
  // Returns a Leaflet layerGroup filled once data arrives. pane is optional.
  function gridLayer(pane) {
    const g = L.layerGroup();
    loadGrid().then((d) => {
      if (!d || !d.pts) return;
      const half = (d.step || 10) / 2;
      d.pts.forEach(([la, lo, wv, wvd, wk, wkd, gu]) => {
        const tip = `${la}°, ${lo}°: waves ${wv == null ? "n/a" : wv.toFixed(1) + " m"}${wvd != null ? " from " + Math.round(wvd) + "°" : ""} · wind ${wk == null ? "n/a" : Math.round(wk) + " kn"}${wkd != null ? " from " + Math.round(wkd) + "°" : ""}${gu != null ? ", gusts " + Math.round(gu) + " kn" : ""}<br><span style="opacity:.75">Open-Meteo model, ${esc(fmt(d.model_time_uk))}</span>`;
        L.rectangle([[la - half, lo - half], [la + half, lo + half]], { pane, stroke: false, fillColor: waveCol(wv), fillOpacity: 0.32, interactive: true }).bindTooltip(tip, { sticky: true, opacity: 0.92 }).addTo(g);
        if (wkd != null) {
          const rot = (wkd + 180) % 360; // arrow points where the wind blows to
          const icon = L.divIcon({ className: "", iconSize: [14, 14], iconAnchor: [7, 7],
            html: `<svg width="14" height="14" viewBox="-9 -9 18 18" style="transform:rotate(${rot}deg);overflow:visible"><path d="M0,-8 L4,3 L0,1 L-4,3 Z" fill="${windCol(wk)}" stroke="#0b1017" stroke-width="1"/></svg>` });
          L.marker([la, lo], { icon, pane, interactive: false, keyboard: false }).addTo(g);
        }
      });
    });
    return g;
  }
  function gridLabel() {
    const d = gridDoc;
    if (!d) return "Wind &amp; waves: loading…";
    return `Wind &amp; waves: <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a> model (CC BY 4.0), ${d.step}° ocean grid, valid ${esc(fmt(d.model_time_uk))}. Shading = wave height (blue &lt;1 m → red 6 m+); arrows = wind direction, colour = speed (yellow 22 kn+, orange gale 34 kn+).`;
  }
  // RainViewer radar: latest past frame. Calls back with (layer, label) or (null, reason).
  function rainLayer(pane) {
    if (!rainP) rainP = fetch("https://api.rainviewer.com/public/weather-maps.json").then((r) => r.json()).catch(() => null);
    return rainP.then((j) => {
      const fr = j && j.radar && j.radar.past && j.radar.past[j.radar.past.length - 1];
      if (!fr) return [null, "RainViewer radar unavailable right now."];
      const t = new Date(fr.time * 1000).toLocaleString("en-GB", { timeZone: "Europe/London", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      const lay = L.tileLayer(`${j.host}${fr.path}/256/{z}/{x}/{y}/2/1_1.png`, { pane, opacity: 0.6, maxNativeZoom: 7, maxZoom: 16, noWrap: true,
        attribution: 'Radar: <a href="https://www.rainviewer.com/" target="_blank" rel="noopener">RainViewer</a>' });
      return [lay, `Rain radar: <a href="https://www.rainviewer.com/" target="_blank" rel="noopener">RainViewer</a>, frame ${esc(t)} UK. Land-based radars only, so open ocean shows nothing. Free for personal use.`];
    });
  }
  window.WXL = { gridLayer, gridLabel, rainLayer, loadGrid };
})();
