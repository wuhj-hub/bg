#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最佳策略验证：日线2B + 30m翻红确认（持10日，可选止损）
=========================================================
沪深300成分股 · 策略级回测：
  - 信号：日线2B事件（前期2倍值≥2.0+回调不破位+首次放大） + 当日30m翻红确认
  - 入场：信号日收盘
  - 退出：持有10日 / 止损（收盘跌破2B回调低点，提前退出）
  - 统计：等权逐信号收益、胜率、盈亏比、最大回撤、时段拆分（稳定性）、vs基准
"""
import os, json

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


def load_klines_full(code, tag):
    """返回 (dates, closes, lows)"""
    fp = os.path.join(DATA_DIR, f"{code}_{tag}.csv")
    if not os.path.exists(fp):
        return None
    dates, closes, lows = [], [], []
    is_min = tag.startswith("m")
    for ln in open(fp, encoding="utf-8"):
        p = ln.strip().split(",")
        if len(p) >= 5:
            try:
                dates.append(p[0])
                if is_min:  # date,open,high,low,close
                    closes.append(float(p[4])); lows.append(float(p[3]))
                else:       # date,open,close,high,low
                    closes.append(float(p[2])); lows.append(float(p[4]))
            except ValueError:
                pass
    return (dates, closes, lows) if len(closes) >= 40 else None


def detect_2b_event(macd, closes, i, lookback=40, threshold=2.0):
    """2B事件检测，返回 {stop_low, ...} 或 None"""
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
    # 回调段最低价（止损位）
    seg_start = max(0, i - lookback) + peak_idx
    stop_low = min(closes[seg_start:i + 1])
    return {"stop_low": stop_low, "x2": x2, "fz2_peak": red_peak * 1.236}


def run_strategy(pool, use_stop=True, hold=10):
    """返回信号列表 [(date, code, ret, hold_days, stop_hit)]"""
    trades = []
    for code, _ in pool:
        d = load_klines_full(code, "D")
        if not d:
            continue
        ddates, dcloses, dlows = d
        dm = calc_macd(dcloses)
        n = len(dcloses)
        m30 = load_klines_full(code, "m30")
        m30m = calc_macd(m30[1]) if m30 else None

        for i in range(2, n):
            if i + 1 >= n:
                continue
            det = detect_2b_event(dm, dcloses, i)
            if not det:
                continue
            # 30m确认：当日8根30m中MACD翻红
            m30_red = False
            if m30m:
                for k in range(i * 8, min(i * 8 + 8, len(m30m))):
                    if k >= 1 and m30m[k] > 0 and m30m[k - 1] <= 0:
                        m30_red = True
                        break
            if not m30_red:
                continue
            # 模拟持有：止损或到期退出
            stop_low = det["stop_low"]
            exit_i, stop_hit = None, False
            for h in range(1, hold + 1):
                if i + h >= n:
                    break
                if use_stop and dcloses[i + h] < stop_low:
                    exit_i, stop_hit = i + h, True
                    break
                exit_i = i + h
            if exit_i is None:
                continue
            ret = (dcloses[exit_i] - dcloses[i]) / dcloses[i] * 100
            trades.append({"date": ddates[i], "code": code, "ret": ret,
                           "days": exit_i - i, "stop": stop_hit})
    return trades


def summarize(trades, label):
    if len(trades) < 10:
        print(f"  {label}: 样本不足({len(trades)})")
        return None
    rets = [t["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    avg = sum(rets) / len(rets)
    pl = sum(r for r in rets if r > 0) / max(1, len(wins))
    ls = abs(sum(r for r in rets if r <= 0) / max(1, len(rets) - len(wins)))
    # 最大回撤（等权资金曲线）
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= (1 + r / 100)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
    stops = sum(1 for t in trades if t["stop"])
    print(f"  {label}: n={len(trades)} 胜率{len(wins)/len(rets)*100:.1f}% 平均{avg:+.2f}% "
          f"盈亏比{pl/ls:.2f} 最大回撤{mdd*100:.1f}% 止损触发{stops/len(trades)*100:.0f}% "
          f"平均持有{sum(t['days'] for t in trades)/len(trades):.1f}日 最差{min(rets):+.1f}%")
    return {"n": len(trades), "wr": len(wins)/len(rets)*100, "avg": avg, "pl": pl/ls,
            "mdd": mdd * 100, "stop_rate": stops/len(trades)*100, "worst": min(rets)}


def main():
    pool = [(ln.strip().split(",")[0], "") for ln in open(os.path.join(BASE, "hs300.csv"), encoding="utf-8")]
    print(f"沪深300: {len(pool)}只 | 最佳策略验证：日线2B+30m确认\n")

    # 1. 有止损 vs 无止损
    t_stop = run_strategy(pool, use_stop=True)
    t_no = run_strategy(pool, use_stop=False)
    print("【退出规则对比】")
    summarize(t_stop, "持10日+止损(跌破回调低点)")
    summarize(t_no, "持10日无止损")
    print()

    # 2. 时段拆分（稳定性验证）
    dates = sorted(set(t["date"] for t in t_stop))
    if len(dates) >= 4:
        mid = dates[len(dates) // 2]
        print(f"【时段拆分（分界 {mid}）】")
        half1 = [t for t in t_stop if t["date"] < mid]
        half2 = [t for t in t_stop if t["date"] >= mid]
        summarize(half1, "前半段")
        summarize(half2, "后半段")
        print()

    # 3. 止损触发时间分布（止损信号是否有效）
    stops = [t for t in t_stop if t["stop"]]
    non_stops = [t for t in t_stop if not t["stop"]]
    print("【止损有效性】")
    summarize(stops, "止损退出样本")
    summarize(non_stops, "持有到期样本")
    print()

    # 4. 等权资金曲线概要（月度）
    months = {}
    for t in t_stop:
        m = t["date"][:7]
        months.setdefault(m, []).append(t["ret"])
    print("【月度表现】")
    for m in sorted(months):
        r = months[m]
        wins = sum(1 for x in r if x > 0)
        print(f"  {m}: {len(r)}信号 胜率{wins/len(r)*100:.0f}% 平均{sum(r)/len(r):+.2f}%")
    print()
    print(f"✅ 信号总数: {len(t_stop)} | 跨{len(dates)}个交易日 | 平均每天{len(t_stop)/max(1,len(dates)):.1f}个")


if __name__ == "__main__":
    main()
