#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monthly_macd_monitor.py —— 上证月线MACD死叉监控（Seaborg方法论）
============================================================
核心：上证综指月线 MACD(12,26,9) 状态监控
  - 柱体 = 2×(DIF-DEA)，柱萎缩→死叉临界，柱转负→确认死叉
  - 历史上：月线高位死叉=牛市终点（2022-01/2015-10），低位死叉=深熊（2023-08/2018-03）
  - 2024-09 月线金叉=本轮牛市起点；2026-08 柱体+5（死叉临界）

输出：outputs/monthly_macd_latest.json（供盘前报告引用）
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]


def cli(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def parse_monthly(txt, limit=60):
    """解析月线K线（升序），返回 [{date, close}]"""
    rows = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and re.match(r"^\|\s*20\d{2}-\d{2}", s):
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 6 and re.match(r"^\d{4}-\d{2}", parts[0]):
                try:
                    rows.append({"date": parts[0], "close": float(parts[3])})
                except ValueError:
                    pass
    rows.sort(key=lambda r: r["date"])
    return rows[-limit:]


def ema_series(vals, n):
    k = 2 / (n + 1)
    e = vals[0]
    out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def calc_macd(closes):
    """返回 (dif, dea, macd_hist, crossings)"""
    if len(closes) < 30:
        return None, None, None, []
    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema_series(dif, 9)
    hist = [2 * (d - e) for d, e in zip(dif, dea)]
    # 金叉/死叉点
    crossings = []
    for i in range(1, len(dif)):
        if dif[i - 1] <= dea[i - 1] and dif[i] > dea[i]:
            crossings.append({"date": None, "type": "金叉", "index": i})
        elif dif[i - 1] >= dea[i - 1] and dif[i] < dea[i]:
            crossings.append({"date": None, "type": "死叉", "index": i})
    return dif, dea, hist, crossings


def main():
    txt = cli(["kline", "sh000001", "--period", "month", "--limit", "60"])
    rows = parse_monthly(txt)
    if len(rows) < 30:
        print("[ERR] 月线数据不足", file=sys.stderr)
        sys.exit(1)

    closes = [r["close"] for r in rows]
    dif, dea, hist, crossings = calc_macd(closes)
    if dif is None:
        print("[ERR] MACD计算失败", file=sys.stderr)
        sys.exit(1)

    # 补 crossings 日期
    for c in crossings:
        c["date"] = rows[c["index"]]["date"]

    i = len(dif) - 1
    cur_dif, cur_dea, cur_hist = dif[i], dea[i], hist[i]
    prev_hist = hist[i - 1] if i >= 1 else 0
    cur_date = rows[i]["date"]
    cur_close = closes[i]

    # 状态判定
    if cur_dif > cur_dea and cur_hist > 0:
        if prev_hist > 0 and cur_hist < prev_hist * 0.3:
            status = "🔴 死叉临界（柱体萎缩至高位30%以下）"
        elif cur_hist < 5:
            status = "🟠 死叉临界（柱体接近零轴）"
        else:
            status = "🟢 金叉维持（柱体为正）"
    else:
        status = "🔴 已死叉（DIF<DEA）"

    # 近12月柱体趋势
    hist_trend = [round(h, 1) for h in hist[-12:]]
    # 历史金叉死叉（近2年）
    recent_cross = [c for c in crossings if c["date"] >= "2024-01"][-6:]

    js = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "index_date": cur_date,
        "close": round(cur_close, 2),
        "dif": round(cur_dif, 2),
        "dea": round(cur_dea, 2),
        "hist": round(cur_hist, 2),
        "hist_prev": round(prev_hist, 2),
        "status": status,
        "hist_trend_12m": hist_trend,
        "recent_cross": recent_cross,
    }
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/monthly_macd_latest.json", "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1)

    print(f"[OK] 上证月线MACD {cur_date}: DIF={cur_dif:.1f} DEA={cur_dea:.1f} 柱={cur_hist:.1f} → {status}")
    print(f"      近12月柱体: {hist_trend}")
    print(f"      近2年金叉死叉: {[(c['date'], c['type']) for c in recent_cross]}")


if __name__ == "__main__":
    main()
