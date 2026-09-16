#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""王者倍量柱退出策略 · 年度分层稳定性检验（2026-09-16）
对最优策略 T10（+10%止盈/最长60日）与基线 H5、H60 做逐年分解，检验跨年稳定性。
"""
import csv, json, os
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
MAX_HOLD = 60; WARMUP = 25

by = defaultdict(list)
with open(DATA, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try:
            by[r["code"]].append((r["date"], float(r["open"]), float(r["high"]),
                                  float(r["low"]), float(r["close"]), float(r["volume"])))
        except (ValueError, KeyError): continue
for c in by: by[c].sort(key=lambda x: x[0])

def clean(bars):
    o=np.array([b[1] for b in bars]); h=np.array([b[2] for b in bars]); l=np.array([b[3] for b in bars])
    c=np.array([b[4] for b in bars]); v=np.array([b[5] for b in bars])
    bad=(c<=0.3)|(v<=0)
    if bad.any():
        k=~bad; o,h,l,c,v=o[k],h[k],l[k],c[k],v[k]; bars=[b for b,kk in zip(bars,k) if kk]
    return bars,o,h,l,c,v

def sim(entry,o,h,l,c,i0,rules):
    n=len(c); maxd=min(MAX_HOLD,n-i0)
    if maxd<1 or entry<=0: return None
    tgt=rules.get("target"); fixed=rules.get("hold")
    for k in range(maxd):
        j=i0+k; r=c[j]/entry-1
        if tgt and r>=tgt: return (r,k+1,bars_yr:=None)
        if fixed and k+1>=fixed: return (r,k+1,None)
    return (c[i0+maxd-1]/entry-1,maxd,None)

REC={}
RULES={"H5":{"hold":5},"H60":{"hold":60},"T10":{"target":0.10,"hold":60},"T15":{"target":0.15,"hold":60}}
for code,bars in by.items():
    bars,o,h,l,c,v=clean(bars); n=len(bars)
    if n<100: continue
    for i in range(WARMUP,n-2):
        if c[i] < round(c[i-1]*1.10,2)-0.001: continue
        if i>=2 and c[i-1] >= round(c[i-2]*1.10,2)-0.001: continue
        vr=v[i]/v[i-1] if v[i-1] else 0
        if not (1.5<=vr<=4): continue
        yr=bars[i][0][:4]
        for k,r in RULES.items():
            rr=sim(c[i],o,h,l,c,i,r)
            if rr: REC.setdefault(k,{}).setdefault(yr,[]).append(rr[0])

print(f"{'年份':<7}" + "".join(f"{k:>16}" for k in RULES))
print("-"*75)
years=sorted(set(y for k in REC for y in REC[k]))
for y in years:
    line=f"{y:<7}"
    for k in RULES:
        v=REC[k].get(y,[])
        if v: line+=f"{np.mean(v)*100:>+9.2f}%({len(v):>4})"[:16].rjust(16)
        else: line+=f"{'-':>16}"
    print(line)
print("-"*75)
line=f"{'合计':<7}"
for k in RULES:
    v=[x for y in REC[k] for x in REC[k][y]]
    line+=f"{np.mean(v)*100:>+9.2f}%({len(v):>4})"[:16].rjust(16)
print(line)

# 逐年胜率
print(f"\n{'年份':<7}" + "".join(f"{k+'胜率':>14}" for k in RULES))
for y in years:
    line=f"{y:<7}"
    for k in RULES:
        v=REC[k].get(y,[])
        line+=f"{(np.array(v)>0).mean()*100:>12.1f}%" if v else f"{'-':>14}"
    print(line)
