"""世行直连指标包（P0 · WGI 治理 + 经济金融）→ wb_series.json。

首个绕过 OWID 直连 api.worldbank.org 的构建器（调研见 docs/MULTI-SOURCE-PLAN.md §3）：
WGI 六项 OWID 无镜像，只能直连。本机（中国大陆）对该 API 约 10% 概率间歇 502/超时，
重试即恢复——wb_get 带 3 次指数退避；世行 API 的错误也返回 HTTP 200（body 是
message 数组），必须验形状，且坏 body 已被 cached_get 落盘——校验失败要删缓存再抛。

WGI 用 2025 改版新增的 SC（0-100 绝对分）而非 EST（±2.5）：染色直观且天然 lin 域。
聚合区域（WLD/EUU/AFE…）带合法 ISO3，靠 /v2/country 的 region.id=="NA" 白名单剔除。
"""
import json
import os
import time

from build_indicator_series import metric_meta
from common import CACHE, cached_get, status, write_json

# metric: (code, source_id, scale)
INDICATORS = {
    # —— P0（弧 2）——
    "wgi_cc": ("GOV_WGI_CC.SC", 3, "lin"),   # 清廉（控制腐败）0–100 · 1996–
    "wgi_ge": ("GOV_WGI_GE.SC", 3, "lin"),   # 政府效能 0–100
    "wgi_pv": ("GOV_WGI_PV.SC", 3, "lin"),   # 政治稳定与无暴力 0–100
    "infl": ("FP.CPI.TOTL.ZG", 2, "lin"),    # CPI 通胀 % · 1960–
    "unemp": ("SL.UEM.TOTL.ZS", 2, "lin"),   # 失业率 %（ILO 模型）· 1991–
    "fdi": ("BX.KLT.DINV.WD.GD.ZS", 2, "lin"),  # FDI 净流入 %GDP · 1970–
    "gini": ("SI.POV.GINI", 2, "lin"),       # 基尼系数（调查年稀疏，前端 step 前向取值）
    "pm25": ("EN.ATM.PM25.MC.M3", 2, "lin"),  # PM2.5 年均暴露 µg/m³ · 1990–
    # —— P1（弧 4）：WGI 补齐 ——
    "wgi_va": ("GOV_WGI_VA.SC", 3, "lin"),   # 话语权与问责 0–100
    "wgi_rq": ("GOV_WGI_RQ.SC", 3, "lin"),   # 监管质量 0–100
    "wgi_rl": ("GOV_WGI_RL.SC", 3, "lin"),   # 法治 0–100
    # —— P1：经济金融/社会 ——
    "remit": ("BX.TRF.PWKR.DT.GD.ZS", 2, "lin"),   # 侨汇流入 %GDP · 1970–
    "milex_gdp": ("MS.MIL.XPND.GD.ZS", 2, "lin"),  # 军费 %GDP · 1960–
    "tax": ("GC.TAX.TOTL.GD.ZS", 2, "lin"),        # 税收 %GDP · 1972–
    "netmig": ("SM.POP.NETM", 2, "lin"),           # 净移民（人，负=净流出）
    "old65": ("SP.POP.65UP.TO.ZS", 2, "lin"),      # 65+ 人口 % · 1960–
    "health_exp": ("SH.XPD.CHEX.GD.ZS", 2, "lin"),  # 卫生支出 %GDP · 2000–
    "edu_exp": ("SE.XPD.TOTL.GD.ZS", 2, "lin"),    # 教育支出 %GDP · 1970–
    "hitech": ("TX.VAL.TECH.MF.ZS", 2, "lin"),     # 高技术出口 %制成品 · 2007–
    # —— P1：基础设施 ——
    "mobile": ("IT.CEL.SETS.P2", 2, "lin"),        # 移动订阅 /100人 · 1960–
    "bband": ("IT.NET.BBND.P2", 2, "lin"),         # 固定宽带 /100人 · 1998–
    "air_pax": ("IS.AIR.PSGR", 2, "log"),          # 航空客运量 · 1970–
    "container": ("IS.SHP.GOOD.TU", 2, "log"),     # 集装箱吞吐 TEU · 2005–
    # —— P1：ESG 气候暴露（source=75，WDI 无）——
    "water_stress": ("ER.H2O.FWST.ZS", 2, "log"),  # 取水压力 %（科威特级 >1000% 长尾）
    "cdd": ("EN.CLC.CDDY.XD", 75, "lin"),          # 制冷度日 · 1960–
    "heat35": ("EN.CLC.HEAT.XD", 75, "lin"),       # >35°C 高温天数 · 1960–
    "spei": ("EN.CLC.SPEI.XD", 75, "lin"),         # 干旱指数 SPEI（越负越旱）
    # —— 弧 6 ——
    "armed": ("MS.MIL.TOTL.P1", 2, "log"),         # 武装部队人数 · 1985–2020
}

API = "https://api.worldbank.org/v2"


def wb_get(url, cache):
    """cached_get + 3 次指数退避 + body 形状校验（校验不过删缓存重试/抛出）。"""
    last = None
    for i in range(3):
        try:
            body = json.loads(cached_get(url, cache, timeout=180))
            if isinstance(body, list) and len(body) >= 2 and isinstance(body[1], list):
                return body
            last = RuntimeError(f"世行 API 200 但 body 异常: {str(body)[:160]}")
        except Exception as e:
            last = e
        try:  # 坏响应可能已被 cached_get 落盘，删掉避免毒缓存
            os.remove(os.path.join(CACHE, cache))
        except OSError:
            pass
        if i < 2:
            time.sleep(2 ** (i + 1))
    raise last


def country_whitelist():
    """真实国家/领地 ISO3 集合：region.id=='NA' 的是收入组/区域聚合体，剔除。"""
    body = wb_get(f"{API}/country?format=json&per_page=400", "wb_countries.json")
    return {r["id"] for r in body[1] if r.get("region", {}).get("id") != "NA"}


def indicator_series(code, src, allow):
    url = f"{API}/country/all/indicator/{code}?format=json&per_page=20000&date=1960:2026&source={src}"
    body = wb_get(url, f"wb_{code.replace('.', '_')}.json")
    out = {}
    for r in body[1]:
        iso = r.get("countryiso3code")
        if not iso or iso not in allow or r.get("value") is None:
            continue
        try:
            out.setdefault(iso, []).append([int(r["date"]), round(float(r["value"]), 3)])
        except (ValueError, TypeError):
            continue
    for k in out:
        out[k].sort()
    return out


def main():
    status("world bank direct series (P0)")
    allow = country_whitelist()
    status(f"  country whitelist: {len(allow)}")
    series, meta = {}, {}
    for m, (code, src, scale) in INDICATORS.items():
        try:  # 单指标失败不炸整包（每日云端刷新韧性；成功者照常产出）
            s = indicator_series(code, src, allow)
            mm = metric_meta(s, scale)
        except Exception as e:
            status(f"  ⚠ {m} ({code}) 拉取失败，跳过: {e}")
            continue
        if not s or mm is None:
            status(f"  ⚠ {m} ({code}) 无有效数据，跳过")
            continue
        series[m], meta[m] = s, mm
        n = sum(len(v) for v in s.values())
        y0 = min(v[0][0] for v in s.values())
        status(f"  {m}: countries={len(s)} points={n} span={y0}–{mm['maxYear']}")
    write_json("finale/wb_series.json", {"meta": meta, "series": series})


if __name__ == "__main__":
    main()
