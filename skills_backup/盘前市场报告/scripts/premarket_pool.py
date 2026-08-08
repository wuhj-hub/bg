"""
盘前报告 - 双弦月度股池引用模块
==================================
在盘前报告中展示双弦系统本月积累的共振/低吸股池

用法：
    python3 premarket_pool.py
    → 输出 Markdown 格式的月度股池板块（可用于盘前报告）
"""

import json
import os
import sys

# 双弦系统的月度股池目录
POOL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "双弦投资系统", "pools")
)


def load_monthly_pool(year_month: str = None) -> dict | None:
    """加载指定月份的股池数据"""
    if year_month is None:
        from datetime import date
        year_month = date.today().strftime("%Y-%m")

    pool_file = os.path.join(POOL_DIR, f"pool_{year_month}.json")
    if not os.path.exists(pool_file):
        return None

    with open(pool_file, "r", encoding="utf-8") as f:
        return json.load(f)


def format_pool_as_markdown(data: dict | None) -> str:
    """将月度股池数据格式化为 Markdown 板块"""
    if data is None or not data.get("entries"):
        return ""

    entries = data["entries"]
    year_month = data["year_month"]
    total = data["total_count"]

    # 分类
    resonance = [e for e in entries if e["signal_type"] == "共振"]
    dip = [e for e in entries if e["signal_type"] == "低吸"]

    lines = []
    lines.append("---")
    lines.append("")
    lines.append(f"## 📋 双弦月度股池 ({year_month})")
    lines.append("")
    lines.append("> 自动积累本月双弦系统捕获的**共振信号**（AND门控通过+共振≥+1）")
    lines.append("> 及**低吸信号**（MACD底背离买点），仅展示价格≤10元的标的")
    lines.append("")

    # 统计摘要行
    avg_score = round(sum(e["score"] for e in entries) / total, 1) if total > 0 else 0
    dates = sorted(set(e["date_str"] for e in entries))
    date_range = f"{dates[0]} ~ {dates[-1]}" if dates else "暂无"
    lines.append(f"**总计 {total} 只** | 共振 {len(resonance)} 只 | 低吸 {len(dip)} 只 | "
                 f"均分 {avg_score} | 数据范围: {date_range}")
    lines.append("")

    # 共振股
    if resonance:
        resonance.sort(key=lambda x: x["score"], reverse=True)
        lines.append("### ✅ 共振信号股")
        lines.append("")
        lines.append("| # | 代码 | 名称 | 价格 | 评分 | 共振标签 | 触发日期 |")
        lines.append("|:-:|:----:|:----:|:----:|:----:|:--------:|:--------:|")
        for i, e in enumerate(resonance[:15], 1):  # 最多展示15只
            lines.append(
                f"| {i} | {e['code']} | {e['name']} | "
                f"**{e['price']}** | {e['score']} | {e.get('resonance_label', '')} | "
                f"{e['date_str']} |"
            )
        lines.append("")

    # 低吸股
    if dip:
        dip.sort(key=lambda x: x["score"], reverse=True)
        lines.append("### 🔍 低吸信号股")
        lines.append("")
        lines.append("| # | 代码 | 名称 | 价格 | 评分 | 触发日期 | 原因 |")
        lines.append("|:-:|:----:|:----:|:----:|:----:|:--------:|:----:|")
        for i, e in enumerate(dip[:10], 1):  # 最多展示10只
            lines.append(
                f"| {i} | {e['code']} | {e['name']} | "
                f"**{e['price']}** | {e['score']} | {e['date_str']} | "
                f"{e.get('reason', '底背离买点')} |"
            )
        lines.append("")

    lines.append("> 📌 股池由双弦系统每日收盘后自动积累，盘前报告仅做引用展示，不构成买卖建议")
    lines.append("")

    return "\n".join(lines)


def get_pool_section(year_month: str = None) -> str:
    """
    主入口：获取月度股池 Markdown 板块

    Args:
        year_month: 格式 "2026-07"，默认本月

    Returns:
        Markdown 格式的股池板块，若无数据返回空字符串
    """
    data = load_monthly_pool(year_month)
    if data is None:
        return ""
    return format_pool_as_markdown(data)


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    year_month = sys.argv[1] if len(sys.argv) > 1 else None
    section = get_pool_section(year_month)
    if section:
        print(section)
    else:
        print("<!-- 双弦月度股池：本月暂无数据 -->")