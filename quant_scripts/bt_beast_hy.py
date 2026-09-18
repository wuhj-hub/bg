#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""猛兽派「低吸股池 / 突破股池」回测（2026-09-18）

来源：猛兽派选股《巧用动量指标选股·总纲》（2026-01-13）

【原文公式】
领先股池（电脑版B）: RSV>74 AND RSV1>85 AND RUN1>=70 AND RSVHY>70
低吸股池: ALLQS:=RSV>74 AND RSVHY>70;
          QZPV:=HHV(PV3,10)>12;  XZPV:=ABS(PV2)<6;
          XZDR:=ABS(RS_D.DR)<15; SBL:=AMO<HHV(AMO,22)*0.6;
          ALLQS AND QZPV AND XZPV AND XZDR AND SBL;
突破股池: ALLQS:=RSV>74 AND RSV1>85 AND RSVHY>74;
          QZPV:=LLV(REF(ABS(PV2),1),2)<6;  XZPV:=PV3>12;
          ALLQS AND QZPV AND XZPV;

【本回测的适配】
- RSV均 = (RSV1 + RSV2)/2，N1=144（原文）；RSV1=个股144日位置, RSV2=RS线144日位置
- 基准指数 880003(平均股价) 本地无 → 用【全市场等权平均收盘】近似（880003 即平均股价指数）
- AMO(成交额) 本地无 → 用 volume 近似（PV3 为比值 AMO/LLV(AMO)，近似影响小）
- RSVHY(行业强度)：本轮先跳过（需行业指数），仅测个股条件
- PV2/PV3 按 beast_screener.calc_ovs_exact 的公式（N1=2, N2=4, M=15）
- DR 按 calc_rs_d 公式（N=5）
"""
import csv, json
from collections import defaultdict
import numpy as np

DATA = "/sandbox/workspace/zxz_bt/data/kline_daily_vol.csv"
OUT = "/sandbox/workspace/zxz_bt/outputs"
HOLD = [5, 10, 20]
WARM = 150          # 需 >=144 日预热
N1 = 144


def load():
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
    return by


def main():
    by = load()
    codes = [c for c in by if c.startswith(("sh600", "sh601", "sh603", "sh605",
                                            "sz000", "sz001", "sz002", "sz003"))]
    print(f"主板股票: {len(codes)}")

    # ① 构造"全市场等权平均收盘"作为 880003 的近似（按日期）
    day_sum = defaultdict(float); day_cnt = defaultdict(int)
    for c in codes:
        for b in by[c]:
            day_sum[b[0]] += b[4]; day_cnt[b[0]] += 1
    mkt = {d: day_sum[d] / day_cnt[d] for d in day_sum if day_cnt[d] > 0}
    mkt_dates = sorted(mkt)
    print(f"平均股价序列: {len(mkt_dates)} 日（{mkt_dates[0]} ~ {mkt_dates[-1]}）")

    # ①b 行业指数（等权平均收盘，按日）—— 用于 RSVHY
    em = json.load(open("/sandbox/workspace/zxz_bt/em_industry.json", encoding="utf-8"))
    industry = em["industry"]          # {行业: [code6, ...]}
    code2ind = {}
    for ind, cl in industry.items():
        for c6 in cl:
            code2ind[c6] = ind
    # 每行业每日的【等权平均 收盘/最高/最低】
    ind_day = defaultdict(lambda: defaultdict(list))
    for c in codes:
        c6 = c[2:]
        ind = code2ind.get(c6)
        if not ind:
            continue
        for b in by[c]:
            ind_day[ind][b[0]].append((b[4], b[2], b[3]))     # close, high, low
    ind_series = {}
    for ind, dd in ind_day.items():
        ds = sorted(dd)
        ind_series[ind] = {
            "dates": ds,
            "c": np.array([np.mean([x[0] for x in dd[d]]) for d in ds]),
            "h": np.array([np.max([x[1] for x in dd[d]]) for d in ds]),
            "l": np.array([np.min([x[2] for x in dd[d]]) for d in ds]),
            "idx": {d: i for i, d in enumerate(ds)},
        }
    print(f"行业指数: {len(ind_series)} 个")

    res = {"低吸": {h: [] for h in HOLD}, "突破": {h: [] for h in HOLD},
           "领先": {h: [] for h in HOLD}}
    base = {h: defaultdict(lambda: [0.0, 0]) for h in HOLD}
    n_sig = defaultdict(int)

    for ci, code in enumerate(codes):
        bars = by[code]
        n = len(bars)
        if n < WARM + 30:
            continue
        d = [b[0] for b in bars]
        o = np.array([b[1] for b in bars]); h = np.array([b[2] for b in bars])
        l = np.array([b[3] for b in bars]); c = np.array([b[4] for b in bars])
        v = np.array([b[5] for b in bars])
        # 平均股价对齐
        mkt_arr = np.array([mkt.get(x, np.nan) for x in d])
        if np.isnan(mkt_arr).all():
            continue

        # ---- RSV1: 个股 N1 日位置 ----
        rsv1 = np.full(n, np.nan)
        for i in range(N1 - 1, n):
            lo = l[i - N1 + 1:i + 1].min(); hi = h[i - N1 + 1:i + 1].max()
            rsv1[i] = (c[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
        # ---- RSV2: RS 线的 N1 日位置 ----
        rs = c / mkt_arr
        rsv2 = np.full(n, np.nan)
        for i in range(N1 - 1, n):
            seg = rs[i - N1 + 1:i + 1]
            if np.isnan(seg).any():
                continue
            lo = seg.min(); hi = seg.max()
            rsv2[i] = (rs[i] - lo) / (hi - lo) * 100 if hi > lo else 50.0
        rsv = (rsv1 + rsv2) / 2          # ← RSV均

        # ---- PV2 / PV3 (OVS) ----
        zf = np.zeros(n); bsr = np.zeros(n)
        for i in range(1, n):
            hi_ = max(h[i], c[i - 1]); lw_ = min(l[i], c[i - 1])
            zf[i] = (c[i] - c[i - 1]) / c[i - 1] if c[i - 1] else 0
            bsr[i] = abs(c[i] - c[i - 1]) / (hi_ - lw_) if hi_ > lw_ else 0
        ns1, ns2, M = 2, 4, 15
        pv2 = np.full(n, np.nan); pv3 = np.full(n, np.nan)
        for i in range(M + ns2, n):
            ma2 = v[i - ns1 + 1:i + 1].mean() or 1
            pv2[i] = sum(bsr[j] * zf[j] * v[j] / (v[j - ns1 + 1:j + 1].mean() or 1)
                         for j in range(i - ns1 + 1, i + 1)) * 100
            pv3[i] = sum(zf[j] * v[j] / (v[j - M + 1:j + 1].min() or 1)
                         for j in range(i - ns2 + 1, i + 1)) * 100

        # ---- DR (RS_D) ----
        nm = 5
        dr = np.full(n, np.nan)
        for i in range(nm + 1, n):
            xs = np.arange(nm)
            seg_rs = rs[i - nm + 1:i + 1]; seg_i = mkt_arr[i - nm + 1:i + 1]; seg_c = c[i - nm + 1:i + 1]
            if np.isnan(seg_rs).any() or np.isnan(seg_i).any():
                continue
            def sl(y):
                return np.polyfit(xs, y, 1)[0] if np.std(y) > 0 else 0
            xl_i = sl(seg_i) / seg_i[-1] * 1000 if seg_i[-1] else 0
            xl_c = sl(seg_c) / seg_c[-1] * 1000 if seg_c[-1] else 0
            dr[i] = xl_i - xl_c

        # ---- RSVHY（行业强度，N1=144）----
        ind = code2ind.get(code[2:])
        rsvhy = np.full(n, np.nan)
        if ind and ind in ind_series:
            S = ind_series[ind]
            idxmap = S["idx"]
            ic = np.array([S["c"][idxmap[x]] if x in idxmap else np.nan for x in d])
            ih = np.array([S["h"][idxmap[x]] if x in idxmap else np.nan for x in d])
            il = np.array([S["l"][idxmap[x]] if x in idxmap else np.nan for x in d])
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

        # ---- 基准 ----
        for i in range(WARM, n):
            for hh in HOLD:
                if i + hh < n and c[i] > 0:
                    b_ = base[hh][d[i]]; b_[0] += c[i + hh] / c[i] - 1; b_[1] += 1

        # ---- 筛选 ----
        for i in range(WARM, n - max(HOLD) - 1):
            if np.isnan(rsv[i]) or np.isnan(pv2[i]) or np.isnan(pv3[i]) or np.isnan(dr[i]):
                continue
            if not (rsv[i] > 74):
                continue
            if np.isnan(rsvhy[i]):
                continue                      # 无行业数据则跳过（严格口径）
            hy = rsvhy[i]
            # 低吸
            qzpv = np.nanmax(pv3[max(0, i - 9):i + 1]) > 12
            xzpv = abs(pv2[i]) < 6
            xzdr = abs(dr[i]) < 15
            sbl = v[i] < np.max(v[max(0, i - 21):i + 1]) * 0.6
            if qzpv and xzpv and xzdr and sbl and hy > 70:      # RSVHY>70（原文条件）
                n_sig["低吸"] += 1
                for hh in HOLD:
                    if i + hh < n:
                        res["低吸"][hh].append((d[i], c[i + hh] / c[i] - 1))
            # 突破
            if not np.isnan(rsv1[i]) and rsv1[i] > 85:
                qzpv2 = np.nanmin(np.abs([pv2[i - 1], pv2[i - 2]])) < 6
                if qzpv2 and pv3[i] > 12 and hy > 74:            # RSVHY>74（原文条件）
                    n_sig["突破"] += 1
                    for hh in HOLD:
                        if i + hh < n:
                            res["突破"][hh].append((d[i], c[i + hh] / c[i] - 1))
            # 领先（RSV>74 且 RSV1>85）
            if not np.isnan(rsv1[i]) and rsv1[i] > 85 and hy > 70:   # RSVHY>70（原文条件）
                n_sig["领先"] += 1
                for hh in HOLD:
                    if i + hh < n:
                        res["领先"][hh].append((d[i], c[i + hh] / c[i] - 1))

    # 基准按日聚合
    base_avg = {}
    for hh in HOLD:
        vals = [vv[0] / vv[1] for vv in base[hh].values() if vv[1]]
        base_avg[hh] = float(np.mean(vals)) if vals else 0
    print("\n基准:", " / ".join(f"{h}日{base_avg[h]*100:+.2f}%" for h in HOLD))
    print(f"信号数: {dict(n_sig)}\n")

    out = {"base": base_avg, "signals": dict(n_sig), "pools": {}}
    for pool in ("领先", "低吸", "突破"):
        print(f"【{pool}股池】")
        if not res[pool][5]:
            print("  （无信号）\n"); continue
        print(f"  {'持有':<5}{'n':>7}{'平均':>10}{'中位':>10}{'胜率':>8}{'超额':>10}{'独立日':>8}")
        out["pools"][pool] = {}
        for hh in HOLD:
            recs = res[pool][hh]
            if not recs:
                continue
            rets = np.array([r for _, r in recs])
            byd = defaultdict(list)
            for dt, r in recs:
                byd[dt].append(r)
            daily = np.array([np.mean(x) for x in byd.values()])
            ex = np.mean(daily) - base_avg[hh]
            print(f"  {hh}日{'':<3}{len(rets):>7}{np.mean(rets)*100:>+9.2f}%{np.median(rets)*100:>+9.2f}%"
                  f"{(rets>0).mean()*100:>7.1f}%{ex*100:>+9.2f}%{len(daily):>8}")
            out["pools"][pool][str(hh)] = {"n": len(rets), "avg": float(np.mean(rets)),
                                           "median": float(np.median(rets)),
                                           "win": float((rets > 0).mean()), "excess": float(ex),
                                           "days": len(daily)}
        print()
    # ---- 分年度稳定性 ----
    print("\n" + "=" * 78)
    print("分年度稳定性（10日持有，按信号年）")
    print("=" * 78)
    # 基准分年度（10日）
    base_year = defaultdict(lambda: [0.0, 0])
    for dt, vv in base[10].items():
        base_year[dt[:4]][0] += vv[0]; base_year[dt[:4]][1] += vv[1]
    byear_base = {y: (s_[0]/s_[1] if s_[1] else 0) for y, s_ in base_year.items()}

    yearly = {}
    for pool in ("领先", "低吸", "突破"):
        recs = res[pool][10]
        if not recs:
            continue
        g = defaultdict(list)
        for dt, r in recs:
            g[dt[:4]].append(r)
        print(f"\n【{pool}池】10日")
        print(f"  {'年份':<7}{'n':>7}{'平均':>10}{'中位':>10}{'胜率':>8}{'基准':>9}{'超额':>10}")
        yearly[pool] = {}
        for y in sorted(g.keys()):
            arr = np.array(g[y])
            b = byear_base.get(y, 0)
            yearly[pool][y] = {"n": len(arr), "avg": float(arr.mean()),
                               "median": float(np.median(arr)), "win": float((arr > 0).mean()),
                               "base": float(b), "excess": float(arr.mean() - b)}
            print(f"  {y:<7}{len(arr):>7}{arr.mean()*100:>+9.2f}%{np.median(arr)*100:>+9.2f}%"
                  f"{(arr>0).mean()*100:>7.1f}%{b*100:>+8.2f}%{(arr.mean()-b)*100:>+9.2f}%")
    out["yearly"] = yearly

    with open(f"{OUT}/beast_hy_bt.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=float)
    print("✅ 结果已存 outputs/beast_hy_bt.json")


if __name__ == "__main__":
    main()
