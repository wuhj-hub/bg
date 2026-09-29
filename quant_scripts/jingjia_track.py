#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jingjia_track.py —— 竞价统计·逐日跟踪模块
================================================================
每个交易日运行，让 紫霞牛 / 一进二 / 超级竞价 的样本「天天长出来」。

流程：
  1) 采集当日集合竞价 → 追加「竞价库」data/jingjia_auction.csv（去重）
     数据源：默认 westock m1 的 09:30 竞价 bar（= 开盘金额，与 TDX OpenAmo 一致）；
             也可 --ingest <json> 摄入通达信 tdx_quotes 抓的竞价（{code:{open,auction_amt}}）。
  2) 用「竞价库 + 日线」逐日回算三策略信号 → 追加「信号库」data/jingjia_signals.csv
  3) 用日线更新历史信号的 T+1~T+5 收益（相对**信号当天 9:30 竞价开盘价**买入）
  4) 生成 outputs/竞价统计_{date}.md（累计统计 + 当日新增信号）

用法：
  # 首次建库：回填最近 20 个交易日的竞价
  python3 quant_scripts/jingjia_track.py --backfill 20 --report
  # 每日：抓当日竞价 + 出报告
  python3 quant_scripts/jingjia_track.py --fetch --report
  # 摄入通达信竞价 json
  python3 quant_scripts/jingjia_track.py --ingest tdx_2026-09-30.json --report

依赖：jingjia_stats.py（同目录，提供策略与取数函数）
"""
import os, sys, csv, json, time, argparse
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jingjia_stats as J

ROOT = os.getcwd()
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
AUCTION_CSV = os.path.join(DATA_DIR, "jingjia_auction.csv")
SIGNAL_CSV = os.path.join(DATA_DIR, "jingjia_signals.csv")
OUT_DIR = os.path.join(ROOT, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)


def wcode(code):
    return ("sh" if code[0] == "6" else "sz") + code


# ---------------- 竞价库 ----------------
def load_auction():
    """→ {date: {code: {'o','v','amt'}}}"""
    out = defaultdict(dict)
    if os.path.exists(AUCTION_CSV):
        with open(AUCTION_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    out[r["date"]][r["code"]] = {"o": float(r["open"]), "v": float(r["vol"]), "amt": float(r["amt"])}
                except Exception:
                    continue
    return out


def save_auction(store):
    with open(AUCTION_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "code", "open", "vol", "amt"])
        for d in sorted(store):
            for c in sorted(store[d]):
                a = store[d][c]
                w.writerow([d, c, f"{a['o']:.3f}", f"{a['v']:.0f}", f"{a['amt']:.0f}"])


def merge_auction(store, date, bought):
    """bought: {code: {'o','v','amt'}}"""
    added = 0
    for c, a in bought.items():
        if c not in store[date]:
            store[date][c] = a
            added += 1
    return added


def fetch_auction_days(uni, dates):
    """westock m1 抓指定交易日的 09:30 竞价 bar → {code:{o,v,amt}} 按日期分组。"""
    wcodes = [w for _, _, w in uni]
    res = J.fetch_m1(wcodes, dates)          # {sym:{date:{o,v,amt}}}
    by_date = defaultdict(dict)
    for sym, dd in res.items():
        code = sym[2:] if sym[:2] in ("sh", "sz") else sym
        for d, a in dd.items():
            by_date[d][code] = a
    return by_date


# ---------------- 信号 + 收益 ----------------
def signal_of_day(d, a, cap, code):
    """返回 {date: [strategy,...]}"""
    hits = defaultdict(list)
    if not d or len(d) < 80:
        return hits
    idx = {r["date"]: i for i, r in enumerate(d)}
    if a:
        zx = J.zixia_niu(d, a, cap)
        ye = J.yijiner(d, a, cap)
        for dt in zx:
            if dt in idx:
                hits[dt].append("紫霞牛")
        for dt in ye:
            if dt in idx:
                hits[dt].append("一进二")
    sig = J.build_gzb(d)
    for dt in a.keys():
        i = idx.get(dt)
        if i is not None and sig[i]:
            hits[dt].append("超级竞价")
    return hits


def fwd(d, k):
    o = d[k]["open"]
    if o <= 0:
        return {}
    out = {}
    for n, lbl in [(0, "R0"), (1, "R1"), (2, "R2"), (3, "R3"), (5, "R5")]:
        if k + n < len(d):
            out[lbl] = d[k + n]["close"] / o - 1
    return out


def load_signals():
    """→ {(date,code,strategy): row}"""
    out = {}
    if os.path.exists(SIGNAL_CSV):
        with open(SIGNAL_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[(r["date"], r["code"], r["strategy"])] = r
    return out


def save_signals(sig):
    cols = ["date", "code", "name", "strategy", "buy_open", "R0", "R1", "R2", "R3", "R5"]
    with open(SIGNAL_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for key in sorted(sig):
            r = sig[key]
            w.writerow([r.get(c, "") for c in cols])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="all_mainboard.csv")
    ap.add_argument("--dlimit", type=int, default=320)
    ap.add_argument("--fetch", action="store_true", help="抓当日竞价入库")
    ap.add_argument("--backfill", type=int, default=0, help="回填最近N个交易日的竞价")
    ap.add_argument("--ingest", default="", help="摄入通达信竞价 json 文件")
    ap.add_argument("--ingest-date", default="", help="--ingest 对应的日期")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    args = ap.parse_args()

    uni = J.load_universe(os.path.join(ROOT, args.universe))
    wcodes = [w for _, _, w in uni]
    name_of = {c: n for c, n, _ in uni}
    print(f"[universe] {len(uni)} 只", file=sys.stderr)

    daily = J.fetch_daily(wcodes, args.dlimit, tag=os.path.basename(args.universe))
    caps = J.fetch_caps(wcodes)
    all_dates = sorted({r["date"] for d in daily.values() for r in d})

    store = load_auction()
    n_before = sum(len(v) for v in store.values())

    # ① 采集/摄入
    if args.backfill > 0:
        days = [d for d in all_dates if d not in store or len(store[d]) < 500][-args.backfill:]
        print(f"[backfill] {days[0]} ~ {days[-1]}（{len(days)}日）", file=sys.stderr)
        by_date = fetch_auction_days(uni, days)
        for d, bought in by_date.items():
            merge_auction(store, d, bought)
    if args.fetch:
        today = args.date
        by_date = fetch_auction_days(uni, [today])
        for d, bought in by_date.items():
            n = merge_auction(store, d, bought)
            print(f"[fetch] {d} 新增 {n} 只竞价", file=sys.stderr)
    if args.ingest:
        with open(args.ingest, encoding="utf-8") as f:
            raw = json.load(f)
        day = args.ingest_date or args.date
        bought = {}
        for c, v in raw.items():
            o = float(v.get("open") or 0)
            amt = float(v.get("auction_amt") or v.get("amt") or 0)
            if o > 0 and amt > 0:
                bought[c] = {"o": o, "v": v.get("vol") or amt / o / 100.0, "amt": amt}
        n = merge_auction(store, day, bought)
        print(f"[ingest] {day} 新增 {n} 只竞价", file=sys.stderr)

    save_auction(store)
    print(f"[auction] 库 {n_before}→{sum(len(v) for v in store.values())} 条，覆盖 {len(store)} 个交易日", file=sys.stderr)

    # ② 信号
    sig = load_signals()
    dates = sorted(store.keys())
    new_cnt = 0
    for code, nm, w in uni:
        d = daily.get(w)
        if not d:
            continue
        cap = caps.get(w, {})
        a = {}   # {date:{o,v,amt}} 仅该股
        for dt in dates:
            if code in store[dt]:
                a[dt] = store[dt][code]
        if not a and not d:
            continue
        hits = signal_of_day(d, a if cap else {}, cap, code)
        idx = {r["date"]: i for i, r in enumerate(d)}
        for dt, strat_list in hits.items():
            i = idx.get(dt)
            if i is None:
                continue
            fr = fwd(d, i)
            for st in strat_list:
                key = (dt, code, st)
                row = sig.get(key, {"date": dt, "code": code, "name": nm, "strategy": st})
                row["buy_open"] = f"{d[i]['open']:.3f}"
                for lbl, v in fr.items():
                    row[lbl] = f"{v:.4f}"
                if key not in sig:
                    new_cnt += 1
                sig[key] = row
    save_signals(sig)
    print(f"[signals] 库 {len(sig)} 条（新增 {new_cnt}）", file=sys.stderr)

    # ③ 报告
    if args.report:
        by_strat = defaultdict(list)
        for (dt, c, st), r in sig.items():
            by_strat[st].append(r)
        LBL = {"R0": "当天", "R1": "次日", "R2": "+2日", "R3": "+3日", "R5": "+5日"}
        md = [f"# 竞价统计·逐日跟踪 · {args.date}", "",
              "- 口径：**信号当天 9:30 集合竞价开盘价买入**，统计当天及 T+1/T+2/T+3/T+5 收盘收益",
              "- universe：沪深主板非ST（剔创业板/科创板/北交所/ST），价格不限",
              f"- 竞价库覆盖：{dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'}（{len(dates)}个交易日）", "",
              "## 一、累计信号收益（当天竞价开盘买入）", "",
              "| 策略 | 期 | 样本 | 胜率 | 均值 | 中位 |", "|---|---|---|---|---|---|"]
        for st in ["紫霞牛", "一进二", "超级竞价"]:
            rows = by_strat.get(st, [])
            for k in ["R0", "R1", "R2", "R3", "R5"]:
                vals = [float(r[k]) for r in rows if r.get(k) not in (None, "")]
                if vals:
                    a = np.array(vals)
                    md.append(f"| {st} | {LBL[k]} | {len(a)} | {(a>0).mean():.0%} | {a.mean():+.2%} | {np.median(a):+.2%} |")
                else:
                    md.append(f"| {st} | {LBL[k]} | 0 | - | - | - |")
        md += ["", "## 二、当日新增信号", ""]
        for st in ["紫霞牛", "一进二", "超级竞价"]:
            today = [r for r in by_strat.get(st, []) if r["date"] == args.date]
            if today:
                md.append(f"### {st}（{len(today)}）")
                md.append("| 代码 | 名称 | 竞价开盘 | R0 |")
                md.append("|---|---|---|---|")
                for r in today:
                    r0 = f"{float(r['R0']):+.2%}" if r.get("R0") else "-"
                    md.append(f"| {r['code']} | {r['name']} | {r['buy_open']} | {r0} |")
                md.append("")
        # 全部信号清单
        md += ["", "## 三、信号全清单", "", "| 日期 | 代码 | 名称 | 策略 | 当天 | 次日 |", "|---|---|---|---|---|---|"]
        for key in sorted(sig.keys(), reverse=True)[:120]:
            r = sig[key]
            r0 = f"{float(r['R0']):+.2%}" if r.get("R0") else "-"
            r1 = f"{float(r['R1']):+.2%}" if r.get("R1") else "-"
            md.append(f"| {r['date']} | {r['code']} | {r['name']} | {r['strategy']} | {r0} | {r1} |")
        outmd = os.path.join(OUT_DIR, f"竞价统计_{args.date}.md")
        with open(outmd, "w", encoding="utf-8") as f:
            f.write("\n".join(md))
        print("[report]", outmd)

    summary = {st: sum(1 for v in sig.values() if v["strategy"] == st) for st in ["紫霞牛", "一进二", "超级竞价"]}
    print(json.dumps({"signals": summary, "days": len(dates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
