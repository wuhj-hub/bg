#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sector_divergence.py —— 断档分歧检测（龚夫财经买点方法论）
============================================================
口诀：主流板块"一日观察，两日关注，三日确认，强度过万，持续增强"
买点：板块**首次跌出强度榜前五** = 断档分歧 = 最佳上车点

实现：
  1. 每日存档板块强度榜 → outputs/板块强度榜_{date}.json
  2. 检测连续≥3日在榜前五的板块，今日跌出前五 → "断档分歧"信号
  3. 与主线中军配对（断档板块的龙头=低吸候选）

用法：
  python3 sector_divergence.py --save          # 存档今日榜（workflow每日跑）
  python3 sector_divergence.py                 # 检测断档（读近5日档案）
输出：outputs/断档分歧_latest.json + 断档分歧_{date}.md
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

OUT_DIR = "outputs"
TOP_N = 5          # 强度榜前五
MIN_DAYS = 3       # 连续在榜天数门槛


def load_latest_board():
    """读当日板块共振 → 强度榜（按 strength 排序取前TOP_N）"""
    for p in ("板块共振_latest.json", "outputs/板块共振_latest.json",
              "../板块共振_latest.json", "../outputs/板块共振_latest.json",
              "/sandbox/workspace/github_bg/板块共振_latest.json",
              "/sandbox/workspace/github_bg/outputs/板块共振_latest.json"):
        try:
            d = json.load(open(p, encoding="utf-8"))
            boards = d.get("resonance_boards", [])
            if not boards:
                return None, None
            # 按 strength 降序，取前 TOP_N
            ranked = sorted(boards, key=lambda b: -b.get("strength", 0))[:TOP_N]
            date = d.get("date", datetime.now().strftime("%Y-%m-%d"))
            return date, [b["name"] for b in ranked]
        except Exception:
            continue
    return None, None


def load_history(days=6):
    """读近N日强度榜档案，返回 {date: [板块名前五]}"""
    hist = {}
    today = datetime.now().strftime("%Y-%m-%d")
    for i in range(days):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        for p in (f"{OUT_DIR}/板块强度榜_{d}.json", f"板块强度榜_{d}.json"):
            try:
                hist[d] = json.load(open(p, encoding="utf-8"))["top5"]
                break
            except Exception:
                continue
    return hist


def detect(hist, today, today_top5):
    """检测断档分歧：连续≥MIN_DAYS在前五的板块，今日跌出"""
    if today in hist:
        hist.pop(today)  # 今日档案可能是昨天的旧榜
    signals = []
    for d, top5 in sorted(hist.items()):
        for b in top5:
            if b in today_top5:
                continue
            # 计算该板块在历史中连续在榜天数（含该日及更早）
            streak = 0
            for dd in sorted(hist.keys(), reverse=True):
                if dd <= d and b in hist.get(dd, []):
                    streak += 1
                elif dd <= d:
                    break
            if streak >= MIN_DAYS:
                signals.append({"board": b, "last_top_date": d,
                                "streak_days": streak, "note": "连续在榜跌出前五（断档分歧）"})
    # 去重
    seen = {}
    for s in signals:
        seen[s["board"]] = s
    return list(seen.values())


def match_zhongjun(boards):
    """从板块共振的中军候选匹配断档板块龙头"""
    for p in ("板块共振_latest.json", "outputs/板块共振_latest.json",
              "../outputs/板块共振_latest.json",
              "/sandbox/workspace/github_bg/outputs/板块共振_latest.json"):
        try:
            d = json.load(open(p, encoding="utf-8"))
            zj = d.get("zhongjun_candidates", [])
            out = []
            for b in boards:
                match = [z for z in zj if z.get("board") == b["board"]]
                out.append({**b, "zhongjun": match[:2] if match else []})
            return out
        except Exception:
            continue
    return boards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="存档今日强度榜")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    date, today_top5 = load_latest_board()
    if not today_top5:
        print("[WARN] 板块共振数据缺失，跳过", file=sys.stderr)
        sys.exit(0)

    if args.save:
        # 存档今日榜
        path = f"{OUT_DIR}/板块强度榜_{date}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"date": date, "top5": today_top5}, f, ensure_ascii=False, indent=1)
        print(f"[OK] 存档强度榜 {date}: {today_top5}")
        # 存档同时检测
    else:
        print(f"[INFO] 今日强度榜前五: {today_top5}", file=sys.stderr)

    hist = load_history()
    print(f"[INFO] 历史档案 {len(hist)} 天: {sorted(hist.keys())}", file=sys.stderr)
    signals = detect(hist, date, today_top5)
    signals = match_zhongjun(signals)

    # 输出
    js = {"date": date, "top5": today_top5, "signals": signals,
          "method": "龚夫财经·断档分歧（连续≥3日强度前五后首次跌出=买点）"}
    with open(f"{OUT_DIR}/断档分歧_latest.json", "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False, indent=1)

    if signals:
        md = [f"# ⚡ 断档分歧信号 {date}", "",
              f"> 连续≥{MIN_DAYS}日强度前五的板块今日跌出前五 = **上车点**（龚夫财经方法论）",
              "> 配对：断档板块 + 主线中军龙头（低吸候选）", "",
              "| 板块 | 最后在榜日 | 连续天数 | 中军龙头 |",
              "|:----|:----|:----:|:----|"]
        for s in signals:
            zj_names = "、".join(f"{z['stock']}({z['code']})" for z in s.get("zhongjun", [])) or "—"
            md.append(f"| {s['board']} | {s['last_top_date']} | {s['streak_days']} | {zj_names} |")
        md += ["", "---", "*本报告由 sector_divergence.py 自动生成（龚夫财经买点方法论程序化）*"]
        with open(f"{OUT_DIR}/断档分歧_{date}.md", "w", encoding="utf-8") as f:
            f.write("\n".join(md))
        print(f"[OK] 断档分歧 {len(signals)} 个: {[s['board'] for s in signals]} -> {OUT_DIR}/断档分歧_{date}.md")
    else:
        print(f"[OK] 今日无断档分歧信号（档案{len(hist)}天）")
        # 清空旧md
        try:
            os.remove(f"{OUT_DIR}/断档分歧_{date}.md")
        except Exception:
            pass


if __name__ == "__main__":
    main()
