#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证：在 120 日窗口内，黄金线 / 持股线 各触发多少次？"""
import csv
from collections import defaultdict
import numpy as np
DATA="/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
by=defaultdict(list)
for r in csv.DictReader(open(DATA,encoding="utf-8")):
    try: by[r["code"]].append((r["date"],float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"]),float(r["volume"])))
    except: continue
for c in by: by[c].sort(key=lambda x:x[0])
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
WARM=30; MAXH=120
g_trig=0; h_trig=0; both=0; tot=0; days_g=[]; days_h=[]
for code,bars in by.items():
    c=np.array([b[4] for b in bars]);h=np.array([b[2] for b in bars]);l=np.array([b[3] for b in bars]);v=np.array([b[5] for b in bars])
    n=len(bars)
    if n<180: continue
    prevc=np.roll(c,1); prevc[0]=c[0]
    tr=np.maximum(h-l,np.maximum(np.abs(h-prevc),np.abs(l-prevc)))
    ma_tr13=sma(tr,13); ref=np.roll(ma_tr13,1); ref[0]=np.nan
    xa73=np.roll(c,1)-ref
    golden=np.full(n,np.nan)
    for j in range(11,n):
        seg=xa73[max(0,j-11):j+1]
        if not np.all(np.isnan(seg)): golden[j]=np.nanmax(seg)
    hold=ema(c,20)-2*sma(tr,14)
    for i in range(WARM,n-3):
        if c[i]<round(c[i-1]*1.10,2)-0.001: continue
        if i>=2 and c[i-1]>=round(c[i-2]*1.10,2)-0.001: continue
        vr=v[i]/v[i-1] if v[i-1] else 0
        if not (1.5<=vr<=4): continue
        tot+=1; end=min(i+1+MAXH,n-1)
        gi=None; hi=None
        for j in range(i+1,end+1):
            if gi is None and not np.isnan(golden[j]) and c[j]<golden[j]: gi=j-i
            if hi is None and not np.isnan(hold[j]) and c[j]<hold[j]: hi=j-i
            if gi and hi: break
        if gi: g_trig+=1; days_g.append(gi)
        if hi: h_trig+=1; days_h.append(hi)
        if gi and hi: both+=1
print(f"总信号: {tot}")
print(f"  黄金线触发: {g_trig} ({g_trig/tot*100:.1f}%)  中位天数 {np.median(days_g):.0f}")
print(f"  持股线触发: {h_trig} ({h_trig/tot*100:.1f}%)  中位天数 {np.median(days_h) if days_h else 0:.0f}")
print(f"  两线都触发: {both} ({both/tot*100:.1f}%)")
print(f"\n→ 持股线触发率 {h_trig/tot*100:.1f}%，'分批'方案的另一半仓位绝大多数从未卖出")
