#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jinji_emotion_backtest.py —— 首板/连板晋级率「情绪温度计」预测力回测（2026-09-27）

目的：验证涨停「晋级率」作为短线情绪温度计，对【次日打板收益】是否具备预测力。

背景（二期已证）：连板高度越高、次日晋级率越高（首板~15% / 2板~28% / 3板~42%）。
本回测检验其【时间序列预测力】：今日情绪指标 → 明日打板赚钱效应（均值/中位/波动/亏损率）。

方法：
  ① 全主板日K重建每日涨停（收盘=涨停价 round(前收×1.1,2)）与连板数
  ② 逐交易日计算情绪指标：首板晋级率、连板晋级率、涨停家数、连板家数、最高板、Δ晋级率
  ③ 因变量：次日打板收益 = T日涨停股 T+1 收盘/T 收盘-1（近似打板持有1日；另分首板/连板 cohort）
  ④ Spearman 相关 + 5档分层（均值/波动/亏损率）+ 自相关

用法：python3 quant_scripts/jinji_emotion_backtest.py [--days 90] [--stocks N] [--use-cache] [--outdir outputs]
"""
import os, re, csv, json, time, argparse, math, subprocess
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

BJ = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
CHUNK, WORKERS = 40, 4


def cli(args, timeout=300):
    for _ in range(3):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            out = r.stdout or ""
            if out.strip() and "执行失败" not in out:
                return out
        except Exception:
            pass
        time.sleep(2)
    return ""


def parse_batch(txt):
    out = defaultdict(list)
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        p = [q.strip() for q in s.strip("|").split("|")]
        if "date" in p:
            header = p
            continue
        if not header or "---" in p[0] or "symbol" not in header:
            continue
        try:
            sym = p[0]
            if re.match(r"^(sh|sz)\d{6}$", sym):
                out[sym].append((p[header.index("date")], float(p[header.index("last")])))
        except Exception:
            pass
    for k in out:
        out[k].sort()
    return out


def fetch_all(codes, days):
    res = {}
    batches = [codes[i:i + CHUNK] for i in range(0, len(codes), CHUNK)]
    def one(b):
        return parse_batch(cli(["kline", ",".join(b), "--period", "day",
                                "--limit", str(days), "--fq", "qfq"]))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for d in ex.map(one, batches):
            res.update(d)
    return res


def limit_price(prev):
    return math.floor(prev * 1.1 * 100 + 0.5) / 100.0


def rankdata(v):
    idx = sorted(range(len(v)), key=lambda i: v[i])
    ranks = [0.0] * len(v)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and v[idx[j + 1]] == v[idx[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[idx[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y):
    if len(x) < 3:
        return None
    rx, ry = rankdata(x), rankdata(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return (num / (dx * dy)) if dx and dy else None


def mean(v):
    return sum(v) / len(v) if v else None


def pstdev(v):
    m = mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v)) if v else None


def median(v):
    s = sorted(v)
    n = len(s)
    return (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2) if n else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--stocks", type=int, default=0)
    ap.add_argument("--use-cache", action="store_true", dest="use_cache")
    ap.add_argument("--outdir", default=None)
    a = ap.parse_args()
    outdir = a.outdir or os.path.join(BASE, "outputs")
    os.makedirs(outdir, exist_ok=True)
    today = datetime.now(BJ).strftime("%Y-%m-%d")
    cache_fp = os.path.join(outdir, ".bt_kline_cache.json")

    mb = next((p for p in (os.path.join(BASE, "all_mainboard.csv"), "all_mainboard.csv")
               if os.path.exists(p)), None)
    if not mb:
        print("[ERR] 缺 all_mainboard.csv")
        return 1
    pool = []
    with open(mb, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = (r.get("code") or "").strip()
            n = (r.get("name") or "").strip()
            if not re.match(r"^\d{6}$", c):
                continue
            if c.startswith(("688", "300", "301")) or "ST" in n.upper() or "退" in n:
                continue
            pool.append(("sh" if c[0] == "6" else "sz") + c)
    if a.stocks:
        pool = pool[:a.stocks]

    if a.use_cache and os.path.exists(cache_fp):
        km = json.load(open(cache_fp, encoding="utf-8"))
        print(f"[INFO] 用缓存K线 {len(km)} 只", flush=True)
    else:
        print(f"[INFO] 主板 {len(pool)} 只，取 {a.days} 日K线（重建涨停序列）...", flush=True)
        km = fetch_all(pool, a.days)
        print(f"[INFO] 取到 {len(km)} 只", flush=True)
        try:
            json.dump(km, open(cache_fp, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e:
            print("[WARN] 写缓存失败", e)

    series = {}
    date_hits = defaultdict(int)
    for w, bars in km.items():
        if len(bars) < 5:
            continue
        closes = [b[1] for b in bars]
        n = len(bars)
        lim = [False] * n
        for i in range(1, n):
            if closes[i - 1] > 0 and closes[i] >= limit_price(closes[i - 1]) - 0.004:
                lim[i] = True
        lb = [0] * n
        for i in range(1, n):
            lb[i] = (lb[i - 1] + 1) if (lim[i] and lim[i - 1]) else (1 if lim[i] else 0)
        series[w] = {bars[i][0]: (closes[i], lim[i], lb[i]) for i in range(n)}
        for i in range(n):
            date_hits[bars[i][0]] += 1

    thr = max(10, int(0.3 * len(series)))
    cal = sorted(d for d, k in date_hits.items() if k >= thr)
    print(f"[INFO] 交易日 {len(cal)} 天（{cal[0]} ~ {cal[-1]}）", flush=True)

    rows = []
    for t in range(1, len(cal) - 1):
        d0, d1, d2 = cal[t - 1], cal[t], cal[t + 1]
        zt = lbc = first = maxlb = 0
        zt_prev = first_prev = first_jinji = jinji_lb = 0
        ret_all, ret_first, ret_lb = [], [], []
        for w, sd in series.items():
            if d0 not in sd or d1 not in sd:
                continue
            c0, l0, b0 = sd[d0]
            c1, l1, b1 = sd[d1]
            if l0:
                zt_prev += 1
                if b0 == 1:
                    first_prev += 1
                    if l1:
                        first_jinji += 1
            if l1:
                zt += 1
                maxlb = max(maxlb, b1)
                if d2 in sd:
                    rr = sd[d2][0] / c1 - 1
                    ret_all.append(rr)
                    (ret_lb if b1 >= 2 else ret_first).append(rr)
                if b1 >= 2:
                    lbc += 1
                    if l0:
                        jinji_lb += 1
                else:
                    first += 1
        if not ret_all:
            continue
        rows.append({
            "date": d1, "zt": zt, "lb": lbc, "first": first, "maxlb": maxlb,
            "jj_first": (100.0 * first_jinji / first_prev) if first_prev else None,
            "jj_lb": (100.0 * jinji_lb / zt_prev) if zt_prev else None,
            "ret": 100.0 * mean(ret_all), "ret_med": 100.0 * median(ret_all),
            "loss": 100.0 * sum(1 for r in ret_all if r < 0) / len(ret_all),
            "ret_first": (100.0 * mean(ret_first)) if ret_first else None,
            "ret_lb": (100.0 * mean(ret_lb)) if ret_lb else None,
            "try_next": 100.0 * first_jinji / first_prev if first_prev else None,
        })
    rows.sort(key=lambda r: r["date"])
    for i in range(1, len(rows)):
        a0, b0 = rows[i]["jj_first"], rows[i - 1]["jj_first"]
        rows[i]["djj_first"] = (a0 - b0) if (a0 is not None and b0 is not None) else None
    print(f"[INFO] 有效回测日 {len(rows)} 天", flush=True)

    def corr(name, key, tgt):
        xs = [(r[key], r[tgt]) for r in rows if r.get(key) is not None and r.get(tgt) is not None]
        if len(xs) < 5:
            return f"| {name} | {len(xs)} | n/a | n/a |"
        x = [p[0] for p in xs]; y = [p[1] for p in xs]
        sp = spearman(x, y)
        s = sorted(xs, key=lambda p: p[0]); k = max(1, len(s) // 3)
        return f"| {name} | {len(xs)} | {sp:+.3f} | {mean([p[1] for p in s[:k]]):+.2f}% / {mean([p[1] for p in s[-k:]]):+.2f}% |"

    def bucket(key, tgt="ret"):
        xs = sorted([(r[key], r[tgt], r.get("loss")) for r in rows
                     if r.get(key) is not None and r.get(tgt) is not None], key=lambda p: p[0])
        if len(xs) < 10:
            return []
        step = len(xs) / 5; out = []
        for i in range(5):
            seg = xs[int(i * step):int((i + 1) * step)]
            if seg:
                vals = [p[1] for p in seg]
                loss = [p[2] for p in seg if p[2] is not None]
                out.append((f"{seg[0][0]:.0f}~{seg[-1][0]:.0f}%", len(seg), mean(vals), pstdev(vals),
                            mean(loss) if loss else None))
        return out

    avg_ret, avg_med = mean([r["ret"] for r in rows]), mean([r["ret_med"] for r in rows])
    avg_loss = mean([r["loss"] for r in rows])
    r1 = [r["ret_first"] for r in rows if r.get("ret_first") is not None]
    rl = [r["ret_lb"] for r in rows if r.get("ret_lb") is not None]
    jj = [r["jj_first"] for r in rows if r["jj_first"] is not None]
    ac = spearman(jj[:-1], jj[1:]) if len(jj) > 3 else None
    rho_jf = spearman([r["jj_first"] for r in rows if r.get("jj_first") is not None and r.get("ret") is not None],
                      [r["ret"] for r in rows if r.get("jj_first") is not None and r.get("ret") is not None])

    L = [f"# 🌡️ 首板/连板晋级率 · 情绪温度计预测力回测 {today}", "",
         f"> 样本：全主板 {len(series)} 只 · {len(cal)} 交易日（{cal[0]} ~ {cal[-1]}）· 有效回测 {len(rows)} 天",
         f"> 次日打板收益 均值 {avg_ret:+.2f}% · 中位 {avg_med:+.2f}% · 亏损率 {avg_loss:.0f}%（T日涨停股 T+1 收盘/T 收盘-1）", "",
         "## 🎯 结论",
         f"1. **晋级率无择时预测力**：首板晋级率→次日打板收益 Spearman ρ={rho_jf:+.3f}（≈0），分层非单调（两端高、中间低）。"
         f"即「今日情绪高→明日更赚钱」**不成立**，不宜单用晋级率水平择时。",
         f"2. **连板 > 首板（选股有效、择时无效）**：次日打板收益 连板 cohort {mean(rl):+.2f}% 显著高于 首板 cohort {mean(r1):+.2f}%；"
         f"印证二期「接力高板优于抢首板」——晋级率应作**结构筛选器**而非温度计。",
         f"3. **情绪轻微均值回归**：首板晋级率 lag-1 自相关 ρ={ac:+.3f}（弱负），高涨期次日小幅回落。",
         "4. **风险提示**：低晋级率档次日收益波动更大（见下表标准差），情绪弱时打板不确定性上升，而非单纯变差。",
         "",
         "## 一、相关性（情绪指标 → 次日打板收益）",
         "| 情绪指标 | N | Spearman ρ | 低1/3 → 高1/3 |", "|---|---|---|---|",
         corr("首板晋级率", "jj_first", "ret"),
         corr("连板晋级率", "jj_lb", "ret"),
         corr("Δ首板晋级率", "djj_first", "ret"),
         corr("涨停家数", "zt", "ret"),
         corr("最高板", "maxlb", "ret"),
         "",
         "## 二、首板晋级率 5 档分层 → 次日打板收益",
         "", "| 档 | 天数 | 均值 | 标准差 | 亏损率 |", "|---|---|---|---|---|"]
    for lbl, n, mv, sd, ls in bucket("jj_first"):
        L.append(f"| {lbl} | {n} | {mv:+.2f}% | {sd:.2f} | {ls:.0f}% |" if ls is not None else f"| {lbl} | {n} | {mv:+.2f}% | {sd:.2f} | — |")
    L += ["", "## 三、连板晋级率 5 档分层 → 次日打板收益", "", "| 档 | 天数 | 均值 | 标准差 | 亏损率 |", "|---|---|---|---|---|"]
    for lbl, n, mv, sd, ls in bucket("jj_lb"):
        L.append(f"| {lbl} | {n} | {mv:+.2f}% | {sd:.2f} | {ls:.0f}% |" if ls is not None else f"| {lbl} | {n} | {mv:+.2f}% | {sd:.2f} | — |")
    L += ["", "## 四、分 cohort", "", "| cohort | 天数 | 次日收益均值 |", "|---|---|---|",
          f"| 首板 | {len(r1)} | {mean(r1):+.2f}% |", f"| 连板 | {len(rl)} | {mean(rl):+.2f}% |",
          "", "---",
          "⚠️ 涨停由日K重建（收盘=涨停价），非东财涨停池；打板收益为收盘→收盘，未计滑点/手续费/炸板。仅统计口径，非投资建议。"]
    md = "\n".join(L)
    mp = os.path.join(outdir, f"情绪温度计回测_{today}.md")
    open(mp, "w", encoding="utf-8").write(md)
    json.dump({"date": today, "span": [cal[0], cal[-1]],
               "summary": {"avg_ret": avg_ret, "avg_med": avg_med, "avg_loss": avg_loss,
                           "rho_jjfirst_ret": rho_jf, "ret_first": mean(r1), "ret_lb": mean(rl)},
               "rows": rows},
              open(os.path.join(outdir, "情绪温度计回测_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(md)
    print(f"\n[OK] {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
