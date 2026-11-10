# Shipping Control Centre

Static dashboard (plain HTML/CSS/JS, no build step) for chokepoints, fuel, freight, agri commodities, weather, risk and shipping news.

* `index.html`, `style.css`, `app.js`: the page; reads `data/*.json`, `static/geo.json` and `fleets.json`.
* `fleets.json`: company fleet lists for the competitor tracker on the live map. You can edit this file to add a company or paste IMO / MMSI numbers (see below). The hourly refresh may add ships or fill MMSIs when AISstream reports a matching name; it never deletes a row.
* `fetch.py`: pulls free, no-key public sources and writes `data/*.json`. Each source fails independently; the last good file is kept and `data/status.json` marks it stale.
* `ais.py`: optional AISstream sampler (chokepoint counts, then fleet last-known positions) when the `AISSTREAM_KEY` repo secret is set. The key stays on the runner and is never written to the site.
* `data/fleet-positions.json`: last-known positions from that hourly sample.
* `.github/workflows/refresh.yml`: runs `fetch.py` hourly on GitHub Actions, then `scripts/risk_refresh.py`, and commits when source data changed.
* `risk.js`, `risk.css`, `data/risk/`: dedicated war-risk map in the Risk tab (JWC listed areas from circular JWLA-035, JMIC advisory areas, UKMTO incidents under the Open Government Licence). `scripts/risk_refresh.py` refreshes incidents hourly and checks for a new JWLA or JMIC circular. Underwriting figures in `data/risk/underwriting.json` are dated manual snapshots.

Sources: IMF PortWatch, UKMTO (Open Government Licence), Lloyd's Market Association JWC listed-area circulars, JMIC advisories, Yahoo Finance (via the atalaya-data Cloudflare Worker /ship/chart route), CNBC public quotes and ECB rates via Frankfurter (fallbacks), Trading Economics public Baltic page, Drewry WCI page, Ship & Bunker price table, Open-Meteo, GDACS, NOAA NHC, World Bank Pink Sheet, RSS from gCaptain, Splash247, Hellenic Shipping News and Google News, AISstream.io (terrestrial AIS sample), Wikidata (CC0) and official company fleet pages for the starting fleet lists.

All times are UK time (Europe/London). Free, delayed data; not advice.

## Adding a company or ships to the Fleet view

The Fleet control on the live map is a dropdown of the companies in `fleets.json`, with a search box that filters that list. When you pick a company, the page shows our map of that fleet's last-known positions (not the VesselFinder "All traffic" widget, which cannot be filtered by company).

To add a company, edit `fleets.json` and commit it to this repository:

1. Copy an existing fleet block and give it a unique `id` (lowercase, no spaces) and a `name`. Optional `aliases` are included in the search box.
2. Paste the ships you know. Each ship can have a `name`, a seven-digit `imo`, and/or a nine-digit `mmsi`. An MMSI is what the refresh uses to look up a position. An IMO-only row is still listed, and the refresh will fill the MMSI if it later hears that IMO or a matching name.

```json
{
  "id": "example-line",
  "name": "Example Line",
  "aliases": ["Example"],
  "source": "Pasted by hand",
  "source_date": "2026-11-10",
  "note": "Ships pasted from a company list.",
  "ships": [
    { "name": "EXAMPLE SHIP", "imo": "1234567", "mmsi": "123456789" },
    { "name": "ANOTHER SHIP", "imo": "7654321" }
  ]
}
```

3. The next hourly refresh (or a manual "Run workflow") will start sampling any new MMSIs. AISstream accepts 200 MMSIs at a time, so large fleets are rotated across hours in batches. Positions are last-known from a short terrestrial sample: ships far offshore, or silent during the window, may be missing or marked stale.

There is no free, complete owner-to-fleet database we can legally use automatically, so lists other than Borchard Lines (taken from the company's own vessels page) are partial. Name prefixes such as MAERSK or MSC miss chartered-in ships that keep another name — paste those IMO or MMSI numbers here if you have them.
