#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反转数值 · 周线信号叠加漏斗回测
================================
基础信号A：周线MACD翻红（反转数值由负转正）
叠加层：
  B = 翻红前绿柱持续≥3周（充分回调，避免高位钝化翻红）
  C = 翻红前绿柱最大深度≥3（超跌程度，百分比MACD口径）
  D = 翻红前4周内存在底背离（价格新低但MACD低点抬高）
漏斗: A → A∩B → A∩B∩C → A∩B∩C∩D，持有4周
"""
import os, json

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "outputs", "reversal_bt_data")


def ema(series, n):
    out = [series[0]]
    k = 2 / (n + 1)
    for x in series[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def calc_macd(closes):
    n = len(closes)
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]
    return macd


def has_divergence(macd, closes, j, lookback=4):
    """翻红前lookback周内：MACD两个局部低点，价格新低但MACD抬高=底背离"""
    s, c = macd[max(0, j - lookback):j], closes[max(0, j - lookback):j]
    if len(s) < 3:
        return False
    lows = [i for i in range(1, len(s) - 1) if s[i] <= s[i - 1] and s[i] <= s[i + 1]]
    if len(lows) < 2:
        return False
    l1, l2 = lows[-2], lows[-1]
    return c[l2] < c[l1] and s[l2] > s[l1]


def load_klines(code, tag):
    fp = os.path.join(DATA_DIR, f"{code}_{tag}.csv")
    if not os.path.exists(fp):
        return None
    closes = []
    for ln in open(fp, encoding="utf-8"):
        p = ln.strip().split(",")
        if len(p) >= 5:
            try:
                closes.append(float(p[2]))  # W/D: date,open,close,high,low
            except ValueError:
                pass
    return closes if len(closes) >= 30 else None


def stat(rets):
    if len(rets) < 10:
        return None
    wins = [r for r in rets if r > 0]
    avg = sum(rets) / len(rets)
    pl = sum(r for r in rets if r > 0) / max(1, len(wins))
    ls = abs(sum(r for r in rets if r <= 0) / max(1, len(rets) - len(wins)))
    return {"n": len(rets), "wr": len(wins) / len(rets) * 100, "avg": avg,
            "med": sorted(rets)[len(rets) // 2],
            "pl_ratio": pl / ls if ls > 0 else 99, "worst": min(rets),
            "best": max(rets)}


def main():
    pool = [(ln.strip().split(",")[0], ln.strip().split(",")[1])
            for ln in open(os.path.join(BASE, "hs300.csv"), encoding="utf-8")]
    print(f"沪深300: {len(pool)}只 | 周线信号漏斗回测（持有4周）\n")

    HOLD = 4
    buckets = {"A": [], "B": [], "C": [], "D": [], "E": [], "F": []}
    for code, name in pool:
        wc = load_klines(code, "W")
        if not wc:
            continue
        macd = calc_macd(wc)
        n = len(macd)
        for i in range(2, n):
            if not (macd[i] > 0 and macd[i - 1] <= 0) or i + HOLD >= n:
                continue
            ret = (wc[i + HOLD] - wc[i]) / wc[i] * 100
            # B: 翻红前绿柱持续≥3周
            b = all(m < 0 for m in macd[max(0, i - 3):i]) and (i - 3) >= 0
            # C: 翻红前绿柱最大深度≥3（近4周）
            seg = macd[max(0, i - 4):i]
            c = (min(seg) if seg else 0) <= -3.0
            # D: 底背离（放宽到前12周，覆盖整个回调段）
            d = has_divergence(macd, wc, i, lookback=12)
            buckets["A"].append(ret)
            if b:
                buckets["B"].append(ret)
                if c:
                    buckets["E"].append(ret)
                    if d:
                        buckets["F"].append(ret)
            if c:
                buckets["C"].append(ret)
            if d:
                buckets["D"].append(ret)

    print(f"{'漏斗层级':<28}{'样本':>7}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>7}{'最差':>8}{'最好':>8}")
    print("-" * 88)
    order = [("A 翻红(基准)", "A"), ("B +回调≥3周", "B"), ("C +超跌≥3", "C"),
             ("D +底背离", "D"), ("E +回调+超跌", "E"), ("F 全条件", "F")]
    for label, k in order:
        s = stat(buckets[k])
        if s:
            print(f"{label:<28}{s['n']:>7}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%{s['med']:>+8.2f}%"
                  f"{s['pl_ratio']:>7.2f}{s['worst']:>+8.2f}%{s['best']:>+8.2f}%")
        else:
            print(f"{label:<28}{'样本不足':>12}")

    # 留存率
    base_n = len(buckets["A"])
    print("\n📉 漏斗留存率:")
    for label, k in order[1:]:
        if base_n:
            print(f"  {label}: {len(buckets[k])} ({len(buckets[k])/base_n*100:.1f}%)")

    with open(os.path.join(DATA_DIR, "funnel_results.json"), "w", encoding="utf-8") as f:
        json.dump({k: stat(v) for k, v in buckets.items()}, f, ensure_ascii=False, indent=1)
    print("\n✅ 已保存 funnel_results.json")


if __name__ == "__main__":
    main()
