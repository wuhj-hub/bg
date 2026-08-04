#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pool_tracking_report.py —— 股池标的跟踪报告（三阶漏斗整合版 v1.0）
====================================================================
对股票池标的逐只执行「三阶漏斗」：
  第一阶 月线反转（曾星智+陶博士）: 月线趋势/反转信号/闸门  ← month_frame.py
  第二阶 武威G1（低吸潜伏）: 双阴/一阴缩量回调到起涨点 + 支撑深度
  第三阶 v2.1质量否决: 支撑≥5% + 非亏损 + 仓位决策

输出: 结构化跟踪报告（整合三阶漏斗的新格式）→ 知识库 + 推送

用法: python3 pool_tracking_report.py [--pool "sz000779,sz002596,..."] [--name 自定义标题]
"""
import subprocess, sys, os, re, json, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_month_kline(txt):
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or "---" in parts[0]:
            continue
        if len(parts) >= 6:
            try:
                di = header.index("date")
                row = {"date": parts[di]}
                for key in ("open", "last", "high", "low", "volume"):
                    if key in header:
                        row[key] = float(parts[header.index(key)])
                if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                    rows.append(row)
            except (ValueError, IndexError):
                pass
    rows.sort(key=lambda r: r["date"])
    return rows

def ma(vals, i, n):
    return sum(vals[i-n+1:i+1]) / n

# ═══════ 第一阶: 月线反转（与month_frame.py一致）═══════
def month_frame(rows):
    if len(rows) < 7:
        return {"trend": "无数据", "gate": "BLOCK", "reversal": None, "ma6": None, "ma12": None, "close": None}
    closes = [r["last"] for r in rows]
    cur = closes[-1]
    ma6 = sum(closes[-6:]) / 6
    ma12 = sum(closes[-12:]) / 12
    ma6_prev = sum(closes[-7:-1]) / 6
    ma12_prev = sum(closes[-13:-1]) / 12
    if cur > ma6 > ma12:
        trend = "多头"
    elif cur < ma6 < ma12:
        trend = "空头"
    else:
        trend = "纠缠"
    reversal = None
    prev_high = max(r["high"] for r in rows[:-1])
    if cur > prev_high and cur > ma6:
        reversal = "平台突破(12月新高)"
    elif ma6 > ma12 and ma6_prev <= ma12_prev:
        reversal = "均线金叉(MA6上穿MA12)"
    elif ma6 > ma12 and cur > ma6 and (ma6 - ma6_prev) > 0:
        reversal = "趋势确立(MA6上行)"
    gate = "PASS" if (trend == "多头" or reversal) else "WARN" if trend == "纠缠" else "BLOCK"
    return {"trend": trend, "gate": gate, "reversal": reversal, "ma6": round(ma6, 2),
            "ma12": round(ma12, 2), "close": round(cur, 2)}

# ═══════ 第二阶: 武威G1 + 支撑深度 ═══════
def wuwei_g1(rows):
    if len(rows) < 4:
        return "无", None, None
    k1, k2, k3, k4 = rows[-4], rows[-3], rows[-2], rows[-1]
    def yang(r): return r["last"] > r["open"]
    def yin(r): return r["last"] < r["open"]
    support = None
    if k4["last"] > 0 and k1["low"] > 0:
        support = (k4["last"] - k1["low"]) / k4["last"]
    ratios = []
    if k2["volume"] > 0:
        ratios.append(k3["volume"] / k2["volume"])
        ratios.append(k4["volume"] / k2["volume"])
    shrink_max = max(ratios) if ratios else 1.0
    if yin(k3) and yin(k4):
        if k4["volume"] <= k2["volume"] * 0.6 and k3["volume"] <= k2["volume"] * 0.6:
            if k1["low"] > 0 and abs(k4["low"] - k1["low"]) / k1["low"] <= 0.12:
                return "双阴", support, shrink_max
    if yang(k3) and yin(k2) and yin(k4):
        if k2["volume"] < k3["volume"] * 0.6 and k4["volume"] < k3["volume"] * 0.6:
            if k3["low"] > 0 and abs(k4["low"] - k3["low"]) / k3["low"] <= 0.12:
                return "一阴", support, shrink_max
    return "无", support, shrink_max

# ═══════ 第三阶: v2.1质量否决（支撑≥5% + 盈利）═══════
def fetch_finance(codes):
    fin = {}
    codes = sorted(set(codes))
    for i in range(0, len(codes), 10):
        batch = codes[i:i+10]
        out = run(["finance", ",".join(batch), "--type", "lrb", "--num", "1"])
        lines = [l for l in out.splitlines() if l.strip().startswith("|")]
        if len(lines) >= 2:
            hdr = [h.strip() for h in lines[0].strip().strip("|").split("|")]
            if "SecuCode" in hdr and "NPParentCompanyOwners" in hdr:
                sci, npi = hdr.index("SecuCode"), hdr.index("NPParentCompanyOwners")
                for l in lines[2:]:
                    cols = [x.strip() for x in l.strip().strip("|").split("|")]
                    if len(cols) > max(sci, npi):
                        code, npv = cols[sci], cols[npi]
                        try:
                            v = float(npv)
                            fin[code] = "盈利" if v > 0 else "亏损"
                        except ValueError:
                            fin[code] = "无数据"
    for c in codes:
        fin.setdefault(c, "无数据")
    return fin

def v21_decision(sig_type, support, finance):
    """v2.1一票否决+仓位决策"""
    if finance == "亏损":
        return "否决", "亏损股(一票否决)"
    if support is None or support < 0.05:
        return "否决", "浅支撑<5%(一票否决)"
    if sig_type == "双阴" and finance == "盈利":
        return "重仓", "双阴+深支撑+盈利 ★"
    if sig_type == "一阴":
        return "轻仓", "一阴仅轻仓(永不重仓)"
    return "观察", "未触发G1"

def track_stock(code, name=""):
    rows = []
    for _ in range(3):
        txt = run(["kline", code, "--period", "month", "--limit", "36"])
        rows = parse_month_kline(txt)
        if rows:
            break
    if len(rows) < 7:
        return {"code": code, "name": name, "ok": False, "err": "月线数据不足"}
    cur_price = rows[-1]["last"] if rows[-1]["date"].startswith("2026-08") else rows[-1]["last"]
    # 月线趋势/反转: 用含当月盘中K线（实时，与猛兽Step 2.6口径一致）
    mf = month_frame(rows)
    # 武威G1: 用最近完整月（当月未走完时去掉当月K线，月末信号定稿）
    rows_g1 = rows
    if rows and re.match(r"^\d{4}-08", rows[-1]["date"]):
        rows_g1 = rows[:-1]
    g1, support, shrink = wuwei_g1(rows_g1)
    return {"code": code, "name": name, "ok": True, "mf": mf, "g1": g1,
            "support": support, "shrink": shrink, "price": cur_price}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="")
    ap.add_argument("--name", default="")
    a = ap.parse_args()

    DEFAULT_POOL = [
        ("sz000779", "甘咨询"), ("sz002596", "海南瑞泽"), ("sh600095", "湘财股份"),
        ("sz000026", "飞亚达(武威7月重仓)"),
        ("sh603259", "药明康德(8/4反转)"), ("sz002354", "天娱数科(8/4反转)"),
        ("sz000636", "风华高科(8/4反转)"), ("sz000725", "京东方A(8/4反转)"),
        ("sh600664", "哈药股份(8/4反转)"), ("sh600396", "华电辽能(8/4反转)"),
        ("sz000938", "紫光股份(8/4反转)"), ("sz000815", "美利云(8/4反转)"),
        ("sz000892", "欢瑞世纪(主力放量)"), ("sz000566", "海南海药(主力放量)"),
        ("sz002131", "利欧股份(主力放量)"),
    ]
    if a.pool:
        pool = [(c.strip(), "") for c in a.pool.split(",") if c.strip()]
    else:
        pool = DEFAULT_POOL
    print(f"跟踪标的: {len(pool)} 只\n")

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(track_stock, c, n): (c, n) for c, n in pool}
        for f in as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda r: r["code"])

    # 财务
    need_fin = [r["code"] for r in results if r["ok"]]
    fin = fetch_finance(need_fin)

    # ═══ 生成报告 ═══
    title = a.name or "股池标的跟踪报告"
    L = []
    A = L.append
    A(f"# 📊 {title} · 三阶漏斗整合版\n")
    A("> 生成时间：2026-08-04 17:45 | 数据：月线K线+利润表（westock）")
    A("> **三阶漏斗**：① 月线反转（曾星智MA6/MA12+陶博士）→ ② 武威G1（双阴/一阴缩量回调）→ ③ v2.1质量否决（支撑≥5%+盈利）")
    A("> 📅 信号基准月：**2026-07**（月末完整月，与武威G1月末选股一致）\n")

    # 汇总表
    A("## 一、三阶漏斗总览\n")
    A("| 代码 | 名称 | 现价 | ①月线 | 闸门 | 反转信号 | ②G1 | 支撑 | ③v2.1 | 决策 |")
    A("|:----|:----|:----:|:----:|:----:|:--------|:----:|:----:|:----:|:----:|")
    for r in results:
        if not r["ok"]:
            A(f"| {r['code']} | {r['name']} | — | 数据不足 | — | — | — | — | — | ⚠️ |")
            continue
        mf, g1 = r["mf"], r["g1"]
        sup_txt = f"{r['support']*100:.0f}%" if r["support"] is not None else "—"
        fst = fin.get(r["code"], "无数据")
        gate_txt = {"PASS": "🟢", "WARN": "🟡", "BLOCK": "🔴"}.get(mf["gate"], "❔")
        rev_txt = mf["reversal"] or "—"
        # 三阶漏斗判定
        if mf["gate"] == "PASS" and g1 in ("双阴", "一阴") and fst == "盈利" and (r["support"] or 0) >= 0.05:
            dec = "★ 三重共振"
        elif mf["gate"] == "PASS" and g1 in ("双阴", "一阴"):
            dec = "二阶共振"
        elif mf["gate"] == "PASS":
            dec = "一阶通过"
        elif mf["gate"] == "WARN":
            dec = "月线纠缠"
        else:
            dec = "月线空头"
        A(f"| {r['code']} | {r['name']} | {r['price']} | {mf['trend']} | {gate_txt} | {rev_txt} | {g1} | {sup_txt} | {fst} | **{dec}** |")

    # 三阶共振明细
    A("\n## 二、三阶共振标的（★ 可执行）\n")
    A("| 代码 | 名称 | 月线反转 | 武威G1 | 支撑 | 财务 | 建议 |")
    A("|:----|:----|:--------|:------|:----:|:----:|:----|")
    n_star = 0
    for r in results:
        if not r["ok"]:
            continue
        mf, g1 = r["mf"], r["g1"]
        fst = fin.get(r["code"], "无数据")
        if mf["gate"] == "PASS" and g1 in ("双阴", "一阴") and fst == "盈利" and (r["support"] or 0) >= 0.05:
            n_star += 1
            sup = f"{r['support']*100:.0f}%"
            weight = "重仓" if g1 == "双阴" else "轻仓"
            A(f"| {r['code']} | {r['name']} | {mf['reversal'] or mf['trend']} | {g1} | {sup} | {fst} | **{weight}关注**（月线破MA6离场） |")
    if n_star == 0:
        A("| — | 当前无三重共振标的 | — | — | — | — | — |")

    # 二阶/一阶明细
    A("\n## 三、二阶共振 / 一阶通过（观察）\n")
    A("| 代码 | 名称 | ①月线 | ②G1 | ③v2.1 | 状态 |")
    A("|:----|:----|:----:|:----:|:----:|:----|")
    for r in results:
        if not r["ok"]:
            continue
        mf, g1 = r["mf"], r["g1"]
        fst = fin.get(r["code"], "无数据")
        sup_ok = (r["support"] or 0) >= 0.05
        if mf["gate"] == "PASS" and g1 in ("双阴", "一阴") and fst == "盈利" and sup_ok:
            continue  # 已在上表
        if mf["gate"] == "PASS":
            A(f"| {r['code']} | {r['name']} | {mf['trend']}{'⚡'+mf['reversal'] if mf['reversal'] else ''} | {g1} | {fst}{'·支撑'+str(round((r['support'] or 0)*100))+'%' if r['support'] else ''} | 观察 |")
        elif mf["gate"] == "WARN":
            A(f"| {r['code']} | {r['name']} | {mf['trend']} | {g1} | {fst} | ⚠️月线纠缠待确认 |")

    # 被否决明细（仅BLOCK或数据不足）
    A("\n## 四、否决 / 拦截标的（三阶漏斗未通过）\n")
    A("| 代码 | 名称 | 拦截原因 |")
    A("|:----|:----|:--------|")
    for r in results:
        if not r["ok"]:
            A(f"| {r['code']} | {r['name']} | 数据不足 |")
            continue
        mf, g1 = r["mf"], r["g1"]
        fst = fin.get(r["code"], "无数据")
        if mf["gate"] != "BLOCK":
            continue
        reason = []
        reason.append("月线空头(BLOCK)")
        if g1 == "无":
            reason.append("无武威G1信号")
        if fst == "亏损":
            reason.append("亏损股")
        elif (r["support"] or 0) < 0.05 and r["support"] is not None:
            reason.append(f"浅支撑{round(r['support']*100)}%<5%")
        A(f"| {r['code']} | {r['name']} | {'、'.join(reason) or '未达条件'} |")

    A("\n---")
    A("⚠️ 本报告基于公开市场数据整理，不构成投资建议。三阶漏斗为量化历史规律总结，实战需结合大盘温度动态调整。")

    md = "\n".join(L)
    out = "/sandbox/workspace/outputs/股池标的跟踪报告_2026-08-04.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {out} ({len(md)} chars)")
    print(md[:800])

if __name__ == "__main__":
    main()
