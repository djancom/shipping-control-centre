#!/usr/bin/env python3
"""Shipping Control Centre data refresh.

Runs on GitHub Actions (see .github/workflows/refresh.yml). Every source is
fetched independently from free, no-key public endpoints. If a source fails,
its last good file in data/ is kept and data/status.json marks it stale with
the time it last succeeded. All display times are Europe/London.
"""
import datetime as dt, email.utils, hashlib, html, io, json, os, re, sys, time, traceback
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import requests

UK = ZoneInfo("Europe/London")
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
NOW = dt.datetime.now(UK)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-GB,en;q=0.9"}
S = requests.Session(); S.headers.update(UA)

def uk(t):  # datetime -> "2026-11-09 16:04" UK
    return t.astimezone(UK).strftime("%Y-%m-%d %H:%M")

def get(url, **kw):
    kw.setdefault("timeout", 40)
    last = None
    for i in range(3):
        try:
            r = S.get(url, **kw)
            if r.status_code == 200 and r.content:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)[:200]
        time.sleep(2 + 3 * i)
    raise RuntimeError(f"{url} -> {last}")

def path(name): return os.path.join(DATA, name + ".json")

def load(name, default=None):
    try:
        with open(path(name)) as f: return json.load(f)
    except Exception: return default

def save(name, obj):
    with open(path(name), "w") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=False)

def strip_meta(o):
    return {k: v for k, v in o.items() if k not in ("fetched_uk",)} if isinstance(o, dict) else o

STATUS = load("status", {}) or {}
STATUS.setdefault("sources", {})

def run(name, fn, label, url):
    """Run one source. On success write data/<name>.json (only if content changed)."""
    st = STATUS["sources"].get(name, {})
    st.update(label=label, url=url)
    try:
        obj = fn()
        old = load(name)
        if old is None or json.dumps(strip_meta(old), sort_keys=True) != json.dumps(strip_meta(obj), sort_keys=True):
            obj["fetched_uk"] = uk(NOW); save(name, obj); st["changed_uk"] = uk(NOW)
        st.update(ok=True, last_ok_uk=uk(NOW), error=None, as_of=obj.get("as_of"))
        print(f"OK   {name}: as_of={obj.get('as_of')}")
    except Exception as e:
        st.update(ok=False, error=(str(e) or repr(e))[:300], last_fail_uk=uk(NOW))
        print(f"FAIL {name}: {e}"); traceback.print_exc(limit=1)
    STATUS["sources"][name] = st

# ---------------------------------------------------------------- markets (Yahoo Finance chart API)
SYMS = {
 "BZ=F": ("Brent crude", "$/bbl", "energy"), "CL=F": ("WTI crude", "$/bbl", "energy"),
 "HO=F": ("ULSD / heating oil (NY Harbor)", "$/gal", "energy"), "NG=F": ("Natural gas (Henry Hub)", "$/MMBtu", "energy"),
 "ZW=F": ("Wheat (CBOT SRW)", "¢/bu", "agri"), "KE=F": ("Wheat (KC HRW)", "¢/bu", "agri"), "ZC=F": ("Corn", "¢/bu", "agri"),
 "ZS=F": ("Soybeans", "¢/bu", "agri"), "ZM=F": ("Soybean meal", "$/short ton", "agri"), "ZL=F": ("Soybean oil", "¢/lb", "agri"),
 "ZR=F": ("Rough rice", "$/cwt", "agri"), "ZO=F": ("Oats", "¢/bu", "agri"), "SB=F": ("Sugar No.11", "¢/lb", "agri"),
 "KC=F": ("Coffee (arabica)", "¢/lb", "agri"), "CC=F": ("Cocoa (ICE US)", "$/t", "agri"), "CT=F": ("Cotton No.2", "¢/lb", "agri"),
 "MAERSK-B.CO": ("Maersk B (Copenhagen)", "DKK", "equity"), "HLAG.DE": ("Hapag-Lloyd (Xetra)", "EUR", "equity"),
 "ZIM": ("ZIM (NYSE)", "USD", "equity"), "GSL": ("Global Ship Lease (NYSE)", "USD", "equity"),
 "GOGL": ("Golden Ocean (Nasdaq)", "USD", "equity"), "SBLK": ("Star Bulk (Nasdaq)", "USD", "equity"),
 "BDRY": ("Breakwave Dry Bulk ETF", "USD", "equity"),
 "GBPUSD=X": ("GBP/USD", "", "fx"), "EURUSD=X": ("EUR/USD", "", "fx"), "GBPEUR=X": ("GBP/EUR", "", "fx"),
}

class RateLimited(Exception): pass

def yahoo_one(sym):
    err = None
    for host in ("query2", "query1"):
        try:
            r = S.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                      params={"range": "1y", "interval": "1d", "includePrePost": "false"}, timeout=25)
            if r.status_code == 429:
                err = RateLimited("HTTP 429 Too Many Requests"); time.sleep(3); continue
            if r.status_code != 200:
                err = RuntimeError(f"HTTP {r.status_code}"); continue
            return r.json()["chart"]["result"][0]
        except Exception as e:
            err = e
    raise err

def parse_chart(sym, r):
    name, unit, grp = SYMS[sym]; m = r["meta"]
    ts, cl = r.get("timestamp") or [], r["indicators"]["quote"][0]["close"]
    pts = [(dt.datetime.fromtimestamp(t, UK).date(), v) for t, v in zip(ts, cl) if v is not None]
    last = m.get("regularMarketPrice"); lt = dt.datetime.fromtimestamp(m["regularMarketTime"], UK)
    if last is None and pts: last = pts[-1][1]
    prev = [v for d, v in pts if d < lt.date()]
    def ago(days):
        c = [v for d, v in pts if d <= lt.date() - dt.timedelta(days=days)]; return c[-1] if c else None
    y0 = [v for d, v in pts if d.year < lt.year]
    pct = lambda a: round((last / a - 1) * 100, 2) if a else None
    hist = [[d.isoformat(), round(v, 4)] for d, v in pts if d >= lt.date() - dt.timedelta(days=186)]
    if hist and hist[-1][0] != lt.date().isoformat(): hist.append([lt.date().isoformat(), round(last, 4)])
    elif hist: hist[-1][1] = round(last, 4)
    return dict(name=name, unit=unit, grp=grp, last=last, time_uk=uk(lt), d=pct(prev[-1] if prev else None),
                m1=pct(ago(30)), ytd=pct(y0[-1] if y0 else None), hist=hist, stale=False)

def markets():
    old = (load("markets") or {}).get("q", {})
    out, fails, limited = {}, [], 0
    for sym in SYMS:
        try:
            if limited >= 4: raise RateLimited("skipped after repeated HTTP 429")
            out[sym] = parse_chart(sym, yahoo_one(sym)); limited = 0
            time.sleep(0.4)
        except Exception as e:
            if isinstance(e, RateLimited): limited += 1
            fails.append(f"{sym}: {e}"[:80])
            if sym in old:
                o = dict(old[sym]); o["stale"] = True; out[sym] = o
    # FX fallback: ECB reference rates via Frankfurter (free, no key) when Yahoo FX failed
    for sym, (b, q) in {"GBPUSD=X": ("GBP", "USD"), "EURUSD=X": ("EUR", "USD"), "GBPEUR=X": ("GBP", "EUR")}.items():
        if sym in out and not out[sym].get("stale"): continue
        try:
            st = (NOW.date() - dt.timedelta(days=200)).isoformat()
            j = get(f"https://api.frankfurter.dev/v1/{st}..", params={"base": b, "symbols": q}).json()
            ser = sorted((d, v[q]) for d, v in j["rates"].items())
            last = ser[-1][1]; ld = dt.date.fromisoformat(ser[-1][0])
            def ago(n):
                c = [v for d, v in ser if d <= (ld - dt.timedelta(days=n)).isoformat()]; return c[-1] if c else None
            y0 = [v for d, v in ser if d < f"{ld.year}-01-01"]
            pct = lambda a: round((last / a - 1) * 100, 2) if a else None
            out[sym] = dict(name=SYMS[sym][0], unit="", grp="fx", last=last, time_uk=ser[-1][0] + " 15:00",
                            d=pct(ser[-2][1]), m1=pct(ago(30)), ytd=pct(y0[-1]) if y0 else None,
                            hist=[[d, v] for d, v in ser], stale=False, alt="ECB reference rate via Frankfurter (Yahoo unavailable)")
        except Exception as e:
            fails.append(f"{sym} ECB: {e}"[:80])
    if not any(not v.get("stale") for v in out.values()):
        raise RuntimeError("all market symbols failed; first errors: " + "; ".join(fails[:3]))
    times = sorted(v["time_uk"] for v in out.values() if not v.get("stale"))
    return dict(as_of=times[-1] if times else None, q=out, failed=fails,
                source="Yahoo Finance chart API (delayed futures, equities, FX); ECB reference rates as FX fallback")

# ---------------------------------------------------------------- IMF PortWatch chokepoint transits
PW_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"
CPN = {"suez": "Suez Canal", "bab": "Bab el-Mandeb Strait", "hormuz": "Strait of Hormuz", "malacca": "Malacca Strait",
       "panama": "Panama Canal", "bosporus": "Bosporus Strait", "gib": "Gibraltar Strait", "dover": "Dover Strait",
       "cape": "Cape of Good Hope"}

def portwatch():
    start = (NOW.date() - dt.timedelta(days=420)).isoformat()
    names = ",".join("'" + n + "'" for n in CPN.values())
    rows, off = [], 0
    while True:
        r = get(PW_URL, params={"where": f"date >= '{start}' AND portname IN ({names})",
                                "outFields": "portname,date,n_total,n_tanker,n_dry_bulk,n_container,n_general_cargo,capacity",
                                "orderByFields": "date", "resultOffset": off, "resultRecordCount": 2000, "f": "json"})
        j = r.json()
        if "error" in j: raise RuntimeError(str(j["error"])[:200])
        feats = j.get("features", [])
        for f in feats:
            a = f["attributes"]; d = a["date"]
            if isinstance(d, (int, float)): d = dt.datetime.fromtimestamp(d / 1000, dt.timezone.utc).date().isoformat()
            a["date"] = str(d)[:10]; rows.append(a)
        if not j.get("exceededTransferLimit") or not feats: break
        off += len(feats)
    if not rows: raise RuntimeError("no rows")
    by = {}
    for a in rows: by.setdefault(a["portname"], {})[a["date"]] = a
    lastd = max(a["date"] for a in rows)
    L = dt.date.fromisoformat(lastd)
    def avg(series, end, n, key="n_total"):
        v = [series[(end - dt.timedelta(days=i)).isoformat()][key] for i in range(n)
             if (end - dt.timedelta(days=i)).isoformat() in series and series[(end - dt.timedelta(days=i)).isoformat()].get(key) is not None]
        return round(sum(v) / len(v), 1) if v else None
    out = {}
    for cid, nm in CPN.items():
        s = by.get(nm, {})
        if not s: continue
        last = max(s)
        E = dt.date.fromisoformat(last)
        wk, wkl = [], []
        for i in range(25, -1, -1):
            e = E - dt.timedelta(days=7 * i); wk.append(avg(s, e, 7)); wkl.append(e.isoformat())
        out[cid] = dict(name=nm, last_date=last, w=avg(s, E, 7), pw=avg(s, E - dt.timedelta(days=7), 7),
                        yo=avg(s, E - dt.timedelta(days=364), 7), m30=avg(s, E, 30), lastday=s[last]["n_total"],
                        mix=[avg(s, E, 7, k) for k in ("n_tanker", "n_dry_bulk", "n_container", "n_general_cargo")],
                        cap=avg(s, E, 7, "capacity"), wk=wk, wkl=wkl)
    return dict(as_of=lastd, last=lastd, cp=out, source="IMF PortWatch daily chokepoint transits (AIS-derived)",
                note="Dates are UTC calendar days as published; PortWatch typically lags about a week.")

# ---------------------------------------------------------------- Baltic indices + EU carbon (Trading Economics public page)
def baltic():
    r = get("https://tradingeconomics.com/commodity/baltic"); s = r.text
    rows = {}
    for m in re.finditer(r'<tr[^>]*data-symbol="([^"]+)"[^>]*>\s*<td>\s*<a href="([^"]+)">\s*(.*?)\s*</a>\s*</td>\s*<td id="p">\s*([\d.,-]+)\s*</td>(.*?)</tr>', s, re.S):
        tds = re.findall(r'<td[^>]*>\s*([^<]*?)\s*</td>', m.group(5))
        rows[m.group(1)] = dict(name=html.unescape(m.group(3)), last=float(m.group(4).replace(",", "")),
                                chg=tds[-5] if len(tds) >= 5 else None, d=tds[-4] if len(tds) >= 4 else None,
                                m1=tds[-3] if len(tds) >= 3 else None, y=tds[-2] if len(tds) >= 2 else None,
                                date=tds[-1] if tds else None)
    if "BDIY:IND" not in rows: raise RuntimeError("BDI row not found")
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S))))
    seg = {}
    for k in ("capesize", "panamax", "supramax", "handysize"):
        m = re.search(k + r" index(.{0,260}?)([\d,]{3,}) points", text, re.I)
        if not m: continue
        body = m.group(1); p = re.findall(r"([\d.]+)%", body)
        neg = re.search(r"\b(fell|down|lost|dropped|declined|eased|decreased|lower|slipped|retreated)\b", body, re.I)
        seg[k] = dict(points=int(m.group(2).replace(",", "")), d=(round((-1 if neg else 1) * float(p[-1]), 2) if p else None))
    summ = re.search(r"(The Baltic Exchange.{0,1200}?points\.(?:[^.]{0,400}?points\.){0,3})", text)
    def te_date(sv):
        try:
            mo, dd = sv.split("/"); d = dt.datetime.strptime(f"{mo} {dd} {NOW.year}", "%b %d %Y").date()
            if d > NOW.date() + dt.timedelta(days=2): d = d.replace(year=d.year - 1)
            return d.isoformat()
        except Exception: return None
    bdi = rows["BDIY:IND"]; eua = rows.get("EECXM:IND")
    out = dict(as_of=te_date(bdi["date"]), bdi=dict(last=bdi["last"], d=bdi["d"], m1=bdi["m1"], y=bdi["y"], date=te_date(bdi["date"])),
               seg=seg, summary=summ.group(1)[:900] if summ else None,
               source="Trading Economics public page summarising Baltic Exchange data")
    if eua: out["eua"] = dict(last=eua["last"], d=eua["d"], m1=eua["m1"], y=eua["y"], date=te_date(eua["date"]))
    return out

# ---------------------------------------------------------------- Drewry World Container Index
def drewry():
    u = "https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry"
    s = get(u).text
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S))))
    md = re.search(r'content="(\d{1,2} \w{3} \d{4}): Drewry.{0,40}?World Container Index \(WCI\) (\w+)[^"]*?\$([\d,]+) per 40ft', s)
    if not md: raise RuntimeError("WCI headline not found")
    date = dt.datetime.strptime(md.group(1), "%d %b %Y").date().isoformat()
    comp = int(md.group(3).replace(",", ""))
    ch = re.search(r"WCI\)[^.]*?(increased|decreased|rose|fell|was stable|remained stable|was unchanged)(?: by)? ?(\d+)?%", text)
    yoy = re.search(r"(\d+)% (higher|lower) YoY", text)
    routes = {}
    for a, b in [("Shanghai", "Rotterdam"), ("Shanghai", "Genoa"), ("Shanghai", "New York"), ("Shanghai", "Los Angeles"),
                 ("Rotterdam", "Shanghai"), ("Rotterdam", "New York"), ("New York", "Rotterdam"), ("Los Angeles", "Shanghai")]:
        m = re.search(rf"{a} to {b} (increased|decreased|rose|fell|climbed|dropped|remained stable|were stable|were unchanged|was unchanged|remained unchanged|stayed)[^$]{{0,40}}?\$([\d,]+)", text)
        if m:
            p = re.search(r"(\d+)%", text[m.start():m.end()])
            sign = -1 if m.group(1) in ("decreased", "fell", "dropped") else 1
            routes[f"{a}–{b}"] = dict(usd=int(m.group(2).replace(",", "")), ww=(sign * int(p.group(1))) if p else 0)
    outlook = re.search(r"(Drewry (?:therefore |)(?:projects|expects)[^.]{0,200}\.)", text)
    ww = None
    if ch:
        ww = 0 if ch.group(2) is None else (int(ch.group(2)) * (-1 if ch.group(1) in ("decreased", "fell") else 1))
    return dict(as_of=date, composite=comp, ww=ww, yoy=(int(yoy.group(1)) * (1 if yoy.group(2) == "higher" else -1)) if yoy else None,
                routes=routes, outlook=outlook.group(1) if outlook else None, url=u, source="Drewry World Container Index (US$/40ft)")

# ---------------------------------------------------------------- Ship & Bunker prices
def bunkers():
    s = get("https://shipandbunker.com/prices").text
    hubs = {}
    for m in re.finditer(r'<tr data-href="(/prices/[^"]+)"[^>]*>\s*<td>\s*<a[^>]*>([^<]+)</a>\s*</td>(.*?)</tr>', s, re.S):
        cells = re.findall(r'<td class="price-cell">(.*?)</td>', m.group(3), re.S)
        vals = []
        for c in cells[:3]:
            v = re.search(r'price-val">\$?([\d,.]+)', c); ch = re.search(r'price-chg[^"]*">([^<]+)', c)
            vals.append([float(v.group(1).replace(",", "")) if v else None, ch.group(1).strip() if ch else None])
        d = re.search(r'col-date">([^<]+)<', m.group(3))
        name = html.unescape(m.group(2).strip())
        if name not in hubs and len(vals) == 3:
            hubs[name] = dict(vlsfo=vals[0], hsfo=vals[1], mgo=vals[2], date=d.group(1).strip() if d else None, href="https://shipandbunker.com" + m.group(1))
    if not hubs: raise RuntimeError("no bunker rows")
    def iso(sv):
        try:
            d = dt.datetime.strptime(f"{sv} {NOW.year}", "%b %d %Y").date()
            if d > NOW.date() + dt.timedelta(days=2): d = d.replace(year=d.year - 1)
            return d.isoformat()
        except Exception: return None
    for h in hubs.values(): h["date_iso"] = iso(h["date"])
    dates = sorted(h["date_iso"] for h in hubs.values() if h["date_iso"])
    return dict(as_of=dates[-1] if dates else None, hubs=hubs, unit="US$ per tonne", source="Ship & Bunker public price table")

# ---------------------------------------------------------------- Weather: Open-Meteo marine + forecast, NHC, GDACS
WX = {"Dover Strait": (51.0, 1.45), "Bay of Biscay": (45.5, -6.0), "Gibraltar": (35.95, -5.6),
      "Bosphorus approach (Black Sea)": (41.4, 29.2), "Suez (Gulf of Suez)": (29.4, 32.7), "Bab el-Mandeb": (12.6, 43.3),
      "Hormuz": (26.4, 56.5), "Malacca": (3.0, 100.6), "Panama (Pacific approach)": (8.7, -79.5),
      "Cape of Good Hope": (-34.6, 18.4), "North Sea (Humber approach)": (53.7, 1.0), "US Gulf (Mississippi approach)": (28.8, -89.2)}

def weather():
    out = {}
    for name, (la, lo) in WX.items():
        mr = get("https://marine-api.open-meteo.com/v1/marine", params=dict(latitude=la, longitude=lo, daily="wave_height_max,swell_wave_height_max", timezone="Europe/London", forecast_days=4)).json()
        fc = get("https://api.open-meteo.com/v1/forecast", params=dict(latitude=la, longitude=lo, daily="wind_speed_10m_max,wind_gusts_10m_max", wind_speed_unit="kn", timezone="Europe/London", forecast_days=4)).json()
        out[name] = dict(lat=la, lon=lo, dates=fc["daily"]["time"], wave=mr.get("daily", {}).get("wave_height_max", [None] * 4),
                         wind=fc["daily"]["wind_speed_10m_max"], gust=fc["daily"]["wind_gusts_10m_max"])
    return dict(as_of=uk(NOW), points=out, source="Open-Meteo Marine (wave height) and Open-Meteo forecast (10 m wind, knots)")

def storms():
    j = get("https://www.nhc.noaa.gov/CurrentStorms.json").json()
    out = []
    for s in j.get("activeStorms", []):
        lu = s.get("lastUpdate")
        try: lu = uk(dt.datetime.fromisoformat(lu.replace("Z", "+00:00")))
        except Exception: pass
        out.append(dict(name=s.get("name"), cls=s.get("classification"), kt=s.get("intensity"), lat=s.get("latitudeNumeric"),
                        lon=s.get("longitudeNumeric"), pos=f'{s.get("latitude")} {s.get("longitude")}', dir=s.get("movementDir"),
                        spd=s.get("movementSpeed"), updated_uk=lu, src="NHC/CPHC"))
    gd = []
    try:
        j = get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH", params={"eventlist": "TC", "alertlevel": "green;orange;red"}).json()
        for f in j.get("features", []):
            p = f["properties"]
            if str(p.get("iscurrent")).lower() != "true": continue
            lon, lat = f["geometry"]["coordinates"][:2]
            gd.append(dict(name=p.get("eventname"), level=p.get("alertlevel"), sev=(p.get("severitydata") or {}).get("severitytext"),
                           frm=_utc2uk(p.get("fromdate")), to=_utc2uk(p.get("todate")), countries=p.get("country"), lat=lat, lon=lon,
                           link=(p.get("url") or {}).get("report")))
    except Exception as e:
        gd = None; print("GDACS failed:", e)
    return dict(as_of=uk(NOW), nhc=out, gdacs=gd, source="GDACS tropical cyclone events (all basins, UTC times converted); NOAA NHC CurrentStorms.json (Atlantic/East & Central Pacific)")

def _utc2uk(v):
    try: return uk(dt.datetime.fromisoformat(v).replace(tzinfo=dt.timezone.utc))
    except Exception: return v

def _f(v):
    try: return float(v)
    except Exception: return None

# ---------------------------------------------------------------- World Bank Pink Sheet (monthly) – fertiliser + gas/grain
def worldbank():
    page = get("https://www.worldbank.org/en/research/commodity-markets").text
    m = re.search(r'https://thedocs\.worldbank\.org/[^"]+CMO-Historical-Data-Monthly\.xlsx', page)
    if not m: raise RuntimeError("monthly xlsx link not found")
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(get(m.group(0), timeout=90).content), read_only=True, data_only=True)
    ws = wb["Monthly Prices"]; rows = list(ws.iter_rows(values_only=True))
    upd = next((r[0] for r in rows[:6] if r[0] and str(r[0]).startswith("Updated")), None)
    hdr = rows[4]; units = rows[5]
    want = {"DAP": "DAP, fob US Gulf", "Urea": "Urea, fob Middle East", "Potassium chloride": "Potassium chloride, CFR Brazil",
            "TSP": "TSP, US Gulf", "Phosphate rock": "Phosphate rock, fob North Africa", "Natural gas, Europe": "Natural gas, Europe (TTF)",
            "Wheat, US HRW": "Wheat, US HRW", "Maize": "Maize (corn), US Gulf", "Soybeans": "Soybeans", "Rice, Thai 5%": "Rice, Thai 5%"}
    data = [r for r in rows[6:] if r[0] and re.match(r"\d{4}M\d\d", str(r[0]))]
    out = {}
    for i, h in enumerate(hdr):
        if not h: continue
        key = next((k for k in want if str(h).strip().rstrip("* ").strip() == k), None)
        if not key: continue
        ser = [(r[0], r[i]) for r in data if isinstance(r[i], (int, float))]
        if len(ser) < 13: continue
        last = ser[-1]; prev = ser[-2]; ya = ser[-13]
        y_last = [v for p, v in ser if p.startswith(str(int(last[0][:4]) - 1))]
        out[key] = dict(label=want[key], unit=str(units[i]).strip("()"), month=last[0], last=round(last[1], 2), prev=round(prev[1], 2),
                        prev_month=prev[0], yago=round(ya[1], 2), prev_year_avg=round(sum(y_last) / len(y_last), 2) if y_last else None,
                        hist=[[p, round(v, 2)] for p, v in ser[-24:]])
    if "DAP" not in out: raise RuntimeError("DAP column missing")
    lm = max(v["month"] for v in out.values())
    return dict(as_of=lm, updated=upd, series=out, url=m.group(0), source="World Bank Commodity Price Data (Pink Sheet), monthly averages")

# ---------------------------------------------------------------- News (RSS)
def gn(q): return "https://news.google.com/rss/search?q=" + requests.utils.quote(q) + "&hl=en-GB&gl=GB&ceid=GB:en"
FEEDS = {"gcaptain": "https://gcaptain.com/feed/", "splash": "https://splash247.com/feed/", "hellenic": "https://www.hellenicshippingnews.com/feed/",
         "g_ship": gn("shipping freight OR vessel OR tanker OR bulker when:3d")}
TABQ = {
 "risk": gn("(Houthi OR UKMTO OR piracy OR \"war risk\" OR \"Red Sea\" OR Hormuz) ship OR tanker OR vessel when:7d"),
 "ports": gn("(\"Port of Felixstowe\" OR Felixstowe OR \"Port of Southampton\" OR \"Port of Rotterdam\" OR \"Antwerp-Bruges\" OR \"Port of Antwerp\" OR \"Port of Immingham\" OR \"Port of Liverpool\" OR \"Port of Hamburg\") (strike OR congestion OR closure OR delays OR berth OR terminal OR \"waiting time\") when:14d"),
 "law": gn("(IMO OR \"FuelEU\" OR \"EU ETS\" OR \"Maritime and Coastguard Agency\" OR OFSI OR OFAC OR \"P&I\" OR demurrage OR \"charter party\" OR \"Commercial Court\" OR GAFTA) shipping when:14d"),
 "trade": gn("(tariff OR \"export ban\" OR \"export quota\" OR \"UK customs\" OR \"border target operating model\") grain OR wheat OR soybean OR fertiliser OR shipping when:14d"),
 "agri": gn("(WASDE OR \"grain exports\" OR \"wheat exports\" OR \"export inspections\" OR \"crop forecast\" OR fertiliser OR fertilizer) when:10d"),
}
CPQ = {"suez": "\"Suez Canal\"", "bab": "(\"Bab el-Mandeb\" OR \"Red Sea\") shipping", "hormuz": "\"Strait of Hormuz\" OR Hormuz shipping",
       "malacca": "\"Strait of Malacca\" OR \"Malacca Strait\"", "panama": "\"Panama Canal\"", "bosporus": "Bosphorus OR Bosporus OR \"Black Sea\" shipping",
       "gib": "\"Strait of Gibraltar\" shipping", "dover": "\"Dover Strait\" OR \"English Channel\" shipping", "cape": "\"Cape of Good Hope\" shipping"}
PLACE = {"suez": r"suez", "bab": r"red sea|bab el|houthi|yemen|aden", "hormuz": r"hormuz|gulf of oman|persian gulf|arabian gulf|qatar|fujairah",
         "malacca": r"malacca|singapore strait", "panama": r"panama", "bosporus": r"black sea|bosp?horus|odesa|odessa|novorossiysk",
         "gib": r"gibraltar", "dover": r"dover|english channel|the channel", "cape": r"cape of good hope|cape town|south africa"}
SHIPW = re.compile(r"\b(ship|ships|shipping|vessel|vessels|tanker|tankers|bulker|carrier|cargo|seafarers?|crew|merchant|transit|transits|traffic|canal|strait|port)\b", re.I)
ATTACK = re.compile(r"\b(attack(ed|s)?|struck|strikes? on|hit (by|three|two|a|an)|missiles?|drone (strike|attack)s?|explosions?|blasts?|seiz(ed|es|ure)|hijack(ed|ing)?|killed|fired on|mined?)\b", re.I)
ADVIS = re.compile(r"\b(warn(s|ing)?|threatens? (ships?|shipping|vessels)|security (alert|warning)s?|advisory|u-turns?|divert(s|ed|ing)?|suspend(s|ed)?|halt(s|ed)?|closure|closed|blockade)\b", re.I)

def parse_rss(content, feed):
    root = ET.fromstring(content); items = []
    for it in root.iter("item"):
        t = html.unescape((it.findtext("title") or "").strip()); l = (it.findtext("link") or "").strip()
        src = it.find("source"); s = src.text if src is not None and src.text else {"gcaptain": "gCaptain", "splash": "Splash247", "hellenic": "Hellenic Shipping News"}.get(feed, "")
        if s and t.endswith(" - " + s): t = t[: -len(s) - 3]
        try: d = email.utils.parsedate_to_datetime(it.findtext("pubDate")).astimezone(UK)
        except Exception: continue
        items.append(dict(t=t, s=s, d=d.strftime("%Y-%m-%d %H:%M"), l=l))
    return items

def dedupe(items, n):
    seen, out = set(), []
    for i in sorted(items, key=lambda x: x["d"], reverse=True):
        k = re.sub(r"\W+", "", i["t"].lower())[:60]
        if k in seen: continue
        seen.add(k); out.append(i)
        if len(out) >= n: break
    return out

def news():
    feed, tabs, cps, fails = [], {}, {}, []
    for k, u in FEEDS.items():
        try: feed += parse_rss(get(u, timeout=30).content, k)
        except Exception as e: fails.append(k)
    old = load("news") or {}
    for k, u in TABQ.items():
        try:
            its = parse_rss(get(u, timeout=30).content, k)
            if k == "ports": its = [i for i in its if re.search(r"port|terminal|container|berth|dock|strike|congestion|vessel|ship|cargo", i["t"], re.I) and not re.search(r"road|traffic|M\d|motorway|ferry fog|airport", i["t"], re.I)]
            cut = (NOW - dt.timedelta(days=21)).strftime("%Y-%m-%d %H:%M")
            tabs[k] = dedupe([i for i in its if i["d"] >= cut], 12)
        except Exception: fails.append(k); tabs[k] = (old.get("tabs") or {}).get(k, [])
    cut7 = (NOW - dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    for cid, q in CPQ.items():
        try:
            its = dedupe(parse_rss(get(gn(q + " when:10d"), timeout=30).content, cid), 8)
        except Exception:
            fails.append(cid); its = ((old.get("cp") or {}).get(cid) or {}).get("items", [])
        recent = [i for i in its if i["d"] >= cut7]
        pl = re.compile(PLACE[cid], re.I)
        rel = [i for i in recent if pl.search(i["t"]) and SHIPW.search(i["t"])]
        att = [i for i in rel if ATTACK.search(i["t"])]
        adv = [i for i in rel if ADVIS.search(i["t"])]
        flag = "attacks" if att else ("advisory" if adv else "")
        cps[cid] = dict(items=its, flag=flag, why=(att or adv)[:2])
    if not feed and not any(tabs.values()): raise RuntimeError("all news feeds failed")
    return dict(as_of=uk(NOW), feed=dedupe(feed, 30), tabs=tabs, cp=cps, failed=fails,
                source="RSS: gCaptain, Splash247, Hellenic Shipping News, Google News searches (UK edition)")

# ---------------------------------------------------------------- derived: chokepoint status, what changed, history
def derived():
    pw = load("portwatch") or {}; nw = load("news") or {}; mk = (load("markets") or {}).get("q", {})
    bal = load("baltic") or {}; wci = load("drewry") or {}; bk = load("bunkers") or {}
    status = {}
    for cid, c in (pw.get("cp") or {}).items():
        flag = ((nw.get("cp") or {}).get(cid) or {}).get("flag", "")
        r = (c["w"] / c["yo"]) if c.get("w") and c.get("yo") else 1
        st = "red" if (r < 0.5 or flag == "attacks") else ("amber" if (r < 0.85 or flag == "advisory") else "green")
        status[cid] = st
    snap = dict(t=uk(NOW), status=status)
    for k in ("BZ=F", "CL=F", "HO=F", "ZW=F", "ZC=F", "ZS=F", "GBPUSD=X", "EURUSD=X"):
        if k in mk: snap[k] = mk[k]["last"]
    if bal.get("bdi"): snap["BDI"] = bal["bdi"]["last"]
    if bal.get("eua"): snap["EUA"] = bal["eua"]["last"]
    if wci.get("composite"): snap["WCI"] = wci["composite"]
    rt = ((bk.get("hubs") or {}).get("Rotterdam") or {}).get("vlsfo")
    if rt: snap["RTM_VLSFO"] = rt[0]
    hist = (load("history") or {}).get("snaps", [])
    hist = [h for h in hist if h["t"] >= (NOW - dt.timedelta(days=4)).strftime("%Y-%m-%d %H:%M")]
    if not hist or {k: v for k, v in hist[-1].items() if k != "t"} != {k: v for k, v in snap.items() if k != "t"}:
        hist.append(snap)
    # baseline: newest snapshot at least ~20h old, else the oldest we have
    base = None
    cut = (NOW - dt.timedelta(hours=20)).strftime("%Y-%m-%d %H:%M")
    older = [h for h in hist if h["t"] <= cut]
    base = older[-1] if older else (hist[0] if hist else None)
    changes = []
    names = {"BZ=F": "Brent", "CL=F": "WTI", "HO=F": "ULSD (NY)", "ZW=F": "Wheat", "ZC=F": "Corn", "ZS=F": "Soybeans",
             "GBPUSD=X": "GBP/USD", "EURUSD=X": "EUR/USD", "BDI": "Baltic Dry Index", "EUA": "EU carbon (EUA)", "WCI": "Drewry WCI", "RTM_VLSFO": "Rotterdam VLSFO"}
    if base and base is not snap:
        for k, n in names.items():
            a, b = base.get(k), snap.get(k)
            if a and b and a != b: changes.append(dict(k=n, frm=a, to=b, pct=round((b / a - 1) * 100, 2)))
        for cid, st in status.items():
            ob = (base.get("status") or {}).get(cid)
            if ob and ob != st: changes.append(dict(k=CPN[cid], frm=ob, to=st, pct=None, status=True))
    changes.sort(key=lambda c: (not c.get("status"), -abs(c["pct"] or 0)))
    fresh = [dict(i, tag="news") for i in (nw.get("feed") or []) if i["d"] >= cut][:8]
    save("history", dict(snaps=hist[-120:]))
    return dict(as_of=uk(NOW), since=base["t"] if base else None, status=status, changes=changes, new_headlines=fresh)

if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    only = set(sys.argv[1:])
    jobs = [
        ("markets", markets, "Futures, equities, FX", "https://finance.yahoo.com/"),
        ("portwatch", portwatch, "Chokepoint transits", "https://portwatch.imf.org/"),
        ("baltic", baltic, "Baltic indices and EU carbon", "https://tradingeconomics.com/commodity/baltic"),
        ("drewry", drewry, "Drewry World Container Index", "https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry"),
        ("bunkers", bunkers, "Bunker prices by hub", "https://shipandbunker.com/prices"),
        ("weather", weather, "Sea state and wind", "https://open-meteo.com/"),
        ("storms", storms, "Tropical storms", "https://www.nhc.noaa.gov/"),
        ("worldbank", worldbank, "Fertiliser and monthly commodity prices", "https://www.worldbank.org/en/research/commodity-markets"),
        ("news", news, "Shipping news and tabs", "https://news.google.com/"),
    ]
    for name, fn, label, url in jobs:
        if only and name not in only: continue
        run(name, fn, label, url)
    try:
        d = derived(); d["fetched_uk"] = uk(NOW); save("derived", d)
    except Exception as e:
        print("derived failed", e); traceback.print_exc()
    STATUS["run_uk"] = uk(NOW)
    STATUS["runner"] = "GitHub Actions" if os.environ.get("GITHUB_ACTIONS") else "local"
    save("status", STATUS)
    bad = [k for k, v in STATUS["sources"].items() if not v.get("ok")]
    print("stale sources:", bad or "none")
