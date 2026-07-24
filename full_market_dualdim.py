#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
full_market_dualdim.py —— 全盘量化扫描

读 all_mainboard.csv，对每只股票并发调用 westock-data-skillhub 计算：
  - 沉淀率 = MainNetFlow5D ÷ 近5日总成交额
  - CJB30 / B30V100 / VEAB（放量趋势，对齐盘前报告 §2.12）
套用双维定性矩阵得到信号，输出：
  - panhou_lianghua.csv（全量结果）
  - panhou_lianghua.md（分布统计 + 重点标的）

运行环境：GitHub Actions runner（westock 需外网 + node）。
注意：此脚本输出为复盘报告的原始数据源，不独立作为分析报告发布。
"""

import subprocess
import re
import json
import csv
import sys
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
TIMEOUT = 120
RETRIES = 2

SIGNAL_ORDER = {
    "主力主导放量🔥(最强)": 0,
    "游资情绪": 1,
    "主力控盘": 2,
    "主力偏强放量": 3,
    "主力惜售": 4,
    "情绪退潮": 5,
}


def run(args, timeout=TIMEOUT):
    for _ in range(RETRIES + 1):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            return r.stdout
        except Exception as e:
            if _ == RETRIES:
                return f"ERR:{e}"
            time.sleep(2)


def parse_kline(txt):
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
        if header and "---" not in parts[0]:
            try:
                if re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                    rows.append({"date": parts[0], "amount": float(parts[header.index("amount")]), "last": float(parts[header.index("last")])})
            except Exception:
                pass
    return sorted(rows, key=lambda r: r["date"])


def parse_asfund(txt):
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "code" in parts:
            header = parts
            continue
        if header and "---" not in parts[0]:
            return {header[i]: parts[i] for i in range(min(len(header), len(parts)))}
    return None


def fnum(d, k):
    try:
        return float(d.get(k, 0))
    except Exception:
        return 0.0


def calc_board(amounts):
    n = len(amounts)
    if n < 105:
        return None
    today = amounts[-1]
    m30 = sum(amounts[n - 60:n - 30]) / 30.0
    m5_100 = sum(amounts[n - 105:n - 100]) / 5.0
    cjb30 = (today - m30) / m30 * 100 if m30 else 0
    b30v100 = m30 / m5_100 if m5_100 else 0
    recent = sum(amounts[n - 10:]) / 10.0
    prev = sum(amounts[n - 20:n - 10]) / 10.0
    veab = (recent - prev) / prev * 100 if prev else 0
    return {"cjb30": round(cjb30, 1), "b30v100": round(b30v100, 2), "veab": round(veab, 1)}


def classify(cjb30, precip):
    vol = "放量" if cjb30 > 50 else "缩量"
    if precip > 10:
        lv = "高"
    elif precip >= 5:
        lv = "中"
    else:
        lv = "低"
    m = {
        ("放量", "高"): "主力主导放量🔥(最强)",
        ("放量", "中"): "主力偏强放量",
        ("放量", "低"): "游资情绪",
        ("缩量", "高"): "主力控盘",
        ("缩量", "中"): "主力惜售",
        ("缩量", "低"): "情绪退潮",
    }
    return vol, lv, m[(vol, lv)]


def to_westock_code(code):
    if code.lower().startswith(("sh", "sz")):
        return code
    if code.startswith("60"):
        return "sh" + code
    if code.startswith(("000", "001", "002", "003")):
        return "sz" + code
    return code


def process(stock):
    code, name = stock
    wcode = to_westock_code(code)
    try:
        kr = parse_kline(run(["kline", wcode, "--period", "day", "--limit", "130"]))
        ar = parse_asfund(run(["asfund", wcode]))
        if not kr or not ar:
            return None
        amounts = [r["amount"] for r in kr]
        if len(amounts) < 105:
            return None
        bt = calc_board(amounts)
        if not bt:
            return None
        m5 = fnum(ar, "MainNetFlow5D")
        m10 = fnum(ar, "MainNetFlow10D")
        m20 = fnum(ar, "MainNetFlow20D")
        denom = sum(amounts[-5:])
        precip = m5 / denom * 100 if denom else 0.0
        vol, lv, sig = classify(bt["cjb30"], precip)
        return {
            "code": code, "name": name,
            "cjb30": bt["cjb30"], "b30v100": bt["b30v100"], "veab": bt["veab"],
            "precip": round(precip, 2), "m5": round(m5), "m10": round(m10), "m20": round(m20),
            "vol": vol, "lv": lv, "sig": sig,
            "price": kr[-1]["last"] if kr else 0,
        }
    except Exception as e:
        return {"code": code, "name": name, "error": str(e)}


def gen_report(results, dist, today):
    ordered = sorted(results, key=lambda r: (SIGNAL_ORDER.get(r["sig"], 9), -r["precip"]))
    L = []
    L.append(f"# 全盘量化报告（{today} 收盘）\n")
    L.append("> 范围：沪深主板（剔除科创板/创业板/北交所/ST），约 3000 只逐只扫描")
    L.append("> 双维口径：沉淀率 = MainNetFlow5D ÷ 近5日总成交额；CJB30 = (今日成交额 − 近30日均量)/近30日均量×100（>50% 为放量）\n")
    L.append("## 一、双维定性分布\n")
    L.append("| 定性 | 数量 |")
    L.append("|---|---|")
    for k, v in sorted(dist.items(), key=lambda x: SIGNAL_ORDER.get(x[0], 9)):
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## 二、重点标的（按信号强度 + 沉淀率降序，前 50）\n")
    L.append("| 代码 | 名称 | CJB30 | 沉淀率 | 5D主力净流(亿) | 定性 |")
    L.append("|---|---|---|---|---|---|")
    top = [r for r in ordered if r["sig"] in ("主力主导放量🔥(最强)", "游资情绪", "主力控盘")][:50]
    for r in top:
        L.append(f"| {r['code']} | {r['name']} | {r['cjb30']} | {r['precip']}% | {r['m5']/1e8:.2f} | {r['sig']} |")
    L.append("")
    L.append("## 三、主力信号专表（含低价标注 💰）\n")
    L.append("")
    main_force = [r for r in results if r["sig"] in ("主力主导放量🔥(最强)", "主力偏强放量", "主力控盘")]
    main_force.sort(key=lambda r: -r["precip"])
    L.append("| 代码 | 名称 | 价格(元) | 信号类型 | CJB30 | 沉淀率 | 5D主力净流(亿) | 低价池 |")
    L.append("|---|---|:---:|---|---|---|---|")
    for r in main_force:
        lp = "💰" if r.get("price", 999) < 10 else ""
        price_str = f"{r['price']:.2f}" if r.get("price", 0) else "N/A"
        L.append(f"| {r['code']} | {r['name']} | {price_str} | {r['sig']} | {r['cjb30']} | {r['precip']}% | {r['m5']/1e8:.2f} | {lp} |")
    L.append("")
    L.append("> 💰 = 股价<10元，适合做低价股池跟踪\n")
    L.append("")
    L.append("## 四、信号释义\n")
    L.append("- 主力主导放量🔥(最强)：放量且高沉淀，主力建仓特征，优先关注（四号是最强信号）")
    L.append("- 游资情绪：放量但低沉淀，情绪驱动，需结合技术确认")
    L.append("- 主力控盘：缩量高沉淀，筹码锁定，观察突破")
    L.append("- 数据由 GitHub Actions 自动扫描生成，回传 ima 知识库\n")
    open("panhou_lianghua.md", "w", encoding="utf-8").write("\n".join(L))


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "all_mainboard.csv"
    workers = int(os.environ.get("SCAN_WORKERS", "6"))
    rows = list(csv.DictReader(open(inp, encoding="utf-8")))
    stocks = [(r["code"], r["name"]) for r in rows]
    print(f"[INFO] total stocks={len(stocks)} workers={workers}")
    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process, s): s for s in stocks}
        for f in as_completed(futs):
            r = f.result()
            done += 1
            if r and "error" not in r and r.get("sig"):
                results.append(r)
            if done % 200 == 0:
                print(f"[PROGRESS] {done}/{len(stocks)} ok={len(results)}")
    with open("panhou_lianghua.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "price", "cjb30", "b30v100", "veab",
                                          "precip", "m5", "m10", "m20", "vol", "lv", "sig"])
        w.writeheader()
        for r in results:
            w.writerow(r)
    dist = Counter(r["sig"] for r in results)
    print("[DIST]", dict(dist))
    gen_report(results, dist, time.strftime("%Y-%m-%d"))
    print(f"[OK] scanned={len(results)} -> panhou_lianghua.csv + panhou_lianghua.md")


if __name__ == "__main__":
    main()
