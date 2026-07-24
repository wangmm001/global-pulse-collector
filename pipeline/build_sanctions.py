# -*- coding: utf-8 -*-
"""OFAC 制裁行动事件库（2.0 支柱三 §1.1 首切片）：SLS changes 增量通道 → 国家-日聚合。

数据源：sanctionslistservice.ofac.treas.gov/changes（官方 Delta 通道，逐 publication
immutable 缓存）。许可：美国联邦政府作品=公有领域（17 U.S.C. §105）——事件化聚合
不再分发实体名单本身（DATASOURCES-2.0 §1.1 设计：规避聚合器 NC 问题的自建路线）。

语义口径（meta 注记随产物走）：
  target_iso 优先 program→国家 curated 映射（"该制裁计划针对谁"：IRAN-EO13902→IRN、
  UKRAINE-EO13661 系针对俄→RUS）；主题类计划（反恐 SDGT/FTO、毒品、网络、GLOMAG）
  无目标国 → 回落实体主地址国（"被列实体在哪"）；两不中 → iso='XX' 保全量不上图。
  动作只计 add / remove（delta 里 modify 为条目维护噪声，不构成制裁事件）。
产物 sanction_events.json：{meta, rows:[[day, iso, act(0=加列/1=移除), n, program]]}
"""
import datetime as dt
import json
import xml.etree.ElementTree as ET
from collections import Counter

from common import cached_get, status, write_json
from geo_iso import iso_by_name

API = "https://sanctionslistservice.ofac.treas.gov/changes"
NS = {"d": "https://www.treasury.gov/ofac/DeltaFile/1.0"}
YEARS = [2023, 2024, 2025, 2026]  # 官方归档起点 2023（SLS Delta 上线年）；更早需 Wayback SDN diff（全量立项）
EPOCH = dt.date(1970, 1, 1)

# program 前缀 → 目标国（自上而下首中即定；None=主题类，走地址国回落）
PROGRAM_ISO = [
    ("IRAN", "IRN"), ("IFSR", "IRN"), ("DPRK", "PRK"), ("NKSPEA", "PRK"),
    ("RUSSIA", "RUS"), ("UKRAINE-EO", "RUS"), ("PEESA", "RUS"), ("MAGNIT", "RUS"),
    ("CAATSA", "RUS"), ("BPI-RUSSIA", "RUS"),
    ("BELARUS", "BLR"), ("SYRIA", "SYR"), ("CUBA", "CUB"), ("VENEZUELA", "VEN"),
    ("NICARAGUA", "NIC"), ("BURMA", "MMR"), ("IRAQ", "IRQ"), ("LIBYA", "LBY"),
    ("SOMALIA", "SOM"), ("YEMEN", "YEM"), ("SOUTH SUDAN", "SSD"), ("DARFUR", "SDN"),
    ("SUDAN", "SDN"), ("CAR", "CAF"), ("DRCONGO", "COD"), ("CONGO", "COD"),
    ("ZIMBABWE", "ZWE"), ("MALI", "MLI"), ("HAITI", "HTI"), ("LEBANON", "LBN"),
    ("ETHIOPIA", "ETH"), ("HK-", "HKG"), ("CMIC", "CHN"), ("CHINESE-MILITARY", "CHN"),
    ("AFGHANISTAN", "AFG"), ("NS-PLC", "PSE"), ("HRIT-SY", "SYR"),
    ("FSE-SY", "SYR"), ("HRIT-IR", "IRN"),
]


def prog_iso(p):
    u = (p or "").upper()
    for pre, iso in PROGRAM_ISO:
        if u.startswith(pre):
            return iso
    return None


def eday(iso_ts):
    return (dt.date.fromisoformat(iso_ts[:10]) - EPOCH).days


def main():
    pubs = []
    for y in YEARS:
        txt = cached_get(f"{API}/history/{y}", f"ofac_hist_{y}.json",
                         max_age=(6 * 3600 if y == dt.date.today().year else None),
                         immutable=(y != dt.date.today().year))
        pubs += json.loads(txt)
    pubs.sort(key=lambda p: p["datePublished"])
    status(f"sanctions: {len(pubs)} publications（{YEARS[0]}–）")

    agg = {}                      # (day, iso, act) -> {n, progs Counter}
    act_dist = Counter()
    unmapped = Counter()
    for p in pubs:
        pid = p["publicationID"]
        xml = cached_get(f"{API}/{pid}", f"ofac_pub_{pid}.xml", immutable=True)
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            status(f"  pub {pid}: XML 解析失败，跳过")
            continue
        day = eday(p["datePublished"])
        ents = root.find("d:entities", NS)
        if ents is None:
            continue
        for e in ents:
            a = (e.attrib.get("action") or "").lower()
            act_dist[a or "(none)"] += 1
            if a == "add":
                act = 0
            elif a in ("remove", "delete", "removed"):
                act = 1
            else:
                continue          # modify/无动作=条目维护，不构成事件
            prog = None
            for sp in e.findall(".//d:sanctionsProgram", NS):
                prog = sp.text
                break
            iso = prog_iso(prog)
            if not iso:           # 主题类计划：回落实体主地址国
                for c in e.findall(".//d:country", NS):
                    iso = iso_by_name(c.text or "")
                    if iso:
                        break
            if not iso:
                unmapped[prog or "(无计划)"] += 1
                iso = "XX"
            k = (day, iso, act)
            if k not in agg:
                agg[k] = {"n": 0, "progs": Counter()}
            agg[k]["n"] += 1
            if prog:
                agg[k]["progs"][prog] += 1

    rows = [[d, iso, act, v["n"], (v["progs"].most_common(1)[0][0] if v["progs"] else "")]
            for (d, iso, act), v in sorted(agg.items())]
    days = [r[0] for r in rows]
    obj = {
        "meta": {
            "note": "OFAC SLS changes 事件化：target_iso=计划映射优先/主题类回落地址国；"
                    "act 0=加列 1=移除；n=当日该国该动作实体数；不含实体名单本身",
            "built": dt.date.today().isoformat(),
            "window": [min(days), max(days)] if days else None,
            "pubs": len(pubs), "rows": len(rows),
            "source": "sanctionslistservice.ofac.treas.gov（美国联邦政府作品，公有领域 17 U.S.C. §105）",
        },
        "rows": rows,
    }
    write_json("sanction_events.json", obj)
    n_add = sum(r[3] for r in rows if r[2] == 0)
    n_rem = sum(r[3] for r in rows if r[2] == 1)
    status(f"sanctions: {len(rows)} 国家-日行（加列 {n_add} / 移除 {n_rem} 实体）"
           f"；动作分布 {dict(act_dist)}；未映射 {dict(unmapped) or '无'}")


if __name__ == "__main__":
    main()
