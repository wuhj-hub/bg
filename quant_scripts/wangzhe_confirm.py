#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wangzhe_confirm.py —— 才哥（刘骥才）正版「涨停王者倍量柱」完整信号回测统计

【正版定义】出处：知识库笔记「王者倍量柱（正版选股指标）」（通达信源码）
  信号 = REF(A1,3) AND A2 AND A3 AND A4 AND A5
  A1 = 涨停 + 换手率>5% + 量比 1.5~4
  A2 = 后三天最低收盘价 > 涨停日收盘价
  A3 = 后两天量能依次递减
  A4 = 后三天最高价较涨停价涨幅 <9% + MA60 向上
  A5 = 后三天平均量能 < 涨停日量能
  → 信号在涨停后第 3 天确认（无未来函数）

【本次任务】不设价格限制重新统计成功率；并对比不同买点。
  换手率>5% 在本地日线无法计算（缺流通股本）→ 用「非一字板」代理（该条件本意即滤一字板/无量涨停）

买点变体：
  P0 涨停日 T 收盘       （理论最优，事后视角）
  P1 确认日 T+3 收盘     （正版确认日）
  P2 T+3 后首次突破涨停日最高价 收盘
对比：不限价 vs 价格<10元
"""
import csv, json, os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import numpy as np

BJT = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "kline_daily_vol.csv")
OUT = os.path.join(BASE, "outputs")
HOLD = [5, 10, 20]


def log(m):
    print(f"[{datetime.now(BJT).strftime('%H:%M:%S')}] {m}", flush=True)


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
    log(f"标的 {len(by)} 只")

    base = {h: defaultdict(lambda: [0.0, 0]) for h in HOLD}
    # 信号：(买点变体, 价格档) -> {h: [(date, ret)]}
    SIGS = ["P0_T", "P05_T1", "P02_T2", "P1_T3", "P2_BREAK"]
    BUCKETS = ["all", "lt10", "lt30"]

    def bucket(px):
        return ["all"] + ([ "lt10"] if px < 10 else []) + (["lt30"] if px < 30 else [])

    sig = defaultdict(lambda: {h: [] for h in HOLD})
    nsig = defaultdict(int)

    for code, bars in by.items():
        if not code.startswith(("sh600", "sh601", "sh603", "sh605",
                                "sz000", "sz001", "sz002", "sz003")):
            continue                                   # 仅沪深主板
        close = np.array([b[4] for b in bars]); high = np.array([b[2] for b in bars])
        low = np.array([b[3] for b in bars]); vol = np.array([b[5] for b in bars])
        bad = (close <= 0.3) | (vol <= 0)
        if bad.any():
            k = ~bad
            bars = [b for b, x in zip(bars, k) if x]
            close, high, low, vol = close[k], high[k], low[k], vol[k]
        n = len(bars)
        if n < 90:
            continue
        ma60 = np.full(n, np.nan)
        for i in range(59, n):
            ma60[i] = close[i - 59:i + 1].mean()

        for i in range(n):
            for h in HOLD:
                if i + h < n and close[i] > 0:
                    b_ = base[h][bars[i][0]]
                    b_[0] += close[i + h] / close[i] - 1
                    b_[1] += 1

        for t in range(25, n - 3):
            # ── A1：涨停 + 非一字板（代理换手>5%）+ 量比 1.5~4 ──
            if close[t] < round(close[t - 1] * 1.10, 2) - 0.001:
                continue
            if high[t] == low[t]:                      # 一字板 → 剔除（换手率必然极低）
                continue
            vr = vol[t] / vol[t - 1] if vol[t - 1] else 0
            if not (1.5 <= vr <= 4):
                continue
            # ── A2：后三天收盘均 > 涨停日收盘 ──
            if min(close[t + 1], close[t + 2], close[t + 3]) <= close[t]:
                continue
            # ── A3：后两天量能递减 ──
            if not (vol[t + 3] < vol[t + 2] < vol[t + 1]):
                continue
            # ── A4：后三天最高涨幅 <9% + MA60 向上 ──
            if max(high[t + 1], high[t + 2], high[t + 3]) / close[t] - 1 >= 0.09:
                continue
            if np.isnan(ma60[t + 3]) or np.isnan(ma60[t + 2]) or ma60[t + 3] < ma60[t + 2]:
                continue
            # ── A5：后三天平均量 < 涨停日量 ──
            if (vol[t + 1] + vol[t + 2] + vol[t + 3]) / 3 >= vol[t]:
                continue

            px = close[t]
            bk = bucket(px)
            nsig["signal"] += 1
            # P0：涨停日收盘入场
            ent = {"P0_T": t, "P05_T1": t + 1, "P02_T2": t + 2}
            # P1：确认日收盘入场
            ent["P1_T3"] = t + 3
            # P2：确认后首次突破涨停日最高价
            e2 = None
            for j in range(t + 4, min(t + 25, n)):
                if close[j] > high[t]:
                    e2 = j
                    break
            if e2 is not None:
                ent["P2_BREAK"] = e2
            for key, ei in ent.items():
                if ei is None or ei >= n or close[ei] <= 0:
                    continue
                for h in HOLD:
                    j = ei + h
                    if j < n:
                        for b_ in bk:
                            sig[(key, b_)][h].append((bars[ei][0], close[j] / close[ei] - 1))

    bavg = {h: np.mean([v[0] / v[1] for v in base[h].values() if v[1]]) for h in HOLD}
    _b = sorted(base[5].keys())
    print("\n" + "=" * 94)
    print(f"区间 {_b[0]} ~ {_b[-1]}（仅沪深主板）| 基准: "
          + " / ".join(f"{h}日{bavg[h]*100:+.2f}%" for h in HOLD))
    print(f"正版信号（不限价）总数: {nsig['signal']}")
    print("=" * 94)

    def calc(key, b_, h):
        rs = sig[(key, b_)][h]
        if not rs:
            return None
        byd = defaultdict(list)
        for d, r in rs:
            byd[d].append(r)
        daily = np.array([np.mean(v) for v in byd.values()])
        se = daily.std(ddof=1) / np.sqrt(len(daily)) if len(daily) > 1 else 0
        return {"n": len(rs), "days": len(daily), "mean": float(daily.mean() * 100),
                "median": float(np.median(daily)) * 100, "win": float((daily > 0).mean() * 100),
                "ex_mean": float((daily.mean() - bavg[h]) * 100),
                "t": float((daily.mean() - bavg[h]) / se) if se else 0}

    labels = {"P0_T": "P0 涨停日T收盘入场【不可交易·未来函数】",
              "P05_T1": "P0.5 涨停次日T+1收盘【部分未来函数】",
              "P02_T2": "P0.2 涨停第2日T+2收盘【少量未来函数】",
              "P1_T3": "P1 确认日T+3收盘【✅可交易】",
              "P2_BREAK": "P2 确认后突破涨停日最高价【✅可交易】"}
    blabels = {"all": "不限价", "lt10": "价格<10元", "lt30": "价格<30元"}
    result = {}
    for key in SIGS:
        for b_ in BUCKETS:
            if not sig[(key, b_)][5]:
                continue
            print(f"\n【{labels[key]} · {blabels[b_]}】")
            print(f"  {'持有':<5}{'有效':>7}{'均值':>9}{'中位':>9}{'胜率':>8}{'平均超额':>10}{'t':>7}{'独立日':>8}")
            result[f"{key}|{b_}"] = {}
            for h in HOLD:
                c = calc(key, b_, h)
                if c:
                    result[f"{key}|{b_}"][str(h)] = c
                    print(f"  {h:<5}{c['n']:>7}{c['mean']:>+8.2f}%{c['median']:>+8.2f}%"
                          f"{c['win']:>7.1f}%{c['ex_mean']:>+9.2f}%{c['t']:>7.1f}{c['days']:>8}")
    os.makedirs(OUT, exist_ok=True)
    json.dump({"baseline": {str(h): bavg[h] * 100 for h in HOLD},
               "signal_total": nsig["signal"], "result": result},
              open(os.path.join(OUT, "wangzhe_confirm_stats.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n[OK] outputs/wangzhe_confirm_stats.json")


if __name__ == "__main__":
    main()
