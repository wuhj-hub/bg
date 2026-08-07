#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全主板 vs 沪深300成分股 · 2B信号对照回测（日线，持10日）
==========================================================
目的：验证幸存者偏差——若非成分股组表现≈成分股组，策略普适；否则成分股回测偏高估。
数据：outputs/reversal_bt_data/*_D.csv（全主板日线缓存）
"""
import os, re, glob

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "outputs", "reversal_bt_data")


def ema(s, n):
    out = [s[0]]; k = 2 / (n + 1)
    for x in s[1:]: out.append(x * k + out[-1] * (1 - k))
    return out


def calc_macd(closes):
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    return [(d - e) * 2 for d, e in zip(dif, dea)]


def detect_2b_event(macd, closes, i, lookback=40, threshold=2.0):
    if i < 30:
        return None
    seg = macd[max(0, i - lookback):i + 1]
    green = [m for m in seg if m < 0]
    if not green:
        return None
    x2 = abs(min(green))
    if x2 <= 0.1:
        return None
    red_peak = max([m for m in seg if m > 0], default=0)
    if not (red_peak > 2 * 0.618 * x2 or red_peak * 1.236 >= threshold):
        return None
    peak_idx = seg.index(red_peak)
    after = seg[peak_idx + 1:]
    pullback_low = min(after) if after else macd[i]
    if not (pullback_low > -x2):
        return None
    if not (macd[i] > 0 and macd[i] > macd[i - 1] and macd[i - 1] <= macd[i - 2]):
        return None
    return True


def load_closes(fp):
    closes = []
    for ln in open(fp, encoding="utf-8"):
        p = ln.strip().split(",")
        if len(p) >= 5:
            try:
                closes.append(float(p[2]))  # date,open,close,high,low
            except ValueError:
                pass
    return closes if len(closes) >= 40 else None


def stat(rets):
    if len(rets) < 10:
        return None
    wins = [r for r in rets if r > 0]
    avg = sum(rets) / len(rets)
    pl = sum(r for r in rets if r > 0) / max(1, len(wins))
    ls = abs(sum(r for r in rets if r <= 0) / max(1, len(rets) - len(wins)))
    return {"n": len(rets), "wr": len(wins) / len(rets) * 100, "avg": avg,
            "med": sorted(rets)[len(rets) // 2],
            "pl_ratio": pl / ls if ls > 0 else 99, "worst": min(rets)}


def main():
    hs300 = set()
    for ln in open(os.path.join(BASE, "hs300.csv"), encoding="utf-8"):
        hs300.add(ln.strip().split(",")[0])
    print(f"沪深300成分股: {len(hs300)}只 | 全主板日线缓存扫描\n")

    groups = {"成分股": [], "非成分股(全主板对照)": [], "全主板合计": []}
    files = glob.glob(os.path.join(DATA_DIR, "*_D.csv"))
    print(f"日线缓存: {len(files)}只")
    for fp in files:
        code = os.path.basename(fp).split("_")[0]
        closes = load_closes(fp)
        if not closes:
            continue
        macd = calc_macd(closes)
        n = len(closes)
        for i in range(2, n):
            if i + 10 >= n:
                continue
            if detect_2b_event(macd, closes, i):
                ret = (closes[i + 10] - closes[i]) / closes[i] * 100
                groups["全主板合计"].append(ret)
                if code in hs300:
                    groups["成分股"].append(ret)
                else:
                    groups["非成分股(全主板对照)"].append(ret)

    print(f"\n{'分组':<22}{'样本':>8}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>7}{'最差':>8}")
    print("-" * 74)
    for g, rets in groups.items():
        s = stat(rets)
        if s:
            print(f"{g:<22}{s['n']:>8}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%{s['med']:>+8.2f}%"
                  f"{s['pl_ratio']:>7.2f}{s['worst']:>+8.2f}%")
    # 偏差判定
    hs = stat(groups["成分股"])
    non = stat(groups["非成分股(全主板对照)"])
    if hs and non:
        diff = hs["avg"] - non["avg"]
        print(f"\n📊 成分股 - 非成分股 平均收益差: {diff:+.2f}个百分点"
              f"（{'存在幸存者偏差↑' if diff > 0.3 else '偏差可控' if abs(diff) <= 0.3 else '非成分股反而更强' if diff < -0.3 else '偏差可控'}）")


if __name__ == "__main__":
    main()
