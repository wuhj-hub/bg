#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反转数值 · 周线信号漏斗每日扫描器
==================================
扫描股票池（默认沪深300）的周线反转信号，按漏斗分层输出：
  🔴 F层 精选（翻红+回调≥3周+超跌+底背离）→ 重仓级
  🟡 D层 标准（翻红+底背离）→ 标准仓
  🟢 A层 基础（周线翻红）→ 分散仓

用法:
  python3 reversal_funnel_screener.py                  # 扫描沪深300
  python3 reversal_funnel_screener.py --pool "sh600519,sz000001"
  python3 reversal_funnel_screener.py --weeks 2        # 最近2根周线内信号
"""
import os, sys, re, json, subprocess, argparse
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
WESTOCK = "npx -y westock-data-skillhub@1.0.3"


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


def has_divergence(macd, closes, j, lookback=12):
    s, c = macd[max(0, j - lookback):j], closes[max(0, j - lookback):j]
    if len(s) < 3:
        return False
    lows = [i for i in range(1, len(s) - 1) if s[i] <= s[i - 1] and s[i] <= s[i + 1]]
    if len(lows) < 2:
        return False
    l1, l2 = lows[-2], lows[-1]
    return c[l2] < c[l1] and s[l2] > s[l1]


def fetch_weekly(code):
    """westock拉周线，返回 [(date, open, close, high, low)] 升序"""
    try:
        r = subprocess.run(f"{WESTOCK} kline {code} --period week --limit 130",
                           shell=True, capture_output=True, text=True, timeout=60)
        rows = []
        for ln in r.stdout.splitlines():
            m = re.match(r"\|\s*([\d-]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
            if m:
                rows.append((m.group(1), float(m.group(2)), float(m.group(3)),
                             float(m.group(4)), float(m.group(5))))
        rows.sort(key=lambda r: r[0])
        return rows
    except Exception as e:
        print(f"  [warn] {code} 拉取失败: {e}")
        return []


def detect_signal(rows, weeks=1):
    """检测最近weeks根周线内的漏斗信号，返回 (层级, 细节dict) 或 None"""
    if len(rows) < 30:
        return None
    closes = [r[2] for r in rows]
    macd = calc_macd(closes)
    n = len(macd)
    # 最近weeks根内翻红
    sig_idx = None
    for i in range(n - weeks, n):
        if i >= 2 and macd[i] > 0 and macd[i - 1] <= 0:
            sig_idx = i
            break
    if sig_idx is None:
        return None
    j = sig_idx
    b = all(m < 0 for m in macd[max(0, j - 3):j]) and (j - 3) >= 0
    seg = macd[max(0, j - 4):j]
    depth = round(min(seg), 2) if seg else 0
    c = depth <= -3.0
    d = has_divergence(macd, closes, j, lookback=12)
    if b and c and d:
        level = "F"
    elif d:
        level = "D"
    elif b and c:
        level = "E"
    elif c:
        level = "C"
    elif b:
        level = "B"
    else:
        level = "A"
    return level, {
        "date": rows[j][0], "close": rows[j][2],
        "fz": round(macd[j] * 0.618, 2), "depth": depth,
        "green_weeks": sum(1 for m in macd[max(0, j - 8):j] if m < 0),
        "divergence": d,
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
    ap.add_argument("--weeks", type=int, default=1, help="检测最近N根周线内信号(默认1)")
    ap.add_argument("--push", action="store_true", help="PushPlus推送")
    a = ap.parse_args()

    pool = load_pool(a.pool)
    if not pool:
        print("❌ 无股票池")
        return
    print(f"🔍 反转数值周线漏斗扫描 | 标的{len(pool)}只 | 检测最近{a.weeks}周 | {datetime.now():%Y-%m-%d %H:%M}")

    signals = {"F": [], "D": [], "E": [], "C": [], "B": [], "A": []}
    for code, name in pool:
        rows = fetch_weekly(code)
        if not rows:
            continue
        r = detect_signal(rows, a.weeks)
        if r:
            level, det = r
            det["code"], det["name"] = code, name
            signals[level].append(det)

    today = datetime.now().strftime("%Y-%m-%d")
    L = []
    A = L.append
    A(f"# 🔄 反转数值周线信号扫描（{today}）\n")
    A(f"> 股票池：沪深300成分股{len(pool)}只 | 信号窗口：最近{a.weeks}根周线 | 漏斗：翻红→回调→超跌→底背离\n")
    A(f"> 体系：🔴F重仓(66.7%/+11.7%) | 🟡D标准(57%/+4.5%) | 🟢A基础(51%/+2.2%) | 持有4周\n")

    lvl_meta = [("F", "🔴 F层精选（翻红+回调≥3周+超跌+底背离）· 重仓级"), 
                ("D", "🟡 D层标准（翻红+底背离）· 标准仓"),
                ("E", "🟠 E层（翻红+回调+超跌）"),
                ("C", "🟣 C层（翻红+超跌）"),
                ("B", "🔵 B层（翻红+回调≥3周）"),
                ("A", "🟢 A层基础（周线翻红）· 分散仓")]
    total = 0
    for lvl, title in lvl_meta:
        ss = signals[lvl]
        if not ss:
            continue
        total += len(ss)
        A(f"\n### {title}（{len(ss)}只）\n")
        A("| 代码 | 名称 | 信号周 | 现价 | 反转数值 | 绿柱深度 | 连续绿柱 | 底背离 |")
        A("|:--|:--|:--|--:|--:|--:|--:|:--:|")
        for s in sorted(ss, key=lambda x: -x["fz"]):
            A(f"| {s['code']} | {s['name']} | {s['date']} | {s['close']} | {s['fz']:+.2f} | "
              f"{s['depth']:.2f} | {s['green_weeks']}周 | {'✅' if s['divergence'] else '—'} |")
    if total == 0:
        A("\n> ⏳ 当前无周线翻红信号（无标的满足漏斗条件）")

    A("\n---")
    A("> ⚠️ 本报告为量化规律统计，不构成投资建议。周线信号持有4周，止损=信号周低点。")

    out_dir = os.path.join(BASE, "outputs")
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, f"反转数值周线信号_{today}.md")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\n✅ 信号总数: {total} | 报告: {fp}")

    # PushPlus推送
    if a.push:
        import urllib.request, urllib.parse
        token = os.environ.get("PUSH_TOKEN", "")
        if token:
            content = "\n".join(L)[:3500] + ("\n...(完整见报告)" if len("\n".join(L)) > 3500 else "")
            body = urllib.parse.urlencode({"token": token, "title": f"🔄 反转数值周线信号 {today}",
                                           "content": content, "template": "markdown"}).encode()
            try:
                r = urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body), timeout=30)
                print(f"[pushplus] {r.read().decode()[:80]}")
            except Exception as e:
                print(f"[pushplus] 失败: {e}")

    # 简要控制台输出
    for lvl, title in lvl_meta:
        if signals[lvl]:
            print(f"  {title}: {len(signals[lvl])}只 → " + "、".join(f"{s['name']}({s['code']})" for s in signals[lvl][:6]))


if __name__ == "__main__":
    main()
