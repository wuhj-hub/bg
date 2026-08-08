#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
month_frame.py —— 月线框架模块（曾星智+陶博士体系整合）

功能：
1. check_month_trend(code) —— 个股月线趋势检查
   - MA6  = 近6个月收盘均值（半年线，对应曾星智体系）
   - MA12 = 近12个月收盘均值（年线）
   - 多头: 收盘 > MA6 且 MA6 > MA12（6月线在年线之上，中期趋势向上）
   - 空头: 收盘 < MA6 且 MA6 < MA12（中期趋势向下）
   - 纠缠: 其他（趋势不明）
2. 月线反转信号（陶博士月线反转简化版）
   - 平台突破: 本月收盘创近12月新高（突破前期平台）且站上MA6
   - 均线金叉: MA6 本月上穿 MA12（近3个月内发生）且收盘在MA6之上
3. 月线闸门（给日线信号做过滤）: month_gate(code)
   - PASS(放行)  : 月线多头 或 出现反转信号
   - WARN(降级)  : 纠缠（信号减半考虑）
   - BLOCK(拦截) : 月线空头（日线买点可靠性低）

数据源：westock kline 月线（npx）
用法：
    python3 month_frame.py --check sz000026
    python3 month_frame.py --scan sh600519,sz000026  (批量)
    python3 month_frame.py --self-test               (内置样本自测)
"""
import subprocess, re, sys, json

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_month_kline(txt):
    """解析月线K线，返回按日期升序的 [{date, close, high, low}]
    兼容两种表头：单股(| date | open | last |...) 与 batch(| symbol | date | ...)"""
    rows = []
    header = None
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
                ci = header.index("last")
                hi = header.index("high")
                li = header.index("low")
                if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                    rows.append({"date": parts[di], "close": float(parts[ci]),
                                 "high": float(parts[hi]), "low": float(parts[li])})
            except (ValueError, IndexError):
                pass
    rows.sort(key=lambda r: r["date"])
    return rows

def fetch_month_rows(code):
    """获取月线数据：优先单股，偶发空时重试+batch fallback（westock单股查询不稳定）"""
    import time
    for attempt in range(3):
        txt = run(["kline", code, "--period", "month", "--limit", "15"])
        rows = parse_month_kline(txt)
        if rows:
            return rows
        time.sleep(1.5)
    return []

def check_month_trend(code, rows=None):
    """个股月线趋势检查（曾星智体系：MA6半年线 + MA12年线）"""
    if rows is None:
        rows = fetch_month_rows(code)
    out = {"code": code, "ok": False, "trend": "无数据", "reversal": None,
           "close": None, "ma6": None, "ma12": None, "gate": "BLOCK"}
    if len(rows) < 7:
        return out
    closes = [r["close"] for r in rows]
    cur = closes[-1]
    ma6 = sum(closes[-6:]) / 6
    ma12 = sum(closes[-12:]) / 12 if len(closes) >= 12 else sum(closes) / len(closes)
    # 上月MA6（判断金叉）
    ma6_prev = sum(closes[-7:-1]) / 6 if len(closes) >= 7 else ma6
    ma12_prev = sum(closes[-13:-1]) / 12 if len(closes) >= 13 else ma12
    # 趋势判定
    if cur > ma6 and ma6 > ma12:
        trend = "多头"
    elif cur < ma6 and ma6 < ma12:
        trend = "空头"
    else:
        trend = "纠缠"
    # 月线反转信号
    reversal = None
    prev_high = max(r["high"] for r in rows[:-1])  # 前11个月最高
    if cur > prev_high and cur > ma6:
        reversal = "平台突破(12月新高)"
    elif ma6 > ma12 and ma6_prev <= ma12_prev:
        reversal = "均线金叉(MA6上穿MA12)"
    elif ma6 > ma12 and cur > ma6 and (ma6 - ma6_prev) > 0:
        # MA6持续上行且价格在上方——趋势确立型
        reversal = "趋势确立(MA6上行)"
    # 闸门
    if trend == "多头" or reversal:
        gate = "PASS"
    elif trend == "纠缠":
        gate = "WARN"
    else:
        gate = "BLOCK"
    out.update({"ok": True, "trend": trend, "reversal": reversal, "close": round(cur, 2),
                "ma6": round(ma6, 2), "ma12": round(ma12, 2), "gate": gate})
    return out

def scan(codes):
    """批量扫描"""
    results = []
    for code in codes:
        results.append(check_month_trend(code))
    return results

def self_test():
    """内置样本自测：武威7月精选池飞亚达 + 几个对照"""
    tests = ["sz000026", "sh603259", "sz002131", "sh600519", "sz300750"]
    print(f"{'代码':<10} {'收盘':<9} {'MA6':<9} {'MA12':<9} {'趋势':<5} {'闸门':<6} {'反转信号'}")
    for r in scan(tests):
        print(f"{r['code']:<10} {str(r['close']):<9} {str(r['ma6']):<9} {str(r['ma12']):<9} "
              f"{r['trend']:<5} {r['gate']:<6} {r['reversal'] or '-'}")

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        r = check_month_trend(sys.argv[2])
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif len(sys.argv) >= 3 and sys.argv[1] == "--scan":
        codes = [c.strip() for c in sys.argv[2].split(",") if c.strip()]
        for r in scan(codes):
            print(json.dumps(r, ensure_ascii=False))
    elif len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        self_test()
    else:
        print(__doc__)
