"""全球温度异常（HadCRUT via OWID grapher）→ temp_stripes.json [[year, anomaly], ...]。
序章温度条纹层（1850 登场）数据。取 World 实体。"""
import csv
import io

from common import cached_get, status, write_json

SLUGS = ["temperature-anomaly", "average-monthly-surface-temperature-anomalies",
         "global-warming-land"]


def main():
    for slug in SLUGS:
        try:
            text = cached_get(
                f"https://ourworldindata.org/grapher/{slug}.csv?v=1&csvType=full&useColumnShortNames=true",
                f"owid_{slug}.csv", timeout=300)
        except Exception as e:
            status(f"{slug} unavailable: {e}")
            continue
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            continue
        col = next((c for c in rows[0] if c.lower() not in ("entity", "code", "year")), None)
        out = []
        for r in rows:
            ent = (r.get("entity") or r.get("Entity") or "").strip()
            code = r.get("code") or r.get("Code") or ""
            if ent != "World" and code != "OWID_WRL":
                continue
            try:
                y, v = int(r.get("year") or r["Year"]), float(r[col])
            except (ValueError, TypeError, KeyError):
                continue
            out.append([y, round(v, 3)])
        if len(out) > 50:
            out.sort()
            # 若为月度数据则按年取均值
            by_year = {}
            for y, v in out:
                by_year.setdefault(y, []).append(v)
            series = [[y, round(sum(vs) / len(vs), 3)] for y, vs in sorted(by_year.items())]
            write_json("temp_stripes.json", {"slug": slug, "series": series})
            status(f"wrote temp_stripes.json from {slug}: {len(series)} years "
                   f"({series[0][0]}–{series[-1][0]})")
            break
    else:
        status("no temperature slug worked; stripes layer will be hidden")


if __name__ == "__main__":
    main()
