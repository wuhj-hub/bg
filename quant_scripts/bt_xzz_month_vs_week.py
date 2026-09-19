#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
曾星智「月线力量」· 月线 vs 周线 移植适用性回测
    牛市 := MA5↑ 且 MA10↑ 且 MA20↑ 且 MA30↑ 且 月/周线DIF↑
    信号 = 非牛→牛 的转折期
"""
import pandas as pd, numpy as np

M_PATH = '/sandbox/workspace/zxz_bt/data/kline_month_adj.csv'
W_PATH = '/sandbox/workspace/zxz_bt/data/kline_week_adj.csv'
START = {'ym': '2010-01', 'wk': '2010-W01'}


def build(path, tcol):
    df = pd.read_csv(path)[['code', tcol, 'open', 'high', 'low', 'close']].dropna()
    df = df[df[tcol] >= START[tcol]]
    df = df.sort_values(['code', tcol], kind='mergesort').reset_index(drop=True)
    bull = pd.Series(False, index=df.index)
    difpos = pd.Series(False, index=df.index)
    for code, g in df.groupby('code', sort=False):
        c = pd.Series(g['close'].values)
        if len(c) < 45:
            continue
        ma = {k: c.rolling(k).mean() for k in (5, 10, 20, 30)}
        e10 = c.ewm(span=10, adjust=False).mean(); e22 = c.ewm(span=22, adjust=False).mean()
        dif = e10 - e22
        b = (ma[5].diff() > 0) & (ma[10].diff() > 0) & (ma[20].diff() > 0) & (ma[30].diff() > 0) & (dif.diff() > 0)
        bull.loc[g.index] = b.fillna(False).values
        difpos.loc[g.index] = (dif > 0).fillna(False).values
    df['bull'] = bull.values
    df['dif_pos'] = difpos.values
    # 转折
    prev = df.groupby('code', sort=False)['bull'].shift(1, fill_value=False)
    df['sig'] = df['bull'] & (~prev)
    return df


def add_fwd(df, horizons):
    """加 forward 收益列：下一期开盘入场 → 第 N 期收盘出场"""
    for N in horizons:
        sr = pd.Series(np.nan, index=df.index)
        for code, g in df.groupby('code', sort=False):
            ob = g['open'].shift(-1); cl = g['close'].shift(-N)
            sr.loc[g.index] = (cl / ob - 1).values
        df[f'r{N}'] = sr
    return df


def report(df, horizons, tcol, label):
    print(f"\n{'='*84}\n{label}\n{'='*84}")
    sig = df[df['sig']].copy()
    rows = []
    for N in horizons:
        bench = df.groupby(tcol)[f'r{N}'].mean()          # 全市场同期等权基准
        s = sig.dropna(subset=[f'r{N}']).copy()
        s['ex'] = s[f'r{N}'] - s[tcol].map(bench)
        s = s.dropna(subset=['ex'])
        rows.append(dict(持有=N, 信号数=len(s),
                         均值=s[f'r{N}'].mean()*100, 中位=s[f'r{N}'].median()*100,
                         胜率=(s[f'r{N}']>0).mean()*100,
                         超额=s['ex'].mean()*100, 超额胜率=(s['ex']>0).mean()*100))
    r = pd.DataFrame(rows)
    print(r.to_string(index=False, float_format=lambda x: f"{x:7.2f}"))
    return r


print("loading...")
M = build(M_PATH, 'ym'); W = build(W_PATH, 'wk')
print(f"  月线 {len(M):,} 行 / {M['code'].nunique():,} 只 | 周线 {len(W):,} 行 / {W['code'].nunique():,} 只")
print(f"  月线区间 {M['ym'].min()}~{M['ym'].max()} | 周线区间 {W['wk'].min()}~{W['wk'].max()}")

H_M = [1, 2, 3, 6, 12]
H_W = [4, 9, 13, 26, 52]
M = add_fwd(M, H_M); W = add_fwd(W, H_W)

n_m = M['sig'].sum(); n_w = W['sig'].sum()
print(f"\n★ 信号密度：月线版 {n_m:,} 个（占 {n_m/len(M)*100:.2f}%） | 周线版 {n_w:,} 个（占 {n_w/len(W)*100:.2f}%）")
print(f"★ 周线版信号数是月线版的 {n_w/n_m:.1f} 倍")

rm = report(M, H_M, 'ym', "【A】月线版 · 持有 N 个月")
rw = report(W, H_W, 'wk', "【B】周线版 · 持有 N 周")

# 时间对齐的公平对比（月线 3月 ≈ 周线 13周）
print(f"\n{'='*84}\n【C】时间对齐对比（同等持有跨度）\n{'='*84}")
print(f"{'跨度':<8}{'月线版超额':>12}{'周线版超额':>12}{'月线胜率':>10}{'周线胜率':>10}")
pairs = [('1月/4.3周', 1, 4), ('2月/8.7周', 2, 9), ('3月/13周', 3, 13), ('6月/26周', 6, 26), ('12月/52周', 12, 52)]
for lab, nm, nw in pairs:
    a = rm[rm['持有'] == nm].iloc[0]; b = rw[rw['持有'] == nw].iloc[0]
    print(f"{lab:<8}{a['超额']:>11.2f}%{b['超额']:>11.2f}%{a['胜率']:>9.1f}%{b['胜率']:>9.1f}%")

M.to_pickle('/tmp/M.pkl'); W.to_pickle('/tmp/W.pkl')
print("\n[saved] /tmp/M.pkl /tmp/W.pkl")
