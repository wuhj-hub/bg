#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反转数值指标 · 沪深300成分股 · 多级别回测与组合体系探索
========================================================
级别: 周线 / 日线 / 30分钟 / 10分钟 / 5分钟
数据源: 周线/日线=westock批量; 分钟线=新浪 getKLineData (scale=5/10/30)
信号: 反转数值完整版（MACD柱翻红=主信号A / 启动点=B / 底背离金叉=C）
回测: 信号日收盘买入 → 持有N周期 → 收盘卖出（未计手续费）

用法:
  python3 backtest_reversal_levels.py --fetch      # 只拉数据缓存
  python3 backtest_reversal_levels.py --bt         # 只回测
  python3 backtest_reversal_levels.py              # 全流程
"""
import os, sys, re, json, time, csv, argparse, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "outputs", "reversal_bt_data")
os.makedirs(DATA_DIR, exist_ok=True)
WESTOCK = "npx -y westock-data-skillhub@1.0.3"


def load_hs300():
    rows = []
    for ln in open(os.path.join(BASE, "hs300.csv"), encoding="utf-8"):
        p = ln.strip().split(",")
        if len(p) >= 2 and p[0].startswith(("sh", "sz")):
            rows.append((p[0], p[1]))
    return rows


# ─────────────── 数据拉取 ───────────────
def fetch_weekly_daily(code, name):
    """westock批量拉周线+日线（各130/260根）"""
    out = {}
    for period, limit, tag in [("week", 130, "W"), ("day", 260, "D")]:
        fp = os.path.join(DATA_DIR, f"{code}_{tag}.csv")
        if os.path.exists(fp):
            continue
        try:
            r = subprocess.run(f"{WESTOCK} kline {code} --period {period} --limit {limit}",
                               shell=True, capture_output=True, text=True, timeout=60)
            rows = []
            for ln in r.stdout.splitlines():
                m = re.match(r"\|\s*([\d-]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
                if m:
                    rows.append((m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)))
            rows.sort(key=lambda r: r[0])
            with open(fp, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(",".join(r) + "\n")
        except Exception as e:
            print(f"  [warn] {code} {tag}失败: {e}")


def fetch_weekly_daily_batch(pool):
    """westock批量模式：一次调用拉多只（100只/批），周线+日线"""
    done_w = len([f for f in os.listdir(DATA_DIR) if f.endswith("_W.csv")])
    done_d = len([f for f in os.listdir(DATA_DIR) if f.endswith("_D.csv")])
    missing_w = [c for c, n in pool if not os.path.exists(os.path.join(DATA_DIR, f"{c}_W.csv"))]
    missing_d = [c for c, n in pool if not os.path.exists(os.path.join(DATA_DIR, f"{c}_D.csv"))]
    print(f"  待拉: 周线{len(missing_w)}只 日线{len(missing_d)}只")
    for tag, period, limit, missing in [("W", "week", 130, missing_w), ("D", "day", 260, missing_d)]:
        if not missing:
            continue
        for i in range(0, len(missing), 100):
            batch = missing[i:i + 100]
            codes = ",".join(batch)
            try:
                r = subprocess.run(f"{WESTOCK} kline {codes} --period {period} --limit {limit}",
                                   shell=True, capture_output=True, text=True, timeout=120)
                # 批量返回按symbol分节
                cur = None
                rows_map = {}
                for ln in r.stdout.splitlines():
                    m = re.match(r"\|\s*([a-z]{2}\d{6})\s*\|\s*([\d-]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
                    if m:
                        sym = m.group(1)
                        rows_map.setdefault(sym, []).append((m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)))
                for sym, rows in rows_map.items():
                    rows.sort(key=lambda r: r[0])
                    with open(os.path.join(DATA_DIR, f"{sym}_{tag}.csv"), "w", encoding="utf-8") as f:
                        for r in rows:
                            f.write(",".join(r) + "\n")
                print(f"  {tag} 批{i//100+1}: 成功{len(rows_map)}只")
            except Exception as e:
                print(f"  [warn] {tag}批{i//100+1}失败: {e}")


def fetch_minute(code, name):
    """新浪拉5/10/30分钟线各1000根"""
    num = code[2:]
    for scale, tag in [(5, "m5"), (10, "m10"), (30, "m30")]:
        fp = os.path.join(DATA_DIR, f"{code}_{tag}.csv")
        if os.path.exists(fp):
            continue
        for attempt in range(3):
            try:
                url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
                       f"CN_MarketDataService.getKLineData?symbol={code}&scale={scale}&ma=no&datalen=1000")
                r = subprocess.run(f"curl -s -m 20 '{url}'", shell=True, capture_output=True, text=True, timeout=30)
                m = re.search(r"var\((.*)\)\s*;?\s*$", r.stdout, re.S)
                if not m:
                    raise ValueError("解析失败")
                data = json.loads(m.group(1))
                with open(fp, "w", encoding="utf-8") as f:
                    for d in data:
                        f.write(f"{d['day']},{d['open']},{d['high']},{d['low']},{d['close']}\n")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [warn] {code} {tag}失败: {e}")
                time.sleep(1)


def fetch_all(pool, max_workers=8):
    print(f"📥 拉取数据: {len(pool)}只 (周线/日线=westock批量, 分钟线=新浪)")
    codes = [(c, n) for c, n in pool]
    # 日线/周线：westock批量（100只/批）
    fetch_weekly_daily_batch(codes)
    # 分钟线并发
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fetch_minute, c, n): c for c, n in codes}
        for i, f in enumerate(as_completed(futs)):
            f.result()
            if (i + 1) % 50 == 0:
                print(f"  分钟线 {i+1}/{len(codes)}")
    print("✅ 数据拉取完成")


# ─────────────── 指标与信号 ───────────────
def ema(series, n):
    out = [series[0]]
    k = 2 / (n + 1)
    for x in series[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def calc_ind(closes):
    n = len(closes)
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]
    return dif, dea, macd


def signals(closes):
    """返回信号位置列表: A=MACD柱翻红(反转数值负转正), B=启动点, C=底背离金叉"""
    dif, dea, macd = calc_ind(closes)
    n = len(macd)
    sigA, sigB, sigC = [], [], []
    # A: 红柱启动（MACD由负转正）
    for i in range(2, n):
        if macd[i] > 0 and macd[i - 1] <= 0:
            sigA.append(i)
        # B: 启动点（绿柱缩短起点）
        if macd[i] < 0 and macd[i] > macd[i - 1] and macd[i - 1] <= macd[i - 2]:
            sigB.append(i)
    # C: 底背离金叉（标准MACD口径）
    e12s, e26s = ema(closes, 12), ema(closes, 26)
    dif1 = [a - b for a, b in zip(e12s, e26s)]
    dea1 = ema(dif1, 9)
    jc = [i for i in range(1, n) if dif1[i - 1] <= dea1[i - 1] and dif1[i] > dea1[i]]
    for j in jc:
        if j < 20:
            continue
        prev = [p for p in jc if p < j]
        ref_i = prev[-1] if prev else j
        # 价格新低但DIF抬升 = 底背离
        if closes[j] < closes[ref_i] and dif1[j] > dif1[ref_i]:
            sigC.append(j)
    return sigA, sigB, sigC


def load_klines(code, tag):
    fp = os.path.join(DATA_DIR, f"{code}_{tag}.csv")
    if not os.path.exists(fp):
        return None
    closes = []
    is_min = tag.startswith("m")  # 新浪分钟线: date,open,high,low,close → close=p[4]
    for ln in open(fp, encoding="utf-8"):
        p = ln.strip().split(",")
        # westock(W/D): date,open,close,high,low → close=p[2]
        if len(p) >= 5:
            try:
                closes.append(float(p[4] if is_min else p[2]))
            except ValueError:
                pass
    return closes if len(closes) >= 30 else None


# ─────────────── 回测 ───────────────
def backtest_level(pool, tag, holds, label):
    """单级别回测：返回 {hold: 统计}"""
    results = {h: [] for h in holds}
    total = 0
    for code, name in pool:
        closes = load_klines(code, tag)
        if not closes:
            continue
        sigA, sigB, sigC = signals(closes)
        n = len(closes)
        total += 1
        for h in holds:
            for i in sigA:  # 主信号：红柱启动
                if i + h < n:
                    ret = (closes[i + h] - closes[i]) / closes[i] * 100
                    results[h].append(ret)
    out = {}
    for h, rets in results.items():
        if len(rets) < 10:
            out[h] = None
            continue
        wins = [r for r in rets if r > 0]
        avg = sum(rets) / len(rets)
        pl = sum(r for r in rets if r > 0) / max(1, len(wins))
        ls = abs(sum(r for r in rets if r <= 0) / max(1, len(rets) - len(wins)))
        out[h] = {
            "n": len(rets), "wr": len(wins) / len(rets) * 100,
            "avg": avg, "med": sorted(rets)[len(rets) // 2],
            "pl": pl, "pl_ratio": (pl / ls) if ls > 0 else 99,
            "worst": min(rets),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--bt", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="限制股票数(调试用)")
    a = ap.parse_args()

    pool = load_hs300()
    if a.limit:
        pool = pool[:a.limit]
    print(f"沪深300成分股: {len(pool)}只\n")

    if a.fetch or not a.bt:
        fetch_all(pool)
    if a.bt or not a.fetch:
        pass
    if not a.fetch and not a.bt:
        fetch_all(pool)

    # ── 回测各级别 ──
    levels = [
        ("周线", "W", [1, 2, 4], "持有1/2/4周"),
        ("日线", "D", [1, 3, 5, 10], "持有1/3/5/10日"),
        ("30分钟", "m30", [4, 8, 16], "持有4/8/16根(0.5/1/2天)"),
        ("10分钟", "m10", [6, 12, 24], "持有6/12/24根(1/2/4小时)"),
        ("5分钟", "m5", [12, 24, 48], "持有12/24/48根(1/2/4小时)"),
    ]
    print("\n" + "=" * 100)
    print("📊 反转数值主信号（MACD柱翻红）· 各级别回测对比")
    print("=" * 100)
    all_stats = {}
    for label, tag, holds, hdesc in levels:
        res = backtest_level(pool, tag, holds, label)
        all_stats[label] = res
        print(f"\n【{label}】数据: {len(pool)}只 | {hdesc}")
        print(f"{'持有':<6}{'信号数':>7}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>8}{'最差':>8}")
        for h in holds:
            s = res[h]
            if not s:
                print(f"{h:<6}{'样本不足':>12}")
                continue
            print(f"{h:<6}{s['n']:>7}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%{s['med']:>+8.2f}%"
                  f"{s['pl_ratio']:>8.2f}{s['worst']:>+8.2f}%")

    # 级别最优持有期对比表
    print("\n" + "=" * 100)
    print("🏆 级别×最优持有期 对比（用于选择主操作级别）")
    print("=" * 100)
    print(f"{'级别':<8}{'持有':<6}{'信号数':>7}{'胜率':>8}{'平均':>8}{'盈亏比':>8}{'最差':>8}")
    best = {}
    for label, tag, holds, hdesc in levels:
        res = all_stats[label]
        for h in holds:
            s = res[h]
            if not s:
                continue
            print(f"{label:<8}{h:<6}{s['n']:>7}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%"
                  f"{s['pl_ratio']:>8.2f}{s['worst']:>+8.2f}%")
        # 选出该级别最优（按平均收益×样本权重）
        valid = {h: s for h, s in res.items() if s and s["n"] >= 20}
        if valid:
            best[label] = max(valid.items(), key=lambda kv: kv[1]["avg"] * min(1, kv[1]["n"] / 100))
            lb, ls = best[label]
            print(f"  → 最优: 持有{lb}, 胜率{ls['wr']:.1f}%, 平均{ls['avg']:+.2f}%")

    # ── 组合策略 ──
    print("\n" + "=" * 100)
    print("🔗 多级别组合策略回测（周线方向 + 日线/分钟线信号）")
    print("=" * 100)
    combo_results = {}
    # 组合1: 周线红柱 + 日线红柱启动
    r1 = []
    for code, name in pool:
        wc, dc = load_klines(code, "W"), load_klines(code, "D")
        if not wc or not dc:
            continue
        wsA, _, _ = signals(wc)
        dsA, _, _ = signals(dc)
        if not wsA:
            continue
        n = len(dc)
        for i in dsA:
            if i + 5 < n:
                r1.append((dc[i + 5] - dc[i]) / dc[i] * 100)
    if len(r1) >= 10:
        wins = [r for r in r1 if r > 0]
        combo_results["周线红柱+日线启动(持5日)"] = {
            "n": len(r1), "wr": len(wins) / len(r1) * 100, "avg": sum(r1) / len(r1),
            "med": sorted(r1)[len(r1) // 2],
            "worst": min(r1),
            "pl": sum(w for w in r1 if w > 0) / max(1, len(wins)) if wins else 0,
        }
    # 组合2: 日线红柱 + 30分钟红柱启动（持8根）
    r2 = []
    for code, name in pool:
        dc, m30 = load_klines(code, "D"), load_klines(code, "m30")
        if not dc or not m30:
            continue
        dsA, _, _ = signals(dc)
        msA, _, _ = signals(m30)
        if not dsA or not msA:
            continue
        n = len(m30)
        for i in msA:
            if i + 8 < n:
                r2.append((m30[i + 8] - m30[i]) / m30[i] * 100)
    if len(r2) >= 10:
        wins = [r for r in r2 if r > 0]
        combo_results["日线红柱+30m启动(持8根)"] = {
            "n": len(r2), "wr": len(wins) / len(r2) * 100, "avg": sum(r2) / len(r2),
            "med": sorted(r2)[len(r2) // 2],
            "worst": min(r2),
            "pl": sum(w for w in r2 if w > 0) / max(1, len(wins)) if wins else 0,
        }
    # 组合3: 日线红柱 + 5分钟逼空（持24根）
    r3 = []
    for code, name in pool:
        dc, m5 = load_klines(code, "D"), load_klines(code, "m5")
        if not dc or not m5:
            continue
        dsA, _, _ = signals(dc)
        msA, _, _ = signals(m5)
        if not dsA or not msA:
            continue
        n = len(m5)
        for i in msA:
            if i + 24 < n:
                r3.append((m5[i + 24] - m5[i]) / m5[i] * 100)
    if len(r3) >= 10:
        wins = [r for r in r3 if r > 0]
        combo_results["日线红柱+5m启动(持24根)"] = {
            "n": len(r3), "wr": len(wins) / len(r3) * 100, "avg": sum(r3) / len(r3),
            "med": sorted(r3)[len(r3) // 2],
            "worst": min(r3),
            "pl": sum(w for w in r3 if w > 0) / max(1, len(wins)) if wins else 0,
        }
    # 组合4: 日线红柱+30m红柱+30m底背离（三重确认）
    r4 = []
    for code, name in pool:
        dc, m30 = load_klines(code, "D"), load_klines(code, "m30")
        if not dc or not m30:
            continue
        dsA, _, _ = signals(dc)
        msA, _, msC = signals(m30)
        if not dsA:
            continue
        n = len(m30)
        for i in msA:
            if i + 8 < n:
                r4.append((m30[i + 8] - m30[i]) / m30[i] * 100)
    if len(r4) >= 10:
        wins = [r for r in r4 if r > 0]
        combo_results["日线红柱+30m启动(全样本)"] = {
            "n": len(r4), "wr": len(wins) / len(r4) * 100, "avg": sum(r4) / len(r4),
            "med": sorted(r4)[len(r4) // 2], "worst": min(r4),
            "pl": sum(w for w in r4 if w > 0) / max(1, len(wins)) if wins else 0,
        }
    print(f"{'组合':<28}{'样本':>7}{'胜率':>8}{'平均':>8}{'中位':>8}{'最差':>8}")
    for k, s in combo_results.items():
        print(f"{k:<28}{s['n']:>7}{s['wr']:>7.1f}%{s['avg']:>+8.2f}%{s['med']:>+8.2f}%{s['worst']:>+8.2f}%")

    # 保存结果
    out = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pool": len(pool), "levels": all_stats, "combos": combo_results,
    }
    with open(os.path.join(DATA_DIR, "bt_results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n✅ 结果已保存 outputs/reversal_bt_data/bt_results.json")


if __name__ == "__main__":
    main()
