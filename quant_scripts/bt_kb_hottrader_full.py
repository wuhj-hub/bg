# -*- coding: utf-8 -*-
"""全市场版回测：重跑命题A/B，新增命题C(狩猎池截面动量)、D(强势且分歧长上影)。
口径同回测机制 v1.0：扣成本0.15%、保守成交、R归一化、分档看单调、时间切分样本外。
数据：data_full.json（沪深主板 3029 只 × 800 根日线，前复权，2023-06~2026-09-24）
"""
import sys, statistics as st
sys.path.insert(0, "quant_scripts")
from btframework import DataFeed, atr_w, ma, prev_high, simulate, stats, fmt, HEADER
from collections import defaultdict

DATA = "data/bt_full.json"
MAXH, COST = 20, 0.0015
feed = DataFeed(DATA, min_bars=300)
print(f"有效股票(>=300根): {len(feed.codes())} | 方向修正: {feed.normalized} 只")


def bucket(r):
    if r < 0: return "1 涨幅<0%"
    if r < 0.2: return "2 涨幅 0~20%"
    if r < 0.4: return "3 涨幅20~40%"
    if r < 0.7: return "4 涨幅40~70%"
    return "5 涨幅>70%"


def scan(fd, n_ret=60, filt=False, stop_atr=2.0, tgt="T20", tag=""):
    acc = defaultdict(list)
    for code in fd.codes():
        rows = fd.bars(code); closes = [r[2] for r in rows]; N = len(rows)
        for t in range(max(250, n_ret + 5), N - MAXH - 1):
            C = closes[t]
            if C <= 0.3: continue
            if filt:
                m = ma(closes, t, 120); mp = ma(closes, t - 20, 120)
                if not m or not mp or C <= m or m <= mp: continue
            a = atr_w(rows, t, 14)
            if not a: continue
            stop = C - stop_atr * a
            if stop <= 0: continue
            target = prev_high(rows, t, 20) if tgt == "T20" else (prev_high(rows, t, 60) if tgt == "T60" else C * 1.10)
            ret, why = simulate(rows, t, stop, target, MAXH, COST)
            if ret is None: continue
            acc[bucket(C / closes[t - n_ret] - 1)].append((ret, (C - stop) / C))
    print(f"\n===== {tag} (n_ret={n_ret}, filt={filt}, stop={stop_atr}ATR, tgt={tgt}) =====")
    print(HEADER)
    for k in sorted(acc): print(fmt(k, stats(acc[k])))
    return acc


def simulate_ma5(rows, t, stop, target, maxh=MAXH, cost=COST):
    C = rows[t][2]
    if C <= 0: return None, "无效价"
    closes = [r[2] for r in rows]; end = min(t + maxh, len(rows) - 1)
    for k in range(t + 1, end + 1):
        lo, hi = rows[k][4], rows[k][3]
        if stop is not None and lo <= stop: ex, why = stop, "止损"; break
        if target is not None and hi >= target: ex, why = target, "目标"; break
        if k >= 4 and closes[k] < sum(closes[k - 4:k + 1]) / 5: ex, why = closes[k], "破MA5"; break
    else: ex, why = rows[end][2], "到期"
    return (ex - C) / C - cost, why


def scan_exit(fd, use_ma5=False, filt=False, tgt="T20"):
    acc = defaultdict(list)
    for code in fd.codes():
        rows = fd.bars(code); closes = [r[2] for r in rows]; N = len(rows)
        for t in range(250, N - MAXH - 1):
            C = closes[t]
            if C <= 0.3: continue
            if filt:
                m = ma(closes, t, 120); mp = ma(closes, t - 20, 120)
                if not m or not mp or C <= m or m <= mp: continue
            a = atr_w(rows, t, 14)
            if not a: continue
            stop = C - 2 * a
            if stop <= 0: continue
            target = prev_high(rows, t, 20) if tgt == "T20" else (C * 1.10 if tgt == "F10" else prev_high(rows, t, 60))
            ret, why = (simulate_ma5(rows, t, stop, target) if use_ma5 else simulate(rows, t, stop, target, MAXH, COST))
            if ret is None: continue
            acc["all"].append((ret, (C - stop) / C))
    return acc


# ══════════ A ══════════
print("\n\n############ 命题A（全市场）：60日涨幅分档 × 追涨20日 ############")
scan(feed, 60, False, 2.0, "T20", "A1 全样本(无过滤)")
scan(feed, 60, True, 2.0, "T20", "A2 月线多头过滤")
for lo, hi, nm in [(0.0, 0.5, "前段(早)"), (0.5, 1.0, "后段(近)")]:
    sub = feed.slice_time(lo, hi)
    scan(sub, 60, False, 2.0, "T20", f"A3-{nm}(股票{len(sub.codes())})")

# ══════════ B ══════════
print("\n\n############ 命题B（全市场）：破MA5离场 vs 固定持有 ############")
for tgt in ["T20", "F10"]:
    for use in [False, True]:
        acc = scan_exit(feed, use, False, tgt)
        print(f"{'破MA5' if use else '持有 '} tgt={tgt}: {fmt('all', stats(acc['all']))}")
for lo, hi, nm in [(0.0, 0.5, "前段"), (0.5, 1.0, "后段")]:
    sub = feed.slice_time(lo, hi)
    for use in [False, True]:
        acc = scan_exit(sub, use, False, "T20")
        print(f"[{nm}] {'破MA5' if use else '持有 '}: {fmt('all', stats(acc['all']))}")

# ══════════ C 狩猎池截面动量 ══════════
print("\n\n############ 命题C（新增）：10日涨幅截面排名分档 × 追涨20日 ############")
codes = feed.codes()
bars = {c: feed.bars(c) for c in codes}
idx = {c: {r[0]: i for i, r in enumerate(bars[c])} for c in codes}
axis = sorted({r[0] for c in codes for r in bars[c]})
accC = defaultdict(list)
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
        if rank < 30: b = "1 狩猎池 R1-30"
        elif rank < 100: b = "2 R31-100"
        elif rank < 300: b = "3 R101-300"
        elif rank < 1000: b = "4 R301-1000"
        else: b = "5 R1001+"
        accC[b].append((ret, risk))
print(HEADER)
for k in sorted(accC): print(fmt(k, stats(accC[k])))

# ══════════ D 强势且分歧（长上影+收阳）事件研究 ══════════
print("\n\n############ 命题D（新增）：长上影+收阳(强势且分歧) 后续表现 ############")
groups = defaultdict(list)
for c in codes:
    rows = bars[c]; closes = [r[2] for r in rows]; N = len(rows)
    for t in range(60, N - 21):
        o, cl, h, l = rows[t][1], rows[t][2], rows[t][3], rows[t][4]
        if cl <= 0.3: continue
        up = (h - cl) / cl
        bullish = cl > o
        s10 = cl / closes[t - 10] - 1
        f1 = closes[t + 1] / cl - 1; f5 = closes[t + 5] / cl - 1; f20 = closes[t + 20] / cl - 1
        if bullish and up >= 0.02:
            groups["D1 长上影>=2%+收阳"].append((f1, f5, f20, up))
            if s10 > 0: groups["D2 D1且10日涨幅>0"].append((f1, f5, f20, up))
            if up >= 0.03: groups["D3 长上影>=3%+收阳"].append((f1, f5, f20, up))
        if bullish: groups["D4 基线:收阳"].append((f1, f5, f20, up))
        groups["D5 基线:全体"].append((f1, f5, f20, up))


def es(g):
    n = len(g)
    m = lambda i: st.mean([x[i] for x in g]) * 100
    w = lambda i: sum(1 for x in g if x[i] > 0) / n * 100
    return f"n={n:>7}  次日:均{m(0):+6.3f}%/胜{w(0):4.1f}%   5日:均{m(1):+6.3f}%/胜{w(1):4.1f}%   20日:均{m(2):+6.3f}%/胜{w(2):4.1f}%"


for k in sorted(groups):
    print(f"{k:<26} {es(groups[k])}")
