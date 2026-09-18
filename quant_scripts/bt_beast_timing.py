#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""猛兽突破池 · 择时 + 分批减仓退出 回测（2026-09-18）

需求：择时过滤 + 突破池筛选 + 「涨多少减多少」的分批减仓退出，保住利润。

信号：猛兽派突破池（照原文公式）
  RSV>74 AND RSV1>85 AND RSVHY>74 AND LLV(REF(ABS(PV2),1),2)<6 AND PV3>12

择时（Timing）：
  T0  无择时（基线）
  T1  市场20日收益 > 0        （全市场等权均价，近似大盘环境）
  T2  个股收盘 > MA20         （个股趋势）
  T3  T1 AND T2               （双条件）

退出（Exit，分批减仓）：
  E0  固定持有 10 日
  E1  跌破 MA10 全出
  E2  +10%减1/3 → +20%减1/3 → +30%清仓
  E3  +15%减半 → +30%清仓
  E4  +10%减半 → 跌破MA10清剩余
  E5  +10%减1/3 → +20%减1/3 → 跌破MA10清剩余
  E6  +10%减1/3 → +20%减1/3 → +15%后回撤5%清剩余
  E7  G4式：+5%后回撤3% 或 跌破MA10
  E8  +20%减半 → +40%清仓
"""
import csv, json
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
IND = "/sandbox/workspace/zxz_bt/em_industry.json"
OUT = "/sandbox/workspace/zxz_bt/outputs"
HOLD = [5, 10, 20]
WARM = 150
N1 = 144
MAXH = 60            # 退出模拟最长持有


def main():
    by = defaultdict(list)
    with open(DATA, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                by[r["code"]].append((r["date"], float(r["open"]), float(r["high"]),
                                      float(r["low"]), float(r["close"]), float(r["volume"])))
            except (ValueError, KeyError):
                continue
    for c in by:
        by[c].sort(key=lambda x: x[0])
    codes = [c for c in by if c.startswith(("sh600", "sh601", "sh603", "sh605",
                                            "sz000", "sz001", "sz002", "sz003"))]
    # 全市场均价
    ds_ = defaultdict(float); dc_ = defaultdict(int)
    for c in codes:
        for b in by[c]:
            ds_[b[0]] += b[4]; dc_[b[0]] += 1
    mkt = {d: ds_[d] / dc_[d] for d in ds_ if dc_[d] > 0}
    mkt_dates = sorted(mkt)
    mkt_arr_all = np.array([mkt[d] for d in mkt_dates])
    mkt_idx = {d: i for i, d in enumerate(mkt_dates)}
    # 市场20日收益
    mkt_ret20 = np.full(len(mkt_dates), np.nan)
    for i in range(20, len(mkt_dates)):
        mkt_ret20[i] = mkt_arr_all[i] / mkt_arr_all[i - 20] - 1
    # 行业
    em = json.load(open(IND, encoding="utf-8"))
    code2ind = {}
    for ind, cl in em["industry"].items():
        for c6 in cl:
            code2ind[c6] = ind
    ind_day = defaultdict(lambda: defaultdict(list))
    for c in codes:
        ind = code2ind.get(c[2:])
        if not ind:
            continue
        for b in by[c]:
            ind_day[ind][b[0]].append((b[4], b[2], b[3]))
    ind_series = {}
    for ind, dd in ind_day.items():
        dts = sorted(dd)
        ind_series[ind] = {
            "c": np.array([np.mean([x[0] for x in dd[d]]) for d in dts]),
            "h": np.array([np.max([x[1] for x in dd[d]]) for d in dts]),
            "l": np.array([np.min([x[2] for x in dd[d]]) for d in dts]),
            "idx": {d: i for i, d in enumerate(dts)},
        }
    print(f"股票 {len(codes)} / 行业 {len(ind_series)}")

    # ===== 生成突破池信号 =====
    signals = []          # (code, date, i)
    for code in codes:
        bars = by[code]; n = len(bars)
        if n < WARM + 30:
            continue
        d = [b[0] for b in bars]
        h = np.array([b[2] for b in bars]); l = np.array([b[3] for b in bars])
        c = np.array([b[4] for b in bars]); v = np.array([b[5] for b in bars])
        mkt_arr = np.array([mkt.get(x, np.nan) for x in d])
        if np.isnan(mkt_arr).all():
            continue
        rsv1 = np.full(n, np.nan); rsv2 = np.full(n, np.nan)
        for i in range(N1 - 1, n):
            lo = l[i - N1 + 1:i + 1].min(); hi = h[i - N1 + 1:i + 1].max()
            rsv1[i] = (c[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
        rs = c / mkt_arr
        for i in range(N1 - 1, n):
            seg = rs[i - N1 + 1:i + 1]
            if np.isnan(seg).any():
                continue
            lo = seg.min(); hi = seg.max()
            rsv2[i] = (rs[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
        rsv = (rsv1 + rsv2) / 2
        # PV2/PV3
        zf = np.zeros(n); bsr = np.zeros(n)
        for i in range(1, n):
            hi_ = max(h[i], c[i - 1]); lw_ = min(l[i], c[i - 1])
            zf[i] = (c[i] - c[i - 1]) / c[i - 1] if c[i - 1] else 0
            bsr[i] = abs(c[i] - c[i - 1]) / (hi_ - lw_) if hi_ > lw_ else 0
        pv2 = np.full(n, np.nan); pv3 = np.full(n, np.nan)
        for i in range(20, n):
            pv2[i] = sum(bsr[j] * zf[j] * v[j] / (v[j - 1:j + 1].mean() or 1)
                         for j in range(i - 1, i + 1)) * 100
            pv3[i] = sum(zf[j] * v[j] / (v[j - 14:j + 1].min() or 1)
                         for j in range(i - 3, i + 1)) * 100
        # RSVHY
        ind = code2ind.get(code[2:]); rsvhy = np.full(n, np.nan)
        if ind in ind_series:
            S = ind_series[ind]; im = S["idx"]
            ic = np.array([S["c"][im[x]] if x in im else np.nan for x in d])
            ih = np.array([S["h"][im[x]] if x in im else np.nan for x in d])
            il = np.array([S["l"][im[x]] if x in im else np.nan for x in d])
            rshy = ic / mkt_arr
            for i in range(N1 - 1, n):
                lo = np.nanmin(il[i - N1 + 1:i + 1]); hi = np.nanmax(ih[i - N1 + 1:i + 1])
                v1 = (ic[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
                seg = rshy[i - N1 + 1:i + 1]
                if np.isnan(seg).any():
                    v2 = 50.0
                else:
                    lo2 = seg.min(); hi2 = seg.max()
                    v2 = (seg[-1] - lo2) / (hi2 - lo2) * 100 if hi2 > lo2 else 50.0
                rsvhy[i] = (v1 + v2) / 2
        for i in range(WARM, n - MAXH - 1):
            if np.isnan(rsv[i]) or np.isnan(rsv1[i]) or np.isnan(pv2[i]) or np.isnan(pv3[i]) or np.isnan(rsvhy[i]):
                continue
            if not (rsv[i] > 74 and rsv1[i] > 85 and rsvhy[i] > 74):
                continue
            if np.nanmin(np.abs([pv2[i - 1], pv2[i - 2]])) < 6 and pv3[i] > 12:
                signals.append((code, d[i], i))
    print(f"突破池信号: {len(signals)}")

    # ===== 择时 + 退出 模拟 =====
    TIMING = {
        "T0无择时": lambda: True,
        "T1市场20日>0": None,      # 占位，下面用闭包
        "T2个股>MA20": None,
        "T3双条件": None,
    }
    EXITS = ["E0固定10日", "E1破MA10", "E2_10/20/30三段", "E3_15减半30清",
             "E4_10减半破MA10清", "E5_10/20三段破MA10清", "E6_10/20三段回撤5%清",
             "E7_+5后回撤3或破MA10", "E8_20减半40清"]

    def simulate(bars, entry_i, ma10, ma20, exit_rule):
        """返回 (ret, days)；分批按等权计算"""
        c = bars["c"]; h = bars["h"]
        E = c[entry_i]
        end = min(entry_i + MAXH, len(c) - 1)
        if E <= 0:
            return None
        if exit_rule == "E0固定10日":
            return (c[min(entry_i + 10, len(c) - 1)] / E - 1, 10)
        peak = E; held = 1.0; realized = 0.0
        for k in range(1, end - entry_i + 1):
            j = entry_i + k
            r = c[j] / E - 1
            peak = max(peak, h[j])
            if exit_rule == "E1破MA10":
                if not np.isnan(ma10[j]) and c[j] < ma10[j]:
                    return (realized + held * r, k)
            elif exit_rule == "E2_10/20/30三段":
                for lvl, cut in ((0.30, 1.0), (0.20, 1 / 3), (0.10, 1 / 3)):
                    if r >= lvl and held > 0 and (held > 1 - lvl * 0 or True):
                        pass
                # 逐档：10%减1/3, 20%再减1/3, 30%清
                if r >= 0.10 and held > 0.66:
                    realized += (1 / 3) * r; held -= 1 / 3
                elif r >= 0.20 and held > 0.33:
                    realized += (1 / 3) * r; held -= 1 / 3
                elif r >= 0.30 and held > 0:
                    realized += held * r; held = 0
                if held <= 0:
                    return (realized, k)
            elif exit_rule == "E3_15减半30清":
                if r >= 0.15 and held > 0.5:
                    realized += 0.5 * r; held -= 0.5
                elif r >= 0.30 and held > 0:
                    realized += held * r; held = 0
                if held <= 0:
                    return (realized, k)
            elif exit_rule == "E4_10减半破MA10清":
                if r >= 0.10 and held > 0.5:
                    realized += 0.5 * r; held -= 0.5
                if not np.isnan(ma10[j]) and c[j] < ma10[j] and held > 0:
                    realized += held * r; held = 0
                if held <= 0:
                    return (realized, k)
            elif exit_rule == "E5_10/20三段破MA10清":
                if r >= 0.10 and held > 0.66:
                    realized += (1 / 3) * r; held -= 1 / 3
                elif r >= 0.20 and held > 0.33:
                    realized += (1 / 3) * r; held -= 1 / 3
                if not np.isnan(ma10[j]) and c[j] < ma10[j] and held > 0:
                    realized += held * r; held = 0
                if held <= 0:
                    return (realized, k)
            elif exit_rule == "E6_10/20三段回撤5%清":
                if r >= 0.10 and held > 0.66:
                    realized += (1 / 3) * r; held -= 1 / 3
                elif r >= 0.20 and held > 0.33:
                    realized += (1 / 3) * r; held -= 1 / 3
                if (peak / E - 1) >= 0.15 and (peak - c[j]) / peak >= 0.05 and held > 0:
                    realized += held * r; held = 0
                if held <= 0:
                    return (realized, k)
            elif exit_rule == "E7_+5后回撤3或破MA10":
                cond1 = (peak / E - 1) >= 0.05 and (peak - c[j]) / peak >= 0.03
                cond2 = not np.isnan(ma10[j]) and c[j] < ma10[j]
                if cond1 or cond2:
                    return (r, k)
            elif exit_rule == "E8_20减半40清":
                if r >= 0.20 and held > 0.5:
                    realized += 0.5 * r; held -= 0.5
                elif r >= 0.40 and held > 0:
                    realized += held * r; held = 0
                if held <= 0:
                    return (realized, k)
        j = end
        return (realized + held * (c[j] / E - 1), end - entry_i)

    # 预计算每只的 MA
    prep = {}
    for code in codes:
        bars = by[code]
        n = len(bars)
        if n < WARM + 30:
            continue
        c = np.array([b[4] for b in bars])
        ma10 = np.full(n, np.nan); ma20 = np.full(n, np.nan)
        for i in range(9, n):
            ma10[i] = c[i - 9:i + 1].mean()
        for i in range(19, n):
            ma20[i] = c[i - 19:i + 1].mean()
        prep[code] = {"c": c, "h": np.array([b[2] for b in bars]),
                      "ma10": ma10, "ma20": ma20, "d": [b[0] for b in bars]}

    results = {}
    for tname in TIMING:
        for ename in EXITS:
            results[(tname, ename)] = []
    for code, dt, i in signals:
        P = prep.get(code)
        if not P:
            continue
        mi = mkt_idx.get(dt)
        # 择时判定
        t1 = mi is not None and not np.isnan(mkt_ret20[mi]) and mkt_ret20[mi] > 0
        t2 = not np.isnan(P["ma20"][i]) and P["c"][i] > P["ma20"][i]
        ok = {"T0无择时": True, "T1市场20日>0": t1, "T2个股>MA20": t2, "T3双条件": t1 and t2}
        for tname, passed in ok.items():
            if not passed:
                continue
            for ename in EXITS:
                r = simulate(P, i, P["ma10"], P["ma20"], ename)
                if r:
                    results[(tname, ename)].append((dt, r[0], r[1]))

    # 基准
    base = {}
    for hh in HOLD:
        tot, cnt = 0.0, 0
        for code in codes:
            bars = by[code]; n = len(bars)
            c = np.array([b[4] for b in bars])
            for i in range(WARM, n - hh):
                if c[i] > 0:
                    tot += c[i + hh] / c[i] - 1; cnt += 1
        base[hh] = tot / cnt if cnt else 0
    print("基准:", " / ".join(f"{h}日{base[h]*100:+.2f}%" for h in HOLD))

    print(f"\n{'择时':<16}{'退出':<28}{'n':>7}{'平均':>9}{'中位':>9}{'胜率':>8}{'持有':>7}{'扣0.2%':>9}")
    print("-" * 92)
    out = {"base": base, "grid": []}
    for tname in TIMING:
        for ename in EXITS:
            rec = results[(tname, ename)]
            if not rec:
                continue
            rets = np.array([r for _, r, _ in rec]); dys = np.array([d for _, _, d in rec])
            net = np.mean(rets) - 0.002
            print(f"{tname:<16}{ename:<28}{len(rets):>7}{np.mean(rets)*100:>+8.2f}%{np.median(rets)*100:>+8.2f}%"
                  f"{(rets>0).mean()*100:>7.1f}%{np.mean(dys):>7.1f}{net*100:>+8.2f}%")
            out["grid"].append({"timing": tname, "exit": ename, "n": len(rets),
                                "avg": float(np.mean(rets)), "median": float(np.median(rets)),
                                "win": float((rets > 0).mean()), "days": float(np.mean(dys)),
                                "net": float(net)})
    # ===== 年度稳定性（关键组合）=====
    KEY = [("T0无择时", "E0固定10日"), ("T0无择时", "E6_10/20三段回撤5%清"),
           ("T0无择时", "E7_+5后回撤3或破MA10"), ("T1市场20日>0", "E0固定10日"),
           ("T1市场20日>0", "E6_10/20三段回撤5%清")]
    # 年度基准（10日，全市场）
    yb = defaultdict(lambda: [0.0, 0])
    tot_by_year = defaultdict(lambda: [0.0, 0])
    for code in codes:
        bars = by[code]; n = len(bars); c = np.array([b[4] for b in bars])
        for i in range(WARM, n - 10):
            if c[i] > 0:
                y = bars[i][0][:4]
                tot_by_year[y][0] += c[i + 10] / c[i] - 1; tot_by_year[y][1] += 1
    ybase = {y: (v[0] / v[1] if v[1] else 0) for y, v in tot_by_year.items()}

    print("\n" + "=" * 86)
    print("年度稳定性（按信号年）")
    print("=" * 86)
    yearly = {}
    for tn, en in KEY:
        rec = results[(tn, en)]
        if not rec: continue
        g = defaultdict(list)
        for dt, r, _d in rec:
            g[dt[:4]].append(r)
        print(f"\n【{tn} × {en}】")
        print(f"  {'年份':<7}{'n':>6}{'平均':>10}{'中位':>10}{'胜率':>8}{'基准10日':>10}{'超额':>10}")
        yearly[f"{tn}|{en}"] = {}
        for y in sorted(g.keys()):
            arr = np.array(g[y]); b = ybase.get(y, 0)
            yearly[f"{tn}|{en}"][y] = {"n": len(arr), "avg": float(arr.mean()),
                                       "median": float(np.median(arr)), "win": float((arr > 0).mean()),
                                       "excess": float(arr.mean() - b)}
            print(f"  {y:<7}{len(arr):>6}{arr.mean()*100:>+9.2f}%{np.median(arr)*100:>+9.2f}%"
                  f"{(arr>0).mean()*100:>7.1f}%{b*100:>+9.2f}%{(arr.mean()-b)*100:>+9.2f}%")
    out["yearly"] = yearly

    json.dump(out, open(f"{OUT}/beast_timing_exit.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)
    print("\n✅ 已存 outputs/beast_timing_exit.json")


if __name__ == "__main__":
    main()
