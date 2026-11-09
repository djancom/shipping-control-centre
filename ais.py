#!/usr/bin/env python3
"""Optional AISstream sampler (dormant until the repo secret AISSTREAM_KEY exists).

Connects to wss://stream.aisstream.io/v0/stream for ~60 s with one bounding box per
chokepoint, counts unique vessels (MMSI) seen in each box and how many of those were
last reported at speed over ground < 1 knot ("waiting"), and returns a dict that
fetch.py writes to data/ais.json. With no key it returns None and nothing is written.
"""
import asyncio, json, os, time

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

def _box_of(lat, lon):
    for k, ((a, b), (c, d)) in BOXES.items():
        if a <= lat <= c and b <= lon <= d:
            return k
    return None

async def _sample(key, seconds):
    import websockets  # installed by the workflow only when the secret exists
    seen = {k: {} for k in BOXES}  # box -> {mmsi: last_sog}
    n = 0
    async with websockets.connect(URL, open_timeout=20, close_timeout=5, max_size=2**20) as ws:
        await ws.send(json.dumps({"APIKey": key, "BoundingBoxes": list(BOXES.values()),
                                  "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"]}))
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, end - time.monotonic()))
            except asyncio.TimeoutError:
                break
            m = json.loads(raw)
            if "error" in m:
                raise RuntimeError(str(m["error"])[:200])
            md = m.get("MetaData") or {}
            body = (m.get("Message") or {}).get(m.get("MessageType"), {}) or {}
            lat, lon, mmsi = md.get("latitude"), md.get("longitude"), md.get("MMSI")
            if lat is None or lon is None or mmsi is None:
                continue
            k = _box_of(lat, lon)
            if not k:
                continue
            seen[k][mmsi] = body.get("Sog")
            n += 1
    return seen, n

def sample(seconds=60):
    key = os.environ.get("AISSTREAM_KEY", "").strip()
    if not key:
        return None  # dormant: no secret configured
    seen, n = asyncio.run(_sample(key, seconds))
    out = {}
    for k, v in seen.items():
        sogs = [s for s in v.values() if isinstance(s, (int, float))]
        out[k] = dict(vessels=len(v), waiting=sum(1 for s in sogs if s < 1.0), box=BOXES[k])
    return dict(seconds=seconds, messages=n, cp=out,
                source="AISstream.io live AIS sample (~60 s per refresh); 'waiting' = last reported speed under 1 knot",
                note="A 60-second sample: counts are vessels reporting in that window, not a full census.")
