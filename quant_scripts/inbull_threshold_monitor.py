#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inbull_threshold_monitor.py —— 入牛广度阈值「季度漂移监控」

用途：每季度用最新全历史月线重算「入牛个股占比」与「大盘牛」的关系，
      与 2026-10-09 建立的基线对比，检测阈值是否漂移。

口径（与基线一致）：
    大盘指数 = 全市场月度等权收益累乘；大盘牛 = 该指数 MA5/10/20/30 ↑ + DIF↑
    入牛个股 = 自身 5 根月线全向上；占比 = 入牛个股 / 有效样本（上市满 30 月）
    数据源：同花顺 v6 后复权月线（hs_{code}/02/all.js），失败自动回退 westock

输出：
    outputs/入牛阈值漂移_{YYYY}Q{q}.md
    outputs/入牛阈值漂移_latest.json

用法：
    python3 quant_scripts/inbull_threshold_monitor.py --source ths --workers 12
    python3 quant_scripts/inbull_threshold_monitor.py --sample 120     # 冒烟
"""
import os, re, sys, json, time, argparse, subprocess
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs")
os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# ── 基线（2026-10-09 建立：1996-01~2026-10，主板 3040 只，同花顺后复权）──
BASELINE = {
    "established": "2026-10-09",
    "window": "1996-01 ~ 2026-10",
    "stocks": 3040,
    "bull_months": 128, "nonbull_months": 242,
    "bull_median": 39.1, "nonbull_median": 7.8,
    "best_lo": 19, "best_hi": 21, "best_f1": 0.85,
    "t25_precision": 0.88, "t15_precision": 0.68,
}


# ── 池 ──
def load_universe():
    codes = []
    fp = os.path.join(ROOT, "all_mainboard.csv")
    with open(fp, encoding="utf-8-sig") as f:
        for ln in f:
            p = ln.strip().split(",")
            if len(p) >= 2 and re.match(r"^\d{6}$", p[0].strip()):
                c = p[0].strip()
                if c.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
                    up = p[1].upper().replace(" ", "")
                    if ("ST" in up) or ("PT" in up) or ("退" in p[1]):
                        continue
                    codes.append(("sh" if c.startswith("6") else "sz") + c)
    return codes


# ── 同花顺全历史月线 ──
def curl(url, retries=4):
    for i in range(retries):
        try:
            r = subprocess.run(["curl", "-s", "--max-time", "40", "-A", UA, url],
                               capture_output=True, text=True)
            t = (r.stdout or "").strip()
            if t and "quotebridge" in t:
                return t
        except Exception:
            pass
        time.sleep(0.6 + 0.9 * i)
    return ""


def parse_monthly(txt):
    m = re.search(r"\((\{.*\})\)\s*;?\s*$", txt, re.S)
    if not m:
        return []
    j = json.loads(m.group(1))
    pf = float(j.get("priceFactor", 100) or 100)
    p = [float(x) / pf for x in j["price"].split(",") if x != ""]
    dates = [x for x in j["dates"].split(",") if x]
    sy = j.get("sortYear", [])
    n = min(len(p) // 4, len(dates))
    full, yi, cnt = [], 0, 0
    for k in range(n):
        while yi < len(sy) and cnt >= int(sy[yi][1]):
            yi += 1; cnt = 0
        if yi >= len(sy):
            break
        full.append(f"{int(sy[yi][0])}{dates[k]}"); cnt += 1
    monthly = {}
    for k in range(min(n, len(full))):
        lo = p[4 * k]; o = lo + p[4 * k + 1]; h = lo + p[4 * k + 2]; c = lo + p[4 * k + 3]
        ym = f"{full[k][:4]}-{full[k][4:6]}"
        if ym not in monthly:
            monthly[ym] = [o, h, lo, c]
        else:
            mm = monthly[ym]; mm[1] = max(mm[1], h); mm[2] = min(mm[2], lo); mm[3] = c
    return [(ym, v[0], v[1], v[2], v[3]) for ym, v in sorted(monthly.items())]


def fetch_ths(codes, workers=12):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    rows, ok = [], 0
    t0 = time.time()

    def one(sym):
        return sym, parse_monthly(curl(f"http://d.10jqka.com.cn/v6/line/hs_{sym[2:]}/02/all.js"))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, s): s for s in codes}
        for i, fu in enumerate(as_completed(futs), 1):
            sym, res = fu.result()
            if res:
                ok += 1
                for ym, o, h, lo, c in res:
                    rows.append((sym, ym, c))
            if i % 500 == 0:
                print(f"  ths {i}/{len(codes)} ok={ok} {time.time()-t0:.0f}s", flush=True)
    print(f"[ths] 覆盖 {ok}/{len(codes)} 用时 {time.time()-t0:.0f}s", flush=True)
    return rows, ok


def fetch_westock(codes, batch=250):
    """回退：westock 月线（仅约 61 个月）"""
    import shutil
    w = shutil.which("westock-data-skillhub")
    W = [w] if w else ["npx", "-y", "westock-data-skillhub@1.0.3"]
    rows = []
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        try:
            r = subprocess.run(W + ["kline", ",".join(chunk), "--period", "month", "--limit", "61"],
                               capture_output=True, text=True, timeout=240)
            txt = r.stdout or ""
        except Exception:
            txt = ""
        hdr, data = None, {}
        for ln in txt.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            parts = [x.strip() for x in s.strip("|").split("|")]
            if "date" in parts and "symbol" in parts:
                hdr = parts; continue
            if not hdr or not parts or set(parts[0]) <= set("-"):
                continue
            try:
                sym, dt = parts[0], parts[1]
                ci = hdr.index("last")
                if re.match(r"^(sh|sz)\d{6}$", sym) and re.match(r"^\d{4}-\d{2}-\d{2}$", dt):
                    c = float(parts[ci])
                    if c > 0:
                        data.setdefault(sym, []).append((dt[:7], c))
            except (ValueError, IndexError):
                pass
        for c, lst in data.items():
            for ym, cl in lst:
                rows.append((c, ym, cl))
        print(f"  westock batch {i//batch+1}/{(len(codes)+batch-1)//batch} rows={len(rows)}", flush=True)
    return rows


# ── 计算 ──
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def gg_frame(C):
    ma5, ma10, ma20, ma30 = [C.rolling(k).mean() for k in (5, 10, 20, 30)]
    dif = ema(C, 10) - ema(C, 22)
    bull = ((ma5 > ma5.shift(1)) & (ma10 > ma10.shift(1)) & (ma20 > ma20.shift(1)) &
            (ma30 > ma30.shift(1)) & (dif > dif.shift(1))).fillna(False)
    return bull, ma30


def analyze(rows, since="1996-01"):
    import pandas as pd
    df = pd.DataFrame(rows, columns=["code", "ym", "close"]).dropna()
    df = df[df["close"] > 0]
    C = df.pivot_table(index="ym", columns="code", values="close", aggfunc="last").sort_index()
    ret = C.pct_change(fill_method=None)
    mret = ret.mean(axis=1)
    mret.iloc[0] = 0.0
    mkt = (1 + mret.fillna(0)).cumprod()
    mbull = gg_frame(mkt.to_frame("m"))[0]["m"]
    sbull, ma30 = gg_frame(C)
    valid = ma30.notna() & C.notna()
    T = pd.DataFrame({
        "n_valid": valid.sum(axis=1),
        "n_bull": (sbull & valid).sum(axis=1),
    })
    T["ratio"] = (T["n_bull"] / T["n_valid"].replace(0, float("nan")) * 100)
    T["mkt_bull"] = mbull
    T = T[T.index >= since]
    return T, C.shape[1], C.index[0], C.index[-1]


def threshold_table(T):
    y = T["mkt_bull"].astype(int)
    x = T["ratio"]
    m = x.notna()
    y, x = y[m], x[m]
    nb = int(y.sum())
    out, best = [], None
    for t in range(3, 41, 2):
        pred = (x >= t).astype(int)
        tp = int(((pred == 1) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / nb if nb else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out.append((t, tp + fp, round(prec, 3), round(rec, 3), round(f1, 3)))
        if best is None or f1 > best[4]:
            best = out[-1]
    return out, best


def pushplus(tok, title, md):
    if not tok:
        print("[SKIP] 无 PUSH_TOKEN"); return
    import urllib.request
    body = json.dumps({"token": tok, "title": title, "content": md, "template": "markdown"}).encode()
    req = urllib.request.Request("https://www.pushplus.plus/send", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        print("推送:", urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace"))
    except Exception as e:
        print("[WARN] 推送失败", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="ths", choices=["ths", "westock", "auto"])
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--since", default="1996-01")
    a = ap.parse_args()

    codes = load_universe()
    if a.sample:
        codes = codes[:a.sample]
    print(f"[阈值监控] universe={len(codes)} source={a.source}", flush=True)

    rows, src = [], a.source
    if a.source in ("ths", "auto"):
        rows, ok = fetch_ths(codes, a.workers)
        if len(rows) < 100 or ok < len(codes) * 0.3:
            if a.source == "ths":
                print("[WARN] 同花顺覆盖不足，自动回退 westock", flush=True)
            rows = fetch_westock(codes); src = "westock"
    else:
        rows = fetch_westock(codes)
    if not rows:
        print("[ERR] 无数据"); sys.exit(1)

    T, ncol, d0, d1 = analyze(rows, a.since)
    bull = T[T["mkt_bull"]]["ratio"].dropna()
    bear = T[~T["mkt_bull"]]["ratio"].dropna()
    tbl, best = threshold_table(T)
    t25 = next((r for r in tbl if r[0] == 25), None)
    t15 = next((r for r in tbl if r[0] == 15), None)

    cur = {
        "bull_months": int(len(bull)), "nonbull_months": int(len(bear)),
        "bull_median": round(float(bull.median()), 1) if len(bull) else None,
        "nonbull_median": round(float(bear.median()), 1) if len(bear) else None,
        "best_lo": best[0], "best_f1": best[4],
        "t25_precision": t25[2] if t25 else None,
        "t15_precision": t15[2] if t15 else None,
    }

    # ── 漂移判定 ──
    drift = []
    if abs(cur["best_lo"] - BASELINE["best_lo"]) >= 3:
        drift.append(f"最优阈值 {BASELINE['best_lo']}% → {cur['best_lo']}%（偏移≥3pp）")
    if cur["t25_precision"] is not None and cur["t25_precision"] < 0.80:
        drift.append(f"25% 档精确率 {BASELINE['t25_precision']} → {cur['t25_precision']}（<0.80）")
    if cur["bull_median"] and abs(cur["bull_median"] - BASELINE["bull_median"]) > 5:
        drift.append(f"牛市月中位 {BASELINE['bull_median']}% → {cur['bull_median']}%（偏移>5pp）")

    now = datetime.now()
    q = (now.month - 1) // 3 + 1
    period = f"{now.year}Q{q}"
    res = {"period": period, "run_date": now.strftime("%Y-%m-%d"),
           "source": src, "window": f"{d0} ~ {d1}", "stocks": ncol,
           "baseline": BASELINE, "current": cur, "drift": drift,
           "threshold_table": [{"t": r[0], "n": r[1], "prec": r[2], "rec": r[3], "f1": r[4]} for r in tbl]}
    json.dump(res, open(os.path.join(OUT, "入牛阈值漂移_latest.json"), "w"), ensure_ascii=False, indent=1)

    L = [f"# 入牛广度阈值 · 季度漂移监控 {period}", "",
         f"- 运行日: {now.strftime('%Y-%m-%d')} ｜ 数据源: **{src}** ｜ 窗口: {d0} ~ {d1} ｜ 样本: {ncol} 只",
         f"- 基线: {BASELINE['established']}（{BASELINE['window']}，{BASELINE['stocks']} 只）", "",
         "## 一、基线 vs 本期", "",
         "| 指标 | 基线 | 本期 | Δ |", "|---|---|---|---|",
         f"| 大盘牛月数 | {BASELINE['bull_months']} | {cur['bull_months']} | {cur['bull_months']-BASELINE['bull_months']:+d} |",
         f"| 大盘非牛月数 | {BASELINE['nonbull_months']} | {cur['nonbull_months']} | {cur['nonbull_months']-BASELINE['nonbull_months']:+d} |",
         f"| 牛市月占比中位 | {BASELINE['bull_median']}% | {cur['bull_median']}% | {(cur['bull_median']-BASELINE['bull_median']):+.1f}pp |",
         f"| 非牛月占比中位 | {BASELINE['nonbull_median']}% | {cur['nonbull_median']}% | {(cur['nonbull_median']-BASELINE['nonbull_median']):+.1f}pp |",
         f"| 最优单阈值 | {BASELINE['best_lo']}~{BASELINE['best_hi']}% | {cur['best_lo']}% | — |",
         f"| 25% 档精确率 | {BASELINE['t25_precision']} | {cur['t25_precision']} | — |",
         f"| 15% 档精确率 | {BASELINE['t15_precision']} | {cur['t15_precision']} | — |", ""]
    if drift:
        L += ["## ⚠️ 漂移告警", ""] + [f"- {d}" for d in drift] + [""]
        L += ["→ **建议**：复核三档阈值（15/25/10）是否需调整，并更新技能与知识库口径文档。", ""]
    else:
        L += ["## ✅ 无漂移", "", "各项指标与基线一致（在容差内），三档阈值维持 15/25/10。", ""]
    L += ["## 二、本期阈值校准表", "", "| 阈值% | 命中 | 精确率 | 召回率 | F1 |", "|---|---|---|---|---|"]
    L += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in tbl]
    L += ["", f"> 最优单阈值 = {best[0]}%（F1={best[4]}）"]
    open(os.path.join(OUT, f"入牛阈值漂移_{period}.md"), "w", encoding="utf-8").write("\n".join(L))

    title = (f"⚠️ 入牛阈值漂移 {period}" if drift else f"入牛阈值监控 {period}")
    P = [f"## 📐 入牛阈值监控 · {period}", "",
         f"- 窗口 {d0}~{d1}，样本 {ncol} 只（{src}）",
         f"- 牛市月 {cur['bull_months']} / 非牛月 {cur['nonbull_months']}",
         f"- 占比中位：牛 {cur['bull_median']}% / 非牛 {cur['nonbull_median']}%",
         f"- 最优单阈值 {cur['best_lo']}%；25%档精确率 {cur['t25_precision']}"]
    if drift:
        P += ["", "### ⚠️ 漂移告警"] + [f"- {d}" for d in drift]
    else:
        P += ["", "✅ 无漂移，三档阈值 15/25/10 维持"]
    pushplus(os.environ.get("PUSH_TOKEN", ""), title, "\n".join(P))

    print(f"[OK] {period} {src} 牛月={cur['bull_months']} 非牛月={cur['nonbull_months']} "
          f"最优阈值={cur['best_lo']}% 漂移={len(drift)}", flush=True)


if __name__ == "__main__":
    main()
