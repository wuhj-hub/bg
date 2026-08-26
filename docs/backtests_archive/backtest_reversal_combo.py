#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反转数值 · 多级别组合体系深度回测
==================================
核心假设：大周期定方向（环境过滤），小周期择时（信号触发）
- 环境分层: 周线红柱/绿柱 × 日线信号效果
- 环境分层: 日线红柱/绿柱 × 30m/5m信号效果
- 三重共振: 周线方向 + 日线启动 + 30m/5m确认
"""
import os, json
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "outputs", "reversal_bt_data")


def ema(series, n):
    out = [series[0]]
    k = 2 / (n + 1)
    for x in series[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def calc_macd(closes):
    n = len(closes)
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]
    return macd


def load_klines(code, tag):
    fp = os.path.join(DATA_DIR, f"{code}_{tag}.csv")
    if not os.path.exists(fp):
        return None
    closes = []
    is_min = tag.startswith("m")
    for ln in open(fp, encoding="utf-8"):
        p = ln.strip().split(",")
        if len(p) >= 5:
            try:
                closes.append(float(p[4] if is_min else p[2]))
            except ValueError:
                pass
    return closes if len(closes) >= 30 else None


def stat(rets):
    if len(rets) < 20:
        return None
    wins = [r for r in rets if r > 0]
    avg = sum(rets) / len(rets)
    pl = sum(r for r in rets if r > 0) / max(1, len(wins))
    ls = abs(sum(r for r in rets if r <= 0) / max(1, len(rets) - len(wins)))
    return {"n": len(rets), "wr": len(wins) / len(rets) * 100, "avg": avg,
            "med": sorted(rets)[len(rets) // 2], "pl_ratio": pl / ls if ls > 0 else 99,
            "worst": min(rets)}


def main():
    pool = [(ln.strip().split(",")[0], ln.strip().split(",")[1]) for ln in open(os.path.join(BASE, "hs300.csv"), encoding="utf-8")]
    print(f"沪深300: {len(pool)}只\n")

    results = {}

    # ═══ 测试1: 周线环境 × 日线信号 ═══
    env_red, env_green = [], []
    for code, name in pool:
        wc, dc = load_klines(code, "W"), load_klines(code, "D")
        if not wc or not dc:
            continue
        wmacd = calc_macd(wc)
        dmacd = calc_macd(dc)
        # 日线红柱启动信号
        for i in range(2, len(dc)):
            if dmacd[i] > 0 and dmacd[i - 1] <= 0 and i + 5 < len(dc):
                ret = (dc[i + 5] - dc[i]) / dc[i] * 100
                # 对应周线环境：找当日所在周（日线i对应周线索引≈i/5）
                wi = min(len(wmacd) - 1, i // 5)
                if wmacd[wi] > 0:
                    env_red.append(ret)
                else:
                    env_green.append(ret)
    results["日线信号@周线红柱环境(持5日)"] = stat(env_red)
    results["日线信号@周线绿柱环境(持5日)"] = stat(env_green)
    print("【测试1】周线环境过滤日线信号（持5日）")
    for k, s in results.items():
        if s:
            print(f"  {k}: n={s['n']} 胜率{s['wr']:.1f}% 平均{s['avg']:+.2f}% 盈亏比{s['pl_ratio']:.2f}")

    # ═══ 测试2: 日线环境 × 30m信号 ═══
    d_red, d_green = [], []
    for code, name in pool:
        dc, m30 = load_klines(code, "D"), load_klines(code, "m30")
        if not dc or not m30:
            continue
        dmacd = calc_macd(dc)
        m30macd = calc_macd(m30)
        # 每根30m对应日线状态（m30一天8根）
        for i in range(2, len(m30)):
            if m30macd[i] > 0 and m30macd[i - 1] <= 0 and i + 8 < len(m30):
                ret = (m30[i + 8] - m30[i]) / m30[i] * 100
                di = min(len(dmacd) - 1, i // 8)
                if dmacd[di] > 0:
                    d_red.append(ret)
                else:
                    d_green.append(ret)
    results["30m信号@日线红柱环境(持8根)"] = stat(d_red)
    results["30m信号@日线绿柱环境(持8根)"] = stat(d_green)
    print("\n【测试2】日线环境过滤30m信号（持8根=1天）")
    for k, s in [("30m信号@日线红柱环境(持8根)", stat(d_red)), ("30m信号@日线绿柱环境(持8根)", stat(d_green))]:
        if s:
            print(f"  {k}: n={s['n']} 胜率{s['wr']:.1f}% 平均{s['avg']:+.2f}% 盈亏比{s['pl_ratio']:.2f}")

    # ═══ 测试3: 日线环境 × 5m信号 ═══
    d5_red, d5_green = [], []
    for code, name in pool:
        dc, m5 = load_klines(code, "D"), load_klines(code, "m5")
        if not dc or not m5:
            continue
        dmacd = calc_macd(dc)
        m5macd = calc_macd(m5)
        for i in range(2, len(m5)):
            if m5macd[i] > 0 and m5macd[i - 1] <= 0 and i + 24 < len(m5):
                ret = (m5[i + 24] - m5[i]) / m5[i] * 100
                di = min(len(dmacd) - 1, i // 48)
                if dmacd[di] > 0:
                    d5_red.append(ret)
                else:
                    d5_green.append(ret)
    results["5m信号@日线红柱环境(持24根)"] = stat(d5_red)
    results["5m信号@日线绿柱环境(持24根)"] = stat(d5_green)
    print("\n【测试3】日线环境过滤5m信号（持24根=2小时）")
    for k, s in [("5m信号@日线红柱环境(持24根)", stat(d5_red)), ("5m信号@日线绿柱环境(持24根)", stat(d5_green))]:
        if s:
            print(f"  {k}: n={s['n']} 胜率{s['wr']:.1f}% 平均{s['avg']:+.2f}% 盈亏比{s['pl_ratio']:.2f}")

    # ═══ 测试4: 三重共振（周线方向+日线启动+30m启动）vs 无共振 ═══
    tri, no_tri = [], []
    for code, name in pool:
        wc, dc, m30 = load_klines(code, "W"), load_klines(code, "D"), load_klines(code, "m30")
        if not wc or not dc or not m30:
            continue
        wmacd, dmacd, m30macd = calc_macd(wc), calc_macd(dc), calc_macd(m30)
        w_red_now = wmacd[-1] > 0  # 最新周线红柱
        d_red_pos = set()
        for i in range(2, len(dc)):
            if dmacd[i] > 0 and dmacd[i - 1] <= 0:
                d_red_pos.add(i)  # 日线红柱启动日
        for i in range(2, len(m30)):
            if m30macd[i] > 0 and m30macd[i - 1] <= 0 and i + 8 < len(m30):
                ret = (m30[i + 8] - m30[i]) / m30[i] * 100
                di = min(len(dmacd) - 1, i // 8)
                if w_red_now and di in d_red_pos:
                    tri.append(ret)   # 三重共振
                elif not w_red_now and di not in d_red_pos:
                    no_tri.append(ret)  # 全无共振
    results["三重共振(周红+日启动+30m启动)持8根"] = stat(tri)
    results["零共振(周绿+日无启动+30m启动)持8根"] = stat(no_tri)
    print("\n【测试4】三重共振 vs 零共振（持8根30m=1天）")
    for k, s in [("三重共振(周红+日启动+30m启动)持8根", stat(tri)), ("零共振(周绿+日无启动+30m启动)持8根", stat(no_tri))]:
        if s:
            print(f"  {k}: n={s['n']} 胜率{s['wr']:.1f}% 平均{s['avg']:+.2f}% 盈亏比{s['pl_ratio']:.2f}")

    # ═══ 测试5: 周线环境 × 周线信号质量（确认周线为主级别）═══
    print("\n【测试5】周线信号本身质量（持1/2/4周）")
    for h in (1, 2, 4):
        rets = []
        for code, name in pool:
            wc = load_klines(code, "W")
            if not wc:
                continue
            wmacd = calc_macd(wc)
            for i in range(2, len(wc)):
                if wmacd[i] > 0 and wmacd[i - 1] <= 0 and i + h < len(wc):
                    rets.append((wc[i + h] - wc[i]) / wc[i] * 100)
        s = stat(rets)
        if s:
            print(f"  持{h}周: n={s['n']} 胜率{s['wr']:.1f}% 平均{s['avg']:+.2f}% 盈亏比{s['pl_ratio']:.2f}")

    with open(os.path.join(DATA_DIR, "combo_results.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in results.items() if v}, f, ensure_ascii=False, indent=1)
    print("\n✅ 已保存 combo_results.json")


if __name__ == "__main__":
    main()
