#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
env_compare.py —— env 与三系统温度对照工具（观察期用，不改动任何模型）
=========================================================
目的：在 env 引擎上线的 2~4 周观察期内，回答三个问题
  1. env 温度 与 猛兽(双弦)/鱼身 温度 的历史走势是否一致？（相关性）
  2. env 的仓位总闸 position_cap，相比盘前原有 final_pos 会砍多少？（总闸是否有效）
  3. 分歧出现在哪些日子？（背离日清单）

数据来源（全部只读）
  env            ← env_history.json（env_engine.py 逐日累积）
  premarket 历史  ← premarket_judgment_*.json（含 beast_score / fish_temp / final_pos）
  latest 三系统   ← quant_results_latest.json（beast 安全分 / shuangxian 温度 / fishbody 温度）

用法
  python3 quant_scripts/env_compare.py                 # 打印 + 写 outputs/env_对照_latest.md
  python3 quant_scripts/env_compare.py --print         # 只打印
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


# ──────────────────────── 工具 ────────────────────────
def find_json(name):
    for base in (os.getcwd(), ROOT, os.path.join(ROOT, "outputs"),
                 os.path.join(os.getcwd(), "outputs")):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return None


def num(v):
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
    m = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", str(v))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx ** 0.5 * syy ** 0.5)


# ──────────────────────── 加载 ────────────────────────
def load_env_history():
    p = find_json("env_history.json")
    if not p:
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def load_premarket_history():
    """从 premarket_judgment_*.json 回填历史 猛兽/鱼身 温度 + final_pos。"""
    out = {}
    cands = []
    for base in (os.getcwd(), ROOT, os.path.join(ROOT, "outputs")):
        cands += glob.glob(os.path.join(base, "premarket_judgment_*.json"))
    for p in sorted(set(cands)):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        dt = norm_date(d.get("date")) or norm_date(os.path.basename(p))
        if not dt:
            continue
        out[dt] = {
            "beast": num(d.get("beast_score")),
            "fish": num(d.get("fish_temp")),
            "final_pos": num(d.get("final_pos")),
            "tone": d.get("tone"),
        }
    return out


def load_quant_latest():
    """从 quant_results_latest.json 取最新三系统温度。"""
    p = find_json("quant_results_latest.json")
    if not p:
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    dt = norm_date(d.get("date"))
    beast_txt = ((d.get("beast") or {}).get("stdout") or "")
    sx_txt = ((d.get("shuangxian") or {}).get("stdout") or "")
    fb = (d.get("fishbody") or {})
    mb = re.search(r"安全评分[:：]\s*([\d.]+)\s*/\s*100", beast_txt)
    ms = re.search(r"温度[:：]\s*([\d.]+)\s*/\s*100", sx_txt)
    ft = (fb.get("market_temp") or {}).get("temp")
    if ft is None:
        mf = re.search(r"温度[:：]\s*([\d.]+)\s*/\s*100", fb.get("stdout") or "")
        ft = mf.group(1) if mf else None
    return {dt: {"beast": num(mb.group(1)) if mb else None,
                 "sx": num(ms.group(1)) if ms else None,
                 "fish": num(ft),
                 "final_pos": None, "tone": None}}


# ──────────────────────── 主逻辑 ────────────────────────
def main():
    ap = argparse.ArgumentParser(description="env 与三系统温度对照")
    ap.add_argument("--print", dest="only_print", action="store_true")
    ap.add_argument("--outdir", default="outputs")
    args = ap.parse_args()

    envh = load_env_history()
    pmh = load_premarket_history()
    ql = load_quant_latest()
    for dt, v in ql.items():
        if dt:
            pmh.setdefault(dt, v)

    dates = sorted(set(envh) | set(pmh))
    if not dates:
        print("[env_compare] 无可用数据（env_history / premarket_judgment 均缺失）")
        return

    L = []
    L.append(f"# env 对照三系统温度（{datetime.now().strftime('%Y-%m-%d')}）\n")
    L.append("> env=环境唯一化引擎温度｜猛兽=猛兽安全评分（双弦温度与之同源，仅 int() 截断）｜鱼身=鱼身上证温度")
    L.append("> Δ=env−对照｜总闸=env.position_cap（%），若 < 盘前 final_pos 则该日 env 会压仓位\n")
    L.append("| 数据日 | env温度 | env档 | 总闸% | 猛兽(双弦) | 鱼身 | Δ(env−猛兽) | Δ(env−鱼身) | 盘前final_pos | 总闸砍仓? |")
    L.append("|---|---:|---|---:|---:|---:|---:|---:|---:|:--:|")

    pairs_b, pairs_f, cuts, div_days = [], [], 0, []
    for dt in dates:
        e = envh.get(dt, {})
        p = pmh.get(dt, {})
        et = e.get("temp")
        beast = p.get("beast")
        fish = p.get("fish")
        cap = e.get("position_cap")
        fp = p.get("final_pos")
        db = round(et - beast, 1) if (et is not None and beast is not None) else None
        df = round(et - fish, 1) if (et is not None and fish is not None) else None
        if db is not None:
            pairs_b.append((et, beast))
        if df is not None:
            pairs_f.append((et, fish))
        cut = ""
        if cap is not None and fp is not None:
            if cap < fp:
                cuts += 1
                cut = f"✅{int(fp - cap)}"
            else:
                cut = "—"
        if db is not None and abs(db) >= 25:
            div_days.append((dt, db))
        L.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            dt,
            f"**{et}**" if et is not None else "—",
            (e.get("level") or "—") + ("⚠️" if e.get("degraded") else ""),
            cap if cap is not None else "—",
            beast if beast is not None else "—",
            fish if fish is not None else "—",
            f"{db:+.1f}" if db is not None else "—",
            f"{df:+.1f}" if df is not None else "—",
            fp if fp is not None else "—",
            cut or "—"))

    L.append("")
    L.append("## 小结")
    if pairs_b:
        xs = [a for a, _ in pairs_b]; ys = [b for _, b in pairs_b]
        r = pearson(xs, ys)
        mad = sum(abs(a - b) for a, b in pairs_b) / len(pairs_b)
        L.append(f"- **env vs 猛兽(双弦)**：n={len(pairs_b)}，相关 r={'%.2f' % r if r is not None else '—'}，平均绝对差 {mad:.1f}")
    if pairs_f:
        xs = [a for a, _ in pairs_f]; ys = [b for _, b in pairs_f]
        r = pearson(xs, ys)
        mad = sum(abs(a - b) for a, b in pairs_f) / len(pairs_f)
        L.append(f"- **env vs 鱼身**：n={len(pairs_f)}，相关 r={'%.2f' % r if r is not None else '—'}，平均绝对差 {mad:.1f}")
    if cuts:
        L.append(f"- **总闸有效性**：{cuts} 个交易日 env.position_cap < 盘前 final_pos（env 会压仓位）")
    if div_days:
        L.append("- **背离日（|Δ(env−猛兽)|≥25）**：" + "、".join(f"{d}({v:+.0f})" for d, v in div_days))
    L.append(f"- env 累积数据日：{len(envh)}（首次产出预计 2026-10-08；≥60~120 日后可切分位归一 + 权重校准）")

    md = "\n".join(L)
    print(md)
    if not args.only_print:
        os.makedirs(args.outdir, exist_ok=True)
        out = os.path.join(args.outdir, "env_对照_latest.md")
        open(out, "w", encoding="utf-8").write(md + "\n")
        print(f"\n[OK] {out}")


if __name__ == "__main__":
    main()
