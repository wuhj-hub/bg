#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
signal_risk_card.py —— 信号级风控卡（《专业投机原理》L5 落地）
==============================================================
给每个交易信号强制计算：
  - 止损位  = 收盘 - 2×ATR(14)（鳄鱼法则：触发即砍）
  - 目标位  = 月线前12月高（创新高标的保底 ×1.08）
  - 盈亏比  = (目标位-现价) / (现价-止损位)，<2 不达标
  - 建议仓位% = 账户风险2% ÷ (止损幅度/现价)（单笔风险封顶）
  - 状态：✅可执行 / ⚠️盈亏比不足 / ⛔无止损不入场

复用 trade_guard.calc_atr / atr_stop / calc_risk_reward
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trade_guard import calc_atr, atr_stop, calc_risk_reward, fetch_kline

ACCOUNT_RISK_PCT = 2.0   # 单笔最大账户风险（斯波朗迪：1%-2%）
MIN_RR = 2.0             # 最小盈亏比门槛
MAX_POS_PCT = 30.0       # 单票仓位上限


def risk_card(code, month_rows=None, day_rows=None, name=""):
    """计算单只信号的风控卡。
    month_rows: 月线K线行（升序，含 high）；day_rows: 日线K线行（升序，≥15根，含 last）
    返回 dict（数据不足时 status=⛔无止损不入场）
    """
    try:
        if not day_rows or len(day_rows) < 15:
            return {"code": code, "name": name, "status": "⛔无止损不入场",
                    "price": 0, "stop": None, "target": None, "rr": None,
                    "pos_pct": 0, "reason": "日线K线不足(15根)"}
        cur = day_rows[-1]["last"]
        if not month_rows or len(month_rows) < 3:
            # 月线不足：用日线前60日高 + 8%保底近似目标位
            rr, target, stop, atr = None, None, None, None
            stop, atr = atr_stop(day_rows)
            if stop and cur > stop:
                prev_high = max(r["high"] for r in day_rows[-60:])
                target = max(prev_high, cur * 1.08)
                reward = target - cur
                rr = reward / (cur - stop)
        else:
            rr, target, stop, atr = calc_risk_reward(month_rows, day_rows)
        if stop is None or stop <= 0 or cur <= stop:
            return {"code": code, "name": name, "status": "⛔无止损不入场",
                    "price": round(cur, 2), "stop": None, "target": None, "rr": None,
                    "pos_pct": 0, "reason": "止损位不可用（ATR异常或现价已破止损）"}
        risk_pct = (cur - stop) / cur * 100          # 止损幅度%
        pos_pct = round(ACCOUNT_RISK_PCT / (risk_pct / 100), 1) if risk_pct > 0 else 0
        pos_pct = min(pos_pct, MAX_POS_PCT)
        if rr is None or rr < MIN_RR:
            status = "⚠️盈亏比不足"
        else:
            status = "✅可执行"
        return {
            "code": code, "name": name, "status": status,
            "price": round(cur, 2),
            "stop": round(stop, 2),
            "target": round(target, 2) if target else None,
            "rr": round(rr, 2) if rr else None,
            "pos_pct": pos_pct,
            "reason": f"止损{stop:.2f}(-{risk_pct:.1f}%) 目标{target:.2f} 盈亏比{rr:.2f} 建议仓位{pos_pct}%",
        }
    except Exception as e:
        return {"code": code, "name": name, "status": "⛔计算异常",
                "price": 0, "stop": None, "target": None, "rr": None,
                "pos_pct": 0, "reason": str(e)[:60]}


def risk_card_batch(cards_input, concurrency=4):
    """批量风控卡。cards_input: [{code, name}] 或 [{code, name, day_rows, month_rows}]
    无预置数据时自动 fetch（westock 日线40根+月线14根）
    """
    from concurrent.futures import ThreadPoolExecutor
    def _one(item):
        code = item["code"]
        name = item.get("name", "")
        day = item.get("day_rows") or fetch_kline(code, "day", 40)
        month = item.get("month_rows") or fetch_kline(code, "month", 14)
        return risk_card(code, month, day, name)
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        return list(ex.map(_one, cards_input))


if __name__ == "__main__":
    codes = sys.argv[1].split(",") if len(sys.argv) > 1 else ["sh600519"]
    cards = risk_card_batch([{"code": c, "name": c} for c in codes])
    for c in cards:
        print(f"{c['code']} {c['name']}: {c['status']} | {c['reason']}")
