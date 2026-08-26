#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全主板 2B+30m确认 对照回测（成分股 vs 非成分股）
==================================================
信号：日线2B事件 + 当日30m翻红确认 → 持10日
数据：reversal_bt_data/ 全主板缓存（日线=westock 260根，30m=腾讯320根≈2个月窗口）
"""
import os, glob

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


def load_klines(code, tag):
    fp = os.path.join(DATA_DIR, f"{code}_{tag}.csv")
    if not os.path.exists(fp):
        return None
    closes = []
    is_min = tag.startswith("m")
    for ln in open(fp, encoding="utf-8"):
        p = ln.strip().split(",")
        if len(p) >= 5:
            try:
                closes.append(float(p[4] if is_min else p[2]))
            except ValueError:
                pass
    return closes if len(closes) >= 40 else None


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
    files = glob.glob(os.path.join(DATA_DIR, "*_D.csv"))
    print(f"日线缓存{len(files)}只 | 30m缓存{len(glob.glob(os.path.join(DATA_DIR, '*_m30.csv')))}只\n")

    groups = {"成分股+30m确认": [], "非成分股+30m确认": [], "全主板+30m确认": [], "全主板无确认(对照)": []}
    n_done = 0
    for fp in files:
        code = os.path.basename(fp).split("_")[0]
        dcloses = load_klines(code, "D")
        if not dcloses:
            continue
        dm = calc_macd(dcloses)
        n = len(dcloses)
        m30 = load_klines(code, "m30")
        m30m = calc_macd(m30) if m30 else None
        for i in range(2, n):
            if i + 10 >= n:
                continue
            if not detect_2b_event(dm, dcloses, i):
                continue
            ret = (dcloses[i + 10] - dcloses[i]) / dcloses[i] * 100
            groups["全主板无确认(对照)"].append(ret)
            m30_red = False
            if m30m:
                for k in range(i * 8, min(i * 8 + 8, len(m30m))):
                    if k >= 1 and m30m[k] > 0 and m30m[k - 1] <= 0:
                        m30_red = True
                        break
            if m30_red:
                groups["全主板+30m确认"].append(ret)
                if code in hs300:
                    groups["成分股+30m确认"].append(ret)
                else:
                    groups["非成分股+30m确认"].append(ret)
        n_done += 1
        if n_done % 500 == 0:
            print(f"  进度 {n_done}/{len(files)}", flush=True)

    print(f"\n{'分组':<20}{'样本':>7}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>7}{'最差':>8}")
    print("-" * 72)
    for g, rets in groups.items():
        s = stat(rets)
        if s:
            print(f"{g:<20}{s['n']:>7}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%{s['med']:>+8.2f}%"
                  f"{s['pl_ratio']:>7.2f}{s['worst']:>+8.2f}%")
        else:
            print(f"{g:<20}{'样本不足':>12}")
    # 30m确认增益
    a = stat(groups["全主板无确认(对照)"])
    b = stat(groups["全主板+30m确认"])
    if a and b:
        print(f"\n📊 30m确认增益(全主板): {a['avg']:+.2f}% → {b['avg']:+.2f}% (增益{b['avg']-a['avg']:+.2f}pct)")


if __name__ == "__main__":
    main()
