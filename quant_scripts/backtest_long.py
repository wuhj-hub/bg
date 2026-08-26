#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_long.py —— 见顶五维长历史补验（2010-09 至 2026-08，腾讯proxy数据源）
补验 westock 5年窗口无法覆盖的 2015-06(5178)/2018-01(3587)/2021-02(3731) 大顶
复用 top_signal.py 的 dim1/dim4/dim5 逻辑
用法：python3 backtest_long.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from top_signal import dim1_vol_divergence, dim4_panic_sell, dim5_euphoria, merge_events

def main():
    rows = json.load(open("data_hs300/上证指数_日K_2013至今.json", encoding="utf-8"))
    print(f"数据: {len(rows)} 根（{rows[0]['date']} ~ {rows[-1]['date']}）")
    hits = {"1_量的背离": [], "4_恐慌抛售": [], "5_情绪亢奋": []}
    n = len(rows)
    for i in range(260, n):
        win = rows[:i + 1]
        if dim1_vol_divergence(win)[0]:
            hits["1_量的背离"].append((win[-1]["date"], dim1_vol_divergence(win)[1]))
        if dim4_panic_sell(win)[0]:
            hits["4_恐慌抛售"].append((win[-1]["date"], dim4_panic_sell(win)[1]))
        if dim5_euphoria(win)[0]:
            hits["5_情绪亢奋"].append((win[-1]["date"], dim5_euphoria(win)[1]))
    events = {k: merge_events(v) for k, v in hits.items()}
    for k, evs in events.items():
        print(f"\n{k} 事件 {len(evs)} 个（长历史）：")
        for s, e, detail in evs:
            tag = f"{s}" if s == e else f"{s}~{e}"
            print(f"  {tag}  {detail}")

    # 关键历史顶部对照（窗口±5交易日，每维计1次）
    print("\n════ 历史大顶五维触发对照（±5交易日，每维计1次）════")
    key_dates = [
        ("2015-06-12", "2015牛市顶5178"),
        ("2015-08-24", "股灾2.0"),
        ("2016-01-04", "熔断顶"),
        ("2018-01-29", "2018顶3587"),
        ("2019-04-08", "2019顶3288"),
        ("2021-02-18", "2021抱团顶3731"),
        ("2021-12-13", "2021-12顶3723"),
        ("2022-04-27", "2022底2863(对照)"),
        ("2022-10-31", "2022底2885(对照)"),
    ]
    for kd, label in key_dates:
        kd_idx = next((j for j, r in enumerate(rows) if r["date"] >= kd), None)
        if kd_idx is None:
            print(f"  {kd} {label}: 超窗口")
            continue
        w = rows[max(0, kd_idx - 5):kd_idx + 6]
        hit_dims = []
        for r in w:
            ri = rows.index(r)
            if dim1_vol_divergence(rows[:ri + 1])[0] and "1" not in hit_dims:
                hit_dims.append("1")
            if dim4_panic_sell(rows[:ri + 1])[0] and "4" not in hit_dims:
                hit_dims.append("4")
            if dim5_euphoria(rows[:ri + 1])[0] and "5" not in hit_dims:
                hit_dims.append("5")
        mark = "🔴" if len(hit_dims) >= 2 else ("🟡" if len(hit_dims) == 1 else "⚪")
        print(f"  {mark} {kd} {label}: {len(hit_dims)}/3 维 {'[' + ','.join(hit_dims) + ']' if hit_dims else '（无）'}")

if __name__ == "__main__":
    main()
