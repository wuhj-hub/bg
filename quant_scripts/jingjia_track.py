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


# ---------------- 报告：紫霞牛 / 一进二 明细（2026-09-30 新增） ----------------
def special_section(by_strat):
    """紫霞牛 / 一进二 明细（信号稀少，单列便于跟踪）。返回 markdown 行列表。"""
    md = ["", "## 四、紫霞牛 / 一进二 明细", "",
          "> 这两个策略信号稀少（累计样本小），单列便于跟踪；收益=信号日 9:30 竞价开盘价买入。", ""]
    for st in ["紫霞牛", "一进二"]:
        rows = sorted(by_strat.get(st, []), key=lambda r: r.get("date", ""), reverse=True)
        md.append(f"### {st}（累计 {len(rows)} 条）")
        if not rows:
            md += ["（暂无信号）", ""]
            continue
        md += ["| 日期 | 代码 | 名称 | 竞价开盘 | 当天 | 次日 | +2日 | +3日 | +5日 |",
               "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            cells = [r.get("date", ""), r.get("code", ""), r.get("name", ""), str(r.get("buy_open", "-"))]
            for k in ["R0", "R1", "R2", "R3", "R5"]:
                v = r.get(k)
                cells.append(f"{float(v):+.2%}" if v not in (None, "") else "-")
            md.append("| " + " | ".join(cells) + " |")
        r0 = [float(r["R0"]) for r in rows if r.get("R0") not in (None, "")]
        if r0:
            a = np.array(r0)
            md += ["", f"*小结：当天(R0) 样本 {len(a)}，胜率 {(a > 0).mean():.0%}，均值 {a.mean():+.2%}*"]
        md.append("")
    return md


# ---------------- 竞价快报（盘前轻量模式） ----------------
def brief_report(uni, args):
    """09:27 盘前竞价快报：只读腾讯行情快照，不做日线/信号重算 → 目标 <2min。

    数据来源 fetch.ext_gtimg（qt.gtimg）：open=集合竞价撮合价、prev_close=昨收、
    amount=累计成交额（万元；09:25 撮合完成至 09:30 连续竞价前，该值即竞价成交额）。
    数据未就绪（有效只数不足）时等待重试，仍无则输出提示并以 0 退出（不误报红）。
    完整「三策略信号判定 + T+1~T+5 收益回填」仍由收盘后的完整模式产出。
    """
    _d = os.path.dirname(os.path.abspath(__file__))
    if _d not in sys.path:
        sys.path.insert(0, _d)
    from fetch import ext_gtimg

    today = args.date
    wcodes = [w for _, _, w in uni]
    recs, ready = {}, 0
    for attempt in range(3):
        try:
            recs = ext_gtimg(wcodes, batch=50) or {}
        except Exception as e:
            print(f"[brief] 行情抓取失败：{e}", file=sys.stderr)
            recs = {}
        ready = sum(1 for r in recs.values() if (r.get("amount") or 0) > 0 and (r.get("open") or 0) > 0)
        if ready >= 100:
            break
        if attempt < 2:
            print(f"[brief] 竞价数据未就绪（有效 {ready} 只），60s 后重试", file=sys.stderr)
            time.sleep(60)

    rows = []
    for code, nm, w in uni:
        r = recs.get(w) or {}
        op, pc = r.get("open") or 0, r.get("prev_close") or 0
        amt = (r.get("amount") or 0) * 1e4          # 万元 → 元
        if op <= 0 or pc <= 0:
            continue
        rows.append({"code": code, "name": nm, "open": op, "prev": pc,
                     "gap": op / pc - 1, "amt": amt})
    if not rows:
        print(f"[brief] 无有效竞价数据（{today}），可能未开盘或休市，跳过", file=sys.stderr)
        return None

    tot_amt = sum(x["amt"] for x in rows)
    by_amt = sorted(rows, key=lambda x: -x["amt"])[:20]
    by_gap = sorted(rows, key=lambda x: -x["gap"])[:20]
    by_low = sorted(rows, key=lambda x: x["gap"])[:15]

    # 上一交易日（最近信号日）三策略信号 → 今日竞价买点表现
    sig_by = defaultdict(list)
    d0 = ""
    if os.path.exists(SIGNAL_CSV):
        ds = set()
        with open(SIGNAL_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("date") and r["date"] < today:
                    ds.add(r["date"])
        if ds:
            d0 = max(ds)
            px = {x["code"]: x for x in rows}
            with open(SIGNAL_CSV, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r.get("date") != d0 or r.get("code") not in px:
                        continue
                    x = px[r["code"]]
                    sig_by[r.get("strategy", "")].append(
                        {"code": r["code"], "name": r.get("name") or x["name"],
                         "prev": x["prev"], "open": x["open"], "gap": x["gap"], "amt": x["amt"]})

    def _tbl(head, keys, data):
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for x in data:
            out.append("| " + " | ".join(keys(x)) + " |")
        return out

    md = [f"# ⚡ 竞价快报 · {today}", "",
          f"- 数据：腾讯行情快照（09:25 集合竞价撮合结果），有效 **{len(rows)}** 只沪深主板",
          f"- 全市场竞价成交额合计 **{tot_amt / 1e8:.1f} 亿元**",
          "- 用途：盘前资金/情绪参考。**三策略信号判定与 T+1~T+5 收益回填由收盘后 15:05 的完整统计产出**", "",
          "## 一、竞价金额 Top 20（资金主攻方向）", ""]
    md += _tbl(["代码", "名称", "竞价金额(亿)", "今开", "高开%", "昨收"],
               lambda x: [x["code"], x["name"], f"{x['amt'] / 1e8:.2f}", f"{x['open']:.2f}",
                          f"{x['gap'] * 100:+.2f}%", f"{x['prev']:.2f}"], by_amt)
    md += ["", "## 二、竞价高开 Top 20（强势预期）", ""]
    md += _tbl(["代码", "名称", "高开%", "今开", "竞价金额(亿)"],
               lambda x: [x["code"], x["name"], f"{x['gap'] * 100:+.2f}%", f"{x['open']:.2f}",
                          f"{x['amt'] / 1e8:.2f}"], by_gap)
    md += ["", "## 三、竞价低开 Top 15（风险名单）", ""]
    md += _tbl(["代码", "名称", "低开%", "今开", "竞价金额(亿)"],
               lambda x: [x["code"], x["name"], f"{x['gap'] * 100:+.2f}%", f"{x['open']:.2f}",
                          f"{x['amt'] / 1e8:.2f}"], by_low)
    ORDER = ["紫霞牛", "一进二", "超级竞价"]
    if sig_by:
        md += ["", f"## 四、三策略今日竞价候选（信号日 {d0} 收盘确认 → 今日集合竞价买点）", "",
               "> 说明：三策略均为「当日收盘确认信号 → 次日集合竞价买入」，故今日可执行的是"
               f"**上一交易日（{d0}）**的信号；今日新信号要等收盘后完整统计产出。", ""]
        summ = []
        for st in ORDER:
            xs = sig_by.get(st) or []
            if not xs:
                continue
            up = sum(1 for x in xs if x["gap"] > 0)
            summ.append((st, len(xs), up, sum(x["gap"] for x in xs) / len(xs)))
        md += _tbl(["策略", "候选数", "竞价高开", "竞价低开", "均值高开%"],
                   lambda x: [x[0], str(x[1]), str(x[2]), str(x[1] - x[2]), f"{x[3] * 100:+.2f}%"], summ)
        for st in ORDER:
            xs = sig_by.get(st) or []
            md += ["", f"### {st}（{len(xs)} 条）" if xs else f"### {st}（当日无信号）", ""]
            if xs:
                xs = sorted(xs, key=lambda x: -x["gap"])
                md += _tbl(["代码", "名称", "昨收", "今开", "高开%", "竞价额(亿)"],
                           lambda x: [x["code"], x["name"], f"{x['prev']:.2f}", f"{x['open']:.2f}",
                                      f"{x['gap'] * 100:+.2f}%", f"{x['amt'] / 1e8:.2f}"], xs)
    else:
        md += ["", "## 四、三策略今日竞价候选", "",
               f"- 信号库中无 {today} 之前的信号记录（`--brief` 依赖收盘后完整统计写入的 signals）"]

    out = os.path.join(OUT_DIR, f"竞价快报_{today}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"[brief] {out}  有效 {len(rows)} 只 / 竞价额 {tot_amt / 1e8:.1f} 亿", file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="all_mainboard.csv")
    ap.add_argument("--dlimit", type=int, default=320)
    ap.add_argument("--fetch", action="store_true", help="抓当日竞价入库")
    ap.add_argument("--backfill", type=int, default=0, help="回填最近N个交易日的竞价")
    ap.add_argument("--ingest", default="", help="摄入通达信竞价 json 文件")
    ap.add_argument("--ingest-date", default="", help="--ingest 对应的日期")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--brief", action="store_true", help="盘前竞价快报模式（只读行情快照，不做日线/信号重算）")
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    args = ap.parse_args()

    uni = J.load_universe(os.path.join(ROOT, args.universe))
    if args.brief:
        out = brief_report(uni, args)
        print(json.dumps({"brief": out, "stocks": len(uni)}, ensure_ascii=False))
        return
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
        md += special_section(by_strat)
        outmd = os.path.join(OUT_DIR, f"竞价统计_{args.date}.md")
        with open(outmd, "w", encoding="utf-8") as f:
            f.write("\n".join(md))
        print("[report]", outmd)

    summary = {st: sum(1 for v in sig.values() if v["strategy"] == st) for st in ["紫霞牛", "一进二", "超级竞价"]}
    print(json.dumps({"signals": summary, "days": len(dates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
