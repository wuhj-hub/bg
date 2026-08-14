#!/usr/bin/env python3
"""
zuot_kuangren.py v2 —— 做T狂人策略引擎（westock数据源版）
=====================================================
提炼自今日头条「做T狂人」《将做T进行到底》系列核心方法：
  1. 走势两分法：均线之上=上涨、之下=下跌（简化判断）
  2. 完全分类：均线上行→正T为主 / 横走→正反T / 下行→反T为主
     （物极必反：K线远离均线时变盘概率最高）
  3. 买卖信号：远离均线 + MACD柱不再伸长（背驰）
  4. 分时层：当日分时均价线(VWAP)方向 + 现价偏离 → 日内做T点
  5. 资金管理：分份操作、底仓不动、弱市降低差价预期

数据源: westock (npx westock-data-skillhub) —— 日线 + 当日分时
用法: python3 zuot_kuangren.py [代码...]
示例: python3 zuot_kuangren.py sh600863 sh603669 sz000725 sz000009
=====================================================
"""
import subprocess, sys, re, time
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

# ============================================================
# 数据获取
# ============================================================
def cli(cmd, timeout=90):
    full = WESTOCK + cmd.split()
    for attempt in range(5):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            out = r.stdout or ""
            if out.strip() and "执行失败" not in out and "SKILL_0" not in out:
                return out
        except Exception:
            pass
        time.sleep(2)
    return ""

def fetch_daily(symbol, limit=70):
    """westock日线 → [{date,open,close,high,low,vol}] 时间升序"""
    out = cli(f"kline {symbol} --period day --limit {limit} --fq qfq")
    rows = []
    for ln in out.splitlines():
        s = ln.strip()
        if not s.startswith("|") or "date" in s or "---" in s:
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 6 and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            try:
                rows.append({"date": parts[0], "open": float(parts[1]), "close": float(parts[2]),
                             "high": float(parts[3]), "low": float(parts[4]), "vol": float(parts[5])})
            except ValueError:
                continue
    rows.sort(key=lambda r: r["date"])
    return rows

def fetch_minute(symbol):
    """westock当日分时 → [{time, price, vol累计}]"""
    out = cli(f"minute {symbol}")
    rows = []
    for ln in out.splitlines():
        s = ln.strip()
        if not s.startswith("|") or "time" in s or "---" in s:
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        # 列序: code | time | price | volume | amount
        if len(parts) >= 5 and re.match(r"\d{4}", parts[1]):
            try:
                rows.append({"time": parts[1], "price": float(parts[2]),
                             "vol": float(parts[3]), "amount": float(parts[4])})
            except ValueError:
                continue
    return rows

# ============================================================
# 技术计算
# ============================================================
def ema_series(vals, n):
    out, k = [], 2 / (n + 1)
    prev = vals[0]
    for v in vals:
        prev = v if not out else v * k + prev * (1 - k)
        out.append(prev)
    return out

def macd_series(closes, fast=12, slow=26, signal=9):
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    dif = [f - s for f, s in zip(ef, es)]
    dea = ema_series(dif, signal)
    hist = [2 * (d - e) for d, e in zip(dif, dea)]
    return dif, dea, hist

# ============================================================
# 日线层：做T狂人波段法（MA两分法 + 完全分类 + 乖离）
# ============================================================
def analyze_daily(symbol, name):
    bars = fetch_daily(symbol)
    if len(bars) < 30:
        return None, "日线数据不足"
    closes = [b["close"] for b in bars]
    cur = bars[-1]["close"]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
    # 均线方向（完全分类）
    def direction(vals, n):
        if len(vals) < n + 3:
            return "横走"
        cur_v, prev_v = vals[-1], vals[-(n + 1)]
        slope = (cur_v - prev_v) / prev_v * 100
        return "上行" if slope > 0.5 else ("下行" if slope < -0.5 else "横走")
    ma5_dir = direction(closes, 5)
    ma20_dir = direction(closes, 20)
    # 乖离率（物极必反）
    bias5 = (cur - ma5) / ma5 * 100
    bias20 = (cur - ma20) / ma20 * 100
    # MACD 背驰
    dif, dea, hist = macd_series(closes)
    h_now, h_prev, h_prev2 = hist[-1], hist[-2], hist[-3]
    macd_state = ""
    if h_now > 0 and h_now < h_prev:
        macd_state = "红柱缩短(顶背离迹象⚠️)"
    elif h_now < 0 and h_now > h_prev:
        macd_state = "绿柱缩短(底背离迹象✅)"
    else:
        macd_state = f"柱{'红' if h_now > 0 else '绿'}伸长中"
    # 综合分类（两分法）
    if cur > ma5 and ma5_dir == "上行":
        regime = "强势(线上)"
        action = "以正T/持股为主；远离均线(乖离>5%)可反T高抛"
    elif cur < ma5 and ma5_dir == "下行":
        regime = "弱势(线下)"
        action = "以反T/减仓为主；远离均线下方(乖离<-5%)可正T低吸"
    else:
        regime = "震荡(纠缠)"
        action = "正T/反T均可；远离均线时效果最佳"
    return {
        "close": cur, "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "ma5_dir": ma5_dir, "ma20_dir": ma20_dir, "bias5": bias5, "bias20": bias20,
        "macd_state": macd_state, "regime": regime, "action": action,
    }, None

# ============================================================
# 分时层：当日做T实战（VWAP均价线 + 偏离 + 量价）
# ============================================================
def analyze_minute(symbol, name):
    rows = fetch_minute(symbol)
    if len(rows) < 10:
        return None, "分时数据不可用"
    # VWAP 序列
    vwap_seq = []
    for i, r in enumerate(rows):
        # amount=元, vol=累计手(×100股)，均价=amount/(vol*100)
        vwap_seq.append(r["amount"] / (r["vol"] * 100) if r["vol"] > 0 else r["price"])
    cur_price = rows[-1]["price"]
    vwap_now = vwap_seq[-1]
    # VWAP 方向（比较近期）
    if len(vwap_seq) >= 30:
        vwap_dir = ("上行" if vwap_seq[-1] > vwap_seq[-30] * 1.001
                    else "下行" if vwap_seq[-1] < vwap_seq[-30] * 0.999 else "横走")
    else:
        vwap_dir = "数据不足"
    dev = (cur_price - vwap_now) / vwap_now * 100
    # 当日高低点
    prices = [r["price"] for r in rows]
    hi, lo = max(prices), min(prices)
    hi_t = rows[prices.index(hi)]["time"]
    lo_t = rows[prices.index(lo)]["time"]
    # 尾盘量能
    vol_total = rows[-1]["vol"]
    # 建议
    if dev > 1.2:
        tip = "现价远离均价线上方 → 反T高抛区（物极必反）"
    elif dev < -1.2:
        tip = "现价远离均价线下方 → 正T低吸区（物极必反）"
    elif cur_price > vwap_now:
        tip = "现价在均价线上方 → 偏多，回踩均价线不破可正T"
    else:
        tip = "现价在均价线下方 → 偏空，反抽均价线可反T"
    return {
        "price": cur_price, "vwap": vwap_now, "vwap_dir": vwap_dir,
        "dev": dev, "high": hi, "high_t": hi_t, "low": lo, "low_t": lo_t,
        "vol": vol_total, "tip": tip,
    }, None

# ============================================================
NAMES = {"sh600863": "华能蒙电", "sh603669": "灵康药业", "sz000725": "京东方A",
         "sz000009": "中国宝安", "sh600797": "浙大网新", "sz000839": "国安股份"}

def main():
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["sh600863"]
    print(f"⏰ 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据源: westock")
    for s in symbols:
        nm = NAMES.get(s, "")
        d_res, d_err = analyze_daily(s, nm)
        print(f"\n{'='*64}")
        print(f"📊 {s} {nm} · 做T狂人策略分析")
        print(f"{'='*64}")
        if d_err:
            print(f"  ❌ 日线: {d_err}")
        else:
            print(f"【日线层·波段法】")
            print(f"  现价 {d_res['close']:.2f} | MA5 {d_res['ma5']:.2f} | MA10 {d_res['ma10']:.2f} | MA20 {d_res['ma20']:.2f}"
                  + (f" | MA60 {d_res['ma60']:.2f}" if d_res['ma60'] else ""))
            print(f"  MA5方向: {d_res['ma5_dir']} | MA20方向: {d_res['ma20_dir']}")
            print(f"  乖离: MA5 {d_res['bias5']:+.1f}% | MA20 {d_res['bias20']:+.1f}% （|乖离|>5%=高概率变盘区）")
            print(f"  MACD: {d_res['macd_state']}")
            print(f"  定性: {d_res['regime']} → {d_res['action']}")
        m_res, m_err = analyze_minute(s, nm)
        if m_err:
            print(f"  ❌ 分时: {m_err}")
        else:
            print(f"【分时层·当日做T】")
            print(f"  现价 {m_res['price']:.2f} | 均价线(VWAP) {m_res['vwap']:.2f} | 偏离 {m_res['dev']:+.2f}%")
            print(f"  VWAP方向: {m_res['vwap_dir']} | 当日高 {m_res['high']:.2f}@{m_res['high_t']} / 低 {m_res['low']:.2f}@{m_res['low_t']}")
            print(f"  💡 {m_res['tip']}")
        time.sleep(2)
    print(f"\n⚠️ 仅供学习参考，不构成投资建议。做T需结合大盘/板块共振与盘口灵活把握。")

if __name__ == "__main__":
    main()
