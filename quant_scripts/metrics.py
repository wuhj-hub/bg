#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""metrics.py —— 指标只读访问层（第2层治理 · 指标层标准化 · 分支B · P0）
=========================================================
把「指标 → 字段定义 → 语义修饰」收口成一处显式契约，消除同一指标多个答案。
定位：**只读**访问层，`report_io.py`（副本读取层）的姊妹。
设计文档：《metrics_registry设计_2026-10-16.md》（知识库「报告」→「指标存档」）

原则
----
1. 只读、幂等、无副作用；不写盘、不发网络。
2. 缺失 / 解析失败一律返回 `None`（**禁止用 50 假装中性**，沿用 env 加固教训）。
3. 不复制业务判断：accessor 只做「字段提取 + 已达成共识的刻度修饰」；
   分档 / 阈值仍留在各业务方。

用法
----
  from metrics import load, get, safety_score, width_normalized
  s = safety_score()            # 猛兽安全评分（0-100）
  w = width_normalized()        # 市场宽度分（已按 50≈中性 下压）

范围（P0 试点）
----
  - safety_score()     ← quant_results_latest.json 的 beast 安全评分（含 premarket 回退）
  - width_raw/level/normalized() ← market_width_latest.json
  其余 top-8 指标（rsv_strength / arbiter / qiankun_a / yearline / quad / sector_res）
  已在 REGISTRY 登记，accessor 按后续 P1/P2 增补。
"""
import os
import re
import sys
import json
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))

# 复用副本新鲜度选择（data_date > bar_date > trade_date > date）
try:
    sys.path.insert(0, HERE)
    from report_io import load_latest as _ri_load          # noqa: E402
except Exception:
    _ri_load = None

# ── 注册表：指标名 → 候选路径（多副本交给 report_io 选最新；缺失返回 None）──
REGISTRY = {
    "market_width": ("market_width_latest.json", "outputs/market_width_latest.json",
                     "../outputs/market_width_latest.json"),
    "quant_results": ("quant_results_latest.json", "outputs/quant_results_latest.json"),
    "rsv_strength":  ("outputs/rsv_strength_latest.json", "rsv_strength_latest.json"),
    "arbiter":       ("outputs/信号仲裁_latest.json", "信号仲裁_latest.json"),
    "qiankun_a":     ("outputs/qiankun_a_latest.json", "qiankun_a_latest.json"),
    "yearline":      ("outputs/yearline_breadth_latest.json", "yearline_breadth_latest.json"),
    "quad":          ("outputs/四维共振_latest.json", "四维共振_latest.json"),
    "sector_res":    ("outputs/板块共振_latest.json", "板块共振_latest.json"),
}


# ══════════════════════════ 通用层 ══════════════════════════
def load(name):
    """取该指标「数据日期最新」的一份 JSON；不可读返回 None。"""
    paths = REGISTRY.get(name)
    if not paths:
        return None
    if _ri_load is not None:
        try:
            return _ri_load(paths)
        except Exception:
            pass
    for p in paths:                       # report_io 不可用时的兜底：首个可读
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None


def get(name, *keys, default=None):
    """安全取字段（支持嵌套）：get("market_width","score")；任一环缺失返回 default。"""
    d = load(name)
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        if m:
            return float(m.group(0))
    return None


def _norm_date(v):
    if not v:
        return None
    s = str(v)
    m = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _anchor(pts, raw):
    """固定锚点分段线性映射（raw → 统一刻度）。"""
    if raw is None:
        return None
    if raw <= pts[0][0]:
        return float(pts[0][1])
    if raw >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= raw <= x1:
            if x1 == x0:
                return float(y1)
            return round(y0 + (raw - x0) * (y1 - y0) / (x1 - x0), 1)
    return None


# ══════════════════════════ accessor：market_width ══════════════════════════
# market_width 的 score 含最高 +30「赚钱效应加成」→ 天然偏高；做温度时需下压使 50≈中性。
# （该「下压」知识原先硬编码在 env_engine；2026-10-16 收口到此处）
WIDTH_ANCHORS = [(0, 0), (40, 35), (55, 50), (70, 70), (100, 100)]


def width_raw():
    """market_width.score（原始，含赚钱效应加成）。"""
    return _num(get("market_width", "score"))


def width_level():
    """market_width.level（温度标签）。"""
    return get("market_width", "level")


def width_normalized(raw=None):
    """market_width.score → 下压后统一刻度（50≈中性）；env 温度用。"""
    r = _num(raw) if raw is not None else width_raw()
    return _anchor(WIDTH_ANCHORS, r)


def width_info():
    """{raw,date,src}；缺失返回 None。"""
    d = load("market_width")
    if not isinstance(d, dict):
        return None
    v = _num(d.get("score"))
    if v is None:
        return None
    return {"raw": v, "date": _norm_date(d.get("date")), "src": "market_width"}


# ══════════════════════════ accessor：safety_score（quant_results）══════════════════════════
# quant_results_latest.json 实为各系统 stdout 文本集；「安全评分」在 beast 段。
# 该提取正则原先多处重复，2026-10-16 收口到此处。
_SAFETY_RE = re.compile(r"安全评分[:：]\s*(\d+(?:\.\d+)?)\s*/\s*100")


def safety_score_info():
    """猛兽大盘安全评分 {raw,date,src}；找不到返回 None。
    优先 quant_results_latest.json 的 beast.stdout；回退最新 premarket_judgment_*.json 的 beast_score。"""
    cands, seen = [], set()
    for base in (os.getcwd(), ROOT, os.path.join(ROOT, "outputs"), os.path.join(os.getcwd(), "outputs")):
        p = os.path.join(base, "quant_results_latest.json")
        if os.path.isfile(p):
            cands.append(p)
        cands += sorted(glob.glob(os.path.join(base, "quant_results_2*.json")), reverse=True)
    for p in cands:
        if p in seen:
            continue
        seen.add(p)
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            txt = (d.get("beast") or {}).get("stdout", "") or ""
            m = _SAFETY_RE.search(txt)
            if m:
                return {"raw": float(m.group(1)), "date": _norm_date(d.get("date")), "src": "beast_safety"}
        except Exception:
            continue
    cands = []
    for base in (os.getcwd(), ROOT, os.path.join(ROOT, "outputs")):
        cands += glob.glob(os.path.join(base, "premarket_judgment_*.json"))
    for pp in sorted(cands, reverse=True):
        try:
            with open(pp, encoding="utf-8") as f:
                d = json.load(f)
            v = _num(d.get("beast_score"))
            if v is not None:
                return {"raw": v, "date": _norm_date(d.get("date")) or _norm_date(pp),
                        "src": "beast_safety(premarket)"}
        except Exception:
            continue
    return None


def safety_score():
    """猛兽安全评分（0-100）；找不到返回 None。"""
    info = safety_score_info()
    return info["raw"] if info else None


if __name__ == "__main__":
    print("safety_score     =", safety_score())
    print("width_raw        =", width_raw())
    print("width_level      =", width_level())
    print("width_normalized =", width_normalized())
