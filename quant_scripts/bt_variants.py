#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变体回测：入场时点与量能确认对信号有效性的影响（2026-09-15）

A  上穿MA20（T收盘入场）          —— 盘中监控现行判据
A2 上穿MA20 + 放量(量比≥1.5)      —— 加量能确认后是否改善
B0 涨停+量比1.5~4（观察级·T收盘）
B1 同上·T+1开盘入场               —— 更贴近"盘中看到后跟进"的真实成本
B2 王者倍量柱确认(T+3)             —— 当前 caige_pool 实际输出
B3 王者倍量柱确认 且 突破涨停日收盘 —— "王者突破"
"""
import csv, json
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
HOLD = [5, 10, 20]
WATCH_POOL = {"sh600797", "sz000839", "sh600863", "sh601398", "sh600030", "sh601318",
              "sh600519", "sh600887", "sh600276", "sh603259", "sh600196", "sz002594",
              "sz002475", "sz000725", "sz002371", "sz000333", "sh601899", "sh600900",
              "sz000063", "sh601728", "sh600487", "sh601857", "sh601088", "sh600585",
              "sh600760", "sh600879", "sz002714", "sh600309", "sz002027", "sh601888",
              "sh600019", "sh603019", "sz002129", "sh601012", "sz000002", "sz002352", "sh600031"}


def main():
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

    base = {h: defaultdict(lambda: [0.0, 0]) for h in HOLD}
    res = {k: {h: [] for h in HOLD} for k in ("A", "A2", "B0", "B1", "B2", "B3")}
    cnt = defaultdict(int)
    ENT = {"A": "close", "A2": "close", "B0": "close", "B1": "open", "B2": "close", "B3": "close"}

    for code, bars in by.items():
        close = np.array([b[4] for b in bars]); high = np.array([b[2] for b in bars])
        low = np.array([b[3] for b in bars]); open_ = np.array([b[1] for b in bars])
        vol = np.array([b[5] for b in bars])
        bad = (close <= 0.3) | (vol <= 0)
        if bad.any():
            keep = ~bad
            bars = [b for b, k in zip(bars, keep) if k]
            close, high, low, open_, vol = close[keep], high[keep], low[keep], open_[keep], vol[keep]
        n = len(bars)
        if n < 80:
            continue
        ma20 = np.full(n, np.nan); ma60 = np.full(n, np.nan)
        for i in range(19, n):
            ma20[i] = close[i - 19:i + 1].mean()
        for i in range(59, n):
            ma60[i] = close[i - 59:i + 1].mean()

        sigs = defaultdict(list)   # (key, i_entry)
        for i in range(61, n):
            for h in HOLD:
                if i + h < n and close[i] > 0:
                    b_ = base[h][bars[i][0]]; b_[0] += close[i + h] / close[i] - 1; b_[1] += 1

            # A / A2：上穿 MA20
            if code in WATCH_POOL and not np.isnan(ma20[i]) and close[i] > ma20[i] and close[i - 1] <= ma20[i - 1]:
                sigs["A"].append(i)
                if vol[i - 1] and vol[i] / vol[i - 1] >= 1.5:
                    sigs["A2"].append(i)

            # 王者倍量柱：涨停日 t=i-3
            t = i - 3
            if t >= 5:
                if close[t] >= round(close[t - 1] * 1.10, 2) - 0.001:
                    vr = vol[t] / vol[t - 1] if vol[t - 1] else 0
                    if 1.5 <= vr <= 4:
                        sigs["B0"].append(t)                       # 观察级：涨停日收盘
                        if t + 1 < n:
                            sigs["B1"].append(t + 1)               # 次日
                        if min(close[t+1], close[t+2], close[t+3]) > close[t] \
                           and vol[t+3] < vol[t+2] < vol[t+1] \
                           and max(high[t+1], high[t+2], high[t+3]) / close[t] - 1 < 0.09 \
                           and not np.isnan(ma60[i]) and ma60[i] >= ma60[i-1] \
                           and (vol[t+1]+vol[t+2]+vol[t+3]) / 3 < vol[t]:
                            sigs["B2"].append(i)                    # 确认日
                            if close[i] > close[t]:                 # 突破涨停日收盘
                                sigs["B3"].append(i)

        for k, idxs in sigs.items():
            for i in idxs:
                cnt[k] += 1
                if ENT[k] == "open" and i < 1:
                    continue
                px0 = open_[i] if ENT[k] == "open" else close[i]
                for h in HOLD:
                    if i + h < n and px0 > 0:
                        res[k][h].append((bars[i][0], close[i + h] / px0 - 1))

    base_avg = {h: np.mean([v[0] / v[1] for v in base[h].values() if v[1]]) for h in HOLD}
    _b = sorted(base[5].keys())
    print("=" * 82)
    print(f"区间 {_b[0]} ~ {_b[-1]} | 基准: " + " / ".join(f"{h}日{base_avg[h]*100:+.2f}%" for h in HOLD))
    print("=" * 82)
    names = {"A": "A  上穿MA20（盘中监控现行·T收盘）", "A2": "A2 上穿MA20+放量≥1.5（T收盘）",
             "B0": "B0 涨停+量比1.5~4 观察级（T收盘）", "B1": "B1 观察级·T+1开盘入场",
             "B2": "B2 王者倍量柱确认（T+3收盘）", "B3": "B3 王者突破：确认+突破涨停日收盘"}
    summary = {}
    for k in ("A", "A2", "B0", "B1", "B2", "B3"):
        print(f"\n【{names[k]}】n={cnt[k]}")
        if cnt[k] == 0:
            print("  （无信号）"); continue
        print(f"  {'持有':<4}{'按日':>9}{'中位':>9}{'胜率':>8}{'超额':>9}{'独立日':>7}")
        summary[k] = {}
        for h in HOLD:
            byd = defaultdict(list)
            for d, r in res[k][h]:
                byd[d].append(r)
            if not byd:
                continue
            daily = np.array([np.mean(v) for v in byd.values()])
            ex = daily.mean() - base_avg[h]
            summary[k][h] = {"mean": daily.mean()*100, "median": float(np.median(daily))*100,
                             "win": float((daily > 0).mean()*100), "excess": ex*100, "days": len(daily)}
            print(f"  {h:<4}{daily.mean()*100:>+8.2f}%{np.median(daily)*100:>+8.2f}%"
                  f"{(daily>0).mean()*100:>7.1f}%{ex*100:>+8.2f}%{len(daily):>7}")
    json.dump({"baseline": {h: base_avg[h]*100 for h in HOLD}, "counts": dict(cnt), "summary": summary},
              open("/sandbox/workspace/zxz_bt/outputs/bt_variants.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    print("\n[OK] outputs/bt_variants.json")


if __name__ == "__main__":
    main()
