#!/usr/bin/env python3
"""
backtest_yitong.py —— 一统天下指标「建仓区」逻辑回测（沪深300成分股）
================================================================
一统天下指标核心逻辑（张穗鸿系列·民间流传版）：
  建仓区 = VAR8 > 0：
    VAR3 = SMA(|LOW-昨LOW|,13,1)/SMA(MAX(LOW-昨LOW,0),13,1)*100   # 下跌动量
    VAR4 = EMA(VAR3*13, 13)                                        # 动量放大
    VAR5 = LLV(LOW,34)  # 34日新低
    VAR6 = HHV(VAR4,34) # 34日动量峰值
    VAR7 = IF(LLV(LOW,55),1,0)                                     # 55日低位确认
    VAR8 = EMA(IF(LOW<=VAR5,(VAR4+VAR6*2)/2,0),3)/618*VAR7         # 吸筹强度
  备钱 = VAR8 见顶回落（建仓尾声）
  启动 = XL1(MA(LOW,2)*0.96) 上穿 XL2(MA(LOW,26)*0.85)

回测信号：
  S1 建仓区触发: VAR8 首次>0（当天确认）
  S2 备钱(回落): VAR8<REF(VAR8,1) 且之前>0（建仓尾声）
  S3 启动金叉: XL3 成立

持有期: 5/10/20/40/60 交易日，信号日收盘买入
对比: 全部样本同期等权（基准）

用法: python3 backtest_yitong.py [--limit N] [--start 2025-01-01]
================================================================
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
BATCH = 20
KLIMIT = 500
WORKERS = 4

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

def parse_kline(md):
    lines = [l.strip() for l in md.split('\n') if l.strip()]
    hi = next((i for i, ln in enumerate(lines) if ln.startswith('| symbol |')), None)
    headers = None
    if hi is None:
        hi = next((i for i, ln in enumerate(lines) if '| date |' in ln), None)
        if hi is None:
            return {}
        headers = [h.strip() for h in lines[hi].split('|')[1:-1]]
        sym_idx, start = 0, hi
        groups = {}
        for ln in lines[hi+2:]:
            if not ln.startswith('|'): continue
            parts = [p.strip() for p in ln.split('|')[1:-1]]
            if len(parts) < len(headers): continue
            row = dict(zip(headers, parts))
            sym = 'unknown'
            groups.setdefault(sym, []).append(row)
        return groups
    headers = [h.strip() for h in lines[hi].split('|')[1:-1]]
    groups = {}
    for ln in lines[hi+2:]:
        if not ln.startswith('|'): continue
        parts = [p.strip() for p in ln.split('|')[1:-1]]
        if len(parts) < len(headers): continue
        row = dict(zip(headers, parts))
        groups.setdefault(row['symbol'], []).append(row)
    return groups

def fetch_batch(symbols):
    md = cli(f"kline {','.join(symbols)} --period day --limit {KLIMIT} --fq qfq")
    if not md:
        return {}
    return parse_kline(md)

# ============================================================
# 一统天下指标
# ============================================================
def sma_series(vals, n, m=1):
    """通达信SMA(X,N,M): Y=(M*X+(N-M)*Y')/N"""
    out = []
    prev = vals[0] if vals else 0
    for v in vals:
        prev = (m * v + (n - m) * prev) / n
        out.append(prev)
    return out

def ema_series(vals, n):
    out, k = [], 2 / (n + 1)
    prev = vals[0] if vals else 0
    for v in vals:
        prev = v if not out else v * k + prev * (1 - k)
        out.append(prev)
    return out

def compute_yitong(bars):
    """一统天下·建仓区（ima正版逻辑）：
    建仓区 = VARO7 < 10；VARO7 = EMA((C-LLV(LOW,27))/(HHV(HIGH,34)-LLV(LOW,27))*4,4)*25
    下单 = 3*SMA(RSV21,5,1)-2*SMA(SMA(RSV21,5,1),3,1) 金叉上穿10
    乖离低买 = BIAS金叉且乖离1<-9
    准备建仓 = L<=LLV(L,30)时 VARC*0.03 的EMA
    """
    n = len(bars)
    lows = [b["low"] for b in bars]
    highs = [b["high"] for b in bars]
    closes = [b["close"] for b in bars]
    # VARO7
    varo7 = [40.0] * n
    for i in range(33, n):
        varo5 = min(lows[i - 26:i + 1])
        varo6 = max(highs[i - 33:i + 1])
        if varo6 > varo5:
            raw = (closes[i] - varo5) / (varo6 - varo5) * 4 * 25
        else:
            raw = 40.0
        if i == 33:
            varo7[i] = raw
        else:
            varo7[i] = (raw * 2 + varo7[i - 1] * 3) / 5  # EMA(,4) 近似 k=2/5
    # 下单指标（KDJ式）
    def sma_series(vals, nn, mm=1):
        out, prev = [], vals[0] if vals else 0
        for v in vals:
            prev = (mm * v + (nn - mm) * prev) / nn
            out.append(prev)
        return out
    rsv = [0.0] * n
    for i in range(n):
        ll, hh = min(lows[max(0, i - 20):i + 1]), max(highs[max(0, i - 20):i + 1])
        rsv[i] = (closes[i] - ll) / (hh - ll) * 100 if hh > ll else 50
    sma5 = sma_series(rsv, 5)
    sma5_2 = sma_series(sma5, 3)
    xd = [3 * a - 2 * b for a, b in zip(sma5, sma5_2)]
    xiadan = [False] * n
    for i in range(1, n):
        if xd[i - 1] <= 10 and xd[i] > 10:
            xiadan[i] = True
    # 乖离低买
    def ma_series(vals, nn):
        out = []
        for i in range(len(vals)):
            if i < nn - 1:
                out.append(vals[i])
            else:
                out.append(sum(vals[i - nn + 1:i + 1]) / nn)
        return out
    ma6 = ma_series(closes, 6)
    ma12 = ma_series(closes, 12)
    ma24 = ma_series(closes, 24)
    bias = [(c - m6) / m6 * 100 + 2 * ((c - m12) / m12 * 100) + 3 * ((c - m24) / m24 * 100) for c, m6, m12, m24 in zip(closes, ma6, ma12, ma24)]
    bias = [b / 6 for b in bias]
    bias_ma = ma_series(bias, 3)
    guaili = [False] * n
    for i in range(1, n):
        if bias[i - 1] <= bias_ma[i - 1] and bias[i] > bias_ma[i] and bias_ma[i] < -9:
            guaili[i] = True
    return varo7, xiadan, guaili


def backtest(bars, hold_days, start_date="2025-01-01"):
    """返回 {s1:[...], s2:[...], s3:[...], bench:[...]} 每信号列表收益"""
    res = {"s1": [], "s2": [], "s3": [], "bench": []}
    if len(bars) < 70:
        return res
    varo7, xiadan, guaili = compute_yitong(bars)
    n = len(bars)
    closes = [b["close"] for b in bars]
    dates = [b["date"] for b in bars]
    # 信号日
    sig = {"s1": [], "s2": [], "s3": []}
    in_jcq = False
    for i in range(35, n):
        # S1: 建仓区进入（VARO7 首次 < 10）
        if varo7[i] < 10 and not in_jcq:
            sig["s1"].append(i)
            in_jcq = True
        elif varo7[i] >= 10:
            in_jcq = False
        # S2: 建仓区内 + 下单信号
        if varo7[i] < 10 and xiadan[i]:
            sig["s2"].append(i)
        # S3: 建仓区内 + 乖离低买
        if varo7[i] < 10 and guaili[i]:
            sig["s3"].append(i)
    # 去重（10日内重复信号只取第一个）
    for k in sig:
        dedup = []
        for idx in sig[k]:
            if not dedup or idx - dedup[-1] >= 10:
                dedup.append(idx)
        sig[k] = dedup
    # 统计收益
    for k, idxs in sig.items():
        for idx in idxs:
            if dates[idx] < start_date or idx + hold_days >= n:
                continue
            entry = closes[idx]
            if entry <= 0:
                continue
            exit_p = closes[idx + hold_days]
            res[k].append((exit_p - entry) / entry * 100)
    # 基准：同区间所有交易日买入持有
    for i in range(60, n - hold_days):
        if dates[i] < start_date:
            continue
        entry = closes[i]
        if entry <= 0:
            continue
        res["bench"].append((closes[i + hold_days] - entry) / entry * 100)
    return res

def stats(lst):
    if not lst:
        return None
    n = len(lst)
    win = sum(1 for x in lst if x > 0)
    avg = sum(lst) / n
    med = sorted(lst)[n // 2]
    gains = [x for x in lst if x > 0]
    losses = [x for x in lst if x <= 0]
    pl = (sum(gains) / len(gains)) / abs(sum(losses) / len(losses)) if gains and losses else 0
    # 最大回撤
    peak, mdd = 0, 0
    cum = 0
    for x in lst:
        cum += x
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return {"n": n, "win_rate": win / n * 100, "avg": avg, "median": med,
            "profit_loss": pl, "max_dd": mdd}

# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--holds", default="10,20,40")
    args = ap.parse_args()
    holds = [int(x) for x in args.holds.split(",")]

    pool = []
    with open("/sandbox/workspace/hs300.csv", encoding="utf-8") as f:
        for ln in f:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                pool.append((parts[0].strip(), parts[1].strip()))
    if args.limit:
        pool = pool[:args.limit]
    print(f"[INFO] 沪深300成分股 {len(pool)} 只，拉取日线...")
    t0 = time.time()
    bars_map = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for i in range(0, len(pool), BATCH):
            syms = [c for c, _ in pool[i:i + BATCH]]
            futs[ex.submit(fetch_batch, syms)] = syms
        done = 0
        for f in as_completed(futs):
            m = f.result()
            done += 1
            print(f"  [进度] {done}/{len(futs)} 批完成", flush=True)
            for sym, rows in m.items():
                if len(rows) < 70:
                    continue
                bars = []
                for r in rows:
                    try:
                        bars.append({"date": r["date"], "open": float(r["open"]),
                                     "close": float(r["last"]), "high": float(r["high"]),
                                     "low": float(r["low"]), "vol": float(r["volume"])})
                    except (ValueError, KeyError):
                        continue
                bars.sort(key=lambda x: x["date"])
                if len(bars) >= 70:
                    bars_map[sym] = bars
    print(f"[INFO] 数据拉取完成 {len(bars_map)} 只，耗时 {time.time()-t0:.0f}s")

    # 回测
    all_res = {h: {"s1": [], "s2": [], "s3": [], "bench": []} for h in holds}
    for sym, bars in bars_map.items():
        for h in holds:
            r = backtest(bars, h, args.start)
            for k in ("s1", "s2", "s3", "bench"):
                all_res[h][k].extend(r[k])

    # 输出报告
    out = []
    out.append(f"# 📊 一统天下·建仓区 回测报告（ima正版逻辑）（沪深300成分股）\n")
    out.append(f"**回测区间**: {args.start} ~ 今日 | **样本**: {len(bars_map)} 只 | **数据**: westock前复权日线\n")
    out.append(f"> 建仓区信号: S1=建仓区触发(VARO7<10) | S2=建仓区+下单信号 | S3=建仓区+乖离低买(BIAS金叉<-9) | 基准=全样本同期买入持有\n")
    for h in holds:
        out.append(f"\n## 持有 {h} 交易日\n")
        out.append("| 信号 | 样本 | 胜率 | 平均收益 | 中位数 | 盈亏比 | 最大回撤 |")
        out.append("|:----|:----:|:----:|:----:|:----:|:----:|:----:|")
        for k, label in (("s1", "S1建仓区"), ("s2", "S2备钱"), ("s3", "S3启动"), ("bench", "基准")):
            st = stats(all_res[h][k])
            if not st:
                out.append(f"| {label} | 0 | - | - | - | - | - |")
            else:
                out.append(f"| {label} | {st['n']} | {st['win_rate']:.1f}% | {st['avg']:+.2f}% | {st['median']:+.2f}% | {st['profit_loss']:.2f} | {st['max_dd']:.1f}% |")
    report = "\n".join(out)
    path = "/sandbox/workspace/outputs/一统天下建仓区回测报告.md"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n[OK] 报告: {path}")

if __name__ == "__main__":
    main()
