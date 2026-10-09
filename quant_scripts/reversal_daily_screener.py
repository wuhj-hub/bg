#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反转数值 · 日线/周线信号跟踪轮动器（reversal_daily_screener.py · v2）
=====================================================================
口径（《反转数值MACD指标_优化版_代码》改①）：
  反转数值 = 0.618 × |MACD|
  S1 突破2倍反转数值 : MACD > 2×0.618×BL_DEEP（BL_DEEP=死叉以来最深绿柱）且 MACD 上升
  S2 回调不破1倍反转数值: 回调深 = |LLV(MACD, 突破以来)| < 0.618 × HHV(MACD, 金叉以来)
  信号 = S1 已发生 且 S2 成立 且 死叉之后（SCB>0 且 JCB>SCB）；现价 < 上限（默认10元）

跟踪轮动（v2 新增）：
  · 每次运行把命中标的并入**跟踪池**（data/reversal_pool_{tf}.json），跨日/跨周保留
  · 后续若**跌破**（回调深 ≥ 1倍反转数值）→ 从池中**删除**
  · 另两类移出：现价 ≥ 上限、距突破超过最大跟踪期（日线45根 / 周线15根）
  · 报告区分：本次新增 / 在池跟踪 / 本次移除

用法:
  python3 reversal_daily_screener.py --tf day  --window 5 --max-price 10 --pool-file all_mainboard.csv
  python3 reversal_daily_screener.py --tf week --window 2 --max-price 10 --pool-file all_mainboard.csv
输出: outputs/反转数值日线信号_{date}.md（day）/ outputs/反转数值周线跟踪_{date}.md（week）
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
MAXGAP = {"day": 45, "week": 15}          # 最大跟踪期（根）


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


def fetch_batch(codes, period="day", limit=250):
    out = {}
    for i in range(0, len(codes), BATCH):
        batch = codes[i:i + BATCH]
        try:
            r = subprocess.run(f"{WESTOCK} kline {','.join(batch)} --period {period} --limit {limit}",
                               shell=True, capture_output=True, text=True, timeout=300)
            rm = {}
            for ln in r.stdout.splitlines():
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
    deep = abs(min(seg))
    line = K * max(macd[max(0, i - int(JCB[i])):i + 1])
    return {"tp_date": rows[tp_bar][0], "tp_val": round(2 * K * bl, 2),
            "red_high": round(red_high, 2), "pullback": round(deep, 2),
            "line": round(line, 2), "valid": deep < line,
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
    ap.add_argument("--tf", default="day", choices=["day", "week"])
    ap.add_argument("--pool", default="")
    ap.add_argument("--pool-file", default="")
    ap.add_argument("--window", type=int, default=0, help="新信号检测窗口(根)；默认 day=5 / week=2")
    ap.add_argument("--max-price", type=float, default=10.0)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    tf = a.tf
    win = a.window or (5 if tf == "day" else 2)
    period, limit = ("day", 250) if tf == "day" else ("week", 130)

    pool = load_pool(a.pool, a.pool_file)
    if not pool:
        print("❌ 无股票池"); return
    print(f"🔍 反转数值[{tf}] 跟踪扫描 | 标的{len(pool)}只 | 新信号窗口{win}根 | 现价<{a.max_price:g}元")

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
            elif st["last_close"] >= a.max_price:
                removed.append({**cur, "code": code, "name": name, "reason": "现价≥上限"})
                tracked.pop(code, None)
            elif st["gap"] > MAXGAP[tf]:
                removed.append({**cur, "code": code, "name": name, "reason": "超过跟踪期"})
                tracked.pop(code, None)
            else:
                cur.update({k: st[k] for k in ("tp_date", "tp_val", "red_high", "pullback", "line", "gap", "last_close", "last_date")})
                cur["name"] = name
                kept.append(cur)
        else:
            # 新信号：突破2倍后回调不破1倍，且窗口内
            if st and st["valid"] and st["gap"] <= win and st["last_close"] < a.max_price:
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
    lbl = "日线" if tf == "day" else "周线"
    L = [f"# 🔄 反转数值·{lbl}信号跟踪（{today}）", "",
         f"> 股票池：{a.pool_file or ('自定义' if a.pool else '沪深300')} {len(pool)}只 ｜ 新信号窗口 {win} 根{lbl} ｜ 现价 < {a.max_price:g}元",
         f"> 口径：突破2倍反转数值 → 回调不破1倍反转数值（改①：不破线=0.618×金叉以来最高红柱）",
         f"> 跟踪规则：并入池后持续跟踪，**跌破1倍反转数值即删除**；另设「现价≥上限」「超跟踪期({MAXGAP[tf]}根)」移出", "",
         f"**本期：新增 {len(added)} ｜ 在池 {len(kept)} ｜ 移除 {len(removed)} ｜ 池内合计 {len(tracked)}**",
         f"> 📊 入池后历史胜率：{perf_line} ｜ 出池结算（跌破等）：{_agg(10, True)[0]} / 均值 {_agg(10, True)[1]}（n={_agg(10, True)[2]}）", ""]

    def tbl(rows, with_reason=False, with_first=False):
        if not rows:
            L.append("> 无")
            L.append("")
            return
        head = "| 代码 | 名称 | " + ("入池日 | " if with_first else "") + "信号日 | 最新价 | 突破日 | 突破2倍值 | 回调深 | 不破线(1倍) | 距突破 |" + (" 移除原因 |" if with_reason else "")
        L.append(head)
        L.append("|:--|:--|" + ("--:|" if with_first else "") + "--:|--:|:--|--:|--:|--:|--:|" + ("--:|" if with_reason else ""))
        for s in rows:
            mid = f"| {s.get('first_date','')} " if with_first else ""
            tail = f"  {s.get('reason','')} |" if with_reason else ""
            L.append(f"| {s['code']} | {s['name']} |{mid}| {s.get('tp_date','')} | {s.get('last_close','')} | {s.get('tp_date','')} | "
                     f"{float(s.get('tp_val',0)):+.2f} | {float(s.get('pullback',0)):.2f} | {float(s.get('line',0)):.2f} | {s.get('gap','')} |" + tail)
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
    fn = f"反转数值日线信号_{today}.md" if tf == "day" else f"反转数值周线跟踪_{today}.md"
    fp = os.path.join("outputs", fn)
    open(fp, "w", encoding="utf-8").write("\n".join(L))
    print(f"✅ [{tf}] 新增{len(added)} 在池{len(kept)} 移除{len(removed)} 池内{len(tracked)} | 报告: {fp} | 池: {pool_fp}")
    for s in added[:12]:
        print(f"   + {s['code']} {s['name']} 价{s['last_close']} 突破{s['tp_date']} 回调{s['pullback']}<{s['line']}")
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
                    P.append(f"- {s['code'][2:]} {s['name']} {s['last_close']}｜突破{s['tp_date']}｜回调{s['pullback']}<{s['line']}")
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
