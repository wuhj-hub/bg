#!/usr/bin/env python3
"""
盘前报告 · 量学扫描 → Markdown 章节生成器（黑马王子体系）
====================================================
读取 liangxue_screener.py 的扫描输出（outputs/liangxue_latest.json），
生成盘前报告中的「量学扫描信号」章节 Markdown。

与曾星智月线闸门(month_frame)同级：曾星智定方向，量学定量价。
来源：黑马王子《股市天经》三部曲（量柱/量线/量波）

用法：python3 premarket_liangxue.py [--json outputs/liangxue_latest.json]
输出：纯 Markdown 文本（可直接嵌入盘前报告）
"""

import json
import os
import sys
from datetime import datetime, timedelta

DEFAULT_JSON = "/sandbox/workspace/outputs/liangxue_latest.json"


def load_liangxue(path=DEFAULT_JSON):
    """读取量学扫描 JSON（近24小时内的数据才有效）"""
    if not os.path.exists(path):
        return None
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    if datetime.now() - mtime > timedelta(hours=30):
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def render(d):
    """渲染量学章节 Markdown"""
    if not d:
        return ""

    lines = []
    lines.append("---")
    lines.append("")
    lines.append("## 📕 量学扫描（黑马王子体系）")
    lines.append("")
    lines.append(f"> 来源：《量柱擒涨停》《量线捉涨停》《量波逮涨停》 | 扫描 {d.get('total', 0)} 只 | "
                 f"📗PASS={d.get('pass_count', 0)} ⚠️WARN={d.get('warn_count', 0)} ⛔BLOCK={d.get('block_count', 0)}")
    lines.append("")
    lines.append("> 🏛️ **框架分工**：曾星智=月线定方向（只做多头趋势）｜量学=日线量价定买点+分时验证（非月线）→ "
                 "月线空头下的量学信号视为反弹需谨慎（联合池 `liangxue_month_join_latest.json` 自动过滤）")
    lines.append("")

    signals = d.get("signals", [])
    passes = [s for s in signals if s.get("level") == "PASS"]
    warns = [s for s in signals if s.get("level") == "WARN"]

    # 核心信号 TOP10（黄金柱+倍量柱共振优先）
    core = [s for s in passes if any(x["type"] == "黄金柱" for x in s.get("signals", []))
            and any("倍量柱" in x["type"] for x in s.get("signals", []))]
    others = [s for s in passes if s not in core]
    top = (core + others)[:10]

    if top:
        lines.append("**📗 量学PASS信号 TOP10（黄金柱+倍量柱共振优先）**")
        lines.append("")
        lines.append("| 代码 | 名称 | 收盘 | 评分 | 量学信号 |")
        lines.append("|:-----|:-----|:----:|:----:|:---------|")
        for s in top:
            sigs = "+".join(x["type"].replace("倍量柱·低位", "倍量柱(低位)").replace("黄金柱", "🟡黄金柱")
                            for x in s.get("signals", [])[:3])
            lines.append(f"| {s['code']} | {s.get('name','')} | {s.get('close','')} | "
                         f"{s.get('score','')} | {sigs} |")
        lines.append("")
    else:
        lines.append("今日无量学 PASS 信号。")
        lines.append("")

    # WARN 观察
    if warns:
        lines.append(f"**⚠️ 量学WARN观察（{len(warns)}只）**：")
        names = "、".join(f"{s['code']}{s.get('name','')}({s.get('score')}分)" for s in warns[:8])
        lines.append(names)
        lines.append("")

    # 量学要点提示
    lines.append("> 💡 量学口诀：**倍量启动 + 三日价涨量缩（黄金柱）+ 回踩不破柱底 = 买点**；"
                 "**远离黄金线的拉升 = 卖点**（黑马王子）")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    jpath = DEFAULT_JSON
    if len(sys.argv) >= 3 and sys.argv[1] == "--json":
        jpath = sys.argv[2]
    data = load_liangxue(jpath)
    print(render(data))
