#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trade_guard.py —— 交易防护层 v1.0（八维计分卡启发四项）
========================================================
① ATR动态止损  — 2×ATR(14)自适应止损线（替代固定-5%）
② 盈亏比门槛   — (目标位-现价)/(现价-止损) ≥2 才可执行
③ 牛熊动态参数 — 按市场状态(猛兽评分/双弦)调整信号档位
④ 离场计分卡   — 月线MA6/日线MA20/MACD死叉/ATR破位 综合计分

数据：日线K线(ATR/MACD/MA20) + 月线(MA6/前高目标位)
用法：python3 trade_guard.py --check sh603259
"""
import subprocess, sys, os, re, json

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_kline(txt):
    """日线/月线K线解析（升序），含open/high/low/close/volume"""
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or "---" in parts[0]:
            continue
        if len(parts) >= 6:
            try:
                di = header.index("date")
                row = {"date": parts[di]}
                for key in ("open", "last", "high", "low", "volume"):
                    if key in header:
                        row[key] = float(parts[header.index(key)])
                if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                    rows.append(row)
            except (ValueError, IndexError):
                pass
    rows.sort(key=lambda r: r["date"])
    return rows

def fetch_kline(code, period="day", limit=40):
    import time
    for _ in range(5):
        txt = run(["kline", code, "--period", period, "--limit", str(limit)])
        rows = parse_kline(txt)
        if rows:
            return rows
        time.sleep(1.5)
    return []

# ═══════ ① ATR动态止损 ═══════
def calc_atr(rows, period=14):
    """ATR(14)：True Range 的 Wilder 平滑。返回最新ATR值"""
    if len(rows) < period + 1:
        return None
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i]["high"], rows[i]["low"], rows[i-1]["last"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    # Wilder平滑: 首个为简单均值，后续递推
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr

def atr_stop(rows, mult=2.0):
    """ATR止损线 = 最新收盘 - mult×ATR"""
    if len(rows) < 15:
        return None, None
    atr = calc_atr(rows)
    if atr is None:
        return None, None
    close = rows[-1]["last"]
    return close - mult * atr, atr

# ═══════ ② 盈亏比门槛 ═══════
def calc_risk_reward(month_rows, day_rows, mult=2.0):
    """盈亏比 = (目标位-现价) / (现价-止损位)
    目标位 = 月线前12月最高价（不含当月，突破目标）；创新高时按现价×1.08保底空间"""
    if len(day_rows) < 15 or len(month_rows) < 3:
        return None, None, None, None
    cur = day_rows[-1]["last"]
    stop, atr = atr_stop(day_rows, mult)
    if stop is None or stop >= cur:
        return None, None, None, None
    prev_rows = month_rows[:-1] if len(month_rows) > 1 else month_rows  # 不含当月
    prev_high = max(r["high"] for r in prev_rows[-12:]) if prev_rows else cur
    target = max(prev_high, cur * 1.08)  # 创新高标的保底8%空间
    reward = target - cur
    risk = cur - stop
    rr = reward / risk if risk > 0 else None
    return rr, target, stop, atr

# ═══════ ③ 牛熊动态参数 ═══════
def market_regime(beast_score=None, sx_temp=None, gate_open=None):
    """市场档位：偏暖(加码)/震荡(标准)/危险(防守)
    输入：猛兽安全评分、双弦温度、门控。缺失时按中性处理"""
    score = beast_score if beast_score is not None else 50
    temp = sx_temp if sx_temp is not None else 50
    if score >= 60 or (temp >= 55 and gate_open):
        return "偏暖", "加码档：信号权重×1.2，仓位上限60%"
    if score < 40 or temp < 40:
        return "危险", "防守档：信号降级为观察，仓位上限30%"
    return "震荡", "标准档：信号正常，仓位上限50%"

# ═══════ ④ 离场计分卡 ═══════
def exit_score(month_rows, day_rows, mult=2.0):
    """离场计分：≤-2 强制离场；-1 减仓；0 持有
    -2: 月线收盘<MA6（大周期破位）
    -2: 日线收盘<ATR止损线（强制）
    -1: 日线收盘<MA20（中期走弱）
    -1: 日线MACD死叉（动能转弱）"""
    score = 0
    reasons = []
    # 月线MA6
    if len(month_rows) >= 7:
        closes = [r["last"] for r in month_rows]
        ma6 = sum(closes[-6:]) / 6
        if closes[-1] < ma6:
            score -= 2
            reasons.append("月线破MA6(-2)")
    # ATR止损线
    if len(day_rows) >= 15:
        stop, atr = atr_stop(day_rows, mult)
        if stop and day_rows[-1]["last"] < stop:
            score -= 2
            reasons.append("ATR止损破位(-2)")
    # 日线MA20
    if len(day_rows) >= 21:
        closes = [r["last"] for r in day_rows]
        ma20 = sum(closes[-20:]) / 20
        if closes[-1] < ma20:
            score -= 1
            reasons.append("日线破MA20(-1)")
    # 日线MACD死叉（简化: EMA12<EMA26 视为死叉状态）
    if len(day_rows) >= 30:
        closes = [r["last"] for r in day_rows]
        ema12 = closes[-1]
        ema26 = closes[-1]
        k = 2 / 13
        for c in closes[-30:]:
            ema12 = c * k + ema12 * (1 - k)
        k26 = 2 / 27
        for c in closes[-30:]:
            ema26 = c * k26 + ema26 * (1 - k26)
        if ema12 < ema26:
            score -= 1
            reasons.append("MACD死叉(-1)")
    # 判定
    if score <= -2:
        action = "🔴 强制离场"
    elif score == -1:
        action = "🟡 减仓/收紧"
    else:
        action = "🟢 持有"
    return score, action, reasons

def check_stock(code):
    """综合交易防护检查"""
    day_rows = fetch_kline(code, "day", 40)
    month_rows = fetch_kline(code, "month", 15)
    if not day_rows or not month_rows:
        return {"code": code, "ok": False, "err": "K线获取失败"}
    cur = day_rows[-1]["last"]
    rr, target, stop, atr = calc_risk_reward(month_rows, day_rows)
    escore, eaction, ereasons = exit_score(month_rows, day_rows)
    out = {
        "code": code, "ok": True, "price": round(cur, 2),
        "atr": round(atr, 3) if atr else None,
        "stop": round(stop, 2) if stop else None,
        "target": round(target, 2) if target else None,
        "rr": round(rr, 2) if rr else None,
        "rr_pass": rr is not None and rr >= 2.0,
        "exit_score": escore, "exit_action": eaction, "exit_reasons": ereasons,
    }
    return out

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        r = check_stock(sys.argv[2])
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif len(sys.argv) >= 3 and sys.argv[1] == "--scan":
        for c in sys.argv[2].split(","):
            r = check_stock(c.strip())
            if r["ok"]:
                print(f"{r['code']} 现价{r['price']} ATR{r['atr']} 止损{r['stop']} 目标{r['target']} "
                      f"盈亏比{r['rr']}{'✅' if r['rr_pass'] else '❌'} 离场{r['exit_score']}({r['exit_action']})")
    else:
        print(__doc__)
