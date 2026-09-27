#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xihu_turns_check.py —— 西湖广度净值"拐点"过滤对比分析
对比三种口径的转正信号数量与前瞻有效性（用上证指数 5/10 日收益验证）：
  原始   : 净值由负转正（0轴穿越）
  过滤A  : 转正后净值连续 ≥N 日保持为正（确认非假突破）
  过滤B  : 过滤A + 当日 QSG% ≥ 阈值
用法：python3 xihu_turns_check.py [--run 3] [--qsg 6]
"""
import argparse
import json
import os
import statistics as st
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/sandbox/workspace")
import xihu_breadth as xb  # noqa


def fetch_index(limit=320):
    try:
        raw = subprocess.run(["npx", "-y", "westock-data-skillhub@1.0.3", "kline",
                              "sh000001", "--period", "day", "--limit", str(limit)],
                             capture_output=True, text=True, timeout=180).stdout
    except Exception as e:
        print("指数拉取失败:", e)
        return [], []
    # 单只K线列序为 date|open|last|high|low（无 symbol 列）
    rows = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        p = [x.strip() for x in s.strip("|").split("|")]
        if len(p) < 5 or len(p[0]) != 10 or p[0][4] != "-":
            continue
        try:
            rows.append((p[0], float(p[2])))
        except ValueError:
            continue
    rows.sort(key=lambda r: r[0])
    return [r[0] for r in rows], [r[1] for r in rows]


def fwd_ret(dates, closes, di, d, nd):
    i = di.get(d)
    if i is None or i + nd >= len(closes):
        return None
    return closes[i + nd] / closes[i] - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, default=3, help="过滤A：连续为正天数阈值")
    ap.add_argument("--qsg", type=float, default=6.0, help="过滤B：QSG%% 阈值")
    a = ap.parse_args()

    h = json.load(open("outputs/xihu_breadth_history.json", encoding="utf-8"))
    ks = sorted(h)
    net = [h[k]["net_high"] for k in ks]
    qsg = [h[k]["qsg_pct"] for k in ks]
    dates, closes = fetch_index()
    di = {d: i for i, d in enumerate(dates)}

    # 原始转正
    raw_up = [i for i in range(1, len(net)) if net[i] > 0 and net[i - 1] <= 0]

    # 过滤A：转正后净值连续 >=run 日为正
    fA = [i for i in raw_up if all(net[j] > 0 for j in range(i, min(i + a.run, len(net))))]

    # 过滤B：过滤A + 当日 QSG% >= 阈值
    fB = [i for i in fA if qsg[i] >= a.qsg]

    def stats(idxs):
        r5 = [x for i in idxs if (x := fwd_ret(dates, closes, di, ks[i], 5)) is not None]
        r10 = [x for i in idxs if (x := fwd_ret(dates, closes, di, ks[i], 10)) is not None]
        return {
            "n": len(idxs),
            "avg5": st.mean(r5) * 100 if r5 else None,
            "win5": sum(1 for x in r5 if x > 0) / len(r5) * 100 if r5 else None,
            "avg10": st.mean(r10) * 100 if r10 else None,
            "win10": sum(1 for x in r10 if x > 0) / len(r10) * 100 if r10 else None,
        }

    # 基线：全样本
    base5 = [x for d in ks if (x := fwd_ret(dates, closes, di, d, 5)) is not None]
    base10 = [x for d in ks if (x := fwd_ret(dates, closes, di, d, 10)) is not None]

    print(f"样本 {len(ks)} 日（{ks[0]}~{ks[-1]}）｜参数 run>={a.run} QSG>={a.qsg}%")
    print(f"基线(全样本任意日): 5日均{st.mean(base5)*100:+.2f}% 胜率{sum(1 for x in base5 if x>0)/len(base5)*100:.0f}%"
          f" | 10日均{st.mean(base10)*100:+.2f}% 胜率{sum(1 for x in base10 if x>0)/len(base10)*100:.0f}%")
    print("-" * 78)
    print(f"{'口径':<28}{'信号数':>6}{'5日均':>10}{'5日胜率':>10}{'10日均':>10}{'10日胜率':>10}")
    rows = []
    for name, idxs in [("原始(0轴穿越)", raw_up),
                       (f"过滤A(连续>={a.run}日为正)", fA),
                       (f"过滤B(A+QSG>={a.qsg}%)", fB)]:
        s = stats(idxs)
        rows.append((name, idxs, s))
        f5 = f"{s['avg5']:+.2f}%" if s['avg5'] is not None else "—"
        w5 = f"{s['win5']:.0f}%" if s['win5'] is not None else "—"
        f10 = f"{s['avg10']:+.2f}%" if s['avg10'] is not None else "—"
        w10 = f"{s['win10']:.0f}%" if s['win10'] is not None else "—"
        print(f"{name:<28}{s['n']:>6}{f5:>10}{w5:>10}{f10:>10}{w10:>10}")
    print("-" * 78)
    for name, idxs, s in rows:
        print(f"{name}: " + "、".join(ks[i] for i in idxs))


if __name__ == "__main__":
    main()
