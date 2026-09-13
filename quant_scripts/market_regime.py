#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""当日市场状态判定（曾星智「三级别力量」体系 + 宽度/情绪）

【力量定义】对 9 大指数分别计算三个级别的「5 根线方向」：
  长期力量 = 月线：MA5/10/20/30月 + 月线 MACD-DIF
  中期力量 = 周线：MA5/10/20/30周 + 周线 MACD-DIF
  短期力量 = 日线：MA5/10/20/30日 + 日线 MACD-DIF
【状态分档】方向分=向上线数/5 → 强势向上(1.0)/向上(0.8)/纠缠(0.4~0.6)/向下(0.2)/弱势向下(0.0)
【综合】三级别力量(9大指数均值) + 市场宽度 + 情绪 → 牛市/震荡市/熊市

输出：
  market_regime_latest.json   （仓库根，结构化，供其他脚本引用）
  market_regime_latest.md     （仓库根，摘要，供推送）
  outputs/市场状态判定_{date}.md
"""
import os, re, json, subprocess, time, datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTD = os.path.join(ROOT, "outputs")
os.makedirs(OUTD, exist_ok=True)
WESTOCK = "npx -y westock-data-skillhub@1.0.3"
IDX = {
    "上证指数": "sh000001", "深证成指": "sz399001", "上证50": "sh000016",
    "沪深300": "sz399300", "中小100": "sz399005", "创业板指": "sz399006",
    "科创50": "sh000688", "北证50": "bj899050", "中证500": "sh000905",
}


def sh(args, timeout=420):
    for i in range(3):
        try:
            r = subprocess.run(f"{WESTOCK} {args}", shell=True, capture_output=True,
                               text=True, timeout=timeout)
            t = r.stdout or ""
            if t and "执行失败" not in t:
                return t
        except Exception:
            pass
        time.sleep(3 + 4 * i)
    return ""


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def power_state(C):
    if C is None or len(C) < 35:
        return None, "数据不足", "-"
    ma5, ma10, ma20, ma30 = [C.rolling(k).mean() for k in (5, 10, 20, 30)]
    dif = ema(C, 10) - ema(C, 22)
    dirs = [ma5.iloc[-1] > ma5.iloc[-2], ma10.iloc[-1] > ma10.iloc[-2],
            ma20.iloc[-1] > ma20.iloc[-2], ma30.iloc[-1] > ma30.iloc[-2],
            dif.iloc[-1] > dif.iloc[-2]]
    up = sum(bool(x) for x in dirs)
    score = up / 5
    st = ("强势向上" if up == 5 else "向上" if up == 4 else "纠缠" if up in (2, 3)
          else "向下" if up == 1 else "弱势向下")
    return score, st, "".join("↑" if d else "↓" for d in dirs)


def avg_state(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return ("强势向上" if x >= .9 else "向上" if x >= .7 else "纠缠" if x >= .3
            else "向下" if x >= .1 else "弱势向下")


def parse_kline(txt, has_sym):
    """westock markdown -> DataFrame(date, close) or dict[sym]->Series"""
    rows = {}
    for ln in txt.splitlines():
        if not ln.strip().startswith("|"):
            continue
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if has_sym:
            if len(c) >= 5 and re.match(r"^(sh|sz|bj)\d{6}$", c[0]):
                try:
                    rows.setdefault(c[0], {})[c[1]] = float(c[3])
                except Exception:
                    pass
        else:
            if len(c) >= 4 and re.match(r"^\d{4}-\d{2}-\d{2}$", c[0]):
                try:
                    rows.setdefault("_s", {})[c[0]] = float(c[2])
                except Exception:
                    pass
    return {k: pd.Series(v).sort_index() for k, v in rows.items()}


def main():
    # ---- 1) 9 大指数 月/周/日 ----
    syms = ",".join(IDX.values())
    res = {}
    for per, key in (("month", "L"), ("week", "M"), ("day", "S")):
        txt = sh(f"kline {syms} --period {per} --limit 120")
        res[key] = parse_kline(txt, has_sym=True)
        print(f"[{key}] 指数数据 {len(res[key])} 个", flush=True)

    rows = []
    for nm, sym in IDX.items():
        sL, stL, dL = power_state(res["L"].get(sym))
        sM, stM, dM = power_state(res["M"].get(sym))
        sS, stS, dS = power_state(res["S"].get(sym))
        rows.append({"指数": nm, "长期": stL, "长明细": dL, "长分": sL,
                     "中期": stM, "中明细": dM, "中分": sM,
                     "短期": stS, "短明细": dS, "短分": sS})
    R = pd.DataFrame(rows)
    L_ = R["长分"].dropna().mean(); M_ = R["中分"].dropna().mean(); S_ = R["短分"].dropna().mean()

    # ---- 2) 全主板日线 -> 宽度/情绪 ----
    pool = []
    fp = os.path.join(ROOT, "all_mainboard.csv")
    if os.path.exists(fp):
        for ln in open(fp, encoding="utf-8-sig"):
            p = ln.strip().split(",")
            if len(p) >= 2 and re.match(r"^\d{6}$", p[0].strip()):
                code = p[0].strip()
                if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
                    up = p[1].strip().upper().replace(" ", "")
                    if ("ST" in up) or ("PT" in up) or ("退" in p[1]):
                        continue
                    pool.append(("sh" if code.startswith("6") else "sz") + code)
    print(f"[宽度] 主板池 {len(pool)} 只", flush=True)
    dd = []
    B = 100
    for i in range(0, len(pool), B):
        # 前复权：用于均线位置与涨跌家数（趋势口径）
        txt = sh(f"kline {','.join(pool[i:i+B])} --period day --limit 260 --fq qfq")
        r = parse_kline(txt, has_sym=True)
        for c, s in r.items():
            if len(s) >= 250:
                dd.append({"code": c, "last": s.iloc[-1], "prev": s.iloc[-2],
                           "ma20": s.iloc[-20:].mean(), "ma60": s.iloc[-60:].mean(),
                           "ma250": s.iloc[-250:].mean()})
        if (i // B + 1) % 8 == 0:
            print(f"  宽度批{i//B+1} 累计{len(dd)}", flush=True)
    # 涨跌停判定：前复权口径（最新段=实际价，且除权日按除权后基准计价，与交易所涨停口径一致）
    S = pd.DataFrame(dd)
    if len(S) == 0:
        raise SystemExit("宽度数据为空")
    up_ratio = float((S["last"] > S["prev"]).mean())
    above20 = float((S["last"] > S["ma20"]).mean())
    above60 = float((S["last"] > S["ma60"]).mean())
    above250 = float((S["last"] > S["ma250"]).mean())
    chg = S["last"] / S["prev"] - 1
    nzt = int((chg >= 0.098).sum()); ndt = int((chg <= -0.098).sum())
    last_date = datetime.date.today().strftime("%Y%m%d")

    width_score = (above250 > .5) * .4 + (above60 > .5) * .3 + (above20 > .5) * .2 + (up_ratio > .5) * .1
    emo_score = min(1.0, nzt / 60.0) * .7 + up_ratio * .3
    comp = (0.45 * (0 if np.isnan(L_) else L_) + 0.20 * (0 if np.isnan(M_) else M_)
            + 0.10 * (0 if np.isnan(S_) else S_) + 0.125 * width_score + 0.125 * emo_score)

    if (not np.isnan(L_) and L_ >= .8) and (not np.isnan(M_) and M_ >= .6) and (not np.isnan(S_) and S_ >= .6):
        verdict = "牛市"
    elif (not np.isnan(M_) and M_ <= .4) and (not np.isnan(S_) and S_ <= .4) and (not np.isnan(L_) and L_ <= .5):
        verdict = "熊市"
    elif (not np.isnan(M_) and M_ <= .4) and (not np.isnan(S_) and S_ <= .4):
        verdict = "弱势（偏熊）"
    else:
        verdict = "震荡市"

    jr = {"date": last_date, "verdict": verdict, "score": round(float(comp), 3),
          "long": {"score": None if np.isnan(L_) else round(float(L_), 3), "state": avg_state(L_)},
          "mid": {"score": None if np.isnan(M_) else round(float(M_), 3), "state": avg_state(M_)},
          "short": {"score": None if np.isnan(S_) else round(float(S_), 3), "state": avg_state(S_)},
          "width": {"above250": round(above250, 3), "above60": round(above60, 3),
                    "above20": round(above20, 3), "up_ratio": round(up_ratio, 3)},
          "emotion": {"limit_up": nzt, "limit_down": ndt},
          "indices": R.to_dict("records"), "n_stocks": len(S)}
    json.dump(jr, open(os.path.join(ROOT, "market_regime_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    L = [f"# 当日市场状态综合判定 · {last_date}", "",
         f"## 结论：**{verdict}**（综合分 {comp:.2f}）", "",
         "| 力量/维度 | 分值 | 状态 |", "|---|---|---|",
         f"| 长期力量（月线·9大指数） | {L_:.2f} | {avg_state(L_)} |",
         f"| 中期力量（周线·9大指数） | {M_:.2f} | {avg_state(M_)} |",
         f"| 短期力量（日线·9大指数） | {S_:.2f} | {avg_state(S_)} |",
         f"| 市场宽度 | {width_score:.2f} | 年线{above250*100:.1f}% / MA60 {above60*100:.1f}% / MA20 {above20*100:.1f}% |",
         f"| 情绪 | {emo_score:.2f} | 涨停{nzt} / 跌停{ndt} / 上涨占比{up_ratio*100:.1f}% |", "",
         "## 9 大指数三级别力量", "",
         "| 指数 | 长期(月) | 方向 | 中期(周) | 方向 | 短期(日) | 方向 |", "|---|---|---|---|---|---|---|"]
    for r in R.itertuples():
        L.append(f"| {r.指数} | {r.长期} | {r.长明细} | {r.中期} | {r.中明细} | {r.短期} | {r.短明细} |")
    L.append("")
    L.append("> 方向明细顺序：MA5·MA10·MA20·MA30·DIF")
    if "牛" in verdict:
        L.append("\n**操作**：月线体系具备开仓条件，可顺势持仓（板块牛市 + Q3/Q4）。")
    elif "熊" in verdict or "弱势" in verdict:
        L.append("\n**操作**：空仓/极轻仓；月线体系无开仓条件。")
    else:
        L.append("\n**操作**：降仓、只做题材短线，等三级别力量共振向上。")
    txt = "\n".join(L)
    open(os.path.join(OUTD, f"市场状态判定_{last_date}.md"), "w", encoding="utf-8").write(txt)
    open(os.path.join(ROOT, "market_regime_latest.md"), "w", encoding="utf-8").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
