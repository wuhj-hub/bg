#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_io.py —— 报告读取公共层（多副本防「陈旧劫持」）

背景（2026-10-14）：同名产物常在「仓库根」与「outputs/」两处并存；
若两者不同步、而读取方恰好读了旧的那一份，会**静默使用陈旧数据**
（实例：盘前报告 ③.3 板块共振读取了冻结于 2026-08-13 的 outputs 副本）。

本模块提供 `load_latest(paths)`：在候选路径中读取「数据日期最新」的一份 JSON。
- 日期键优先级：`data_date` > `bar_date` > `trade_date` > `date`
- 行为：取第一个可读的；**仅当**后续候选的数据日期**严格更新**时替换；
  无日期则不替换（保持「今日/dated 文件优先」的既有语义）。
- 详见知识库《产物副本口径与新鲜度约定》、CHANGELOG v2.9。

用法：`from report_io import load_latest as _ri_load` → `_ri_load(("a.json","outputs/a.json"))`
"""
import json

_DATE_KEYS = ("data_date", "bar_date", "trade_date", "date")


def data_date(obj):
    """从 dict 中提取数据日期字符串；无则返回 None。"""
    if isinstance(obj, dict):
        for k in _DATE_KEYS:
            v = obj.get(k)
            if v:
                return str(v)
    return None


def load_latest(paths):
    """在候选路径中读取「数据日期最新」的一份 JSON；全部不可读返回 None。"""
    best = None
    best_key = None
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            continue
        if best is None:
            best, best_key = obj, data_date(obj)
            continue
        k = data_date(obj)
        if best_key is not None and k and k > best_key:
            best, best_key = obj, k
    return best


def first_readable(paths):
    """读取第一个可读的 JSON（不做日期比较）；全部不可读返回 None。"""
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None
