"""空间天气 · NOAA SWPC（公有领域，免注册）
传播太阳风（L1 → 地球传播修正：速度/密度/Bz 一个端点全含）+ 行星 Kp 指数 +
GOES X 射线耀斑。给极光层补"原因"维度：太阳风抵达 → Kp 上升 → 极光环南扩。

端点核实（2026-07，products/solar-wind/* 旧路径已 404）：
  products/geospace/propagated-solar-wind-1-hour.json  首行表头列表表，分钟粒度
  products/noaa-planetary-k-index.json                 对象行 {time_tag, Kp, …}
  json/goes/primary/xray-flares-7-day.json             对象行 {max_time, max_class, …}

产物 spaceweather.json（UTC epoch 秒）：
  wind:   [[ts, speed km/s, density /cm3, bz nT], …]   近 1h 每 ~6 分钟
  kp:     [[ts, kp], …]                                 近 7 天 3h 粒度
  flares: [[ts_peak, class 如 'M1.4'], …]               近 7 天
  latest: {speed, density, bz, kp, flare, flareTs}      仪表行直读
"""
import datetime as dt
import json

from common import cached_get, status, write_json

TTL = 21600  # 6h：cron 每日跑，手动重跑也不至于打爆端点


def _ts(s):
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
               .timestamp())


def main():
    status("spaceweather")
    sw = json.loads(cached_get(
        "https://services.swpc.noaa.gov/products/geospace/propagated-solar-wind-1-hour.json",
        "sw_wind.json", max_age=TTL))
    kp = json.loads(cached_get(
        "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
        "sw_kp.json", max_age=TTL))
    try:
        flares = json.loads(cached_get(
            "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json",
            "sw_flares.json", max_age=TTL))
    except Exception as e:
        status(f"  flares 端点失败（{e}）——留空")
        flares = []

    # 列表表：header + rows；列 0=time_tag 1=speed 2=density 6=bz
    wind = []
    for r in sw[1:]:
        try:
            wind.append([_ts(r[0]), round(float(r[1])), round(float(r[2]), 1),
                         round(float(r[6]), 1)])
        except (TypeError, ValueError):
            continue
    wind = wind[::6]  # 分钟粒度 → ~6 分钟

    kp_rows = []
    for r in kp:
        try:
            kp_rows.append([_ts(r["time_tag"]), float(r["Kp"])])
        except (TypeError, ValueError, KeyError):
            continue

    fl = []
    for f in flares or []:
        c = f.get("max_class") or f.get("begin_class")
        t = f.get("max_time") or f.get("begin_time")
        if c and t:
            try:
                fl.append([_ts(t), c])
            except (TypeError, ValueError):
                continue
    fl.sort()

    latest = {
        "speed": wind[-1][1] if wind else None,
        "density": wind[-1][2] if wind else None,
        "bz": wind[-1][3] if wind else None,
        "kp": kp_rows[-1][1] if kp_rows else None,
        "flare": fl[-1][1] if fl else None,
        "flareTs": fl[-1][0] if fl else None,
    }
    write_json("spaceweather.json", {"wind": wind, "kp": kp_rows, "flares": fl, "latest": latest})
    status(f"  wind={len(wind)} kp={len(kp_rows)} flares={len(fl)} latest={latest}")


if __name__ == "__main__":
    main()
