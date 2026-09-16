#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""王者倍量柱「观察期」介入点回测（2026-09-16）

问题：知识库案例显示倍量柱后有中位 52 天的观察期，但"突破确认"后买入跑输 -7.08%。
      → 那么观察期内该怎么介入才能吃到这段涨幅？

信号：倍量柱 = 首板 + 涨停 + 量比1.5~4（T 日）
买点变体（均持有到 T+60 或最多 60 交易日）：
  E0 T日收盘（原始）
  E1 回踩 MA10 首次触及
  E2 回踩 MA20 首次触及
  E3 T+20 收盘（观察期中段）
  E4 突破 T 日最高价（= 王后突破 TP2）
  E5 回踩 MA5 首次触及
"""
import csv, json
from collections import defaultdict
import numpy as np
DATA="/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
OUT="/sandbox/workspace/zxz_bt/outputs"
WARM=25; MAXH=60

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

res={k:[] for k in ("E0","E1","E2","E3","E4","E5")}
cnt=defaultdict(int)
base={}
for code,bars in by.items():
    bars,o,h,l,c,v=clean(bars); n=len(bars)
    if n<120: continue
    ma={}
    for p in (5,10,20):
        a=np.full(n,np.nan)
        for j in range(p-1,n): a[j]=c[j-p+1:j+1].mean()
        ma[p]=a
    for i in range(WARM,n-70):
        if c[i] < round(c[i-1]*1.10,2)-0.001: continue
        if i>=2 and c[i-1] >= round(c[i-2]*1.10,2)-0.001: continue
        vr=v[i]/v[i-1] if v[i-1] else 0
        if not (1.5<=vr<=4): continue
        cnt["sig"]+=1
        tgt_date=bars[i][0]
        # E0: T收盘
        e0=i; 
        if e0+MAXH<n: res["E0"].append((tgt_date, c[e0+MAXH]/c[e0]-1))
        # E1/E2/E5: 观察期内首次回踩均线（T+1 起，最多 40 日）
        for p,key in ((10,"E1"),(20,"E2"),(5,"E5")):
            for j in range(i+1, min(i+41,n)):
                if not np.isnan(ma[p][j]) and l[j]<=ma[p][j]:
                    if j+MAXH<n: res[key].append((tgt_date, c[j+MAXH]/c[j]-1))
                    break
        # E3: T+20 收盘
        if i+20<n and i+20+MAXH<n: res["E3"].append((tgt_date, c[i+20+MAXH]/c[i+20]-1))
        # E4: 突破 T 日最高价（观察期 40 日内首次）
        for j in range(i+1, min(i+41,n)):
            if c[j] > h[i]:
                if j+MAXH<n: res["E4"].append((tgt_date, c[j+MAXH]/c[j]-1))
                break
    for hh in (60,):
        for j in range(WARM,n-hh):
            if c[j]>0: 
                b_=base.setdefault(hh,[0.0,0]); b_[0]+=c[j+hh]/c[j]-1; b_[1]+=1
base60=base[60][0]/base[60][1]
print(f"信号数: {cnt['sig']} | 基准(60日): {base60*100:+.2f}%")
NAMES={"E0":"T日收盘（原始）","E1":"回踩MA10首次","E2":"回踩MA20首次","E3":"T+20收盘","E4":"突破T日最高（王后突破）","E5":"回踩MA5首次"}
print(f"\n{'买点':<22}{'n':>7}{'平均':>10}{'中位':>10}{'胜率':>8}{'超额':>10}")
print("-"*70)
out={}
for k in ("E0","E1","E2","E3","E4","E5"):
    r=res[k]
    if not r: continue
    rets=np.array([x[1] for x in r])
    ex=np.mean(rets)-base60
    print(f"{NAMES[k]:<22}{len(rets):>7}{np.mean(rets)*100:>+9.2f}%{np.median(rets)*100:>+9.2f}%{(rets>0).mean()*100:>7.1f}%{ex*100:>+9.2f}%")
    out[k]={"name":NAMES[k],"n":len(rets),"avg":float(np.mean(rets)),"median":float(np.median(rets)),
            "win":float((rets>0).mean()),"excess":float(ex)}
json.dump({"base60":base60,"signals":cnt["sig"],"variants":out}, open(f"{OUT}/wangzhe_entry_bt.json","w"), ensure_ascii=False, indent=2, default=float)
print("\n✅ 结果已存 outputs/wangzhe_entry_bt.json")
