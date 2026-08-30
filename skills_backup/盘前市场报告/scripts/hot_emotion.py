#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hot_emotion.py — 热点情绪模块（连板梯队 + 板块持续性 + 退潮预警）
====================================================================
补齐现有体系缺失的「情绪高度」维度：
  涨停家数 = 板块广度  |  连板家数 = 板块高度（资金敢不敢做接力）
  涨停多+连板少 = 套利一日游  |  涨停多+连板多 = 强主线（叶岚热点版面方法论量化版）

数据源（双轨）：
  1) tdx 模式（默认）：读取 tdx_screener 导出的 JSON（含连续涨停天数/涨停原因/板型/封单）
     —— 由 IMA 会话中调用 tdx_screener（"涨停" 全量 + "2连板以上"）导出
  2) westock 模式：westock 批量 kline 自算涨停/连板（无题材/封单，供自动化降级）
     —— 预留接口，--westock 时从 all_mainboard.csv 批量拉K线自算

输出：
  outputs/hot_emotion_{date}.md    报告片段（Markdown，供盘前/复盘报告引用）
  outputs/hot_emotion_latest.json  最新数据（含情绪温度/连板梯队/主线判定）
  outputs/hot_emotion_history.json 历史累积（题材持续性/退潮预警依据）

用法：
  python3 hot_emotion.py --date 2026-08-18 --input tdx_2026-08-18.json
  python3 hot_emotion.py --date 2026-08-18 --westock            # 自动化降级
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "outputs")
HISTORY_FILE = os.path.join(OUT_DIR, "hot_emotion_history.json")
LATEST_FILE = os.path.join(OUT_DIR, "hot_emotion_latest.json")


# 标签归一化：tdx 题材标签碎片化，合并同义标签还原真实主线
TAG_MERGE = {
    "乡村振兴": "农业/粮食", "种业": "农业/粮食", "种植业": "农业/粮食",
    "粮食概念": "农业/粮食", "农业种植": "农业/粮食", "养殖业": "农业/粮食",
    "饲料": "农业/粮食", "转基因": "农业/粮食", "土地流转": "农业/粮食",
    "农产品加工": "农业/粮食", "预制菜": "农业/粮食", "食品饮料": "农业/粮食",
    "化肥概念": "农业化工", "农用化工": "农业化工", "煤化工": "农业化工",
    "CPO概念": "CPO/光通信", "光通信器件": "CPO/光通信", "光纤": "CPO/光通信",
    "芯片": "半导体/芯片", "存储芯片": "半导体/芯片", "电子身份证": "半导体/芯片",
    "机器人概念": "机器人", "人形机器人": "机器人", "具身智能": "机器人",
    "智能制造": "机器人", "微型传动": "机器人", "丝杠": "机器人",
    "人工智能": "AI", "AI智能体": "AI", "在线教育": "AI",
    "新零售": "消费/新零售", "电商概念": "消费/新零售", "一般零售": "消费/新零售",
    "生鲜电商": "消费/新零售", "数据要素": "消费/新零售",
    "化学制药": "医药", "中药": "医药", "生物医药": "医药",
    "维生素": "医药", "医疗器械概念": "医药", "合成生物": "医药",
    "动物保健": "医药", "医药商业": "医药",
    "储能": "储能/绿电", "绿色电力": "储能/绿电", "碳中和": "储能/绿电",
    "氢能源": "储能/绿电", "光伏": "储能/绿电",
    "新能源车": "汽车链", "汽车零部件": "汽车链", "汽车线束": "汽车链",
    "比亚迪概念": "汽车链",
    "核电概念": "核电/军工", "军工": "核电/军工", "卫星导航": "核电/军工",
    "低空经济": "低空经济",
}


def norm_tag(tag):
    """标签归一化：返回合并后的主线标签。"""
    return TAG_MERGE.get(tag, tag)


# ---------- 涨停/连板解析 ----------

def parse_tdx_json(data):
    """解析 tdx_screener 导出的 JSON（meta.data 数组）。
    兼容两种返回：'涨停'（字段全）与 '2连板以上'（字段略少）。
    返回: list[dict] 每条含 code/name/lianban/ji_ji_ban/reason/banxing/time/fengdan（按 code 去重）
    """
    rows = []
    seen = set()
    items = data.get("data", []) if isinstance(data, dict) else data
    for it in items:
        if not isinstance(it, dict):
            continue
        code = str(it.get("sec_code", ""))
        if not code or code in seen:
            continue
        seen.add(code)
        try:
            lb = int(float(it.get("连续涨停天数", it.get("连续涨停天数0#", 0)) or 0))
        except (ValueError, TypeError):
            lb = 0
        rows.append({
            "code": code,
            "name": str(it.get("sec_name", "")),
            "price": it.get("now_price", ""),
            "chg": it.get("chg", ""),
            "lianban": lb,
            "ji_ji_ban": str(it.get("几天几板", "")),
            "reason": str(it.get("涨停原因", it.get("短线主题名称", ""))),
            "banxing": str(it.get("板型", "")),
            "first_time": str(it.get("首次涨停时间", "")),
            "open_cnt": it.get("涨停打开次数", ""),
            "fengdan": it.get("封单金额0#", it.get("封单金额", "")),
        })
    return rows


def parse_westock_kline(csv_text):
    """westock 批量 kline 自算涨停/连板（--westock 模式）。
    输入: kline 批量输出文本（列序: symbol,date,open,last,high,low,...）
    输出: list[dict]（无题材/板型字段，lianban 通过连续涨停日推算）
    """
    rows = []
    by_code = defaultdict(list)
    for line in csv_text.strip().splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        sym, date, open_, last, high, low = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        if not (sym.startswith("sh") or sym.startswith("sz")):
            continue
        if not (date.replace("-", "").isdigit()):
            continue
        try:
            close = float(last)
            prev = None
            by_code[sym].append((date, close))
        except ValueError:
            continue
    for sym, bars in by_code.items():
        bars.sort(key=lambda x: x[0])
        # 从最近一天往前数连续涨停天数
        lb = 0
        for i in range(len(bars) - 1, 0, -1):
            d, c = bars[i]
            pd, pc = bars[i - 1]
            if pc > 0 and c / pc - 1 >= 0.095:
                lb += 1
            else:
                break
        if lb >= 1:
            rows.append({
                "code": sym, "name": "", "price": "", "chg": "",
                "lianban": lb, "ji_ji_ban": f"{lb}天{lb}板",
                "reason": "", "banxing": "", "first_time": "",
                "open_cnt": "", "fengdan": "",
            })
    return rows


# ---------- 统计与情绪温度 ----------

def build_stats(rows, total_hint=None):
    """从涨停记录构建统计。"""
    total = total_hint or len(rows)
    by_lb = Counter(r["lianban"] for r in rows)
    lianban_rows = sorted([r for r in rows if r["lianban"] >= 2],
                          key=lambda r: -r["lianban"])
    shouban = total - sum(by_lb.get(n, 0) for n in range(2, 10))
    lianban_cnt = len(lianban_rows)
    max_lb = max((r["lianban"] for r in rows), default=0)
    # 题材聚类（按涨停原因中的标签，先归一化合并同义标签；每只股票每个合并标签只计一次）
    tag_counter = Counter()
    for r in rows:
        seen_tags = set()
        for tag in r["reason"].replace("，", ".").replace(" ", "").split("."):
            t = norm_tag(tag.strip())
            if len(t) >= 2 and t not in ("活跃小盘非融", "微小盘股", "扣非亏损", "预计扭亏", "业绩预亏", "预计转亏"):
                seen_tags.add(t)
        for t in seen_tags:
            tag_counter[t] += 1
    # 连板梯队按题材聚合（最强主线=连板股集中的题材）
    lianban_tags = Counter()
    for r in lianban_rows:
        seen_tags = set()
        for tag in r["reason"].split("."):
            t = norm_tag(tag.strip())
            if len(t) >= 2 and t not in ("活跃小盘非融", "微小盘股"):
                seen_tags.add(t)
        for t in seen_tags:
            lianban_tags[t] += 1
    # 题材龙头（曾星智"热点概念龙头"法落地）：每个题材内 连板最高→封单最大→首板时间最早 为龙头
    def leader_key(r):
        fengdan = 0.0
        fd = str(r.get("fengdan") or "").strip()
        m = re.match(r"([\d.]+)(亿|万)?", fd)
        if m:
            fengdan = float(m.group(1))
            if m.group(2) == "亿":
                fengdan *= 1e8
            elif m.group(2) == "万":
                fengdan *= 1e4
        ft = str(r.get("first_time") or "")
        return (-r["lianban"], -fengdan, ft)
    tag_leaders = {}
    for r in rows:
        seen_tags = set()
        for tag in r["reason"].replace("，", ".").replace(" ", "").split("."):
            t = norm_tag(tag.strip())
            if len(t) >= 2 and t not in ("活跃小盘非融", "微小盘股", "扣非亏损", "预计扭亏", "业绩预亏", "预计转亏"):
                if t not in seen_tags:
                    seen_tags.add(t)
                    if t not in tag_leaders or leader_key(r) < leader_key(tag_leaders[t]):
                        tag_leaders[t] = r
    return {
        "total": total,
        "shouban": shouban,
        "lianban_cnt": lianban_cnt,
        "max_lb": max_lb,
        "by_lb": dict(sorted(by_lb.items(), reverse=True)),
        "lianban_rows": lianban_rows,
        "tags": tag_counter.most_common(15),
        "lianban_tags": lianban_tags.most_common(10),
        "tag_leaders": tag_leaders,
    }


def emotion_score(stats):
    """情绪温度计 0-100：涨停家数(20) + 连板高度(45) + 连板占比(35)。
    权重设计（校准自叶岚方法论）：连板结构决定情绪温度，涨停数量只代表广度。
    涨停多+连板少（一日游）得分天然被压；只有连板高度与占比同时走高才到"活跃/亢奋"。
    校准样本：8/18 涨停80只但最高4板、连板占比13.75% → 50分"中性"（广度好但结构弱）。
    """
    total = stats["total"]
    if total >= 100:
        s1 = 20
    elif total >= 80:
        s1 = 16
    elif total >= 60:
        s1 = 12
    elif total >= 40:
        s1 = 8
    elif total >= 20:
        s1 = 5
    else:
        s1 = 2
    ml = stats["max_lb"]
    if ml >= 8:
        s2 = 45
    elif ml == 7:
        s2 = 42
    elif ml == 6:
        s2 = 36
    elif ml == 5:
        s2 = 28
    elif ml == 4:
        s2 = 18
    elif ml == 3:
        s2 = 10
    elif ml == 2:
        s2 = 5
    else:
        s2 = 2
    ratio = stats["lianban_cnt"] / total if total else 0
    if ratio >= 0.25:
        s3 = 35
    elif ratio >= 0.20:
        s3 = 30
    elif ratio >= 0.15:
        s3 = 24
    elif ratio >= 0.10:
        s3 = 16
    elif ratio >= 0.05:
        s3 = 8
    else:
        s3 = 3
    score = s1 + s2 + s3
    if score >= 70:
        level = "亢奋"
    elif score >= 55:
        level = "活跃"
    elif score >= 40:
        level = "中性"
    elif score >= 25:
        level = "低迷"
    else:
        level = "冰点"
    return {"score": score, "level": level, "parts": {"涨停家数": s1, "连板高度": s2, "连板占比": s3}}


# ---------- 历史累积 / 板块持续性 / 退潮预警 ----------

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def build_persistence(date, stats, history):
    """板块持续性：题材连续上榜天数 / 近5日出现次数 / 与昨日对比。"""
    tags = dict(stats["tags"])
    ltags = dict(stats["lianban_tags"])
    # 题材热度合并：涨停家数 + 连板股加权
    theme_heat = defaultdict(float)
    for tag, cnt in tags.items():
        theme_heat[tag] += cnt
    for tag, cnt in ltags.items():
        theme_heat[tag] += cnt * 2.0  # 连板股加权
    top_themes = sorted(theme_heat.items(), key=lambda x: -x[1])[:8]

    persistence = []
    for tag, heat in top_themes:
        streak = 0
        days = sorted(history.keys())
        for d in reversed(days):
            rec = history[d].get("themes", {})
            if tag in rec:
                streak += 1
            else:
                break
        appear_5d = sum(1 for d in days[-5:] if tag in history[d].get("themes", {}))
        yesterday = history[days[-1]] if days else None
        prev_heat = yesterday["themes"].get(tag, {}).get("heat", 0) if yesterday else None
        prev_zt = yesterday["themes"].get(tag, {}).get("zt", 0) if yesterday else None
        # 主线定性（叶岚方法论：连板集中=资金敢接力=强主线；涨停多+连板少=一日游；连续上榜=持续主线）
        lb_in_tag = ltags.get(tag, 0)
        zt_in_tag = tags.get(tag, 0)
        if lb_in_tag >= 3:
            kind = "强主线"
        elif zt_in_tag >= 8 and lb_in_tag >= 2:
            kind = "强主线"
        elif zt_in_tag >= 5 and lb_in_tag == 0:
            kind = "一日游⚠️"
        elif streak >= 2 and zt_in_tag >= 5:
            kind = "持续主线"
        elif streak >= 1 and zt_in_tag >= 3:
            kind = "发酵中"
        else:
            kind = "新方向"
        persistence.append({
            "tag": tag, "heat": round(heat, 1), "zt": zt_in_tag, "lianban": lb_in_tag,
            "streak": streak, "appear_5d": appear_5d,
            "prev_heat": prev_heat, "prev_zt": prev_zt, "kind": kind,
        })
    return persistence


def build_alerts(date, stats, history, persistence):
    """退潮预警规则化。"""
    alerts = []
    days = sorted(history.keys())
    if not days:
        return alerts
    prev = history[days[-1]]
    p_total = prev.get("total", 0)
    p_lianban = prev.get("lianban_cnt", 0)
    p_max = prev.get("max_lb", 0)
    # 1) 涨停多但连板家数环比下滑≥50% → 情绪退潮
    if stats["total"] >= 40 and p_lianban > 0 and \
            stats["lianban_cnt"] <= p_lianban * 0.5:
        alerts.append(f"⚠️ 退潮预警：涨停{stats['total']}只但连板家数{stats['lianban_cnt']}，仅为昨日({days[-1]}){p_lianban}的一半 → 情绪退潮，谨慎接力")
    # 2) 最高板环比下降
    if p_max >= 3 and stats["max_lb"] < p_max:
        alerts.append(f"⚠️ 高度退潮：最高板从{p_max}板降至{stats['max_lb']}板（昨{days[-1]}）")
    # 3) 昨日 TOP 题材今日涨停家数减半 → 主线退潮
    prev_themes = prev.get("themes", {})
    if prev_themes:
        top_prev_tag = max(prev_themes.items(), key=lambda x: x[1].get("zt", 0))[0]
        prev_zt = prev_themes[top_prev_tag].get("zt", 0)
        cur_zt = dict(stats["tags"]).get(top_prev_tag, 0)
        if prev_zt >= 5 and cur_zt <= prev_zt * 0.5:
            alerts.append(f"⚠️ 主线退潮：昨日主线「{top_prev_tag}」涨停{prev_zt}只 → 今日仅{cur_zt}只")
    return alerts


# ---------- 报告生成 ----------

def render_md(date, stats, score, persistence, alerts, sample_note=""):
    L = []
    L.append(f"### 🔥 热点情绪（{date} 收盘）\n")
    L.append(f"> **情绪温度 {score['score']}/100 · {score['level']}** ｜ 涨停 {stats['total']} 只 ｜ "
             f"连板 {stats['lianban_cnt']} 只 ｜ 最高 {stats['max_lb']} 板"
             f"（广度{score['parts']['涨停家数']} + 高度{score['parts']['连板高度']} + 占比{score['parts']['连板占比']}）\n")
    if sample_note:
        L.append(f"> ⚠️ {sample_note}\n")
    # 连板梯队
    L.append("**连板梯队**：")
    if stats["lianban_rows"]:
        tiers = defaultdict(list)
        for r in stats["lianban_rows"]:
            tiers[r["lianban"]].append(r)
        for lb in sorted(tiers.keys(), reverse=True):
            names = "、".join(f"{r['name']}({r['ji_ji_ban']}{('·' + r['banxing'].replace('(涨停)', '')) if r['banxing'] else ''})"
                              for r in tiers[lb])
            L.append(f"- {lb}板×{len(tiers[lb])}：{names}")
    else:
        L.append("- 无连板（最高仅首板，情绪冰点）")
    L.append("")
    # 首板
    if stats["shouban"] > 0:
        L.append(f"- 首板 {stats['shouban']} 只")
        L.append("")
    # 主线判定（板块持续性）
    L.append("**主线判定**（涨停多+连板多=强主线；连续上榜=持续主线；涨停多+连板少=一日游）：")
    if persistence:
        leaders = stats.get("tag_leaders", {})
        for p in persistence:
            seq = f"连续{p['streak']}日" if p["streak"] >= 1 else "新上榜"
            ld = leaders.get(p["tag"])
            ld_txt = ""
            if ld:
                lb_txt = f"{ld['lianban']}板" if ld["lianban"] >= 2 else "首板"
                bxt = ld.get("banxing", "").replace("(涨停)", "")
                ld_txt = f" ｜ 🐲龙头：**{ld['name']}**（{lb_txt}{('·' + bxt) if bxt else ''}）"
            L.append(f"- {p['tag']}：涨停{p['zt']}只/连板{p['lianban']}只 → **{p['kind']}**（{seq}，近5日{p['appear_5d']}次）{ld_txt}")
    else:
        L.append("- 无显著题材")
    L.append("")
    # 退潮预警
    if alerts:
        L.append("**⚠️ 情绪预警**：")
        for a in alerts:
            L.append(f"- {a}")
        L.append("")
    return "\n".join(L)


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(description="热点情绪模块：连板梯队+板块持续性+退潮预警")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="交易日 YYYY-MM-DD")
    ap.add_argument("--input", action="append", help="tdx_screener 导出的 JSON 文件路径（可多个，自动合并去重）")
    ap.add_argument("--westock", action="store_true", help="westock 批量K线自算模式（降级）")
    ap.add_argument("--kline-file", help="westock 模式：kline 批量输出文本文件")
    ap.add_argument("--outdir", default=OUT_DIR, help="输出目录")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    date = args.date

    # 1. 数据加载
    if args.westock:
        if not args.kline_file:
            print("错误：--westock 模式需要 --kline-file（westock kline 批量输出）", file=sys.stderr)
            sys.exit(1)
        with open(args.kline_file, "r", encoding="utf-8") as f:
            rows = parse_westock_kline(f.read())
        total_hint = len(rows)
        sample_note = "数据源=westock批量K线自算（无题材/封单明细）"
    else:
        if not args.input:
            print("错误：需要 --input（tdx_screener 导出的 JSON）或 --westock", file=sys.stderr)
            sys.exit(1)
        # 支持多文件：--input a.json --input b.json（"涨停"全量 + "2连板以上"），自动合并去重
        all_rows = []
        seen_codes = set()
        total_hint = None
        for in_path in args.input:
            with open(in_path, "r", encoding="utf-8") as f:
                tdx = json.load(f)
            for r in parse_tdx_json(tdx):
                if r["code"] not in seen_codes:
                    seen_codes.add(r["code"])
                    all_rows.append(r)
            if isinstance(tdx, dict):
                meta = tdx.get("meta", {})
                t = meta.get("total")
                if t and (total_hint is None or t > total_hint):
                    total_hint = t
        rows = all_rows
        sample_note = "" if total_hint and total_hint == len(rows) else \
            f"样本 {len(rows)}/{total_hint or '?'} 只涨停（tdx导出截断）"

    if not rows:
        print("错误：未解析到任何涨停记录", file=sys.stderr)
        sys.exit(1)

    # 2. 统计 + 情绪温度
    stats = build_stats(rows, total_hint=total_hint)
    score = emotion_score(stats)

    # 3. 历史累积 + 板块持续性 + 退潮预警
    history = load_history()
    persistence_now = build_persistence(date, stats, history)
    alerts = build_alerts(date, stats, history, persistence_now)

    # 4. 更新历史
    history[date] = {
        "total": stats["total"],
        "lianban_cnt": stats["lianban_cnt"],
        "max_lb": stats["max_lb"],
        "score": score["score"],
        "level": score["level"],
        "themes": {p["tag"]: {"heat": p["heat"], "zt": p["zt"]} for p in persistence_now},
    }
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    # 5. 输出
    md = render_md(date, stats, score, persistence_now, alerts, sample_note)
    latest = {
        "date": date,
        "total": stats["total"], "lianban_cnt": stats["lianban_cnt"],
        "max_lb": stats["max_lb"], "shouban": stats["shouban"],
        "by_lb": stats["by_lb"],
        "score": score, "persistence": persistence_now, "alerts": alerts,
        "lianban_rows": stats["lianban_rows"],
        "leaders": {t: {"code": r["code"], "name": r["name"], "lianban": r["lianban"],
                        "ji_ji_ban": r["ji_ji_ban"], "banxing": r["banxing"],
                        "first_time": r["first_time"], "fengdan": r["fengdan"]}
                    for t, r in stats["tag_leaders"].items()},
    }
    with open(os.path.join(args.outdir, f"hot_emotion_latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.outdir, f"hot_emotion_{date}.md"), "w", encoding="utf-8") as f:
        f.write(md)

    print(md)


if __name__ == "__main__":
    main()
