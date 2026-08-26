#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_month_reversal_v4.py —— 多选股方法对比回测 v1.0
=====================================================
同一股票池、同一时间段，对比5种选股方法的完整效果：
  方法A 月线反转only        （月线PASS闸门）
  方法B A + 武威G1          （双阴/一阴缩量回调）
  方法C B + v2.1过滤        （支撑≥5% + 盈利）
  方法D A + 盈亏比≥2        （ATR止损+月线前高目标）
  方法E C + 盈亏比≥2        （三阶共振完整）

输出：各组 胜率/平均/中位/盈亏比/最大回撤（等权持有6个月）

用法: python3 backtest_month_reversal_v4.py --limit 3000 --workers 10
"""
import subprocess, sys, os, re, random, argparse, time
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_kline(txt):
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
    if i < 12:
        return "震荡"
    closes = [r["last"] for r in sh_rows]
    cur, ma6, ma12 = closes[i], ma(closes, i, 6), ma(closes, i, 12)
    if cur > ma6 > ma12:
        return "牛"
    if cur < ma6 < ma12:
        return "熊"
    return "震荡"

def wuwei_g1_v2(rows, i):
    if i < 3:
        return "无", None, None
    k1, k2, k3, k4 = rows[i-3], rows[i-2], rows[i-1], rows[i]
    def yang(r): return r["last"] > r["open"]
    def yin(r): return r["last"] < r["open"]
    support = None
    if k4["last"] > 0 and k1["low"] > 0:
        support = (k4["last"] - k1["low"]) / k4["last"]
    ratios = []
    if k2["volume"] > 0:
        ratios.append(k3["volume"] / k2["volume"])
        ratios.append(k4["volume"] / k2["volume"])
    shrink = max(ratios) if ratios else 1.0
    if yin(k3) and yin(k4):
        if k4["volume"] <= k2["volume"] * 0.6 and k3["volume"] <= k2["volume"] * 0.6:
            if k1["low"] > 0 and abs(k4["low"] - k1["low"]) / k1["low"] <= 0.12:
                return "双阴", support, shrink
    if yang(k3) and yin(k2) and yin(k4):
        if k2["volume"] < k3["volume"] * 0.6 and k4["volume"] < k3["volume"] * 0.6:
            if k3["low"] > 0 and abs(k4["low"] - k3["low"]) / k3["low"] <= 0.12:
                return "一阴", support, shrink
    return "无", support, shrink

def detect_reversal(rows, i):
    if i < 12:
        return None
    closes = [r["last"] for r in rows]
    cur = closes[i]
    ma6, ma12 = ma(closes, i, 6), ma(closes, i, 12)
    ma6_prev, ma12_prev = ma(closes, i-1, 6), ma(closes, i-1, 12)
    prev_max = max(closes[i-11:i])
    if cur > prev_max and cur > ma6:
        return "平台突破"
    if ma6 > ma12 and ma6_prev <= ma12_prev:
        return "均线金叉"
    if ma6 > ma12 and cur > ma6 and ma6 > ma6_prev:
        return "趋势确立"
    return None

def calc_rr_approx(month_rows, i):
    """简化盈亏比：目标=前12月高（不含当月），止损=现价-8%"""
    cur = month_rows[i]["last"]
    prev_high = max(r["high"] for r in month_rows[max(0, i-11):i]) if i > 0 else cur
    target = max(prev_high, cur * 1.08)
    stop = cur * 0.92
    risk = cur - stop
    if risk <= 0:
        return None
    return (target - cur) / risk

def backtest_stock(code, sh_rows):
    samples = []
    for attempt in range(3):
        txt = run(["kline", code, "--period", "month", "--limit", "36"])
        rows = parse_kline(txt)
        if rows:
            break
    if len(rows) < 18:
        return code, []
    closes = [r["last"] for r in rows]
    for i in range(12, len(rows)):
        rev = detect_reversal(rows, i)
        if not rev:
            continue
        regime = market_regime(sh_rows, i)
        g1, support, shrink = wuwei_g1_v2(rows, i)
        rr = calc_rr_approx(rows, i)
        methods = ["A月线反转only"]
        if g1 in ("双阴", "一阴"):
            methods.append("B+武威G1")
            if support is not None and support >= 0.05:
                methods.append("C+v2.1支撑")
        if rr is not None and rr >= 2.0:
            methods.append("D+盈亏比≥2")
            if g1 in ("双阴", "一阴") and support is not None and support >= 0.05:
                methods.append("E三阶共振")
        j = i + 6
        if j < len(closes):
            ret = (closes[j] / closes[i] - 1) * 100
            for m in methods:
                samples.append({"method": m, "ret": ret, "regime": regime})
    return code, samples

def show_group(title, samples):
    if len(samples) < 10:
        print(f"| {title:<14} | 样本不足({len(samples)}) |")
        return
    rets = sorted(s["ret"] for s in samples)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    pl = (sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if wins and losses else float("inf")
    avg = sum(rets)/len(rets)
    med = rets[len(rets)//2]
    eq = [1 + r/100 for r in rets]
    peak, maxdd = 1.0, 0.0
    for v in eq:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v)/peak * 100)
    print(f"| {title:<14} | {len(rets):>5} | {len(wins)/len(rets)*100:>5.1f}% | {avg:>+7.2f}% | {med:>+7.2f}% | {pl:>5.2f} | {maxdd:>5.1f}% |")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2024-01")
    a = ap.parse_args()

    sh_rows = []
    for _ in range(5):
        sh_rows = parse_kline(run(["kline", "sh000001", "--period", "month", "--limit", "36"]))
        if sh_rows:
            break
        time.sleep(2)
    if not sh_rows:
        print("❌ 上证月线获取失败"); return
    print(f"上证月线: {len(sh_rows)} 个月")

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
            _, ss = f.result()
            all_samples.extend(ss)
    print(f"\n方法样本总数: {len(all_samples)}\n")

    print("=" * 82)
    print("多选股方法对比回测（持有6个月，等权组合）")
    print("=" * 82)
    print(f"| {'方法':<14} | {'样本':>5} | {'胜率':>6} | {'平均':>8} | {'中位':>8} | {'盈亏比':>6} | {'最大回撤':>7} |")
    print("|" + "-" * 80 + "|")
    methods = ["A月线反转only", "B+武威G1", "C+v2.1支撑", "D+盈亏比≥2", "E三阶共振"]
    for m in methods:
        show_group(m, [s for s in all_samples if s["method"] == m])

    print("\n方法叠加边际贡献（6月持有）:")
    groups = {}
    for s in all_samples:
        groups.setdefault(s["method"], []).append(s)
    prev = None
    for m in methods:
        ss = groups.get(m, [])
        if len(ss) < 10:
            continue
        avg = sum(s["ret"] for s in ss)/len(ss)
        wr = len([s for s in ss if s["ret"] > 0])/len(ss)*100
        if prev:
            print(f"  {m}: 胜率{wr:.1f}% 平均{avg:+.1f}% (vs {prev['m']}: {prev['wr']:.1f}%→{wr:.1f}%, {prev['avg']:+.1f}%→{avg:+.1f}%)")
        else:
            print(f"  {m}: 胜率{wr:.1f}% 平均{avg:+.1f}% (基准)")
        prev = {"m": m, "wr": wr, "avg": avg}

    # 牛熊分层（全部方法 × 市场状态）
    print("\n牛熊分层（全部方法 × 市场状态，持有6个月）:")
    print(f"| {'方法':<14} | {'牛市':<22} | {'震荡市':<22} | {'熊市':<22} |")
    print("|" + "-" * 82 + "|")
    for m in methods:
        ss = groups.get(m, [])
        cells = []
        for regime in ("牛", "震荡", "熊"):
            sub = [s for s in ss if s["regime"] == regime]
            if len(sub) >= 10:
                rets = [s["ret"] for s in sub]
                wins = len([r for r in rets if r > 0])
                cells.append(f"{len(sub)}样本/胜率{wins/len(sub)*100:.0f}%/平均{sum(rets)/len(rets):+.1f}%")
            else:
                cells.append(f"样本不足({len(sub)})")
        print(f"| {m:<14} | {cells[0]:<22} | {cells[1]:<22} | {cells[2]:<22} |")

    print("\n⚠️ 本回测为历史规律统计，非投资建议；盈亏比用8%近似止损；未计交易成本。")

if __name__ == "__main__":
    main()
