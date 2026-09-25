#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trade_day_check.py —— A股交易日判断（供 workflow 节假日守卫使用，2026-09-25）

背景：cron-job.org 只能按"周一至周五"周期触发，无法感知 A股节假日
（中秋 9/25-9/27、国庆 10/1-10/7 等休市日仍会触发 → 空跑白耗算力）。

判断方法（基于真实数据，自动适应临时休市/调休，不依赖人工维护日历）：
  1) 主：westock kline sh000001 --limit 1 → 最新K线日期 == 今天 → 交易日
  2) 备：腾讯 qt.gtimg.cn 实时快照的时间戳日期 == 今天 → 交易日
  非交易日（周末/节假日）两种方法都会得到"最新日期 != 今天" → 返回 0

用法：
  python3 trade_day_check.py                 # 退出码 0=交易日 1=非交易日
  python3 trade_day_check.py --quiet         # 仅退出码
  python3 trade_day_check.py --github-output # 同时写入 GITHUB_OUTPUT: is_trade_day=0/1
"""
import os, re, sys, json, argparse, subprocess, urllib.request
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))
TODAY = datetime.now(BJ).strftime("%Y-%m-%d")


def log(*a):
    print(*a, flush=True)


def via_westock():
    """最新日K日期 == 今天 → 交易日"""
    for _ in range(3):
        try:
            r = subprocess.run(["npx", "-y", "westock-data-skillhub@1.0.3",
                                "kline", "sh000001", "--period", "day", "--limit", "2"],
                               capture_output=True, text=True, timeout=120)
            out = r.stdout or ""
            dates = re.findall(r"(\d{4}-\d{2}-\d{2})", out)
            if dates:
                return max(dates), "westock"
        except Exception:
            pass
    return None, "westock-fail"


def via_tencent():
    """qt.gtimg.cn 快照里的日期字段（第31位 YYYYMMDDHHMMSS）"""
    try:
        req = urllib.request.Request("http://qt.gtimg.cn/q=sh000001",
                                     headers={"User-Agent": "Mozilla/5.0"})
        txt = urllib.request.urlopen(req, timeout=15).read().decode("gbk", errors="replace")
        # 时间戳为 YYYYMMDDHHMMSS（快照时间），校验年份合理
        for m in re.finditer(r"(20\d{2})(\d{2})(\d{2})\d{6}", txt):
            y, mo, dd = m.group(1), m.group(2), m.group(3)
            if "01" <= mo <= "12" and "01" <= dd <= "31":
                return f"{y}-{mo}-{dd}", "tencent"
    except Exception:
        pass
    return None, "tencent-fail"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--github-output", action="store_true")
    a = ap.parse_args()

    # 周末快速判断（无需网络）
    wd = datetime.now(BJ).weekday()
    if wd >= 5:
        is_td, date, src = False, None, "weekend"
    else:
        # 优先腾讯（纯 HTTP，无需 node，约 1s）；失败再退 westock（需 npx）
        date, src = via_tencent()
        if not date:
            date, src = via_westock()
        if not date:
            # 数据源不可用：保守放行（宁可多跑一次，不可漏跑）
            is_td, src = True, src + "|assume-trade"
        else:
            is_td = (date == TODAY)

    if not a.quiet:
        log(f"[trade_day_check] {TODAY} → {'交易日 ✅' if is_td else '非交易日 ⏭️'} "
            f"(判据: {src}, 最新行情日: {date})")
    if a.github_output:
        p = os.environ.get("GITHUB_OUTPUT")
        if p:
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"is_trade_day={1 if is_td else 0}\n")
    sys.exit(0 if is_td else 1)


if __name__ == "__main__":
    main()
