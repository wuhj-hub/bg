#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""牛市区间标签（曾星智 2026-11-23 六段牛市 + 后续维护）

用途：
  1) 回测分层——判断某个信号是否「只在牛市有效」
  2) 报告提示——当前是否处于牛市区间 / 是否临近区间末段

口径来源：曾星智《过去20年的6次"大牛市"》(2026-11-23)，事后确认的真值标签。
与 regime_history.csv 的分工：regime 是「当日可得的实时判定」（会滞后），
本文件是「事后确认的真值」（不可用于实时择时，只用于统计分层）。

维护：新的牛市结束后，追加一行并 refresh；不要修改历史行。
"""
import csv, os
from datetime import date

CSV_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "bull_markets.csv")


def load(path=None):
    p = path or CSV_DEFAULT
    out = []
    with open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out.append({
                "seq": int(r["seq"]), "start": r["start"], "end": r["end"],
                "months": int(r["months"]), "type": r["type"], "note": r.get("note", ""),
            })
    return out


def label(day, rows=None):
    """返回该日期所处的牛市类型：'full' / 'local' / 'none'（无牛市=熊市或震荡）"""
    d = str(day)[:7]
    for r in (rows or load()):
        if r["start"] <= d <= r["end"]:
            return r["type"], r
    return "none", None


def in_bull(day, rows=None):
    return label(day, rows)[0] != "none"


def tail_zone(day, months=3, rows=None):
    """是否处在某个牛市区间的最后 N 个月（用于「牛市末段减仓」提示）"""
    t, r = label(day, rows)
    if r is None:
        return False, None
    y, m = int(r["end"][:4]), int(r["end"][5:7])
    m -= months
    if m <= 0:
        y, m = y - 1, m + 12
    start_tail = "%04d-%02d" % (y, m)
    return (str(day)[:7] >= start_tail), r


if __name__ == "__main__":
    for d in ("2025-06-30", "2026-05-25", "2026-06-30", "2026-07-16", "2026-11-23", "2023-06-01"):
        t, r = label(d)
        tail, _ = tail_zone(d)
        print(f"{d}  bull={t:5s}  tail3m={tail}  {r['note'] if r else '非牛市'}")
