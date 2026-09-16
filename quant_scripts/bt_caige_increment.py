#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""才哥/曾星智增量回测（2026-09-16）

来源：才哥 2026-09-16 文章《绝地反击，托举资金大笔流入！》华瓷股份案例：
  「围绕前方瞒天过海（8月11号）寻找突破机会，前期以一次几乎标准的王者倍量柱见底，
    随后又在 **20日线上** 走出王者倍量柱的震荡上攻。在昨天的拉升中，以一次
    **放量涨停反包了前方瞒天过海的关键位置**，今天加速一字板加速上涨。」

→ 提取两个可证伪的增量条件，测其是否改善基线（B0 涨停+量比1.5~4）：
  C1  B0 + **收盘站上 MA20**（才哥「20日线上」）
  C2  B0 + **反包**：当日涨停且收盘 > 前5日最高价（收复「关键位置」）
  C3  B0 + **先抑后扬**：前3日内至少1根阴线（反包的前置形态）
  C4  C1 + C2（才哥完整描述）
  C5  C1 + C3

曾星智增量（长期力量向下仍参与短期反弹）已在 market_regime.py 落地，此处不复测。
"""
import csv, json
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
HOLD = [5, 10, 20]
VARIANTS = ["B0", "C1", "C2", "C3", "C4", "C5"]
NAMES = {
    "B0": "B0 基线：涨停+量比1.5~4（T收盘）",
    "C1": "C1 B0 + 收盘站上MA20（才哥「20日线上」）",
    "C2": "C2 B0 + 反包（收盘>前5日最高，收复关键位）",
    "C3": "C3 B0 + 先抑后扬（前3日有阴线）",
    "C4": "C4 C1+C2（才哥完整描述）",
    "C5": "C5 C1+C3",
}


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
    res = {k: {h: [] for h in HOLD} for k in VARIANTS}
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
        if n < 80:
            continue
        ma20 = np.full(n, np.nan)
        for i in range(19, n):
            ma20[i] = close[i - 19:i + 1].mean()

        for i in range(25, n):
            for h in HOLD:
                if i + h < n and close[i] > 0:
                    b_ = base[h][bars[i][0]]; b_[0] += close[i + h] / close[i] - 1; b_[1] += 1

            # 涨停判定（主板 10%）
            if close[i] < round(close[i - 1] * 1.10, 2) - 0.001:
                continue
            # 首板（前一日未涨停）
            if i >= 2 and close[i - 1] >= round(close[i - 2] * 1.10, 2) - 0.001:
                continue
            vr = vol[i] / vol[i - 1] if vol[i - 1] else 0
            if not (1.5 <= vr <= 4):
                continue
            if np.isnan(ma20[i]):
                continue

            hit = {"B0": True}
            hit["C1"] = close[i] > ma20[i]                                  # 站上20日线
            hit["C2"] = close[i] > high[i - 5:i].max()                      # 反包前5日高点
            hit["C3"] = bool((close[i - 3:i] < np.roll(close, 1)[i - 3:i]).any())  # 前3日有阴线
            hit["C4"] = hit["C1"] and hit["C2"]
            hit["C5"] = hit["C1"] and hit["C3"]

            for k in VARIANTS:
                if hit.get(k):
                    cnt[k] += 1
                    for h in HOLD:
                        if i + h < n:
                            res[k][h].append((bars[i][0], close[i + h] / close[i] - 1))

    base_avg = {h: np.mean([v[0] / v[1] for v in base[h].values() if v[1]]) for h in HOLD}
    _b = sorted(base[5].keys())
    print("=" * 88)
    print(f"区间 {_b[0]} ~ {_b[-1]} | 基准: " + " / ".join(f"{h}日{base_avg[h]*100:+.2f}%" for h in HOLD))
    print("=" * 88)

    out = {"period": [_b[0], _b[-1]], "base": {str(h): base_avg[h] for h in HOLD}, "variants": {}}
    for k in VARIANTS:
        print(f"\n【{NAMES[k]}】n={cnt[k]}")
        if cnt[k] == 0:
            print("  （无信号）"); continue
        print(f"  {'持有':<5}{'按日':>10}{'中位':>10}{'胜率':>9}{'超额':>10}{'t值':>8}")
        out["variants"][k] = {"n": cnt[k], "holds": {}}
        for h in HOLD:
            byd = defaultdict(list)
            for d, r in res[k][h]:
                byd[d].append(r)
            daily = [np.mean(v) for v in byd.values()]           # 按信号日聚合，避免同日重复放大
            allr = [r for _, r in res[k][h]]
            dayexc = [x - base_avg[h] for x in daily]
            t = (np.mean(dayexc) / (np.std(dayexc, ddof=1) / np.sqrt(len(dayexc)))) if len(dayexc) > 1 and np.std(dayexc) > 0 else 0
            print(f"  {h}日{'':<3}{np.mean(allr)*100:>+9.2f}%{np.median(allr)*100:>+9.2f}%"
                  f"{(np.array(allr)>0).mean()*100:>8.1f}%{(np.mean(daily)-base_avg[h])*100:>+9.2f}%{t:>8.2f}")
            out["variants"][k]["holds"][str(h)] = {
                "avg": float(np.mean(allr)), "median": float(np.median(allr)),
                "win": float((np.array(allr) > 0).mean()),
                "excess": float(np.mean(daily) - base_avg[h]),
                "t": float(t), "n_days": len(daily)}

    with open("/sandbox/workspace/zxz_bt/outputs/caige_zxz_increment_bt.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n✅ 结果已存 outputs/caige_zxz_increment_bt.json")


if __name__ == "__main__":
    main()
