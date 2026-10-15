#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反转数值 · 日线/周线/月线信号跟踪轮动器（reversal_daily_screener.py · v3）
=====================================================================
口径（《反转数值MACD指标_优化版_代码》改①）：
  反转数值 = 0.618 × |MACD|
  S1 突破2倍反转数值 : MACD > 2×0.618×BL_DEEP（BL_DEEP=死叉以来最深绿柱）且 MACD 上升
  S2 回调不破1倍反转数值: 回调深 = |LLV(MACD, 突破以来)| < 0.618 × HHV(MACD, 金叉以来)
  信号 = S1 已发生 且 S2 成立 且 死叉之后（SCB>0 且 JCB>SCB）；现价 < 上限（默认10元）

跟踪轮动（v2 新增）：
  · 每次运行把命中标的并入**跟踪池**（data/reversal_pool_{tf}.json），跨日/跨周保留
  · 后续若**跌破**（回调深 ≥ 1倍反转数值）→ 从池中**删除**
  · 另两类移出：现价 ≥ 上限、距突破超过最大跟踪期（日线45根 / 周线30根 / 月线18根）
  · 报告区分：本次新增 / 在池跟踪 / 本次移除

口径差异（v3）：
  · 日线：保留「改1+改2」；新信号须在窗口内（--window，默认5）
  · 周线/月线：只保留「改2」，且取消新信号窗口（凡当前结构构成改2即纳入跟踪）
用法:
  python3 reversal_daily_screener.py --tf day   --window 5 --max-price 10 --pool-file all_mainboard.csv
  python3 reversal_daily_screener.py --tf week  --max-price 10 --pool-file all_mainboard.csv
  python3 reversal_daily_screener.py --tf month --max-price 10 --pool-file all_mainboard.csv
输出: outputs/反转数值日线信号_{date}.md（day）/ outputs/反转数值周线跟踪_{date}.md（week）
      / outputs/反转数值月线跟踪_{date}.md（month）
"""
import os, sys, re, json, subprocess, argparse, shutil
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
_W = shutil.which("westock-data-skillhub")
WESTOCK = _W if _W else "npx -y westock-data-skillhub@1.0.3"
BATCH = 250
K = 0.618
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
    """改1->+0.618×H（水上）；改2->−0.618×H（水下）"""
    ln = float(s.get("line", 0))
    return ln if s.get("angle") == "改1" else -ln


def fetch_batch(codes, period="day", limit=250):
    out = {}
    for i in range(0, len(codes), BATCH):
        batch = codes[i:i + BATCH]
        try:
            _out = _fetch_layer(["kline", ",".join(batch), "--period", str(period),
                                 "--limit", str(limit)], 300)
            rm = {}
            for ln in _out.splitlines():
                m = re.match(r"\|\s*([a-z]{2}\d{6})\s*\|\s*([\d-]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
                if m:
                    rm.setdefault(m.group(1), []).append(
                        (m.group(2), float(m.group(3)), float(m.group(4)), float(m.group(5)), float(m.group(6))))
            for sym, rows in rm.items():
                rows.sort(key=lambda x: x[0])
                out[sym] = rows
        except Exception as e:
            print(f"  [warn] 批{i//BATCH+1}拉取失败: {e}")
    return out


def eval_state(rows, lookback_tp=120):
    """对一只股票评估当前状态: 是否'突破2倍后回调不破1倍'
    返回 dict(tp_date,tp_val,red_high,pullback,line,valid,gap,last_date,last_close) 或 None"""
    if len(rows) < 80:
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
    if SCB[i] is None or JCB[i] is None or SCB[i] == 0:
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
    return {"tp_date": rows[tp_bar][0], "tp_val": round(2 * K * bl, 2),
            "red_high": round(red_high, 2), "pullback": round(deep, 2),
            "line": round(line, 2), "m_low": round(m_low, 2),
            "angle": ("改1" if m_low > 0 else "改2"), "valid": deep < line,   # 窄口径：仅保留「回踩幅度 < 0.618×金叉以来最高红柱」(回踩确认)
            "gap": i - tp_bar, "last_date": rows[-1][0], "last_close": round(closes[-1], 2)}


def load_pool(pool_arg="", pool_file=""):
    if pool_arg:
        return [(c.strip(), "") for c in pool_arg.split(",") if c.strip()]
    name = pool_file or "hs300.csv"
    cands = [name] if os.path.isabs(name) else [
        os.path.join(BASE, name), os.path.join(ROOT, name), os.path.join(os.getcwd(), name)]
    fp = next((p for p in cands if os.path.exists(p)), None)
    rows = []
    if fp:
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
    else:
        print(f"  [warn] 未找到股票池文件: {name}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="day", choices=["day", "week", "month"])
    ap.add_argument("--pool", default="")
    ap.add_argument("--pool-file", default="")
    ap.add_argument("--window", type=int, default=0, help="新信号检测窗口(根)；默认 day=5 / week=2")
    ap.add_argument("--max-price", type=float, default=10.0)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    tf = a.tf
    win = a.window or (5 if tf == "day" else 2)
    only2 = tf in ("week", "month")   # 周线/月线：只保留「改2（死叉回调·不破水下反转数值线）」
    nowin = tf in ("week", "month")   # 周线/月线：取消「新信号窗口」，凡当前结构构成改2即纳入
    period, limit = {"day": ("day", 250), "week": ("week", 130), "month": ("month", 124)}[tf]

    pool = load_pool(a.pool, a.pool_file)
    if not pool:
        print("❌ 无股票池"); return
    print(f"🔍 反转数值[{tf}] 跟踪扫描 | 标的{len(pool)}只 | " + ("只留改2·无窗口 | " if only2 else f"新信号窗口{win}根 | ") + f"现价<{a.max_price:g}元")

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

    added, removed, kept = [], [], []
    for code, name in pool:
        rows = rows_map.get(code)
        if not rows:
            continue
        st = eval_state(rows)
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
                removed.append({**cur, "code": code, "name": name, "reason": "跌破1倍反转数值"})
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
                cur.update({k: st[k] for k in ("tp_date", "tp_val", "red_high", "pullback", "line", "m_low", "angle", "gap", "last_close", "last_date")})
                cur["name"] = name
                kept.append(cur)
        else:
            # 新信号：突破2倍后回调不破1倍
            #   日线：须在「新信号窗口」内（gap ≤ win）
            #   周线/月线（only2+nowin）：取消窗口，凡当前结构构成「改2」即纳入跟踪
            ok_new = (bool(st) and st["valid"] and st["last_close"] < a.max_price
                      and (not only2 or st["angle"] == "改2")
                      and (nowin or st["gap"] <= win))
            if ok_new:
                item = {"code": code, "name": name, "first_date": today, **st}
                tracked[code] = item
                added.append(item)

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
          else f"> 股票池：{a.pool_file or ('自定义' if a.pool else '沪深300')} {len(pool)}只 ｜ 新信号窗口 {win} 根{lbl} ｜ 现价 < {a.max_price:g}元"),
         (f"> 口径：突破2倍反转数值 → 回调不破1倍反转数值；**仅保留「改2」**——突破后死叉下水、但不破水下反转数值线（−0.618×金叉以来最高红柱）；纳入不看突破窗口（当前结构构成改2即纳入）" if only2
          else f"> 口径：突破2倍反转数值 → 回调不破1倍反转数值后回踩，分两角度——**改1（保持强势）**：突破后 MACD 未下水（自突破以来最低值 > 0）；**改2（死叉回调）**：突破后死叉下水、但不破水下反转数值线（−0.618×金叉以来最高红柱）"),
         f"> 跟踪规则：并入池后持续跟踪，**跌破1倍反转数值即删除**；另设「现价≥上限」「超跟踪期({MAXGAP[tf]}根)」移出", "",
         f"**本期：新增 {len(added)} ｜ 在池 {len(kept)} ｜ 移除 {len(removed)} ｜ 池内合计 {len(tracked)}**",
         f"> 📊 入池后历史胜率：{perf_line} ｜ 出池结算（跌破等）：{_agg(10, True)[0]} / 均值 {_agg(10, True)[1]}（n={_agg(10, True)[2]}）", ""]

    def tbl(rows, with_reason=False, with_first=False):
        if not rows:
            L.append("> 无")
            L.append("")
            return
        cols = ["代码", "名称"] + (["入池日"] if with_first else []) + \
               ["最新日期", "最新价", "角度", "突破日", "突破2倍值", "回调深", "不破线", "距突破"] + \
               (["移除原因"] if with_reason else [])
        L.append("| " + " | ".join(cols) + " |")
        L.append("|" + "|".join(":--" if c in ("代码", "名称", "入池日", "最新日期", "角度", "突破日", "移除原因") else "--:" for c in cols) + "|")
        for s in rows:
            cells = [s["code"], s["name"]]
            if with_first:
                cells.append(s.get("first_date", ""))
            cells += [s.get("last_date", ""), s.get("last_close", ""), s.get("angle", ""), s.get("tp_date", ""),
                      f"{float(s.get('tp_val', 0)):+.2f}", f"{float(s.get('pullback', 0)):.2f}",
                      f"{_line_signed(s):+.2f}", s.get("gap", "")]
            if with_reason:
                cells.append(s.get("reason", ""))
            L.append("| " + " | ".join(str(c) for c in cells) + " |")
        L.append("")

    L.append(f"## 🆕 本次新增（{len(added)}）")
    L.append("")
    tbl(sorted(added, key=lambda x: x["gap"]), with_first=True)
    L.append(f"## 📌 在池跟踪（{len(kept)}）")
    L.append("")
    tbl(sorted(kept, key=lambda x: x["gap"]))
    L.append(f"## 🗑️ 本次移除（{len(removed)}）")
    L.append("")
    tbl(sorted(removed, key=lambda x: x.get("pullback", 0), reverse=True), with_reason=True, with_first=True)
    L.append("---")
    L.append("> ⚠️ 量化规律统计，不构成投资建议。跌破1倍反转数值即出池。")

    os.makedirs("outputs", exist_ok=True)
    fn = {"day": f"反转数值日线信号_{today}.md", "week": f"反转数值周线跟踪_{today}.md", "month": f"反转数值月线跟踪_{today}.md"}[tf]
    fp = os.path.join("outputs", fn)
    open(fp, "w", encoding="utf-8").write("\n".join(L))
    print(f"✅ [{tf}] 新增{len(added)} 在池{len(kept)} 移除{len(removed)} 池内{len(tracked)} | 报告: {fp} | 池: {pool_fp}")
    for s in added[:12]:
        print(f"   + [{s.get('angle','')}] {s['code']} {s['name']} 价{s['last_close']} 突破{s['tp_date']} 回调{s['pullback']}<{s['line']}")
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
            if added:
                P += ["", f"### 🆕 新增（{len(added)}）"]
                for s in sorted(added, key=lambda x: x["gap"])[:12]:
                    P.append(f"- {s['code'][2:]} {s['name']} {s['last_close']}｜{s.get('angle','')}｜突破{s['tp_date']}｜回调{s['pullback']}<{s['line']}")
                if len(added) > 12:
                    P.append(f"- …等共 {len(added)} 只（完整见知识库报告）")
            if removed:
                P += ["", f"### 🗑️ 移除（{len(removed)}）"]
                for s in removed[:8]:
                    P.append(f"- {s['code'][2:]} {s['name']}｜{s.get('reason','')}")
                if len(removed) > 8:
                    P.append(f"- …等共 {len(removed)} 只")
            P += ["", "> 规则：跌破1倍反转数值即出池；完整报告见知识库"]
            body = urllib.parse.urlencode({"token": token, "title": f"🔄 反转数值{lbl}跟踪 {today}",
                                           "content": "\n".join(P), "template": "markdown"}).encode()
            try:
                r = urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body), timeout=30)
                print(f"[pushplus] {r.read().decode()[:80]}")
            except Exception as e:
                print(f"[pushplus] 失败: {e}")


if __name__ == "__main__":
    main()
