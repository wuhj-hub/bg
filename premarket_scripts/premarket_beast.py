#!/usr/bin/env python3
"""
盘前报告 · 猛兽体系扫描 → Markdown 章节生成器 (v3.0)
================================================
读取 beast_screener.py v3.0 的扫描输出，解析关键数据，
输出盘前报告中的「猛兽扫描信号」章节 Markdown。

v3.0 新增解析: G点信号 / 伏击线 / RS_D背离 / 双模式
输出格式：纯 Markdown 文本（可直接嵌入报告）
"""

import re, sys, os
from datetime import datetime, timedelta

OUTPUT_FILE = "/sandbox/workspace/outputs/beast_scan_output.txt"


def read_beast_output() -> str:
    """读取猛兽扫描输出文件"""
    if not os.path.exists(OUTPUT_FILE):
        return ""
    mtime = datetime.fromtimestamp(os.path.getmtime(OUTPUT_FILE))
    if datetime.now() - mtime > timedelta(hours=24):
        return ""
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        return f.read()


def parse_safety_score(text: str) -> dict:
    """解析大盘安全评分"""
    result = {"score": "N/A", "level": "未知", "details": "", "emotion": ""}
    m = re.search(r"安全评分:\s*([\d.]+)/100", text)
    if m:
        result["score"] = m.group(1)
    m = re.search(r"市场状态:\s*(.+)", text)
    if m:
        result["level"] = m.group(1).strip()
    m = re.search(r"加权:\s*(.+)", text)
    if m:
        details = m.group(1).strip()
        if details.endswith(")"):
            details = details[:-1]
        result["details"] = details
    m = re.search(r"情绪指标:\s*(.+)", text)
    if m:
        result["emotion"] = m.group(1).strip()
    idx_line = ""
    for line in text.split("\n"):
        if "上证指数:" in line and "中证全指:" in line:
            idx_line = line.strip()
            break
    result["idx_line"] = idx_line
    return result


def parse_sectors(text: str) -> list:
    """解析领先板块"""
    sectors = []
    in_section = False
    for line in text.split("\n"):
        if "一、领先板块" in line:
            in_section = True
            continue
        if in_section and ("二、领先股" in line or "三、回调股" in line or "四、" in line or "📋" in line):
            in_section = False
            continue
        if in_section:
            m = re.match(r"\s*\d+\.\s*(.+?)\s+涨幅:\s*([+-]?[\d.]+)%\s+领涨:\s*(.+)", line)
            if m:
                sectors.append({"name": m.group(1).strip(), "zdf": m.group(2), "lead_stock": m.group(3).strip()})
    return sectors


def parse_leaders(text: str) -> list:
    """解析领先股"""
    leaders = []
    lines = text.split("\n")
    in_section = False
    header_found = False
    for line in lines:
        if "二、领先股" in line:
            in_section = True; header_found = False; continue
        if in_section and ("三、回调股" in line or "四、" in line or "📋" in line):
            in_section = False; continue
        if in_section:
            if "代码" in line and "名称" in line and "总分" in line:
                header_found = True; continue
            if header_found and ("-" * 10) in line: continue
            if header_found and line.strip() and "⚠️" not in line and "说明" not in line:
                m = re.match(r"\s{2}(sh\d+|sz\d+|bj\d+)\s+(\S+)\s+(\d+)/100\s+(\d+)/\d+\s+([\d.]+)\s+(\S+)?\s+([\d.]+)%\s+(\S+)\s+(.+)?", line)
                if m:
                    leaders.append({"code": m.group(1), "name": m.group(2), "setup": m.group(3),
                                    "breakout": m.group(4), "rsva": m.group(5), "lead_tag": m.group(6) or "",
                                    "dist_from_high": m.group(7), "mode": m.group(8), "tag": (m.group(9) or "").strip()})
    return leaders


def parse_pullbacks(text: str) -> list:
    """解析回调股"""
    pullbacks = []
    lines = text.split("\n")
    in_section = False
    header_found = False
    for line in lines:
        if "三、回调股" in line:
            in_section = True; header_found = False; continue
        if in_section and ("四、" in line or "候选股综合评分" in line or "💡" in line):
            in_section = False; continue
        if in_section:
            if "代码" in line and "名称" in line: header_found = True; continue
            if header_found and ("-" * 10) in line: continue
            if header_found and line.strip():
                m = re.match(r"\s+(sh\d+|sz\d+|bj\d+)\s+(\S+)\s+(\d+)/\d+\s+([\d.]+)%\s+([\d.]+)\s+(\d+)\s+(\d+)/\d+\s+(\d+)/\d+\s+(.*)", line)
                if m:
                    pullbacks.append({"code": m.group(1), "name": m.group(2), "vcp_score": m.group(3),
                                      "dist_from_high": m.group(4), "vol_ratio": m.group(5), "setup": m.group(6),
                                      "ambush_score": m.group(7), "rsd_score": m.group(8), "note": m.group(9).strip()})
    return pullbacks


def parse_gap_signals(text: str) -> list:
    """解析净利润断层信号"""
    gaps = []
    lines = text.split("\n")
    in_section = False
    for line in lines:
        if "净利润断层信号" in line or "断层信号" in line:
            in_section = True; continue
        if in_section and ("综合总结" in line or "💡" in line or "候选股" in line):
            in_section = False; continue
        if in_section:
            m = re.match(r"\s+(\S+)\((\w+)\)\s+扣非增速:\s*([\d.]+)%\s+跳空:\s*(\S+)", line)
            if m:
                gaps.append({"name": m.group(1), "code": m.group(2), "np_growth": m.group(3), "gap_detected": m.group(4)})
    return gaps


def parse_gpoints(text: str) -> list:
    """解析G点信号"""
    gpoints = []
    lines = text.split("\n")
    in_section = False
    for line in lines:
        if "G点信号" in line:
            in_section = True; continue
        if in_section and ("💡" in line or "综合总结" in line or "📊" in line):
            in_section = False; continue
        if in_section:
            m = re.match(r"\s+(\S+)\((\w+)\)\s+PV3=\s*([-\d.]+)\s+OV3=\s*([-\d.]+)\s+模式=(.*)", line)
            if m:
                gpoints.append({"name": m.group(1), "code": m.group(2), "pv3": m.group(3), "ov3": m.group(4),
                                "mode": m.group(5).strip() if m.group(5) else ""})
    return gpoints


def parse_ambush_signals(text: str) -> list:
    """解析伏击线信号"""
    signals = []
    lines = text.split("\n")
    in_section = False
    for line in lines:
        if "伏击线信号" in line:
            in_section = True; continue
        if in_section and ("💡" in line or "综合总结" in line or "📉" in line):
            in_section = False; continue
        if in_section:
            m = re.match(r"\s+(\S+)\((\w+)\)\s+伏击线=\s*([\d.]+)分\s+UB=\s*([\d.]+)", line)
            if m:
                signals.append({"name": m.group(1), "code": m.group(2), "score": m.group(3), "ub": m.group(4)})
    return signals


def parse_rsd_signals(text: str) -> list:
    """解析RS_D背离信号"""
    signals = []
    lines = text.split("\n")
    in_section = False
    for line in lines:
        if "RS_D背离" in line:
            in_section = True; continue
        if in_section and ("💡" in line or "综合总结" in line):
            in_section = False; continue
        if in_section:
            m = re.match(r"\s+(\S+)\((\w+)\)\s+DR5=\s*([-\d.]+)\s+DR4=\s*([-\d.]+)", line)
            if m:
                signals.append({"name": m.group(1), "code": m.group(2), "dr5": m.group(3), "dr4": m.group(4)})
    return signals


def parse_summary(text: str) -> dict:
    """解析综合总结"""
    summary = {"leaders_count": "0", "pullbacks_count": "0", "gap_count": "0",
               "gpoint_count": "0", "ambush_count": "0", "rsd_count": "0", "top_sectors": ""}
    m = re.search(r"领先板块:\s*(\d+)个\s*\|\s*领先股:\s*(\d+)只\s*\|\s*回调股:\s*(\d+)只", text)
    if m:
        summary["leaders_count"] = m.group(2); summary["pullbacks_count"] = m.group(3)
    m = re.search(r"净利润断层:\s*(\d+)只", text)
    if m: summary["gap_count"] = m.group(1)
    m = re.search(r"G点信号:\s*(\d+)只", text)
    if m: summary["gpoint_count"] = m.group(1)
    m = re.search(r"伏击线低吸:\s*(\d+)只", text)
    if m: summary["ambush_count"] = m.group(1)
    m = re.search(r"RS_D背离:\s*(\d+)只", text)
    if m: summary["rsd_count"] = m.group(1)
    m = re.search(r"热门板块TOP3:\s*(.+)", text)
    if m: summary["top_sectors"] = m.group(1).strip()
    return summary


def generate_markdown():
    text = read_beast_output()
    if not text:
        print("""---
#### 🐅 猛兽扫描信号

> ⏳ 猛兽体系v3.0尚未运行当日扫描。大盘温度稳定后自动触发。
> 
> 盘前运行：`python3 /sandbox/workspace/skills/猛兽体系/scripts/beast_screener.py`
""")
        return

    safety = parse_safety_score(text)
    sectors = parse_sectors(text)
    leaders = parse_leaders(text)
    pullbacks = parse_pullbacks(text)
    gaps = parse_gap_signals(text)
    gpoints = parse_gpoints(text)
    ambush = parse_ambush_signals(text)
    rsds = parse_rsd_signals(text)
    summary = parse_summary(text)

    try:
        s_score = float(safety["score"])
        safety_icon = "🟢" if s_score >= 60 else ("🟡" if s_score >= 40 else "🔴")
    except:
        safety_icon = "⚪"

    signals_summary = (f"领先板块 {len(sectors)}个 | 领先股 {summary['leaders_count']}只"
                       f" | 回调股 {summary['pullbacks_count']}只"
                       f" | G点 {summary['gpoint_count']}只"
                       f" | 断层 {summary['gap_count']}只"
                       f" | 伏击线 {summary['ambush_count']}只"
                       f" | RS_D {summary['rsd_count']}只")

    print(f"""---
#### 🐅 猛兽扫描信号

> **大盘安全评分**: {safety_icon} **{safety['score']}/100** — {safety['level']}
> 
> {signals_summary}
""")

    # 板块
    if sectors:
        print("##### 🔴 板块RSR排名 TOP5\n")
        print("| 排名 | 板块 | 涨跌幅 | 领涨股 |")
        print("|:---:|:----|:-----:|:------|")
        for i, s in enumerate(sectors, 1):
            icon = "🟢" if float(s["zdf"]) > 0 else "🔴"
            print(f"| {i} | {s['name']} | {icon} {s['zdf']}% | {s['lead_stock']} |")
        print()

    # 领先股
    if leaders:
        print("##### 🟢 领先股 — 强势突破信号\n")
        print("| 代码 | 名称 | Setup分 | 突破分 | RSVA | 距高点 | 模式 | 评级 |")
        print("|:---:|:----:|:------:|:-----:|:---:|:-----:|:----:|:----:|")
        for s in leaders:
            tag = s.get("tag", "")
            star = "⭐⭐" if "⭐⭐" in tag else ("⭐" if "⭐" in tag else "")
            gap_mark = "⍟" if "断层" in tag else ""
            gpoint_mark = "⚡" if "G点" in tag else ""
            mtag = s.get("mode", "")
            mode_icon = "📦" if "堆量" in mtag else ("🐎" if "欧马" in mtag else "🔀")
            print(f"| {s['code']} | {s['name']} | {s['setup']}/100 | {s['breakout']}/15 | {s['rsva']}"
                  f" | {s['dist_from_high']}% | {mode_icon}{mtag} | {star}{gap_mark}{gpoint_mark} |")
        print()

    # 回调股
    if pullbacks:
        print("##### 🔵 回调股 — 基底回撤末期\n")
        print("| 代码 | 名称 | VCP分 | 距高点 | 量比 | 总分 | 伏击 | RS_D | 备注 |")
        print("|:---:|:----:|:----:|:-----:|:---:|:----:|:---:|:----:|:-----|")
        for s in pullbacks[:8]:
            print(f"| {s['code']} | {s['name']} | {s['vcp_score']}/20 | {s['dist_from_high']}%"
                  f" | {s['vol_ratio']} | {s['setup']}/100 | {s['ambush_score']}/5 | {s['rsd_score']}/5 | {s['note']} |")
        print()

    # G点
    if gpoints:
        print("##### ⚡ G点信号 — 堆量间隙弱转强\n")
        print("| 代码 | 名称 | PV3 | OV3 | 模式 |")
        print("|:---:|:----:|:---:|:---:|:----:|")
        for s in gpoints:
            print(f"| {s['code']} | {s['name']} | {s['pv3']} | {s['ov3']} | {s['mode']} |")
        print()

    # 伏击线
    if ambush:
        print("##### 🔔 伏击线信号 — 低波动率低吸点\n")
        print("| 代码 | 名称 | 评分 | UB价 |")
        print("|:---:|:----:|:---:|:----:|")
        for s in ambush:
            print(f"| {s['code']} | {s['name']} | {s['score']}/5 | {s['ub']} |")
        print()

    # RS_D
    if rsds:
        print("##### 📉 RS_D背离信号 — 低吸区\n")
        print("| 代码 | 名称 | DR5 | DR4 |")
        print("|:---:|:----:|:---:|:---:|")
        for s in rsds:
            print(f"| {s['code']} | {s['name']} | {s['dr5']} | {s['dr4']} |")
        print()

    # 净利润断层
    if gaps:
        print("##### 📊 净利润断层信号\n")
        print("| 代码 | 名称 | 扣非增速 | 跳空缺口 |")
        print("|:---:|:----:|:-------:|:--------:|")
        for s in gaps:
            gap_icon = "✅" if s["gap_detected"] == "是" else "❌"
            print(f"| {s['code']} | {s['name']} | {s['np_growth']}% | {gap_icon} |")
        print()

    # 操作建议
    print("""##### 💡 操作建议

| 类型 | 策略 | 风险提示 |
|:----|:----|:---------|
| 🟢 领先股 | 强势突破+高RSVA，可跟踪回调低吸机会 | 大盘安全评分偏低，注意仓位控制 |
| 🔵 回调股 | VCP收缩+缩量回踩，等待放量突破确认 | 基底可能失败，须设止损 |
| ⚡ G点信号 | 堆量间隙弱转强，双模式识别(堆量/欧马) | 高位G点注意回调风险 |
| 🔔 伏击线 | 低波动率低吸点，爬升途中回调末端 | 须结合趋势确认，不宜逆势 |
| 📉 RS_D背离 | 斜率差底背离，动量角度低吸 | 非每个信号都准确，需大周期过滤 |
| 📊 断层票 | 净利润跳空+高增速，基本面驱动 | 可能一日游，须进一步分析 |
""")

    print()


if __name__ == "__main__":
    generate_markdown()
