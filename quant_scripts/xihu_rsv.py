#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xihu_rsv.py —— 西湖-RSV 多周期相对强度模型 v1.1（全市场扫描版）
============================================================
【设计原则】猛兽体系框架为核心 + 西湖框架为方法论
  猛兽框架（骨架）            西湖框架（方法论）
  ───────────────            ──────────────────
  数据层 cli/批量kline     →   基准 = 中证全指 sh000985（对齐猛兽主基准）
  RSV体质 (RSV1+RSV2)/2    →   多周期 N=50/144/250（对齐RPS三周期）
  评分层 分项挂接(猛兽式)   →   新高能力/第二阶段/50日线/周线闸门
  输出层 表格+JSON+评级     →   共振层级（三红/两红）
  并发/主板过滤(猛兽口径)   →   全市场扫描

【模型定义】
  RSV1(N) = (C - LLV(L,N)) / (HHV(H,N) - LLV(L,N)) * 100
  RSV2(N) = (RS - min(RS,N)) / (max(RS,N) - min(RS,N)) * 100   , RS = C / 基准
  RSV(N)  = (RSV1 + RSV2) / 2
  CRS     = 0.25*RSV50 + 0.35*RSV144 + 0.40*RSV250
  结构分  = 100*(0.40*强势股 + 0.35*第二阶段 + 0.25*站上50日线)
  Score   = 0.80*CRS + 0.20*结构分

用法:
  # 全市场扫描（默认，读 all_mainboard.csv，仅主板）
  python3 xihu_rsv.py --top 50 --report outputs/西湖RSV全市场_{date}.md
  # 指定标的
  python3 xihu_rsv.py --stocks sh600519,sz000993
============================================================
"""
import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
BENCH = "sh000985"          # 基准：中证全指（对齐猛兽体系主基准）
N_LIST = [50, 144, 250]
W_CRS = {50: 0.25, 144: 0.35, 250: 0.40}
MAINBOARD_PREFIX = ("600", "601", "603", "605", "000", "001", "002", "003")

DEFAULT_POOL = ["sh600519", "sz000993", "sh601138", "sz002415", "sh600036", "sh601899"]


# ============================================================
#  猛兽数据层
# ============================================================
def cli(args, timeout=180):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def norm(code):
    code = str(code).strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    return ("sh" if code.startswith(("6", "9", "5")) else "sz") + code


def is_mainboard(full):
    return full[2:5] in MAINBOARD_PREFIX


def is_st_name(name):
    n = (name or "").upper().replace(" ", "")
    return "ST" in n


def parse_batch_kline(txt):
    out, cur = {}, None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        p = [x.strip() for x in s.strip("|").split("|")]
        if len(p) < 8 or p[0] == "symbol" or "---" in p[0]:
            continue
        if re.match(r"^(sh|sz|bj)\d{6}$", p[0]):
            cur = p[0]
            try:
                out.setdefault(cur, []).append({
                    "date": p[1], "open": float(p[2]), "close": float(p[3]),
                    "high": float(p[4]), "low": float(p[5]),
                    "volume": float(p[6]), "amount": float(p[7]),
                })
            except (ValueError, IndexError):
                pass
    for c in out:
        out[c].sort(key=lambda r: r["date"])
    return out


def _kline_args(codes, period, limit):
    return ["kline", ",".join(codes), "--period", period, "--limit", str(limit), "--fq", "qfq"]


def fetch(codes, period, limit, chunk=40, workers=8, retries=2):
    """并发批量拉K线 + 缺失补齐（防 westock 静默丢股票）"""
    codes = [norm(c) for c in codes]
    batches = [codes[i:i + chunk] for i in range(0, len(codes), chunk)]

    def _one(sub):
        for _ in range(retries):
            d = parse_batch_kline(cli(_kline_args(sub, period, limit)))
            if d:
                return d
        return {}

    data = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for d in ex.map(_one, batches):
            data.update(d)
    missing = [c for c in codes if c not in data]
    for c in missing:                      # 逐只补齐
        data.update(parse_batch_kline(cli(_kline_args([c], period, limit))))
    return data


# ============================================================
#  猛兽 RSV 体质 + 西湖判据
# ============================================================
def rsv1_price(rows, n):
    seg = rows[-n:] if len(rows) >= n else rows
    if not seg:
        return 50.0
    hi, lo = max(r["high"] for r in seg), min(r["low"] for r in seg)
    c = seg[-1]["close"]
    return (c - lo) / (hi - lo) * 100 if hi != lo else 50.0


def rsv2_rel(rows, idx_map, n):
    rs = [r["close"] / idx_map[r["date"]] for r in rows if r["date"] in idx_map]
    if not rs:
        return 50.0
    seg = rs[-n:] if len(rs) >= n else rs
    hi, lo = max(seg), min(seg)
    return (seg[-1] - lo) / (hi - lo) * 100 if hi != lo else 50.0


def ma(rows, n):
    seg = rows[-n:]
    return sum(r["close"] for r in seg) / len(seg) if seg else 0.0


def judge_xihu(rows):
    if len(rows) < 60:
        return {"strong": False, "stage2": False, "above_ma50": False, "c": rows[-1]["close"] if rows else 0, "ma50": 0}
    c = rows[-1]["close"]
    hhv250 = max(r["high"] for r in rows[-250:])
    llvc200 = min(r["close"] for r in rows[-200:])
    hhvc200 = max(r["close"] for r in rows[-200:])
    m50, m150, m200 = ma(rows, 50), ma(rows, 150), ma(rows, 200)
    stage2 = (c > m50 > m150 > m200) and (c / llvc200 > 1.3) and (c / hhvc200 > 0.75)
    return {"strong": c / hhv250 > 0.90 if hhv250 else False, "stage2": bool(stage2),
            "above_ma50": c > m50, "c": c, "ma50": m50}


def weekly_gate(rows_week):
    if len(rows_week) < 35:
        return None
    closes = [r["close"] for r in rows_week]

    def ema_series(vals, n):
        k = 2 / (n + 1)
        out, e = [], vals[0]
        for v in vals:
            e = v * k + e * (1 - k)
            out.append(e)
        return out
    e12, e26 = ema_series(closes, 12), ema_series(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema_series(dif, 9)
    bar = 2 * (dif[-1] - dea[-1])
    return {"macd_bar": round(bar, 3), "pass": bar >= 0}


def rate(score):
    if score >= 85: return "🔥强共振"
    if score >= 70: return "🟢强势"
    if score >= 55: return "🟡中性偏强"
    if score >= 40: return "⚪中性"
    return "🔻弱势"


def resonance_tag(vals):
    hi = sum(1 for n in N_LIST if vals[n] >= 85)
    if hi == 3: return "🔥三周期共振"
    if hi >= 2: return "⚡双周期共振"
    if hi == 1: return "·单周期强"
    if all(vals[n] >= 70 for n in N_LIST): return "○三周期偏强"
    return "—"


def score_stock(code, rows, idx_map, name="", rps_map=None):
    if rps_map and code in rps_map:
        # 横截面模式：RSV2 用全市场N日涨幅排名百分位（西湖RPS）
        vals = {n: (rsv1_price(rows, n) + rps_map[code][n]) / 2 for n in N_LIST}
    else:
        vals = {n: (rsv1_price(rows, n) + rsv2_rel(rows, idx_map, n)) / 2 for n in N_LIST}
    crs = sum(W_CRS[n] * vals[n] for n in N_LIST)
    jx = judge_xihu(rows)
    structure = 100 * (0.40 * jx["strong"] + 0.35 * jx["stage2"] + 0.25 * jx["above_ma50"])
    score = 0.80 * crs + 0.20 * structure
    return {"code": code, "name": name, "close": round(jx["c"], 2),
            "rsv50": round(vals[50], 1), "rsv144": round(vals[144], 1), "rsv250": round(vals[250], 1),
            "crs": round(crs, 1), "structure": round(structure, 1), "score": round(score, 1),
            "rating": rate(score), "resonance": resonance_tag(vals),
            "strong": jx["strong"], "stage2": jx["stage2"], "above_ma50": jx["above_ma50"],
            "weekly_macd_bar": None, "weekly_gate": "NA"}


def compute_cross_rps(day, codes, n_list=N_LIST):
    """横截面 RPS：全市场 N 日涨幅排名百分位（西湖《RPS高于一切》口径）
    {code: {n: rps_pct}}；RPS=(1-rank/total)*100，排名1=涨幅最高"""
    gains = {}
    for c in codes:
        rows = day.get(c, [])
        if len(rows) < max(n_list) + 1:
            continue
        gains[c] = {n: (rows[-1]["close"] / rows[-1 - n]["close"] - 1) for n in n_list}
    rps = {c: {} for c in gains}
    for n in n_list:
        order = sorted(gains, key=lambda c: gains[c][n], reverse=True)
        tot = len(order)
        for i, c in enumerate(order):
            rps[c][n] = (1 - i / tot) * 100 if tot > 1 else 50.0
    return rps


# ============================================================
#  股票池
# ============================================================
def read_universe(path):
    """读主板清单 csv(code,name) → {fullcode: name}（主板+非ST）"""
    out = {}
    for ln in open(path, encoding="utf-8", errors="ignore"):
        ln = ln.strip()
        if not ln or ln.lower().startswith("code"):
            continue
        parts = ln.split(",")
        c6 = parts[0].strip()
        nm = parts[1].strip() if len(parts) > 1 else ""
        if not (c6.isdigit() and len(c6) == 6):
            continue
        full = ("sh" if c6[0] in "69" else "sz") + c6
        if not is_mainboard(full) or is_st_name(nm):
            continue
        out[full] = nm
    return out


# ============================================================
#  主流程
# ============================================================
def scan(codes_names, args):
    codes = list(codes_names.keys())
    print(f"[西湖-RSV] 扫描 {len(codes)} 只 | 基准 {BENCH} | 周期 {N_LIST} | workers {args.workers}")
    day = fetch(codes + [BENCH], "day", max(args.limit, 300), workers=args.workers)
    idx = day.get(BENCH, [])
    if not idx:
        print("[ERR] 基准指数数据缺失，终止"); sys.exit(1)
    idx_map = {r["date"]: r["close"] for r in idx}
    print(f"  基准 {len(idx)} 根 | 个股返回 {len([c for c in codes if c in day])}/{len(codes)}")

    rps_map = None
    if getattr(args, "rsv2_mode", "rel") == "cross":
        rps_map = compute_cross_rps(day, codes, N_LIST)
        print(f"  RSV2 模式：横截面RPS（覆盖 {len(rps_map)} 只）")

    results = []
    for c in codes:
        rows = day.get(c, [])
        if len(rows) < 60:
            continue
        results.append(score_stock(c, rows, idx_map, codes_names.get(c, ""), rps_map))
    results.sort(key=lambda x: x["score"], reverse=True)

    top = results[:args.top]
    if args.weekly_top > 0 and top:
        wk = fetch([r["code"] for r in top], "week", 60, workers=args.workers)
        for r in top:
            g = weekly_gate(wk.get(r["code"], []))
            r["weekly_macd_bar"] = g["macd_bar"] if g else None
            r["weekly_gate"] = ("PASS" if g["pass"] else "BLOCK") if g else "NA"
    return results, top


def print_table(rows):
    print("\n" + "=" * 118)
    print(f"{'代码':<10}{'名称':<9}{'现价':>9}{'RSV50':>7}{'RSV144':>7}{'RSV250':>7}{'CRS':>6}{'结构':>6}{'Score':>7}  {'评级':<8}{'共振':<10}{'周线'}")
    print("-" * 118)
    for r in rows:
        print(f"{r['code']:<10}{(r['name'] or '')[:8]:<9}{r['close']:>9}{r['rsv50']:>7}{r['rsv144']:>7}{r['rsv250']:>7}"
              f"{r['crs']:>6}{r['structure']:>6}{r['score']:>7}  {r['rating']:<8}{r['resonance']:<10}{r['weekly_gate']}")
    print("=" * 118)


def build_report(top, total, args):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# 🏔️ 西湖-RSV 全市场扫描报告", "",
             f"**模型**：西湖-RSV 多周期相对强度（猛兽框架 × 西湖方法论）",
             f"**扫描时间**：{now}  |  **样本**：{total} 只（沪深主板，剔除ST）",
             f"**基准**：中证全指 sh000985  |  **周期**：50/144/250  |  **公式**：RSV(N)=(价格位置+相对基准位置)/2",
             "", "## 📊 TOP 榜单", "",
             "| # | 代码 | 名称 | 现价 | RSV50 | RSV144 | RSV250 | CRS | 结构 | **Score** | 评级 | 共振 | 周线 |",
             "|--:|--|--|--:|--:|--:|--:|--:|--:|--:|--|--|--|"]
    for i, r in enumerate(top, 1):
        lines.append(f"| {i} | {r['code']} | {r['name']} | {r['close']} | {r['rsv50']} | {r['rsv144']} | "
                     f"{r['rsv250']} | {r['crs']} | {r['structure']} | **{r['score']}** | {r['rating']} | {r['resonance']} | {r['weekly_gate']} |")
    # 分布
    from collections import Counter
    cnt = Counter(r["rating"] for r in top)
    res = Counter(r["resonance"] for r in top if r["resonance"] != "—")
    lines += ["", "## 📈 分布", "",
              "- 评级：" + " ".join(f"{k} {v}" for k, v in cnt.items()),
              "- 共振：" + (" ".join(f"{k} {v}" for k, v in res.items()) or "无"),
              "", "> 判据：强势股=C/HHV250>0.9；第二阶段=C>MA50>MA150>MA200 且距200低>30% 且距200高>75%；周线闸门=周线MACD柱≥0",
              f"> 生成：xihu_rsv.py v1.1"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stocks", default="", help="逗号分隔代码；留空=全市场")
    ap.add_argument("--universe-file", default="all_mainboard.csv", help="主板清单")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--weekly-top", type=int, default=50, help="对前N补周线闸门")
    ap.add_argument("--rsv2-mode", default="rel", choices=["rel", "cross"],
                    help="RSV2口径：rel=相对基准时序位置(默认) / cross=全市场横截面RPS排名")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--json", default="", help="结果 JSON 路径")
    ap.add_argument("--report", default="", help="Markdown 报告路径")
    args = ap.parse_args()

    if args.stocks.strip():
        pool = {norm(c): "" for c in args.stocks.split(",") if c.strip()}
    else:
        uni = Path(args.universe_file)
        if not uni.exists():
            print(f"[WARN] 未找到 {args.universe_file}，使用内置池"); pool = {c: "" for c in DEFAULT_POOL}
        else:
            pool = read_universe(uni)
            print(f"[池] {args.universe_file} → 主板非ST {len(pool)} 只")
    if not pool:
        print("[ERR] 股票池为空"); sys.exit(1)

    results, top = scan(pool, args)
    print_table(top if args.stocks.strip() else top)
    print(f"\n共评分 {len(results)} 只")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        json.dump({"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "bench": BENCH,
                   "periods": N_LIST, "total": len(results), "top": top}, open(args.json, "w"),
                  ensure_ascii=False, indent=2)
        print(f"[OK] JSON → {args.json}")
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        open(args.report, "w", encoding="utf-8").write(build_report(top, len(results), args))
        print(f"[OK] 报告 → {args.report}")


if __name__ == "__main__":
    main()
