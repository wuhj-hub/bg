#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日线底背离 × 30分钟底背离 组合回测（全主板）
==============================================
信号矩阵：
  A. 日线翻红（基准）
  B. 日线翻红 + 日线底背离（前20日）
  C. 日线翻红 + 日线底背离（前40日）
  D. B + 30m底背离确认（信号日前2日~当日的30m窗口）
  E. C + 30m底背离确认
  F. 30m底背离单独（对照：分钟底背离是否独立有效）
  G. 日线底背离+30m底背离（不要求当日翻红——双底背离共振左侧信号）
持有：3/5/10日
"""
import os, glob, json

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


def has_divergence(macd, closes, j, lookback):
    """j之前lookback窗口：MACD两个局部低点，价格新低但MACD抬高=底背离"""
    s, c = macd[max(0, j - lookback):j], closes[max(0, j - lookback):j]
    if len(s) < 5:
        return False
    lows = [i for i in range(1, len(s) - 1) if s[i] <= s[i - 1] and s[i] <= s[i + 1]]
    if len(lows) < 2:
        return False
    l1, l2 = lows[-2], lows[-1]
    return c[l2] < c[l1] and s[l2] > s[l1]


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
    files = glob.glob(os.path.join(DATA_DIR, "*_D.csv"))
    print(f"全主板日线{len(files)}只 | 日线底背离×30m底背离回测\n")

    H = [3, 5, 10]
    buckets = {k: {h: [] for h in H} for k in "ABCDEFG"}
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
        m30c = m30 if m30 else None

        for i in range(2, n):
            is_red = dm[i] > 0 and dm[i - 1] <= 0  # 日线翻红
            d_div20 = has_divergence(dm, dcloses, i, 20)
            d_div40 = has_divergence(dm, dcloses, i, 40)
            # 30m底背离：信号日前2日~当日窗口（i*8-16 .. i*8+8）
            m_div = False
            if m30m:
                s0, e0 = max(0, i * 8 - 16), min(len(m30m), i * 8 + 8)
                if e0 - s0 >= 10:
                    m_div = has_divergence(m30m, m30c, e0 - 1, e0 - s0)
            for h in H:
                if i + h >= n:
                    continue
                ret = (dcloses[i + h] - dcloses[i]) / dcloses[i] * 100
                if is_red:
                    buckets["A"][h].append(ret)
                    if d_div20:
                        buckets["B"][h].append(ret)
                        if m_div:
                            buckets["D"][h].append(ret)
                    if d_div40:
                        buckets["C"][h].append(ret)
                        if m_div:
                            buckets["E"][h].append(ret)
                if m_div:
                    buckets["F"][h].append(ret)
                    if d_div40:
                        buckets["G"][h].append(ret)
        n_done += 1
        if n_done % 500 == 0:
            print(f"  进度 {n_done}/{len(files)}", flush=True)

    names = {
        "A": "日线翻红(基准)",
        "B": "翻红+日线底背离20日",
        "C": "翻红+日线底背离40日",
        "D": "B+30m底背离确认",
        "E": "C+30m底背离确认",
        "F": "30m底背离单独",
        "G": "日线底背离+30m底背离(左侧)",
    }
    print(f"\n{'信号':<22}{'持':<4}{'样本':>7}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>7}{'最差':>8}")
    print("-" * 76)
    for k in "ABCDEFG":
        for h in H:
            s = stat(buckets[k][h])
            if s:
                print(f"{names[k]:<22}{h:<4}{s['n']:>7}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%"
                      f"{s['med']:>+8.2f}%{s['pl_ratio']:>7.2f}{s['worst']:>+8.2f}%")

    with open(os.path.join(DATA_DIR, "bt_divergence.json"), "w", encoding="utf-8") as f:
        json.dump({k: {h: stat(v) for h, v in m.items()} for k, m in buckets.items()},
                  f, ensure_ascii=False, indent=1, default=str)
    print("\n✅ 已保存 bt_divergence.json")


if __name__ == "__main__":
    main()
