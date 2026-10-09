#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反转数值 · 日线信号扫描器（reversal_daily_screener.py）
=======================================================
口径（来自《反转数值MACD指标_优化版_代码》，改①版）：
  反转数值  = 0.618 × |MACD|
  S1 突破2倍反转数值 : MACD > 2×0.618×BL_DEEP 且 MACD 上升（BL_DEEP=死叉以来最深绿柱）
  S2 回调不破1倍反转数值: 回调深 = |LLV(MACD, 突破以来)| < 0.618 × HHV(MACD, 金叉以来)
  信号 = S1 已发生 且 S2 成立 且 死叉之后（SCB>0 且 JCB>SCB）
  过滤：现价 < 上限（默认 10 元）

用法:
  python3 reversal_daily_screener.py --days 5 --max-price 10
  python3 reversal_daily_screener.py --pool "sz000560,sh600400"
  python3 reversal_daily_screener.py --pool-file all_mainboard.csv   # 全市场
输出: outputs/反转数值日线信号_{date}.md
"""
import os, sys, re, json, subprocess, argparse
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
WESTOCK = "npx -y westock-data-skillhub@1.0.3"
K = 0.618


def ema(series, n):
    out = [series[0]]
    k = 2 / (n + 1)
    for x in series[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def calc_dif_dea(closes):
    """归一化 DIF/DEA/MACD（与指标一致：EMA(C,n)/C*100）"""
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]
    return dif, dea, macd


def fetch_batch(codes, period="day", limit=250):
    """westock 批量 K 线（100只/批），返回 {code: rows[(date,open,last,high,low)]}"""
    out = {}
    for i in range(0, len(codes), 100):
        batch = codes[i:i + 100]
        try:
            r = subprocess.run(f"{WESTOCK} kline {','.join(batch)} --period {period} --limit {limit}",
                               shell=True, capture_output=True, text=True, timeout=240)
            rm = {}
            for ln in r.stdout.splitlines():
                m = re.match(r"\|\s*([a-z]{2}\d{6})\s*\|\s*([\d-]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
                if m:
                    rm.setdefault(m.group(1), []).append(
                        (m.group(2), float(m.group(3)), float(m.group(4)), float(m.group(5)), float(m.group(6))))
            for sym, rows in rm.items():
                rows.sort(key=lambda x: x[0])
                out[sym] = rows
        except Exception as e:
            print(f"  [warn] 批{i//100+1}拉取失败: {e}")
    return out


def detect_daily(rows, days=5):
    """检测最近 days 根日线内的「突破2倍→回调不破1倍」信号"""
    if len(rows) < 80:
        return None
    closes = [r[2] for r in rows]
    dif, dea, macd = calc_dif_dea(closes)
    n = len(macd)
    JC = [False] * n
    SC = [False] * n
    for i in range(1, n):
        JC[i] = dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]
        SC[i] = dif[i] < dea[i] and dif[i - 1] >= dea[i - 1]
    JCB = [None] * n
    SCB = [None] * n
    lj = ls = None
    for i in range(n):
        if JC[i]: lj = i
        if SC[i]: ls = i
        JCB[i] = None if lj is None else i - lj
        SCB[i] = None if ls is None else i - ls

    def bl_deep(i):
        if SCB[i] is None or SCB[i] == 0:
            return abs(min(macd[max(0, i - (SCB[i] or 0)):i + 1]))
        return abs(min(macd[max(0, i - int(SCB[i])):i + 1]))

    hit = None
    for i in range(max(1, n - days), n):
        if SCB[i] is None or JCB[i] is None or SCB[i] == 0:
            continue
        # 自上次死叉以来是否出现过「突破2倍反转数值」（MACD 上升）
        tp_bar = None
        for kk in range(max(1, i - 90), i + 1):
            if SCB[kk] is None:
                continue
            if macd[kk] > 2 * K * bl_deep(kk) and macd[kk] > macd[kk - 1]:
                tp_bar = kk
        if tp_bar is None:
            continue
        seg = macd[tp_bar:i + 1]                 # 突破以来
        red_high = max(seg)                      # 突破红柱高
        deep = abs(min(seg))                     # 回调深
        line = K * max(macd[max(0, i - int(JCB[i])):i + 1])   # 1倍反转数值（改①：0.618×金叉以来红柱高）
        if deep < line and JCB[i] > SCB[i]:
            hit = (i, tp_bar, red_high, deep, line, 2 * K * bl_deep(tp_bar))
    if not hit:
        return None
    i, tp_bar, red_high, deep, line, tp_val = hit
    return {"date": rows[i][0], "close": round(closes[i], 2),
            "last_close": round(closes[-1], 2), "last_date": rows[-1][0],
            "tp_date": rows[tp_bar][0], "tp_val": round(tp_val, 2),
            "red_high": round(red_high, 2), "pullback": round(deep, 2),
            "line": round(line, 2), "gap": i - tp_bar}


def load_pool(pool_arg="", pool_file=""):
    if pool_arg:
        return [(c.strip(), "") for c in pool_arg.split(",") if c.strip()]
    fp = pool_file or os.path.join(BASE, "hs300.csv")
    if not os.path.isabs(fp):
        fp = os.path.join(BASE, fp)
    rows = []
    if os.path.exists(fp):
        for ln in open(fp, encoding="utf-8-sig"):
            p = ln.strip().split(",")
            if len(p) >= 2 and (p[0].startswith(("sh", "sz"))):
                rows.append((p[0], p[1]))
            elif len(p) >= 2 and re.match(r"^\d{6}$", p[0]):
                rows.append((("sh" if p[0].startswith("6") else "sz") + p[0], p[1]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="", help="代码列表(逗号分隔)")
    ap.add_argument("--pool-file", default="", help="股票池文件(默认 hs300.csv)")
    ap.add_argument("--days", type=int, default=5, help="检测最近N根日线内信号(默认5)")
    ap.add_argument("--max-price", type=float, default=10.0, help="仅保留现价<该值(默认10)")
    ap.add_argument("--push", action="store_true", help="PushPlus 推送")
    a = ap.parse_args()

    pool = load_pool(a.pool, a.pool_file)
    if not pool:
        print("❌ 无股票池"); return
    print(f"🔍 反转数值日线信号扫描 | 标的{len(pool)}只 | 检测最近{a.days}日 | 现价<{a.max_price:g}元")

    rows_map = fetch_batch([c for c, n in pool], "day", 250)
    print(f"  数据就绪: {len(rows_map)}/{len(pool)}只")

    hits = []
    for code, name in pool:
        rows = rows_map.get(code)
        if not rows:
            continue
        d = detect_daily(rows, a.days)
        if not d:
            continue
        # 数据时效：最新K线距今 >15 天视为停牌/退市/吸收合并，剔除
        try:
            if (datetime.now() - datetime.strptime(d["last_date"], "%Y-%m-%d")).days > 15:
                continue
        except Exception:
            pass
        if a.max_price > 0 and d["last_close"] >= a.max_price:
            continue
        d["code"], d["name"] = code, name
        hits.append(d)

    today = datetime.now().strftime("%Y-%m-%d")
    L = []
    L.append(f"# 🔄 反转数值日线信号扫描（{today}）\n")
    L.append(f"> 股票池：{'自定义' if a.pool else (a.pool_file or '沪深300')} {len(pool)}只 | 信号窗口：最近{a.days}根日线 | 现价 < {a.max_price:g}元\n")
    L.append("> 口径：**突破2倍反转数值 → 回调不破1倍反转数值**（反转数值=0.618×|MACD|；改①：不破线=0.618×金叉以来最高红柱）\n")
    if hits:
        L.append(f"\n### 📈 命中信号（{len(hits)}只）\n")
        L.append("| 代码 | 名称 | 信号日 | 信号价 | 最新价 | 突破日 | 突破2倍值 | 突破红柱高 | 回调深 | 不破线(1倍) | 距突破 |")
        L.append("|:--|:--|:--|--:|--:|:--|--:|--:|--:|--:|--:|")
        for s in sorted(hits, key=lambda x: x["gap"]):
            L.append(f"| {s['code']} | {s['name']} | {s['date']} | {s['close']} | {s['last_close']} | {s['tp_date']} | "
                     f"{s['tp_val']:+.2f} | {s['red_high']:.2f} | {s['pullback']:.2f} | {s['line']:.2f} | {s['gap']}日 |")
    else:
        L.append("\n> ⏳ 当前无满足「突破2倍后回调不破1倍」的日线信号（且现价<%.0f元）" % a.max_price)
    L.append("\n---")
    L.append("> ⚠️ 本报告为量化规律统计，不构成投资建议。信号后建议配合环境过滤（大盘/行业温度）与止损。")

    os.makedirs("outputs", exist_ok=True)
    fp = os.path.join("outputs", f"反转数值日线信号_{today}.md")
    open(fp, "w", encoding="utf-8").write("\n".join(L))
    print(f"✅ 命中 {len(hits)} 只 | 报告: {fp}")
    for s in hits[:12]:
        print(f"   {s['code']} {s['name']} 现价{s['close']} 突破{s['tp_date']} 回调深{s['pullback']}<{s['line']}")

    if a.push:
        import urllib.request, urllib.parse
        token = os.environ.get("PUSH_TOKEN", "")
        if token:
            content = "\n".join(L)[:3500]
            body = urllib.parse.urlencode({"token": token, "title": f"🔄 反转数值日线信号 {today}",
                                           "content": content, "template": "markdown"}).encode()
            try:
                r = urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body), timeout=30)
                print(f"[pushplus] {r.read().decode()[:80]}")
            except Exception as e:
                print(f"[pushplus] 失败: {e}")


if __name__ == "__main__":
    main()
