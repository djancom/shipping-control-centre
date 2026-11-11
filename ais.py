#!/usr/bin/env python3
"""AISstream sampler for chokepoint counts and fleet last-known positions.

Dormant until the repo secret AISSTREAM_KEY exists. The key is only used here,
on the GitHub Actions runner, and is never written to the site or to data files.

After the ~60 s chokepoint sample, the fleet pass opens three parallel connections
(AISstream allows three per account) for FLEET_SECONDS: one world-box static-data
harvest that fills missing MMSIs from IMO numbers, and two that rotate through
200-MMSI position batches. Last-known positions are
merged into data/fleet-positions.json. Matching names/IMOs are added to
fleets.json (rows are never deleted).
"""
import asyncio, json, os, re, time
import datetime as dt
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
FLEETS_PATH = os.path.join(ROOT, "fleets.json")
POS_PATH = os.path.join(DATA, "fleet-positions.json")

# [[lat_min, lon_min], [lat_max, lon_max]] per chokepoint (approach areas included)
BOXES = {
    "suez":     [[29.5, 32.2], [31.6, 32.7]],
    "bab":      [[12.0, 42.8], [13.4, 44.0]],
    "hormuz":   [[25.6, 55.6], [27.2, 57.2]],
    "malacca":  [[1.0, 100.0], [4.5, 104.2]],
    "panama":   [[8.6, -80.2], [9.6, -79.3]],
    "gib":      [[35.7, -6.2], [36.3, -5.0]],
    "dover":    [[50.6, 0.9], [51.4, 2.2]],
    "bosporus": [[40.9, 28.8], [41.4, 29.4]],
    "cape":     [[-35.5, 17.5], [-33.5, 20.5]],
}
URL = "wss://stream.aisstream.io/v0/stream"
WORLD = [[[-90, -180], [90, 180]]]
BATCH = 200
BATCH_SECONDS = 75
MAX_BATCHES = 6          # 6 × 75 s = 7.5 min of position batches
STATIC_SECONDS = 60      # world-box ShipStaticData harvest before the batches
STALE_HOURS = 6
POS_TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"]
STAT_TYPES = ["ShipStaticData", "StaticDataReport"]

# Name patterns used to attach an AIS-heard ship to a pre-built fleet.
# Keep these tight: a loose pattern (especially K Line) adds the wrong ships.
def _norm(s):
    s = (s or "").upper().replace("Æ", "AE").replace("MÆRSK", "MAERSK")
    return re.sub(r"\s+", " ", s).strip()

def match_fleet_id(name):
    u = _norm(name)
    if not u:
        return None
    if re.search(r"\bBORCHARDT\b", u):
        return None
    if re.search(r"\bBORCHARD\b", u):
        return "borchard"
    if "MAERSK" in u:
        return "maersk"
    if "CMA CGM" in u or re.search(r"\bCMA\s*CGM\b", u):
        return "cma-cgm"
    if re.search(r"\bHAPAG\b", u):
        return "hapag"
    if re.search(r"\bCOSCO\b", u) or re.search(r"\bOOCL\b", u):
        return "cosco"
    if u.startswith("MSC ") or re.search(r"\bMSC\s", u):
        return "msc"
    if u.startswith("EVER ") or "EVERGREEN" in u:
        return "evergreen"
    if u.startswith("HYUNDAI ") or u.startswith("HMM "):
        return "hmm"
    if u.startswith("YM "):
        return "yangming"
    if u.startswith("ZIM ") or re.search(r"\bZIM\s", u):
        return "zim"
    if u.startswith("NYK "):
        return "nyk"
    if u.startswith("MOL ") or re.search(r"(^|\s)MOL(\s|$)", u):
        return "mol"
    if re.search(r"(^|\s)K[\s-]LINE\b", u) and not re.search(r"\bS\.?\s*K[\s-]LINE\b", u):
        return "kline"
    if u.startswith("ONE "):
        return "one"
    return None

def _uk_now():
    return dt.datetime.now(UK).strftime("%Y-%m-%d %H:%M")

def _box_of(lat, lon):
    for k, ((a, b), (c, d)) in BOXES.items():
        if a <= lat <= c and b <= lon <= d:
            return k
    return None

def _g(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if d.get(k) is not None and d.get(k) != "":
            return d[k]
    return None

def _mmsi_str(v):
    if v is None or v == "":
        return ""
    s = re.sub(r"\D", "", str(v))
    return s.zfill(9) if s and len(s) <= 9 else (s if len(s) == 9 else "")

def _imo_str(v):
    if v is None or v == "":
        return ""
    s = re.sub(r"\D", "", str(v))
    return s if re.fullmatch(r"\d{7}", s) else ""

def _name_str(v):
    if v is None:
        return ""
    if isinstance(v, dict):
        # ShipStaticData.Name is sometimes { "Value": "..." } or a byte map; prefer text fields
        v = v.get("Value") or v.get("value") or v.get("Name") or ""
    s = _norm(str(v)).replace("@", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s if s and s not in {".", "0", "UNKNOWN"} else ""

def parse_ais_message(m):
    """Pull identity and, when present, a position from one AIS stream message."""
    if not isinstance(m, dict) or "error" in m:
        return None
    md = m.get("MetaData") or {}
    typ = m.get("MessageType") or ""
    body = (m.get("Message") or {}).get(typ, {}) or {}
    rec = {
        "mmsi": _mmsi_str(_g(md, "MMSI", "mmsi") or _g(body, "UserID", "userID", "MMSI")),
        "name": _name_str(_g(md, "ShipName", "shipName", "Name") or _g(body, "Name", "ShipName")),
        "imo": _imo_str(_g(body, "ImoNumber", "IMO", "Imo", "imo")),
        "lat": _g(md, "latitude", "Latitude") if _g(md, "latitude", "Latitude") is not None else _g(body, "Latitude", "latitude"),
        "lon": _g(md, "longitude", "Longitude") if _g(md, "longitude", "Longitude") is not None else _g(body, "Longitude", "longitude"),
        "sog": _g(body, "Sog", "SOG", "sog"),
        "cog": _g(body, "Cog", "COG", "cog"),
        "heading": _g(body, "TrueHeading", "Heading", "trueHeading"),
        "destination": _name_str(_g(body, "Destination", "destination")),
        "type": typ,
    }
    if typ == "StaticDataReport":
        # Class B parts: ReportA has Name, ReportB has length etc.; IMOs are rare
        pa, pb = body.get("ReportA") or {}, body.get("ReportB") or {}
        rec["name"] = rec["name"] or _name_str(_g(pa, "Name") or _g(body, "Name"))
        rec["imo"] = rec["imo"] or _imo_str(_g(pb, "ImoNumber") or _g(body, "ImoNumber"))
    if not rec["mmsi"]:
        return None
    try:
        if rec["lat"] is not None:
            rec["lat"] = float(rec["lat"])
        if rec["lon"] is not None:
            rec["lon"] = float(rec["lon"])
        if rec["sog"] is not None:
            rec["sog"] = float(rec["sog"])
        if rec["cog"] is not None:
            rec["cog"] = float(rec["cog"])
    except (TypeError, ValueError):
        return None
    # AIS uses 91 / 181 as "not available"
    if rec["lat"] is not None and not (-90 <= rec["lat"] <= 90):
        rec["lat"] = rec["lon"] = None
    if rec["lon"] is not None and not (-180 <= rec["lon"] <= 180):
        rec["lat"] = rec["lon"] = None
    if rec["heading"] is not None:
        try:
            rec["heading"] = int(rec["heading"])
            if rec["heading"] > 360:
                rec["heading"] = None
        except (TypeError, ValueError):
            rec["heading"] = None
    return rec

async def _open(key):
    import websockets
    return websockets.connect(
        URL, open_timeout=20, close_timeout=5, max_size=2 ** 22,
        compression="deflate",
    )

async def _subscribe(ws, key, boxes, mmsis=None, types=None):
    msg = {"APIKey": key, "BoundingBoxes": boxes, "FilterMessageTypes": types or POS_TYPES}
    if mmsis:
        msg["FiltersShipMMSI"] = [_mmsi_str(x) for x in mmsis if _mmsi_str(x)]
    await ws.send(json.dumps(msg))

async def _listen(ws, seconds, on_msg):
    end = time.monotonic() + seconds
    n = 0
    while time.monotonic() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.4, end - time.monotonic()))
        except asyncio.TimeoutError:
            break
        try:
            m = json.loads(raw)
        except Exception:
            continue
        if "error" in m:
            raise RuntimeError(str(m["error"])[:200])
        rec = parse_ais_message(m)
        if rec:
            on_msg(rec)
            n += 1
    return n

async def _sample_chokepoints(key, seconds):
    import websockets
    seen = {k: {} for k in BOXES}  # box -> {mmsi: last_sog}
    heard = []
    n = 0
    async with websockets.connect(URL, open_timeout=20, close_timeout=5, max_size=2 ** 20, compression="deflate") as ws:
        await _subscribe(ws, key, list(BOXES.values()), types=POS_TYPES)
        def on(rec):
            nonlocal n
            n += 1
            heard.append(rec)
            if rec["lat"] is None or rec["lon"] is None:
                return
            k = _box_of(rec["lat"], rec["lon"])
            if k:
                seen[k][rec["mmsi"]] = rec.get("sog")
        await _listen(ws, seconds, on)
    return seen, n, heard

def sample(seconds=60):
    key = os.environ.get("AISSTREAM_KEY", "").strip()
    if not key:
        return None  # dormant: no secret configured
    seen, n, heard = asyncio.run(_sample_chokepoints(key, seconds))
    out = {}
    for k, v in seen.items():
        sogs = [s for s in v.values() if isinstance(s, (int, float))]
        out[k] = dict(vessels=len(v), waiting=sum(1 for s in sogs if s < 1.0), box=BOXES[k])
    # stash identities so sample_fleets() can harvest names/MMSIs from this window too
    sample._heard = heard
    return dict(seconds=seconds, messages=n, cp=out,
                source="AISstream.io live AIS sample (~60 s per refresh); 'waiting' = last reported speed under 1 knot",
                note="A 60-second sample: counts are vessels reporting in that window, not a full census. Coverage is terrestrial AIS (typically within about 200 km of a shore station).")

def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)

def _fleet_mmsis(fleets_doc):
    out = []
    seen = set()
    for fl in (fleets_doc or {}).get("fleets") or []:
        fid = fl.get("id")
        for s in fl.get("ships") or []:
            m = _mmsi_str(s.get("mmsi"))
            if m and m not in seen:
                seen.add(m)
                out.append((m, fid, s))
    return out

class FleetIndex:
    """MMSI / IMO lookups over fleets.json so each AIS message is matched in O(1)."""
    def __init__(self, doc):
        self.doc = doc
        self.by_id = {fl.get("id"): fl for fl in (doc or {}).get("fleets") or []}
        self.mmsi, self.imo = {}, {}
        for fl in self.by_id.values():
            for s in fl.get("ships") or []:
                self._add(fl.get("id"), s)
        self.filled = {}   # fid -> MMSIs filled from IMO matches this run
        self.added = {}    # fid -> ships appended by name match this run

    def _add(self, fid, s):
        m, i = _mmsi_str(s.get("mmsi")), _imo_str(s.get("imo"))
        if m: self.mmsi.setdefault(m, (fid, s))
        if i: self.imo.setdefault(i, (fid, s))

    def ident(self, rec):
        """Fill MMSI/IMO/name on a listed ship, or append a name-matched ship. Never deletes a row."""
        m, i = rec.get("mmsi"), rec.get("imo")
        if not m:
            return None
        hit = self.mmsi.get(m)
        if hit:
            fid, s = hit
            if i and not s.get("imo"):
                s["imo"] = i; self.imo.setdefault(i, hit)
            if rec.get("name") and (not s.get("name") or _norm(s.get("name")) == _norm(f"Hapag-Lloyd ship {s.get('imo') or ''}")):
                s["name"] = rec["name"]
            return fid
        if i and i in self.imo:
            fid, s = self.imo[i]
            if not s.get("mmsi"):
                s["mmsi"] = m; s["mmsi_via"] = "aisstream-imo"
                self.mmsi[m] = (fid, s)
                self.filled[fid] = self.filled.get(fid, 0) + 1
            if rec.get("name") and not s.get("name"):
                s["name"] = rec["name"]
            return fid
        fid = match_fleet_id(rec.get("name") or "")
        if not fid or fid not in self.by_id:
            return None
        fl = self.by_id[fid]
        row = {"name": rec.get("name") or f"MMSI {m}", **({"imo": i} if i else {}), "mmsi": m, "via": "aisstream"}
        fl.setdefault("ships", []).append(row)
        self._add(fid, row)
        self.added[fid] = self.added.get(fid, 0) + 1
        return fid

    def mmsis(self):
        return list(self.mmsi.keys())

TRAIL_POINTS = 8
TRAIL_DAYS = 7

def _parse_uk(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    except Exception:
        return None

def _merge_position(store, rec, as_of, this_run):
    m = rec.get("mmsi")
    if not m:
        return
    row = store.get(m) or {"mmsi": m}
    if rec.get("name"):
        row["name"] = rec["name"]
    if rec.get("imo"):
        row["imo"] = rec["imo"]
    if rec.get("destination"):
        row["destination"] = rec["destination"]
    if rec.get("lat") is not None and rec.get("lon") is not None:
        lat, lon = round(rec["lat"], 4), round(rec["lon"], 4)
        if lat == 0 and lon == 0:
            return  # common "no fix" value
        # small trail: keep the previous fix when the ship has moved about 5 km or more
        if row.get("lat") is not None and row.get("seen_uk") and row.get("seen_uk") != as_of:
            if abs(row["lat"] - lat) + abs(row["lon"] - lon) > 0.05:
                tr = row.setdefault("trail", [])
                if not tr or tr[-1][:2] != [row["lat"], row["lon"]]:
                    tr.append([row["lat"], row["lon"], row["seen_uk"]])
                del tr[:-TRAIL_POINTS]
        row["lat"], row["lon"] = lat, lon
        row["seen_uk"] = as_of
        this_run.add(m)
    if rec.get("sog") is not None:
        row["sog"] = rec["sog"]
    if rec.get("cog") is not None:
        row["cog"] = rec["cog"]
    if rec.get("heading") is not None:
        row["heading"] = rec["heading"]
    row["updated_uk"] = as_of
    store[m] = row

FLEET_SECONDS = int(os.environ.get("FLEET_SECONDS", "660"))   # whole fleet window, 3 parallel connections
ROTATE_SECONDS = 80     # each position connection listens to one 200-MMSI batch for this long, then moves on

async def _run_conn(label, key, seconds, plan, ingest, stats):
    """One AISstream connection with reconnect. plan() yields (boxes, mmsis, types, listen_seconds)."""
    import websockets
    end = time.monotonic() + seconds
    backoff = 2
    while time.monotonic() < end - 5:
        try:
            async with websockets.connect(URL, open_timeout=20, close_timeout=5, max_size=2 ** 22, compression="deflate", ping_interval=20) as ws:
                for boxes, mmsis, types, secs in plan():
                    left = end - time.monotonic()
                    if left < 3:
                        break
                    await _subscribe(ws, key, boxes, mmsis=mmsis, types=types)
                    stats[label] = stats.get(label, 0) + await _listen(ws, min(secs, left), ingest)
                    await asyncio.sleep(1.1)  # at most one subscription update per second
                return
        except Exception as e:
            stats.setdefault("errors", []).append(f"{label}: {str(e)[:120]}")
            await asyncio.sleep(backoff); backoff = min(backoff * 2, 30)

async def _fleet_pass(key, fleets_doc, pos_store, as_of):
    idx = FleetIndex(fleets_doc)
    this_run = set()
    stats = {}
    heard_static = [0]

    def ingest(rec):
        fid = idx.ident(rec)
        if rec.get("type") in STAT_TYPES:
            heard_static[0] += 1
        # Only keep last-known positions for ships that belong to a listed fleet (or match a line's name)
        if fid:
            _merge_position(pos_store, rec, as_of, this_run)
            if rec["mmsi"] in pos_store:
                pos_store[rec["mmsi"]]["fleet"] = fid

    for rec in list(getattr(sample, "_heard", []) or []):
        ingest(rec)

    prev = _load_json(POS_PATH, {}) or {}
    cursor = {"i": int(prev.get("next_batch") or 0), "done": 0}

    def static_plan():
        # Connection 1: world-box static/voyage data for the whole window. ShipStaticData carries the
        # IMO number, so listed ships without an MMSI get one filled (and name-matched ships are added).
        while True:
            yield WORLD, None, STAT_TYPES, FLEET_SECONDS

    def pos_plan():
        # Connections 2 and 3: rotate through 200-MMSI batches; the list is rebuilt each time,
        # so MMSIs filled by connection 1 are polled later in the same run.
        while True:
            mm = sorted(idx.mmsis())
            nb = max(1, (len(mm) + BATCH - 1) // BATCH)
            b = cursor["i"] % nb
            cursor["i"] = b + 1; cursor["done"] += 1
            yield WORLD, mm[b * BATCH:(b + 1) * BATCH], POS_TYPES + STAT_TYPES, ROTATE_SECONDS

    await asyncio.gather(
        _run_conn("static", key, FLEET_SECONDS, static_plan, ingest, stats),
        _run_conn("pos_a", key, FLEET_SECONDS, pos_plan, ingest, stats),
        _run_conn("pos_b", key, FLEET_SECONDS, pos_plan, ingest, stats),
    )
    mm = idx.mmsis()
    nb = max(1, (len(mm) + BATCH - 1) // BATCH)
    return {
        "static_messages": stats.get("static", 0),
        "position_messages": stats.get("pos_a", 0) + stats.get("pos_b", 0),
        "batches_run": cursor["done"],
        "batches_total": nb,
        "next_batch": cursor["i"] % nb,
        "mmsis_listed": len(mm),
        "seen_this_run": len(this_run),
        "added": idx.added,
        "filled": idx.filled,
        "errors": stats.get("errors", [])[:6],
        "this_run": this_run,
    }

def sample_fleets():
    """Harvest identities and rotate MMSI position batches. Writes fleet-positions.json
    and may update fleets.json (additions and MMSI fills only). Returns the positions doc.
    """
    key = os.environ.get("AISSTREAM_KEY", "").strip()
    if not key:
        raise RuntimeError("AISSTREAM_KEY not set")
    as_of = _uk_now()
    fleets_doc = _load_json(FLEETS_PATH, {"fleets": []})
    prev = _load_json(POS_PATH, {}) or {}
    pos_store = dict(prev.get("ships") or {})
    # keep previous last-known; merge updates on top
    stats = asyncio.run(_fleet_pass(key, fleets_doc, pos_store, as_of))
    this_run = stats.pop("this_run", set())

    # Tag fleet id on each stored ship when we can
    mmsi_to_fleet = {m: fid for m, fid, _ in _fleet_mmsis(fleets_doc)}
    imo_to_fleet = {}
    for fl in fleets_doc.get("fleets") or []:
        for s in fl.get("ships") or []:
            if s.get("imo"):
                imo_to_fleet[_imo_str(s["imo"])] = fl["id"]
    for m, row in pos_store.items():
        fid = mmsi_to_fleet.get(m) or imo_to_fleet.get(_imo_str(row.get("imo"))) or match_fleet_id(row.get("name") or "")
        if fid:
            row["fleet"] = fid

    # prune: drop trail points older than TRAIL_DAYS; keep each ship's last-known fix
    now = _parse_uk(as_of)
    for row in pos_store.values():
        if row.get("trail") and now:
            row["trail"] = [t for t in row["trail"] if (_parse_uk(t[2]) or now) >= now - dt.timedelta(days=TRAIL_DAYS)]
            if not row["trail"]:
                row.pop("trail", None)
    if stats.get("added") or stats.get("filled"):
        fleets_doc["updated_uk"] = as_of
        for fl in fleets_doc.get("fleets") or []:
            fl["listed"] = len(fl.get("ships") or [])
            fl["with_mmsi"] = sum(1 for s in fl.get("ships") or [] if s.get("mmsi"))
        _save_json(FLEETS_PATH, fleets_doc)

    listed = stats["mmsis_listed"]
    batches_note = (
        f"This run listened for about {FLEET_SECONDS // 60} minutes on three connections: one collecting ship identity data worldwide "
        f"(filling missing MMSIs from IMO numbers), two cycling through {stats['batches_total']} batches of up to {BATCH} fleet MMSIs "
        f"({stats['batches_run']} batch windows of ~{ROTATE_SECONDS}s)."
    )
    doc = {
        "as_of": as_of,
        "source": "AISstream.io",
        "stale_after_hours": STALE_HOURS,
        "next_batch": stats["next_batch"],
        "batches_run": stats["batches_run"],
        "batches_total": stats["batches_total"],
        "mmsis_listed": listed,
        "seen_this_run": stats["seen_this_run"],
        "added_to_fleets": stats["added"],
        "mmsi_filled": stats.get("filled", {}),
        "static_messages": stats.get("static_messages"),
        "position_messages": stats.get("position_messages"),
        "errors": stats.get("errors", []),
        "fleet_seconds": FLEET_SECONDS,
        "batch_seconds": ROTATE_SECONDS,
        "keep_days": 7,
        "note": (
            "Last-known positions from a terrestrial AIS sample (typically within about 200 km of a shore station). "
            "Ships far offshore, or silent during this window, keep an older last-known fix or appear as not seen. "
            + batches_note +
            " Positions are kept for 7 days and shaded by age (older than 6 hours is marked stale); older fixes are listed but not drawn. Not a live feed and not a complete census."
        ),
        "ships": pos_store,
        "seen": sorted(this_run),
    }
    return doc
