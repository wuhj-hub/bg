#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_month_reversal_v3.py —— 月线反转 × 武威G1 × v2.1质量过滤 叠加回测
==========================================================================
在 v2（反转∩G1交叉验证）基础上，叠加武威 v2.1 质量过滤（单独列出，作为方法叠加结果）：

  v2.1 一票否决规则（与 wuwei_v21_filter.py 一致）:
    - 浅支撑<5% 否决: support = (K4收盘 - K1低点) / K4收盘
    - 亏损股否决: 归属母公司净利润 NPParentCompanyOwners <= 0

输出分层（持有6个月）:
  A. 月线反转(全部)
  B. 反转∩武威G1 (v2结果, 保留)
  C. B + 支撑≥5% (浅支撑过滤)
  D. C + 盈利 (v2.1完整否决过滤) ★方法叠加结果
  E. D 按信号类型/市场状态细分

用法: python3 backtest_month_reversal_v3.py --limit 3000 --workers 10
"""
import subprocess, sys, os, re, random, argparse, json
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=60):
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
    """武威G1（双阴/一阴缩量回调到起涨点，容差12%），返回 (类型, 支撑深度, 缩量max)"""
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
    shrink_max = max(ratios) if ratios else 1.0
    if yin(k3) and yin(k4):
        if k4["volume"] <= k2["volume"] * 0.6 and k3["volume"] <= k2["volume"] * 0.6:
            if k1["low"] > 0 and abs(k4["low"] - k1["low"]) / k1["low"] <= 0.12:
                return "双阴", support, shrink_max
    if yang(k3) and yin(k2) and yin(k4):
        if k2["volume"] < k3["volume"] * 0.6 and k4["volume"] < k3["volume"] * 0.6:
            if k3["low"] > 0 and abs(k4["low"] - k3["low"]) / k3["low"] <= 0.12:
                return "一阴", support, shrink_max
    return "无", support, shrink_max

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
        g1, support, shrink = wuwei_g1_v2(rows, i)
        for h in (1, 3, 6):
            j = i + h
            if j < len(rows):
                ret = (closes[j] / closes[i] - 1) * 100
                samples.append({"code": code, "type": rev, "regime": regime,
                                "g1": g1, "support": support, "shrink": shrink,
                                "month": rows[i]["date"], "horizon": h, "ret": ret})
    return samples

def fetch_finance(codes):
    """批量拉利润表净利润（10只/批），返回 {code: 盈利/亏损/无数据}"""
    fin = {}
    codes = sorted(set(codes))
    for i in range(0, len(codes), 10):
        batch = codes[i:i+10]
        out = run(["finance", ",".join(batch), "--type", "lrb", "--num", "1"])
        lines = [l for l in out.splitlines() if l.strip().startswith("|")]
        if len(lines) >= 2:
            hdr = [h.strip() for h in lines[0].strip().strip("|").split("|")]
            if "SecuCode" in hdr and "NPParentCompanyOwners" in hdr:
                sci, npi = hdr.index("SecuCode"), hdr.index("NPParentCompanyOwners")
                for l in lines[2:]:
                    cols = [x.strip() for x in l.strip().strip("|").split("|")]
                    if len(cols) > max(sci, npi):
                        code, npv = cols[sci], cols[npi]
                        if code in set(codes):
                            try:
                                v = float(npv)
                                fin[code] = "盈利" if v > 0 else "亏损"
                            except ValueError:
                                fin[code] = "无数据"
    for c in codes:
        fin.setdefault(c, "无数据")
    return fin

def show(title, ss, h=6):
    sub = [s["ret"] for s in ss if s["horizon"] == h]
    if len(sub) < 5:
        print(f"{title:<26} 样本不足({len(sub)})")
        return
    wins = [x for x in sub if x > 0]
    losses = [x for x in sub if x <= 0]
    pl = (sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if wins and losses else float("inf")
    print(f"{title:<26} {len(sub):>5} {len(wins)/len(sub)*100:>6.1f}% {sum(sub)/len(sub):>+8.2f} "
          f"{sorted(sub)[len(sub)//2]:>+8.2f} {max(sub):>+8.1f} {pl:>7.2f}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2024-01")
    a = ap.parse_args()

    sh_rows = []
    for _ in range(3):
        sh_rows = parse_month_kline(run(["kline", "sh000001", "--period", "month", "--limit", "36"]))
        if sh_rows:
            break
    if not sh_rows:
        print("❌ 上证月线获取失败"); return
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
    print(f"\n信号样本总数: {len(all_samples)}\n")

    # 交叉信号财务过滤（仅对反转∩G1的股票拉财务）
    cross_codes = sorted(set(s["code"] for s in all_samples if s["g1"] in ("双阴", "一阴")))
    print(f"拉取财务数据: {len(cross_codes)} 只交叉信号股票...")
    fin = fetch_finance(cross_codes)
    for s in all_samples:
        s["finance"] = fin.get(s["code"], "无数据")
    print("财务过滤完成\n")

    print("=" * 92)
    print("武威v2.1质量过滤叠加回测（持有6个月）——保留v2模式，新增叠加层")
    print("=" * 92)
    print(f"{'组合':<26} {'样本':>5} {'胜率':>7} {'平均':>9} {'中位':>9} {'最大':>9} {'盈亏比':>7}")
    print("-" * 92)

    rev_all = all_samples
    cross = [s for s in all_samples if s["g1"] in ("双阴", "一阴")]
    cross_sup = [s for s in cross if s["support"] is not None and s["support"] >= 0.05]
    cross_sup_profit = [s for s in cross_sup if s["finance"] == "盈利"]

    show("A. 月线反转(全部)", rev_all)
    show("B. 反转∩武威G1(v2结果)", cross)
    show("C. B + 支撑≥5%", cross_sup)
    show("D. C + 盈利(v2.1否决)", cross_sup_profit)
    print("-" * 92)

    # D组细分
    print("\nD组细分（反转∩G1∩支撑≥5%∩盈利，持有6个月）:")
    print(f"{'组合':<26} {'样本':>5} {'胜率':>7} {'平均':>9} {'中位':>9} {'最大':>9} {'盈亏比':>7}")
    print("-" * 92)
    show("  按信号: ∩双阴", [s for s in cross_sup_profit if s["g1"] == "双阴"])
    show("  按信号: ∩一阴", [s for s in cross_sup_profit if s["g1"] == "一阴"])
    show("  按反转: 均线金叉", [s for s in cross_sup_profit if s["type"] == "均线金叉"])
    show("  按反转: 趋势确立", [s for s in cross_sup_profit if s["type"] == "趋势确立"])
    show("  按反转: 平台突破", [s for s in cross_sup_profit if s["type"] == "平台突破"])
    show("  按市场: 牛市", [s for s in cross_sup_profit if s["regime"] == "牛"])
    show("  按市场: 震荡市", [s for s in cross_sup_profit if s["regime"] == "震荡"])
    print("-" * 92)

    # 各层过滤漏斗统计
    print("\n过滤漏斗（6月持有样本数）:")
    n_all = len([s for s in rev_all if s["horizon"] == 6])
    n_cross = len([s for s in cross if s["horizon"] == 6])
    n_sup = len([s for s in cross_sup if s["horizon"] == 6])
    n_d = len([s for s in cross_sup_profit if s["horizon"] == 6])
    print(f"  月线反转 {n_all} → ∩G1 {n_cross} (-{100*(1-n_cross/n_all):.0f}%) "
          f"→ 支撑≥5% {n_sup} → 盈利 {n_d}（留存 {100*n_d/n_all:.1f}%）")

    # 支撑深度分布
    sups = sorted([s["support"] for s in cross if s["support"] is not None and s["horizon"] == 6])
    if sups:
        print(f"\n交叉信号支撑深度分布(6月): 中位 {sups[len(sups)//2]*100:.1f}% | "
              f"p25 {sups[len(sups)//4]*100:.1f}% | p75 {sups[len(sups)*3//4]*100:.1f}% | "
              f"≥5%占比 {sum(1 for x in sups if x>=0.05)/len(sups)*100:.0f}%")

    # 样例
    print("\nD组信号样例（反转+G1+支撑≥5%+盈利）:")
    seen = set()
    for s in sorted(cross_sup_profit, key=lambda x: -x["ret"]):
        if s["horizon"] != 6:
            continue
        key = (s["code"], s["month"])
        if key in seen:
            continue
        seen.add(key)
        print(f"  {s['code']} {s['month']} {s['type']}+{s['g1']} 支撑{s['support']*100:.0f}% 6月{s['ret']:+.1f}%")
        if len(seen) >= 10:
            break

    print("\n⚠️ 本回测为历史规律统计，非投资建议。财务用最新一期净利润近似（非信号月当期），未含交易成本。")

if __name__ == "__main__":
    main()
