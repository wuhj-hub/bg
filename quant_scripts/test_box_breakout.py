#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_box_breakout.py —— 箱体突破有效性三条件单元测试（《全球第一炒股笔录》体系）
运行：python3 test_box_breakout.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fish_body_enhanced import box_breakout_valid

def mk_row(close, high, low, vol, date):
    return {"date": date, "last": close, "high": high, "low": low, "volume": vol}

def synth_case(break_vol_ratio, pullback_break=False, brk_last=False):
    """构造合成K线：43根箱体(10.0~10.9) + 突破日 + (可选回踩日)"""
    rows = []
    for i in range(43):
        c = 10.0 + (i % 10) * 0.1
        rows.append(mk_row(round(c, 2), round(c + 0.2, 2), round(c - 0.2, 2), 1000, f"2025-12-{(i % 28) + 1:02d}"))
    rows.append(mk_row(11.3, 11.5, 10.9, 1000 * break_vol_ratio, "2026-02-02"))
    if brk_last:
        rows.append(mk_row(10.7, 10.9, 10.5, 800, "2026-02-01"))
        return list(reversed(rows))
    if pullback_break:
        rows.append(mk_row(10.4, 10.6, 10.3, 600, "2026-02-03"))   # 收盘回落箱体内部=诱多
    else:
        rows.append(mk_row(11.1, 11.2, 10.95, 600, "2026-02-03"))  # 回踩守住箱顶
    return list(reversed(rows))

def test_all():
    r1 = box_breakout_valid(synth_case(2.0, pullback_break=False))
    assert r1["valid"] is True, f"用例1应有效: {r1}"
    print("✅ 用例1 放量突破+回踩守住 → 有效")

    r2 = box_breakout_valid(synth_case(1.2, pullback_break=False))
    assert r2["valid"] is False and "量能" in r2["reason"], f"用例2应无效(量能): {r2}"
    print("✅ 用例2 无量突破(1.2倍) → 量能不足无效")

    r3 = box_breakout_valid(synth_case(2.0, pullback_break=True))
    assert r3["valid"] is False and "诱多" in r3["reason"], f"用例3应无效(回踩破): {r3}"
    print("✅ 用例3 突破后回落箱体 → 诱多剔除")

    r4 = box_breakout_valid(synth_case(2.0, brk_last=True))
    assert r4["valid"] is True and r4["checks"]["pullback_state"] == "pending", f"用例4应有效(待确认): {r4}"
    print("✅ 用例4 突破日为最新 → 待回踩确认(不判无效)")

    rows = []
    for i in range(20):
        c = 30.0 + i * 0.5
        rows.append(mk_row(round(c, 2), round(c + 1, 2), round(c - 1, 2), 1000, f"2025-11-{(i % 30) + 1:02d}"))
    for i in range(43):
        c = 100.0 + (i % 10) * 1.0
        rows.append(mk_row(round(c, 2), round(c + 2, 2), round(c - 2, 2), 1000, f"2025-12-{(i % 28) + 1:02d}"))
    rows.append(mk_row(112.0, 114.0, 110.0, 3000, "2026-02-02"))
    rows.append(mk_row(111.0, 112.0, 110.5, 800, "2026-02-03"))
    r5 = box_breakout_valid(list(reversed(rows)))
    assert r5["valid"] is False and r5["checks"]["position"] is False, f"用例5应无效(位置): {r5}"
    print("✅ 用例5 低位大涨后高位盘整突破 → 位置过高无效")

    print("\n🎉 全部5个单元测试通过：量能/回踩/位置/待确认 四路径逻辑正确")

if __name__ == "__main__":
    test_all()
