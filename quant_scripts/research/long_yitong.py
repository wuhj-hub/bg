#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一统天下·建仓区 全历史长样本验证（流式）
口径照搬 yitong_screener.py（60分钟确认无历史数据，故只能复现到★★★★）：
  VARO7: v5=min(low,i-26..i), v6=max(high,i-33..i), raw=(C-v5)/(v6-v5)*100,
         varo7[i]=(raw*2+varo7[i-1]*3)/5  → ewm(alpha=0.4)
  日线建仓区 = 近5根内 VARO7<10
  周线闸门  = 近8周内 周线VARO7<10
  乖离低买  = (C-MA5)/MA5*100 < -7
  双共振    = 日线建仓区 且 周线闸门
输出 outputs/long_yitong_daily.csv
"""
import os, csv, time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

OUT = "/sandbox/workspace/zxz_bt/outputs"
UA = {"User-Agent": "Mozilla/5.0", "Referer": "http://stockpage.10jqka.com.cn/"}


def ths(six):
    url = f"http://d.10jqka.com.cn/v6/line/hs_{six}/01/all.js"
    for _ in range(3):
        try:
            r = urllib.request.Request(url, headers=UA)
            t = urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "ignore")
            i = t.find("{")
            if i < 0:
                return None
            d = pd.JSONDecoder().raw_decode(t[i:])[0] if hasattr(pd, "JSONDecoder") else __import__("json").JSONDecoder().raw_decode(t[i:])[0]
            pf = d["priceFactor"]; P = [int(x) for x in d["price"].split(",")]
            V = d["volumn"].split(",") if "volumn" in d else []
            md = d["dates"].split(","); k = 0; full = []
            for y, cnt in d["sortYear"]:
                for s in md[k:k + cnt]:
                    s = s.zfill(4); full.append(f"{y}-{s[:2]}-{s[2:]}")
                k += cnt
            n = min(len(full), len(P) // 4, len(V))
            o = np.empty(n); h = np.empty(n); l = np.empty(n); c = np.empty(n); v = np.empty(n)
            for j in range(n):
                b = P[4 * j:4 * j + 4]
                l[j] = b[0] / pf; o[j] = (b[0] + b[1]) / pf
                h[j] = (b[0] + b[2]) / pf; c[j] = (b[0] + b[3]) / pf
            return full, o, h, l, c, v
        except Exception:
            time.sleep(1.2)
    return None


def varo7_ewm(h, l, c, alpha=0.4):
    low27 = pd.Series(l).rolling(27).min().values
    high34 = pd.Series(h).rolling(34).max().values
    den = high34 - low27
    raw = np.where(den > 0, (c - low27) / den * 100, 40.0)
    r = pd.Series(raw)
    return r.ewm(alpha=alpha, adjust=False).mean().values


def main():
    ix = ths("000001")
    idates = ix[0]
    ic = ix[4]
    s = pd.Series(ic, dtype="float64")
    ma = [s.rolling(k).mean() for k in (5, 10, 20, 30)]
    dif0 = s.ewm(span=10, adjust=False).mean() - s.ewm(span=22, adjust=False).mean()
    up = sum([(m > m.shift(1)).astype(int) for m in ma]) + (dif0 > dif0.shift(1)).astype(int)
    SENV = {d: ("牛市" if u >= 4 else ("熊市" if u <= 1 else "震荡市")) for d, u in zip(idates, up)}
    mdf = pd.DataFrame({"date": idates, "close": ic}); mdf["ym"] = mdf["date"].str[:7]
    mo = mdf.groupby("ym")["close"].last().reset_index()
    sm = pd.Series(mo["close"].values, dtype="float64")
    ma2 = [sm.rolling(k).mean() for k in (5, 10, 20, 30)]
    d2 = sm.ewm(span=10, adjust=False).mean() - sm.ewm(span=22, adjust=False).mean()
    u2 = sum([(m > m.shift(1)).astype(int) for m in ma2]) + (d2 > d2.shift(1)).astype(int)
    st2 = ["牛市" if u >= 4 else ("熊市" if u <= 1 else "震荡市") for u in u2]
    MENV = {ym: (st2[i - 1] if i >= 1 else "震荡市") for i, ym in enumerate(mo["ym"].values)}

    codes = [r["code"] for r in csv.DictReader(open("/sandbox/workspace/zxz_bt/data/pool.csv", encoding="utf-8"))
             if len(r["code"]) == 8]
    print("股票数", len(codes), flush=True)
    base_sum = {}; events = {}; done = 0

    def work(code):
        return code, ths(code[2:])

    with ThreadPoolExecutor(8) as ex:
        for fu in as_completed({ex.submit(work, c): c for c in codes}):
            code, res = fu.result(); done += 1
            if done % 400 == 0:
                print(f"  {done}/{len(codes)} 事件{len(events)}", flush=True)
            if not res:
                continue
            dates, o, h, l, c, v = res
            ixk = c > 0.3; idx = np.where(ixk)[0]
            if len(idx) < 400:
                continue
            dates = [dates[i] for i in idx]; o, h, l, c, v = o[idx], h[idx], l[idx], c[idx], v[idx]
            n = len(c)
            nxt = np.concatenate([o[1:], [np.nan]])
            r20f = np.concatenate([c[20:] / nxt[:-20] - 1, [np.nan] * 20])
            vd = varo7_ewm(h, l, c)
            in_jcq = pd.Series(vd < 10).rolling(5).max().fillna(0).astype(bool).values
            ma5 = pd.Series(c).rolling(5).mean().values
            with np.errstate(invalid="ignore", divide="ignore"):
                bias = (c - ma5) / ma5 * 100
            guaili = bias < -7
            # 周线
            wk = pd.DataFrame({"date": pd.to_datetime(dates), "o": o, "h": h, "l": l, "c": c, "v": v})
            wk = wk.set_index("date").resample("W").agg({"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}).dropna()
            wj = np.zeros(n, bool)
            if len(wk) > 40:
                wv = varo7_ewm(wk["h"].values, wk["l"].values, wk["c"].values)
                win = pd.Series(wv < 10).rolling(8).max().fillna(0).astype(bool).values
                wmap = {d.strftime("%Y-%m-%d"): win[i] for i, d in enumerate(wk.index)}
                wkidx = np.array([d.strftime("%Y-%m-%d") for d in wk.index])
                pos = np.searchsorted(wkidx, np.array(dates), side="right") - 1
                wj = np.where(pos >= 0, win[np.maximum(pos, 0)], False)
            dual = in_jcq & wj
            envl = np.array([MENV.get(d[:7], "震荡市") for d in dates])
            envs = np.array([SENV.get(d, "震荡市") for d in dates])
            good = np.isfinite(r20f) & (np.abs(r20f) <= 3) & (np.abs(np.concatenate([[np.nan], c[1:] / np.where(c[:-1] > 0, c[:-1], np.nan) - 1])) <= 0.6)
            for dim, ev in (("L", envl), ("S", envs)):
                dfa = pd.DataFrame({"e": ev[good], "d": np.array(dates)[good], "r": r20f[good]})
                for (e, dd), row in dfa.groupby(["e", "d"])["r"].agg(["sum", "count"]).iterrows():
                    k = (dim, e, dd); base_sum.setdefault(k, [0.0, 0])
                    base_sum[k][0] += float(row["sum"]); base_sum[k][1] += int(row["count"])
            for nm, sig in (("一统·日线建仓区", in_jcq), ("一统·乖离低买", guaili), ("一统·日周双共振", dual)):
                prev = False
                for i in range(280, n - 21):
                    st = bool(sig[i])
                    if st and not prev and (np.isfinite(r20f[i]) and abs(r20f[i]) <= 3) and nxt[i] > 0:
                        for dim, ev in (("L", envl[i]), ("S", envs[i])):
                            k = (nm, dim, ev, dates[i]); events.setdefault(k, [0.0, 0])
                            events[k][0] += r20f[i]; events[k][1] += 1
                    prev = st
    E = pd.DataFrame([(k[0], k[1], k[2], k[3], x[0], x[1]) for k, x in events.items()],
                     columns=["signal", "dim", "env", "date", "sum", "n"])
    E.to_csv(f"{OUT}/long_yitong_daily.csv", index=False)
    B = pd.DataFrame([(k[0], k[1], k[2], x[0], x[1]) for k, x in base_sum.items()],
                     columns=["dim", "env", "date", "sum", "n"])
    B.to_csv(f"{OUT}/long_yitong_base.csv", index=False)
    print("done 信号行", len(E), "基线行", len(B), flush=True)


if __name__ == "__main__":
    main()
