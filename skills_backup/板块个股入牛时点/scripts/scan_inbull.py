#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板块-个股「入牛时点」扫描（曾星智月线力量体系）

流程：
  1) 读主板股票池（all_mainboard.csv）
  2) 拉同花顺后复权月线（hs_{code}/02/all.js），缓存到 data/kline_month_adj.csv
  3) 计算：个股 / 行业指数(等权) / 大盘指数(等权) 的「5根月线全向上」
  4) 识别最近 N 个月内的「个股入牛事件」，按相对板块入牛的时点分层
  5) 输出报告

用法:
  python3 scan_inbull.py                # 扫描最近3个月
  python3 scan_inbull.py --months 6     # 扫描最近6个月
  python3 scan_inbull.py --fetch        # 强制重新拉数据
"""
import os, sys, re, json, time, datetime, argparse
import subprocess
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT = os.path.join(BASE, "outputs")
os.makedirs(DATA, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def curl(url):
    for i in range(4):
        try:
            r = subprocess.run(["curl", "-s", "--max-time", "45", "-A", UA, url],
                               capture_output=True, text=True)
            t = (r.stdout or "").strip()
            if t and "quotebridge" in t:
                return t
        except Exception:
            pass
        time.sleep(0.8 + 1.2 * i)
    return ""


def parse_monthly(txt):
    m = re.search(r"\((\{.*\})\)\s*;?\s*$", txt, re.S)
    if not m:
        return []
    j = json.loads(m.group(1))
    pf = float(j.get("priceFactor", 100) or 100)
    p = [float(x) / pf for x in j["price"].split(",") if x != ""]
    dates = [x for x in j["dates"].split(",") if x]
    sy = j.get("sortYear", [])
    n = min(len(p) // 4, len(dates))
    full, yi, cnt = [], 0, 0
    for k in range(n):
        while yi < len(sy) and cnt >= int(sy[yi][1]):
            yi += 1; cnt = 0
        if yi >= len(sy):
            break
        full.append(f"{int(sy[yi][0])}{dates[k]}")
        cnt += 1
    monthly = {}
    for k in range(min(n, len(full))):
        lo = p[4 * k]; o = lo + p[4 * k + 1]; h = lo + p[4 * k + 2]; c = lo + p[4 * k + 3]
        ym = f"{full[k][:4]}-{full[k][4:6]}"
        if ym not in monthly:
            monthly[ym] = [o, h, lo, c]
        else:
            mm = monthly[ym]; mm[1] = max(mm[1], h); mm[2] = min(mm[2], lo); mm[3] = c
    return [(ym, v[0], v[1], v[2], v[3]) for ym, v in sorted(monthly.items())]


def load_pool():
    fp = os.path.join(DATA, "all_mainboard.csv")
    if not os.path.exists(fp):
        raise SystemExit("缺少 all_mainboard.csv（code,name），请先放入 data/")
    rows = []
    with open(fp, encoding="utf-8-sig") as f:
        for ln in f:
            p = ln.strip().split(",")
            if len(p) >= 2 and re.match(r"^\d{6}$", p[0].strip()):
                code = p[0].strip(); name = p[1].strip()
                if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
                    up = name.upper().replace(" ", "")
                    if ("ST" in up) or ("PT" in up) or ("退" in name):
                        continue
                    rows.append((("sh" if code.startswith("6") else "sz") + code, name))
    return rows


def fetch_monthly(pool, force=False):
    fp = os.path.join(DATA, "kline_month_adj.csv")
    if os.path.exists(fp) and not force:
        age = time.time() - os.path.getmtime(fp)
        if age < 86400 * 3:
            print(f"复用缓存 {fp}（{age/3600:.1f} 小时前）", flush=True)
            return pd.read_csv(fp)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print(f"拉取月线 {len(pool)} 只 ...", flush=True)
    def one(args):
        sym, code = args
        t = curl(f"http://d.10jqka.com.cn/v6/line/hs_{code}/02/all.js")
        if not t: return sym, []
        try: return sym, parse_monthly(t)
        except Exception: return sym, []
    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(one, (s, s[2:])): s for s, n in pool}
        for i, fu in enumerate(as_completed(futs), 1):
            sym, res = fu.result()
            for ym, o, h, lo, c in res:
                rows.append((sym, ym, o, h, lo, c))
            if i % 600 == 0:
                print(f"  {i}/{len(pool)}", flush=True)
    df = pd.DataFrame(rows, columns=["code", "ym", "open", "high", "low", "close"])
    df.to_csv(fp, index=False)
    print(f"已保存 {fp}", flush=True)
    return df


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def gg_of(C):
    if len(C) < 6:
        return pd.Series(False, index=C.index)
    ma5, ma10, ma20, ma30 = [C.rolling(k).mean() for k in (5, 10, 20, 30)]
    dif = ema(C, 10) - ema(C, 22)
    return ((ma5 > ma5.shift(1)) & (ma10 > ma10.shift(1)) & (ma20 > ma20.shift(1)) &
            (ma30 > ma30.shift(1)) & (dif > dif.shift(1))).fillna(False).astype(bool)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=3)
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args()

    pool = load_pool()
    name_of = dict(pool)
    df = fetch_monthly(pool, a.fetch)
    df = df.dropna(subset=["close"])
    df = df[(df["close"] > 0) & (df["high"] > 0)]

    # 行业分类（westock profile 批量）——若无则用配置文件
    indfp = os.path.join(DATA, "pool.csv")
    if os.path.exists(indfp):
        pi = pd.read_csv(indfp)
        ind_of = dict(zip(pi["code"], pi["industry"]))
    else:
        ind_of = {}

    months = sorted(df["ym"].unique())
    if not months:
        raise SystemExit("无月线数据")
    cur = months[-1]
    recent = months[-a.months - 1:]

    # 个股 / 行业 / 大盘
    st_enter, st_state = {}, {}
    for code, g in df.groupby("code", sort=False):
        g = g.sort_values("ym").reset_index(drop=True)
        gg = gg_of(g["close"])
        st_enter[code] = list(g.loc[gg & (~gg.shift(1, fill_value=False)), "ym"])
        st_state[code] = set(g.loc[gg, "ym"])

    ret = df.pivot_table(index="ym", columns="code", values="close").pct_change(fill_method=None)
    ind_codes = {}
    for c, i in ind_of.items():
        if isinstance(i, str) and i:
            ind_codes.setdefault(i, []).append(c)
    ind_enter, ind_state = {}, {}
    for ind, cs in ind_codes.items():
        cs = [c for c in cs if c in ret.columns]
        if not cs:
            continue
        idx = (1 + ret[cs].mean(axis=1).fillna(0.0)).cumprod() * 1000
        gg = gg_of(idx)
        ind_enter[ind] = list(idx.index[gg & (~gg.shift(1, fill_value=False))])
        ind_state[ind] = set(idx.index[gg])
    mk = (1 + ret.mean(axis=1).fillna(0.0)).cumprod() * 1000
    mkg = gg_of(mk)
    mkt_bull = bool(mkg.iloc[-1]) if len(mkg) else False
    mi = {x: i for i, x in enumerate(months)}

    lines = [f"# 板块-个股「入牛时点」扫描 · {cur}", ""]
    lines.append(f"- 大盘（全市场等权指数）当前是否牛市（5根月线全向上）: **{'是' if mkt_bull else '否'}**")
    nb = sum(1 for i in ind_state if cur in ind_state[i])
    lines.append(f"- 32个行业中处于牛市的: {nb} 个")
    lines.append(f"- 扫描窗口: 最近 {a.months} 个月（{recent[0]} ~ {cur}）")
    lines.append("")
    lines.append("## 入牛事件（按相对板块入牛的时点分层）")
    lines.append("| 月份 | 代码 | 名称 | 行业 | 分层 | 板块状态 | 大盘 |")
    lines.append("|---|---|---|---|---|---|---|")

    cnt = {}
    for code, g in df.groupby("code", sort=False):
        g = g.reset_index(drop=True)
        ind = ind_of.get(code, "")
        for t in range(len(g)):
            ym = g.loc[t, "ym"]
            if ym not in recent or ym not in st_enter[code]:
                continue
            if ind and ym in ind_state.get(ind, set()):
                ens = [d for d in ind_enter.get(ind, []) if d <= ym]
                d = mi[ym] - mi[max(ens)] if ens else 0
                grp = "Q1 板块入牛当月" if d == 0 else ("Q2 后1-3月" if d <= 3 else "Q3 后4-6月" if d <= 6 else "Q4 后>6月")
                sstat = "牛市"
            else:
                grp = "L 板块未牛(个股领先)"; sstat = "非牛"
            cnt[grp] = cnt.get(grp, 0) + 1
            lines.append(f"| {ym} | {code} | {name_of.get(code,'')} | {ind or '-'} | {grp} | {sstat} | {'牛' if mkt_bull else '非牛'} |")
    lines.append("")
    lines.append("## 统计")
    for k in sorted(cnt):
        lines.append(f"- {k}: {cnt[k]}")
    lines.append("")
    lines.append("> 用法提示（据 1990-2026 回测）：Q4（板块入牛>6月后个股才入牛）在**大盘牛市**中带正超额；Q1（板块入牛当月同步）历史上最差；「率先入牛」无超额。止盈用「周线顶背离后跌破周线黄金线」。")
    txt = "\n".join(lines)
    fp = os.path.join(OUT, f"入牛时点扫描_{cur}.md")
    open(fp, "w", encoding="utf-8").write(txt)
    print(txt)
    print(f"\n已保存 {fp}")


if __name__ == "__main__":
    main()
