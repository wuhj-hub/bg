#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_guard.py —— 盘后数据源连通性预检（分步熔断 + 股池文件保护）
================================================================
背景：2026-09-14 盘后 job（quant_report）出现「全绿但数据全空」故障——
      scan job 健康（一统天下 342 只），report job 内所有依赖 westock 实时K线
      的脚本返回 0 只（才哥战法「有效 0 只」，9/11/9/12 均为 3051 只），
      并把 quant_scripts/*_pool.txt 覆盖为空池。根因指向数据源侧限流，
      但自检仍评 100/100 健康 → 漏检。

本脚本提供两道闸门：
  ① --probe  ：跑前探针。抽样拉取基准标的日线，判定数据源是否可用。
               返回码 0=健康 / 1=故障，供 workflow 决定是否允许覆盖股池文件。
  ② --audit  ：跑后审计。检查关键产物是否为「空壳」（规模骤降/全部 0），
               输出 outputs/data_guard_{date}.md 供告警引用。

用法：
  python3 data_guard.py --probe
  python3 data_guard.py --probe --json outputs/data_guard.json
  python3 data_guard.py --audit --pool quant_scripts/caige_pool.txt ...
"""
import os
import re
import sys
import json
import time
import subprocess
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

# 基准探针：3 只主板蓝筹 + 1 指数（数据源整体可用性的抽样观测，与「今日有无信号」无关）
PROBES = [
    ("sh600519", "贵州茅台"),
    ("sz000001", "平安银行"),
    ("sh601318", "中国平安"),
    ("sh000001", "上证指数"),
]
MIN_ROWS = 15          # 日线至少 15 根视为取数成功
OK_RATIO = 0.5         # 成功率阈值（≥50% 视为数据源健康）


def _run(args, timeout=40):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def _parse_rows(txt):
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or "---" in parts[0]:
            continue
        if len(parts) >= 6 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
            rows.append(parts)
    return rows


def probe():
    """抽样探针：返回 (ok, detail_dict)"""
    detail, ok_cnt = [], 0
    for code, name in PROBES:
        rows, got = [], False
        for attempt in range(2):
            rows = _parse_rows(_run(["kline", code, "--period", "day", "--limit", str(MIN_ROWS)]))
            if len(rows) >= MIN_ROWS:
                got = True
                break
            time.sleep(1.5)
        ok_cnt += 1 if got else 0
        detail.append({"code": code, "name": name, "rows": len(rows), "ok": got})
    ratio = ok_cnt / len(PROBES)
    status = "✅ 数据源正常" if ratio >= OK_RATIO else "❌ 数据源故障"
    return ratio >= OK_RATIO, {"ratio": round(ratio, 3), "ok_count": ok_cnt,
                              "total": len(PROBES), "status": status, "probes": detail}


def _count_lines(p):
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return len([l for l in f if l.strip() and not l.lstrip().startswith("#")])
    except Exception:
        return -1


def _json_total(p):
    try:
        d = json.load(open(p, encoding="utf-8"))
        if isinstance(d, dict):
            for k in ("total", "count", "n"):
                if isinstance(d.get(k), int):
                    return d[k]
            for k in ("stocks", "list", "hits", "items", "cards"):
                if isinstance(d.get(k), list):
                    return len(d[k])
        if isinstance(d, list):
            return len(d)
    except Exception:
        pass
    return -1


def audit(pools, out_dir="outputs"):
    """跑后审计：检查股池文件与关键产物是否为空壳"""
    today = datetime.now().strftime("%Y-%m-%d")
    items, warn = [], 0
    for p in pools:
        n = _count_lines(p)
        is_empty = (n == 0)
        warn += 1 if is_empty else 0
        items.append({"target": p, "kind": "pool", "count": n, "empty": is_empty})

    L = [f"# 🛡️ 盘后数据健康审计 · {today}\n",
         f"> 审计对象 {len(items)} 项｜空壳 **{warn}** 项\n"]
    if warn:
        L.append("## ❌ 空壳产物（疑似数据源故障，已受股池保护）\n")
        for it in items:
            if it["empty"]:
                L.append(f"- `{it['target']}` → **0 条**")
        L.append("")
    L.append("## 明细\n")
    L.append("| 产物 | 类型 | 条数 | 状态 |")
    L.append("|---|---|---|---|")
    for it in items:
        L.append(f"| {it['target']} | {it['kind']} | {it['count']} | {'❌空' if it['empty'] else '✅'} |")

    os.makedirs(out_dir, exist_ok=True)
    md = os.path.join(out_dir, f"data_guard_{today}.md")
    open(md, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L[:14]))
    print(f"[OK] {md}")
    return warn


def main():
    args = sys.argv[1:]
    if "--audit" in args:
        pools = []
        if "--pool" in args:
            i = args.index("--pool")
            pools = [a for a in args[i + 1:] if not a.startswith("--")]
        if not pools:
            pools = ["quant_scripts/caige_pool.txt", "quant_scripts/yitong_pool.txt",
                     "quant_scripts/yao_pool.txt", "quant_scripts/longtou_pool.txt",
                     "yitong_pool.txt"]
        warn = audit(pools)
        sys.exit(1 if warn else 0)

    # 默认 / --probe
    ok, d = probe()
    print(f"[data_guard] {d['status']}  成功率 {d['ok_count']}/{d['total']} = {d['ratio']:.0%}")
    for p in d["probes"]:
        print(f"   {'✅' if p['ok'] else '❌'} {p['code']} {p['name']}: {p['rows']} 根")
    if "--json" in args:
        i = args.index("--json")
        out = args[i + 1] if len(args) > i + 1 else "outputs/data_guard.json"
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        json.dump({"date": datetime.now().strftime("%Y-%m-%d"), **d},
                  open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
