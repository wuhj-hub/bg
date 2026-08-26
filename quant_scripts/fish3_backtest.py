#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fish3_backtest.py —— 鱼身三模式长历史重验（P0-3 · 2026-08-26）
================================================================
用腾讯proxy长历史（2013至今）重验鱼身三大模式：
  模式1 MACD空中加油 / 模式2 均线回踩支撑 / 模式3 箱体突破（有效性三条件）
输出回测卡（backtest_gate 门槛判定）+ 牛熊分层 + 大顶附近行为

用法：python3 fish3_backtest.py [--pool stock_pool.txt] [--max 30] [--hold 5 10 20]
"""
import json, os, sys, re, time, urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from fetch_history import fetch_stock_history
from backtest_gate import compute_gate, judge_gate, render_card, regime_map



def ma(closes, i, n):
    return sum(closes[i - n + 1:i + 1]) / n if i >= n - 1 else None


def ema_series(vals, n):
    k = 2 / (n + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def detect_air_refuel(rows, i):
    """模式1 MACD空中加油：DIF>0 DEA>0 DIF>=DEA 且 MACD柱刚翻红(<0.15) 且 收盘>MA5"""
    if i < 35:
        return False
    closes = [r["last"] for r in rows[:i + 1]]
    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema_series(dif, 9)
    hist = [2 * (d - e) for d, e in zip(dif, dea)]
    ma5 = ma(closes, i, 5)
    if dif[-1] > 0 and dea[-1] > 0 and dif[-1] >= dea[-1] and 0 < hist[-1] < 0.15:
        if ma5 and rows[i]["last"] > ma5:
            return True
    return False


def detect_pullback(rows, i):
    """模式2 均线回踩：MA20>MA60 多头 + 收盘偏离MA10<5% + 收盘>MA5"""
    if i < 60:
        return False
    closes = [r["last"] for r in rows[:i + 1]]
    ma20, ma60 = ma(closes, i, 20), ma(closes, i, 60)
    if not (ma20 and ma60 and ma20 > ma60):
        return False
    ma5, ma10 = ma(closes, i, 5), ma(closes, i, 10)
    if not (ma5 and ma10):
        return False
    dev = abs(rows[i]["last"] - ma10) / ma10 * 100
    return dev < 5 and rows[i]["last"] > ma5


def detect_box(rows, i):
    """模式3 箱体突破（简化三条件）：近40根箱体(高度<40%) + 当日收盘突破箱顶 + 量≥1.5倍均量"""
    if i < 45:
        return False
    box = rows[i - 43:i - 3]
    if len(box) < 15:
        return False
    box_closes = [r["last"] for r in box]
    box_top = max(box_closes)
    box_bot = min(box_closes)
    if box_bot <= 0 or (box_top - box_bot) / box_bot > 0.40:
        return False
    cur = rows[i]
    if cur["last"] <= box_top * 1.005:
        return False
    box_avg_vol = sum(r["volume"] for r in box) / len(box)
    if box_avg_vol <= 0 or cur["volume"] < box_avg_vol * 1.5:
        return False
    return True


DETECTORS = {"空中加油": detect_air_refuel, "均线回踩": detect_pullback, "箱体突破": detect_box}


def month_gate_hist(rows, i):
    """月线闸门（实盘同款）：个股月线收盘>MA6且MA6>MA12 才放行（BLOCK剔除）
    用日线近60根近似月线结构（20日均线≈月线MA6近似不准确，改用：近60日价格在MA20上方且MA20>MA60上行）"""
    if i < 60:
        return False
    closes = [r["last"] for r in rows[:i + 1]]
    ma20, ma60 = ma(closes, i, 20), ma(closes, i, 60)
    if not (ma20 and ma60):
        return False
    ma20_prev = ma(closes, i - 5, 20) if i >= 25 else ma20
    return rows[i]["last"] > ma20 > ma60 and ma20 >= ma20_prev * 0.995



def load_pool(fpath, max_n):
    codes = []
    try:
        for ln in open(fpath, encoding="utf-8"):
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            m = re.match(r"((?:sh|sz)\d{6})", s)
            if m:
                codes.append(m.group(1))
    except FileNotFoundError:
        print(f"❌ 池文件不存在: {fpath}")
    seen = set()
    out = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:max_n]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="stock_pool.txt")
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--hold", type=int, nargs="+", default=[5, 10, 20])
    args = ap.parse_args()

    idx = json.load(open(os.path.join(BASE, "data_hs300/上证指数_日K_2013至今.json"), encoding="utf-8"))
    regs = regime_map(idx)

    pool = load_pool(args.pool, args.max)
    print(f"样本池 {len(pool)} 只，拉取长历史（2013至今）…")
    cache_file = os.path.join(BASE, f"data_hs300/fish3_pool_{len(pool)}.json")
    if os.path.exists(cache_file):
        stock_data = json.load(open(cache_file, encoding="utf-8"))
        print(f"缓存命中: {len(stock_data)} 只")
    else:
        stock_data = {}
        for k, code in enumerate(pool):
            rows = fetch_stock_history(code)
            if rows:
                stock_data[code] = rows
            if (k + 1) % 5 == 0:
                print(f"  ...{k + 1}/{len(pool)}（{code} {len(rows)}根）")
            time.sleep(0.3)
        os.makedirs(os.path.join(BASE, "data_hs300"), exist_ok=True)
        json.dump(stock_data, open(cache_file, "w", encoding="utf-8"))
        print(f"数据缓存: {cache_file}（{len(stock_data)}只）")

    # 逐模式统计（实盘同款过滤：大盘环境牛/震荡 + 个股月线闸门）
    for mode, detect in DETECTORS.items():
        events_all, filtered_env, filtered_month = [], 0, 0
        for code, rows in stock_data.items():
            pm = {r["date"]: r["last"] for r in rows}
            for i in range(60, len(rows)):
                if not detect(rows, i):
                    continue
                d = rows[i]["date"]
                if regs.get(d, "震荡") == "熊市":  # 实盘大盘温度<40不出信号（近似）
                    filtered_env += 1
                    continue
                if not month_gate_hist(rows, i):  # 月线闸门
                    filtered_month += 1
                    continue
                events_all.append({"code": code, "date": d, "entry": rows[i]["last"]})
        print(f"\n════ 模式：{mode} 信号 {len(events_all)} 个（过滤：熊市{filtered_env} 月线{filtered_month}）════")
        for hold in args.hold:
            # 每只股票单独构建 price_map（信号后走势按各自价格）
            by_stock = {}
            for ev in events_all:
                by_stock.setdefault(ev["code"], []).append(ev)
            events_hold = []
            for code, evs in by_stock.items():
                pm = {r["date"]: r["last"] for r in stock_data[code]}
                dates = sorted(pm.keys())
                for ev in evs:
                    try:
                        idx_d = dates.index(ev["date"])
                        exit_p = pm[dates[min(idx_d + hold, len(dates) - 1)]]
                    except ValueError:
                        continue
                    events_hold.append({"date": ev["date"], "entry": ev["entry"], "exit": exit_p})
            card = compute_gate(events_hold, {}, idx, hold)
            if card:
                ok, reasons = judge_gate(card)
                extra = f"> 持有{hold}日 · 信号{len(events_hold)}个（样本池{len(pool)}只·2013至今）"
                md = render_card(f"鱼身{mode}·持{hold}日", card, reasons, ok, extra)
                os.makedirs(os.path.join(BASE, "outputs"), exist_ok=True)
                today = datetime.now().strftime("%Y-%m-%d")
                p = os.path.join(BASE, f"outputs/回测卡_鱼身{mode}_持{hold}日_{today}.md")
                open(p, "w", encoding="utf-8").write(md)
                print(f"持{hold}日: 样本{card['samples']} 胜率{card['winrate']}% 盈亏比{card['avg_rr']} "
                      f"回撤{card['max_drawdown']}% → {'✅PASS' if ok else '❌FAIL'}")
                # 大顶附近信号（2015-06/2018-01/2021-02）
                tops = ("2015-06-12", "2018-01-29", "2021-02-18")
                near = [e for e in events_hold if any(abs((datetime.strptime(e['date'],'%Y-%m-%d')-datetime.strptime(k,'%Y-%m-%d')).days) <= 15 for k in tops)]
                if near:
                    wr = sum(1 for e in near if e["exit"] > e["entry"]) / len(near) * 100
                    print(f"  ⚠️ 三大顶附近信号 {len(near)} 个，胜率 {wr:.0f}%（顶部追高风险检验）")
                else:
                    print(f"  ℹ️ 三大顶±15日无信号（{tops}）")
                # 过滤后牛熊分层（用 card.by_regime）
                if card.get("by_regime"):
                    _br = card["by_regime"]
                    print(f"  分层: " + " ".join(f"{k}:{v['n']}个/{v['winrate']}%" for k, v in _br.items()))


if __name__ == "__main__":
    main()
