#!/usr/bin/env python3
"""One-off builder for data/risk/zones.json (JWC JWLA-035 polygons + advisory areas).

Needs shapely and a Natural Earth countries/ocean GeoJSON (public domain).
Not run by GitHub Actions; the committed zones.json is the source the site uses.
The circular wording of JWLA-035 prevails over these illustrations.
"""
from __future__ import annotations
import json, os, sys, urllib.request
from pathlib import Path

# Allow running from a venv
try:
    from shapely.geometry import shape, mapping, Polygon, MultiPolygon, LineString, box, Point
    from shapely.ops import unary_union, transform
    from shapely.validation import make_valid
except ImportError:
    sys.exit("shapely is required to rebuild zones.json")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "risk" / "zones.json"
CACHE = Path("/tmp/geodata")
CACHE.mkdir(parents=True, exist_ok=True)

NE_COUNTRIES = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
NE_OCEAN = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_ocean.geojson"

# 12 nautical miles in degrees of latitude
NM12 = 12 / 60.0  # 0.2 deg

LISTED_COUNTRIES = {
    # Natural Earth ADMIN name -> display name
    "Benin": "Benin",
    "Djibouti": "Djibouti",
    "Eritrea": "Eritrea",
    "Libya": "Libya",
    "Nigeria": "Nigeria",
    "Somalia": "Somalia",
    "Sudan": "Sudan",
    "Togo": "Togo",
    "Bahrain": "Bahrain",
    "Iran": "Iran",
    "Iraq": "Iraq",
    "Israel": "Israel",
    "Kuwait": "Kuwait",
    "Lebanon": "Lebanon",
    "Oman": "Oman",
    "Qatar": "Qatar",
    "Saudi Arabia": "Saudi Arabia",
    "Syria": "Syria",
    "United Arab Emirates": "United Arab Emirates",
    "Yemen": "Yemen",
    "Russia": "Russia",
    "Venezuela": "Venezuela",
}

# Used only to subtract 12nm from the Black Sea listed area / Egyptian Red Sea
SUBTRACT = ["Romania", "Bulgaria", "Turkey", "Georgia", "Egypt"]
KEEP_BLACK = ["Russia", "Ukraine"]
CABO = ["Mozambique", "Tanzania"]


def fetch(url, name):
    p = CACHE / name
    if p.exists() and p.stat().st_size > 1000:
        print("cache", p)
        return json.loads(p.read_text())
    print("download", url)
    req = urllib.request.Request(url, headers={"User-Agent": "shipping-control-centre-zone-builder"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    p.write_bytes(data)
    return json.loads(data)


def valid(g):
    if g is None or g.is_empty:
        return None
    if not g.is_valid:
        g = make_valid(g)
    return g if g and not g.is_empty else None


def buf12(geom, lat_hint=None):
    """Approximate 12nm buffer. Scale longitude so 1 deg ~ 1 deg lat, buffer 0.2, scale back."""
    g = valid(geom)
    if not g:
        return None
    c = g.centroid
    lat = lat_hint if lat_hint is not None else c.y
    k = max(0.15, abs(math_cos(lat)))
    def to_eq(x, y, z=None):
        return (x * k, y)
    def from_eq(x, y, z=None):
        return (x / k, y)
    scaled = transform(lambda x, y, z=None: to_eq(x, y), g)
    b = scaled.buffer(NM12, resolution=8)
    return valid(transform(lambda x, y, z=None: from_eq(x, y), b))


def math_cos(lat):
    import math
    return math.cos(math.radians(lat))


def load_countries(fc):
    out = {}
    for feat in fc["features"]:
        props = feat.get("properties") or {}
        name = props.get("ADMIN") or props.get("NAME") or props.get("name")
        g = valid(shape(feat["geometry"]))
        if name and g:
            out[name] = g
    return out


def simplify(g, tol=0.08):
    g = valid(g)
    if not g:
        return None
    s = g.simplify(tol, preserve_topology=True)
    return valid(s) or g


def to_gj(g, tol=0.08):
    g = simplify(g, tol)
    if not g:
        return None
    # Drop tiny bits
    if g.geom_type == "GeometryCollection":
        parts = [p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon") and p.area > 0.002]
        if not parts:
            return None
        g = unary_union(parts)
    if g.geom_type == "MultiPolygon":
        parts = [p for p in g.geoms if p.area > 0.002]
        if not parts:
            return None
        g = parts[0] if len(parts) == 1 else MultiPolygon(parts)
    if g.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    return mapping(g)


def feat(fid, name, layer, color, geometry, **props):
    gj = to_gj(geometry, props.pop("tol", 0.08))
    if not gj:
        print("skip empty", fid)
        return None
    return {
        "type": "Feature",
        "id": fid,
        "properties": {
            "id": fid,
            "name": name,
            "layer": layer,  # jwc | advisory
            "color": color,
            **props,
        },
        "geometry": gj,
    }


def main():
    countries_fc = fetch(NE_COUNTRIES, "ne_50m_admin_0_countries.geojson")
    ocean_fc = fetch(NE_OCEAN, "ne_50m_ocean.geojson")
    C = load_countries(countries_fc)
    print("countries loaded", len(C), "sample", list(C)[:8])
    missing = [n for n in list(LISTED_COUNTRIES) + SUBTRACT + KEEP_BLACK + CABO if n not in C]
    if missing:
        # try alternate names
        aliases = {
            "Syria": ["Syrian Arab Republic", "Syria"],
            "Russia": ["Russian Federation", "Russia"],
            "Iran": ["Iran, Islamic Republic of", "Iran"],
            "Venezuela": ["Venezuela, Bolivarian Republic of", "Venezuela"],
        }
        for n in list(missing):
            for a in aliases.get(n, []):
                if a in C:
                    C[n] = C[a]
                    missing.remove(n)
                    break
        # fuzzy
        if missing:
            print("looking up", missing)
            for k in list(C):
                for n in list(missing):
                    if n.lower() in k.lower() or k.lower() in n.lower():
                        C[n] = C[k]
                        missing.remove(n)
                        print("mapped", n, "->", k)
    if missing:
        print("WARNING still missing", missing)

    ocean = valid(unary_union([shape(f["geometry"]) for f in ocean_fc["features"]]))
    land = valid(unary_union(list(C.values())))
    print("ocean/land ready", ocean.area if ocean else None, land.area if land else None)

    features = []

    # ---- Defined waters: Cabo Delgado ----
    # North: Mnazi Bay 10°19.6'S, 40°18.9'E to high seas 10°10.3'S, 40°34.44'E
    # South: Baía do Lúrio 13°30'S, 40°31.6'E to high seas 13°29.97'S, 40°49.7'E
    cabo_poly = Polygon([
        (40.315, -10.3267),  # Mnazi Bay
        (40.574, -10.1717),  # high seas N
        (40.8283, -13.4995),  # high seas S
        (40.5267, -13.5),  # Baía do Lúrio
        (40.315, -10.3267),
    ])
    cabo_states = unary_union([C[n] for n in CABO if n in C])
    cabo_sea = buf12(cabo_states)
    if cabo_sea and land:
        cabo_sea = valid(cabo_sea.difference(land))
    cabo = valid(cabo_poly.intersection(cabo_sea or cabo_poly).intersection(ocean or cabo_poly))
    features.append(feat(
        "jwc-cabo-delgado", "Cabo Delgado (defined waters)", "jwc", "red", cabo or cabo_poly,
        meaning="JWC listed area. Ships entering must notify hull-war underwriters. Rating is a private negotiation; the Joint War Committee does not set premiums.",
        circular="JWLA-035, 16 September 2026",
        detail="Territorial sea of Mozambique and Tanzania between the north line (Mnazi Bay 10°19.6'S, 40°18.9'E to high seas 10°10.3'S, 40°34.44'E) and the south line (Baía do Lúrio 13°30'S, 40°31.6'E to high seas 13°29.97'S, 40°49.7'E).",
        tol=0.02,
    ))

    # ---- Gulf of Guinea defined waters ----
    # Togo coast 6°06′45″N, 1°12′E, south to 0°40′S, 3°00′E, east to Cape Lopez 0°40′S, 8°42′E, then along coast back.
    gog_fence = Polygon([
        (1.2, 6.1125),  # Togo coast
        (3.0, -0.6667),  # high seas
        (8.7, -0.6667),  # Cape Lopez lat
        (8.7, 0.8),  # Cape Lopez / Gabon coast
        (9.5, 1.5),
        (10.0, 4.0),
        (8.5, 4.8),
        (7.0, 4.5),
        (5.0, 5.0),
        (3.5, 6.3),
        (2.0, 6.3),
        (1.2, 6.1125),
    ])
    gog = valid((gog_fence.intersection(ocean) if ocean else gog_fence))
    features.append(feat(
        "jwc-gulf-of-guinea", "Gulf of Guinea (defined waters)", "jwc", "red", gog or gog_fence,
        meaning="JWC listed area. Ships entering must notify hull-war underwriters. Rating is a private negotiation; the Joint War Committee does not set premiums.",
        circular="JWLA-035, 16 September 2026",
        detail="Waters enclosed on the west from the coast of Togo 6°06′45″N, 1°12′E, south to high seas 0°40′S, 3°00′E, then east to Cape Lopez Peninsula, Gabon 0°40′S, 8°42′E.",
        tol=0.04,
    ))

    # ---- Red Sea / GOA / IO / Gulf of Oman / Arabian Gulf defined waters ----
    io_fence = Polygon([
        # Southern Red Sea south of 25.5N (wide enough to include the sea, land clipped later)
        (32.4, 25.5),
        (38.2, 25.5),
        (43.8, 16.5),
        (45.5, 13.0),
        (52.5, 16.0),
        # Pakistan coast at 25°19'15"N, 65°E, then the eastern fence
        (65.0, 25.321),
        (65.0, 10.8),
        (60.25, 10.8),
        (48.75, -6.75),
        (41.5667, -1.6667),  # Somalia border
        (43.0, 1.5),
        (39.0, 12.0),
        (36.0, 20.0),
        (32.4, 25.5),
    ])
    # Arabian / Persian Gulf + Hormuz + Gulf of Oman, to join the IO box
    gulf_fence = Polygon([
        (47.5, 29.9),  # Shatt al-Arab / Iraq
        (47.8, 27.5),
        (48.5, 25.5),
        (50.8, 24.5),
        (54.0, 24.2),
        (56.0, 24.8),
        (56.6, 25.2),  # Hormuz south
        (57.2, 25.5),
        (58.5, 24.8),
        (60.5, 24.5),
        (61.5, 25.3),
        (62.0, 25.6),  # Iran/Makran toward 65E box
        (65.0, 25.321),
        (65.0, 22.0),
        (60.0, 22.0),
        (58.0, 23.0),
        (56.8, 24.0),
        (55.8, 24.8),
        (55.0, 25.5),
        (53.5, 25.5),
        (52.0, 26.5),
        (50.0, 27.8),
        (48.0, 29.5),
        (47.5, 29.9),
    ])
    combined = valid(unary_union([make_valid(io_fence.buffer(0)), make_valid(gulf_fence.buffer(0))]))
    if ocean and combined:
        combined = valid(combined.intersection(ocean))
    # Subtract Egyptian territorial waters (12nm), as the circular excludes them
    if "Egypt" in C:
        eg = buf12(C["Egypt"], lat_hint=24)
        if eg and combined:
            combined = valid(combined.difference(eg)) or combined
    features.append(feat(
        "jwc-red-sea-gulf-io",
        "Southern Red Sea, Gulf of Aden, Arabian Sea, Gulf of Oman and Arabian Gulf (defined waters)",
        "jwc", "red", combined or io_fence,
        meaning="JWC listed area. Ships entering must notify hull-war underwriters. Rating is a private negotiation; the Joint War Committee does not set premiums.",
        circular="JWLA-035, 16 September 2026",
        detail="Waters enclosed: Red Sea south of 25.5°N (Egyptian territorial waters excluded); from the Pakistan coastline at 25°19′15″N, 65°E; east by a line to 10°48′N, 65°E, then 10°48′N, 60°15′E, then 6°45′S, 48°45′E; southwest from the Somalia border at 1°40′S, 41°34′E to 6°45′S, 48°45′E. The heading also includes the Persian/Arabian Gulf and Gulf of Oman. This is our reading of those limits, not an official chart.",
        tol=0.06,
    ))

    # ---- Europe: Sea of Azov + Black Sea excluding TW of RO/BG/TR/GE ----
    azov_box = box(34.7, 45.15, 39.4, 47.4)
    black_box = box(27.4, 40.9, 41.8, 47.4)
    azov = valid(azov_box.intersection(ocean) if ocean else azov_box)
    black = valid(black_box.intersection(ocean) if ocean else black_box)
    # Remove Azov from black to avoid double-fill, then we'll add both
    if black and azov:
        black = valid(black.difference(azov.buffer(0.05))) or black
    subtract_geoms = [C[n] for n in SUBTRACT if n in C and n != "Egypt"]
    if subtract_geoms:
        sub = buf12(unary_union(subtract_geoms), lat_hint=42)
        if sub and black:
            black = valid(black.difference(sub)) or black
    features.append(feat(
        "jwc-sea-of-azov", "Sea of Azov", "jwc", "red", azov or azov_box,
        meaning="JWC listed area. Ships entering must notify hull-war underwriters. Rating is a private negotiation; the Joint War Committee does not set premiums.",
        circular="JWLA-035, 16 September 2026",
        detail="The Sea of Azov is listed in full under JWLA-035 (Europe, defined waters item 1).",
        tol=0.03,
    ))
    features.append(feat(
        "jwc-black-sea", "Black Sea (except some territorial waters)", "jwc", "red", black or black_box,
        meaning="JWC listed area. Ships entering must notify hull-war underwriters. Rating is a private negotiation; the Joint War Committee does not set premiums.",
        circular="JWLA-035, 16 September 2026",
        detail="JWLA-035 lists the Black Sea excluding territorial waters of adjoining countries other than Russia and Ukraine. This drawing insets about 12 nautical miles off Romania, Bulgaria, Turkey and Georgia. Inland waters of Ukraine (including Crimea and other Ukrainian territories under Russian control), the River Don to 41°E, the River Donets to the Ukraine border, and Belarus south of 52°30′N are also listed in the circular but are not drawn in full here. The circular wording prevails.",
        tol=0.04,
    ))

    # ---- Named-country 12nm belts ----
    for admin, display in LISTED_COUNTRIES.items():
        if admin not in C:
            print("no geom", admin)
            continue
        belt = buf12(C[admin])
        if belt and land:
            belt = valid(belt.difference(land))
        if belt and ocean:
            belt = valid(belt.intersection(ocean))
        # Venezuela: include EEZ installations — we only draw the 12nm belt and note the EEZ
        extra = ""
        if admin == "Venezuela":
            extra = " The circular also includes all offshore installations in the Venezuelan EEZ, which extend beyond this 12 nautical mile belt and are not drawn here."
        if admin == "Iraq":
            extra = " Including all Iraqi offshore oil terminals."
        if admin == "Russia":
            extra = " Russia is listed as a named country (ports and coastal waters to 12 nautical miles), in addition to the Black Sea / Azov / inland-water entries."
        features.append(feat(
            "jwc-" + admin.lower().replace(" ", "-"),
            f"{display} (ports and 12 nm coastal waters)",
            "jwc", "red", belt,
            meaning="JWC listed area. Named countries include their ports and coastal waters up to 12 nautical miles offshore, unless specifically varied. Ships entering must notify hull-war underwriters. Rating is a private negotiation; the Joint War Committee does not set premiums.",
            circular="JWLA-035, 16 September 2026",
            detail=f"Our 12 nautical mile coastal belt is drawn from a public-domain coastline and is illustrative only.{extra} The circular wording prevails.",
            tol=0.06 if admin in ("Russia", "Somalia", "Saudi Arabia", "Libya", "Iran") else 0.04,
        ))

    # Guyana is offshore EEZ calls only — draw a light hatched box in the offshore area, not the 12nm belt
    # Approximate Guyanese EEZ beyond 12nm: offshore Guyana ~7-10N, 56-58.5W, outside 12nm
    if "Guyana" in C:
        gy = C["Guyana"]
        # rough EEZ box east of Guyana, minus 12nm
        gy_box = box(-58.6, 5.8, -55.0, 10.2)
        gy12 = buf12(gy, lat_hint=7)
        gy_off = gy_box
        if ocean:
            gy_off = gy_off.intersection(ocean)
        if gy12:
            gy_off = gy_off.difference(gy12)
        if land:
            gy_off = gy_off.difference(land)
        features.append(feat(
            "jwc-guyana-offshore",
            "Guyana (offshore EEZ installations only)",
            "jwc", "red", valid(gy_off),
            meaning="JWC listed area, but only for calls to offshore installations in the Guyanese EEZ beyond territorial waters — not for the territorial sea itself. Ships making those calls must notify hull-war underwriters. Rating is a private negotiation.",
            circular="JWLA-035, 16 September 2026",
            detail="The circular lists Guyana only for calls to offshore installations in the EEZ beyond territorial waters. The shaded area is a rough offshore box, not an official EEZ chart.",
            tol=0.05,
        ))

    # ---- Amber advisory areas (JMIC / UKMTO / MARAD named areas) ----
    def adv(fid, name, poly, level, notes, source):
        g = valid(poly.intersection(ocean) if ocean else poly)
        features.append(feat(
            fid, name, "advisory", "amber", g or poly,
            meaning="Naval / industry advisory area. This is not a JWC listed-area boundary. Cover and routing decisions remain with owners, masters and insurers.",
            threat_level=level,
            threat_as_of="2026-11-08 13:00",
            threat_as_of_note="JMIC Update 112, ICOD 08 Nov 2026 13:00 UTC (13:00 UK).",
            detail=notes,
            source=source,
            circular="JMIC Update 112, 1 March–8 November 2026",
            tol=0.06,
        ))

    # UKMTO VRA: Suez to western Hormuz, 078°E, 10°S (indicative)
    vra = Polygon([
        (32.3, 31.2),  # Port Said / Suez north
        (32.6, 29.9),
        (33.9, 27.7),
        (34.2, 25.5),
        (38.0, 22.0),
        (42.5, 16.0),
        (44.0, 12.4),
        (52.0, 15.5),
        (56.0, 26.8),  # west entrance Hormuz
        (57.5, 27.2),
        (78.0, 26.0),
        (78.0, -10.0),
        (40.0, -10.0),
        (32.3, 12.0),
        (32.3, 31.2),
    ])
    adv("adv-ukmto-vra", "UKMTO Voluntary Reporting Area",
        vra, None,
        "Indicative outline of the UKMTO Voluntary Reporting Area (Suez, the western entrance to the Strait of Hormuz, longitude 078°E and latitude 10°S, as commonly described; the authoritative picture is Admiralty Maritime Security Chart Q6099). Reporting to UKMTO is voluntary. This is not a JWC boundary.",
        "UKMTO")

    adv("adv-hormuz", "Strait of Hormuz",
        box(55.3, 25.2, 57.8, 27.3),
        "SEVERE",
        "JMIC threat level SEVERE as of 8 November 2026: deliberate attacks considered highly likely. Several tanker attacks were reported off the Musandam coast in early November 2026.",
        "JMIC Update 112")
    adv("adv-arabian-gulf", "Arabian Gulf",
        Polygon([(47.6, 30.0), (47.8, 27.0), (50.5, 24.4), (54.2, 24.3), (56.2, 25.3), (55.0, 26.8), (52.0, 28.0), (48.2, 30.1), (47.6, 30.0)]),
        "SUBSTANTIAL",
        "JMIC threat level SUBSTANTIAL as of 8 November 2026, citing Iranian attacks and increased navigation interference. An attack is assessed as a strong possibility, including in the northern and central Gulf, anchorages and STS areas.",
        "JMIC Update 112")
    adv("adv-gulf-of-oman", "Gulf of Oman",
        box(56.6, 22.8, 62.5, 26.4),
        "MODERATE",
        "JMIC threat level MODERATE as of 8 November 2026. Persistent IRGC monitoring and routing pressure in the western Gulf of Oman; blockade-enforcement activity has also been reported.",
        "JMIC Update 112")
    adv("adv-arabian-sea", "Arabian Sea",
        box(58.0, 10.0, 73.0, 25.0),
        "MODERATE",
        "JMIC threat level MODERATE as of 8 November 2026, with no imminent change indicated in that update.",
        "JMIC Update 112")
    adv("adv-gulf-of-aden", "Gulf of Aden",
        box(43.0, 10.8, 52.2, 15.4),
        "SUBSTANTIAL",
        "JMIC threat level SUBSTANTIAL as of 8 November 2026, citing piracy-related events and Houthi activity in coastal approaches and transit corridors.",
        "JMIC Update 112")
    adv("adv-bab-s-red-sea", "Bab el-Mandeb and Southern Red Sea",
        Polygon([(41.8, 18.2), (43.7, 18.2), (45.2, 12.0), (43.2, 11.3), (42.0, 12.4), (41.8, 15.5), (41.8, 18.2)]),
        "SUBSTANTIAL",
        "JMIC threat level SUBSTANTIAL as of 8 November 2026. The strait remains open but is described as volatile, including a Houthi selective embargo of Saudi-linked shipping.",
        "JMIC Update 112")
    adv("adv-n-red-sea-suez", "Northern Red Sea and Suez Canal",
        Polygon([(32.2, 31.3), (32.7, 29.9), (34.0, 27.5), (34.4, 22.0), (39.5, 22.0), (39.5, 28.5), (35.0, 31.5), (32.2, 31.3)]),
        "MODERATE",
        "JMIC threat level MODERATE as of 8 November 2026. Suez Canal operations were described as normal, with periodic electromagnetic interference possible.",
        "JMIC Update 112")
    # MARAD Black Sea / Azov advisory (overlaps JWC; useful when JWC layer is off)
    adv("adv-black-sea-marad", "Black Sea and Sea of Azov (US maritime advisory)",
        box(27.4, 40.9, 41.8, 47.4),
        None,
        "US Maritime Advisory 2026-012 (Black Sea and Sea of Azov — military combat operations) was active as of 10 November 2026, effective 23 September 2026 to 22 March 2027. This outline is a named-area box, not an official MARAD polygon. MARAD's pages sometimes block automated fetches, so the list is checked when possible and otherwise kept as a dated snapshot.",
        "US MARAD MSCI 2026-012")

    features = [f for f in features if f]
    doc = {
        "type": "FeatureCollection",
        "as_of": "2026-11-10",
        "circular": "JWLA-035",
        "circular_date": "2026-09-16",
        "circular_url": "https://lmalloyds.com/wp-content/uploads/2026/09/JWLA-035-Black-Sea.pdf",
        "listed_areas_page": "https://lmalloyds.com/specialist-areas/underwriting/listed-areas/",
        "disclaimer": "JWC listed-area polygons are our reading of Joint War Committee circular JWLA-035 (16 September 2026), drawn from the published coordinates and a public-domain coastline. They are illustrative only. The wording of the circular prevails. The Joint War Committee does not set premiums; ships sailing into a listed area would be required to notify underwriters, and rating is a matter for negotiation. Advisory (amber) areas are indicative naval and industry warning footprints, not official legal boundaries. Not insurance, routing or navigation advice.",
        "coastline_source": "Natural Earth 50m countries and ocean (public domain), used only to draw 12 nautical mile coastal belts and to clip land from the defined-water boxes.",
        "features": features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    print("wrote", OUT, "features", len(features), "bytes", OUT.stat().st_size)
    for f in features:
        print(" ", f["id"], f["properties"]["layer"], f["geometry"]["type"])


if __name__ == "__main__":
    main()
