#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""王者倍量柱 · 均线/死叉类动态退出回测（2026-09-16）

用户要求：不用固定天数止盈止损，改为根据 5日线 / 10日线 / 死叉 等动态规则。

入场：T 日（倍量柱当天）收盘 —— 前测唯一正超额的口径
退出：全部由均线/形态驱动（不设固定持有天数），仅设 120 日上限防无限持有
对比：T10（+10%固定止盈，前测最优）

规则集：
  G1  跌破 MA5（收盘）
  G2  跌破 MA10
  G3  跌破 MA20
  G4  MA5 下穿 MA10（死叉）        ← 用户明确提到
  G5  MA10 下穿 MA20（死叉）
  G6  MA5死叉 或 收盘跌破MA10（先到先出）
  G7  MA5死叉 或 收盘跌破MA20
  G8  跌破 MA5 且 MA5 拐头向下
  G9  MA5死叉 或 跌破MA5（最敏感）
  G10 收盘跌破 MA10 且 MA10 拐头向下
"""
import csv, json, os
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
OUT = "/sandbox/workspace/zxz_bt/outputs"
WARM = 25
MAXH = 120          # 安全上限（防"永不触发"导致无限持有）

by = defaultdict(list)
with open(DATA, encoding="utf-8") as f:
    for r in csv.DictReader(f):
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


def exit_signal(rule, j, ma, c):
    """返回 True 表示第 j 日触发退出"""
    def cross_down(fast, slow):
        return (j >= 1 and not np.isnan(ma[fast][j]) and not np.isnan(ma[slow][j])
                and not np.isnan(ma[fast][j-1]) and not np.isnan(ma[slow][j-1])
                and ma[fast][j-1] >= ma[slow][j-1] and ma[fast][j] < ma[slow][j])
    if rule == "G1":
        return not np.isnan(ma[5][j]) and c[j] < ma[5][j]
    if rule == "G2":
        return not np.isnan(ma[10][j]) and c[j] < ma[10][j]
    if rule == "G3":
        return not np.isnan(ma[20][j]) and c[j] < ma[20][j]
    if rule == "G4":
        return cross_down(5, 10)
    if rule == "G5":
        return cross_down(10, 20)
    if rule == "G6":
        return cross_down(5, 10) or (not np.isnan(ma[10][j]) and c[j] < ma[10][j])
    if rule == "G7":
        return cross_down(5, 10) or (not np.isnan(ma[20][j]) and c[j] < ma[20][j])
    if rule == "G8":
        return (not np.isnan(ma[5][j]) and c[j] < ma[5][j]
                and not np.isnan(ma[5][j-1]) and ma[5][j] < ma[5][j-1])
    if rule == "G9":
        return cross_down(5, 10) or (not np.isnan(ma[5][j]) and c[j] < ma[5][j])
    if rule == "G10":
        return (not np.isnan(ma[10][j]) and c[j] < ma[10][j]
                and not np.isnan(ma[10][j-1]) and ma[10][j] < ma[10][j-1])
    return False


RULES = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10"]
NAMES = {
    "G1": "跌破MA5（收盘）", "G2": "跌破MA10", "G3": "跌破MA20",
    "G4": "MA5死叉MA10", "G5": "MA10死叉MA20",
    "G6": "MA5死叉 或 跌破MA10", "G7": "MA5死叉 或 跌破MA20",
    "G8": "跌破MA5且MA5拐头", "G9": "MA5死叉 或 跌破MA5",
    "G10": "跌破MA10且MA10拐头",
}

res = {k: [] for k in RULES}
res["T10"] = []
cnt = defaultdict(int)

for code, bars in by.items():
    bars, o, h, l, c, v = clean(bars)
    n = len(bars)
    if n < 150:
        continue
    ma = {}
    for p in (5, 10, 20):
        a = np.full(n, np.nan)
        for j in range(p - 1, n):
            a[j] = c[j - p + 1:j + 1].mean()
        ma[p] = a
    for i in range(WARM, n - 3):
        if c[i] < round(c[i - 1] * 1.10, 2) - 0.001:
            continue
        if i >= 2 and c[i - 1] >= round(c[i - 2] * 1.10, 2) - 0.001:
            continue
        vr = v[i] / v[i - 1] if v[i - 1] else 0
        if not (1.5 <= vr <= 4):
            continue
        cnt["sig"] += 1
        d0 = bars[i][0]
        entry = c[i]
        # 均线类：从 T+1 起按规则退出
        end = min(i + 1 + MAXH, n - 1)
        for k in RULES:
            for j in range(i + 1, end + 1):
                if exit_signal(k, j, ma, c):
                    res[k].append((d0, c[j] / entry - 1, j - i))
                    break
            else:
                res[k].append((d0, c[end] / entry - 1, MAXH))   # 120日上限内未触发
        # T10 对比
        done = False
        for j in range(i + 1, end + 1):
            if c[j] / entry - 1 >= 0.10:
                res["T10"].append((d0, 0.10, j - i)); done = True; break
        if not done:
            res["T10"].append((d0, c[end] / entry - 1, MAXH))

# 基准（等权，各持有期）
print(f"信号数: {cnt['sig']}")
# 用"平均持有天数"对应的基准做公平对比
base_cache = {}
def base_for(hh):
    if hh in base_cache: return base_cache[hh]
    tot, n2 = 0.0, 0
    for code, bars in by.items():
        bars, o, h, l, c, v = clean(bars)
        nn = len(bars)
        for j in range(WARM, nn - hh):
            if c[j] > 0:
                tot += c[j + hh] / c[j] - 1; n2 += 1
    base_cache[hh] = tot / n2 if n2 else 0
    return base_cache[hh]

print(f"\n{'规则':<24}{'n':>7}{'平均':>10}{'中位':>10}{'胜率':>8}{'平均持有':>9}{'超额':>10}{'年化':>9}")
print("-" * 92)
out = {"signals": cnt["sig"], "rules": []}
for k in RULES + ["T10"]:
    r = res[k]
    if not r: continue
    rets = np.array([x[1] for x in r])
    dys = np.array([x[2] for x in r])
    med_days = np.median(dys)
    b = base_for(int(max(5, round(med_days))))
    ex = np.mean(rets) - b
    ann = (1 + np.mean(rets)) ** (240 / max(np.mean(dys), 1)) - 1
    lbl = NAMES.get(k, "T10 +10%固定止盈")
    print(f"{lbl:<24}{len(rets):>7}{np.mean(rets)*100:>+9.2f}%{np.median(rets)*100:>+9.2f}%"
          f"{(rets>0).mean()*100:>7.1f}%{np.mean(dys):>9.1f}{(np.mean(rets)-b)*100:>+9.2f}%{ann*100:>+8.1f}%")
    out["rules"].append({"rule": k, "name": lbl, "n": len(rets), "avg": float(np.mean(rets)),
                         "median": float(np.median(rets)), "win": float((rets > 0).mean()),
                         "days_mean": float(np.mean(dys)), "days_median": float(med_days),
                         "excess": float(ex)})
os.makedirs(OUT, exist_ok=True)
json.dump(out, open(f"{OUT}/wangzhe_ma_exit_bt.json", "w"), ensure_ascii=False, indent=2, default=float)
print("✅ 结果已存 outputs/wangzhe_ma_exit_bt.json")
