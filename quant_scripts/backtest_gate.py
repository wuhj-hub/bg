#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_gate.py —— 回测门槛制度（P0-2 · 2026-08-26）
================================================================
新信号源接入实盘前的强制回测卡：统一框架 + 判定规则
任何新系统（或新信号源）接入 signal_arbiter 前，必须先生成回测卡并通过门槛，
未通过只能进"观察池"，不能进"今日操作清单"。

门槛规则（GATE_RULES）：
  ① 样本数 ≥ 30（统计意义）
  ② 胜率 ≥ 50%（整体）
  ③ 盈亏比 ≥ 2.0（风险收益比，trade_guard 同口径）
  ④ 最大回撤 ≤ 40%（信号组合级）
  ⑤ 牛熊分层：熊市胜率 ≥ 牛市胜率 - 20pct（不允许牛市强、熊市崩的脆弱策略）

用法：
  # 通用：直接对信号事件统计（events: [{date, entry, exit}]，price_map: date->收盘）
  python3 backtest_gate.py --events events.json --prices sh000001_daily.json --hold 5

  # 策略重验：鱼身三模式（P0-3 长历史）
  python3 backtest_gate.py --strategy fish3 --pool sample_pool.txt --source txproxy --hold 5

输出：outputs/回测卡_{strategy}_{date}.md + .json
"""
import json, os, sys, re, time, subprocess, argparse
from datetime import datetime

GATE_RULES = {
    "min_samples": 30,
    "min_winrate": 0.50,
    "min_rr": 2.0,
    "max_drawdown": 0.40,
    "bear_winrate_gap": 0.20,  # 熊市胜率不得低于牛市胜率20pct以上
}


# ═══════ 牛熊分层（用指数自身结构）═══════
def regime_map(index_rows):
    """返回 date -> 市场状态（牛市/震荡/熊市）
    牛：收盘>MA200 且 MA200上行；熊：收盘<MA200 且 MA200下行；其余震荡"""
    closes = [r["last"] for r in index_rows]
    dates = [r["date"] for r in index_rows]
    out = {}
    for i in range(200, len(closes)):
        ma200 = sum(closes[i - 199:i + 1]) / 200
        ma200_prev = sum(closes[i - 200:i]) / 200
        c = closes[i]
        if c > ma200 and ma200 > ma200_prev:
            out[dates[i]] = "牛市"
        elif c < ma200 and ma200 < ma200_prev:
            out[dates[i]] = "熊市"
        else:
            out[dates[i]] = "震荡"
    return out


# ═══════ 核心统计 ═══════
def compute_gate(events, price_map, index_rows, hold_days=5):
    """对信号事件统计回测卡
    events: [{date, entry, exit}]（entry=信号日收盘，exit=持有到期收盘）
    price_map: {date: close}（标的自身价格序列，用于验证信号后走势）
    index_rows: 指数序列（牛熊分层用）"""
    regs = regime_map(index_rows) if index_rows else {}
    stats = {"total": 0, "win": 0, "loss": 0, "sum_rr": 0.0,
             "by_regime": {"牛市": {"n": 0, "win": 0, "sum_rr": 0.0},
                           "震荡": {"n": 0, "win": 0, "sum_rr": 0.0},
                           "熊市": {"n": 0, "win": 0, "sum_rr": 0.0}}}
    # 信号后 hold_days 走势统计（简化：events 里已含 entry/exit 则直接用，否则从 price_map 推）
    for ev in events:
        d, entry = ev.get("date"), ev.get("entry")
        if not d or entry is None:
            continue
        if "exit" in ev and ev["exit"] is not None:
            exit_p = ev["exit"]
        else:
            # 从 price_map 找信号日后第 hold_days 个交易日的收盘
            dates = sorted(price_map.keys())
            try:
                idx = dates.index(d)
                target = dates[min(idx + hold_days, len(dates) - 1)]
                exit_p = price_map[target]
            except (ValueError, KeyError):
                continue
        if exit_p <= 0 or entry <= 0:
            continue
        ret = (exit_p - entry) / entry
        rr = ret if ret > 0 else ret  # 简化：收益率即盈亏比代理（-10% = -0.1）
        stats["total"] += 1
        reg = regs.get(d, "震荡")
        stats["by_regime"].setdefault(reg, {"n": 0, "win": 0, "sum_rr": 0.0})
        if ret > 0:
            stats["win"] += 1
            stats["by_regime"][reg]["win"] += 1
        else:
            stats["loss"] += 1
        stats["sum_rr"] += rr
        stats["by_regime"][reg]["n"] += 1
        stats["by_regime"][reg]["sum_rr"] += rr
    if stats["total"] == 0:
        return None
    winrate = stats["win"] / stats["total"]
    # 盈亏比 = 平均盈利 / 平均亏损绝对值（trade_guard 同口径）
    all_rets = []
    for ev in events:
        d, entry = ev.get("date"), ev.get("entry")
        if not d or entry is None:
            continue
        if "exit" in ev and ev["exit"] is not None:
            exit_p = ev["exit"]
        else:
            dates = sorted(price_map.keys())
            try:
                idx = dates.index(d)
                exit_p = price_map[dates[min(idx + hold_days, len(dates) - 1)]]
            except (ValueError, KeyError):
                continue
        if exit_p and entry:
            all_rets.append((exit_p - entry) / entry)
    wins_r = [r for r in all_rets if r > 0]
    loss_r = [r for r in all_rets if r <= 0]
    avg_rr = (sum(wins_r) / len(wins_r)) / abs(sum(loss_r) / len(loss_r)) if loss_r and wins_r else 0.0
    # 最大回撤（净值法：nav 连乘，回撤=(peak-nav)/peak，有界0-100%）
    nav, peak, mdd = 1.0, 1.0, 0.0
    for ev in events:
        d, entry = ev.get("date"), ev.get("entry")
        if not d or entry is None or entry <= 0:
            continue
        if "exit" in ev and ev["exit"] is not None:
            exit_p = ev["exit"]
        else:
            dates = sorted(price_map.keys())
            try:
                idx = dates.index(d)
                exit_p = price_map[dates[min(idx + hold_days, len(dates) - 1)]]
            except (ValueError, KeyError):
                continue
        if not exit_p or exit_p <= 0:
            continue
        ret = (exit_p - entry) / entry
        nav *= (1 + ret)
        peak = max(peak, nav)
        mdd = max(mdd, (peak - nav) / peak)
    card = {
        "samples": stats["total"], "winrate": round(winrate * 100, 1),
        "avg_rr": round(avg_rr, 2), "max_drawdown": round(mdd * 100, 1),
        "wins": stats["win"], "losses": stats["loss"],
        "by_regime": {},
    }
    # 分环境盈亏比（盈利/亏损比）
    for reg, st in stats["by_regime"].items():
        if not st["n"]:
            continue
        reg_rets = []
        for ev in events:
            d, entry = ev.get("date"), ev.get("entry")
            if not d or entry is None or regs.get(d) != reg:
                continue
            if "exit" in ev and ev["exit"] is not None:
                exit_p = ev["exit"]
            else:
                dates = sorted(price_map.keys())
                try:
                    idx = dates.index(d)
                    exit_p = price_map[dates[min(idx + hold_days, len(dates) - 1)]]
                except (ValueError, KeyError):
                    continue
            if exit_p and entry:
                reg_rets.append((exit_p - entry) / entry)
        rw = [r for r in reg_rets if r > 0]
        rl = [r for r in reg_rets if r <= 0]
        rr_reg = (sum(rw) / len(rw)) / abs(sum(rl) / len(rl)) if rw and rl else 0.0
        card["by_regime"][reg] = {"n": st["n"], "winrate": round(st["win"] / st["n"] * 100, 1),
                                  "avg_rr": round(rr_reg, 2)}
    return card


# ═══════ 门槛判定 ═══════
def judge_gate(card):
    """按 GATE_RULES 判定：返回 (pass, reasons[])"""
    reasons = []
    ok = True
    if card["samples"] < GATE_RULES["min_samples"]:
        ok = False
        reasons.append(f"❌ 样本不足：{card['samples']}<{GATE_RULES['min_samples']}")
    else:
        reasons.append(f"✅ 样本 {card['samples']}≥{GATE_RULES['min_samples']}")
    if card["winrate"] < GATE_RULES["min_winrate"] * 100:
        ok = False
        reasons.append(f"❌ 胜率 {card['winrate']}%<{GATE_RULES['min_winrate']*100}%")
    else:
        reasons.append(f"✅ 胜率 {card['winrate']}%≥{GATE_RULES['min_winrate']*100}%")
    if card["avg_rr"] < GATE_RULES["min_rr"]:
        ok = False
        reasons.append(f"❌ 盈亏比 {card['avg_rr']}<{GATE_RULES['min_rr']}")
    else:
        reasons.append(f"✅ 盈亏比 {card['avg_rr']}≥{GATE_RULES['min_rr']}")
    if card["max_drawdown"] > GATE_RULES["max_drawdown"] * 100:
        ok = False
        reasons.append(f"❌ 最大回撤 {card['max_drawdown']}%>{GATE_RULES['max_drawdown']*100}%")
    else:
        reasons.append(f"✅ 最大回撤 {card['max_drawdown']}%≤{GATE_RULES['max_drawdown']*100}%")
    # 牛熊分层
    br = card.get("by_regime", {})
    bull = br.get("牛市", {}).get("winrate", 0)
    bear = br.get("熊市", {}).get("winrate", 0)
    if br.get("牛市", {}).get("n", 0) >= 5 and br.get("熊市", {}).get("n", 0) >= 5:
        if bear < bull - GATE_RULES["bear_winrate_gap"] * 100:
            ok = False
            reasons.append(f"❌ 熊市胜率{bear}%<牛市{bull}%-{GATE_RULES['bear_winrate_gap']*100:.0f}pct（脆弱策略）")
        else:
            reasons.append(f"✅ 牛熊分层稳健（牛{bull}%/熊{bear}%）")
    else:
        reasons.append(f"⚠️ 牛熊样本不足（牛{br.get('牛市',{}).get('n',0)}/熊{br.get('熊市',{}).get('n',0)}），分层不判定")
    return ok, reasons


def render_card(name, card, reasons, ok, extra=""):
    today = datetime.now().strftime("%Y-%m-%d")
    md = [f"# 🎫 回测卡：{name}（{today}）", "",
          f"**判定**：{'✅ PASS 可接入实盘' if ok else '❌ FAIL 禁止接入实盘（只能进观察池）'}", ""]
    md.append("| 指标 | 数值 | 门槛 | 结果 |")
    md.append("|:----|:----:|:----:|:----:|")
    md.append(f"| 样本数 | {card['samples']} | ≥{GATE_RULES['min_samples']} | {'✅' if card['samples']>=GATE_RULES['min_samples'] else '❌'} |")
    md.append(f"| 胜率 | {card['winrate']}% | ≥{GATE_RULES['min_winrate']*100:.0f}% | {'✅' if card['winrate']>=GATE_RULES['min_winrate']*100 else '❌'} |")
    md.append(f"| 盈亏比 | {card['avg_rr']} | ≥{GATE_RULES['min_rr']} | {'✅' if card['avg_rr']>=GATE_RULES['min_rr'] else '❌'} |")
    md.append(f"| 最大回撤 | {card['max_drawdown']}% | ≤{GATE_RULES['max_drawdown']*100:.0f}% | {'✅' if card['max_drawdown']<=GATE_RULES['max_drawdown']*100 else '❌'} |")
    md.append("")
    md.append("### 牛熊分层")
    md.append("| 环境 | 样本 | 胜率 | 平均盈亏 |")
    md.append("|:----|:----:|:----:|:----:|")
    for k, v in card["by_regime"].items():
        md.append(f"| {k} | {v['n']} | {v['winrate']}% | {v['avg_rr']} |")
    md.append("")
    md.append("### 判定明细")
    for r in reasons:
        md.append(f"- {r}")
    if extra:
        md.append("")
        md.append(extra)
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", help="信号事件JSON [{date,entry,exit?}]")
    ap.add_argument("--prices", help="价格序列JSON（{date: close} 或 rows）")
    ap.add_argument("--index", default="data_hs300/上证指数_日K_2013至今.json",
                    help="指数序列JSON（牛熊分层）")
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--name", default="策略")
    args = ap.parse_args()
    if not args.events or not args.prices:
        print(__doc__)
        sys.exit(1)
    events = json.load(open(args.events, encoding="utf-8"))
    pm = json.load(open(args.prices, encoding="utf-8"))
    if isinstance(pm, list):
        pm = {r["date"]: r["last"] for r in pm}
    idx = json.load(open(args.index, encoding="utf-8")) if os.path.exists(args.index) else None
    card = compute_gate(events, pm, idx, args.hold)
    if not card:
        print("❌ 无有效信号事件")
        sys.exit(1)
    ok, reasons = judge_gate(card)
    md = render_card(args.name, card, reasons, ok)
    os.makedirs("outputs", exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    md_path = f"outputs/回测卡_{args.name}_{today}.md"
    open(md_path, "w", encoding="utf-8").write(md)
    json.dump({"name": args.name, "date": today, "pass": ok, "card": card, "reasons": reasons},
              open(f"outputs/回测卡_{args.name}_{today}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(md)
    print(f"\n[OK] {md_path}")

if __name__ == "__main__":
    main()
