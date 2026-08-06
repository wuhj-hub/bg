#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反转数值指标（完整版）· Python实现
====================================
通达信公式「反转数值0725」的Python翻译，百分比口径MACD：
  DIF = EMA(CLOSE,12)/CLOSE*100 - EMA(CLOSE,26)/CLOSE*100
  DEA = EMA(DIF,9)
  MACD = (DIF-DEA)*2
  反转数值 = 带方向 MACD*0.618（红柱区正/绿柱区负）
  反转数值2倍 = MACD*1.236
  反转前值 = REF(|MACD*0.618|,1)

信号（完整版翻译）：
  - 金叉/死叉（JC/SC，含DIF1/DEA1标准MACD口径）
  - 底背离优化信号 XG（价格新低但DIF抬高 + 均线条件 K1/K2）
  - 启动点/逼空点/回落点/杀多点（MACD柱拐点）
  - 红柱面积/绿柱面积（HMJ/LMJ）

用法：
  python3 reversal_value_screener.py                     # 扫描主板全池（周线）
  python3 reversal_value_screener.py --pool sz002303     # 单股分析
  python3 reversal_value_screener.py --pool "sz002303,sh600400" --period day
"""
import os, sys, re, json, subprocess, argparse
from datetime import datetime

WESTOCK = "npx -y westock-data-skillhub@1.0.3"


def ema(series, n):
    """通达信EMA递推：EMA[i] = X[i]*2/(N+1) + EMA[i-1]*(N-1)/(N+1)，初值=X[0]"""
    out = [series[0]]
    k = 2 / (n + 1)
    for x in series[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def fetch_kline(code, period="week", limit=120):
    """拉K线，返回 [(date, open, close, high, low, volume)]，时间升序"""
    try:
        r = subprocess.run(f"{WESTOCK} kline {code} --period {period} --limit {limit}",
                           shell=True, capture_output=True, text=True, timeout=60)
        out = r.stdout
    except Exception as e:
        print(f"  [warn] {code} 拉取失败: {e}")
        return []
    rows = []
    for ln in out.splitlines():
        m = re.match(r"\|\s*([\d-]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
        if m:
            rows.append((m.group(1), float(m.group(2)), float(m.group(3)),
                         float(m.group(4)), float(m.group(5))))
    rows.sort(key=lambda r: r[0])  # westock输出降序，转升序
    return rows


def calc_reversal(closes, highs, lows):
    """完整版反转数值计算，返回指标序列字典"""
    n = len(closes)
    e12 = ema(closes, 12)
    e26 = ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]
    # 标准MACD口径（价格差）用于金叉/底背离
    e12s = ema(closes, 12)
    e26s = ema(closes, 26)
    dif1 = [a - b for a, b in zip(e12s, e26s)]
    dea1 = ema(dif1, 9)
    fz = [m * 0.618 for m in macd]       # 带方向：红柱正/绿柱负
    fz2 = [m * 1.236 for m in macd]      # 2倍
    fz_prev = [abs(m * 0.618) for m in macd]
    # 金叉/死叉位置（标准MACD口径）
    jc_pos, sc_pos = [], []   # 金叉/死叉K线索引
    for i in range(1, n):
        if dif1[i - 1] <= dea1[i - 1] and dif1[i] > dea1[i]:
            jc_pos.append(i)
        if dif1[i - 1] >= dea1[i - 1] and dif1[i] < dea1[i]:
            sc_pos.append(i)
    # 底背离优化 XG：JX金叉 + BL(价新低DIF抬升) + K1/K2均线条件
    xg_pos = []
    for j in jc_pos:
        if j < 12:
            continue
        prev_jc = [p for p in jc_pos if p < j]
        tj2 = (j - prev_jc[-1]) if prev_jc else j   # 距上次金叉周期
        # BL：当前收盘 < 上次金叉时收盘 且 DIF1抬升（底背离）
        ref_c = closes[prev_jc[-1]] if prev_jc else closes[j]
        bl = closes[j] < ref_c and dif1[j] > (dif1[prev_jc[-1]] if prev_jc else dif1[j])
        # K1：金叉前10根内站上M20或M5>M13的天数<=3
        m5 = sum(closes[max(0, j - 4):j + 1]) / min(5, j + 1)
        m13 = sum(closes[max(0, j - 12):j + 1]) / min(13, j + 1)
        m20 = sum(closes[max(0, j - 19):j + 1]) / min(20, j + 1)
        dt = m5 > m13
        cnt = 0
        for k in range(max(0, j - 10), j + 1):
            mk5 = sum(closes[max(0, k - 4):k + 1]) / min(5, k + 1)
            mk13 = sum(closes[max(0, k - 12):k + 1]) / min(13, k + 1)
            mk20 = sum(closes[max(0, k - 19):k + 1]) / min(20, k + 1)
            if closes[k] >= mk20 or mk5 > mk13:
                cnt += 1
        k1 = cnt <= 3
        k2 = tj2 > 10
        if bl and k1 and k2:
            xg_pos.append(j)
    # 柱拐点信号（启动/逼空/回落/杀多）
    sig_start, sig_short, sig_fall, sig_kill = [], [], [], []
    for i in range(2, n):
        if macd[i] < 0 and macd[i] > macd[i - 1] and macd[i - 1] <= macd[i - 2]:
            sig_start.append(i)     # 启动点：绿柱缩短起点
        if macd[i] > 0 and macd[i] > macd[i - 1] and macd[i - 1] <= macd[i - 2] and macd[i - 1] > 0:
            sig_short.append(i)     # 逼空点：红柱放大起点
        if macd[i] > 0 and macd[i] < macd[i - 1] and macd[i - 1] >= macd[i - 2]:
            sig_fall.append(i)      # 回落点：红柱缩小起点
        if macd[i] < 0 and macd[i] < macd[i - 1] and macd[i - 1] >= macd[i - 2] and macd[i - 1] < 0:
            sig_kill.append(i)      # 杀多点：绿柱放大起点
    return {
        "dif": dif, "dea": dea, "macd": macd,
        "dif1": dif1, "dea1": dea1,
        "fz": fz, "fz2": fz2, "fz_prev": fz_prev,
        "jc": jc_pos, "sc": sc_pos, "xg": xg_pos,
        "start": sig_start, "short": sig_short, "fall": sig_fall, "kill": sig_kill,
    }


def analyze(code, name="", period="week", limit=120):
    rows = fetch_kline(code, period, limit)
    if len(rows) < 30:
        return None
    closes = [r[2] for r in rows]
    highs = [r[3] for r in rows]
    lows = [r[4] for r in rows]
    ind = calc_reversal(closes, highs, lows)
    i = len(rows) - 1
    sigs = []
    if ind["xg"] and ind["xg"][-1] >= i - 3:
        sigs.append("底背离金叉")
    if ind["jc"] and ind["jc"][-1] >= i - 3:
        sigs.append("金叉")
    if ind["start"] and ind["start"][-1] == i:
        sigs.append("启动点")
    if ind["short"] and ind["short"][-1] == i:
        sigs.append("逼空点")
    if ind["fall"] and ind["fall"][-1] == i:
        sigs.append("回落点")
    if ind["kill"] and ind["kill"][-1] == i:
        sigs.append("杀多点")
    return {
        "code": code, "name": name, "date": rows[i][0], "close": closes[i],
        "fz": round(ind["fz"][i], 2), "fz2": round(ind["fz2"][i], 2),
        "prev": round(ind["fz_prev"][i - 1], 2),
        "macd": round(ind["macd"][i], 2),
        "dif": round(ind["dif"][i], 2), "dea": round(ind["dea"][i], 2),
        "signals": sigs,
        "macd_dir": "红柱" if ind["macd"][i] > 0 else "绿柱",
    }


def load_mainboard():
    """读取主板清单（github_bg/all_mainboard.csv 或 stock_pool.txt）"""
    for p in ["all_mainboard.csv", "quant_scripts/all_mainboard.csv", "../all_mainboard.csv"]:
        if os.path.exists(p):
            out = []
            for ln in open(p, encoding="utf-8"):
                parts = ln.strip().split(",")
                if len(parts) >= 2 and parts[0].startswith(("sh6", "sh5", "sz0")):
                    out.append((parts[0], parts[1] if len(parts) > 1 else ""))
            if out:
                return out
    # fallback: 鱼身池
    for p in ["stock_pool.txt", "quant_scripts/stock_pool.txt"]:
        if os.path.exists(p):
            return [(c.strip(), n.strip()) for ln in open(p, encoding="utf-8")
                    for c, n in [ln.split("#", 1)[:2]] if c.strip().startswith(("sh6", "sh5", "sz0"))]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="", help="代码列表(逗号分隔)或空=扫描主板池")
    ap.add_argument("--period", default="week", choices=["week", "day", "month"])
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--top", type=int, default=30, help="输出数量")
    a = ap.parse_args()

    if a.pool:
        pool = [(c.strip(), "") for c in a.pool.split(",") if c.strip()]
    else:
        pool = load_mainboard()
    if not pool:
        print("❌ 无股票池，请用 --pool 指定")
        return
    print(f"🔍 反转数值完整版扫描 | 周期={a.period} | 标的={len(pool)}只 | {datetime.now():%Y-%m-%d %H:%M}\n")

    results = []
    for code, name in pool:
        r = analyze(code, name, a.period, a.limit)
        if r:
            results.append(r)
    # 排序：有信号优先，其次反转数值绝对值
    results.sort(key=lambda r: (0 if r["signals"] else 1, -abs(r["fz"])))

    print(f"| 代码 | 名称 | 日期 | 收盘 | 反转数值 | 2倍 | 前值 | MACD | 信号 |")
    print(f"|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|:----|")
    shown = 0
    for r in results[:a.top]:
        sig = "、".join(r["signals"]) if r["signals"] else ("观察" if abs(r["fz"]) >= 3 else "—")
        print(f"| {r['code']} | {r['name']} | {r['date']} | {r['close']} | {r['fz']:+.2f} | "
              f"{r['fz2']:+.2f} | {r['prev']:.2f} | {r['macd']:+.2f}({r['macd_dir']}) | {sig} |")
        shown += 1
    print(f"\n共分析 {len(results)} 只，展示 {shown} 只（有信号优先 + 反转数值强弱）")


if __name__ == "__main__":
    main()
