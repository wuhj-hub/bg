#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""20 年长样本验证（流式：拉一只算一只，只保留事件，不存原始面板）
信号：S1超跌(RSI14<25) / RSV启动(RSV均<20拐头↑) / 123买入 / 2B买入 / 武威G1双阴
基准：上证指数（RSV2 相对强度 + 环境判定）；同期全样本20日收益为基线
输出 outputs/long_events.csv + outputs/long_base.csv
"""
import os, csv, json, time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

OUT = "/sandbox/workspace/zxz_bt/outputs"
UA = {"User-Agent": "Mozilla/5.0", "Referer": "http://stockpage.10jqka.com.cn/"}
N = 144


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
            o = np.empty(n); h = np.empty(n); l = np.empty(n); c = np.empty(n)
            v = np.empty(n)
            for j in range(n):
                b = P[4 * j:4 * j + 4]
                l[j] = b[0] / pf; o[j] = (b[0] + b[1]) / pf
                h[j] = (b[0] + b[2]) / pf; c[j] = (b[0] + b[3]) / pf
                v[j] = float(V[j]) if V[j].isdigit() else 0.0
            return full, o, h, l, c, v
        except Exception:
            time.sleep(1.2)
    return None


def rsv_pct(vals, n=N):
    s = pd.Series(vals, dtype="float64")
    hh = s.rolling(n).max(); ll = s.rolling(n).min()
    r = (s - ll) / (hh - ll).replace(0, np.nan) * 100
    return r.values, (r > r.shift(3)).values


def main():
    # 上证指数（基准 + 环境）
    ix = ths("000001")
    idates, io_, ih, il, ic, iv = ix
    ib = dict(zip(idates, ic))
    print("上证", len(idates), idates[0], "~", idates[-1])
    # 环境（长期=月线5线 / 短期=日线5线，market_regime 口径）
    def power_states(cl):
        s = pd.Series(cl, dtype="float64")
        ma = [s.rolling(k).mean() for k in (5, 10, 20, 30)]
        dif = s.ewm(span=10, adjust=False).mean() - s.ewm(span=22, adjust=False).mean()
        up = sum([(m > m.shift(1)).astype(int) for m in ma]) + (dif > dif.shift(1)).astype(int)
        b = np.where(up >= 4, "牛市", np.where(up <= 1, "熊市", "震荡市"))
        return b
    sst = power_states(ic)
    SENV = {d: b for d, b in zip(idates, sst)}
    mdf = pd.DataFrame({"date": idates, "close": ic}); mdf["ym"] = mdf["date"].str[:7]
    mo = mdf.groupby("ym")["close"].last().reset_index()
    lst = power_states(mo["close"].values)
    MENV = list(zip(mo["ym"], lst))                       # 当月末状态
    MENV = {ym: (MENV[i - 1][1] if i >= 1 else "震荡市") for i, (ym, _) in enumerate(MENV)}  # 滞后一期

    codes = [r["code"] for r in csv.DictReader(open("/sandbox/workspace/zxz_bt/data/pool.csv", encoding="utf-8"))
             if len(r["code"]) == 8]
    print("股票数", len(codes))
    base_sum = {}   # (dim,env,date) -> [sum,n]
    events = {}     # (signal,dim,env,date) -> [sum,n]
    done = 0
    def work(code):
        return code, ths(code[2:])
    with ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(work, c): c for c in codes}
        for fu in as_completed(futs):
            code, res = fu.result()
            done += 1
            if done % 400 == 0:
                print(f"  {done}/{len(codes)} 事件{len(events)}", flush=True)
            if not res:
                continue
            dates, o, h, l, c, v = res
            n = len(c)
            if n < 400:
                continue
            m = c > 0.3
            if m.sum() < 400:
                continue
            # 只保留有效段
            idx = np.where(m)[0]
            if len(idx) < 400:
                continue
            dates = [dates[i] for i in idx]; o = o[idx]; h = h[idx]; l = l[idx]; c = c[idx]; v = v[idx]
            n = len(c)
            sc = pd.Series(c)
            pct = np.concatenate([[np.nan], c[1:] / c[:-1] - 1])
            nxt = np.concatenate([o[1:], [np.nan]])
            r20f = np.concatenate([c[20:] / nxt[:-20] - 1, [np.nan] * 20])
            # S1 超跌
            d1 = sc.diff()
            up = d1.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
            dn = (-d1.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
            rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values
            s1 = rsi < 25
            # RSV 启动
            r1, u1 = rsv_pct(c)
            bs = np.array([ib.get(d, np.nan) for d in dates])
            with np.errstate(invalid="ignore", divide="ignore"):
                rs = np.where(bs > 0, c / bs, np.nan)
            r2, _ = rsv_pct(rs)
            avg = (r1 + r2) / 2
            rsvs = (avg < 20) & u1
            # 123 / 2B
            Ls, Hs = pd.Series(l), pd.Series(h)
            cur_low = Ls.rolling(3).min().values
            min_lows = Ls.shift(3).rolling(17).min().values
            prev_high = Hs.shift(4).rolling(16).max().values
            ma5 = sc.rolling(5).mean().values
            s123 = (cur_low > min_lows) & (c > prev_high) & (c > ma5) & (ma5 > np.concatenate([[np.nan], ma5[:-1]]))
            m25 = Ls.rolling(25).min().values
            m_mid = Ls.shift(3).rolling(19).min().values
            old = Ls.shift(24).values
            s2b = (m_mid == m25) & (Ls.rolling(3).min().values > m25) & (old > m25) & (c > m25 * 1.02)
            # 鱼身·均线回踩
            e12 = sc.ewm(span=12, adjust=False).mean(); e26 = sc.ewm(span=26, adjust=False).mean()
            DIF = (e12 - e26); DEA = DIF.ewm(span=9, adjust=False).mean()
            ma10 = sc.rolling(10).mean().values
            ma20v = sc.rolling(20).mean().values; ma60v = sc.rolling(60).mean().values
            fish_ma = (ma20v > ma60v) & (DIF > 0) & (DEA > 0) & \
                      (np.abs(c - ma10) / np.where(ma10 > 0, ma10, np.nan) < .05) & (c > ma5) & (c >= ma20v)
            # 猛兽·伏击线
            sd5 = sc.rolling(5).std(ddof=0).values
            UB = ma20v + 5 * sd5
            with np.errstate(invalid="ignore", divide="ignore"):
                pf = (UB - c) / UB * 100
            amb = (pf > 0) & (pf < 6)
            # 猛兽·RS_D
            bcv = np.array([ib.get(d, np.nan) for d in dates])
            def lin5(y):
                t = pd.Series(y, dtype="float64")
                return ((4 * t + 3 * t.shift(1) + 2 * t.shift(2) + 1 * t.shift(3) - 10 * t.rolling(5).mean()) / 10.0).values
            with np.errstate(invalid="ignore", divide="ignore"):
                dr = lin5(bcv) / bcv * 1000 - lin5(c) / c * 1000
            rsd = (np.abs(dr) < 15) & (dr > 0)
            # 双弦·低价共振（近似）
            bscore = np.array([{"牛市": .8, "震荡市": .4, "熊市": 0.0}.get(SENV.get(d, "震荡市"), .4) for d in dates])
            sx = (c <= 10) & (bscore >= .4) & (c / np.concatenate([[np.nan] * 20, c[:-20]]) - 1 > 0)
            # 鱼身·箱体突破
            fbox = np.zeros(n, bool)
            vv_ = v
            for i in range(70, n):
                bx = c[i - 42:i - 2]
                if len(bx) < 15:
                    continue
                bt, bb2 = bx.max(), bx.min()
                if bb2 <= 0 or (bt - bb2) / bb2 * 100 > 40:
                    continue
                bav = vv_[i - 42:i - 2].mean()
                if bav <= 0 or c[i] <= bt * 1.005 or vv_[i] / bav < 1.5:
                    continue
                pre = c[max(0, i - 62):i - 42]
                if len(pre) >= 3 and pre.mean() > 0 and (bb2 / pre.mean() - 1) * 100 >= 30:
                    continue
                fbox[i] = True
            # 武威 G1 双阴（日线聚合月线）
            mm = pd.DataFrame({"d": dates, "o": o, "c": c, "l": l, "v": v})
            mm["ym"] = [x[:7] for x in dates]
            g = mm.groupby("ym").agg(o=("o", "first"), c=("c", "last"), l=("l", "min"), v=("v", "sum")).reset_index()
            mo_, mc_, ml_, mv_ = g["o"].values, g["c"].values, g["l"].values, g["v"].values
            ymv = g["ym"].values
            fl = np.zeros(len(ymv), bool)
            for j in range(4, len(ymv)):
                k1, k2, k3, k4 = j - 3, j - 2, j - 1, j
                if mc_[k3] < mo_[k3] and mc_[k4] < mo_[k4] and mv_[k2] > 0 \
                   and mv_[k4] <= mv_[k2] * .6 and mv_[k3] <= mv_[k2] * .6 \
                   and ml_[k1] > 0 and abs(ml_[k4] - ml_[k1]) / ml_[k1] <= .12:
                    fl[j] = True
            dayym = np.array([x[:7] for x in dates])
            jj = np.searchsorted(ymv, dayym, side="left") - 1
            ww = np.where(jj >= 0, fl[np.maximum(jj, 0)], False)
            # 基线：全样本（股票×日）按环境累加 20 日收益
            envl = np.array([MENV.get(x[:7], "震荡市") for x in dates])
            envs = np.array([SENV.get(x, "震荡市") for x in dates])
            good = np.isfinite(r20f)
            for dim, ev in (("L", envl), ("S", envs)):
                dfa = pd.DataFrame({"e": ev[good], "d": np.array(dates)[good], "r": r20f[good]})
                for (e, dd), row in dfa.groupby(["e", "d"])["r"].agg(["sum", "count"]).iterrows():
                    k = (dim, e, dd); base_sum.setdefault(k, [0.0, 0])
                    base_sum[k][0] += float(row["sum"]); base_sum[k][1] += int(row["count"])
            prev_state = {}
            for i in range(280, n - 21):
                if not good[i] or np.isnan(nxt[i]) or nxt[i] <= 0:
                    continue
                for nm, flag in (("S1超跌", s1[i]), ("RSV启动", rsvs[i]), ("123买入", s123[i]),
                                 ("2B买入", s2b[i]), ("武威双阴", ww[i]), ("鱼身均线回踩", fish_ma[i]),
                                 ("鱼身箱体突破", fbox[i]), ("猛兽伏击线", amb[i]),
                                 ("猛兽RS_D低吸", rsd[i]), ("双弦低价共振", sx[i])):
                    st = bool(flag)
                    if st and not prev_state.get(nm, False):
                        for dim, ev in (("L", envl[i]), ("S", envs[i])):
                            k = (nm, dim, ev, dates[i]); events.setdefault(k, [0.0, 0])
                            events[k][0] += r20f[i]; events[k][1] += 1
                    prev_state[nm] = st
    E = pd.DataFrame([(k[0], k[1], k[2], k[3], v[0], v[1]) for k, v in events.items()],
                     columns=["signal", "dim", "env", "date", "sum", "n"])
    E.to_csv(f"{OUT}/long_sig_daily.csv", index=False)
    B = pd.DataFrame([(k[0], k[1], k[2], v[0], v[1]) for k, v in base_sum.items()],
                     columns=["dim", "env", "date", "sum", "n"])
    B.to_csv(f"{OUT}/long_base_daily.csv", index=False)
    print("信号日聚合行", len(E), "| 基线日聚合行", len(B))
    print(B.groupby(["dim", "env"]).apply(lambda x: x["sum"].sum() / max(x["n"].sum(), 1)).to_string())


if __name__ == "__main__":
    main()
