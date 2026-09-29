#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jingjia_stats.py —— 竞价统计模块
================================================
比较三个竞价/强势策略的效果：
  1) 紫霞牛        (纯竞价形态，需当日集合竞价额)
  2) 一进二        (首板背景 + 竞价强度)
  3) 超级竞价(GZB) (纯日线 OHLCV 选股)

统一口径：
  universe = 沪深主板非ST（剔创业板/科创板/北交所/ST），价格不限。
  收益口径 = 信号日 T（收盘确认）→ 次日 T+1 竞价开盘价买入
             → 统计 T+1 当日及 T+2/T+3/T+5 收盘收益。

数据源：
  日线 / 分钟：westock-data-skillhub (kline)
  流通市值/股本：腾讯 qt.gtimg.cn

用法：
  python3 jingjia_stats.py --universe all_mainboard.csv --dlimit 600 \
      --m1start 2026-09-01 --m1end 2026-09-29
"""
import os, sys, re, json, time, gzip, argparse, subprocess
_DBG = {}
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd

WESTOCK = ["npx", "-y", "westock-data-skillhub"]
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "outputs")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


# ============================ 外部数据拉取 ============================
def _run_westock(args, timeout=240, retries=3):
    for i in range(retries):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.stdout and "执行失败" not in r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(1.5 * (i + 1))
    return ""


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def parse_kline_txt(txt):
    out = defaultdict(list)
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if header is None or not parts or "---" in parts[0]:
            continue
        try:
            d = {header[i]: parts[i] for i in range(min(len(header), len(parts)))}
            sym = d.get("symbol", "")
            if not sym:
                continue
            out[sym].append({
                "date": d["date"][:10],
                "open": float(d["open"]), "close": float(d["last"]),
                "high": float(d["high"]), "low": float(d["low"]),
                "volume": float(d.get("volume") or 0), "amount": float(d.get("amount") or 0),
                "dt_full": d["date"],
            })
        except Exception:
            continue
    for k in out:
        out[k].sort(key=lambda r: r["dt_full"])
    return out


def fetch_daily(codes, limit, batch=25, workers=1, tag=""):
    cachef = os.path.join(CACHE, f"daily_{tag}_{limit}_{len(codes)}.json.gz")
    if os.path.exists(cachef):
        with gzip.open(cachef, "rt") as f:
            return json.load(f)
    import gzip as _gz
    res = defaultdict(list)

    def work(chunk):
        return parse_kline_txt(_run_westock(["kline", ",".join(chunk), "--period", "day", "--limit", str(limit)]))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fu in as_completed([ex.submit(work, c) for c in _chunks(codes, batch)]):
            for k, v in fu.result().items():
                res[k] = v
    with _gz.open(cachef, "wt") as f:
        json.dump(res, f)
    return res


def fetch_m1(codes, dates, batch=40, workers=6):
    """逐交易日批量抓 m1（接口每次仅返回一天），提取09:30竞价bar → {sym:{date:{o,v,amt}}}"""
    tag = f"{dates[0]}_{dates[-1]}_{len(dates)}"
    cachef = os.path.join(CACHE, f"m1_{tag}_{len(codes)}.json.gz")
    if os.path.exists(cachef):
        with gzip.open(cachef, "rt") as f:
            return json.load(f)
    import gzip as _gz
    res = defaultdict(dict)
    tasks = [(d, c) for d in dates for c in _chunks(codes, batch)]

    def work(t):
        d, chunk = t
        rows = parse_kline_txt(_run_westock(["kline", ",".join(chunk), "--period", "m1",
                                             "--start", d, "--end", d], timeout=120, retries=2))
        out = defaultdict(dict)
        for sym, rs in rows.items():
            for r in rs:
                if r["dt_full"].endswith("09:30:00") and r["date"] == d:
                    out[sym][d] = {"o": r["open"], "v": r["volume"], "amt": r["amount"]}
        return out

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fu in as_completed([ex.submit(work, t) for t in tasks]):
            for sym, dd in fu.result().items():
                res[sym].update(dd)
    with _gz.open(cachef, "wt") as f:
        json.dump(res, f)
    return res


def fetch_caps(wcodes, batch=60):
    cachef = os.path.join(CACHE, f"caps_{len(wcodes)}.json.gz")
    if os.path.exists(cachef):
        with gzip.open(cachef, "rt") as f:
            return json.load(f)
    import gzip as _gz, urllib.request
    res = {}

    def work(chunk):
        url = "https://qt.gtimg.cn/q=" + ",".join(chunk)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com"})
        raw = urllib.request.urlopen(req, timeout=20).read().decode("gbk", "replace")
        d = {}
        for line in raw.split(";"):
            line = line.strip()
            m = re.match(r'v_(\w+)="([^"]*)"', line)
            if not m:
                continue
            p = m.group(2).split("~")
            if len(p) < 48:
                continue
            try:
                d[m.group(1)] = {"name": p[1], "price": float(p[3] or 0), "prevclose": float(p[4] or 0),
                                 "float_mv": float(p[44] or 0), "total_mv": float(p[45] or 0),
                                 "float_shares": float(p[47] or 0)}
            except Exception:
                pass
        return d

    with ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(work, list(_chunks(wcodes, batch))):
            res.update(r)
    with _gz.open(cachef, "wt") as f:
        json.dump(res, f)
    return res


# ============================ 指标函数（对齐通达信） ============================
def REF(x, n):
    x = np.asarray(x, float)
    return np.concatenate([np.full(n, np.nan), x[:-n]]) if n > 0 else x


def EMA(x, n):
    x = np.asarray(x, float); a = 2.0 / (n + 1); out = np.full_like(x, np.nan); e = None
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        e = v if e is None else a * v + (1 - a) * e
        out[i] = e
    return out


def SMA(x, n, m):
    x = np.asarray(x, float); out = np.full_like(x, np.nan); y = None
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        y = v if y is None else (m * v + (n - m) * y) / n
        out[i] = y
    return out


def MA(x, n):
    return pd.Series(np.asarray(x, float)).rolling(n).mean().values


def HHV(x, n):
    return pd.Series(np.asarray(x, float)).rolling(n).max().values


def LLV(x, n):
    return pd.Series(np.asarray(x, float)).rolling(n).min().values


def SUM0(x):
    return np.nancumsum(np.asarray(x, float))


def COUNT(x, n):
    return pd.Series(np.nan_to_num(np.asarray(x, float))).rolling(n).sum().values


def EXIST(x, n):
    return (pd.Series(np.nan_to_num(np.asarray(x, float))).rolling(n).sum().values > 0).astype(float)


def CROSS(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float) if np.ndim(b) else np.full_like(a, b)
    return ((REF(a, 1) <= REF(b, 1)) & (a > b)).astype(float)


def FORCAST(x, n):
    """线性回归预测值（预测下一周期，t=1..n）"""
    x = np.asarray(x, float); L = len(x); i = np.arange(L, dtype=float); k = np.arange(L, dtype=float)
    Sx = pd.Series(x).rolling(n).sum().values
    SiX = pd.Series(i * x).rolling(n).sum().values
    Sxx = (n * (n + 1) * (2 * n + 1) / 6.0) - n * ((n + 1) / 2.0) ** 2  # Σ(t-t̄)², 常数
    slope = (SiX - (k - n) * Sx - (n + 1) / 2.0 * Sx) / Sxx
    return Sx / n + slope * (n + 1) / 2.0


def DMA(x, a):
    x = np.asarray(x, float); a = np.asarray(a, float); out = np.full_like(x, np.nan); y = None
    for i in range(len(x)):
        if np.isnan(x[i]):
            continue
        ai = a[i] if (i < len(a) and not np.isnan(a[i])) else 0.0
        y = x[i] if y is None else ai * x[i] + (1 - ai) * y
        out[i] = y
    return out


def FILTER(x, n):
    x = np.asarray(x, float) > 0; out = np.zeros(len(x), float); last = -10 ** 9
    for i in range(len(x)):
        if x[i] and (i - last) > n:
            out[i] = 1.0; last = i
    return out


def ZTPRICE(prev, pct):
    return np.round(np.asarray(prev, float) * (1 + pct), 2)


def div(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    return np.divide(a, b, out=np.full_like(a, np.nan), where=(b != 0))


# ============================ 策略3：超级竞价 (GZB) ============================
def build_gzb(d):
    C = np.array([r["close"] for r in d], float)
    O = np.array([r["open"] for r in d], float)
    H = np.array([r["high"] for r in d], float)
    L = np.array([r["low"] for r in d], float)
    V = np.array([r["volume"] for r in d], float)
    n = len(C)
    if n < 80:
        return np.zeros(n, bool)
    Cprev = REF(C, 1)
    GZB4 = div(C, MA(REF(C, 18), 18)) * 100
    GZB5 = MA(FORCAST(GZB4, 20), 6)
    GZB6 = EMA(C, 240) - EMA(C, 520)
    GZB8 = GZB6 * 2 - EMA(GZB6, 180)
    GZB9 = SMA(GZB8, 3, 1)
    GZB15 = EMA(C, 60) - EMA(C, 130)
    GZB17 = GZB15 * 2 - EMA(GZB15, 45)
    GZB18 = SMA(GZB17, 3, 1)
    GZB19 = EMA(C, 12) - EMA(C, 26)
    GZB20 = EMA(GZB19, 9)
    GZB21 = GZB19 * 2 - GZB20
    GZB22 = SMA(GZB21, 3, 1)

    up9 = (C / Cprev > 1.09)
    GZB31 = np.where(up9 & (COUNT(up9, 10) <= 1), 1.0, 0.0)
    GZB32 = (EMA(2.055 * EMA(EMA(H, 34), 34) - EMA(EMA(L, 34), 34), 5) > C)
    GZB33 = (C / Cprev - 1 >= 0.08)
    GZB34 = L < REF(L, 2); GZB35 = L < REF(L, 1)
    GZB36 = div(O - L, C - O) >= 1.48
    GZB37 = C > Cprev; GZB42 = C > Cprev; GZB46 = C > Cprev
    GZB38 = (C / Cprev - 1 >= 0.0502)
    GZB39 = div(H - C, C - O) < 0.33
    GZB40 = V > REF(V, 1) * 2.5
    GZB41 = V > REF(V, 1)
    GZB43 = (C / Cprev - 1 >= 0.0502)
    GZB44 = div(H - C, C - O) < 0.33
    GZB45 = (C / Cprev - 1 >= 0.049)
    GZB47 = V > REF(V, 1) * 1.9
    cond48 = ((GZB47 & GZB46 & GZB45 & GZB44) |
              (GZB43 & GZB42 & GZB41 & GZB40 & GZB39) |
              (GZB38 & GZB37 & GZB36 & GZB35 & GZB34) |
              (GZB33 & GZB32))
    GZB48 = (FILTER(cond48, 34) * GZB31) > 0.5

    GZB49 = C / Cprev > 1.048
    GZB50 = C == H
    GZB51 = (FORCAST(V, 4) >= 0.2 * FORCAST(V, 12)) & (FORCAST(V, 4) <= 2.1 * FORCAST(V, 12))
    GZB52 = L > REF(C, 1) * 0.93
    rsv = div(C - LLV(L, 9), HHV(H, 9) - LLV(L, 9)) * 100
    K = SMA(rsv, 3, 1); Dk = SMA(K, 3, 1); J = 3 * K - 2 * Dk
    GZB53 = J - REF(J, 1) > 30
    GZB54 = C / Cprev > 1.043
    DIF = EMA(C, 12) - EMA(C, 26); DEA = EMA(DIF, 9); MACH = (DIF - DEA) * 2

    va = np.maximum(V / 700000000.0, 1.1 * (np.maximum(H, Cprev) / np.minimum(L, Cprev) - 1))
    DMA_ = DMA(C, 2.5 * va)
    GZB57 = SMA(20 * (div(DMA_, REF(DMA_, 1)) - 1), 2, 1)
    GZB58 = EMA(GZB57, 2)
    _z = (GZB57 > 0.24) & (GZB58 >= 0.005) & (C >= Cprev)
    part_a = (FILTER(GZB49 & GZB50 & GZB51, 28) > 0.5) & GZB52
    part_b = (GZB53 & GZB54 & (MACH > 0) & (DEA > 0)) & \
             (CROSS(_z.astype(float), 0.5) > 0.5) & \
             (COUNT(_z.astype(float), 10) == 1)
    GZB63 = part_a | part_b | GZB48

    TP = (L + H + C) / 3.0
    MA_TP5 = MA(TP, 5)
    GZB64 = L < HHV(MA_TP5, 13)
    GZB65 = H > HHV(MA_TP5, 13)
    GZB66 = C > Cprev
    _up = (MA_TP5 > REF(MA_TP5, 1)) & (REF(MA_TP5, 1) < REF(MA_TP5, 2))
    GZB67 = COUNT(_up, 2)
    prev_pat = (GZB64 & GZB65 & GZB66 & (C > O) & (GZB67 > 0))
    GZB68 = ~(REF(prev_pat.astype(float), 1) > 0)
    GZB69 = GZB64 & GZB65 & GZB66 & (C > O) & (GZB67 > 0) & GZB68

    GZB71 = C >= ZTPRICE(Cprev, 0.1) - 0.001
    GZB72 = (COUNT(GZB71, 2) == 1) & GZB71

    GZB74 = V > MA(V, 89)
    GZB77 = EMA(C, 5) > EMA(C, 29)
    GZB79 = div(SMA(np.maximum(C - Cprev, 0), 12, 1), SMA(np.abs(C - Cprev), 12, 1)) * 100
    GZB80 = div(SMA(np.maximum(C - Cprev, 0), 56, 1), SMA(np.abs(C - Cprev), 56, 1)) * 100
    GZB81 = (GZB79 > GZB80) & GZB77 & GZB74
    GZB84 = (REF((HHV(H, 30) / LLV(L, 30) - 1) * 100 <= 30, 1) > 0)
    GZB85 = np.abs(div((3.48 * C + H + L) / 4 - EMA(C, 23), EMA(C, 23)))
    GZB86 = DMA((2.15 * C + L + H) / 4, GZB85)
    GZB87 = EMA(GZB86, 200) * 1.1
    GZB89 = (CROSS(C, GZB87) > 0.5) & (REF(C * 1.097, 1) < C) & GZB81 & GZB84 & GZB72

    GZB26 = EMA(EMA(div(C - LLV(L, 9), HHV(H, 9) - LLV(L, 9)) * 100, 3), 3)
    GZB92 = (CROSS(GZB4, GZB5) > 0.5) & (GZB21 > GZB22) & (GZB17 > GZB18) & (GZB8 > GZB9) & \
            GZB72 & (GZB26 - MA(GZB26, 3) >= -1)
    GZB93 = (C / Cprev > 1.048) & (C == H) & GZB51
    GZB94 = (FILTER(GZB93, 28) > 0.5) & GZB72 & (GZB26 - MA(GZB26, 3) >= -1) & GZB63
    GZB100 = GZB92 | GZB89 | GZB94
    global _DBG
    _DBG = {"48": int(np.nansum(GZB48)), "63": int(np.nansum(GZB63)), "69": int(np.nansum(GZB69)),
            "72": int(np.nansum(GZB72)), "81": int(np.nansum(GZB81)), "84": int(np.nansum(GZB84)),
            "cross45": int(np.nansum(CROSS(GZB4, GZB5) > 0.5)),
            "tri": int(np.nansum((GZB21 > GZB22) & (GZB17 > GZB18) & (GZB8 > GZB9))),
            "crossC87": int(np.nansum(CROSS(C, GZB87) > 0.5)),
            "93": int(np.nansum(GZB93)),
            "89": int(np.nansum(GZB89)), "92": int(np.nansum(GZB92)),
            "94": int(np.nansum(GZB94)), "100": int(GZB100.sum())}
    return GZB100.astype(bool)


# ============================ 策略1：紫霞牛 ============================
def zixia_niu(d, auc, cap):
    res = {}
    if not d or not auc:
        return res
    C = np.array([r["close"] for r in d], float)
    O = np.array([r["open"] for r in d], float)
    L = np.array([r["low"] for r in d], float)
    V = np.array([r["volume"] for r in d], float)
    dates = [r["date"] for r in d]
    MA30 = MA(C, 30)
    STD60 = pd.Series(C).rolling(60).std(ddof=1).values
    QS上 = MA30 + 2 * STD60
    fs = cap.get("float_shares", 0) * 1e8
    fmv = cap.get("float_mv", 0)
    if not fs:
        return res
    for i, dt in enumerate(dates):
        a = auc.get(dt)
        if not a or i < 30 or i > len(C) - 2:
            continue
        o = O[i]
        if o <= 0:
            continue
        prevC = C[i - 1]
        竞价额 = a["amt"]
        if 竞价额 <= 0:
            continue
        开幅 = (o / prevC - 1) * 100
        开盘量 = 竞价额 / o / 100.0
        昨量 = V[i - 1]
        承接强度 = 开盘量 / 昨量 if 昨量 else 0
        ma5v = V[i - 5:i].mean() if i >= 5 else 0
        开量比 = 开盘量 / ma5v * 240 if ma5v else 0
        capital_shou = fs / 100.0
        开盘换手 = 开盘量 / capital_shou * 100 if capital_shou else 0
        竞价强度 = 开量比 * 开盘换手 * 开幅
        LTP = max(capital_shou, 100000)
        竞价动能 = 开幅 * (开盘量 / LTP * 10000)
        开盘换手1 = 竞价额 / o / fs * 100
        昨连板 = (i >= 3 and C[i - 1] / C[i - 2] > 1.097 and C[i - 1] == d[i - 1]["high"]
                  and C[i - 2] / C[i - 3] > 1.097 and C[i - 2] == d[i - 2]["high"])
        cond = (C[i] > QS上[i] and o >= prevC * 1.01 and 0 < fmv < 200 and
                开盘换手1 > 0.16 and C[i] > o and 竞价额 > 3_000_000 and
                竞价动能 > 180 and (not 昨连板) and o / C[i - 2] < 1.18 and
                o / min(L[max(0, i - 120):i + 1]) <= 1.88)
        if cond:
            res[dt] = True
    return res


# ============================ 策略2：一进二 ============================
def yijiner(d, auc, cap):
    res = {}
    if not d or not auc:
        return res
    C = np.array([r["close"] for r in d], float)
    O = np.array([r["open"] for r in d], float)
    H = np.array([r["high"] for r in d], float)
    V = np.array([r["volume"] for r in d], float)
    dates = [r["date"] for r in d]
    fs = cap.get("float_shares", 0) * 1e8
    fs_yi = cap.get("float_shares", 0)
    if not fs:
        return res
    for i, dt in enumerate(dates):
        a = auc.get(dt)
        if not a or i < 22 or i > len(C) - 2:
            continue
        o = O[i]
        if o <= 0:
            continue
        prevC = C[i - 1]
        xx2 = 0
        j = i - 1
        while j >= 1 and (C[j] > C[j - 1] * 1.09 and H[j] == C[j]):
            xx2 += 1; j -= 1
        竞价额 = a["amt"]
        开幅 = (o / prevC - 1) * 100
        开盘换手1 = 竞价额 / o / fs * 100
        X_4 = 开盘换手1 * 开幅
        X_5 = 竞价额 > 1500 * 10000
        X_6 = 竞价额 > 500 * 10000
        X_7 = 开盘换手1
        昨量 = V[i - 1] if i >= 1 else 0
        X_8 = (竞价额 / o / 100.0) / 昨量 * 100 if 昨量 else 0  # 竞价量/昨量(%)
        X_9 = X_5 and (X_8 > 10) and (3 <= 开幅 <= 9) and (fs_yi < 10) and (0.9 <= X_7 <= 2)
        X_10 = X_6 and (X_8 > 5) and (4 <= 开幅 <= 16) and (0.7 <= X_7 <= 7)
        cond = (X_4 >= 10 and (X_9 or X_10) and xx2 <= 1 and C[i] / C[i - 20] < 1.4)
        if cond:
            res[dt] = True
    return res


# ============================ 收益统计 ============================
def forward_returns(d, entry_idx):
    o = d[entry_idx]["open"]
    if o <= 0:
        return None
    out = {}
    for k, lbl in [(0, "R0"), (1, "R1"), (2, "R2"), (3, "R3"), (5, "R5")]:
        j = entry_idx + k
        if j < len(d):
            out[lbl] = d[j]["close"] / o - 1
    return out


def summarize(rets):
    row = {}
    for k in ["R0", "R1", "R2", "R3", "R5"]:
        vals = [r[k] for r in rets if k in r]
        if vals:
            a = np.array(vals)
            row[k] = {"n": len(a), "win": float((a > 0).mean()), "mean": float(a.mean()),
                      "med": float(np.median(a)), "max": float(a.max()), "min": float(a.min())}
        else:
            row[k] = None
    return row


# ============================ 主流程 ============================
def load_universe(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("code") or "," not in s:
                continue
            code, name = s.split(",", 1)
            code = code.strip(); name = name.strip()
            if not re.match(r"^\d{6}$", code):
                continue
            out.append((code, name, ("sh" if code.startswith("6") else "sz") + code))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="all_mainboard.csv")
    ap.add_argument("--dlimit", type=int, default=600)
    ap.add_argument("--dwin", type=int, default=260)
    ap.add_argument("--m1days", type=int, default=12, help="竞价策略回看交易日数(逐日抓取)")
    ap.add_argument("--limit-codes", type=int, default=0)
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    args = ap.parse_args()

    uni = load_universe(args.universe)
    if args.limit_codes:
        uni = uni[:args.limit_codes]
    wcodes = [w for _, _, w in uni]
    print(f"[universe] {len(uni)} 只主板非ST", file=sys.stderr)

    caps = fetch_caps(wcodes)
    daily = fetch_daily(wcodes, args.dlimit, tag=os.path.basename(args.universe))
    all_dates = sorted({r["date"] for d in daily.values() for r in d})
    m1_dates = all_dates[-args.m1days:] if args.m1days > 0 else []
    auc = fetch_m1(wcodes, m1_dates) if m1_dates else {}
    print(f"[data] caps={len(caps)} daily={len(daily)} m1_dates={len(m1_dates)} auction={len(auc)}", file=sys.stderr)

    strat = {"超级竞价": [], "紫霞牛": [], "一进二": []}
    for code, name, w in uni:
        d = daily.get(w)
        if not d or len(d) < 80:
            continue
        sig = build_gzb(d)
        start = max(0, len(d) - args.dwin - 6)
        for i in range(start, len(d) - 1):
            if sig[i]:
                r = forward_returns(d, i + 1)
                if r:
                    r.update(code=code, name=name, date=d[i]["date"])
                    strat["超级竞价"].append(r)
        cap = caps.get(w, {})
        a = auc.get(w, {})
        if not a or not cap:
            continue
        idx = {r["date"]: k for k, r in enumerate(d)}
        for dt in list(zixia_niu(d, a, cap)) + list(yijiner(d, a, cap)):
            k = idx.get(dt)
            if k is not None and k + 1 < len(d):
                r = forward_returns(d, k + 1)
                if r:
                    nm = "紫霞牛" if dt in zixia_niu(d, a, cap) else "一进二"
                    r.update(code=code, name=name, date=dt)
                    strat[nm].append(r)

    md = [f"# 竞价统计对比 · {args.date}", "",
          "- 口径：信号日 T（收盘确认）→ **T+1 竞价开盘价买入**，收益为相对买入价",
          "- universe：沪深主板非ST（剔创业板/科创板/北交所/ST），价格不限",
          f"- 日线窗口：近 {args.dwin} 交易日；竞价窗口：{m1_dates[0] if m1_dates else '-'} ~ {m1_dates[-1] if m1_dates else '-'}（{len(m1_dates)}日）", "",
          "## 一、三策略收益对比（T+1 竞价开盘买入）", "",
          "| 策略 | 期 | 样本 | 胜率 | 均值 | 中位 | 最大 | 最小 |", "|---|---|---|---|---|---|---|---|"]
    summary = {}
    for name, rets in strat.items():
        s = summarize(rets)
        summary[name] = {"count": len(rets), "stats": s}
        for k in ["R0", "R1", "R2", "R3", "R5"]:
            v = s[k]
            md.append(f"| {name} | {k} | {v['n']} | {v['win']:.1%} | {v['mean']:+.2%} | {v['med']:+.2%} | {v['max']:+.1%} | {v['min']:+.1%} |"
                      if v else f"| {name} | {k} | 0 | - | - | - | - | - |")
    md += ["", "## 二、信号清单（最近20条/策略）"]
    for name, rets in strat.items():
        md += [f"### {name}（共 {len(rets)} 条）", "| 日期 | 代码 | 名称 | R0 | R1 | R3 |", "|---|---|---|---|---|---|"]
        for r in sorted(rets, key=lambda x: x["date"], reverse=True)[:20]:
            md.append(f"| {r['date']} | {r['code']} | {r['name']} | {r.get('R0', 0):+.2%} | {r.get('R1', 0):+.2%} | {r.get('R3', 0):+.2%} |")
        md.append("")
    outmd = os.path.join(OUT, f"竞价统计_{args.date}.md")
    with open(outmd, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    with open(os.path.join(OUT, f"竞价统计_{args.date}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("[done]", outmd)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
