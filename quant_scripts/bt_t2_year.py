#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T2 vs G4 年度稳定性"""
import csv
from collections import defaultdict
import numpy as np
DATA="/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
WARM=30; MAXH=180
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
        y=bars[i][0][:4]; E=c[i]; end=min(i+1+MAXH,n-1)
        peak=E; armed=False; hit={"T2":False,"G4":False}
        acc={"T2":0.0,"G4":0.0}; left={"T2":1.0,"G4":1.0}
        for j in range(i+1,end+1):
            r_=c[j]/E-1; peak=max(peak,h[j])
            if not armed and (peak/E-1)>=0.05: armed=True
            gb = not np.isnan(golden[j]) and c[j]<golden[j]
            hb = not np.isnan(hold[j]) and c[j]<hold[j]
            tb = armed and (peak-c[j])/peak>=0.03
            if not hit["T2"]:
                if (gb or tb) and left["T2"]>0.5: acc["T2"]+=0.5*r_; left["T2"]-=0.5
                if tb and left["T2"]<=0.5 and left["T2"]>0:
                    acc["T2"]+=left["T2"]*r_; REC.setdefault("T2",{}).setdefault(y,[]).append(acc["T2"]); hit["T2"]=True
                if hb and left["T2"]>0 and not hit["T2"]:
                    acc["T2"]+=left["T2"]*r_; REC.setdefault("T2",{}).setdefault(y,[]).append(acc["T2"]); hit["T2"]=True
            if not hit["G4"] and (hb or tb):
                REC.setdefault("G4",{}).setdefault(y,[]).append(r_); hit["G4"]=True
        for k in ("T2","G4"):
            if not hit[k]: REC.setdefault(k,{}).setdefault(y,[]).append(acc[k]+left[k]*(c[end]/E-1))
years=sorted(set(y for k in REC for y in REC[k]))
print(f"{'年份':<7}{'T2 平均':>11}{'T2 胜率':>10}{'G4 平均':>11}{'G4 胜率':>10}")
print("-"*50)
for y in years:
    t2=REC["T2"].get(y,[]); g4=REC["G4"].get(y,[])
    f1=f"{np.mean(t2)*100:>+10.2f}%" if t2 else f"{'-':>11}"
    f2=f"{(np.array(t2)>0).mean()*100:>9.1f}%" if t2 else f"{'-':>10}"
    f3=f"{np.mean(g4)*100:>+10.2f}%" if g4 else f"{'-':>11}"
    f4=f"{(np.array(g4)>0).mean()*100:>9.1f}%" if g4 else f"{'-':>10}"
    print(f"{y:<7}{f1}{f2}{f3}{f4}")
print("-"*50)
for k in ("T2","G4"):
    allv=[x for y in REC[k] for x in REC[k][y]]
    print(f"  {k} 合计: 平均{np.mean(allv)*100:+.2f}% 中位{np.median(allv)*100:+.2f}% 胜率{(np.array(allv)>0).mean()*100:.1f}% n={len(allv)}")
