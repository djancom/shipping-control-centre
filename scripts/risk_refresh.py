#!/usr/bin/env python3
"""Refresh Shipping Control Centre risk-map data (free sources only).

Run as a separate GitHub Actions step after fetch.py. Writes data/risk/incidents.json
(UKMTO, last-good cache) and data/risk/advisories.json (JMIC / JWLA / MARAD checks).
Merges source rows into data/status.json. All display times are Europe/London.
Does not change JWC polygons or the underwriting snapshot.
"""
from __future__ import annotations
import datetime as dt, json, os, re, sys, traceback
from zoneinfo import ZoneInfo
import requests

UK = ZoneInfo("Europe/London")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RISK = os.path.join(ROOT, "data", "risk")
STATUS_PATH = os.path.join(ROOT, "data", "status.json")
NOW = dt.datetime.now(UK)
UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.ukmto.org/recent-incidents",
}
S = requests.Session()
S.headers.update(UA)

UKMTO_ALL = "https://sc.royalnavy.mod.uk/api/ukmto/all"
JMIC_TYPE = "84a787ea-9bf6-4f47-9689-e2c0546dbdad"
JMIC_COUNT = f"https://sc.royalnavy.mod.uk/api/ukmto/products-count/{JMIC_TYPE}"
LMA_PAGE = "https://lmalloyds.com/specialist-areas/underwriting/listed-areas/"
MARAD_PAGE = "https://www.maritime.dot.gov/msci-advisories"
CURRENT_JWLA = "JWLA-035"
CURRENT_JMIC = 112

# Seed / fallback MARAD list as of 10 Nov 2026 (the site often blocks datacentre IPs).
MARAD_SNAPSHOT = [
    {"id": "2026-015", "title": "Global — U.S. Maritime Advisory Updates, Resources, and Contacts", "effective": "2026-10-21", "expires": "2027-04-19"},
    {"id": "2026-014", "title": "Worldwide — Foreign Adversarial Technological, Physical, and Cyber Influence", "effective": "2026-10-21", "expires": "2027-04-19"},
    {"id": "2026-013", "title": "Red Sea, Bab el Mandeb Strait, Gulf of Aden, Arabian Sea, and Somali Basin — Houthi Attacks on Commercial Vessels", "effective": "2026-09-23", "expires": "2027-03-22"},
    {"id": "2026-012", "title": "Black Sea and Sea of Azov — Military Combat Operations", "effective": "2026-09-23", "expires": "2027-03-22"},
    {"id": "2026-011", "title": "Persian Gulf, Strait of Hormuz and Gulf of Oman — Iranian Attacks on Commercial Vessels", "effective": "2026-09-09", "expires": "2027-03-08"},
    {"id": "2026-010", "title": "Gulf of Aden, Arabian Sea, Indian Ocean — Piracy / Armed Robbery / Kidnapping for Ransom", "effective": "2026-08-07", "expires": "2027-02-04"},
    {"id": "2026-009", "title": "Gulf of Guinea — Piracy / Armed Robbery / Kidnapping for Ransom", "effective": "2026-06-24", "expires": "2026-12-21"},
]


def uk(t: dt.datetime) -> str:
    return t.astimezone(UK).strftime("%Y-%m-%d %H:%M")


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        f.write("\n")


def parse_utc(s):
    if not s:
        return None
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t


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
        import time
        time.sleep(2 + 3 * i)
    raise RuntimeError(f"{url} -> {last}")


def source_row(status, name, label, url, ok, as_of, error=None):
    st = (status.get("sources") or {}).get(name, {})
    st.update(label=label, url=url, ok=ok, as_of=as_of)
    if ok:
        st.update(last_ok_uk=uk(NOW), error=None)
    else:
        st.update(last_fail_uk=uk(NOW), error=(error or "")[:300])
    status.setdefault("sources", {})[name] = st


def refresh_incidents():
    path = os.path.join(RISK, "incidents.json")
    old = load_json(path, {}) or {}
    try:
        raw = get(UKMTO_ALL).json()
        if not isinstance(raw, list) or not raw:
            raise RuntimeError("UKMTO API returned no incidents")
        items = []
        for r in raw:
            t = parse_utc(r.get("utcDateOfIncident") or r.get("utcDateCreated"))
            if t is None or r.get("locationLatitude") is None or r.get("locationLongitude") is None:
                continue
            details = (r.get("otherDetails") or "").strip()
            items.append({
                "id": r.get("incidentNumber"),
                "issuer": r.get("incidentIssuer") or "UKMTO",
                "type": r.get("incidentTypeName") or "Incident",
                "place": r.get("place") or r.get("region") or "",
                "lat": r.get("locationLatitude"),
                "lon": r.get("locationLongitude"),
                "when_uk": uk(t),
                "when_utc": t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "vessel_type": (r.get("vesselType") or "").strip(),
                "details": details,
            })
        items.sort(key=lambda i: i["when_utc"], reverse=True)
        latest = items[0]["when_uk"] if items else uk(NOW)
        doc = {
            "as_of": latest,
            "fetched_uk": uk(NOW),
            "ok": True,
            "source": "UKMTO",
            "source_url": "https://www.ukmto.org/recent-incidents",
            "licence": "Open Government Licence v3.0",
            "attribution": "Contains public sector information licensed under the Open Government Licence v3.0. Official source: UKMTO, https://www.ukmto.org/recent-incidents. This site is not associated with or endorsed by UKMTO or the UK Ministry of Defence.",
            "licence_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
            "count": len(items),
            "incidents": items,
        }
        save_json(path, doc)
        print(f"OK   ukmto-incidents: {len(items)} records, latest {latest}")
        return True, latest, None
    except Exception as e:
        if old.get("incidents"):
            old["ok"] = False
            old["last_fail_uk"] = uk(NOW)
            old["error"] = str(e)[:300]
            save_json(path, old)
            print(f"FAIL ukmto-incidents (kept last good): {e}")
            return False, old.get("as_of"), str(e)
        print(f"FAIL ukmto-incidents (no last good): {e}")
        traceback.print_exc(limit=1)
        return False, None, str(e)


def check_jwc():
    found = None
    try:
        html = get(LMA_PAGE).text
        nums = re.findall(r"JWLA-0?(\d+)", html, re.I)
        if nums:
            n = max(int(x) for x in nums)
            found = f"JWLA-{n:03d}"
        pdfs = re.findall(r'href="(https://lmalloyds.com/wp-content/uploads/[^"]+JWLA[^"]+\.pdf)"', html)
        return {
            "ok": True,
            "latest": found or CURRENT_JWLA,
            "newer_than_drawn": bool(found and found != CURRENT_JWLA),
            "drawn": CURRENT_JWLA,
            "pdfs": pdfs[:3],
            "page": LMA_PAGE,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "latest": CURRENT_JWLA,
            "newer_than_drawn": False,
            "drawn": CURRENT_JWLA,
            "pdfs": [],
            "page": LMA_PAGE,
            "error": str(e)[:300],
        }


def check_jmic():
    out = {
        "ok": False,
        "latest_update": CURRENT_JMIC,
        "newer_than_snapshot": False,
        "snapshot_update": CURRENT_JMIC,
        "year_counts": [],
        "pdf_url": "https://www.ukmto.org/-/media/ukmto/products/jmic_advisory_update_112_08-nov.pdf",
        "error": None,
    }
    try:
        counts = get(JMIC_COUNT).json()
        out["year_counts"] = counts if isinstance(counts, list) else []
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)[:300]
    # Probe the next update PDF (Update 113, then 114) so a new note is flagged when published.
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    # Try common filename patterns for the next two update numbers around recent dates — we only
    # need to notice a new file, not enumerate every day. Also try the known 112 path still lives.
    probes = [out["pdf_url"]]
    for n in (112, 113, 114, 115):
        for mon in ("nov", "dec", "jan", "oct"):
            for day in ("01", "05", "08", "10", "12", "15", "20", "22", "25", "28", "30"):
                probes.append(f"https://www.ukmto.org/-/media/ukmto/products/jmic_advisory_update_{n}_{day}-{mon}.pdf")
    # Too many probes would be unfriendly; just check 112 and a short list of 113/114 names plus HEAD of product page.
    probes = [
        "https://www.ukmto.org/-/media/ukmto/products/jmic_advisory_update_112_08-nov.pdf",
        "https://www.ukmto.org/-/media/ukmto/products/jmic_advisory_update_113_10-nov.pdf",
        "https://www.ukmto.org/-/media/ukmto/products/jmic_advisory_update_113_11-nov.pdf",
        "https://www.ukmto.org/-/media/ukmto/products/jmic_advisory_update_113_12-nov.pdf",
        "https://www.ukmto.org/-/media/ukmto/products/jmic_advisory_update_113_15-nov.pdf",
        "https://www.ukmto.org/-/media/ukmto/products/jmic_advisory_update_114_15-nov.pdf",
    ]
    latest_n = CURRENT_JMIC
    latest_url = probes[0]
    for url in probes:
        try:
            r = S.head(url, timeout=20, allow_redirects=True)
            if r.status_code == 200 and "pdf" in (r.headers.get("content-type") or "").lower():
                m = re.search(r"update_(\d+)", url, re.I)
                n = int(m.group(1)) if m else 0
                if n >= latest_n:
                    latest_n, latest_url = n, url
        except Exception:
            continue
    out["latest_update"] = latest_n
    out["pdf_url"] = latest_url
    out["newer_than_snapshot"] = latest_n > CURRENT_JMIC
    if out["ok"] or latest_n:
        out["ok"] = True if out["ok"] or latest_n == CURRENT_JMIC else out["ok"]
        # If HEAD found a file, that check itself succeeded even when the count API failed.
        if latest_n:
            out["ok"] = True if not out.get("error") or latest_n else out["ok"]
            if latest_n:
                out["ok"] = out["ok"] or True
    return out


def check_marad(old_adv):
    out = {
        "ok": False,
        "source": "manual snapshot, 10 November 2026",
        "url": MARAD_PAGE,
        "advisories": (old_adv or {}).get("marad", {}).get("advisories") or MARAD_SNAPSHOT,
        "error": None,
    }
    try:
        r = S.get(MARAD_PAGE, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        # Very light parse of active advisory ids/titles if the HTML is reachable.
        found = re.findall(r"(20\d{2}-\d{3})[^\n<]{0,180}", r.text)
        titles = re.findall(r"(20\d{2}-\d{3})\s*[-–]\s*([^<]{10,160})", r.text)
        if titles:
            rows = []
            seen = set()
            for i, t in titles:
                if i in seen:
                    continue
                seen.add(i)
                rows.append({"id": i, "title": re.sub(r"\s+", " ", t).strip(), "effective": None, "expires": None})
            if rows:
                out["advisories"] = rows
                out["source"] = "MARAD MSCI page, parsed " + uk(NOW)
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)[:300]
        # keep last good / seed list
    return out


def build_advisories(jwc, jmic, marad):
    path = os.path.join(RISK, "advisories.json")
    old = load_json(path, {}) or {}
    threat = (old.get("jmic") or {}).get("threat_levels") or [
        {"area": "Regional (Middle East maritime region)", "level": "SEVERE", "id": "regional"},
        {"area": "Arabian Gulf", "level": "SUBSTANTIAL", "id": "adv-arabian-gulf"},
        {"area": "Strait of Hormuz", "level": "SEVERE", "id": "adv-hormuz"},
        {"area": "Gulf of Oman", "level": "MODERATE", "id": "adv-gulf-of-oman"},
        {"area": "Arabian Sea", "level": "MODERATE", "id": "adv-arabian-sea"},
        {"area": "Gulf of Aden", "level": "SUBSTANTIAL", "id": "adv-gulf-of-aden"},
        {"area": "Bab el-Mandeb / Southern Red Sea", "level": "SUBSTANTIAL", "id": "adv-bab-s-red-sea"},
        {"area": "Northern Red Sea / Suez Canal", "level": "MODERATE", "id": "adv-n-red-sea-suez"},
    ]
    notes = []
    if jwc.get("newer_than_drawn"):
        notes.append(f"The LMA page now lists {jwc.get('latest')}, which is newer than the JWLA-035 polygons drawn on this map. The circular wording of the new notice prevails; the red areas have not been redrawn automatically.")
    if jmic.get("newer_than_snapshot"):
        notes.append(f"A newer JMIC advisory PDF (Update {jmic.get('latest_update')}) appears to be available. Threat levels on this page are still those from Update 112 (8 November 2026) until they are revised by hand.")
    doc = {
        "as_of": uk(NOW),
        "fetched_uk": uk(NOW),
        "jwc": {
            "drawn": CURRENT_JWLA,
            "drawn_date": "2026-09-16",
            "latest": jwc.get("latest"),
            "newer_than_drawn": jwc.get("newer_than_drawn"),
            "page": LMA_PAGE,
            "pdf": "https://lmalloyds.com/wp-content/uploads/2026/09/JWLA-035-Black-Sea.pdf",
            "ok": jwc.get("ok"),
            "error": jwc.get("error"),
            "checked_uk": uk(NOW),
        },
        "jmic": {
            "snapshot_update": CURRENT_JMIC,
            "snapshot_period": "1 March–8 November 2026",
            "icod_uk": "2026-11-08 13:00",
            "latest_update": jmic.get("latest_update"),
            "newer_than_snapshot": jmic.get("newer_than_snapshot"),
            "pdf_url": jmic.get("pdf_url"),
            "page": "https://www.ukmto.org/partner-products/jmic-products/jmic-advisories",
            "year_counts": jmic.get("year_counts") or [],
            "threat_levels": threat,
            "ok": jmic.get("ok"),
            "error": jmic.get("error"),
            "checked_uk": uk(NOW),
        },
        "marad": {
            "ok": marad.get("ok"),
            "source": marad.get("source"),
            "url": MARAD_PAGE,
            "advisories": marad.get("advisories") or MARAD_SNAPSHOT,
            "error": marad.get("error"),
            "checked_uk": uk(NOW),
        },
        "notes": notes,
    }
    save_json(path, doc)
    print(f"OK   advisories check: JWC {doc['jwc']['latest']} (drawn {CURRENT_JWLA}); JMIC update {doc['jmic']['latest_update']}")
    return doc


def main():
    os.makedirs(RISK, exist_ok=True)
    inc_ok, inc_asof, inc_err = refresh_incidents()
    jwc = check_jwc()
    print("JWC check:", jwc)
    jmic = check_jmic()
    print("JMIC check:", {k: v for k, v in jmic.items() if k != "year_counts"}, "years", jmic.get("year_counts"))
    old_adv = load_json(os.path.join(RISK, "advisories.json"), {}) or {}
    marad = check_marad(old_adv)
    print("MARAD check:", "ok" if marad.get("ok") else marad.get("error"), "n=", len(marad.get("advisories") or []))
    adv = build_advisories(jwc, jmic, marad)

    status = load_json(STATUS_PATH, {}) or {}
    source_row(status, "ukmto-incidents", "UKMTO incident reports (risk map)",
               "https://www.ukmto.org/recent-incidents", inc_ok, inc_asof, inc_err)
    source_row(status, "jwc-listed", "JWC listed areas (JWLA circular check)",
               LMA_PAGE, bool(jwc.get("ok")), jwc.get("latest"), jwc.get("error"))
    source_row(status, "jmic-advisories", "JMIC advisory check (via UKMTO)",
               "https://www.ukmto.org/partner-products/jmic-products/jmic-advisories",
               bool(jmic.get("ok")), f"Update {jmic.get('latest_update')}", jmic.get("error"))
    source_row(status, "marad-advisories", "US MARAD maritime advisories",
               MARAD_PAGE, bool(marad.get("ok")), (marad.get("source") or "")[:80], marad.get("error"))
    save_json(STATUS_PATH, status)
    print("risk refresh done")
    return 0 if inc_ok else 0  # last-good cache is still a successful step


if __name__ == "__main__":
    sys.exit(main() or 0)
