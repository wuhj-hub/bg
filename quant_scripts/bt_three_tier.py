#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三级减仓组合：黄金线(快线/预警) + 回撤止盈(锁利) + 持股线(慢线/兜底)"""
import csv, json
from collections import defaultdict
import numpy as np
DATA="/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"; OUT="/sandbox/workspace/zxz_bt/outputs"
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
res={k:[] for k in ("T1","T2","T3","T4","G4")}
cnt=0
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
        cnt+=1; d0=bars[i][0]; E=c[i]; end=min(i+1+MAXH,n-1)
        peak=E; armed=False
        acc={k:0.0 for k in res}; left={k:1.0 for k in res}; hit={k:False for k in res}
        for j in range(i+1,end+1):
            r_=c[j]/E-1; peak=max(peak,h[j])
            if not armed and (peak/E-1)>=0.05: armed=True
            gb = not np.isnan(golden[j]) and c[j]<golden[j]
            hb = not np.isnan(hold[j]) and c[j]<hold[j]
            tb = armed and (peak-c[j])/peak>=0.03
            # T1 三级：黄金线卖1/3 → 回撤3%卖1/3 → 持股线清1/3
            if not hit["T1"]:
                if (gb or tb) and left["T1"]>0.67:   acc["T1"]+=1/3*r_; left["T1"]-=1/3
                elif (gb or tb) and left["T1"]>0.34: acc["T1"]+=1/3*r_; left["T1"]-=1/3
                if hb: acc["T1"]+=left["T1"]*r_; res["T1"].append((d0,acc["T1"],j-i)); hit["T1"]=True
            # T2 两级：黄金线卖半 → 回撤3%卖半
            if not hit["T2"]:
                if (gb or tb) and left["T2"]>0.5: acc["T2"]+=0.5*r_; left["T2"]-=0.5
                if tb and left["T2"]<=0.5 and left["T2"]>0:
                    acc["T2"]+=left["T2"]*r_; res["T2"].append((d0,acc["T2"],j-i)); hit["T2"]=True
            # T3 G4 + 黄金线预警减半（跌破黄金线时若无回撤信号，先减半）
            if not hit["T3"]:
                if gb and left["T3"]>0.5 and not armed: acc["T3"]+=0.5*r_; left["T3"]-=0.5
                if (hb or tb) and left["T3"]>0:
                    acc["T3"]+=left["T3"]*r_; res["T3"].append((d0,acc["T3"],j-i)); hit["T3"]=True
            # T4 黄金线卖半 → 持股线清（不含回撤）
            if not hit["T4"]:
                if gb and left["T4"]>0.5: acc["T4"]+=0.5*r_; left["T4"]-=0.5
                if hb and left["T4"]>0: acc["T4"]+=left["T4"]*r_; res["T4"].append((d0,acc["T4"],j-i)); hit["T4"]=True
            if not hit["G4"] and (hb or tb): res["G4"].append((d0,r_,j-i)); hit["G4"]=True
        for k in res:
            if not hit[k]:
                res[k].append((d0, acc[k]+left[k]*(c[end]/E-1), end-i))
NAMES={"T1":"三级:黄金线1/3+回撤3%1/3+持股线清","T2":"两级:黄金线半+回撤3%半","T3":"G4+黄金线预警减半",
       "T4":"黄金线半→持股线清","G4":"G4 持股线或回撤3%（基准）"}
print(f"信号数: {cnt}")
print(f"\n{'方案':<36}{'平均':>10}{'中位':>10}{'胜率':>8}{'持有':>7}{'扣0.2%':>10}")
print("-"*82); out=[]
for k in ("T1","T2","T3","T4","G4"):
    r=res[k]
    if not r: continue
    rets=np.array([x[1] for x in r]); dys=np.array([x[2] for x in r]); net=np.mean(rets)-0.002
    print(f"{NAMES[k]:<36}{np.mean(rets)*100:>+9.2f}%{np.median(rets)*100:>+9.2f}%{(rets>0).mean()*100:>7.1f}%{np.mean(dys):>7.1f}{net*100:>+9.2f}%")
    out.append({"rule":k,"name":NAMES[k],"avg":float(np.mean(rets)),"median":float(np.median(rets)),
                "win":float((rets>0).mean()),"days":float(np.mean(dys)),"net":float(net)})
json.dump({"signals":cnt,"rules":out}, open(f"{OUT}/wangzhe_three_tier.json","w"), ensure_ascii=False, indent=2, default=float)
print("\n✅ 已存 outputs/wangzhe_three_tier.json")
