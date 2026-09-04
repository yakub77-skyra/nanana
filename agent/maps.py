import os, math, json, time, hashlib
import httpx
from PIL import Image, ImageOps
from loguru import logger
from pathlib import Path
from .config import settings

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
CACHE_DIR = Path(settings.output_dir) / "map_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- GeoJSON Hardening ---
def _load_states_geojson():
    cache_file = CACHE_DIR / "states.geojson"
    if cache_file.exists() and cache_file.stat().st_size > 10000:
        try: return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception: pass
    
    url = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson"
    try:
        r = httpx.get(url, timeout=60, headers=UA)
        if r.status_code == 200:
            data = r.json()
            if data.get("features"):
                cache_file.write_text(json.dumps(data), encoding="utf-8")
                return data
    except Exception as e:
        logger.warning(f"GeoJSON fetch failed: {e}")
    return {"features": []}

def _get_state_feature(name):
    if not name: return None
    gj = _load_states_geojson().get("features", [])
    n = name.lower().strip()
    aliases = {"jammu kashmir": "jammu and kashmir", "j&k": "jammu and kashmir", "orissa": "odisha", "chattisgarh": "chhattisgarh", "uk": "uttarakhand", "up": "uttar pradesh", "delhi": "delhi"}
    n = aliases.get(n, n)
    
    for f in gj:
        p = f.get("properties", {})
        if p.get("admin") != "India": continue
        fname = (p.get("name") or p.get("NAME_1") or "").lower()
        if fname == n or n in fname or fname in n:
            return f
    return None

# --- Mercator Math ---
def lon_to_x(lon, z): return (lon + 180.0) / 360.0 * (1 << z)
def lat_to_y(lat, z): return (1.0 - math.log(math.tan(lat * math.pi / 180.0) + 1.0 / math.cos(lat * math.pi / 180.0)) / math.pi) / 2.0 * (1 << z)

def _download_tile(z, x, y):
    # Try ESRI Satellite first, fallback to OSM
    urls = [
        f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    ]
    for url in urls:
        try:
            r = httpx.get(url, timeout=10, headers=UA)
            if r.status_code == 200 and len(r.content) > 1000:
                return Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception: continue
    return None

import io

def stitch_map(center_lon, center_lat, z, grid_w=3, grid_h=4):
    """Stitches a grid of tiles around a center point."""
    cx_tile = lon_to_x(center_lon, z)
    cy_tile = lat_to_y(center_lat, z)
    
    start_x = int(cx_tile - grid_w / 2)
    start_y = int(cy_tile - grid_h / 2)
    
    img_w, img_h = grid_w * 256, grid_h * 256
    stitched = Image.new("RGB", (img_w, img_h), (20, 25, 30)) # Dark fallback
    
    for dy in range(grid_h):
        for dx in range(grid_w):
            tile = _download_tile(z, start_x + dx, start_y + dy)
            if tile:
                stitched.paste(tile, (dx * 256, dy * 256))
    
    # Grayscale and darken for the "satellite" look
    stitched = ImageOps.grayscale(stitched).convert("RGB")
    # PIL.ImageOps has no enhance method, use ImageEnhance instead
    from PIL import ImageEnhance
    stitched = ImageEnhance.Contrast(stitched).enhance(1.2)
    
    # Calculate centroid pixel in the stitched image
    px_x = (cx_tile - start_x) * 256
    px_y = (cy_tile - start_y) * 256
    
    # Scale to 1080x1920 viewport
    vp_x = (px_x / img_w) * 1080
    vp_y = (px_y / img_h) * 1920
    
    return stitched, vp_x, vp_y

def get_state_svg_path(feature, z, start_x, start_y, grid_w, grid_h):
    """Converts GeoJSON coordinates to SVG path relative to the stitched grid."""
    if not feature: return ""
    geom = feature.get("geometry", {})
    coords = geom.get("coordinates", [])
    if geom.get("type") == "MultiPolygon": coords = [c[0] for c in coords]
    elif geom.get("type") == "Polygon": coords = [coords[0]]
    
    paths = []
    for ring in coords:
        pts = []
        for lon, lat in ring:
            px_x = (lon_to_x(lon, z) - start_x) * 256
            px_y = (lat_to_y(lat, z) - start_y) * 256
            # Scale to 1080x1920
            vp_x = (px_x / (grid_w * 256)) * 1080
            vp_y = (px_y / (grid_h * 256)) * 1920
            pts.append(f"{vp_x:.1f},{vp_y:.1f}")
        if pts: paths.append("M" + "L".join(pts) + "Z")
    return " ".join(paths)

def build_state_pack(state_name):
    """Returns bg_b64, state_svg, cx, cy for the news_frame."""
    feat = _get_state_feature(state_name)
    if not feat:
        # Fallback to center of India
        feat = _get_state_feature("Madhya Pradesh") 
        if not feat: return None
        
    props = feat.get("properties", {})
    # Centroid
    c_lon = props.get("longitude") or 82.0
    c_lat = props.get("latitude") or 23.0
    
    z = 6 # Zoom level for state
    grid_w, grid_h = 4, 5
    
    img, vp_x, vp_y = stitch_map(c_lon, c_lat, z, grid_w, grid_h)
    
    cx_tile = lon_to_x(c_lon, z)
    cy_tile = lat_to_y(c_lat, z)
    start_x = int(cx_tile - grid_w / 2)
    start_y = int(cy_tile - grid_h / 2)
    
    svg_path = get_state_svg_path(feat, z, start_x, start_y, grid_w, grid_h)
    
    # Save to cache and get b64
    import base64
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    
    return {"bg_b64": b64, "state_svg": svg_path, "cx": vp_x, "cy": vp_y}

def build_india_pack():
    """Wide view of India for the intro."""
    img, _, _ = stitch_map(82.0, 22.0, z=4, grid_w=3, grid_h=4)
    import base64
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()