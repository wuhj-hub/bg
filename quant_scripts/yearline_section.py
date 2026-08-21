#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yearline_section.py —— 年线广度章节片段生成器（供盘前/复盘报告嵌入）
======================================================================
读取 yearline_breadth_latest.json，输出可直接嵌入报告的 Markdown 片段。
设计原则：永不报错退出（数据缺失时输出占位注释，不占正文）。

集成方式（盘前 gen_premarket_report.py / 复盘 gen_review_report.py）：
    import subprocess
    r = subprocess.run(["python3", "yearline_section.py", "--json",
                        "outputs/yearline_breadth_latest.json"],
                       capture_output=True, text=True, timeout=30)
    section_md = r.stdout  # 嵌入报告对应章节

输出：纯 Markdown 文本
"""
import argparse
import json
import os
import sys
from datetime import datetime


def render(json_path):
    if not os.path.exists(json_path):
        return "<!-- 年线广度：未找到 " + json_path + "（yearline_breadth.py 未运行） -->\n"
    try:
        with open(json_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return f"<!-- 年线广度：JSON 解析失败 {e} -->\n"

    ratio = d.get("ratio_pct", 0)
    above = d.get("above", 0)
    total = d.get("total", 0)
    level_map = {
        "bull": "🟢 牛市结构（>60%）",
        "mixed": "🟡 结构分化（40-60%）",
        "bear": "🟠 熊市结构（20-40%）",
        "deep_bear": "🔴 深度熊市（<20%）",
    }
    level = level_map.get(d.get("level"), d.get("level", "-"))

    lines = []
    lines.append("### ②.5.x 年线广度（市场牛熊结构）")
    lines.append(f"- 站上年线（收盘≥MA250）：**{above}/{total} = {ratio:.1f}%**　{level}")
    lines.append(f"- 数据日期：{d.get('date', '-')}（主板口径，qt.gtimg.cn 清单）")
    # 临界标的：最接近年线的 5 只（突破/跌破临界）
    stocks = d.get("above_stocks", [])
    if stocks:
        # above_stocks 已按距年线幅度升序（最接近在前）
        near = stocks[:5]
        names = "、".join(f"{s['name']}({s['code']})" for s in near)
        lines.append(f"- 临界站上年线：{names}（距年线+{near[0]['dist_pct']}%~+{near[-1]['dist_pct']}%）")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="outputs/yearline_breadth_latest.json")
    args = ap.parse_args()
    sys.stdout.write(render(args.json))


if __name__ == "__main__":
    main()
