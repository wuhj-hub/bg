#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""均线退出 + 目标止盈 组合测试（2026-09-16）—— 先到先出"""
import csv, json, os
from collections import defaultdict
import numpy as np
DATA="/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
OUT="/sandbox/workspace/zxz_bt/outputs"
WARM=25; MAXH=120
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
COMBOS={
 "C1 跌破MA5或+10%":{"ma":5,"tgt":0.10},
 "C2 跌破MA5或+20%":{"ma":5,"tgt":0.20},
 "C3 跌破MA5或+30%":{"ma":5,"tgt":0.30},
 "C4 跌破MA10或+10%":{"ma":10,"tgt":0.10},
 "C5 死叉MA10或+10%":{"cross":True,"tgt":0.10},
 "C6 跌破MA5或≥+5%后回撤3%":{"ma":5,"trail":0.03,"eng":0.05},
 "C7 跌破MA5(+15%后改用回撤5%)":{"ma":5,"trail":0.05,"eng":0.15},
}
res={k:[] for k in COMBOS}
cnt=0
for code,bars in by.items():
    bars,o,h,l,c,v=clean(bars);n=len(bars)
    if n<150: continue
    ma={}
    for p in (5,10):
        a=np.full(n,np.nan)
        for j in range(p-1,n): a[j]=c[j-p+1:j+1].mean()
        ma[p]=a
    for i in range(WARM,n-3):
        if c[i] < round(c[i-1]*1.10,2)-0.001: continue
        if i>=2 and c[i-1] >= round(c[i-2]*1.10,2)-0.001: continue
        vr=v[i]/v[i-1] if v[i-1] else 0
        if not (1.5<=vr<=4): continue
        cnt+=1; d0=bars[i][0]; entry=c[i]; end=min(i+1+MAXH,n-1)
        for k,cfg in COMBOS.items():
            peak=entry; armed=False; done=False
            for j in range(i+1,end+1):
                r_=c[j]/entry-1; peak=max(peak,h[j])
                if cfg.get("tgt") and r_>=cfg["tgt"]:
                    res[k].append((d0,r_,j-i)); done=True; break
                if cfg.get("cross"):
                    if (not np.isnan(ma[10][j]) and not np.isnan(ma[5][j]) and not np.isnan(ma[10][j-1]) and not np.isnan(ma[5][j-1])
                        and ma[5][j-1]>=ma[10][j-1] and ma[5][j]<ma[10][j]):
                        res[k].append((d0,r_,j-i)); done=True; break
                if cfg.get("trail"):
                    if not armed and (peak/entry-1)>=cfg["eng"]: armed=True
                    if armed and (peak-c[j])/peak>=cfg["trail"]:
                        res[k].append((d0,r_,j-i)); done=True; break
                if cfg.get("ma") and not np.isnan(ma[cfg["ma"]][j]) and c[j]<ma[cfg["ma"]][j]:
                    res[k].append((d0,r_,j-i)); done=True; break
            if not done: res[k].append((d0,c[end]/entry-1,MAXH))
base={}
for hh in (5,10,20,30,50,60):
    t,n2=0.0,0
    for code,bars in by.items():
        bars,o,h,l,c,v=clean(bars);nn=len(bars)
        for j in range(WARM,nn-hh):
            if c[j]>0: t+=c[j+hh]/c[j]-1; n2+=1
    base[hh]=t/n2 if n2 else 0
print(f"信号数: {cnt}")
print(f"\n{'组合':<30}{'平均':>10}{'中位':>10}{'胜率':>8}{'持有':>7}{'年化':>9}")
print("-"*76)
out=[]
for k,r in res.items():
    if not r: continue
    rets=np.array([x[1] for x in r]); dys=np.array([x[2] for x in r])
    ann=(1+np.mean(rets))**(240/max(np.mean(dys),1))-1
    print(f"{k:<30}{np.mean(rets)*100:>+9.2f}%{np.median(rets)*100:>+9.2f}%{(rets>0).mean()*100:>7.1f}%{np.mean(dys):>7.1f}{ann*100:>+8.1f}%")
    out.append({"name":k,"n":len(rets),"avg":float(np.mean(rets)),"median":float(np.median(rets)),
                "win":float((rets>0).mean()),"days":float(np.mean(dys)),"annual":float(ann)})
json.dump({"signals":cnt,"combos":out}, open(f"{OUT}/wangzhe_combo_bt.json","w"), ensure_ascii=False, indent=2, default=float)
print("\n✅ 结果已存 outputs/wangzhe_combo_bt.json")
