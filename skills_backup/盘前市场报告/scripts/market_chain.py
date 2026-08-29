#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_chain.py — 领涨链条传导 + 三类行情策略矩阵（曾星智体系落地）
====================================================================
补强项1：领涨链条（领涨指数→领涨行业→领涨个股的传导）
补强项2：三类行情矩阵（牛市中继/震荡反弹/熊市反弹 → 仓位策略）

用法：
  python3 market_chain.py --date 2026-08-29 \
    --sx 47 --beast 46.7 --fish 45 [--width 82.5] [--style 情绪市]
  # 自动拉四指数日K判领涨指数；板块/个股从板块共振JSON或hot board

输出：Markdown 片段（盘前报告 ②行情类型 + ③领涨链条）
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

WESTOCK = "npx -y westock-data-skillhub@1.0.3"
INDICES = ["sh000001", "sz399001", "sz399006", "sh000688"]
INDEX_NAMES = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指", "sh000688": "科创50"}


def fetch_kline(codes, limit=25):
    """拉取指数日K，返回 {code: [(date, close), ...]} 升序"""
    r = subprocess.run([*WESTOCK.split(), "kline", ",".join(codes),
                        "--period", "day", "--limit", str(limit), "--fq", "qfq"],
                       capture_output=True, text=True, timeout=180)
    data = {}
    for line in r.stdout.split("\n"):
        m = re.match(r'\| (sh\d{6}|sz\d{6}) \| (\d{4}-\d{2}-\d{2}) \| [\d.]+ \| ([\d.]+)', line)
        if m:
            code, date, close = m.groups()
            data.setdefault(code, []).append((date, float(close)))
    for c in data:
        data[c].sort(key=lambda x: x[0])
    return data


def leading_index(data):
    """领涨指数：近5/10/20日涨幅最强的指数"""
    results = []
    for code, bars in data.items():
        if len(bars) < 21:
            continue
        closes = [b[1] for b in bars]
        r5 = (closes[-1] / closes[-6] - 1) * 100
        r10 = (closes[-1] / closes[-11] - 1) * 100
        r20 = (closes[-1] / closes[-21] - 1) * 100
        results.append((INDEX_NAMES.get(code, code), r5, r10, r20, (r5 + r10 + r20) / 3))
    results.sort(key=lambda x: -x[4])
    return results


def load_board_resonance():
    """尝试读板块共振 JSON（本地/仓库根）"""
    for path in ["outputs/板块共振_latest.json", "板块共振_latest.json",
                 "/sandbox/workspace/skills/盘前市场报告/scripts/outputs/板块共振_latest.json"]:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue
    return None


def fetch_hot_board():
    """westock hot board 拿板块涨幅榜"""
    r = subprocess.run([*WESTOCK.split(), "hot", "board", "--limit", "10"],
                       capture_output=True, text=True, timeout=120)
    boards = []
    for line in r.stdout.split("\n"):
        # hot board 格式: | index | level | symbol | rank | rankdelta | date | stock_type | name | zdf | zxj |
        m = re.match(r'\| \d+ \| \d+ \| pt[\w]+ \| \d+ \| -?\d+ \| [\d\- :]+ \| [\w-]+ \| ([^|]+) \| ([\d.]+) \|', line)
        if m:
            name, chg = m.group(1).strip(), float(m.group(2))
            boards.append((name, chg))
    return boards


def regime_type(sx, beast, fish, width=None):
    """三类行情矩阵（曾星智体系：牛市中继/震荡反弹/熊市反弹）"""
    vals = [v for v in (sx, beast, fish) if v is not None]
    avg = sum(vals) / len(vals) if vals else 50
    if avg >= 55 and (width is None or width >= 60):
        return "🐂 牛市中继（长期力量向上，可积极）", "60-100%", "主扫强势股/领涨龙头，回调低吸"
    if avg >= 55:
        return "🐂 牛市中继·边界（偏暖）", "50-70%", "谨慎乐观，等回踩确认"
    if avg >= 40:
        return "⚖️ 震荡反弹（力量冲突）", "30-50%", "精选领涨股，快进快出"
    return "🐻 熊市反弹（长期力量向下）", "≤20%或空仓", "回避为主，仅超跌反弹快进快出"


def render(date, sx, beast, fish, width, style):
    L = []
    # 行情类型
    rtype, pos, tactic = regime_type(sx, beast, fish, width)
    L.append(f"### 🧭 行情类型（曾星智三类矩阵）\n")
    L.append(f"> **{rtype}** ｜ 建议仓位 {pos} ｜ 策略：{tactic}\n")
    L.append(f"> 依据：三系统均值 {((sx or 0)+(beast or 0)+(fish or 0))/3:.0f}"
             f"（双弦{sx}/猛兽{beast}/鱼身{fish}）" + (f"｜ 宽度 {width}" if width else "") +
             (f"｜ 风格 {style}" if style else "") + "\n")
    # 领涨指数
    idx_data = fetch_kline(INDICES)
    if idx_data:
        ranks = leading_index(idx_data)
        L.append("**领涨指数传导**：")
        for name, r5, r10, r20, avg in ranks[:3]:
            L.append(f"- {name}：5日{r5:+.1f}% / 10日{r10:+.1f}% / 20日{r20:+.1f}%")
        leader = ranks[0][0] if ranks else "—"
        L.append(f"  → **领涨指数：{leader}**（传导方向：{leader} 强则做多其权重板块）\n")
    # 领涨板块与个股
    boards = fetch_hot_board()
    if boards:
        L.append("**领涨行业/概念（hot board TOP）**：")
        for name, chg in boards[:5]:
            L.append(f"- {name}：{chg:+.2f}%")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="领涨链条+行情矩阵（曾星智落地）")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--sx", type=float, help="双弦温度")
    ap.add_argument("--beast", type=float, help="猛兽安全评分")
    ap.add_argument("--fish", type=float, help="鱼身温度")
    ap.add_argument("--width", type=float, help="市场宽度分")
    ap.add_argument("--style", help="市场风格（情绪市/指数市/均衡）")
    args = ap.parse_args()
    print(render(args.date, args.sx, args.beast, args.fish, args.width, args.style))


if __name__ == "__main__":
    main()
