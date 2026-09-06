#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
execution_card.py —— 个股执行卡 v1.0（张穗鸿「卷钱机器」周期级联机制落地）
====================================================================
将「指导周期×操作周期」机构分仓思想融入现有体系，给候选信号强制生成执行卡：

  ① 上级周期门禁（张式级联）：月线方向 + 周线方向 → ✅放行 / 🟡试仓 / ⛔拦截
       - 月线 = 大方向闸门（既有铁律：BLOCK不入）
       - 周线 = 新增中继级联（张：周线指导30分钟；我们：周线验证日线信号）
  ② 资金预算卡（斯波朗迪×张穗鸿3331 双源头）：
       ATR止损(2×ATR14) / 目标位(月线前12月高) / 盈亏比≥2 / 单票≤30% / 最大亏损金额
  ③ 分批执行计划（张式 5:3:2 拆分）：
       底仓50% @信号确认 → 加仓30% @回踩MA10不破 → 右侧20% @突破前高
       止盈分工：B1+B2波段仓到目标分批走（张式）；B3趋势仓跌破MA20走（强势体系式）

数据：westock 月线/周线/日线K线（无需新数据源）
用法：
  python3 execution_card.py --codes sh600797,sz000839 --total 1000000
  python3 execution_card.py --file signals.json --total 1000000
  signals.json: {"stocks":[{"code":"sh600797","name":"浙大网新","signal":"月线反转"}]}
  python3 execution_card.py --holdings --total 1000000   # 读 holdings.txt
输出：outputs/execution_cards_latest.json + outputs/execution_cards_{date}.md
"""
import json, os, sys, re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trade_guard import fetch_kline, calc_atr

MAX_SINGLE_POS = 30.0      # 单票仓位上限%（张穗鸿3331 与 signal_risk_card 一致）
ACCOUNT_RISK_PCT = 2.0     # 账户单笔最大风险%（斯波朗迪）
SPLIT = [0.5, 0.3, 0.2]    # 分批 5:3:2
BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(BASE), "outputs")

# ══════════ ① 上级周期门禁 ══════════

def trend_gate(rows, ma_fast=6, ma_slow=12):
    """通用多均线方向闸门：多头(close>MA6>MA12)=PASS / 纠缠=WARN / 空头=BLOCK
    rows: 升序 [{date,last,high,low,...}]（trade_guard.parse_kline 格式）
    """
    out = {"trend": "无数据", "gate": "BLOCK", "close": None, "ma6": None, "ma12": None}
    if not rows or len(rows) < ma_fast + 1:
        return out
    closes = [r["last"] for r in rows]
    cur = closes[-1]
    ma6 = sum(closes[-ma_fast:]) / ma_fast
    ma12 = sum(closes[-ma_slow:]) / ma_slow if len(closes) >= ma_slow else sum(closes) / len(closes)
    if cur > ma6 and ma6 > ma12:
        trend = "多头"
    elif cur < ma6 and ma6 < ma12:
        trend = "空头"
    else:
        trend = "纠缠"
    gate = "PASS" if trend == "多头" else ("WARN" if trend == "纠缠" else "BLOCK")
    out.update({"trend": trend, "gate": gate, "close": round(cur, 2),
                "ma6": round(ma6, 2), "ma12": round(ma12, 2)})
    return out


def fetch_rows(code, period, limit):
    """带重试的K线拉取（升序）"""
    return fetch_kline(code, period=period, limit=limit)


def upper_gate(code):
    """上级周期门禁：月线 + 周线 双闸门合成
    合成规则（军队式，上级优先）：
      月线BLOCK → ⛔拦截（月线空头，既有铁律）
      月线WARN 或 周线BLOCK → 🟡试仓（仓位×0.5）
      月线PASS + 周线WARN → 🟡谨慎（仓位×0.7）
      月线PASS + 周线PASS → ✅放行（正常仓位）
    """
    month = trend_gate(fetch_rows(code, "month", 15))
    week = trend_gate(fetch_rows(code, "week", 15))
    m_g, w_g = month["gate"], week["gate"]
    if m_g == "BLOCK":
        gate, level, desc = "BLOCK", "⛔拦截", f"月线{month['trend']}(BLOCK) / 周线{week['trend']}({w_g}) —— 大方向向下，不入场"
    elif m_g == "WARN" or w_g == "BLOCK":
        gate, level, desc = "WARN", "🟡试仓", f"月线{month['trend']}({m_g}) / 周线{week['trend']}({w_g}) —— 上级周期未共振，仅可试仓(仓位×0.5)"
    elif w_g == "WARN":
        gate, level, desc = "WARN", "🟡谨慎", f"月线{month['trend']}(PASS) / 周线{week['trend']}(WARN) —— 中继方向不明，谨慎放行(仓位×0.7)"
    else:
        gate, level, desc = "PASS", "✅放行", f"月线{month['trend']}(PASS) + 周线{week['trend']}(PASS) —— 大小周期共振，正常仓位"
    return {"month": month, "week": week, "gate": gate, "level": level, "desc": desc}


# ══════════ ② 资金预算卡 ══════════

def risk_budget(code, name, day_rows, month_rows, total_capital):
    """资金预算：ATR止损 / 目标(月线前12月高) / 盈亏比 / 建议仓位 / 最大亏损额
    逻辑对齐 signal_risk_card（斯波朗迪2%风险）+ 张穗鸿3331单票30%上限
    """
    cur = day_rows[-1]["last"] if day_rows else 0
    budget = {"price": round(cur, 2), "stop": None, "target": None, "rr": None,
              "pos_pct": 0.0, "max_loss": 0, "status": "⛔无止损不入场", "reason": ""}
    stop = None
    if len(day_rows) >= 15:
        atr = calc_atr(day_rows)
        if atr:
            stop = cur - 2 * atr
    if not stop or stop <= 0 or cur <= stop:
        budget["reason"] = "止损位不可用（ATR异常或现价已破2×ATR止损）"
        return budget
    # 目标 = 月线前12月高（创新高按 ×1.08 保底）
    target = None
    if month_rows and len(month_rows) > 1:
        prev_high = max(r["high"] for r in month_rows[:-1])
        target = max(prev_high, cur * 1.08)
    elif day_rows:
        prev_high = max(r["high"] for r in day_rows[-60:])
        target = max(prev_high, cur * 1.08)
    rr = None
    if target and target > cur:
        reward = target - cur
        risk = cur - stop
        rr = reward / risk if risk > 0 else None
    # 仓位：账户风险2% ÷ 止损幅度%，封顶单票30%（3331）
    risk_pct = (cur - stop) / cur * 100
    pos = ACCOUNT_RISK_PCT / (risk_pct / 100)
    pos_pct = round(min(pos, MAX_SINGLE_POS), 1)
    # 张式风险预算：最大亏损金额 = 满仓建议金额 × 止损幅度
    max_loss = round(total_capital * pos_pct / 100 * risk_pct / 100)
    if rr is None or rr < 2.0:
        status = "⚠️盈亏比不足"
    else:
        status = "✅预算达标"
    budget.update({"stop": round(stop, 2), "target": round(target, 2) if target else None,
                   "rr": round(rr, 2) if rr else None, "pos_pct": pos_pct,
                   "max_loss": max_loss, "status": status,
                   "reason": f"止损{stop:.2f}(-{risk_pct:.1f}%) 目标{target:.2f} 盈亏比{rr if rr else 0:.2f} "
                             f"满仓建议{pos_pct}% 满仓最大亏损≈{max_loss}元"})
    return budget


# ══════════ ③ 分批执行计划 ══════════

def batch_plan(pos_pct, day_rows, budget, gate_mult):
    """张式 5:3:2 分批：底仓@信号确认 / 加仓@回踩MA10 / 右侧@突破前高
    止盈分工：B1+B2 波段仓→目标位分批止盈（张式顶分型思路的价位化）
              B3 趋势仓→跌破MA20止盈（强势体系趋势跟踪，让利润奔跑）
    """
    if not day_rows:
        return []
    closes = [r["last"] for r in day_rows]
    cur = closes[-1]
    ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else cur
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else ma10
    target = budget.get("target") or round(max(closes[-30:]) * 1.02, 2)

    def r5(x):
        return round(round(x / 0.5) * 0.5, 1)
    b1 = r5(pos_pct * SPLIT[0] * gate_mult)
    b2 = r5(pos_pct * SPLIT[1] * gate_mult)
    b3 = r5(pos_pct * SPLIT[2] * gate_mult)
    return [
        {"batch": "B1底仓", "pct": b1, "trigger": f"信号确认位附近(≈{cur:.2f})",
         "note": "底分型/站上5日线确认", "exit": f"到目标{target:.2f}止盈"},
        {"batch": "B2加仓", "pct": b2, "trigger": f"回踩MA10({ma10:.2f})不破",
         "note": "或回踩缺口/前平台企稳", "exit": f"到目标{target:.2f}或前高止盈"},
        {"batch": "B3右侧", "pct": b3, "trigger": f"放量突破前高({target:.2f})",
         "note": "或上级周期转多共振", "exit": f"跌破MA20({ma20:.2f})或MACD死叉离场"},
    ]


# ══════════ 主流程 ══════════

def exec_card(code, name="", signal="", total_capital=1000000):
    """单只股票执行卡"""
    card = {"code": code, "name": name or code, "signal": signal,
            "date": datetime.now().strftime("%Y-%m-%d")}
    try:
        day = fetch_rows(code, "day", 40)
        month = fetch_rows(code, "month", 15)
        if not day or len(day) < 15:
            card["error"] = "日线数据不足"
            return card
        # ① 上级周期门禁
        gate = upper_gate(code)
        card["upper"] = {"month_trend": gate["month"]["trend"], "month_gate": gate["month"]["gate"],
                         "week_trend": gate["week"]["trend"], "week_gate": gate["week"]["gate"],
                         "verdict": gate["level"], "desc": gate["desc"]}
        # ② 资金预算
        budget = risk_budget(code, name, day, month, total_capital)
        card["budget"] = budget
        if budget["status"].startswith("⛔") or budget["stop"] is None:
            card["verdict"] = "⛔无止损不入场"
            card["action"] = "止损不可用（ATR异常/现价破位），放弃或等待重新站上2×ATR止损线。"
            return card
        # ③ 分批执行（含门禁系数）
        if gate["gate"] == "BLOCK":
            card["verdict"] = "⛔拦截"
            card["action"] = ("不入场：" + gate["desc"] +
                              " 等待月线/周线转多(PASS)后重新出卡；若为持仓，按既有离场纪律管理。")
            return card
        gate_mult = 0.5 if "试仓" in gate["level"] else (0.7 if "谨慎" in gate["level"] else 1.0)
        card["batches"] = batch_plan(budget["pos_pct"], day, budget, gate_mult)
        total_b = sum(b["pct"] for b in card["batches"])
        # 实际最大亏损 = 门禁后实际总仓位 × 止损幅度
        cur_p = day[-1]["last"]
        risk_pct = (cur_p - budget["stop"]) / cur_p * 100
        final_loss = round(total_b / 100 * total_capital * risk_pct / 100)
        card["verdict"] = gate["level"]
        card["max_loss_final"] = final_loss
        card["summary"] = (f"{gate['level']} {budget['status']} | 分批合计{total_b}%"
                           f"（单票上限{MAX_SINGLE_POS:.0f}%×门禁{gate_mult:.1f}）"
                           f"实际最大亏损≈{final_loss}元")
    except Exception as e:
        card["error"] = str(e)[:100]
    return card


def render_md(cards, total_capital):
    L = ["## 🃏 个股执行卡（张穗鸿卷钱机器·周期级联落地版）\n",
         f"> 三层检查：①上级周期门禁(月+周) ②资金预算(2×ATR止损/盈亏比≥2/单票≤{MAX_SINGLE_POS:.0f}%) "
         f"③分批执行(5:3:2)。总资金基准：{total_capital/10000:.0f}万。\n"]
    for c in cards:
        if "error" in c:
            L.append(f"- {c['code']} {c['name']}：⚠️ {c['error']}")
            continue
        up = c.get("upper", {})
        L.append(f"\n### {c['verdict']} {c['name']}({c['code']}) · {c.get('signal') or '候选'}")
        L.append(f"- **上级门禁**：月线{up.get('month_trend')}({up.get('month_gate')}) / "
                 f"周线{up.get('week_trend')}({up.get('week_gate')}) → {up.get('verdict')}")
        if c.get("action"):
            L.append(f"- **裁决**：{c['action']}")
            continue
        b = c.get("budget", {})
        L.append(f"- **预算**：{b.get('reason', '无')}")
        for bp in c.get("batches", []):
            L.append(f"- **{bp['batch']}** {bp['pct']}%：{bp['trigger']}（{bp['note']}）→ {bp['exit']}")
        L.append(f"- **汇总**：{c.get('summary', '')}")
    L.append("\n---\n⚠️ 本卡为机械规则输出，不构成投资建议；B2/B3触发位需盘中人工确认。")
    return "\n".join(L)


def load_holdings():
    """读 holdings.txt（格式: code # 名称）"""
    out = []
    for p in ["holdings.txt", os.path.join(BASE, "holdings.txt"),
              os.path.join(os.path.dirname(BASE), "holdings.txt")]:
        if os.path.exists(p):
            for ln in open(p, encoding="utf-8"):
                ln = ln.strip()
                m = re.match(r"^((?:sh|sz)\d{6})\s*#?\s*(.*)$", ln)
                if m:
                    out.append({"code": m.group(1), "name": m.group(2).strip(), "signal": "持仓"})
            return out
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", help="逗号分隔代码列表")
    ap.add_argument("--names", help="逗号分隔名称（与codes对应，可选）")
    ap.add_argument("--file", help="JSON文件: {\"stocks\":[{code,name,signal}]}")
    ap.add_argument("--holdings", action="store_true", help="读持仓")
    ap.add_argument("--total", type=float, default=1000000, help="总资金（默认100万）")
    ap.add_argument("--out", default=OUT_DIR, help="输出目录")
    args = ap.parse_args()

    stocks = []
    if args.file:
        data = json.load(open(args.file, encoding="utf-8"))
        stocks = data.get("stocks", data if isinstance(data, list) else [])
    elif args.holdings:
        stocks = load_holdings()
    elif args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        names = [n.strip() for n in args.names.split(",")] if args.names else []
        for i, c in enumerate(codes):
            stocks.append({"code": c, "name": names[i] if i < len(names) else "", "signal": ""})
    if not stocks:
        print(__doc__)
        sys.exit(1)

    print(f"生成执行卡：{len(stocks)}只 | 总资金 {args.total/10000:.0f}万")
    cards = []
    for s in stocks:
        card = exec_card(s["code"], s.get("name", ""), s.get("signal", ""), args.total)
        cards.append(card)
        v = card.get("verdict", card.get("error", "?"))
        print(f"  {card['code']} {card['name']}: {v}")

    os.makedirs(args.out, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    md = render_md(cards, args.total)
    with open(os.path.join(args.out, f"execution_cards_{date}.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(args.out, "execution_cards_latest.json"), "w", encoding="utf-8") as f:
        json.dump({"date": date, "total_capital": args.total, "cards": cards},
                  f, ensure_ascii=False, indent=1)
    print(f"\n✅ 输出: {args.out}/execution_cards_{date}.md")
