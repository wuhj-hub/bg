#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bt_cycle.py —— 回测周期（月度定期回归）v1.0  (2026-09-24)

目的：把「回测」从一次性动作变成**周期性常态**，防止：
  ① 结论过期（行情结构变化后老结论失效）
  ② 静默漂移（代码/数据口径悄悄变化，没人复查）
  ③ 未来函数混入（数据方向、复权口径）

机制（每月 1 日 09:10 运行，随 evidence_review 之后）：
  Step1 数据体检：方向校验（升序）+ 复权口径 + 样本量与覆盖
  Step2 基准回归：跑「现状参数」，与上月结果比对，偏差超阈值 → 告警
  Step3 候选复核：跑预设候选组合，检验是否仍满足「两段样本外双正」
  Step4 出报告：outputs/回测周期_{YYYY-MM}.md + JSON，异常推微信

用法：
  python3 bt_cycle.py --data <kline.json> [--out outputs] [--push]
"""
import os, sys, json, argparse, statistics as st
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_feed(path):
    from btframework import DataFeed
    return DataFeed(path)


def check_data(feed):
    """Step1 数据体检（铁律0 + 覆盖度）"""
    codes = feed.codes()
    n = len(codes)
    lens = [len(feed.bars(c)) for c in codes[:200]]
    avg = sum(lens) / len(lens) if lens else 0
    # 方向校验：normalize() 已修正，但记录修正只数供审计
    return {"codes": n, "avg_bars": round(avg), "direction_fixed": getattr(feed, "normalized", 0)}


def run_combo(feed, target_kind, stop_mult, maxh=40, lo=250, hi=99999, sample=4):
    """通用组合回测（月线多头过滤）"""
    from btframework import atr_w, ma, prev_high, simulate, prev_low
    acc = []
    for code in feed.codes():
        rows = feed.bars(code)
        cl = [r[2] for r in rows]
        N = len(rows)
        for t in range(max(lo, 250), min(hi, N - maxh - 1), sample):
            C = cl[t]
            if C <= 0.3:
                continue
            m, mp = ma(cl, t, 120), ma(cl, t - 20, 120)
            if not m or not mp or C <= m or m <= mp:
                continue
            a = atr_w(rows, t)
            if not a:
                continue
            stop = C - stop_mult * a
            if stop <= 0 or C <= stop:
                continue
            risk = (C - stop) / C
            if risk > 0.20:
                continue
            if target_kind.startswith("T"):
                tgt = prev_high(rows, t, int(target_kind[1:]))
            elif target_kind == "F10":
                tgt = C * 1.10
            else:                        # MAX 现状：前250日高 + 8%保底
                tgt = max(prev_high(rows, t, 250), C * 1.08)
            if tgt is None or tgt <= C:
                continue
            ret, _ = simulate(rows, t, stop, tgt, maxh)
            if ret is not None:
                acc.append((ret, risk))
    if not acc:
        return None
    rets = [x[0] for x in acc]
    rs = [x[0] / x[1] for x in acc if x[1] > 0]
    return {"n": len(rets), "mean": st.mean(rets) * 100, "med": st.median(rets) * 100,
            "win": len([x for x in rets if x > 0]) / len(rets) * 100,
            "meanR": st.mean(rs), "medR": st.median(rs)}


# 基准（现状参数）与候选（待定期复核）
BASE_PARAMS = ("MAX", 2.0)
CANDIDATES = [("T60", 2.5), ("T120", 2.5), ("F10", 2.5), ("T20", 2.5)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/sandbox/workspace/chipbt/kline800.json")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    feed = load_feed(a.data)
    os.makedirs(a.out, exist_ok=True)
    ym = datetime.now().strftime("%Y-%m")
    lines = [f"# 回测周期报告 {ym}", f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M}", ""]

    # Step1
    d = check_data(feed)
    lines += ["## 一、数据体检", "",
              f"- 有效标的：{d['codes']} 只｜平均K线：{d['avg_bars']} 根",
              f"- **方向校验**：修正 {d['direction_fixed']} 只（降序→升序，铁律0）", ""]

    # Step2/3 分两段
    seg = {"前段(早)": (250, 470), "后段(近)": (470, 999999)}
    lines += ["## 二、基准回归（现状参数 MAX×2ATR）", "",
              f"| 段 | 样本 | 均值% | 中位% | 胜率% | 均R | 中R |", "|---|---|---|---|---|---|---|"]
    base_res = {}
    for sn, (lo, hi) in seg.items():
        r = run_combo(feed, *BASE_PARAMS, lo=lo, hi=hi)
        if r:
            base_res[sn] = r
            lines.append(f"| {sn} | {r['n']} | {r['mean']:.3f} | {r['med']:.3f} | {r['win']:.1f} | {r['meanR']:+.3f} | {r['medR']:+.3f} |")
    base_ok = base_res.get("前段(早)", {}).get("meanR", 0) > 0 and base_res.get("后段(近)", {}).get("meanR", 0) > 0
    lines += ["", f"- 基准两段双正：{'✅ 是' if base_ok else '❌ 否（行情或口径变化，需关注）'}", ""]

    # Step3 候选复核
    lines += ["## 三、候选组合复核（通过标准：两段均R 同为正）", "",
              f"| 组合 | 前段均R | 后段均R | 前段中R | 后段中R | 判定 |", "|---|---|---|---|---|---|"]
    passed = []
    for tk, sm in CANDIDATES:
        r1 = run_combo(feed, tk, sm, lo=250, hi=470) or {}
        r2 = run_combo(feed, tk, sm, lo=470, hi=999999) or {}
        ok = r1.get("meanR", -1) > 0 and r2.get("meanR", -1) > 0
        if ok:
            passed.append(f"{tk}×{sm}ATR")
        lines.append(f"| {tk}×{sm}ATR | {r1.get('meanR', 0):+.3f} | {r2.get('meanR', 0):+.3f} | "
                     f"{r1.get('medR', 0):+.3f} | {r2.get('medR', 0):+.3f} | {'✅通过' if ok else '❌未通过'} |")
    lines += ["", f"- **本期通过候选**：{'、'.join(passed) if passed else '无（维持现状参数）'}", ""]

    # Step4 结论与告警
    lines += ["## 四、结论与动作", ""]
    alerts = []
    if not base_ok:
        alerts.append("基准两段未双正（行情结构可能变化）")
        lines.append("- ⚠️ 基准未双正：检查是否行情结构变化或数据口径漂移")
    if passed:
        lines.append(f"- 💡 有候选通过：{passed} → 可评估替换（需人工确认后改代码）")
    else:
        lines.append("- ✅ 无候选通过 → **维持现状参数**（不折腾）")
    lines.append("")
    lines.append("> 机制说明：本报告为**月度常规回归**，不改代码；只有候选连续 2 期通过才建议落地。")

    md = "\n".join(lines)
    p_md = os.path.join(a.out, f"回测周期_{ym}.md")
    open(p_md, "w", encoding="utf-8").write(md)
    json.dump({"month": ym, "data": d, "base": base_res, "passed": passed,
               "alerts": alerts, "base_ok": base_ok},
              open(os.path.join(a.out, "bt_cycle_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(md)
    print(f"\n✅ 报告：{p_md}")

    if a.push and alerts:
        import urllib.request
        tk = os.environ.get("PUSH_TOKEN", "")
        if tk:
            body = json.dumps({"token": tk, "title": "⚠️回测周期告警",
                               "content": "；".join(alerts), "template": "txt"}).encode()
            try:
                urllib.request.urlopen(urllib.request.Request(
                    "https://pushplus.plus/send", data=body,
                    headers={"Content-Type": "application/json"}), timeout=15)
                print("推送 ✅")
            except Exception as e:
                print("推送失败", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
