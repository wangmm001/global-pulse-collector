"""共用工具：带缓存的抓取、JSON 输出、反子午线切割。全部脚本幂等。"""
import csv
import io
import json
import math
import os
import sys
import time
import zipfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
OUT = os.path.join(ROOT, "public", "data")
UA = {"User-Agent": "GlobalPulse-research/0.1 (data-viz film prototype)"}

os.makedirs(CACHE, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def cached_get(url, name, binary=False, timeout=120, max_age=None, immutable=False, headers=None):
    """GET with on-disk cache（设计文档 §4.2：默认幂等，重跑不再请求）。

    max_age: 秒——缓存超龄则重取（动态数据集用）。None=永不过期。
    immutable=True：豁免 GP_FRESH_HOURS——发布后不变的大文件（年度版 zip 等）
    进每日刷新数据集时不被全局 TTL 逼着天天重下。
    环境变量 GP_FRESH_HOURS：全局把有效期压到 N 小时（run.py --daily 设 12），
    与 max_age 取更严者；未设置该变量时行为与旧版完全一致。
    重取失败但旧缓存尚在：警告并回退旧缓存——端点抖动/离线不致构建失败。
    """
    path = os.path.join(CACHE, name)
    has = os.path.exists(path) and os.path.getsize(path) > 0
    ttl = max_age
    env_h = os.environ.get("GP_FRESH_HOURS")
    if env_h and not immutable:
        try:
            env_ttl = float(env_h) * 3600
            ttl = env_ttl if ttl is None else min(ttl, env_ttl)
        except ValueError:
            pass
    fresh = has and (ttl is None or time.time() - os.path.getmtime(path) <= ttl)
    if fresh:
        with open(path, "rb" if binary else "r") as f:
            return f.read()
    try:
        print(f"  fetch {url}")
        r = requests.get(url, headers={**UA, **(headers or {})}, timeout=timeout)
        r.raise_for_status()
        data = r.content if binary else r.text
        with open(path, "wb" if binary else "w") as f:
            f.write(data)
        return data
    except Exception as e:
        if has:
            print(f"  !! 重取失败（{e}）——回退旧缓存 {name}")
            with open(path, "rb" if binary else "r") as f:
                return f.read()
        raise


def write_json(name, obj):
    path = os.path.join(OUT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    print(f"  wrote {name} ({os.path.getsize(path)/1e6:.2f} MB)")


def read_csv_text(text):
    return list(csv.DictReader(io.StringIO(text)))


def zip_csv_rows(blob, member_suffix=".csv"):
    zf = zipfile.ZipFile(io.BytesIO(blob))
    member = next(n for n in zf.namelist() if n.endswith(member_suffix))
    with zf.open(member) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace")))


def split_antimeridian(coords):
    """把跨 ±180° 的 LineString 切成多段（设计文档 §7.1 硬要求）。"""
    if len(coords) < 2:
        return [coords]
    segs, cur = [], [coords[0]]
    for prev, pt in zip(coords, coords[1:]):
        lon0, lon1 = prev[0], pt[0]
        if abs(lon1 - lon0) > 180:  # crossing
            # interpolate latitude at the seam
            if lon1 > lon0:
                span = (lon0 + 180) + (180 - lon1)
                t = (lon0 + 180) / span if span else 0.5
                seam0, seam1 = -180.0, 180.0
            else:
                span = (180 - lon0) + (lon1 + 180)
                t = (180 - lon0) / span if span else 0.5
                seam0, seam1 = 180.0, -180.0
            lat = prev[1] + (pt[1] - prev[1]) * t
            cur.append([seam0, lat])
            segs.append(cur)
            cur = [[seam1, lat], pt]
        else:
            cur.append(pt)
    segs.append(cur)
    return [s for s in segs if len(s) >= 2]


def gc_interpolate(a, b, n):
    """大圆插值（AIS 远洋缺口补全，设计文档 §7.5）。a/b=[lon,lat]，返回 n+1 个点。"""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2 * math.asin(math.sqrt(
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2))
    if d < 1e-9:
        return [list(a)] * (n + 1)
    pts = []
    for i in range(n + 1):
        f = i / n
        A = math.sin((1 - f) * d) / math.sin(d)
        B = math.sin(f * d) / math.sin(d)
        x = A * math.cos(lat1) * math.cos(lon1) + B * math.cos(lat2) * math.cos(lon2)
        y = A * math.cos(lat1) * math.sin(lon1) + B * math.cos(lat2) * math.sin(lon2)
        z = A * math.sin(lat1) + B * math.sin(lat2)
        pts.append([round(math.degrees(math.atan2(y, x)), 4),
                    round(math.degrees(math.atan2(z, math.sqrt(x * x + y * y))), 4)])
    return pts


def quantile_classes(values, n):
    """分位数分级（终章文档 3.2：不用等距）。返回阈值列表（n-1 个）。"""
    vs = sorted(v for v in values if v is not None and not math.isnan(v))
    if not vs:
        return []
    return [vs[min(len(vs) - 1, int(len(vs) * k / n))] for k in range(1, n)]


def classify(v, thresholds):
    c = 0
    for t in thresholds:
        if v is not None and v > t:
            c += 1
    return c


def status(msg):
    print(f"[{os.path.basename(sys.argv[0])}] {msg}")


def env_secret(key):
    """通用密钥读取：环境变量优先 → pipeline/.env 的 KEY= 行。无则 None。"""
    v = os.environ.get(key)
    if v:
        return v.strip()
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return None


def ucdp_token():
    """UCDP API token（2026 起 API 需 x-ucdp-access-token 头；下载页仍免注册）。
    读取顺序：环境变量 UCDP_TOKEN → pipeline/.env 的 UCDP_TOKEN=。无则返回 None。"""
    t = os.environ.get("UCDP_TOKEN")
    if t:
        return t.strip()
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line.startswith("UCDP_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


# OpenSky OAuth2 token 端点（Keycloak realm=opensky-network）。
# 实测 2026-07-18（curl）：老 basic-auth 已退役（2026-03 官方公告），带错误
# basic 凭据请求 /states/all 静默返回 200 匿名体——basic 头被忽略，不再是认证通道；
# 认证一律走此 client-credentials 流。空 grant_type=client_credentials POST 得
# 401 {"error":"invalid_client"}，证端点在线且要求 client_id/secret。
# token 有效期 30 分钟（单次构建远短于此，无需刷新逻辑）。
OPENSKY_TOKEN_URL = ("https://auth.opensky-network.org/auth/realms/"
                     "opensky-network/protocol/openid-connect/token")


def opensky_token():
    """OpenSky OAuth2 access token（client-credentials 流）。
    凭据 OPENSKY_CLIENT_ID/OPENSKY_CLIENT_SECRET（env_secret：环境变量 → .env）。
    在 opensky-network.org 账号 → My OpenSky → API client 处生成 client_id/secret。
    缺凭据或换取失败 → 返回 None（调用方降级匿名，语义不变）。"""
    cid, secret = env_secret("OPENSKY_CLIENT_ID"), env_secret("OPENSKY_CLIENT_SECRET")
    if not (cid and secret):
        return None
    try:
        r = requests.post(OPENSKY_TOKEN_URL, headers=UA, timeout=60, data={
            "grant_type": "client_credentials",
            "client_id": cid, "client_secret": secret})
        r.raise_for_status()
        tok = r.json().get("access_token")
        return tok.strip() if tok else None
    except Exception as e:
        print(f"  !! opensky_token 换取失败（{e}）——降级匿名")
        return None
