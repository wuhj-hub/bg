#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
武威体系 · 多月底样本验证脚本（finance获取净利润做基本面维度）
========================================================
对 samples.json 中多个月底（3/4/5/6月）武威选股样本，做规律验证：
  - 月K判定信号类型：双阴(阳2阴2)/一阴(阳1阴2)/非标准
  - 支撑深度 = (信号月收盘-第一支撑)/信号月收盘×100%
  - 缩量质量 = 阴线量/前面阳线量
  - 日K算两种收益：ret_hold(信号月底后首交易日→07-16) / ret_low(回踩最低→07-16)
  - finance取净利润(NP)做基本面维度（亏损股一票否决）
  - 六维评分 + 分组统计验证
用法：
  python3 wuwei_verify.py --mode fetch
  python3 wuwei_verify.py --mode analyze
  python3 wuwei_verify.py
"""
import subprocess, json, os, sys, time, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "cache_wuwei")
os.makedirs(CACHE, exist_ok=True)
SAMPLES = os.path.join(BASE, "samples.json")

def prefix(code):
    return ("sh" if code[0] == "6" else "sz") + code

def parse_kline(txt):
    rows = []
    for line in txt.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 8:
            continue
        if cells[0] == "date":
            continue
        if set(cells[1]) <= set("-"):
            continue
        try:
            rows.append({"date": cells[0], "open": float(cells[1]), "close": float(cells[2]),
                         "high": float(cells[3]), "low": float(cells[4]), "volume": float(cells[5])})
        except Exception:
            continue
    rows.sort(key=lambda r: r["date"])
    return rows

def fetch_kline(code, period="day", limit=90):
    pcode = prefix(code)
    cf = os.path.join(CACHE, f"{code}_{period}.json")
    if os.path.exists(cf):
        try:
            return json.load(open(cf))
        except Exception:
            pass
    for _ in range(3):
        try:
            out = subprocess.run(
                ["npx", "-y", "westock-data-skillhub@1.0.3", "kline", pcode,
                 "--period", period, "--limit", str(limit), "--fq", "qfq"],
                capture_output=True, text=True, timeout=90)
            data = parse_kline(out.stdout)
            if data:
                json.dump(data, open(cf, "w"))
                return data
        except Exception:
            time.sleep(2)
    return None

def fetch_finance(codes):
    cf = os.path.join(CACHE, "finance.json")
    if os.path.exists(cf):
        try:
            return json.load(open(cf))
        except Exception:
            pass
    res = {}
    for i in range(0, len(codes), 15):
        batch = codes[i:i+15]
        pcs = ",".join(prefix(c) for c in batch)
        try:
            out = subprocess.run(
                ["npx", "-y", "westock-data-skillhub@1.0.3", "finance", pcs,
                 "--type", "lrb", "--num", "1"],
                capture_output=True, text=True, timeout=120)
            res.update(parse_finance(out.stdout, batch))
        except Exception:
            pass
        sys.stdout.write(f"  finance {i}-{i+len(batch)}\n")
        sys.stdout.flush()
    json.dump(res, open(cf, "w"))
    return res

def parse_finance(txt, batch):
    res = {c: {"np": None, "eps": None} for c in batch}
    lines = [l for l in txt.splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        return res
    header = [h.strip() for h in lines[0].strip("|").split("|")]
    try:
        i_sym = header.index("symbol")
        i_np = header.index("NPParentCompanyOwners")
        i_eps = header.index("BasicEPS")
    except Exception:
        return res
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) <= i_eps:
            continue
        sym = cells[i_sym]
        code = sym[2:] if sym[:2] in ("sh", "sz", "bj") else sym
        if code not in res:
            continue
        try:
            res[code]["np"] = float(cells[i_np])
        except Exception:
            pass
        try:
            res[code]["eps"] = float(cells[i_eps])
        except Exception:
            pass
    return res

def is_yang(m):
    return m["close"] > m["open"]

def judge_signal(months):
    if len(months) < 4:
        last = months[-1] if months else {"low": 0, "close": 0}
        return {"type": "数据不足", "support": last["low"], "depth": 0,
                "shrink": 1, "signal_close": last["close"]}
    last, prev, prev2, prev3 = months[-1], months[-2], months[-3], months[-4]
    yang_vol = 0
    for m in [prev3, prev3 if False else prev2, prev]:
        if is_yang(m):
            yang_vol = max(yang_vol, m["volume"])
    if yang_vol <= 0:
        return {"type": "非标准/无信号", "support": last["low"], "depth": 0,
                "shrink": 1, "signal_close": last["close"]}
    if last["close"] < last["open"] and prev["close"] < prev["open"]:
        if last["volume"] <= yang_vol * 0.6 and prev["volume"] <= yang_vol * 0.6:
            fs = min([m["low"] for m in [prev2, prev3] if is_yang(m)] + [last["low"]])
            depth = (last["close"] - fs) / last["close"] if last["close"] > 0 else 0
            shrink = max(last["volume"], prev["volume"]) / yang_vol
            return {"type": "双阴(阳2阴2)", "support": round(fs, 2),
                    "depth": round(depth * 100, 2), "shrink": round(shrink, 2),
                    "signal_close": last["close"]}
    if last["close"] < last["open"]:
        if last["volume"] <= yang_vol * 0.6:
            fs = min([m["low"] for m in [prev, prev2, prev3] if is_yang(m)] + [last["low"]])
            depth = (last["close"] - fs) / last["close"] if last["close"] > 0 else 0
            shrink = last["volume"] / yang_vol
            return {"type": "一阴(阳1阴2)", "support": round(fs, 2),
                    "depth": round(depth * 100, 2), "shrink": round(shrink, 2),
                    "signal_close": last["close"]}
    return {"type": "非标准/无信号", "support": round(last["low"], 2), "depth": 0,
            "shrink": round(last["volume"] / yang_vol, 2), "signal_close": last["close"]}

def day_metrics(day_rows, select_date):
    if not day_rows:
        return None
    buy = None
    low_after = None
    for r in day_rows:
        if r["date"] > select_date:
            if buy is None:
                buy = r["close"]
            if low_after is None or r["low"] < low_after:
                low_after = r["low"]
    end = day_rows[-1]["close"]
    if buy is None or buy == 0:
        return None
    return {"buy": round(buy, 2), "low_after": round(low_after, 2), "end": round(end, 2),
            "ret_hold": round((end - buy) / buy * 100, 2),
            "ret_low": round((end - low_after) / low_after * 100, 2) if low_after else 0}

def score(sig, npv):
    s = 0
    st = sig["type"]
    if "双阴" in st:
        s += 30
    elif "一阴" in st:
        s += 20
    d = sig["depth"]
    if d >= 8:
        s += 20
    elif d >= 5:
        s += 15
    elif d >= 3:
        s += 10
    elif d >= 1:
        s += 5
    sh = sig["shrink"]
    if sh <= 0.4:
        s += 15
    elif sh <= 0.5:
        s += 10
    elif sh <= 0.6:
        s += 5
    if npv is not None:
        s += 0 if npv < 0 else 15   # 亏损股一票否决，盈利给满分
    else:
        s += 10
    s += 5  # 大盘(震荡)
    s += 5  # 价格位置
    return s

def grp_stats(recs, key_fn):
    groups = {}
    for r in recs:
        if r.get("ret_hold") is None:
            continue
        k = key_fn(r)
        groups.setdefault(k, []).append(r)
    out = []
    for k, rs in groups.items():
        ups = [x for x in rs if x["ret_hold"] > 0]
        out.append({"组": k, "数量": len(rs), "上涨数": len(ups),
                    "上涨率%": round(len(ups)/len(rs)*100, 1),
                    "平均持有收益%": round(sum(x["ret_hold"] for x in rs)/len(rs), 2),
                    "平均低吸收益%": round(sum(x["ret_low"] for x in rs)/len(rs), 2)})
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fetch", "analyze", "all"], default="all")
    args = ap.parse_args()
    with open(SAMPLES, encoding="utf-8") as f:
        samples = json.load(f)
    codes = []
    for k, v in samples.items():
        if k.startswith("_"):
            continue
        for c, n in v:
            if c not in codes:
                codes.append(c)
    if args.mode in ("fetch", "all"):
        print(f"[fetch] {len(codes)} 只，月K+日K...")
        def wf(c):
            return c, (fetch_kline(c, "month", 24), fetch_kline(c, "day", 90))
        with ThreadPoolExecutor(max_workers=5) as ex:
            for fu in as_completed([ex.submit(wf, c) for c in codes]):
                fu.result()
        print("[fetch] 月K+日K 完成")
        print("[fetch] 获取财务(净利润/EPS)...")
        fetch_finance(codes)
        print("[fetch] 财务完成")
    if args.mode in ("analyze", "all"):
        mdata = {}
        for c in codes:
            mc = os.path.join(CACHE, f"{c}_month.json")
            dc = os.path.join(CACHE, f"{c}_day.json")
            m = json.load(open(mc)) if os.path.exists(mc) else None
            d = json.load(open(dc)) if os.path.exists(dc) else None
            mdata[c] = (m, d)
        fc = os.path.join(CACHE, "finance.json")
        fins = json.load(open(fc)) if os.path.exists(fc) else {}
        results = []
        for k, v in samples.items():
            if k.startswith("_"):
                continue
            for c, n in v:
                m, d = mdata.get(c, (None, None))
                if not m or not d:
                    results.append({"select": k, "code": c, "name": n, "status": "无数据"})
                    continue
                sig = judge_signal(m)
                dm = day_metrics(d, k)
                fin = fins.get(c)
                npv = fin.get("np") if isinstance(fin, dict) else None
                sc = score(sig, npv)
                sup = sig["support"]
                stop = round(sup * 0.92, 2)
                if npv is not None and npv < 0:
                    decision = "✗放弃(亏损股)"
                elif sig["depth"] < 3:
                    decision = "✗放弃(支撑浅<3%)"
                elif sc < 60:
                    decision = "⚠观望(<60分)"
                elif sig["depth"] >= 5 and "双阴" in sig["type"]:
                    decision = "★重仓买点"
                else:
                    decision = "●轻仓(等回踩)"
                results.append({"select": k, "code": c, "name": n, "signal": sig["type"],
                                "depth": sig["depth"], "shrink": sig["shrink"],
                                "support": sup, "stop": stop, "np": npv, "score": sc,
                                "decision": decision,
                                "ret_hold": dm["ret_hold"] if dm else None,
                                "ret_low": dm["ret_low"] if dm else None,
                                "end": dm["end"] if dm else None})
        valid = [r for r in results if r.get("ret_hold") is not None]
        by_sig = grp_stats(valid, lambda r: r["signal"])
        by_depth = grp_stats(valid, lambda r: "支撑≥5%" if r["depth"] >= 5 else ("支撑3-5%" if r["depth"] >= 3 else "支撑<3%"))
        by_fund = grp_stats(valid, lambda r: "亏损股(NP<0)" if (r.get("np") is not None and r["np"] < 0) else ("盈利股" if r.get("np") is not None else "财务未知"))
        by_month = grp_stats(valid, lambda r: r["select"])
        total = len(valid)
        ups = sum(1 for r in valid if r["ret_hold"] > 0)
        avg = sum(r["ret_hold"] for r in valid) / total
        avg_low = sum(r["ret_low"] for r in valid) / total
        out = {"by_signal": by_sig, "by_depth": by_depth, "by_fund": by_fund, "by_month": by_month,
               "summary": {"total": total, "up": ups, "up_rate": round(ups/total*100, 1),
                           "avg_hold": round(avg, 2), "avg_low": round(avg_low, 2)}}
        json.dump({"summary_stats": out, "details": results},
                  open(os.path.join(BASE, "wuwei_verify_result.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

        def pt(title, rows):
            print(f"\n=== {title} ===")
            print(f"{'组':<16}{'数量':>5}{'上涨':>5}{'上涨率%':>8}{'持有收益%':>10}{'低吸收益%':>10}")
            for r in rows:
                print(f"{str(r['组']):<16}{r['数量']:>5}{r['上涨数']:>5}{r['上涨率%']:>8}{r['平均持有收益%']:>10}{r['平均低吸收益%']:>10}")
        print("\n########## 武威体系 · 多月底样本验证 ##########")
        print(f"有效样本 {total} 只 | 上涨 {ups} ({round(ups/total*100,1)}%) | "
              f"平均持有 {round(avg,2)}% | 平均低吸 {round(avg_low,2)}%")
        pt("按信号类型", by_sig)
        pt("按支撑深度", by_depth)
        pt("按基本面(净利润)", by_fund)
        pt("按选股月份", by_month)
        from collections import Counter
        dec = Counter(r.get("decision", "未知") for r in valid)
        print("\n=== 研判决策分布 ===")
        for kk, vv in dec.most_common():
            print(f"  {kk}: {vv}只")
        print("\n明细写入 wuwei_verify_result.json")

if __name__ == "__main__":
    main()
