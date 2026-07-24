"""几何→国家（ISO3）判定共享层（2026-07 连接点亮扩展到基础设施线类）。

- isos_of_points(pts)：点在国界内（NE-50m + shapely STRtree，一次建树复用）；
  近海落点（海缆登陆站在岸线外侧）用 0.35° 缓冲最近国兜底。
- iso_by_name(name)：GEM 等来源的国家英文名 → ISO3（NE 名主表 + 别名表）。
供 build_static(cables)/build_pipelines_v2/build_transmission 产 `c` 字段。
"""
import json
import os

from common import OUT

_tree = None
_geoms = None
_isos = None
_name2iso = None

ALIASES = {
    "United States": "USA", "USA": "USA", "Russia": "RUS", "South Korea": "KOR",
    "North Korea": "PRK", "Iran": "IRN", "Syria": "SYR", "Venezuela": "VEN",
    "Bolivia": "BOL", "Tanzania": "TZA", "Democratic Republic of the Congo": "COD",
    "DR Congo": "COD", "Republic of the Congo": "COG", "Congo": "COG",
    "Czech Republic": "CZE", "Czechia": "CZE", "Türkiye": "TUR", "Turkey": "TUR",
    "Myanmar": "MMR", "Burma": "MMR", "Laos": "LAO", "Vietnam": "VNM",
    "Brunei": "BRN", "Moldova": "MDA", "North Macedonia": "MKD",
    "Bosnia and Herzegovina": "BIH", "United Kingdom": "GBR", "UK": "GBR",
    "United Arab Emirates": "ARE", "UAE": "ARE", "Ivory Coast": "CIV",
    "Côte d'Ivoire": "CIV", "Cote d'Ivoire": "CIV", "Cape Verde": "CPV",
    "East Timor": "TLS", "Timor-Leste": "TLS", "Eswatini": "SWZ",
    "The Gambia": "GMB", "Gambia": "GMB", "Palestine": "PSE", "Taiwan": "TWN",
    "Hong Kong": "HKG", "Macau": "MAC", "Macao": "MAC",
}


def _load():
    global _tree, _geoms, _isos, _name2iso
    if _tree is not None:
        return
    from shapely import STRtree
    from shapely.geometry import shape
    gj = json.load(open(os.path.join(OUT, "geometry", "ne_50m.json")))
    _geoms, _isos, _name2iso = [], [], {}
    cents = json.load(open(os.path.join(OUT, "geometry", "centroids.json")))
    for iso, row in cents.items():
        _name2iso[str(row[2]).lower()] = iso
    for f in gj["features"]:
        try:
            _geoms.append(shape(f["geometry"]))
            _isos.append(f["properties"]["iso"])
        except Exception:
            continue
    _tree = STRtree(_geoms)


def isos_of_points(pts, buffer_deg=0.35):
    """点列表 → ISO3 集合。命中国界直接归属；未命中（近海落点）在 buffer 内取最近国。"""
    from shapely.geometry import Point
    _load()
    out = set()
    for lon, lat in pts:
        p = Point(lon, lat)
        hit = None
        for i in _tree.query(p):
            if _geoms[i].covers(p):
                hit = _isos[i]
                break
        if hit is None and buffer_deg:
            best, bd = None, buffer_deg
            for i in _tree.query(p.buffer(buffer_deg)):
                d = _geoms[i].distance(p)
                if d < bd:
                    best, bd = _isos[i], d
            hit = best
        if hit:
            out.add(hit)
    return out


def iso_of_point(lon, lat, buffer_deg=0.0):
    """单点 → ISO3（栅格聚合用；build_era5_anomaly 格点归属）。
    命中国界直接归属；buffer_deg>0 时未命中在缓冲内取最近国（默认 0：格网内部
    落海即弃，不向最近国吸附——国家均温采样只要陆格）。复用一次建的 STRtree。"""
    from shapely.geometry import Point
    _load()
    p = Point(lon, lat)
    for i in _tree.query(p):
        if _geoms[i].covers(p):
            return _isos[i]
    if buffer_deg:
        best, bd = None, buffer_deg
        for i in _tree.query(p.buffer(buffer_deg)):
            d = _geoms[i].distance(p)
            if d < bd:
                best, bd = _isos[i], d
        return best
    return None


def iso_by_name(name):
    _load()
    n = (name or "").strip()
    if not n:
        return None
    if n in ALIASES:
        return ALIASES[n]
    return _name2iso.get(n.lower())
