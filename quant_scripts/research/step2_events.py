"""妖股"走得远"六维特征提取
事件定义：放量异动启动日 —— 当日涨幅>=5% 且 量比>=2 且 前20日涨幅<25%（相对平静）
标签：启动日收盘起，后续 60 个交易日内的最大涨幅
维度：外围(纳指/恒生) / 板块(行业强度) / 涨停启动 / 筹码(换手活跃度) / 形态(建仓-拉升-洗盘) / 资金(量价)
"""
import numpy as np
import pandas as pd

df = pd.read_csv("data/kline_daily_vol.csv")
df = df[df.volume > 0]
pool = pd.read_csv("data/pool.csv")
ind_map = dict(zip(pool["code"], pool["industry"]))
df["industry"] = df["code"].map(ind_map)
df = df.dropna(subset=["industry"]).sort_values(["code", "date"]).reset_index(drop=True)
print("载入", len(df), "行", df.code.nunique(), "只")

# 外围
def load_idx(p):
    d = pd.read_csv(p)
    d["ret"] = d["close"].pct_change()
    return dict(zip(d["date"], d["ret"]))

us = load_idx("data/idx/usIXIC.csv")
hk = load_idx("data/idx/hkHSI.csv")

# 行业等权指数（用个股收益率均值近似，避免市值偏差）
df["pct"] = df.groupby("code")["close"].pct_change()
ind_ret = df.groupby(["date", "industry"])["pct"].mean().reset_index().rename(columns={"pct": "ind_pct"})
ind_ret["ind_ret20"] = ind_ret.groupby("industry")["ind_pct"].transform(
    lambda s: (1 + s).rolling(20).apply(np.prod, raw=True) - 1)
ind_ret["ind_ret60"] = ind_ret.groupby("industry")["ind_pct"].transform(
    lambda s: (1 + s).rolling(60).apply(np.prod, raw=True) - 1)
ind_map2 = {(r.date, r.industry): (r.ind_ret20, r.ind_ret60) for r in ind_ret.itertuples()}
# ST 剔除
st = {r["code"] for r in __import__("csv").DictReader(open("data/pool.csv", encoding="utf-8"))
      if "ST" in (r["name"] or "")}
print("ST 剔除", len(st))
df = df[~df["code"].isin(st)]

VOL_W, ZT = 20, 0.095
rows = []
for code, g in df.groupby("code"):
    g = g.reset_index(drop=True)
    c = g["close"].values; h = g["high"].values; l = g["low"].values
    o = g["open"].values; v = g["volume"].values
    d = g["date"].values; ind = g["industry"].iloc[0]
    n = len(g)
    if n < 200:
        continue
    pct = np.concatenate([[np.nan], c[1:] / c[:-1] - 1])
    zt = pct >= ZT
    vma20 = pd.Series(v).rolling(VOL_W).mean().values
    vma120 = pd.Series(v).rolling(120).mean().values
    ma5 = pd.Series(c).rolling(5).mean().values
    ma10 = pd.Series(c).rolling(10).mean().values
    ma20 = pd.Series(c).rolling(20).mean().values
    ma60 = pd.Series(c).rolling(60).mean().values
    ma120 = pd.Series(c).rolling(120).mean().values
    tr = np.maximum(h - l, np.maximum(abs(h - np.concatenate([[np.nan], c[:-1]])),
                                       abs(l - np.concatenate([[np.nan], c[:-1]]))))
    atr20 = pd.Series(tr).rolling(20).mean().values
    hh60 = pd.Series(h).rolling(60).max().values
    for i in range(130, n - 61):
        if not (pct[i] >= 0.05 and pct[i] <= 0.25 and vma20[i] > 0 and v[i] / vma20[i] >= 2):
            continue
        if c[i] <= 0.3 or c[i - 1] <= 0.3:
            continue
        ret20 = c[i - 1] / c[i - 21] - 1
        if ret20 >= 0.25:
            continue
        ret60 = c[i - 1] / c[i - 61] - 1
        # 筹码/形态（截至启动前一日）
        shrink = vma20[i - 1] / vma120[i - 1] if vma120[i - 1] > 0 else np.nan   # 缩量度：越小越缩量
        amp = np.std(pct[i - 60:i]) if not np.isnan(pct[i - 60:i]).any() else np.nan
        box = (h[i - 60:i].max() - l[i - 60:i].min()) / c[i - 1]                   # 箱体高度
        turn60 = v[i - 60:i].sum() / vma20[i - 1] / 60                             # 相对换手累积
        bull = 1.0 if (not np.isnan(ma5[i - 1]) and ma5[i - 1] > ma10[i - 1] > ma20[i - 1] > ma60[i - 1]) else 0.0
        # 后续
        fut = c[i:min(i + 61, n)]
        fh = h[i:min(i + 61, n)]
        max60 = fh.max() / c[i] - 1
        r20f = c[min(i + 20, n - 1)] / c[i] - 1
        zt60 = int(zt[i + 1:min(i + 61, n)].sum())
        # 最大连板
        run = mx = 0
        for j in range(i, min(i + 61, n)):
            run = run + 1 if zt[j] else 0
            mx = max(mx, run)
        dt = d[i]
        u = us.get(dt, np.nan)
        k = hk.get(dt, np.nan)
        ir20, ir60 = ind_map2.get((dt, ind), (np.nan, np.nan))
        rows.append([code, dt, ind, pct[i], 1.0 if zt[i] else 0.0,
                     v[i] / vma20[i], o[i] / c[i - 1] - 1,   # 开盘涨幅（一字/高开）
                     ret20, ret60, c[i - 1] / ma20[i - 1] - 1, c[i - 1] / ma60[i - 1] - 1,
                     c[i - 1] / ma120[i - 1] - 1, c[i - 1] / hh60[i - 1] - 1,
                     atr20[i - 1] / c[i - 1], bull, shrink, amp, box, turn60,
                     max60, r20f, zt60, mx, u, k, ir20, ir60, np.log(c[i])])
    if len(rows) % 20000 < 40:
        print("  ...", len(rows), flush=True)

cols = ["code", "date", "industry", "pct", "is_zt_hit", "volr", "open_gap",
        "ret20", "ret60", "pma20", "pma60", "pma120", "pdist_hi60", "atr_pct", "ma_bull",
        "shrink", "amp", "box", "turn60", "max60", "r20_fwd", "zt60", "max_lianban",
        "us_prev", "hk_day", "ind_ret20", "ind_ret60", "logprice"]
E = pd.DataFrame(rows, columns=cols)
E.to_csv("outputs/yaogu_events.csv", index=False)
print("事件数", len(E))
print(E[["max60", "max_lianban", "volr", "pct"]].describe().round(3))
