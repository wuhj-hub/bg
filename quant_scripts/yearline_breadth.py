#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yearline_breadth.py —— 年线广度指标（站上年线个股占比）
=========================================================
方法论来源：V纪元《用这个指标判断市场牛熊》（2026-07-26）
  核心逻辑：统计沪深主板中「收盘价 ≥ MA250(年线)」的个股数量与占比，
           作为市场牛熊结构的中期广度指标（季度级，与日频宽度互补）。

数据源：
  - 主板清单 all_mainboard.csv（qt.gtimg.cn 生成，列: code,name）
  - westock-data-skillhub technical 批量（--group ma 含 ma.MA_250）

输出：
  - outputs/年线广度_{date}.md            报告
  - outputs/yearline_breadth_latest.json  结构化JSON（供盘前/复盘引用）

用法：
  python3 yearline_breadth.py                     # 全量计算（~3100只，63批，约5-10分钟）
  python3 yearline_breadth.py --list xxx.csv      # 指定清单
  python3 yearline_breadth.py --batch 50          # 每批数量（默认50）
  python3 yearline_breadth.py --quick 36 3188     # 快速模式：外部已算好分子/分母

经验阈值（参考文章+历史极值，待积累校准）：
  >60% 牛市结构 / 40-60% 结构分化 / <40% 熊市结构 / <20% 深度熊
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]


def cli(args, timeout=90):
    """执行 westock CLI，返回原始输出；失败返回 None。"""
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        out = r.stdout or ""
        if "执行失败" in out or "error" in out.lower()[:500]:
            return None
        return out
    except Exception as e:
        print(f"[WARN] cli {args[:3]} failed: {e}", file=sys.stderr)
        return None


def norm_code(code):
    """纯数字code -> sh/sz前缀。"""
    code = code.strip()
    if code.startswith(("sh", "sz")):
        return code
    if code.startswith(("6", "9", "5")):
        return "sh" + code
    return "sz" + code


def parse_technical_table(raw):
    """
    解析 technical 批量输出表（Markdown表格）。
    返回 [{code,name,date,close,ma250}, ...]
    """
    rows = []
    lines = [l.strip() for l in raw.splitlines() if l.strip().startswith("|")]
    if len(lines) < 3:
        return rows
    header = [h.strip() for h in lines[0].strip("|").split("|")]
    try:
        idx_name = header.index("name")
        idx_close = header.index("closePrice")
        idx_ma250 = header.index("ma.MA_250")
    except ValueError:
        return rows
    idx_code = 0
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) <= idx_ma250:
            continue
        try:
            close = float(cells[idx_close])
        except ValueError:
            continue
        ma250_raw = cells[idx_ma250]
        if ma250_raw in ("-", "", "None"):
            continue
        try:
            ma250 = float(ma250_raw)
        except ValueError:
            continue
        if ma250 <= 0:
            continue
        rows.append({
            "code": cells[idx_code],
            "name": cells[idx_name],
            "date": cells[2] if len(cells) > 2 else "",
            "close": close,
            "ma250": ma250,
        })
    return rows


def load_list(path):
    """读 all_mainboard.csv，返回 [(code, name), ...]。"""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and row[0] and row[0].lower() != "code":
                name = row[1].strip() if len(row) > 1 else ""
                out.append((row[0].strip(), name))
    return out


def scan_full(stocks, batch=50):
    """批量调 westock technical，返回 {code: {name, close, ma250, above}, ...}"""
    result = {}
    n = len(stocks)
    for i in range(0, n, batch):
        chunk = stocks[i:i + batch]
        codes = ",".join(norm_code(c) for c, _ in chunk)
        raw = None
        for attempt in range(3):
            raw = cli(["technical", codes, "--group", "ma"])
            if raw and "[Batch]" in raw:
                break
            time.sleep(2)
        got = parse_technical_table(raw) if raw else []
        got_map = {r["code"]: r for r in got}
        # 缺失补查：单只查询最可靠（批量偶发缺行/僵尸代码）
        for code, name in chunk:
            wcode = norm_code(code)
            if wcode not in got_map:
                for attempt in range(2):
                    raw1 = cli(["technical", wcode, "--group", "ma"])
                    r1 = parse_technical_table(raw1)
                    if r1:
                        got_map[wcode] = r1[0]
                        break
                    time.sleep(1)
        if len(got_map) < len(chunk):
            miss = [c for c, _ in chunk if norm_code(c) not in got_map]
            print(f"[WARN] batch {i} missing {len(miss)}: {miss[:5]}", file=sys.stderr)
        for code, name in chunk:
            wcode = norm_code(code)
            if wcode in got_map:
                r = got_map[wcode]
                halt = (r["close"] == r["ma250"])  # 停牌/僵尸股：现价=年线精确相等
                result[code] = {
                    "name": r["name"] or name,
                    "close": r["close"],
                    "ma250": r["ma250"],
                    "above": None if halt else (r["close"] >= r["ma250"]),
                    "halt": halt,
                }
            else:
                result[code] = {"name": name, "close": None, "ma250": None, "above": None, "halt": False}
        if (i // batch) % 10 == 0:
            done = sum(1 for v in result.values() if v["close"] is not None)
            print(f"[INFO] {i}/{n} queried, valid={done}", file=sys.stderr)
    return result


def build_report(stats, stocks, results, date_str):
    """生成 Markdown 报告。"""
    total = stats["total"]
    above = stats["above"]
    ratio = stats["ratio"]
    if stats["ratio"] >= 60:
        level = "🟢 牛市结构"
    elif stats["ratio"] >= 40:
        level = "🟡 结构分化"
    elif stats["ratio"] >= 20:
        level = "🟠 熊市结构"
    else:
        level = "🔴 深度熊市"
    lines = []
    lines.append(f"# 年线广度指标（站上年线个股占比）— {date_str}\n")
    lines.append(f"> 口径：沪深主板 {total} 只（qt.gtimg.cn 清单）｜收盘价 ≥ MA250(年线) 计为站上年线\n")
    lines.append("## 核心数据\n")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 主板总数 | {total} |")
    lines.append(f"| 站上年线 | **{above}**（{ratio:.1f}%） |")
    lines.append(f"| 年线下方 | {total - above}（{100 - ratio:.1f}%） |")
    lines.append(f"| 市场结构 | {level} |")
    lines.append("")
    lines.append("### 参考阈值")
    lines.append("- >60% 牛市结构 / 40-60% 结构分化 / <40% 熊市结构 / <20% 深度熊")
    lines.append("")
    # 站上年线明细
    above_list = [s for s in stocks if results.get(s[0], {}).get("above") is True]
    above_list.sort(key=lambda s: results[s[0]]["close"] / results[s[0]]["ma250"])
    lines.append(f"## 站上年线个股（{len(above_list)} 只）\n")
    lines.append("| 代码 | 名称 | 现价 | MA250 | 距年线 |")
    lines.append("|---|---|---|---|---|")
    for code, name in above_list[:80]:
        r = results[code]
        dist = (r["close"] / r["ma250"] - 1) * 100
        lines.append(f"| {code} | {r['name']} | {r['close']:.2f} | {r['ma250']:.2f} | +{dist:.1f}% |")
    if len(above_list) > 80:
        lines.append(f"| ... 其余 {len(above_list) - 80} 只省略 |")
    lines.append("")
    # 对比参考
    lines.append("## 参考：文章历史序列（全A口径）")
    lines.append("- 2026-04底 2923 / 05底 2166 / 06底 1603 / 07底 863（V纪元，占比约16%）")
    lines.append("")
    lines.append("---")
    lines.append("*本报告由 yearline_breadth.py 自动生成，量化规律总结非投资建议*")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="all_mainboard.csv")
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--quick", nargs=2, type=int, metavar=("ABOVE", "TOTAL"),
                    help="快速模式：直接给定分子/分母，跳过全量扫描")
    ap.add_argument("--outdir", default="outputs")
    args = ap.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(args.outdir, exist_ok=True)

    if args.quick:
        above, total = args.quick
        ratio = above / total * 100
        stats = {"total": total, "above": above, "ratio": ratio, "mode": "quick"}
        results = {}
        stocks = []
    else:
        if not os.path.exists(args.list):
            print(f"[ERR] list not found: {args.list}", file=sys.stderr)
            sys.exit(1)
        stocks = load_list(args.list)
        print(f"[INFO] loaded {len(stocks)} stocks from {args.list}", file=sys.stderr)
        results = scan_full(stocks, batch=args.batch)
        valid = {c: v for c, v in results.items() if v["above"] is not None}
        above = sum(1 for v in valid.values() if v["above"])
        total = len(valid)
        ratio = above / total * 100 if total else 0
        stats = {"total": total, "above": above, "ratio": ratio, "mode": "full"}

    stats["date"] = date_str
    md = build_report(stats, stocks, results, date_str)

    md_path = os.path.join(args.outdir, f"年线广度_{date_str}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    # 结构化JSON
    above_list = []
    for code, v in results.items():
        if v.get("above") is True:
            above_list.append({
                "code": code, "name": v["name"],
                "close": v["close"], "ma250": v["ma250"],
                "dist_pct": round((v["close"] / v["ma250"] - 1) * 100, 1),
            })
    above_list.sort(key=lambda x: x["dist_pct"])  # 距年线升序：临界标的在前
    json_out = {
        "date": date_str,
        "total": stats["total"],
        "above": stats["above"],
        "ratio_pct": round(stats["ratio"], 1),
        "mode": stats["mode"],
        "level": ("bull" if stats["ratio"] >= 60 else
                  "mixed" if stats["ratio"] >= 40 else
                  "bear" if stats["ratio"] >= 20 else "deep_bear"),
        "above_stocks": above_list[:200],
        "above_count_full": len(above_list),
        "above_codes": [s["code"] for s in above_list],
        "thresholds": {"bull": 60, "mixed": 40, "bear": 20},
    }
    jpath = os.path.join(args.outdir, "yearline_breadth_latest.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(json_out, f, ensure_ascii=False, indent=2)

    print(f"[OK] 站上年线 {stats['above']}/{stats['total']} = {stats['ratio']:.1f}%")
    print(f"[OK] {md_path}")
    print(f"[OK] {jpath}")


if __name__ == "__main__":
    main()
