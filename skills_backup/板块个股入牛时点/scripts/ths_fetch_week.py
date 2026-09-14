#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step1(新): 同花顺后复权日线 -> 聚合周线
URL: http://d.10jqka.com.cn/v6/line/hs_{code}/02/all.js
price 每4个数一组 [low, open-low, high-low, close-low] / priceFactor
输出: data/kline_week_adj.csv (code,wk,open,high,low,close,volume)
"""
import json, subprocess, os, sys, re, time, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "/sandbox/workspace/zxz_bt"
DATA = os.path.join(BASE, "data")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


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


def parse_weekly(txt):
    m = re.search(r"\((\{.*\})\)\s*;?\s*$", txt, re.S)
    if not m:
        return []
    j = json.loads(m.group(1))
    pf = float(j.get("priceFactor", 100) or 100)
    p = [float(x) / pf for x in j["price"].split(",") if x != ""]
    dates = [x for x in j["dates"].split(",") if x]
    sy = j.get("sortYear", [])
    n = min(len(p) // 4, len(dates))
    full, yi, cnt = [], 0, 0
    for k in range(n):
        while yi < len(sy) and cnt >= int(sy[yi][1]):
            yi += 1
            cnt = 0
        if yi >= len(sy):
            break
        full.append(f"{int(sy[yi][0])}{dates[k]}")
        cnt += 1
    weekly = {}
    for k in range(min(n, len(full))):
        lo = p[4 * k]
        o = lo + p[4 * k + 1]
        h = lo + p[4 * k + 2]
        c = lo + p[4 * k + 3]
        ds = full[k]
        try:
            d = datetime.date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
        except Exception:
            continue
        iso = d.isocalendar()
        wk = f"{iso[0]}-W{iso[1]:02d}"
        if wk not in weekly:
            weekly[wk] = [o, h, lo, c]
        else:
            w = weekly[wk]
            w[1] = max(w[1], h)
            w[2] = min(w[2], lo)
            w[3] = c
    return [(wk, v[0], v[1], v[2], v[3]) for wk, v in sorted(weekly.items())]


def fetch_one(args):
    sym, code = args
    txt = curl(f"http://d.10jqka.com.cn/v6/line/hs_{code}/02/all.js")
    if not txt:
        return sym, []
    try:
        return sym, parse_weekly(txt)
    except Exception:
        return sym, []


def main():
    syms = []
    with open(os.path.join(DATA, "pool.csv"), encoding="utf-8") as f:
        next(f)
        for ln in f:
            p = ln.strip().split(",")
            if p and p[0]:
                syms.append((p[0], p[0][2:]))
    print(f"拉取 {len(syms)} 只 -> 周线 ...", flush=True)
    outfp = os.path.join(DATA, "kline_week_adj.csv")
    f = open(outfp, "w", encoding="utf-8")
    f.write("code,wk,open,high,low,close,volume\n")
    ok, t0 = 0, time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_one, s): s for s in syms}
        for i, fu in enumerate(as_completed(futs), 1):
            sym, res = fu.result()
            if res:
                ok += 1
                for wk, o, h, lo, c in res:
                    f.write(f"{sym},{wk},{o:.4f},{h:.4f},{lo:.4f},{c:.4f},0\n")
            if i % 500 == 0:
                print(f"  {i}/{len(syms)} ok={ok} {time.time()-t0:.0f}s", flush=True)
    f.close()
    print(f"完成 {ok}/{len(syms)} -> {outfp} 用时{time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
