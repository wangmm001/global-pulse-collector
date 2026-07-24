# global-pulse open-license collector

私仓 [global-pulse] 的**开放许可数据源采集器**。与 [`visit-g2`](https://github.com/wangmm001/visit-g2) 同模式：

> 公开仓 GitHub Actions 免费不限量 → 把**开放许可**（CC0 / CC-BY / 公有领域）数据源的
> 每日 fetch+build 搬到这里；私仓 `daily-data` 浅克隆本仓 `out/` 取产物，本地只保留
> 受限源（ACLED / GBIF / WHO / UCDP / OpenSky / CelesTrak 等）的抓取。目的：给配额吃紧的
> 私仓 Actions 减负。

## 许可边界（铁律）

**本仓只采集开放许可源。** 判定与依据逐条见 [`ALLOWLIST.md`](./ALLOWLIST.md)：

- **public（11，进本仓）**：`longrun_series` `wb_series` `temp`（OWID/世行 CC BY）、
  `sanctions`（OFAC 公有领域）、`quakes`（USGS 公有领域）、`fires`（NASA FIRMS 开放）、
  `aurora` `storms` `spaceweather`（NOAA 公有领域）、`lightning` `gpsjam_synth`（自生成合成）。
  **全部免登录 → 本仓 Actions 不需要任何 Secret。**
- **private（14，绝不进本仓）**：`sdg_series` `anomalies` `conflict(_bin)` `space`
  `traffic` `gdacs` `chokepoints` `conjunctions` `radar` `carbon` `daily_series`
  `events` `finance_layers` —— 存疑许可 / 受限条款（OpenSky 研究、yfinance 非商用、
  Space-Track 再分发受限）/ 需私仓凭据 / 派生自受限源。
- **硬排除（永不进本仓）**：ACLED（NC+禁再分发）、GBIF（含 CC BY-NC）、
  WHO FluNet / GHO（CC BY-NC-SA）。`fetch_open.py` 的 `DENY_IDS` 显式拦截。

发布前每次 `collect.yml` 都跑 [`audit.sh`](./audit.sh)：**零受限数据 + 零凭据明文**，
不通过即拒绝 commit。审计方法与最近结论见 [`AUDIT.md`](./AUDIT.md)。

## 结构

```
collector/
├── fetch_open.py                 # 只 build ALLOWLIST 里 public 的数据集 → out/
├── ALLOWLIST.md                  # 25 个 daily 数据集的许可分类（public 11 / private 14）
├── audit.sh + AUDIT.md           # 零受限数据 + 零凭据 审计闸门与结论
├── PRIVATE_WIRING.md             # 私仓侧改造预案（如何浅克隆本仓取数）
├── pipeline/                     # 主仓 pipeline 的**开放源子集**（编排建仓时拷入；见下）
├── out/                          # 采集产物（committed，私仓浅克隆取此）
│   ├── COLLECTED.json            # 采集清单：id/许可/署名/sha256（私仓据此核对+取数）
│   ├── finale/longrun_series.json, finale/wb_series.json, finale/attributions.json
│   ├── temp_stripes.json, sanction_events.json, quakes.json, fires.json
│   ├── aurora.json, storms.json, storms_daily.json, spaceweather.json
│   ├── lightning_synth.json, gps_interference_synth.json
│   └── geometry/ne_50m.json, geometry/centroids.json   # sanctions geo_iso 前置（NE 公有领域）
└── .github/workflows/collect.yml # 每日 cron 23:15 UTC + 手动；fetch→audit→commit
```

## pipeline 代码来源（自包含范式）

`fetch_open.py` 不复制、不改动主仓 pipeline 模块，运行时把 pipeline 目录挂 `sys.path`
直接 import 既有 builder。目录来源优先级：

1. 环境变量 `GP_PIPELINE_DIR`
2. `./pipeline`（**本仓部署形态**：编排在建公开仓时，从主仓**只拷开放源用到的**
   builder + `common.py` + `registry.py`——受限源 builder 一律不拷）
3. `../pipeline`（本地主仓内审计回退）

采集时 `common.OUT` / `common.CACHE` 被重定向到 `collector/out` 与 `collector/.cache`，
**绝不写主仓 `public/data`**。

**编排建仓时需拷入 `collector/pipeline/` 的文件**（只这些，受限 builder 不拷）：
`common.py` `registry.py` `geo_iso.py` `build_static.py`（countries 前置）
`build_longrun_series.py` `build_worldbank.py` `build_temp.py` `build_sanctions.py`
`build_dynamic.py`（quakes/fires/aurora/storms/lightning/gps 合成）`build_spaceweather.py`
`vendored/`（若被上列引用）。**不拷**：`build_acled.py` `build_gbif.py` `build_flunet.py`
`build_gho.py` `build_conflict*.py` `build_space.py` `build_traffic.py` `build_radar.py`
`build_carbon.py` `build_finance_layers.py` `build_sdg.py` `build_gdacs.py`
`build_conjunctions.py` 等受限/私仓 builder。

## 本地跑

```bash
cd collector
python3 fetch_open.py     # 默认回退 ../pipeline（主仓内）；产物落 out/，缓存落 .cache/
bash audit.sh             # 发布前闸门
```

## 私仓如何取数

见 [`PRIVATE_WIRING.md`](./PRIVATE_WIRING.md)：私仓 `daily-data` 加一步浅克隆本公开仓
（`git clone --depth 1`），把 `out/` 里的开放源产物拷进自己的 `public/data/`，私仓侧
`run.py --daily` 名单据此裁掉这 11 个源，只保留受限源本地抓取。
