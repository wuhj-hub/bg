#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rps.py —— 横截面 RPS 相对强度（西湖《寻找交易的圣杯：RPS高于一切》）
============================================================
RPS(N) = 全市场 N 日涨幅排名百分位 = (1 - rank / total) * 100
  · rank=1 表示涨幅最高 → RPS 接近 100
  · 西湖口径：RPS>85/87/90 为强势；两红/三红为多周期共振

与 RSV2 的区别：
  RSV2(相对基准) = 个股/基准指数 的时序归一化位置（纵向）
  RPS(横截面)   = 个股在全市场中的涨幅名次（横向）
  → 前者回答"比自己过去强吗"，后者回答"比全市场多少股票强"

用法:
  python3 rps.py --top 30 --json outputs/rps_latest.json
  python3 rps.py --universe-file all_mainboard.csv
============================================================
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import xihu_rsv as xr   # 复用猛兽数据层（cli / fetch / read_universe / compute_cross_rps）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe-file", default="all_mainboard.csv")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--json", default="outputs/rps_latest.json")
    args = ap.parse_args()

    uni = Path(args.universe_file)
    if not uni.exists():
        print(f"[ERR] 未找到 {args.universe_file}"); sys.exit(1)
    pool = xr.read_universe(uni)
    codes = list(pool)
    print(f"[RPS] 全市场主板非ST {len(codes)} 只 | 周期 {xr.N_LIST} | 基准无关（横截面）")

    day = xr.fetch(codes, "day", max(args.limit, 300), workers=args.workers)
    print(f"  K线返回 {len(day)}/{len(codes)}")
    rps = xr.compute_cross_rps(day, codes, xr.N_LIST)

    rows = []
    for c in codes:
        if c in rps:
            rows.append({"code": c, "name": pool[c],
                         **{f"rps{n}": round(rps[c][n], 1) for n in xr.N_LIST}})
    rows.sort(key=lambda r: r["rps250"], reverse=True)

    print(f"\n{'代码':<10}{'名称':<9}{'RPS50':>7}{'RPS144':>7}{'RPS250':>7}  三红")
    print("-" * 52)
    for r in rows[:args.top]:
        red = sum(1 for n in xr.N_LIST if r[f"rps{n}"] >= 90)
        print(f"{r['code']:<10}{(r['name'] or '')[:8]:<9}{r['rps50']:>7}{r['rps144']:>7}{r['rps250']:>7}  {'🔥'*red}")
    print(f"\n共 {len(rows)} 只 | 三周期均≥90: {sum(1 for r in rows if all(r[f'rps{n}']>=90 for n in xr.N_LIST))} 只")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        json.dump({"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "n_list": xr.N_LIST, "total": len(rows), "data": rows},
                  open(args.json, "w"), ensure_ascii=False, indent=2)
        print(f"[OK] JSON → {args.json}")


if __name__ == "__main__":
    main()
