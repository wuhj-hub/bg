#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反转数值2B · 沪深300 级别×组合 系统回测
========================================
单级别：周线/日线 翻红 vs 2B（已确认：日线2B持10日最优）
组合级别考察：
  A. 日线2B基准（持10日）
  B. 日线2B × 30m确认（信号日30m MACD翻红/放大）
  C. 日线2B × 5m确认（信号日5m MACD翻红）
  D. 日线2B × 周线绿柱 × 30m确认（逆势选强+分钟确认）
  E. 日线2B × 周线翻红（周线主仓+日线2B）
  F. 日线翻红 × 2B动能门槛（漏斗：翻红∩前期强动能，无回调要求）
  G. 周线2B × 日线2B（双级2B共振）
  H. 日线2B × 周线绿柱（对照：逆势选强基准+2.27%）
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


def detect_2b_at(macd, i, lookback=40, threshold=2.0):
    """返回 RED/YELLOW/None（不要求事件）"""
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
    return "RED" if (macd[i] > 0 and macd[i] > macd[i - 1]) else "YELLOW"


def is_2b_event(macd, i):
    """2B事件：RED且回调后首次放大拐点"""
    return detect_2b_at(macd, i) == "RED" and macd[i] > macd[i - 1] and macd[i - 1] <= macd[i - 2]


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
    pool = [(ln.strip().split(",")[0], "") for ln in open(os.path.join(BASE, "hs300.csv"), encoding="utf-8")]
    HOLD = 10  # 日线持有10日
    print(f"沪深300: {len(pool)}只 | 组合级别回测（日线持有{HOLD}日）\n")

    results = {k: [] for k in "ABCDEFGH"}
    for code, _ in pool:
        dc = load_klines(code, "D")
        if not dc:
            continue
        dm = calc_macd(dc)
        n = len(dc)
        wc = load_klines(code, "W")
        wm = calc_macd(wc) if wc else None
        m30 = load_klines(code, "m30")
        m30m = calc_macd(m30) if m30 else None
        m5 = load_klines(code, "m5")
        m5m = calc_macd(m5) if m5 else None

        for i in range(2, n):
            if i + HOLD >= n:
                continue
            ret = (dc[i + HOLD] - dc[i]) / dc[i] * 100
            wi = min(len(wm) - 1, i // 5) if wm else None
            # 30m/5m确认：信号日对应时段是否有MACD翻红
            m30_red = False
            if m30m:
                for k in range(i * 8, min(i * 8 + 8, len(m30m))):
                    if m30m[k] > 0 and m30m[k - 1] <= 0:
                        m30_red = True
                        break
            m5_red = False
            if m5m:
                for k in range(i * 48, min(i * 48 + 48, len(m5m))):
                    if m5m[k] > 0 and m5m[k - 1] <= 0:
                        m5_red = True
                        break

            # A: 日线2B事件（基准）
            if is_2b_event(dm, i):
                results["A"].append(ret)
                # B: +30m确认
                if m30_red:
                    results["B"].append(ret)
                # C: +5m确认
                if m5_red:
                    results["C"].append(ret)
                # D: +周线绿柱 +30m确认
                if wm and wm[wi] < 0 and m30_red:
                    results["D"].append(ret)
                # E: +周线翻红
                if wm and wm[wi] > 0 and wm[wi - 1] <= 0:
                    results["E"].append(ret)
                # G: 周线2B × 日线2B（双级共振）
                if wm and is_2b_event(wm, wi):
                    results["G"].append(ret)
                # H: +周线绿柱
                if wm and wm[wi] < 0:
                    results["H"].append(ret)
            # F: 日线翻红 × 2B动能门槛（前期强动能，漏斗简化）
            if dm[i] > 0 and dm[i - 1] <= 0:
                seg = dm[max(0, i - 40):i]
                green = [m for m in seg if m < 0]
                red_peak = max([m for m in seg if m > 0], default=0)
                if green and (red_peak > 2 * 0.618 * abs(min(green)) or red_peak * 1.236 >= 2.0):
                    results["F"].append(ret)

    names = {
        "A": "日线2B（基准）",
        "B": "日线2B × 30m翻红确认",
        "C": "日线2B × 5m翻红确认",
        "D": "日线2B × 周线绿柱 × 30m确认",
        "E": "日线2B × 周线翻红",
        "F": "日线翻红 ∩ 2B动能门槛（无回调要求）",
        "G": "周线2B × 日线2B（双级共振）",
        "H": "日线2B × 周线绿柱（逆势选强）",
    }
    print(f"{'组合':<28}{'样本':>7}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>7}{'最差':>8}")
    print("-" * 80)
    for k in "ABCDEFGH":
        s = stat(results[k])
        if s:
            print(f"{names[k]:<28}{s['n']:>7}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%{s['med']:>+8.2f}%"
                  f"{s['pl_ratio']:>7.2f}{s['worst']:>+8.2f}%")
        else:
            print(f"{names[k]:<28}{'样本不足':>12}")

    with open(os.path.join(DATA_DIR, "bt_2b_combo.json"), "w", encoding="utf-8") as f:
        json.dump({k: stat(v) for k, v in results.items()}, f, ensure_ascii=False, indent=1)
    print("\n✅ 已保存 bt_2b_combo.json")


if __name__ == "__main__":
    main()
