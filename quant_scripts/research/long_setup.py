#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""猛兽十维 Setup 评分 · 全历史长样本（流式）
八维可复现（①VCP②均线③成交量④VAD+抗跌⑤突破+高阳+孤狼⑦RSVA/SSV/RSL⑨伏击线⑩RS_D）=100分
setup = min(100, raw*100/115)。输出 outputs/long_setup_daily.csv（signal=Setup≥60/≥50/≥40）
"""
import os, csv, json, time
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
            d = json.JSONDecoder().raw_decode(t[i:])[0]
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
                v[j] = float(V[j]) if V[j].isdigit() else 0.0
            return full, o, h, l, c, v
        except Exception:
            time.sleep(1.2)
    return None


def main():
    ix = ths("000001")
    idates, io_, ih, il, ic, iv = ix
    ib = dict(zip(idates, ic))
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
    up2 = sum([(m > m.shift(1)).astype(int) for m in ma2]) + (d2 > d2.shift(1)).astype(int)
    st2 = ["牛市" if u >= 4 else ("熊市" if u <= 1 else "震荡市") for u in up2]
    MENV = {ym: (st2[i - 1] if i >= 1 else "震荡市") for i, ym in enumerate(mo["ym"].values)}

    codes = [r["code"] for r in csv.DictReader(open("/sandbox/workspace/zxz_bt/data/pool.csv", encoding="utf-8"))
             if len(r["code"]) == 8]
    print("股票数", len(codes), flush=True)
    base_sum = {}; events = {}
    done = 0

    def work(code):
        return code, ths(code[2:])

    with ThreadPoolExecutor(8) as ex:
        for fu in as_completed({ex.submit(work, c): c for c in codes}):
            code, res = fu.result(); done += 1
            if done % 300 == 0:
                print(f"  {done}/{len(codes)} 事件{len(events)}", flush=True)
            if not res:
                continue
            dates, o, h, l, c, v = res
            m = c > 0.3; idx = np.where(m)[0]
            if len(idx) < 400:
                continue
            dates = [dates[i] for i in idx]; o, h, l, c, v = o[idx], h[idx], l[idx], c[idx], v[idx]
            n = len(c); sc = pd.Series(c); AMO = c * v
            dom = np.array([(mk := ib.get(d, np.nan)) for d in dates], dtype=float)
            ok = np.isfinite(dom) & (dom > 0)
            if ok.sum() < 300:
                continue
            nxt = np.concatenate([o[1:], [np.nan]])
            r20f = np.concatenate([c[20:] / nxt[:-20] - 1, [np.nan] * 20])
            # ① VCP
            amp = (h - l) / c * 100
            a5 = pd.Series(amp).rolling(5).mean().values; a20 = pd.Series(amp).rolling(20).mean().values
            with np.errstate(invalid="ignore", divide="ignore"):
                vr_ = a5 / a20
            vcp = np.select([vr_ <= .30, vr_ <= .45, vr_ <= .60, vr_ <= .75, vr_ <= .90, vr_ <= 1.],
                            [20, 17, 13, 8, 4, 2], default=0).astype(float)
            # ② 均线
            e5 = sc.ewm(span=5, adjust=False).mean(); e20 = sc.ewm(span=20, adjust=False).mean()
            e60 = sc.ewm(span=60, adjust=False).mean()
            mas = np.where((e5 > e20) & (e20 > e60), 8, np.where(e5 > e20, 4, 0)).astype(float)
            s5 = (e5 - e5.shift(5)) / e5.shift(5)
            mas += np.where(s5 > .002, 5, np.where(s5 > 0, 2, 0))
            s20 = (e20 - e20.shift(20)) / e20.shift(20)
            mas += np.where(s20 > .002, 4, np.where(s20 > 0, 2, 0))
            mas += np.where(sc > e60, 3, 0); mas = np.minimum(20, mas)
            # ③ 成交量
            v5 = pd.Series(v).rolling(5).mean().values; v20 = pd.Series(v).rolling(20).mean().values
            with np.errstate(invalid="ignore", divide="ignore"):
                vr = v5 / v20; vbr = v / v20
            vol = np.select([vr < .5, vr < .7, vr < .9], [8, 5, 3], default=0).astype(float)
            vol += np.select([vbr > 1.8, vbr > 1.4, vbr > 1.1], [7, 5, 3], default=0)
            vol = np.minimum(15, vol)
            # ④ VAD + 抗跌
            hi = np.maximum(h, np.concatenate([[np.nan], c[:-1]]))
            lw = np.minimum(l, np.concatenate([[np.nan], c[:-1]]))
            bsr = (c - np.concatenate([[np.nan], c[:-1]])) / np.where(hi != lw, hi - lw, 1)
            vv = pd.Series(bsr * AMO)
            vad = vv.rolling(14).sum().values / 1e7; vp = vv.rolling(14).sum().shift(1).values / 1e7
            vsc = np.select([vad > 8, vad > 5, vad > 3, vad > 1, vad > 0, vad > -1, vad > -3],
                            [10, 8, 6, 4, 3, 2, 1], default=0).astype(float)
            vsc = np.where((vad > 0) & (vp < 0), np.minimum(10, vsc + 2), vsc)
            mkret = np.concatenate([[np.nan], dom[1:] / dom[:-1] - 1])
            pct = np.concatenate([[np.nan], c[1:] / c[:-1] - 1])
            down = mkret < -0.005
            td = pd.Series(np.where(down, np.abs(np.where(pct < 0, pct, 0)), 0)).rolling(20).sum().values
            ti = pd.Series(np.where(down, -mkret, 0)).rolling(20).sum().values
            with np.errstate(invalid="ignore", divide="ignore"):
                anti = np.where(ti > 0, np.clip((1 - td / ti) * 100, 0, 100), 50.)
            vsc = np.where(anti > 70, np.minimum(10, vsc + 2), np.where(anti > 50, np.minimum(10, vsc + 1), vsc))
            # ⑤ 突破
            hh60 = pd.Series(h).rolling(60).max().values
            with np.errstate(invalid="ignore", divide="ignore"):
                dfh = (hh60 - c) / hh60 * 100
            b = np.select([dfh < 2, dfh < 5, dfh < 10], [3, 2, 1], default=0).astype(float)
            b += np.where(c > o, 2, 0)
            vy = np.concatenate([[False], v[1:] > v[:-1]]).astype(float)
            vy2 = np.concatenate([[False, False], v[2:] > v[1:-1]]).astype(float)
            b += np.minimum(2, vy + vy2)
            e20up = np.concatenate([[False] * 20, e20.values[20:] > e20.values[:-20]])
            b += np.where((c > e20.values) & e20up, 2, 0)
            s5d = c / np.concatenate([[np.nan] * 5, c[:-5]]) - 1
            with np.errstate(invalid="ignore", divide="ignore"):
                i5d = dom / np.concatenate([[np.nan] * 5, dom[:-5]]) - 1
            lead = (s5d - i5d) * 100
            b += np.select([lead > 10, lead > 5, lead > 2], [3, 2, 1], default=0)
            ma20v = pd.Series(v).rolling(20).mean().values
            hv = (c > o) & (v > ma20v * 1.5)
            hv_idx = np.where(hv)[0]
            if len(hv_idx):
                pos = np.searchsorted(hv_idx, np.arange(n))
                last = np.where(pos > 0, hv_idx[np.maximum(pos - 1, 0)], -1)
                valid = (last >= 0) & (last + 3 <= np.arange(n)) & (last >= np.arange(n) - 15)
                for i in np.where(valid)[0]:
                    j = last[i]; hc = c[j]
                    d1 = (c[j + 1] - hc) / hc * 100; d2 = (c[j + 2] - hc) / hc * 100; d3 = (c[j + 3] - hc) / hc * 100
                    if d1 > 0 and d2 > 0:
                        b[i] += 3
                    elif d1 >= -1 and d2 >= -1 and d3 >= -1:
                        b[i] += 2
                    elif v[j + 1] < ma20v[j] * .8:
                        b[i] += 1
                    elif d1 < -3 and v[j + 1] > ma20v[j]:
                        b[i] -= 1
            brk = np.clip(b, 0, 15)
            # ⑦ RSVA/SSV/RSL
            with np.errstate(invalid="ignore", divide="ignore"):
                rs = c / dom
            h20 = pd.Series(h).rolling(20).max().values; l20 = pd.Series(l).rolling(20).min().values
            with np.errstate(invalid="ignore", divide="ignore"):
                r1 = np.clip((c - l20) / (h20 - l20) * 100, 0, 100)
            rsh = pd.Series(rs).rolling(20).max().values; rsl_ = pd.Series(rs).rolling(20).min().values
            with np.errstate(invalid="ignore", divide="ignore"):
                r2 = np.clip((rs - rsl_) / (rsh - rsl_) * 100, 0, 100)
            rsva = np.nanmean([r1, r2], axis=0)
            rsc = np.select([rsva >= 85, rsva >= 75, rsva >= 65], [3, 2, 1], default=0).astype(float)
            sA = pd.Series(AMO); sAC = pd.Series(AMO * c)
            vwap = (sAC.rolling(200).sum() / sA.rolling(200).sum()).values
            m2 = pd.Series((c - vwap) ** 2).rolling(200).sum().values
            cnt = pd.Series(np.ones(n)).rolling(200).sum().values
            with np.errstate(invalid="ignore", divide="ignore"):
                ssv2 = (c - vwap) / np.sqrt(m2 / (cnt - 1)) * 100
            rsc += np.select([ssv2 > 100, ssv2 > 50, ssv2 > 0], [3, 2, 1], default=0)
            vwrs = (pd.Series(rs * AMO).rolling(144).sum() / sA.rolling(144).sum()).values
            m3 = pd.Series((rs - vwrs) ** 2).rolling(144).sum().values
            cnt2 = pd.Series(np.ones(n)).rolling(144).sum().values
            with np.errstate(invalid="ignore", divide="ignore"):
                rsl2 = (rs - vwrs) / np.sqrt(m3 / (cnt2 - 1)) * 100
            rsc += np.select([rsl2 > 100, rsl2 > 50, rsl2 > 0], [4, 3, 1], default=0)
            rsc = np.minimum(10, rsc)
            # ⑨ 伏击线
            sd5 = sc.rolling(5).std(ddof=0).values
            UB = e20.values + 5 * sd5
            with np.errstate(invalid="ignore", divide="ignore"):
                pfx = (UB - c) / UB * 100
            amb = np.select([(pfx > 0) & (pfx < 3), (pfx > 0) & (pfx < 6)], [5, 3], default=0).astype(float)
            amb = np.where((amb >= 3) & (ssv2 > 0), np.minimum(5, amb + 2), amb)
            # ⑩ RS_D
            def lin(y):
                t_ = pd.Series(y, dtype="float64")
                return ((4 * t_ + 3 * t_.shift(1) + 2 * t_.shift(2) + 1 * t_.shift(3) - 10 * t_.rolling(5).mean()) / 10.0).values
            with np.errstate(invalid="ignore", divide="ignore"):
                dr5 = lin(dom) / dom * 1000 - lin(c) / c * 1000
            rsd = np.select([(np.abs(dr5) < 15), (np.abs(dr5) < 25)], [3, 2], default=0).astype(float)
            rsd = np.where((np.abs(dr5) < 15) & (dr5 > 0), np.minimum(5, rsd + 2), rsd)
            raw = vcp + mas + vol + vsc + brk + rsc + amb + rsd
            setup = np.minimum(100, raw * 100 / 115)
            # 基线
            envl = np.array([MENV.get(d[:7], "震荡市") for d in dates])
            envs = np.array([SENV.get(d, "震荡市") for d in dates])
            good = np.isfinite(r20f) & (np.abs(r20f) <= 3) & (np.abs(np.concatenate([[np.nan], c[1:] / np.where(c[:-1] > 0, c[:-1], np.nan) - 1])) <= 0.6)
            for dim, ev in (("L", envl), ("S", envs)):
                dfa = pd.DataFrame({"e": ev[good], "d": np.array(dates)[good], "r": r20f[good]})
                for (e, dd), row in dfa.groupby(["e", "d"])["r"].agg(["sum", "count"]).iterrows():
                    k = (dim, e, dd); base_sum.setdefault(k, [0.0, 0])
                    base_sum[k][0] += float(row["sum"]); base_sum[k][1] += int(row["count"])
            for th in (60, 55, 50):
                prev = False
                for i in range(320, n - 21):
                    st = bool(np.isfinite(setup[i]) and setup[i] >= th)
                    if st and not prev and (np.isfinite(r20f[i]) and abs(r20f[i]) <= 3) and nxt[i] > 0:
                        for dim, ev in (("L", envl[i]), ("S", envs[i])):
                            k = (f"猛兽Setup≥{th}", dim, ev, dates[i]); events.setdefault(k, [0.0, 0])
                            events[k][0] += r20f[i]; events[k][1] += 1
                    prev = st
    E = pd.DataFrame([(k[0], k[1], k[2], k[3], v2[0], v2[1]) for k, v2 in events.items()],
                     columns=["signal", "dim", "env", "date", "sum", "n"])
    E.to_csv(f"{OUT}/long_setup_daily.csv", index=False)
    B = pd.DataFrame([(k[0], k[1], k[2], v2[0], v2[1]) for k, v2 in base_sum.items()],
                     columns=["dim", "env", "date", "sum", "n"])
    B.to_csv(f"{OUT}/long_setup_base.csv", index=False)
    print("done | 信号行", len(E), "| 基线行", len(B), flush=True)


if __name__ == "__main__":
    main()
