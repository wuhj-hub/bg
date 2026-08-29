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


def load_emotion():
    """读 hot_emotion_latest.json（情绪温度/连板/最高板）
    结构: {score: {score: 48, level: "中性", ...}, lianban_cnt: 4, max_lb: 5, ...}
    """
    for path in ["outputs/hot_emotion_latest.json",
                 "/sandbox/workspace/skills/盘前市场报告/scripts/outputs/hot_emotion_latest.json"]:
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                sc = d.get("score", {})
                if isinstance(sc, dict):
                    return (sc.get("score"), sc.get("level"),
                            d.get("lianban_cnt"), d.get("max_lb"))
            except Exception:
                continue
    return None


def parse_beast(text):
    """解析 beast_results_{date}.txt → 猛兽快照数据（容错正则）"""
    info = {}
    m = re.search(r'安全评分:\s*([\d.]+)/100', text)
    if m:
        info['score'] = float(m.group(1))
    m = re.search(r'市场状态[:：]?\s*(\S+)', text)
    if m:
        info['state'] = m.group(1)
    # RSR TOP（两种格式兼容）
    boards = re.findall(r'\d+\.\s*(\S+?)\s*([+-][\d.]+)%[（(]领涨[:：]?\s*(\S+?)\s*([\d.]+)?', text)
    info['rsr'] = [(b[0], float(b[1]), b[2]) for b in boards[:3]]
    # 信号计数
    for key, pat in [('gpoint', r'G点信号[:：]?\s*(\d+)'), ('fuji', r'伏击线低吸[:：]?\s*(\d+)'),
                     ('rsd', r'RS_D背离[:：]?\s*(\d+)'), ('leaders', r'领先股:\s*(\d+)'),
                     ('pullbacks', r'回调股:\s*(\d+)')]:
        mm = re.search(pat, text)
        if mm:
            info[key] = int(mm.group(1))
    # 双模式
    m = re.search(r'主导模式[:：]?\s*(\S+)', text)
    if m:
        info['mode'] = m.group(1)
    m = re.search(r'堆量模式\s*(\d+)[,，\s]+欧马模式\s*(\d+)', text)
    if m:
        info['mode_cnt'] = (int(m.group(1)), int(m.group(2)))
    # 月线闸门
    m = re.search(r'PASS\s*(\d+)\s*/\s*WARN\s*(\d+)\s*/\s*BLOCK\s*(\d+)', text)
    if m:
        info['gate'] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r'反转信号\s*(\d+)', text)
    if m:
        info['reversal'] = int(m.group(1))
    return info


def render_beast(beast_file):
    """猛兽体系快照（三层漏斗：大盘→板块→个股+双模式+月线闸门）"""
    if not os.path.exists(beast_file):
        return "- 🐅 **猛兽**：数据缺失（未找到 beast_results）"
    with open(beast_file, encoding="utf-8", errors="replace") as f:
        info = parse_beast(f.read())
    L = ["### 🐅 猛兽体系快照（三层漏斗：大盘→板块→个股）"]
    # 大盘层
    if 'score' in info:
        L.append(f"- 🛡️ **大盘**：安全评分 **{info['score']}/100**"
                 + (f"（{info.get('state','')}）" if 'state' in info else ""))
    # 板块层
    if info.get('rsr'):
        rsr_txt = "、".join(f"{n}({c:+.1f}%)" for n, c, _ in info['rsr'])
        L.append(f"- 📊 **板块 RSR**：{rsr_txt}")
    # 个股层
    sigs = []
    if 'gpoint' in info: sigs.append(f"G点{info['gpoint']}")
    if 'fuji' in info: sigs.append(f"伏击线{info['fuji']}")
    if 'rsd' in info: sigs.append(f"RS_D{info['rsd']}")
    L.append(f"- ⭐ **个股信号**：领先股 {info.get('leaders','—')} 只 / 回调股 {info.get('pullbacks','—')} 只"
             + (f" ｜ {' ｜ '.join(sigs)}" if sigs else ""))
    # 双模式
    if 'mode' in info:
        cnt = f"（堆量{info['mode_cnt'][0]}/欧马{info['mode_cnt'][1]}）" if 'mode_cnt' in info else ""
        L.append(f"- 🔄 **主导模式**：{info['mode']}{cnt}")
    # 月线闸门
    if 'gate' in info:
        p, w, b = info['gate']
        L.append(f"- 📅 **月线闸门**：PASS {p} / WARN {w} / BLOCK {b}"
                 + (f"，反转 {info['reversal']} 只" if 'reversal' in info else ""))
    # 操作映射
    mode_map = {"堆量模式": "主扫堆量/G1低吸（情绪+资金溢出小盘）", "欧马模式": "主扫欧马/乾坤金股（产业+业绩中大盘）"}
    if 'mode' in info:
        L.append(f"> **操作映射**：{mode_map.get(info['mode'], '按猛兽信号纪律')}")
    return "\n".join(L)


def render(date, sx, beast, fish, width, style, month_gate=None, reversal=None, beast_file=None):
    L = []
    # 行情类型（中线）
    rtype, pos, tactic = regime_type(sx, beast, fish, width)
    L.append("### 🧭 曾星智三系统快照（长线/中线/短线）\n")
    # 🐢 长线：月线闸门 + 月线反转
    if month_gate:
        L.append(f"- 🐢 **长线**：月线闸门 **{month_gate}**" +
                 (f"，月线反转 {reversal} 只" if reversal is not None else "") + "\n")
    else:
        L.append("- 🐢 **长线**：月线闸门（待传 --month-gate）\n")
    # 🐂 中线：行情类型 + 领涨链条
    L.append(f"- 🐂 **中线**：**{rtype}**（建议仓位 {pos}）\n")
    idx_data = fetch_kline(INDICES)
    if idx_data:
        ranks = leading_index(idx_data)
        leader = ranks[0][0] if ranks else "—"
        L.append(f"  → 领涨指数：**{leader}**（5日{ranks[0][1]:+.1f}% 最强）\n")
    boards = fetch_hot_board()
    if boards:
        bnames = "、".join(f"{n}({c:+.1f}%)" for n, c in boards[:3])
        L.append(f"  → 领涨板块：{bnames}\n")
    # 🐺 短线：热点情绪 + 连板 + 顶背离预警
    emo = load_emotion()
    if emo:
        score, level, lb, maxlb = emo
        L.append(f"- 🐺 **短线**：情绪温度 **{score}/100（{level}）**，连板 {lb} 只/最高 {maxlb} 板\n")
        # 顶背离预警：连板高度骤降（前日高今低）→ 简化为连板<3 且涨停多时提示
        if lb is not None and lb < 3:
            L.append(f"  → ⚠️ 连板高度不足（{lb}只）→ 短线接力风险，防顶背离\n")
    else:
        L.append("- 🐺 **短线**：情绪温度（先跑 hot_emotion）\n")
    # 策略总括
    L.append(f"\n> **操作映射**：{tactic} ｜ 三系统均值 {((sx or 0)+(beast or 0)+(fish or 0))/3:.0f}"
             f"（双弦{sx}/猛兽{beast}/鱼身{fish}）" + (f"｜ 宽度 {width}" if width else "") +
             (f"｜ 风格 {style}" if style else "") + "\n")
    # 猛兽体系快照（附在曾星智快照之后）
    if beast_file:
        L.append("\n" + render_beast(beast_file))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="曾星智三系统快照（长线/中线/短线）")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--sx", type=float, help="双弦温度")
    ap.add_argument("--beast", type=float, help="猛兽安全评分")
    ap.add_argument("--fish", type=float, help="鱼身温度")
    ap.add_argument("--width", type=float, help="市场宽度分")
    ap.add_argument("--style", help="市场风格（情绪市/指数市/均衡）")
    ap.add_argument("--month-gate", help="月线闸门状态（多头/纠缠/空头）")
    ap.add_argument("--reversal", type=int, help="月线反转信号数")
    ap.add_argument("--beast-file", help="beast_results 文件路径（猛兽快照）")
    args = ap.parse_args()
    print(render(args.date, args.sx, args.beast, args.fish, args.width, args.style,
                 args.month_gate, args.reversal, args.beast_file))


if __name__ == "__main__":
    main()
