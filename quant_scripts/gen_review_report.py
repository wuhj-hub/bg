#!/usr/bin/env python3
"""
gen_review_report.py —— 复盘报告生成器
由全盘量化扫描 workflow 末尾自动触发

输入：全盘量化报告 + 盘前市场报告（昨日）
输出：复盘报告_YYYY-MM-DD.md → 上传复盘报告文件夹 + 推送
"""

import subprocess, json, os, sys, time, re, csv, io
from datetime import datetime, timedelta

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
KB_ID = os.environ.get("IMA_KB_ID", "")
CLIENT_ID = os.environ.get("IMA_OPENAPI_CLIENTID", "")
API_KEY = os.environ.get("IMA_OPENAPI_APIKEY", "")

def run(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except:
        return ""

def read_local_file(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def parse_kline_table(txt):
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"): continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts; continue
        if header and "---" not in parts[0] and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            rows.append({header[i]: parts[i] for i in range(min(len(header), len(parts)))})
    return rows

def calc_change(rows):
    if len(rows) >= 2:
        r1, r2 = rows[-1], rows[-2]
        return (float(r1["last"]) - float(r2["last"])) / float(r2["last"]) * 100
    return 0

def read_lianghua_report():
    """读取本地生成的全盘量化报告"""
    txt = read_local_file("panhou_lianghua.md")
    if not txt:
        print("[WARN] panhou_lianghua.md not found")
        return {}
    data = {}
    for line in txt.splitlines():
        if re.match(r"^\|\s*(主力主导放量|游资情绪|主力控盘|主力偏强放量|主力惜售|情绪退潮)", line):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 2:
                data[parts[0]] = parts[1]
    return data

def read_lianghua_csv():
    """读取全量CSV中提取主力信号低价股"""
    csv_path = "panhou_lianghua.csv"
    if not os.path.exists(csv_path):
        return []
    stocks = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sig = row.get("sig", "")
            if sig in ("主力主导放量🔥(最强)", "主力偏强放量", "主力控盘"):
                try:
                    price = float(row.get("price", 999))
                except:
                    price = 999
                stocks.append({
                    "code": row["code"], "name": row["name"],
                    "price": price, "sig": sig,
                    "precip": row.get("precip", "0"),
                    "m5": float(row.get("m5", 0)) / 1e8
                })
    # 低价优先排序
    stocks.sort(key=lambda s: s["price"])
    return stocks

def gen_report(today_str):
    today = today_str
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    
    lines = []
    lines.append(f"# 📊 复盘报告（{today}）\n")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("数据源：全盘量化扫描 + 盘前市场报告\n")
    
    # 一、大盘全景
    lines.append("## 一、大盘全景\n")
    idx = run(["kline", "sh000001,sz399001,sz399006,sh000688", "--period", "day", "--limit", "3"])
    idx_rows = parse_kline_table(idx)
    if idx_rows:
        lines.append("| 指数 | 昨收 | 今收 | 涨跌幅 |")
        lines.append("|---|---|---|---|")
        symbols = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指", "sh000688": "科创50"}
        for code, name in symbols.items():
            rows = [r for r in idx_rows if r.get("symbol") == code]
            if len(rows) >= 2:
                r_today, r_yest = rows[-1], rows[-2]
                chg = (float(r_today["last"]) - float(r_yest["last"])) / float(r_yest["last"]) * 100
                lines.append(f"| {name} | {r_yest['last']} | {r_today['last']} | **{chg:+.2f}%** |")
    
    # 二、盘后量化分析
    lines.append("\n## 二、盘后量化分析\n")
    dist = read_lianghua_report()
    if dist:
        lines.append("| 信号类型 | 数量 |")
        lines.append("|---|---|")
        for sig in ["主力主导放量🔥(最强)", "主力偏强放量", "主力控盘", "主力惜售", "游资情绪", "情绪退潮"]:
            if sig in dist:
                lines.append(f"| {sig} | {dist[sig]} |")
    
    # 三、主力信号低价股池
    lines.append("\n## 三、💰 主力信号低价股池\n")
    stocks = read_lianghua_csv()
    cheap = [s for s in stocks if s["price"] < 10]
    if cheap:
        lines.append("| 代码 | 名称 | 价格(元) | 信号 | 沉淀率 | 5D主力(亿) |")
        lines.append("|---|---|:---:|:---|---:|:---:|")
        for s in cheap:
            lines.append(f"| {s['code']} | {s['name']} | {s['price']:.2f} | {s['sig'][:10]} | {s['precip']}% | {s['m5']:.2f} |")
    
    lines.append("\n---\n")
    lines.append("⚠️ 本报告基于公开市场数据整理，不构成投资建议。\n")
    
    return "\n".join(lines)

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    md = gen_report(today)
    fname = f"复盘报告_{today}.md"
    os.makedirs("outputs", exist_ok=True)
    with open(f"outputs/{fname}", "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {fname} generated")
    
    # 上传
    for i in 1, 2, 3:
        r = subprocess.run(
            ["python3", "upload_ima.py", "--file", f"outputs/{fname}", "--name", fname],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            print("[OK] uploaded to IMA")
            break
        print(f"attempt {i} failed")
        time.sleep(10)

if __name__ == "__main__":
    main()
