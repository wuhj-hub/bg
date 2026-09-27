#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""limitup_concept_rank.py —— 热板作战面板 v3（2026-09-27）

灵感来源：
  ① 曾星智《中秋快乐及短线核心方法》(2026-09-25)：汇总涨停 → 按概念归类 → 涨停家数最多者=热点。
  ② 《热板选龙头、先锋、中军战法》(指标乐园, 2026-09-27)：
       模块一 板块热度筛选（分级）→ 模块二 龙头先锋识别（五步法）→ 模块三 中军配置。
       主线：涨停≥8家 + 梯队完整 + 晋级率≥35% / 支线：3-7家 + 20-35% / 一日游：≤2家 或 <20%
       龙头五步法：启动最早 / 涨幅最大 / 封单最强(封单/流通≥5%) / 带动性强 / 辨识度最高
       中军：板块内市值前3、沿5/10日线慢涨、少连板、调整抗跌（趋势压舱石）
  ③ 曾星智「短线备选池·晋级率」二期：晋级率=次日继续涨停比例，作情绪温度计。

版本演进：
  v1 (2026-09-25) 涨停家数 / 连板家数排行
  v2 (2026-09-27) ★概念晋级率 ★板块三级分档 ★梯队指标 ★市场情绪刻度 ★数据日期自适应
  v3 (2026-09-27) ★龙头榜·五步法（接东财涨停池，量化封单/首封时间/带动性/弹性/辨识）
                  ★中军榜（板块内成交额前列 + 非涨停 + 沿MA5/MA10 + 近10日回撤）

数据源：all_mainboard.csv + westock 日线 + outputs/sector_component_em.json + 东财涨停池(push2ex)。
口径提示：概念来自东财板块成分（一票多概念会放大家数）；市值接口在沙箱不可用，
  故"中军"以**成交额**近似市值/流动性（与仓库 longtou.py 现行中军口径一致）。

用法：
  python3 quant_scripts/limitup_concept_rank.py [--days 20] [--top 20] [--date YYYY-MM-DD]
         [--main-zt 8] [--main-jj 35] [--sub-jj 20] [--max-stocks N] [--outdir DIR]
"""
import os, re, sys, csv, json, time, argparse, subprocess, urllib.request
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
JJ_HOT = 22.0
JJ_COLD = 13.0
# 东财涨停池（含 fbt首封时间 / fund封单 / ltsz流通市值 / zbc炸板 / zttj涨停统计）
ZT_URL = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989"
          "&dpt=wz.ztzt&Pageindex=0&pagesize=500&sort=fbt%3Aasc&date={d}")
UA = {"User-Agent": "Mozilla/5.0"}


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
    """批量 kline 长表 → {symbol: [(date,open,close,high,low,vol,amount), ...]}（升序）"""
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
            g = lambda c: float(p[header.index(c)])
            out[sym].append((p[header.index("date")], g("open"), g("last"),
                             g("high"), g("low"), g("volume"), g("amount")))
        except Exception:
            pass
    for k in out:
        out[k].sort()
    return out


def fetch_all(codes, days):
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
                return (d.get("code_sector", {}), d.get("code_name", {}),
                        d.get("sectors", {}), d.get("date", ""))
            except Exception:
                continue
    return {}, {}, {}, ""


def fetch_ztpool(d8):
    """东财涨停池 → (实际数据日 qdate, {6位代码: {...}})；失败返回 (None, {})（优雅降级）"""
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(ZT_URL.format(d=d8), headers=UA), timeout=25).read().decode()
        data = json.loads(raw).get("data") or {}
        pool, qdate = data.get("pool") or [], data.get("qdate")
    except Exception as e:
        print(f"[WARN] 涨停池获取失败（{e}），龙头榜将降级", flush=True)
        return None, {}
    d = {}
    for p in pool:
        c = p.get("c") or ""
        if not re.match(r"^\d{6}$", c):
            continue
        d[c] = {"fbt": p.get("fbt") or 0, "fund": p.get("fund") or 0,
                "ltsz": p.get("ltsz") or 0, "zbc": p.get("zbc") or 0,
                "amount": p.get("amount") or 0, "hybk": p.get("hybk") or "",
                "name": p.get("n") or "", "lbc": p.get("lbc") or 1, "zdp": p.get("zdp") or 0}
    return (str(qdate) if qdate else None), d


def classify(zt, prev_zt, jj, a):
    if zt <= 2:
        return "一日游"
    if jj is not None and jj < a.sub_jj:
        return "一日游"
    if prev_zt == 0:
        return "主线" if zt >= a.main_zt else "支线"
    if zt >= a.main_zt and jj is not None and jj >= a.main_jj:
        return "主线"
    return "支线"


GRADE_ORDER = {"主线": 0, "支线": 1, "一日游": 2}


def fmt_jj(jj, prev_zt):
    if jj is None:
        return "—  "
    return f"{jj:.0f}%{'!' if prev_zt < 3 else ''}"


def fmt_t(fbt):
    if not fbt:
        return "—"
    return f"{fbt // 10000:02d}:{fbt // 100 % 100:02d}:{fbt % 100:02d}"


def rank_frac(values, asc):
    """数值列表 → 每项 0..1 排名分（1=最优）；缺值=0。asc=True 表示越小越好"""
    n = len(values)
    out = {i: 0.0 for i in range(n)}
    valid = [(i, v) for i, v in enumerate(values) if v is not None]
    if not valid:
        return out
    sv = sorted(valid, key=lambda x: x[1], reverse=not asc)
    m = len(sv)
    for j, (i, v) in enumerate(sv):
        out[i] = (1 - j / (m - 1)) if m > 1 else 1.0
    return out


def leader_pick(members):
    """龙头五步法：对同一概念内今日涨停股打分（0-100），返回 (龙头dict, 明细list)"""
    k = len(members)
    fbt = rank_frac([m.get("fbt") or None for m in members], asc=True)       # 启动最早
    ret = rank_frac([m.get("ret5") for m in members], asc=False)            # 涨幅最大
    fd = rank_frac([m.get("fdratio") for m in members], asc=False)          # 封单最强
    maxlb = max([m.get("lianban") or 0 for m in members] + [1])
    for i, m in enumerate(members):
        s = 20 * fbt[i] + 20 * ret[i] + 25 * fd[i]
        f = m.get("fbt")
        later = sum(1 for y in members if f and y.get("fbt") and y["fbt"] > f)
        m["s_qidong"] = round(20 * fbt[i])
        m["s_danda"] = round(20 * (later / (k - 1))) if k > 1 else 20
        m["s_fengdan"] = round(25 * fd[i])
        m["s_bianshi"] = round(15 * ((m.get("lianban") or 0) / maxlb) - (5 if m.get("zbc") else 0))
        m["s_elastic"] = round(20 * ret[i])
        s += m["s_danda"] + max(0, m["s_bianshi"])
        m["leader_score"] = int(max(0, round(s)))
    leaders = sorted(members, key=lambda x: -x["leader_score"])
    return leaders[0], leaders


def find_zhongjun(codes, km, ups_codes, code_name):
    """中军：概念内非涨停、沿 MA5>MA10、成交额前列。返回 前2 列表"""
    cands = []
    for c6 in codes:
        if c6 in ups_codes:
            continue
        w = ("sh" if c6[0] == "6" else "sz") + c6
        b = km.get(w)
        if not b or len(b) < 11:
            continue
        cl = [x[2] for x in b]
        ma5 = sum(cl[-5:]) / 5
        ma10 = sum(cl[-10:]) / 10
        if not (cl[-1] > ma5 > ma10):        # 均线多头、沿5/10日线
            continue
        run = cl[-10]
        mdd = 0.0
        for c in cl[-10:]:
            run = max(run, c)
            mdd = min(mdd, c / run - 1)
        cands.append({"code": w, "name": code_name.get(c6, ""), "amt": b[-1][6] or 0,
                      "ma5": ma5, "ma10": ma10, "price": cl[-1],
                      "ret5": (cl[-1] / cl[-6] - 1) if len(cl) >= 6 else 0.0,
                      "mdd": mdd})
    cands.sort(key=lambda x: -x["amt"])
    return cands[:2]


def main_filter(c):
    return bool(re.match(r"^(600|601|603|605|000|001|002|003)\d{3}$", c or ""))


def fetch_pool_meta(d8):
    """东财涨停池原始 list + 实际数据日 qdate（非交易日/未来日期会返回最近交易日数据）"""
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(ZT_URL.format(d=d8), headers=UA), timeout=25).read().decode()
        data = json.loads(raw).get("data") or {}
        return data.get("qdate"), (data.get("pool") or [])
    except Exception as e:
        print(f"[WARN] 涨停池 {d8} 获取失败: {e}", flush=True)
        return None, []


def fast_prepare(a):
    """轻量模式：仅用东财涨停池（今日+前一交易日），秒级，无K线/中军"""
    if a.date:
        cand = [a.date.replace("-", "")]
    else:
        base0 = datetime.now(BJ)
        cand = [(base0 - timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 6)]
    qd, pool_today = None, []
    for d8 in cand:
        qd, pool_today = fetch_pool_meta(d8)
        if pool_today:
            break
    if not pool_today or not qd:
        return None
    qd = str(qd)
    # 前一交易日：从 qdate 往前取第一个非空涨停池（非交易日返回空）
    base = datetime.strptime(qd, "%Y%m%d")
    prev_pool = []
    for i in range(1, 8):
        _, prev_pool = fetch_pool_meta((base - timedelta(days=i)).strftime("%Y%m%d"))
        if prev_pool:
            break
    today = f"{qd[:4]}-{qd[4:6]}-{qd[6:]}"
    ups = []
    for p in pool_today:
        c = p.get("c") or ""
        if not main_filter(c):
            continue
        ltsz = p.get("ltsz") or 0
        fund = p.get("fund") or 0
        ups.append({"code": ("sh" if c[0] == "6" else "sz") + c, "c6": c, "name": p.get("n", ""),
                    "chg": round(p.get("zdp") or 0, 2), "lianban": p.get("lbc") or 1,
                    "price": None, "ret5": None,
                    "fbt": p.get("fbt"), "fund": fund, "ltsz": ltsz, "zbc": p.get("zbc"),
                    "fdratio": (fund / ltsz) if ltsz else None})
    prev_zt_codes = {p.get("c") for p in prev_pool if main_filter(p.get("c"))}
    prev_first_codes = {p.get("c") for p in prev_pool if main_filter(p.get("c")) and (p.get("lbc") or 1) == 1}
    today_codes = {u["c6"] for u in ups}
    prev_first_jinji = len(prev_first_codes & today_codes)
    ztpool = {u["c6"]: {"fbt": u["fbt"], "fund": u["fund"], "ltsz": u["ltsz"], "zbc": u["zbc"]}
              for u in ups}
    return today, ups, prev_zt_codes, prev_first_codes, prev_first_jinji, ztpool


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--date", default=None)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--main-zt", type=int, default=8, dest="main_zt")
    ap.add_argument("--main-jj", type=float, default=35.0, dest="main_jj")
    ap.add_argument("--sub-jj", type=float, default=20.0, dest="sub_jj")
    ap.add_argument("--max-stocks", type=int, default=0, dest="max_stocks")
    ap.add_argument("--fast", action="store_true", help="轻量模式：仅用东财涨停池（秒级，不含中军/5日弹性）")
    a = ap.parse_args()
    outdir = a.outdir or os.path.join(BASE, "outputs")
    os.makedirs(outdir, exist_ok=True)
    today = a.date or datetime.now(BJ).strftime("%Y-%m-%d")

    # ── 数据准备：默认全市场K线；--fast 改用东财涨停池（秒级，不含中军）──
    km = {}
    ztpool = {}
    ups = []
    prev_zt_codes = set()
    prev_first_codes = set()
    prev_first_jinji = 0
    pool = []

    if a.fast:
        r = fast_prepare(a)
        if not r:
            print("[ERR] 轻量模式：未取到涨停池数据")
            return 1
        today, ups, prev_zt_codes, prev_first_codes, prev_first_jinji, ztpool = r
        srcdesc = "东财涨停池（轻量·无K线）"
        print(f"[INFO][FAST] 涨停池日 {today}｜涨停 {len(ups)} 只", flush=True)
    else:
        mb = None
        for p in (os.path.join(BASE, "all_mainboard.csv"), "all_mainboard.csv"):
            if os.path.exists(p):
                mb = p
                break
        if not mb:
            print("[ERR] 缺 all_mainboard.csv")
            return 1
        with open(mb, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                c = (row.get("code") or "").strip()
                nm0 = (row.get("name") or "").strip()
                if not re.match(r"^\d{6}$", c):
                    continue
                if c.startswith(("688", "300", "301")) or "ST" in nm0.upper() or "退" in nm0:
                    continue
                pool.append((("sh" if c[0] == "6" else "sz") + c, c, nm0))
        if a.max_stocks:
            pool = pool[:a.max_stocks]
        print(f"[INFO] 主板池 {len(pool)} 只，取最近 {a.days} 日K线...", flush=True)
        km = fetch_all([x[0] for x in pool], a.days)
        print(f"[INFO] 取到 {len(km)} 只", flush=True)
        _ds = [bars[-1][0] for bars in km.values() if bars]
        kd = max(set(_ds), key=_ds.count) if _ds else None
        srcdesc = f"全主板 {len(pool)} 只（westock 日线 {a.days}日）"

        # 涨停识别以【涨停池】为准（K线仅供 5日弹性 / 中军）；池不可用时回退 K线
        target = a.date.replace("-", "") if a.date else datetime.now(BJ).strftime("%Y%m%d")
        qd, ztpool = fetch_ztpool(target)
        if qd:
            today = f"{qd[:4]}-{qd[4:6]}-{qd[6:]}"
        elif kd:
            today = kd

        if ztpool and qd:
            base = datetime.strptime(qd, "%Y%m%d")
            prev_pool = {}
            for i in range(1, 8):
                _, pp = fetch_ztpool((base - timedelta(days=i)).strftime("%Y%m%d"))
                if pp:
                    prev_pool = pp
                    break
            for c6, z in ztpool.items():
                if not main_filter(c6):
                    continue
                w = ("sh" if c6[0] == "6" else "sz") + c6
                bars = km.get(w)
                ret5 = None
                if bars and bars[-1][0] == today and len(bars) >= 6:
                    ret5 = (bars[-1][2] / bars[-6][2] - 1) * 100
                ltsz = z.get("ltsz") or 0
                fund = z.get("fund") or 0
                ups.append({"code": w, "c6": c6, "name": z.get("name") or "", "chg": round(z.get("zdp") or 0, 2),
                            "lianban": z.get("lbc") or 1, "price": None, "ret5": ret5,
                            "fbt": z.get("fbt"), "fund": fund, "ltsz": ltsz, "zbc": z.get("zbc"),
                            "fdratio": (fund / ltsz) if ltsz else None})
            prev_zt_codes = {c6 for c6 in prev_pool if main_filter(c6)}
            prev_first_codes = {c6 for c6, z in prev_pool.items() if main_filter(c6) and (z.get("lbc") or 1) == 1}
            prev_first_jinji = len(prev_first_codes & {u["c6"] for u in ups})
            print(f"[INFO] 涨停池 {len(ztpool)} 只（{today}，主板涨停 {len(ups)}）", flush=True)
        else:
            print(f"[WARN] 涨停池不可用，回退 K线识别（涨跌幅≥{LIMIT_UP}%）", flush=True)
            for wcode, c6, nm in pool:
                bars = km.get(wcode)
                if not bars or len(bars) < 4:
                    continue
                if bars[-1][0] != today:
                    continue
                closes = [b[2] for b in bars]
                n = len(bars)
                lim = [False] * n
                for i in range(1, n):
                    if closes[i - 1] > 0 and (closes[i] / closes[i - 1] - 1) * 100 >= LIMIT_UP:
                        lim[i] = True
                lb = [0] * n
                for i in range(1, n):
                    lb[i] = (lb[i - 1] + 1) if (lim[i] and lim[i - 1]) else (1 if lim[i] else 0)
                if lim[-2]:
                    prev_zt_codes.add(c6)
                    if lb[-2] == 1:
                        prev_first_codes.add(c6)
                        if lim[-1]:
                            prev_first_jinji += 1
                if not lim[-1]:
                    continue
                chg = (closes[-1] / closes[-2] - 1) * 100 if closes[-2] else 0
                ret5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else None
                ups.append({"code": wcode, "c6": c6, "name": nm, "chg": round(chg, 2),
                            "lianban": lb[-1], "price": closes[-1], "ret5": ret5,
                            "fbt": None, "fund": 0, "ltsz": 0, "zbc": None, "fdratio": None})

    code_sector, code_name, sectors, sec_date = load_sector()
    print(f"[INFO] 题材映射 {len(code_sector)} 只（更新于 {sec_date}）", flush=True)

    n_lb = sum(1 for u in ups if u["lianban"] >= 2)
    n_first = sum(1 for u in ups if u["lianban"] == 1)
    print(f"[INFO] 涨停 {len(ups)} 只（连板 {n_lb} / 首板 {n_first}）｜昨日涨停 {len(prev_zt_codes)} 只", flush=True)

    # 市场情绪刻度
    prev_zt_n = len(prev_zt_codes)
    mkt_lb_jj = (100.0 * n_lb / prev_zt_n) if prev_zt_n else None
    mkt_first_jj = (100.0 * prev_first_jinji / len(prev_first_codes)) if prev_first_codes else None
    mood = ("—" if mkt_first_jj is None else
            "🔥 活跃（题材接力强）" if mkt_first_jj >= JJ_HOT else
            "🧊 退潮（谨慎打板）" if mkt_first_jj < JJ_COLD else "⚖️ 中性")

    # 概念聚合
    agg = defaultdict(lambda: {"n": 0, "lb": 0, "first": 0, "maxlb": 0, "prev": 0, "stocks": []})
    for u in ups:
        for s in (code_sector.get(u["c6"]) or code_sector.get(u["code"]) or []):
            g = agg[s]
            g["n"] += 1
            g["lb"] += 1 if u["lianban"] >= 2 else 0
            g["first"] += 1 if u["lianban"] == 1 else 0
            g["maxlb"] = max(g["maxlb"], u["lianban"])
            g["stocks"].append(u)
    for c6 in prev_zt_codes:
        for s in (code_sector.get(c6) or []):
            agg[s]["prev"] += 1

    rank = []
    for s, v in agg.items():
        if v["n"] < 2:
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

    ups_codes = {u["c6"] for u in ups}
    icon = {"主线": "🔴", "支线": "🟡", "一日游": "⚪"}

    L = [f"# 🔥 热板作战面板 {today}", "",
         f"> 数据源：{srcdesc}｜题材映射 {len(code_sector)} 只（{sec_date}）｜涨停池 {len(ztpool)} 只",
         f"> 当日涨停 **{len(ups)}** 只｜连板 **{n_lb}** 只｜首板 **{n_first}** 只", "",
         "## 📊 市场情绪刻度",
         f"- 昨日涨停 **{prev_zt_n}** 只 → 今日连板 **{n_lb}** 只，**连板晋级率 {mkt_lb_jj:.0f}%**" if prev_zt_n else "- 连板晋级率 —",
         f"- 昨日首板 {len(prev_first_codes)} 只 → 今日晋级 {prev_first_jinji} 只，**首板晋级率 {mkt_first_jj:.0f}%**" if prev_first_codes else "- 首板晋级率 —",
         f"- 情绪档位：**{mood}**（首板晋级率阈值 活跃≥{JJ_HOT:.0f}% / 退潮<{JJ_COLD:.0f}%）", "",
         "## 🧭 板块分级",
         "| 级别 | 概念数 | 判定标准 |", "|---|---|---|",
         f"| 🔴 主线 | {n_main} | 涨停≥{a.main_zt}家 且 晋级率≥{a.main_jj:.0f}% |",
         f"| 🟡 支线 | {n_sub} | 涨停3-7家 或 晋级率{a.sub_jj:.0f}-{a.main_jj:.0f}% |",
         f"| ⚪ 一日游 | {n_day} | 涨停≤2家 或 晋级率<{a.sub_jj:.0f}% |", "",
         "## 概念排行（按级别 + 涨停家数）", "",
         "| 级别 | 概念 | 涨停 | 连板 | 昨日涨停 | 晋级率 | 最高板 | 首板 | 代表龙头（连板数） |",
         "|---|---|---|---|---|---|---|---|---|"]
    for s, v in rank:
        tops = sorted(v["stocks"], key=lambda x: -x["lianban"])[:4]
        names = "、".join(f"{t['name']}({t['lianban']}板)" if t["lianban"] >= 2 else t["name"] for t in tops)
        L.append(f"| {icon.get(v['grade'],'')} {v['grade']} | **{s}** | {v['n']} | {v['lb']} | "
                 f"{v['prev']} | {fmt_jj(v['jj'], v['prev'])} | {v['maxlb']} | {v['first']} | {names} |")

    # ── 模块二：龙头榜 · 五步法 ──
    L += ["", "## 👑 龙头榜 · 五步法（各热门板块龙头）", "",
          "| 板块 | 龙头 | 板数 | 首封 | 封单/流通 | 5日涨幅 | 带动(后涨) | 辨识 | 龙头分 | 五维构成(启动/弹性/封单/带动/辨识) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    leaders_json = []
    for s, v in rank:
        if v["n"] < 3:
            continue
        lead, allm = leader_pick(v["stocks"])
        ratio = f"{(lead['fdratio']*100):.1f}%" if lead.get("fdratio") is not None else "—"
        r5 = f"{lead['ret5']:.1f}%" if lead.get("ret5") is not None else "—"
        later = lead["s_danda"] // 20 * (len(allm) - 1) if len(allm) > 1 else 0
        con = f"{lead['s_qidong']}/{lead['s_elastic']}/{lead['s_fengdan']}/{lead['s_danda']}/{max(0,lead['s_bianshi'])}"
        L.append(f"| {s} | **{lead['name']}**({lead['code']}) | {lead['lianban']} | {fmt_t(lead.get('fbt'))} | "
                 f"{ratio} | {r5} | {later} | {max(0,lead['s_bianshi'])} | **{lead['leader_score']}** | {con} |")
        leaders_json.append({"concept": s, "leader": lead["name"], "code": lead["code"],
                             "lianban": lead["lianban"], "score": lead["leader_score"],
                             "fbt": fmt_t(lead.get("fbt")),
                             "fd_ratio": round(lead["fdratio"] * 100, 2) if lead.get("fdratio") is not None else None,
                             "ret5": round(lead["ret5"], 2) if lead.get("ret5") is not None else None})
    if not leaders_json:
        L.append("| — | 无（当日无≥3家涨停的板块） | | | | | | | | |")

    # ── 模块三：中军榜 ──
    L += ["", "## 🛡️ 中军榜（趋势压舱石 · 概念内成交额前列 · 沿MA5/MA10）", "",
          "> 中军口径：概念内**非涨停**、多头排列(收盘>MA5>MA10)、成交额前列（以成交额近似市值/流动性，市值接口沙箱不可用）", "",
          "| 板块 | 中军 | 成交额(亿) | 收盘 | MA5 | MA10 | 5日涨幅 | 近10日回撤 |", "|---|---|---|---|---|---|---|---|"]
    zj_json = []
    for s, v in rank[:10]:
        zjs = find_zhongjun(sectors.get(s) or [], km, ups_codes, code_name)
        if not zjs:
            L.append(f"| {s} | —（无符合均线多头的中军） | | | | | | |")
            continue
        for i, z in enumerate(zjs):
            L.append(f"| {s if i == 0 else ''} | {z['name']}({z['code']}) | {z['amt']/1e8:.1f} | {z['price']:.2f} | "
                     f"{z['ma5']:.2f} | {z['ma10']:.2f} | {z['ret5']*100:+.1f}% | {z['mdd']*100:.1f}% |")
            zj_json.append({"concept": s, "name": z["name"], "code": z["code"],
                            "amount_yi": round(z["amt"] / 1e8, 2),
                            "ret5": round(z["ret5"] * 100, 2), "mdd": round(z["mdd"] * 100, 2)})

    L += ["", "## 涨停明细（按连板数）", "",
          "| 代码 | 名称 | 连板 | 涨幅% | 首封 | 封单(万) | 流通(亿) | 所属题材 |",
          "|---|---|---|---|---|---|---|---|"]
    for u in sorted(ups, key=lambda x: (-x["lianban"], -x["chg"])):
        secs = code_sector.get(u["c6"]) or []
        fd = f"{u['fund']/1e4:.0f}" if u.get("fund") else "—"
        lz = f"{u['ltsz']/1e8:.0f}" if u.get("ltsz") else "—"
        L.append(f"| {u['code']} | {u['name']} | {u['lianban']} | {u['chg']} | {fmt_t(u.get('fbt'))} | "
                 f"{fd} | {lz} | {'/'.join(secs[:4])} |")
    L += ["", "---",
          "⚠️ 概念分类来自东财板块成分（一票可属多个概念，家数会放大）；晋级率=今日连板家数/昨日涨停家数（昨日涨停<3标 `!`）；"
          "龙头五步法为板块内相对排名打分（启动=首封时间最早、弹性=5日涨幅、封单=封单/流通市值、带动=首封后跟涨家数、辨识=最高板+未炸板）；"
          "中军以成交额近似市值。以上均为**统计口径**，实际热点须结合新闻面人工复核。"]
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
               "leaders": leaders_json,
               "zhongjun": zj_json,
               "stocks": ups},
              open(os.path.join(outdir, "涨停概念排行_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(md)
    print(f"\n[OK] {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
