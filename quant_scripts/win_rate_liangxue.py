#!/usr/bin/env python3
"""
win_rate_liangxue.py —— 量学信号胜率统计（2026-08-30）
=====================================================
读 liangxue_signals_log.csv（量学扫描每日累积的PASS信号），
对每个信号拉取后续K线，计算 T+1 / T+3 / T+5 收益，输出胜率报告。

用法：
  python3 win_rate_liangxue.py                    # 统计全部历史信号
  python3 win_rate_liangxue.py --days 5           # 只统计最近5天的信号
  python3 win_rate_liangxue.py --refresh          # 强制刷新已算过的信号

输出：outputs/liangxue_winrate_latest.json + stdout 报告
说明：日志仅积累中（2026-08-30 起），样本少时输出占位提示，随积累自动充实。
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
CACHE_FILE = "outputs/liangxue_winrate_cache.json"  # 已算信号缓存（增量）

def norm(code):
    code = str(code).strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    return ("sh" if code.startswith(("6", "9", "5")) else "sz") + code


def cli(args, timeout=120):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def fetch_after_rows(code, signal_date, days=8):
    """拉信号日之后的K线（含信号日），返回 {date: close} 升序"""
    txt = cli(["kline", norm(code), "--period", "day", "--limit", "20", "--fq", "qfq"])
    rows = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 4 or "date" in parts[0] or "---" in parts[0]:
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
            try:
                rows.append((parts[0], float(parts[3])))
            except (ValueError, IndexError):
                pass
    rows.sort()
    # 找信号日位置
    idx = None
    for i, (dt, _) in enumerate(rows):
        if dt >= signal_date:
            idx = i
            break
    if idx is None:
        return {}
    out = {}
    for dt, c in rows[idx:idx + days]:
        out[dt] = c
    return out


def calc_returns(signal):
    """计算信号后续收益：返回 {t1, t3, t5, base_close, last_date} 或 None"""
    code, date, close = signal["code"], signal["date"], signal["close"]
    try:
        base = float(close)
        after = fetch_after_rows(code, date, days=8)
        if len(after) < 2:
            return None
        dates = sorted(after.keys())
        # 信号日收盘为基准，找 T+1/T+3/T+5
        ret = {}
        base_date = None
        for dt in dates:
            if dt >= date:
                base_date = dt
                break
        if base_date is None:
            return None
        base_close = after[base_date] if base > 0 else base
        for n, key in ((1, "t1"), (3, "t3"), (5, "t5")):
            target = dates[dates.index(base_date) + n] if dates.index(base_date) + n < len(dates) else None
            if target and base_close > 0:
                ret[key] = round((after[target] / base_close - 1) * 100, 2)
        if not ret:
            return None
        return {"base_close": round(base_close, 2), "last_date": dates[-1], **ret}
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="只统计最近N天信号")
    ap.add_argument("--refresh", action="store_true", help="强制重算所有信号")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    log_path = "outputs/liangxue_signals_log.csv"
    if not os.path.exists(log_path):
        print(f"[ERR] 信号日志不存在: {log_path}（需先运行 liangxue_screener.py 积累）", file=sys.stderr)
        sys.exit(1)

    # 读信号日志
    signals = []
    with open(log_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            signals.append({"date": row["date"], "code": row["code"], "name": row["name"],
                            "close": row["close"], "score": row["score"], "signals": row["signals"]})
    if args.days:
        cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        signals = [s for s in signals if s["date"] >= cutoff]
    if not signals:
        print("无信号样本")
        return

    # 读缓存（增量计算）
    cache = {}
    if os.path.exists(CACHE_FILE) and not args.refresh:
        try:
            cache = json.load(open(CACHE_FILE, encoding="utf-8"))
        except Exception:
            cache = {}

    # 计算未缓存信号的收益
    todo = []
    for s in signals:
        key = f"{s['date']}_{s['code']}"
        if key not in cache:
            todo.append(s)

    print(f"[INFO] 信号 {len(signals)} 条，待计算 {len(todo)} 条（缓存 {len(cache)}）", file=sys.stderr)
    results = {}
    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for s, r in zip(todo, ex.map(calc_returns, todo)):
                key = f"{s['date']}_{s['code']}"
                if r:
                    cache[key] = {"date": s["date"], "code": s["code"], "name": s["name"],
                                  "score": s["score"], "signals": s["signals"], "returns": r}
        os.makedirs("outputs", exist_ok=True)
        json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 统计
    valid = [v for v in cache.values() if v.get("returns")]
    if len(valid) < 3:
        print(f"⚠️ 有效样本仅 {len(valid)} 条（信号日志 2026-08-30 起积累），待积累后自动充实")
        json.dump({"date": datetime.now().strftime("%Y-%m-%d"), "samples": len(valid),
                   "note": "样本不足，待积累"}, open("outputs/liangxue_winrate_latest.json", "w"),
                 ensure_ascii=False, indent=1)
        return

    def win_rate(key):
        vals = [v["returns"].get(key) for v in valid if v["returns"].get(key) is not None]
        if not vals:
            return None
        win = sum(1 for x in vals if x > 0)
        return {"n": len(vals), "win": win, "rate": round(win / len(vals) * 100, 1),
                "avg": round(sum(vals) / len(vals), 2)}

    t1, t3, t5 = win_rate("t1"), win_rate("t3"), win_rate("t5")

    # 按评分分层
    high = [v for v in valid if int(v.get("score", 0)) >= 95]
    mid = [v for v in valid if 85 <= int(v.get("score", 0)) < 95]
    layer = {}
    for name, grp in (("≥95分", high), ("85-94分", mid)):
        vals3 = [v["returns"].get("t3") for v in grp if v["returns"].get("t3") is not None]
        if len(vals3) >= 3:
            win = sum(1 for x in vals3 if x > 0)
            layer[name] = {"n": len(vals3), "t3_rate": round(win / len(vals3) * 100, 1),
                           "t3_avg": round(sum(vals3) / len(vals3), 2)}

    out = {"date": datetime.now().strftime("%Y-%m-%d"), "samples": len(valid),
           "t1": t1, "t3": t3, "t5": t5, "layer": layer}
    json.dump(out, open("outputs/liangxue_winrate_latest.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"✅ outputs/liangxue_winrate_latest.json")

    print(f"\n📊 量学PASS信号胜率统计（样本 {len(valid)} 条，{cache_file_date() if False else '信号日志累积'}）")
    print(f"{'周期':<6}{'样本':<6}{'盈利':<6}{'胜率':<8}{'平均收益'}")
    for k, v in (("T+1", t1), ("T+3", t3), ("T+5", t5)):
        if v:
            print(f"{k:<6}{v['n']:<6}{v['win']:<6}{v['rate']}%   {v['avg']}%")
    if layer:
        print(f"\n分层(T+3):")
        for name, v in layer.items():
            print(f"  {name}: {v['n']}条 胜率{v['t3_rate']}% 均{v['t3_avg']}%")


def cache_file_date():
    return ""


if __name__ == "__main__":
    main()
