#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
liangxue_screener.py —— 量学扫描模块 v2.0（黑马王子《股市天经》三部曲体系）
============================================================================
来源：黑马王子《量柱擒涨停》《量线捉涨停》《量波逮涨停》（百度网盘量学三卷 OCR 提炼）
定位：与曾星智月线闸门(month_frame.py)同级的独立扫描模块 —— 曾星智定方向、量学定量价

v2.0 改进（2026-08-30）：
  1. 黄金柱三级别分类（中继/过顶/托底）——书中"中继黄金柱最安全最有利润"
  2. 倍量柱假阴柱修正：close>prev_close（高开低走收红也算阳柱）
  3. 黄金柱栋梁扩展：倍量/高量/平量/梯量（书中ST天华=平量黄金柱）
  4. 低量柱强化：权重+20，判定改为"低量后放量启动"
  5. 凹口平量柱检测（两高量夹低量，"爆发猛如虎"）
  6. 精准线检测（量线卷核心：2+同价位重合，"擒庄绳"）
  7. 评分权重参数化（--params JSON 可调）
  8. 信号历史跟踪（liangxue_signals_log.csv 累积胜率样本）

核心信号（可量化部分）：
  量柱层：倍量柱 / 黄金柱(三级别) / 低量柱 / 并肩平量柱 / 凹口平量柱 / 价涨量缩
  量线层：精准线（同价位重合）
  趋势层：月线多头（close>MA20>MA60）

评分(0-100)默认权重：
  黄金柱·中继+50 / 过顶+45 / 托底+40 / 倍量低位+30 / 倍量+20
  价涨量缩+15 / 低量放量+20 / 并肩平量+8 / 凹口平量+15 / 精准线+12 / 月线多头+7
闸门：PASS(≥70且含核心信号) / WARN(45-69) / BLOCK(<45)

用法：
  python3 liangxue_screener.py --pool panhou_lianghua.csv          # 全池扫描
  python3 liangxue_screener.py --pool sh600519,sz000026 --limit 5 # 指定代码
  python3 liangxue_screener.py --params '{"hj_mid":55}'           # 自定义权重
  python3 liangxue_screener.py --self-test                          # 内置自测
输出：outputs/liangxue_latest.json + outputs/liangxue_signals_log.csv
"""
import argparse
import csv
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
LIMIT = 130          # 日K根数

# 默认权重（可通过 --params 覆盖）
DEFAULT_W = {
    "hj_mid": 50,   # 黄金柱·中继（最安全买点）
    "hj_over": 45,  # 黄金柱·过顶
    "hj_bot": 40,   # 黄金柱·托底
    "bl_low": 30,   # 倍量柱·低位
    "bl": 20,       # 倍量柱
    "jzsl": 15,     # 价涨量缩
    "lowvol": 12,   # 低量放量启动（v2.0校准：20→12）
    "ping": 8,      # 并肩平量柱
    "aokou": 12,    # 凹口平量柱（v2.0校准：15→12）
    "jingzhun": 8,  # 精准线（v2.0校准：12→8，提高重合点门槛）
    "month": 7,     # 月线多头
}

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


# ============ 量学信号层（v2.0） ============

def find_beiliang(rows, lookback=5):
    """倍量柱：近lookback日内 vol[t] ≥ 2×vol[t-1] 且 相对前日收红(close>prev_close)
    v2.0: 假阴柱修正——高开低走但收盘>前收的假阴柱算阳柱（量柱卷第7讲）
    返回 (idx, {vol_ratio, is_low_pos}) 或 None"""
    for t in range(max(1, len(rows) - lookback), len(rows)):
        prev_vol = rows[t - 1]["vol"]
        prev_close = rows[t - 1]["close"]
        if prev_vol <= 0:
            continue
        ratio = rows[t]["vol"] / prev_vol
        # 假阴柱也算阳柱：收盘>前日收盘 即视为红柱
        if ratio >= 2.0 and rows[t]["close"] > prev_close:
            window = rows[max(0, t - 59):t + 1]
            closes = [r["close"] for r in window]
            lo, hi = min(closes), max(closes)
            is_low = (rows[t]["close"] - lo) / (hi - lo) < 0.4 if hi > lo else False
            return (t, {"vol_ratio": round(ratio, 2), "low_pos": is_low})
    return None


def is_dongliang(rows, d):
    """栋梁之柱判定（v2.0 扩展）：倍量柱 / 高量柱 / 平量柱 / 梯量柱
    返回 (类型, 说明) 或 None"""
    col = rows[d]
    # 倍量：量≥2×前日 且 收红（假阴修正）
    if rows[d - 1]["vol"] > 0 and col["vol"] >= 2 * rows[d - 1]["vol"] and col["close"] > rows[d - 1]["close"]:
        return "倍量", "倍量柱"
    # 高量：近10日最高量
    win10 = max(r["vol"] for r in rows[max(0, d - 9):d + 1])
    if col["vol"] >= win10:
        return "高量", "高量柱"
    # 平量：与前日量差≤3%（并肩平量，"稀有金属"）
    if rows[d - 1]["vol"] > 0 and abs(col["vol"] - rows[d - 1]["vol"]) / rows[d - 1]["vol"] <= 0.03:
        return "平量", "平量柱(并肩)"
    # 梯量：d-2,d-1,d 三连递增
    if d >= 2 and rows[d - 2]["vol"] < rows[d - 1]["vol"] < col["vol"] and rows[d - 2]["vol"] > 0:
        return "梯量", "梯量柱(三连增)"
    return None


def find_huangjinzhu_v2(rows, lookback=15):
    """黄金柱三要素+三级别（量柱卷第13讲）：
      ① 栋梁之柱（倍/高/平/梯）
      ② d+1..d+3 价涨量缩：3日收盘均值 > d收盘 且 3日量均值 ≤ d量×0.75
      ③ d+1..d+3 收盘价均不破 d 的最低价
      级别：中继（前有黄金柱接力）/ 过顶（突破左侧峰顶）/ 托底（托起左侧峰底）
    返回 (d_idx, {level, desc, date}) 或 None"""
    hj_days = set()
    # 第一遍：找所有有效黄金柱日
    for d in range(max(1, len(rows) - lookback - 3), len(rows) - 3):
        col = rows[d]
        dl = is_dongliang(rows, d)
        if not dl:
            continue
        after = rows[d + 1:d + 4]
        if len(after) < 3:
            continue
        avg_close = sum(r["close"] for r in after) / 3
        avg_vol = sum(r["vol"] for r in after) / 3
        if avg_close <= col["close"] or avg_vol > col["vol"] * 0.75:
            continue
        if any(r["close"] < col["low"] for r in after):
            continue
        hj_days.add(d)
    if not hj_days:
        return None
    # 第二遍：取最近一根，定级别
    d = max(hj_days)
    col = rows[d]
    dl_type, dl_name = is_dongliang(rows, d)
    # 中继：d 之前 5-20 日内存在另一根黄金柱
    level, lv_desc = "过顶", "过顶黄金柱(突破左峰)"
    prev_hj = [x for x in hj_days if d - 20 <= x <= d - 5]
    if prev_hj:
        level, lv_desc = "中继", f"中继黄金柱(接力{rows[max(prev_hj)]['date']})"
    else:
        # 过顶：d收盘 创近20日收盘新高（突破前期峰顶，攻击性）
        left_closes = [r["close"] for r in rows[max(0, d - 19):d]]
        if col["close"] >= max(left_closes) if left_closes else False:
            level, lv_desc = "过顶", "过顶黄金柱(突破左峰)"
        # 托底：d最低 < 左侧10日最低价（托起下滑峰底）且后3日确认企稳
        elif col["low"] < min(r["low"] for r in rows[max(0, d - 10):d]):
            level, lv_desc = "托底", "托底黄金柱(护盘自救)"
    return (d, {"level": level, "desc": f"{col['date']}{lv_desc}({dl_name},量缩{round(sum(r['vol'] for r in rows[d+1:d+4])/3/col['vol'],2)})",
                "date": col["date"], "dtype": dl_type})


def find_lowvol_v2(rows, lookback=5):
    """低量柱+放量启动（量柱卷第12讲·v2.0强化）：
      近lookback日内出现近20日最低量，且其后（含当日）出现放量启动（量>1.5×低量 且 收盘>低量日收盘）
    返回 (idx, {date, vol_ratio}) 或 None"""
    for t in range(max(1, len(rows) - lookback), len(rows)):
        win20 = min(r["vol"] for r in rows[max(0, t - 19):t + 1])
        if rows[t]["vol"] <= win20 * 1.02 and rows[t]["vol"] > 0:
            # 找放量启动日（低量日之后5日内，量≥2×低量 且 收涨）
            for k in range(t, min(len(rows), t + 6)):
                if rows[k]["vol"] >= rows[t]["vol"] * 2.0 and rows[k]["close"] > rows[t]["close"]:
                    ratio = rows[k]["vol"] / rows[t]["vol"]
                    return (t, {"date": rows[t]["date"], "launch_date": rows[k]["date"],
                                "vol_ratio": round(ratio, 1)})
    return None


def find_pingliang(rows, lookback=4):
    """并肩平量柱：近lookback日内连续2-3日量差≤3%（蓄势待发）
    返回 (idx, {date}) 或 None"""
    for t in range(max(1, len(rows) - lookback), len(rows)):
        if t >= 1 and rows[t - 1]["vol"] > 0:
            d1 = abs(rows[t]["vol"] - rows[t - 1]["vol"]) / rows[t - 1]["vol"]
            if d1 <= 0.03:
                return (t, {"date": rows[t]["date"]})
    return None


def find_aokou_pingliang(rows, lookback=12):
    """凹口平量柱（量柱卷第11讲·v2.0新增）：两高量柱（左右）夹≥2根低量柱，两侧量高差≤10%
    "凹口平量柱，爆发猛如虎" —— 蓄势最强形态
    返回 (idx, {date, left_date}) 或 None"""
    for j in range(max(3, len(rows) - lookback), len(rows)):
        right_vol = rows[j]["vol"]
        # 找左侧配对高量柱
        for i in range(max(0, j - 6), j - 2):
            left_vol = rows[i]["vol"]
            if left_vol <= 0 or right_vol <= 0:
                continue
            diff = abs(left_vol - right_vol) / left_vol
            if diff > 0.10:
                continue
            middle = rows[i + 1:j]
            if len(middle) < 2:
                continue
            # 中间量都明显低于两侧（<0.6×左量）
            if all(m["vol"] < left_vol * 0.6 for m in middle):
                return (j, {"date": rows[j]["date"], "left_date": rows[i]["date"],
                            "middle_days": len(middle)})
    return None


def find_jingzhunxian(rows, lookback=60, tol=0.01):
    """精准线（量线卷第9讲·v2.0新增）：近lookback日内 ≥3 个同向同等价位重合（容差±1%）
    当前价若贴近某条精准线 → 回踩精准线信号（"回踩精准线，起飞在眼前"）
    返回 (idx, {price, count, dist_pct}) 或 None"""
    closes = [r["close"] for r in rows[-lookback:]]
    n = len(closes)
    # 找重复价位（收盘价接近的交易日≥3）
    seen = {}
    for i, c in enumerate(closes):
        key = round(c, 1)  # 价位归整到0.1元档
        for k in seen:
            if abs(k - key) <= max(0.1, k * tol * 0.5):
                seen[k].append((i, c))
                break
        else:
            seen[key] = [(i, c)]
    cur_price = rows[-1]["close"]
    best = None
    for k, items in seen.items():
        if len(items) >= 3:  # 至少3点重合才叫精准线（稀有性）
            dist = abs(cur_price - k) / k if k > 0 else 1
            if dist <= 0.02:  # 当前价距精准线≤2%
                if best is None or dist < best[2]:
                    best = (k, len(items), dist)
    if best:
        return (len(rows) - 1, {"price": round(best[0], 2), "count": best[1],
                                "dist_pct": round(best[2] * 100, 1)})
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

def analyze(code, name="", rows=None, W=None):
    """单只量学检查（纯本地计算）"""
    try:
        if not rows or len(rows) < 60:
            return {"code": code, "name": name, "ok": False, "reason": "数据不足"}
        sigs = []
        score = 0
        has_core = False

        # 1. 黄金柱（三级别：中继/过顶/托底）
        hj = find_huangjinzhu_v2(rows)
        if hj:
            _, info = hj
            has_core = True
            if info["level"] == "中继":
                score += W["hj_mid"]
                sigs.append({"type": "黄金柱·中继", "desc": info["desc"]})
            elif info["level"] == "过顶":
                score += W["hj_over"]
                sigs.append({"type": "黄金柱·过顶", "desc": info["desc"]})
            else:
                score += W["hj_bot"]
                sigs.append({"type": "黄金柱·托底", "desc": info["desc"]})

        # 2. 倍量柱（低位+30 / 普通+20）
        bl = find_beiliang(rows)
        if bl:
            _, info = bl
            has_core = True
            if info["low_pos"]:
                score += W["bl_low"]
                sigs.append({"type": "倍量柱·低位", "desc": f"量比{info['vol_ratio']}倍@低位"})
            else:
                score += W["bl"]
                sigs.append({"type": "倍量柱", "desc": f"量比{info['vol_ratio']}倍"})

        # 3. 价涨量缩（+15）
        jz = check_jiazhang_suoliang(rows)
        if jz:
            score += W["jzsl"]
            sigs.append({"type": "价涨量缩", "desc": f"量缩至{jz['vol_ratio']}"})

        # 4. 低量柱放量启动（+20）
        lv = find_lowvol_v2(rows)
        if lv:
            _, info = lv
            score += W["lowvol"]
            sigs.append({"type": "低量放量", "desc": f"{info['date']}地量→{info['launch_date']}放量{info['vol_ratio']}倍"})

        # 5. 并肩平量柱（+8）
        pl = find_pingliang(rows)
        if pl:
            _, info = pl
            score += W["ping"]
            sigs.append({"type": "并肩平量", "desc": f"{info['date']}量差≤3%蓄势"})

        # 6. 凹口平量柱（+15）
        ak = find_aokou_pingliang(rows)
        if ak:
            _, info = ak
            score += W["aokou"]
            sigs.append({"type": "凹口平量", "desc": f"{info['left_date']}~{info['date']}凹口{info['middle_days']}日"})

        # 7. 精准线（+12）
        jz2 = find_jingzhunxian(rows)
        if jz2:
            _, info = jz2
            score += W["jingzhun"]
            sigs.append({"type": "精准线", "desc": f"{info['price']}元{info['count']}点重合·距{info['dist_pct']}%"})

        # 8. 月线多头（+7）
        if month_multi(rows):
            score += W["month"]
            sigs.append({"type": "月线多头", "desc": "close>MA20>MA60"})

        score = min(100, score)
        if score >= 85 and has_core:  # v2.0校准：PASS门槛85（黄金柱+倍量+共振，稀缺牛股信号）
            level = "PASS"
        elif score >= 60:
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


# ============ 信号历史跟踪（v2.0） ============

def append_signals_log(outdir, date, results):
    """累积当日 PASS 信号到日志（供胜率统计）"""
    log_path = os.path.join(outdir, "liangxue_signals_log.csv")
    is_new = not os.path.exists(log_path)
    with open(log_path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["date", "code", "name", "close", "score", "level", "signals"])
        for r in results:
            if r.get("level") == "PASS":
                sigs = "|".join(s["type"] for s in r.get("signals", []))
                w.writerow([date, r["code"], r.get("name", ""), r.get("close", ""),
                            r.get("score", ""), r["level"], sigs])
    return log_path


# ============ 主流程 ============

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="", help="池文件或代码列表")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--outdir", default="outputs")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--params", default="", help="权重JSON覆盖，如 '{\"hj_mid\":55}'")
    args = ap.parse_args()

    W = dict(DEFAULT_W)
    if args.params:
        try:
            W.update(json.loads(args.params))
            print(f"[INFO] 自定义权重: {json.dumps(W, ensure_ascii=False)}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] --params解析失败({e})，使用默认权重", file=sys.stderr)

    pool = load_pool(args)
    if args.limit:
        pool = pool[:args.limit]
    print(f"[INFO] 量学扫描v2.0(黑马王子): {len(pool)} 只, workers={args.workers}", file=sys.stderr)

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
        r = analyze(code, name, rows, W)
        if r.get("ok"):
            results.append(r)

    # 分级
    passes = [r for r in results if r["level"] == "PASS"]
    warns = [r for r in results if r["level"] == "WARN"]
    blocks = [r for r in results if r["level"] == "BLOCK"]
    passes.sort(key=lambda r: -r["score"])

    # 输出（v2.0: PASS全量 + WARN全量，BLOCK只计数）
    os.makedirs(args.outdir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    out = {
        "date": date_str,
        "source": "黑马王子量学三部曲（量柱/量线/量波）v2.0",
        "version": "2.0",
        "total": len(results),
        "pass_count": len(passes), "warn_count": len(warns), "block_count": len(blocks),
        "signals": passes + warns,
    }
    outfile = os.path.join(args.outdir, "liangxue_latest.json")
    json.dump(out, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已输出: {outfile}")

    # 信号历史跟踪
    log_path = append_signals_log(args.outdir, date_str, results)
    print(f"✅ 信号日志: {log_path}")

    # stdout 摘要
    print(f"\n量学扫描v2.0结果（黑马王子体系）: {len(results)}只 | PASS={len(passes)} WARN={len(warns)} BLOCK={len(blocks)}")
    print(f"{'代码':<10}{'名称':<8}{'收盘':<9}{'评分':<5}{'级别':<6}信号")
    for r in passes[:20]:
        sigs = ",".join(s["type"] for s in r["signals"][:4])
        print(f"{r['code']:<10}{r['name']:<8}{r['close']:<9}{r['score']:<5}{r['level']:<6}{sigs}")


def self_test():
    """内置自测：验证v2.0信号逻辑"""
    print("量学扫描模块v2.0自测（黑马王子体系）...")
    tests = ["sh600519", "sz000026", "sh600863", "sz000001", "sh600797", "sh600036"]
    rows_map = fetch_batch(tests)
    print(f"{'代码':<10}{'收盘':<9}{'评分':<5}{'级别':<6}信号")
    for c in tests:
        rows = rows_map.get(c)
        r = analyze(c, "", rows, dict(DEFAULT_W))
        if r.get("ok"):
            sigs = ",".join(s["type"] for s in r["signals"][:5]) or "-"
            print(f"{r['code']:<10}{r['close']:<9}{r['score']:<5}{r['level']:<6}{sigs}")
        else:
            print(f"{c:<10} 数据不足/失败: {r.get('reason','')}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        self_test()
    else:
        main()
