#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_tracker.py —— 纸面组合跟踪（不依赖实盘，比较选股方法效果）
================================================================
将选股信号建成"虚拟持仓"组合（paper portfolio），记录信号日价格，
之后每日更新现价计算盈亏，按选股方法分组统计，比较不同方法效果。

方法分组（同一标的可属于多个组）：
  A 月线反转only   B +武威G1   C +v2.1(支撑≥5%+盈利)
  D +盈亏比≥2      E 三阶共振(完整)   对照组: 月线空头

用法:
  python3 paper_tracker.py --init pool_signals.json   # 初始化组合（首次）
  python3 paper_tracker.py --update                    # 每日更新盈亏
  python3 paper_tracker.py --report                    # 输出对比报告
"""
import subprocess, sys, os, re, json, argparse
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
PORTFOLIO = "outputs/paper_portfolio.json"

def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_kline(txt):
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

def get_price(code):
    """最新收盘价 + 信号日次日收盘"""
    for _ in range(3):
        txt = run(["kline", code, "--period", "day", "--limit", "60"])
        rows = parse_kline(txt)
        if rows:
            return rows
    return []


def load_rsg_state():
    """读取 RSV 扫描的 RSG 状态（2026-08-28：RSG实盘验证闭环）→ {code: {rsg_dev, rsg_strong}}
    供纸面组合按"强势池/非强势池"分组对比，验证 RSG 过滤是否真的提升信号质量"""
    rsg = {}
    for p in ("outputs/rsv_strength_latest.json", "rsv_strength_latest.json"):
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                for r in (d.get("launch", []) + d.get("hold", []) + d.get("exit", [])):
                    if r.get("code"):
                        rsg[r["code"]] = {"rsg_dev": r.get("rsg_dev"),
                                          "rsg_strong": bool(r.get("rsg_strong"))}
                break
            except Exception:
                continue
    return rsg

def init_portfolio(signals_file):
    """从信号日志初始化纸面组合：取每个(date,code)最新一行"""
    signals = {}
    with open(signals_file, encoding="utf-8") as f:
        for row in __import__("csv").DictReader(f):
            key = (row["date"], row["code"])
            signals[key] = row
    # 初始化：记录信号日价格（取信号日之后第一个交易日的收盘作为入场价）
    portfolio = {"init_date": datetime.now().strftime("%Y-%m-%d"), "positions": []}
    for (sig_date, code), s in sorted(signals.items()):
        rows = get_price(code)
        if not rows:
            continue
        # 入场价 = 信号日（或其后第一个交易日）收盘
        entry = None
        for d, c in rows:
            if d >= sig_date:
                entry = c
                break
        if entry is None:
            continue
        _rsg_sig = load_rsg_state().get(code, {})
        position = {
            "code": code, "name": s.get("name", ""), "sig_date": sig_date,
            "entry": entry, "gate": s.get("gate", ""), "g1": s.get("g1", ""),
            "support": s.get("support", ""), "finance": s.get("finance", ""),
            "rsg_sig": _rsg_sig.get("rsg_dev"), "rsg_sig_strong": _rsg_sig.get("rsg_strong", False),
        }
        # 方法分组
        methods = ["A月线反转only"]
        if s.get("g1") in ("双阴", "一阴"):
            methods.append("B+武威G1")
            try:
                if float(s.get("support", 0) or 0) >= 0.05:
                    methods.append("C+v2.1支撑")
            except ValueError:
                pass
        if s.get("finance") == "盈利":
            methods.append("C+v2.1盈利")
        position["methods"] = methods
        portfolio["positions"].append(position)
    with open(PORTFOLIO, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)
    print(f"✅ 纸面组合初始化: {len(portfolio['positions'])} 个信号（{PORTFOLIO}）")

def update_portfolio():
    """更新所有持仓现价，计算盈亏"""
    if not os.path.exists(PORTFOLIO):
        print("❌ 组合未初始化，先 --init")
        return
    pf = json.load(open(PORTFOLIO, encoding="utf-8"))
    _rsg_now = load_rsg_state()
    for p in pf["positions"]:
        rows = get_price(p["code"])
        if rows:
            p["cur_price"] = rows[-1][1]
            p["cur_date"] = rows[-1][0]
            p["ret"] = (p["cur_price"] / p["entry"] - 1) * 100
            p["days"] = (datetime.strptime(rows[-1][0], "%Y-%m-%d") - datetime.strptime(p["sig_date"], "%Y-%m-%d")).days
            _rg_now = _rsg_now.get(p["code"], {})
            p["rsg_now"] = _rg_now.get("rsg_dev")
            p["rsg_now_strong"] = _rg_now.get("rsg_strong", False)
    pf["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    json.dump(pf, open(PORTFOLIO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ 组合已更新（{len(pf['positions'])} 个信号）")

def report():
    pf = json.load(open(PORTFOLIO, encoding="utf-8"))
    positions = [p for p in pf["positions"] if "ret" in p]
    if not positions:
        print("⏳ 先 --update 更新盈亏")
        return
    L = []
    A = L.append
    A(f"# 📊 纸面组合跟踪报告（不依赖实盘）\n")
    A(f"> 初始化: {pf.get('init_date')} | 更新: {pf.get('last_update')} | 信号数: {len(positions)}")
    A(f"> 口径：信号日收盘入场 → 现价盈亏，按选股方法分组对比\n")
    A("## 一、选股方法效果对比（纸面组合）\n")
    A("| 方法 | 持仓数 | 胜率 | 平均收益 | 中位 | 累计 |")
    A("|:----|:---:|:----:|:-------:|:----:|:----:|")
    groups = {}
    for p in positions:
        for m in p.get("methods", []):
            groups.setdefault(m, []).append(p["ret"])
    order = ["A月线反转only", "B+武威G1", "C+v2.1支撑", "C+v2.1盈利", "E三阶共振"]
    for m in order:
        rets = groups.get(m, [])
        if len(rets) < 3:
            continue
        wins = [r for r in rets if r > 0]
        A(f"| {m} | {len(rets)} | {len(wins)/len(rets)*100:.0f}% | {sum(rets)/len(rets):+.2f}% | {sorted(rets)[len(rets)//2]:+.2f}% | {sum(rets):+.1f}% |")
    # RSG 分组对比（2026-08-28：RSG实盘验证闭环，验证强势侧过滤是否有效）
    A("\n## 二、RSG 强势池分组对比（RSG实盘验证）\n")
    A("> 口径：按**当前RSG状态**分组（周线RS偏离52周均线>50‰=强势池）。若RSG过滤有效，强势池组收益应显著优于非强势池组。\n")
    A("| 分组 | 持仓数 | 胜率 | 平均收益 | 累计 |")
    A("|:----|:---:|:----:|:-------:|:----:|")
    _grp_s = [p["ret"] for p in positions if p.get("rsg_now_strong")]
    _grp_w = [p["ret"] for p in positions if not p.get("rsg_now_strong")]
    for _name, _rets in (("🟢 强势池(RSG>50‰)", _grp_s), ("⚪ 非强势池", _grp_w)):
        if len(_rets) >= 3:
            _w = [r for r in _rets if r > 0]
            A(f"| {_name} | {len(_rets)} | {len(_w)/len(_rets)*100:.0f}% | {sum(_rets)/len(_rets):+.2f}% | {sum(_rets):+.1f}% |")
        else:
            A(f"| {_name} | {len(_rets)}（样本不足） | — | — | — |")
    _sig_s = [p["ret"] for p in positions if p.get("rsg_sig_strong")]
    _sig_w = [p["ret"] for p in positions if not p.get("rsg_sig_strong") and p.get("rsg_sig") is not None]
    if len(_sig_s) >= 3 or len(_sig_w) >= 3:
        A("\n> 信号日RSG分组（信号发生时即标注，更严格）：")
        for _name, _rets in (("🟢 信号日强势", _sig_s), ("⚪ 信号日非强势", _sig_w)):
            if len(_rets) >= 3:
                _w = [r for r in _rets if r > 0]
                A(f"| {_name} | {len(_rets)} | {len(_w)/len(_rets)*100:.0f}% | {sum(_rets)/len(_rets):+.2f}% | {sum(_rets):+.1f}% |")
    A("\n## 三、当前持仓清单\n")
    A("| 代码 | 名称 | 信号日 | 入场价 | 现价 | 盈亏 | 天数 | RSG | 方法 |")
    A("|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|:----|")
    for p in sorted(positions, key=lambda x: -x.get("ret", 0)):
        _rsg_txt = "🟢" if p.get("rsg_now_strong") else ("🟡" if (p.get("rsg_now") or 0) > 0 else "⚪")
        A(f"| {p['code']} | {p['name']} | {p['sig_date']} | {p['entry']:.2f} | {p.get('cur_price', 0):.2f} | {p.get('ret', 0):+.1f}% | {p.get('days', 0)} | {_rsg_txt} | {'+'.join(p.get('methods', [])[:3])} |")
    A("\n---")
    A("⚠️ 本报告为纸面模拟跟踪，非实盘记录，不构成投资建议。")
    md = "\n".join(L)
    os.makedirs("outputs", exist_ok=True)
    out = f"outputs/纸面组合跟踪报告_{datetime.now().strftime('%Y-%m-%d')}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {out}")
    print(md[:1200])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="", help="从信号日志CSV初始化")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.init:
        init_portfolio(a.init)
    elif a.update:
        update_portfolio()
    elif a.report:
        report()
    else:
        print(__doc__)
