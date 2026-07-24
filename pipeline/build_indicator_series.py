"""国家指标全时间序列 → indicators_series.json（探索台染色随历史年份轴回放）。

v2：新增长时序指标（预期寿命 1770–、儿童死亡率 1800–、识字率 1475–、人均能耗 1965–、
城市化率、平均受教育年限），并输出每指标元数据：
  meta[m] = {maxYear, scale: 'log'|'lin', lo, hi}   # lo/hi = 全序列 2/98 分位（染色域）
GDP 类长尾指标前端用连续对数色标（固定全期域）→ 逐年变化清晰可读。
"""
import csv
import io
import math

from common import cached_get, status, write_json

GRAPHER = "https://ourworldindata.org/grapher/{}.csv?v=1&csvType=full&useColumnShortNames=true"
# metric: (slug, cache, scale)
SLUGS = {
    "gdp": ("gross-domestic-product", "owid_gdp.csv", "log"),          # NY.GDP.MKTP.KD＝2015 不变价美元（官方页复核，非现价）
    "gdp_pc": ("gdp-per-capita-worldbank", "owid_gdppc.csv", "log"),   # NY.GDP.PCAP.PP.KD＝PPP 不变价国际元
    "elec": ("share-of-the-population-with-access-to-electricity", "owid_elec.csv", "lin"),
    "net": ("share-of-individuals-using-the-internet", "owid_net.csv", "lin"),
    "life_exp": ("life-expectancy", "owid_lifeexp.csv", "lin"),
    "child_mort": ("child-mortality", "owid_childmort.csv", "log"),
    "literacy": ("cross-country-literacy-rates", "owid_literacy.csv", "lin"),
    "energy_pc": ("per-capita-energy-use", "owid_energypc.csv", "log"),
    "urban": ("share-of-population-urban", "owid_urban.csv", "lin"),
    "school": ("mean-years-of-schooling-long-run", "owid_school.csv", "lin"),
    # 电网碳强度年度史（Ember 口径，1990–2025）——实时版见 carbon 数据集（Electricity Maps）
    "co2_kwh": ("carbon-intensity-electricity", "owid_co2kwh.csv", "lin"),
}


def grapher_series(slug, cache, col=None):
    rows = list(csv.DictReader(io.StringIO(cached_get(GRAPHER.format(slug), cache, timeout=300))))
    # 值列可显式传入（V-Dem 系图带 owid_region / __annotations 附加列，列序不可赌）
    col = col or next(c for c in rows[0] if c.lower() not in ("entity", "code", "year")
                      and c != "owid_region" and not c.endswith("__annotations"))
    out = {}
    for r in rows:
        code = r.get("code") or r.get("Code")
        if not code or len(code) != 3:
            continue
        try:
            y, v = int(r.get("year") or r["Year"]), float(r[col])
        except (ValueError, TypeError):
            continue
        out.setdefault(code, []).append([y, round(v, 3)])
    for k in out:
        out[k].sort()
    return out


def co2_series():
    text = cached_get(
        "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv",
        "owid-co2-data.csv", timeout=600)
    cum, pc = {}, {}
    for r in csv.DictReader(io.StringIO(text)):
        code = r.get("iso_code")
        if not code or len(code) != 3:
            continue
        try:
            y = int(r["year"])
        except ValueError:
            continue
        if y < 1950 and y % 10 != 0:
            continue
        if 1950 <= y < 2000 and y % 5 != 0:
            continue
        for field, store, nd in (("cumulative_co2", cum, 1), ("co2_per_capita", pc, 3)):
            v = r.get(field)
            if v:
                try:
                    store.setdefault(code, []).append([y, round(float(v), nd)])
                except ValueError:
                    pass
    for s in (cum, pc):
        for k in s:
            s[k].sort()
    return cum, pc


def metric_meta(s, scale):
    vals = sorted(v for series in s.values() for _, v in series
                  if v is not None and (scale != "log" or v > 0))
    if not vals:
        return None
    if scale == "log":
        # 对数指标域：
        # - 下界 p10（p25 会把人均 GDP 这类指标的穷国与大国早期全压成 0——中国 1990/2000 曾不可见）
        # - 上界离群检测：孤立极值（如人均 CO₂ 数据里 611 t/人的怪点、能耗的卡塔尔级极值）
        #   用 p99.5 截断；顶部是连续体（如累计 CO₂ 的美国历年）则保留真最大以区分头部国家
        lo = vals[int(len(vals) * 0.10)]
        p995 = vals[int(len(vals) * 0.995)]
        p999 = vals[int(len(vals) * 0.999)]
        hi = vals[-1] if vals[-1] / max(p999, 1e-12) <= 2 else p995
        lo = max(lo, hi * 1e-6, 1e-9)
    else:
        lo = vals[max(0, int(len(vals) * 0.02))]
        hi = vals[min(len(vals) - 1, int(len(vals) * 0.98))]
    max_year = max(series[-1][0] for series in s.values())
    return {"maxYear": max_year, "scale": scale, "lo": lo, "hi": hi}


def main():
    status("indicator time series v2")
    series, meta = {}, {}
    for m, (slug, cache, scale) in SLUGS.items():
        series[m] = grapher_series(slug, cache)
        meta[m] = metric_meta(series[m], scale)
    series["co2_cum"], series["co2_pc"] = co2_series()
    meta["co2_cum"] = metric_meta(series["co2_cum"], "log")
    meta["co2_pc"] = metric_meta(series["co2_pc"], "log")
    for k, s in series.items():
        n = sum(len(v) for v in s.values())
        y0 = min(v[0][0] for v in s.values())
        status(f"  {k}: countries={len(s)} points={n} span={y0}–{meta[k]['maxYear']}")
    write_json("finale/indicators_series.json", {"meta": meta, "series": series})


if __name__ == "__main__":
    main()
