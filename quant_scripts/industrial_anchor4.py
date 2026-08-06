#!/usr/bin/env python3
"""产业锚定4·三季盈增寻锚选股公式"""
import warnings
warnings.filterwarnings("ignore")

MIN_REVENUE_GROWTH = 0.0
MIN_PROFIT_GROWTH = 0.0
REQUIRED_QUARTERS = 2
LOOKBACK_QUARTERS = 3


def _find_cum(df, year, month_day, col):
    target = "{}-{}".format(year, month_day)
    for i in range(len(df)):
        d = str(df.iloc[i].get("REPORT_DATE", ""))[:10]
        if d == target:
            return float(df.iloc[i].get(col, 0) or 0)
    return 0


def calc_quarterly_growth(code):
    result = {"code": code, "name": "", "score": 0, "qualify": False,
              "avg_rev_growth": 0, "avg_profit_growth": 0, "details": [], "error": ""}
    raw_code = code.replace("sh", "").replace("sz", "").replace("bj", "")
    market = "SH" if code.startswith("sh") else "SZ"
    symbol = "{}{}".format(market, raw_code)
    try:
        import akshare as ak
        df = ak.stock_profit_sheet_by_report_em(symbol=symbol)
    except Exception as e:
        result["error"] = "akshare fail: {}".format(e)
        return result
    if df is None or df.empty:
        result["error"] = "empty data"
        return result
    df = df.sort_values("REPORT_DATE", ascending=True).reset_index(drop=True)
    single_q = []
    for i in range(len(df)):
        row = df.iloc[i]
        rd = str(row.get("REPORT_DATE", ""))[:10]
        cum_rev = float(row.get("OPERATE_INCOME", 0) or 0)
        cum_profit = float(row.get("PARENT_NETPROFIT", 0) or 0)
        yr = rd[:4]
        if rd.endswith("03-31"):
            prev_rev, prev_profit = 0, 0
        elif rd.endswith("06-30"):
            prev_rev = _find_cum(df, yr, "03-31", "OPERATE_INCOME")
            prev_profit = _find_cum(df, yr, "03-31", "PARENT_NETPROFIT")
        elif rd.endswith("09-30"):
            prev_rev = _find_cum(df, yr, "06-30", "OPERATE_INCOME")
            prev_profit = _find_cum(df, yr, "06-30", "PARENT_NETPROFIT")
        elif rd.endswith("12-31"):
            prev_rev = _find_cum(df, yr, "09-30", "OPERATE_INCOME")
            prev_profit = _find_cum(df, yr, "09-30", "PARENT_NETPROFIT")
        else:
            continue
        q_rev = cum_rev - prev_rev
        q_profit = cum_profit - prev_profit
        if q_rev > 0:
            single_q.append({"date": rd, "year": yr, "qtype": rd[5:10],
                             "q_revenue": q_rev, "q_profit": q_profit})
    growth = []
    for q in single_q:
        ly = str(int(q["year"]) - 1)
        match = [x for x in single_q if x["year"] == ly and x["qtype"] == q["qtype"]]
        if match and match[0]["q_revenue"] > 0:
            rg = (q["q_revenue"] - match[0]["q_revenue"]) / match[0]["q_revenue"] * 100
            pg = (q["q_profit"] - match[0]["q_profit"]) / match[0]["q_profit"] * 100
        else:
            rg = pg = None
        growth.append({"date": q["date"], "revenue": round(q["q_revenue"]/1e8, 2),
                       "profit": round(q["q_profit"]/1e8, 2),
                       "rev_growth": round(rg, 2) if rg is not None else None,
                       "profit_growth": round(pg, 2) if pg is not None else None})
    result["details"] = growth
    recent = [g for g in growth if g["rev_growth"] is not None][-LOOKBACK_QUARTERS:]
    if not recent:
        return result
    qualified = sum(1 for g in recent if g["rev_growth"] >= MIN_REVENUE_GROWTH
                    and g["profit_growth"] >= MIN_PROFIT_GROWTH)
    avg_rev = sum(g["rev_growth"] for g in recent) / len(recent)
    avg_profit = sum(g["profit_growth"] for g in recent) / len(recent)
    result["avg_rev_growth"] = round(avg_rev, 2)
    result["avg_profit_growth"] = round(avg_profit, 2)
    result["qualify"] = qualified >= REQUIRED_QUARTERS
    score = 50
    if avg_rev > 0:
        score += min(avg_rev, 25)
    if avg_profit > 0:
        score += min(avg_profit, 25)
    result["score"] = round(min(score, 100), 0)
    return result
