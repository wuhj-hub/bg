#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trade_journal.py —— 实盘执行纪律跟踪（P1-3 · 2026-08-26）
================================================================
解决"信号触发→实际执行"鸿沟无法量化的问题：
  ① 实盘交易记录（trade_journal.csv）：买入/卖出/加仓/减仓 + 价格 + 依据信号
  ② 执行率对比：信号仲裁操作清单（buy/watch/avoid） vs 实盘 journal
     - 买入执行率 = 实盘买入的buy候选 / 当日buy候选
     - 卖出执行率 = 实盘卖出的应离场标的 / 离场信号触发数
     - 漏执行/错执行清单
  ③ 执行纪律报告（每日+累计），复盘报告引用

数据：
  输入：outputs/信号仲裁_latest.json（operations 操作清单）+ 仲裁信号日志.csv（历史）
        trade_journal.csv（人工记录，本地唯一真源：只push不pull）
  输出：outputs/执行纪律_{date}.md + outputs/执行纪律_latest.json

用法：
  python3 trade_journal.py --add "sh600797 buy 6.78 依据:离场计分-5"   # 记录实盘操作
  python3 trade_journal.py --report                                   # 生成执行纪律报告
  python3 trade_journal.py --report --days 7                          # 近7日执行率
"""
import csv, json, os, sys, re, argparse
from datetime import datetime, date

BASE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(BASE, "outputs", "trade_journal.csv")
ARB_JSON = os.path.join(BASE, "outputs", "信号仲裁_latest.json")
ARB_LOG = os.path.join(BASE, "outputs", "仲裁信号日志.csv")

FIELDS = ["date", "code", "name", "action", "price", "reason", "signal_src"]


def load_journal():
    rows = []
    if os.path.exists(JOURNAL):
        with open(JOURNAL, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return rows


def save_journal(rows):
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def add_entry(arg):
    """--add 'code action price reason' 或 'code action price 依据:xxx'"""
    m = re.match(r"((?:sh|sz)\d{6})\s+(\w+)\s+([\d.]+)\s*(.*)", arg.strip())
    if not m:
        print("❌ 格式：--add 'sh600797 buy 6.78 原因描述'（action: buy/sell/add/reduce）")
        return
    code, action, price, reason = m.group(1), m.group(2), float(m.group(3)), m.group(4).strip()
    rows = load_journal()
    rows.append({"date": date.today().isoformat(), "code": code, "name": "",
                 "action": action, "price": price, "reason": reason,
                 "signal_src": ""})
    save_journal(rows)
    print(f"✅ 已记录: {date.today()} {code} {action}@{price} {reason}")


def load_arb_log():
    """仲裁信号日志（历史）：date,code,pts,level,month,src（按 date+code 去重，保留最高pts）"""
    out = {}
    if os.path.exists(ARB_LOG):
        with open(ARB_LOG, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d, c = r.get("date", ""), r.get("code", "")
                if not d or not c:
                    continue
                key = (d, c)
                try:
                    pts = int(r.get("pts", 0))
                except ValueError:
                    pts = 0
                if key not in out or pts > out[key].get("_pts", -99):
                    r["_pts"] = pts
                    out[key] = r
    # 转成 {date: [rows]}
    grouped = {}
    for (d, _), r in out.items():
        grouped.setdefault(d, []).append(r)
    return grouped


def load_arb_json():
    """今日操作清单（operations）"""
    if os.path.exists(ARB_JSON):
        try:
            return json.load(open(ARB_JSON, encoding="utf-8"))
        except Exception:
            return None
    return None


def report(days=30):
    journal = load_journal()
    arb_log = load_arb_log()
    arb = load_arb_json()
    today = date.today().isoformat()

    # 时间窗口
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    jn = [r for r in journal if r["date"] >= cutoff]

    # 1) 买入执行率：仲裁日志中 pts≥3（★及以上）的信号日 → 当日是否有实盘买入
    buy_candidates, buy_done = 0, 0
    missed_buy = []  # (date, code, pts, level)
    for d, rows in arb_log.items():
        if d < cutoff:
            continue
        for r in rows:
            try:
                pts = int(r.get("pts", 0))
            except ValueError:
                continue
            if pts >= 3 and r.get("month", "?") != "BLOCK":  # ★及以上且月线非空头
                buy_candidates += 1
                if any(j["code"] == r["code"] and j["action"] in ("buy", "add")
                       and j["date"] >= d for j in jn):
                    buy_done += 1
                else:
                    missed_buy.append((d, r["code"], pts, r.get("level", "")))
    buy_rate = buy_done / buy_candidates * 100 if buy_candidates else 0

    # 2) 卖出执行率：仲裁日志 level 含"离场/空头/否决"或 pts<0 → 实盘是否有卖出
    sell_candidates, sell_done = 0, 0
    missed_sell = []
    for d, rows in arb_log.items():
        if d < cutoff:
            continue
        for r in rows:
            lv = r.get("level", "")
            if "离场" in lv or "空头" in lv or "否决" in lv or int(r.get("pts", 0) or 0) < 0:
                sell_candidates += 1
                if any(j["code"] == r["code"] and j["action"] in ("sell", "reduce")
                       and j["date"] >= d for j in jn):
                    sell_done += 1
                else:
                    missed_sell.append((d, r["code"], r.get("pts", "?"), lv))
    sell_rate = sell_done / sell_candidates * 100 if sell_candidates else 0

    # 3) 今日操作清单 vs 今日 journal（当日执行快照）
    today_buy_cands = []
    if arb:
        ops = arb.get("operations", {})
        today_buy_cands = [(b["code"], b["pts"], b["level"]) for b in ops.get("buy", [])]
        today_watch = [(w["code"], w["pts"]) for w in ops.get("watch", [])]
    today_done = [(j["code"], j["action"]) for j in jn if j["date"] == today]

    # 输出
    js = {"date": today, "days": days, "buy_rate": round(buy_rate, 1),
          "sell_rate": round(sell_rate, 1), "buy_candidates": buy_candidates,
          "buy_done": buy_done, "sell_candidates": sell_candidates, "sell_done": sell_done,
          "missed_buy": missed_buy[:15], "missed_sell": missed_sell[:15],
          "journal_count": len(jn)}
    os.makedirs(os.path.join(BASE, "outputs"), exist_ok=True)
    json.dump(js, open(os.path.join(BASE, "outputs", "执行纪律_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    L = [f"# 📋 实盘执行纪律报告 {today}", ""]
    L.append(f"> 窗口：近{days}日 | 实盘记录 {len(jn)} 笔（累计 {len(journal)} 笔）")
    L.append("")
    L.append("## ① 执行率")
    L.append(f"| 指标 | 执行 | 候选 | 执行率 | 评价 |")
    L.append(f"|:---|:---:|:---:|:---:|:---|")
    L.append(f"| 买入执行率（★及以上信号→实盘买入） | {buy_done} | {buy_candidates} | **{buy_rate:.0f}%** | {'✅ 纪律良好' if buy_rate >= 70 else '🟡 需加强' if buy_rate >= 40 else '🔴 严重漏执行'} |")
    L.append(f"| 卖出执行率（离场信号→实盘卖出） | {sell_done} | {sell_candidates} | **{sell_rate:.0f}%** | {'✅ 纪律良好' if sell_rate >= 70 else '🟡 需加强' if sell_rate >= 40 else '🔴 严重漏执行'} |")
    L.append("")
    L.append("## ② 漏执行清单（信号触发但未操作）")
    if missed_buy:
        L.append("### 🟢 漏买（错过候选信号）")
        for d, c, p, lv in missed_buy[:10]:
            L.append(f"- {d} {c} {p}分 {lv}")
    if missed_sell:
        L.append("### 🔴 漏卖（离场信号未执行）")
        for d, c, p, lv in missed_sell[:10]:
            L.append(f"- {d} {c} {p}分 {lv}")
    if not missed_buy and not missed_sell:
        L.append("- ✅ 窗口内无漏执行")
    L.append("")
    L.append("## ③ 今日操作清单执行快照")
    L.append(f"- 今日买入候选：{len(today_buy_cands)} 个" +
             ("（" + "、".join(f"{c}({p}分)" for c, p, _ in today_buy_cands[:8]) + "）" if today_buy_cands else ""))
    L.append(f"- 今日实盘操作：{len(today_done)} 笔" +
             ("（" + "、".join(f"{c} {a}" for c, a in today_done[:8]) + "）" if today_done else ""))
    if today_buy_cands and not any(a in ("buy", "add") for _, a in today_done):
        L.append("- ⚠️ 今日有买入候选但未记录买入——确认是否已执行（未执行请说明原因）")
    L.append("")
    L.append("## ④ 实盘交易流水（近" + str(days) + "日）")
    if jn:
        L.append("| 日期 | 代码 | 操作 | 价格 | 原因 |")
        L.append("|:---|:---|:---:|:---:|:---|")
        for r in sorted(jn, key=lambda x: x["date"], reverse=True)[:20]:
            L.append(f"| {r['date']} | {r['code']} | {r['action']} | {r['price']} | {r['reason'][:40]} |")
    else:
        L.append("- 无实盘记录（使用 `--add '代码 操作 价格 原因'` 记录）")
    L.append("")
    L.append("*规则：买入执行率=★及以上信号日实盘买入比例；卖出执行率=离场信号实盘卖出比例；≥70%纪律良好*")
    md = "\n".join(L)
    md_path = os.path.join(BASE, "outputs", f"执行纪律_{today}.md")
    open(md_path, "w", encoding="utf-8").write(md)
    print(md)
    print(f"\n[OK] {md_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", default="", help="记录实盘操作：'代码 操作 价格 原因'")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    if args.add:
        add_entry(args.add)
    if args.report:
        report(args.days)
    if not args.add and not args.report:
        print(__doc__)


if __name__ == "__main__":
    main()
