"""事件层快照：USGS 地震、FIRMS 火点、SWPC 极光、IBTrACS 台风回放、
闪电(合成,标注)、GPS 干扰(合成,标注)。全部对齐采集时刻的 UTC 时间基准。"""
import csv
import io
import json
import math
import os
import random
from collections import defaultdict

from common import OUT, cached_get, read_csv_text, status, write_json


def quakes():
    status("USGS earthquakes (7 days)")
    gj = json.loads(cached_get(
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson",
        "usgs_week.geojson", timeout=300))
    out = []
    for f in gj["features"]:
        c = f["geometry"]["coordinates"]
        p = f["properties"]
        if p.get("mag") is None:
            continue
        out.append([round(c[0], 3), round(c[1], 3), round(p["mag"], 1),
                    p["time"] // 1000])
    out.sort(key=lambda e: e[3])
    write_json("quakes.json", out)
    status(f"  quakes={len(out)}")


# FIRMS 24h 多卫星通道：任一停摆（如 Suomi-NPP 2026-06/07 两度异常）其余顶上。
# 保留 suomi-npp——它恢复后返回非空即自动重新参与，无需再改代码。
FIRMS_CHANNELS = [
    ("noaa-20-viirs-c2", "J1_VIIRS_C2_Global_24h", "firms_j1_24h.csv"),
    ("noaa-21-viirs-c2", "J2_VIIRS_C2_Global_24h", "firms_j2_24h.csv"),
    ("suomi-npp-viirs-c2", "SUOMI_VIIRS_C2_Global_24h", "firms_snpp_24h.csv"),
]


def fires():
    status("NASA FIRMS VIIRS 24h (multi-sat)")
    rows = []
    for sensor, fname, cache in FIRMS_CHANNELS:
        try:
            got = read_csv_text(cached_get(
                f"https://firms.modaps.eosdis.nasa.gov/data/active_fire/{sensor}/csv/{fname}.csv",
                cache, timeout=600))
            status(f"  {sensor}: {len(got)} rows")
            rows.extend(got)
        except Exception as e:  # noqa: BLE001 — 单通道故障不拖垮整层
            status(f"  {sensor}: FETCH FAILED ({e})")
    rows.sort(key=lambda r: -float(r.get("frp") or 0))
    out = []
    for r in rows[:9000]:
        try:
            out.append([round(float(r["longitude"]), 2), round(float(r["latitude"]), 2),
                        round(float(r.get("frp") or 1), 1)])
        except (ValueError, KeyError):
            continue
    # 空结果守卫：全通道停摆时保留上次产物，绝不让空数组覆盖（对齐 cached_get 的回退旧缓存策略）。
    if not out:
        prev = os.path.join(OUT, "fires.json")
        if os.path.exists(prev) and os.path.getsize(prev) > 2:
            status("::warning:: fires 全通道 0 行 — 保留上次产物，跳过写入")
            return
        status("::warning:: fires 全通道 0 行且无历史产物 — 写入空数组")
    write_json("fires.json", out)
    status(f"  fires kept={len(out)} of {len(rows)}")


def aurora():
    status("NOAA SWPC OVATION")
    d = json.loads(cached_get(
        "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json",
        "aurora.json", timeout=120))
    pts = []
    for lon, lat, val in d["coordinates"]:
        if val >= 8:  # keep meaningful probability only
            lon = lon - 360 if lon > 180 else lon
            pts.append([lon, lat, val])
    write_json("aurora.json", pts)
    status(f"  aurora cells={len(pts)}")


def storms():
    """IBTrACS 近三年：storms.json＝最新 4 个有名字风暴的完整轨迹（回放层）；
    storms_daily.json＝近 570 天全部有名风暴的**带时间戳**轨迹（历史轴日粒度：
    该日活跃台风的至当日尾迹+当日位置；每日刷新自动生长，天然含回补）。
    行 [epochHour, lon, lat, wind]，epochHour=UTC 起算小时（紧凑且日界可算）。"""
    status("IBTrACS last3years")
    text = cached_get(
        "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.last3years.list.v04r01.csv",
        "ibtracs.csv", timeout=900)
    lines = text.splitlines()
    reader = csv.DictReader(io.StringIO("\n".join([lines[0]] + lines[2:])))  # row 2 = units
    tracks = defaultdict(list)
    for r in reader:
        name = r.get("NAME") or ""
        if name in ("", "NOT_NAMED", "UNNAMED"):
            continue
        # PROVISIONAL 行的 WMO_WIND/USA_WIND 常为单个空格（truthy！），
        # `float(" ")` 抛错曾把近月台风整行丢掉（实时层"最新4"停在数月前）——
        # 必须 strip 后判空再回退（坑 #18 同类：字段名义 ≠ 内容形状）
        def fnum(x):
            x = (x or "").strip()
            return float(x) if x else 0.0
        try:
            lon, lat = float(r["LON"]), float(r["LAT"])
        except (ValueError, KeyError):
            continue
        wind = fnum(r.get("WMO_WIND")) or fnum(r.get("USA_WIND"))
        tracks[(r["SID"], name)].append([r["ISO_TIME"], round(lon, 2), round(lat, 2), wind])
    latest = sorted(tracks.items(), key=lambda kv: kv[1][-1][0])[-4:]
    out = [{"name": k[1], "track": [[p[1], p[2], p[3]] for p in v]} for k, v in latest]
    write_json("storms.json", out)
    status(f"  storms={[s['name'] for s in out]}")

    import datetime as dt
    # 570 天=逐日档案窗（2025-01-01 起回补，2026-07 用户裁定）+ 余量
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=570)
    daily = []
    for (sid, name), pts in tracks.items():
        rows = []
        for iso, lon, lat, wind in pts:
            try:
                t = dt.datetime.fromisoformat(iso).replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
            if t < cutoff:
                continue
            rows.append([int(t.timestamp() // 3600), lon, lat, int(wind)])
        if len(rows) > 1:
            daily.append({"name": name, "track": rows})
    write_json("storms_daily.json", daily)
    status(f"  storms_daily：{len(daily)} 风暴（近 570 天，带时间戳）")


def lightning_synthetic():
    """闪电：Blitzortung WS 需社区握手，此处用气候学热区驱动的合成脉冲。
    热区取全球闪电气候学公认高发区（NASA LIS/OTD 文献），仅作氛围层，图例标 synthetic。"""
    status("lightning (synthetic, labeled)")
    hotspots = [  # lon, lat, sigma_deg, weight
        [23.0, 0.5, 6, 10],     # Congo Basin
        [-71.6, 9.0, 2, 6],     # Lake Maracaibo
        [102.0, 3.0, 5, 6],     # Malay Peninsula / Indonesia
        [-60.0, -3.0, 6, 6],    # Amazon
        [90.0, 24.0, 3, 5],     # Bengal
        [-90.0, 30.0, 5, 4],    # Gulf Coast
        [30.0, -2.0, 4, 5],     # Lake Victoria
        [70.0, 30.0, 3, 3],     # Indus
        [-75.0, 5.0, 3, 4],     # Colombia
        [135.0, -12.0, 4, 3],   # N Australia
    ]
    rng = random.Random(7)
    strikes = []
    for lon, lat, sig, w in hotspots:
        for _ in range(w * 120):
            strikes.append([round(rng.gauss(lon, sig), 2),
                            round(rng.gauss(lat, sig * 0.7), 2),
                            round(rng.random(), 3)])  # phase for animation
    rng.shuffle(strikes)
    write_json("lightning_synth.json", {"synthetic": True, "strikes": strikes})
    status(f"  strikes={len(strikes)}")


def gps_interference_synthetic():
    """GPS 干扰：合成演示区块（公开报道的干扰高发区域附近随机 H3 状六边形），图例标 synthetic。

    真实 NIC 聚合勘定终局（实测 2026-07-18，见 REGISTERED-SOURCES-CANDIDATES.md #8）：
    NIC/NACp 完整性指标**不在** OpenSky 实时 REST /states/all 向量里（字段 0-17 只到
    position_source/category，官方 rest.html 确认）——本弧已建的 OAuth2 认证通道解锁的是
    /states 配额（4000/日），拿不到 NIC。NIC 只存于 OpenSky 历史 Trino 库（raw position
    表；GPS-anomaly 研究先例 eugenepik/Opensky_ADS-B_GPS_anomalies 即用之），而 Trino 需
    单独申请（My OpenSky → Request Data Access，限高校/政府/航管研究）且走
    --external-authentication 交互浏览器登录，与无人值守 CI 的 client-credentials 不兼容。
    故本层维持 synthetic；真实 NIC 需另立弧走 Trino 申请路径（不许造数）。"""
    status("gps interference (synthetic, labeled)")
    zones = [[35.0, 33.5, 3.0], [28.0, 47.0, 4.0], [21.0, 55.0, 3.5],
             [47.5, 30.0, 2.5], [13.0, 35.0, 2.0]]
    rng = random.Random(11)
    hexes = []
    for lon, lat, sig in zones:
        for _ in range(60):
            cx, cy = rng.gauss(lon, sig), rng.gauss(lat, sig * 0.6)
            r = 0.35
            poly = [[round(cx + r * math.cos(a) / math.cos(math.radians(cy)), 3),
                     round(cy + r * math.sin(a), 3)]
                    for a in [i * math.pi / 3 for i in range(7)]]
            hexes.append({"c": poly, "w": round(rng.random(), 2)})
    write_json("gps_interference_synth.json", {"synthetic": True, "hexes": hexes})
    status(f"  hexes={len(hexes)}")


if __name__ == "__main__":
    quakes()
    fires()
    aurora()
    storms()
    lightning_synthetic()
    gps_interference_synthetic()
    status("done")
