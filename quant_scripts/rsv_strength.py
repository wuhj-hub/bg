#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rsv_strength.py —— RSV均相对强度系统（《腰缠万贯0825》融合）
============================================================
指标定义（通达信公式程序化）：
  RSV1 = (C-LLV(L,144))/(HHV(H,144)-LLV(L,144))*100      # 价格位置
  RS   = C / 基准指数收盘（sz399106 深证综指，替代880003平均股价）
  RSV2 = (RS-LLV(RS,144))/(HHV(RS,144)-LLV(RS,144))*100  # 相对强度位置
  RSV均 = (RSV1+RSV2)/2

用法（笔记提炼）：
  日线：RSV均<20拐头向上 = 半年级别启动（买点）；>80拐头向下 = 卖点
  周线：突破50 = 3年级别大行情；70-90 持有；破70 = 离场
  月线估波信号(月牛3)：ROC14+ROC11 的 WMA10>0

输出：outputs/rsv_strength_latest.json + 启动/持有/离场信号

性能优化（2026-08-27）：
  原实现逐只 3 次 npx 调用（日/周/月线）→ 4000只×3=12000次进程启动，耗时1h42m
  现改为 westock 批量 kline（逗号分隔代码，100只/批）→ 3周期×40批=120次调用，
  8线程并发约 1-2 分钟。计算逻辑与信号判定完全不变。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
BENCH = "sz399106"   # 基准指数（深证综指，替代880003）
N = 144
BATCH = 100          # 批量kline每批股票数


def cli(args, timeout=120):
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


def parse_kline(txt):
    """解析单股K线（升序），返回 [{high, low, close}, ...]"""
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
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                continue
            row = {"date": parts[di]}
            for key, hk in (("high", "high"), ("low", "low"), ("close", "last")):
                if hk in header:
                    row[key] = float(parts[header.index(hk)])
            rows.append(row)
        except (ValueError, IndexError):
            pass
    rows.sort(key=lambda r: r["date"])
    return rows


def parse_batch_kline(txt):
    """解析批量kline输出：{full_code: [升序 {date,high,low,close}, ...]}
    ⚠️ 批量列序: symbol|date|open|last|high|low|volume|amount|exchange，date降序（最新在前）"""
    out, cur = {}, None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 6 or parts[0] == "symbol" or "---" in parts[0]:
            continue
        if re.match(r"^(sh|sz|bj)\d{6}$", parts[0]):
            cur = parts[0]
            try:
                out.setdefault(cur, []).append({"date": parts[1],
                                                "high": float(parts[4]),
                                                "low": float(parts[5]),
                                                "close": float(parts[3])})
            except (ValueError, IndexError):
                pass
    for c in out:
        out[c].sort(key=lambda r: r["date"])  # 降序→升序
    return out


def fetch_batch(codes, period, limit, fq=True, retries=3):
    """批量拉K线，{full_code: rows升序}。失败批次重试。"""
    codes = [norm(c) for c in codes]
    joined = ",".join(codes)
    args = ["kline", joined, "--period", period, "--limit", str(limit)]
    if fq:
        args += ["--fq", "qfq"]
    for i in range(retries):
        txt = cli(args)
        if txt:
            data = parse_batch_kline(txt)
            # 校验：返回的代码数≥请求的80%才接受，否则重试
            got = set(data.keys())
            want = set(codes)
            if len(got) >= max(1, int(len(want) * 0.8)):
                return data
        time.sleep(2 * (i + 1))
    return {}


def rsv_of(rows, field="close"):
    """RSV 计算：最后值 + 拐头方向（rows: dict列表 或 数值列表）"""
    if rows and isinstance(rows[0], dict):
        vals = [r[field] for r in rows]
    else:
        vals = list(rows)
    if len(vals) < N + 1:
        return None, None
    cur = vals[-1]
    window = vals[-N:]
    hhv = max(window)
    llv = min(window)
    if hhv == llv:
        rsv = 50.0
    else:
        rsv = (cur - llv) / (hhv - llv) * 100
    # 拐头：RSV 与 3 日前比较
    prev3 = None
    if len(vals) >= N + 4:
        w2 = vals[-(N + 3):-3]
        h2, l2 = max(w2), min(w2)
        prev3 = (vals[-4] - l2) / (h2 - l2) * 100 if h2 != l2 else 50.0
    turn_up = prev3 is not None and rsv > prev3
    turn_dn = prev3 is not None and rsv < prev3
    return round(rsv, 1), {"up": turn_up, "down": turn_dn, "prev": prev3}


def calc_estimator(month_rows):
    """月线估波信号（月牛3）：ROC14+ROC11 的 WMA10 > 0"""
    closes = [r["close"] for r in month_rows]
    if len(closes) < 25:
        return None
    roc = []
    for i in range(14, len(closes)):
        c14 = closes[i - 14]
        c11 = closes[i - 11]
        r14 = (closes[i] - c14) / c14 * 100 if c14 else 0
        r11 = (closes[i] - c11) / c11 * 100 if c11 else 0
        roc.append(r14 + r11)
    wma = []
    for i in range(len(roc)):
        w = roc[max(0, i - 9):i + 1]
        weights = list(range(1, len(w) + 1))
        wma.append(sum(x * wgt for x, wgt in zip(w, weights)) / sum(weights))
    return wma[-1] > 0 if wma else None


def analyze(code, name="", day_rows=None, week_rows=None, month_rows=None, bench_rows=None, bench_week_rows=None):
    """单只分析（纯本地计算，无网络调用）：日线RSV + 周线RSV + 月线估波 + RSG强势标注"""
    try:
        if not day_rows or len(day_rows) < N + 10:
            return None
        # 日线 RSV1 + RSV2
        rsv1, d1 = rsv_of(day_rows, "close")
        if not bench_rows or len(bench_rows) < N + 10:
            return None
        # RS = 个股收盘/基准收盘（按日期对齐，取最近N+1根）
        bmap = {r["date"]: r["close"] for r in bench_rows}
        rs_list = []
        for r in day_rows[-N - 1:]:
            if r["date"] in bmap and bmap[r["date"]] > 0:
                rs_list.append(r["close"] / bmap[r["date"]])
        if len(rs_list) < N + 1:
            return None
        rsv2, d2 = rsv_of(rs_list, "close")
        rsv_avg = round((rsv1 + rsv2) / 2, 1)
        # 周线 RSV（144周）
        wrsv, wdir = None, None
        if week_rows and len(week_rows) >= N + 5:
            wrsv, wdir = rsv_of(week_rows, "close")
        # RSG 强势标注（2026-08-27：RS相对52周均线偏离，>50‰=偏离>5%强势侧过滤）
        rsg_dev, rsg_strong = None, False
        if bench_week_rows and week_rows and len(week_rows) >= 60:
            bmap_w = {r["date"]: r["close"] for r in bench_week_rows}
            w_rs = []
            for r in week_rows:
                if r["date"] in bmap_w and bmap_w[r["date"]] > 0:
                    w_rs.append(r["close"] / bmap_w[r["date"]])
            if len(w_rs) >= 53:
                rss52 = sum(w_rs[-52:]) / 52
                if rss52 > 0:
                    rsg_dev = round((w_rs[-1] / rss52 - 1) * 1000, 1)
                    rsg_strong = rsg_dev > 50
        # 月线估波
        est = calc_estimator(month_rows) if month_rows and len(month_rows) >= 25 else None
        close = day_rows[-1]["close"]

        # 信号判定
        sigs = []
        # 日线启动：RSV<20 且拐头向上
        if rsv_avg < 20 and d1 and d1["up"]:
            sigs.append({"type": "日线启动", "desc": f"RSV均{rsv_avg}<20拐头向上（半年级别）"})
        # 半启动：RSV<40 拐头向上 + 当日涨幅≥9%（涨停确认，2026-08-26金健米业案例补充）
        if 20 <= rsv_avg < 40 and d1 and d1["up"] and len(day_rows) >= 2:
            prev_close = day_rows[-2]["close"]
            day_chg = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0
            if day_chg >= 9:
                sigs.append({"type": "半启动", "desc": f"RSV均{rsv_avg}<40拐头+涨停{day_chg:.0f}%（启动确认）"})
        # 日线卖点：RSV>80 且拐头向下
        if rsv_avg > 80 and d1 and d1["down"]:
            sigs.append({"type": "日线卖点", "desc": f"RSV均{rsv_avg}>80拐头向下"})
        # 周线突破50（穿越：前值≤50 → 当前>50）
        if wrsv is not None and wrsv > 50 and wdir and wdir["prev"] is not None and wdir["prev"] <= 50:
            sigs.append({"type": "周线突破50", "desc": f"周RSV{wrsv}突破50（3年级别）"})
        # 周线破70（穿越：前值≥70 → 当前<70，离场）
        if wrsv is not None and wrsv < 70 and wdir and wdir["prev"] is not None and wdir["prev"] >= 70:
            sigs.append({"type": "周线破70", "desc": f"周RSV{wrsv}跌破70（离场）"})
        # 月线估波转正
        if est is True:
            sigs.append({"type": "月线估波正", "desc": "估波信号>0（月牛3确认）"})

        state = "持有" if (wrsv is not None and 70 <= wrsv <= 90) else \
                "启动" if any(s["type"] in ("日线启动", "半启动", "周线突破50") for s in sigs) else \
                "离场" if any(s["type"] in ("日线卖点", "周线破70") for s in sigs) else "观察"
        return {
            "code": code, "name": name, "close": round(close, 2),
            "rsv_day": rsv_avg, "rsv_week": wrsv,
            "estimator": est, "state": state, "signals": sigs,
            "rsg_dev": rsg_dev, "rsg_strong": rsg_strong,
        }
    except Exception as e:
        return {"code": code, "name": name, "error": str(e)[:60]}


def load_pool(args):
    pool = []
    p = args.pool
    if not p:
        p = "quant_scripts/stock_pool.txt"
        if not os.path.exists(p):
            p = "stock_pool.txt"
    if "," in p and not os.path.exists(p):
        for c in p.split(","):
            if c.strip():
                pool.append((norm(c.strip()), ""))
        return pool
    if not os.path.exists(p):
        print(f"[ERR] 池文件不存在: {p}", file=sys.stderr)
        sys.exit(1)
    if p.endswith(".csv"):
        import csv
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                code = (row.get("code") or "").strip()
                name = (row.get("name") or "").strip()
                if code and "ST" not in name.upper() and "退" not in name:
                    pool.append((norm(code), name))
    else:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                code = ln.replace("#", ",").split(",")[0].strip()
                name = ln.split("#")[-1].strip() if "#" in ln else ""
                if code:
                    pool.append((norm(code), name))
    return pool


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="", help="池文件或代码列表")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--outdir", default="outputs")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    pool = load_pool(args)
    if args.limit:
        pool = pool[:args.limit]
    print(f"[INFO] RSV强度扫描: {len(pool)} 只（批量kline模式，workers={args.workers}）", file=sys.stderr)

    # ST/退市 批量校验（一次批量请求，避免逐只查询）
    st_set = set()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from st_guard import check_st_batch
        st_set, _ = check_st_batch([c for c, _ in pool])
        st_set = {("sh" if c.startswith(("6", "9", "5")) else "sz") + c for c in st_set}
    except Exception:
        pass
    pool = [(c, n) for c, n in pool if c not in st_set]
    print(f"[INFO] ST过滤后: {len(pool)} 只", file=sys.stderr)

    # 基准指数日线（一次拉取，全池共用；westock单股偶发返回空，重试3次）
    bench_rows = []
    for _i in range(3):
        bench_rows = parse_kline(cli(["kline", BENCH, "--period", "day", "--limit", "160"]))
        if len(bench_rows) >= 100:
            break
        time.sleep(2)
    # 基准指数周线（RSG强势标注用；westock单股偶发返回空，重试3次）
    bench_week_rows = []
    for _i in range(3):
        bench_week_rows = parse_kline(cli(["kline", BENCH, "--period", "week", "--limit", "100"]))
        if len(bench_week_rows) >= 80:
            break
        time.sleep(2)
    print(f"[INFO] 基准 {BENCH} 日线 {len(bench_rows)} 根 周线 {len(bench_week_rows)} 根", file=sys.stderr)

    # ── 批量拉取日/周/月线 ──
    t0 = time.time()
    tasks = []
    for period, limit in (("day", 160), ("week", 150), ("month", 30)):
        for i in range(0, len(pool), BATCH):
            tasks.append((period, pool[i:i + BATCH], limit))

    fetched = {"day": {}, "week": {}, "month": {}}
    def _fetch(task):
        period, chunk, limit = task
        return period, chunk, fetch_batch([c for c, _ in chunk], period, limit)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for period, chunk, data in ex.map(_fetch, tasks):
            for c, _ in chunk:
                if c in data:
                    fetched[period][c] = data[c]
    print(f"[INFO] 批量取数完成: 日{len(fetched['day'])} 周{len(fetched['week'])} 月{len(fetched['month'])}，耗时 {time.time()-t0:.0f}s", file=sys.stderr)

    # ── 本地计算（无网络）──
    results = []
    for code, name in pool:
        r = analyze(code, name, fetched["day"].get(code), fetched["week"].get(code),
                    fetched["month"].get(code), bench_rows, bench_week_rows)
        if r:
            results.append(r)

    date_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(args.outdir, exist_ok=True)
    launch = [r for r in results if r.get("state") == "启动" or any(s["type"] in ("日线启动", "周线突破50") for s in r.get("signals", []))]
    hold = [r for r in results if r.get("state") == "持有"]
    exit_sig = [r for r in results if r.get("state") == "离场" or any(s["type"] in ("日线卖点", "周线破70") for s in r.get("signals", []))]

    # RSG 强势池（2026-08-27：RS相对52周均线偏离>5% = 强势侧过滤，供鱼身高阳/猛兽领先/仲裁右侧信号标注）
    rsg_pool = [r for r in results if r.get("rsg_strong")]
    rsg_pool.sort(key=lambda x: -(x.get("rsg_dev") or 0))
    js = {"date": date_str, "pool_size": len(pool), "analyzed": len(results),
          "launch": launch, "hold": hold, "exit": exit_sig,
          "rsg_pool": [r["code"] for r in rsg_pool]}
    json_path = os.path.join(args.outdir, "rsv_strength_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    md = [f"# 📈 RSV均相对强度扫描 {date_str}", "",
          f"> 候选池 {len(pool)} 只｜检出 {len(results)} 只（启动 {len(launch)} / 持有 {len(hold)} / 离场 {len(exit_sig)}）",
          "> 方法：腰缠万贯RSV均（144日价格+相对深综指）｜基准 sz399106",
          "", "## 🟢 启动信号（日线<20拐头 / 周线突破50）", "",
          "| 代码 | 名称 | 现价 | 日RSV | 周RSV | 信号 |",
          "|:----|:----|:----:|:----:|:----:|:----|"]
    for r in launch[:30]:
        sigs = "；".join(f"{s['type']}({s['desc']})" for s in r["signals"] if s["type"] in ("日线启动", "周线突破50"))
        md.append(f"| {r['code']} | {r['name']} | {r['close']} | {r['rsv_day']} | {r['rsv_week']} | {sigs} |")
    md += ["", "## 🟡 持有状态（周RSV 70-90）", "",
           "| 代码 | 名称 | 现价 | 日RSV | 周RSV |", "|:----|:----|:----:|:----:|:----:|"]
    for r in hold[:30]:
        md.append(f"| {r['code']} | {r['name']} | {r['close']} | {r['rsv_day']} | {r['rsv_week']} |")
    md += ["", "## 🔴 离场信号（日线>80拐头 / 周线破70）", "",
           "| 代码 | 名称 | 现价 | 日RSV | 周RSV | 信号 |", "|:----|:----|:----:|:----:|:----:|:----|"]
    for r in exit_sig[:30]:
        sigs = "；".join(f"{s['type']}({s['desc']})" for s in r["signals"] if s["type"] in ("日线卖点", "周线破70"))
        md.append(f"| {r['code']} | {r['name']} | {r['close']} | {r['rsv_day']} | {r['rsv_week']} | {sigs} |")
    md += ["", "## 🟢 RSG强势池（周线RS偏离52周均线>5%，强势侧过滤）", "",
           "> 用法：仅用于右侧/强势类信号（高阳强势/空中加油/箱体突破/猛兽领先股）标注；左侧低吸（武威G1/月线反转/RSV启动）不适用",
           "", "| 代码 | 名称 | 现价 | RSG偏离 | 日RSV | 周RSV | 状态 |", "|:----|:----|:----:|:----:|:----:|:----:|:----|"]
    for r in rsg_pool[:30]:
        st = r.get("state", "")
        md.append(f"| {r['code']} | {r['name']} | {r['close']} | {r.get('rsg_dev')}‰ | {r['rsv_day']} | {r['rsv_week']} | {st} |")
    if not rsg_pool:
        md.append("| — | 当前无 | — | — | — | — | 无 |")
    md += ["", "> 说明：RSV均=(价格RSV1+相对深综指RSV2)/2，N=144；周线突破50=3年级别，70-90持有，破70离场；月线估波=ROC14+ROC11的WMA10>0；RSG=周线RS偏离52周均线(‰)，>50=强势"]
    md_path = os.path.join(args.outdir, f"rsv_strength_{date_str}.md")
    open(md_path, "w", encoding="utf-8").write("\n".join(md))
    print(f"[OK] {json_path}")
    print(f"[OK] {md_path}")
    print(f"信号: 启动{len(launch)} 持有{len(hold)} 离场{len(exit_sig)}")


if __name__ == "__main__":
    main()
