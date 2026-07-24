#!/usr/bin/env bash
# 零受限数据 + 零凭据明文 审计（发布前闸门）
#
# 两道独立检查，任一失败即 exit 1（collect.yml 据此拒绝 commit）：
#   A. out/ 只含 ALLOWLIST 里 public 数据集的产物 —— 白名单强校验（任何计划外文件即失败）
#      + 受限源关键词黑名单（acled/gbif/flunet/gho/conflict/ucdp/radar/carbon/finance/…）。
#   B. 整个 collector/ 无凭据明文 —— 无 .env 文件；无 token/key/secret/password 的**字面值**
#      赋值（`${{ secrets.X }}` 引用与 os.environ.get("X") 变量名不算，属正常）。
#
# 用法：bash audit.sh   （在 collector/ 目录下；CI 与本地同一脚本）
set -uo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
OUT="$HERE/out"
FAIL=0
echo "== 审计 collector 发布前闸门 =="
echo "-- 位置：$HERE"

# ── A. out/ 产物白名单 + 受限关键词黑名单 ──────────────────────────────────────
# 允许清单从 fetch_open.PUBLIC_IDS × registry.outputs 派生（单一事实源，防漂移），
# 外加静态前置 geometry/* 与采集清单 COLLECTED.json。
ALLOWED="$(GP_PIPELINE_DIR="${GP_PIPELINE_DIR:-$HERE/pipeline}" python3 - <<'PY'
import os, sys
HERE = os.path.dirname(os.path.abspath("audit.sh")) if False else os.getcwd()
pd = os.environ.get("GP_PIPELINE_DIR", os.path.join(HERE, "pipeline"))
if not os.path.isdir(pd):
    pd = os.path.abspath(os.path.join(HERE, "..", "pipeline"))
sys.path.insert(0, HERE); sys.path.insert(0, pd)
from fetch_open import PUBLIC_IDS
from registry import BY_ID
allowed = set()
for did in PUBLIC_IDS:
    d = BY_ID.get(did)
    if d:
        allowed.update(d.outputs)
# 静态前置（countries，公有领域）+ 采集清单
allowed.update(["geometry/ne_50m.json", "geometry/centroids.json", "COLLECTED.json"])
print("\n".join(sorted(allowed)))
PY
)"
if [ -z "$ALLOWED" ]; then
  echo "!! A: 无法派生允许清单（pipeline/registry 不可 import）——审计不可信，判失败"
  FAIL=1
else
  echo "-- A1 白名单强校验：out/ 每个文件须在允许清单内"
  # 列 out/ 下全部普通文件（相对 out/ 的路径）
  while IFS= read -r rel; do
    [ -z "$rel" ] && continue
    if ! grep -qxF "$rel" <<<"$ALLOWED"; then
      echo "   !! 计划外产物（不在 ALLOWLIST）：$rel"
      FAIL=1
    fi
  done < <(cd "$OUT" 2>/dev/null && find . -type f | sed 's|^\./||')

  echo "-- A2 受限源关键词黑名单：out/ 文件名不得含受限源标识"
  # 这些子串唯一指向受限/私仓产物，且不与任何 public 产物名冲突
  BLACK='acled gbif flunet gho_ conflict ged_ camera_belt sdg_series gdacs chokepoint conjunction radar carbon finance_ ais_ fishing flights_replay satcat starlink launches ucdp covid idmc resource_trade g2_visits leader_visits refugee'
  FILES="$(cd "$OUT" 2>/dev/null && find . -type f | sed 's|^\./||')"
  for kw in $BLACK; do
    hit="$(grep -iF "$kw" <<<"$FILES" || true)"
    if [ -n "$hit" ]; then
      echo "   !! 命中受限关键词「$kw」：$hit"
      FAIL=1
    fi
  done
  [ "$FAIL" = 0 ] && echo "   ✓ A 通过：$(wc -l <<<"$FILES") 个产物全部在 ALLOWLIST 内，无受限关键词"
fi

# ── B. 零凭据明文 ─────────────────────────────────────────────────────────────
echo "-- B1 无 .env / 凭据文件"
ENVF="$(find "$HERE" -maxdepth 3 -type f \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name 'id_rsa*' -o -name '*.key' \) \
        -not -path '*/.cache/*' 2>/dev/null || true)"
if [ -n "$ENVF" ]; then echo "   !! 发现凭据文件：$ENVF"; FAIL=1; else echo "   ✓ 无 .env/密钥文件"; fi

echo "-- B2 无 token/key/secret 字面值赋值（排除 \${{ secrets.X }} 引用与 environ 变量名）"
# 扫码与配置文本（不扫 .cache/out 的数据 JSON 之外，另单独扫 out 见 B3）。
# 规则：形如  NAME = "字面值≥16"  或  NAME: 'xxxx'  且 NAME 含 KEY/TOKEN/SECRET/PASS/PWD，
# 但值不是 ${{ ... }}、不是 os.environ...、不是纯变量引用。
SUSPECT="$(grep -rInE "(TOKEN|SECRET|PASSWORD|PASSWD|PWD|API_?KEY|ACCESS_?KEY|[A-Z]+_KEY)[\"' ]*[:=][\"' ]*[\"'][^\"']{16,}[\"']" \
            "$HERE" --include='*.py' --include='*.yml' --include='*.yaml' --include='*.sh' \
            --include='*.md' --include='*.json' --include='*.txt' --include='*.cfg' --include='*.ini' \
            2>/dev/null \
          | grep -vE '\$\{\{|os\.environ|getenv|secrets\.' || true)"
if [ -n "$SUSPECT" ]; then echo "   !! 疑似凭据明文赋值："; echo "$SUSPECT"; FAIL=1; else echo "   ✓ 无凭据字面值赋值"; fi

echo "-- B3 产物 out/ 无 Bearer/长密钥形态串"
LEAK="$(grep -rIlE "Bearer [A-Za-z0-9._-]{20,}|eyJ[A-Za-z0-9._-]{20,}" "$OUT" 2>/dev/null || true)"
if [ -n "$LEAK" ]; then echo "   !! 产物疑似含令牌：$LEAK"; FAIL=1; else echo "   ✓ 产物无 Bearer/JWT 形态串"; fi

echo "== 审计结论 =="
if [ "$FAIL" = 0 ]; then
  echo "PASS：零受限数据 + 零凭据明文"
  exit 0
else
  echo "FAIL：见上（拒绝发布）"
  exit 1
fi
