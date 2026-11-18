#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wangzhe_breakout.py —— 王者突破（神龙摆尾尾部突破K × 王者倍量柱）选股 + 纪律跟踪

【来源】
  ① 林中独步《神龙摆尾（三线合一）指标的一个小妙用》(2026-10-17)
     CG:=MA(C,15); FL:=HHV(CG,5); FS:=CG-(FL-CG);
     突破K = (C-REF(C,1))/REF(C,1)>=0.03 AND CROSS(C,FL) AND CG<>FS
     要点：突破K的「实顶(C)」是强支撑，不破则走牛概率增加；跌破「实底(O)」转压力 → 出局
  ② 王者倍量柱：量 >= 2×前5日均量 且 阳线 且 涨幅>=3%（量能突破）
  两者同日成立 = 「王者突破」：量的证据 × 结构的证据（均线压缩后的第一次上穿）

【纪律（跟踪池）】
  入池：信号日收盘 = 实顶防守线；信号日开盘 = 实底止损线；且收盘价 < --max-price（默认 10 元）
  每日更新：close >= 实顶 → 强（不破顶）；实底 <= close < 实顶 → 观察；close < 实底 → **删除**
  文章口径：长期小阴小阳横盘不破实顶 = 走牛概率增加 → days>=5 且从未破顶 标 🔥

【回测结论（2026-10-17，400只主板×800根，2023-10~2026-10）】
  WS 双条件信号 1784 个：T+5 +0.60% / T+20 +0.65%（基准 +0.24% / +1.01%），胜率 45% < 基准 47.9%
  「不破实顶 5 日」子集后续更弱（+5日 -1.42%），「跌破实底」后继续持有不显著变差
  → 本形态无独立方向性 alpha（与「主升浪四信号」「峰峦叠翠」一致，属高波动彩票型）
  → 定位：**观察/候选池 + 防守线纪律工具**，不做信号日追买；须叠加环境闸门与自身体系过滤

【用法】
  --scan            扫描最新交易日信号 + 更新跟踪池 + 出报告（默认）
  --pool-file F     股票池（默认 all_mainboard.csv）
  --limit N         K线根数（默认 80，足够 MA15+5日量+20日振幅）
  --max-price P     入池价格门槛：只把「信号日收盘价 < P 元」（默认 10；0=不限）的标的纳入跟踪。
                    涨过 P 元**不再移出**，继续按止盈规则跟踪（标 🎓 出圈）；--cap-mode exit 可回退旧口径
  --cap-mode M      hold（默认）=涨过上限继续跟踪；exit=涨过即移出（旧口径）
  --take-profit     启用止盈（默认开）：浮盈破 MA10 / 峰值回撤 8% / 持有满 60 交易日
  --no-take-profit  只保留「跌破实底」止损
  --tp-ma N         止盈均线周期（默认 10 日）
  --tp-dd X         移动止盈回撤阈值（默认 0.08＝8%）
  --tp-min-gain G   移动止盈启动的浮盈门槛（默认 5%）
  --max-hold N      最长持有交易日（默认 60）
  --date YYYY-MM-DD 指定信号日（默认各股最新K线日）
  --push            推送摘要（PushPlus，env PUSH_TOKEN）
  --no-fetch        只用缓存/池文件，不取数（调试）
"""
import os, sys, json, csv, argparse, subprocess, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE) if os.path.basename(BASE) == "quant_scripts" else BASE
OUT = os.path.join(ROOT, "outputs")
DATA = os.path.join(ROOT, "data")
POOL_F = os.path.join(DATA, "wangzhe_breakout_pool.json")
SNAP = os.path.join(OUT, "wangzhe_breakout_latest.json")

try:
    sys.path.insert(0, BASE)
    from fetch import kline as _fk
except Exception:
    _fk = None


def log(m):
    print(f"[{datetime.now(BJT).strftime('%H:%M:%S')}] {m}", flush=True)


def norm(c):
    c = str(c).strip()
    if c.startswith(("sh", "sz", "bj")):
        return c
    return ("sh" if c[0] == "6" else "sz") + c


def load_pool_file(p):
    rows = []
    with open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = (r.get("code") or "").strip()
            nm = (r.get("name") or "").strip()
            if c and c.isdigit() and len(c) == 6:
                rows.append((c, nm))
    return rows


def _westock_fallback(codes, limit, period="day"):
    """fetch 不可用时的兜底（本地 CLI）。"""
    exe = None
    for p in (os.environ.get("PATH") or "").split(os.pathsep):
        for n in ("westock-data-skillhub",):
            cand = os.path.join(p, n)
            if os.path.exists(cand):
                exe = cand
    if not exe:
        return {}
    out = {}
    for k in range(0, len(codes), 200):
        batch = codes[k:k + 200]
        args = [exe, "kline", ",".join(batch), "--period", period, "--limit", str(limit)]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=180)
        except Exception:
            continue
        out.update(parse_txt(r.stdout or "", limit))
    return out


def parse_txt(txt, limit):
    by, header = {}, None
    for ln in (txt or "").splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or len(parts) < 6 or "---" in parts[0]:
            continue
        try:
            di = header.index("date")
            d = parts[di]
            if len(d) != 10:
                continue
            sym = parts[header.index("symbol")] if "symbol" in header else ""
            bar = {"date": d,
                   "open": float(parts[header.index("open")]),
                   "close": float(parts[header.index("last")]),
                   "high": float(parts[header.index("high")]),
                   "low": float(parts[header.index("low")]),
                   "volume": float(parts[header.index("volume")])}
        except (ValueError, IndexError):
            continue
        by.setdefault(sym, []).append(bar)
    for s in by:
        by[s].sort(key=lambda x: x["date"])
        by[s] = by[s][-limit:]
    return by


def prescreen(codes, min_up=3.0):
    """用腾讯行情快照预筛当日涨幅>=min_up 的候选（把 3000 只取数降到 ~300 只）。
    返回 (candidates, quote_map)；快照不可用返回 (None, {})。"""
    try:
        from fetch import ext_gtimg
    except Exception:
        return None, {}
    syms = [norm(c) for c in codes]
    try:
        q = ext_gtimg(syms, batch=50, timeout=15, retries=2)
    except Exception as e:
        log(f"[WARN] 行情预筛失败: {e}")
        return None, {}
    if len(q) < len(codes) * 0.95:
        log(f"[WARN] 行情覆盖率不足({len(q)}/{len(codes)})，跳过预筛改用全市场K线")
        return None, {}
    keep = []
    for c in codes:
        rec = q.get(norm(c)) or {}
        pct = rec.get("change_pct")
        if pct is not None and pct >= min_up - 0.05:
            keep.append(c)
    return keep, q


def fetch_bars(codes, limit=80, no_fetch=False, batch=100, period="day"):
    """分批取日线（单批 100 只，避免 fetch 内部 120s 超时导致整批丢失）。"""
    if no_fetch:
        return {}
    res = {}
    syms = [norm(c) for c in codes]
    if _fk:
        for k in range(0, len(codes), batch):
            part = syms[k:k + batch]
            try:
                r = _fk(part, period=period, limit=limit)
            except Exception as e:
                log(f"[WARN] fetch.kline 异常({k}): {e}")
                r = {}
            if r:
                for s, bars in r.items():
                    if bars:
                        res[bare(s)] = bars
    if len(res) < len(codes) * 0.5:
        log(f"[WARN] fetch 覆盖不足({len(res)}/{len(codes)})，走本地 CLI 兜底")
        fb = _westock_fallback(syms, limit, period)
        for s, bars in fb.items():
            if bars:
                res.setdefault(bare(s), bars)
    return res


def bare(sym):
    s = str(sym).strip()
    return s[2:] if s.startswith(("sh", "sz", "bj")) and len(s) == 8 else s


def month_strength(mb):
    """曾星智「月线长期力量」5 力：MA5/10/20/30 月均线向上 + 月线 MACD DIF 向上。每项 3 分，满分 15。"""
    if not mb or len(mb) < 34:
        return None
    c = [b["close"] for b in mb]
    cnt = 0
    for n in (5, 10, 20, 30):
        a, b = ma(c, n)[-1], ma(c, n)[-2]
        if a is not None and b is not None and a > b:
            cnt += 1
    def _ema(x, n):
        k, e = 2.0 / (n + 1), None
        for v in x:
            e = v if e is None else v * k + e * (1 - k)
        return e
    d1 = (_ema(c, 12) or 0) - (_ema(c, 26) or 0)
    d0 = (_ema(c[:-1], 12) or 0) - (_ema(c[:-1], 26) or 0)
    if d1 > d0:
        cnt += 1
    return cnt * 3


def ma(x, n):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def eval_last(bars, comp_th=0.03, lp=None):
    """对最后一根K线判定王者突破；返回 dict 或 None。"""
    n = len(bars)
    if n < 25:
        return None
    c = [b["close"] for b in bars]
    o = [b["open"] for b in bars]
    v = [b["volume"] for b in bars]
    cg = ma(c, 15)
    if cg[-1] is None or cg[-2] is None:
        return None
    fl_win = [x for x in cg[-5:] if x is not None]
    flp_win = [x for x in cg[-6:-1] if x is not None]
    if len(fl_win) < 5 or len(flp_win) < 5:
        return None
    fl, flp = max(fl_win), max(flp_win)
    cgv = cg[-1]
    fs = 2 * cgv - fl
    comp = (fl - fs) / cgv if cgv else 9.0          # 尾部张开度：小 = 三线合一
    prev = c[-2]
    up = (c[-1] / prev - 1) * 100 if prev else 0
    cross = c[-1] > fl and prev <= flp
    cg_ne_fs = abs(fl - cgv) > 1e-9                  # CG<>FS ⟺ FL<>CG（均线已回落/走平）
    pv = [x for x in v[-6:-1] if x > 0]
    volx = v[-1] / (sum(pv) / len(pv)) if len(pv) == 5 and v[-1] > 0 else 0
    yang = c[-1] > o[-1]
    shenlong = up >= 3 and cross and cg_ne_fs
    wangbei = volx >= 2 and yang and up >= 3
    if not (shenlong or wangbei):
        return None
    pre = c[-21:-1]
    rng = (max(pre) - min(pre)) / min(pre) * 100 if pre and min(pre) > 0 else 999
    kind = "王者突破" if (shenlong and wangbei) else ("神龙突破" if shenlong else "倍量突破")
    # 评分：量能 35 + 三线合一 25 + 横盘 15 + 月线长期力量 25
    s_vol = 35 * min(volx, 4) / 4
    s_comp = 25 * max(0.0, min(1.0, (comp_th * 2 - comp) / (comp_th * 2))) if comp < comp_th * 2 else 0
    s_rng = 15 * max(0.0, min(1.0, (25 - rng) / 25))
    s_lp = (lp / 15.0) * 25 if lp is not None else 0.0
    score = round(s_vol + s_comp + s_rng + s_lp, 1)
    parts = (s_vol, s_comp, s_rng)
    return dict(date=bars[-1]["date"], close=round(c[-1], 2), open=round(o[-1], 2),
                high=round(bars[-1]["high"], 2), low=round(bars[-1]["low"], 2),
                up=round(up, 2), volx=round(volx, 2), comp=round(comp * 100, 2), rng=round(rng, 1),
                kind=kind, shenlong=shenlong, wangbei=wangbei,
                top=round(c[-1], 2), bottom=round(o[-1], 2), score=score,
                long_power=lp, parts=parts)


def load_pool():
    if os.path.exists(POOL_F):
        try:
            d = json.load(open(POOL_F, encoding="utf-8"))
            return d.get("signals", {}), d.get("removed", [])
        except Exception:
            pass
    return {}, []


def save_pool(sig, removed):
    os.makedirs(DATA, exist_ok=True)
    removed = removed[-2000:]      # 2026-11-18：300→2000（原截断会丢历史，累计了结数倒退）
    json.dump({"updated": datetime.now(BJT).strftime("%Y-%m-%d %H:%M"),
               "signals": sig, "removed": removed},
              open(POOL_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def read_env():
    """读鱼身温度作为环境提示（只提示，不拦信号）。"""
    for rel in ("outputs/fish_body_latest.json", "fish_body_latest.json"):
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                t = d.get("market_temp") or d.get("temp") or (d.get("market") or {}).get("temp")
                if t is not None:
                    return float(t)
            except Exception:
                pass
    return None


def _calc_ma(vals, n):
    out, sm = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        sm += v
        if i >= n:
            sm -= vals[i - n]
        if i >= n - 1:
            out[i] = sm / n
    return out


def update_pool(sig, bars_map, target_date, max_price=0.0, cap_mode="hold",
                take_profit=True, tp_ma=10, tp_dd=0.08, tp_min_gain=5.0, max_hold=60):
    """更新池内状态（逐日、以**收盘价**判定）。出场规则优先级：

      1) 跌破实底（收盘 < 信号日开盘）              -> 跌破实底（止损）
      2) 止盈·破均线：已浮盈 且 收盘跌破 MA{tp_ma}    -> 浮盈破MA{n}止盈
      3) 止盈·移动：一度浮盈>=tp_min_gain% 且 自最高收盘回撤>=tp_dd -> 峰值回撤止盈
      4) 持有满 max_hold 个交易日                   -> 持有到期

    价格上限 --max-price **只做入池筛选**：起始价<上限的标的涨过上限后**继续跟踪**
    （cap_mode="exit" 才回退「涨破即移出」的旧口径）。

    注：信号日必为涨幅>=3% 的阳线（收盘>开盘），故「跌破实底」的收益在数学上恒为负、
    胜率恒为 0%，它只代表止损单的损伤，不能当作策略胜率。

    返回 (still, removed_today)
    """
    still, removed_today = {}, []
    for code, it in sig.items():
        bars = bars_map.get(code) or []
        if not bars:
            it["note"] = "今日无数据（停牌？）"
            still[code] = it
            continue
        last = bars[-1]
        close = last["close"]
        it["last_date"] = last["date"]
        it["last_close"] = round(close, 2)
        since = [b for b in bars if b["date"] > it.get("signal_date", "")]
        it["days"] = max(int(it.get("days") or 0), len(since))   # 只前进不倒退
        it["last_date_prev"] = last["date"]
        it["peak"] = max(it.get("peak") or 0, round(close, 2))
        it["max_gain"] = round((it["peak"] / it["sig_close"] - 1) * 100, 2) if it.get("sig_close") else 0
        it["dist_bottom"] = round((close / it["sig_open"] - 1) * 100, 2) if it.get("sig_open") else 0
        gain = (close / it["sig_close"] - 1) * 100 if it.get("sig_close") else 0.0

        # 出圈：涨过入池门槛后继续跟踪（只打标，不退出）
        if max_price and close >= max_price and not it.get("graduate"):
            it["graduate"] = True
            it["graduate_date"] = last["date"]
            it["graduate_price"] = round(close, 2)

        # 旧口径（可选）：涨破上限即移出
        if cap_mode == "exit" and max_price and close >= max_price:
            it.update(exit_date=last["date"], exit_price=round(close, 2),
                      exit_reason="超出价格上限", ret=round(gain, 2))
            removed_today.append(it)
            continue

        # 1) 止损：跌破实底
        if close < it["sig_open"]:
            it.update(exit_date=last["date"], exit_price=round(close, 2),
                      exit_reason="跌破实底", ret=round(gain, 2))
            removed_today.append(it)
            continue

        # 2) 止盈
        reason = None
        if take_profit:
            m = _calc_ma([b["close"] for b in bars], tp_ma)[-1] if len(bars) >= tp_ma else None
            if gain > 0 and m and close < m:
                reason = "浮盈破MA%d止盈" % tp_ma
            elif it["max_gain"] >= tp_min_gain and close <= it["peak"] * (1 - tp_dd):
                reason = "峰值回撤%d%%止盈" % round(tp_dd * 100)
        if reason:
            it.update(exit_date=last["date"], exit_price=round(close, 2),
                      exit_reason=reason, ret=round(gain, 2))
            removed_today.append(it)
            continue

        # 3) 持有到期
        if max_hold and it["days"] >= max_hold:
            it.update(exit_date=last["date"], exit_price=round(close, 2),
                      exit_reason="持有到期", ret=round(gain, 2))
            removed_today.append(it)
            continue

        it["status"] = "强" if close >= it["sig_close"] else "观察"
        it["hold_top_days"] = max(int(it.get("hold_top_days") or 0),
                                  sum(1 for b in since if b["close"] >= it["sig_close"]))
        still[code] = it
    return still, removed_today


def backfill_exit_after(removed_all, bars_map):
    """回填「出场后 5/10/20 交易日」涨跌（正=出场过早）。只用本次已取到的K线，不额外取数。"""
    n = 0
    for x in removed_all:
        if x.get("exit_date") is None or x.get("after20") is not None:
            continue
        bars = bars_map.get(x.get("code")) or []
        dates = [b["date"] for b in bars]
        if x["exit_date"] not in dates:
            continue
        k = dates.index(x["exit_date"])
        px = x.get("exit_price") or bars[k]["close"]
        if not px:
            continue
        got = False
        for h in (5, 10, 20):
            key = "after%d" % h
            if x.get(key) is None and k + h < len(bars):
                x[key] = round((bars[k + h]["close"] / px - 1) * 100, 2)
                got = True
        if got:
            n += 1
    return n


def build_report(date, news, sig, removed_today, removed_all, temp, stats, limit, max_price=0.0):
    L = []
    L.append(f"# 👑 王者突破选股 · {date}")
    L.append("")
    L.append("> 口径：**神龙摆尾尾部突破K**（涨幅≥3% + 收盘上穿 HHV(MA15,5) + CG≠FS）× **王者倍量柱**（量≥2×前5日均量 + 阳线）")
    L.append("> 防守：信号K **实顶=收盘**（强支撑）、**实底=开盘**（破则出局）。跟踪池每日更新，**跌破实底即删除**。")
    if max_price:
        L.append(f"> 入池：**信号日收盘价 < {max_price:g} 元**；涨过上限**不再移出**，继续按止盈规则跟踪（🎓 出圈）")
    L.append("> 止盈：①已浮盈且收盘跌破 **MA10** ②自最高收盘回撤 **8%**（浮盈≥5% 起启用）③持有满 **60** 个交易日；止损：收盘**跌破实底**")
    if temp is not None:
        tag = "🟢" if temp >= 55 else ("🟡" if temp >= 40 else "🔴")
        L.append(f"> 环境：鱼身温度 **{temp:.0f}** {tag}" + ("（低温，信号弱化，仅观察）" if temp < 40 else ""))
    L.append("")
    main_news = [x for x in news if x["kind"] == "王者突破"]
    watch = [x for x in news if x["kind"] != "王者突破"]
    L.append(f"## 一、今日新信号 · 🌟王者突破（价量双确认，{len(main_news)} 只）")
    if main_news:
        L.append("")
        L.append("| 代码 | 名称 | 收盘 | 涨幅% | 量比倍数 | 三线张开% | 前20日振幅% | 月线5力 | 实顶(守) | 实底(损) | 评分 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for x in sorted(main_news, key=lambda z: -z["score"]):
            L.append(f"| {x['code']} | {x['name']} | {x['close']} | {x['up']:+.2f} | {x['volx']:.2f} | "
                     f"{x['comp']:.2f} | {x['rng']:.1f} | {x.get('long_power', '-')} | {x['top']} | {x['bottom']} | {x['score']:.1f} |")
    else:
        L.append("")
        L.append("📭 今日无「王者突破」（量能与均线突破同日共振）信号。")
    L.append("")
    L.append(f"## 一·附｜单条件观察（不入池，{len(watch)} 只，列前 15）")
    if watch:
        L.append("")
        L.append("| 代码 | 名称 | 收盘 | 涨幅% | 量比倍数 | 类型 | 实顶(守) | 实底(损) | 评分 |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for x in sorted(watch, key=lambda z: -z["score"])[:15]:
            L.append(f"| {x['code']} | {x['name']} | {x['close']} | {x['up']:+.2f} | {x['volx']:.2f} | "
                     f"{x['kind']} | {x['top']} | {x['bottom']} | {x['score']:.1f} |")
        L.append("")
        L.append("> 单条件 = 只有量能（倍量）或只有均线突破，缺一条腿；仅观察，不入跟踪池。")
    L.append("")
    L.append(f"## 二、跟踪池（{len(sig)} 只）")
    if sig:
        L.append("")
        L.append("| 状态 | 代码 | 名称 | 信号日 | 持有(交易日) | 最新价 | 实顶(守) | 实底(损) | 距实底% | 最高浮盈% | 评分 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        order = {"强": 0, "观察": 1}
        for x in sorted(sig.values(), key=lambda z: (order.get(z.get("status"), 2), -z.get("hold_top_days", 0))):
            flag = "🔥" if x.get("status") == "强" and x.get("hold_top_days", 0) >= 5 else x.get("status", "")
            L.append(f"| {flag} | {x['code']} | {x['name']} | {x['signal_date']} | {x.get('days', 0)} | "
                     f"{x.get('last_close', '-')} | {x['sig_close']} | {x['sig_open']} | "
                     f"{x.get('dist_bottom', 0):+.2f} | {x.get('max_gain', 0):+.2f} | {x.get('score', 0):.1f} |")
        L.append("")
        L.append("> 🔥 = 不破实顶 ≥5 个交易日（文章「长期横盘不破突破K顶」形态）")
        grad = [x for x in sig.values() if x.get("graduate")]
        if grad:
            L.append(f"> 🎓 其中 **{len(grad)}** 只已涨过入池门槛仍在跟踪（不再移出）：" +
                     "、".join(f"{x['code']} {x['name']}({x.get('last_close', '-')})" for x in grad[:12]))
    else:
        L.append("")
        L.append("（池内为空）")
    L.append("")
    L.append(f"## 三、今日移出（{len(removed_today)} 只，含止损/止盈/到期）")
    if removed_today:
        L.append("")
        L.append("| 代码 | 名称 | 信号日 | 移出日 | 出场价 | 相对信号收盘% | 原因 |")
        L.append("|---|---|---|---|---|---|---|")
        for x in removed_today:
            L.append(f"| {x['code']} | {x['name']} | {x['signal_date']} | {x['exit_date']} | {x['exit_price']} | "
                     f"{x['ret']:+.2f} | {x.get('exit_reason', '跌破实底')} |")
    else:
        L.append("")
        L.append("（无）")
    L.append("")
    L.append("## 四、池内已了结统计")
    if removed_all:
        # 全口径：所有真实了结（含历史「涨破上限」项），只剔除历史脏数据（invalid）
        valid = [x for x in removed_all
                 if x.get("ret") is not None and not x.get("invalid")]
        dirty = [x for x in removed_all if x.get("invalid")]
        legacy = [x for x in valid if x.get("exit_reason") == "超出价格上限"]
        L.append("")
        if valid:
            rs = [x["ret"] for x in valid]
            win = sum(1 for r in rs if r > 0)
            med = sorted(rs)[len(rs) // 2]
            L.append(f"- **全口径了结 {len(rs)} 只**：胜率 **{100*win/len(rs):.1f}%**，"
                     f"平均 **{sum(rs)/len(rs):+.2f}%**，中位 **{med:+.2f}%**（含止盈/止损/到期）")
            L.append(f"- 最长持有 {max([x.get('days', 0) for x in valid] or [0])} 个交易日")
            L.append("")
            L.append("| 出场原因 | 只数 | 胜率 | 均值 | 中位 |")
            L.append("|---|---|---|---|---|")
            groups = {}
            for x in valid:
                groups.setdefault(x.get("exit_reason") or "未标注", []).append(x["ret"])
            for why, arr in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                w2 = sum(1 for r in arr if r > 0)
                a2 = sorted(arr)[len(arr) // 2]
                L.append(f"| {why} | {len(arr)} | {100*w2/len(arr):.1f}% | {sum(arr)/len(arr):+.2f}% | {a2:+.2f}% |")
            L.append("")
            L.append("> ⚠️ 「跌破实底」胜率恒为 0.0% 是定义决定的：信号日必为涨幅≥3% 的阳线（收盘>开盘），"
                     "而跌破实底=收盘<开盘 → 相对信号收盘必然为负。它只衡量止损单的损伤，**不是策略胜率**。")
            aft = [x for x in valid if x.get("after5") is not None]
            if aft:
                seg = " / ".join(
                    f"{k}日 {sum(x[k] for x in aft if x.get(k) is not None)/max(1,len([x for x in aft if x.get(k) is not None])):+.2f}%"
                    for k in ("5", "10", "20") if any(x.get("after" + k) is not None for x in aft))
                L.append(f"- 出场后表现（已回填 {len(aft)} 只，正=出场过早）：{seg}")
        if legacy:
            _lr = [x["ret"] for x in legacy]
            L.append(f"- 其中旧口径「涨破价格上限」移出 {len(legacy)} 只："
                     f"均值 {sum(_lr)/len(_lr):+.2f}%（已停用，现改为出圈继续跟踪）")
        if dirty:
            L.append(f"- 🧹 历史脏数据 {len(dirty)} 条（信号日收盘 ≥ 入池门槛，旧参数遗留）已剔除统计")
    else:
        L.append("")
        L.append("（暂无）")
    L.append("")
    L.append("## 五、使用说明（重要）")
    L.append("")
    L.append("- **回测结论**（400只主板×800根）：双条件信号 T+20 +0.65% vs 基准 +1.01%，胜率 45% vs 47.9% → **本形态无独立方向性 alpha**，不可信号日追买。")
    L.append("- 定位：**候选观察池 + 纪律跟踪**。真正的用法是「入池 → 等回踩实顶附近/缩量横盘 → 结合双弦·猛兽·鱼身共振再做」；止损=收盘跌破实底，止盈=浮盈破MA10 / 峰值回撤8%。")
    L.append("- 环境闸门：鱼身温度 <40（🔴）时全部信号降级为观察，不介入。")
    L.append("")
    L.append(f"> 生成：wangzhe_breakout.py · 扫描 {stats.get('scanned', 0)} 只 / 覆盖 {stats.get('covered', 0)} / 池 {len(sig)} / 新增 {len(news)} / 删除 {len(removed_today)}")
    return "\n".join(L)


def push_md(title, md):
    tok = os.environ.get("PUSH_TOKEN")
    if not tok:
        log("[WARN] 无 PUSH_TOKEN，跳过推送")
        return
    body = urllib.parse.urlencode({"token": tok, "title": title, "content": md, "template": "markdown"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            "https://www.pushplus.plus/send", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=20).read()
        log("推送已发送")
    except Exception as e:
        log(f"[WARN] 推送失败: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--pool-file", default=os.path.join(ROOT, "all_mainboard.csv"))
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--date", default="")
    ap.add_argument("--comp-th", type=float, default=0.03)
    ap.add_argument("--max-new", type=int, default=40)
    ap.add_argument("--max-price", type=float, default=10.0,
                    help="入池价格门槛：仅信号日收盘价低于该值才入池（默认 10 元；0=不限）；涨过不再移出")
    ap.add_argument("--cap-mode", choices=["hold", "exit"], default="hold",
                    help="hold=涨过门槛继续跟踪（默认）；exit=涨过即移出（旧口径）")
    ap.add_argument("--take-profit", dest="take_profit", action="store_true", default=True)
    ap.add_argument("--no-take-profit", dest="take_profit", action="store_false")
    ap.add_argument("--tp-ma", type=int, default=10, help="止盈均线周期（默认 10）")
    ap.add_argument("--tp-dd", type=float, default=0.08, help="移动止盈回撤阈值（默认 0.08）")
    ap.add_argument("--tp-min-gain", type=float, default=5.0, help="移动止盈启动浮盈门槛（默认 5%%）")
    ap.add_argument("--max-hold", type=int, default=60, help="最长持有交易日（默认 60）")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--with-month", action="store_true", default=True)
    ap.add_argument("--no-month", dest="with_month", action="store_false")
    a = ap.parse_args()

    if not os.path.exists(a.pool_file):
        pool_file = os.path.join(BASE, "all_mainboard.csv")
    else:
        pool_file = a.pool_file
    codes_names = load_pool_file(pool_file)
    log(f"股票池 {len(codes_names)} 只（{os.path.basename(pool_file)}）")

    sig, removed_all = load_pool()
    all_codes = [c for c, _ in codes_names]
    cand, qmap = prescreen(all_codes)
    if cand is None:
        targets = list(all_codes)
        log("预筛不可用 → 全市场取数")
    else:
        # 池内标的必须参与更新（即使今日涨幅不足3%）
        if a.max_price and qmap:
            n0 = len(cand)
            keep = []
            for c in cand:
                px = (qmap.get(norm(c)) or {}).get("price")
                if px is None or px <= 0 or px < a.max_price:
                    keep.append(c)
            cand = keep
            log(f"价格预筛：涨幅≥3% {n0} 只 → 现价<{a.max_price:g} 元 {len(cand)} 只")
        targets = sorted(set(cand) | {c for c in sig if c in set(all_codes)})
        log(f"预筛：涨幅≥3% 的 {len(cand)} 只 + 池内 {len(sig)} 只 → 取数 {len(targets)} 只")

    bars_map = fetch_bars(targets, a.limit, a.no_fetch)
    log(f"取数完成：{len(bars_map)} 只")

    mb_map = {}

    # 目标信号日 = 多数股票最新K线日
    from collections import Counter
    dates = Counter(b["date"] for bs in bars_map.values() if bs for b in bs[-1:])
    target = a.date or (dates.most_common(1)[0][0] if dates else datetime.now(BJT).strftime("%Y-%m-%d"))
    log(f"信号日 = {target}（样本 {dates.most_common(1)[0][1] if dates else 0} 只同日期）")

    name_map = dict(codes_names)
    news = []
    for code in list(bars_map.keys()):
        bars = bars_map.get(code) or []
        if not bars or bars[-1]["date"] != target:
            continue
        lp = month_strength(mb_map.get(code)) if mb_map else None
        s = eval_last(bars, a.comp_th, lp)
        if not s:
            continue
        s["code"], s["name"] = code, (name_map.get(code) or "").strip()
        if s["close"] < 3:
            continue
        if a.max_price and s["close"] >= a.max_price:
            continue
        news.append(s)

    # 月线长期力量：只对「王者突破」候选取（全量取太慢）
    dups = [x for x in news if x["kind"] == "王者突破"]
    if a.with_month and dups and not a.no_fetch:
        log(f"月线取数（仅王者突破 {len(dups)} 只）...")
        mb_map = fetch_bars([x["code"] for x in dups], 60, False, batch=100, period="month")
        for x in dups:
            lp = month_strength(mb_map.get(x["code"]))
            x["long_power"] = lp
            if lp is not None:
                x["score"] = round(sum(x.get("parts") or (0, 0, 0)) + (lp / 15.0) * 25, 1)
        log(f"月线完成 {len(mb_map)} 只")

    # 先更新旧池（用今日数据）
    sig, removed_today = update_pool(sig, bars_map, target, a.max_price,
                                     cap_mode=a.cap_mode, take_profit=a.take_profit,
                                     tp_ma=a.tp_ma, tp_dd=a.tp_dd,
                                     tp_min_gain=a.tp_min_gain, max_hold=a.max_hold)
    removed_all.extend(removed_today)

    # 新信号入池：只收「王者突破」双确认（单条件仅列观察，不入池）
    added = 0
    for s in sorted([x for x in news if x["kind"] == "王者突破"], key=lambda z: -z["score"]):
        if s["code"] in sig or added >= a.max_new:
            continue
        sig[s["code"]] = dict(code=s["code"], name=s["name"], signal_date=s["date"],
                              sig_close=s["close"], sig_open=s["open"], sig_high=s["high"],
                              volx=s["volx"], comp=s["comp"], rng=s["rng"], kind=s["kind"],
                              score=s["score"], long_power=s.get("long_power"),
                              status="观察", days=0, hold_top_days=0,
                              last_date=s["date"], last_close=s["close"], peak=s["close"],
                              max_gain=0.0, dist_bottom=0.0, last_date_prev=s["date"])
        added += 1

    n_aft = backfill_exit_after(removed_all, bars_map)
    if n_aft:
        log(f"出场后表现回填 {n_aft} 条")
    save_pool(sig, removed_all)
    temp = read_env()
    md = build_report(target, news, sig, removed_today, removed_all, temp,
                      dict(scanned=len(codes_names), covered=len(bars_map)), a.limit, a.max_price)
    os.makedirs(OUT, exist_ok=True)
    rp = os.path.join(OUT, f"王者突破_{target}.md")
    open(rp, "w", encoding="utf-8").write(md)
    _valid = [x for x in removed_all if x.get("ret") is not None and not x.get("invalid")]
    _why = {}
    for _x in _valid:
        _why[_x.get("exit_reason") or "未标注"] = _why.get(_x.get("exit_reason") or "未标注", 0) + 1
    json.dump({"date": target, "new": news, "pool": list(sig.values()), "temp": temp,
               "removed_today": removed_today,
               "stats": dict(scanned=len(codes_names), covered=len(bars_map), pool=len(sig),
                             graduate=sum(1 for x in sig.values() if x.get("graduate")),
                             closed=len(_valid),
                             winrate=round(100 * sum(1 for x in _valid if x["ret"] > 0) / len(_valid), 1) if _valid else None,
                             avg_ret=round(sum(x["ret"] for x in _valid) / len(_valid), 2) if _valid else None,
                             by_reason=_why)},
              open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"报告 {rp}；新信号 {len(news)}，池 {len(sig)}，移出 {len(removed_today)}")

    if a.push:
        lines = [f"### 👑 王者突破 {target}", f"- 新信号 **{len(news)}** / 池内 **{len(sig)}** / 移出 **{len(removed_today)}**"]
        if temp is not None:
            lines.append(f"- 鱼身温度 {temp:.0f}" + ("（低温仅观察）" if temp < 40 else ""))
        for s in sorted(news, key=lambda z: -z["score"])[:10]:
            lines.append(f"- {s['code']} {s['name']} 收{s['close']} 量{s['volx']:.1f}× 守{s['top']}/损{s['bottom']} 分{s['score']:.0f}")
        if removed_today:
            lines.append("- 移出：" + "、".join(f"{x['name']}({x['ret']:+.1f}%·{x.get('exit_reason','')})"
                                                for x in removed_today[:8]))
        _g = [x for x in sig.values() if x.get("graduate")]
        if _g:
            lines.append(f"- 🎓 已涨过入池门槛仍在跟踪 {len(_g)} 只：" +
                         "、".join(f"{x['name']}({x.get('last_close','-')})" for x in _g[:8]))
        push_md(f"👑王者突破 {target}", "\n".join(lines))


if __name__ == "__main__":
    main()
