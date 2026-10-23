#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crowding_watch.py —— 抱团瓦解监控（拥挤度 + 盈利上修广度 + 卖方关注度）

背景与方法论来源：Eagle量化《第四阶段的第三部分：杀白马》(2026-10-23) 的跟踪清单，
把其中「基金 AI 持仓拥挤度 / 融资余额 / 分析师盈利上修广度 / 龙头放量滞涨」四条
转成可自动跑的量化指标。数据全部走 quant_scripts/fetch.py 统一取数层。

三块指标
--------
A 融资拥挤度    fetch.ext_em_margin —— 融资余额、占流通市值比、5/10 日融资净买入
                （占比 = 拥挤度绝对水平；净买入 = 拥挤度变化方向）
B 盈利上修广度  fetch.ext_em_report —— 同一股票年内研报 EPS(当年) 前后半中位数比较
                → 上修/下修家数 + 上修广度%；同时统计评级调高/调低/首次/维持
C 卖方关注度    fetch.ext_em_report —— 近 30 日研报篇数 vs 前 30 日（关注退潮 = 抱团松动前兆）

口径与局限（重要）
------------------
1. 两融数据 T+1 披露：最新一条通常比今天早 1 个交易日，报告里显式标注数据日。
2. 上修广度用「前后半中位数」抗单篇噪声；剔除 |变动|>100% 的小额基数失真样本；
   跨年不可比（eps_this 会随年份滚动），故只取与报告年度相同的研报。
3. 评级调高/调低条数极少（券商不愿公开下调，多用「维持」），**只作辅助不作主判据**。
4. 研报覆盖不等于真实盈利上修，只反映卖方观点边际变化。

用法
----
python3 quant_scripts/crowding_watch.py                        # 默认 AI 硬件链池 + 全市场广度
python3 quant_scripts/crowding_watch.py --no-market            # 只算池内，跳过全市场（快）
python3 quant_scripts/crowding_watch.py --pool-file quant_scripts/stock_pool.txt
python3 quant_scripts/crowding_watch.py --codes 300308,300502 --days 120
"""
import os
import sys
import json
import argparse
import statistics as st
import collections
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from fetch import ext_em_margin, ext_em_report
except Exception as _e:                                    # 兜底：不炸主流程
    ext_em_margin = ext_em_report = None
    _IMPORT_ERR = str(_e)
else:
    _IMPORT_ERR = ""

# AI 硬件链代表池（光模块 / PCB / 算力芯片 / 代工 / 服务器 / IDC）
DEFAULT_POOL = [
    "300308", "300502", "300394", "002281", "600487",      # 光模块 & 光纤
    "002463", "300476", "600183", "002916",                # PCB / 覆铜板
    "688256", "688041", "688008",                          # 算力芯片
    "601138", "000977", "000938",                          # 代工 / 服务器
    "300442", "603019", "002049",                          # IDC / 其他算力
]


def load_pool(path=None, codes=None):
    if codes:
        return [c.strip() for c in codes.replace("，", ",").split(",") if c.strip()]
    if path and os.path.exists(path):
        out = []
        for line in open(path, encoding="utf-8", errors="ignore"):
            c = line.strip().split(",")[0].strip()
            if c and c[0].isdigit():
                out.append(c.split(".")[0])
        if out:
            return out
    return DEFAULT_POOL


# ── A. 融资拥挤度 ────────────────────────────────────────────────
def margin_block(pool):
    m = ext_em_margin(pool) or {}
    rows = []
    for c in pool:
        v = m.get(c)
        if v:
            rows.append(v)
    if not rows:
        return {"rows": [], "date": "", "sum_bal": 0, "sum_net10": 0, "med_ratio": None}
    ratios = [r["bal_ratio"] for r in rows if r.get("bal_ratio") is not None]
    return {
        "rows": rows,
        "date": max(r["date"] for r in rows),
        "sum_bal": sum(r.get("margin_bal") or 0 for r in rows),
        "sum_net5": sum(r.get("net5") or 0 for r in rows),
        "sum_net10": sum(r.get("net10") or 0 for r in rows),
        "med_ratio": round(st.median(ratios), 2) if ratios else None,
        "max_ratio": max([(r["bal_ratio"], r.get("name"), r.get("code")) for r in rows
                          if r.get("bal_ratio") is not None], default=None),
    }


# ── B/C. 盈利上修广度 + 卖方关注度 ───────────────────────────────
def revision_stats(rows, year, end, recent=30, back=120):
    """边际盈利上修广度：近 recent 日研报 vs 之前 (recent, back] 日的 EPS(当年) 中位数比较。

    为什么不用「全年前后半」：半年跨度测的是累计上修幅度，会把 5~7 月的早期上修算进来，
    掩盖「最近一个月是否转为下修」。抱团瓦解要看的是**边际方向**，故取近窗口对基准窗口。
    """
    e = datetime.date.fromisoformat(end)
    d_recent = (e - datetime.timedelta(days=recent)).isoformat()
    d_back = (e - datetime.timedelta(days=back)).isoformat()

    def _bucket(lo, hi):                      # (lo, hi] 区间
        return [x for x in rows
                if x.get("eps_this") and x.get("code")
                and x.get("date", "")[:4] == str(year)
                and lo < x.get("date", "") <= hi]

    new_by = collections.defaultdict(list)
    old_by = collections.defaultdict(list)
    for x in _bucket(d_recent, end):
        new_by[x["code"]].append(x)
    for x in _bucket(d_back, d_recent):
        old_by[x["code"]].append(x)

    up = dn = flat = 0
    detail = []
    for code in set(new_by) & set(old_by):    # 两个窗口都有研报才可比
        a = st.median([x["eps_this"] for x in old_by[code]])
        b = st.median([x["eps_this"] for x in new_by[code]])
        if not a or a <= 0:
            continue
        chg = (b - a) / a * 100.0
        if abs(chg) > 100:                    # 小额基数失真，剔除
            continue
        name = new_by[code][-1].get("name")
        if chg > 1:
            up += 1
            detail.append((round(chg, 1), name, code))
        elif chg < -1:
            dn += 1
            detail.append((round(chg, 1), name, code))
        else:
            flat += 1
    tot = up + dn
    return {
        "up": up, "down": dn, "flat": flat,
        "breadth": round(100.0 * up / tot, 1) if tot else None,
        "covered": up + dn + flat,
        "only_recent": len(set(new_by) - set(old_by)),   # 新覆盖（base 期无研报）
        "no_recent": len(set(old_by) - set(new_by)),     # 关注退潮（近期无研报）
        "window": [d_recent, end, d_back],
        "detail_up": sorted([d for d in detail if d[0] > 0], reverse=True)[:10],
        "detail_down": sorted([d for d in detail if d[0] < 0])[:10],
    }


def rating_stats(rows):
    c = collections.Counter(x.get("rating_change_text") or "未标注" for x in rows)
    return {k: c.get(k, 0) for k in ("调高", "调低", "首次", "维持", "未标注")}


def coverage_stats(rows, end, win=30):
    """近 win 日 vs 前 win 日 研报篇数（卖方关注度变化）。"""
    e = datetime.date.fromisoformat(end)
    a1 = (e - datetime.timedelta(days=win)).isoformat()
    a2 = (e - datetime.timedelta(days=2 * win)).isoformat()
    cur = sum(1 for x in rows if a1 < x.get("date", "") <= end)
    prev = sum(1 for x in rows if a2 < x.get("date", "") <= a1)
    return {"cur": cur, "prev": prev,
            "chg_pct": round(100.0 * (cur - prev) / prev, 1) if prev else None}


def collect_market_report(end, since, max_pages=80, page_size=100):
    """全市场个股研报（分页拉全）。"""
    out, pg = [], 1
    while pg <= max_pages:
        r = ext_em_report(begin=since, end=end, page=pg, page_size=page_size) or {}
        d = r.get("data") or []
        if not d:
            break
        out.extend(d)
        if r.get("total_page") and pg >= int(r["total_page"]):
            break
        pg += 1
    return out


# ── 渲染 ────────────────────────────────────────────────────────
def fmt_yi(v):
    return "—" if v is None else "%.2f 亿" % (v / 1e8)


def render(res, args):
    pool, mb = res["pool"], res["margin"]
    L = []
    L.append("# 拥挤度监控（抱团瓦解）· %s" % res["date"])
    L.append("")
    L.append("> 数据源：东财两融明细 + 东财研报（经 fetch.py 统一取数层）｜口径见脚本 docstring")
    L.append("> 池：%d 只（%s）｜行情/两融数据日 %s（两融 T+1 披露）" % (
        len(pool), args.pool_name, mb.get("date") or "—"))
    L.append("")

    L.append("## 一、融资拥挤度（A）")
    L.append("")
    if mb["rows"]:
        L.append("| 代码 | 名称 | 收盘 | 当日 | 融资余额 | 占流通市值 | 5日净买入 | 10日净买入 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in sorted(mb["rows"], key=lambda z: -(z.get("bal_ratio") or 0)):
            L.append("| %s | %s | %.2f | %+.2f%% | %s | %.2f%% | %s | %s |" % (
                r["code"], r.get("name") or "", r.get("close") or 0, r.get("pct") or 0,
                fmt_yi(r.get("margin_bal")), r.get("bal_ratio") or 0,
                fmt_yi(r.get("net5")), fmt_yi(r.get("net10"))))
        L.append("")
        L.append("- 池内融资余额合计 **%s**；5 日净买入合计 **%s**、10 日 **%s**" % (
            fmt_yi(mb["sum_bal"]), fmt_yi(mb["sum_net5"]), fmt_yi(mb["sum_net10"])))
        L.append("- 融资余额占流通市值比中位数 **%.2f%%**%s" % (
            mb["med_ratio"] or 0,
            ("；最高 %s %s %.2f%%" % (mb["max_ratio"][1], mb["max_ratio"][2], mb["max_ratio"][0]))
            if mb["max_ratio"] else ""))
        direction = "融资盘在撤（拥挤度下降）" if mb["sum_net10"] < 0 else "融资盘仍在加（拥挤度上升）"
        L.append("- 结论：**%s**" % direction)
    else:
        L.append("_两融数据未取到（接口异常或代码不在两融标的池）_")
    L.append("")

    L.append("## 二、盈利上修广度（B）")
    L.append("")
    for tag, key in (("池内", "rev_pool"), ("全市场", "rev_market")):
        s = res.get(key) or {}
        if not s.get("up") and not s.get("down"):
            L.append("- %s：样本不足" % tag)
            continue
        L.append("- **%s**：上修 %d / 下修 %d / 持平 %d → 边际上修广度 **%s%%**（可比 %d 只；新覆盖 %d、近期无研报 %d）" % (
            tag, s["up"], s["down"], s["flat"], s["breadth"], s["covered"],
            s.get("only_recent", 0), s.get("no_recent", 0)))
    if res.get("rev_market", {}).get("detail_down"):
        L.append("")
        L.append("  全市场下修幅度前列：" + "、".join(
            "%s(%+.0f%%)" % (d[1], d[0]) for d in res["rev_market"]["detail_down"][:6]))
    L.append("")

    L.append("## 三、评级变动与卖方关注度（C）")
    L.append("")
    rs = res.get("rating") or {}
    L.append("- 池内近 %d 日研报评级变动：调高 %d / 调低 %d / 首次 %d / 维持 %d" % (
        args.days, rs.get("调高", 0), rs.get("调低", 0), rs.get("首次", 0), rs.get("维持", 0)))
    cv = res.get("coverage") or {}
    if cv.get("chg_pct") is not None:
        L.append("- 池内研报篇数：近 30 日 %d 篇 vs 前 30 日 %d 篇（%+.1f%%）" % (
            cv["cur"], cv["prev"], cv["chg_pct"]))
    L.append("- 注：券商极少公开下调评级（多用「维持」），调高/调低条数只作辅助，不作主判据。")
    L.append("")

    L.append("## 四、综合判读")
    L.append("")
    L.append(res["verdict"])
    L.append("")
    L.append("---")
    L.append("_方法来源：Eagle量化《第四阶段的第三部分：杀白马》跟踪清单的量化落地版本。_")
    return "\n".join(L)


def verdict(res):
    parts = []
    mb = res.get("margin") or {}
    if mb.get("med_ratio") is not None:
        r = mb["med_ratio"]
        lvl = "偏高（拥挤）" if r >= 4 else ("中等" if r >= 2 else "偏低")
        parts.append("融资拥挤度 %.2f%%（%s）" % (r, lvl))
    if mb.get("sum_net10") is not None:
        parts.append("10 日融资净买入 %s（%s）" % (
            fmt_yi(mb["sum_net10"]),
            "融资盘撤出=拥挤交易在瓦解" if mb["sum_net10"] < 0 else "融资盘流入=拥挤度仍在上升"))
    mk = res.get("rev_market") or {}
    if mk.get("breadth") is not None:
        parts.append("全市场盈利上修广度 %s%%（%s）" % (
            mk["breadth"],
            "预测在下修" if mk["breadth"] < 50 else "预测仍在上修"))
    cv = res.get("coverage") or {}
    if cv.get("chg_pct") is not None and cv["chg_pct"] < -30:
        parts.append("卖方关注度明显退潮（研报 -%.0f%%）" % abs(cv["chg_pct"]))
    if not parts:
        return "_数据不足，无法判读_"
    head = ""
    if mb.get("sum_net10", 0) < 0 and (mk.get("breadth") or 100) < 50:
        head = "**价、量、预期三者同向走弱** —— 抱团瓦解进行时，不是启动初期。\n\n"
    return head + "\n".join("- " + p for p in parts)


def main():
    ap = argparse.ArgumentParser(description="抱团瓦解监控：拥挤度 + 盈利上修广度 + 卖方关注度")
    ap.add_argument("--codes", help="逗号分隔代码，覆盖默认池")
    ap.add_argument("--pool-file", help="股票池文件（首列代码）")
    ap.add_argument("--pool-name", default="AI 硬件链默认池")
    ap.add_argument("--days", type=int, default=180, help="研报回溯天数（默认 180）")
    ap.add_argument("--recent", type=int, default=30, help="边际窗口：近 N 日（默认 30）")
    ap.add_argument("--back", type=int, default=120, help="基准窗口外沿：前 N 日（默认 120）")
    ap.add_argument("--no-market", action="store_true", help="跳过全市场广度（更快）")
    ap.add_argument("--outdir", default="outputs")
    ap.add_argument("--date", help="报告日期 YYYY-MM-DD（默认今天北京）")
    args = ap.parse_args()

    if not ext_em_margin:
        print("::error:: fetch.py 导入失败：%s" % _IMPORT_ERR)
        return 1

    today = args.date or (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
    year = today[:4]
    since = (datetime.date.fromisoformat(today) - datetime.timedelta(days=args.days)).isoformat()
    pool = load_pool(args.pool_file, args.codes)
    if args.pool_file:
        args.pool_name = os.path.basename(args.pool_file)

    res = {"date": today, "pool": pool, "pool_name": args.pool_name}
    res["margin"] = margin_block(pool)

    rp = ext_em_report(pool, begin=since, end=today) or {}
    rows_pool = rp.get("data") or []
    res["rev_pool"] = revision_stats(rows_pool, year, today, args.recent, args.back)
    res["rating"] = rating_stats(rows_pool)
    res["coverage"] = coverage_stats(rows_pool, today, win=30)

    if not args.no_market:
        print("[crowding] 拉全市场研报 …")
        rows_mkt = collect_market_report(today, since)
        print("[crowding] 全市场研报 %d 篇" % len(rows_mkt))
        res["rev_market"] = revision_stats(rows_mkt, year, today, args.recent, args.back)
    res["verdict"] = verdict(res)

    os.makedirs(args.outdir, exist_ok=True)
    md = render(res, args)
    p_md = os.path.join(args.outdir, "拥挤度监控_%s.md" % today)
    p_js = os.path.join(args.outdir, "拥挤度监控_%s.json" % today)
    open(p_md, "w", encoding="utf-8").write(md)
    open(p_js, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(md)
    print("\n[saved] %s\n[saved] %s" % (p_md, p_js))
    return 0


if __name__ == "__main__":
    sys.exit(main())
