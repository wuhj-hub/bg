#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反转数值 · 日线/周线/月线信号跟踪轮动器（reversal_daily_screener.py · v7.7）
=====================================================================
口径（《反转数值MACD指标_优化版_代码》改①）：
  反转数值 = 0.618 × |MACD|
  S1 突破2倍反转数值 : MACD > 2×0.618×BL_DEEP（BL_DEEP=死叉以来最深绿柱）且 MACD 上升
  S2 回踩不破线（分角度，2026-10-29 v7.7 起，日/周/月统一；用户选「信号严、跟踪稳」）:
     改1（突破后未下水）= 原指标 AA + ★：
         AA   := MACD>0 AND MACD > 2×0.618×ABS(LLV(MACD,SCB))（BL_DEEP=死叉以来最深绿柱）
         ★    := AA AND MACD>REF(MACD,1)          ——【入池条件】当下在突破2倍值之上且红柱放大
         存续  := AA                              ——入池后只要仍在突破位上方即继续跟踪，
                                                     当日红柱缩量不踢出；跌破突破2倍值才移出
     改2（突破后死叉下水）：回调深 = |LLV(MACD, 突破以来)| ≤ 0.618 × HHV(MACD, 金叉以来)
  信号 = S1 已发生 且 S2 成立 且 死叉之后（SCB>0 且 JCB>SCB）；现价 < 上限（默认10元）
  【2026-10-17 新增】突破段中大阳线：突破日所属「金叉」→「突破日」整段内，须出现至少一根
     涨幅 ≥ --big-yang-pct（默认5%）的阳线（涨停板自然满足）；
     2026-10-18 起三周期（日/周/月）均要求该条件

跟踪轮动（v2 新增）：
  · 每次运行把命中标的并入**跟踪池**（data/reversal_pool_{tf}.json），跨日/跨周保留
  · 后续若**跌破**（回调深 ≥ 1倍反转数值）→ 从池中**删除**
  · 另两类移出：现价 ≥ 上限、距突破超过最大跟踪期（日线45根 / 周线30根 / 月线18根）
  · 报告区分：本次新增 / 在池跟踪 / 本次移除
  · 【v7·2026-10-18】①分角度窗口：改1 走 --window（day5/week3/month2）；改2 走 --window-gai2
     （day5/week8/month4）——改2 需「突破→回调→死叉」的演化时间，用改1 的窄窗口会把改2 全部挡掉
     （实测全市场周/月线新增 0 只改2）。②存量观察区按 --watch-max-gap 截断（day15/week8/month6），
     避免月线观察区膨胀到数百只。③周/月线「突破段大阳线」区间改为「突破日前 N 根」
     （--bigyang-lookback，默认 week6/month6；日线仍为「突破日所属金叉→突破日」）——
     月线金叉可跨 1-2 年，原口径下该条件几乎形同虚设
  · 【v6·2026-10-18】报告各节（新增/在池/移除/观察）一律按角度归类为「改1 / 改2」两组子表，
     并给出角度分布统计
  · 【v5·2026-10-18】另设「📎 存量结构观察」：结构仍有效（valid + 有突破段大阳线）但不满足入池条件
     （超新信号窗口）的标的单列展示，**不入池、不计胜率**，仅作形态跟踪
  · 【v7.2·2026-10-18】观察区同样要求「现价 < --max-price」——全表（新增/在池/移除/观察）
     价格门槛统一，不再把超价标的混进观察区
  · 【v7.7·2026-10-29】用户选「信号严、跟踪稳」：改1 **入池**用 ★（AA AND MACD 上升）、
     **存续**只用 AA（MACD>0 AND MACD>2×0.618×BL_DEEP）——避免红柱缩量一天就被踢出、
     次日又重入池导致 first_date 重置、胜率统计失真。移除原因：跌破突破2倍值 / MACD 已下水。
  · 【v7.6·2026-10-29】改1 判定对齐原指标 AA + ★：**MACD>0 AND MACD>2×0.618×ABS(LLV(MACD,SCB))
     AND MACD>REF(MACD,1)**——用「当前 MACD」而非「突破以来最低值」，并要求红柱仍在放大；
     报告「回调深」列对改1 改显示「MACD 现值」，便于与「不破线(=突破2倍值)」直接对照。
  · 【v7.5·2026-10-29】用户口径：**改1（保持强势）判定改为「自突破以来 MACD 最低值 ≥ 突破2倍值」**
     （m_low ≥ 2×0.618×死叉以来最深绿柱，即「突破后不下来」、不跌回突破位）；日/周/月三周期统一。
     原口径「回踩幅度 < 0.618×金叉以来最高红柱」废止。报告「不破线」列对改1 显示突破2倍值、
     对改2 仍显示 −0.618×H；移除原因相应区分为「跌破突破2倍值」/「跌破1倍反转数值」。
  · 【v7.4·2026-10-23】取消「新信号窗口」的改动由日线**扩展到周线/月线**（三周期统一）；
     同时撤销「创业板入池」尝试（股票池回到 all_mainboard.csv）。--use-window 可整体回退。
  · 【v7.3·2026-10-23】日线**取消「新信号窗口」**（--use-window 可回退）：结构有效即入池，
     仅受最大跟踪期约束（gap ≤ MAXGAP[tf]），存量观察区随之关闭；改2 判定明确为
     「回调至水下、且 MACD 不低于 −0.618×金叉以来最高红柱」（改1 保持「回踩幅度<0.618H」）；
     死叉当日（SCB==0）不再判「无结构」，消除在池票逢死叉日被移出、次日又入池的抖动；
     --pool-file 支持逗号分隔多文件（主板 + 创业板）

口径（v4 · 2026-10-18 周/月线对齐日线）：
  · 三周期统一：改1 + 改2 双角度都收
  · 三周期统一：新信号须在窗口内（--window，默认 day=5 / week=3 / month=2）
  · 三周期统一：须有「突破段中大阳线」（≥ --big-yang-pct，默认5%）
  · 仅存的差异：最大跟踪期（日线45根 / 周线30根 / 月线18根）、数据周期与长度
用法:
  python3 reversal_daily_screener.py --tf day   --window 5 --max-price 10 --pool-file all_mainboard.csv
  python3 reversal_daily_screener.py --tf week  --max-price 10 --pool-file all_mainboard.csv
  python3 reversal_daily_screener.py --tf month --max-price 10 --pool-file all_mainboard.csv
输出: outputs/反转数值日线信号_{date}.md（day）/ outputs/反转数值周线跟踪_{date}.md（week）
      / outputs/反转数值月线跟踪_{date}.md（month）
"""
import os, sys, re, json, subprocess, argparse, shutil, time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
_W = shutil.which("westock-data-skillhub")
WESTOCK = _W if _W else "npx -y westock-data-skillhub@1.0.3"
BATCH = 100    # 2026-10-23：250/批在实测中覆盖不足（返回 success 但丢股），改 100/批 + 批间退避
K = 0.618
BIG_YANG_PCT = 0.05    # 突破段「中大阳线」涨幅阈值（>=5%；涨停板自然满足）
POOL_DIR = os.path.join(ROOT, "data")
MAXGAP = {"day": 45, "week": 30, "month": 18}   # 最大跟踪期（根）


def _fetch_layer(args, timeout):
    """统一取数层（fetch.raw；免npx + 重试退避 + 超时）。不可用/空返回 -> ""（回退原实现）。
    2026-10-16 阶段3 迁移（见 docs/取数层迁移进度.md）。"""
    try:
        for _p in (BASE, ROOT):
            if _p and _p not in sys.path:
                sys.path.insert(0, _p)
        from fetch import raw as _fraw
        out = _fraw(list(args), timeout=timeout) or ""
        if out.strip() and "执行失败" not in out and "SKILL_0" not in out:
            return out
    except Exception:
        pass
    return ""


def _westock_run(args, timeout=300):
    """本地 westock CLI 兜底（fetch.raw 不可用/空返回时）。"""
    cmd = (WESTOCK.split() if isinstance(WESTOCK, str) else [WESTOCK]) + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def ema(series, n):
    out = [series[0]]
    k = 2 / (n + 1)
    for x in series[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def calc_dif_dea(closes):
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a / c * 100 - b / c * 100 for a, b, c in zip(e12, e26, closes)]
    dea = ema(dif, 9)
    macd = [(d - e) * 2 for d, e in zip(dif, dea)]
    return dif, dea, macd


def _line_signed(s):
    """改1->突破2倍值（2×0.618×死叉以来最深绿柱，「突破后不下来」的线）；改2->−0.618×H（水下1倍线）"""
    if s.get("angle") == "改1":
        return float(s.get("tp_val", 0))
    return -float(s.get("line", 0))


def fetch_batch(codes, period="day", limit=250):
    out = {}
    for i in range(0, len(codes), BATCH):
        batch = codes[i:i + BATCH]
        try:
            _args = ["kline", ",".join(batch), "--period", str(period), "--limit", str(limit)]
            _out = _fetch_layer(_args, 300)
            if not _out:
                _out = _westock_run(_args, 300)
            if not _out or _out.strip() == "数据为空":
                time.sleep(3)
                _out = _fetch_layer(_args, 300) or _westock_run(_args, 300)
            rm = {}
            for ln in _out.splitlines():
                m = re.match(r"\|\s*([a-z]{2}\d{6})\s*\|\s*([\d-]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
                if m:
                    rm.setdefault(m.group(1), []).append(
                        (m.group(2), float(m.group(3)), float(m.group(4)), float(m.group(5)), float(m.group(6))))
                elif len(batch) == 1:
                    # 单只调用时 westock 输出不含 symbol 列（2026-10-23 补）
                    m2 = re.match(r"\|\s*([\d-]{10})\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
                    if m2:
                        rm.setdefault(batch[0], []).append(
                            (m2.group(1), float(m2.group(2)), float(m2.group(3)), float(m2.group(4)), float(m2.group(5))))
            for sym, rows in rm.items():
                rows.sort(key=lambda x: x[0])
                out[sym] = rows
        except Exception as e:
            print(f"  [warn] 批{i//BATCH+1}拉取失败: {e}")
        time.sleep(0.4)
    return out


def eval_state(rows, lookback_tp=120, big_yang_pct=BIG_YANG_PCT, min_bars=80, bigyang_lookback=0):
    """对一只股票评估当前状态: 是否'突破2倍后回调不破1倍'，且突破段含中大阳线
    返回 dict(tp_date,tp_val,red_high,pullback,line,valid,big_yang,by_date,by_gain,gap,last_date,last_close) 或 None"""
    if len(rows) < min_bars:
        return None
    closes = [r[2] for r in rows]
    dif, dea, macd = calc_dif_dea(closes)
    n = len(macd)
    JC = [False] * n; SC = [False] * n
    for i in range(1, n):
        JC[i] = dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]
        SC[i] = dif[i] < dea[i] and dif[i - 1] >= dea[i - 1]
    JCB = [None] * n; SCB = [None] * n
    lj = ls = None
    for i in range(n):
        if JC[i]: lj = i
        if SC[i]: ls = i
        JCB[i] = None if lj is None else i - lj
        SCB[i] = None if ls is None else i - ls
    i = n - 1
    if SCB[i] is None or JCB[i] is None:
        return None
    bl = abs(min(macd[max(0, i - int(SCB[i])):i + 1]))
    tp_bar = None
    for kk in range(max(1, n - lookback_tp), n):
        if SCB[kk] is None:
            continue
        b2 = abs(min(macd[max(0, kk - int(SCB[kk])):kk + 1]))
        if macd[kk] > 2 * K * b2 and macd[kk] > macd[kk - 1]:
            tp_bar = kk
    if tp_bar is None:
        return None
    seg = macd[tp_bar:i + 1]
    red_high = max(seg)
    m_low = min(seg)                      # 自突破以来 MACD 最低值（可为负）
    deep = abs(m_low)
    line = K * max(macd[max(0, i - int(JCB[i])):i + 1])
    # ── 需求(2026-10-17)：突破段须出现「中大阳线」（涨幅>=big_yang_pct，涨停板自然满足）──
    #    范围 = 突破日所属「金叉」→「突破日」整段（对应底部反转的启动过程）；by_* 记录涨幅最大的那根阳线
    if bigyang_lookback and int(bigyang_lookback) > 0:
        lj_tp = max(1, tp_bar - int(bigyang_lookback) + 1)        # 突破日前 N 根（含突破日）
    else:
        lj_tp = tp_bar - (int(JCB[tp_bar]) if JCB[tp_bar] is not None else 0)
    by_idx, by_gain = None, 0.0
    for j in range(max(1, lj_tp), tp_bar + 1):
        if rows[j][2] > rows[j][1]:                       # 阳线（收 > 开）
            g = rows[j][2] / rows[j - 1][2] - 1
            if g >= big_yang_pct and g > by_gain:
                by_idx, by_gain = j, g
    big_yang = by_idx is not None
    return {"tp_date": rows[tp_bar][0], "tp_val": round(2 * K * bl, 2),
            "red_high": round(red_high, 2), "pullback": round(deep, 2),
            "line": round(line, 2), "m_low": round(m_low, 2),
            "angle": ("改1" if m_low > 0 else "改2"),
            # 2026-10-29 用户口径 v7.6（日/周/月统一，对齐原指标 AA + ★ 条件）：
            #   改1（保持强势）= AA 且 MACD 上升
            #       AA := MACD>0 AND MACD > 2×0.618×ABS(LLV(MACD,SCB))（当前值仍在突破2倍值之上）
            #       即「突破后不下来、当下仍在突破位上方且红柱未缩」
            #   改2（死叉回调）= 回调至水下、且 MACD 不低于 −0.618×金叉以来最高红柱（不变）
            #   改1 存续（valid）只需 AA：MACD>0 且 MACD>2×0.618×BL_DEEP（当日红柱缩量不踢出）
            #   改1 入池（star）需 ★：AA 且 MACD>REF(MACD,1)
            "valid": ((macd[i] > 0 and macd[i] > 2 * K * bl) if m_low > 0 else (deep <= line)),
            "star": ((macd[i] > 0 and macd[i] > 2 * K * bl and macd[i] > macd[i - 1]) if m_low > 0 else None),
            "macd_now": round(macd[i], 2),
            "big_yang": big_yang, "by_date": (rows[by_idx][0] if by_idx is not None else ""),
            "by_gain": round(by_gain * 100, 1),
            "gap": i - tp_bar, "last_date": rows[-1][0], "last_close": round(closes[-1], 2)}


def load_pool(pool_arg="", pool_file=""):
    """读股票池；--pool-file 支持逗号分隔多文件（2026-10-23 起：all_mainboard.csv,all_chinext.csv）"""
    if pool_arg:
        return [(c.strip(), "") for c in pool_arg.split(",") if c.strip()]
    names = [x.strip() for x in (pool_file or "hs300.csv").split(",") if x.strip()]
    rows, used = [], []
    for name in names:
        cands = [name] if os.path.isabs(name) else [
            os.path.join(BASE, name), os.path.join(ROOT, name), os.path.join(os.getcwd(), name)]
        fp = next((p for p in cands if os.path.exists(p)), None)
        if not fp:
            print(f"  [warn] 未找到股票池文件: {name}")
            continue
        used.append(os.path.basename(fp))
        for ln in open(fp, encoding="utf-8-sig"):
            p = ln.strip().split(",")
            if len(p) < 2:
                continue
            nm = p[1]
            if "ST" in nm.upper().replace(" ", "") or "退" in nm:
                continue
            if p[0].startswith(("sh", "sz")):
                rows.append((p[0], nm))
            elif re.match(r"^\d{6}$", p[0]):
                rows.append((("sh" if p[0].startswith("6") else "sz") + p[0], nm))
    if not rows:
        print(f"  [warn] 股票池为空: {names}")
    # 去重（多池合并时可能重叠）
    seen, uniq = set(), []
    for c, nm in rows:
        if c in seen:
            continue
        seen.add(c); uniq.append((c, nm))
    return uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="day", choices=["day", "week", "month"])
    ap.add_argument("--pool", default="")
    ap.add_argument("--pool-file", default="")
    ap.add_argument("--window", type=int, default=0,
                    help="改1（保持强势）新信号窗口(根)；默认 day=5 / week=3 / month=2")
    ap.add_argument("--window-gai2", type=int, default=0,
                    help="改2（死叉回调）新信号窗口(根)；默认 day=5 / week=8 / month=6")
    ap.add_argument("--watch-max-gap", type=int, default=0,
                    help="存量观察区最大「距突破」根数；默认 day=15 / week=8 / month=6")
    ap.add_argument("--bigyang-lookback", type=int, default=0,
                    help="大阳线区间取「突破日前N根」；默认 day=0(金叉→突破) / week=6 / month=6")
    ap.add_argument("--max-price", type=float, default=10.0)
    ap.add_argument("--big-yang-pct", type=float, default=5.0,
                    help="突破段「中大阳线」涨幅阈值(%)，三周期均生效（默认5.0）")
    ap.add_argument("--use-window", action="store_true",
                    help="恢复「新信号窗口」过滤（2026-10-23 起日/周/月线默认全部取消窗口）")
    ap.add_argument("--no-window", action="store_true",
                    help="（保留兼容，已默认生效）取消「新信号窗口」过滤")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    tf = a.tf
    WIN1 = {"day": 5, "week": 3, "month": 2}    # 改1（保持强势）新信号窗口
    WIN2 = {"day": 5, "week": 8, "month": 4}    # 改2（死叉回调）新信号窗口（需演化时间，故更宽）
    WMAX = {"day": 15, "week": 8, "month": 6}   # 存量观察区最大「距突破」根数
    BYLB = {"day": 0, "week": 6, "month": 6}    # 大阳线区间 0=金叉→突破
    win = a.window or WIN1[tf]
    win2 = a.window_gai2 or WIN2[tf]
    wmax = a.watch_max_gap or WMAX[tf]
    bylb = a.bigyang_lookback or BYLB[tf]
    _by_desc = ("突破日所属金叉→突破日" if bylb <= 0 else f"突破日前 {bylb} 根内")
    # ── 2026-10-18：周线/月线口径对齐日线，三周期一致。三个开关保留于此，便于按需回退 ──
    only2 = False       # 曾(v3)：周/月线只保留「改2」→ 现：改1 + 改2 双角度都收
    # ── 2026-10-23 用户口径：三周期（日/周/月）统一取消「新信号窗口」——结构有效即入池
    #    （改1/改2 判定照旧），仅受「最大跟踪期 MAXGAP」约束；--use-window 可回退到原窗口口径
    nowin = not a.use_window
    req_bigyang = True  # 曾(2026-10-17)：大阳线条件仅日线 → 现：三周期均要求
    period, limit = {"day": ("day", 250), "week": ("week", 130), "month": ("month", 124)}[tf]
    # 最少K线根数：月线 westock 硬上限仅 61 根（--limit 更大也无用），故门槛必须低于 61，
    # 否则月线永远返回 None（v3 时期月线实际从未产出过信号）。40 个月≈3.3 年，EMA26 已预热。
    MIN_BARS = {"day": 80, "week": 60, "month": 40}

    pool = load_pool(a.pool, a.pool_file)
    if not pool:
        print("❌ 无股票池"); return
    _mode = ("只留改2·无窗口" if only2 else
             f"不限新信号窗口(跟踪期{MAXGAP[tf]}根)" if nowin else f"窗口 改1 {win}/改2 {win2} 根")
    print(f"🔍 反转数值[{tf}] 跟踪扫描 | 标的{len(pool)}只 | {_mode}·大阳线≥{a.big_yang_pct:g}%（{_by_desc}） | 现价<{a.max_price:g}元")

    rows_map = fetch_batch([c for c, n in pool], period, limit)
    print(f"  数据就绪: {len(rows_map)}/{len(pool)}只")
    name_of = dict(pool)
    today = datetime.now().strftime("%Y-%m-%d")

    # ── 加载跟踪池 ──
    os.makedirs(POOL_DIR, exist_ok=True)
    pool_fp = os.path.join(POOL_DIR, f"reversal_pool_{tf}.json")
    try:
        tracked = json.load(open(pool_fp, encoding="utf-8")).get("items", {})
    except Exception:
        tracked = {}

    added, removed, kept, watch = [], [], [], []
    for code, name in pool:
        rows = rows_map.get(code)
        if not rows:
            continue
        st = eval_state(rows, big_yang_pct=(a.big_yang_pct / 100.0 if req_bigyang else 0.0),
                        min_bars=MIN_BARS[tf], bigyang_lookback=bylb)
        cur = tracked.get(code)
        # 数据时效（>15天视为停牌/退市）
        if st:
            try:
                if (datetime.now() - datetime.strptime(st["last_date"], "%Y-%m-%d")).days > 15:
                    if cur:
                        removed.append({**cur, "code": code, "name": name, "reason": "数据停更"})
                        tracked.pop(code, None)
                    continue
            except Exception:
                pass
        if cur:
            # 已有跟踪 → 判定去留
            if not st:
                removed.append({**cur, "code": code, "name": name, "reason": "结构失效（无突破）"})
                tracked.pop(code, None)
            elif not st["valid"]:
                if st.get("angle") == "改1":
                    _mn, _tp = float(st.get("macd_now") or 0), float(st.get("tp_val") or 0)
                    _rs = ("MACD 已下水" if _mn <= 0 else "跌破突破2倍值")
                else:
                    _rs = "跌破1倍反转数值"
                removed.append({**cur, "code": code, "name": name, "reason": _rs})
                tracked.pop(code, None)
            elif only2 and st["angle"] != "改2":
                removed.append({**cur, "code": code, "name": name, "reason": "已非改2"})
                tracked.pop(code, None)
            elif st["last_close"] >= a.max_price:
                removed.append({**cur, "code": code, "name": name, "reason": "现价≥上限"})
                tracked.pop(code, None)
            elif st["gap"] > MAXGAP[tf]:
                removed.append({**cur, "code": code, "name": name, "reason": "超过跟踪期"})
                tracked.pop(code, None)
            else:
                cur.update({k: st[k] for k in ("tp_date", "tp_val", "red_high", "pullback", "line", "m_low", "angle", "big_yang", "by_date", "by_gain", "gap", "last_close", "last_date")})
                cur["name"] = name
                kept.append(cur)
        else:
            # 新信号：突破2倍后回调不破1倍
            #   三周期统一（v4）：须在「新信号窗口」内（gap ≤ win）、须有突破段中大阳线、改1/改2 都收
            _entry_ok = (st.get("star") if st.get("angle") == "改1" else st["valid"]) if st else False
            ok_new = (bool(st) and _entry_ok and st["last_close"] < a.max_price
                      and (not req_bigyang or st.get("big_yang"))
                      and (not only2 or st["angle"] == "改2")
                      and (st["gap"] <= MAXGAP[tf] if nowin else st["gap"] <= (win2 if st["angle"] == "改2" else win)))
            if ok_new:
                item = {"code": code, "name": name, "first_date": today, **st}
                tracked[code] = item
                added.append(item)
            elif (not nowin and bool(st) and (st.get("star") if st.get("angle") == "改1" else st["valid"])
                  and st.get("big_yang") and st["gap"] <= wmax
                  and st["last_close"] < a.max_price):   # 价格门槛与入池一致
                # 📎 存量结构观察：形态仍成立，仅因「超新信号窗口 / 现价超上限」未入池；不入池、不计胜率
                _why = []
                _w = win2 if st["angle"] == "改2" else win
                if st["gap"] > _w:
                    _why.append(f"超窗口 {st['gap']}>{_w}根")
                if st["last_close"] >= a.max_price:
                    _why.append(f"现价{st['last_close']:g}≥{a.max_price:g}")
                if _why:
                    watch.append({**st, "code": code, "name": name, "reason": "·".join(_why)})

    json.dump({"tf": tf, "updated": today, "total": len(tracked), "items": tracked},
              open(pool_fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ── 胜率记录：入池后 5/10/20 日表现 + 出池结算收益（data/reversal_perf_{tf}.csv）──
    perf_fp = os.path.join(POOL_DIR, f"reversal_perf_{tf}.csv")
    perf = {}
    if os.path.exists(perf_fp):
        for ln in open(perf_fp, encoding="utf-8"):
            p = ln.rstrip("\n").split(",")
            if len(p) >= 4 and p[0] != "code":
                perf[(p[0], p[3])] = p

    def _upd(code, name, first_date, rows, exit_reason=""):
        if not rows or not first_date:
            return
        idx = next((i for i, r in enumerate(rows) if r[0] == first_date), None)
        if idx is None:
            return
        if idx + 1 >= len(rows):      # 入池当日尚无次日K线 → 先占位，后续运行自动回填
            perf.setdefault((code, first_date),
                            [code, (name or "").replace(",", " "), tf, first_date, "", "", "", "", "", "", ""])
            return
        entry = rows[idx + 1][1]
        if entry <= 0:
            return
        get = lambda h: (f"{rows[idx+1+h][2]/entry-1:.4f}" if idx + 1 + h < len(rows) else "")
        exit_dt = rows[-1][0] if exit_reason else ""
        ret_exit = f"{rows[-1][2]/entry-1:.4f}" if exit_reason else ""
        old = perf.get((code, first_date), [])
        # 已记录的出池信息不被后续覆盖丢失
        perf[(code, first_date)] = [code, (name or (old[1] if len(old) > 1 else "")).replace(",", " "), tf, first_date,
                                    f"{entry:.3f}", get(5), get(10), get(20),
                                    exit_dt or (old[8] if len(old) > 8 else ""),
                                    exit_reason or (old[9] if len(old) > 9 else ""),
                                    ret_exit or (old[10] if len(old) > 10 else "")]
    for it in added + kept:
        _upd(it["code"], it["name"], it["first_date"], rows_map.get(it["code"]))
    for it in removed:
        _upd(it["code"], it["name"], it.get("first_date", ""), rows_map.get(it["code"]), it.get("reason", ""))
    with open(perf_fp, "w", encoding="utf-8") as f:
        f.write("code,name,tf,first_date,entry,r5,r10,r20,exit_date,exit_reason,ret_exit\n")
        for k in sorted(perf, key=lambda x: x[1]):
            f.write(",".join(str(v) for v in perf[k]) + "\n")

    def _agg(col, only_exit=False):
        vs = [float(p[col]) for p in perf.values() if len(p) > col and p[col] not in ("", None)
              and (not only_exit or p[9])]
        if not vs:
            return "—", "—", 0
        return f"{sum(1 for x in vs if x>0)/len(vs)*100:.1f}%", f"{sum(vs)/len(vs)*100:+.2f}%", len(vs)
    perf_line = "｜".join(f"{lab} 胜率{_agg(c)[0]}（均值 {_agg(c)[1]}，n={_agg(c)[2]}）"
                          for lab, c in (("5日", 5), ("10日", 6), ("20日", 7)))

    # ── 报告 ──
    lbl = {"day": "日线", "week": "周线", "month": "月线"}[tf]
    L = [f"# 🔄 反转数值·{lbl}信号跟踪（{today}）", "",
         (f"> 股票池：{a.pool_file or ('自定义' if a.pool else '沪深300')} {len(pool)}只 ｜ 现价 < {a.max_price:g}元" if only2
          else f"> 股票池：{a.pool_file or ('自定义' if a.pool else '沪深300')} {len(pool)}只 ｜ "
               + ("**不限新信号窗口**（结构有效即入池，仅受跟踪期 "
                  f"{MAXGAP[tf]} 根约束） ｜ 现价 < {a.max_price:g}元" if nowin else
                  f"新信号窗口：改1 {win} 根 / 改2 {win2} 根（{lbl}） ｜ 现价 < {a.max_price:g}元")),
         (f"> 口径：突破2倍反转数值 → 回调不破1倍反转数值；**仅保留「改2」**——突破后死叉下水、但不破水下反转数值线（−0.618×金叉以来最高红柱）；纳入不看突破窗口（当前结构构成改2即纳入）" if only2
          else f"> 口径：突破2倍反转数值后分两角度——**改1（保持强势）**：突破后 MACD 未下水；**入池**需 ★ = AA（MACD>0 且 MACD>2×0.618×死叉以来最深绿柱）且 MACD 上升，**入池后只要 AA 仍成立即继续跟踪**（当日红柱缩量不踢出，跌破突破2倍值才移出）；**改2（死叉回调）**：突破后死叉下水、但不破水下反转数值线（−0.618×金叉以来最高红柱）；**突破段须出现涨幅≥{a.big_yang_pct:g}% 的中大阳线（涨停板自然满足），区间={_by_desc}**"),
         (f"> 跟踪规则：并入池后持续跟踪，**改1 跌破突破2倍值 / 改2 跌破1倍反转数值 即删除**（改1 存续不要求当日 MACD 上升）；另设「现价≥上限」「超跟踪期({MAXGAP[tf]}根)」移出；**不限新信号窗口**（结构有效即入池）" if nowin else
          f"> 跟踪规则：并入池后持续跟踪，**改1 跌破突破2倍值 / 改2 跌破1倍反转数值 即删除**；另设「现价≥上限」「超跟踪期({MAXGAP[tf]}根)」移出；存量观察区限「距突破≤{wmax}根」"), "",
         (f"**本期：新增 {len(added)} ｜ 在池 {len(kept)} ｜ 移除 {len(removed)} ｜ "
          f"观察 {len(watch)} ｜ 池内合计 {len(tracked)}**" if watch else
          f"**本期：新增 {len(added)} ｜ 在池 {len(kept)} ｜ 移除 {len(removed)} ｜ 池内合计 {len(tracked)}**"),
         f"> 📊 入池后历史胜率：{perf_line} ｜ 出池结算（跌破等）：{_agg(10, True)[0]} / 均值 {_agg(10, True)[1]}（n={_agg(10, True)[2]}）", ""]

    def tbl(rows, with_reason=False, with_first=False, reason_label="移除原因", with_angle=True):
        if not rows:
            L.append("> 无")
            L.append("")
            return
        cols = ["代码", "名称"] + (["入池日"] if with_first else []) + \
               ["最新日期", "最新价"] + (["角度"] if with_angle else []) + \
               ["突破日", "突破段阳线", "突破2倍值", "回调深(MACD)", "不破线(改1=2倍/改2=1倍)", "距突破"] + \
               ([reason_label] if with_reason else [])
        L.append("| " + " | ".join(cols) + " |")
        L.append("|" + "|".join(":--" if c in ("代码", "名称", "入池日", "最新日期", "角度", "突破日", "突破段阳线", reason_label) else "--:" for c in cols) + "|")
        for s in rows:
            cells = [s["code"], s["name"]]
            if with_first:
                cells.append(s.get("first_date", ""))
            _by = f"{s.get('by_date','')} +{s.get('by_gain',0):.1f}%" if s.get("by_date") else "—"
            cells += [s.get("last_date", ""), s.get("last_close", "")] + \
                     ([s.get("angle", "")] if with_angle else []) + \
                     [s.get("tp_date", ""), _by,
                      f"{float(s.get('tp_val', 0)):+.2f}",
                      (f"{float(s.get('macd_now', 0)):+.2f}" if s.get("angle") == "改1" else f"{float(s.get('pullback', 0)):.2f}"),
                      f"{_line_signed(s):+.2f}", s.get("gap", "")]
            if with_reason:
                cells.append(s.get("reason", ""))
            L.append("| " + " | ".join(str(c) for c in cells) + " |")
        L.append("")

    ANG_LABEL = (("改1", "🅰️ 改1 · 保持强势（突破后 MACD 未下水）"),
                 ("改2", "🅱️ 改2 · 死叉回调（水下反转数值线上方）"))

    def tbl_group(rows, with_reason=False, with_first=False, reason_label="移除原因"):
        """按角度归类渲染：改1 / 改2 各一张子表；组内保持传入顺序。空组不显示"""
        if not rows:
            L.append("> 无")
            L.append("")
            return
        for ang, lab in ANG_LABEL:
            sub = [s for s in rows if s.get("angle") == ang]
            if not sub:
                continue
            L.append(f"### {lab} · {len(sub)} 只")
            L.append("")
            tbl(sub, with_reason=with_reason, with_first=with_first,
                reason_label=reason_label, with_angle=False)
        other = [s for s in rows if s.get("angle") not in ("改1", "改2")]
        if other:
            L.append(f"### 其他角度 · {len(other)} 只")
            L.append("")
            tbl(other, with_reason=with_reason, with_first=with_first, reason_label=reason_label)

    _all = added + kept + watch        # 全表口径（新增 + 在池 + 存量观察；移除的不计）
    _a1 = sum(1 for s in _all if s.get("angle") == "改1")
    _a2 = sum(1 for s in _all if s.get("angle") == "改2")
    L.append(f"> 🧭 角度分布（新增+在池+观察）：**改1 保持强势 {_a1} 只** ｜ **改2 死叉回调 {_a2} 只**")
    L.append("")

    L.append(f"## 🆕 本次新增（{len(added)}）")
    L.append("")
    tbl_group(sorted(added, key=lambda x: x["gap"]), with_first=True)
    L.append(f"## 📌 在池跟踪（{len(kept)}）")
    L.append("")
    tbl_group(sorted(kept, key=lambda x: x["gap"]))
    L.append(f"## 🗑️ 本次移除（{len(removed)}）")
    L.append("")
    tbl_group(sorted(removed, key=lambda x: x.get("pullback", 0), reverse=True), with_reason=True, with_first=True)
    if watch:
        L.append(f"## 📎 存量结构观察（{len(watch)}）")
        L.append("")
        L.append(f"> 结构仍有效（改1 未跌破突破2倍值 / 改2 未跌破1倍反转数值 + 突破段有大阳线 + **现价 < {a.max_price:g}元**），"
                 f"仅因**超出新信号窗口**未入池——不作为新信号、不计胜率，仅作形态跟踪（限「距突破≤{wmax}根」）。")
        L.append("")
        tbl_group(sorted(watch, key=lambda x: x["gap"]), with_reason=True, reason_label="未入池原因")
    L.append("---")
    L.append("> ⚠️ 量化规律统计，不构成投资建议。改1 跌破突破2倍值、改2 跌破1倍反转数值即出池。")

    os.makedirs("outputs", exist_ok=True)
    fn = {"day": f"反转数值日线信号_{today}.md", "week": f"反转数值周线跟踪_{today}.md", "month": f"反转数值月线跟踪_{today}.md"}[tf]
    fp = os.path.join("outputs", fn)
    open(fp, "w", encoding="utf-8").write("\n".join(L))
    print(f"✅ [{tf}] 新增{len(added)} 在池{len(kept)} 移除{len(removed)} 观察{len(watch)} 池内{len(tracked)} | 报告: {fp} | 池: {pool_fp}")
    for s in added[:12]:
        print(f"   + [{s.get('angle','')}] {s['code']} {s['name']} 价{s['last_close']} 突破{s['tp_date']} MACD{s.get('macd_now',0):+.2f} vs 线{_line_signed(s):+.2f}")
    for s in removed[:8]:
        print(f"   - {s['code']} {s['name']} [{s['reason']}]")

    if a.push:
        import urllib.request, urllib.parse
        token = os.environ.get("PUSH_TOKEN", "")
        if token:
            # —— 摘要推送（只推新增/移除，明细过长则截断）——
            P = [f"## 🔄 反转数值·{lbl}跟踪 · {today}", "",
                 f"- 本次：🆕新增 **{len(added)}** ｜ 📌在池 **{len(kept)}** ｜ 🗑️移除 **{len(removed)}**",
                 f"- 池内合计：**{len(tracked)}** 只（现价<{a.max_price:g}元）",
                 f"- 📊 入池后胜率：{perf_line}"]
            P.append(f"- 🧭 角度：改1 **{_a1}** ｜ 改2 **{_a2}**（新增+在池+观察）")
            if watch:
                P.append(f"- 📎 存量结构观察：**{len(watch)}** 只（超窗口/超价，未入池）")
            if added:
                P += ["", f"### 🆕 新增（{len(added)}）"]
                for s in sorted(added, key=lambda x: x["gap"])[:12]:
                    _by = f"｜阳线{s.get('by_date','')} +{s.get('by_gain',0):.1f}%" if s.get('by_date') else ""
                    P.append(f"- {s['code'][2:]} {s['name']} {s['last_close']}｜{s.get('angle','')}｜突破{s['tp_date']}{_by}｜MACD{s.get('macd_now',0):+.2f}/线{_line_signed(s):+.2f}")
                if len(added) > 12:
                    P.append(f"- …等共 {len(added)} 只（完整见知识库报告）")
            if removed:
                P += ["", f"### 🗑️ 移除（{len(removed)}）"]
                for s in removed[:8]:
                    P.append(f"- {s['code'][2:]} {s['name']}｜{s.get('reason','')}")
                if len(removed) > 8:
                    P.append(f"- …等共 {len(removed)} 只")
            P += ["", "> 规则：改1 跌破突破2倍值 / 改2 跌破1倍反转数值 即出池；完整报告见知识库"]
            body = urllib.parse.urlencode({"token": token, "title": f"🔄 反转数值{lbl}跟踪 {today}",
                                           "content": "\n".join(P), "template": "markdown"}).encode()
            try:
                r = urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body), timeout=30)
                print(f"[pushplus] {r.read().decode()[:80]}")
            except Exception as e:
                print(f"[pushplus] 失败: {e}")


if __name__ == "__main__":
    main()
