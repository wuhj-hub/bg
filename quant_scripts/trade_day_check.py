#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trade_day_check.py —— A股交易日判断（交易日守卫，供 workflow 使用）

【2026-09-28 重构 · 修复盘前误判】
────────────────────────────────────────────────────────────
旧版缺陷（2026-09-25 引入）：
    判据 = 「最新行情日 == 今天 → 交易日」。
    该判据在**盘前（如 08:00）必然失效**——当日行情尚未产生，最新行情日永远
    等于上一交易日；只要今天与上一交易日不重合，就会把**交易日误判为非交易日**。
    典型：2026-09-28(周一，中秋假期后首个交易日)，最新行情日=09-24 → 被判"非
    交易日" → 盘前报告 premarket job 被 gate 跳过。且此错误对**每个交易日的盘前
    任务**都成立，属系统性漏跑。

新版判据（不依赖"当日是否已有行情"，盘前/盘中/盘后通用）：
    1) 周六/周日            → 非交易日
    2) 命中交易所休市表      → 非交易日
    3) 其余               → 交易日
    数据源不可用不再影响结论（去掉对 westock/腾讯行情的强依赖），判据确定、可预测。

维护方式：
    交易所每年 12 月发布次年休市安排（如 2026：证监办发〔2025〕130号）。
    届时把次年"工作日休市"日期加入 HOLIDAYS、把年份加入 COVERED_YEARS 即可
    （约 15 行/年）。未覆盖年份 → 非周末一律放行（宁多跑，不漏跑）。

用法：
    python3 trade_day_check.py                    # 退出码 0=交易日 1=非交易日
    python3 trade_day_check.py --quiet            # 仅退出码
    python3 trade_day_check.py --github-output    # 写 GITHUB_OUTPUT: is_trade_day=0/1
    python3 trade_day_check.py --date 2026-09-28  # 判定指定日期（测试用）
"""
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))

# ── 交易所年度休市安排（仅列"工作日休市"；周六周日由 weekday() 覆盖）──
# 数据来源：沪深北交易所年度休市公告
HOLIDAYS = {
    # ── 2026 年（证监办发〔2025〕130号）──
    "2026-01-01", "2026-01-02",                                              # 元旦 1/1-1/3
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    "2026-02-23",                                                            # 春节 2/15-2/23
    "2026-04-06",                                                            # 清明 4/4-4/6
    "2026-05-01", "2026-05-04", "2026-05-05",                                # 劳动 5/1-5/5
    "2026-06-19",                                                            # 端午 6/19-6/21
    "2026-09-25",                                                            # 中秋 9/25-9/27
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",    # 国庆 10/1-10/7
    # ── 2027 年：待交易所公布后补充 ──
}
COVERED_YEARS = {2026}


def log(*a):
    print(*a, flush=True)


def judge(dt):
    """返回 (is_trade_day: bool, reason: str)"""
    ymd = dt.strftime("%Y-%m-%d")
    if dt.weekday() >= 5:
        return False, "weekend(周末)"
    if ymd in HOLIDAYS:
        return False, "holiday(休市日)"
    if dt.year not in COVERED_YEARS:
        # 未覆盖年份：非周末一律放行（宁多跑一次，不可漏跑），并提示维护
        return True, f"uncovered-year {dt.year}(assume-trade, 请补充休市表)"
    return True, "workday(工作日)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--github-output", action="store_true")
    ap.add_argument("--date", default=None, help="判定指定日期 YYYY-MM-DD（默认今天，北京时）")
    a = ap.parse_args()

    if a.date:
        dt = datetime.strptime(a.date, "%Y-%m-%d").replace(tzinfo=BJ)
    else:
        dt = datetime.now(BJ)

    is_td, reason = judge(dt)

    if not a.quiet:
        log(f"[trade_day_check] {dt.strftime('%Y-%m-%d')} → "
            f"{'交易日 ✅' if is_td else '非交易日 ⏭️'} (判据: {reason})")

    if a.github_output:
        p = os.environ.get("GITHUB_OUTPUT")
        if p:
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"is_trade_day={1 if is_td else 0}\n")

    sys.exit(0 if is_td else 1)


if __name__ == "__main__":
    main()
