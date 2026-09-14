#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""弱市（震荡/熊市）适用信号验证
从现有体系抽取可量化的「非趋势型」信号，按市场环境分层回测：
  S1 超跌         = RSI(14) < 25                       ← 腰缠万贯/RSV 超跌思路
  S2 超跌拐头     = RSI(14) < 30 且 当日收阳            ← 反转数值 / 123-2B 反转思路
  S3 回调MA20企稳 = |C/MA20-1|<3% 且 收阳 且 振幅收窄    ← 武威量价 / 双弦低吸 / 鱼身回踩思路
  S4 抗跌         = 近20日跑赢市场 >5%                  ← 抗跌性过滤层
  S5 强势(对照)   = C/MA20-1 >5% 且 20日涨幅>10%         ← 趋势型（牛市用）
收益：次日开盘买入，持有 5/10/20 日；按市场环境(短期/中期)分层 + 相对等权基准的超额
"""
import os
import numpy as np
import pandas as pd

BASE = "/sandbox/workspace/zxz_bt"
DATA, OUT = os.path.join(BASE, "data"), os.path.join(BASE, "outputs")


def rsi(C, n=14):
    d = C.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def main():
    df = pd.read_csv(os.path.join(DATA, "kline_daily_qfq.csv"), dtype={"code": str, "date": str})
    df = df[df["close"] > 0].sort_values(["code", "date"]).reset_index(drop=True)
    ret = df.pivot_table(index="date", columns="code", values="close").pct_change(fill_method=None)
    mk = (1 + ret.mean(axis=1).fillna(0.0)).cumprod()
    ma20m = mk.rolling(20).mean(); ma60m = mk.rolling(60).mean()
    short_env = pd.Series(np.where((mk > ma20m) & (ma20m > ma60m), "牛市",
                          np.where((mk < ma20m) & (ma20m < ma60m), "熊市", "震荡市")), index=mk.index)
    mk2 = mk.copy(); mk2.index = pd.to_datetime(mk2.index, format="%Y-%m-%d")
    mm = mk2.resample("ME").last().dropna()
    m6 = mm.rolling(6).mean(); m12 = mm.rolling(12).mean()
    mid = pd.Series(np.where((mm > m6) & (m6 > m12), "牛市",
                    np.where((mm < m6) & (m6 < m12), "熊市", "震荡市")), index=mm.index)
    mid.index = mid.index.strftime("%Y%m")
    mkt20 = (1 + ret.mean(axis=1).fillna(0.0)).rolling(20).apply(np.prod, raw=True) - 1
    m20 = dict(zip(mkt20.index, mkt20.values))

    rows = []
    for code, g in df.groupby("code", sort=False):
        g = g.reset_index(drop=True)
        if len(g) < 90:
            continue
        C, H, L, O = g["close"], g["high"], g["low"], g["open"]
        ma20 = C.rolling(20).mean()
        r = rsi(C, 14)
        atr = (H - L).rolling(20).mean() / C
        ret20 = C / C.shift(20) - 1
        rs20 = pd.Series([ret20.iloc[i] - m20.get(g.loc[i, "date"], np.nan) for i in range(len(g))], index=g.index)
        dist20 = C / ma20 - 1
        nxt = O.shift(-1)
        ok = (nxt > 0)
        r5 = pd.Series(np.where(ok, C.shift(-5) / nxt.replace(0, np.nan) - 1, np.nan), index=g.index)
        r10 = pd.Series(np.where(ok, C.shift(-10) / nxt.replace(0, np.nan) - 1, np.nan), index=g.index)
        r20 = pd.Series(np.where(ok, C.shift(-20) / nxt.replace(0, np.nan) - 1, np.nan), index=g.index)
        ym = g["date"].str[:4] + g["date"].str[5:7]
        for i in range(70, len(g) - 21):
            if np.isnan(r.iloc[i]) or np.isnan(ma20.iloc[i]) or np.isnan(rs20.iloc[i]):
                continue
            bull_c = C.iloc[i] > O.iloc[i]
            narrow = atr.iloc[i] < atr.iloc[i - 20] if not np.isnan(atr.iloc[i - 20]) else False
            rows.append((g.loc[i, "date"], ym.iloc[i], short_env.get(g.loc[i, "date"], "震荡市"),
                         mid.get(ym.iloc[i], "震荡市"),
                         bool(r.iloc[i] < 25), bool(r.iloc[i] < 30 and bull_c),
                         bool(abs(dist20.iloc[i]) < .03 and bull_c and narrow),
                         bool(rs20.iloc[i] > .05),
                         bool(dist20.iloc[i] > .05 and ret20.iloc[i] > .10),
                         r5.iloc[i], r10.iloc[i], r20.iloc[i]))
    D = pd.DataFrame(rows, columns=["date", "ym", "senv", "menv", "S1", "S2", "S3", "S4", "S5", "r5", "r10", "r20"])
    print("样本", len(D), "日期", D.date.min(), "~", D.date.max())

    def stat(sub):
        if len(sub) < 50:
            return None
        o = []
        for c in ("r5", "r10", "r20"):
            x = sub[c].dropna()
            o.append((x.mean(), (x > 0).mean(), x.median(), x.quantile(.25)))
        return o

    L = ["# 弱市（震荡/熊市）适用信号验证\n",
         f"- 样本：3070 只主板股 × 近 800 交易日（前复权），共 {len(D):,} 个交易日观测",
         "- 收益：次日开盘买入，持有 5/10/20 日；**超额 = 个股收益 − 同期全市场等权**",
         "- 信号 S1–S5 见脚本说明\n"]

    names = {"S1": "S1 超跌(RSI<25)", "S2": "S2 超跌拐头(RSI<30且收阳)",
             "S3": "S3 回调MA20企稳(收阳+振幅收窄)", "S4": "S4 抗跌(20日跑赢>5%)",
             "S5": "S5 强势(对照·趋势型)"}
    for env_col, env_name in (("senv", "短期环境(日线)"), ("menv", "中期环境(月线)")):
        for env in ["震荡市", "熊市", "牛市"]:
            base = D[D[env_col] == env]
            if len(base) < 500:
                continue
            L.append(f"### {env_name} = {env}（基准样本 {len(base):,}）")
            L.append("| 信号 | 样本 | 5日 | 10日 | 20日均值 | 20日中位 | 20日胜率 |")
            L.append("|---|---|---|---|---|---|---|")
            bm = base["r20"].mean()
            for k, nm in names.items():
                s = stat(base[base[k]])
                if not s:
                    continue
                L.append(f"| {nm} | {len(base[base[k]]):,} | {s[0][0]*100:+.2f}% | {s[1][0]*100:+.2f}% | "
                         f"**{s[2][0]*100:+.2f}%** | {s[2][2]*100:+.2f}% | {s[2][1]*100:.1f}% |")
            L.append(f"| *（该环境全部样本基准）* | {len(base):,} | - | - | {bm*100:+.2f}% | {base['r20'].median()*100:+.2f}% | {(base['r20']>0).mean()*100:.1f}% |")
            L.append("")
    txt = "\n".join(L)
    open(os.path.join(OUT, "weak_market_signals.md"), "w", encoding="utf-8").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
