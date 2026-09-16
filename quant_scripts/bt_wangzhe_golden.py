#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""王者倍量柱 · 黄金线 / 持股线 退出回测（2026-09-16）

定义（已从技能库确认）：
  黄金线 = HHV(REF(C,1) - REF(MA(TR,13),1), 12)   —— 出自「腰缠万贯」主图
          TR = MAX(H-L, ABS(H-REF(C,1)), ABS(L-REF(C,1)))
          原文用法：周线顶背离后收盘 < 黄金线 → 离场；这里测【日线收盘 < 黄金线】
  持股线 = EMA(C,20) - 2*ATR(14)                  —— 猛兽派 TR持股线（动态支撑）
  ATR(14) 用 MA(TR,14)

入场：T 日（倍量柱当天）收盘；退出由线驱动，不设固定天数（120日上限）
对照：跌破MA5 / C6 / T10
"""
import csv, json, os
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
OUT = "/sandbox/workspace/zxz_bt/outputs"
WARM = 30; MAXH = 120

by = defaultdict(list)
for r in csv.DictReader(open(DATA, encoding="utf-8")):
    try:
        by[r["code"]].append((r["date"], float(r["open"]), float(r["high"]),
                              float(r["low"]), float(r["close"]), float(r["volume"])))
    except (ValueError, KeyError):
        continue
for c in by:
    by[c].sort(key=lambda x: x[0])


def clean(bars):
    o = np.array([b[1] for b in bars]); h = np.array([b[2] for b in bars])
    l = np.array([b[3] for b in bars]); c = np.array([b[4] for b in bars])
    v = np.array([b[5] for b in bars])
    bad = (c <= 0.3) | (v <= 0)
    if bad.any():
        k = ~bad
        o, h, l, c, v = o[k], h[k], l[k], c[k], v[k]
        bars = [b for b, kk in zip(bars, k) if kk]
    return bars, o, h, l, c, v


def ema(a, n):
    out = np.full(len(a), np.nan)
    if len(a) < n: return out
    out[n - 1] = a[:n].mean()
    k = 2 / (n + 1)
    for i in range(n, len(a)):
        out[i] = a[i] * k + out[i - 1] * (1 - k)
    return out


def sma(a, n):
    out = np.full(len(a), np.nan)
    for i in range(n - 1, len(a)):
        out[i] = a[i - n + 1:i + 1].mean()
    return out


res = {k: [] for k in ("GOLD_D", "HOLD_L", "GOLD_OR_HOLD", "MA5", "C6", "T10")}
cnt = 0

for code, bars in by.items():
    bars, o, h, l, c, v = clean(bars)
    n = len(bars)
    if n < 180:
        continue
    # --- 指标 ---
    prevc = np.roll(c, 1); prevc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prevc), np.abs(l - prevc)))
    ma_tr13 = sma(tr, 13)
    ref_ma_tr = np.roll(ma_tr13, 1); ref_ma_tr[0] = np.nan
    xa73 = np.roll(c, 1) - ref_ma_tr
    golden = np.full(n, np.nan)
    for j in range(11, n):
        seg = xa73[max(0, j - 11):j + 1]
        if not np.all(np.isnan(seg)):
            golden[j] = np.nanmax(seg)
    ema20 = ema(c, 20)
    atr14 = sma(tr, 14)
    holdline = ema20 - 2 * atr14
    ma5 = sma(c, 5)

    for i in range(WARM, n - 3):
        if c[i] < round(c[i - 1] * 1.10, 2) - 0.001: continue
        if i >= 2 and c[i - 1] >= round(c[i - 2] * 1.10, 2) - 0.001: continue
        vr = v[i] / v[i - 1] if v[i - 1] else 0
        if not (1.5 <= vr <= 4): continue
        cnt += 1
        d0 = bars[i][0]; entry = c[i]
        end = min(i + 1 + MAXH, n - 1)
        peak = entry; armed = False; hit = {k: False for k in res}
        for j in range(i + 1, end + 1):
            r_ = c[j] / entry - 1; peak = max(peak, h[j])
            if not hit["GOLD_D"] and not np.isnan(golden[j]) and c[j] < golden[j]:
                res["GOLD_D"].append((d0, r_, j - i)); hit["GOLD_D"] = True
            if not hit["HOLD_L"] and not np.isnan(holdline[j]) and c[j] < holdline[j]:
                res["HOLD_L"].append((d0, r_, j - i)); hit["HOLD_L"] = True
            if not hit["GOLD_OR_HOLD"] and (
                (not np.isnan(golden[j]) and c[j] < golden[j]) or
                (not np.isnan(holdline[j]) and c[j] < holdline[j])):
                res["GOLD_OR_HOLD"].append((d0, r_, j - i)); hit["GOLD_OR_HOLD"] = True
            if not hit["MA5"] and not np.isnan(ma5[j]) and c[j] < ma5[j]:
                res["MA5"].append((d0, r_, j - i)); hit["MA5"] = True
            if not hit["C6"]:
                if not armed and (peak / entry - 1) >= 0.05: armed = True
                if (not np.isnan(ma5[j]) and c[j] < ma5[j]) or (armed and (peak - c[j]) / peak >= 0.03):
                    res["C6"].append((d0, r_, j - i)); hit["C6"] = True
            if not hit["T10"] and r_ >= 0.10:
                res["T10"].append((d0, 0.10, j - i)); hit["T10"] = True
        for k in res:
            if not hit[k]:
                res[k].append((d0, c[end] / entry - 1, MAXH))

NAMES = {"GOLD_D": "日线黄金线（收盘跌破）", "HOLD_L": "持股线 EMA20-2ATR",
         "GOLD_OR_HOLD": "黄金线 或 持股线（先到）", "MA5": "跌破MA5", "C6": "C6 跌破MA5或+5%回撤3%", "T10": "T10 +10%止盈"}
print(f"信号数: {cnt}")
print(f"\n{'规则':<26}{'平均':>10}{'中位':>10}{'胜率':>8}{'持有':>7}{'扣0.2%':>10}{'年化':>9}")
print("-" * 80)
out = []
for k in ("GOLD_D", "HOLD_L", "GOLD_OR_HOLD", "MA5", "C6", "T10"):
    r = res[k]
    if not r: continue
    rets = np.array([x[1] for x in r]); dys = np.array([x[2] for x in r])
    net = np.mean(rets) - 0.002
    ann = (1 + net) ** (240 / max(np.mean(dys), 1)) - 1
    print(f"{NAMES[k]:<26}{np.mean(rets)*100:>+9.2f}%{np.median(rets)*100:>+9.2f}%{(rets>0).mean()*100:>7.1f}%"
          f"{np.mean(dys):>7.1f}{net*100:>+9.2f}%{ann*100:>+8.1f}%")
    out.append({"rule": k, "name": NAMES[k], "n": len(rets), "avg": float(np.mean(rets)),
                "median": float(np.median(rets)), "win": float((rets > 0).mean()),
                "days": float(np.mean(dys)), "net": float(net), "annual": float(ann)})
json.dump({"signals": cnt, "rules": out}, open(f"{OUT}/wangzhe_golden_bt.json", "w"), ensure_ascii=False, indent=2, default=float)
print("\n✅ 结果已存 outputs/wangzhe_golden_bt.json")
