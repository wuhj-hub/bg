#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vcp_backtest.py —— 猛兽「回调股（VCP收缩/缩量回踩）」有效性回测（2026-09-16）

背景：猛兽报告第三部分「回调股 — 基底回撤末期（VCP收缩/缩量回踩）」，判据为
      (vcp_score>=8 或 (5/20量比<0.75 且 距高点>5%)) 且 setup_total>=15。
      本脚本用本地日线近似该形态，检验：①形态本身 ②叠加均线/量缩/回撤 ③「等放量突破确认」买点。

结论（2015-2026 / 沪深主板3051只 / 基准5日+0.38%）：
  VCP≤0.45  −1.36%(t=−7.1) | VCP≤0.75 −0.31%(t=−3.1)  → 越收缩越差
  +均线多头  −0.18%(t=−1.5，唯一正贡献) | +量缩 −0.34% | +回撤>10% −0.50%
  +确认放量突破 −0.23%(胜率46.4%)  → 等确认无效
用法：python3 vcp_backtest.py
"""
import csv, json, os
from collections import defaultdict
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "kline_daily_vol.csv")
OUT = os.path.join(BASE, "outputs")
HOLD = [5, 10, 20]
MAIN = ("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003")


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
    KEYS = ["VCP≤0.45", "VCP≤0.60", "VCP≤0.75", "VCP≤0.90",
            "VCP≤0.75+均线多头", "VCP≤0.75+量缩", "VCP≤0.75+回撤5~15%",
            "VCP≤0.75+距高点>10%", "VCP≤0.75+确认放量突破", "VCP≤0.75+均线多头+确认突破"]
    S = {k: {h: [] for h in HOLD} for k in KEYS}
    cnt = defaultdict(int)

    for code, bars in by.items():
        if not code.startswith(MAIN):
            continue
        cl = np.array([b[4] for b in bars]); hi = np.array([b[2] for b in bars])
        lo = np.array([b[3] for b in bars]); vo = np.array([b[5] for b in bars])
        bad = (cl <= 0.3) | (vo <= 0)
        if bad.any():
            k = ~bad
            bars = [b for b, x in zip(bars, k) if x]
            cl, hi, lo, vo = cl[k], hi[k], lo[k], vo[k]
        n = len(bars)
        if n < 80:
            continue
        amp = (hi - lo) / cl * 100
        ma20 = np.full(n, np.nan); ma60 = np.full(n, np.nan)
        v5 = np.full(n, np.nan); v20 = np.full(n, np.nan)
        for i in range(19, n): ma20[i] = cl[i - 19:i + 1].mean()
        for i in range(59, n): ma60[i] = cl[i - 59:i + 1].mean()
        for i in range(5, n): v5[i] = vo[i - 5:i].mean()
        for i in range(20, n): v20[i] = vo[i - 19:i + 1].mean()
        for i in range(n):
            for h in HOLD:
                if i + h < n and cl[i] > 0:
                    b_ = base[h][bars[i][0]]; b_[0] += cl[i + h] / cl[i] - 1; b_[1] += 1
        for t in range(62, n - 1):
            amp5 = amp[t - 4:t + 1].mean(); amp20 = amp[t - 19:t + 1].mean()
            if amp20 <= 0:
                continue
            vr = amp5 / amp20
            hh20 = hi[t - 19:t + 1].max(); dist = (hh20 - cl[t]) / hh20 * 100
            if dist <= 5:
                continue
            if vr <= 0.45: tag = "VCP≤0.45"
            elif vr <= 0.60: tag = "VCP≤0.60"
            elif vr <= 0.75: tag = "VCP≤0.75"
            elif vr <= 0.90: tag = "VCP≤0.90"
            else: tag = None
            bull = (not np.isnan(ma60[t])) and cl[t] > ma20[t] > ma60[t]
            shrk = (not np.isnan(v20[t])) and v20[t] > 0 and v5[t] / v20[t] < 0.75
            tags = ([tag] if tag else []) + (["VCP≤0.75+均线多头"] if (vr <= 0.75 and bull) else []) \
                + (["VCP≤0.75+量缩"] if (vr <= 0.75 and shrk) else []) \
                + (["VCP≤0.75+回撤5~15%"] if (vr <= 0.75 and 5 < dist <= 15) else []) \
                + (["VCP≤0.75+距高点>10%"] if (vr <= 0.75 and dist > 10) else [])
            for k_ in tags:
                cnt[k_] += 1
                for h in HOLD:
                    if t + h < n:
                        S[k_][h].append((bars[t][0], cl[t + h] / cl[t] - 1))
            if vr <= 0.75 and bull:
                for j in range(t + 1, min(t + 16, n)):
                    if np.isnan(v5[j]) or v5[j] <= 0:
                        continue
                    if cl[j] > hi[max(0, j - 10):j].max() and vo[j] > v5[j] * 1.5:
                        for k_ in ("VCP≤0.75+确认放量突破", "VCP≤0.75+均线多头+确认突破"):
                            cnt[k_] += 1
                            for h in HOLD:
                                if j + h < n:
                                    S[k_][h].append((bars[j][0], cl[j + h] / cl[j] - 1))
                        break

    bavg = {h: np.mean([v[0] / v[1] for v in base[h].values() if v[1]]) for h in HOLD}
    print(f"基准: " + " / ".join(f"{h}日{bavg[h]*100:+.2f}%" for h in HOLD))
    print(f"{'形态/买点':<30}{'n':>9}{'5日超额':>10}{'t':>7}{'胜率':>8}")
    out = {"baseline": {str(h): bavg[h] * 100 for h in HOLD}, "result": {}}
    for k in KEYS:
        if not cnt[k]:
            continue
        sig = S[k][5]
        byd = defaultdict(list)
        for d, r in sig:
            byd[d].append(r)
        dl = np.array([np.mean(v) for v in byd.values()])
        se = dl.std(ddof=1) / np.sqrt(len(dl)) if len(dl) > 1 else 0
        ex = dl.mean() - bavg[5]
        out["result"][k] = {"n": cnt[k], "ex5": float(ex * 100), "t5": float(ex / se if se else 0),
                            "win5": float((dl > 0).mean() * 100)}
        print(f"{k:<30}{cnt[k]:>9}{ex*100:>+9.2f}%{(ex/se if se else 0):>7.1f}{(dl>0).mean()*100:>7.1f}%")
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, "vcp_backtest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[OK] outputs/vcp_backtest.json")


if __name__ == "__main__":
    main()
