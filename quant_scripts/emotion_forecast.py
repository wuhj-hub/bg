#!/usr/bin/env python3
"""
emotion_forecast.py —— 市场情绪状态判定与次日预判（颜劼情绪周期量化版）
================================================================
基于颜劼复盘笔记 105 份日报统计出的情绪转移矩阵（2025.8-2026.2）：
  高潮(涨停≥100) 次日: 43%高潮/14%分化/19%偏强/19%中性/5%偏弱 → 95%不转弱
  高潮后分化    次日: 43%重回高潮（分歧转一致）
  偏强(70-99)   次日: 30%升高潮
  中性(40-69)   次日: 48%转偏强（蓄水池）
  偏弱(15-39)   次日: 75%修复
  冰点(<15)     次日: 100%转中性（黄金坑）

涨停家数来源（优先级）:
  1. market_width_latest.json 的 limitup
  2. 全主板批量K线实时计算（westock）

用法: python3 emotion_forecast.py            # 输出当日情绪+次日预判
      python3 emotion_forecast.py --inline   # 输出单行摘要（供妖股池嵌入）
====================================================
"""
import subprocess, sys, os, re, json, time
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

# 转移矩阵（当日状态 → 次日各状态概率%，来自颜劼统计）
MATRIX = {
    "高潮":       {"高潮": 43, "分化": 14, "偏强": 19, "中性": 19, "偏弱": 5, "冰点": 0},
    "高潮后分化": {"高潮": 43, "分化": 0, "偏强": 29, "中性": 14, "偏弱": 14, "冰点": 0},
    "偏强":       {"高潮": 30, "分化": 13, "偏强": 26, "中性": 22, "偏弱": 9, "冰点": 0},
    "中性":       {"高潮": 5,  "分化": 5,  "偏强": 48, "中性": 29, "偏弱": 14, "冰点": 0},
    "偏弱":       {"高潮": 12, "分化": 0,  "偏强": 25, "中性": 50, "偏弱": 12, "冰点": 0},
    "冰点":       {"高潮": 0,  "分化": 0,  "偏强": 0,  "中性": 100, "偏弱": 0, "冰点": 0},
}
ADVICE = {
    "高潮": "情绪高潮，次日95%不转弱→持有核心不恐高，但分化日临近",
    "高潮后分化": "分歧中继，43%次日回高潮→分化日低吸核心龙头（分歧转一致）",
    "偏强": "偏强延续，30%概率升高潮→可参与，关注能否加速",
    "中性": "蓄水池，48%转偏强→低吸潜伏窗口",
    "偏弱": "偏弱修复期，75%次日修复→布局窗口不恐慌",
    "冰点": "冰点黄金坑，100%转中性→逆向布局信号",
}

def cli(cmd, timeout=180):
    full = WESTOCK + cmd.split()
    for attempt in range(3):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            if r.stdout.strip() and "执行失败" not in r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""

def get_limitup_from_width():
    """读 market_width_latest.json 涨停数（本地→GitHub）"""
    for p in ("/sandbox/workspace/market_width_latest.json",
              "/sandbox/workspace/outputs/market_width_latest.json",
              "/sandbox/workspace/bg/market_width_latest.json"):
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                lu = d.get("limitup") or d.get("limit_up") or (d.get("limitup_stats") or {}).get("limitup")
                if lu is not None:
                    return int(lu), d.get("date", "?")
            except Exception:
                pass
    # GitHub 拉取兜底
    try:
        import urllib.request
        tok = os.environ.get("GITHUB_TOKEN", "")
        if not tok:
            for ln in open("/sandbox/workspace/.env"):
                if ln.startswith("GITHUB_TOKEN="):
                    tok = ln.strip().split("=", 1)[1]
                    break
        req = urllib.request.Request(
            "https://api.github.com/repos/wuhj-hub/bg/contents/market_width_latest.json",
            headers={"Authorization": f"token {tok}"} if tok else {})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
        import base64
        j = json.loads(base64.b64decode(d["content"]).decode())
        lu = j.get("limitup") or j.get("limit_up") or (j.get("limitup_stats") or {}).get("limitup")
        if lu is not None:
            return int(lu), j.get("date", "?")
    except Exception:
        pass
    return None, None

def calc_limitup_live(limit=2000):
    """全主板批量K线实时算当日涨停数（westock，limit只取前N只加速）"""
    pool = []
    csv = "/sandbox/workspace/all_mainboard.csv"
    if not os.path.exists(csv):
        return None
    with open(csv, encoding="utf-8-sig") as f:
        next(f)
        for ln in f:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                code = parts[0].strip()
                if code.startswith(("688", "300", "301")) or "ST" in parts[1].upper() or "退" in parts[1]:
                    continue
                pool.append(("sh" + code if code.startswith("6") else "sz" + code))
            if len(pool) >= limit:
                break
    count = 0
    valid = 0
    for i in range(0, len(pool), 50):
        syms = ",".join(pool[i:i+50])
        md = cli(f"kline {syms} --period day --limit 3 --fq qfq")
        has_symbol = "| symbol |" in md
        cur = {}
        for ln in md.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            try:
                if has_symbol:
                    if parts[0] in ("symbol", "---"):
                        continue
                    sym, d, o, c = parts[0], parts[1], parts[2], parts[3]
                else:
                    if not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                        continue
                    sym, d, o, c = pool[i], parts[0], parts[1], parts[2]
                if sym not in cur or d > cur[sym][0]:
                    cur[sym] = (d, float(c))
            except (ValueError, IndexError):
                continue
        # 需要前收盘：再拉 limit 2 已含，直接用 cur 里最新两根？
        # 简化：cur 只有最新一根，涨停需前收——用 batch 内第二根
        # 改为：limit 2 时 cur 存 (最新, 前收)
        cur2 = {}
        for ln in md.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            try:
                if has_symbol:
                    if parts[0] in ("symbol", "---"):
                        continue
                    sym, d, c = parts[0], parts[1], parts[3]
                else:
                    if not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                        continue
                    sym, d, c = pool[i], parts[0], parts[2]
                cur2.setdefault(sym, []).append((d, float(c)))
            except (ValueError, IndexError):
                continue
        for sym, rows in cur2.items():
            rows.sort(key=lambda x: x[0])
            if len(rows) >= 2 and rows[-1][1] > 0:
                valid += 1
                if rows[-1][1] / rows[-2][1] >= 1.097:
                    count += 1
    if valid == 0:
        return None
    return int(count)

def judge(limitup, today_str):
    """情绪状态判定 + 次日预判"""
    if limitup is None:
        return None
    if limitup >= 100:
        state = "高潮"
    elif limitup >= 70:
        state = "偏强"
    elif limitup >= 40:
        state = "中性"
    elif limitup >= 15:
        state = "偏弱"
    else:
        state = "冰点"
    row = MATRIX[state]
    # 次日最可能状态
    nxt = max(row, key=row.get)
    top2 = sorted(row.items(), key=lambda x: -x[1])[:2]
    return {"date": today_str, "limitup": limitup, "state": state,
            "next": nxt, "next_prob": row[nxt], "top2": top2,
            "advice": ADVICE[state], "matrix_row": row}

def main():
    limitup, wdate = get_limitup_from_width()
    today = datetime.now(BJ).strftime("%Y-%m-%d")
    src = f"market_width({wdate})" if limitup is not None else "N/A"
    if limitup is None:
        print("[INFO] market_width 不可用，实时计算涨停家数（约2-3分钟）...", flush=True)
        limitup = calc_limitup_live()
        src = "实时计算" if limitup is not None else "N/A"
    r = judge(limitup, today)
    if "--inline" in sys.argv:
        if r:
            print(f"🎭情绪:{r['state']}(涨停{r['limitup']})→明日{r['next']}概率{r['next_prob']}%")
        else:
            print("🎭情绪:数据缺失")
        return
    print(f"# 🎭 市场情绪状态与次日预判（{today}）\n")
    if not r:
        print("⏳ 涨停数据不可用（market_width_latest 缺失），情绪模块跳过")
        return
    print(f"**当日涨停**: {r['limitup']} 家（来源: {src}）")
    print(f"**情绪状态**: 【{r['state']}】")
    print(f"**次日预判**: 最可能【{r['next']}】（{r['next_prob']}%），次可能 {r['top2'][1][0]}（{r['top2'][1][1]}%）")
    print(f"**操作建议**: {r['advice']}")
    print("\n**转移矩阵**:")
    for k, v in r["matrix_row"].items():
        bar = "█" * (v // 5)
        print(f"  {k:<4} {v:>3}% {bar}")

if __name__ == "__main__":
    main()
