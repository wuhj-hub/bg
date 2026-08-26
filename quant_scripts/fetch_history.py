#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_history.py —— 腾讯proxy长历史分段拉取（P0-3 · 2026-08-26）
腾讯接口单次最多约800根，按2年分段拉取合并，覆盖2013至今。
个股与指数通用（指数也可用）。
"""
import json, time, urllib.request

SEGMENTS = [
    ("2013-01-01", "2014-12-31"), ("2015-01-01", "2016-12-31"),
    ("2017-01-01", "2018-12-31"), ("2019-01-01", "2020-12-31"),
    ("2021-01-01", "2022-12-31"), ("2023-01-01", "2024-06-30"),
    ("2024-07-01", "2026-12-31"),
]


def fetch_stock_history(code, start="2013-01-01", end="2026-12-31"):
    """腾讯proxy个股/指数日K（前复权）·分段拉取合并去重，返回升序 rows"""
    all_rows, seen = [], set()
    for s, e in SEGMENTS:
        if s < start:
            continue
        url = f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param={code},day,{s},{e},800,qfq"
        d = {}
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
                break
            except Exception:
                if attempt == 3:
                    d = {}
                time.sleep(1.5 * (attempt + 1))
        kl = d.get("data", {}).get(code, {}).get("qfqday") or d.get("data", {}).get(code, {}).get("day") or []
        for k in kl:
            try:
                date = k[0]
                if date in seen:
                    continue
                seen.add(date)
                all_rows.append({"date": date, "open": float(k[1]), "last": float(k[2]),
                                 "high": float(k[3]), "low": float(k[4]), "volume": float(k[5])})
            except (ValueError, IndexError):
                continue
        time.sleep(0.2)
    all_rows.sort(key=lambda r: r["date"])
    return all_rows


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "sh000001"
    rows = fetch_stock_history(code)
    print(f"{code}: {len(rows)} 根（{rows[0]['date']} ~ {rows[-1]['date']}）")
