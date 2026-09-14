#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 market_regime.py 的精确口径（三级力量·5根线）重算环境，join 到信号事件上
长期力量 = 月线 MA5/10/20/30 + MACD-DIF 方向（对应回测的"中期环境"）
短期力量 = 日线 MA5/10/20/30 + MACD-DIF 方向（对应回测的"短期环境"）
"""
import json, os, urllib.request
import numpy as np
import pandas as pd

BASE = "/sandbox/workspace/zxz_bt"
DATA = f"{BASE}/data"


def ths(code):
    url = f"http://d.10jqka.com.cn/v6/line/hs_{code}/01/all.js"
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
    n = min(len(full), len(P) // 4)
    return [(full[i], (P[4 * i] + P[4 * i + 3]) / pf) for i in range(n)]


def power_state(C):
    """照搬 market_regime.py：5根线方向 → 状态"""
    s = pd.Series(C, dtype="float64")
    if len(s) < 35:
        return None, None
    ma = {k: s.rolling(k).mean() for k in (5, 10, 20, 30)}
    dif = s.ewm(span=10, adjust=False).mean() - s.ewm(span=22, adjust=False).mean()
    up = sum([(ma[k] > ma[k].shift(1)).astype(float) for k in (5, 10, 20, 30)]) + (dif > dif.shift(1)).astype(float)
    return up, up / 5


def buck(x):
    return "牛市" if x >= 4 else ("熊市" if x <= 1 else "震荡市")


def main():
    print("拉上证指数 日线/月线 …")
    daily = ths("000001")
    ddf = pd.DataFrame(daily, columns=["date", "close"])
    dd = ddf.copy(); dd["ym"] = dd["date"].str[:7]
    mo = dd.groupby("ym")["close"].last().reset_index()
    upS, scS = power_state(ddf["close"].values)
    upL, scL = power_state(mo["close"].values)
    S = pd.DataFrame({"date": ddf["date"], "s_up": upS, "s_sc": scS}).dropna()
    S["senv_new"] = S["s_up"].map(buck)
    M = pd.DataFrame({"ym": mo["ym"], "l_up": upL, "l_sc": scL}).dropna()
    M["menv_new"] = M["l_up"].map(buck)
    # 月线状态滞后一期（避免用当月未完成数据）
    M["menv_new"] = M["menv_new"].shift(1)
    print("上证 日线状态分布:", S["senv_new"].value_counts().to_dict())
    print("上证 月线(滞后)状态分布:", M["menv_new"].value_counts().to_dict())
    S.to_csv(f"{DATA}/regime_new_daily.csv", index=False)
    M.to_csv(f"{DATA}/regime_new_month.csv", index=False)

    E = pd.read_csv(f"{BASE}/outputs/weak_system_events.csv", dtype={"code": str, "date": str})
    E["ym"] = E["ym"].astype(str).str.zfill(6)
    E["ym"] = E["ym"].str[:4] + "-" + E["ym"].str[4:6]
    S["date"] = S["date"].astype(str)
    E = E.merge(S[["date", "senv_new"]], on="date", how="left").merge(M[["ym", "menv_new"]], on="ym", how="left")
    E = E.dropna(subset=["senv_new", "menv_new"])
    print("join 后事件", len(E))
    names = {"RSV启动": "RSV启动(RSV均<20拐头↑)", "RSV半启动": "RSV半启动(20-40+涨停)", "RSV周破50": "RSV周线破50",
             "123买入": "123买入(突破次高+回踩)", "2B买入": "2B买入(20日新低收回2%)", "2B严格": "2B严格(低点≥5日前+5%)",
             "武威双阴": "武威G1·双阴", "武威一阴": "武威G1·一阴", "S1超跌RSI25": "S1超跌(RSI<25)"}
    L = ["# 环境切换决策表（market_regime 精确口径验证版）\n",
         "- 环境口径 = `market_regime.py` 三级别力量：**长期力量**=月线 MA5/10/20/30+DIF 方向；**短期力量**=日线同口径（5 线全向下=弱势向下→熊市，2-3 线向上=纠缠→震荡市，4-5 线向上→牛市）",
         f"- 样本 {len(E):,} 个信号观测；超额 = 个股 20 日收益 − 同期全市场等权\n"]
    for ec, en in (("menv_new", "长期力量（月线）"), ("senv_new", "短期力量（日线）")):
        for env in ["熊市", "震荡市", "牛市"]:
            b = E[E[ec] == env]
            if len(b) < 200: continue
            L.append(f"## {en} = {env}（样本 {len(b):,}）\n")
            L.append("| 信号 | 样本 | 20日均值 | 20日中位 | 20日胜率 | 20日超额 |")
            L.append("|---|---|---|---|---|---|")
            bm = b["mkt20"].mean()
            L.append(f"| *（全市场基准）* | {len(b):,} | {bm*100:+.2f}% | - | - | - |")
            out = []
            for k, nm in names.items():
                s = b[b[k]].dropna(subset=["r20"])
                if len(s) < 100: continue
                out.append((nm, len(s), s.r20.mean(), s.r20.median(), (s.r20 > 0).mean(), s.r20.mean() - s.mkt20.mean()))
            out.sort(key=lambda x: -x[5])
            for nm, n, c, m, w, ex in out:
                L.append(f"| {nm} | {n:,} | **{c*100:+.2f}%** | {m*100:+.2f}% | {w*100:.1f}% | {ex*100:+.2f}% |")
            L.append("")
    open(f"{BASE}/outputs/环境切换决策表_验证.md", "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
