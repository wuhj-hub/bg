#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pool_winrate_biweekly.py —— 股池胜率「总览」（双周 · 统一 OOS 口径）v2（2026-10-10）

统一体系内所有「股池 / 信号源」的胜率跟踪到**一套 OOS 口径**：
    entry = 信号/入池日（或其后的首个交易日）收盘价
    收益  = 收盘(+N) / entry − 1，N ∈ {5,10,20,60} 交易日（严格样本外，非前视）

数据源（均在仓库检出，无需外部）：
  · 各池       outputs/pool_entries.csv        （pool_snapshot.py 每日累积，entry_date=首次入池日）
  · 涨停王者   outputs/wangzhe_signals.csv     （用其自带 r5/r10/r20 回测列，避免重取）
  · 量学       outputs/liangxue_signals_log.csv（date+code → 现算）
  · 竞价       data/jingjia_signals.csv        （date+code → 现算，统一为收盘口径）

取代（2026-10-10 起，方案「乙」直接停用被替代的重复报告）：
  · 《股池信号胜率跟踪报告》（win_rate_tracker.py 之报告部分）
  · 《纸面组合跟踪报告》（paper_tracker.py 之报告部分；其数据仍由 pool_snapshot/paper_tracker 维护）
  保留：四态胜率（资金行为维度，非股池）；三阶漏斗「股池标的跟踪报告」（体检，非胜率）。

触发：.github/workflows/pool_winrate_biweekly.yml（每周一触发，脚本内做 ISO 双周判断）。
用法：python3 pool_winrate_biweekly.py [--force] [--push] [--out PATH]
"""
import os, re, sys, csv, json, argparse, subprocess, shutil, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))
ENTRY = "outputs/pool_entries.csv"
WANGZHE = "outputs/wangzhe_signals.csv"
LIANGXUE = "outputs/liangxue_signals_log.csv"
JINGJIA = "data/jingjia_signals.csv"
HOLDS = [5, 10, 20, 60]
NEW_POOLS = {"四维共振", "信号仲裁", "乖离低买", "RSV强度", "123ABC"}
WESTOCK = ([shutil.which("westock-data-skillhub")] if shutil.which("westock-data-skillhub")
           else ["npx", "-y", "westock-data-skillhub@1.0.3"])


def run(args, timeout=300):
    # 2026-10-16 阶段3·批次4：插入式迁移——优先统一取数层 fetch.raw，失败回退本地 npx
    try:
        import sys as _s, os as _o
        _pd = _o.path.dirname(_o.path.abspath(__file__))
        _qp = _o.path.join(_pd, 'quant_scripts')
        for _c in (_pd, _qp):
            if _c not in _s.path:
                _s.path.insert(0, _c)
        from fetch import raw as _fraw
        _r = _fraw(args, timeout=timeout)
        if _r and _r.strip() and '执行失败' not in _r:
            return _r
    except Exception:
        pass
    try:
        return subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout).stdout or ""
    except Exception:
        return ""


def parse_batch(txt):
    out, hdr = {}, None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        p = [x.strip() for x in s.strip("|").split("|")]
        if "date" in p:
            hdr = p
            continue
        if not hdr or "---" in p[0]:
            continue
        try:
            di, ci = hdr.index("date"), hdr.index("last")
            if re.match(r"^(sh|sz)\d{6}$", p[0]) and re.match(r"^\d{4}-\d{2}-\d{2}$", p[di]):
                out.setdefault(p[0], []).append((p[di], float(p[ci])))
        except (ValueError, IndexError):
            pass
    for c in out:
        out[c].sort()
    return out


def norm(c):
    c = (c or "").strip()
    if re.match(r"^(sh|sz)\d{6}$", c):
        return c
    m = re.search(r"(\d{6})", c)
    if not m:
        return ""
    d = m.group(1)
    return ("sh" if d[0] in ("6", "9", "5") else "sz") + d


def fetch_klines(codes):
    kline = {}
    codes = sorted({c for c in codes if c})
    for i in range(0, len(codes), 250):
        kline.update(parse_batch(run(["kline", ",".join(codes[i:i + 250]), "--period", "day", "--limit", "250"])))
    return kline


def trading_ret(bars, entry_date, h):
    if not bars:
        return None
    idx = next((i for i, x in enumerate(bars) if x[0] >= entry_date), None)
    if idx is None or idx + h >= len(bars):
        return None
    c0, c1 = bars[idx][1], bars[idx + h][1]
    return (c1 / c0 - 1) * 100 if c0 > 0 else None


def agg(vals):
    if not vals:
        return None
    return round(sum(1 for x in vals if x > 0) / len(vals) * 100, 1), round(sum(vals) / len(vals), 2), len(vals)


def cell(res):
    return "—" if not res else f"{res[0]:.0f}% / {res[1]:+.2f}% (n={res[2]})"


def read_csv(p):
    if not os.path.exists(p):
        return []
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(p, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    now = datetime.now(BJ)
    wk = now.isocalendar()[1]
    if not a.force and wk % 2 != 0:
        print(f"[SKIP] ISO 第 {wk} 周（奇数周），非双周报告周；--force 可强制")
        return

    # ── 收集所有需要 K 线的 (来源, 日期, 代码) ──
    if not os.path.exists(ENTRY):
        print(f"[ERR] 缺 {ENTRY}")
        return
    p_rows = [(r["pool"], r["code"], r["entry_date"]) for r in read_csv(ENTRY) if r.get("code") and r.get("entry_date")]
    lx = [(r.get("date"), norm(r.get("code"))) for r in read_csv(LIANGXUE) if r.get("date") and r.get("code")]
    jj = [(r.get("date"), norm(r.get("code")), r.get("strategy")) for r in read_csv(JINGJIA) if r.get("date") and r.get("code")]

    codes = [c for _, c, _ in p_rows] + [c for _, c in lx] + [c for _, c, _ in jj]
    kline = fetch_klines(codes)
    print(f"[INFO] 标的 {len(set(c for c in codes if c))} 只，取到 K 线 {len(kline)} 只", flush=True)

    # ── 一、各池 OOS ──
    agg_pool = {}
    for pool, c, ed in p_rows:
        for h in HOLDS:
            v = trading_ret(kline.get(c), ed, h)
            if v is not None:
                agg_pool.setdefault(pool, {}).setdefault(h, []).append(v)
    base = {h: [v for _, c, ed in p_rows if (v := trading_ret(kline.get(c), ed, h)) is not None] for h in HOLDS}

    # ── 二、信号源 OOS ──
    src = {}
    # 涨停王者：用自带 r5/r10/r20 列（不重取）
    wz = read_csv(WANGZHE)
    if wz:
        for h, col in ((5, "r5"), (10, "r10"), (20, "r20")):
            vals = []
            for r in wz:
                try:
                    if r.get(col):
                        vals.append(float(r[col]))
                except ValueError:
                    pass
            if vals:
                src.setdefault("涨停王者（自带回测列）", {})[h] = vals
    # 量学：现算
    lx_agg = {}
    for d, c in lx:
        for h in (5, 10, 20):
            v = trading_ret(kline.get(c), d, h)
            if v is not None:
                lx_agg.setdefault(h, []).append(v)
    if lx_agg:
        src["量学（月线闸门 PASS）"] = lx_agg
    # 竞价：按策略现算
    for d, c, st in jj:
        for h in (5, 10, 20):
            v = trading_ret(kline.get(c), d, h)
            if v is not None:
                src.setdefault(f"竞价·{st}", {}).setdefault(h, []).append(v)

    # ── 组装报告 ──
    date_str = now.strftime("%Y-%m-%d")
    out_path = a.out or f"outputs/股池胜率总览_{date_str}.md"
    HDR = "| 池 / 来源 | 5日 胜率/均值 | 10日 | 20日 | 60日 |"
    SEP = "|---|---|---|---|---|"

    def row(name, d):
        return f"| {name} | " + " | ".join(cell(agg(d.get(h, []))) for h in HOLDS) + " |"

    L = [f"# 📊 股池胜率总览 · {date_str}", "",
         "> **统一口径（OOS）**：entry = 信号/入池日（或其后的首个交易日）收盘价，收益 = 收盘(+N)/entry−1，N∈{5,10,20,60} 交易日",
         f"> 生成 {now.strftime('%Y-%m-%d %H:%M')} 北京 · 双周（ISO 第 {wk} 周）· 样本：pool_entries {len(p_rows)} 条",
         "> 本报告已统一取代《股池信号胜率跟踪报告》《纸面组合跟踪报告》", ""]

    L += ["## 一、各池 OOS 表现（按 20日样本量排序）", "", HDR, SEP]
    order = sorted(agg_pool, key=lambda p: -len(agg_pool[p].get(20, agg_pool[p].get(5, []))))
    for p in order:
        L.append(row(p, agg_pool[p]))
    L += ["", HDR.replace("池 / 来源", "**基准（全池等权）**"), SEP, row("全池基准", base), ""]

    L += ["## 二、🆕 2026-10-10 新增跟踪池", "", HDR, SEP]
    np_ = sorted(p for p in agg_pool if p in NEW_POOLS)
    if np_:
        for p in np_:
            L.append(row(p, agg_pool[p]))
    else:
        L.append("| （样本积累中） | — | — | — | — |")
    L += ["", "> 新池自 2026-10-10 盘后起累积 entry_date；20/60 日列需持有满相应交易日才有值。", ""]

    L += ["## 三、体系信号源 OOS", "", HDR, SEP]
    if src:
        for s in sorted(src):
            L.append(row(s, src[s]))
    else:
        L.append("| （无信号源数据） | — | — | — | — |")
    L += ["", "> 王者=其自带 r5/r10/r20 回测列；量学/竞价=按上表统一口径现算（竞价原为开盘口径，此处统一为收盘口径）。", ""]

    # ── 四、按行情类型分层（曾星智《悟道01》三类短线行情 · 指数口径）──
    reg_map = {}
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from regime_history import ensure as _rge, REGIME_LABEL as _RL
        reg_map = _rge()
    except Exception as e:
        print(f"[WARN] 行情类型历史不可用: {e}", flush=True)

    L += ["## 四、按行情类型分层（曾星智《悟道01》三类短线行情 · 指数口径）", ""]
    if not reg_map:
        L += ["| （行情类型历史不可用，本节跳过） | — | — | — | — |", ""]
    else:
        import bisect
        import collections
        rdates = sorted(reg_map)

        def regime_of(d):
            d = (d or "")[:10]
            i = bisect.bisect_right(rdates, d) - 1
            return reg_map[rdates[i]] if i >= 0 else None

        def split(pairs):
            out = {}
            for d, c in pairs:
                r = regime_of(d)
                if not r:
                    continue
                for h in HOLDS:
                    v = trading_ret(kline.get(c), d, h)
                    if v is not None:
                        out.setdefault(r, {}).setdefault(h, []).append(v)
            return out

        cnt250 = collections.Counter(reg_map[d] for d in rdates[-250:])
        L += ["> 分层依据：`quant_scripts/regime_history.py` 回算的**每日行情类型**"
              "（上证 MA250/60/20 方向 + 年线位置；历史口径无广度，比实盘 v4.6 判定略粗）；"
              "样本按**信号日/入池日所属类型**归组。",
              f"> 序列覆盖 {rdates[0]} ~ {rdates[-1]}（{len(rdates)} 交易日）；近250日分布："
              + "｜".join(f"{_RL[k]} {cnt250.get(k, 0)}日" for k in (1, 2, 3)), "",
              "| 来源 · 行情类型 | 5日 胜率/均值 | 10日 | 20日 | 60日 |", "|---|---|---|---|---|"]

        src_pairs = [("全池基准", [(ed, c) for _, c, ed in p_rows])]
        for p in sorted(agg_pool, key=lambda x: -len(agg_pool[x].get(20, agg_pool[x].get(5, []))))[:6]:
            src_pairs.append((f"池·{p}", [(ed, c) for pp, c, ed in p_rows if pp == p]))
        if wz:
            src_pairs.append(("涨停王者（自带回测列）", None))
        src_pairs.append(("量学", lx))
        src_pairs.append(("竞价（合并策略）", [(d, c) for d, c, _ in jj]))

        rows_out = []
        for name, pairs in src_pairs:
            if pairs is None:                       # 涨停王者：用自带 r5/r10/r20，不重取
                d_by_reg = {}
                for r in wz:
                    reg = regime_of(r.get("date"))
                    if not reg:
                        continue
                    for h, col in ((5, "r5"), (10, "r10"), (20, "r20")):
                        try:
                            v = float(r.get(col))
                        except (TypeError, ValueError):
                            continue
                        d_by_reg.setdefault(reg, {}).setdefault(h, []).append(v)
            else:
                d_by_reg = split(pairs)
            for reg in (1, 2, 3):
                d_ = d_by_reg.get(reg)
                if not d_:
                    continue
                rows_out.append(f"| {name} · {_RL[reg]} | "
                                + " | ".join(cell(agg(d_.get(h, []))) for h in HOLDS) + " |")
        L += rows_out if rows_out else ["| （暂无可分层样本，等待累积） | — | — | — | — |"]
        # 样本期警示：某类型覆盖的入池日过少 → 分层近似「时间切片」，不可当纯环境效应读
        cov = {}
        for _, _c, _ed in p_rows:
            _r = regime_of(_ed)
            if _r:
                cov.setdefault(_r, set()).add((_ed or "")[:10])
        thin = sorted(k for k, v in cov.items() if len(v) < 20)
        if thin:
            L += ["", "> ⚠️ 样本期警示：" + "、".join(f"{_RL[k]} 仅覆盖 {len(cov[k])} 个入池日" for k in thin)
                  + " → 该分组近似「按入池时间切片」，**不能当作纯环境效应**；按月累积（每类 ≥20 个入池日）后结论才成立。"]
        L += ["", "> 每格 = 胜率 / 均值（n=样本数），样本 <5 仅供观察。三类无优劣、只是手法不同——"
              "分层的目的就是验证「哪种手法在哪类环境里正期望」。", ""]

    L += ["---", "",
          "**口径与边界**：",
          "- 严格样本外：自入池/信号日往后看；区别于 `pool_quality.py` 的「取当前标的回头算」（有选样偏差）。",
          "- 保留的独立报告：四态胜率（资金行为维度）、三阶漏斗「股池标的跟踪报告」（体检，非胜率）。",
          "- 休眠脚本 `win_rate_pool.py` / `win_rate_liangxue.py` 的能力已并入本总览。", ""]

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    open(out_path, "w", encoding="utf-8").write("\n".join(L))
    print(f"[OK] {out_path}")

    if a.push:
        tok = os.environ.get("PUSH_TOKEN")
        if tok:
            body = "\n".join(L[:50])
            data = urllib.parse.urlencode({"token": tok, "title": f"📊 股池胜率总览 {date_str}",
                                           "content": body, "template": "markdown"}).encode()
            try:
                urllib.request.urlopen("https://pushplus.plus/send", data=data, timeout=20)
                print("[PUSH] ok")
            except Exception as e:
                print(f"[PUSH] fail: {e}")


if __name__ == "__main__":
    main()
