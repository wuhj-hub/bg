#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rsg_weekly_report.py —— RSG 过滤有效性周报（P0#1 配套验证，2026-08-28）
============================================================
读 outputs/paper_portfolio.json（paper_tracker.py 维护，含 rsg_sig_strong/rsg_now_strong），
输出 RSG 强势侧过滤的实盘验证：信号日分组 + 当前分组 + 周度趋势。
样本≥10/组时给出结论（有效/无效/待积累）。

用法:
  python3 quant_scripts/rsg_weekly_report.py
输出: outputs/RSG过滤验证周报_{date}.md
"""
import json, os, sys
from datetime import datetime
from collections import defaultdict

PORTFOLIO = "outputs/paper_portfolio.json"

def stat(rets):
    if len(rets) < 3:
        return None
    wins = [r for r in rets if r > 0]
    return {"n": len(rets), "wr": len(wins) / len(rets) * 100,
            "avg": sum(rets) / len(rets), "med": sorted(rets)[len(rets) // 2]}

def main():
    if not os.path.exists(PORTFOLIO):
        print(f"❌ 纸面组合不存在: {PORTFOLIO}\n提示: 先运行 paper_tracker.py --init 和 --update")
        return
    pf = json.load(open(PORTFOLIO, encoding="utf-8"))
    positions = [p for p in pf.get("positions", []) if "ret" in p]
    if not positions:
        print("⏳ 组合未更新盈亏，先 paper_tracker.py --update")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    L = [f"# 🟢 RSG 强势侧过滤验证周报 {today}", "",
         f"> 数据: 纸面组合 {len(positions)} 个信号（{pf.get('init_date')} 起）",
         "> 口径: 信号日收盘入场 → 当前盈亏；RSG>50‰=强势池", ""]

    # 1. 信号日 RSG 分组（最严格：信号发生时是否在强势池）
    L.append("## 一、信号日 RSG 分组（信号发生时状态）\n")
    L.append("| 分组 | 样本 | 胜率 | 平均收益 | 中位 |")
    L.append("|:----|:---:|:----:|:----:|:----:|")
    sig_s = [p["ret"] for p in positions if p.get("rsg_sig_strong")]
    sig_w = [p["ret"] for p in positions if not p.get("rsg_sig_strong") and p.get("rsg_sig") is not None]
    sig_u = [p["ret"] for p in positions if p.get("rsg_sig") is None]
    for name, rets in (("🟢 信号日强势(>50‰)", sig_s), ("⚪ 信号日非强势", sig_w), ("❔ 信号日无RSG数据", sig_u)):
        s = stat(rets)
        L.append(f"| {name} | {len(rets)} | {s['wr']:.0f}% | {s['avg']:+.2f}% | {s['med']:+.2f}% |" if s else f"| {name} | {len(rets)}（样本不足） | — | — | — |")
    L.append("")

    # 2. 当前 RSG 分组
    L.append("## 二、当前 RSG 分组（现在是否仍在强势池）\n")
    L.append("| 分组 | 样本 | 胜率 | 平均收益 | 中位 |")
    L.append("|:----|:---:|:----:|:----:|:----:|")
    now_s = [p["ret"] for p in positions if p.get("rsg_now_strong")]
    now_w = [p["ret"] for p in positions if not p.get("rsg_now_strong")]
    for name, rets in (("🟢 当前强势池", now_s), ("⚪ 当前非强势池", now_w)):
        s = stat(rets)
        L.append(f"| {name} | {len(rets)} | {s['wr']:.0f}% | {s['avg']:+.2f}% | {s['med']:+.2f}% |" if s else f"| {name} | {len(rets)}（样本不足） | — | — | — |")
    L.append("")

    # 3. 周度新增信号趋势
    L.append("## 三、周度新增信号趋势\n")
    L.append("| 周起始 | 新信号 | RSG强势占比 |")
    L.append("|:----|:---:|:---:|")
    weeks = defaultdict(list)
    for p in positions:
        weeks[p["sig_date"][:7]].append(p)
    for ym in sorted(weeks.keys())[-6:]:
        ps = weeks[ym]
        strong = sum(1 for p in ps if p.get("rsg_sig_strong"))
        L.append(f"| {ym} | {len(ps)} | {strong}/{len(ps)} |")
    L.append("")

    # 4. 结论
    L.append("## 📌 结论\n")
    s_s, s_w = stat(sig_s), stat(sig_w)
    if s_s and s_w and s_s["n"] >= 10 and s_w["n"] >= 10:
        diff = s_s["avg"] - s_w["avg"]
        if diff > 2 and s_s["wr"] > s_w["wr"]:
            L.append(f"- ✅ **RSG 过滤有效**：信号日强势组胜率 {s_s['wr']:.0f}% vs 非强势 {s_w['wr']:.0f}%，收益差 {diff:+.1f}pp")
        elif diff < -2:
            L.append(f"- ❌ **RSG 过滤无效/反向**：强势组 {s_s['avg']:+.1f}% vs 非强势 {s_w['avg']:+.1f}%（样本需再验证）")
        else:
            L.append(f"- ⚪ **差异不显著**：强势组 {s_s['avg']:+.1f}% vs 非强势 {s_w['avg']:+.1f}%（继续积累）")
    else:
        L.append(f"- ⏳ 样本待积累：信号日强势 {len(sig_s)} 只 / 非强势 {len(sig_w)} 只（需各≥10 只后出结论）")
        L.append("- 继续每日运行 paper_tracker --update，2-4 周后重跑本脚本")
    L += ["", "---", "⚠️ 本报告为纸面模拟统计，不构成投资建议。"]

    md = "\n".join(L)
    os.makedirs("outputs", exist_ok=True)
    out = f"outputs/RSG过滤验证周报_{today}.md"
    open(out, "w", encoding="utf-8").write(md)
    print(f"[OK] {out}")
    print(md[:1200])

if __name__ == "__main__":
    main()
