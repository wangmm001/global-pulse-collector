# 私仓侧改造预案（PROPOSAL ONLY — 不改私仓 daily-data.yml）

本文件是**改造方案**，不动私仓任何 `.github/`。真正的接线由编排审计后亲手做。

## 现状

私仓 `.github/workflows/daily-data.yml` 每日 UTC 00:30 跑 `refresh` job（timeout 70min）：
AIS 30-min 全量窗口 ∥ GPS 采集（并行 ~12min）→ `run.py --daily`（刷新全部 25 个
`daily=True` 数据集 + 打包）→ commit + Release。其中 `--daily` 的网络抓取里，**11 个
开放源**（`longrun_series` `wb_series` `temp` `sanctions` `quakes` `fires` `aurora`
`storms` `spaceweather` + 2 个自生成合成）现在由本公开仓 `collect-open` 每日 UTC 23:15
先行采集并 commit 到 `out/`。

现成范式就在同一文件里——G2 互访图层步骤（daily-data.yml 第 65-74 行）已经在
「浅克隆公开仓 → 取数」：

```yaml
- name: G2 互访图层（克隆 visit-g2 → build_visitg2）
  continue-on-error: true
  working-directory: pipeline
  run: |
    git clone -q --depth 1 https://github.com/wangmm001/visit-g2.git "$RUNNER_TEMP/visit-g2" || { echo "::warning::…"; exit 1; }
    VISITG2_DIR="$RUNNER_TEMP/visit-g2" python3 build_visitg2.py || { echo "::warning::…"; exit 1; }
```

## 改造（两处）

### 1) 新增一步：浅克隆 collector → 取开放源产物（放在「每日动态刷新」之前）

```yaml
# 开放源产物由公开仓 collector 采集（visit-g2 同模式，Actions 免费不限量）。
# 浅克隆取 out/ 直接覆盖进 public/data，随后 --daily 只跑受限源。
# 失败不阻塞：克隆/取数失败时保留仓内上一版产物（留白优于断链）。
- name: 开放源图层（克隆 collector → 取 out/ 产物）
  continue-on-error: true
  run: |
    git clone -q --depth 1 https://github.com/wangmm001/global-pulse-collector.git "$RUNNER_TEMP/collector" \
      || { echo "::warning::开放源：collector 克隆失败，保留仓内上一版"; exit 1; }
    SRC="$RUNNER_TEMP/collector/out"
    # 逐文件覆盖（COLLECTED.json 可选核对 sha256）；geometry 已在仓内静态资产，不覆盖
    for rel in finale/longrun_series.json finale/attributions.json finale/wb_series.json \
               temp_stripes.json sanction_events.json quakes.json fires.json \
               aurora.json storms.json storms_daily.json spaceweather.json \
               lightning_synth.json gps_interference_synth.json; do
      [ -f "$SRC/$rel" ] && mkdir -p "public/data/$(dirname "$rel")" && cp "$SRC/$rel" "public/data/$rel" \
        || echo "::warning::开放源缺 $rel（保留旧版）"
    done
```

### 2) 私仓 `run.py --daily` 名单裁掉这 11 个源

**最小改动、无需碰 registry**：给 `run.py` 加一个环境变量开关，`--daily` 时读一份
「外部已供给」跳过名单。改动落在 `pipeline/run.py` 的 `cmd_daily()`：

```python
def cmd_daily():
    os.environ.setdefault("GP_FRESH_HOURS", "12")
    external = set(filter(None, os.environ.get("GP_EXTERNAL_IDS", "").split(",")))
    ids = [d.id for d in DATASETS if d.daily and d.id not in external]
    status(f"每日动态刷新: {', '.join(ids)} (跳过外部供给: {', '.join(sorted(external)) or '—'})")
    rc = cmd_build(ids)
    cmd_pack()   # 打包仍读 public/data 全量——外部产物已被步骤①覆盖到位，照常入包
    return rc
```

daily-data.yml 的「每日动态刷新」步骤设：

```yaml
env:
  GP_EXTERNAL_IDS: longrun_series,wb_series,temp,sanctions,quakes,fires,aurora,storms,spaceweather,lightning,gpsjam_synth
```

> 注：`cmd_pack()` 的包成员按 `daily=True` 全量取 `public/data`，外部源产物已由步骤①
> 覆盖到位，离线包与 manifest 完整性不受影响。`--check` 亦照常校验这些产物存在（存在即可，
> 来源是本地抓还是外部克隆无差别）。派生源 `anomalies/events/daily_series/conflict_bin`
> **仍在私仓跑**（它们消费的输入含受限源，本就 private），且现在读的是步骤①覆盖后的
> 开放源产物 + 私仓受限源产物，口径不变。

## 预计 Actions 分钟下降

**方法**：私仓按实际运行时长计费；AIS 30-min 窗口 + GPS 采集是固定地板（不受影响，
必须留私仓）。可迁移的是 `--daily` 里这 11 个开放源的**网络抓取+构建**耗时：

| 源 | 典型耗时（暖缓存） | 说明 |
|---|---|---|
| `wb_series` | ~1–4 min | 世行 28 指标，本机间歇 502 带重试（registry 注）——最大变量 |
| `longrun_series` | ~1–2 min | OWID ~20 grapher CSV |
| `sanctions` | ~20–40 s（暖）/ 数 min（冷） | OFAC 逐 publication delta，immutable 缓存命中后快 |
| `temp` + NOAA/USGS/NASA 五源 | ~1–2 min | 小 JSON/CSV feed |
| 2 个合成 | ~10 s | 纯计算 |

- **典型日**：≈ 4–8 min/日 → **≈ 120–240 min/月**。
- **坏月**（World Bank 502 频发 + 冷缓存重下）：可上探 ≈ 12–15 min/日 → **≈ 300–450 min/月**。

即 task #176 目标「~450 分/月」是**乐观上限**（坏月口径）；稳态更接近 **150–300 分/月**。
无论哪档，AIS/GPS 采集与受限源抓取的地板不变，减负全部来自开放源迁出。公开仓 Actions
免费不限量承接这部分，净效果：私仓月度 Actions 消耗下降上述区间，且 World-Bank-502
拖时间的风险从私仓关键路径移出。

## 回滚

步骤①失败已 `continue-on-error` 保留旧版；若要整体回退，删步骤① + 清空 `GP_EXTERNAL_IDS`
即恢复私仓自采全部 25 源，零数据丢失。
