#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反转数值 · 2B强动能回调再启动信号筛选器
========================================
信号形态（国安股份30分钟示例）：
  ① 前期强动能：MACD红柱峰值超过 2×0.618×前期绿柱深度（X_3条件），
     或反转数值2倍值 ≥ 2.0（"2B"）
  ② 回调不破位：MACD从峰值回落，回调低点 > 前期绿柱深度（-X_2），
     最好不破0轴（红柱区内回调）或短暂破0快速收回
  ③ 再次启动：回调后 MACD 再次放大（MACD>REF且MACD>0），反转数值回升

信号输出分级：
  🔴 2B再启动（条件①②③全满足：回调后MACD重新放大）→ 买入信号
  🟡 2B回调中（条件①②满足：强动能+回调未破位，等待③确认）→ 观察信号
  🟢 2B已启动（条件①③满足：强动能+已启动）→ 趋势中

用法：
  python3 reversal_2b_screener.py --pool sz000839 --period m30   # 单股30分钟验证
  python3 reversal_2b_screener.py --pool "sz000839,sh600400" --period day
  python3 reversal_2b_screener.py --period week                  # 全池周线（默认沪深300）
"""
import os, sys, re, json, subprocess, argparse, urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
WESTOCK = "npx -y westock-data-skillhub@1.0.3"


def ema(series, n):
    out = [series[0]]
    k = 2 / (n + 1)
    for x in series[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def calc_ind(closes):
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]
    return macd


def fetch_kline(code, period="m30", limit=500):
    """拉K线: 分钟线用新浪(scale=5/10/30/60), 日/周线用westock"""
    rows = []
    if period.startswith("m"):
        scale = period[1:]
        try:
            url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
                   f"CN_MarketDataService.getKLineData?symbol={code}&scale={scale}&ma=no&datalen={limit}")
            r = subprocess.run(f"curl -s -m 20 '{url}'", shell=True, capture_output=True, text=True, timeout=30)
            m = re.search(r"var\((.*)\)\s*;?\s*$", r.stdout, re.S)
            if m:
                for d in json.loads(m.group(1)):
                    rows.append((d["day"], float(d["close"])))
        except Exception as e:
            print(f"  [warn] {code} 分钟线失败: {e}")
    else:
        try:
            r = subprocess.run(f"{WESTOCK} kline {code} --period {period} --limit 260",
                               shell=True, capture_output=True, text=True, timeout=60)
            for ln in r.stdout.splitlines():
                m = re.match(r"\|\s*([\d-]+)\s*\|\s*[\d.]+\s*\|\s*([\d.]+)", ln)
                if m:
                    rows.append((m.group(1), float(m.group(2))))
        except Exception as e:
            print(f"  [warn] {code} {period}失败: {e}")
    rows.sort(key=lambda r: r[0])
    return rows


def detect_2b(macd, closes, n, lookback=40, threshold=2.0):
    """
    检测最近一根K线是否处于2B形态。
    返回 (等级, 详情dict) 或 None
    等级: RED=2B再启动(买点) / YELLOW=2B回调中(观察) / GREEN=2B已启动(趋势)
    """
    i = n - 1
    if i < 30:
        return None
    seg = macd[max(0, i - lookback):i + 1]
    # 前期绿柱最深（排除当前段，找最近一次绿柱段）
    green_depths = [m for m in seg if m < 0]
    if not green_depths:
        return None
    x2 = abs(min(green_depths))  # 前期最深绿柱
    if x2 <= 0.1:
        return None
    # 前期红柱峰值（绿柱段之后）
    red_peak = max([m for m in seg if m > 0], default=0)
    # 条件①：红柱峰值超过 2×0.618×绿柱深度（X_3），或 2倍值≥threshold
    x3_line = 2 * 0.618 * x2
    cond1 = (red_peak > x3_line) or (red_peak * 1.236 >= threshold)
    if not cond1:
        return None
    # 条件②：当前回调低点（从峰值后）> 绿柱深度（不破位）
    peak_idx = seg.index(red_peak)
    after_peak = seg[peak_idx + 1:] if peak_idx + 1 < len(seg) else []
    pullback_low = min(after_peak) if after_peak else macd[i]
    cond2 = pullback_low > -x2  # 回调低点未跌破前期绿柱深度
    # 条件③：当前MACD>0 且 正在放大（再次启动）
    cond3 = macd[i] > 0 and macd[i] > macd[i - 1]
    # 当前状态
    if cond3 and macd[i] > 0:
        level = "RED"      # 再启动买点
    elif cond2 and macd[i] > 0:
        level = "YELLOW"   # 回调中未破位
    elif cond2:
        level = "YELLOW"
    else:
        level = None
    if level is None:
        return None
    return level, {
        "x2": round(x2, 2), "x3_line": round(x3_line, 2),
        "red_peak": round(red_peak, 2), "fz2_peak": round(red_peak * 1.236, 2),
        "pullback_low": round(pullback_low, 2),
        "macd": round(macd[i], 2), "fz": round(macd[i] * 0.618, 2),
        "close": closes[i], "date": None,
    }


def load_pool(pool_arg=""):
    if pool_arg:
        return [(c.strip(), "") for c in pool_arg.split(",") if c.strip()]
    rows = []
    fp = os.path.join(BASE, "hs300.csv")
    if os.path.exists(fp):
        for ln in open(fp, encoding="utf-8"):
            p = ln.strip().split(",")
            if len(p) >= 2 and p[0].startswith(("sh", "sz")):
                rows.append((p[0], p[1]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="", help="代码列表(逗号分隔)，默认沪深300")
    ap.add_argument("--period", default="day", choices=["m5", "m10", "m30", "m60", "day", "week", "month"])
    ap.add_argument("--lookback", type=int, default=40, help="检测窗口")
    ap.add_argument("--threshold", type=float, default=2.0, help="2B阈值(2倍值)")
    a = ap.parse_args()

    pool = load_pool(a.pool)
    print(f"🔍 反转数值2B信号扫描 | 级别={a.period} | 标的{len(pool)}只 | 2B阈值≥{a.threshold} | {datetime.now():%H:%M}")

    results = []
    for code, name in pool:
        rows = fetch_kline(code, a.period)
        if len(rows) < 40:
            continue
        closes = [r[1] for r in rows]
        macd = calc_ind(closes)
        det = detect_2b(macd, closes, len(closes), a.lookback, a.threshold)
        if det:
            level, d = det
            d["code"], d["name"], d["date"] = code, name, rows[-1][0]
            results.append((level, d))

    order = {"RED": 0, "YELLOW": 1}
    results.sort(key=lambda x: order.get(x[0], 9))
    for level, d in results:
        lvl_txt = {"RED": "🔴 2B再启动(买点)", "YELLOW": "🟡 2B回调中(观察)", "GREEN": "🟢 2B已启动"}[level]
        print(f"  {lvl_txt} | {d['code']} {d['name']} | {d['date']} 收{d['close']} | "
              f"MACD={d['macd']:+.2f} 反={d['fz']:+.2f} | 前期峰2B={d['fz2_peak']:.2f} "
              f"(X3线{d['x3_line']:.2f}) | 回调低点{d['pullback_low']:+.2f} vs 绿柱深度-{d['x2']:.2f}")
    print(f"\n共{len(results)}只触发2B形态（RED={sum(1 for l,_ in results if l=='RED')}, "
          f"YELLOW={sum(1 for l,_ in results if l=='YELLOW')}）")


if __name__ == "__main__":
    main()
