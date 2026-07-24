# 开放源 ALLOWLIST（公开仓采集边界）

逐条核对主仓 `pipeline/registry.py` 里 `run.py --daily` 会刷新的**全部 25 个** `daily=True`
数据集，按 `docs/ATTRIBUTIONS.md`（许可权威）分类。判定口径（铁律）：

- **public** 仅当许可明确落在 **CC0 / CC-BY(-SA) / 公有领域**，且**不掺受限源**（无 NC / 无禁再分发 / 无非派生 ND）、**无需私仓凭据**。
- **存疑一律判 private**（宁可少拆不可错拆）。凡 license 记作宽泛「公开 / 开放 / 免费 / 研究条款 / UN Terms / IMF Terms / 站点自有条款」而无明确 CC/PD 依据者 → private。
- **硬排除（铁律，永不进公开仓）**：ACLED（NC+禁再分发）、GBIF（16.7% CC BY-NC→整体 NC）、WHO FluNet / GHO（CC BY-NC-SA）。这三源不在 `--daily` 名单（ACLED/GBIF/WHO 均非 daily），但仍显式列入 denylist 防误拆。

**结论：public 11 个 / private 14 个（共 25）。** public 集合**全部免登录**，公开仓 Actions 不需要任何 Secret。

---

## public（11）— 进公开仓采集

| id | build 入口 | 产物 | 许可 | 判定依据 |
|---|---|---|---|---|
| `longrun_series` | `build_longrun_series:main` | `finale/longrun_series.json`, `finale/attributions.json` | CC BY（V-Dem 底层 CC BY-SA） | OWID grapher CSV，CC BY；V-Dem 底层 CC BY-SA 是**开放**共享（再分发衍生须同许可），仍允许公开仓再分发。免登录。 |
| `wb_series` | `build_worldbank:main` | `finale/wb_series.json` | CC BY 4.0 | 世行 WDI + WGI 2025 Revision，明确 CC BY 4.0（ATTRIBUTIONS 第 19 行）。api.worldbank.org 免登录。 |
| `temp` | `build_temp:main` | `temp_stripes.json` | CC BY | HadCRUT via OWID grapher，CC BY。免登录。 |
| `sanctions` | `build_sanctions:main` | `sanction_events.json` | 公有领域（17 U.S.C. §105） | 美财政部 OFAC，美联邦政府作品公有领域（ATTRIBUTIONS 第 35 行）。官方 Delta 通道免登录。国家-日聚合，不含实体名单。 |
| `quakes` | `build_dynamic:quakes` | `quakes.json` | 公有领域 | USGS，公有领域（registry + ATTRIBUTIONS 第 21 行）。GeoJSON feed 免登录。 |
| `fires` | `build_dynamic:fires` | `fires.json` | 美联邦民用开放（≈公有领域） | NASA FIRMS VIIRS，NASA 民用航天开放数据政策，免登录公开 CSV（registry「公开 CSV」/ ATTRIBUTIONS 第 22 行）。**已核 build_dynamic 不读任何 key**（FIRMS_MAP_KEY 未使用）。 |
| `aurora` | `build_dynamic:aurora` | `aurora.json` | 公有领域 | NOAA SWPC OVATION，公有领域（ATTRIBUTIONS 第 23 行）。免登录 JSON。 |
| `storms` | `build_dynamic:storms` | `storms.json`, `storms_daily.json` | 公开（NOAA 美联邦作品） | NOAA IBTrACS v04r01，NOAA 美联邦作品公有领域口径（ATTRIBUTIONS 第 24/39 行「公开（NOAA）」；prompt 明列 NOAA 为免登录开放源）。免登录 CSV。 |
| `spaceweather` | `build_spaceweather:main` | `spaceweather.json` | 公有领域 | NOAA SWPC，公有领域（registry）。services.swpc.noaa.gov 免登录。 |
| `lightning` | `build_dynamic:lightning_synthetic` | `lightning_synth.json` | —（自生成合成） | 本管线自生成的气候学近似合成数据，无外部许可、无外部抓取。标 SYNTHETIC。 |
| `gpsjam_synth` | `build_dynamic:gps_interference_synthetic` | `gps_interference_synth.json` | —（自生成合成） | 同上，自生成合成，无外部许可。标 SYNTHETIC。 |

> 静态前置：`sanctions` 的 `geo_iso.iso_by_name` 需 Natural Earth 国界几何 `geometry/ne_50m.json`（数据集 `countries`，**公有领域**）。私仓里它是已提交静态资产；公开仓自包含形态由 `fetch_open.py` 缺失时先建 `countries`（同属开放许可）。

## private（14）— 留在私仓

| id | build 入口 | 许可（registry） | 判定 private 依据 |
|---|---|---|---|
| `sdg_series` | `build_sdg:main` | UN Terms of Use（注明出处；商用需另行确认） | 非 CC/PD 命名许可，商用需另行确认 → 存疑。 |
| `anomalies` | `build_anomalies:main` | 派生（口径随各源包） | 派生自 sdg 等四序列包（含 sdg=存疑）→ 随最严者 private；且需私仓输入包在场。 |
| `conflict` | `build_conflict:main` | 免费（官方引用格式） | UCDP GED，非 CC/PD 命名许可（「免费按引用」）→ 存疑；且候选增量走 `UCDP_TOKEN`。 |
| `conflict_bin` | `build_conflict_bin:main` | 同 conflict | 派生自 conflict → private。 |
| `space` | `build_space:main` | 公开 | CelesTrak/TheSpaceDevs「公开」宽泛无 CC/PD 依据；主 TLE 通道 `SPACETRACK_USER/PASS` 且 **Space-Track 再分发受限** → 存疑。 |
| `traffic` | `build_traffic:main_all` | OpenSky 研究条款 | **OpenSky 研究/非商业条款限再分发** → 受限；且用 `OPENSKY_CLIENT_ID/SECRET`。 |
| `gdacs` | `build_gdacs:main` | 公开（EC-JRC/UN OCHA） | 「公开」宽泛，无明确 CC/PD 依据 → 存疑。 |
| `chokepoints` | `build_portwatch:main` | IMF Data 条款（可再分发含商用，须署名） | IMF 自有条款虽允许再分发，但非 CC0/CC-BY/PD 命名许可 → 按严存疑判 private（可后续法务复核后升 public）。 |
| `conjunctions` | `build_conjunctions:main` | 公开 | CelesTrak SOCRATES「公开」宽泛，与 space 同源同存疑。 |
| `radar` | `build_radar:main` | 公开（署名 Cloudflare Radar） | Cloudflare 自有条款，**需 `CLOUDFLARE_RADAR_TOKEN`** → 存疑+需凭据。 |
| `carbon` | `build_carbon:main` | 公开（署名） | Electricity Maps 自有条款，**需 `ELECTRICITYMAPS_TOKEN`** → 存疑+需凭据。 |
| `daily_series` | `build_daily_series:main` | 同各源 | 派生自全部 daily 源（含上列受限源）→ private。 |
| `events` | `build_events:main` | 同各源 | 派生自 daily 源集合（混合出处，含受限）→ private。 |
| `finance_layers` | `build_finance_layers:main` | 各源原许可（yfinance **非商用** / BACI 学术使用 / …） | 含 **yfinance 非商用 + BACI 学术使用** 受限源 → private；且属 `finance-layer/` 子仓（不碰）。 |

## 硬排除 denylist（铁律，非 daily 但显式拦截）

`acled`（NC+禁再分发）、`gbif`（混合含 CC BY-NC 16.7%→整体 NC）、`flunet`（CC BY-NC-SA 3.0 IGO）、`gho`（CC BY-NC-SA 3.0 IGO）。
registry 里 flunet/gho 的 `license` 字段虽含「CC BY」字样，但 `docs/ATTRIBUTIONS.md` 权威判定为 **NC-SA**（第 44-46、84-88、109-114 行）——**按严的算，排除**。`fetch_open.py` 的 `DENY_IDS` 已含这四个 id 作防御纵深。
