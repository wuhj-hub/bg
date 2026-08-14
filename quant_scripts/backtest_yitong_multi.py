#!/usr/bin/env python3
"""
backtest_yitong_multi.py —— 一统天下建仓区·多周期组合效果分析
================================================================
周期数据来源：
  日线/周线: westock kline（长历史，完整回测）
  60m/30m/15m: 新浪5分钟K线聚合（约22个交易日窗口，近期样本）

信号：建仓区 = VARO7 < 10（VARO7 = EMA((C-LLV(LOW,27))/(HHV(HIGH,34)-LLV(LOW,27))*4,4)*25）
组合：单周期 + 日线×周线共振 + 日线×60m共振

用法: python3 backtest_yitong_multi.py [--limit N]
输出: outputs/一统天下多周期组合分析.md
================================================================
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
BATCH = 20
WORKERS = 4

# ============================================================
# 数据获取
# ============================================================
def cli(cmd, timeout=180):
    full = WESTOCK + cmd.split()
    for attempt in range(5):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            out = r.stdout or ""
            if out.strip() and "执行失败" not in out and "SKILL_0" not in out:
                return out
        except Exception:
            pass
        time.sleep(2)
    return ""

def fetch_kline(symbols, period, limit):
    """westock 日线/周线 → {symbol: [bars]}"""
    md = cli(f"kline {','.join(symbols)} --period {period} --limit {limit} --fq qfq")
    groups = {}
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 7 or "symbol" in parts[0]:
            continue
        try:
            sym = parts[0]
            bar = {"date": parts[1], "open": float(parts[2]), "close": float(parts[3]),
                   "high": float(parts[4]), "low": float(parts[5])}
            groups.setdefault(sym, []).append(bar)
        except ValueError:
            continue
    for sym in groups:
        groups[sym].sort(key=lambda x: x["date"])
    return groups

def fetch_sina_5m(symbol, datalen=1023):
    """新浪5分钟K线（带重试+间隔）"""
    from urllib.request import urlopen
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService"
           f".getKLineData?symbol={symbol}&scale=5&ma=no&datalen={datalen}")
    for attempt in range(4):
        try:
            txt = urlopen(url, timeout=20).read().decode("utf-8", errors="replace")
            m = re.search(r"\((\[.*\])\)", txt, re.S)
            if not m:
                return []
            rows = json.loads(m.group(1))
            return [{"date": x["day"][:10], "time": x["day"][11:16],
                     "open": float(x["open"]), "close": float(x["close"]),
                     "high": float(x["high"]), "low": float(x["low"])} for x in rows]
        except Exception:
            if attempt < 3:
                time.sleep(3)
    return []

def aggregate(bars_5m, period_min):
    """5分钟K线聚合为 N 分钟K线"""
    out = []
    chunk = []
    for b in bars_5m:
        chunk.append(b)
        if len(chunk) >= period_min // 5:
            out.append({"date": chunk[0]["date"], "open": chunk[0]["open"],
                        "close": chunk[-1]["close"],
                        "high": max(x["high"] for x in chunk),
                        "low": min(x["low"] for x in chunk)})
            chunk = []
    return out

# ============================================================
# 建仓区指标
# ============================================================
def compute_varo7(bars):
    n = len(bars)
    lows = [b["low"] for b in bars]
    highs = [b["high"] for b in bars]
    closes = [b["close"] for b in bars]
    varo7 = [40.0] * n
    for i in range(33, n):
        v5 = min(lows[i - 26:i + 1])
        v6 = max(highs[i - 33:i + 1])
        raw = (closes[i] - v5) / (v6 - v5) * 4 * 25 if v6 > v5 else 40.0
        varo7[i] = raw if i == 33 else (raw * 2 + varo7[i - 1] * 3) / 5
    return varo7

def build_signals(bars, varo7):
    """建仓区进入信号（首次<10）"""
    sigs = []
    in_jcq = False
    for i in range(35, len(bars)):
        if varo7[i] < 10 and not in_jcq:
            sigs.append(i)
            in_jcq = True
        elif varo7[i] >= 10:
            in_jcq = False
    return sigs

def backtest_series(bars, varo7, hold_days, start="2025-01-01"):
    """单周期回测 → [收益...]"""
    rets = []
    sigs = build_signals(bars, varo7)
    closes = [b["close"] for b in bars]
    dates = [b["date"] for b in bars]
    n = len(bars)
    for idx in sigs:
        if dates[idx] < start or idx + hold_days >= n:
            continue
        e = closes[idx]
        if e <= 0:
            continue
        rets.append((closes[idx + hold_days] - e) / e * 100)
    return rets

def stats(lst):
    if not lst:
        return None
    n = len(lst)
    win = sum(1 for x in lst if x > 0)
    avg = sum(lst) / n
    gains = [x for x in lst if x > 0]
    losses = [x for x in lst if x <= 0]
    pl = (sum(gains) / len(gains)) / abs(sum(losses) / len(losses)) if gains and losses else 0
    return {"n": n, "win_rate": win / n * 100, "avg": avg, "pl": pl}

# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sina-limit", type=int, default=60, help="新浪分钟回测股票数（慢）")
    args = ap.parse_args()

    pool = []
    with open("/sandbox/workspace/hs300.csv", encoding="utf-8") as f:
        for ln in f:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                pool.append((parts[0].strip(), parts[1].strip()))
    if args.limit:
        pool = pool[:args.limit]
    syms = [c for c, _ in pool]

    L = []
    A = L.append
    A(f"# 📊 一统天下·建仓区 多周期组合分析\n")
    A(f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')} | **样本**: 沪深300成分股 | **逻辑**: VARO7<10\n")

    # ═══ 1. 日线/周线 完整回测 ═══
    for period, label, klimit, hold in (("day", "日线", 500, 20), ("week", "周线", 120, 8)):
        print(f"[INFO] 拉取{label}数据...", flush=True)
        bars_map = {}
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {}
            for i in range(0, len(syms), BATCH):
                futs[ex.submit(fetch_kline, syms[i:i + BATCH], period, klimit)] = 1
            for f in as_completed(futs):
                for k, v in f.result().items():
                    if len(v) > 40:
                        bars_map[k] = v
        A(f"\n## {label}周期（{len(bars_map)}只样本）\n")
        all_r = []
        for sym, bars in bars_map.items():
            varo7 = compute_varo7(bars)
            all_r.extend(backtest_series(bars, varo7, hold, "2025-01-01"))
        st = stats(all_r)
        if st:
            A(f"- 持有{hold}根K线: **{st['n']}个信号**, 胜率 {st['win_rate']:.1f}%, 平均 {st['avg']:+.2f}%, 盈亏比 {st['pl']:.2f}")
        # 信号当前状态（最新是否在建仓区）
        in_jcq_now = sum(1 for sym, bars in bars_map.items() if len(bars) > 35 and compute_varo7(bars)[-1] < 10)
        A(f"- 当前处于建仓区: {in_jcq_now} 只")

    # ═══ 2. 分钟周期（新浪5分钟聚合，约22交易日） ═══
    A(f"\n## 分钟周期（新浪5分钟聚合·近期窗口约22交易日，样本有限仅参考）\n")
    print("[INFO] 拉取新浪5分钟数据（慢）...", flush=True)
    sina_syms = syms[:args.sina_limit]
    m5_map = {}
    for i, s in enumerate(sina_syms):
        rows = fetch_sina_5m(s)
        if len(rows) > 300:
            m5_map[s] = rows
        if (i + 1) % 10 == 0:
            print(f"  [进度] {i+1}/{len(sina_syms)}", flush=True)
        time.sleep(1)
    print(f"[INFO] 新浪5分钟成功 {len(m5_map)} 只")
    for pmin, label, hold in ((15, "15分钟", 16), (30, "30分钟", 8), (60, "60分钟", 4)):
        all_r = []
        for sym, rows in m5_map.items():
            bars = aggregate(rows, pmin)
            if len(bars) < 40:
                continue
            varo7 = compute_varo7(bars)
            # 近期回测：用后半段数据（前半段预热）
            rets = []
            for idx in build_signals(bars, varo7):
                if idx < 35 or idx + hold >= len(bars):
                    continue
                e = bars[idx]["close"]
                if e > 0:
                    rets.append((bars[idx + hold]["close"] - e) / e * 100)
            all_r.extend(rets)
        st = stats(all_r)
        if st:
            A(f"- {label}: **{st['n']}个信号**, 胜率 {st['win_rate']:.1f}%, 平均 {st['avg']:+.2f}%, 盈亏比 {st['pl']:.2f}")
        else:
            A(f"- {label}: 样本不足")

    # ═══ 3. 组合分析（日线×周线共振，日线×60m共振） ═══
    A(f"\n## 组合共振分析\n")
    # 日线×周线：需两只都拉——简化用日线池 ∩ 周线池
    day_map, week_map = {}, {}
    print("[INFO] 组合分析数据...", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for i in range(0, len(syms), BATCH):
            futs[ex.submit(fetch_kline, syms[i:i + BATCH], "day", 500)] = 1
        for f in as_completed(futs):
            for k, v in f.result().items():
                if len(v) > 40:
                    day_map[k] = v
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for i in range(0, len(syms), BATCH):
            futs[ex.submit(fetch_kline, syms[i:i + BATCH], "week", 120)] = 1
        for f in as_completed(futs):
            for k, v in f.result().items():
                if len(v) > 40:
                    week_map[k] = v
    common = set(day_map) & set(week_map)
    A(f"- 日线∩周线样本: {len(common)} 只")
    # 共振：周线建仓区成立后（周线VARO7<10），日线建仓区信号
    combo_r = []
    for sym in common:
        wb = week_map[sym]
        wv = compute_varo7(wb)
        w_sig = build_signals(wb, wv)
        if not w_sig:
            continue
        w_last = w_sig[-1]
        db = day_map[sym]
        dv = compute_varo7(db)
        for idx in build_signals(db, dv):
            if idx + 20 >= len(db):
                continue
            # 日线信号在最近一次周线建仓区之后
            w_date = wb[w_last]["date"]
            d_date = db[idx]["date"]
            if d_date >= w_date:
                e = db[idx]["close"]
                if e > 0:
                    combo_r.append((db[idx + 20]["close"] - e) / e * 100)
    st = stats(combo_r)
    if st:
        A(f"- **日线建仓区 + 周线建仓区共振**（持20日）: {st['n']}信号, 胜率 {st['win_rate']:.1f}%, 平均 {st['avg']:+.2f}%, 盈亏比 {st['pl']:.2f}")
    else:
        A(f"- 日线+周线共振: 样本不足")

    report = "\n".join(L)
    path = "/sandbox/workspace/outputs/一统天下多周期组合分析.md"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n[OK] 报告: {path}")

if __name__ == "__main__":
    main()
