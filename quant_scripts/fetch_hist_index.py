#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_hist_index.py —— 腾讯 proxy.finance.qq.com 历史K线拉取（补验2015/2018顶部）
输出 data_hs300/上证指数_日K_2014至今.json（升序 rows: date/open/last/high/low/volume/amount）
"""
import json, time, urllib.request

def fetch_range(code, start, end, cnt=800):
    url = f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param={code},day,{start},{end},{cnt},qfq"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode())
            break
        except Exception as e:
            if attempt == 4:
                print(f"  ⚠️ {start}~{end} 拉取失败: {e}")
                return []
            time.sleep(3 * (attempt + 1))
    klines = d.get("data", {}).get(code, {}).get("day") or d.get("data", {}).get(code, {}).get("qfqday") or []
    rows = []
    for k in klines:
        # [date, open, close, high, low, volume, {}, pct, amount(万), ...]
        try:
            rows.append({
                "date": k[0],
                "open": float(k[1]), "last": float(k[2]),
                "high": float(k[3]), "low": float(k[4]),
                "volume": float(k[5]),
                "amount": float(k[8]) * 10000 if len(k) > 8 else 0,  # 万→元
            })
        except (ValueError, IndexError):
            continue
    return rows

def main():
    code = "sh000001"
    all_rows, seen = [], set()
    # 分段拉取：2013 至 2026（覆盖 2015-06 顶部前 2 年窗口）
    for y in range(2013, 2027):
        seg = fetch_range(code, f"{y}-01-01", f"{y}-12-31")
        for r in seg:
            if r["date"] not in seen:
                seen.add(r["date"])
                all_rows.append(r)
        time.sleep(0.5)
        print(f"{y}: {len(seg)} 根")
    all_rows.sort(key=lambda r: r["date"])
    print(f"\n合计 {len(all_rows)} 根（{all_rows[0]['date']} ~ {all_rows[-1]['date']}）")
    # 抽查关键时点
    for d in ("2015-06-12", "2015-08-24", "2018-01-29", "2021-02-18"):
        hit = [r for r in all_rows if r["date"] == d]
        if hit:
            r = hit[0]
            print(f"  {d}: 收盘{r['last']:.2f} 成交额{r['amount']/1e8:.0f}亿")
    import os
    os.makedirs("data_hs300", exist_ok=True)
    out = "data_hs300/上证指数_日K_2013至今.json"
    json.dump(all_rows, open(out, "w"), ensure_ascii=False)
    print(f"保存: {out}")

if __name__ == "__main__":
    main()
