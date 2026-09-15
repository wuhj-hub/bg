#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wangzhe_track.py —— 涨停型王者 · 筛选 + 成功率跟踪（2026-09-15）

【信号定义】涨停型王者（v2.0）：
  ① 涨停（主板 10% 幅度）
  ② 首板（前一日未涨停）
  ③ 量能：历史口径「量比 1.5~4」（当日量/前日量）；实盘口径「换手率 > 5%」
  ④ 价格 < 10 元
  ⑤ 实盘追加：未炸板（东财 zbc == 0）

【用法】
  --backfill   用本地日线全历史回填信号（量比口径，2015-2026）
  --scan       抓当日实时涨停池 → 追加信号（换手口径，含行业）
  --update     更新未到期信号的后续 5/10/20 日收益
  --stats      输出成功率统计（默认）
  --report     生成 Markdown 报告

【数据】
  日线：data/kline_daily_vol.csv（同花顺前复权）
  实时：东财涨停池 push2ex（沙箱可直连）
  信号库：outputs/wangzhe_signals.csv（唯一真源，只增不改，推 GitHub）
"""
import csv, json, os, sys, re, argparse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import numpy as np

BJT = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.abspath(__file__))
# 输出目录：沙箱内脚本与 outputs/ 同级；仓库内脚本在 quant_scripts/，输出需落到仓库根 outputs/
OUT = os.path.join(BASE, "outputs")
if os.path.basename(BASE) == "quant_scripts":
    OUT = os.path.join(os.path.dirname(BASE), "outputs")
DATA = os.path.join(BASE, "data", "kline_daily_vol.csv")
SIG = os.path.join(OUT, "wangzhe_signals.csv")
BENCH = os.path.join(OUT, "wangzhe_benchmark.json")
HOLD = [5, 10, 20]
FIELDS = ["signal_date", "code", "name", "price", "vol_ratio", "turnover", "lbc",
          "fbt", "hybk", "source", "variant", "limit_date", "r5", "r10", "r20",
          "b5", "b10", "b20", "ex5", "ex10", "ex20"]


def log(m):
    print(f"[{datetime.now(BJT).strftime('%H:%M:%S')}] {m}", flush=True)


def load_kline():
    """载入本地日线（沙箱专用）。GitHub runner 上无此大文件 → 返回空，改走 --update-live"""
    if not os.path.exists(DATA):
        log(f"[WARN] 本地日线不存在（{DATA}）→ 跳过，请用 --update-live")
        return {}
    by = defaultdict(list)
    with open(DATA, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                by[r["code"]].append((r["date"], float(r["open"]), float(r["high"]),
                                      float(r["low"]), float(r["close"]), float(r["volume"])))
            except (ValueError, KeyError):
                continue
    for c in by:
        by[c].sort(key=lambda x: x[0])
    return by


def clean(bars, close, vol, high):
    bad = (close <= 0.3) | (vol <= 0)
    if bad.any():
        k = ~bad
        return ([b for b, x in zip(bars, k) if x], close[k], vol[k], high[k])
    return bars, close, vol, high


def calc_benchmark(by):
    """基准：按日期聚合的全市场 H 日平均收益"""
    base = {h: defaultdict(lambda: [0.0, 0]) for h in HOLD}
    for code, bars in by.items():
        close = np.array([b[4] for b in bars]); vol = np.array([b[5] for b in bars])
        high = np.array([b[2] for b in bars])
        bars, close, vol, high = clean(bars, close, vol, high)
        n = len(bars)
        for i in range(n):
            for h in HOLD:
                if i + h < n and close[i] > 0:
                    b_ = base[h][bars[i][0]]
                    b_[0] += close[i + h] / close[i] - 1
                    b_[1] += 1
    out = {h: {d: v[0] / v[1] for d, v in base[h].items() if v[1]} for h in HOLD}
    json.dump(out, open(BENCH, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def load_benchmark():
    if os.path.exists(BENCH):
        d = json.load(open(BENCH, encoding="utf-8"))
        return {int(k): v for k, v in d.items()}
    return None


def is_limit_up(close, prev_close):
    return close >= round(prev_close * 1.10, 2) - 0.001


def backfill(by, bench):
    """用日线全历史回填「涨停型王者」（量比口径）"""
    rows, seen = [], set()
    for code, bars in by.items():
        if not code.startswith(("sh600", "sh601", "sh603", "sh605",
                                "sz000", "sz001", "sz002", "sz003")):
            continue                                    # 仅沪深主板
        close = np.array([b[4] for b in bars]); vol = np.array([b[5] for b in bars])
        high = np.array([b[2] for b in bars])
        bars, close, vol, high = clean(bars, close, vol, high)
        n = len(bars)
        if n < 90:
            continue
        for t in range(25, n):
            if not is_limit_up(close[t], close[t - 1]):
                continue
            if is_limit_up(close[t - 1], close[t - 2]):
                continue                                # 首板
            vr = vol[t] / vol[t - 1] if vol[t - 1] else 0
            if not (1.5 <= vr <= 4):
                continue
            # ⚠️ 2026-09-15 复核：才哥正版无价格限制，故移除「价<10元」过滤
            key = f"{bars[t][0]}_{code}"
            if key in seen:
                continue
            seen.add(key)
            r = {k: "" for k in FIELDS}
            r.update({"signal_date": bars[t][0], "code": code, "name": "",
                      "price": round(close[t], 2), "vol_ratio": round(vr, 2),
                      "turnover": "", "lbc": 1, "fbt": "", "hybk": "",
                      "source": "backfill", "variant": "day1", "limit_date": bars[t][0]})
            rows.append(r)
    return rows


def backfill_full(by, bench):
    """才哥正版「涨停王者倍量柱」完整确认信号（涨停日 T-3 / 信号日 T+3），不限价"""
    rows, seen = [], set()
    for code, bars in by.items():
        if not code.startswith(("sh600", "sh601", "sh603", "sh605",
                                "sz000", "sz001", "sz002", "sz003")):
            continue
        close = np.array([b[4] for b in bars]); high = np.array([b[2] for b in bars])
        low = np.array([b[3] for b in bars]); vol = np.array([b[5] for b in bars])
        bars, close, vol, high = clean(bars, close, vol, high)
        n = len(bars)
        if n < 90:
            continue
        ma60 = np.full(n, np.nan)
        for i in range(59, n):
            ma60[i] = close[i - 59:i + 1].mean()
        for t in range(25, n - 3):
            if not is_limit_up(close[t], close[t - 1]):
                continue
            if high[t] == low[t]:
                continue                       # 一字板（代理「换手>5%」过滤）
            vr = vol[t] / vol[t - 1] if vol[t - 1] else 0
            if not (1.5 <= vr <= 4):
                continue
            if min(close[t + 1], close[t + 2], close[t + 3]) <= close[t]:
                continue
            if not (vol[t + 3] < vol[t + 2] < vol[t + 1]):
                continue
            if max(high[t + 1], high[t + 2], high[t + 3]) / close[t] - 1 >= 0.09:
                continue
            if np.isnan(ma60[t + 3]) or np.isnan(ma60[t + 2]) or ma60[t + 3] < ma60[t + 2]:
                continue
            if (vol[t + 1] + vol[t + 2] + vol[t + 3]) / 3 >= vol[t]:
                continue
            key = f"{bars[t + 3][0]}_{code}"
            if key in seen:
                continue
            seen.add(key)
            r = {k: "" for k in FIELDS}
            r.update({"signal_date": bars[t + 3][0], "code": code, "name": "",
                      "price": round(close[t + 3], 2), "vol_ratio": round(vr, 2),
                      "turnover": "", "lbc": 1, "fbt": "", "hybk": "",
                      "source": "backfill", "variant": "full",
                      "limit_date": bars[t][0]})
            rows.append(r)
    return rows


def fill_returns(rows, by, bench):
    """填 5/10/20 日收益 + 同期基准 + 超额"""
    idx = {c: {b[0]: i for i, b in enumerate(bars)} for c, bars in by.items()}
    hit = 0
    for r in rows:
        bars = by.get(r["code"])
        if not bars:
            continue
        i = idx[r["code"]].get(r["signal_date"])
        if i is None:
            continue
        t = i
        for h in HOLD:
            j = t + h
            if j < len(bars):
                c0, c1 = bars[t][4], bars[j][4]
                if c0 > 0:
                    r[f"r{h}"] = round((c1 / c0 - 1) * 100, 2)
                    bb = float(bench[h].get(bars[j][0], "nan"))
                    if bb == bb:
                        r[f"b{h}"] = round(bb * 100, 2)
                        r[f"ex{h}"] = round(r[f"r{h}"] - r[f"b{h}"], 2)
                        hit += 1
    return hit


def save_rows(rows):
    os.makedirs(os.path.dirname(SIG), exist_ok=True)
    rows.sort(key=lambda r: (r["signal_date"], r["code"]))
    with open(SIG, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def load_rows():
    if not os.path.exists(SIG):
        return []
    out = []
    with open(SIG, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append(dict(r))
    return out


def scan(live=True):
    """抓当日实时涨停池 → 涨停型王者（换手口径）"""
    date = datetime.now(BJT).strftime("%Y%m%d")
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989"
           f"&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt%3Aasc&date={date}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        pool = (json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
                .get("data") or {}).get("pool") or []
    except Exception as e:
        log(f"[WARN] 涨停池获取失败: {e}")
        return []
    ds = datetime.now(BJT).strftime("%Y-%m-%d")
    rows = []
    for it in pool:
        try:
            code = str(it.get("c", "")); name = str(it.get("n", "")).strip()
            price = float(it.get("p", 0)) / 1000.0
            hs = float(it.get("hs", 0)); lbc = int(it.get("lbc") or 0)
            zbc = int(it.get("zbc") or 0); fbt = int(it.get("fbt") or 0)
        except (ValueError, TypeError):
            continue
        if not code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
            continue
        if "ST" in name.upper():
            continue
        # ⚠️ 2026-09-15 复核：才哥正版定义**不含价格限制**，故去掉「价<10元」（回测亦显示不限价更优）
        if lbc != 1 or hs <= 5 or zbc > 0:
            continue
        pre = "sh" if code[0] == "6" else "sz"
        r = {k: "" for k in FIELDS}
        r.update({"signal_date": ds, "code": pre + code, "name": name,
                  "price": round(price, 2), "vol_ratio": "", "turnover": round(hs, 2),
                  "lbc": lbc, "fbt": fbt, "hybk": it.get("hybk", ""), "source": "live",
                  "variant": "day1", "limit_date": ds})
        rows.append(r)
    rows.sort(key=lambda x: x["fbt"])
    return rows


def merge(new_rows, old_rows):
    seen = {f"{r['signal_date']}_{r['code']}_{r.get('variant','day1')}" for r in old_rows}
    add = [r for r in new_rows
           if f"{r['signal_date']}_{r['code']}_{r.get('variant','day1')}" not in seen]
    return old_rows + add, len(add)


def stats(rows, bench, title="全部"):
    print(f"\n{'='*88}\n【{title}】样本 {len(rows)}\n{'='*88}")
    if not rows:
        print("  （无样本）")
        return None
    out = {}
    print(f"  {'持有':<5}{'有效':>7}{'均值':>9}{'中位':>9}{'胜率':>8}{'超额胜率':>10}"
          f"{'平均超额':>10}{'t':>7}{'独立日':>8}")
    for h in HOLD:
        rs = [(r["signal_date"], float(r[f"r{h}"]), float(r[f"ex{h}"]))
              for r in rows if r.get(f"r{h}") not in ("", None) and r.get(f"ex{h}") not in ("", None)]
        if not rs:
            continue
        byd = defaultdict(list)
        for d, r_, e_ in rs:
            byd[d].append((r_, e_))
        arr_r = np.array([np.mean([x[0] for x in v]) for v in byd.values()])
        arr_e = np.array([np.mean([x[1] for x in v]) for v in byd.values()])
        se = arr_e.std(ddof=1) / np.sqrt(len(arr_e)) if len(arr_e) > 1 else 0
        t = arr_e.mean() / se if se else 0
        out[h] = {"n": len(rs), "days": len(byd), "mean": float(arr_r.mean()),
                  "median": float(np.median(arr_r)), "win": float((arr_r > 0).mean() * 100),
                  "ex_win": float((arr_e > 0).mean() * 100), "ex_mean": float(arr_e.mean()),
                  "t": float(t)}
        print(f"  {h:<5}{len(rs):>7}{arr_r.mean():>+8.2f}%{np.median(arr_r):>+8.2f}%"
              f"{(arr_r>0).mean()*100:>7.1f}%{(arr_e>0).mean()*100:>9.1f}%"
              f"{arr_e.mean():>+9.2f}%{t:>7.1f}{len(byd):>8}")
    return out


def update_live(rows, lookback=45):
    """workflow 端收益更新：用 westock 批量 kline 取近 lookback 日内的信号后续收益。
    本地沙箱无 248MB 日线文件时使用。基准用上证指数同期收益。"""
    import subprocess
    cutoff = (datetime.now(BJT) - timedelta(days=lookback)).strftime("%Y-%m-%d")
    todo = [r for r in rows if r["signal_date"] >= cutoff and r.get("r20") in ("", None)]
    if not todo:
        log("无待更新信号")
        return 0
    codes = sorted({r["code"] for r in todo})
    log(f"待更新 {len(todo)} 条 / {len(codes)} 只（近 {lookback} 日）")
    # 基准：上证指数
    bmap = {}
    try:
        out = subprocess.run(["npx", "-y", "westock-data-skillhub@1.0.3", "kline", "sh000001",
                              "--period", "day", "--limit", "80"], capture_output=True, text=True, timeout=90).stdout
        ser = []
        for ln in out.splitlines():
            if ln.strip().startswith("|") and "---" not in ln:
                ps = [x.strip() for x in ln.strip("|").split("|")]
                if len(ps) >= 5 and re.match(r"\d{4}-\d{2}-\d{2}", ps[0]):
                    try:
                        ser.append((ps[0], float(ps[4])))
                    except ValueError:
                        pass
        ser.sort()
        b5 = {d: (ser[i + 5][1] / c - 1) * 100 for i, (d, c) in enumerate(ser) if i + 5 < len(ser) and c > 0}
        bmap = b5
    except Exception as e:
        log(f"[WARN] 基准指数获取失败: {e}")
    # 批量取个股（每批 50 只）
    kd = {}
    for i in range(0, len(codes), 50):
        chunk = codes[i:i + 50]
        try:
            out = subprocess.run(["npx", "-y", "westock-data-skillhub@1.0.3", "kline", ",".join(chunk),
                                  "--period", "day", "--limit", "80"], capture_output=True, text=True, timeout=180).stdout
            cur = None
            for ln in out.splitlines():
                if not ln.strip().startswith("|") or "---" in ln:
                    continue
                ps = [x.strip() for x in ln.strip("|").split("|")]
                if len(ps) < 5:
                    continue
                try:
                    if re.match(r"^(sh|sz)\d{6}$", ps[0]):
                        cur = ps[0]; kd.setdefault(cur, [])
                        d, c = ps[1], float(ps[4])
                    elif re.match(r"\d{4}-\d{2}-\d{2}", ps[0]) and cur:
                        d, c = ps[0], float(ps[4] if len(ps) > 4 else ps[3])
                    else:
                        continue
                    kd[cur].append((d, c))
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            log(f"[WARN] 批量行情失败 {chunk[:2]}: {e}")
    hit = 0
    for r in todo:
        bars = kd.get(r["code"])
        if not bars:
            continue
        bars.sort()
        idx = {d: i for i, (d, _) in enumerate(bars)}
        t = idx.get(r["signal_date"])
        if t is None:
            continue
        c0 = bars[t][1]
        if c0 <= 0:
            continue
        for h in HOLD:
            j = t + h
            if j < len(bars):
                r[f"r{h}"] = round((bars[j][1] / c0 - 1) * 100, 2)
                bg = bmap.get(bars[j][0])
                if bg is not None:
                    r[f"b{h}"] = round(bg, 2)
                    r[f"ex{h}"] = round(r[f"r{h}"] - bg, 2)
                    hit += 1
    log(f"在线更新填收益 {hit} 项")
    return hit


def push_summary(rows, st, new_live):
    """PushPlus 推送：当日新增信号 + 5日成功率摘要"""
    tok = os.environ.get("PUSH_TOKEN", "")
    if not tok:
        log("[WARN] 未设置 PUSH_TOKEN，跳过推送")
        return
    d = datetime.now(BJT).strftime("%Y-%m-%d")
    v = st.get(5) or st.get("5") or {}
    lines = [f"# 👑 涨停型王者跟踪 {d}", ""]
    if new_live:
        lines.append(f"## 当日信号 {len(new_live)} 只")
        for w in new_live[:20]:
            ft = w.get("fbt") or ""
            t = f"{int(ft)//10000:02d}:{int(ft)//100%100:02d}" if ft else "--:--"
            lines.append(f"👑 **{w['name']}**({w['code']}) {w['price']}元 换手{w['turnover']}% 封板{t} · {w['hybk']}")
        lines.append("")
    else:
        lines += ["## 当日信号 0 只（无符合「首板+换手>5%+价<10元+未炸板」）", ""]
    if v:
        lines += ["## 历史成功率（全样本）",
                  f"- 5日胜率 **{v.get('win', 0):.1f}%**（超额胜率 {v.get('ex_win', 0):.1f}%）",
                  f"- 5日均值 {v.get('mean', 0):+.2f}% / 平均超额 {v.get('ex_mean', 0):+.2f}% (t={v.get('t', 0):.1f})",
                  f"- 样本 {v.get('n', 0)} 条 / 独立日 {v.get('days', 0)}",
                  "", "> 持有周期 5 日；10日衰减、20日无优势"]
    body = json.dumps({"token": tok, "title": f"👑王者跟踪 {d}（{len(new_live)}只）",
                       "content": "\n".join(lines), "template": "markdown"}).encode()
    try:
        req = urllib.request.Request("https://www.pushplus.plus/send", data=body,
                                     headers={"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        log(f"推送: {'✅' if r.get('code') == 200 else r}")
    except Exception as e:
        log(f"[WARN] 推送失败: {e}")


def by_period(rows, key_fn, label, min_n=30):
    """按期间分组统计 5 日表现"""
    g = defaultdict(list)
    for r in rows:
        if r.get("r5") not in ("", None) and r.get("ex5") not in ("", None):
            g[key_fn(r)].append((r["signal_date"], float(r["r5"]), float(r["ex5"])))
    print(f"\n【{label}】")
    print(f"  {'期间':<12}{'样本':>7}{'5日均值':>10}{'中位':>9}{'胜率':>8}{'超额胜率':>10}{'平均超额':>10}")
    out = {}
    for k in sorted(g.keys()):
        rs = g[k]
        if len(rs) < min_n:
            continue                      # 样本过少（数据边界噪声）不纳入
        byd = defaultdict(list)
        for d, r_, e_ in rs:
            byd[d].append((r_, e_))
        arr_r = np.array([np.mean([x[0] for x in v]) for v in byd.values()])
        arr_e = np.array([np.mean([x[1] for x in v]) for v in byd.values()])
        out[k] = {"n": len(rs), "mean": float(arr_r.mean()), "median": float(np.median(arr_r)),
                  "win": float((arr_r > 0).mean() * 100), "ex_win": float((arr_e > 0).mean() * 100),
                  "ex_mean": float(arr_e.mean())}
        print(f"  {str(k):<12}{len(rs):>7}{arr_r.mean():>+9.2f}%{np.median(arr_r):>+8.2f}%"
              f"{(arr_r>0).mean()*100:>7.1f}%{(arr_e>0).mean()*100:>9.1f}%{arr_e.mean():>+9.2f}%")
    return out


def write_report(rows, st_all, st_year, st_recent, by):
    """生成 Markdown 报告"""
    lines = ["# 涨停型王者 · 信号筛选与成功率跟踪报告", "",
             f"**生成**：{datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}（北京时间）",
             f"**信号库**：`outputs/wangzhe_signals.csv`（{len(rows)} 条）", "",
             "## 一、信号定义（涨停型王者）", "",
             "| # | 条件 |", "|---|---|",
             "| ① | 涨停（主板 10% 幅度） |",
             "| ② | **首板**（前一日未涨停） |",
             "| ③ | 量能：历史口径「量比 1.5~4」／实盘口径「换手率 > 5%」 |",
             "| ④ | 实盘追加：未炸板（东财 `zbc==0`） |",
             "",
             "> ⚠️ **2026-09-15 复核**：才哥（刘骥才）正版定义**不含价格限制**，原「价<10元」已移除。",
             "> 另：才哥正版为**涨停后第 3 天确认**（T+3），本工具另保留「涨停日触发 day1」口径用于对比。", "",
             "**两种口径**：",
             "- `day1`：涨停日当天触发（实盘可判定）",
             "- `full`：才哥正版完整确认（8 条件，T+3 确认）", "",
             "## 二、成功率总览（全样本）", "",
             "| 持有 | 有效样本 | 均值 | 中位 | **胜率** | 超额胜率 | 平均超额 | t | 独立日 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for h in HOLD:
        v = st_all.get(h) or st_all.get(str(h))
        if not v:
            continue
        lines.append(f"| **{h}日** | {v['n']} | {v['mean']:+.2f}% | {v['median']:+.2f}% | "
                     f"**{v['win']:.1f}%** | {v['ex_win']:.1f}% | {v['ex_mean']:+.2f}% | {v['t']:.1f} | {v['days']} |")
    lines += ["", "> 基准为同期全市场平均收益（按日聚合，剔除系统性涨跌）。|t|>2 视为显著。", "",
              "## 三、分年度稳定性", "",
              "| 年度 | 样本 | 5日均值 | 中位 | 胜率 | 超额胜率 | 平均超额 |",
              "|---|---|---|---|---|---|---|"]
    for k in sorted(st_year.keys()):
        v = st_year[k]
        lines.append(f"| {k} | {v['n']} | {v['mean']:+.2f}% | {v['median']:+.2f}% | "
                     f"{v['win']:.1f}% | {v['ex_win']:.1f}% | {v['ex_mean']:+.2f}% |")
    lines += ["", "## 四、近 12 个月（当前有效性）", "",
              "| 月份 | 样本 | 5日均值 | 中位 | 胜率 | 超额胜率 | 平均超额 |",
              "|---|---|---|---|---|---|---|"]
    for k in sorted(st_recent.keys()):
        v = st_recent[k]
        lines.append(f"| {k} | {v['n']} | {v['mean']:+.2f}% | {v['median']:+.2f}% | "
                     f"{v['win']:.1f}% | {v['ex_win']:.1f}% | {v['ex_mean']:+.2f}% |")
    lines += ["", "## 五、口径说明与局限", "",
              "1. **历史回填用「量比 1.5~4」**（本地日线无流通股本，无法算换手率）；**实盘记录用「换手率 > 5%」**——两者近似等价，统计时按 `source` 字段分开标注。",
              "2. 首板判定基于前一日收盘价，与实盘「前一日未涨停」一致；ST 股涨停幅度为 5%，用 10% 判据不会误判。",
              "3. 信号收益按**信号日收盘价**为基准计算（实盘即封板价）。",
              "4. 回填样本天然排除「盘中封板后炸板」的标的（轻微生存偏差）。",
              "5. **免责**：历史统计不代表未来表现。", ""]
    text = "\n".join(lines)
    out = os.path.join(OUT, f"涨停型王者_成功率报告_{datetime.now(BJT).strftime('%Y-%m-%d')}.md")
    open(out, "w", encoding="utf-8").write(text)
    log(f"报告已生成: {out}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--backfill-full", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--update-live", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    if not any([a.backfill, getattr(a, "backfill_full"), a.scan, a.update,
                getattr(a, "update_live"), a.stats, a.report, a.push]):
        a.stats = True

    by = load_kline()
    bench = load_benchmark()
    if bench is None:
        if by:
            log("计算基准（按日聚合全市场收益）…")
            bench = calc_benchmark(by)
        else:
            log("[WARN] 无本地日线且无基准文件 → 基准为空（仅影响超额列）")
            bench = {h: {} for h in HOLD}
    rows = load_rows()

    if a.backfill:
        log("回填历史信号（量比口径，全历史）…")
        new = backfill(by, bench)
        rows, n = merge(new, rows)
        log(f"回填 {len(new)} 条，新增 {n} 条")
    if a.backfill_full:
        log("回填才哥正版「涨停王者倍量柱」完整确认信号（不限价）…")
        new = backfill_full(by, bench)
        rows, n = merge(new, rows)
        log(f"正版确认 {len(new)} 条，新增 {n} 条")
    if a.scan:
        log("扫描当日实时涨停池（换手口径）…")
        new = scan()
        rows, n = merge(new, rows)
        log(f"当日命中 {len(new)} 条，新增 {n} 条")
    if a.update_live:
        update_live(rows)
    if a.backfill or getattr(a, "backfill_full") or a.scan or a.update:
        log("更新后续收益（本地日线）…")
        hit = fill_returns(rows, by, bench)
        log(f"已填收益 {hit} 条")
    if a.backfill or getattr(a, "backfill_full") or a.scan or a.update or a.update_live:
        save_rows(rows)
        log(f"信号库已保存: {SIG}（共 {len(rows)} 条）")
    if a.push and not (a.stats or a.report):
        st = json.load(open(os.path.join(OUT, "wangzhe_stats.json"), encoding="utf-8")).get("all", {}) \
            if os.path.exists(os.path.join(OUT, "wangzhe_stats.json")) else {}
        push_summary(rows, st, [r for r in rows if r["source"] == "live" and r["signal_date"] == datetime.now(BJT).strftime("%Y-%m-%d")])
    if a.stats or a.report:
        out_all = stats(rows, bench, "涨停型王者 · 全部")
        d1 = [r for r in rows if r.get("variant", "day1") == "day1"]
        fu = [r for r in rows if r.get("variant") == "full"]
        if d1:
            stats(d1, bench, "口径A·涨停日触发 day1（不限价）")
        if fu:
            stats(fu, bench, "口径B·才哥正版确认 full（T+3·不限价）")
        lv = [r for r in rows if r["source"] == "live"]
        if lv:
            stats(lv, bench, "实盘前瞻（换手口径）")
        st_year = by_period(d1, lambda r: r["signal_date"][:4], "分年度（day1口径·5日）")
        # 近 12 个月
        cutoff = (datetime.now(BJT) - timedelta(days=370)).strftime("%Y-%m")
        st_recent = by_period([r for r in d1 if r["signal_date"][:7] >= cutoff],
                              lambda r: r["signal_date"][:7], "近 12 个月（day1口径·5日）")
        json.dump({"all": out_all, "year": st_year, "recent": st_recent, "n": len(rows),
                   "full": stats(fu, bench, "口径B·才哥正版确认 full（T+3·不限价）") if fu else None,
                   "day1": out_all},
                  open(os.path.join(OUT, "wangzhe_stats.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, default=str)
        if a.report:
            write_report(rows, out_all, st_year, st_recent, by)
        if a.push:
            push_summary(rows, out_all, [r for r in rows if r["source"] == "live"
                                         and r["signal_date"] == datetime.now(BJT).strftime("%Y-%m-%d")])


if __name__ == "__main__":
    main()
