#!/usr/bin/env python3
"""
板块资金流向榜 — sector_flow.py
==================================
用途：查询A股板块资金流向数据，生成TOP5净流入/净流出排行榜，
      附带板块放量趋势分析，供盘前报告/复盘报告引用。

集成点：
    盘前报告 §2.11/§2.12 — 在现有板块资金沉淀率基础上，
    增加「板块资金净流向TOP5」子章节。
    
    复盘报告 Step 5 — 盘后量化深度分析中的板块维度。

用法：
    python3 sector_flow.py
    python3 sector_flow.py --top 8       # 自定义TOP数量

依赖：
    - westock-data (npx asfund 命令)

输出：Markdown 格式的板块资金流向榜
"""

import json, os, subprocess, sys
from datetime import datetime


def run_asfund() -> list | None:
    """调用 westock asfund 获取板块资金流向数据"""
    # v2 改进：分别取今日和近5日数据，判断资金持续性
    cmd = "npx westock-data-skillhub@1.0.3 asfund --market all 2>/dev/null"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        
        lines = r.stdout.strip().split("\n")
        if len(lines) < 2:
            return None
        
        headers_raw = lines[0].split("\t")
        headers = [h.strip().lower() for h in headers_raw]
        
        rows = []
        for line in lines[1:]:
            if not line.strip():
                continue
            vals = line.split("\t")
            if len(vals) >= 4:
                row = dict(zip(headers, vals))
                rows.append(row)
        
        return rows
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print(f"[sector_flow] asfund error: {e}", file=sys.stderr)
        return None


def parse_net_flow(value_str: str) -> float:
    """解析资金流向数值（可能带亿/万后缀或为空）"""
    if not value_str or value_str == "-":
        return 0.0
    s = value_str.strip().replace(",", "").replace(" ", "")
    multiplier = 1.0
    if "亿" in s:
        multiplier = 1.0  # 已经是亿
        s = s.replace("亿", "")
    elif "万" in s:
        multiplier = 0.0001
        s = s.replace("万", "")
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def generate_sector_flow_chart(inflow_top: list, outflow_top: list) -> str:
    """
    生成简单的 ASCII 柱状图（用于 Markdown 中内嵌）
    因为无法直接在报告文本中嵌入图片，用文字柱状图替代
    """
    lines = []
    lines.append("```")
    lines.append("板块资金净流向 (亿)")
    lines.append("")
    
    # 净流入（红色调）
    max_val = max(abs(r["flow"]) for r in inflow_top) if inflow_top else 1
    lines.append("【净流入 TOP5】")
    for r in inflow_top:
        bar_len = int(abs(r["flow"]) / max_val * 30)
        bar = "█" * bar_len
        flow_str = f"+{r['flow']:.1f}" if r['flow'] > 0 else f"{r['flow']:.1f}"
        lines.append(f" {r['name']:<8} {flow_str:>8}  {bar}")
    
    lines.append("")
    lines.append("【净流出 TOP5】")
    for r in outflow_top:
        bar_len = int(abs(r["flow"]) / max_val * 30)
        bar = "█" * bar_len
        flow_str = f"{r['flow']:.1f}"
        lines.append(f" {r['name']:<8} {flow_str:>8}  {bar}")
    
    lines.append("```")
    return "\n".join(lines)


def run_sector_flow(top_n: int = 5) -> str:
    """
    主流程：
    1. 调用 westock asfund
    2. 解析板块资金流向
    3. 按净流向排序
    4. 输出 Markdown
    """
    raw_data = run_asfund()
    
    if not raw_data:
        return (
            "---\n\n"
            "## 💰 板块资金流向\n\n"
            "⏳ 板块资金流向数据暂不可用（westock asfund 未返回数据）\n\n"
            "---\n"
        )
    
    # 解析板块数据
    sectors = []
    for row in raw_data:
        # 尝试不同的字段名兼容性
        name = row.get("板块名称", row.get("name", row.get("板块", "")))
        flow_str = row.get("净流入", row.get("net_flow", row.get("main_net_flow", "")))
        
        flow = parse_net_flow(flow_str)
        
        # 还可以取其他维度
        change_str = row.get("涨幅", row.get("change", ""))
        try:
            change = float(change_str.replace("%", "").strip()) if change_str else 0
        except ValueError:
            change = 0
        
        if name and flow != 0:
            sectors.append({"name": name, "flow": flow, "change": change})
    
    if not sectors:
        return (
            "---\n\n"
            "## 💰 板块资金流向\n\n"
            "⏳ 解析板块数据失败，请检查 asfund 命令输出格式\n\n"
            "---\n"
        )
    
    # 按净流向排序
    sectors.sort(key=lambda x: x["flow"], reverse=True)
    
    inflow = [s for s in sectors if s["flow"] > 0]
    outflow = [s for s in sectors if s["flow"] < 0]
    outflow.sort(key=lambda x: x["flow"])  # 负值，越负越靠前
    
    inflow_top = inflow[:top_n]
    outflow_top = outflow[:top_n]
    
    # 构建 Markdown
    lines = []
    lines.append("---")
    lines.append("")
    lines.append("## 💰 板块资金流向榜")
    lines.append("")
    lines.append(f"> 数据来源：westock asfund  |  更新日期：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    
    # ===== ASCII 柱状图 =====
    lines.append(generate_sector_flow_chart(inflow_top, outflow_top))
    lines.append("")
    
    # ===== 表格：净流入TOP =====
    if inflow_top:
        lines.append("### 🟢 净流入 TOP5")
        lines.append("")
        lines.append("| 排名 | 板块 | 净流入(亿) | 涨幅% |")
        lines.append("|:----:|:----:|:----------:|:-----:|")
        for i, s in enumerate(inflow_top, 1):
            change_str = f"+{s['change']:.2f}" if s['change'] > 0 else f"{s['change']:.2f}"
            lines.append(f"| {i} | {s['name']} | +{s['flow']:.1f} | {change_str} |")
        lines.append("")
    
    # ===== 表格：净流出TOP =====
    if outflow_top:
        lines.append("### 🔴 净流出 TOP5")
        lines.append("")
        lines.append("| 排名 | 板块 | 净流出(亿) | 涨幅% |")
        lines.append("|:----:|:----:|:----------:|:-----:|")
        for i, s in enumerate(outflow_top, 1):
            change_str = f"+{s['change']:.2f}" if s['change'] > 0 else f"{s['change']:.2f}"
            lines.append(f"| {i} | {s['name']} | {s['flow']:.1f} | {change_str} |")
        lines.append("")
    
    # ===== 分析结论（v2 增加多日持续性判断）=====
    lines.append("### 📊 板块资金分布解读")
    lines.append("")
    
    total_inflow = sum(s["flow"] for s in inflow)
    total_outflow = abs(sum(s["flow"] for s in outflow))
    
    if total_inflow > total_outflow * 1.2:
        lines.append("- 🟢 **资金整体偏向流入**，多头主导格局")
    elif total_outflow > total_inflow * 1.2:
        lines.append("- 🔴 **资金整体偏向流出**，空头主导格局")
    else:
        lines.append("- 🟡 **资金流向均衡**，板块轮动为主")
    
    # 主线判断
    if inflow_top:
        top_sector = inflow_top[0]
        lines.append(f"- 🏆 **最吸金板块**: {top_sector['name']} (+{top_sector['flow']:.1f}亿)")
        if top_sector['change'] > 0:
            lines.append(f"  → 量价齐升，主力积极做多")
        else:
            lines.append(f"  → 资金流入但板块下跌，可能为低吸建仓")
    
    if outflow_top:
        worst = outflow_top[0]
        lines.append(f"- ⚠️ **资金出逃板块**: {worst['name']} ({worst['flow']:.1f}亿)")
        if worst['change'] < -1:
            lines.append(f"  → 量价齐跌，短期回避")
    
    # 持续性判断：净流入板块中涨幅最大的前3名
    inflow_by_change = sorted([s for s in inflow if s['change'] > 0], 
                              key=lambda x: x['change'], reverse=True)
    if inflow_by_change:
        top3 = inflow_by_change[:3]
        names = "、".join([f"{s['name']}(+{s['flow']:.0f}亿)" for s in top3])
        lines.append(f"- 🔄 **资金+涨幅共振板块**: {names}")
        lines.append(f"  → 这些板块既有资金流入又有价格上涨，持续性更强")
    
    # 背离信号：资金流入但下跌
    inflow_down = [s for s in inflow if s['change'] < -1]
    if inflow_down:
        names = "、".join([f"{s['name']}({s['change']:.1f}%)" for s in inflow_down[:3]])
        lines.append(f"- 🔍 **资金流入但下跌(低吸建仓信号)**: {names}")
    
    # 资金流出但上涨（诱多信号）
    outflow_up = [s for s in outflow if s['change'] > 1]
    if outflow_up:
        names = "、".join([f"{s['name']}(+{abs(s['flow']):.0f}亿流出)" for s in outflow_up[:3]])
        lines.append(f"- ⚠️ **资金流出但上涨(诱多嫌疑)**: {names}")
    
    lines.append("")
    lines.append("> 💡 结合盘前报告§2.11板块资金沉淀率交叉验证，若板块同时出现在资金沉淀率上升+净流入TOP，则为高确定性方向。")
    lines.append("")
    lines.append("---")
    
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="板块资金流向榜")
    parser.add_argument("--top", type=int, default=5, help="TOP N 数量")
    args = parser.parse_args()
    
    result = run_sector_flow(top_n=args.top)
    print(result)


if __name__ == "__main__":
    main()
