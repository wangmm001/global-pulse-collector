#!/usr/bin/env python3
"""开放许可源采集器（公开仓侧）—— 只跑 ALLOWLIST 里判定 public 的数据集。

设计目标（visit-g2 同模式）：
  私仓 GitHub Actions 配额吃紧 → 把**开放许可**（CC0 / CC-BY / 公有领域）数据源的
  fetch+build 搬到公开仓（Actions 免费不限量）。私仓侧改为浅克隆本仓 out/ 取产物，
  本地只保留受限源（ACLED/GBIF/WHO/UCDP/OpenSky/CelesTrak 等）的抓取。

复用主仓 pipeline 代码的机制（自包含，无私仓 token）：
  本脚本不复制、不改动主仓 pipeline 模块，而是在运行时把 pipeline 目录挂到 sys.path，
  直接 import 既有 builder。pipeline 目录来源按优先级：
    1) 环境变量 GP_PIPELINE_DIR
    2) ./pipeline           —— 公开仓部署形态：编排在建公开仓时，**只**把
       ALLOWLIST 里 public 数据集用到的 builder + common.py + registry.py 拷进来
       （受限源 builder 一律不拷，见 README「许可边界」）。这是 visit-g2 的自包含范式，
       公开仓 Actions 无需任何私仓凭据。
    3) ../pipeline          —— 本地审计形态：collector/ 位于主仓内，回退到主仓 pipeline。

不触碰主仓 public/data（铁律）：
  主仓 common.py 的 OUT 默认指向 <主仓>/public/data。本脚本 import common 后、
  import 任何 builder 之前，把 common.OUT / common.CACHE **重定向**到 collector/out
  与 collector/.cache。builder 里 `from common import write_json`（调用时读 common 全局
  OUT）与 `from common import OUT`（import 时按值绑定）都因此拿到重定向后的路径——
  故本地审计跑 build 不会写进主仓 public/data。

凭据：ALLOWLIST 的 public 集合**全部免登录**（OWID / 世行 / USGS / NASA FIRMS /
  NOAA / OFAC），不需要任何 Secret。脚本仍会优雅处理缺失 env（public 集合根本不读 env），
  受限源不在此运行。哪些源要哪些 key 见 collect.yml 注释与 README。
"""
import hashlib
import importlib
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
CACHE_DIR = os.path.join(HERE, ".cache")

# ── 开放许可 allowlist（与 ALLOWLIST.md 单一事实源；改这里必同步改文档）──────────
# 只有 license 落在 {CC0, CC-BY(-SA), 公有领域} 且非受限源污染的数据集才在此。
# 判定依据逐条见 ALLOWLIST.md。存疑一律不列入（宁可少拆不可错拆）。
PUBLIC_IDS = [
    "longrun_series",   # OWID grapher · CC BY（V-Dem 底层 CC BY-SA）
    "wb_series",        # World Bank WDI/WGI · CC BY 4.0
    "temp",             # HadCRUT via OWID · CC BY
    "sanctions",        # US Treasury OFAC · 公有领域（17 U.S.C. §105）
    "quakes",           # USGS · 公有领域
    "fires",            # NASA FIRMS · 美联邦民用开放数据（免登录 CSV）
    "aurora",           # NOAA SWPC · 公有领域
    "storms",           # NOAA IBTrACS · 公开（NOAA 美联邦作品）
    "spaceweather",     # NOAA SWPC · 公有领域
    "lightning",        # 自生成合成（气候学近似）· 无外部许可
    "gpsjam_synth",     # 自生成合成 · 无外部许可
]

# 防御纵深：即便某受限 builder 被误拷进 pipeline，这份 denylist + 许可白名单双闸也拦住。
DENY_IDS = {
    "acled", "gbif", "flunet", "gho",          # 铁律硬排除（NC / 禁再分发 / NC-SA）
    "sdg_series", "anomalies", "conflict", "conflict_bin", "space", "traffic",
    "gdacs", "chokepoints", "conjunctions", "radar", "carbon",
    "daily_series", "events", "finance_layers",  # 存疑或受限或派生自受限
    "ucdp_violence", "resourcetrade", "covid", "idmc", "g2visits",
}
# 许可白名单（大小写不敏感子串匹配）——public 集合的 license 必须命中其一。
LICENSE_ALLOW_SUBSTR = ("cc0", "cc by", "公有领域", "public domain")
# 合成源例外（license 记为 "—"，无外部许可，自生成）。
SYNTHETIC_OK = {"lightning", "gpsjam_synth"}
# 美联邦民用开放数据例外：registry 里 license 记作宽泛的「公开」，但依据明确——
# NASA FIRMS（NASA 民用航天）与 NOAA IBTrACS（NOAA 美联邦作品）均为免登录开放数据，
# 等同公有领域口径（依据逐条见 ALLOWLIST.md）。故对这两个 id 显式放行。
FEDERAL_OPEN_OK = {"fires", "storms"}

# 静态前置：部分 builder（如 sanctions 的 geo_iso.iso_by_name）需要 Natural Earth
# 国界几何（geometry/ne_50m.json，数据集 countries，公有领域）。私仓里它是已提交的
# 静态资产；公开仓自包含形态需现建。缺失则先建 countries（同属开放许可）。
GEOMETRY_MARKER = os.path.join("geometry", "ne_50m.json")
PREREQ_ID = "countries"


def _resolve_pipeline_dir():
    env = os.environ.get("GP_PIPELINE_DIR")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    local = os.path.join(HERE, "pipeline")
    if os.path.isdir(local):
        return local
    sibling = os.path.abspath(os.path.join(HERE, "..", "pipeline"))
    if os.path.isdir(sibling):
        return sibling
    sys.exit("[fetch_open] 找不到 pipeline 目录：设 GP_PIPELINE_DIR，或放 ./pipeline，或在主仓内运行")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    pipeline_dir = _resolve_pipeline_dir()
    sys.path.insert(0, pipeline_dir)
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    # 重定向 OUT/CACHE —— 必须在 import 任何 builder 之前（builder 会按值绑定 OUT）
    import common
    common.OUT = OUT_DIR
    common.CACHE = CACHE_DIR
    os.makedirs(common.OUT, exist_ok=True)
    os.makedirs(common.CACHE, exist_ok=True)

    from registry import BY_ID

    # 缓存有效期压到 12h，与私仓 run.py --daily 同口径（端点失败回退旧缓存）
    os.environ.setdefault("GP_FRESH_HOURS", "12")
    print(f"[fetch_open] pipeline={pipeline_dir}")
    print(f"[fetch_open] OUT={OUT_DIR}  CACHE={CACHE_DIR}  GP_FRESH_HOURS={os.environ['GP_FRESH_HOURS']}")
    print(f"[fetch_open] public 数据集 {len(PUBLIC_IDS)} 个：{', '.join(PUBLIC_IDS)}")

    import datetime as dt
    manifest = {"collected": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "source": "global-pulse open-license collector (visit-g2 pattern)",
                "datasets": {}}
    ok, failed, skipped = [], [], []

    # 静态前置：确保 Natural Earth 国界几何存在（sanctions 的 geo_iso 依赖；公有领域）
    if not os.path.exists(os.path.join(OUT_DIR, GEOMETRY_MARKER)):
        pre = BY_ID.get(PREREQ_ID)
        if pre is not None:
            try:
                mn, fnn = pre.builder.split(":")
                print(f"  → prereq {PREREQ_ID} ({pre.builder}) —— 建 Natural Earth 几何供 geo_iso")
                getattr(importlib.import_module(mn), fnn)()
            except Exception:
                traceback.print_exc()
                print(f"  !! prereq {PREREQ_ID} 构建失败 —— 依赖它的数据集（sanctions）可能随之失败")

    for did in PUBLIC_IDS:
        d = BY_ID.get(did)
        if d is None:
            print(f"  ?? {did}: 主仓 registry 无此 id —— 跳过"); skipped.append(did); continue
        # 双闸校验：denylist + 许可白名单
        if did in DENY_IDS:
            print(f"  !! {did}: 命中 denylist —— 拒绝（不应发生，检查 PUBLIC_IDS）"); skipped.append(did); continue
        lic = (d.license or "").lower()
        lic_ok = (did in SYNTHETIC_OK or did in FEDERAL_OPEN_OK
                  or any(s in lic for s in LICENSE_ALLOW_SUBSTR))
        if not lic_ok:
            print(f"  !! {did}: license「{d.license}」不在开放白名单 —— 跳过（防误拆）")
            skipped.append(did); continue
        try:
            mod_name, fn_name = d.builder.split(":")
            fn = getattr(importlib.import_module(mod_name), fn_name)
            print(f"  → build {did} ({d.builder})")
            fn()
            files = {}
            missing = False
            for o in d.outputs:
                p = os.path.join(OUT_DIR, o)
                if not os.path.exists(p) or os.path.getsize(p) == 0:
                    print(f"    !! 产物缺失/空：{o}"); missing = True; continue
                files[o] = {"bytes": os.path.getsize(p), "sha256": sha256(p)}
            if missing or not files:
                failed.append(did); continue
            manifest["datasets"][did] = {
                "builder": d.builder, "license": d.license, "attribution": d.attribution,
                "title": d.title, "outputs": files}
            ok.append(did)
        except Exception:
            traceback.print_exc()
            print(f"  !! {did}: 构建失败 —— 保留 out/ 上一版产物（留白优于断链）")
            failed.append(did)

    # 写采集清单（私仓浅克隆后据此核对+取数）
    import json
    with open(os.path.join(OUT_DIR, "COLLECTED.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    print(f"\n[fetch_open] 完成 ok={len(ok)} failed={len(failed)} skipped={len(skipped)}")
    print(f"  ok: {', '.join(ok) or '—'}")
    if failed:
        print(f"  failed: {', '.join(failed)}")
    if skipped:
        print(f"  skipped: {', '.join(skipped)}")
    # 失败不作为进程失败（留白优于断链；workflow 侧看 warning）
    return 0


if __name__ == "__main__":
    sys.exit(main())
