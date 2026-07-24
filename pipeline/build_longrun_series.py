"""长时序指标包（P0 · OWID 独有超长序列）→ longrun_series.json + attributions.json。

与 indicators_series.json 同构旁挂：该包 ~2MB 超出前端 1.5MB 懒加载阈值，独立成文件
由 manifest 自动划入后台加载，不并入叙事核心的 eager 文件；也不做有损年度抽稀
（1918 大流感、1848 革命年这类单年信号是长时序叙事的价值所在）。

attributions.json：全部 grapher 指标（本包 + indicators_series）的
citationShort / lastUpdated / nextUpdate —— 署名自动生成 + 上游过期探测
（today > nextUpdate 时构建日志告警）。数据源调研见 docs/MULTI-SOURCE-PLAN.md。
"""
import datetime
import json

from build_indicator_series import GRAPHER, SLUGS, grapher_series, metric_meta
from common import cached_get, status, write_json

# metric: (slug, cache, scale, col)  # col 显式指定，防上游加列/列序漂移
LONGRUN = {
    "gdp_mad": ("gdp-per-capita-maddison-project-database", "owid_gdpmad.csv", "log",
                "gdp_per_capita"),                       # 公元 1–2022 · Maddison 2023
    "democ": ("electoral-democracy-index", "owid_democ.csv", "lin",
              "electdem_vdem__estimate_best"),           # 1789–2025 · V-Dem
    "rights": ("human-rights-index-vdem", "owid_rights.csv", "lin",
               "civ_libs_vdem__estimate_best"),          # 1789–2025 · V-Dem
    "women_parl": ("share-of-women-in-parliament", "owid_womparl.csv", "lin",
                   "wom_parl_vdem__estimate_best"),      # 1900–2025 · V-Dem
    "mat_mort": ("maternal-mortality", "owid_matmort.csv", "log", "mmr"),  # 1751–2020
    "fertility": ("children-born-per-woman", "owid_fertility.csv", "lin",
                  "fertility_rate_hist"),                # 1891–2023 · HFD/UN
    "top1": ("income-share-top-1-before-tax-wid", "owid_top1.csv", "lin",
             "share_top_1__welfare_type_before_tax__extrapolated_no"),  # 1820–2024 · WID
    "workhrs": ("annual-working-hours-per-worker", "owid_workhrs.csv", "lin",
                "working_hours_omm"),                    # 1870–2023
    "height": ("average-height-of-men-for-selected-countries", "owid_height.csv", "lin",
               "height"),                                # 1550–2000 · 按出生代际
    "coal": ("coal-production-by-country", "owid_coal.csv", "log",
             "coal_production__twh"),                    # 1700–2024 · Etemad/EI
    # —— P2（弧 5）——
    "oil": ("oil-production-by-country", "owid_oil.csv", "log",
            "oil_production__twh"),                      # 1900–2024 · 化石三件套之二
    "gas": ("gas-production-by-country", "owid_gas.csv", "log",
            "gas_production__twh"),                      # 1900–2024 · 化石三件套之三
    "calories": ("daily-per-capita-caloric-supply", "owid_calories.csv", "lin",
                 "daily_calories"),                      # 1274–2023 · FAO+历史重建
    "tertiary": ("share-of-the-population-with-completed-tertiary-education",
                 "owid_tertiary.csv", "lin",
                 "mf_adults__25_64_years__percentage_of_tertiary_education"),  # 1870–2020 · Lee-Lee
    "poverty": ("share-of-population-in-extreme-poverty", "owid_poverty.csv", "lin",
                "headcount_ratio__ppp_version_2021__poverty_line_300__welfare_type_income_"
                "or_consumption__table_income_or_consumption_consolidated__survey_comparability_no_spells"),
    # ↑ 极端贫困率（$3/日 2021 PPP）· 1963– · 世行 PIP；CSV 带 population_historical 副列
    #   （行至 -10000 年但贫困列为空，解析时自然跳过）——值列名超长但必须显式钉死
    "renew_elec": ("share-electricity-renewables", "owid_renewelec.csv", "lin",
                   "renewable_share_of_electricity__pct"),  # 1985–2025 · Ember/EI
    # —— 核武 / 森林（弧 6）——
    "nuke_stock": ("nuclear-warhead-stockpiles", "owid_nukestock.csv", "log",
                   "number_of_warheads"),                   # 1945–2026 · FAS，仅 10 国有值
    "nuke_tests": ("number-of-nuclear-weapons-tests", "owid_nuketests.csv", "lin",
                   "nuclear_weapons_tests"),                # 1945–2024 · 年度次数，8 国
    "tree_loss": ("tree-cover-loss", "owid_treeloss.csv", "log",
                  "tree_cover_loss_ha__category_total"),    # 2001–2024 · GFW/Hansen，公顷
    "forest_chg": ("annual-change-forest-area", "owid_forestchg.csv", "lin",
                   "net_change_forest_area"),               # 1991–2025 · FAO，含负值（+绿化/−毁林）
    # —— 深时土地利用（P3 深时前传全量序列，2026-07-17）——
    # 同一 slug 三列（HYDE 2025 via OWID）：-10000→2025 共 128 时点，210 国，公顷。
    # 评估裁定（DATASOURCES §2.2）：弃"森林原始覆盖近似"，直接挂如实三指标。
    "cropland": ("land-use-over-the-long-term", "owid_landuse.csv", "log",
                 "cropland_c"),                             # 耕地面积 · -10000–2025 · HYDE
    "grazing": ("land-use-over-the-long-term", "owid_landuse.csv", "log",
                "grazing_c"),                               # 牧场面积 · -10000–2025 · HYDE
    "builtup": ("land-use-over-the-long-term", "owid_landuse.csv", "log",
                "uopp_c"),                                  # 建成区面积 · -10000–2025 · HYDE
}

META_URL = "https://ourworldindata.org/grapher/{}.metadata.json"


def slug_attribution(metric, slug, col):
    """grapher metadata.json → {slug, title, unit, timespan, lastUpdated, nextUpdate, citation}。"""
    raw = cached_get(META_URL.format(slug), f"owid_meta_{metric}.json", timeout=120)
    cols = json.loads(raw).get("columns", {})
    c = cols.get(col) if col else None
    if c is None and col:  # metadata columns 键是显示名——按 shortName 二次匹配（土地利用三列同 slug 必需）
        c = next((v for v in cols.values() if v.get("shortName") == col), None)
    if c is None:  # indicators_series 的 3 元组条目：取首个数据列（与 grapher_series 同规则）
        c = next((v for k, v in cols.items()
                  if k != "owid_region" and not k.endswith("__annotations")), {})
    return {"slug": slug, "title": c.get("titleShort"), "unit": c.get("shortUnit") or c.get("unit"),
            "timespan": c.get("timespan"), "lastUpdated": c.get("lastUpdated"),
            "nextUpdate": c.get("nextUpdate"), "citation": c.get("citationShort")}


def attributions():
    out = {}
    both = {m: (s[0], s[1], s[3] if len(s) > 3 else None)
            for m, s in list(SLUGS.items()) + list(LONGRUN.items())}
    for m, (slug, _cache, col) in both.items():
        try:
            out[m] = slug_attribution(m, slug, col)
        except Exception as e:  # 署名是旁路产物，单指标失败不阻塞数据构建
            status(f"  ⚠ attribution {m}: {e}")
            continue
        nxt = out[m].get("nextUpdate")
        if nxt and nxt < datetime.date.today().isoformat():
            status(f"  ⚠ {m}: 上游预期更新已过期（nextUpdate={nxt}）")
    # 非 grapher 通道（owid/co2-data 仓库直拉），静态署名
    for m in ("co2_cum", "co2_pc"):
        out[m] = {"slug": None, "title": m, "unit": "t",
                  "citation": "Global Carbon Budget – processed by Our World in Data (owid/co2-data)"}
    return out


def main():
    status("longrun indicator series (P0)")
    series, meta = {}, {}
    for m, (slug, cache, scale, col) in LONGRUN.items():
        series[m] = grapher_series(slug, cache, col)
        meta[m] = metric_meta(series[m], scale)
        n = sum(len(v) for v in series[m].values())
        y0 = min(v[0][0] for v in series[m].values())
        status(f"  {m}: countries={len(series[m])} points={n} span={y0}–{meta[m]['maxYear']}")
    write_json("finale/longrun_series.json", {"meta": meta, "series": series})
    write_json("finale/attributions.json",
               {"generated": datetime.date.today().isoformat(), "metrics": attributions()})


if __name__ == "__main__":
    main()
