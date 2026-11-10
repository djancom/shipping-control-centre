#!/usr/bin/env python3
"""AISstream sampler for chokepoint counts and fleet last-known positions.

Dormant until the repo secret AISSTREAM_KEY exists. The key is only used here,
on the GitHub Actions runner, and is never written to the site or to data files.

After the ~60 s chokepoint sample, fleet sampling uses one connection, a world
bounding box and FiltersShipMMSI in rotating batches of 200 (about 75 s each),
capped so the added runtime stays under ~10 minutes. Last-known positions are
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

def _apply_ident(fleets_doc, rec, added_counts):
    """Fill MMSI/IMO/name, or append a name-matched ship. Never deletes a row."""
    if not fleets_doc or not rec.get("mmsi"):
        return False
    fid = None
    # Prefer an existing row with this MMSI or IMO
    for fl in fleets_doc.get("fleets") or []:
        for s in fl.get("ships") or []:
            if rec["mmsi"] and _mmsi_str(s.get("mmsi")) == rec["mmsi"]:
                fid = fl.get("id")
                changed = False
                if rec.get("imo") and not s.get("imo"):
                    s["imo"] = rec["imo"]; changed = True
                if rec.get("name") and _norm(s.get("name") or "") in {"", _norm(f"Hapag-Lloyd ship {s.get('imo') or ''}")}:
                    s["name"] = rec["name"]; changed = True
                if rec.get("name") and not s.get("name"):
                    s["name"] = rec["name"]; changed = True
                return changed
            if rec.get("imo") and _imo_str(s.get("imo")) == rec["imo"]:
                fid = fl.get("id")
                changed = False
                if rec["mmsi"] and not s.get("mmsi"):
                    s["mmsi"] = rec["mmsi"]; changed = True
                if rec.get("name") and not s.get("name"):
                    s["name"] = rec["name"]; changed = True
                return changed
    fid = match_fleet_id(rec.get("name") or "")
    if not fid:
        return False
    for fl in fleets_doc.get("fleets") or []:
        if fl.get("id") != fid:
            continue
        fl.setdefault("ships", []).append({
            "name": rec.get("name") or f"MMSI {rec['mmsi']}",
            **({"imo": rec["imo"]} if rec.get("imo") else {}),
            "mmsi": rec["mmsi"],
            "via": "aisstream",
        })
        fl["listed"] = len(fl["ships"])
        fl["with_mmsi"] = sum(1 for s in fl["ships"] if s.get("mmsi"))
        added_counts[fid] = added_counts.get(fid, 0) + 1
        return True
    return False


def _fleet_id_for(fleets_doc, rec):
    """Return a fleet id if this contact is one of our listed or name-matched ships."""
    m, imo = rec.get("mmsi") or "", rec.get("imo") or ""
    for fl in (fleets_doc or {}).get("fleets") or []:
        fid = fl.get("id")
        for s in fl.get("ships") or []:
            if m and _mmsi_str(s.get("mmsi")) == m:
                return fid
            if imo and _imo_str(s.get("imo")) == imo:
                return fid
    return match_fleet_id(rec.get("name") or "")

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
        row["lat"] = round(rec["lat"], 5)
        row["lon"] = round(rec["lon"], 5)
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

async def _fleet_pass(key, fleets_doc, pos_store, as_of):
    import websockets
    heard_static = 0
    heard_pos = 0
    this_run = set()
    added = {}
    identities = list(getattr(sample, "_heard", []) or [])

    def ingest(rec):
        nonlocal heard_static, heard_pos
        identities.append(rec)
        _apply_ident(fleets_doc, rec, added)
        if rec.get("type") in STAT_TYPES or rec.get("destination") or rec.get("imo"):
            heard_static += 1
        if rec.get("lat") is not None:
            heard_pos += 1
        # Only keep last-known positions for ships that belong to a listed fleet
        # (or whose name matches a line's prefix). Do not store the rest of the
        # world-box static traffic.
        fid = _fleet_id_for(fleets_doc, rec)
        if fid:
            _merge_position(pos_store, rec, as_of, this_run)
            pos_store[rec["mmsi"]]["fleet"] = fid

    mmsis = [m for m, _, _ in _fleet_mmsis(fleets_doc)]
    n_batches = max(1, (len(mmsis) + BATCH - 1) // BATCH) if mmsis else 0
    prev = _load_json(POS_PATH, {}) or {}
    start = int(prev.get("next_batch") or 0)
    if n_batches:
        start = start % n_batches
    batches_run = 0
    next_batch = start

    async with websockets.connect(URL, open_timeout=20, close_timeout=5, max_size=2 ** 22, compression="deflate") as ws:
        # 1) Short world-box static harvest: catch prefix-named ships (incl. chartered-in) and MMSIs
        await _subscribe(ws, key, WORLD, types=STAT_TYPES)
        n_stat = await _listen(ws, STATIC_SECONDS, ingest)
        # 2) Rotating MMSI position batches
        if mmsis:
            # Refresh the MMSI list in case the static pass added some
            mmsis = [m for m, _, _ in _fleet_mmsis(fleets_doc)]
            n_batches = max(1, (len(mmsis) + BATCH - 1) // BATCH)
            start = start % n_batches
            to_run = min(MAX_BATCHES, n_batches)
            for i in range(to_run):
                bi = (start + i) % n_batches
                chunk = mmsis[bi * BATCH:(bi + 1) * BATCH]
                if not chunk:
                    continue
                await _subscribe(ws, key, WORLD, mmsis=chunk, types=POS_TYPES + STAT_TYPES)
                await _listen(ws, BATCH_SECONDS, ingest)
                batches_run += 1
                next_batch = (bi + 1) % n_batches
        # Apply any leftover identities (incl. chokepoint window)
        for rec in identities:
            _apply_ident(fleets_doc, rec, added)
            fid = _fleet_id_for(fleets_doc, rec)
            if fid:
                _merge_position(pos_store, rec, as_of, this_run)
                pos_store[rec["mmsi"]]["fleet"] = fid

    return {
        "static_messages": n_stat if 'n_stat' in locals() else 0,
        "batches_run": batches_run,
        "batches_total": n_batches,
        "next_batch": next_batch,
        "mmsis_listed": len(mmsis),
        "seen_this_run": len(this_run),
        "added": added,
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

    if stats.get("added"):
        fleets_doc["updated_uk"] = as_of
        for fl in fleets_doc.get("fleets") or []:
            fl["listed"] = len(fl.get("ships") or [])
            fl["with_mmsi"] = sum(1 for s in fl.get("ships") or [] if s.get("mmsi"))
        _save_json(FLEETS_PATH, fleets_doc)

    listed = stats["mmsis_listed"]
    batches_note = (
        f"This run sampled {stats['batches_run']} of {stats['batches_total'] or 0} "
        f"MMSI batches ({BATCH} ships, ~{BATCH_SECONDS}s each)"
        + (f", then the next run starts at batch {stats['next_batch'] + 1}." if stats["batches_total"] > stats["batches_run"] else ".")
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
        "static_seconds": STATIC_SECONDS,
        "batch_seconds": BATCH_SECONDS,
        "note": (
            "Last-known positions from a terrestrial AIS sample (typically within about 200 km of a shore station). "
            "Ships far offshore, or silent during this window, keep an older last-known fix or appear as not seen. "
            + batches_note +
            " A position older than 6 hours is marked stale. Not a live feed and not a complete census."
        ),
        "ships": pos_store,
        "seen": sorted(this_run),
    }
    return doc
