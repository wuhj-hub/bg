#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""王者倍量柱案例回溯：倍量柱 → 观察期 → 突破（王后突破 TP2）→ 主升（2026-09-16）

来源：知识库「王者倍量柱」知识库的扫描报告
  · 「王者倍量-历史」（扫描 2026-06-27）：27 只去重信号，标注了【倍量柱发生日】
  · 「王者倍量-前日2」（扫描 2026-06-28）：1536 只 → 778 信号 / 591 只
    （TP1 标准突破 401 / TP2 王后突破 190）
  · 「王者倍量」（扫描 2026-06-30）：43 只 → 1 信号（凯美特气）

关键观察：报告中「倍量柱发生日」到「突破确认日」间隔很长（最长 117 天）
         → 本脚本量化这段「观察期」，并测「突破后还能涨多少」

案例列表（code, 倍量柱日）来自「王者倍量-历史」报告的日期列
"""
import csv, json, os
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
OUT = "/sandbox/workspace/zxz_bt/outputs"

# 「王者倍量-历史」报告：倍量柱发生日 + 类型（TP1 标准突破 / TP2 王后突破）
CASES = [
    ("000417", "合百集团", "2026-05-18", "TP2"),
    ("000925", "众合科技", "2026-04-21", "TP1"),
    ("002132", "恒星科技", "2026-05-07", "TP2"),
    ("600545", "卓郎智能", "2026-04-15", "TP1"),
    ("002141", "贤丰控股", "2026-06-12", "TP1"),
    ("002617", "露笑科技", "2026-05-11", "TP1"),
    ("002354", "天娱数科", "2026-05-08", "TP1"),
    ("603956", "威派格",   "2026-05-07", "TP1"),
    ("002546", "新联电子", "2026-05-11", "TP1"),
    ("002183", "怡亚通",   "2026-04-10", "TP1"),
    ("600382", "广东明珠", "2026-04-09", "TP2"),
    ("600603", "广汇物流", "2026-03-02", "TP1"),
    ("601016", "节能风电", "2026-04-28", "TP1"),
    ("600935", "华塑股份", "2026-02-27", "TP1"),
    ("600500", "中化国际", "2026-05-06", "TP1"),
    ("600075", "新疆天业", "2026-03-26", "TP1"),
    ("002641", "公元股份", "2026-06-03", "TP1"),
    ("000876", "新希望",   "2026-04-08", "TP1"),
    ("600179", "安通控股", "2026-06-17", "TP1"),
]
CONFIRM = "2026-06-27"   # 扫描/突破确认日


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


def wcode(c):
    return ("sh" if c[0] in "69" else "sz") + c


def main():
    by = load()
    rows = []
    print(f"{'代码':<8}{'名称':<10}{'倍量柱日':<12}{'观察天数':>8}{'期内最大涨幅':>12}{'期内最大回撤':>12}"
          f"{'期间量能比':>11}{'突破后5日':>10}{'突破后10日':>11}{'突破后20日':>11}")
    print("-" * 118)
    for code, name, bd, tp in CASES:
        bars = by.get(wcode(code))
        if not bars:
            continue
        dates = [b[0] for b in bars]
        if bd not in dates:
            continue
        i0 = dates.index(bd)
        # 确认日索引
        ic = next((j for j, d in enumerate(dates) if d >= CONFIRM), None)
        if ic is None or ic <= i0:
            continue
        # 倍量柱日 → 确认日 这段观察期
        seg = bars[i0:ic]
        c0 = bars[i0][4]
        seg_h = max(b[2] for b in seg); seg_l = min(b[3] for b in seg)
        up = seg_h / c0 - 1
        dd = seg_l / seg_h - 1                      # 期内最大回撤（从阶段高点）
        vol_ratio = np.mean([b[5] for b in seg[3:]]) / bars[i0][5] if bars[i0][5] else 0
        # 突破后收益（从确认日收盘）
        cc = bars[ic][4]
        rets = []
        for hh in (5, 10, 20):
            if ic + hh < len(bars):
                rets.append(bars[ic + hh][4] / cc - 1)
            else:
                rets.append(None)
        gap = (np.datetime64(CONFIRM) - np.datetime64(bd)).astype(int)
        rows.append({"code": code, "name": name, "bar_date": bd, "type": tp,
                     "gap_days": int(gap), "seg_up": float(up), "seg_dd": float(dd),
                     "vol_ratio": float(vol_ratio),
                     "r5": rets[0], "r10": rets[1], "r20": rets[2]})
        f = lambda x: f"{x*100:>+9.2f}%" if x is not None else f"{'-':>10}"
        print(f"{code:<8}{name:<10}{bd:<12}{gap:>8}{up*100:>11.1f}%{dd*100:>11.1f}%"
              f"{vol_ratio:>11.2f}{f(rets[0]):>10}{f(rets[1]):>11}{f(rets[2]):>11}")

    if rows:
        gaps = np.array([r["gap_days"] for r in rows])
        print("-" * 118)
        print(f"\n观察期统计：中位 {np.median(gaps):.0f} 天 / 均值 {np.mean(gaps):.0f} 天 / "
              f"范围 {gaps.min()}~{gaps.max()} 天")
        for tp in ("TP1", "TP2"):
            sub = [r for r in rows if r["type"] == tp]
            if not sub:
                continue
            g = np.array([r["gap_days"] for r in sub])
            r20 = [r["r20"] for r in sub if r["r20"] is not None]
            print(f"  {tp}: n={len(sub)} 观察期中位 {np.median(g):.0f}天 "
                  f"突破后20日均值 {np.mean(r20)*100:+.2f}%" if r20 else f"  {tp}: n={len(sub)}")
        os.makedirs(OUT, exist_ok=True)
        with open(f"{OUT}/wangzhe_case_review.json", "w", encoding="utf-8") as f:
            json.dump({"confirm_date": CONFIRM, "cases": rows}, f, ensure_ascii=False, indent=2)
        print("\n✅ 结果已存 outputs/wangzhe_case_review.json")


if __name__ == "__main__":
    main()
