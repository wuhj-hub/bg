#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weight_change_review.py —— 仲裁权重·改进台账回验器（L1 闭环第 5 环）
========================================================================
配套：learn_weights.py（提议，--emit-proposals）、signal_arbiter.py（执行，读 config 权重）
定位：AI 只做「回验 + 给结论」，不改交易逻辑；rollback 默认需人工确认才执行。

输入（均可自动解析，缺失容错）：
  logs/weight_change_ledger.csv   改进台账（提议+确认+排期；本脚本回填回验列）
  outputs/仲裁信号日志.csv         仲裁信号日累积（CI 实际产物，列 date,code,pts,level,month,src）
                                   —— 回退旧路径 logs/arbiter_signals_log.csv
  config/arbiter_weights.json     权重配置（仅 --execute-rollback 且单键映射时改写）
  westock kline                   个股/基准 日线

逻辑：
  对所有 decision=adopt、verdict 为空、且 eval_due <= 今天的台账行：
    取该信号源在 [date_decided, eval_date] 内的新信号 →
    算每条信号 H 交易日前瞻「超额收益」(个股收益 − 同期基准收益) →
    汇总 eval_n / eval_winrate / eval_avg_excess，与 evidence_avg_excess（调整前基准）比 →
    判定 keep / rollback / inconclusive

判定阈值（可调，宁可 inconclusive 不硬给结论）：
  MIN_EVAL_N     = 6     回验样本不足 → inconclusive（顺延一个 horizon）
  ROLLBACK_DELTA = 1.5   平均超额较调整前恶化 >1.5pp → rollback
  ROLLBACK_WR    = 0.40  回验胜率 <40% → rollback
  其余（不劣化）→ keep

安全边界：
  · 默认 dry-run，只出报告，不改任何文件；
  · --apply 才回填台账回验列；
  · --execute-rollback 才改权重，且**仅当** signal_source 能唯一映射到一个配置键时才执行；
    粗标签（如「猛兽」「四维加分」跨多个键）一律只给结论、不自动改，交人工。

用法：
  python3 weight_change_review.py                 # 干跑
  python3 weight_change_review.py --apply         # 回填台账
  python3 weight_change_review.py --apply --execute-rollback   # 且自动回滚（单键时）
  python3 weight_change_review.py --horizon 20 --bench sh000001
输出：outputs/权重改进回验_{date}.md
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

LEDGER = "logs/weight_change_ledger.csv"
SIGNAL_LOG = "logs/arbiter_signals_log.csv"
SIGNAL_LOG_CANDIDATES = ["outputs/仲裁信号日志.csv", SIGNAL_LOG]
WEIGHTS_JSON = "config/arbiter_weights.json"
OUT_DIR = "outputs"

# ---- 免 npx：命中已装 bin 则直调，否则回退 npx（与主流水线一致）----
_bin = shutil.which("westock-data-skillhub")
WESTOCK = [_bin] if _bin else ["npx", "-y", "westock-data-skillhub@1.0.3"]

MIN_EVAL_N = 6
ROLLBACK_DELTA = 1.5   # pp
ROLLBACK_WR = 0.40
KLINE_LIMIT = 160

# 聚合标签 → 外置配置键（与 learn_weights.py HINT 同口径）
HINT = {
    "四维加分": ["四维高置信", "四维弱共振"],
    "四维否决": ["四维否决"],
    "猛兽": ["猛兽Setup60", "猛兽Setup50", "猛兽Setup40", "猛兽RS_D", "猛兽G点"],
    "鱼身": ["鱼身空中加油"],
    "双弦": ["双弦共振"],
    "乾坤": ["乾坤A级"],
    "武威": [],
    "反转": [],
}

LEDGER_COLS = [
    "change_id", "date_proposed", "signal_source", "weight_before", "weight_after",
    "rule", "evidence_window", "evidence_n", "evidence_winrate", "evidence_avg_excess",
    "decision", "decided_by", "date_decided", "cooldown_until", "eval_horizon",
    "eval_due", "eval_date", "eval_n", "eval_winrate", "eval_avg_excess", "delta_excess",
    "verdict", "action", "notes",
]


def resolve_signal_log():
    for p in SIGNAL_LOG_CANDIDATES:
        if os.path.exists(p):
            return p
    return SIGNAL_LOG


# ---------------------------------------------------------------- utils
def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
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
        if not header or "---" in parts[0] or len(parts) < 6:
            continue
        try:
            di, ci = header.index("date"), header.index("last")
            if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                rows.append((parts[di], float(parts[ci])))
        except (ValueError, IndexError):
            pass
    rows.sort(key=lambda r: r[0])
    return rows


def norm_code(code):
    code = (code or "").strip()
    if re.match(r"^\d{6}$", code):
        return ("sh" if code.startswith("6") else "sz") + code
    return code


def fetch_kline(code):
    for _ in range(3):
        rows = parse_kline(run(["kline", norm_code(code), "--period", "day", "--limit", str(KLINE_LIMIT)]))
        if rows:
            return rows
    return []


def fwd_ret(rows, start_date, horizon):
    i = next((k for k, (d, _) in enumerate(rows) if d >= start_date), None)
    if i is None or i + horizon >= len(rows):
        return None
    return (rows[i + horizon][1] / rows[i][1] - 1) * 100


def classify_src(src):
    s, tags = src or "", []
    if "四维" in s:
        tags.append("四维" + ("否决" if "否决" in s else "加分"))
    for key, tag in [("鱼身", "鱼身"), ("猛兽", "猛兽"), ("双弦", "双弦"),
                     ("乾坤", "乾坤"), ("武威", "武威"), ("反转", "反转")]:
        if key in s:
            tags.append(tag)
    return tags


def today():
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- core
def load_ledger():
    if not os.path.exists(LEDGER):
        print(f"❌ 台账不存在: {LEDGER}")
        sys.exit(2)
    with open(LEDGER, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def pending_rows(rows, tdate):
    out = []
    for r in rows:
        if (r.get("verdict") or "").strip():
            continue
        due = (r.get("eval_due") or "").strip()
        if due and due <= tdate and (r.get("decision") or "").strip() == "adopt":
            out.append(r)
    return out


def load_signals(log_path):
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def review_one(row, signals, bench_rows, horizon, tdate):
    src = (row.get("signal_source") or "").strip()
    d0 = (row.get("date_decided") or "").strip() or (row.get("date_proposed") or "").strip()
    d1 = (row.get("eval_date") or "").strip() or tdate
    pool = [s for s in signals
            if d0 <= (s.get("date") or "") <= d1 and src in classify_src(s.get("src", ""))]
    rets, cache = [], {}
    for s in pool:
        code = s.get("code", "")
        if code not in cache:
            cache[code] = fetch_kline(code)
        rg = fwd_ret(cache[code], s.get("date", ""), horizon)
        bg = fwd_ret(bench_rows, s.get("date", ""), horizon) if bench_rows else None
        if rg is not None and bg is not None:
            rets.append(rg - bg)
    n = len(rets)
    if n < MIN_EVAL_N:
        return dict(eval_n=n, eval_winrate="", eval_avg_excess="",
                    delta_excess="", verdict="inconclusive", action="none",
                    notes=f"回验样本{n}<{MIN_EVAL_N}，顺延")
    wr = sum(1 for x in rets if x > 0) / n
    avg = sum(rets) / n
    try:
        before = float(row.get("evidence_avg_excess") or 0)
    except ValueError:
        before = 0.0
    delta = avg - before
    verdict = "rollback" if (avg <= before - ROLLBACK_DELTA or wr < ROLLBACK_WR) else "keep"
    return dict(eval_n=n, eval_winrate=f"{wr:.2f}", eval_avg_excess=f"{avg:+.2f}",
                delta_excess=f"{delta:+.2f}", verdict=verdict, action="none", notes="")


def write_ledger(rows):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in LEDGER_COLS})


def can_auto_rollback(src):
    """仅当标签唯一映射到一个配置键时才允许自动回滚。"""
    keys = HINT.get(src, [])
    return keys[0] if len(keys) == 1 else None


def do_rollback(row):
    """按单键映射把权重改回 weight_before；粗标签返回 False（交人工）。"""
    key = can_auto_rollback((row.get("signal_source") or "").strip())
    if not key or not os.path.exists(WEIGHTS_JSON):
        return False
    try:
        wb = int(row.get("weight_before"))
    except (TypeError, ValueError):
        return False
    cfg = json.load(open(WEIGHTS_JSON, encoding="utf-8"))
    if key not in (cfg.get("weights") or {}):
        return False
    cfg["weights"][key] = wb
    cfg["updated"] = today()
    json.dump(cfg, open(WEIGHTS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="回填台账回验列")
    ap.add_argument("--execute-rollback", action="store_true", help="自动回滚（仅单键映射生效）")
    ap.add_argument("--horizon", type=int, default=20, help="前瞻交易日")
    ap.add_argument("--bench", default="sh000001", help="基准指数代码")
    ap.add_argument("--log", default=None, help="信号日志路径（默认自动解析）")
    a = ap.parse_args()

    tdate = today()
    rows = load_ledger()
    todo = pending_rows(rows, tdate)
    print(f"台账 {len(rows)} 行，待回验 {len(todo)} 行（{tdate}）")
    if not todo:
        print("无到期回验项。")
        return

    log_path = a.log or resolve_signal_log()
    signals = load_signals(log_path)
    bench_rows = fetch_kline(a.bench)
    print(f"信号日志 {log_path}（{len(signals)} 条）；基准 {a.bench} {len(bench_rows)} 根K线；horizon={a.horizon}日")

    L = [f"# 🔁 权重改进回验报告 {tdate}", "",
         f"> 台账待回验 {len(todo)} 项 | 前瞻 {a.horizon} 交易日 | 基准 {a.bench} | 口径=超额收益",
         f"> 信号日志: {log_path}", "",
         "| change_id | 信号源 | 权重变化 | n | 胜率 | 平均超额 | Δvs调整前 | 结论 |",
         "|:---|:---|:---:|:--:|:--:|:--:|:--:|:--|"]
    n_rollback = 0
    for r in todo:
        res = review_one(r, signals, bench_rows, a.horizon, tdate)
        L.append(f"| {r.get('change_id','')} | {r.get('signal_source','')} | "
                 f"{r.get('weight_before','')}→{r.get('weight_after','')} | {res['eval_n']} | "
                 f"{res['eval_winrate'] or '—'} | {res['eval_avg_excess'] or '—'} | "
                 f"{res['delta_excess'] or '—'} | {res['verdict']} |")
        if res["verdict"] == "rollback":
            n_rollback += 1
            auto = can_auto_rollback((r.get("signal_source") or "").strip())
            done = False
            if a.execute_rollback and auto:
                done = do_rollback(r)
            res["action"] = "rolled_back" if done else "rollback_pending"
            tip = ("已自动回滚" if done else
                   (f"可自动回滚至 {r.get('weight_before','')}（单键 {auto}）" if auto
                    else "粗标签跨多键，需人工拆分后手动回滚"))
            L.append(f"| ↳ | ⚠️ 建议回滚 {r.get('signal_source','')} | | | | | | {tip} |")
        if a.apply:
            r["eval_date"] = tdate
            for k in ("eval_n", "eval_winrate", "eval_avg_excess", "delta_excess", "verdict", "action", "notes"):
                r[k] = res[k]

    L += ["", "---",
          "> 判定：avg 超额 ≤ 调整前−1.5pp 或 胜率<40% → rollback；样本<6 → inconclusive；其余 keep。",
          f"> 本轮 rollback {n_rollback} 项；rollback 默认需人工确认（--execute-rollback 且单键映射才自动）。",
          "> ⚠️ 本报告为统计输出，不构成投资建议。"]

    md = "\n".join(L)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = f"{OUT_DIR}/权重改进回验_{tdate}.md"
    open(out, "w", encoding="utf-8").write(md)
    if a.apply:
        write_ledger(rows)
    print(f"[OK] {out}" + ("（已回填台账）" if a.apply else "（干跑，未改文件）"))
    print(md[:1400])


if __name__ == "__main__":
    main()
