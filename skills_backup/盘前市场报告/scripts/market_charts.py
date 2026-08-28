#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_charts.py — 市场图表生成器（情绪图 + 三系统温度图）
================================================================
固化到盘前/复盘报告流程：每日运行 hot_emotion 后自动生成两张图。

图1：🔥 市场情绪走势（情绪温度 + 涨停/连板）  ← 数据源 hot_emotion_history.json
图2：🐟🐅🔗 三系统温度走势（双弦/猛兽/鱼身）    ← 数据源 system_temp_history.json

用法：
  python3 market_charts.py                       # 生成当前月两张图
  python3 market_charts.py --append-temp 96 88 75 --date 2026-08-28
      # 追加当日三系统温度（双弦/猛兽/鱼身）到历史后再生成

输出：
  outputs/市场情绪走势_YYYY-MM.png
  outputs/三系统温度走势_YYYY-MM.png
"""
import argparse
import json
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# 中文字体
for _f in ['/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc',
           '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
    try:
        fm.fontManager.addfont(_f)
    except Exception:
        pass
matplotlib.rcParams['font.sans-serif'] = ['Noto Sans SC', 'Noto Serif CJK JP']
matplotlib.rcParams['axes.unicode_minus'] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "outputs")
EMOTION_HIST = os.path.join(OUT_DIR, "hot_emotion_history.json")
TEMP_HIST = os.path.join(OUT_DIR, "system_temp_history.json")

# 情绪温度等级
def temp_level(t):
    if t >= 70: return '亢奋'
    if t >= 55: return '活跃'
    if t >= 40: return '中性'
    if t >= 25: return '低迷'
    return '冰点'


def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def append_temp(sx, beast, fish, date):
    """追加当日三系统温度到历史"""
    hist = load_json(TEMP_HIST)
    hist[date] = {"双弦": sx, "猛兽": beast, "鱼身": fish}
    with open(TEMP_HIST, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    print(f"✅ 已追加 {date}: 双弦{sx} 猛兽{beast} 鱼身{fish}")


def plot_emotion():
    """图1：情绪温度 + 涨停/连板"""
    hist = load_json(EMOTION_HIST)
    if not hist:
        print("⚠️ 无情绪历史数据，跳过情绪图（先运行 hot_emotion.py）")
        return None
    days = sorted(hist.keys())
    zt = [hist[d]["total"] for d in days]
    lb = [hist[d]["lianban_cnt"] for d in days]
    temp = [hist[d]["score"] for d in days]
    labels = [d[5:].replace('-', '/') for d in days]  # 2026-08-18 -> 08/18

    fig, ax1 = plt.subplots(figsize=(11, 6.2), dpi=120)
    x = np.arange(len(days))

    ax1.bar(x, zt, width=0.5, color='#FFE0B2', edgecolor='#E65100', linewidth=1, label='涨停家数')
    ax1.set_xlabel('日期', fontsize=11)
    ax1.set_ylabel('涨停家数（只）', fontsize=11, color='#E65100')
    ax1.tick_params(axis='y', labelcolor='#E65100')
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=11)
    ax1.set_ylim(0, max(zt) * 1.25 + 10)

    ax2 = ax1.twinx()
    ax2.plot(x, temp, color='#D32F2F', marker='o', markersize=8, linewidth=2.5, label='情绪温度')
    ax2.fill_between(x, temp, 0, color='#D32F2F', alpha=0.08)
    for i, v in enumerate(temp):
        ax2.annotate(f'{v}', xy=(x[i], v), xytext=(0, 10), textcoords='offset points',
                     color='#D32F2F', fontsize=11, fontweight='bold', ha='center')
    ax2.set_ylabel('情绪温度（0-100）', fontsize=11, color='#D32F2F')
    ax2.tick_params(axis='y', labelcolor='#D32F2F')
    ax2.set_ylim(0, 100)

    for i, v in enumerate(lb):
        ax1.annotate(f'连板{v}只', xy=(x[i], zt[i] + 2), ha='center', fontsize=10,
                     color='#6D4C41', fontweight='bold')

    # 等级带
    for y0, y1, c, label in [(70, 100, '#FFEBEE', '亢奋'), (55, 70, '#FFF3E0', '活跃'),
                              (40, 55, '#FFFDE7', '中性'), (25, 40, '#F3E5F5', '低迷'),
                              (0, 25, '#EFEBE9', '冰点')]:
        ax2.axhspan(y0, y1, color=c, alpha=0.35, zorder=0)
    ax2.text(x[-1] + 0.35, 85, '亢奋', fontsize=9, color='#999')
    ax2.text(x[-1] + 0.35, 62, '活跃', fontsize=9, color='#999')
    ax2.text(x[-1] + 0.35, 47, '中性', fontsize=9, color='#999')
    ax2.text(x[-1] + 0.35, 32, '低迷', fontsize=9, color='#999')
    ax2.text(x[-1] + 0.35, 12, '冰点', fontsize=9, color='#999')

    month = days[0][:7]
    ax1.set_title(f'市场情绪温度走势（{month} · 涨停/连板/情绪温度）', fontsize=14, fontweight='bold', pad=14)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10, frameon=True)
    ax1.grid(axis='y', color='#EEEEEE', linestyle='-', linewidth=0.6)
    ax1.set_axisbelow(True)
    for spine in ['top']:
        ax1.spines[spine].set_visible(False)
        ax2.spines[spine].set_visible(False)

    out = os.path.join(OUT_DIR, f'市场情绪走势_{month}.png')
    plt.tight_layout()
    plt.savefig(out, dpi=120, facecolor='white', bbox_inches='tight')
    plt.close()
    print(f'✅ 情绪图: {out}（{len(days)} 个交易日）')
    return out


def plot_system():
    """图2：三系统温度走势"""
    hist = load_json(TEMP_HIST)
    if not hist:
        print("⚠️ 无三系统温度历史，跳过体系图（首次需 --append-temp 或手动初始化）")
        return None
    days = sorted(hist.keys())
    labels = [d[5:].replace('-', '/') for d in days]
    x = np.arange(len(days))
    sx = [hist[d].get("双弦") for d in days]
    beast = [hist[d].get("猛兽") for d in days]
    fish = [hist[d].get("鱼身") for d in days]

    fig, ax = plt.subplots(figsize=(11, 6.2), dpi=120)

    for y0, y1, c, label in [(70, 100, '#FFEBEE', '安全/偏热'), (55, 70, '#FFF3E0', '偏暖'),
                              (40, 55, '#FFFDE7', '中性'), (0, 40, '#E8F5E9', '偏冷')]:
        ax.axhspan(y0, y1, color=c, alpha=0.5, zorder=0)
        ax.text(len(days) - 1 + 0.35, (y0 + y1) / 2, label, fontsize=9, color='#999', va='center')
    ax.axhline(40, color='#888', linestyle='--', linewidth=0.8, zorder=1)
    ax.axhline(55, color='#888', linestyle='--', linewidth=0.8, zorder=1)
    ax.axhline(70, color='#888', linestyle='--', linewidth=0.8, zorder=1)

    # 各系统画线（跳过 None）
    def _plot(vals, color, marker, label):
        xs = [i for i, v in enumerate(vals) if v is not None]
        ys = [vals[i] for i in xs]
        if xs:
            ax.plot(xs, ys, color=color, marker=marker, markersize=6, linewidth=2, label=label, zorder=3)
            for xi, yi in zip(xs, ys):
                ax.annotate(f'{yi}', xy=(xi, yi), xytext=(0, 8), textcoords='offset points',
                            fontsize=8, color=color, ha='center')

    _plot(sx, '#1E55B5', 'o', '双弦温度')
    _plot(beast, '#E65100', 's', '猛兽安全评分')
    _plot(fish, '#00897B', '^', '鱼身温度')

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel('温度 / 评分（0-100）', fontsize=11)
    ax.set_ylim(0, 105)
    ax.set_xlim(-0.4, len(days) - 0.2)
    month = days[0][:7]
    ax.set_title(f'三系统温度走势（{month} · 双弦/猛兽/鱼身）', fontsize=14, fontweight='bold', pad=14)

    ax.legend(loc='upper right', fontsize=10, frameon=True)
    ax.grid(axis='y', color='#EEEEEE', linestyle='-', linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)

    out = os.path.join(OUT_DIR, f'三系统温度走势_{month}.png')
    plt.tight_layout()
    plt.savefig(out, dpi=120, facecolor='white', bbox_inches='tight')
    plt.close()
    print(f'✅ 体系图: {out}（{len(days)} 个交易日）')
    return out


def extract_from_quant(date):
    """从 quant_results_{date}.json 提取三系统温度（workflow 自动模式）"""
    import re
    path = os.path.join(OUT_DIR, f'quant_results_{date}.json')
    if not os.path.exists(path):
        # 仓库根（workflow cwd）
        path = f'quant_results_{date}.json'
    if not os.path.exists(path):
        print(f'⚠️ 未找到 quant_results_{date}.json，跳过温度提取')
        return None
    try:
        with open(path, encoding='utf-8') as f:
            q = json.load(f)
    except Exception as e:
        print(f'⚠️ quant_results 解析失败: {e}')
        return None

    # 猛兽：从 stdout 正则解析 "安全评分: XX.X/100"
    beast = None
    bs_out = q.get('beast', {}).get('stdout', '') or ''
    m = re.search(r'安全评分:\s*(\d+\.?\d*)/100', bs_out)
    if m:
        beast = float(m.group(1))

    # 鱼身：market_temp.temp
    fish = q.get('fishbody', {}).get('market_temp', {}).get('temp')

    # 双弦：stdout 温度计（多种格式兜底）
    sx = None
    sx_out = q.get('shuangxian', {}).get('stdout', '') or ''
    m = re.search(r'温度(?:计)?[:：]\s*(\d+\.?\d*)/100', sx_out)
    if not m:
        m = re.search(r'大盘温度(?:计)?[:：]?\s*(\d+\.?\d*)', sx_out)
    if not m:
        m = re.search(r'温度计:\s*(\d+\.?\d*)/100', sx_out)
    if m:
        sx = float(m.group(1))

    print(f'📊 提取 {date}: 双弦{sx} 猛兽{beast} 鱼身{fish}')
    return sx, beast, fish


def main():
    global OUT_DIR, EMOTION_HIST, TEMP_HIST
    ap = argparse.ArgumentParser(description='市场图表生成器（情绪图+三系统温度图）')
    ap.add_argument('--append-temp', nargs=3, type=float, metavar=('双弦', '猛兽', '鱼身'),
                    help='追加当日三系统温度到历史（如 --append-temp 49 49.5 45）')
    ap.add_argument('--from-quant', action='store_true',
                    help='从 outputs/quant_results_{date}.json 自动提取温度并追加（workflow 模式）')
    ap.add_argument('--hist-dir', default=None, help='历史文件目录（默认 scripts/outputs）')
    ap.add_argument('--date', default=datetime.now().strftime('%Y-%m-%d'), help='日期 YYYY-MM-DD')
    args = ap.parse_args()

    if args.hist_dir:
        os.makedirs(args.hist_dir, exist_ok=True)
        OUT_DIR = args.hist_dir
        EMOTION_HIST = os.path.join(OUT_DIR, "hot_emotion_history.json")
        TEMP_HIST = os.path.join(OUT_DIR, "system_temp_history.json")
    os.makedirs(OUT_DIR, exist_ok=True)

    if args.append_temp:
        append_temp(args.append_temp[0], args.append_temp[1], args.append_temp[2], args.date)

    if args.from_quant:
        temps = extract_from_quant(args.date)
        if temps and any(t is not None for t in temps):
            append_temp(temps[0], temps[1], temps[2], args.date)

    plot_emotion()
    plot_system()


if __name__ == '__main__':
    main()
