#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""learn_weights.py —— 仲裁权重自学习（P1-6 配套，2026-08-28）
============================================================
输入：logs/arbiter_signals_log.csv（signal_arbiter.py 每日累积）
     字段: date,code,pts,level,src(用|分隔的信号源明细),rsg_dev
逻辑：对每个信号用 westock 计算"信号后收益"（信号日收盘→当前），
     按 src 中的信号源归属拆分统计各信号源胜率/平均收益/盈亏比，
     对比当前仲裁权重（signal_arbiter.py）给出建议调整。

建议规则（2026-10-11 P0 升级）：
  按「配置键」粒度统计（四维高置信/弱共振/否决、鱼身空中加油、猛兽Setup60/50/40/RS_D/G点、
  双弦共振、乾坤A级，另补 武威精选/反转数值/123-2B/RSV-*），并计算超额收益与 Wilson 置信区间。
  胜率≥60% 且平均超额>0 且样本≥10 → 权重 +1；胜率≤40% 且超额<0 → -1；样本<10 维持现状。
  Wilson 仅作置信标注（下限≥0.45 / 上限≤0.55 记「高」，否则记「小样本」）。

用法:
  python3 learn_weights.py                    # 全量学习
  python3 learn_weights.py --min-days 3       # 信号后≥3天计入
输出: outputs/仲裁权重学习报告_{date}.md
"""
import csv, json, os, re, subprocess, sys, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import shutil as _shutil
_westock_bin = _shutil.which("westock-data-skillhub")
WESTOCK = [_westock_bin] if _westock_bin else ["npx", "-y", "westock-data-skillhub@1.0.3"]
LOG = "logs/arbiter_signals_log.csv"
LOG_CANDIDATES = ["outputs/仲裁信号日志.csv", LOG]


def resolve_log():
    """解析信号日志真实路径：优先 CI 实际产物 outputs/仲裁信号日志.csv，回退旧路径。"""
    for _p in LOG_CANDIDATES:
        if os.path.exists(_p):
            return _p
    return LOG

# 当前仲裁权重（signal_arbiter.py 手工设定，作为对比基线）
CUR_WEIGHTS = {
    "四维高置信": 3, "猛兽Setup60": 3, "猛兽Setup50": 2, "猛兽Setup40": 1,
    "乾坤A级": 2, "鱼身高分": 2, "鱼身普通": 1, "猛兽信号(伏击/RS_D/G点)": 1,
    "双弦共振": 1, "武威精选": 2, "反转数值": 1, "四维否决": -3,
}

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
            di = header.index("date")
            ci = header.index("last")
            if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                rows.append((parts[di], float(parts[ci])))
        except (ValueError, IndexError):
            pass
    rows.sort(key=lambda r: r[0])
    return rows

def signal_return(code, signal_date):
    """信号日收盘 → 当前收益（%），以及自然日数"""
    if re.match(r"^\d{6}$", code):
        code = ("sh" if code.startswith("6") else "sz") + code
    rows = []
    for _ in range(3):
        txt = run(["kline", code, "--period", "day", "--limit", "120"])
        rows = parse_kline(txt)
        if rows:
            break
    if not rows:
        return None, None
    entry = None
    for d, c in rows:
        if d >= signal_date:
            entry = c
            break
    if entry is None:
        return None, None
    cur = rows[-1][1]
    days = (datetime.strptime(rows[-1][0], "%Y-%m-%d") - datetime.strptime(signal_date, "%Y-%m-%d")).days
    return (cur / entry - 1) * 100, days

def classify_keys(src_str):
    """把 src 明细归类到「配置键」粒度（可多属）。2026-10-11：细粒度化，补 123/2B、RSV。"""
    keys = []
    s = src_str or ""
    if "四维" in s:
        if "否决" in s:
            keys.append("四维否决")
        else:
            m = re.search(r"四维(\d+)分", s)
            t = int(m.group(1)) if m else 0
            keys.append("四维高置信" if t >= 7 else "四维弱共振")
    if "鱼身" in s:
        keys.append("鱼身空中加油")
    if "猛兽" in s:
        m = re.search(r"猛兽Setup(\d+)", s)
        if m:
            v = int(m.group(1))
            keys.append("猛兽Setup60" if v >= 60 else ("猛兽Setup50" if v >= 50 else "猛兽Setup40"))
        if "RS_D" in s:
            keys.append("猛兽RS_D")
        if "G点" in s:
            keys.append("猛兽G点")
    if "双弦" in s:
        keys.append("双弦共振")
    if "乾坤" in s:
        keys.append("乾坤A级")
    if "武威" in s:
        keys.append("武威精选")
    if "反转" in s:
        keys.append("反转数值")
    if "123" in s or "2B" in s:
        keys.append("123/2B")
    m = re.search(r"RSV-([A-Za-z_]+)", s)
    if m:
        keys.append(f"RSV-{m.group(1)}")
    out = []
    for k in keys:
        if k not in out:
            out.append(k)
    return out


def wilson(wins, n, z=1.96):
    """Wilson 得分区间（95%）下限/上限。用于小样本胜率的置信判断。"""
    if n <= 0:
        return None, None
    p = wins / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (c - h) / d, (c + h) / d


# 2026-10-11：已改为「配置键」粒度，键名即配置键；无配置键者 keys=[]。
HINT = {}


def _load_config_weights():
    for p in ("config/arbiter_weights.json",
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "arbiter_weights.json")):
        if os.path.exists(p):
            try:
                return (json.load(open(p, encoding="utf-8")).get("weights") or {})
            except Exception:
                pass
    return {}


def _bench_return(bench_rows, d):
    entry = None
    for dd, cc in bench_rows:
        if dd >= d:
            entry = cc
            break
    if entry is None or not bench_rows:
        return None
    return (bench_rows[-1][1] / entry - 1) * 100


def _emit_proposals(date_str, log_path, rows, results, groups, stats, a):
    """输出结构化提案 JSON（供改进台账 / 回验脚本消费）。"""
    bench_rows = []
    for _ in range(3):
        bench_rows = parse_kline(run(["kline", a.bench, "--period", "day", "--limit", "120"]))
        if bench_rows:
            break
    cfg = _load_config_weights()
    key_excess = {}
    for r in results:
        bidx = _bench_return(bench_rows, r["date"]) if bench_rows else None
        if bidx is None:
            continue
        ex = r["ret"] - bidx
        for k in classify_keys(r.get("src", "")):
            key_excess.setdefault(k, []).append(ex)
    props = []
    for key, st in stats.items():
        exs = key_excess.get(key, [])
        avg_ex = (sum(exs) / len(exs)) if exs else None
        keys = [key] if key in cfg else []
        wcur = cfg.get(key, st.get("cur"))
        wsug = wcur
        if st.get("action") == "+1" and isinstance(wcur, int):
            wsug = wcur + 1
        elif st.get("action") == "-1" and isinstance(wcur, int):
            wsug = wcur - 1
        props.append({
            "signal_source": key,
            "n": st["n"],
            "winrate": (round(st["wr"], 3) if st["wr"] is not None else None),
            "avg_ret": (round(st["avg"], 3) if st["avg"] is not None else None),
            "avg_excess": (round(avg_ex, 3) if avg_ex is not None else None),
            "weight_current": wcur,
            "weight_suggested": wsug,
            "action": st.get("action", "hold"),
            "config_keys": keys,
            "note": ("" if keys else "该信号源暂无外置配置键"),
        })
    doc = {
        "date": date_str,
        "log_source": log_path,
        "log_rows": len(rows),
        "window": f"{rows[0]['date']}~{rows[-1]['date']}" if rows else "",
        "min_days": a.min_days,
        "bench": a.bench,
        "rule": "winrate>=60%&n>=10 → +1 ; winrate<=40%&n>=10 → -1 ; 其余 hold",
        "proposals": props,
    }
    os.makedirs("outputs", exist_ok=True)
    json.dump(doc, open(f"outputs/权重提案_{date_str}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-days", type=int, default=3)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--log", default=None, help="信号日志路径（默认自动解析 outputs/仲裁信号日志.csv）")
    ap.add_argument("--emit-proposals", action="store_true", help="额外输出结构化提案 JSON（默认关闭，行为不变）")
    ap.add_argument("--bench", default="sh000001", help="基准指数（提案超额口径）")
    a = ap.parse_args()

    log_path = a.log or resolve_log()
    if not os.path.exists(log_path):
        print(f"❌ 日志不存在: {log_path}\n提示: signal_arbiter.py 运行后自动累积，需积累 2-4 周才有统计意义")
        return

    rows = list(csv.DictReader(open(log_path, encoding="utf-8")))
    print(f"仲裁信号日志: {log_path}（{len(rows)} 条，{rows[0]['date']} ~ {rows[-1]['date']}）")

    # 计算收益
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(signal_return, r["code"], r["date"]): r for r in rows}
        for f in as_completed(futs):
            r = futs[f]
            ret, days = f.result()
            if ret is not None and days >= a.min_days:
                r["ret"] = ret
                r["days"] = days
                results.append(r)
    print(f"有效样本（≥{a.min_days}日）: {len(results)}\n")

    # 按「配置键」粒度分组统计（2026-10-11 P0）
    cfg0 = _load_config_weights()
    bench_rows = []
    for _ in range(3):
        bench_rows = parse_kline(run(["kline", a.bench, "--period", "day", "--limit", "120"]))
        if bench_rows:
            break
    for r in results:
        b = _bench_return(bench_rows, r["date"]) if bench_rows else None
        r["exc"] = (r["ret"] - b) if b is not None else None

    groups = {}
    for r in results:
        for k in classify_keys(r.get("src", "")):
            groups.setdefault(k, []).append(r)

    ORDER = ["四维高置信", "四维弱共振", "四维否决", "鱼身空中加油",
             "猛兽Setup60", "猛兽Setup50", "猛兽Setup40", "猛兽RS_D", "猛兽G点",
             "双弦共振", "乾坤A级", "武威精选", "反转数值", "123/2B",
             "RSV-launch", "RSV-hold", "RSV-exit"]
    KEYS = ORDER + sorted([k for k in groups if k not in ORDER])

    L = [f"# ⚖️ 仲裁权重学习报告 {datetime.now():%Y-%m-%d}", "",
         f"> 数据: {log_path}（{len(rows)}条信号，有效{len(results)}条）| 收益口径: 信号日收盘→当前",
         "> 判据: 胜率≥60%且平均超额>0 → +1；≤40%且超额<0 → -1；样本<10 维持（Wilson 仅作置信标注）",
         "> 2026-10-11 P0：按配置键粒度 + 补 123/2B/RSV + 超额/Wilson", "",
         "| 信号源(配置键) | 样本 | 胜率 | 平均收益 | 平均超额 | 中位 | 盈亏比 | Wilson[下,上] | 当前 | 建议 | 置信 |",
         "|:----|:---:|:----:|:----:|:----:|:----:|:----:|:----:|:----:|:----|:----|"]
    advice = []
    stats = {}
    for key in KEYS:
        rs = groups.get(key, [])
        rets = [x["ret"] for x in rs]
        n = len(rets)
        if n < 3:
            _cur = cfg0.get(key, CUR_WEIGHTS.get(key, "—"))
            L.append(f"| {key} | {n} | 样本不足 | — | — | — | — | — | {_cur} | 数据不足 | — |")
            stats[key] = {"n": n, "wr": None, "avg": None, "exc": None, "med": None, "pl": None,
                          "wlb": None, "wub": None, "cur": (_cur if isinstance(_cur, int) else None),
                          "action": "hold", "conf": ""}
            continue
        wins = [x for x in rets if x > 0]
        wr = len(wins) / n
        avg = sum(rets) / n
        excs = [x["exc"] for x in rs if x.get("exc") is not None]
        exc = (sum(excs) / len(excs)) if excs else None
        med = sorted(rets)[n // 2]
        loss = [x for x in rets if x <= 0]
        pl = (sum(wins) / len(wins)) / abs(sum(loss) / len(loss)) if wins and loss else 99
        wlb, wub = wilson(len(wins), n)
        cur = cfg0.get(key, CUR_WEIGHTS.get(key, 1))
        act, conf = "hold", ""
        if n >= 10 and exc is not None:
            if wr >= 0.60 and exc > 0:
                act = "+1"; conf = "高" if (wlb is not None and wlb >= 0.45) else "低"
            elif wr <= 0.40 and exc < 0:
                act = "-1"; conf = "高" if (wub is not None and wub <= 0.55) else "低"
        tag_c = "高置信" if conf == "高" else "小样本"
        if act == "+1":
            advice.append(f"{key}: 当前{cur} → 建议{min(3, cur+1)}（胜率{wr*100:.0f}%，超额{exc:+.2f}%，{tag_c}）")
        elif act == "-1":
            advice.append(f"{key}: 当前{cur} → 建议{max(-3, cur-1)}（胜率{wr*100:.0f}%，超额{exc:+.2f}%，{tag_c}）")
        sug = {"+1": "↑ +1", "-1": "↓ -1", "hold": "维持"}[act]
        exc_s = f"{exc:+.2f}%" if exc is not None else "—"
        L.append(f"| {key} | {n} | {wr*100:.0f}% | {avg:+.2f}% | {exc_s} | {med:+.2f}% | {pl:.2f} | "
                 f"[{wlb:.2f},{wub:.2f}] | {cur} | {sug} | {conf or '—'} |")
        stats[key] = {"n": n, "wr": wr, "avg": avg, "exc": exc, "med": med, "pl": pl,
                      "wlb": wlb, "wub": wub, "cur": cur, "action": act, "conf": conf}

    L += ["", "## 📌 建议权重调整", ""]
    if advice:
        for x in advice:
            L.append(f"- {x}")
        L.append("")
        L.append("> ⚠️ 建议仅基于信号后表现统计，调整前需人工确认信号逻辑未变")
    else:
        L.append("- 当前样本不足或权重已合理，维持现状")
        L.append("- 建议继续累积 2-4 周后重跑本脚本")
    base = _load_config_weights() or CUR_WEIGHTS
    L += ["", "## 当前仲裁权重基线（config/arbiter_weights.json）", ""]
    for k, v in base.items():
        L.append(f"- {k}: {v}")
    L += ["", "---", "⚠️ 本报告为统计学习输出，不构成投资建议。"]

    md = "\n".join(L)
    os.makedirs("outputs", exist_ok=True)
    date_str = f"{datetime.now():%Y-%m-%d}"
    out = f"outputs/仲裁权重学习报告_{date_str}.md"
    open(out, "w", encoding="utf-8").write(md)

    if a.emit_proposals:
        doc = _emit_proposals(date_str, log_path, rows, results, groups, stats, a)
        print(f"[OK] outputs/权重提案_{date_str}.json（{len(doc['proposals'])} 项）")

    print(f"[OK] {out}")
    print(md[:1500])

if __name__ == "__main__":
    main()
