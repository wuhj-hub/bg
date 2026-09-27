#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""limitup_concept_rank.py —— 涨停概念排行 · 板块分级 · 晋级率（v2, 2026-09-27）

灵感来源：
  ① 曾星智《中秋快乐及短线核心方法》(2026-09-25)
       汇总当日全部涨停 → 按概念归类 → 涨停家数最多者即当日热点概念。
  ② 《热板选龙头、先锋、中军战法》(指标乐园, 2026-09-27) —— 板块三级分类：
       主线板块：涨停≥8家 + 梯队完整 + 晋级率≥35%   → 重点布局
       支线板块：涨停3-7家 + 晋级率20%-35%           → 小仓试错
       一日游题材：涨停≤2家 或 晋级率<20%            → 直接放弃
  ③ 曾星智「短线备选池·晋级率」二期（xzz_shortlist）：晋级率=次日继续涨停比例，
       可作情绪温度计（首板晋级率>22% 题材活跃 / <13% 情绪退潮）。

v2 在 v1（涨停家数 / 连板家数排行）基础上新增：
  ★ 概念晋级率 = 该概念内「今日连板家数(≥2板)」/「该概念昨日涨停家数」
  ★ 板块三级自动分档（主线 / 支线 / 一日游），阈值可调 (--main-zt/--main-jj/--sub-jj)
  ★ 梯队指标：最高连板数 maxlb / 首板数 first
  ★ 全市场情绪刻度：首板晋级率 + 连板晋级率（情绪温度计）

⚠️ 口径说明（沿用 v1）：概念分类来自东财板块成分，一票可属多个概念（会放大家数），
   晋级率分子=今日连板家数（连板必为"昨涨停且今涨停"）；分母=该概念昨日涨停家数。
   样本过小(昨日涨停<3)时晋级率噪声大，已在输出中标注 "!"。

用法：
  python3 quant_scripts/limitup_concept_rank.py [--days 6] [--top 20] [--date YYYY-MM-DD]
         [--main-zt 8] [--main-jj 35] [--sub-jj 20] [--max-stocks N] [--outdir DIR]
"""
import os, re, sys, csv, json, time, argparse, subprocess
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

BJ = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
LIMIT_UP = 9.8          # 主板涨停阈值（含四舍五入误差）
CHUNK = 40
WORKERS = 4

# 情绪刻度阈值（参考 xzz_shortlist 二期：首板晋级率 13%~18% 为常态带）
JJ_HOT = 22.0           # 首板晋级率 ≥22% → 题材接力活跃
JJ_COLD = 13.0          # 首板晋级率 <13%  → 情绪退潮


def cli(args, timeout=180):
    for _ in range(3):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            out = r.stdout or ""
            if out.strip() and "执行失败" not in out:
                return out
        except Exception:
            pass
        time.sleep(2)
    return ""


def parse_batch(txt):
    """批量 kline 长表 → {symbol: [(date, close), ...]}（升序）"""
    out = defaultdict(list)
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        p = [q.strip() for q in s.strip("|").split("|")]
        if "date" in p:
            header = p
            continue
        if not header or "---" in p[0] or "symbol" not in header:
            continue
        try:
            sym = p[0]
            if not re.match(r"^(sh|sz)\d{6}$", sym):
                continue
            out[sym].append((p[header.index("date")], float(p[header.index("last")])))
        except Exception:
            pass
    for k in out:
        out[k].sort()
    return out


def fetch_all(codes, days):
    """批量取K线"""
    res = {}
    batches = [codes[i:i + CHUNK] for i in range(0, len(codes), CHUNK)]
    def one(b):
        return parse_batch(cli(["kline", ",".join(b), "--period", "day",
                                "--limit", str(days), "--fq", "qfq"]))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for d in ex.map(one, batches):
            res.update(d)
    return res


def load_sector():
    for p in (os.path.join(BASE, "outputs/sector_component_em.json"),
              os.path.join(BASE, "sector_component_em.json")):
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                return d.get("code_sector", {}), d.get("code_name", {}), d.get("date", "")
            except Exception:
                continue
    return {}, {}, ""


def classify(zt, prev_zt, jj, a):
    """板块三级分档。jj=晋级率(%)或None；prev_zt=昨日涨停家数"""
    if zt <= 2:
        return "一日游"
    if jj is not None and jj < a.sub_jj:
        return "一日游"
    if prev_zt == 0:                                  # 今日新启动，无昨日样本
        return "主线" if zt >= a.main_zt else "支线"
    if zt >= a.main_zt and jj is not None and jj >= a.main_jj:
        return "主线"
    return "支线"


GRADE_ORDER = {"主线": 0, "支线": 1, "一日游": 2}


def fmt_jj(jj, prev_zt):
    if jj is None:
        return "—  "
    mark = "!" if prev_zt < 3 else ""
    return f"{jj:.0f}%{mark}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=6)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--date", default=None)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--main-zt", type=int, default=8, dest="main_zt")   # 主线涨停家数下限
    ap.add_argument("--main-jj", type=float, default=35.0, dest="main_jj")  # 主线晋级率下限
    ap.add_argument("--sub-jj", type=float, default=20.0, dest="sub_jj")    # 支线晋级率下限
    ap.add_argument("--max-stocks", type=int, default=0, dest="max_stocks", help="调试：仅取前N只")
    a = ap.parse_args()
    outdir = a.outdir or os.path.join(BASE, "outputs")
    os.makedirs(outdir, exist_ok=True)
    today = a.date or datetime.now(BJ).strftime("%Y-%m-%d")

    # 股票池
    pool = []
    mb = None
    for p in (os.path.join(BASE, "all_mainboard.csv"), "all_mainboard.csv"):
        if os.path.exists(p):
            mb = p
            break
    if not mb:
        print("[ERR] 缺 all_mainboard.csv")
        return 1
    with open(mb, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = (r.get("code") or "").strip()
            n = (r.get("name") or "").strip()
            if not re.match(r"^\d{6}$", c):
                continue
            if c.startswith(("688", "300", "301")) or "ST" in n.upper() or "退" in n:
                continue
            pool.append((("sh" if c[0] == "6" else "sz") + c, c, n))
    if a.max_stocks:
        pool = pool[:a.max_stocks]
    print(f"[INFO] 主板池 {len(pool)} 只，取最近 {a.days} 日K线...", flush=True)
    km = fetch_all([x[0] for x in pool], a.days)
    print(f"[INFO] 取到 {len(km)} 只", flush=True)

    # 数据日期自适应：未显式指定日期且当日无行情（周末/节假日/数据滞后）→ 回退截面最大日期
    if not a.date:
        dates = [bars[-1][0] for bars in km.values() if bars]
        if dates:
            latest = max(set(dates), key=dates.count)
            if latest != today:
                print(f"[WARN] {today} 无行情（周末/节假日/数据滞后），自动回退到 {latest}", flush=True)
                today = latest

    code_sector, code_name, sec_date = load_sector()
    print(f"[INFO] 题材映射 {len(code_sector)} 只（更新于 {sec_date}）", flush=True)

    # 逐股：计算窗口内每日涨停标记 lim[] 与连板数 lb[]（升序），取今日/昨日截面
    ups = []          # 今日涨停
    prev_zt_codes = set()   # 昨日涨停（用于分母）
    prev_first_codes = set()  # 昨日首板（用于市场首板晋级率）
    prev_first_jinji = 0
    for wcode, c6, nm in pool:
        bars = km.get(wcode)
        if not bars or len(bars) < 4:
            continue
        if bars[-1][0] != today:      # 最新K线须为当日（非当日=停牌/未更新）
            continue
        closes = [b[1] for b in bars]
        n = len(bars)
        lim = [False] * n
        for i in range(1, n):
            if closes[i - 1] > 0 and (closes[i] / closes[i - 1] - 1) * 100 >= LIMIT_UP:
                lim[i] = True
        lb = [0] * n
        for i in range(1, n):
            lb[i] = (lb[i - 1] + 1) if (lim[i] and lim[i - 1]) else (1 if lim[i] else 0)
        # 昨日截面
        if lim[-2]:
            prev_zt_codes.add(c6)
            if lb[-2] == 1:
                prev_first_codes.add(c6)
                if lim[-1]:
                    prev_first_jinji += 1
        # 今日截面
        if not lim[-1]:
            continue
        chg = (closes[-1] / closes[-2] - 1) * 100 if closes[-2] else 0
        ups.append({"code": wcode, "c6": c6, "name": nm, "chg": round(chg, 2),
                    "lianban": lb[-1], "price": closes[-1]})

    n_lb = sum(1 for u in ups if u["lianban"] >= 2)
    n_first = sum(1 for u in ups if u["lianban"] == 1)
    print(f"[INFO] 涨停 {len(ups)} 只（连板 {n_lb} / 首板 {n_first}）｜昨日涨停 {len(prev_zt_codes)} 只", flush=True)

    # 市场情绪刻度
    prev_zt_n = len(prev_zt_codes)
    mkt_lb_jj = (100.0 * n_lb / prev_zt_n) if prev_zt_n else None       # 连板晋级率
    mkt_first_jj = (100.0 * prev_first_jinji / len(prev_first_codes)) if prev_first_codes else None
    if mkt_first_jj is None:
        mood = "—"
    elif mkt_first_jj >= JJ_HOT:
        mood = "🔥 活跃（题材接力强）"
    elif mkt_first_jj < JJ_COLD:
        mood = "🧊 退潮（谨慎打板）"
    else:
        mood = "⚖️ 中性"

    # 概念聚合（今日涨停 + 昨日涨停 + 晋级）
    agg = defaultdict(lambda: {"n": 0, "lb": 0, "first": 0, "maxlb": 0,
                               "prev": 0, "stocks": []})
    for u in ups:
        secs = code_sector.get(u["c6"]) or code_sector.get(u["code"]) or []
        for s in secs:
            g = agg[s]
            g["n"] += 1
            if u["lianban"] >= 2:
                g["lb"] += 1
            else:
                g["first"] += 1
            g["maxlb"] = max(g["maxlb"], u["lianban"])
            g["stocks"].append(u)
    # 昨日涨停回填（分母）—— 概念可含未在今日涨停池的昨日涨停股
    for c6 in prev_zt_codes:
        secs = code_sector.get(c6) or []
        for s in secs:
            agg[s]["prev"] += 1

    rank = []
    for s, v in agg.items():
        if v["n"] < 2:                      # 单只涨停=噪声（沿用 v1）
            continue
        jj = (100.0 * v["lb"] / v["prev"]) if v["prev"] else None
        v["jj"] = jj
        v["grade"] = classify(v["n"], v["prev"], jj, a)
        rank.append((s, v))
    rank.sort(key=lambda kv: (GRADE_ORDER.get(kv[1]["grade"], 9),
                              -kv[1]["n"], -(kv[1]["jj"] or -1), -kv[1]["lb"]))
    rank = rank[:a.top]

    n_main = sum(1 for _, v in rank if v["grade"] == "主线")
    n_sub = sum(1 for _, v in rank if v["grade"] == "支线")
    n_day = sum(1 for _, v in rank if v["grade"] == "一日游")

    # ── Markdown ──
    L = [f"# 🔥 涨停概念排行 · 板块分级 {today}", "",
         f"> 数据源：全主板 {len(pool)} 只（westock 日线）｜题材映射 {len(code_sector)} 只（{sec_date}）",
         f"> 当日涨停 **{len(ups)}** 只｜连板 **{n_lb}** 只｜首板 **{n_first}** 只", "",
         "## 📊 市场情绪刻度",
         f"- 昨日涨停 **{prev_zt_n}** 只 → 今日连板 **{n_lb}** 只，**连板晋级率 {mkt_lb_jj:.0f}%**" if prev_zt_n else "- 连板晋级率 —",
         f"- 昨日首板 {len(prev_first_codes)} 只 → 今日晋级 {prev_first_jinji} 只，**首板晋级率 {mkt_first_jj:.0f}%**" if prev_first_codes else "- 首板晋级率 —",
         f"- 情绪档位：**{mood}**（首板晋级率阈值 活跃≥{JJ_HOT:.0f}% / 退潮<{JJ_COLD:.0f}%，参考 xzz 二期）", "",
         "## 🧭 板块分级",
         f"| 级别 | 概念数 | 判定标准 |",
         "|---|---|---|",
         f"| 🔴 主线 | {n_main} | 涨停≥{a.main_zt}家 且 晋级率≥{a.main_jj:.0f}% |",
         f"| 🟡 支线 | {n_sub} | 涨停3-7家 或 晋级率{a.sub_jj:.0f}-{a.main_jj:.0f}% |",
         f"| ⚪ 一日游 | {n_day} | 涨停≤2家 或 晋级率<{a.sub_jj:.0f}% |", "",
         "## 概念排行（按级别 + 涨停家数）", "",
         "| 级别 | 概念 | 涨停 | 连板 | 昨日涨停 | 晋级率 | 最高板 | 首板 | 代表龙头（连板数） |",
         "|---|---|---|---|---|---|---|---|---|"]
    icon = {"主线": "🔴", "支线": "🟡", "一日游": "⚪"}
    for s, v in rank:
        tops = sorted(v["stocks"], key=lambda x: -x["lianban"])[:4]
        names = "、".join(f"{t['name']}({t['lianban']}板)" if t["lianban"] >= 2 else t["name"] for t in tops)
        L.append(f"| {icon.get(v['grade'],'')} {v['grade']} | **{s}** | {v['n']} | {v['lb']} | "
                 f"{v['prev']} | {fmt_jj(v['jj'], v['prev'])} | {v['maxlb']} | {v['first']} | {names} |")
    L += ["", "## 涨停明细（按连板数）", "",
          "| 代码 | 名称 | 连板 | 涨幅% | 所属题材 |", "|---|---|---|---|---|"]
    for u in sorted(ups, key=lambda x: (-x["lianban"], -x["chg"])):
        secs = code_sector.get(u["c6"]) or []
        L.append(f"| {u['code']} | {u['name']} | {u['lianban']} | {u['chg']} | {'/'.join(secs[:4])} |")
    L += ["", "---",
          "⚠️ 概念分类来自东财板块成分（一票可属多个概念，家数会放大）；晋级率 = 今日连板家数 / 昨日涨停家数，"
          "昨日涨停<3只的概念标注 `!`（样本小、噪声大）。此为**统计口径**，实际热点须结合新闻面人工复核（方法第③步）。"]
    md = "\n".join(L)
    mp = os.path.join(outdir, f"涨停概念排行_{today}.md")
    open(mp, "w", encoding="utf-8").write(md)

    json.dump({"date": today,
               "limitup_total": len(ups), "lianban_total": n_lb, "first_total": n_first,
               "prev_limitup_total": prev_zt_n,
               "market": {"lianban_jinji_rate": round(mkt_lb_jj, 1) if mkt_lb_jj is not None else None,
                          "first_jinji_rate": round(mkt_first_jj, 1) if mkt_first_jj is not None else None,
                          "mood": mood},
               "grade_summary": {"main": n_main, "sub": n_sub, "oneday": n_day},
               "concept_rank": [{"concept": k, "n": v["n"], "lb": v["lb"], "prev_zt": v["prev"],
                                 "jinji_rate": round(v["jj"], 1) if v["jj"] is not None else None,
                                 "maxlb": v["maxlb"], "first": v["first"], "grade": v["grade"],
                                 "stocks": [x["name"] for x in v["stocks"]]} for k, v in rank],
               "stocks": ups},
              open(os.path.join(outdir, "涨停概念排行_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(md)
    print(f"\n[OK] {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
