#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_123_2b.py —— 123法则 / 2B法则 / ABC修正 反转扫描器
========================================================
《专业投机原理》L3 结构确认触发器（Victor Sperandeo）：
  - 123法则：趋势线破位 + 未创新高/低 + 反向突破次高点/低点 → 反转确认
  - 2B法则 ：创新高/低后迅速拉回原区间 → 假突破（高弹性反转，小仓试错）
  - ABC修正：三波修正（A跌/B反弹/C再跌）C浪末端与123协同

与现有反转体系互补：月线反转/反转数值=形态类（大周期），本扫描器=结构类（日线确认）。

用法：
  python3 scan_123_2b.py --pool stock_pool.txt          # 从池文件扫描
  python3 scan_123_2b.py --pool "sh600519,sz000001"     # 指定代码
  python3 scan_123_2b.py --pool panhou_lianghua.csv --panhou   # 从panhou csv读池
  python3 scan_123_2b.py --limit 200                    # 只扫前200只（默认池）

输出：outputs/123_2b反转信号_{date}.md + 123_2b_latest.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]


def cli(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def norm(code):
    code = str(code).strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    return ("sh" if code.startswith(("6", "9", "5")) else "sz") + code


def parse_kline(txt, limit=90):
    """解析日K线（升序），返回 [{date, open, high, low, close}, ...]"""
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or "---" in parts[0] or len(parts) < 6:
            continue
        try:
            di = header.index("date")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                continue
            row = {"date": parts[di]}
            for key, hk in (("open", "open"), ("high", "high"), ("low", "low"), ("close", "last")):
                if hk in header:
                    row[key] = float(parts[header.index(hk)])
            rows.append(row)
        except (ValueError, IndexError):
            pass
    rows.sort(key=lambda r: r["date"])
    return rows[-limit:] if limit else rows


def trendline_slope(rows, window=5):
    """最近window根收盘的线性趋势（简化：用首尾差/根数）"""
    if len(rows) < window + 1:
        return 0
    recent = rows[-window:]
    return (recent[-1]["close"] - recent[0]["close"]) / window


def detect_123(rows):
    """123法则检测（做多版本：下降趋势反转向上）
    返回 (信号, 说明) 或 (None, None)
    ① 突破下降趋势线（近N日高点连线下压被突破）
    ② 回踩未创新低
    ③ 突破前一个次高点
    """
    if len(rows) < 30:
        return None, None
    # 找最近20日的 swing 高低点
    window = 20
    recent = rows[-window:]
    # ② 回踩未创新低：当前低点 > 前期低点
    lows = [r["low"] for r in recent[:-3]]
    cur_low = min(r["low"] for r in recent[-3:])
    if lows and cur_low <= min(lows):
        return None, None
    # ③ 突破前一个次高点：最近收盘 > 前20日内的次高点
    highs = [r["high"] for r in recent[:-1]]
    if not highs:
        return None, None
    prev_high = max(highs[:-3]) if len(highs) > 3 else max(highs)
    cur_close = recent[-1]["close"]
    if cur_close <= prev_high:
        return None, None
    # ① 趋势线突破：近10日最低点连线是否被突破（简化：现价站上5日线且5日线拐头）
    closes = [r["close"] for r in rows[-10:]]
    ma5 = sum(closes[-5:]) / 5
    ma5_prev = sum(closes[-6:-1]) / 5 if len(closes) >= 6 else ma5
    if cur_close > ma5 and ma5 > ma5_prev:
        return ("123买入", f"突破次高{prev_high:.2f}+回踩未创新低+5日线拐头")
    return None, None


def detect_2b(rows):
    """2B法则检测（做多版本：创新低后迅速收回 → 假突破买入）
    做空版本：创新高后迅速跌破前高 → 风险警示
    返回 [(信号, 说明), ...]
    """
    out = []
    if len(rows) < 25:
        return out
    recent = rows[-25:]
    # 做多2B：近期创20日新低，随后N日内收回新低之上
    lows = [r["low"] for r in recent]
    min_low = min(lows)
    min_idx = lows.index(min_low)
    if min_idx <= len(lows) - 4 and min_idx >= 1:  # 新低在3-20日前
        after = lows[min_idx + 1:]
        if after and min(after) > min_low and recent[-1]["close"] > min_low * 1.02:
            out.append(("2B买入", f"创{min_idx+1}日前新低{min_low:.2f}后收回(+2%)"))
    # 做空2B（风险）：近期创20日新高后跌破前高
    highs = [r["high"] for r in recent]
    max_high = max(highs)
    max_idx = highs.index(max_high)
    if max_idx <= len(highs) - 4 and max_idx >= 1:
        after_h = highs[max_idx + 1:]
        if after_h and max(after_h) < max_high and recent[-1]["close"] < max_high * 0.98:
            out.append(("2B风险", f"创{max_idx+1}日前新高{max_high:.2f}后跌破(-2%)"))
    return out


def detect_abc(rows):
    """ABC修正末端检测（C浪末端：连续下跌后缩量企稳+低点抬高）"""
    if len(rows) < 30:
        return None, None
    recent = rows[-15:]
    closes = [r["close"] for r in recent]
    lows = [r["low"] for r in recent]
    # C浪特征：近10日下跌（收盘连续走低）后近3日止跌（低点抬高）
    if closes[-10] > closes[-3] and lows[-3] > lows[-5] > lows[-8]:
        return ("ABC末端", "C浪下跌后低点抬高（止跌企稳）")
    return None, None


def analyze(code, name=""):
    """单只检测，返回 {code, name, signals: [...]}"""
    txt = cli(["kline", code, "--period", "day", "--limit", "90", "--fq", "qfq"])
    rows = parse_kline(txt)
    if len(rows) < 30:
        return None
    sigs = []
    s123, d123 = detect_123(rows)
    if s123:
        sigs.append({"type": s123, "desc": d123})
    for s2b, d2b in detect_2b(rows):
        sigs.append({"type": s2b, "desc": d2b})
    sabc, dabc = detect_abc(rows)
    if sabc:
        sigs.append({"type": sabc, "desc": dabc})
    if not sigs:
        return None
    return {"code": code, "name": name, "close": rows[-1]["close"],
            "date": rows[-1]["date"], "signals": sigs}


def load_pool(args):
    """加载候选池：--pool 文件或代码列表，或默认 stock_pool.txt"""
    pool = []
    p = args.pool
    if not p:
        p = "quant_scripts/stock_pool.txt"
        if not os.path.exists(p):
            p = "stock_pool.txt"
    if "," in p and not os.path.exists(p):
        # 代码列表
        for c in p.split(","):
            c = c.strip()
            if c:
                pool.append((norm(c), ""))
        return pool
    if not os.path.exists(p):
        print(f"[ERR] 池文件不存在: {p}", file=sys.stderr)
        sys.exit(1)
    if p.endswith(".csv"):
        import csv
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                code = (row.get("code") or "").strip()
                name = (row.get("name") or "").strip()
                if code and "ST" not in name.upper() and "退" not in name:
                    pool.append((norm(code), name))
    else:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                code = ln.replace("#", ",").split(",")[0].strip()
                name = ln.split("#")[-1].strip() if "#" in ln else ""
                if code:
                    pool.append((norm(code), name))
    return pool


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="", help="池文件或代码列表")
    ap.add_argument("--limit", type=int, default=0, help="仅扫前N只")
    ap.add_argument("--outdir", default="outputs")
    args = ap.parse_args()

    pool = load_pool(args)
    if args.limit:
        pool = pool[:args.limit]
    print(f"[INFO] 123/2B扫描: {len(pool)} 只", file=sys.stderr)

    results = []
    def _one(item):
        code, name = item
        r = analyze(code, name)
        if r:
            # ST/退市兜底
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from st_guard import check_st_batch
                st, _ = check_st_batch([code])
                if st:
                    return None
            except Exception:
                pass
        return r

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(_one, pool):
            if r:
                results.append(r)

    # 输出
    os.makedirs(args.outdir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    buy = [r for r in results if any(s["type"] in ("123买入", "2B买入") for s in r["signals"])]
    risk = [r for r in results if any(s["type"] in ("2B风险",) for s in r["signals"])]
    abc = [r for r in results if any(s["type"] == "ABC末端" for s in r["signals"])]

    md = [f"# ⚡ 123/2B/ABC 反转信号 {date_str}", "",
          f"> 候选池 {len(pool)} 只｜检出 {len(results)} 只（买入 {len(buy)} / 风险 {len(risk)} / ABC末端 {len(abc)}）",
          "> 方法论：维克多·斯波朗迪《专业投机原理》L3 结构确认触发器", "",
          "## 🟢 买入候选（123/2B）", "",
          "| 代码 | 名称 | 现价 | 信号 | 说明 |",
          "|:----|:----|:----:|:----|:----|"]
    for r in sorted(buy, key=lambda x: -x["close"]):
        for s in r["signals"]:
            if s["type"] in ("123买入", "2B买入"):
                md.append(f"| {r['code']} | {r['name']} | {r['close']} | {s['type']} | {s['desc']} |")
    md += ["", "## 🔴 风险警示（2B风险）", "",
           "| 代码 | 名称 | 现价 | 信号 | 说明 |",
           "|:----|:----|:----:|:----|:----|"]
    for r in sorted(risk, key=lambda x: -x["close"]):
        for s in r["signals"]:
            if s["type"] == "2B风险":
                md.append(f"| {r['code']} | {r['name']} | {r['close']} | {s['type']} | {s['desc']} |")
    md += ["", "## 🌀 ABC修正末端", "",
           "| 代码 | 名称 | 现价 | 信号 | 说明 |",
           "|:----|:----|:----:|:----|:----|"]
    for r in abc:
        for s in r["signals"]:
            if s["type"] == "ABC末端":
                md.append(f"| {r['code']} | {r['name']} | {r['close']} | {s['type']} | {s['desc']} |")
    md += ["", "---", "*本报告由 scan_123_2b.py 自动生成，量化规律总结非投资建议*"]
    md_path = os.path.join(args.outdir, f"123_2b反转信号_{date_str}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    js = {"date": date_str, "pool": len(pool), "total": len(results),
          "buy": buy, "risk": risk, "abc": abc}
    with open(os.path.join(args.outdir, "123_2b_latest.json"), "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1)
    print(f"[OK] 买入{len(buy)} 风险{len(risk)} ABC{len(abc)} -> {md_path}")


if __name__ == "__main__":
    main()
