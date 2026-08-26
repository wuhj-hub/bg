#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_month_reversal.py —— 月线反转信号回测 v1.0
===================================================
对沪深主板样本股逐月回放「月线反转信号」（曾星智+陶博士体系），
统计信号出现后未来 1/3/6 个月的收益、胜率、盈亏比。

信号定义（与 month_frame.py 一致）：
  - 平台突破: 本月收盘 > 前11个月最高 且 收盘 > MA6(半年线)
  - 均线金叉: MA6 本月上穿 MA12（上月MA6<=上月MA12，本月MA6>MA12）
  - 趋势确立: MA6>MA12 且 收盘>MA6 且 MA6较上月上行

样本：主板清单随机抽样（默认300只），月K线36个月（2024-01起回放）

用法：
  python3 backtest_month_reversal.py --limit 300 --workers 8
  python3 backtest_month_reversal.py --limit 300 --start 2024-01
"""
import subprocess, sys, os, re, json, random, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_month_kline(txt):
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
        if len(parts) >= 6:
            try:
                di = header.index("date"); ci = header.index("last")
                if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                    rows.append({"date": parts[di], "close": float(parts[ci])})
            except (ValueError, IndexError):
                pass
    rows.sort(key=lambda r: r["date"])
    return rows

def detect_signals(closes):
    """逐月检测月线反转信号，返回 [{month_idx, type}]（month_idx为月线数组下标，需>=12）"""
    sigs = []
    n = len(closes)
    for i in range(12, n):  # 需要12个月窗口
        cur = closes[i]
        ma6 = sum(closes[i-5:i+1]) / 6
        ma12 = sum(closes[i-11:i+1]) / 12
        ma6_prev = sum(closes[i-6:i]) / 6
        ma12_prev = sum(closes[i-12:i]) / 12
        # 平台突破: cur > 前11个月最高收盘
        prev_max = max(closes[i-11:i])
        if cur > prev_max and cur > ma6:
            sigs.append({"idx": i, "type": "平台突破"})
            continue
        # 均线金叉
        if ma6 > ma12 and ma6_prev <= ma12_prev:
            sigs.append({"idx": i, "type": "均线金叉"})
            continue
        # 趋势确立
        if ma6 > ma12 and cur > ma6 and ma6 > ma6_prev:
            sigs.append({"idx": i, "type": "趋势确立"})
    return sigs

def backtest_stock(code):
    """对单只股票回测，返回所有信号样本"""
    samples = []
    for attempt in range(3):
        txt = run(["kline", code, "--period", "month", "--limit", "36"])
        rows = parse_month_kline(txt)
        if rows:
            break
    if len(rows) < 18:
        return samples
    closes = [r["close"] for r in rows]
    dates = [r["date"] for r in rows]
    sigs = detect_signals(closes)
    for s in sigs:
        i = s["idx"]
        for horizon in (1, 3, 6):
            j = i + horizon
            if j < len(closes):
                ret = (closes[j] / closes[i] - 1) * 100
                samples.append({"code": code, "type": s["type"],
                                "signal_month": dates[i], "horizon": horizon, "ret": ret})
    return samples

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300, help="样本股票数")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2024-01", help="信号统计起始月")
    a = ap.parse_args()

    # 样本：优先 all_mainboard.csv，缺失则用热搜股
    codes = []
    if os.path.exists("all_mainboard.csv"):
        with open("all_mainboard.csv", encoding="utf-8") as f:
            for ln in f:
                p = ln.strip().split(",")
                if len(p) >= 1 and re.match(r"^\d{6}$", p[0]):
                    codes.append(("sh" if p[0].startswith("6") else "sz") + p[0])
    if not codes:
        txt = run(["hot", "stock", "--limit", "60"])
        for m in re.finditer(r"(sh\d{6}|sz\d{6})", txt):
            codes.append(m.group(1))
    random.seed(a.seed)
    sample = random.sample(codes, min(a.limit, len(codes)))
    print(f"样本: {len(sample)} 只主板股（来自{len(codes)}只清单）\n")

    all_samples = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(backtest_stock, c): c for c in sample}
        done = 0
        for f in as_completed(futs):
            done += 1
            if done % 50 == 0:
                print(f"  进度 {done}/{len(sample)}...", end="\r")
            all_samples.extend(f.result())
    print(f"\n信号样本总数: {len(all_samples)}（{len(set(s['code'] for s in all_samples))} 只股票产生信号）\n")

    # 过滤起始月
    if a.start:
        all_samples = [s for s in all_samples if s["signal_month"] >= a.start]

    # 汇总
    types = ["平台突破", "均线金叉", "趋势确立"]
    print("=" * 78)
    print("月线反转信号回测结果（信号确认后 N 个月收益，%）")
    print("=" * 78)
    print(f"{'信号类型':<8} {'持有':>4} {'样本':>6} {'胜率':>7} {'平均':>7} {'中位':>7} {'最大':>7} {'最小':>7} {'盈亏比':>7}")
    print("-" * 78)
    for t in types + ["全部"]:
        ss = all_samples if t == "全部" else [s for s in all_samples if s["type"] == t]
        for h in (1, 3, 6):
            sub = [s["ret"] for s in ss if s["horizon"] == h]
            if len(sub) < 10:
                continue
            wins = [x for x in sub if x > 0]
            losses = [x for x in sub if x <= 0]
            winrate = len(wins) / len(sub) * 100
            avg = sum(sub) / len(sub)
            med = sorted(sub)[len(sub) // 2]
            pl = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else float("inf")
            print(f"{t:<8} {h:>4} {len(sub):>6} {winrate:>6.1f}% {avg:>+7.2f} {med:>+7.2f} "
                  f"{max(sub):>+7.2f} {min(sub):>+7.2f} {pl:>7.2f}")
        print("-" * 78)

    # 按信号月分布
    print("\n信号数量按月份分布（近12个月）:")
    months = {}
    for s in all_samples:
        if s["horizon"] == 3:
            months[s["signal_month"]] = months.get(s["signal_month"], 0) + 1
    for m in sorted(months.keys())[-12:]:
        bar = "█" * min(months[m], 40)
        print(f"  {m}: {months[m]:>3} {bar}")

    # 结论
    print("\n⚠️ 本回测为历史规律统计，非投资建议。样本为随机抽样主板股，未含交易成本。")

if __name__ == "__main__":
    main()
