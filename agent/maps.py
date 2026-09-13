"""Whole-India satellite base map + aligned GeoJSON overlays.

One stitched Mercator satellite mosaic (ESRI World Imagery, grayscale, dark)
covers lon 61-101 / lat 38-5 and is stretched to the 1080x1920 canvas the same
way the reference reel does. Every SVG overlay (country fill, state highlight,
number marker, connector) is drawn through the same px(lon, lat) projection, so
overlays always sit exactly on the terrain underneath.
"""
import base64, io, json, math
from pathlib import Path
import httpx
from PIL import Image, ImageOps, ImageEnhance
from loguru import logger
from .config import settings

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
CACHE_DIR = Path(settings.output_dir) / "map_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

Z = 6                      # mercator zoom for the base mosaic
W, H = 1080, 1920          # canvas
LON_MIN, LON_MAX = 61.0, 101.0
LAT_MAX, LAT_MIN = 38.0, 5.0

def _mx(lon): return (lon + 180.0) / 360.0 * (1 << Z)
def _my(lat):
    return (1.0 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * (1 << Z)

X0, X1 = _mx(LON_MIN) * 256, _mx(LON_MAX) * 256
Y0, Y1 = _my(LAT_MAX) * 256, _my(LAT_MIN) * 256

def px(lon, lat):
    """Geo -> canvas px (same mapping as the stitched background image)."""
    return ((( _mx(lon) * 256 - X0) / (X1 - X0)) * W,
            ((_my(lat) * 256 - Y0) / (Y1 - Y0)) * H)

# ---------------------------------------------------------------- tiles
def _download_tile(x, y):
    urls = [
        f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{Z}/{y}/{x}",
        f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{Z}/{y}/{x}",
    ]
    for url in urls:
        try:
            r = httpx.get(url, timeout=20, headers=UA)
            if r.status_code == 200 and len(r.content) > 1000:
                return Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception:
            continue
    return None

def _stitch():
    cache = CACHE_DIR / "base_india_z6.jpg"
    if cache.exists() and cache.stat().st_size > 100000:
        return Image.open(cache).convert("RGB")
    tx0, tx1 = int(_mx(LON_MIN)), int(_mx(LON_MAX))      # inclusive tile range
    ty0, ty1 = int(_my(LAT_MAX)), int(_my(LAT_MIN))
    grid = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (16, 18, 20))
    missing = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            t = _download_tile(tx, ty)
            if t: grid.paste(t, ((tx - tx0) * 256, (ty - ty0) * 256))
            else: missing += 1
    if missing > 8:
        logger.warning(f"{missing} map tiles missing — map may have dark patches")
    # crop to the geographic box, then stretch to the portrait canvas
    crop = grid.crop((int(X0 - tx0 * 256), int(Y0 - ty0 * 256), int(X1 - tx0 * 256), int(Y1 - ty0 * 256)))
    crop = crop.resize((W, H), Image.LANCZOS)
    crop = ImageOps.grayscale(crop).convert("RGB")
    crop = ImageEnhance.Contrast(crop).enhance(1.3)
    crop = ImageEnhance.Brightness(crop).enhance(0.62)
    crop.save(cache, "JPEG", quality=88)
    return crop

# ---------------------------------------------------------------- geojson
def _load_states_geojson():
    cache_file = CACHE_DIR / "states.geojson"
    if cache_file.exists() and cache_file.stat().st_size > 10000:
        try: return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception: pass
    url = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson"
    try:
        r = httpx.get(url, timeout=120, headers=UA)
        if r.status_code == 200 and r.json().get("features"):
            cache_file.write_text(json.dumps(r.json()), encoding="utf-8")
            return r.json()
    except Exception as e:
        logger.warning(f"states geojson fetch failed: {e}")
    return {"features": []}

def _load_countries_geojson():
    cache_file = CACHE_DIR / "countries.geojson"
    if cache_file.exists() and cache_file.stat().st_size > 10000:
        try: return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception: pass
    for url in ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson",
                "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"):
        try:
            r = httpx.get(url, timeout=120, headers=UA)
            if r.status_code == 200 and r.json().get("features"):
                cache_file.write_text(json.dumps(r.json()), encoding="utf-8")
                return r.json()
        except Exception:
            continue
    return {"features": []}

STATE_ALIASES = {"jammu kashmir": "jammu and kashmir", "j&k": "jammu and kashmir",
                 "jammu & kashmir": "jammu and kashmir", "orissa": "odisha",
                 "chattisgarh": "chhattisgarh", "uttaranchal": "uttarakhand",
                 "uk": "uttarakhand", "up": "uttar pradesh", "pondicherry": "puducherry",
                 "nct of delhi": "delhi", "national capital territory of delhi": "delhi"}

def _feat_name(f):
    p = f.get("properties", {}) or {}
    for k in ("name", "NAME", "NAME_1", "NAME_EN", "shapeName", "st_nm"):
        if p.get(k): return str(p[k]).lower().strip()
    return ""

def _rings(geom, step=2, max_rings=8):
    if geom.get("type") == "MultiPolygon":
        rings = [p[0] for p in geom.get("coordinates", [])]
    elif geom.get("type") == "Polygon":
        rings = [geom.get("coordinates", [[]])[0]]
    else:
        return []
    rings = sorted(rings, key=len, reverse=True)[:max_rings]
    return [r[::step] for r in rings]

def _d_of(ring):
    pts = [px(lo, la) for lo, la in ring]
    dedup = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - dedup[-1][0]) > 0.5 or abs(p[1] - dedup[-1][0]) > 0.5: dedup.append(p)
    if len(dedup) < 3: return ""
    return "M" + "L".join(f"{x:.0f} {y:.0f}" for x, y in dedup) + "Z"

def _state_feature(name):
    if not name: return None
    n = STATE_ALIASES.get(name.lower().strip(), name.lower().strip())
    feats = _load_states_geojson().get("features", [])
    india = [f for f in feats if (f.get("properties", {}) or {}).get("admin") == "India"
             or (f.get("properties", {}) or {}).get("iso_a2") == "IN"]
    for f in india:
        if _feat_name(f) == n: return f
    for f in india:
        fn = _feat_name(f)
        if n and fn and (n in fn or fn in n): return f
    return None

def state_path(name):
    f = _state_feature(name)
    if not f: return ""
    return " ".join(d for d in (_d_of(r) for r in _rings(f["geometry"])) if d)

def state_centroid(name):
    f = _state_feature(name)
    if not f: return (W / 2, H * 0.48)
    ring = max(_rings(f["geometry"], step=1, max_rings=1), key=len, default=[])
    if len(ring) < 4: return (W / 2, H * 0.48)
    pts = [px(lo, la) for lo, la in ring]
    a = cx = cy = 0.0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]; x2, y2 = pts[i + 1]
        cross = x1 * y2 - x2 * y1
        a += cross; cx += (x1 + x2) * cross; cy += (y1 + y2) * cross
    if abs(a) < 1e-9:
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    a *= 0.5
    return (cx / (6 * a), cy / (6 * a))

def india_path():
    for f in _load_countries_geojson().get("features", []):
        if (f.get("properties", {}).get("NAME") or "").lower() == "india":
            d = " ".join(d for d in (_d_of(r, ) for r in _rings(f["geometry"], step=2, max_rings=6)) if d)
            if d: return d
    return ""

def states_outline():
    parts = []
    for f in _load_states_geojson().get("features", []):
        p = f.get("properties", {}) or {}
        if p.get("admin") != "India" and p.get("iso_a2") != "IN": continue
        for r in _rings(f["geometry"], step=3, max_rings=3):
            d = _d_of(r)
            if d: parts.append(d)
    return " ".join(parts)

# ---------------------------------------------------------------- packs
_BG_CACHE = {}
def base_pack():
    """bg_b64 + india country path + internal state borders, all in canvas space."""
    if "pack" not in _BG_CACHE:
        buf = io.BytesIO()
        _stitch().save(buf, "JPEG", quality=85)
        _BG_CACHE["pack"] = {"bg_b64": base64.b64encode(buf.getvalue()).decode(),
                             "india_path": india_path(),
                             "outline": states_outline()}
    return _BG_CACHE["pack"]

def state_pack(state_name):
    """bg + highlight path + marker centroid for one state scene."""
    base = base_pack()
    f = _state_feature(state_name)
    path = state_path(state_name)
    cx, cy = state_centroid(state_name)
    if not path:  # unknown state -> gentle fallback so the reel still renders
        path, (cx, cy) = base["india_path"], (W / 2, H * 0.46)
    return {"bg_b64": base["bg_b64"], "outline": base["outline"],
            "state_svg": path, "cx": cx, "cy": cy}

# ---- legacy wrappers -------------------------------------------------
def build_state_pack(state_name):
    sp = state_pack(state_name)
    return {"bg_b64": sp["bg_b64"], "state_svg": sp["state_svg"], "cx": sp["cx"], "cy": sp["cy"]}

def build_india_pack():
    return base_pack()["bg_b64"]
