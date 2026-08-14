#!/usr/bin/env python3
"""
yitong_60m_fullscan.py —— 60分钟建仓区·全A股主板验证
====================================================
新浪5分钟K线聚合60分钟 → VARO7<10建仓区 → 持有4根60分钟K线(约2-3天)
样本: all_mainboard.csv 全主板
用法: python3 yitong_60m_fullscan.py [--limit N] [--workers 3]
输出: outputs/一统天下60m全市场验证.md
====================================================
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_sina_5m(symbol, datalen=1023, workers_share=0):
    from urllib.request import urlopen
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService"
           f".getKLineData?symbol={symbol}&scale=5&ma=no&datalen={datalen}")
    for attempt in range(3):
        try:
            txt = urlopen(url, timeout=20).read().decode("utf-8", errors="replace")
            m = re.search(r"\(\[(.*)\]\)", txt, re.S)
            if not m:
                return []
            rows = json.loads(m.group(1))
            return [{"date": x["day"][:10], "open": float(x["open"]), "close": float(x["close"]),
                     "high": float(x["high"]), "low": float(x["low"])} for x in rows]
        except Exception:
            if attempt < 2:
                time.sleep(2.5)
    return []

def aggregate(bars_5m, period_min=60):
    out, chunk = [], []
    for b in bars_5m:
        chunk.append(b)
        if len(chunk) >= period_min // 5:
            out.append({"date": chunk[0]["date"], "open": chunk[0]["open"],
                        "close": chunk[-1]["close"], "high": max(x["high"] for x in chunk),
                        "low": min(x["low"] for x in chunk)})
            chunk = []
    return out

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

def analyze(symbol, name):
    rows = fetch_sina_5m(symbol)
    if len(rows) < 500:
        return None
    bars = aggregate(rows, 60)
    if len(bars) < 40:
        return None
    varo7 = compute_varo7(bars)
    closes = [b["close"] for b in bars]
    # 建仓区信号（后半段，留34根预热）
    rets = []
    in_jcq = False
    for i in range(35, len(bars) - 4):
        if varo7[i] < 10 and not in_jcq:
            in_jcq = True
            e = closes[i]
            if e > 0:
                rets.append((closes[i + 4] - e) / e * 100)  # 持有4根60m（约2-3天）
        elif varo7[i] >= 10:
            in_jcq = False
    in_now = varo7[-1] < 10
    return {"rets": rets, "in_now": in_now, "n60": len(bars), "last": closes[-1]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    pool = []
    with open("/sandbox/workspace/all_mainboard.csv", encoding="utf-8-sig") as f:
        next(f)
        for ln in f:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                code = parts[0].strip()
                if code.startswith(("688", "300", "301")) or "ST" in parts[1].upper() or "退" in parts[1]:
                    continue
                pool.append(("sh" + code if code.startswith("6") else "sz" + code, parts[1].strip()))
    if args.limit:
        pool = pool[:args.limit]
    print(f"[INFO] 60分钟建仓区全市场验证: {len(pool)} 只（新浪5分钟聚合）", flush=True)
    t0 = time.time()
    all_rets, in_now_list, done = [], [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(analyze, c, n): (c, n) for c, n in pool}
        for f in as_completed(futs):
            r = f.result()
            done += 1
            if r:
                all_rets.extend(r["rets"])
                if r["in_now"]:
                    in_now_list.append(futs[f][0])
            if done % 100 == 0:
                print(f"  [进度] {done}/{len(pool)} | 信号 {len(all_rets)}", flush=True)
    elapsed = time.time() - t0
    n = len(all_rets)
    win = sum(1 for x in all_rets if x > 0)
    avg = sum(all_rets) / n if n else 0
    gains = [x for x in all_rets if x > 0]
    losses = [x for x in all_rets if x <= 0]
    pl = (sum(gains)/len(gains))/abs(sum(losses)/len(losses)) if gains and losses else 0
    report = f"""# 📊 一统天下·60分钟建仓区 全A股主板验证

**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**样本**: {len(pool)} 只主板（剔除ST/退市/科创创业）
**有效**: 实际拉取到5分钟数据并聚合成功的股票数 = {done} 只处理完成
**信号样本**: {n} 个（持有4根60分钟K线≈2-3天）
**胜率**: {win/n*100 if n else 0:.1f}%
**平均收益**: {avg:+.2f}%
**盈亏比**: {pl:.2f}
**耗时**: {elapsed:.0f}s

## 当前处于60分钟建仓区标的（{len(in_now_list)}只）
"""
    for s in in_now_list[:40]:
        report += f"- {s}\n"
    path = "/sandbox/workspace/outputs/一统天下60m全市场验证.md"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report[:1500])
    print(f"\n[OK] 报告: {path}")

if __name__ == "__main__":
    main()
