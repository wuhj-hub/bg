#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
beast_tech_backtest.py —— 猛兽Setup技术代理长历史重验（P0-3b · 2026-08-26）
================================================================
猛兽Setup依赖资金流（asfund 无历史数据源，无法完整回放）。
本脚本重验其"纯技术可计算部分"（VAD/RSL/月线多头）：
  信号 = VAD上穿零轴（单位无关） + RSL1>0（相对强度） + 月线多头（MA20>MA60上行）
周度重放，持有4周，输出回测卡（backtest_gate 门槛判定）+ 牛熊分层。

结论定位：Setup 中资金/财务维度（SSV/断层/基本）无法历史回放，
技术代理通过/不通过只能部分说明问题，最终以实盘胜率累积为准。

用法：python3 beast_tech_backtest.py [--max 30] [--hold 4]
"""
import json, os, sys, re, time, urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import pandas as pd
from beast_screener import calc_vad, calc_rsl
from fetch_history import fetch_stock_history
from backtest_gate import compute_gate, judge_gate, render_card, regime_map



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
        pass
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:max_n]


def to_df(rows):
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.rename(columns={"last": "close"})
    for col in ("open", "close", "high", "low", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["amount"] = df["volume"]  # 腾讯proxy无个股amount字段，用volume近似（RSL加权同源）
    return df


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="stock_pool.txt")
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--hold", type=int, nargs="+", default=[4])
    args = ap.parse_args()

    idx_rows = json.load(open(os.path.join(BASE, "data_hs300/上证指数_日K_2013至今.json"), encoding="utf-8"))
    idx_df = to_df(idx_rows)
    regs = regime_map(idx_rows)

    pool = load_pool(args.pool, args.max)
    cache = os.path.join(BASE, f"data_hs300/fish3_pool_{len(pool)}.json")
    stock_data = json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else {}
    if not stock_data:
        for k, code in enumerate(pool):
            rows = fetch_stock_history(code)
            if rows:
                stock_data[code] = rows
            time.sleep(0.3)
        json.dump(stock_data, open(cache, "w", encoding="utf-8"))

    # 信号：周度重放（每周最后一个交易日计算）
    events_all, filtered = [], {"熊市": 0, "月线": 0, "RSL": 0}
    for code, rows in stock_data.items():
        df = to_df(rows)
        if df.empty or len(df) < 200:
            continue
        # 按周分组（ISO周）
        df["week"] = pd.to_datetime(df["date"]).dt.to_period("W")
        for wk, grp in df.groupby("week"):
            i = df.index[df["week"] == wk][-1]  # 周内最后一天
            if i < 200:
                continue
            d = df.loc[i, "date"]
            if regs.get(d, "震荡") == "熊市":
                filtered["熊市"] += 1
                continue
            sub = df.iloc[:i + 1].copy()
            vad = calc_vad(sub)
            rsl = calc_rsl(sub, idx_df.iloc[:i + 1].copy())
            # 月线多头近似：MA20>MA60 且 MA20 上行
            closes = sub["close"].values
            if i < 60:
                continue
            ma20 = closes[i - 19:i + 1].mean()
            ma60 = closes[i - 59:i + 1].mean()
            ma20_prev = closes[i - 24:i - 4].mean() if i >= 24 else ma20
            if not (closes[i] > ma20 > ma60 and ma20 >= ma20_prev * 0.995):
                filtered["月线"] += 1
                continue
            if rsl["rsl1"] <= 0:
                filtered["RSL"] += 1
                continue
            if not vad.get("vad_cross_up"):  # 单位无关信号：VAD上穿零轴
                filtered["RSL"] += 0
                continue
            events_all.append({"code": code, "date": d, "entry": float(closes[i])})
    print(f"信号 {len(events_all)} 个（过滤：熊市{filtered['熊市']} 月线{filtered['月线']} RSL{filtered['RSL']}）")

    for hold in args.hold:
        events_hold = []
        for ev in events_all:
            code = ev["code"]
            pm = {r["date"]: r["last"] for r in stock_data[code]}
            dates = sorted(pm.keys())
            try:
                idx_d = dates.index(ev["date"])
                exit_p = pm[dates[min(idx_d + hold * 5, len(dates) - 1)]]  # 周→交易日近似
            except ValueError:
                continue
            events_hold.append({"date": ev["date"], "entry": ev["entry"], "exit": exit_p})
        card = compute_gate(events_hold, {}, idx_rows, hold * 5)
        if card:
            ok, reasons = judge_gate(card)
            extra = f"> 猛兽Setup技术代理（VAD+RSL+月线多头）· 持有{hold}周 · 样本池{len(pool)}只·2013至今\n> ⚠️ 资金/财务维度（SSV/断层/基本）无历史数据源未纳入，通过不代表完整Setup通过"
            md = render_card(f"猛兽技术代理·持{hold}周", card, reasons, ok, extra)
            os.makedirs(os.path.join(BASE, "outputs"), exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            open(os.path.join(BASE, f"outputs/回测卡_猛兽技术代理_持{hold}周_{today}.md"), "w", encoding="utf-8").write(md)
            print(f"持{hold}周: 样本{card['samples']} 胜率{card['winrate']}% 盈亏比{card['avg_rr']} 回撤{card['max_drawdown']}% → {'✅PASS' if ok else '❌FAIL'}")
            if card.get("by_regime"):
                print("  分层: " + " ".join(f"{k}:{v['n']}个/{v['winrate']}%" for k, v in card["by_regime"].items()))


if __name__ == "__main__":
    main()
