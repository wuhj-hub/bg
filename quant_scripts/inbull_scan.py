#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inbull_scan.py —— 板块-个股「入牛时点」扫描（曾星智·月线力量）

个股/行业/大盘「5根月线全部向上」判定：
    MA5↑ 且 MA10↑ 且 MA20↑ 且 MA30↑ 且 月线DIF↑
行业指数 = 成分股月收益等权合成；大盘 = 全市场等权。

数据源：westock 批量月线（前复权）。
输出：
    outputs/入牛时点扫描_{date}.md
    outputs/入牛时点_latest.json

用法：
    python3 quant_scripts/inbull_scan.py                 # 全市场
    python3 quant_scripts/inbull_scan.py --sample 250    # 仅前N只（冒烟测试）
    python3 quant_scripts/inbull_scan.py --date 2026-10-09
"""
import subprocess, re, json, os, sys, shutil, time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs")
os.makedirs(OUT, exist_ok=True)

BATCH = 250
MONTHS = 48          # 请求月数（够算 MA30）
WESTOCK = None       # 运行时确定


def westock_bin():
    w = shutil.which("westock-data-skillhub")
    return [w] if w else ["npx", "-y", "westock-data-skillhub@1.0.3"]


def run(args, timeout=180):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def parse_batch_month(txt):
    """解析批量月线表(symbol|date|open|last|high|low|...) -> {code:[(ym,close)]}"""
    hdr, data = None, {}
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts and "symbol" in parts:
            hdr = parts
            continue
        if not hdr or not parts or set(parts[0]) <= set("-"):
            continue
        try:
            sym, dt = parts[0], parts[1]
            ci = hdr.index("last")
            if re.match(r"^(sh|sz)\d{6}$", sym) and re.match(r"^\d{4}-\d{2}-\d{2}$", dt):
                c = float(parts[ci])
                if c > 0:
                    data.setdefault(sym, []).append((dt[:7], c))
        except (ValueError, IndexError):
            pass
    return data


def load_universe():
    """all_mainboard.csv (code,name) -> [sh/sz+code]"""
    codes = []
    fp = os.path.join(ROOT, "all_mainboard.csv")
    with open(fp, encoding="utf-8-sig") as f:
        for ln in f:
            p = ln.strip().split(",")
            if len(p) >= 1 and re.match(r"^\d{6}$", p[0].strip()):
                c = p[0].strip()
                codes.append(("sh" if c.startswith("6") else "sz") + c)
    return codes


def load_industry():
    """em_industry.json -> {6位code: 行业}"""
    fp = os.path.join(ROOT, "quant_scripts", "em_industry.json")
    d = json.load(open(fp, encoding="utf-8"))
    st = d.get("stocks", d)
    ind = {}
    for c, v in st.items():
        if isinstance(v, dict):
            ind[str(c)] = v.get("ind", "")
    return ind


def fetch_all(codes):
    rows, n = [], len(codes)
    for i in range(0, n, BATCH):
        chunk = codes[i:i + BATCH]
        d = parse_batch_month(run(["kline", ",".join(chunk), "--period", "month",
                                   "--limit", str(MONTHS)]))
        miss = [c for c in chunk if c not in d]
        if len(miss) == len(chunk):          # 整批失败 → 重试一次
            time.sleep(2)
            d2 = parse_batch_month(run(["kline", ",".join(chunk), "--period", "month",
                                        "--limit", str(MONTHS)]))
            for k, v in d2.items():
                d.setdefault(k, []).extend(v)
        for c, lst in d.items():
            for ym, cl in lst:
                rows.append((c, ym, cl))
        print(f"  batch {i//BATCH+1}/{(n+BATCH-1)//BATCH} rows={len(rows)}", flush=True)
    return rows


def gg_of(C):
    import pandas as pd
    if len(C) < 6:
        return pd.Series(False, index=C.index)
    ma = {k: C.rolling(k).mean() for k in (5, 10, 20, 30)}
    dif = C.ewm(span=10, adjust=False).mean() - C.ewm(span=22, adjust=False).mean()
    return ((ma[5] > ma[5].shift(1)) & (ma[10] > ma[10].shift(1)) &
            (ma[20] > ma[20].shift(1)) & (ma[30] > ma[30].shift(1)) &
            (dif > dif.shift(1))).fillna(False)


def main():
    global WESTOCK
    WESTOCK = westock_bin()
    date_str = datetime.now().strftime("%Y-%m-%d")
    sample = None
    a = sys.argv[1:]
    for i, x in enumerate(a):
        if x == "--date" and i + 1 < len(a):
            date_str = a[i + 1]
        if x == "--sample" and i + 1 < len(a):
            sample = int(a[i + 1])

    import pandas as pd
    codes = load_universe()
    if sample:
        codes = codes[:sample]
    ind6 = load_industry()
    print(f"[入牛时点] 标的 {len(codes)} 只, date={date_str}", flush=True)

    rows = fetch_all(codes)
    df = pd.DataFrame(rows, columns=["code", "ym", "close"]).dropna()
    df = df[df["close"] > 0]
    months = sorted(df["ym"].unique())
    if not months:
        print("[ERR] 无月线数据"); return
    cur = months[-1]
    print(f"[入牛时点] 数据月={cur}, 有效标的={df['code'].nunique()}", flush=True)

    # 个股
    st_bull, st_enter = {}, {}
    for code, g in df.groupby("code"):
        s = g.set_index("ym")["close"].sort_index()
        gg = gg_of(s)
        st_bull[code] = bool(gg.iloc[-1])
        st_enter[code] = [gg.index[k] for k in range(1, len(gg)) if gg.iloc[k] and not gg.iloc[k - 1]]

    # 行业等权
    piv = df.pivot_table(index="ym", columns="code", values="close")
    ret = piv.pct_change(fill_method=None)
    ind_codes = {}
    for c in ret.columns:
        i = ind6.get(c[2:], "")
        if i:
            ind_codes.setdefault(i, []).append(c)
    ind_bull, ind_enter = {}, {}
    for i, cs in ind_codes.items():
        if len(cs) < 3:
            continue
        idx = (1 + ret[cs].mean(axis=1).fillna(0)).cumprod() * 1000
        gg = gg_of(idx)
        ind_bull[i] = bool(gg.iloc[-1])
        ind_enter[i] = [gg.index[k] for k in range(1, len(gg)) if gg.iloc[k] and not gg.iloc[k - 1]]

    # 大盘等权
    mk = (1 + ret.mean(axis=1).fillna(0)).cumprod() * 1000
    mkg = gg_of(mk)
    mkt_bull = bool(mkg.iloc[-1]) if len(mkg) else False

    sectors_bull = sorted([k for k, v in ind_bull.items() if v])
    stocks_bull = [{"code": c, "ind": ind6.get(c[2:], ""),
                    "entry": (st_enter[c][-1] if st_enter[c] else "")}
                   for c in st_bull if st_bull[c]]
    res = {"date": date_str, "data_month": cur, "market_bull": mkt_bull,
           "sectors_bull": sectors_bull, "sectors_bull_n": len(sectors_bull),
           "sectors_total": len(ind_bull), "stocks_bull_n": len(stocks_bull),
           "stocks_total": int(df["code"].nunique()),
           "sector_entry": {k: (ind_enter[k][-1] if ind_enter.get(k) else "") for k in sectors_bull},
           "stocks_bull": stocks_bull}
    json.dump(res, open(os.path.join(OUT, "入牛时点_latest.json"), "w"), ensure_ascii=False, indent=1)

    L = [f"# 板块-个股「入牛时点」扫描 · {date_str}", "",
         f"- 数据月: **{cur}**",
         f"- 大盘（全市场等权）5根月线全向上: **{'是' if mkt_bull else '否'}**",
         f"- 入牛行业: **{len(sectors_bull)}/{len(ind_bull)}** → {'、'.join(sectors_bull) or '无'}",
         f"- 入牛个股: **{len(stocks_bull)}/{res['stocks_total']}**",
         f"- 口径: 月线 MA5/10/20/30 均向上 + 月线DIF向上（前复权）", ""]
    if sectors_bull:
        L.append("## 入牛行业")
        L.append("")
        L.append("| 行业 | 入牛月 | 成分(入牛) |")
        L.append("|---|---|---|")
        for s in sectors_bull:
            mem = [c for c in stocks_bull if c["ind"] == s]
            L.append(f"| {s} | {res['sector_entry'].get(s,'')} | " +
                     "、".join(f"{x['code'][2:]}({x['entry']})" for x in mem[:12]) + " |")
        L.append("")
    from collections import Counter
    L.append("## 入牛个股行业分布")
    L.append("")
    L.append("| 行业 | 只数 |")
    L.append("|---|---|")
    for k, v in Counter(x["ind"] for x in stocks_bull).most_common():
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## 入牛个股清单")
    L.append("")
    L.append("| 代码 | 行业 | 入牛月 |")
    L.append("|---|---|---|")
    for x in sorted(stocks_bull, key=lambda z: (z["ind"], z["entry"])):
        L.append(f"| {x['code']} | {x['ind']} | {x['entry']} |")
    L.append("")
    L.append("> 回测口径：Q4(板块入牛>6月后个股才入牛)+大盘牛 最优；Q1(板块当月同步)最差；「个股领先板块」无超额。止盈=周线顶背离后破周线黄金线。")
    open(os.path.join(OUT, f"入牛时点扫描_{date_str}.md"), "w", encoding="utf-8").write("\n".join(L))
    print(f"[OK] 大盘牛={mkt_bull} 入牛行业={len(sectors_bull)} 入牛个股={len(stocks_bull)}", flush=True)


if __name__ == "__main__":
    main()
