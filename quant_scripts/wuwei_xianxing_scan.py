#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wuwei_xianxing_scan.py —— 无为"显性建仓标准"（倍量+实体5%+无长上影）选股扫描+信号提取
=====================================================================================
规则来源：张德涛（无为老师）《交易必杀计》显性建仓成功标准：
  ① 量：至少为倍量（当日成交量 >= 2 × 前一日成交量）
  ② 价：实体 >= 5%，实体 = (收盘价-开盘价)/昨日收盘价
  ③ 影线：最好无上影线，上影线越短越好
  ④ 周期：60分钟或日线任一周期（本回测用日线）

输出：outputs/xianxing_signals_{batch}.json —— 每条信号含多档持有期收益
用法：python3 wuwei_xianxing_scan.py --batch 0 --total 2 --workers 4
"""
import subprocess, sys, os, re, json, time, random, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
OUT_DIR = "/sandbox/workspace/outputs"
os.makedirs(OUT_DIR, exist_ok=True)

def run_westock(args, timeout=120):
    for attempt in range(4):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            out = r.stdout
            if "执行失败" in out or "数据为空" in out and "|" not in out:
                time.sleep(1 + attempt)
                continue
            return out
        except Exception:
            time.sleep(1 + attempt)
    return ""

def parse_kline_batch(txt):
    """解析westock批量/单股K线markdown表。
    批量列序: symbol|date|open|last|high|low|volume|amount|exchange (date降序)
    单股列序: date|open|last|high|low|volume|amount|exchange (date降序)
    返回 {code: [row升序]}，row含 date/open/close/high/low/volume
    """
    stocks = {}
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if not parts or parts[0] == "---":
            continue
        if "date" in parts:
            header = parts
            continue
        if not header:
            continue
        try:
            di = header.index("date")
            has_symbol = header[0] == "symbol"
            if has_symbol:
                code = parts[0]
                oi, li, hi, loi, vi = (header.index(k) for k in ("open", "last", "high", "low", "volume"))
                date = parts[di]
            else:
                code = None
                oi, li, hi, loi, vi = (header.index(k) for k in ("open", "last", "high", "low", "volume"))
                date = parts[di]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                continue
            row = {
                "date": date,
                "open": float(parts[oi]),
                "close": float(parts[li]),
                "high": float(parts[hi]),
                "low": float(parts[loi]),
                "volume": float(parts[vi]),
            }
            if code is None:
                code = "single"
            stocks.setdefault(code, []).append(row)
        except (ValueError, IndexError):
            continue
    for code in stocks:
        stocks[code].sort(key=lambda r: r["date"])  # 升序
    return stocks

def load_pool():
    """读取主板清单并过滤（排除ST/PT/退市/非主板代码）"""
    codes = []
    with open("/sandbox/workspace/all_mainboard.csv") as f:
        next(f)
        for l in f:
            l = l.strip()
            if not l:
                continue
            code, name = l.split(",", 1)
            name = name.strip()
            if "ST" in name.upper() or "PT" in name.upper() or "退" in name:
                continue
            if not re.match(r"^(6\d{5}|0\d{5})$", code):
                continue
            if code.startswith("688") or code.startswith("300") or code.startswith("301"):
                continue
            if code.startswith("8") or code.startswith("43") or code.startswith("83") or code.startswith("87"):
                continue
            pref = "sh" if code.startswith("6") else "sz"
            codes.append(f"{pref}{code}")
    return codes

def fetch_regime():
    """上证指数 MA60/MA120 → 每日牛熊震荡标记"""
    txt = run_westock(["kline", "sh000001", "--period", "day", "--limit", "1000"])
    rows = parse_kline_batch(txt).get("single", [])
    regime = {}
    closes = [r["close"] for r in rows]
    for i in range(len(rows)):
        if i < 119:
            regime[rows[i]["date"]] = "震荡"
            continue
        ma60 = sum(closes[i-59:i+1]) / 60
        ma120 = sum(closes[i-119:i+1]) / 120
        cur = closes[i]
        if cur > ma60 > ma120:
            regime[rows[i]["date"]] = "牛"
        elif cur < ma60 < ma120:
            regime[rows[i]["date"]] = "熊"
        else:
            regime[rows[i]["date"]] = "震荡"
    return regime

def detect_signals(code, rows):
    """检测显性建仓信号（多档上影线过滤），计算多持有期收益。
    同时返回该股票全样本基准（任意日买入持有H日的平均收益与胜率），用于alpha检验"""
    signals = []
    n = len(rows)
    if n < 70:
        return signals, {}
    # 全样本基准：任意交易日收盘买入，持有H日
    base = {}
    for H in (5, 10, 20, 60):
        rets = []
        for i in range(1, n - H):
            if rows[i]["close"] > 0 and rows[i + H]["close"] > 0:
                rets.append(rows[i + H]["close"] / rows[i]["close"] - 1)
        if rets:
            base[H] = {"avg": round(sum(rets) / len(rets) * 100, 2),
                       "win": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1)}
    for i in range(1, n - 60):
        cur, prev = rows[i], rows[i-1]
        if cur["close"] <= cur["open"]:
            continue
        if prev["volume"] <= 0:
            continue
        # ① 倍量
        vol_ratio = cur["volume"] / prev["volume"]
        if vol_ratio < 2.0:
            continue
        # ② 实体>=5%（相对昨收）
        body_pct = (cur["close"] - cur["open"]) / prev["close"]
        if body_pct < 0.05:
            continue
        # ③ 上影线占比（上影/实体），全档记录（分析时按档位筛选）
        body = cur["close"] - cur["open"]
        upper_shadow = cur["high"] - cur["close"]  # 阳线：上影=最高-收盘
        if body > 0:
            shadow_pct = upper_shadow / body
        else:
            shadow_pct = 1.0
        # 持有期收益（信号日收盘买入）
        base_price = cur["close"]
        rets = {}
        for H in (5, 10, 20, 60):
            if i + H < n:
                rets[f"ret_{H}"] = rows[i + H]["close"] / base_price - 1
            else:
                rets[f"ret_{H}"] = None
        if any(v is None for v in rets.values()):
            continue
        signals.append({
            "code": code,
            "date": cur["date"],
            "open": cur["open"],
            "close": cur["close"],
            "prev_close": prev["close"],
            "vol_ratio": round(vol_ratio, 2),
            "body_pct": round(body_pct * 100, 2),
            "shadow_pct": round(shadow_pct * 100, 1),
            "pct_chg": round((cur["close"] / prev["close"] - 1) * 100, 2),
            "ret_5": round(rets["ret_5"] * 100, 2),
            "ret_10": round(rets["ret_10"] * 100, 2),
            "ret_20": round(rets["ret_20"] * 100, 2),
            "ret_60": round(rets["ret_60"] * 100, 2),
        })
    return signals, base

def work_batch(codes, regime):
    """批量4只拉取+检测信号。返回 (results, bases)"""
    results = []
    bases = {}
    txt = run_westock(["kline", ",".join(codes), "--period", "day", "--limit", "1000", "--fq", "qfq"])
    parsed = parse_kline_batch(txt)
    for code in codes:
        rows = parsed.get(code) or parsed.get("single", [])
        if len(rows) < 70:
            results.append((code, 0, []))
            continue
        sigs, base = detect_signals(code, rows)
        for s in sigs:
            s["regime"] = regime.get(s["date"], "震荡")
        results.append((code, len(rows), sigs))
        if sigs:
            bases[code] = base
    return results, bases

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=0, help="批次号")
    ap.add_argument("--total", type=int, default=2, help="总批次数")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit-pool", type=int, default=0, help="只取前N只（调试用）")
    args = ap.parse_args()

    codes = load_pool()
    if args.limit_pool > 0:
        codes = codes[:args.limit_pool]
    random.seed(args.seed)
    random.shuffle(codes)
    per = (len(codes) + args.total - 1) // args.total
    chunk = codes[args.batch * per:(args.batch + 1) * per]
    print(f"[batch {args.batch}] 池大小={len(codes)} 本批={len(chunk)}", flush=True)

    regime = fetch_regime()
    print(f"[batch {args.batch}] 指数regime日数={len(regime)}", flush=True)

    all_signals = []
    all_bases = {}
    stats = {"ok": 0, "empty": 0, "fail": 0}
    t0 = time.time()
    # 每4只一批（westock批量接口上限约4只）
    batches = [chunk[i:i+4] for i in range(0, len(chunk), 4)]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work_batch, b, regime): i for i, b in enumerate(batches)}
        done = 0
        for fut in as_completed(futs):
            results, bases = fut.result()
            all_bases.update(bases)
            for code, nrows, sigs in results:
                done += 1
                if nrows > 0:
                    stats["ok"] += 1
                else:
                    stats["empty"] += 1
                if sigs:
                    all_signals.extend(sigs)
            if done % 100 == 0 or done == len(chunk):
                el = time.time() - t0
                print(f"[batch {args.batch}] {done}/{len(chunk)} 用时{el:.0f}s 信号累计{len(all_signals)}", flush=True)

    out = os.path.join(OUT_DIR, f"xianxing_signals_b{args.batch}.json")
    with open(out, "w") as f:
        json.dump({"batch": args.batch, "codes": len(chunk), "signals": all_signals, "bases": all_bases, "stats": stats}, f, ensure_ascii=False)
    print(f"[batch {args.batch}] 完成 信号={len(all_signals)} 保存={out} 用时={time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
