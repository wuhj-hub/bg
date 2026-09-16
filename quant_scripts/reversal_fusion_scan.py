# -*- coding: utf-8 -*-
"""
融合策略扫描：零轴下第一次金叉 + 3K加均底
—— 用最新数据（akshare 新浪源）生成当前股池 + 形态明细
"""
import os, json, time, numpy as np, pandas as pd, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import akshare as ak

_orig = requests.get
def _get(*a, **k):
    k.setdefault("timeout", 8)
    return _orig(*a, **k)
requests.get = _get

BASE = "/sandbox/workspace"
OUTD = os.path.join(BASE, "data")
os.makedirs(OUTD, exist_ok=True)

uni = pd.read_csv(os.path.join(BASE, "data/mainboard_universe.csv"), dtype={"code": str})
name = dict(zip(uni["code"], uni["name"]))
codes = uni["code"].tolist()
print("universe:", len(codes), flush=True)

def sym(c): return ("sh" if c.startswith("6") else "sz") + c

def fetch(c):
    for _ in range(2):
        try:
            d = ak.stock_zh_a_daily(symbol=sym(c), adjust="qfq")
            if d is not None and len(d) >= 130:
                return c, d.tail(300).reset_index(drop=True)
        except Exception:
            time.sleep(0.5)
    return c, None

data = {}
done = 0
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = {ex.submit(fetch, c): c for c in codes}
    for f in as_completed(futs):
        c, d = f.result(); done += 1
        if d is not None: data[c] = d
        if done % 500 == 0: print("  fetched %d/%d" % (done, len(codes)), flush=True)

print("ok stocks:", len(data), flush=True)

def cross_up(a, b):
    o = np.zeros(len(a), bool); o[1:] = (a[:-1] <= b[:-1]) & (a[1:] > b[1:]); return o

rows = []
LAST_K = 5      # 最近5个交易日内出现的信号都收进池子
KEEP = 300
for c, d in data.items():
    close = d["close"].astype(float).values
    high  = d["high"].astype(float).values
    low   = d["low"].astype(float).values
    dates = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d").values
    n = len(close)
    s = pd.Series(close)
    dif = (s.ewm(span=12, adjust=False).mean().values - s.ewm(span=26, adjust=False).mean().values) / close * 100
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    macd = (dif - dea) * 2
    jc = cross_up(dif, dea)
    ma5 = s.rolling(5).mean().values
    hhv = pd.Series(macd).rolling(40, min_periods=1).max().values
    llv = pd.Series(macd).rolling(40, min_periods=1).min().values
    hong_fan1 = 0.618 * np.abs(llv)          # 红柱反转数值(1倍)
    lv_fan1 = 0.618 * hhv                     # 绿柱反转数值(1倍)
    lv_fan2 = 1.236 * hhv                     # 绿柱反转数值(2倍)
    for i in range(max(5, n - LAST_K - 1), n - 1):
        if not (jc[i] and dif[i] < 0):
            continue
        k3_hit = False; m_used = None
        for m in range(i - 4, i - 1):
            if 1 <= m < n - 1 and low[m] < low[m-1] and low[m] < low[m+1] and close[i] > high[m-1] and close[i] > ma5[i]:
                k3_hit = True; m_used = m; break
        if not k3_hit:
            continue
        rows.append({
            "code": c, "name": name.get(c, ""), "date": dates[i], "close": round(float(close[i]),2),
            "dif": round(float(dif[i]),3), "macd": round(float(macd[i]),3),
            "MA5": round(float(ma5[i]),2),
            "品字底K": f'{dates[m_used]}(低{low[m_used]:.2f})',
            "左K": f'{dates[m_used-1]}(高{high[m_used-1]:.2f})',
            "突破线": round(float(high[m_used-1]),2),
            "绿反转1": round(float(lv_fan1[i]),3), "绿反转2": round(float(lv_fan2[i]),3),
            "红反转1": round(float(hong_fan1[i]),3),
            "未破1倍": bool(macd[max(0,i-20):i+1].min() > -lv_fan1[i]),
            "量比": round(float(d["volume"].iloc[i]/max(1, d["volume"].iloc[i-5:i].mean())),2) if "volume" in d else None,
        })

P = pd.DataFrame(rows).sort_values(["date","code"], ascending=[False,True])
P.to_csv(os.path.join(OUTD, "反转数值融合股池.csv"), index=False, encoding="utf-8-sig")
print("\n股池信号数:", len(P))
if len(P):
    print(P[["date","code","name","close","MA5","突破线","未破1倍"]].to_string(index=False))
print("saved -> data/反转数值融合股池.csv")
