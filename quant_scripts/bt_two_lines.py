#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""黄金线 × 持股线 组合方式回测（2026-09-16）

已验证：黄金线在上（99.4%）、持股线在下 → 天然两级防线

组合方式：
  H1 或：跌破黄金线 或 跌破持股线（先到全出）
  H2 且：同时跌破两线才出
  H3 分批：跌破黄金线卖50% + 跌破持股线卖50%
  H4 = G5：黄金线 或 持股线 或 +5%后回撤3%
  H5 分批+回撤：跌破黄金线卖50% 或 +5%后回撤3%卖50%（先到先卖），跌破持股线清剩余
  H6 分批+回撤(优先)：+5%后回撤3%卖50%，跌破黄金线卖剩余50%，跌破持股线兜底清仓
"""
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
res={k:[] for k in ("H1","H2","H3","H4","H5","H6","G4")}
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
    hold=ema(c,20)-2*sma(tr,14); ma5=sma(c,5)
    for i in range(WARM,n-3):
        if c[i]<round(c[i-1]*1.10,2)-0.001: continue
        if i>=2 and c[i-1]>=round(c[i-2]*1.10,2)-0.001: continue
        vr=v[i]/v[i-1] if v[i-1] else 0
        if not (1.5<=vr<=4): continue
        cnt+=1; d0=bars[i][0]; E=c[i]; end=min(i+1+MAXH,n-1)
        peak=E; armed=False
        s={k:None for k in res}       # 已实现收益累计（分批加权用）
        hit={k:False for k in res}
        for j in range(i+1,end+1):
            r_=c[j]/E-1; peak=max(peak,h[j])
            if not armed and (peak/E-1)>=0.05: armed=True
            gb = not np.isnan(golden[j]) and c[j]<golden[j]
            hb = not np.isnan(hold[j]) and c[j]<hold[j]
            tb = armed and (peak-c[j])/peak>=0.03
            if not hit["H1"] and (gb or hb): res["H1"].append((d0,r_,j-i)); hit["H1"]=True
            if not hit["H2"] and gb and hb: res["H2"].append((d0,r_,j-i)); hit["H2"]=True
            if not hit["H4"] and (gb or hb or tb): res["H4"].append((d0,r_,j-i)); hit["H4"]=True
            if not hit["G4"] and (hb or tb): res["G4"].append((d0,r_,j-i)); hit["G4"]=True
            # H3 分批：黄金线卖50% → 持股线卖50%
            if hit["H3"] is False:
                if gb and s["H3"] is None: s["H3"]=0.5*r_
                if hb:
                    half = s["H3"] if s["H3"] is not None else 0.5*r_
                    res["H3"].append((d0, half+0.5*r_, j-i)); hit["H3"]=True
            # H5 分批：黄金线 或 回撤3% 卖50%（先到先卖）→ 持股线清剩余
            if not hit["H5"]:
                if (gb or tb) and s["H5"] is None: s["H5"]=0.5*r_
                if hb:
                    half = s["H5"] if s["H5"] is not None else 0.5*r_
                    res["H5"].append((d0, half+0.5*r_, j-i)); hit["H5"]=True
            # H6 分批：回撤3% 或 黄金线 卖50% → 跌破持股线清剩余
            if not hit["H6"]:
                if (tb or gb) and s["H6"] is None: s["H6"]=0.5*r_
                if hb:
                    half = s["H6"] if s["H6"] is not None else 0.5*r_
                    res["H6"].append((d0, half+0.5*r_, j-i)); hit["H6"]=True
        for k in res:
            if not hit[k]: res[k].append((d0, c[end]/E-1, MAXH))
NAMES={"H1":"或：破黄金线或持股线(全出)","H2":"且：两线同时破才出","H3":"分批：黄金线50%→持股线50%",
       "H4":"黄金线 或 持股线 或 回撤3%","H5":"分批：黄金线/回撤3%卖50%→持股线清",
       "H6":"分批：回撤3%或黄金线卖50%→持股线清","G4":"G4 持股线 或 回撤3%（基准）"}
print(f"信号数: {cnt}")
print(f"\n{'方案':<34}{'平均':>10}{'中位':>10}{'胜率':>8}{'持有':>7}{'扣0.2%':>10}{'年化':>9}")
print("-"*90)
out=[]
for k in ("H1","H2","H3","H4","H5","H6","G4"):
    r=res[k]
    if not r: continue
    rets=np.array([x[1] for x in r]); dys=np.array([x[2] for x in r]); net=np.mean(rets)-0.002
    ann=(1+net)**(240/max(np.mean(dys),1))-1
    print(f"{NAMES[k]:<34}{np.mean(rets)*100:>+9.2f}%{np.median(rets)*100:>+9.2f}%{(rets>0).mean()*100:>7.1f}%{np.mean(dys):>7.1f}{net*100:>+9.2f}%{ann*100:>+8.1f}%")
    out.append({"rule":k,"name":NAMES[k],"avg":float(np.mean(rets)),"median":float(np.median(rets)),
                "win":float((rets>0).mean()),"days":float(np.mean(dys)),"net":float(net),"annual":float(ann)})
json.dump({"signals":cnt,"rules":out}, open(f"{OUT}/wangzhe_two_lines.json","w"), ensure_ascii=False, indent=2, default=float)
print("\n✅ 已存 outputs/wangzhe_two_lines.json")
