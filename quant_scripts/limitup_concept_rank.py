#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""limitup_concept_rank.py —— 涨停概念排行（2026-09-25）

灵感来源：曾星智《中秋快乐及短线核心方法》（2026-09-25）
  其方法第①-②步 =「汇总当日全部涨停股 → 按概念归类 → 涨停家数最多的即热点概念」。
  体系此前只有 hot_emotion（涨停总数/连板梯队），**缺"按概念聚合排行"这一步**（自动化最大的缺口）。

本脚本将其自动化：
  ① 批量取全主板最近 5 日K线（40只/次）→ 算当日涨跌幅 + 连板数
  ② 筛涨停（主板 ≥9.8%，剔除 ST/退市）
  ③ 读 sector_component_em.json（999板块/4487只题材映射）→ 每只股票的题材
  ④ 按题材聚合 → 涨停家数 / 连板家数 排行
  ⑤ 输出 outputs/涨停概念排行_{date}.md + 涨停概念排行_latest.json

用法：python3 quant_scripts/limitup_concept_rank.py [--days 5] [--top 20] [--date YYYY-MM-DD]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--date", default=None)
    ap.add_argument("--outdir", default=None)
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
    print(f"[INFO] 主板池 {len(pool)} 只，取最近 {a.days} 日K线...", flush=True)
    km = fetch_all([x[0] for x in pool], a.days)
    print(f"[INFO] 取到 {len(km)} 只", flush=True)

    code_sector, code_name, sec_date = load_sector()
    print(f"[INFO] 题材映射 {len(code_sector)} 只（更新于 {sec_date}）", flush=True)

    # 涨停 + 连板
    ups = []
    for wcode, c6, nm in pool:
        bars = km.get(wcode)
        if not bars or len(bars) < 2:
            continue
        if bars[-1][0] != today:      # 最新K线须为当日（非当日=停牌/未更新）
            continue
        chg = (bars[-1][1] / bars[-2][1] - 1) * 100 if bars[-2][1] else 0
        if chg < LIMIT_UP:
            continue
        # 连板数：今日已计 1，再向前逐日数（⚠️须从"昨日"开始，否则今日被重复计算）
        lb = 1
        k = len(bars) - 2
        while k >= 1:
            r = (bars[k][1] / bars[k - 1][1] - 1) * 100 if bars[k - 1][1] else 0
            if r >= LIMIT_UP:
                lb += 1
                k -= 1
            else:
                break
        ups.append({"code": wcode, "c6": c6, "name": nm, "chg": round(chg, 2),
                    "lianban": lb, "price": bars[-1][1]})
    print(f"[INFO] 涨停 {len(ups)} 只（其中连板 {sum(1 for u in ups if u['lianban']>=2)} 只）", flush=True)

    # 概念聚合
    agg = defaultdict(lambda: {"n": 0, "lb": 0, "stocks": []})
    for u in ups:
        secs = code_sector.get(u["c6"]) or code_sector.get(u["code"]) or []
        for s in secs:
            agg[s]["n"] += 1
            if u["lianban"] >= 2:
                agg[s]["lb"] += 1
            agg[s]["stocks"].append(u)
    rank = sorted(agg.items(), key=lambda kv: (-kv[1]["n"], -kv[1]["lb"]))[:a.top]
    # 只保留 ≥2 只涨停的概念（单只=噪声）
    rank = [(k, v) for k, v in rank if v["n"] >= 2]

    L = [f"# 🔥 涨停概念排行 {today}", "",
         f"> 数据源：全主板 {len(pool)} 只（westock 日线）｜题材映射 {len(code_sector)} 只（{sec_date}）",
         f"> 当日涨停 **{len(ups)}** 只｜连板 **{sum(1 for u in ups if u['lianban']>=2)}** 只",
         "> 方法参考：曾星智《短线核心方法》第①-②步（涨停家数最多的概念 = 当日热点）", "",
         "## 概念排行（按涨停家数）", "",
         "| # | 概念 | 涨停家数 | 连板家数 | 代表龙头（连板数） |", "|---|---|---|---|---|"]
    for i, (s, v) in enumerate(rank, 1):
        tops = sorted(v["stocks"], key=lambda x: -x["lianban"])[:4]
        names = "、".join(f"{t['name']}({t['lianban']}板)" if t["lianban"] >= 2 else t["name"] for t in tops)
        L.append(f"| {i} | **{s}** | {v['n']} | {v['lb']} | {names} |")
    L += ["", "## 涨停明细（按连板数）", "",
          "| 代码 | 名称 | 连板 | 涨幅% | 所属题材 |", "|---|---|---|---|---|"]
    for u in sorted(ups, key=lambda x: (-x["lianban"], -x["chg"])):
        secs = code_sector.get(u["c6"]) or []
        L.append(f"| {u['code']} | {u['name']} | {u['lianban']} | {u['chg']} | {'/'.join(secs[:4])} |")
    L += ["", "---", "⚠️ 概念分类来自东财板块成分（一票可属多个概念），" 
          "单只涨停的概念已过滤；此为**统计口径**，实际热点需结合新闻面人工复核（方法第③步）。"]
    md = "\n".join(L)
    mp = os.path.join(outdir, f"涨停概念排行_{today}.md")
    open(mp, "w", encoding="utf-8").write(md)
    json.dump({"date": today, "limitup_total": len(ups),
               "lianban_total": sum(1 for u in ups if u["lianban"] >= 2),
               "concept_rank": [{"concept": k, "n": v["n"], "lb": v["lb"],
                                 "stocks": [x["name"] for x in v["stocks"]]} for k, v in rank],
               "stocks": ups},
              open(os.path.join(outdir, "涨停概念排行_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(md)
    print(f"\n[OK] {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
