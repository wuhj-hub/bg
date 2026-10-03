#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
env_engine.py —— 环境唯一化引擎（第 1 层 env）
=========================================================
把散落的 5 个「环境/温度」子分收敛为【一个 env 温度】，消除"同一问题多个答案"。
定位：**仓位总闸**（温度 → position_cap）。
设计文档：《env设计草案_第1层环境唯一化_2026-10-03.md》（知识库「报告」→「指标存档」）

设计原则
--------
1. **只读各子分已有 latest，不重复取数** —— 零额外网络成本
2. **阶段 1 = 线性加权 + 固定锚点分档映射**（准归一化，把各子分刻度拉齐到"50≈各自中性"）
   · 阶段 2（env_history ≥ 60~120 日）再切分位归一
3. **数据源故障一律 null / degraded，禁止用 50 假装中性**（沿用 2026-09-15 加固教训）
4. 不动任何现有模型（双弦/鱼身/猛兽 2~4 周内只做对照）

子分与来源
----------
  index_trend ← quant_results_latest.json 的 beast "安全评分"（猛兽 check_market_safety）
                （回退：最新 premarket_judgment_*.json 的 beast_score）
  emotion     ← hot_emotion_latest.json        score.score
  width       ← market_width_latest.json       score
  breadth     ← xihu_breadth_latest.json       qsg_pct（+ 新高/新低净额微调）
  structure   ← yearline_breadth_latest.json   ratio_pct（回退 market_regime_latest.json width.above250）
  style       ← market_style_latest.json       （独立轴，**不进温度**）
  phase       ← 情绪预判_latest.json            （独立字段）

用法
----
  python3 quant_scripts/env_engine.py            # 合成并写盘
  python3 quant_scripts/env_engine.py --dry-run  # 只打印不写文件
  python3 quant_scripts/env_engine.py --no-gate  # 不加 structure 硬门槛（对照用）

输出
----
  outputs/env_latest.json    （+ 仓库根 env_latest.json 副本，供同 job 后续步骤）
  outputs/env_history.json   （按 data_date 累积，供阶段 2 分位归一 / 权重校准）
"""
import sys
import os
import re
import json
import glob
import argparse
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))

# ── 权重（§5.3 默认组合，加总=1.00）─────────────────────────────
WEIGHTS = {
    "index_trend": 0.30,
    "emotion":     0.22,
    "width":       0.20,
    "breadth":     0.18,
    "structure":   0.10,
}
SUBS = list(WEIGHTS.keys())

# ── 固定锚点映射（阶段1：把各子分刻度拉齐，50 ≈ 各自中性区）──────
# 每项为 [(raw, mapped), ...]，线性内插；raw 单调递增
ANCHORS = {
    # 猛兽自带 0-100，中性带 40~55（安全≥70/偏暖≥55/中性≥40/偏冷≥25/危险<25）→ 近似恒等
    "index_trend": [(0, 0), (25, 25), (40, 40), (55, 55), (70, 70), (100, 100)],
    # hot_emotion：score 50 = 中性（叶岚校准，8/18 涨停80只→50分"中性"）→ 恒等
    "emotion":     [(0, 0), (25, 25), (40, 40), (55, 55), (70, 70), (100, 100)],
    # market_width：含最高 +30 赚钱效应加成，天然偏高 → 下压（40/55/70 为其震荡/偏强/强分档边界）
    "width":       [(0, 0), (40, 35), (55, 50), (70, 70), (100, 100)],
    # 西湖 QSG%：原文参考线 6 / 20；13.2 = 563 日历史均值（映射到 50）
    "breadth":     [(0, 0), (6, 30), (13.2, 50), (20, 70), (36, 100)],
    # 年线广度（站上年线占比%）：20/40/60 为深度熊/熊/分化/牛 分档边界
    "structure":   [(0, 0), (20, 15), (40, 40), (60, 65), (100, 100)],
}

# ── 温度分档 → 建议仓位上限（§7 f(E) 初值）────────────────────
LEVELS = [   # (下界, level, position_cap%)
    (75, "偏热", 100),
    (60, "偏暖", 80),
    (45, "中性", 60),
    (30, "偏冷", 40),
    (-1, "冰点", 20),
]
# structure 硬门槛（一票否决）：占比 < 阈值 → 封顶
STRUCT_GATES = [(20, 30), (40, 50)]

METHOD = "linear+anchors(stage1)"


# ══════════════════════════ 工具 ══════════════════════════
def find_json(name):
    """在 cwd / 仓库根 / outputs / ../outputs 里找文件，返回首个命中路径。"""
    for base in (os.getcwd(), ROOT, os.path.join(ROOT, "outputs"),
                 os.path.join(os.getcwd(), "outputs")):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return None


def _num(v):
    """从数字或 '33.0/100' 这类字符串里取数值。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        if m:
            return float(m.group(0))
    return None


def norm_date(v):
    if not v:
        return None
    s = str(v)
    m = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def anchor(sub, raw):
    """固定锚点分段线性映射 raw → 统一刻度 0~100。"""
    if raw is None:
        return None
    pts = ANCHORS[sub]
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


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════ 子分加载器 ══════════════════════════
def load_index_trend():
    """猛兽大盘安全评分（index_trend）。"""
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
            d = _read(p)
            txt = (d.get("beast") or {}).get("stdout", "") or ""
            m = re.search(r"安全评分[:：]\s*(\d+(?:\.\d+)?)\s*/\s*100", txt)
            if m:
                return {"raw": float(m.group(1)), "date": norm_date(d.get("date")),
                        "src": "beast_safety"}
        except Exception:
            continue
    # 回退：最新 premarket_judgment_*.json
    cands = []
    for base in (os.getcwd(), ROOT, os.path.join(ROOT, "outputs")):
        cands += glob.glob(os.path.join(base, "premarket_judgment_*.json"))
    for pp in sorted(cands, reverse=True):
        try:
            d = _read(pp)
            v = _num(d.get("beast_score"))
            if v is not None:
                return {"raw": v, "date": norm_date(d.get("date")) or norm_date(pp),
                        "src": "beast_safety(premarket)"}
        except Exception:
            continue
    return None


def load_emotion():
    p = find_json("hot_emotion_latest.json")
    if not p:
        return None
    try:
        d = _read(p)
        sc = d.get("score")
        v = sc.get("score") if isinstance(sc, dict) else sc
        v = _num(v)
        if v is None:
            return None
        return {"raw": v, "date": norm_date(d.get("date")), "src": "hot_emotion"}
    except Exception:
        return None


def load_width():
    p = find_json("market_width_latest.json")
    if not p:
        return None
    try:
        d = _read(p)
        v = _num(d.get("score"))
        if v is None:
            return None
        return {"raw": v, "date": norm_date(d.get("date")), "src": "market_width"}
    except Exception:
        return None


def load_breadth():
    p = find_json("xihu_breadth_latest.json")
    if not p:
        return None
    try:
        d = _read(p)
        qsg = _num(d.get("qsg_pct"))
        if qsg is None:
            return None
        net = _num(d.get("net_high"))
        adj = 0.0
        if net is not None:
            adj = 5.0 if net > 0 else (-5.0 if net < 0 else 0.0)   # 晴/雨微调（作用于映射后分数）
        return {"raw": qsg, "adj": adj, "date": norm_date(d.get("date")),
                "src": "xihu_breadth", "qsg_pct": qsg, "net_high": net}
    except Exception:
        return None


def load_structure():
    p = find_json("yearline_breadth_latest.json")
    if p:
        try:
            d = _read(p)
            v = _num(d.get("ratio_pct"))
            if v is None:
                v = _num(d.get("ratio"))
            if v is not None:
                return {"raw": v, "date": norm_date(d.get("date")), "src": "yearline_breadth"}
        except Exception:
            pass
    # 回退：market_regime_latest.json 的 width.above250（比例 0~1）
    p2 = find_json("market_regime_latest.json")
    if p2:
        try:
            d = _read(p2)
            a = _num((d.get("width") or {}).get("above250"))
            if a is not None:
                v = a * 100 if a <= 1 else a
                return {"raw": v, "date": norm_date(d.get("date")), "src": "market_regime.above250"}
        except Exception:
            pass
    return None


LOADERS = {
    "index_trend": load_index_trend,
    "emotion":     load_emotion,
    "width":       load_width,
    "breadth":     load_breadth,
    "structure":   load_structure,
}


def load_style():
    p = find_json("market_style_latest.json")
    if not p:
        return None
    try:
        d = _read(p)
        return {"score": d.get("score"), "label": d.get("style"), "icon": d.get("icon", "")}
    except Exception:
        return None


def load_phase():
    p = find_json("情绪预判_latest.json")
    if not p:
        return None
    try:
        d = _read(p)
        return {"label": d.get("state") or d.get("level"),
                "limitup": d.get("limitup"), "date": norm_date(d.get("date"))}
    except Exception:
        return None


# ══════════════════════════ 合成 ══════════════════════════
def pick_date(subs):
    """data_date = 各子分日期的多数票（防单源滞后/灌假数据）。"""
    from collections import Counter
    ds = [v["date"] for v in subs.values() if v.get("date")]
    if not ds:
        return None
    return Counter(ds).most_common(1)[0][0]


def level_cap(temp):
    for lo, lv, cap in LEVELS:
        if temp >= lo:
            return lv, cap
    return "冰点", 20


def gate_cap(cap, structure_mapped):
    if structure_mapped is None:
        return cap
    for thr, limit in STRUCT_GATES:
        if structure_mapped < thr:
            return min(cap, limit)
    return cap


def compose(use_gate=True):
    subs, detail, missing = {}, {}, []
    for name, fn in LOADERS.items():
        r = fn()
        if not r:
            missing.append(name)
            continue
        mapped = anchor(name, r["raw"])
        if mapped is not None and r.get("adj"):
            mapped = max(0.0, min(100.0, round(mapped + r["adj"], 1)))   # 晴/雨微调
        if mapped is None:
            missing.append(name)
            continue
        r["mapped"] = mapped
        subs[name] = r

    avail_w = sum(WEIGHTS[n] for n in subs)
    temp = None
    if subs and avail_w > 0:
        temp = round(sum(WEIGHTS[n] * subs[n]["mapped"] for n in subs) / avail_w, 1)

    level, pos_cap = ("⚠️数据缺失", None) if temp is None else level_cap(temp)
    if temp is not None and use_gate:
        pos_cap = gate_cap(pos_cap, subs.get("structure", {}).get("mapped"))

    for n in SUBS:
        if n in subs:
            detail[n] = {"raw": round(subs[n]["raw"], 2), "score": subs[n]["mapped"],
                         "w": WEIGHTS[n], "src": subs[n]["src"], "date": subs[n]["date"]}
        else:
            detail[n] = {"raw": None, "score": None, "w": WEIGHTS[n],
                         "src": "缺失", "date": None}

    div = {}
    if "index_trend" in subs and "emotion" in subs:
        div["index_vs_emotion"] = round(subs["index_trend"]["mapped"] - subs["emotion"]["mapped"], 1)
    if "breadth" in subs and "width" in subs:
        div["breadth_vs_width"] = round(subs["breadth"]["mapped"] - subs["width"]["mapped"], 1)

    out = {
        "data_date": pick_date(subs),
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "temp": temp,
        "level": level,
        "position_cap": pos_cap,
        "subs": detail,
        "style": load_style(),
        "phase": load_phase(),
        "divergence": div,
        "degraded": len(missing) > 0,
        "missing": missing,
        "weights": dict(WEIGHTS),
        "method": METHOD,
        "gate_applied": bool(use_gate),
    }
    return out


# ══════════════════════════ 写盘 ══════════════════════════
def write_out(out, outdir="outputs"):
    os.makedirs(outdir, exist_ok=True)
    latest = os.path.join(outdir, "env_latest.json")
    hist = os.path.join(outdir, "env_history.json")
    dd = out.get("data_date")

    # 防倒灌：旧数据日快照不得覆盖较新的
    if os.path.isfile(latest):
        try:
            old = _read(latest)
            od = old.get("data_date")
            if od and dd and od > dd:
                print(f"[SKIP] 已有更新快照({od}) > 本次({dd})，不覆盖 env_latest.json")
                return
            if od and dd and od == dd:
                print(f"[WARN] 同一数据日 {dd} 重复写入，覆盖（可能是不同源/不同运行时刻）")
        except Exception:
            pass

    txt = json.dumps(out, ensure_ascii=False, indent=1)
    open(latest, "w", encoding="utf-8").write(txt)
    print(f"[OK] {latest}")

    # 仓库根副本（供同 job 后续步骤读取）
    root_copy = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(latest)), "..", "env_latest.json"))
    try:
        with open(root_copy, "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"[OK] {root_copy}")
    except Exception as e:
        print(f"[WARN] 写仓库根副本失败: {e}")

    # 按 data_date 累积 history
    h = {}
    if os.path.isfile(hist):
        try:
            h = _read(hist)
        except Exception:
            h = {}
    if dd:
        h[dd] = {"temp": out["temp"], "level": out["level"], "position_cap": out["position_cap"],
                 "subs": {k: v["score"] for k, v in out["subs"].items()},
                 "divergence": out["divergence"], "degraded": out["degraded"]}
        open(hist, "w", encoding="utf-8").write(json.dumps(h, ensure_ascii=False, indent=1))
        print(f"[OK] {hist}（累积 {len(h)} 个数据日）")


def main():
    ap = argparse.ArgumentParser(description="环境唯一化引擎（第1层 env）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    ap.add_argument("--no-gate", action="store_true", help="不加 structure 硬门槛")
    ap.add_argument("--outdir", default="outputs")
    args = ap.parse_args()

    out = compose(use_gate=not args.no_gate)

    print("=" * 60)
    print(f"  环境引擎 env · 数据日 {out['data_date']} · 方法 {out['method']}")
    print("=" * 60)
    for n in SUBS:
        d = out["subs"][n]
        if d["score"] is None:
            print(f"  {n:<12} 缺失")
        else:
            print(f"  {n:<12} raw={d['raw']:>7} → {d['score']:>5}  (w={d['w']})  [{d['src']}]")
    print("-" * 60)
    print(f"  温度 temp = {out['temp']}  ({out['level']})   仓位上限 = {out['position_cap']}%"
          + ("" if out["gate_applied"] else "  [未加门槛]"))
    if out["divergence"]:
        print(f"  背离     = {out['divergence']}")
    if out["style"]:
        print(f"  风格轴   = {out['style']['icon']} {out['style']['label']} ({out['style']['score']})")
    if out["phase"]:
        print(f"  情绪阶段 = {out['phase']['label']}")
    if out["degraded"]:
        print(f"  ⚠️ degraded=True 缺失子分: {out['missing']}（权重已按比例分摊）")
    print("=" * 60)

    if not args.dry_run:
        write_out(out, args.outdir)


if __name__ == "__main__":
    main()
