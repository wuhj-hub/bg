#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_month_reversal_v2.py —— 月线反转信号 牛熊分层 + 武威G1交叉验证 回测
============================================================================
1. 牛熊市分层: 按信号月上证指数月线状态(牛: 收>MA6>MA12 / 熊: 收<MA6<MA12 / 震荡)
   分别统计月线反转信号 1/3/6 月收益
2. 武威G1交叉验证: 同月同时满足武威G1(双阴/一阴缩量回调到起涨点,容差12%)
   vs 仅月线反转 vs 仅武威G1 → 对比 6 月收益，验证交叉信号是否更优

样本: 沪深主板 all_mainboard.csv 随机抽样(默认3000)
用法: python3 backtest_month_reversal_v2.py --limit 3000 --workers 10
"""
import subprocess, sys, os, re, random, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_month_kline(txt):
    """解析月线(含open/high/low/vol)，升序"""
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
                di = header.index("date")
                row = {"date": parts[di]}
                for key in ("open", "last", "high", "low", "volume"):
                    if key in header:
                        row[key] = float(parts[header.index(key)])
                if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                    rows.append(row)
            except (ValueError, IndexError):
                pass
    rows.sort(key=lambda r: r["date"])
    return rows

def ma(vals, i, n):
    return sum(vals[i-n+1:i+1]) / n

def market_regime(sh_rows, i):
    """上证指数月线状态: 牛/熊/震荡（i为当前月下标）"""
    if i < 12:
        return "震荡"
    closes = [r["last"] for r in sh_rows]
    cur = closes[i]
    ma6 = ma(closes, i, 6)
    ma12 = ma(closes, i, 12)
    if cur > ma6 > ma12:
        return "牛"
    if cur < ma6 < ma12:
        return "熊"
    return "震荡"

def wuwei_g1_v2(rows, i):
    """武威G1（用open判断阴阳），rows为月线dict列表"""
    if i < 3:
        return "无"
    k1, k2, k3, k4 = rows[i-3], rows[i-2], rows[i-1], rows[i]
    def yang(r): return r["last"] > r["open"]
    def yin(r): return r["last"] < r["open"]
    # 双阴: 末端两阴 + K4量<=K2量*0.6 + K3量<=K2量*0.6 + K4低≈K1低(±12%)
    if yin(k3) and yin(k4):
        if k4["volume"] <= k2["volume"] * 0.6 and k3["volume"] <= k2["volume"] * 0.6:
            if k1["low"] > 0 and abs(k4["low"] - k1["low"]) / k1["low"] <= 0.12:
                return "双阴"
    # 一阴: K3阳,K2阴,K4阴 + K2量<K3量*0.6 + K4量<K3量*0.6 + K4低≈K3低(±12%)
    if yang(k3) and yin(k2) and yin(k4):
        if k2["volume"] < k3["volume"] * 0.6 and k4["volume"] < k3["volume"] * 0.6:
            if k3["low"] > 0 and abs(k4["low"] - k3["low"]) / k3["low"] <= 0.12:
                return "一阴"
    return "无"

def detect_reversal(rows, i):
    """月线反转信号（平台突破/均线金叉/趋势确立），i为信号月"""
    if i < 12:
        return None
    closes = [r["last"] for r in rows]
    cur = closes[i]
    ma6 = ma(closes, i, 6)
    ma12 = ma(closes, i, 12)
    ma6_prev = ma(closes, i-1, 6)
    ma12_prev = ma(closes, i-1, 12)
    prev_max = max(closes[i-11:i])
    if cur > prev_max and cur > ma6:
        return "平台突破"
    if ma6 > ma12 and ma6_prev <= ma12_prev:
        return "均线金叉"
    if ma6 > ma12 and cur > ma6 and ma6 > ma6_prev:
        return "趋势确立"
    return None

def backtest_stock(code, sh_rows):
    samples = []
    for attempt in range(3):
        txt = run(["kline", code, "--period", "month", "--limit", "36"])
        rows = parse_month_kline(txt)
        if rows:
            break
    if len(rows) < 18:
        return samples
    closes = [r["last"] for r in rows]
    for i in range(12, len(rows)):
        rev = detect_reversal(rows, i)
        if not rev:
            continue
        regime = market_regime(sh_rows, i)
        g1 = wuwei_g1_v2(rows, i)
        for h in (1, 3, 6):
            j = i + h
            if j < len(rows):
                ret = (closes[j] / closes[i] - 1) * 100
                samples.append({"code": code, "type": rev, "regime": regime,
                                "g1": g1, "month": rows[i]["date"], "horizon": h, "ret": ret})
    return samples

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2024-01")
    a = ap.parse_args()

    # 上证指数月线（市场状态分层基准）
    sh_rows = []
    for _ in range(3):
        sh_rows = parse_month_kline(run(["kline", "sh000001", "--period", "month", "--limit", "36"]))
        if sh_rows:
            break
    if not sh_rows:
        print("❌ 上证指数月线获取失败，终止"); return
    print(f"上证月线: {len(sh_rows)} 个月（基准 {sh_rows[-1]['date']}）")

    codes = []
    if os.path.exists("all_mainboard.csv"):
        with open("all_mainboard.csv", encoding="utf-8-sig") as f:
            for ln in f:
                p = ln.strip().split(",")
                if len(p) >= 1 and re.match(r"^\d{6}$", p[0]):
                    codes.append(("sh" if p[0].startswith("6") else "sz") + p[0])
    random.seed(a.seed)
    sample = random.sample(codes, min(a.limit, len(codes)))
    print(f"样本: {len(sample)} 只主板股\n")

    all_samples = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(backtest_stock, c, sh_rows): c for c in sample}
        done = 0
        for f in as_completed(futs):
            done += 1
            if done % 100 == 0:
                print(f"  进度 {done}/{len(sample)}...", end="\r")
            all_samples.extend(f.result())
    all_samples = [s for s in all_samples if s["month"] >= a.start]
    print(f"\n信号样本总数: {len(all_samples)}（含市场状态与武威G1标注）\n")

    def show(title, ss, h=6):
        sub = [s["ret"] for s in ss if s["horizon"] == h]
        if len(sub) < 10:
            return
        wins = [x for x in sub if x > 0]
        losses = [x for x in sub if x <= 0]
        pl = (sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if wins and losses else float("inf")
        print(f"{title:<18} {len(sub):>6} {len(wins)/len(sub)*100:>6.1f}% {sum(sub)/len(sub):>+8.2f} "
              f"{sorted(sub)[len(sub)//2]:>+8.2f} {pl:>7.2f}")

    # ═══ 一、牛熊市分层（6月持有）═══
    print("=" * 84)
    print("一、牛熊市分层回测（月线反转信号，持有6个月）")
    print("=" * 84)
    print(f"{'分层':<18} {'样本':>6} {'胜率':>7} {'平均':>9} {'中位':>9} {'盈亏比':>7}")
    print("-" * 84)
    for regime in ("牛", "熊", "震荡"):
        ss = [s for s in all_samples if s["regime"] == regime]
        show(f"{regime}市", ss)
    show("全部", all_samples)
    print()

    # 牛熊×信号类型
    print("二、牛熊×信号类型（持有6个月）")
    print("-" * 84)
    for regime in ("牛", "熊", "震荡"):
        for t in ("平台突破", "均线金叉", "趋势确立"):
            ss = [s for s in all_samples if s["regime"] == regime and s["type"] == t]
            if len(ss) >= 20:
                show(f"{regime}市/{t}", ss)
    print()

    # ═══ 二、武威G1交叉验证（6月持有）═══
    print("=" * 84)
    print("三、武威G1交叉验证（持有6个月）")
    print("=" * 84)
    print(f"{'组合':<22} {'样本':>6} {'胜率':>7} {'平均':>9} {'中位':>9} {'盈亏比':>7}")
    print("-" * 84)
    rev_only = [s for s in all_samples if s["g1"] == "无"]
    cross = [s for s in all_samples if s["g1"] in ("双阴", "一阴")]
    show("月线反转(全部)", all_samples)
    show("反转∩武威G1", cross)
    show("  其中∩双阴", [s for s in cross if s["g1"] == "双阴"])
    show("  其中∩一阴", [s for s in cross if s["g1"] == "一阴"])
    show("反转-only", rev_only)
    print()
    # G1整体对照（独立统计所有G1信号的表现）
    g1_all = []
    # 补充: 单独统计G1(无论是否反转)
    g1_only_samples = [s for s in all_samples if s["g1"] in ("双阴", "一阴")]
    show("反转∩G1 按类型:", [])
    for g1t in ("双阴", "一阴"):
        ss = [s for s in all_samples if s["g1"] == g1t]
        show(f"反转∩{g1t}", ss)
    print()

    # 交叉信号明细样例
    cross_samples = [s for s in all_samples if s["g1"] in ("双阴", "一阴") and s["horizon"] == 6]
    if cross_samples:
        print("交叉信号样例（反转+G1）:")
        seen = set()
        for s in cross_samples:
            key = (s["code"], s["month"])
            if key in seen:
                continue
            seen.add(key)
            print(f"  {s['code']} {s['month']} {s['type']}+{s['g1']} 6月收益{s['ret']:+.1f}%")
            if len(seen) >= 12:
                break
    print("\n⚠️ 本回测为历史规律统计，非投资建议，未含交易成本。")

if __name__ == "__main__":
    main()
