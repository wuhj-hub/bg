#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""猛兽十维 Setup 评分 历史复现（beast_screener.setup_score_stock v2.2 口径）

十维: ①VCP(20) ②均线(20) ③成交量(15) ④VAD(10) ⑤突破(15) ⑥净利润断层(10) ⑦RSVA/SSV/RSL(10)
      ⑧基本面增速(5) ⑨伏击线(5) ⑩RS_D(5)；raw/115*100 → setup_total
历史可复现：①-⑤⑦⑨⑩（共100分）；不可复现：⑥净利润断层(10) ⑧基本面(5) → 上限 100/115=87
输出 outputs/beast_setup_events.csv
"""
import os
import numpy as np
import pandas as pd

BASE = "/sandbox/workspace/zxz_bt"
DATA, OUT = f"{BASE}/data", f"{BASE}/outputs"


def main():
    df = pd.read_csv(f"{DATA}/kline_daily_vol.csv", dtype={"code": str, "date": str})
    df = df[df["close"] > 0].sort_values(["code", "date"]).reset_index(drop=True)
    # 基准：等权大盘（替代 880003 平均股价 / 上证）
    ret = df.pivot_table(index="date", columns="code", values="close").pct_change(fill_method=None)
    mk = (1 + ret.mean(axis=1).fillna(0.0)).cumprod()
    mkret = mk.pct_change()
    print("面板", len(df), df.code.nunique(), "只")

    rows = []
    codes = list(df.groupby("code", sort=False))
    for ci, (code, g) in enumerate(codes):
        g = g.reset_index(drop=True)
        if len(g) < 320:
            continue
        C = g["close"].values.astype(float); H = g["high"].values.astype(float)
        L = g["low"].values.astype(float); O = g["open"].values.astype(float)
        V = g["volume"].values.astype(float); D = g["date"].values
        n = len(g)
        AMO = C * V
        sc = pd.Series(C)
        pct = np.concatenate([[np.nan], C[1:] / C[:-1] - 1])
        nxt = np.concatenate([O[1:], [np.nan]])
        r20f = np.concatenate([C[20:] / nxt[:-20] - 1, [np.nan] * 20])

        # ① VCP
        amp = (H - L) / C * 100
        amp5 = pd.Series(amp).rolling(5).mean().values
        amp20 = pd.Series(amp).rolling(20).mean().values
        with np.errstate(invalid="ignore", divide="ignore"):
            vcp_r = amp5 / amp20
        vcp = np.select([vcp_r <= .30, vcp_r <= .45, vcp_r <= .60, vcp_r <= .75, vcp_r <= .90, vcp_r <= 1.0],
                        [20, 17, 13, 8, 4, 2], default=0).astype(float)

        # ② 均线系统
        e5 = sc.ewm(span=5, adjust=False).mean(); e20 = sc.ewm(span=20, adjust=False).mean()
        e60 = sc.ewm(span=60, adjust=False).mean()
        ma = np.where((e5 > e20) & (e20 > e60), 8, np.where(e5 > e20, 4, 0)).astype(float)
        s5 = (e5 - e5.shift(5)) / e5.shift(5)
        ma += np.where(s5 > .002, 5, np.where(s5 > 0, 2, 0))
        s20 = (e20 - e20.shift(20)) / e20.shift(20)
        ma += np.where(s20 > .002, 4, np.where(s20 > 0, 2, 0))
        ma += np.where(sc > e60, 3, 0)
        ma = np.minimum(20, ma)

        # ③ 成交量
        v5 = pd.Series(V).rolling(5).mean().values; v20 = pd.Series(V).rolling(20).mean().values
        with np.errstate(invalid="ignore", divide="ignore"):
            vr = v5 / v20; vbr = V / v20
        vol = np.select([vr < .5, vr < .7, vr < .9], [8, 5, 3], default=0).astype(float)
        vol += np.select([vbr > 1.8, vbr > 1.4, vbr > 1.1], [7, 5, 3], default=0)
        vol = np.minimum(15, vol)

        # ④ VAD(14) + 抗跌
        hi = np.maximum(H, np.concatenate([[np.nan], C[:-1]]))
        lw = np.minimum(L, np.concatenate([[np.nan], C[:-1]]))
        den = np.where(hi != lw, hi - lw, 1)
        bsr = (C - np.concatenate([[np.nan], C[:-1]])) / den
        vv = pd.Series(bsr * AMO)
        vad = vv.rolling(14).sum().values / 1e7
        vad_prev = vv.rolling(14).sum().shift(1).values / 1e7
        vad_sc = np.select([vad > 8, vad > 5, vad > 3, vad > 1, vad > 0, vad > -1, vad > -3],
                           [10, 8, 6, 4, 3, 2, 1], default=0).astype(float)
        cross_up = (vad > 0) & (vad_prev < 0)
        vad_sc = np.where(cross_up, np.minimum(10, vad_sc + 2), vad_sc)
        # 抗跌（20日，大盘下跌日相对跌幅）
        mkd = dict(zip(mk.index, mk.values)); mkrd = dict(zip(mkret.index, mkret.values))
        mkv = np.array([mkd.get(d, np.nan) for d in D])
        mk_a = np.array([mkrd.get(d, np.nan) for d in D])
        sret = pct
        down = mk_a < -0.005
        td = pd.Series(np.where(down, np.abs(np.where(sret < 0, sret, 0)), 0)).rolling(20).sum().values
        ti = pd.Series(np.where(down, -mk_a, 0)).rolling(20).sum().values
        with np.errstate(invalid="ignore", divide="ignore"):
            anti = np.where(ti > 0, np.clip((1 - td / ti) * 100, 0, 100), 50.0)
        vad_sc = np.where(anti > 70, np.minimum(10, vad_sc + 2), np.where(anti > 50, np.minimum(10, vad_sc + 1), vad_sc))

        # ⑤ 突破确认
        hh60 = pd.Series(H).rolling(60).max().values
        with np.errstate(invalid="ignore", divide="ignore"):
            dfh = (hh60 - C) / hh60 * 100
        b = np.select([dfh < 2, dfh < 5, dfh < 10], [3, 2, 1], default=0).astype(float)
        b += np.where(C > O, 2, 0)
        vdy = (np.concatenate([[False], V[1:] > V[:-1]])).astype(float)
        vdy2 = (np.concatenate([[False, False], V[2:] > V[1:-1]])).astype(float)
        b += np.minimum(2, vdy + vdy2)
        e20up = np.concatenate([[False] * 20, (e20.values[20:] > e20.values[:-20])])
        b += np.where((C > e20.values) & e20up, 2, 0)
        # 孤狼：5日跑赢大盘 >10/+5/+2
        s5d = C / np.concatenate([[np.nan] * 5, C[:-5]]) - 1
        with np.errstate(invalid="ignore", divide="ignore"):
            i5d = mkv / np.concatenate([[np.nan] * 5, mkv[:-5]]) - 1
        lead = (s5d - i5d) * 100
        b += np.select([lead > 10, lead > 5, lead > 2], [3, 2, 1], default=0)
        # 高阳模式
        ma20v = pd.Series(V).rolling(20).mean().values
        hv = (C > O) & (V > ma20v * 1.5)
        for i in range(20, n):
            idx = [j for j in range(max(0, i - 14), i + 1) if hv[j]]
            if not idx:
                continue
            j = idx[-1]
            if j + 3 >= i + 1:
                continue
            hc = C[j]
            d1 = (C[j + 1] - hc) / hc * 100; d2 = (C[j + 2] - hc) / hc * 100; d3 = (C[j + 3] - hc) / hc * 100
            if d1 > 0 and d2 > 0:
                b[i] += 3
            elif d1 >= -1 and d2 >= -1 and d3 >= -1:
                b[i] += 2
            elif V[j + 1] < ma20v[j] * .8:
                b[i] += 1
            elif d1 < -3 and V[j + 1] > ma20v[j]:
                b[i] -= 1
        brk = np.clip(b, 0, 15)

        # ⑦ RSVA(20) + SSV(200) + RSL(144)
        with np.errstate(invalid="ignore", divide="ignore"):
            rs = C / mkv
        hh20 = pd.Series(H).rolling(20).max().values; ll20 = pd.Series(L).rolling(20).min().values
        with np.errstate(invalid="ignore", divide="ignore"):
            r1 = np.clip((C - ll20) / (hh20 - ll20) * 100, 0, 100)
        rsh = pd.Series(rs).rolling(20).max().values; rsl_ = pd.Series(rs).rolling(20).min().values
        with np.errstate(invalid="ignore", divide="ignore"):
            r2 = np.clip((rs - rsl_) / (rsh - rsl_) * 100, 0, 100)
        rsva = np.nanmean([r1, r2], axis=0)
        rs_sc = np.select([rsva >= 85, rsva >= 75, rsva >= 65], [3, 2, 1], default=0).astype(float)
        # SSV2 = (C-VWAP)/STDD*100, 窗口200
        sA = pd.Series(AMO); sAC = pd.Series(AMO * C)
        vwap = (sAC.rolling(200).sum() / sA.rolling(200).sum()).values
        m2 = pd.Series((C - vwap) ** 2).rolling(200).sum().values
        cnt = pd.Series(np.ones(n)).rolling(200).sum().values
        with np.errstate(invalid="ignore", divide="ignore"):
            stdd = np.sqrt(m2 / (cnt - 1))
            ssv2 = (C - vwap) / stdd * 100
        rs_sc += np.select([ssv2 > 100, ssv2 > 50, ssv2 > 0], [3, 2, 1], default=0)
        # RSL2
        vwrs = (pd.Series(rs * AMO).rolling(144).sum() / sA.rolling(144).sum()).values
        m3 = pd.Series((rs - vwrs) ** 2).rolling(144).sum().values
        cnt2 = pd.Series(np.ones(n)).rolling(144).sum().values
        with np.errstate(invalid="ignore", divide="ignore"):
            std2 = np.sqrt(m3 / (cnt2 - 1))
            rsl2 = (rs - vwrs) / std2 * 100
        rs_sc += np.select([rsl2 > 100, rsl2 > 50, rsl2 > 0], [4, 3, 1], default=0)
        rs_sc = np.minimum(10, rs_sc)

        # ⑨ 伏击线 & ⑩ RS_D
        sd5 = sc.rolling(5).std(ddof=0).values
        UB = pd.Series(e20).values + 5 * sd5
        with np.errstate(invalid="ignore", divide="ignore"):
            pf = (UB - C) / UB * 100
        amb = np.select([(pf > 0) & (pf < 3), (pf > 0) & (pf < 6)], [5, 3], default=0).astype(float)
        amb = np.where((amb >= 3) & (ssv2 > 0), np.minimum(5, amb + 2), amb)
        w = np.arange(5.0)
        def lin(y):
            s = pd.Series(y, dtype="float64")
            return ((4 * s + 3 * s.shift(1) + 2 * s.shift(2) + 1 * s.shift(3) - 10 * s.rolling(5).mean()) / 10.0).values
        slc = lin(C); slb = lin(mkv)
        with np.errstate(invalid="ignore", divide="ignore"):
            dr5 = slb / mkv * 1000 - slc / C * 1000
        rsd = np.select([(np.abs(dr5) < 15), (np.abs(dr5) < 25)], [3, 2], default=0).astype(float)
        rsd = np.where((np.abs(dr5) < 15) & (dr5 > 0), np.minimum(5, rsd + 2), rsd)

        raw = vcp + ma + vol + vad_sc + brk + rs_sc + amb + rsd
        setup = np.minimum(100, (raw * 100 / 115))
        for i in range(320, n - 21):
            if np.isnan(setup[i]) or np.isnan(nxt[i]) or nxt[i] <= 0 or np.isnan(r20f[i]):
                continue
            if setup[i] >= 40:
                rows.append((code, D[i], setup[i], r20f[i]))
        if ci % 400 == 0:
            print(f"  {ci}/{len(codes)} 事件{len(rows)}", flush=True)

    E = pd.DataFrame(rows, columns=["code", "date", "setup", "r20f"])
    E.to_csv(f"{OUT}/beast_setup_events.csv", index=False)
    print("事件", len(E))
    print(E["setup"].describe().round(1).to_string())


if __name__ == "__main__":
    main()
