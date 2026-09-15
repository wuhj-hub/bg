#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘中监控 vs 王者倍量柱 —— 信号有效性对比回测（2026-09-15）

盘中监控信号（intraday_monitor.py 实际判据）：
  A 突破MA20：现价 > MA20 且 昨收 ≤ MA20（首次上穿，缺量能确认）
  B 大涨：当日涨幅 ≥ 8%
王者倍量柱（caige_pool.detect_wangzhe 正版，因无流通股本数据省略「换手>5%」）：
  涨停(T-3) + 量比1.5~4 + 后3日收盘>涨停日收盘 + 后2日量递减
  + 后3日最高涨幅<9% + MA60向上 + 3日均量<涨停日量

方法：信号日收盘入场，持有 5/10/20 个交易日；与「全样本同期平均收益」作基准比较。
数据：data/kline_daily_vol.csv（同花顺前复权，3120 只，2019-09 起）
"""
import csv, json, os, sys
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
HOLD = [5, 10, 20]

# 盘中监控的观察池（intraday_monitor.py：CORE_STOCKS + WATCHLIST 35 只行业龙头）
WATCH_POOL = {"sh600797", "sz000839", "sh600863",  # CORE_STOCKS（持仓）
              "sh601398", "sh600030", "sh601318", "sh600519", "sh600887", "sh600276",
              "sh603259", "sh600196", "sz002594", "sz002475", "sz000725", "sz002371",
              "sz000333", "sh601899", "sh600900", "sz000063", "sh601728", "sh600487",
              "sh601857", "sh601088", "sh600585", "sh600760", "sh600879", "sz002714",
              "sh600309", "sz002027", "sh601888", "sh600019", "sh603019", "sz002129",
              "sh601012", "sz000002", "sz002352", "sh600031"}


def load():
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
    return by


def main():
    by = load()
    print(f"[INFO] 标的 {len(by)} 只", flush=True)

    # 全样本基线：每个「日期→该日之后 H 日收益」的平均（用于剔除系统性涨跌）
    base = {h: defaultdict(lambda: [0.0, 0]) for h in HOLD}   # date -> [Σ收益, 计数]
    sigA, sigB = {h: [] for h in HOLD}, {h: [] for h in HOLD}
    nA = nB = 0
    dates_A, dates_B = defaultdict(int), defaultdict(int)

    for code, bars in by.items():
        n = len(bars)
        if n < 80:
            continue
        close = np.array([b[4] for b in bars])
        high = np.array([b[2] for b in bars])
        vol = np.array([b[5] for b in bars])
        # ⚠️ 数据清洗：前复权早期价格可能为 0/负（除权因子异常），会污染基线（divide by zero → nan）
        if (close <= 0.3).any() or (vol <= 0).any():
            bad = (close <= 0.3) | (vol <= 0)
            keep = ~bad
            close, high, vol = close[keep], high[keep], vol[keep]
            bars = [b for b, k in zip(bars, keep) if k]
            n = len(bars)
            if n < 80:
                continue
        # MA20（含当日）
        ma20 = np.full(n, np.nan)
        for i in range(19, n):
            ma20[i] = close[i - 19:i + 1].mean()
        ma60 = np.full(n, np.nan)
        for i in range(59, n):
            ma60[i] = close[i - 59:i + 1].mean()

        for i in range(60, n):
            # 基线（全样本，每只每天都计一次会过拟合个别股，故按日期聚合后取平均）
            for h in HOLD:
                if i + h < n and close[i] > 0:
                    b_ = base[h][bars[i][0]]
                    b_[0] += close[i + h] / close[i] - 1
                    b_[1] += 1

            # 信号A：上穿 MA20（仅在监控池内）
            if code in WATCH_POOL and not np.isnan(ma20[i]) and close[i] > ma20[i] and close[i - 1] <= ma20[i - 1]:
                nA += 1
                dates_A[bars[i][0]] += 1
                for h in HOLD:
                    if i + h < n:
                        sigA[h].append((bars[i][0], close[i + h] / close[i] - 1))

            # 信号B：王者倍量柱（正版近似，省略换手）
            t = i - 3
            if t >= 5:
                limit_price = round(close[t - 1] * 1.10, 2)
                if close[t] >= limit_price - 0.001:
                    vr = vol[t] / vol[t - 1] if vol[t - 1] else 0
                    if 1.5 <= vr <= 4:
                        if min(close[t + 1], close[t + 2], close[t + 3]) > close[t]:
                            if vol[t + 3] < vol[t + 2] < vol[t + 1]:
                                if max(high[t + 1], high[t + 2], high[t + 3]) / close[t] - 1 < 0.09:
                                    if not np.isnan(ma60[i]) and ma60[i] >= ma60[i - 1]:
                                        if (vol[t + 1] + vol[t + 2] + vol[t + 3]) / 3 < vol[t]:
                                            nB += 1
                                            dates_B[bars[i][0]] += 1
                                            for h in HOLD:
                                                if i + h < n:
                                                    sigB[h].append((bars[i][0], close[i + h] / close[i] - 1))
        if len(by) and len(sigB[5]) and len(bars) % 500 == 0:
            pass

    base_avg = {h: (np.mean([v[0] / v[1] for v in base[h].values() if v[1]]) if base[h] else 0)
                for h in HOLD}

    def stat(sig, h):
        if not sig:
            return None
        byd = defaultdict(list)
        for d, r in sig:
            byd[d].append(r)
        # 按日聚合取均值 → 再对日求均值（防同日多信号放大）
        daily = np.array([np.mean(v) for v in byd.values()])
        return {"n": len(sig), "days": len(daily),
                "mean": float(daily.mean() * 100), "median": float(np.median(daily) * 100),
                "win": float((daily > 0).mean() * 100),
                "excess": float((daily.mean() - base_avg[h]) * 100)}

    print("\n" + "=" * 78)
    _allb = sorted(base[5].keys())
    print(f"回测区间: {_allb[0] if _allb else '?'} ~ {_allb[-1] if _allb else '?'} | 全样本基线: "
          + " / ".join(f"{h}日 {base_avg[h]*100:+.2f}%" for h in HOLD))
    print("=" * 78)
    for name, sig, cnt in (("A 盘中监控·上穿MA20（监控池）", sigA, nA),
                           ("B 王者倍量柱（全主板·正版近似）", sigB, nB)):
        print(f"\n【{name}】信号数 {cnt}")
        if cnt == 0:
            print("  （无信号）")
            continue
        print(f"  {'持有':<5}{'按日均值':>10}{'中位':>9}{'胜率':>8}{'超额':>10}{'独立日':>8}")
        for h in HOLD:
            s = stat(sig[h], h)
            if s:
                print(f"  {h:<5}{s['mean']:>+9.2f}%{s['median']:>+8.2f}%{s['win']:>7.1f}%{s['excess']:>+9.2f}%{s['days']:>8}")
    out = {"baseline": base_avg,
           "A": {h: stat(sigA[h], h) for h in HOLD},
           "B": {h: stat(sigB[h], h) for h in HOLD},
           "counts": {"A": nA, "B": nB},
           "days": {"A": dict(dates_A), "B": dict(dates_B)}}
    json.dump(out, open("/sandbox/workspace/zxz_bt/outputs/bt_intraday_vs_wangzhe.json", "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n[OK] /sandbox/workspace/zxz_bt/outputs/bt_intraday_vs_wangzhe.json")


if __name__ == "__main__":
    main()
