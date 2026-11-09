# Shipping Control Centre

Static dashboard (plain HTML/CSS/JS, no build step) for chokepoints, fuel, freight, agri commodities, weather, risk and shipping news.

* `index.html`, `style.css`, `app.js`: the page; reads `data/*.json` and `static/geo.json`.
* `fetch.py`: pulls free, no-key public sources and writes `data/*.json`. Each source fails independently; the last good file is kept and `data/status.json` marks it stale.
* `.github/workflows/refresh.yml`: runs `fetch.py` hourly on GitHub Actions and commits when source data changed.

Sources: IMF PortWatch, Yahoo Finance (via the atalaya-data Cloudflare Worker /ship/chart route), CNBC public quotes and ECB rates via Frankfurter (fallbacks), Trading Economics public Baltic page, Drewry WCI page, Ship & Bunker price table, Open-Meteo, GDACS, NOAA NHC, World Bank Pink Sheet, RSS from gCaptain, Splash247, Hellenic Shipping News and Google News.

All times are UK time (Europe/London). Free, delayed data; not advice.
