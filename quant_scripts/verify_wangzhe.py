#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核验 600545 / 600103 是否符合『王者倍量柱』形态（才哥正版定义）"""
import csv
from collections import defaultdict
import numpy as np
DATA="/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
# 本地数据只到 9/11，这里用抓到的 9/12-9/16 数据手工补
EXTRA={
 "sh600545":[("2026-09-11",4.09,4.24,3.93,4.18,1103660),("2026-09-14",4.12,4.57,4.07,4.45,1962999),
             ("2026-09-15",4.42,4.55,4.28,4.29,1143101),("2026-09-16",4.30,4.72,4.22,4.72,2052690)],
 "sh600103":[("2026-09-11",3.72,3.76,3.55,3.67,2051449),("2026-09-14",3.60,3.70,3.50,3.61,1842528),
             ("2026-09-15",3.56,3.57,3.33,3.35,2567658),("2026-09-16",3.28,3.69,3.28,3.69,2628783)],
}
by=defaultdict(list)
for r in csv.DictReader(open(DATA,encoding="utf-8")):
    try: by[r["code"]].append((r["date"],float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"]),float(r["volume"])))
    except: continue
for c in by: by[c].sort(key=lambda x:x[0])
for code,rows in EXTRA.items():
    have={b[0] for b in by[code]}
    for b in rows:
        if b[0] not in have: by[code].append(b)
    by[code].sort(key=lambda x:x[0])

def analyze(code,name):
    bars=by[code]
    print(f"\n{'='*70}\n【{code} {name}】最近 10 日")
    print(f"{'日期':<12}{'收盘':>8}{'涨跌幅':>9}{'量':>12}{'量比':>8}{'判定':>12}")
    for i in range(max(1,len(bars)-10), len(bars)):
        d,o,h,l,c,v=bars[i]
        prev=bars[i-1][4]; pc=(c/prev-1)*100
        vr=v/bars[i-1][5] if bars[i-1][5] else 0
        lim = c >= round(prev*1.10,2)-0.001
        tag=""
        if lim: tag="涨停"
        print(f"{d:<12}{c:>8.2f}{pc:>+8.2f}%{int(v):>12,}{vr:>8.2f}{tag:>12}")
    # 判定：王者倍量柱 = 涨停日T(量比1.5~4) + T+1..T+3 缩量且站稳
    print(f"\n  形态核验（才哥正版：放量涨停 → 后3日缩量且平均收盘>涨停日收盘）：")
    for i in range(max(1,len(bars)-8), len(bars)):
        d,o,h,l,c,v=bars[i]
        prev=bars[i-1][4]
        if c < round(prev*1.10,2)-0.001: continue
        vr=v/bars[i-1][5] if bars[i-1][5] else 0
        print(f"    {d} 涨停：量比 {vr:.2f} {'✅在1.5~4内' if 1.5<=vr<=4 else '❌不在1.5~4内（不是倍量柱）'}")
        if i+1 < len(bars):
            print(f"      → 后续交易日数：{len(bars)-1-i} 天（需≥3天才能确认）")
            if len(bars)-1-i >= 3:
                c1,c2,c3=bars[i+1][4],bars[i+2][4],bars[i+3][4]
                v1,v2,v3=bars[i+1][5],bars[i+2][5],bars[i+3][5]
                avg_c=(c1+c2+c3)/3; avg_v=(v1+v2+v3)/3
                ok_c = avg_c > c; ok_v = avg_v < v
                print(f"      → T+1~T+3 均收盘 {avg_c:.2f} vs 涨停日 {c:.2f} → {'✅站稳' if ok_c else '❌未站稳'}")
                print(f"      → T+1~T+3 均量 {int(avg_v):,} vs 涨停日 {int(v):,} → {'✅缩量' if ok_v else '❌未缩量'}")
                print(f"      → 结论：{'✅ 是王者倍量柱' if (ok_c and ok_v) else '❌ 不是王者倍量柱'}")
            else:
                print(f"      → ❌ 尚不足3天，无法确认王者倍量柱")
analyze("sh600545","卓郎智能")
analyze("sh600103","青山纸业")
