#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
liangxue_screener.py —— 量学扫描模块（黑马王子《股市天经》三部曲体系）
========================================================================
来源：黑马王子《量柱擒涨停》《量线捉涨停》《量波逮涨停》（百度网盘量学三卷 OCR 提炼）
定位：与曾星智月线闸门(month_frame.py)同级的独立扫描模块 —— 曾星智定方向、量学定量价

核心信号（可量化部分）：
  1. 倍量柱   （量柱卷第7讲）：当日量 ≥ 2×前日量 且收红 —— 主力实力介入
  2. 黄金柱   （量柱卷第13讲）：倍量/高量柱 + 后3日价涨量缩 + 收盘不破柱底 —— 牛股黑马
  3. 价涨量缩 （量柱卷缩量柱）：close↑ & vol↓ —— 主力控盘
  4. 低量柱   （量柱卷第12讲）：近20日最低量 —— 拐头向上的前夜
  5. 平量柱   （量柱卷第11讲）：连续2-3日量差≤3% —— 蓄势待发（次日/隔日涨停特性）
  6. 量性升华 （量柱卷第6讲）：高量柱+3日价升量缩 = 黄金柱 —— 涨停在望

评分(0-100)：黄金柱+40 / 倍量柱+20(低位+10) / 价涨量缩+15 / 低量柱拐点+15 / 平量柱+10 / 月线多头+10
闸门：PASS(≥60) 量学强信号 / WARN(40-59) / BLOCK(<40)

用法：
  python3 liangxue_screener.py --pool panhou_lianghua.csv          # 全池扫描
  python3 liangxue_screener.py --pool sh600519,sz000026 --limit 5 # 指定代码
  python3 liangxue_screener.py --self-test                          # 内置自测
输出：outputs/liangxue_latest.json
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
BATCH = 100          # 批量kline每批股票数
LIMIT = 130          # 日K根数（黄金柱需柱日+3日，MA60需60日，低量需20日）

# ============ 数据层 ============

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


def parse_batch_kline(txt):
    """解析批量kline：{full_code: [升序 {date,open,close,high,low,vol}]}
    ⚠️ 批量列序: symbol|date|open|last|high|low|volume|amount|exchange，date降序（最新在前）"""
    out, cur = {}, None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 8 or parts[0] == "symbol" or "---" in parts[0]:
            continue
        if re.match(r"^(sh|sz|bj)\d{6}$", parts[0]):
            cur = parts[0]
            try:
                out.setdefault(cur, []).append({
                    "date": parts[1], "open": float(parts[2]),
                    "close": float(parts[3]), "high": float(parts[4]),
                    "low": float(parts[5]), "vol": float(parts[6])})
            except (ValueError, IndexError):
                pass
    for c in out:
        out[c].sort(key=lambda r: r["date"])  # 降序→升序
    return out


def fetch_batch(codes, retries=3):
    """批量拉日K，{full_code: rows升序}。失败批次重试。"""
    codes = [norm(c) for c in codes]
    joined = ",".join(codes)
    args = ["kline", joined, "--period", "day", "--limit", str(LIMIT), "--fq", "qfq"]
    for i in range(retries):
        txt = cli(args)
        if txt and "执行失败" not in txt:
            data = parse_batch_kline(txt)
            got = set(data.keys())
            want = set(codes)
            if len(got) >= max(1, int(len(want) * 0.8)):
                return data
        time.sleep(2 * (i + 1))
    return {}


# ============ 量学信号层 ============

def find_beiliang(rows, lookback=5):
    """倍量柱：近lookback日内 vol[t] ≥ 2×vol[t-1] 且 收红(close>open)
    返回 (idx, {vol_ratio, is_low_pos}) 或 None"""
    for t in range(max(1, len(rows) - lookback), len(rows)):
        prev_vol = rows[t - 1]["vol"]
        if prev_vol <= 0:
            continue
        ratio = rows[t]["vol"] / prev_vol
        if ratio >= 2.0 and rows[t]["close"] > rows[t]["open"]:
            # 相对低位判断：close < 近60日(40%分位)
            window = rows[max(0, t - 59):t + 1]
            closes = [r["close"] for r in window]
            lo, hi = min(closes), max(closes)
            is_low = (rows[t]["close"] - lo) / (hi - lo) < 0.4 if hi > lo else False
            return (t, {"vol_ratio": round(ratio, 2), "low_pos": is_low})
    return None


def find_huangjinzhu(rows, lookback=12):
    """黄金柱三要素（量柱卷第13讲）：近lookback日内存在柱日d：
      ① d为倍量柱 或 近10日最高量（栋梁之柱）
      ② d+1..d+3 价涨量缩：3日收盘均值 > d收盘 且 3日量均值 ≤ d量×0.75（喇叭口）
      ③ d+1..d+3 收盘价均不破 d 的最低价
    返回 (d_idx, {desc}) 或 None"""
    for d in range(max(1, len(rows) - lookback), len(rows) - 3):
        col = rows[d]
        # ① 栋梁之柱：倍量 或 近10日最高量
        is_beiliang = (rows[d - 1]["vol"] > 0 and
                       col["vol"] >= 2 * rows[d - 1]["vol"] and col["close"] > col["open"])
        win10 = max(r["vol"] for r in rows[max(0, d - 9):d + 1])
        is_high = col["vol"] >= win10
        if not (is_beiliang or is_high):
            continue
        after = rows[d + 1:d + 4]
        if len(after) < 3:
            continue
        # ② 价涨量缩：3日收盘均值 > d收盘，3日量均值 ≤ d量×0.75
        avg_close = sum(r["close"] for r in after) / 3
        avg_vol = sum(r["vol"] for r in after) / 3
        if avg_close <= col["close"] or avg_vol > col["vol"] * 0.75:
            continue
        # ③ 收盘不破柱底
        if any(r["close"] < col["low"] for r in after):
            continue
        desc = f"{col['date']}黄金柱(倍量{is_beiliang}/高量{is_high},量缩{round(avg_vol/col['vol'],2)})"
        return (d, {"desc": desc, "date": col["date"]})
    return None


def find_lowvol(rows, lookback=3):
    """低量柱拐点：近lookback日内出现近20日最低量（拐头向上的前夜）
    返回 (idx, {date}) 或 None"""
    for t in range(max(1, len(rows) - lookback), len(rows)):
        win20 = min(r["vol"] for r in rows[max(0, t - 19):t + 1])
        if rows[t]["vol"] <= win20 * 1.02 and rows[t]["vol"] > 0:
            # 当日或次日回升（收盘高于低量日收盘）
            if t < len(rows) - 1 and rows[t + 1]["close"] >= rows[t]["close"]:
                return (t, {"date": rows[t]["date"]})
            if t == len(rows) - 1:
                return (t, {"date": rows[t]["date"]})
    return None


def find_pingliang(rows, lookback=4):
    """平量柱：近lookback日内连续2-3日量差≤3%（并肩平量柱，蓄势待发）
    返回 (idx, {date}) 或 None"""
    for t in range(max(1, len(rows) - lookback), len(rows)):
        if t >= 1 and rows[t - 1]["vol"] > 0:
            d1 = abs(rows[t]["vol"] - rows[t - 1]["vol"]) / rows[t - 1]["vol"]
            if d1 <= 0.03:
                return (t, {"date": rows[t]["date"]})
    return None


def check_jiazhang_suoliang(rows):
    """价涨量缩（当日）：close↑ & vol↓ —— 主力控盘"""
    if len(rows) < 2:
        return None
    t = len(rows) - 1
    if (rows[t]["close"] > rows[t - 1]["close"] and
            rows[t]["vol"] < rows[t - 1]["vol"]):
        ratio = rows[t]["vol"] / rows[t - 1]["vol"]
        return {"vol_ratio": round(ratio, 2)}
    return None


def month_multi(rows):
    """月线多头简化：close>MA20 且 MA20>MA60"""
    closes = [r["close"] for r in rows]
    if len(closes) < 60:
        return False
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    return closes[-1] > ma20 and ma20 > ma60


# ============ 分析主函数 ============

def analyze(code, name="", rows=None):
    """单只量学检查（纯本地计算）"""
    try:
        if not rows or len(rows) < 60:
            return {"code": code, "name": name, "ok": False, "reason": "数据不足"}
        sigs = []
        score = 0
        has_core = False  # 量学核心信号（黄金柱/倍量柱）

        # 1. 黄金柱（+45，量学最高信号）
        hj = find_huangjinzhu(rows)
        if hj:
            _, info = hj
            score += 45
            has_core = True
            sigs.append({"type": "黄金柱", "desc": info["desc"]})

        # 2. 倍量柱（低位+30 / 普通+20）
        bl = find_beiliang(rows)
        if bl:
            _, info = bl
            if info["low_pos"]:
                score += 30
                has_core = True
                sigs.append({"type": "倍量柱·低位", "desc": f"量比{info['vol_ratio']}倍@低位"})
            else:
                score += 20
                has_core = True
                sigs.append({"type": "倍量柱", "desc": f"量比{info['vol_ratio']}倍"})

        # 3. 价涨量缩（+15）
        jz = check_jiazhang_suoliang(rows)
        if jz:
            score += 15
            sigs.append({"type": "价涨量缩", "desc": f"量缩至{jz['vol_ratio']}"})

        # 4. 低量柱拐点（+10）
        lv = find_lowvol(rows)
        if lv:
            _, info = lv
            score += 10
            sigs.append({"type": "低量柱拐点", "desc": f"{info['date']}阶段地量"})

        # 5. 平量柱（+8）
        pl = find_pingliang(rows)
        if pl:
            _, info = pl
            score += 8
            sigs.append({"type": "平量柱", "desc": f"{info['date']}并肩平量蓄势"})

        # 6. 月线多头（+7）
        if month_multi(rows):
            score += 7
            sigs.append({"type": "月线多头", "desc": "close>MA20>MA60"})

        score = min(100, score)
        # PASS：≥70 且含量学核心信号（黄金柱/倍量柱）
        if score >= 70 and has_core:
            level = "PASS"
        elif score >= 45:
            level = "WARN"
        else:
            level = "BLOCK"
        close = rows[-1]["close"]
        chg = ((rows[-1]["close"] - rows[-2]["close"]) / rows[-2]["close"] * 100
               if len(rows) >= 2 and rows[-2]["close"] > 0 else 0)

        return {"code": code, "name": name, "ok": True, "close": round(close, 2),
                "chg": round(chg, 2), "score": score, "level": level,
                "signals": sigs}
    except Exception as e:
        return {"code": code, "name": name, "ok": False, "reason": str(e)[:60]}


# ============ 池加载 ============

def load_pool(args):
    pool = []
    p = args.pool
    if not p:
        p = "panhou_lianghua.csv"
        if not os.path.exists(p):
            p = "quant_scripts/panhou_lianghua.csv"
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


# ============ 主流程 ============

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
    print(f"[INFO] 量学扫描(黑马王子): {len(pool)} 只, workers={args.workers}", file=sys.stderr)

    # 分批批量拉取
    all_rows = {}
    batches = [pool[i:i + BATCH] for i in range(0, len(pool), BATCH)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(fetch_batch, [c for c, _ in b]): b for b in batches}
        for i, fut in enumerate(futures):
            data = fut.result()
            all_rows.update(data)
            if (i + 1) % 5 == 0:
                print(f"[INFO] 已拉取 {len(all_rows)} 只 ({time.time()-t0:.0f}s)", file=sys.stderr)
    print(f"[INFO] 数据拉取完成: {len(all_rows)}/{len(pool)} 只 ({time.time()-t0:.0f}s)", file=sys.stderr)

    # 分析
    results = []
    for code, name in pool:
        rows = all_rows.get(code)
        r = analyze(code, name, rows)
        if r.get("ok"):
            results.append(r)

    # 分级
    passes = [r for r in results if r["level"] == "PASS"]
    warns = [r for r in results if r["level"] == "WARN"]
    blocks = [r for r in results if r["level"] == "BLOCK"]
    passes.sort(key=lambda r: -r["score"])

    # 输出
    os.makedirs(args.outdir, exist_ok=True)
    out = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "source": "黑马王子量学三部曲（量柱/量线/量波）",
        "total": len(results),
        "pass_count": len(passes), "warn_count": len(warns), "block_count": len(blocks),
        "signals": passes + warns[:30],
    }
    outfile = os.path.join(args.outdir, "liangxue_latest.json")
    json.dump(out, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已输出: {outfile}")

    # stdout 摘要
    print(f"\n量学扫描结果（黑马王子体系）: {len(results)}只 | PASS={len(passes)} WARN={len(warns)} BLOCK={len(blocks)}")
    print(f"{'代码':<10}{'名称':<8}{'收盘':<9}{'评分':<5}{'级别':<6}信号")
    for r in passes[:20]:
        sigs = ",".join(s["type"] for s in r["signals"][:3])
        print(f"{r['code']:<10}{r['name']:<8}{r['close']:<9}{r['score']:<5}{r['level']:<6}{sigs}")


def self_test():
    """内置自测：用几只样本验证信号逻辑"""
    print("量学扫描模块自测（黑马王子体系）...")
    tests = ["sh600519", "sz000026", "sh600863", "sz000001", "sh600797"]
    rows_map = fetch_batch(tests)
    print(f"{'代码':<10}{'收盘':<9}{'评分':<5}{'级别':<6}信号")
    for c in tests:
        rows = rows_map.get(c)
        r = analyze(c, "", rows)
        if r.get("ok"):
            sigs = ",".join(s["type"] for s in r["signals"][:4]) or "-"
            print(f"{r['code']:<10}{r['close']:<9}{r['score']:<5}{r['level']:<6}{sigs}")
        else:
            print(f"{c:<10} 数据不足/失败: {r.get('reason','')}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        self_test()
    else:
        main()
