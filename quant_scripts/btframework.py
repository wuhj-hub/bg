#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""btframework.py —— 标准化回测框架（2026-09-24）

制定背景：9/24 的「rr 分档」回测因遗漏「风险归一化」而得出初版错误结论，
且体系中各类回测脚本各自为政、口径不一。本框架把回测收敛为统一口径。

═══ 回测七原则（每条都在代码中强制实现）═══
 1. 无未来函数：第 t 根决策，特征只用 rows[0..t]；成交从 t+1 开始
 2. 保守成交：同一根 K 线内既触止损又触目标 → 按「止损」计（不挑好的）
 3. 扣成本：默认双边 0.15%（印花税+佣金）
 4. 风险归一化：主指标用 R 倍数 = 收益% / 止损幅度%（不能只比百分比收益，
    否则「窄止损」会被误判成优势）
 5. 分档看单调性：不只看均值，要看档位是否单调（避免选择性报告）
 6. 样本量门槛：分档样本 < 300 不做结论（标注「样本不足」）
 7. 时间切分样本外：用前段调参、后段验证；两段结论不一致 = 不可信

用法：
    from btframework import DataFeed, atr_w, ma, simulate, stats, run_matrix
"""
import json
import statistics as st

DEFAULT_COST = 0.0015
MIN_SAMPLES = 300


# ═══════════ 数据层 ═══════════

class DataFeed:
    """标准化 K 线数据源。bars 为 [date, open, close, high, low, volume]"""

    def __init__(self, path, min_bars=300):
        self.path = path
        self.raw = json.load(open(path, encoding="utf-8"))
        self.min_bars = min_bars

    def codes(self):
        return [c for c, r in self.raw.items() if len(r) >= self.min_bars]

    def bars(self, code):
        return self.raw[code]

    def slice_time(self, lo_ratio=0.0, hi_ratio=1.0):
        """时间切分（原则7）：返回新的 DataFeed 视图，按 bar 序号区间裁剪"""
        out = {}
        for c, rows in self.raw.items():
            if len(rows) < self.min_bars:
                continue
            a = int(len(rows) * lo_ratio)
            b = int(len(rows) * hi_ratio)
            sub = rows[a:b]
            if len(sub) >= self.min_bars:
                out[c] = sub
        d = DataFeed.__new__(DataFeed)
        d.path = self.path
        d.raw = out
        d.min_bars = self.min_bars
        return d


# ═══════════ 指标层（原则1：只用 <= i）═══════════

def atr_w(rows, i, n=14):
    """Wilder ATR，截至第 i 根"""
    if i < n:
        return None
    trs = []
    for k in range(i - n + 1, i + 1):
        h, l, pc = rows[k][3], rows[k][4], rows[k - 1][2]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs) / len(trs)
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def ma(vals, i, n):
    return sum(vals[i - n + 1:i + 1]) / n if i >= n - 1 else None


def prev_high(rows, t, n):
    """前 n 日最高（不含当日；原则1）"""
    lo = max(0, t - n)
    seg = rows[lo:t]
    return max(r[3] for r in seg) if seg else None


def prev_low(rows, t, n):
    lo = max(0, t - n)
    seg = rows[lo:t]
    return min(r[4] for r in seg) if seg else None


# ═══════════ 模拟层（原则2/3）═══════════

def simulate(rows, t, stop, target, maxh=20, cost=DEFAULT_COST):
    """从 t+1 起持有 maxh 根。返回 (收益, 出场原因)
    - 同时触止损与目标 → 止损优先（保守）
    - 止损与目标均为 None 时按到期收盘
    """
    C = rows[t][2]
    if C <= 0:
        return None, "无效价"
    end = min(t + maxh, len(rows) - 1)
    for k in range(t + 1, end + 1):
        lo, hi = rows[k][4], rows[k][3]
        if stop is not None and lo <= stop:
            ex, why = stop, "止损"
            break
        if target is not None and hi >= target:
            ex, why = target, "目标"
            break
    else:
        ex, why = rows[end][2], "到期"
    ret = (ex - C) / C - cost
    return ret, why


# ═══════════ 统计层（原则4/5/6）═══════════

def stats(pairs):
    """pairs: [(ret, risk_pct), ...] → 统一口径统计"""
    if not pairs:
        return None
    rets = [p[0] for p in pairs]
    rs = [p[0] / p[1] if p[1] > 0 else 0 for p in pairs]
    n = len(rets)
    wins = [x for x in rets if x > 0]
    out = {
        "n": n, "mean_pct": st.mean(rets) * 100, "med_pct": st.median(rets) * 100,
        "win": len(wins) / n * 100 if n else 0,
        "meanR": st.mean(rs), "medR": st.median(rs),
        "stop_pct": st.mean([p[1] for p in pairs]) * 100 if pairs else 0,
    }
    if n < MIN_SAMPLES:
        out["thin"] = True
    return out


def fmt(tag, s, indent=0):
    pad = " " * indent
    if not s:
        return f"{pad}{tag:<26} 无样本"
    thin = " ⚠️样本不足" if s.get("thin") else ""
    return (f"{pad}{tag:<26}{s['n']:>8}{s['mean_pct']:>9.3f}{s['med_pct']:>9.3f}"
            f"{s['win']:>8.1f}{s['meanR']:>8.3f}{s['medR']:>8.3f}{s['stop_pct']:>8.1f}{thin}")


HEADER = f"{'档位/组合':<26}{'样本':>8}{'均值%':>9}{'中位%':>9}{'胜率%':>8}{'均R':>8}{'中R':>8}{'止损%':>8}"


# ═══════════ 组合层 ═══════════

def run_matrix(feed, setup_fn, maxh=20, month_filter=True, sample_every=1, verbose=True):
    """通用回测器。
    setup_fn(rows, t) → dict(stop=, target=, label=, extra=) 或 None
    返回 {label: [(ret, risk), ...]}
    """
    from collections import defaultdict
    acc = defaultdict(list)
    cnt = 0
    for code in feed.codes():
        rows = feed.bars(code)
        closes = [r[2] for r in rows]
        N = len(rows)
        for t in range(250, N - maxh - 1, sample_every):
            C = closes[t]
            if C <= 0.3:
                continue
            if month_filter:
                m = ma(closes, t, 120)
                mp = ma(closes, t - 20, 120)
                if not m or not mp or C <= m or m <= mp:
                    continue
            sp = setup_fn(rows, t)
            if not sp:
                continue
            stop, target = sp.get("stop"), sp.get("target")
            if not stop or stop <= 0 or C <= stop:
                continue
            ret, why = simulate(rows, t, stop, target, maxh)
            if ret is None:
                continue
            risk = (C - stop) / C
            acc[sp.get("label", "-")].append((ret, risk))
            cnt += 1
    if verbose:
        print(f"  [矩阵] 信号总数 {cnt}")
    return acc
