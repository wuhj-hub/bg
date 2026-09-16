#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""王者倍量柱 · 退出机制回测 v2（2026-09-16）

v1 发现：统一用 T+1 开盘入场时，所有策略超额均 ≤ +0.40%（信号价值集中在 T 日当天）。
        → v2 增加【T 收盘入场】口径做对比，并细化止盈档位、修正回撤计算。

才哥原文规则（《牛股的迹象：王者倍量柱》+《战法核心精要与操作指南》）：
  · 止损（铁律）：以倍量柱当日最低价为硬止损线，收盘跌破无条件离场
  · 止盈：第一目标=前期小高点；第二目标=倍量柱涨幅×1.5等幅位；分批减仓+移动止盈
  · 口诀：倍量起爆不追高，三日缩量站稳腰；缺口不补更强势，破底即走莫恋战
"""
import csv, json, os
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
OUT = "/sandbox/workspace/zxz_bt/outputs"
MAX_HOLD = 60
WARMUP = 25


def load():
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
    return by


def clean(bars):
    o = np.array([b[1] for b in bars]); h = np.array([b[2] for b in bars])
    l = np.array([b[3] for b in bars]); c = np.array([b[4] for b in bars])
    v = np.array([b[5] for b in bars])
    bad = (c <= 0.3) | (v <= 0)
    if bad.any():
        keep = ~bad
        o, h, l, c, v = o[keep], h[keep], l[keep], c[keep], v[keep]
        bars = [b for b, k in zip(bars, keep) if k]
    return bars, o, h, l, c, v


def simulate(entry, o, h, l, c, i_start, stop_px, prev_high, eng, rules):
    """return (ret, days, reason)"""
    n = len(c)
    maxd = min(MAX_HOLD, n - i_start)
    if maxd < 1 or entry <= 0:
        return None
    ma_p = rules.get("ma")
    ma = None
    if ma_p:
        ma = np.full(n, np.nan)
        for j in range(ma_p - 1, n):
            ma[j] = c[j - ma_p + 1:j + 1].mean()
    trail = rules.get("trail"); tgt = rules.get("target"); fixed = rules.get("hold")
    use_peak_high = rules.get("prev_high")     # 才哥第一目标：前期小高点
    peak = entry; armed = (trail is None)
    for k in range(maxd):
        j = i_start + k
        px = c[j]
        peak = max(peak, h[j])
        r = px / entry - 1
        if stop_px and px < stop_px:
            return (r, k + 1, "stop")
        if tgt and r >= tgt:
            return (r, k + 1, "target")
        if use_peak_high and prev_high and px >= prev_high:
            return (r, k + 1, "prevhigh")
        if ma is not None and not np.isnan(ma[j]) and px < ma[j]:
            return (r, k + 1, "ma")
        if trail:
            if not armed and (peak / entry - 1) >= eng:
                armed = True
            if armed and (peak - px) / peak >= trail:
                return (r, k + 1, "trail")
        if fixed and k + 1 >= fixed:
            return (r, k + 1, "hold")
    return (c[i_start + maxd - 1] / entry - 1, maxd, "eod")


# 单规则集（不含止损/含止损两版由 stop 开关控制）
RULES = {
    "H5":        {"hold": 5},
    "H10":       {"hold": 10},
    "H20":       {"hold": 20},
    "H60":       {"hold": 60},
    "T5":        {"target": 0.05, "hold": 60},
    "T10":       {"target": 0.10, "hold": 60},
    "T15":       {"target": 0.15, "hold": 60},
    "T20":       {"target": 0.20, "hold": 60},
    "T30":       {"target": 0.30, "hold": 60},
    "T10+S":     {"target": 0.10, "hold": 60, "stop": True},
    "T10+S+PH":  {"target": 0.10, "hold": 60, "stop": True, "prev_high": True},
    "PH":        {"hold": 60, "prev_high": True},          # 才哥第一目标：前期小高点
    "PH+S":      {"hold": 60, "prev_high": True, "stop": True},
    "tr15+eng10": {"trail": 0.15, "eng": 0.10},            # 移动止盈：涨10%后回撤15%出
    "tr20+eng20": {"trail": 0.20, "eng": 0.20},
    "S+tr15":    {"stop": True, "trail": 0.15, "eng": 0.05},
    "MA10":      {"ma": 10},
}


def main():
    by = load()
    print(f"股票数: {len(by)}")

    stats = {f"{ent}|{k}": [] for ent in ("close", "open") for k in RULES}
    sig_dates = {f"{ent}|{k}": [] for ent in ("close", "open") for k in RULES}
    nsig = 0

    for code, bars in by.items():
        bars, o, h, l, c, v = clean(bars)
        n = len(bars)
        if n < 100:
            continue
        for i in range(WARMUP, n - 2):
            if c[i] < round(c[i - 1] * 1.10, 2) - 0.001:
                continue
            if i >= 2 and c[i - 1] >= round(c[i - 2] * 1.10, 2) - 0.001:
                continue
            vr = v[i] / v[i - 1] if v[i - 1] else 0
            if not (1.5 <= vr <= 4):
                continue
            bar_low = l[i]
            ph = h[max(0, i - 20):i].max() if i >= 20 else None   # 前期（20日）小高点
            for ent, ie, px in (("close", i, c[i]), ("open", i + 1, o[i + 1] if i + 1 < n else 0)):
                if ie + 1 >= n or px <= 0:
                    continue
                if ent == "close":
                    nsig += 1
                for k, r in RULES.items():
                    rr = simulate(px, o, h, l, c, ie, bar_low if r.get("stop") else None,
                                  ph, r.get("eng", 0.05), r)
                    if rr:
                        stats[f"{ent}|{k}"].append((rr[0], rr[1]))

    # 基准
    base = {}
    for hh in (5, 10, 20, 60):
        tot, c2 = 0.0, 0
        for code, bars in by.items():
            bars, o, h, l, c, v = clean(bars)
            n = len(bars)
            for i in range(WARMUP, n - hh):
                if c[i] > 0:
                    tot += c[i + hh] / c[i] - 1; c2 += 1
        base[hh] = tot / c2 if c2 else 0
    print("基准:", " / ".join(f"{h}日{base[h]*100:+.2f}%" for h in base))
    print(f"信号数(T收盘口径): {nsig}")

    out = {"base": base, "signals": nsig, "strategies": []}
    for ent in ("close", "open"):
        print(f"\n{'='*104}\n【入场口径：' + ('T 收盘（信号当日）' if ent=='close' else 'T+1 开盘（次日跟进）') + '】")
        print(f"{'策略':<14}{'平均':>9}{'中位':>9}{'胜率':>8}{'盈亏比':>8}{'超额(vs20日)':>13}{'天数':>7}{'年化':>9}")
        for k in RULES:
            rec = stats[f"{ent}|{k}"]
            if not rec:
                continue
            rets = np.array([r for r, _ in rec]); days = np.array([d for _, d in rec])
            wins = rets[rets > 0]; losses = rets[rets <= 0]
            pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float("inf")
            pos = (rets > 0).mean()
            hr = 20 if "20" in k or "H2" in k else (10 if "T10" in k or "H1" in k else 20)
            b = base.get(hr, base[20])
            ann = (1 + np.mean(rets)) ** (240 / max(np.mean(days), 1)) - 1
            print(f"{k:<14}{np.mean(rets)*100:>+8.2f}%{np.median(rets)*100:>+8.2f}%{pos*100:>7.1f}%"
                  f"{pf:>8.2f}{(np.mean(rets)-b)*100:>+12.2f}%{np.mean(days):>7.1f}{ann*100:>+8.1f}%")
            out["strategies"].append({"entry": ent, "name": k, "n": len(rets),
                                      "avg": float(np.mean(rets)), "median": float(np.median(rets)),
                                      "win": float(pos), "pf": float(pf), "excess": float(np.mean(rets) - b),
                                      "days": float(np.mean(days)), "annual": float(ann)})
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/wangzhe_exit_bt_v2.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)
    print("\n✅ 结果已存 outputs/wangzhe_exit_bt_v2.json")


if __name__ == "__main__":
    main()
