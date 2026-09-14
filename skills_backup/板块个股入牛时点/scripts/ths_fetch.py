#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step2(final): 同花顺 v6 后复权日线(02) -> 月线
URL: http://d.10jqka.com.cn/v6/line/hs_{code}/02/all.js
编码: price 每4个数一组 [low, open-low, high-low, close-low] / priceFactor
输出: data/kline_month_adj.csv (code,ym,open,high,low,close,volume)
用法: python3 fetch_ths.py test N | all
"""
import json, subprocess, os, sys, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "/sandbox/workspace/zxz_bt"
DATA = os.path.join(BASE, "data")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
HEAD = "quotebridge_v6_line_"


def curl(url):
    for i in range(4):
        try:
            r = subprocess.run(["curl", "-s", "--max-time", "45", "-A", UA, url],
                               capture_output=True, text=True)
            t = (r.stdout or "").strip()
            if t and "quotebridge" in t:
                return t
        except Exception:
            pass
        time.sleep(0.8 + 1.2 * i)
    return ""


def parse(txt, code):
    m = re.search(r"\((\{.*\})\)\s*;?\s*$", txt, re.S)
    if not m:
        return []
    j = json.loads(m.group(1))
    pf = float(j.get("priceFactor", 100) or 100)
    p = [float(x) / pf for x in j["price"].split(",") if x != ""]
    dates = [x for x in j["dates"].split(",") if x]
    sy = j.get("sortYear", [])
    n = min(len(p) // 4, len(dates))
    # 还原完整日期
    full = []
    yi, cnt = 0, 0
    for k in range(n):
        while yi < len(sy) and cnt >= int(sy[yi][1]):
            yi += 1
            cnt = 0
        if yi >= len(sy):
            break
        full.append(f"{int(sy[yi][0])}{dates[k]}")
        cnt += 1
    # OHLC + 月线聚合
    monthly = {}
    for k in range(min(n, len(full))):
        lo = p[4 * k]
        o = lo + p[4 * k + 1]
        h = lo + p[4 * k + 2]
        c = lo + p[4 * k + 3]
        ym = f"{full[k][:4]}-{full[k][4:6]}"
        if ym not in monthly:
            monthly[ym] = [o, h, lo, c]
        else:
            mm = monthly[ym]
            mm[1] = max(mm[1], h)
            mm[2] = min(mm[2], lo)
            mm[3] = c
    return [(ym, v[0], v[1], v[2], v[3]) for ym, v in sorted(monthly.items())]


def fetch_one(args):
    sym, code = args
    txt = curl(f"http://d.10jqka.com.cn/v6/line/hs_{code}/02/all.js")
    if not txt:
        return sym, []
    try:
        return sym, parse(txt, code)
    except Exception:
        return sym, []


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    syms = []
    with open(os.path.join(DATA, "pool.csv"), encoding="utf-8") as f:
        next(f)
        for ln in f:
            p = ln.strip().split(",")
            if p and p[0]:
                syms.append((p[0], p[0][2:]))
    if mode == "test":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        syms = syms[:n] + syms[-5:]
    workers = 8
    print(f"拉取 {len(syms)} 只, {workers} workers ...", flush=True)
    outfp = os.path.join(DATA, "kline_month_adj.csv")
    f = open(outfp, "w", encoding="utf-8")
    f.write("code,ym,open,high,low,close,volume\n")
    ok, t0 = 0, time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_one, s): s for s in syms}
        for i, fu in enumerate(as_completed(futs), 1):
            sym, res = fu.result()
            if res:
                ok += 1
                for ym, o, h, lo, c in res:
                    f.write(f"{sym},{ym},{o:.4f},{h:.4f},{lo:.4f},{c:.4f},0\n")
            if i % 300 == 0:
                print(f"  {i}/{len(syms)} ok={ok} {time.time()-t0:.0f}s", flush=True)
    f.close()
    print(f"完成 {ok}/{len(syms)} -> {outfp} 用时{time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
