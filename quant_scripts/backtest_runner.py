#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_runner.py —— 参数化回测执行器（黑石 strategy_type + params_json 启发）
================================================================================
同一回测引擎 + 配置驱动，替代每策略一脚本：
  strategy: 信号策略类型（注册表）
  params:   策略参数JSON（过滤层开关/持有期/止损等）

用法:
  # 月线反转+武威G1+盈亏比过滤（v4方法E等价），随机1500只
  python3 backtest_runner.py --strategy month_reversal \
      --params '{"g1":true,"min_support":5,"profit_filter":true,"min_ratio":2,"hold_months":6}' \
      --pool all_mainboard.csv --limit 1500 --seed 42

  # 纯月线反转（方法A等价）
  python3 backtest_runner.py --strategy month_reversal --params '{"hold_months":6}' --limit 1500

输出: outputs/backtest_result_{strategy}_{ts}.json/.md（统一格式）
"""
import subprocess, sys, os, re, json, random, argparse, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
STRATEGIES = ["month_reversal"]


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
    return sum(vals[i - n + 1:i + 1]) / n if i >= n - 1 else None


# ═══════════════════════════════════════════════
# 信号策略注册表：month_reversal（月线反转，v4方法A-E参数化）
# ═══════════════════════════════════════════════
def detect_reversal_m(rows, i):
    """月线反转检测（v4逻辑）：平台突破/均线金叉/趋势确立"""
    if i < 12:
        return None
    closes = [r["last"] for r in rows]
    cur = closes[i]
    ma6, ma12 = ma(closes, i, 6), ma(closes, i, 12)
    ma6_prev, ma12_prev = ma(closes, i - 1, 6), ma(closes, i - 1, 12)
    prev_max = max(closes[i - 11:i])
    if cur > prev_max and cur > ma6:
        return "平台突破"
    if ma6 > ma12 and ma6_prev <= ma12_prev:
        return "均线金叉"
    if ma6 > ma12 and cur > ma6 and ma6 > ma6_prev:
        return "趋势确立"
    return None


def wuwei_g1_m(rows, i):
    """武威G1（v4逻辑）：双阴/一阴缩量回调"""
    if i < 3:
        return "无", None
    k1, k2, k3, k4 = rows[i - 3], rows[i - 2], rows[i - 1], rows[i]
    def yang(r): return r["last"] > r["open"]
    def yin(r): return r["last"] < r["open"]
    support = None
    if k4["last"] > 0 and k1["low"] > 0:
        support = (k4["last"] - k1["low"]) / k4["last"]
    if yin(k3) and yin(k4):
        if k4["volume"] <= k2["volume"] * 0.6 and k3["volume"] <= k2["volume"] * 0.6:
            if k1["low"] > 0 and abs(k4["low"] - k1["low"]) / k1["low"] <= 0.12:
                return "双阴", support
    if yang(k3) and yin(k2) and yin(k4):
        if k2["volume"] < k3["volume"] * 0.6 and k4["volume"] < k3["volume"] * 0.6:
            if k3["low"] > 0 and abs(k4["low"] - k3["low"]) / k3["low"] <= 0.12:
                return "一阴", support
    return "无", support


def calc_rr_m(rows, i):
    """简化盈亏比：目标=前12月高，止损=现价-8%（v4逻辑）"""
    cur = rows[i]["last"]
    prev_high = max(r["high"] for r in rows[max(0, i - 11):i]) if i > 0 else cur
    target = max(prev_high, cur * 1.08)
    stop = cur * 0.92
    risk = cur - stop
    if risk <= 0:
        return None
    return (target - cur) / risk


def fetch_finance(wcode):
    txt = run(["finance", wcode, "--num", "1"])
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "NPParentCompanyOwnersTTM" in parts:
            header = parts
            continue
        if header and "---" not in parts[0] and len(parts) == len(header):
            try:
                return float(parts[header.index("NPParentCompanyOwnersTTM")])
            except (ValueError, IndexError):
                return None
    return None


def atr14(kr, i):
    """ATR(14) Wilder at index i"""
    if i < 14:
        return None
    trs = []
    for j in range(i - 13, i + 1):
        tr = max(kr[j]["high"] - kr[j]["low"],
                 abs(kr[j]["high"] - kr[j - 1]["last"]),
                 abs(kr[j]["low"] - kr[j - 1]["last"]))
        trs.append(tr)
    return sum(trs) / len(trs)


def backtest_one(stock, params):
    """历史遍历回测（月线版，v4等价）：月K线逐月检测反转信号→持有N月
    返回 [(entry_date, ret%, rev, g1, support, rr), ...]"""
    code, name = stock
    wcode = code if code.lower().startswith(("sh", "sz")) else ("sh" if code.startswith("60") else "sz") + code
    hold = params.get("hold_months", 6)
    profit_filter = params.get("profit_filter", False)
    min_ratio = params.get("min_ratio", 0)
    min_support = params.get("min_support", 0)
    use_g1 = params.get("g1", False)

    rows = parse_kline(run(["kline", wcode, "--period", "month", "--limit", "36"]))
    if len(rows) < 18:
        return []
    closes = [r["last"] for r in rows]

    if profit_filter:
        profit = fetch_finance(wcode)
        if profit is None or profit <= 0:
            return []

    samples = []
    for i in range(12, len(rows) - hold + 1):
        rev = detect_reversal_m(rows, i)
        if not rev:
            continue
        g1, support = wuwei_g1_m(rows, i)
        if use_g1 and g1 == "无":
            continue
        # min_support 参数单位=百分比（5=5%），support为小数（0.05=5%）
        if min_support > 0 and (support is None or support * 100 < min_support):
            continue
        rr = None
        if min_ratio > 0:
            rr = calc_rr_m(rows, i)
            if rr is None or rr < min_ratio:
                continue
        e = closes[i]
        x = closes[i + hold]
        ret = (x - e) / e * 100 if e else 0
        samples.append((rows[i]["date"], round(ret, 2), rev, g1, round(support * 100, 1) if support else None, round(rr, 2) if rr else None))
    return samples


def fetch_hold_return(wcode, hold):
    """（保留兼容，不再使用）"""
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="month_reversal", choices=STRATEGIES)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--pool", default="all_mainboard.csv")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--hold", type=int, default=0)  # 覆盖params里的hold_months
    args = ap.parse_args()

    params = json.loads(args.params)
    if args.hold:
        params["hold_months"] = args.hold

    rows = list(__import__("csv").DictReader(open(args.pool, encoding="utf-8-sig")))
    rows = [r for r in rows if "退" not in r.get("name", "")]
    if args.limit and len(rows) > args.limit:
        random.seed(args.seed)
        rows = random.sample(rows, args.limit)
    total = len(rows)
    print(f"[INFO] 池 {total}只 strategy={args.strategy} params={json.dumps(params, ensure_ascii=False)}", flush=True)

    # 1+2. 历史遍历回测（每只股票250天窗口逐日检测信号→持有N日）
    returns, details = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(backtest_one, (r["code"], r["name"]), params): r for r in rows}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                samples = fut.result()
                for d, ret, rev, g1, sup, rr in samples:
                    returns.append(ret)
                    details.append({"code": futs[fut]["code"], "name": futs[fut]["name"], "date": d, "ret": ret,
                                    "rev": rev, "g1": g1, "support": sup, "ratio": rr})
            except Exception:
                pass
            if i % 200 == 0:
                print(f"  [回测 {i}/{total}] 样本 {len(returns)}", flush=True)
    hold = params.get("hold_months", 6)
    signals = len(returns)
    print(f"[OK] 信号样本 {signals} 个", flush=True)

    n = len(returns)
    if n == 0:
        print("[WARN] 无有效回测样本")
        return
    wins = [r for r in returns if r > 0]
    avg = sum(returns) / n
    med = sorted(returns)[n // 2]
    win_rate = len(wins) / n * 100
    avg_win = sum(wins) / len(wins) if wins else 0
    losses = [r for r in returns if r <= 0]
    avg_loss = sum(losses) / len(losses) if losses else 0
    ratio = abs(avg_win / avg_loss) if avg_loss else float("inf")
    # 最大回撤（累计净值）
    nav, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        nav *= (1 + r / 100)
        peak = max(peak, nav)
        mdd = max(mdd, (peak - nav) / peak)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result = {
        "strategy": args.strategy, "params": params, "pool": args.pool,
        "limit": total, "seed": args.seed, "signals": signals, "samples": n,
        "win_rate": round(win_rate, 1), "avg": round(avg, 2), "median": round(med, 2),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "profit_ratio": round(ratio, 2), "max_drawdown": round(mdd * 100, 1),
        "ts": ts,
    }
    os.makedirs("outputs", exist_ok=True)
    json_path = f"outputs/backtest_result_{args.strategy}_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    md_path = f"outputs/backtest_result_{args.strategy}_{ts}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"""# 📈 参数化回测结果（{args.strategy}）{ts}

> 池 {total}只（seed={args.seed}）| 信号样本 {signals} 个（250日窗口逐日检测）| 有效样本 {n} 个
> 参数：{json.dumps(params, ensure_ascii=False)}

## 核心指标（持有 {hold} 日，等权）

| 胜率 | 平均收益 | 中位收益 | 盈亏比 | 最大回撤 |
|---|---|---|---|---|
| {win_rate}% | +{avg:.2f}% | {med:+.2f}% | {ratio:.2f} | -{mdd*100:.1f}% |

## 明细TOP（按收益排序，前20）

| 代码 | 名称 | 收益% | 详情 |
|---|---|---|---|
""")
        for d in sorted(details, key=lambda x: -x["ret"])[:20]:
            f.write(f"| {d['code']} | {d['name']} | {d['date']} | {d['ret']} | {d['rev']} | {d.get('g1','-')} | {d.get('support','-')}% | {d.get('ratio','-')} |\n")
    print(f"[OK] {json_path}")
    print(f"[OK] {md_path}")
    print(f"胜率 {win_rate}% | 平均 {avg:+.2f}% | 盈亏比 {ratio:.2f} | 回撤 -{mdd*100:.1f}%")


def fetch_hold_return(wcode, hold):
    """拉K线并计算信号后持有hold日收益（简化：用最新信号日，需改进为历史回测）"""
    kr = parse_kline(run(["kline", wcode, "--period", "day", "--limit", str(hold + 30)]))
    if len(kr) <= hold:
        return None
    e = kr[0]["last"]  # 最新收盘≈信号日入场（简化口径）
    x = kr[hold]["last"]
    return (x - e) / e * 100 if e else None


if __name__ == "__main__":
    main()
