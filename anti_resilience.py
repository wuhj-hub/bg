#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抗跌性过滤层（anti_resilience.py · 2026-08-12 落地，源自OPPO笔记"熊市选股先看抗跌性"）
====================================================================================
对候选池计算「20日相对大盘超额收益」（个股20日涨幅 - 上证20日涨幅），
按抗跌性分级：超额≥0 抗跌强（熊市优先）/ 0~-5 中性 / <-5 弱势回避。

用法：
    python3 anti_resilience.py [--pool 候选池文件|--date YYYY-MM-DD]
    → 输出 outputs/抗跌性排序_{date}.md + outputs/anti_resilience_latest.json

数据源：westock 批量 kline（100只/批，limit 21 → 最新 vs 20日前收盘）
与体系联动：复盘③.5 三阶漏斗候选、盘前④ 个股层引用（熊市/弱势市过滤优先）
"""
import json, os, re, subprocess, sys, time
from datetime import datetime, timedelta

POOL_FILES = ["stock_pool.txt", "quant_scripts/stock_pool.txt", "outputs/stock_pool.txt"]


def run(args):
    r = subprocess.run(["npx", "-y", "westock-data-skillhub@1.0.3"] + args,
                       capture_output=True, text=True, timeout=120)
    return r.stdout


def parse_batch_kline(txt):
    """批量K线：symbol|date|open|last|high...（降序，最新在前）→ {code: {date: last}}"""
    out = {}
    for ln in txt.splitlines():
        p = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(p) >= 4 and re.match(r"^(sh|sz)\d{6}$", p[0]) and re.match(r"^\d{4}-\d{2}-\d{2}$", p[1]):
            out.setdefault(p[0], {})[p[1]] = float(p[3])
    return out


def load_pool(path):
    codes = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        m = re.search(r"(sh|sz)\d{6}", ln)
        if m:
            codes.append(m.group(0))
    return codes


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    if len(sys.argv) > 1 and re.match(r"^\d{4}-\d{2}-\d{2}$", sys.argv[1]):
        today = sys.argv[1]
    pool_path = None
    if "--pool" in sys.argv:
        pool_path = sys.argv[sys.argv.index("--pool") + 1]
    else:
        for f in POOL_FILES:
            if os.path.exists(f):
                pool_path = f
                break
    if not pool_path:
        print("[ERR] 未找到候选池（stock_pool.txt），用 --pool 指定")
        return

    codes = load_pool(pool_path)
    if not codes:
        print("[ERR] 候选池为空")
        return
    print(f"[INFO] 候选池 {len(codes)} 只：{pool_path}")

    # 上证20日涨跌幅基准（单只K线无symbol列：date|open|last|high）
    sh_last = {}
    for ln in run(["kline", "sh000001", "--period", "day", "--limit", "21"]).splitlines():
        p = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(p) >= 4 and re.match(r"^\d{4}-\d{2}-\d{2}$", p[0]):
            sh_last[p[0]] = float(p[2])
    sh_rows = sorted(sh_last.items())
    if len(sh_rows) < 21:
        print("[ERR] 上证数据不足21日")
        return
    sh_chg = (sh_rows[-1][1] - sh_rows[-21][1]) / sh_rows[-21][1] * 100

    # 分批批量拉候选池K线
    results = []
    for i in range(0, len(codes), 100):
        batch = codes[i:i + 100]
        txt = run(["kline", ",".join(batch), "--period", "day", "--limit", "21"])
        kd = parse_batch_kline(txt)
        for c in batch:
            rows = sorted(kd.get(c, {}).items())
            if len(rows) < 21:
                continue
            chg = (rows[-1][1] - rows[-21][1]) / rows[-21][1] * 100
            excess = chg - sh_chg
            if excess >= 0:
                level = "🛡️抗跌强"
            elif excess >= -5:
                level = "⚖️中性"
            else:
                level = "❌弱势"
            results.append({"code": c, "chg20": round(chg, 2), "sh_chg20": round(sh_chg, 2),
                            "excess": round(excess, 2), "level": level})
        time.sleep(1)

    results.sort(key=lambda r: -r["excess"])
    strong = [r for r in results if r["level"] == "🛡️抗跌强"]
    weak = [r for r in results if r["level"] == "❌弱势"]

    # 输出 md
    md = []
    md.append(f"# 🛡️ 抗跌性排序（20日相对大盘超额收益）· {today}\n")
    md.append(f"> 基准：上证20日涨幅 **{sh_chg:+.2f}%** ｜ 候选池 {len(results)} 只（有效）｜ "
              f"抗跌强 {len(strong)} / 中性 {len(results)-len(strong)-len(weak)} / 弱势 {len(weak)}\n")
    md.append(f"> 逻辑：熊市选股先看抗跌性（超额≥0优先），再过滤结构分型（2026-08-12落地，源自OPPO笔记）\n")
    md.append("\n## 🛡️ 抗跌强（超额≥0，熊市优先）\n")
    md.append("| 代码 | 20日涨幅 | 超额收益 | 等级 |")
    md.append("|:----|:----|:----|:----|")
    for r in strong[:20]:
        md.append(f"| {r['code']} | {r['chg20']:+.2f}% | **{r['excess']:+.2f}%** | {r['level']} |")
    md.append("\n## ❌ 弱势（超额<-5%，回避）\n")
    md.append("| 代码 | 20日涨幅 | 超额收益 |")
    md.append("|:----|:----|:----|")
    for r in weak[:15]:
        md.append(f"| {r['code']} | {r['chg20']:+.2f}% | {r['excess']:+.2f}% |")
    md.append("\n---\n⚠️ 基于公开数据整理，不构成投资建议。\n")

    os.makedirs("outputs", exist_ok=True)
    fn = f"outputs/抗跌性排序_{today}.md"
    with open(fn, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    with open("outputs/anti_resilience_latest.json", "w", encoding="utf-8") as f:
        json.dump({"date": today, "sh_chg20": sh_chg, "strong": strong[:20], "weak": weak[:15]},
                  f, ensure_ascii=False, indent=2)
    print(f"[OK] {fn}（有效{len(results)}只/抗跌强{len(strong)}/弱势{len(weak)}）")


if __name__ == "__main__":
    main()
