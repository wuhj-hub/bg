#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""research_panic_rebound.py —— 「极端恐慌日之后」反弹统计（研究脚本，不接入 CI）

问题：2026-10-23 盘前判「防守/不开新仓」，当日上证 +0.89%、创业板 +4.16% 普涨。
事后追问：**恐慌日之后到底该不该抢反弹？** 本脚本给出统计答案。

方法
----
数据：上证指数全历史日线（同花顺 v6 line hs_1A0001，8748 根，1990-12-19 ~ 今）。
信号分档（在 T 日收盘判定，T+N 收益按 T 日收盘价买入计算）：
  · 单日跌幅 ≤ -1.2% / -1.5% / -2.0% / -3.0%
  · 连 3 日累计跌幅 ≤ -4% / -6%
输出：T+1/3/5/10 的均值、中位、胜率，以及与全样本基线（同样持有期）的超额。

结论（2026-10-23 实测）
----------------------
1. 单日 -1.2%~-2% 的次日胜率 55.4~55.8%（基线 52.6%），**但 T+3/T+5 均值超额为负**
   （-0.06 ~ -0.37pct）→ 抢反弹"赢面略高、赚得少"，右偏分布（中位为负）。
2. 只有**单日 ≤-3%**（n=337）或**连 3 日累计 ≤-6%**（n=250）时，T+5/T+10 才有正超额
   （+0.34 ~ +1.45pct）→ 尾部越极端越有效。
3. 分年代：「单日 ≤-1.5%」的 T+1 胜率 ≤2009 53.7% / 2010-2019 61.7% / 2020+ 56.0%，
   优势在 2020 后减弱，但 2020+ 的 T+5 超额转正（+0.32pct）。

用法
----
python3 quant_scripts/research_panic_rebound.py            # 默认同花顺取数（需 fetch.py 可用）
"""
import sys, os, json, statistics as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from fetch import ext_ths_kline
except Exception as e:                                    # pragma: no cover
    ext_ths_kline = None
    _ERR = str(e)
else:
    _ERR = ""

THS_INDEX_CODE = "1A0001"      # 同花顺上证指数代码（hs_1A0001）


def load_bars(path=None):
    if path and os.path.exists(path):
        return json.load(open(path))
    if ext_ths_kline is None:
        raise SystemExit("fetch.ext_ths_kline 不可用：%s" % _ERR)
    return ext_ths_kline(THS_INDEX_CODE, period="day")


def analyse(bars):
    d = [b["date"] for b in bars]
    c = [b["close"] for b in bars]
    n = len(c)
    ret = [None] + [(c[i] - c[i - 1]) / c[i - 1] * 100 for i in range(1, n)]

    def fwd(i, k):
        j = i + k
        return None if j >= n or i < 0 else (c[j] - c[i]) / c[i] * 100

    def stats(sig, horizon):
        xs = [x for x in (fwd(i, horizon) for i in range(n - 1) if sig(i)) if x is not None]
        if not xs:
            return None
        return {"n": len(xs), "mean": st.mean(xs), "med": st.median(xs),
                "win": 100 * sum(1 for x in xs if x > 0) / len(xs)}

    base = {h: stats(lambda i: True, h) for h in (1, 3, 5, 10)}
    sigs = {
        "单日≤-1.2%": lambda i: ret[i] is not None and ret[i] <= -1.2,
        "单日≤-1.5%": lambda i: ret[i] is not None and ret[i] <= -1.5,
        "单日≤-2.0%": lambda i: ret[i] is not None and ret[i] <= -2.0,
        "单日≤-3.0%": lambda i: ret[i] is not None and ret[i] <= -3.0,
        "连3日≤-4%": lambda i: i >= 3 and all(x is not None for x in ret[i - 2:i + 1]) and sum(ret[i - 2:i + 1]) <= -4,
        "连3日≤-6%": lambda i: i >= 3 and all(x is not None for x in ret[i - 2:i + 1]) and sum(ret[i - 2:i + 1]) <= -6,
    }
    return d, c, n, ret, fwd, base, sigs, stats


def main():
    bars = load_bars(sys.argv[1] if len(sys.argv) > 1 else None)
    d, c, n, ret, fwd, base, sigs, stats = analyse(bars)
    print("样本：%s ~ %s，共 %d 个交易日" % (d[0], d[-1], n))
    print("\n[基线]")
    for h in (1, 3, 5, 10):
        b = base[h]
        print("  T+%-2d 均值%+.3f%% 中位%+.3f%% 胜率%.1f%% n=%d" % (h, b["mean"], b["med"], b["win"], b["n"]))
    for name, sig in sigs.items():
        print("\n[%s]" % name)
        for h in (1, 3, 5, 10):
            s = stats(sig, h)
            if not s:
                continue
            b = base[h]
            print("  T+%-2d 均值%+.3f%% (超额%+.3f) 中位%+.3f%% 胜率%.1f%% (基线%.1f) n=%d"
                  % (h, s["mean"], s["mean"] - b["mean"], s["med"], s["win"], b["win"], s["n"]))
    print("\n[分年代 · 单日≤-1.5% 的 T+1/T+5]")
    for e, lo, hi in (("≤2009", 0, 2009), ("2010-2019", 2010, 2019), ("2020+", 2020, 2100)):
        sg = lambda i, lo=lo, hi=hi: ret[i] is not None and ret[i] <= -1.5 and lo <= int(d[i][:4]) <= hi
        s1, s5 = stats(sg, 1), stats(sg, 5)
        if s1:
            print("  %-10s n=%4d  T+1 %+.3f%%(胜%4.1f%%)  T+5 %+.3f%%"
                  % (e, s1["n"], s1["mean"], s1["win"], s5["mean"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
