#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反转数值 · 2B强动能回调再启动 回测
====================================
沪深300 × 周/日/30m/10m/5m 五级别
信号：RED=2B再启动(①②③全满足) / YELLOW=2B回调中(①②)
对比基准：纯MACD翻红（反转数值负转正）
回测：信号日收盘买入 → 持有N根收盘卖出（未计手续费）
数据：outputs/reversal_bt_data/ 缓存（W/D: p[2]close, m*: p[4]close）
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
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    return [(d - e) * 2 for d, e in zip(dif, dea)]


def detect_2b_at(macd, i, lookback=40, threshold=2.0):
    """检测第i根是否为2B形态，返回 'RED'/'YELLOW'/None"""
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
    x3_line = 2 * 0.618 * x2
    if not (red_peak > x3_line or red_peak * 1.236 >= threshold):
        return None
    peak_idx = seg.index(red_peak)
    after = seg[peak_idx + 1:]
    pullback_low = min(after) if after else macd[i]
    if not (pullback_low > -x2):
        return None
    if macd[i] > 0 and macd[i] > macd[i - 1]:
        return "RED"
    return "YELLOW"


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
    pool = [(ln.strip().split(",")[0], ln.strip().split(",")[1])
            for ln in open(os.path.join(BASE, "hs300.csv"), encoding="utf-8")]
    print(f"沪深300: {len(pool)}只 | 2B信号回测（阈值≥2.0，窗口40）\n")

    levels = [
        ("周线", "W", [1, 2, 4]),
        ("日线", "D", [1, 3, 5, 10]),
        ("30分钟", "m30", [8, 16, 32]),
        ("10分钟", "m10", [12, 24, 48]),
        ("5分钟", "m5", [24, 48, 96]),
    ]
    report = {}
    for label, tag, holds in levels:
        print(f"【{label}】")
        buckets = {"RED": {h: [] for h in holds}, "YELLOW": {h: [] for h in holds},
                   "翻红": {h: [] for h in holds}}
        for code, name in pool:
            closes = load_klines(code, tag)
            if not closes:
                continue
            macd = calc_macd(closes)
            n = len(closes)
            for i in range(2, n):
                # 基准：纯MACD翻红
                if macd[i] > 0 and macd[i - 1] <= 0:
                    for h in holds:
                        if i + h < n:
                            buckets["翻红"][h].append((closes[i + h] - closes[i]) / closes[i] * 100)
                # 2B信号（事件化：仅回调后首次放大拐点触发，避免信号重叠）
                lvl = detect_2b_at(macd, i)
                if lvl == "RED":
                    # 事件确认：当前为回调后首次放大拐点（MACD上穿前值且前值是局部低点）
                    is_event = (macd[i] > macd[i - 1] and macd[i - 1] <= macd[i - 2])
                    if not is_event:
                        lvl = None
                if lvl:
                    for h in holds:
                        if i + h < n:
                            buckets[lvl][h].append((closes[i + h] - closes[i]) / closes[i] * 100)
        print(f"  {'信号':<8}{'持有':<6}{'样本':>7}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>7}{'最差':>8}")
        for sig in ("RED", "YELLOW", "翻红"):
            for h in holds:
                s = stat(buckets[sig][h])
                if s:
                    print(f"  {sig:<8}{h:<6}{s['n']:>7}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%"
                          f"{s['med']:>+8.2f}%{s['pl_ratio']:>7.2f}{s['worst']:>+8.2f}%")
        report[label] = {sig: {h: stat(v) for h, v in holds_map.items()}
                         for sig, holds_map in buckets.items()}
        print()

    with open(os.path.join(DATA_DIR, "bt_2b_results.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print("✅ 已保存 bt_2b_results.json")


if __name__ == "__main__":
    main()
