#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
强势体系 · 回测脚本
==================
对「武威量价操盘 2026-03-31 月线选股」的 51 只标的，应用
「强势突破买入 + 趋势跟踪止盈」操作体系做历史回测：

买入四关（本回测实现）：
  形态关：空中加油 / 箱体突破 / 高阳快速推升（任一）
  量价关：突破日放量（量比 >= 1.5）
  评分关：以上强势形态信号本身即视为技术评分达标
  环境关：买点日上证指数站上 MA60（代理大盘温度计 >= 40）

止盈（趋势跟踪，非预设目标位）：
  - 收盘价跌破 MA20        -> 卖出（MA20破位）
  - MACD 死叉(DIF下穿DEA)  -> 卖出（信号失效）
  - 持有至回测期末(07-16)  -> 以末日收盘卖出

用法：
  python3 backtest.py --mode fetch     # 仅拉取K线并缓存（可多次增量补齐）
  python3 backtest.py --mode analyze   # 仅读缓存做回测统计
  python3 backtest.py                  # 先fetch再analyze
"""
import subprocess, json, os, sys, time, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cache")
os.makedirs(CACHE, exist_ok=True)
POOL = os.path.join(BASE, "pool_51.txt")
START_DATE = "2026-03-31"
END_DATE = "2026-07-16"
NKLINE = 90  # 交易日数，覆盖 3月底 ~ 7月中

# ---------------- 工具 ----------------
def prefix(code):
    return ("sh" if code[0] == "6" else "sz") + code

def load_pool():
    stocks = []
    with open(POOL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                stocks.append((parts[0], parts[1]))
    return stocks

def parse_kline(txt):
    rows = []
    for line in txt.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 8:
            continue
        if cells[0] == "date":
            continue
        if set(cells[1]) <= set("-"):
            continue
        try:
            rows.append({
                "date": cells[0],
                "open": float(cells[1]),
                "close": float(cells[2]),
                "high": float(cells[3]),
                "low": float(cells[4]),
                "volume": float(cells[5]),
                "amount": float(cells[6]),
                "exchange": float(cells[7]) if cells[7] else 0.0,
            })
        except Exception:
            continue
    rows.sort(key=lambda r: r["date"])
    return rows

def fetch_kline(code, limit=NKLINE):
    pcode = prefix(code)
    cf = os.path.join(CACHE, f"{code}.json")
    if os.path.exists(cf):
        try:
            with open(cf) as f:
                return json.load(f)
        except Exception:
            pass
    for _ in range(3):
        try:
            out = subprocess.run(
                ["npx", "-y", "westock-data-skillhub@1.0.3", "kline", pcode,
                 "--period", "day", "--limit", str(limit), "--fq", "qfq"],
                capture_output=True, text=True, timeout=90)
            data = parse_kline(out.stdout)
            if data:
                with open(cf, "w") as f:
                    json.dump(data, f)
                return data
        except Exception:
            time.sleep(2)
    return None

def fetch_all(codes):
    def worker(code):
        return code, fetch_kline(code)
    res = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(worker, c) for c in codes]
        for fu in as_completed(futs):
            c, d = fu.result()
            res[c] = d
            sys.stdout.write(f"  {c}: {'OK' if d else 'FAIL'} ({len(res)}/{len(codes)})\n")
            sys.stdout.flush()
    return res

# ---------------- 指标 ----------------
def ema(vals, n):
    if not vals:
        return []
    k = 2 / (n + 1)
    e = [vals[0]]
    for i in range(1, len(vals)):
        e.append(vals[i] * k + e[-1] * (1 - k))
    return e

def macd(closes):
    e12 = ema(closes, 12)
    e26 = ema(closes, 26)
    dif = [e12[i] - e26[i] for i in range(len(closes))]
    dea = ema(dif, 9)
    hist = [2 * (dif[i] - dea[i]) for i in range(len(closes))]
    return dif, dea, hist

def sma(vals, n):
    out = [None] * len(vals)
    for i in range(len(vals)):
        if i + 1 >= n:
            out[i] = sum(vals[i - n + 1:i + 1]) / n
    return out

def enrich(rows):
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    n = len(rows)
    ma5 = sma(closes, 5); ma10 = sma(closes, 10)
    ma20 = sma(closes, 20); ma60 = sma(closes, 60)
    dif, dea, hist = macd(closes)
    vma5 = sma(vols, 5)
    # 九五至尊：13日量加权成本线（EMA(AMOUNT)/EMA(VOL)*0.01），JWZZ=价格偏离成本千分比
    amts = [r.get("amount", 0) or 0 for r in rows]
    e_amt = ema(amts, 13); e_vol = ema(vols, 13)
    cost13 = [(e_amt[i] / e_vol[i] * 0.01) if (e_amt[i] and e_vol[i]) else None for i in range(n)]
    jwzz = [((closes[i] - cost13[i]) / cost13[i] * 1000) if cost13[i] else None for i in range(n)]
    for i in range(n):
        rows[i].update({
            "ma5": ma5[i], "ma10": ma10[i], "ma20": ma20[i], "ma60": ma60[i],
            "dif": dif[i], "dea": dea[i], "hist": hist[i], "vma5": vma5[i],
            "vol_ratio": (vols[i] / vma5[i]) if (vma5[i] and vma5[i] > 0) else 0.0,
            "jwzz": jwzz[i],
        })
    return rows

# ---------------- 信号 ----------------
def find_buy(rows, start_idx):
    """从 start_idx 起找第一个强势突破买点，返回 (idx, 信号名) 或 (None,None)"""
    for i in range(start_idx, len(rows)):
        r = rows[i]
        if r["ma20"] is None or r["dif"] is None or r["ma20"] == 0:
            continue
        vol_ok = r["vol_ratio"] >= 1.5
        prev_hist = rows[i - 1]["hist"] if i > 0 else 0
        # 空中加油：0轴上方，柱翻红向上，价在MA5上
        ao = (r["dif"] > 0 and r["hist"] > 0 and r["hist"] >= prev_hist and r["close"] > r["ma5"])
        # 箱体突破：前20日窄幅(<18%)，今日放量突破前高，站上MA20
        box = False
        if i >= 20:
            win = rows[i - 20:i]
            hi = max(x["high"] for x in win); lo = min(x["low"] for x in win)
            if hi > 0 and (hi / lo) < 1.18 and r["close"] > hi and r["close"] > r["ma20"]:
                box = True
        # 高阳快速推升：近3日累计涨>8% 且放量
        gy = False
        if i >= 3:
            chg = (r["close"] - rows[i - 3]["close"]) / rows[i - 3]["close"]
            if chg > 0.08 and r["vol_ratio"] >= 1.3:
                gy = True
        # 九五至尊（张穗鸿）：价格偏离13日成本线 +9.5% 上穿（强势突破成本密集区）
        # 验证结论(398只×5年)：仅在高价股(>30元)+环境关内有效，低价股无效——须配环境关使用
        qswz = False
        if i >= 1 and r.get("jwzz") is not None and rows[i-1].get("jwzz") is not None:
            if r["jwzz"] > 95 and rows[i-1]["jwzz"] <= 95 and r["close"] > 30:
                qswz = True
        if (ao or box or gy or qswz) and vol_ok:
            sig = []
            if ao: sig.append("空中加油")
            if box: sig.append("箱体突破")
            if gy: sig.append("高阳快速推升")
            if qswz: sig.append("九五至尊")
            return i, "+".join(sig)
    return None, None

def simulate(rows, buy_idx):
    buy = rows[buy_idx]["close"]
    for j in range(buy_idx + 1, len(rows)):
        r = rows[j]
        if r["ma20"] is not None and r["ma20"] > 0 and r["close"] < r["ma20"]:
            return j, "MA20破位", (r["close"] - buy) / buy * 100.0
        if j > 0 and rows[j - 1]["dif"] >= rows[j - 1]["dea"] and r["dif"] < r["dea"]:
            return j, "MACD死叉", (r["close"] - buy) / buy * 100.0
    last = rows[-1]
    return len(rows) - 1, "持有至期末", (last["close"] - buy) / buy * 100.0

# ---------------- 主流程 ----------------
def run_fetch():
    stocks = load_pool()
    codes = [c for c, _ in stocks]
    print(f"[fetch] 拉取 {len(codes)} 只 + 上证指数 ...")
    data = fetch_all(codes)
    idx = fetch_kline("000001")  # 上证指数用于环境判断
    ok = sum(1 for v in data.values() if v)
    print(f"[fetch] 完成：{ok}/{len(codes)} 只成功，指数={'OK' if idx else 'FAIL'}")
    return data

def run_analyze():
    stocks = load_pool()
    data = {}
    for c, _ in stocks:
        cf = os.path.join(CACHE, f"{c}.json")
        if os.path.exists(cf):
            try:
                with open(cf) as f:
                    data[c] = json.load(f)
            except Exception:
                pass
    idx_rows = None
    icf = os.path.join(CACHE, "000001.json")
    if os.path.exists(icf):
        with open(icf) as f:
            idx_rows = enrich(json.load(f))
    idx_map = {r["date"]: r for r in idx_rows} if idx_rows else {}

    results = []
    for code, name in stocks:
        rows = data.get(code)
        if not rows:
            results.append({"code": code, "name": name, "status": "无数据"})
            continue
        rows = enrich(rows)
        # 起点：3-31 之后
        si = 0
        for k, r in enumerate(rows):
            if r["date"] > START_DATE:
                si = k
                break
        bidx, sig = find_buy(rows, si)
        rec = {"code": code, "name": name, "status": "无可操作买点"}
        if bidx is not None:
            selly, reason, ret = simulate(rows, bidx)
            buy_date = rows[bidx]["date"]; sell_date = rows[0]["date"]  # placeholder
            sell_date = rows[selly]["date"]
            # 环境关
            env = None
            if buy_date in idx_map:
                ir = idx_map[buy_date]
                env = (ir["ma60"] is not None and ir["ma60"] > 0 and ir["close"] > ir["ma60"])
            rec.update({
                "status": "可操作",
                "signal": sig,
                "buy_date": buy_date,
                "buy_price": round(rows[bidx]["close"], 2),
                "sell_date": sell_date,
                "sell_price": round(rows[selly]["close"], 2),
                "exit_reason": reason,
                "return_pct": round(ret, 2),
                "env_ok": env,
            })
        results.append(rec)

    # 汇总
    operable = [r for r in results if r["status"] == "可操作"]
    no_data = [r for r in results if r["status"] == "无数据"]
    env_ok_ops = [r for r in operable if r.get("env_ok")]
    wins = [r for r in operable if r["return_pct"] > 0]
    losses = [r for r in operable if r["return_pct"] <= 0]
    rets = [r["return_pct"] for r in operable]
    avg = sum(rets) / len(rets) if rets else 0
    rets_sorted = sorted(rets)
    med = rets_sorted[len(rets_sorted)//2] if rets_sorted else 0

    summary = {
        "total": len(stocks),
        "operable_loose": len(operable),
        "operable_loose_pct": round(len(operable)/len(stocks)*100, 1),
        "operable_strict_env": len(env_ok_ops),
        "operable_strict_pct": round(len(env_ok_ops)/len(stocks)*100, 1),
        "no_data": len(no_data),
        "win": len(wins), "loss": len(losses),
        "win_rate": round(len(wins)/len(operable)*100, 1) if operable else 0,
        "avg_return": round(avg, 2),
        "median_return": round(med, 2),
        "max_win": round(max(rets), 2) if rets else 0,
        "max_loss": round(min(rets), 2) if rets else 0,
    }
    out = {"summary": summary, "details": results}
    with open(os.path.join(BASE, "backtest_result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 打印
    print("\n====== 强势体系 · 51只回测汇总 ======")
    print(f"样本总数          : {summary['total']}")
    print(f"无可操作买点      : {summary['total']-summary['operable_loose']-summary['no_data']}")
    print(f"无数据(获取失败)  : {summary['no_data']}")
    print(f"--- 可操作比例（出现强势突破买点）---")
    print(f"  宽松口径        : {summary['operable_loose']} 只 / {summary['operable_loose_pct']}%")
    print(f"  严格口径(环境符合): {summary['operable_strict_env']} 只 / {summary['operable_strict_pct']}%")
    print(f"--- 操作后止盈盈利（对可操作 {summary['operable_loose']} 只）---")
    print(f"  盈利只数/亏损    : {summary['win']} / {summary['loss']}  (胜率 {summary['win_rate']}%)")
    print(f"  平均收益        : {summary['avg_return']}%")
    print(f"  收益中位数      : {summary['median_return']}%")
    print(f"  最大盈利/最大亏损: {summary['max_win']}% / {summary['max_loss']}%")
    print("\n--- 可操作明细 ---")
    for r in operable:
        print(f"  {r['code']} {r['name']:6s} {r['signal']:12s} 买{r['buy_date']}@{r['buy_price']} "
              f"卖{r['sell_date']}@{r['sell_price']} [{r['exit_reason']}] "
              f"收益{r['return_pct'] if False else r['return_pct']}% 环境{'✓' if r['env_ok'] else '✗'}")
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fetch", "analyze", "all"], default="all")
    args = ap.parse_args()
    if args.mode in ("fetch", "all"):
        run_fetch()
    if args.mode in ("analyze", "all"):
        run_analyze()
