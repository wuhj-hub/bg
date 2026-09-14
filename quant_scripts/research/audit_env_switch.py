#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""②.7 决策表数据支撑度审计
对每个 信号 × 环境：
  - 名义事件数、独立交易日数、覆盖年份
  - 按日聚合的超额收益序列（先按日取均值，消除同日截面相关）
  - Newey-West t 值（lag=20，校正 20 日持有期重叠）
输出 outputs/env_switch_audit.md
"""
import os
import numpy as np
import pandas as pd

BASE = "/sandbox/workspace/zxz_bt"
OUT = f"{BASE}/outputs"


def nw_t(x, lag=20):
    """Newey-West t 统计量"""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 30:
        return np.nan, np.nan, n
    m = x.mean()
    d = x - m
    g0 = (d @ d) / n
    s = g0
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        gl = (d[L:] @ d[:-L]) / n
        s += 2 * w * gl
    s = max(s, 1e-12)
    se = np.sqrt(s / n)
    return m / se, m, n


S = pd.read_csv(f"{BASE}/data/regime_new_daily.csv", dtype={"date": str})
M = pd.read_csv(f"{BASE}/data/regime_new_month.csv", dtype={"ym": str})
BASE_R = pd.read_csv(f"{OUT}/all_obs_r20.csv", dtype={"code": str, "date": str})
bmap = {}
for env in ["熊市", "震荡市", "牛市"]:
    bmap[("L", env)] = BASE_R[BASE_R.menv_new == env].r20f.mean() * 100
    bmap[("S", env)] = BASE_R[BASE_R.senv_new == env].r20f.mean() * 100

key = BASE_R[["code", "date", "r20f"]]

def prep(E, name_col=None):
    E = E.copy()
    E["ym"] = E["ym"].astype(str).str.zfill(6)
    E["ym"] = E["ym"].str[:4] + "-" + E["ym"].str[4:6]
    return E

ev = []
# ---- 旧信号 ----
E1 = prep(pd.read_csv(f"{OUT}/weak_system_events.csv", dtype={"code": str, "date": str}))
E1 = E1.merge(key, on=["code", "date"], how="left")
for c in ["RSV启动", "RSV半启动", "RSV周破50", "123买入", "2B买入", "2B严格", "武威双阴", "武威一阴", "S1超跌RSI25"]:
    sub = E1[E1[c] == True][["date", "r20f"]].copy()
    if len(sub):
        sub["signal"] = c
        ev.append(sub)
# ---- 鱼身/猛兽/双弦 ----
E2 = prep(pd.read_csv(f"{OUT}/yaogu_events2.csv", dtype={"code": str, "date": str}))
E2 = E2.merge(key, on=["code", "date"], how="left")
for k in E2["signal"].unique():
    sub = E2[E2.signal == k][["date", "r20f"]].copy()
    sub["signal"] = k
    ev.append(sub)
# ---- 猛兽 Setup ----
E3 = pd.read_csv(f"{OUT}/beast_setup_events.csv", dtype={"code": str, "date": str})
for th in [60]:
    sub = E3[E3.setup >= th][["date", "r20f"]].copy()
    sub["signal"] = f"猛兽Setup≥{th}"
    ev.append(sub)

ALL = pd.concat(ev, ignore_index=True)
ALL = ALL.merge(S[["date", "senv_new"]], on="date", how="left")
ALL["ym"] = ALL["date"].str[:4] + "-" + ALL["date"].str[5:7]
ALL = ALL.merge(M[["ym", "menv_new"]], on="ym", how="left")
ALL = ALL.dropna(subset=["r20f", "senv_new", "menv_new"])
print("合并事件", len(ALL))

NAME = {"S1超跌RSI25": "S1 超跌(RSI<25)", "RSV启动": "RSV启动", "RSV半启动": "RSV半启动",
        "RSV周破50": "RSV周线破50", "123买入": "123买入", "2B买入": "2B买入", "2B严格": "2B严格(未入表)",
        "武威双阴": "武威G1·双阴", "武威一阴": "武威G1·一阴",
        "鱼身均线回踩": "鱼身·均线回踩", "鱼身箱体突破": "鱼身·箱体突破", "鱼身黄金起爆": "鱼身·黄金起爆",
        "猛兽伏击线": "猛兽·伏击线", "猛兽RS_D低吸": "猛兽·RS_D低吸", "双弦低价共振": "双弦·低价共振",
        "猛兽Setup≥60": "猛兽·Setup≥60"}

L = ["# ②.7 决策表 · 数据支撑度审计\n",
     "**方法**：先按交易日聚合（同一天多只信号股取均值，消除截面相关），再对日度序列做 "
     "**Newey-West t 检验（lag=20，校正20日持有期重叠）**。|t|≥1.96 为 5% 显著，≥1.64 为 10% 显著。\n",
     "| 信号 | 环境 | 名义事件 | 独立交易日 | 年均事件 | 日均超额 | t值 | 结论 |",
     "|---|---|---|---|---|---|---|---|"]
verdict = {}
for sig, g in ALL.groupby("signal"):
    for dim, envcol, envs in [("长", "menv_new", ["熊市", "震荡市", "牛市"]),
                              ("短", "senv_new", ["熊市", "震荡市", "牛市"])]:
        for env in envs:
            s = g[g[envcol] == env]
            if len(s) < 30:
                continue
            s = s.copy()
            s["ex"] = s.r20f * 100 - bmap[("L" if dim == "长" else "S", env)]
            daily = s.groupby("date")["ex"].mean()
            t, m, nd = nw_t(daily.values, 20)
            yrs = max(1, s["date"].str[:4].nunique())
            v = ("✅ 5%显著" if abs(t) >= 1.96 else ("🔸 10%显著" if abs(t) >= 1.64 else "❌ 不显著"))
            L.append(f"| {NAME.get(sig, sig)} | {dim}·{env} | {len(s):,} | {nd:,} | {len(s)/yrs/244:.1f}/日 | "
                     f"{m:+.2f}% | {t:+.2f} | {v} |")
            verdict[(sig, dim, env)] = (m, t, len(s), nd)
L.append("")
L.append("## 汇总：各信号「显著为正」的环境数\n")
L.append("| 信号 | 显著为正(全环境) | 显著为负 | 不显著 | 判定可信度 |")
L.append("|---|---|---|---|---|")
for sig in NAME:
    pos = sum(1 for k, (m, t, n, nd) in verdict.items() if k[0] == sig and t >= 1.96)
    neg = sum(1 for k, (m, t, n, nd) in verdict.items() if k[0] == sig and t <= -1.96)
    neu = sum(1 for k, (m, t, n, nd) in verdict.items() if k[0] == sig and abs(t) < 1.96)
    tot = pos + neg + neu
    if tot == 0: continue
    c = "🟢 强" if pos >= 2 else ("🔴 明确无效" if neg >= 2 and pos == 0 else "🟡 弱/不稳")
    L.append(f"| {NAME[sig]} | {pos} | {neg} | {neu} | {c} |")
open(f"{OUT}/env_switch_audit.md", "w", encoding="utf-8").write("\n".join(L))
print("\n".join(L))
