#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""perf_schema.py —— 战绩层统一 schema（第4层蒸馏 · 只读适配）
=====================================================================
问题：体系里有 5 套互不兼容的战绩记录格式，各自算各自的胜率：
  1. outputs/pool_entries.csv          entry_date,pool,code,last_seen,times_seen   （无收益，需现算）
  2. outputs/wangzhe_signals.csv       r5/r10/r20 …                                 （百分数，自带）
  3. data/reversal_perf_{day,week,month}.csv  r5/r10/r20 …                          （小数，自带）
  4. data/jingjia_signals.csv          R0..R5                                       （小数，自带）
  5. pools/pool_YYYY-MM.json           双弦月度池 entries（无收益，需现算）
  6. outputs/liangxue_signals_log.csv  date,code,close …                            （无收益，需现算）

本模块把 1~6 归一成同一条记录，收益统一为**百分数**，并提供：
  · trading_ret(bars, date, h)  —— 全体系唯一的「入池日后第 h 个交易日」收益算法
  · fill_returns(recs, kline)   —— 对缺失收益按 K 线现算（只在有 kline 时）
  · summary(recs)               —— 按来源汇总 胜率/均值/样本量

设计原则：**只读、无网络、无副作用**。取数仍由调用方负责（kline 由外部传入），
避免把「数据获取」和「口径定义」再次耦合。

用法（库）：
    from perf_schema import load_all, fill_returns, summary, cell, trading_ret
    recs = load_all()                 # 默认排除 pool_entries（池由章一单独算）
    fill_returns(recs, kline)         # kline: {code: [(date, close), ...]}
    for src, d in summary(recs).items(): ...

用法（CLI，只做自检，不取数）：
    python3 perf_schema.py            # 打印各类来源的记录数与内置收益覆盖
"""
import csv
import glob
import json
import os
import re
import sys

HOLDS = (5, 10, 20, 60)
FIELDS = ("code", "name", "source", "signal_date", "entry_price",
          "r5", "r10", "r20", "r60", "ret_src", "exit_date", "exit_reason", "status")


# ────────────────────────── 基础工具 ──────────────────────────
def norm_code(c):
    """'000001' / 'sz000001' → 'sz000001'。"""
    c = (c or "").strip()
    if re.match(r"^(sh|sz|bj)\d{6}$", c):
        return c
    m = re.search(r"(\d{6})", c)
    if not m:
        return ""
    d = m.group(1)
    return ("sh" if d[0] in ("6", "9", "5") else "sz") + d


def read_csv(p):
    if not os.path.exists(p):
        return []
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(p, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:  # noqa: BLE001
            continue
    return []


def _f(v, pct=False):
    """转 float；pct=True 表示原值是小数，×100 转百分数。"""
    try:
        if v is None or str(v).strip() == "":
            return None
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x * 100.0 if pct else x


def trading_ret(bars, entry_date, h):
    """入池日（或其后的首个交易日）收盘 → +h 个交易日收盘的收益（百分数）。

    bars: [(date, close), ...] 升序；不足 h 根返回 None。
    全体系唯一实现——不要在各脚本里再写一份。
    """
    if not bars or not entry_date:
        return None
    idx = next((i for i, x in enumerate(bars) if x[0] >= entry_date), None)
    if idx is None or idx + h >= len(bars):
        return None
    c0, c1 = bars[idx][1], bars[idx + h][1]
    return (c1 / c0 - 1) * 100 if c0 > 0 else None


def agg(vals):
    """[(百分数)] → (胜率%, 均值%, n)；空返回 None。"""
    if not vals:
        return None
    return (round(sum(1 for x in vals if x > 0) / len(vals) * 100, 1),
            round(sum(vals) / len(vals), 2), len(vals))


def cell(res):
    return "—" if not res else f"{res[0]:.0f}% / {res[1]:+.2f}% (n={res[2]})"


def _rec(**kw):
    r = {k: "" for k in FIELDS}
    r.update({k: v for k, v in kw.items() if k in FIELDS})
    return r


# ────────────────────────── 适配器 ──────────────────────────
def from_pool_entries(root="."):
    """各池累计入池表（无收益，status=open）。"""
    out = []
    for r in read_csv(os.path.join(root, "outputs/pool_entries.csv")):
        code = norm_code(r.get("code"))
        if not code or not r.get("entry_date"):
            continue
        out.append(_rec(code=code, source=r.get("pool", "未命名池"),
                        signal_date=r.get("entry_date"), status="open"))
    return out


def from_wangzhe(root="."):
    """涨停王者：自带 r5/r10/r20（百分数）。"""
    out = []
    for r in read_csv(os.path.join(root, "outputs/wangzhe_signals.csv")):
        code = norm_code(r.get("code"))
        if not code or not r.get("signal_date"):
            continue
        out.append(_rec(code=code, name=r.get("name", ""), source="涨停王者",
                        signal_date=r.get("signal_date"), entry_price=_f(r.get("price")),
                        r5=_f(r.get("r5")), r10=_f(r.get("r10")), r20=_f(r.get("r20")),
                        ret_src="builtin", status="closed"))
    return out


def from_reversal(root="."):
    """反转数值日/周/月线：自带 r5/r10/r20（小数 → 百分数）。"""
    out = []
    for p in sorted(glob.glob(os.path.join(root, "data/reversal_perf_*.csv"))):
        tf = re.search(r"reversal_perf_(\w+)\.csv$", p.replace("\\", "/"))
        tf = tf.group(1) if tf else "day"
        label = {"day": "日线", "week": "周线", "month": "月线"}.get(tf, tf)
        for r in read_csv(p):
            code = norm_code(r.get("code"))
            if not code:
                continue
            out.append(_rec(code=code, name=r.get("name", ""),
                            source=f"反转数值·{label}", signal_date=r.get("first_date"),
                            entry_price=_f(r.get("entry")),
                            r5=_f(r.get("r5"), True), r10=_f(r.get("r10"), True),
                            r20=_f(r.get("r20"), True), ret_src="builtin",
                            exit_date=r.get("exit_date", ""), exit_reason=r.get("exit_reason", ""),
                            status="closed" if r.get("exit_date") else "open"))
    return out


def from_jingjia(root="."):
    """竞价信号：**不采用 CSV 的 R0~R5**。

    原因：该文件的 R 列按「信号日开盘 → 第 N 日收盘」计价，而竞价信号是用
    当日收盘数据算出的 → 含未来函数（实测 R5 均值 +7.27%，真口径约 −4.2%）。
    统一改为「买入价 = buy_open，收益由 K 线现算」，与 pool_winrate 原口径一致。
    """
    out = []
    for r in read_csv(os.path.join(root, "data/jingjia_signals.csv")):
        code = norm_code(r.get("code"))
        if not code or not r.get("date"):
            continue
        out.append(_rec(code=code, name=r.get("name", ""),
                        source=f"竞价·{r.get('strategy', '未知')}", signal_date=r.get("date"),
                        entry_price=_f(r.get("buy_open")), status="open"))
    return out


def from_liangxue(root="."):
    """量学：无收益列，全部待现算。"""
    out = []
    for r in read_csv(os.path.join(root, "outputs/liangxue_signals_log.csv")):
        code = norm_code(r.get("code"))
        if not code or not r.get("date"):
            continue
        out.append(_rec(code=code, name=r.get("name", ""), source="量学",
                        signal_date=r.get("date"), entry_price=_f(r.get("close")),
                        status="open"))
    return out


def from_month_pool(root="."):
    """双弦月度池 pools/pool_YYYY-MM.json：无收益，待现算。"""
    out = []
    for p in sorted(glob.glob(os.path.join(root, "pools/pool_*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:  # noqa: BLE001
            continue
        for e in d.get("entries", []):
            code = norm_code(e.get("code"))
            if not code or not e.get("date_str"):
                continue
            out.append(_rec(code=code, name=e.get("name", ""),
                            source=f"双弦月度池·{e.get('signal_type', '未分类')}",
                            signal_date=e.get("date_str"), entry_price=_f(e.get("price")),
                            status="open"))
    return out


# ────────────────────────── 汇总 ──────────────────────────
def load_all(root=".", with_pools=False):
    """合并所有来源。with_pools=False 时排除 pool_entries（避免与章一重复）。"""
    recs = []
    if with_pools:
        recs += from_pool_entries(root)
    recs += from_wangzhe(root)
    recs += from_reversal(root)
    recs += from_jingjia(root)
    recs += from_liangxue(root)
    recs += from_month_pool(root)
    return recs


def fill_returns(recs, kline, holds=HOLDS):
    """对缺失的 r{h} 用 K 线现算（有 builtin 的保留 builtin，不覆盖）。"""
    n = 0
    for r in recs:
        bars = kline.get(r["code"])
        if not bars:
            continue
        for h in holds:
            key = f"r{h}"
            if key not in r or r[key] != "":
                continue
            v = trading_ret(bars, r["signal_date"], h)
            if v is not None:
                r[key] = round(v, 4)
                r["ret_src"] = r["ret_src"] or "computed"
                n += 1
    return n


def summary(recs, holds=(5, 10, 20)):
    """按来源汇总 → {source: {h: (win%, mean%, n)}}。"""
    out = {}
    for r in recs:
        for h in holds:
            v = r.get(f"r{h}")
            if v == "" or v is None:
                continue
            out.setdefault(r["source"], {}).setdefault(h, []).append(float(v))
    return {s: {h: agg(vs) for h, vs in d.items()} for s, d in out.items()}


def main():
    root = os.getcwd()
    recs = load_all(root, with_pools=False)
    by_src = {}
    for r in recs:
        d = by_src.setdefault(r["source"], {"n": 0, "builtin": 0})
        d["n"] += 1
        if r["ret_src"] == "builtin":
            d["builtin"] += 1
    print(f"统一记录 {len(recs)} 条，来源 {len(by_src)} 个：")
    for s, d in sorted(by_src.items(), key=lambda x: -x[1]["n"]):
        print(f"  {s:<22} 记录 {d['n']:>6}  自带收益 {d['builtin']:>6}")
    sm = summary([r for r in recs if r["ret_src"] == "builtin"])
    if sm:
        print("\n自带收益的源（5日）：")
        for s, d in sorted(sm.items(), key=lambda x: -(x[1].get(5) or (0, 0, 0))[2]):
            print(f"  {s:<22} {cell(d.get(5))}")


if __name__ == "__main__":
    sys.exit(main())
