# 零受限数据 + 零凭据明文 审计证明

发布前闸门。脚本 [`audit.sh`](./audit.sh) 每次 `collect.yml` 都跑，不通过即拒绝 commit。
本文件记录方法与**最近一次本地实跑结论**。

## 方法（两道独立检查）

**A. 零受限数据**
- **A1 白名单强校验**：`out/` 下每个普通文件必须在允许清单内。允许清单从
  `fetch_open.PUBLIC_IDS × registry.outputs` 派生（单一事实源，防漂移），外加静态前置
  `geometry/*`（Natural Earth 公有领域）与采集清单 `COLLECTED.json`。任何计划外文件 → 失败。
  这是最强的一道：无论受限产物叫什么名字，只要不在 11 个 public 源的产物清单里就被拦。
- **A2 关键词黑名单**：`out/` 文件名不得含受限源标识子串
  （`acled` `gbif` `flunet` `gho_` `conflict` `ged_` `camera_belt` `sdg_series` `gdacs`
  `chokepoint` `conjunction` `radar` `carbon` `finance_` `ais_` `fishing` `flights_replay`
  `satcat` `starlink` `launches` `ucdp` `covid` `idmc` `resource_trade` `g2_visits`
  `leader_visits` `refugee`）。这些子串唯一指向受限/私仓产物，且与 11 个 public 产物名无冲突。

**B. 零凭据明文**
- **B1**：`collector/`（除 `.cache/`）无 `.env` / `.env.*` / `*.pem` / `id_rsa*` / `*.key`。
- **B2**：无 `TOKEN|SECRET|PASSWORD|PWD|API_KEY|*_KEY` 的**字面值**赋值
  （`${{ secrets.X }}` 引用、`os.environ.get("X")` / `getenv` 变量名不算——那是正常引用）。
  扫 `*.py *.yml *.yaml *.sh *.md *.json *.txt *.cfg *.ini`。
- **B3**：`out/` 产物无 `Bearer …` / `eyJ…`（JWT）形态的令牌串。

## 最近一次本地实跑结论（主仓内，`../pipeline` 回退，产物落 `collector/out/`）

```
[fetch_open] 完成 ok=11 failed=0 skipped=0
  ok: longrun_series, wb_series, temp, sanctions, quakes, fires, aurora, storms,
      spaceweather, lightning, gpsjam_synth
audit.sh → PASS：零受限数据 + 零凭据明文
```

**out/ 全部 16 个文件**（均在 ALLOWLIST 内，对照 `COLLECTED.json` 的 11 个 public 数据集）：

| 文件 | 数据集 | 许可（COLLECTED.json 记录） |
|---|---|---|
| `finale/longrun_series.json`, `finale/attributions.json` | longrun_series | CC BY（V-Dem 底层 CC BY-SA） |
| `finale/wb_series.json` | wb_series | CC BY 4.0 |
| `temp_stripes.json` | temp | CC BY |
| `sanction_events.json` | sanctions | 公有领域（17 U.S.C. §105） |
| `quakes.json` | quakes | 公有领域 |
| `fires.json` | fires | 公开（NASA FIRMS 开放数据） |
| `aurora.json` | aurora | 公有领域 |
| `storms.json`, `storms_daily.json` | storms | 公开（NOAA 美联邦作品） |
| `spaceweather.json` | spaceweather | 公有领域 |
| `lightning_synth.json` | lightning | —（自生成合成） |
| `gps_interference_synth.json` | gpsjam_synth | —（自生成合成） |
| `geometry/ne_50m.json`, `geometry/centroids.json` | countries（静态前置） | 公有领域（Natural Earth） |
| `COLLECTED.json` | 采集清单 | — |

- **A1** ✓ 16/16 文件在允许清单内，无计划外产物。
- **A2** ✓ 无受限关键词命中（无 acled/gbif/flunet/gho/conflict/ucdp/radar/carbon/finance/…）。
- **B1** ✓ 无 `.env`/密钥文件。
- **B2** ✓ 无凭据字面值赋值（代码只用 `os.environ.get(...)` 变量名与 `${{ secrets.X }}` 引用；
  public 集合根本不读任何 Secret）。
- **B3** ✓ 产物无 Bearer/JWT 形态串。

**结论：零受限数据 + 零凭据明文，通过。** 总体积 `out/` ≈ 9.4 MB。

## 备注

- 首跑冷缓存时 `sanctions`（OFAC 逐 publication delta，数百顺序请求）耗时长；曾在沙箱
  网络瞬断（`Errno 101 Network is unreachable`）中途失败，`fetch_open.py` 优雅跳过并保留
  其余 10 源——非代码缺陷、非许可问题。缓存暖后重跑即 11/11 完整（本结论即暖缓存态）。
  GitHub Actions 侧配 `actions/cache` 持久化 `.cache`，稳态不受影响。
- `fires`/`storms` 在 registry 里 `license` 记作宽泛「公开」，`fetch_open.py` 以
  `FEDERAL_OPEN_OK` 显式放行（依据：NASA/NOAA 美联邦民用开放数据，逐条见 ALLOWLIST.md）。
