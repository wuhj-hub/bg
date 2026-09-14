#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「鱼身 / 猛兽 / 双弦」体系的口径搬到历史面板上，按 market_regime 环境分层

口径严格照搬仓库脚本：
  鱼身·黄金起爆  ← fish_body_enhanced.detect_golden_breakout
      近10日内有涨停(涨幅≥9.5%) → 其后2~5日 量≤涨停日量×0.8 且 不破均价线((H+L)/2×0.98)
  鱼身·均线回踩  ← fish_body_enhanced.detect_fish_patterns 模式2
      MA20>MA60 且 DIF>0 且 DEA>0 且 |C-MA10|/MA10<5% 且 C>MA5 且 C≥布林中轨
  鱼身·箱体突破  ← fish_body_enhanced.box_breakout_valid
      箱体(前40根收盘,宽≤40%) + 当日收盘>箱顶×1.005 + 突破量≥箱体均量×1.5 + 箱底乖离<30%
  猛兽·伏击线    ← beast_screener.calc_ambush_line
      BOL=MA20, SD=STD(C,5), UB=BOL+5SD, 0<(UB-C)/UB<6%  → ambush_score≥3
  猛兽·RS_D低吸  ← beast_screener.calc_rs_d
      DR = SLOPE(IND,5)/IND*1000 − SLOPE(C,5)/C*1000，|DR|<15 且 DR>0
  双弦·低价共振  ← run_shuangxian 门控的近似（原版含资金维度，历史不可得，此处用价格+动量代理）
      price≤10 且 大盘温度≥40 且 20日动量>0
"""
import os
import numpy as np
import pandas as pd

BASE = "/sandbox/workspace/zxz_bt"
DATA, OUT = f"{BASE}/data", f"{BASE}/outputs"


def main():
    df = pd.read_csv(f"{DATA}/kline_daily_vol.csv", dtype={"code": str, "date": str})
    df = df[df["close"] > 0].sort_values(["code", "date"]).reset_index(drop=True)
    print("面板", len(df), df.code.nunique(), "只")

    # 指数（上证）作 RS_D 基准
    idx = pd.read_csv(f"{DATA}/regime_new_daily.csv", dtype={"date": str})
    # 大盘温度门控：上证 5 线力量得分 s_sc（≥0.4 视为温度≥40）
    ret = df.pivot_table(index="date", columns="code", values="close").pct_change(fill_method=None)
    mk = (1 + ret.mean(axis=1).fillna(0.0)).cumprod()
    ma20 = mk.rolling(20).mean(); ma60 = mk.rolling(60).mean()
    idx_map = dict(zip(idx["date"], idx["s_sc"] if "s_sc" in idx else pd.Series([np.nan] * len(idx))))

    rows = []
    codes = list(df.groupby("code", sort=False))
    for ci, (code, g) in enumerate(codes):
        g = g.reset_index(drop=True)
        if len(g) < 300:
            continue
        C = g["close"].values; H = g["high"].values; L = g["low"].values
        O = g["open"].values; V = g["volume"].values; D = g["date"].values
        n = len(g)
        O_ = O; C_ = C
        pct = np.concatenate([[np.nan], C[1:] / C[:-1] - 1])
        nxt = np.concatenate([O[1:], [np.nan]])
        r5 = np.concatenate([C[5:] / nxt[:-5] - 1, [np.nan] * 5])
        r10 = np.concatenate([C[10:] / nxt[:-10] - 1, [np.nan] * 10])
        r20 = np.concatenate([C[20:] / nxt[:-20] - 1, [np.nan] * 20])

        sc = pd.Series(C)
        ma5 = sc.rolling(5).mean().values; ma10 = sc.rolling(10).mean().values
        ma20v = sc.rolling(20).mean().values; ma60v = sc.rolling(60).mean().values
        ema12 = sc.ewm(span=12, adjust=False).mean(); ema26 = sc.ewm(span=26, adjust=False).mean()
        dif = (ema12 - ema26); dea = dif.ewm(span=9, adjust=False).mean()
        DIF = dif.values; DEA = dea.values

        # ── 鱼身·均线回踩 ──
        fish_ma = (ma20v > ma60v) & (DIF > 0) & (DEA > 0) & \
                  (np.abs(C - ma10) / np.where(ma10 > 0, ma10, np.nan) < .05) & \
                  (C > ma5) & (C >= ma20v)

        # ── 猛兽·伏击线（UB = MA20 + 5×STD(C,5)）──
        sd5 = sc.rolling(5).std(ddof=0).values
        UB = ma20v + 5 * sd5
        with np.errstate(invalid="ignore", divide="ignore"):
            pf = (UB - C) / UB * 100
        ambush = (pf > 0) & (pf < 6)

        # ── 猛兽·RS_D（SLOPE 5日线性回归）──
        w = np.arange(5.0)
        def roll_slope(y):
            y = np.asarray(y, dtype=float)
            if len(y) < 5: return np.nan
            seg = y[-5:]
            m = seg.mean()
            return (float((w * seg).sum()) - 10 * m) / 10.0
        # 向量化：Σ(x_i·y_i) = 4y[t]+3y[t-1]+2y[t-2]+1y[t-3]+0y[t-4]
        def lin5(y):
            s = pd.Series(y, dtype="float64")
            num = 4 * s + 3 * s.shift(1) + 2 * s.shift(2) + 1 * s.shift(3)
            m = s.rolling(5).mean()
            return ((num - 10 * m) / 10.0).values
        # 基准对齐
        mkc = dict(zip(mk.index, mk.values))
        bclose = np.array([mkc.get(D[i], np.nan) for i in range(n)])
        sl_c = lin5(C)
        sl_b = lin5(bclose) if not np.isnan(bclose).all() else np.full(n, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            dr = sl_b / bclose * 1000 - sl_c / C * 1000
        rsd = (np.abs(dr) < 15) & (dr > 0)

        # ── 鱼身·箱体突破（当日突破 + 量能 + 位置）──
        fish_box = np.zeros(n, bool)
        for i in range(70, n):
            box = C[i - 42:i - 2]
            if len(box) < 15: continue
            bt, bb = box.max(), box.min()
            if bb <= 0 or (bt - bb) / bb * 100 > 40: continue
            bav = V[i - 42:i - 2].mean()
            if bav <= 0: continue
            if C[i] <= bt * 1.005: continue
            if V[i] / bav < 1.5: continue
            pre = C[max(0, i - 62):i - 42]
            if len(pre) >= 3:
                pv = pre.mean()
                if pv > 0 and (bb / pv - 1) * 100 >= 30: continue
            fish_box[i] = True

        # ── 鱼身·黄金起爆（近10日涨停 → 其后2~5日缩量回踩不破均价线）──
        fish_gold = np.zeros(n, bool)
        for i in range(20, n):
            lo = max(0, i - 9)
            for j in range(lo, i - 1):
                if np.isnan(pct[j]) or pct[j] < .095: continue
                if V[j] <= 0: continue
                avgp = (H[j] + L[j]) / 2
                ok = True
                for k in range(j + 1, min(j + 6, i + 1)):
                    if V[k] > V[j] * .8 or L[k] < avgp * .98:
                        ok = False; break
                if ok:
                    fish_gold[i] = True; break

        # ── 双弦·低价共振（近似）──
        sx = np.zeros(n, bool)
        for i in range(30, n):
            if C[i] > 10: continue
            sc_ = idx_map.get(D[i], np.nan)
            if np.isnan(sc_) or sc_ < 0.4: continue          # 门控1：大盘温度≥40（5线得分≥0.4）
            if C[i] / C[i - 20] - 1 <= 0: continue
            sx[i] = True

        for sig, name in ((fish_gold, "鱼身黄金起爆"), (fish_ma, "鱼身均线回踩"),
                          (fish_box, "鱼身箱体突破"), (ambush, "猛兽伏击线"),
                          (rsd, "猛兽RS_D低吸"), (sx, "双弦低价共振")):
            prev = False
            for i in range(280, n - 21):
                if not sig[i] or np.isnan(nxt[i]) or nxt[i] <= 0 or np.isnan(r20[i]):
                    prev = sig[i]; continue
                if prev:                      # 只保留状态起点，避免重复计数
                    prev = sig[i]; continue
                rows.append((code, D[i], D[i][:4] + D[i][5:7], name,
                             r5[i], r10[i], r20[i]))
                prev = sig[i]
        if ci % 400 == 0:
            print(f"  {ci}/{len(codes)} 事件{len(rows)}", flush=True)

    E = pd.DataFrame(rows, columns=["code", "date", "ym", "signal", "r5", "r10", "r20"])
    mkt = (1 + ret.mean(axis=1).fillna(0.0)).rolling(20).apply(np.prod, raw=True) - 1
    E["mkt20"] = E["date"].map(dict(zip(mkt.index, mkt.values)))
    E.to_csv(f"{OUT}/yaogu_events2.csv", index=False)
    print("事件总数", len(E))
    print(E["signal"].value_counts().to_string())


if __name__ == "__main__":
    main()
