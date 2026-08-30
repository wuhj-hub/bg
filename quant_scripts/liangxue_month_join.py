#!/usr/bin/env python3
"""
liangxue_month_join.py —— 量学 × 曾星智月线闸门 联合输出（2026-08-30）
========================================================================
量学PASS（黑马王子量价信号） ∩ 月线闸门（曾星智 MA6/MA12 方向）联合池：
  - 曾星智月线闸门 PASS(多头)  = 月线定方向（顺势）
  - 量学 PASS(≥85)             = 量学定买点（量价共振）
  - 联合 = 趋势+量价双确认（SKILL 2.16 衔接逻辑落地）

用法：
  python3 liangxue_month_join.py [--json outputs/liangxue_latest.json] [--limit 0]
输出：
  - stdout: 联合池分级列表
  - outputs/liangxue_month_join_latest.json：{PASS(月线多头∩量学), WARN(纠缠), BLOCK(月线空头)}
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]


def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def month_gate(code):
    """月线闸门（复用 signal_arbiter 逻辑）：PASS(收盘>MA6>MA12) / WARN / BLOCK"""
    txt = run(["kline", code, "--period", "month", "--limit", "12"])
    closes = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and re.match(r"^\|\s*20\d{2}", s):
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 4 and parts[3]:
                try:
                    closes.append(float(parts[3]))
                except ValueError:
                    continue
    if len(closes) < 6:
        return "?"
    cur = closes[0]
    ma6 = sum(closes[:6]) / 6
    ma12 = sum(closes[:min(12, len(closes))]) / min(12, len(closes)) if len(closes) >= 10 else ma6
    if cur > ma6 > ma12:
        return "PASS"
    if cur > ma6:
        return "WARN"
    return "BLOCK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="outputs/liangxue_latest.json")
    ap.add_argument("--limit", type=int, default=0, help="只处理前N只PASS（调试用）")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if not os.path.exists(args.json):
        print(f"[ERR] 量学JSON不存在: {args.json}", file=sys.stderr)
        sys.exit(1)
    d = json.load(open(args.json, encoding="utf-8"))
    passes = [s for s in d.get("signals", []) if s.get("level") == "PASS"]
    if args.limit:
        passes = passes[:args.limit]
    print(f"[INFO] 量学PASS {len(passes)} 只 → 逐只月线闸门校验...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        gates = list(ex.map(lambda s: (s, month_gate(s["code"])), passes))

    join, warn, block, na = [], [], [], []
    for s, g in gates:
        item = {"code": s["code"], "name": s.get("name", ""), "score": s.get("score"),
                "close": s.get("close"), "sigs": [x["type"] for x in s.get("signals", [])],
                "month": g}
        if g == "PASS":
            join.append(item)
        elif g == "WARN":
            warn.append(item)
        elif g == "BLOCK":
            block.append(item)
        else:
            na.append(item)

    join.sort(key=lambda x: -x["score"])
    out = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "desc": "量学PASS ∩ 曾星智月线闸门：月线定方向+量学定买点（趋势+量价双确认）",
        "pass_total": len(passes),
        "join_count": len(join), "warn_count": len(warn),
        "block_count": len(block), "na_count": len(na),
        "join": join, "warn": warn[:30], "block": block[:20],
    }
    os.makedirs("outputs", exist_ok=True)
    json.dump(out, open("outputs/liangxue_month_join_latest.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"✅ outputs/liangxue_month_join_latest.json")

    print(f"\n量学×月线联合池: 量学PASS {len(passes)} → 月线PASS(联合) {len(join)} | WARN {len(warn)} | BLOCK {len(block)} | 无数据 {len(na)}")
    print(f"{'代码':<10}{'名称':<8}{'量学分':<6}{'月线':<5} 信号")
    for it in join[:25]:
        sigs = ",".join(it["sigs"][:3])
        print(f"{it['code']:<10}{it['name']:<8}{it['score']:<6}{it['month']:<5} {sigs}")


if __name__ == "__main__":
    main()
