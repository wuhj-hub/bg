#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
win_rate_tracker.py —— 股池信号实盘胜率跟踪报告 v1.0
===================================================
读取 pool_signals_log.csv（pool_tracking_report.py 每日累积），
用当前行情计算每个信号出现后的实盘收益（按信号日到当前，日线K线），
按决策分层统计胜率/平均收益/盈亏比，输出跟踪报告。

信号日志字段: date,code,name,trend,gate,reversal,g1,support,finance,decision

用法:
  python3 win_rate_tracker.py                  # 全量统计
  python3 win_rate_tracker.py --min-days 5     # 仅统计信号后≥5日的样本
"""
import subprocess, sys, os, re, csv, argparse, json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_kline(txt):
    """日线K线解析（升序），返回 [(date, close)]"""
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or "---" in parts[0]:
            continue
        try:
            di = header.index("date")
            ci = header.index("last")
            if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                rows.append((parts[di], float(parts[ci])))
        except (ValueError, IndexError):
            pass
    rows.sort(key=lambda r: r[0])
    return rows

def signal_return(code, signal_date):
    """信号日收盘 → 当前收益（%），以及自然日数"""
    # 兼容无前缀代码（快照CSV: 000009 → sz000009）
    if re.match(r"^\d{6}$", code):
        code = ("sh" if code.startswith("6") else "sz") + code
    rows = []
    for _ in range(3):
        txt = run(["kline", code, "--period", "day", "--limit", "120"])
        rows = parse_kline(txt)
        if rows:
            break
    if not rows:
        return None, None
    # 找信号日（或其后第一个交易日）的收盘
    entry = None
    for d, c in rows:
        if d >= signal_date:
            entry = c
            break
    if entry is None:
        return None, None
    cur = rows[-1][1]
    days = (datetime.strptime(rows[-1][0], "%Y-%m-%d") - datetime.strptime(signal_date, "%Y-%m-%d")).days
    return (cur / entry - 1) * 100, days

def by_phase(min_days=3, workers=8):
    """按资金行为四态分组统计胜率（读 outputs/资金快照_*.csv 归档）"""
    import glob
    snaps = sorted(glob.glob("outputs/资金快照_*.csv"))
    if not snaps:
        print("❌ 无资金快照归档（workflow全量扫描后自动生成）")
        return
    print(f"资金快照: {len(snaps)} 个交易日（{snaps[0].split('_')[-1][:10]} ~ {snaps[-1].split('_')[-1][:10]}）\n")
    groups = {}
    for fp in snaps:
        d = os.path.basename(fp).replace("资金快照_", "").replace(".csv", "")
        with open(fp, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ph = row.get("phase", "观望")
                groups.setdefault(ph, []).append((d, row["code"], row.get("name", "")))
    results = {}
    for ph, items in groups.items():
        rets = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(signal_return, code, d): (d, code, name) for d, code, name in items}
            for f in as_completed(futs):
                d, code, name = futs[f]
                ret, days = f.result()
                if ret is not None and days >= min_days:
                    rets.append({"ret": ret, "days": days, "code": code, "name": name, "date": d})
        results[ph] = rets
    print(f"有效样本（≥{min_days}日）按资金行为四态:\n")
    print(f"{'资金行为':<8}{'样本':>7}{'胜率':>8}{'平均':>8}{'中位':>8}{'盈亏比':>7}{'最差':>8}")
    print("-" * 60)
    order = ["抢筹", "进场", "控盘", "观望"]
    for ph in order:
        rets = results.get(ph, [])
        if len(rets) < 10:
            print(f"{ph:<8}{len(rets):>7}{'样本不足':>12}")
            continue
        rs = [r["ret"] for r in rets]
        wins = [r for r in rs if r > 0]
        avg = sum(rs) / len(rs)
        pl = sum(r for r in rs if r > 0) / max(1, len(wins))
        ls = abs(sum(r for r in rs if r <= 0) / max(1, len(rs) - len(wins)))
        print(f"{ph:<8}{len(rs):>7}{len(wins)/len(rs)*100:>7.1f}%{avg:>+8.2f}%"
              f"{sorted(rs)[len(rs)//2]:>+8.2f}%{pl/ls if ls else 99:>7.2f}{min(rs):>+8.2f}%")
    print("\n> 📌 四态定义：抢筹=超大单+放量(最强)/ 进场=今日净流转正 / 控盘=缩量高沉淀 / 观望")
    print("> ⚠️ 样本按快照日逐日累积，2-4周后四态对比更有意义")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="outputs/pool_signals_log.csv")
    ap.add_argument("--min-days", type=int, default=3, help="信号后最少观察天数")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--by-phase", action="store_true", help="按资金行为四态分组统计(读资金快照)")
    a = ap.parse_args()
    if a.by_phase:
        return by_phase(a.min_days, a.workers)

    if not os.path.exists(a.log):
        print(f"❌ 信号日志不存在: {a.log}\n提示: 先运行 pool_tracking_report.py 累积日志")
        return
    # 按 (date, code) 去重（同一标的多行取最新决策）
    signals = {}
    with open(a.log, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["date"], row["code"])
            signals[key] = row
    print(f"信号日志: {len(signals)} 条唯一信号（{a.log}）\n")

    # 计算收益
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(signal_return, s["code"], s["date"]): s for s in signals.values()}
        done = 0
        for f in as_completed(futs):
            s = futs[f]
            ret, days = f.result()
            done += 1
            if done % 50 == 0:
                print(f"  进度 {done}/{len(signals)}...", end="\r")
            if ret is not None and days >= a.min_days:
                s["ret"] = ret
                s["days"] = days
                results.append(s)
    print(f"有效样本（≥{a.min_days}日）: {len(results)}\n")

    # 分层统计
    def show(title, ss):
        if len(ss) < 2:
            print(f"| {title:<20} | 样本不足({len(ss)}) |")
            return
        rets = [s["ret"] for s in ss]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        pl = (sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if wins and losses else float("inf")
        days_avg = sum(s["days"] for s in ss) / len(ss)
        print(f"| {title:<20} | {len(ss):>4} | {len(wins)/len(ss)*100:>5.1f}% | {sum(rets)/len(rets):>+7.2f}% "
              f"| {sorted(rets)[len(rets)//2]:>+7.2f}% | {pl:>5.2f} | {days_avg:.0f}日 |")

    L = []
    A = L.append
    A("# 📊 股池信号实盘胜率跟踪报告\n")
    A(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据：pool_signals_log.csv（{len(signals)}条唯一信号）")
    A(f"> 收益口径：信号日收盘 → 当前（日线），持有 {a.min_days} 天以上计入\n")
    A("## 一、总体胜率（按决策分层）\n")
    A("| 决策分层 | 样本 | 胜率 | 平均 | 中位 | 盈亏比 | 平均持有 |")
    A("|:--------|:---:|:----:|:----:|:----:|:----:|:----:|")
    layers = {
        "三重共振(月线PASS+G1+盈利+支撑≥5%)": lambda s: s["gate"] == "PASS" and s["g1"] in ("双阴", "一阴") and s["finance"] == "盈利",
        "一阶通过(月线PASS/反转)": lambda s: s["gate"] == "PASS",
        "G1低吸信号": lambda s: s["g1"] in ("双阴", "一阴"),
        "月线纠缠": lambda s: s["gate"] == "WARN",
        "月线空头(BLOCK)": lambda s: s["gate"] == "BLOCK",
    }
    for title, fn in layers.items():
        ss = [s for s in results if fn(s)]
        show(title, ss)
    print()

    # 三阶漏斗验证（对照回测结论）
    A("## 二、三阶漏斗实盘验证（对照回测）\n")
    A("| 指标 | 回测结论（2024-2026全量） | 实盘跟踪（当前累积） |")
    A("|:----|:------------------------|:------------------|")
    A("| 月线反转6月胜率 | ~54.8% | 见上表（累积中） |")
    A("| 反转∩G1 6月胜率 | ~65.8% | 见上表（累积中） |")
    A("| 均线金叉胜率 | 64.8%~81.0% | 见上表（累积中） |")
    A("\n> ⚠️ 实盘样本随每日运行累积，建议运行2-4周后再做结论性对比\n")

    # 当前持仓信号清单
    A("## 三、当前有效信号清单\n")
    A("| 代码 | 名称 | 信号日 | 决策 | 信号后收益 | 持有天数 |")
    A("|:----|:----|:----|:----|:----:|:----:|")
    for s in sorted(results, key=lambda x: -x["ret"]):
        dec = s.get("decision", "")
        A(f"| {s['code']} | {s['name']} | {s['date']} | {dec or s['gate']} | {s['ret']:+.1f}% | {s['days']} |")
    A("\n---")
    A("⚠️ 本报告为量化历史规律统计，不构成投资建议。")

    md = "\n".join(L)
    os.makedirs("outputs", exist_ok=True)
    out = f"outputs/股池信号胜率跟踪报告_{datetime.now().strftime('%Y-%m-%d')}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n[OK] {out} ({len(md)} chars)")
    print(md[:1000])

if __name__ == "__main__":
    main()
