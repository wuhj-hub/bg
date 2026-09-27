#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xihu_breadth.py —— 西湖广度温度计（下雨图 + 大盘量化）
=========================================================
方法论来源：西湖区的孩纸《西湖大盘量化分析系统升级版（解决无卡顿）》(2020-03-04)
  把通达信「横向统计函数 + 拓展数据」方案，复刻为纯 Python 的
    信号层（逐股 0/1）→ 统计层（全市场计数）→ 展示层（广度占比 / 下雨图）

四个信号（口径与原文公式一致）：
  强势股  : CLOSE / HHV(HIGH,250) > 0.9
  第二阶段: C>MA50>MA150>MA200 且 MA200 连升 N 日 且 C/LLV(C,200)>1.3 且 C/HHV(C,200)>T
  新高    : HIGH = HHV(HIGH,250) 且 上市 > 60 日
  新低    : LOW < 前 250 日最低价（不含当日）

三张广度图：
  QSG%  强势股占比（原文参考线 6 / 20）
  EJD%  第二阶段占比
  下雨图净值 = 新高数 − 新低数

数据源：westock-data-skillhub 批量日K（默认前复权，--limit 260）
输出：
  outputs/xihu_breadth_{date}.md          报告
  outputs/xihu_breadth_latest.json         结构化 JSON（供盘前/复盘引用）
  outputs/xihu_breadth_history.json        按日累积（供趋势/画净值曲线）
  outputs/xihu_breadth_chart.png           净值曲线图（--chart / --chart-only）

用法：
  python3 xihu_breadth.py --list all_mainboard.csv --batch 40                              # 全量当日
  python3 xihu_breadth.py --list all_mainboard.csv --batch 40 --limit 800 --backfill 550 --chart  # 回算2年+画图
  python3 xihu_breadth.py --chart-only                                                     # 仅用已有 history 画图
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
DATA_ROW = re.compile(r"^(sh|sz|bj)\d{6}$")


def run(args, timeout=150):
    """执行 westock CLI，返回原始输出（含重试）。"""
    for i in range(4):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(3 * (i + 1))
    return ""


def norm_code(code):
    """纯数字/带前缀 code -> sh/sz/bj 前缀。"""
    code = code.strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith(("6", "9", "5")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def parse_kline(raw):
    """解析批量K线输出 -> {wcode: [(date, open, close, high, low), ...] 按日期升序}
    批量列序: symbol|date|open|last|high|low|volume|amount|exchange，且 date 降序输出。"""
    out = {}
    for ln in raw.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 6 or not DATA_ROW.match(parts[0]):
            continue
        try:
            row = (parts[1], float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5]))
        except ValueError:
            continue
        out.setdefault(parts[0], []).append(row)
    for k in out:
        out[k].sort(key=lambda x: x[0])  # 升序（最旧在前）
    return out


def _ma(seq, i, n):
    """以 i 结尾、长度 n 的均值；数据不足返回 None。"""
    if i + 1 < n:
        return None
    return sum(seq[i - n + 1:i + 1]) / n


def eval_signals(kl, p):
    """对单只股票计算四信号（最新一日）。kl 为升序 (date,open,close,high,low)。"""
    n = len(kl)
    if n < 2:
        return None
    highs = [r[3] for r in kl]
    lows = [r[4] for r in kl]
    closes = [r[2] for r in kl]
    c_last = closes[-1]
    h_last = highs[-1]
    l_last = lows[-1]
    if not c_last or c_last <= 0:
        return None

    win = p["window"]
    w = min(win, n)
    hhv_h = max(highs[-w:])

    # 强势股：收盘价在 250 日最高价的 90% 以内
    strong = (c_last / hhv_h) > p["strong_thr"] if hhv_h else False

    # 新高：当日最高价 = 250 日最高价，且上市 > 60 日
    new_high = (h_last >= hhv_h - 1e-6) and (n > 60)

    # 新低：当日最低价 < 前 250 日最低价（不含当日）
    new_low = False
    if n >= win + 1:
        new_low = l_last < min(lows[-win - 1:-1])

    # 第二阶段（Minervini 趋势模板变体）
    stage2 = False
    if n >= 220:
        ma50 = _ma(closes, n - 1, 50)
        ma150 = _ma(closes, n - 1, 150)
        ma200 = _ma(closes, n - 1, 200)
        if ma50 and ma150 and ma200:
            trend = (c_last > ma50 > ma150 > ma200)
            rising = True
            for i in range(n - p["stage2_n"], n):
                m_cur = _ma(closes, i, 200)
                m_prev = _ma(closes, i - 1, 200)
                if m_cur is None or m_prev is None or not (m_cur > m_prev):
                    rising = False
                    break
            c200_l = min(closes[-min(200, n):])
            c200_h = max(closes[-min(200, n):])
            gain_ok = (c_last / c200_l) > 1.3 if c200_l else False
            near_ok = (c_last / c200_h) > p["stage2_t"] if c200_h else False
            stage2 = trend and rising and gain_ok and near_ok

    return {
        "close": round(c_last, 3),
        "pct_to_high": round(c_last / hhv_h * 100, 1) if hhv_h else None,
        "strong": strong, "stage2": stage2,
        "new_high": new_high, "new_low": new_low, "bars": n,
    }


def load_list(path):
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if row and row[0].strip() and row[0].strip().lower() != "code":
                name = row[1].strip() if len(row) > 1 else ""
                out.append((row[0].strip(), name))
    return out


def _apply(chunk, codes, data, result, p):
    """把一批返回结果并入 result，返回本批有效数。"""
    got = 0
    for (code, name), wcode in zip(chunk, codes):
        if result.get(code, {}).get("strong") is not None:
            got += 1
            continue
        kl = data.get(wcode, [])
        sig = eval_signals(kl, p) if kl else None
        if sig:
            got += 1
            sig["name"] = name or result.get(code, {}).get("name", "")
            result[code] = sig
        else:
            prev = result.get(code, {})
            result[code] = {"name": name or prev.get("name", ""), "strong": None,
                            "stage2": None, "new_high": None, "new_low": None, "bars": len(kl)}
    return got


def scan(stocks, p, cache=None):
    """批量扫描，返回 {code: {name, ...signals}}。
    runner 上 westock 批量偶发丢股票 → 收集缺口后小批(10)补取，仍缺则逐只补。
    cache 不为 None 时把每只原始K线存入 cache（供历史回算）。"""
    result = {}
    n = len(stocks)
    batch = p["batch"]
    lacks = []

    def _keep(data):
        if cache is not None:
            cache.update(data)

    for i in range(0, n, batch):
        chunk = stocks[i:i + batch]
        codes = [norm_code(c) for c, _ in chunk]
        raw = run(["kline", ",".join(codes), "--period", "day", "--limit", str(p["limit"])])
        data = parse_kline(raw)
        _keep(data)
        got = _apply(chunk, codes, data, result, p)
        missing = [c for c, w in zip(chunk, codes) if not data.get(w)]
        print(f"[{i + len(chunk)}/{n}] 本批有效 {got}/{len(chunk)}"
              + (f" | ⚠️缺 {len(missing)} 只" if missing else ""), flush=True)
        lacks.append((chunk, missing))

    # ── 缺口补齐：小批(10)复取 → 仍缺逐只补
    miss_stocks = [c for _, m in lacks for c in m]
    if miss_stocks:
        print(f"[补齐] 共 {len(miss_stocks)} 只缺数据，启动补偿…", flush=True)
        for j in range(0, len(miss_stocks), 10):
            sub = miss_stocks[j:j + 10]
            codes = [norm_code(c[0]) for c in sub]
            raw = run(["kline", ",".join(codes), "--period", "day", "--limit", str(p["limit"])])
            data = parse_kline(raw)
            _keep(data)
            _apply(sub, codes, data, result, p)
        still = [c for c in miss_stocks if result.get(c[0], {}).get("strong") is None]
        for (code, name) in still:
            wcode = norm_code(code)
            raw = run(["kline", wcode, "--period", "day", "--limit", str(p["limit"])])
            data = parse_kline(raw)
            _keep(data)
            _apply([(code, name)], [wcode], data, result, p)
        fixed = sum(1 for c in miss_stocks if result.get(c[0], {}).get("strong") is not None)
        print(f"[补齐] 成功补回 {fixed}/{len(miss_stocks)} 只", flush=True)
    return result


def aggregate(result):
    """统计层：全市场计数。"""
    valid = {c: v for c, v in result.items() if v.get("strong") is not None}
    n = len(valid)
    strong = sum(1 for v in valid.values() if v["strong"])
    stage2 = sum(1 for v in valid.values() if v["stage2"])
    new_high = sum(1 for v in valid.values() if v["new_high"])
    new_low = sum(1 for v in valid.values() if v["new_low"])
    return {
        "total": n, "strong": strong, "stage2": stage2,
        "new_high": new_high, "new_low": new_low,
        "qsg_pct": round(strong / n * 100, 2) if n else 0.0,
        "ejd_pct": round(stage2 / n * 100, 2) if n else 0.0,
        "net_high": new_high - new_low,
    }


def eval_series(kl, p, days):
    """对单只股票回算最近 days 个交易日的四信号，返回 [(date, strong, stage2, new_high, new_low), ...]。
    与 eval_signals 同口径，用 numpy 向量化加速。"""
    import numpy as np
    n = len(kl)
    if n < 2:
        return []
    C = np.array([r[2] for r in kl], dtype=float)
    H = np.array([r[3] for r in kl], dtype=float)
    L = np.array([r[4] for r in kl], dtype=float)
    D = [r[0] for r in kl]
    win = p["window"]
    csum = np.concatenate([[0.0], np.cumsum(C)])

    def ma(i, k):
        if i + 1 < k:
            return None
        return (csum[i + 1] - csum[i + 1 - k]) / k

    out = []
    start = max(0, n - days)
    for i in range(start, n):
        lo = max(0, i - win + 1)
        hhv_h = H[lo:i + 1].max()
        strong = bool(hhv_h and C[i] / hhv_h > p["strong_thr"])
        new_high = bool(hhv_h and H[i] >= hhv_h - 1e-6 and (i + 1) > 60)
        new_low = bool(i >= win and L[i] < L[i - win:i].min())
        stage2 = False
        if i + 1 >= 220:
            m50, m150, m200 = ma(i, 50), ma(i, 150), ma(i, 200)
            if m50 and m150 and m200 and C[i] > m50 > m150 > m200:
                rising = True
                for j in range(i - p["stage2_n"] + 1, i + 1):
                    a, b = ma(j, 200), ma(j - 1, 200)
                    if a is None or b is None or not a > b:
                        rising = False
                        break
                if rising:
                    c200l = C[max(0, i - 199):i + 1].min()
                    c200h = C[max(0, i - 199):i + 1].max()
                    if c200l and c200h and (C[i] / c200l > 1.3) and (C[i] / c200h > p["stage2_t"]):
                        stage2 = True
        out.append((D[i], strong, stage2, new_high, new_low))
    return out


def build_history(cache, p, days, existing=None):
    """对 cache 中所有股票回算最近 days 日广度序列，合并 existing，返回按日期升序的 dict。"""
    daily = {}
    for kl in cache.values():
        for (d, s, s2, nh, nl) in eval_series(kl, p, days):
            a = daily.setdefault(d, [0, 0, 0, 0, 0])
            a[0] += 1
            a[1] += 1 if s else 0
            a[2] += 1 if s2 else 0
            a[3] += 1 if nh else 0
            a[4] += 1 if nl else 0
    hist = dict(existing or {})
    for d, (n, s, s2, nh, nl) in daily.items():
        if n < 50:      # 样本过少（早期数据不足）不记录
            continue
        hist[d] = {"qsg_pct": round(s / n * 100, 2), "ejd_pct": round(s2 / n * 100, 2),
                   "new_high": nh, "new_low": nl, "net_high": nh - nl, "total": n}
    return {k: hist[k] for k in sorted(hist.keys())}


def make_chart(history, out_png, title="西湖广度温度计", turn_run=3):
    """把历史序列画成净值曲线图（下雨图净值柱 + 强势股/第二阶段占比线）。
    拐点：净值由负转正=▲（转正后连续 ≥turn_run 日为正记"确认"，实心大红▲；否则空心△）；由正转负=▽。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    for _f in ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
               "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
               "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"):
        try:
            fm.fontManager.addfont(_f)
        except Exception:
            pass
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "Noto Sans CJK JP", "WenQuanYi Zen Hei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    ks = sorted(history.keys())
    if len(ks) < 2:
        return False
    dates = [k[5:] for k in ks]
    net = [history[k].get("net_high", 0) for k in ks]
    qsg = [history[k].get("qsg_pct", 0) for k in ks]
    ejd = [history[k].get("ejd_pct", 0) for k in ks]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True,
                                   gridspec_kw={"height_ratios": [1.2, 1]})
    colors = ["#d62728" if v >= 0 else "#2ca02c" for v in net]
    ax1.bar(range(len(net)), net, color=colors, width=0.75)
    ax1.axhline(0, color="#555", lw=0.8)
    ax1.set_ylabel("下雨图净值（新高-新低）")
    ax1.set_title(f"{title} · 下雨图净值曲线（红=晴/绿=雨；实心▲=确认转正(连续≥{turn_run}日) △=未确认 ▽=转负）")
    ax1.grid(alpha=0.25)
    # ── 拐点标注：新高/新低交叉（净值由负转正 ↑ / 由正转负 ↓）
    up_idx = [i for i in range(1, len(net)) if net[i] > 0 and net[i - 1] <= 0]
    dn_idx = [i for i in range(1, len(net)) if net[i] <= 0 and net[i - 1] > 0]
    conf_up = [i for i in up_idx if all(net[j] > 0 for j in range(i, min(i + turn_run, len(net))))]
    conf_set = set(conf_up)
    for i in up_idx:
        if i in conf_set:
            ax1.plot([i], [max(net[i], 2)], marker="^", ms=12, color="#b71c1c", zorder=6)
            ax1.annotate("↑" + dates[i], xy=(i, max(net[i], 0)), xytext=(0, 15),
                         textcoords="offset points", ha="center", fontsize=8,
                         color="#b71c1c", fontweight="bold", zorder=7)
        else:
            ax1.axvline(i, color="#d62728", ls=":", lw=0.7, alpha=0.3)
            ax1.plot([i], [max(net[i], 1)], marker="^", ms=6, mfc="white", mec="#ef9a9a", mew=1.2, zorder=5)
    for i in dn_idx:
        ax1.axvline(i, color="#2ca02c", ls=":", lw=0.7, alpha=0.3)
        ax1.plot([i], [min(net[i], -1)], marker="v", ms=6, color="#a5d6a7", zorder=4)
    print(f"[拐点] 净值转正{len(up_idx)}次（其中确认≥{turn_run}日 {len(conf_up)}次）: "
          + "、".join(ks[i] for i in up_idx))
    print(f"[拐点] 净值转负{len(dn_idx)}次: " + "、".join(ks[i] for i in dn_idx))
    ax2.plot(range(len(qsg)), qsg, color="#d62728", marker="o", ms=2, lw=1.2, label="强势股占比 QSG%")
    ax2.plot(range(len(ejd)), ejd, color="#1f77b4", marker="o", ms=2, lw=1.2, label="第二阶段占比 EJD%")
    ax2.axhline(6, color="#999", ls="--", lw=0.8)
    ax2.axhline(20, color="#999", ls="--", lw=0.8)
    ax2.set_ylabel("占比 %")
    ax2.legend(loc="upper left", fontsize=9)
    ax2.grid(alpha=0.25)
    step = max(1, len(dates) // 15)
    ax2.set_xticks(range(0, len(dates), step))
    ax2.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=45, fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)
    return True


def judge(agg):
    """展示层：给出广度定性判断。"""
    q = agg["qsg_pct"]
    if q >= 20:
        q_level = "🔥 极热（强势股占比>20%，原文上轨）"
    elif q >= 6:
        q_level = "🟢 健康（强势股占比 6%~20%）"
    else:
        q_level = "❄️ 偏冷（强势股占比<6%，原文下轨）"
    net = agg["net_high"]
    if net > 0:
        rain = "☀️ 晴（新高 > 新低）"
    elif net == 0:
        rain = "⛅ 阴（新高 = 新低）"
    else:
        rain = "🌧️ 雨（新高 < 新低，广度收缩）"
    return {"qsg_level": q_level, "rain": rain}


def build_report(agg, result, jd, date_str, p):
    top_high = sorted([(c, v) for c, v in result.items() if v.get("new_high")],
                      key=lambda x: -(x[1].get("pct_to_high") or 0))[:20]
    stage2_list = sorted([(c, v) for c, v in result.items() if v.get("stage2")],
                         key=lambda x: -(x[1].get("pct_to_high") or 0))

    L = []
    L.append(f"# 🌧️ 西湖广度温度计（下雨图 + 大盘量化）— {date_str}\n")
    L.append(f"> 口径：沪深主板 {agg['total']} 只有效（日K口径，前复权）｜"
             f"参数 强势>0.9 · 第二阶段 N={p['stage2_n']}/T={p['stage2_t']} · 窗口{p['window']}日\n")
    L.append("## 核心数据\n")
    L.append("| 指标 | 数值 | 说明 |")
    L.append("|---|---|---|")
    L.append(f"| 强势股占比 QSG% | **{agg['qsg_pct']}%**（{agg['strong']}只） | 收盘≥250日高点的90% |")
    L.append(f"| 第二阶段占比 EJD% | **{agg['ejd_pct']}%**（{agg['stage2']}只） | 多头排列+均线抬升+贴近高点 |")
    L.append(f"| 新高家数 | {agg['new_high']} | 创250日新高 |")
    L.append(f"| 新低家数 | {agg['new_low']} | 创250日新低 |")
    L.append(f"| **下雨图净值** | **{agg['net_high']:+d}** | 新高−新低 |")
    L.append("")
    L.append("## 广度判读\n")
    L.append(f"- 强势股温度：{jd['qsg_level']}（参考线 6 / 20）")
    L.append(f"- 下雨图天气：{jd['rain']}")
    L.append("")

    L.append(f"## 创新高个股（{len(top_high)}只，展示前20）\n")
    L.append("| 代码 | 名称 | 收盘 | 距250日高点 |")
    L.append("|---|---|---|---|")
    for c, v in top_high:
        L.append(f"| {c} | {v['name']} | {v['close']} | {v['pct_to_high']}% |")
    L.append("")

    L.append(f"## 第二阶段个股（{len(stage2_list)}只，展示前25）\n")
    L.append("| 代码 | 名称 | 收盘 | 距250日高点 |")
    L.append("|---|---|---|---|")
    for c, v in stage2_list[:25]:
        L.append(f"| {c} | {v['name']} | {v['close']} | {v['pct_to_high']}% |")
    if len(stage2_list) > 25:
        L.append(f"| ... 其余 {len(stage2_list) - 25} 只省略 |")
    L.append("")
    L.append("---")
    L.append("*本报告由 xihu_breadth.py 自动生成｜复刻自「西湖大盘量化分析系统」｜量化规律总结非投资建议*")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="all_mainboard.csv")
    ap.add_argument("--stocks", help="逗号分隔的代码，直接指定股票池（测试用）")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--limit", type=int, default=260)
    ap.add_argument("--window", type=int, default=250)
    ap.add_argument("--strong-thr", type=float, default=0.9)
    ap.add_argument("--stage2-n", type=int, default=20)
    ap.add_argument("--stage2-t", type=float, default=0.75)
    ap.add_argument("--quick", nargs=4, metavar=("QSG", "EJD", "NHIGH", "NLOW"),
                    help="快速模式：直接给定 QSG% EJD% 新高数 新低数，跳过扫描")
    ap.add_argument("--backfill", type=int, default=0,
                    help="回算最近 N 个交易日的广度序列并写入 history（0=仅当日）")
    ap.add_argument("--chart", action="store_true", help="读 history 画净值曲线图 PNG")
    ap.add_argument("--chart-only", action="store_true", help="仅读 history 画图，跳过扫描（供 CI 复用已累积的 history）")
    ap.add_argument("--turn-run", type=int, default=3, help="确认拐点：转正后净值连续为正天数阈值（画图用）")
    ap.add_argument("--outdir", default="outputs")
    args = ap.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(args.outdir, exist_ok=True)
    p = {"batch": args.batch, "limit": args.limit, "window": args.window,
         "strong_thr": args.strong_thr, "stage2_n": args.stage2_n, "stage2_t": args.stage2_t}

    if args.chart_only:
        hist = {}
        for hp in (os.path.join(args.outdir, "xihu_breadth_history.json"),
                   "xihu_breadth_history.json", "../outputs/xihu_breadth_history.json"):
            if os.path.exists(hp):
                try:
                    hist = json.load(open(hp, encoding="utf-8"))
                    break
                except Exception:
                    pass
        if len(hist) < 2:
            print("[WARN] history 数据点不足(<2)，未生成图")
            return
        chart_path = os.path.join(args.outdir, "xihu_breadth_chart.png")
        ok = make_chart(hist, chart_path, turn_run=args.turn_run)
        print(f"[{'OK' if ok else 'WARN'}] {chart_path}")
        return

    if args.quick:
        qsg, ejd, nh, nl = args.quick
        agg = {"total": 0, "strong": 0, "stage2": 0, "new_high": int(nh), "new_low": int(nl),
               "qsg_pct": float(qsg), "ejd_pct": float(ejd), "net_high": int(nh) - int(nl)}
        result = {}
        jd = judge(agg)
        md = build_report(agg, result, jd, date_str, p)
        md_path = os.path.join(args.outdir, f"xihu_breadth_{date_str}.md")
        open(md_path, "w", encoding="utf-8").write(md)
        print(f"[OK] {md_path}")
        return

    if args.stocks:
        stocks = [(c.strip(), "") for c in args.stocks.split(",") if c.strip()]
    else:
        if not os.path.exists(args.list):
            print(f"[ERR] list not found: {args.list}", file=sys.stderr)
            sys.exit(1)
        stocks = load_list(args.list)
    print(f"[INFO] 股票池 {len(stocks)} 只", flush=True)

    kl_cache = {} if args.backfill > 0 else None
    result = scan(stocks, p, kl_cache)
    agg = aggregate(result)
    jd = judge(agg)

    md = build_report(agg, result, jd, date_str, p)
    md_path = os.path.join(args.outdir, f"xihu_breadth_{date_str}.md")
    open(md_path, "w", encoding="utf-8").write(md)

    js = {
        "date": date_str,
        "total": agg["total"],
        "strong": agg["strong"], "qsg_pct": agg["qsg_pct"],
        "stage2": agg["stage2"], "ejd_pct": agg["ejd_pct"],
        "new_high": agg["new_high"], "new_low": agg["new_low"], "net_high": agg["net_high"],
        "qsg_level": jd["qsg_level"], "rain": jd["rain"],
        "params": {"window": p["window"], "strong_thr": p["strong_thr"],
                   "stage2_n": p["stage2_n"], "stage2_t": p["stage2_t"]},
        "new_high_list": [{"code": c, "name": v["name"], "close": v["close"]}
                          for c, v in result.items() if v.get("new_high")][:200],
        "stage2_list": [{"code": c, "name": v["name"], "close": v["close"]}
                        for c, v in result.items() if v.get("stage2")][:200],
    }
    jpath = os.path.join(args.outdir, "xihu_breadth_latest.json")
    open(jpath, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    # 历史累积（按日期，供画净值曲线）
    hist_path = os.path.join(args.outdir, "xihu_breadth_history.json")
    hist = {}
    if os.path.exists(hist_path):
        try:
            hist = json.load(open(hist_path, encoding="utf-8"))
        except Exception:
            hist = {}
    if args.backfill > 0:
        print(f"[回算] 回填最近 {args.backfill} 个交易日的广度序列…", flush=True)
        hist = build_history(kl_cache, p, args.backfill, existing=hist)
    hist[date_str] = {"qsg_pct": agg["qsg_pct"], "ejd_pct": agg["ejd_pct"],
                      "new_high": agg["new_high"], "new_low": agg["new_low"],
                      "net_high": agg["net_high"], "total": agg["total"]}
    hist = {k: hist[k] for k in sorted(hist.keys())}
    open(hist_path, "w", encoding="utf-8").write(json.dumps(hist, ensure_ascii=False, indent=1))

    # 净值曲线图
    if args.chart:
        chart_path = os.path.join(args.outdir, "xihu_breadth_chart.png")
        try:
            ok = make_chart(hist, chart_path, turn_run=args.turn_run)
            print(f"[{'OK' if ok else 'WARN'}] {chart_path}" if ok else "[WARN] 数据点不足(<2)，未生成图")
        except Exception as e:
            print(f"[WARN] 绘图失败: {e}")

    print(f"[OK] QSG%={agg['qsg_pct']} EJD%={agg['ejd_pct']} "
          f"新高{agg['new_high']} 新低{agg['new_low']} 净值{agg['net_high']:+d} | {jd['rain']}")
    print(f"[OK] {md_path}\n[OK] {jpath}\n[OK] {hist_path}")


if __name__ == "__main__":
    main()
