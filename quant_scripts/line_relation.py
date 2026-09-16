#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证黄金线与持股线的位置关系（倍量柱信号点抽样）"""
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
above=0; below=0; equal=0; samples=[]
for code,bars in list(by.items())[:800]:
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
    for i in range(30,n-3):
        if c[i]<round(c[i-1]*1.10,2)-0.001: continue
        if i>=2 and c[i-1]>=round(c[i-2]*1.10,2)-0.001: continue
        vr=v[i]/v[i-1] if v[i-1] else 0
        if not (1.5<=vr<=4): continue
        hd = hold[i]
        if np.isnan(golden[i]) or np.isnan(hold[i]): continue
        rel=golden[i]/hold[i]-1
        if rel>0.005: above+=1
        elif rel<-0.005: below+=1
        else: equal+=1
        if len(samples)<8: samples.append((code,round(golden[i],2),round(hold[i],2),round(rel*100,1)))
print("倍量柱信号点：黄金线 / 持股线 位置关系")
print(f"  黄金线在上(>持股线): {above}  ({above/(above+below+equal)*100:.1f}%)")
print(f"  黄金线在下(<持股线): {below}  ({below/(above+below+equal)*100:.1f}%)")
print(f"  基本重合: {equal}  ({equal/(above+below+equal)*100:.1f}%)")
print("\n样例 (code, 黄金线, 持股线, 差值%):")
for s in samples: print("  ", s)
