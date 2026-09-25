# -*- coding: utf-8 -*-
"""按「回测机制 v1.0」回测《股票交易高手大模型》的两条量化主张。

命题A：「充分演绎后少追高」——短期(60日)涨幅越大，追涨买入的远期期望越差？
       （源自《趋势股被套的量化应对》：启动>20交易日 + 顶部>=2 + 涨幅>70% = 充分演绎）
命题B：「线破股亡」——以"收盘跌破MA5"离场，是否优于"固定持有20日"？
       （源自胡布斯18条速查卡：破分时均线无法修复→离场；日线近似用MA5）

铁律遵循：DataFeed 自动方向校验(0)、特征只用<=t(1)、simulate 止损优先(2)、
          扣成本0.15%(3)、R归一化(4)、分档单调性(5)、样本门槛300(6)、时间切分(7)。
数据：data_bt_sample.json（沪深主板 400 只 × 800 根日线，2023-06-08~2026-09-22，前复权）
"""
import sys
sys.path.insert(0, "quant_scripts")
from btframework import DataFeed, atr_w, ma, prev_high, simulate, stats, fmt, HEADER

DATA = "data/bt_sample.json"
MAXH = 20
COST = 0.0015

feed = DataFeed(DATA, min_bars=300)
print(f"有效股票数(>=300根): {len(feed.codes())}  方向修正: {getattr(feed,'normalized','?')} 只")


def bucket(r):
    if r < 0: return "1 涨幅<0%"
    if r < 0.2: return "2 涨幅 0~20%"
    if r < 0.4: return "3 涨幅20~40%"
    if r < 0.7: return "4 涨幅40~70%"
    return "5 涨幅>70%"


def scan(fd, n_ret=60, filt=False, stop_atr=2.0, tgt="T20", tag=""):
    from collections import defaultdict
    acc = defaultdict(list)
    for code in fd.codes():
        rows = fd.bars(code)
        closes = [r[2] for r in rows]
        N = len(rows)
        for t in range(max(250, n_ret + 5), N - MAXH - 1):
            C = closes[t]
            if C <= 0.3:
                continue
            if filt:
                m = ma(closes, t, 120); mp = ma(closes, t - 20, 120)
                if not m or not mp or C <= m or m <= mp:
                    continue
            a = atr_w(rows, t, 14)
            if not a:
                continue
            stop = C - stop_atr * a
            if stop <= 0:
                continue
            if tgt == "T20":
                target = prev_high(rows, t, 20)
            elif tgt == "T60":
                target = prev_high(rows, t, 60)
            elif tgt == "F10":
                target = C * 1.10
            else:
                target = None
            r60 = C / closes[t - n_ret] - 1
            ret, why = simulate(rows, t, stop, target, MAXH, COST)
            if ret is None:
                continue
            acc[bucket(r60)].append((ret, (C - stop) / C))
    print(f"\n===== {tag}  (n_ret={n_ret}, month_filter={filt}, stop={stop_atr}ATR, target={tgt}) =====")
    print(HEADER)
    for k in sorted(acc):
        print(fmt(k, stats(acc[k])))
    return acc


def simulate_ma5(rows, t, stop, target, maxh=MAXH, cost=COST):
    """命题B：加入 收盘跌破MA5 即离场（保守：当日收盘出）。"""
    C = rows[t][2]
    if C <= 0:
        return None, "无效价"
    closes = [r[2] for r in rows]
    end = min(t + maxh, len(rows) - 1)
    for k in range(t + 1, end + 1):
        lo, hi = rows[k][4], rows[k][3]
        if stop is not None and lo <= stop:
            ex, why = stop, "止损"; break
        if target is not None and hi >= target:
            ex, why = target, "目标"; break
        if k >= 4:
            m5 = sum(closes[k - 4:k + 1]) / 5
            if closes[k] < m5:
                ex, why = closes[k], "破MA5"; break
    else:
        ex, why = rows[end][2], "到期"
    return (ex - C) / C - cost, why


def scan_exit(fd, use_ma5=False, filt=False, tgt="T20"):
    from collections import defaultdict
    acc = defaultdict(list)
    for code in fd.codes():
        rows = fd.bars(code)
        closes = [r[2] for r in rows]
        N = len(rows)
        for t in range(250, N - MAXH - 1):
            C = closes[t]
            if C <= 0.3:
                continue
            if filt:
                m = ma(closes, t, 120); mp = ma(closes, t - 20, 120)
                if not m or not mp or C <= m or m <= mp:
                    continue
            a = atr_w(rows, t, 14)
            if not a:
                continue
            stop = C - 2 * a
            if stop <= 0:
                continue
            target = prev_high(rows, t, 20) if tgt == "T20" else (C * 1.10 if tgt == "F10" else prev_high(rows, t, 60))
            if use_ma5:
                ret, why = simulate_ma5(rows, t, stop, target)
            else:
                ret, why = simulate(rows, t, stop, target, MAXH, COST)
            if ret is None:
                continue
            acc["all"].append((ret, (C - stop) / C))
    return acc


print("\n\n############ 命题A：60日涨幅分档 × 追涨20日 ############")
scan(feed, 60, False, 2.0, "T20", "A1 全样本(无趋势过滤)")
scan(feed, 60, True, 2.0, "T20", "A2 月线多头过滤")

print("\n\n############ 命题A 样本外（时间前半段/后半段）############")
for lo, hi, nm in [(0.0, 0.5, "前段(早/2023-06~2024-12)"), (0.5, 1.0, "后段(近/2024-12~2026-09)")]:
    sub = feed.slice_time(lo, hi)
    print(f"\n--- {nm} 股票数={len(sub.codes())} ---")
    scan(sub, 60, False, 2.0, "T20", f"A3-{nm}")

print("\n\n############ 命题B：离场规则对比（无过滤）############")
for use_ma5 in [False, True]:
    for tgt in ["T20", "F10"]:
        acc = scan_exit(feed, use_ma5, False, tgt)
        print(f"{'破MA5离场' if use_ma5 else '固定持有 '}  target={tgt}: {fmt('all', stats(acc['all']))}")

print("\n\n############ 命题B 样本外 ############")
for lo, hi, nm in [(0.0, 0.5, "前段"), (0.5, 1.0, "后段")]:
    sub = feed.slice_time(lo, hi)
    for use_ma5 in [False, True]:
        acc = scan_exit(sub, use_ma5, False, "T20")
        print(f"[{nm}] {'破MA5' if use_ma5 else '持有 '}: {fmt('all', stats(acc['all']))}")
