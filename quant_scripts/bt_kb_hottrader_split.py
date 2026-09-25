# -*- coding: utf-8 -*-
"""命题C/D 的时间切分样本外（铁律7）：前段/后段分别统计。"""
import sys, statistics as st
sys.path.insert(0, "quant_scripts")
from btframework import DataFeed, atr_w, prev_high, simulate, stats, fmt, HEADER
from collections import defaultdict

feed = DataFeed("data/bt_full.json", min_bars=300)
MAXH, COST = 20, 0.0015


def run_C(fd, tag):
    codes = fd.codes(); bars = {c: fd.bars(c) for c in codes}
    idx = {c: {r[0]: i for i, r in enumerate(bars[c])} for c in codes}
    axis = sorted({r[0] for c in codes for r in bars[c]})
    acc = defaultdict(list)
    for d in axis:
        scored = []
        for c in codes:
            t = idx[c].get(d)
            if t is None or t < 10: continue
            rows = bars[c]; C = rows[t][2]; C10 = rows[t - 10][2]
            if C <= 0.3 or C10 <= 0: continue
            scored.append((C / C10 - 1, c, t))
        scored.sort(key=lambda x: -x[0])
        if len(scored) < 50: continue
        for rank, (r10, c, t) in enumerate(scored):
            rows = bars[c]; a = atr_w(rows, t, 14)
            if not a: continue
            stop = rows[t][2] - 2 * a
            if stop <= 0: continue
            ret, why = simulate(rows, t, stop, prev_high(rows, t, 20), MAXH, COST)
            if ret is None: continue
            risk = (rows[t][2] - stop) / rows[t][2]
            b = "1 狩猎池R1-30" if rank < 30 else ("2 R31-100" if rank < 100 else ("3 R101-300" if rank < 300 else ("4 R301-1000" if rank < 1000 else "5 R1001+")))
            acc[b].append((ret, risk))
    print(f"\n== 命题C 样本外 {tag} ==")
    print(HEADER)
    for k in sorted(acc): print(fmt(k, stats(acc[k])))


def run_D(fd, tag):
    groups = defaultdict(list)
    for c in fd.codes():
        rows = fd.bars(c); closes = [r[2] for r in rows]; N = len(rows)
        for t in range(60, N - 21):
            o, cl, h, l = rows[t][1], rows[t][2], rows[t][3], rows[t][4]
            if cl <= 0.3: continue
            up = (h - cl) / cl; bullish = cl > o
            f1 = closes[t + 1] / cl - 1; f5 = closes[t + 5] / cl - 1; f20 = closes[t + 20] / cl - 1
            if bullish and up >= 0.02: groups["D1 长上影+收阳"].append((f1, f5, f20))
            if bullish: groups["D4 基线收阳"].append((f1, f5, f20))

    def es(g):
        n = len(g); m = lambda i: st.mean([x[i] for x in g]) * 100
        w = lambda i: sum(1 for x in g if x[i] > 0) / n * 100
        return f"n={n:>7} 次日{m(0):+.3f}%/胜{w(0):.1f}%  5日{m(1):+.3f}%/胜{w(1):.1f}%  20日{m(2):+.3f}%/胜{w(2):.1f}%"
    print(f"\n== 命题D 样本外 {tag} ==")
    for k in sorted(groups): print(f"{k:<16} {es(groups[k])}")


for lo, hi, nm in [(0.0, 0.5, "前段"), (0.5, 1.0, "后段")]:
    sub = feed.slice_time(lo, hi)
    run_C(sub, nm)
    run_D(sub, nm)
