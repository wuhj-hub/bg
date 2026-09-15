#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""王者观察级·过滤条件精扫（2026-09-15）

基础信号 B0 = 涨停 + 量比 1.5~4（T 日收盘入场） —— 5日超额 +0.61%/胜率59.1%
逐项叠加过滤器，找最优盘中可判定的判据：
  F1 首板（前一日未涨停）        F2 突破前20日高点
  F3 MA60向上                    F4 均线多头(MA5>MA20)
  F5 非ST                        F6 流通盘/价格区间(10元以下? 高价?)
输出 t 统计量，判断超额是否显著。
"""
import csv, json
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
HOLD = [5, 10, 20]


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
    KEYS = ["B0", "F1", "F2", "F3", "F4", "F2+F3", "F1+F2", "F1+F2+F3", "P10", "P3"]
    res = {k: {h: [] for h in HOLD} for k in KEYS}
    cnt = defaultdict(int)

    for code, bars in by.items():
        close = np.array([b[4] for b in bars]); high = np.array([b[2] for b in bars])
        vol = np.array([b[5] for b in bars])
        bad = (close <= 0.3) | (vol <= 0)
        if bad.any():
            keep = ~bad
            bars = [b for b, k in zip(bars, keep) if k]
            close, high, vol = close[keep], high[keep], vol[keep]
        n = len(bars)
        if n < 90:
            continue
        ma5 = np.full(n, np.nan); ma20 = np.full(n, np.nan); ma60 = np.full(n, np.nan)
        for i in range(4, n):
            ma5[i] = close[i - 4:i + 1].mean()
        for i in range(19, n):
            ma20[i] = close[i - 19:i + 1].mean()
        for i in range(59, n):
            ma60[i] = close[i - 59:i + 1].mean()

        for i in range(61, n):
            for h in HOLD:
                if i + h < n and close[i] > 0:
                    b_ = base[h][bars[i][0]]; b_[0] += close[i + h] / close[i] - 1; b_[1] += 1

            t = i
            if t < 25:
                continue
            # 涨停判定（主板10%）
            if close[t] < round(close[t - 1] * 1.10, 2) - 0.001:
                continue
            vr = vol[t] / vol[t - 1] if vol[t - 1] else 0
            if not (1.5 <= vr <= 4):
                continue
            cnt["B0"] += 1
            f1 = close[t - 1] < round(close[t - 2] * 1.10, 2) - 0.001      # 首板
            f2 = close[t] > high[t - 21:t - 1].max()                        # 突破前20日高
            f3 = (not np.isnan(ma60[i])) and ma60[i] >= ma60[i - 1]         # MA60向上
            f4 = (not np.isnan(ma5[i])) and ma5[i] > ma20[i]                # 均线多头
            tags = []
            if f1: tags.append("F1")
            if f2: tags.append("F2")
            if f3: tags.append("F3")
            if f4: tags.append("F4")
            if f2 and f3: tags.append("F2+F3")
            if f1 and f2: tags.append("F1+F2")
            if f1 and f2 and f3: tags.append("F1+F2+F3")
            if close[t] < 10: tags.append("P10")
            if close[t] < 3: tags.append("P3")
            for tg in tags:
                cnt[tg] += 1
                for h in HOLD:
                    if i + h < n:
                        res[tg][h].append((bars[i][0], close[i + h] / close[i] - 1))
        if code.endswith("999999"):
            pass

    base_avg = {h: np.mean([v[0] / v[1] for v in base[h].values() if v[1]]) for h in HOLD}
    _b = sorted(base[5].keys())

    def calc(sig, h):
        if not sig:
            return None
        byd = defaultdict(list)
        for d, r in sig:
            byd[d].append(r)
        daily = np.array([np.mean(v) for v in byd.values()])
        se = daily.std(ddof=1) / np.sqrt(len(daily)) if len(daily) > 1 else 0
        return {"n": len(sig), "days": len(daily), "mean": daily.mean()*100,
                "median": float(np.median(daily))*100, "win": float((daily > 0).mean()*100),
                "excess": (daily.mean() - base_avg[h])*100,
                "t": (daily.mean() - base_avg[h]) / se if se else 0}

    print("=" * 92)
    print(f"区间 {_b[0]} ~ {_b[-1]} | 基准: " + " / ".join(f"{h}日{base_avg[h]*100:+.2f}%" for h in HOLD))
    print("=" * 92)
    print(f"{'过滤':<10}{'n':>8}{'5日超额':>9}{'t':>7}{'胜率':>7}{'中位':>8}"
          f"{'10日超额':>10}{'t':>7}{'20日超额':>10}{'t':>7}")
    out = {}
    for k in KEYS:
        if cnt[k] == 0:
            continue
        line = f"{k:<10}{cnt[k]:>8}"
        row = {}
        for h in HOLD:
            s = calc(res[k][h], h)
            row[h] = s
            if s:
                line += f"{s['excess']:>+8.2f}%{s['t']:>7.1f}"
                if h == 5:
                    line += f"{s['win']:>6.1f}%{s['median']:>+8.2f}%"
            else:
                line += f"{'--':>9}{'--':>7}" + ("      --      --" if h == 5 else "")
        print(line)
        out[k] = row
    json.dump({"baseline": {h: base_avg[h]*100 for h in HOLD}, "counts": dict(cnt), "result": out},
              open("/sandbox/workspace/zxz_bt/outputs/bt_filters.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    print("\n[OK] outputs/bt_filters.json")


if __name__ == "__main__":
    main()
