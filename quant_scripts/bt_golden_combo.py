#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""黄金线/持股线 + 回撤止盈 组合补测（2026-09-16）"""
import csv, json
from collections import defaultdict
import numpy as np
DATA="/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"; OUT="/sandbox/workspace/zxz_bt/outputs"
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
COMBOS={
 "G1 黄金线或+5%回撤3%":{"golden":True,"trail":0.03,"eng":0.05},
 "G2 黄金线或+10%":{"golden":True,"tgt":0.10},
 "G3 黄金线或MA5(先到)":{"golden":True,"ma5":True},
 "G4 持股线或+5%回撤3%":{"hold":True,"trail":0.03,"eng":0.05},
 "G5 黄金线或持股线或回撤3%":{"golden":True,"hold":True,"trail":0.03,"eng":0.05},
}
res={k:[] for k in COMBOS}; cnt=0
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
    holdline=ema(c,20)-2*sma(tr,14); ma5=sma(c,5)
    for i in range(WARM,n-3):
        if c[i]<round(c[i-1]*1.10,2)-0.001: continue
        if i>=2 and c[i-1]>=round(c[i-2]*1.10,2)-0.001: continue
        vr=v[i]/v[i-1] if v[i-1] else 0
        if not (1.5<=vr<=4): continue
        cnt+=1; d0=bars[i][0]; entry=c[i]; end=min(i+1+MAXH,n-1)
        peak=entry; armed=False; hit={k:False for k in COMBOS}
        for j in range(i+1,end+1):
            r_=c[j]/entry-1; peak=max(peak,h[j])
            if not armed and (peak/entry-1)>=0.05: armed=True
            for k,cfg in COMBOS.items():
                if hit[k]: continue
                g=cfg.get("golden") and not np.isnan(golden[j]) and c[j]<golden[j]
                hl=cfg.get("hold") and not np.isnan(holdline[j]) and c[j]<holdline[j]
                m5=cfg.get("ma5") and not np.isnan(ma5[j]) and c[j]<ma5[j]
                tg=cfg.get("tgt") and r_>=cfg["tgt"]
                tr_=cfg.get("trail") and armed and (peak-c[j])/peak>=cfg["trail"]
                if g or hl or m5 or tg or tr_:
                    res[k].append((d0, (0.10 if (cfg.get("tgt") and r_>=cfg["tgt"]) else r_), j-i)); hit[k]=True
        for k in COMBOS:
            if not hit[k]: res[k].append((d0, c[end]/entry-1, MAXH))
print(f"信号数: {cnt}\n{'组合':<30}{'平均':>10}{'中位':>10}{'胜率':>8}{'持有':>7}{'扣0.2%':>10}")
print("-"*76); out=[]
for k,r in res.items():
    if not r: continue
    rets=np.array([x[1] for x in r]); dys=np.array([x[2] for x in r]); net=np.mean(rets)-0.002
    print(f"{k:<30}{np.mean(rets)*100:>+9.2f}%{np.median(rets)*100:>+9.2f}%{(rets>0).mean()*100:>7.1f}%{np.mean(dys):>7.1f}{net*100:>+9.2f}%")
    out.append({"name":k,"avg":float(np.mean(rets)),"median":float(np.median(rets)),"win":float((rets>0).mean()),"days":float(np.mean(dys)),"net":float(net)})
json.dump({"signals":cnt,"combos":out}, open(f"{OUT}/wangzhe_golden_combo.json","w"), ensure_ascii=False, indent=2, default=float)
print("\n✅ 已存 outputs/wangzhe_golden_combo.json")
