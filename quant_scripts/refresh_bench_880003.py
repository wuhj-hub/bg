#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_bench_880003.py —— 880003 平均股价快照刷新（P1-5 运维补缺，2026-08-28）
============================================================
背景：bench_880003.json 是 tdx 快照，rsv_strength.py 读它计算 RSG，
     快照过期(>3天)会自动降级 399106。本脚本用于保持快照新鲜。

用法（tdx 是 MCP 工具，需在 ima 会话中用 tdx_kline 取数后传入）：
  1. 会话中调用 tdx_kline(code=880003, setcode=1, period=4, wantNum=25) 取最新日线
  2. 从返回提取 (date, close) 对，运行：
     python3 refresh_bench_880003.py --day "2026-08-28:28.90,2026-08-29:29.10" [--push]
  3. 周线数据由脚本自动从日线重建（按 ISO 周取最后交易日），无需手动传
  4. --push 推送到 GitHub（git_api_commit.py）

输出：更新 quant_scripts/bench_880003.json（updated 刷新为今天）
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timedelta

BENCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_880003.json")


def parse_pairs(s):
    """解析 "date:close,date:close" → [(date, float)]"""
    out = []
    for item in s.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 2:
            print(f"[WARN] 忽略无法解析: {item}", file=sys.stderr)
            continue
        d, c = parts[0].strip(), parts[1].strip()
        if len(d) == 8 and d.isdigit():  # 20260828 → 2026-08-28
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        try:
            out.append((d, round(float(c), 2)))
        except ValueError:
            print(f"[WARN] 忽略无法解析: {item}", file=sys.stderr)
    return out


def rebuild_week(day_rows, old_week_rows=None):
    """从日线重建周线（ISO 周取最后交易日收盘）。
    旧周线中"日线覆盖范围之前"的周保留（如 2025-08-29 补根，日线无此数据）"""
    def _key(r):
        return datetime.strptime(r["date"], "%Y-%m-%d").isocalendar()[:2]
    weeks = {_key(r): r for r in day_rows}
    if old_week_rows and day_rows:
        first_day = day_rows[0]["date"]
        for r in old_week_rows:
            if r["date"] < first_day and _key(r) not in weeks:
                weeks[_key(r)] = r
    return [{"date": weeks[k]["date"], "close": weeks[k]["close"]} for k in sorted(weeks.keys())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help='新增日线 "2026-08-28:28.90,2026-08-29:29.10"')
    ap.add_argument("--push", action="store_true", help="推送到 GitHub")
    a = ap.parse_args()

    if not os.path.exists(BENCH_PATH):
        print(f"[ERR] 快照不存在: {BENCH_PATH}", file=sys.stderr)
        sys.exit(1)
    bench = json.load(open(BENCH_PATH, encoding="utf-8"))
    before = len(bench["day"])

    # 合并新日线（去重：同日期保留新值）
    dmap = {r["date"]: r["close"] for r in bench["day"]}
    for d, c in parse_pairs(a.day):
        dmap[d] = c
    bench["day"] = [{"date": d, "close": dmap[d]} for d in sorted(dmap.keys())]

    # 重建周线（保留旧周线中日线覆盖外的补根）
    bench["week"] = rebuild_week(bench["day"], bench.get("week", []))
    bench["updated"] = datetime.now().strftime("%Y-%m-%d")

    json.dump(bench, open(BENCH_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 快照更新: 日线 {before} → {len(bench['day'])} 根 | 周线 {len(bench['week'])} 根 | updated={bench['updated']}")
    print(f"   最新: {bench['day'][-1]['date']} 收 {bench['day'][-1]['close']}")

    if a.push:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run(
            ["python3", "git_api_commit.py", "--msg", f"chore: 880003快照刷新 ({bench['updated']})",
             "quant_scripts/bench_880003.json"],
            capture_output=True, text=True, cwd=repo_root, timeout=120)
        print(r.stdout[-500:] if r.stdout else r.stderr[-300:])
        print("✅ 已推送 GitHub" if "完成" in (r.stdout or "") else "⚠️ 推送结果请确认")


if __name__ == "__main__":
    main()
