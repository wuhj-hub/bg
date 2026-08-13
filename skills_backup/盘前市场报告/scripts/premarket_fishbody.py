#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盘前报告 · 鱼身昨夜扫描 → Markdown 第9章生成器

读取 /sandbox/workspace/outputs/ 下最新的 fish_body_enhanced_*.json，
输出报告第9章（鱼身昨夜扫描）片段。

设计原则：永不报错退出。
  - 无 JSON（鱼身未运行 / 大盘偏冷全池暂停）：输出 HTML 注释占位，不占正文
  - 有 JSON 但 signals 为空：输出偏冷提示注释
  - 有信号：渲染表格（空中加油 / 均线回踩 / 箱体突破）
"""

import glob
import json
import os
import sys

OUTPUTS_DIR = "/sandbox/workspace/outputs"
JSON_GLOB = os.path.join(OUTPUTS_DIR, "fish_body_enhanced_*.json")


def emit_comment(msg):
    """输出 HTML 注释占位（不占报告正文），正常退出。"""
    print("<!-- 鱼身扫描：%s -->" % msg)
    sys.exit(0)


def get_temp(data):
    """返回 (temp数值, level文本)。market_temp 可能是 dict 或标量。"""
    mt = data.get("market_temp")
    if isinstance(mt, dict):
        return mt.get("temp"), mt.get("level")
    if isinstance(mt, (int, float)):
        return mt, None
    return None, None


def pick(sig, keys):
    """按候选键顺序取第一个非空值。"""
    for k in keys:
        if k in sig and sig[k] not in (None, ""):
            return sig[k]
    return ""


def main():
    files = sorted(glob.glob(JSON_GLOB), reverse=True)
    if not files:
        emit_comment("暂无扫描数据（鱼身系统未运行，或大盘偏冷全池暂停）")

    latest = files[0]
    try:
        with open(latest, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        emit_comment("JSON 读取失败：%s" % e)

    if not isinstance(data, dict):
        emit_comment("数据结构异常：根节点非 dict")

    temp, level = get_temp(data)
    signals = data.get("signals", [])

    if not signals:
        if temp is not None:
            emit_comment("大盘温度计 %s/100 偏冷 · 鱼身全池暂停开仓信号" % temp)
        else:
            emit_comment("0 信号（鱼身系统未捕获有效买点）")

    temp_str = ("%s/100" % temp) if temp is not None else "N/A"
    cold = "（偏冷·谨慎）" if (isinstance(temp, (int, float)) and temp < 40) else ""
    print("> 大盘温度计：**%s** %s%s" % (temp_str, (level or ""), cold))
    print()

    headers = ["标签", "代码", "名称", "模式", "评分", "信号价", "止损", "目标", "共振"]
    cols = [
        ["tag"],
        ["code"],
        ["name"],
        ["pattern", "type", "mode_name"],
        ["final_score", "raw_score", "score", "total"],
        ["price", "entry"],
        ["stop_loss", "stop", "sl"],
        ["target", "tp"],
        ["resonance", "note", "remark"],
    ]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["------"] * len(headers)) + "|")
    for s in signals:
        if not isinstance(s, dict):
            continue
        row = [str(pick(s, c)) for c in cols]
        # 标签列美化
        if row[0] == "黄金起爆":
            row[0] = "🔥黄金起爆"
        print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
