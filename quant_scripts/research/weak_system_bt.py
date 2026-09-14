#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""弱市体系复测：把仓库真实脚本的信号口径搬到历史面板，按市场环境分层
信号口径严格照搬：rsv_strength.py / scan_123_2b.py / wuwei_scan_month.py
"""
import os, json, urllib.request
import numpy as np
import pandas as pd

BASE = "/sandbox/workspace/zxz_bt"
DATA, OUT = f"{BASE}/data", f"{BASE}/outputs"
N = 144


def fetch_bench():
    p = f"{DATA}/idx/sz399106.csv"
    if os.path.exists(p):
        d = pd.read_csv(p, dtype={"date": str})
        return dict(zip(d["date"], d["close"]))
    url = "http://d.10jqka.com.cn/v6/line/hs_399106/01/all.js"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "http://stockpage.10jqka.com.cn/"})
    t = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    d = json.JSONDecoder().raw_decode(t[t.find("{"):])[0]
    pf = d["priceFactor"]; P = [int(x) for x in d["price"].split(",")]
    md = d["dates"].split(","); k = 0; full = []
    for y, cnt in d["sortYear"]:
        for s in md[k:k + cnt]:
            s = s.zfill(4); full.append(f"{y}-{s[:2]}-{s[2:]}")
        k += cnt
    n = min(len(full), len(P) // 4); rows = []
    for i in range(n):
        b = P[4 * i:4 * i + 4]
        rows.append([full[i], round((b[0] + b[3]) / pf, 3)])
    pd.DataFrame(rows, columns=["date", "close"]).to_csv(p, index=False)
    return dict(rows)


def rsv_np(vals, n=N):
    s = pd.Series(vals, dtype="float64")
    hh = s.rolling(n).max(); ll = s.rolling(n).min()
    rsv = (s - ll) / (hh - ll).replace(0, np.nan) * 100
    return rsv.values, (rsv > rsv.shift(3)).values


def main():
    bench = fetch_bench()
    df = pd.read_csv(f"{DATA}/kline_daily_vol.csv", dtype={"code": str, "date": str})
    df = df[df["close"] > 0].sort_values(["code", "date"]).reset_index(drop=True)
    print("面板", len(df), df.code.nunique(), "只")

    ret = df.pivot_table(index="date", columns="code", values="close").pct_change(fill_method=None)
    mk = (1 + ret.mean(axis=1).fillna(0.0)).cumprod()
    ma20, ma60 = mk.rolling(20).mean(), mk.rolling(60).mean()
    senv = pd.Series(np.where((mk > ma20) & (ma20 > ma60), "牛市",
                              np.where((mk < ma20) & (ma20 < ma60), "熊市", "震荡市")), index=mk.index)
    mk2 = mk.copy(); mk2.index = pd.to_datetime(mk2.index, format="%Y-%m-%d")
    mm = mk2.resample("ME").last().dropna()
    m6, m12 = mm.rolling(6).mean(), mm.rolling(12).mean()
    mid = pd.Series(np.where((mm > m6) & (m6 > m12), "牛市",
                             np.where((mm < m6) & (m6 < m12), "熊市", "震荡市")), index=mm.index)
    mid.index = mid.index.strftime("%Y%m")
    mkt20 = (1 + ret.mean(axis=1).fillna(0.0)).rolling(20).apply(np.prod, raw=True) - 1
    m20m = dict(zip(mkt20.index, mkt20.values))
    print("短期环境", senv.value_counts().to_dict(), "\n中期环境", mid.value_counts().to_dict())

    # 月线：由日线聚合（同花顺月线接口无 volume，武威G1需要量能）
    dd = df.copy(); dd["ym"] = dd["date"].str[:7]
    agg = dd.groupby(["code", "ym"]).agg(open=("open", "first"), high=("high", "max"),
                                         low=("low", "min"), close=("close", "last"),
                                         volume=("volume", "sum")).reset_index()
    mrows = {c: g.sort_values("ym").reset_index(drop=True) for c, g in agg.groupby("code", sort=False)}

    rows = []
    codes = list(df.groupby("code", sort=False))
    for ci, (code, g) in enumerate(codes):
        g = g.reset_index(drop=True)
        if len(g) < 300:
            continue
        C = g["close"].values; H = g["high"].values; L = g["low"].values
        O = g["open"].values; D = g["date"].values; n = len(g)

        rsv1, up1 = rsv_np(C)
        bs = np.array([bench.get(d, np.nan) for d in D])
        with np.errstate(invalid="ignore", divide="ignore"):
            rs = np.where(bs > 0, C / bs, np.nan)
        rsv2, _ = rsv_np(rs)
        rsvavg = (rsv1 + rsv2) / 2

        sc = pd.Series(C)
        ma5 = sc.rolling(5).mean().values
        r14 = sc.diff(); u = r14.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        dn = (-r14.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rsi = (100 - 100 / (1 + u / dn.replace(0, np.nan))).values
        pct = np.concatenate([[np.nan], C[1:] / C[:-1] - 1])
        nxt = np.concatenate([O[1:], [np.nan]])
        r5 = np.concatenate([C[5:] / nxt[:-5] - 1, [np.nan] * 5])
        r10 = np.concatenate([C[10:] / nxt[:-10] - 1, [np.nan] * 10])
        r20 = np.concatenate([C[20:] / nxt[:-20] - 1, [np.nan] * 20])

        # ── 123法则（scan_123_2b.py detect_123）──
        Ls, Hs = pd.Series(L), pd.Series(H)
        cur_low = Ls.rolling(3).min().values                       # L[i-2..i]
        min_lows = Ls.shift(3).rolling(17).min().values            # L[i-19..i-3]
        prev_high = Hs.shift(4).rolling(16).max().values           # H[i-19..i-4]
        s123 = (cur_low > min_lows) & (C > prev_high) & (C > ma5) & (ma5 > np.concatenate([[np.nan], ma5[:-1]]))

        # ── 2B法则（detect_2b 做多版）──
        m25 = Ls.rolling(25).min().values
        m_mid = Ls.shift(3).rolling(19).min().values
        old = Ls.shift(24).values
        s2b = (m_mid == m25) & (Ls.rolling(3).min().values > m25) & (old > m25) & (C > m25 * 1.02)
        # 严格版：低点至少 5 日前形成（rolling5 全在上方）+ 已收回 5% + 站上MA5
        m25s = Ls.rolling(25).min().values
        s2b_s = (Ls.rolling(5).min().values > m25s) & (m_mid == m25s) & (C > m25s * 1.05) & (C > ma5)

        # ── 周线RSV（自然周最后一日）──
        wser = pd.Series(C, index=pd.to_datetime(D)).resample("W").last().dropna()
        wmap = {}
        if len(wser) >= N + 5:
            wr, _ = rsv_np(wser.values)
            wmap = {d.strftime("%Y-%m-%d"): v for d, v in zip(wser.index, wr)}

        # ── 武威月线 G1（wuwei_scan_month.py signal）──
        ww = np.array(["无"] * n, dtype=object)
        mr = mrows.get(code)
        if mr is not None and len(mr) >= 5:
            mstr = np.array([d for d in mr["ym"].values])
            mo, mc = mr["open"].values, mr["close"].values
            ml, mv = mr["low"].values, mr["volume"].values
            k4a = np.searchsorted(mstr, np.array([d[:7] for d in D]), side="left") - 1
            for j in range(4, len(mstr)):
                k1, k2, k3, k4 = j - 3, j - 2, j - 1, j
                if yin(mc, mo, k3) and yin(mc, mo, k4) and mv[k2] > 0 \
                   and mv[k4] <= mv[k2] * .6 and mv[k3] <= mv[k2] * .6 \
                   and ml[k1] > 0 and abs(ml[k4] - ml[k1]) / ml[k1] <= .12:
                    ww[k4a == j] = "双阴"
                elif yang(mc, mo, k3) and yin(mc, mo, k2) and yin(mc, mo, k4) and mv[k3] > 0 \
                        and mv[k2] < mv[k3] * .6 and mv[k4] < mv[k3] * .6 \
                        and ml[k3] > 0 and abs(ml[k4] - ml[k3]) / ml[k3] <= .12:
                    ww[k4a == j] = "一阴"

        wkeys = np.array(list(wmap.keys())) if wmap else np.array([])
        for i in range(280, n - 21):
            if np.isnan(rsvavg[i]) or np.isnan(rsi[i]) or np.isnan(nxt[i]) or nxt[i] <= 0 or np.isnan(r20[i]):
                continue
            wk50 = False
            if len(wkeys):
                pos = np.searchsorted(wkeys, D[i], side="left") - 1
                if pos >= 1:
                    wk50 = bool(wmap[wkeys[pos]] > 50 and wmap[wkeys[pos - 1]] <= 50)
            t = [bool(rsvavg[i] < 20 and up1[i]),
                 bool(20 <= rsvavg[i] < 40 and up1[i] and pct[i] >= .09),
                 wk50, bool(s123[i]), bool(s2b[i]), bool(s2b_s[i]),
                 bool(ww[i] == "双阴"), bool(ww[i] == "一阴"), bool(rsi[i] < 25)]
            if not any(t):
                continue
            ym = D[i][:4] + D[i][5:7]
            rows.append((code, D[i], ym, senv.get(D[i], "震荡市"), mid.get(ym, "震荡市")) + tuple(t) +
                        (r5[i], r10[i], r20[i], m20m.get(D[i], np.nan)))
        if ci % 500 == 0:
            print(f"  {ci}/{len(codes)} 事件{len(rows)}", flush=True)

    cols = ["code", "date", "ym", "senv", "menv", "RSV启动", "RSV半启动", "RSV周破50", "123买入",
            "2B买入", "2B严格", "武威双阴", "武威一阴", "S1超跌RSI25", "r5", "r10", "r20", "mkt20"]
    E = pd.DataFrame(rows, columns=cols)
    E["ex20"] = E["r20"] - E["mkt20"]
    E.to_csv(f"{OUT}/weak_system_events.csv", index=False)
    print("事件总数", len(E))
    print(E[cols[5:14]].sum().to_string())


def yin(c, o, k): return c[k] < o[k]
def yang(c, o, k): return c[k] > o[k]


if __name__ == "__main__":
    main()
