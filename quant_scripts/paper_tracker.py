#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper_tracker.py v3 —— 纸面组合 / 股池 OOS 前瞻跟踪（2026-09-24）

v3 相对 v2 的改造（A+B+C 三轨）：
  A 多期快照：不结仓、不删除，记录 ret_5/10/20/60（按交易日）→ 任何时候都能回答"持多久最好"
  B 分池观察窗：按池类型标注观察期（短线5-10 / 趋势20 / 月线60），仅供参考不强制
  C 三线退出对照：黄金线 / 持股线 / 锚定线，各自给"按该线退出的收益" → 与固定持有期对比
  + 结仓改为「标记」（status=closed 仍保留在统计里，永不丢信息）

三线定义（与体系既有口径一致）：
  黄金线（腰缠万贯）：XA72=MA(TR,13); XA73=REF(C,1)-REF(XA72,1); 黄金线=HHV(XA73,12)
  持股线（猛兽派）  ：EMA(C,20) - 2*ATR(14)
  锚定线（标准AVWAP）：锚点=最近一次「250日新低」日；AVWAP=Σ((H+L+C)/3*V)/Σ(V)

用法:
  python3 paper_tracker.py --init outputs/pool_signals_log.csv
  python3 paper_tracker.py --add                 # 各股池新标的入池
  python3 paper_tracker.py --update              # 更新收益快照 + 三线状态
  python3 paper_tracker.py --report              # 按期收益曲线 + 三线退出对照
"""
import subprocess, sys, os, re, csv, json, argparse
from datetime import datetime, timezone, timedelta

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
PORTFOLIO = "outputs/paper_portfolio.json"
BJT = timezone(timedelta(hours=8))
HOLDS = [5, 10, 20, 60]

# 分池观察窗（交易日）：短线池短、趋势池中、月线池长
POOL_WINDOW = {
    "王者": 5, "才哥": 5, "妖股": 10, "龙头": 5, "龙头战法": 5,
    "双弦": 20, "鱼身": 20, "猛兽突破": 20, "猛兽本月": 20, "西湖RSV": 20,
    "一统天下": 20, "乾坤A": 20, "宁静卡位": 20,
    "武威": 60, "卡位": 60,
}
DEFAULT_WINDOW = 20

POOL_SOURCES = [
    ("鱼身", "quant_scripts/stock_pool.txt"),
    ("一统天下", "quant_scripts/yitong_pool.txt"),
    ("才哥", "quant_scripts/caige_pool.txt"),
    ("龙头", "quant_scripts/longtou_pool.txt"),
    ("龙头战法", "quant_scripts/dragon_pool.txt"),
    ("妖股", "quant_scripts/yao_pool.txt"),
    ("乾坤A", "outputs/qiankun_a_latest.json"),
    ("双弦", "outputs/双弦观察池_latest.json"),
    ("猛兽突破", "outputs/beast_pool_latest.json"),
    ("宁静卡位", "quant_scripts/ai_chain_pool.json"),
    ("低空经济", "quant_scripts/low_altitude_pool.json"),
    ("固态电池", "quant_scripts/solid_battery_pool.json"),
    ("商业航天", "quant_scripts/space_pool.json"),
    ("西湖RSV", "outputs/xihu_rsv_latest.json"),
]


def run(args, timeout=45):
    try:
        return subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def parse_bars(txt, single_code=None):
    """→ [(date, open, close, high, low, volume)] 升序"""
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        p = [x.strip() for x in s.strip("|").split("|")]
        if "date" in p:
            header = p
            continue
        if not header or "---" in p[0]:
            continue
        try:
            di = header.index("date")
            oi = header.index("open")
            ci = header.index("last")
            hi = header.index("high")
            li = header.index("low")
            vi = header.index("volume")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", p[di]):
                continue
            rows.append((p[di], float(p[oi]), float(p[ci]), float(p[hi]), float(p[li]), float(p[vi])))
        except (ValueError, IndexError):
            pass
    rows.sort(key=lambda r: r[0])
    return rows


def get_bars(code, limit=500):
    for _ in range(3):
        b = parse_bars(run(["kline", code, "--period", "day", "--limit", str(limit)]))
        if b:
            return b
    return []


def norm(c):
    c = (c or "").strip()
    if re.match(r"^(sh|sz)\d{6}$", c):
        return c
    m = re.search(r"(\d{6})", c)
    if not m:
        return ""
    d = m.group(1)
    return ("sh" if d[0] in ("6", "9") else "sz") + d


# ── 三线计算 ───────────────────────────────────────────────────
def tr_series(bars):
    n = len(bars)
    tr = [0.0] * n
    for i in range(1, n):
        h, l, pc = bars[i][3], bars[i][4], bars[i - 1][2]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    return tr


def line_gold(bars):
    """黄金线：XA72=MA(TR,13); XA73=REF(C,1)-REF(XA72,1); 黄金线=HHV(XA73,12)"""
    n = len(bars)
    tr = tr_series(bars)
    xa72 = [None] * n
    for i in range(12, n):
        xa72[i] = sum(tr[i - 12:i + 1]) / 13
    xa73 = [None] * n
    for i in range(1, n):
        if xa72[i - 1] is not None:
            xa73[i] = bars[i - 1][2] - xa72[i - 1]
    gold = [None] * n
    for i in range(12, n):
        seg = [x for x in xa73[max(0, i - 11):i + 1] if x is not None]
        if len(seg) >= 12:
            gold[i] = max(seg)
    return gold


def line_hold(bars, n_ema=20, n_atr=14):
    """持股线 = EMA(C,20) - 2*ATR(14)"""
    n = len(bars)
    close = [b[2] for b in bars]
    ema = [None] * n
    k = 2.0 / (n_ema + 1)
    for i in range(n):
        if i == 0:
            ema[i] = close[0]
        else:
            ema[i] = close[i] * k + ema[i - 1] * (1 - k)
    tr = tr_series(bars)
    atr = [None] * n
    for i in range(n_atr, n):                     # Wilder 平滑
        if atr[i - 1] is None:
            atr[i] = sum(tr[i - n_atr + 1:i + 1]) / n_atr
        else:
            atr[i] = (atr[i - 1] * (n_atr - 1) + tr[i]) / n_atr
    return [None if (ema[i] is None or atr[i] is None) else ema[i] - 2 * atr[i] for i in range(n)]


def anchor_index(bars, lookback=250):
    """标准 Anchored VWAP 的锚点：最近一次「创 lookback 日新低」的交易日
    ⚠️ 无未来函数：只用「过去 lookback 日」判断，锚点在当天收盘即可确定。
    """
    n = len(bars)
    anchor = 0
    for i in range(n):
        seg = bars[max(0, i - lookback + 1):i + 1]
        lo = min(b[4] for b in seg)
        if bars[i][4] <= lo + 1e-9:              # 当日即为区间最低 → 新低点
            anchor = i
    return anchor


def line_anchor(bars, lookback=250):
    """锚定线（标准 Anchored VWAP 口径）
        锚点 anchor = 最近一次「lookback 日新低」日
        AVWAP(t) = Σ_{i=anchor..t} ((H+L+C)/3 × V) / Σ_{i=anchor..t} V
    无未来函数：锚点当天即可确定；本函数对全部 t>=anchor 输出。
    """
    n = len(bars)
    out = [None] * n
    if n == 0:
        return out
    a = anchor_index(bars, lookback)
    pv = vv = 0.0
    for t in range(a, n):
        tp = (bars[t][3] + bars[t][4] + bars[t][2]) / 3
        v = bars[t][5] or 0
        pv += tp * v
        vv += v
        out[t] = pv / vv if vv > 0 else None
    return out


def eval_position(p, bars):
    """计算：多期收益 + 三线状态 + 按各线退出的收益"""
    dates = [b[0] for b in bars]
    if p["entry_date"] not in dates:
        return False
    ei = dates.index(p["entry_date"])
    entry = p["entry"]
    n = len(bars)
    cur = bars[-1][2]
    p["cur_date"] = bars[-1][0]
    p["cur_price"] = cur
    p["ret"] = (cur / entry - 1) * 100
    try:
        p["days_td"] = n - 1 - ei                  # 已持有交易日
    except Exception:
        p["days_td"] = 0
    # A 多期收益
    for h in HOLDS:
        j = ei + h
        p[f"ret_{h}"] = round((bars[j][2] / entry - 1) * 100, 2) if j < n else None
    # C 三线
    g = line_gold(bars)
    hd = line_hold(bars)
    an = line_anchor(bars)
    p["gold_now"] = round(g[-1], 2) if g and g[-1] is not None else None
    p["hold_now"] = round(hd[-1], 2) if hd and hd[-1] is not None else None
    p["anchor_now"] = round(an[-1], 3) if an and an[-1] is not None else None
    p["below_gold"] = bool(g[-1] is not None and cur < g[-1])
    p["below_hold"] = bool(hd[-1] is not None and cur < hd[-1])
    p["below_anchor"] = bool(an[-1] is not None and cur < an[-1])

    def exit_ret(line):
        for i in range(ei + 1, n):
            if line[i] is not None and bars[i][2] < line[i]:
                return round((bars[i][2] / entry - 1) * 100, 2), dates[i]
        return round((cur / entry - 1) * 100, 2), "持有中"

    for tag, ln in (("gold", g), ("hold", hd), ("anchor", an)):
        r, d = exit_ret(ln)
        p[f"exit_{tag}_ret"] = r
        p[f"exit_{tag}_date"] = d
    # 标记（不删除）：跌破入场锚定线视为"结构走坏"
    if p.get("below_anchor") and p.get("status") == "open":
        p["status"] = "closed"
        p["closed_by"] = "anchor"
    return True


def _load():
    if os.path.exists(PORTFOLIO):
        try:
            return json.load(open(PORTFOLIO, encoding="utf-8"))
        except Exception:
            pass
    return {"init_date": datetime.now(BJT).strftime("%Y-%m-%d"), "positions": [], "closed": []}


def _save(pf):
    os.makedirs(os.path.dirname(PORTFOLIO) or ".", exist_ok=True)
    json.dump(pf, open(PORTFOLIO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def collect_pool_codes():
    out = []
    for pool, path in POOL_SOURCES:
        if not os.path.exists(path):
            continue
        try:
            if path.endswith(".json"):
                raw = json.load(open(path, encoding="utf-8"))
                found = []

                def walk(x):
                    if isinstance(x, dict):
                        for k, v in x.items():
                            if k in ("code", "symbol", "ts_code") and isinstance(v, str):
                                found.append(v)
                            else:
                                walk(v)
                    elif isinstance(x, list):
                        for i in x:
                            walk(i)
                walk(raw)
                codes = {norm(c) for c in found}
            else:
                codes = {norm(c) for c in re.findall(r"\b(?:sh|sz)?\d{6}\b", open(path, encoding="utf-8", errors="ignore").read())}
            for c in sorted(x for x in codes if x):
                out.append((pool, c))
        except Exception as e:
            print(f"  [WARN] {path}: {e}")
    seen, res = set(), []
    for pool, c in out:
        if c in seen:
            continue
        seen.add(c)
        res.append((pool, c))
    return res


def init_portfolio(signals_file):
    signals = {}
    with open(signals_file, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            signals[(row.get("date", ""), row.get("code", ""))] = row
    pf = {"init_date": datetime.now(BJT).strftime("%Y-%m-%d"), "positions": [], "closed": []}
    for (sig_date, code), s in sorted(signals.items()):
        bars = get_bars(code)
        if not bars:
            continue
        b = next((x for x in bars if x[0] >= sig_date), None)
        if not b:
            continue
        pf["positions"].append({
            "code": code, "name": s.get("name", ""), "entry_date": b[0], "entry": b[2],
            "pool": "池信号", "status": "open",
        })
    _save(pf)
    print(f"✅ 初始化 {len(pf['positions'])} 个信号")


def add_positions():
    pf = _load()
    have = {p["code"] for p in pf.get("positions", [])}
    added, bypool = 0, {}
    for pool, code in collect_pool_codes():
        if code in have:
            continue
        bars = get_bars(code, limit=40)
        if not bars:
            continue
        pf.setdefault("positions", []).append({
            "code": code, "name": "", "entry_date": bars[-1][0], "entry": bars[-1][2],
            "pool": pool, "status": "open",
        })
        have.add(code)
        added += 1
        bypool[pool] = bypool.get(pool, 0) + 1
    _save(pf)
    print(f"✅ 新增入池 {added} 只（{bypool or '无'}）")


def update_portfolio():
    pf = _load()
    pos = pf.get("positions", [])
    if not pos:
        print("❌ 组合为空")
        return
    ok, fail = 0, 0
    for p in pos:
        bars = get_bars(p["code"], limit=500)
        if not bars:
            p["last_err"] = "K线获取失败"
            fail += 1
            continue
        if eval_position(p, bars):
            p.pop("last_err", None)
            ok += 1
    pf["last_update"] = datetime.now(BJT).strftime("%Y-%m-%d %H:%M")
    if pos:
        pf["last_bars_date"] = pos[0].get("cur_date", "")
    _save(pf)
    print(f"✅ 更新 {ok} 只（失败 {fail}）| 共 {len(pos)} 只")


def _stat(v):
    if not v:
        return ["—", "—", "—"]
    w = sum(1 for x in v if x > 0) / len(v) * 100
    return [f"{len(v)}", f"{w:.0f}%", f"{sum(v)/len(v):+.2f}%"]


def report():
    pf = _load()
    pos = [p for p in pf.get("positions", []) if "ret" in p]
    L = []
    A = L.append
    A("# 📊 纸面组合跟踪报告 v3（OOS 前瞻 · 多期收益 + 三线退出对照）\n")
    A(f"> 更新 {pf.get('last_update')} | 标的 {len(pos)} 只 | 行情截止 {pf.get('last_bars_date','—')}")
    A("> 口径：入池日收盘=入场价；**不设固定结仓**，记录 5/10/20/60 交易日收益 + 三条线的退出对照\n")

    allp = sorted({p.get("pool", "?") for p in pos})
    A("## 一、各池 · 多期收益（A 轨：任何时候都能回答\"持多久最好\"）\n")
    A("| 池 | 样本 | 5日 | 10日 | 20日 | 60日 | 今收 |")
    A("|:----|:---:|:----:|:----:|:----:|:----:|:----:|")
    for pool in allp:
        row = [p for p in pos if p.get("pool") == pool]
        cells = []
        for h in HOLDS:
            vs = [p[f"ret_{h}"] for p in row if p.get(f"ret_{h}") is not None]
            cells.append(f"{sum(vs)/len(vs):+.2f}%" if vs else "—")
        cur = [p["ret"] for p in row]
        A(f"| {pool} | {len(row)} | " + " | ".join(cells) + f" | {sum(cur)/len(cur):+.2f}% |")

    A("\n## 二、三线 × 固定持有期 收益对比（**仅对比用，不作退出规则**）\n")
    A("> 口径：① 固定持有 5/10/20/60 交易日的收益；② 三条线各自\"持有到破线\"的收益（**仅作对比基准，实盘不执行**）\n")
    A("| 池 | 样本 | 黄金线 | 持股线 | 锚定线 | 固定5日 | 固定10日 | 固定20日 | 固定60日 |")
    A("|:----|:---:|:----:|:----:|:----:|:----:|:----:|:----:|:----:|")
    tot = {"gold": [], "hold": [], "anchor": []}
    for pool in allp:
        row = [p for p in pos if p.get("pool") == pool]
        cells = []
        for tag in ("gold", "hold", "anchor"):
            vs = [p[f"exit_{tag}_ret"] for p in row if p.get(f"exit_{tag}_ret") is not None]
            tot[tag] += vs
            cells.append(f"{sum(vs)/len(vs):+.2f}%" if vs else "—")
        fixed = []
        for h in HOLDS:
            vs = [p[f"ret_{h}"] for p in row if p.get(f"ret_{h}") is not None]
            fixed.append(f"{sum(vs)/len(vs):+.2f}%" if vs else "—")
        A(f"| {pool} | {len(row)} | " + " | ".join(cells) + " | " + " | ".join(fixed) + " |")
    A("\n**全体合计**：" + " ｜ ".join(
        f"{n} {sum(tot[t])/len(tot[t]):+.2f}%（{sum(1 for x in tot[t] if x>0)/len(tot[t])*100:.0f}%胜）"
        for n, t in (("黄金线", "gold"), ("持股线", "hold"), ("锚定线", "anchor")) if tot[t]))
    A("\n## 三、三线状态分布（当前）\n")
    A("| 状态 | 只数 |")
    A("|:----|:---:|")
    A(f"| 跌破黄金线（快线/预警） | {sum(1 for p in pos if p.get('below_gold'))} |")
    A(f"| 跌破持股线（慢线/兜底） | {sum(1 for p in pos if p.get('below_hold'))} |")
    A(f"| 跌破锚定线（结构走坏） | {sum(1 for p in pos if p.get('below_anchor'))} |")
    A("\n---")
    A("⚠️ 纸面模拟，非实盘记录，不构成投资建议。")
    md = "\n".join(L)
    os.makedirs("outputs", exist_ok=True)
    out = f"outputs/纸面组合跟踪报告_{datetime.now(BJT).strftime('%Y-%m-%d')}.md"
    open(out, "w", encoding="utf-8").write(md)
    print(f"[OK] {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="")
    ap.add_argument("--add", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.init:
        init_portfolio(a.init)
    elif a.add:
        add_positions()
    elif a.update:
        update_portfolio()
    elif a.report:
        report()
    else:
        print(__doc__)
