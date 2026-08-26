#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
30m底背离信号优化筛选回测（全主板，信号日买入持10日线日）
==========================================================
基准：30m底背离单独（+1.88%/53.6%/1.77，22213样本）
优化筛选矩阵：
  A. ×日线MACD红柱环境
  B. ×日线MACD绿柱环境
  C. ×周线红柱环境
  D. ×周线绿柱环境
  E. ×日线翻红后3日内（回调后底背离确认）
  F. ×底背离深度（30m窗口MACD低点≤-3，超跌）
  G. ×F+日线绿柱（超跌+逆势）
  H. ×E+D（回踩确认+周线绿柱）
  I. ×A+F（红柱环境+超跌）
  J. 底背离后30m再次放大（右侧确认，非纯左侧）
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


def divergence_info(macd, closes, j, lookback):
    """检测底背离，返回 (是否, 窗口内MACD低点深度)"""
    s, c = macd[max(0, j - lookback):j], closes[max(0, j - lookback):j]
    if len(s) < 5:
        return False, 0
    lows = [i for i in range(1, len(s) - 1) if s[i] <= s[i - 1] and s[i] <= s[i + 1]]
    if len(lows) < 2:
        return False, 0
    l1, l2 = lows[-2], lows[-1]
    if c[l2] < c[l1] and s[l2] > s[l1]:
        return True, min(s)
    return False, 0


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
    HOLD = 10
    print(f"全主板{len(files)}只 | 30m底背离优化（持{HOLD}日线日）\n")

    buckets = {k: [] for k in ["基准","A","B","C","D","E","F","G","H","I","J"]}
    n_done = 0
    for fp in files:
        code = os.path.basename(fp).split("_")[0]
        dcloses = load_klines(code, "D")
        if not dcloses:
            continue
        dm = calc_macd(dcloses)
        n = len(dcloses)
        wc = load_klines(code, "W")
        wm = calc_macd(wc) if wc else None
        m30 = load_klines(code, "m30")
        m30m = calc_macd(m30) if m30 else None

        for i in range(2, n):
            if i + HOLD >= n:
                continue
            ret = (dcloses[i + HOLD] - dcloses[i]) / dcloses[i] * 100
            m_div, m_depth = False, 0
            if m30m:
                s0, e0 = max(0, i * 8 - 16), min(len(m30m), i * 8 + 8)
                if e0 - s0 >= 10:
                    m_div, m_depth = divergence_info(m30m, m30, e0 - 1, e0 - s0)
            if not m_div:
                continue
            d_red = dm[i] > 0
            d_green = dm[i] < 0
            w_red = wm[i // 5] > 0 if wm and i // 5 < len(wm) else False
            w_green = wm[i // 5] < 0 if wm and i // 5 < len(wm) else False
            # 日线翻红后3日内
            red_recent = any(dm[k] > 0 and dm[k - 1] <= 0 for k in range(max(2, i - 3), i + 1))
            deep = m_depth <= -3.0
            # 30m右侧确认：底背离后MACD回升（当前MACD>窗口内低点+回升）
            right_confirm = m30m[e0 - 1] > m30m[e0 - 2] and m30m[e0 - 1] > 0

            buckets["基准"].append(ret)
            if d_red: buckets["A"].append(ret)
            if d_green: buckets["B"].append(ret)
            if w_red: buckets["C"].append(ret)
            if w_green: buckets["D"].append(ret)
            if red_recent: buckets["E"].append(ret)
            if deep: buckets["F"].append(ret)
            if deep and d_green: buckets["G"].append(ret)
            if red_recent and w_green: buckets["H"].append(ret)
            if d_red and deep: buckets["I"].append(ret)
            if right_confirm: buckets["J"].append(ret)
        n_done += 1
        if n_done % 500 == 0:
            print(f"  进度 {n_done}/{len(files)}", flush=True)

    names = {
        "基准": "30m底背离(基准)", "A": "×日线红柱", "B": "×日线绿柱",
        "C": "×周线红柱", "D": "×周线绿柱", "E": "×翻红后3日内",
        "F": "×深度≤-3", "G": "×深度+日绿", "H": "×回踩+周绿",
        "I": "×日红+深度", "J": "×30m右侧确认",
    }
    print(f"\n{'组合':<16}{'样本':>8}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>7}{'最差':>8}")
    print("-" * 72)
    for k in ["基准","A","B","C","D","E","F","G","H","I","J"]:
        s = stat(buckets[k])
        if s:
            print(f"{names[k]:<16}{s['n']:>8}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%{s['med']:>+8.2f}%"
                  f"{s['pl_ratio']:>7.2f}{s['worst']:>+8.2f}%")
        else:
            print(f"{names[k]:<16}{'样本不足':>12}")

    with open(os.path.join(DATA_DIR, "bt_30m_div_opt.json"), "w", encoding="utf-8") as f:
        json.dump({names[k]: stat(v) for k, v in buckets.items()}, f, ensure_ascii=False, indent=1)
    print("\n✅ 已保存 bt_30m_div_opt.json")


if __name__ == "__main__":
    main()
