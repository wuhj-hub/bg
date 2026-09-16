#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G4 vs C6 vs T10 年度稳定性检验（2026-09-16）"""
import csv
from collections import defaultdict
import numpy as np
DATA="/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
WARM=30; MAXH=120
by=defaultdict(list)
for r in csv.DictReader(open(DATA,encoding="utf-8")):
    try: by[r["code"]].append((r["date"],float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"]),float(r["volume"])))
    except: continue
for c in by: by[c].sort(key=lambda x:x[0])
def clean(bars):
    o=np.array([b[1] for b in bars]);h=np.array([b[2] for b in bars]);l=np.array([b[3] for b in bars])
    c=np.array([b[4] for b in bars]);v=np.array([b[5] for b in bars])
    bad=(c<=0.3)|(v<=0)
    if bad.any():
        k=~bad;o,h,l,c,v=o[k],h[k],l[k],c[k],v[k];bars=[b for b,kk in zip(bars,k) if kk]
    return bars,o,h,l,c,v
def ema(a,n):
    out=np.full(len(a),np.nan)
    if len(a)<n: return out
    out[n-1]=a[:n].mean(); k=2/(n+1)
    for i in range(n,len(a)): out[i]=a[i]*k+out[i-1]*(1-k)
    return out
def sma(a,n):
    out=np.full(len(a),np.nan)
    for i in range(n-1,len(a)): out[i]=a[i-n+1:i+1].mean()
    return out
REC={}
for code,bars in by.items():
    bars,o,h,l,c,v=clean(bars); n=len(bars)
    if n<180: continue
    prevc=np.roll(c,1); prevc[0]=c[0]
    tr=np.maximum(h-l,np.maximum(np.abs(h-prevc),np.abs(l-prevc)))
    holdline=ema(c,20)-2*sma(tr,14); ma5=sma(c,5)
    for i in range(WARM,n-3):
        if c[i]<round(c[i-1]*1.10,2)-0.001: continue
        if i>=2 and c[i-1]>=round(c[i-2]*1.10,2)-0.001: continue
        vr=v[i]/v[i-1] if v[i-1] else 0
        if not (1.5<=vr<=4): continue
        y=bars[i][0][:4]; entry=c[i]; end=min(i+1+MAXH,n-1)
        peak=entry; armed=False; hit={"G4":False,"C6":False,"T10":False}
        for j in range(i+1,end+1):
            r_=c[j]/entry-1; peak=max(peak,h[j])
            if not armed and (peak/entry-1)>=0.05: armed=True
            if not hit["G4"] and ((not np.isnan(holdline[j]) and c[j]<holdline[j]) or (armed and (peak-c[j])/peak>=0.03)):
                REC.setdefault("G4",{}).setdefault(y,[]).append(r_); hit["G4"]=True
            if not hit["C6"] and ((not np.isnan(ma5[j]) and c[j]<ma5[j]) or (armed and (peak-c[j])/peak>=0.03)):
                REC.setdefault("C6",{}).setdefault(y,[]).append(r_); hit["C6"]=True
            if not hit["T10"] and r_>=0.10:
                REC.setdefault("T10",{}).setdefault(y,[]).append(0.10); hit["T10"]=True
        for k in ("G4","C6","T10"):
            if not hit[k]: REC.setdefault(k,{}).setdefault(y,[]).append(c[end]/entry-1)
years=sorted(set(y for k in REC for y in REC[k]))
print("=== 年度平均收益 ===")
print(f"{'年份':<7}"+"".join(f"{k:>12}" for k in ("G4","C6","T10")))
for y in years:
    line=f"{y:<7}"
    for k in ("G4","C6","T10"):
        vals=REC[k].get(y,[])
        line+=f"{np.mean(vals)*100:>+11.2f}%" if vals else f"{'-':>12}"
    print(line)
print("\n=== 年度胜率 ===")
print(f"{'年份':<7}"+"".join(f"{k:>12}" for k in ("G4","C6","T10")))
for y in years:
    line=f"{y:<7}"
    for k in ("G4","C6","T10"):
        vals=REC[k].get(y,[])
        line+=f"{(np.array(vals)>0).mean()*100:>11.1f}%" if vals else f"{'-':>12}"
    print(line)
print("\n=== 合计 ===")
for k in ("G4","C6","T10"):
    allv=[x for y in REC[k] for x in REC[k][y]]
    print(f"  {k}: 平均{np.mean(allv)*100:+.2f}% 中位{np.median(allv)*100:+.2f}% 胜率{(np.array(allv)>0).mean()*100:.1f}% n={len(allv)}")
