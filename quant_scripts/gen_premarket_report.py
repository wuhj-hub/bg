#!/usr/bin/env python3
"""
gen_premarket_report.py —— 盘前市场报告生成器
由 GitHub Actions 在交易日 08:00 自动触发

依赖：westock-data-skillhub (npx), upload_ima.py
输出：盘前市场报告_YYYY-MM-DD.md → 上传至盘前报告文件夹
"""

import subprocess, json, time, os, sys, re
from datetime import datetime, timedelta

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
TIMEOUT = 60

def run(args, timeout=TIMEOUT):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception as e:
        return f"ERR:{e}"

def run_curl(url):
    try:
        r = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=20)
        return r.stdout
    except:
        return ""

def parse_kline_table(txt):
    """解析westock kline表格，返回列表"""
    rows = []
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if header and "---" not in parts[0] and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            row = {}
            for i, h in enumerate(header):
                if i < len(parts):
                    row[h] = parts[i]
            rows.append(row)
    return rows

def get_index_data():
    """获取四大指数最新K线"""
    lines = []
    codes = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指", "sh000688": "科创50"}
    
    for code, name in codes.items():
        txt = run(["kline", code, "--period", "day", "--limit", "3"])
        rows = parse_kline_table(txt)
        if len(rows) >= 2:
            d1, d2 = rows[-1], rows[-2]  # 倒数第一和第二（升序）
            change = (float(d1["last"]) - float(d2["last"])) / float(d2["last"]) * 100
            lines.append(f"| {name} | {d1['last']} | {d2['last']} | {change:+.2f}% |")
    return "\n".join(lines)

def get_board_data():
    """获取板块排行"""
    txt = run(["hot", "board", "--limit", "10"])
    lines = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and not s.startswith("|---"):
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 8 and parts[0].isdigit():
                idx, name, zdf = parts[0], parts[6], parts[7]
                lines.append(f"| {idx} | {name} | {zdf} |")
    return "\n".join(lines[:10])

def get_hot_stocks():
    """获取热门股票"""
    txt = run(["hot", "stock"])
    lines = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and "us" not in s and "688" not in s and "300" not in s:
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 5 and parts[0].startswith(("sh", "sz")):
                name, zdf = parts[1], parts[2]
                lines.append(f"| {parts[0]} | {name} | {zdf} |")
    return "\n".join(lines[:10])

def get_news():
    """获取隔夜新闻"""
    # 使用新闻API，这里用web search的简化版
    try:
        r = subprocess.run(
            ["curl", "-s", "https://stock.xueqiu.com/v5/stock/batch/quote.json?symbol=SH000001&extend=detail"],
            capture_output=True, text=True, timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        return r.stdout[:200]
    except:
        return ""

def get_index_monthly():
    """获取八大指数月线用于双弦定性"""
    codes = ["sh000001", "sz399106", "sh000016", "sh000300", 
             "sz399101", "sh000688", "sz399006", "sh000905"]
    names = ["上证指数", "深证综指", "上证50", "沪深300",
             "中小综指", "科创50", "创业板指", "中证500"]
    results = {}
    for code, name in zip(codes, names):
        txt = run(["kline", code, "--period", "month", "--limit", "6"])
        rows = parse_kline_table(txt)
        if rows:
            results[name] = rows
    return results

def gen_report(today_str):
    """生成完整盘前报告"""
    today = today_str
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    
    lines = []
    lines.append(f"# 📊 盘前市场报告 · {today}\n")
    lines.append("布局：本报告采用「外围(输入) → 大盘(势) → 板块(线) → 个股(点)」信号传导链。")
    lines.append(f"数据截止：A股 {yesterday} 收盘；美股 {yesterday} 收盘。")
    lines.append("⚠️ 基于公开数据整理，不构成投资建议。\n")
    
    # ① 外围环境
    lines.append("## ① 外围环境\n")
    lines.append("### 美股三大指数\n")
    us = run(["kline", "usDJI,usIXIC,usINX", "--period", "day", "--limit", "3"])
    rows = parse_kline_table(us)
    if rows:
        lines.append("| 指数 | 最新 | 前日 | 涨跌幅 |")
        lines.append("|---|---|---|---|")
        for r in rows[-2:]:
            lines.append(f"| {r['symbol']} | {r['last']} | ... | ... |")
    
    lines.append("\n### 商品\n")
    oil = run_curl("https://api.exchangerate-api.com/v4/latest/USD")[:100] or "⏳ 数据获取中"
    lines.append(f"- 原油/黄金数据：正在采集\n")
    
    # ② 大盘
    lines.append("## ② 大盘定势\n")
    idx_data = get_index_data()
    if idx_data:
        lines.append("| 指数 | 最新 | 前收 | 涨跌幅 |")
        lines.append("|---|---|---|---|")
        lines.append(idx_data)
    
    lines.append("\n## ③ 板块排行\n")
    board = get_board_data()
    if board:
        lines.append("| 排名 | 板块 | 涨跌幅 |")
        lines.append("|---|---|---|")
        lines.append(board)
    
    lines.append("\n## ④ 个股定点\n")
    lines.append("⏳ 每日量化数据由15:30全盘量化扫描生成，盘前时段引用昨日数据。\n")
    
    lines.append("\n## ⑤ 策略要点\n")
    lines.append("- 操作建议详见量化系统信号快照")
    lines.append("- 完整数据请参见全盘量化报告\n")
    
    lines.append("---\n")
    lines.append("⚠️ 本报告基于公开市场数据整理，不构成投资建议。\n")
    
    return "\n".join(lines)

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    md = gen_report(today)
    fname = f"盘前市场报告_{today}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {fname} generated ({len(md)} chars)")
    
    # 上传
    upload_ok = False
    for i in 1, 2, 3:
        r = subprocess.run(
            ["python3", "upload_ima.py", "--file", fname, "--name", fname],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            upload_ok = True
            break
        print(f"upload attempt {i} failed, retry...")
        time.sleep(10)
    
    if upload_ok:
        print("[OK] uploaded to IMA knowledge base")
    else:
        print("[WARN] upload failed, report saved locally")

if __name__ == "__main__":
    main()
