#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pool_tracking_report.py —— 股池标的跟踪报告（三阶漏斗整合版 v1.0）
====================================================================
对股票池标的逐只执行「三阶漏斗」：
  第一阶 月线反转（曾星智+陶博士）: 月线趋势/反转信号/闸门  ← month_frame.py
  第二阶 武威G1（低吸潜伏）: 双阴/一阴缩量回调到起涨点 + 支撑深度
  第三阶 v2.1质量否决: 支撑≥5% + 非亏损 + 仓位决策

输出: 结构化跟踪报告（整合三阶漏斗的新格式）→ 知识库 + 推送

用法: python3 pool_tracking_report.py [--pool "sz000779,sz002596,..."] [--name 自定义标题]
"""
import subprocess, sys, os, re, json, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def run(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_month_kline(txt):
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or "---" in parts[0]:
            continue
        if len(parts) >= 6:
            try:
                di = header.index("date")
                row = {"date": parts[di]}
                for key in ("open", "last", "high", "low", "volume"):
                    if key in header:
                        row[key] = float(parts[header.index(key)])
                if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                    rows.append(row)
            except (ValueError, IndexError):
                pass
    rows.sort(key=lambda r: r["date"])
    return rows

def ma(vals, i, n):
    return sum(vals[i-n+1:i+1]) / n

# ═══════ 第一阶: 月线反转（与month_frame.py一致）═══════
def month_frame(rows):
    if len(rows) < 7:
        return {"trend": "无数据", "gate": "BLOCK", "reversal": None, "ma6": None, "ma12": None, "close": None}
    closes = [r["last"] for r in rows]
    cur = closes[-1]
    ma6 = sum(closes[-6:]) / 6
    ma12 = sum(closes[-12:]) / 12
    ma6_prev = sum(closes[-7:-1]) / 6
    ma12_prev = sum(closes[-13:-1]) / 12
    if cur > ma6 > ma12:
        trend = "多头"
    elif cur < ma6 < ma12:
        trend = "空头"
    else:
        trend = "纠缠"
    reversal = None
    prev_high = max(r["high"] for r in rows[:-1])
    if cur > prev_high and cur > ma6:
        reversal = "平台突破(12月新高)"
    elif ma6 > ma12 and ma6_prev <= ma12_prev:
        reversal = "均线金叉(MA6上穿MA12)"
    elif ma6 > ma12 and cur > ma6 and (ma6 - ma6_prev) > 0:
        reversal = "趋势确立(MA6上行)"
    gate = "PASS" if (trend == "多头" or reversal) else "WARN" if trend == "纠缠" else "BLOCK"
    return {"trend": trend, "gate": gate, "reversal": reversal, "ma6": round(ma6, 2),
            "ma12": round(ma12, 2), "close": round(cur, 2)}

# ═══════ 第二阶: 武威G1 + 支撑深度 ═══════
def wuwei_g1(rows):
    if len(rows) < 4:
        return "无", None, None
    k1, k2, k3, k4 = rows[-4], rows[-3], rows[-2], rows[-1]
    def yang(r): return r["last"] > r["open"]
    def yin(r): return r["last"] < r["open"]
    support = None
    if k4["last"] > 0 and k1["low"] > 0:
        support = (k4["last"] - k1["low"]) / k4["last"]
    ratios = []
    if k2["volume"] > 0:
        ratios.append(k3["volume"] / k2["volume"])
        ratios.append(k4["volume"] / k2["volume"])
    shrink_max = max(ratios) if ratios else 1.0
    if yin(k3) and yin(k4):
        if k4["volume"] <= k2["volume"] * 0.6 and k3["volume"] <= k2["volume"] * 0.6:
            if k1["low"] > 0 and abs(k4["low"] - k1["low"]) / k1["low"] <= 0.12:
                return "双阴", support, shrink_max
    if yang(k3) and yin(k2) and yin(k4):
        if k2["volume"] < k3["volume"] * 0.6 and k4["volume"] < k3["volume"] * 0.6:
            if k3["low"] > 0 and abs(k4["low"] - k3["low"]) / k3["low"] <= 0.12:
                return "一阴", support, shrink_max
    return "无", support, shrink_max

# ═══════ 第三阶: v2.1质量否决（支撑≥5% + 盈利）═══════
def fetch_finance(codes):
    fin = {}
    codes = sorted(set(codes))
    for i in range(0, len(codes), 10):
        batch = codes[i:i+10]
        out = run(["finance", ",".join(batch), "--type", "lrb", "--num", "1"])
        lines = [l for l in out.splitlines() if l.strip().startswith("|")]
        if len(lines) >= 2:
            hdr = [h.strip() for h in lines[0].strip().strip("|").split("|")]
            if "SecuCode" in hdr and "NPParentCompanyOwners" in hdr:
                sci, npi = hdr.index("SecuCode"), hdr.index("NPParentCompanyOwners")
                for l in lines[2:]:
                    cols = [x.strip() for x in l.strip().strip("|").split("|")]
                    if len(cols) > max(sci, npi):
                        code, npv = cols[sci], cols[npi]
                        try:
                            v = float(npv)
                            fin[code] = "盈利" if v > 0 else "亏损"
                        except ValueError:
                            fin[code] = "无数据"
    for c in codes:
        fin.setdefault(c, "无数据")
    return fin

def v21_decision(sig_type, support, finance):
    """v2.1一票否决+仓位决策"""
    if finance == "亏损":
        return "否决", "亏损股(一票否决)"
    if support is None or support < 0.05:
        return "否决", "浅支撑<5%(一票否决)"
    if sig_type == "双阴" and finance == "盈利":
        return "重仓", "双阴+深支撑+盈利 ★"
    if sig_type == "一阴":
        return "轻仓", "一阴仅轻仓(永不重仓)"
    return "观察", "未触发G1"

def load_regime_from_quant():
    """从quant_results_latest.json读取市场档位（猛兽评分/双弦温度）"""
    try:
        for p in ("quant_results_latest.json", "outputs/quant_results_latest.json"):
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                beast = d.get("beast") or {}
                sx = d.get("shuangxian") or {}
                bstd = beast.get("stdout", "")
                m = re.search(r"安全评分:\s*([\d.]+)/100", bstd)
                bs = float(m.group(1)) if m else None
                sstd = sx.get("stdout", "")
                m2 = re.search(r"温度[:计]?\s*([\d.]+)", sstd)
                temp = float(m2.group(1)) if m2 else None
                gate = "关闭" in sstd and "开启" not in sstd
                from trade_guard import market_regime
                regime, hint = market_regime(bs, temp, not gate)
                return regime, hint
    except Exception:
        pass
    return "震荡", "标准档：信号正常，仓位上限50%"

def track_stock(code, name=""):
    rows = []
    for _ in range(3):
        txt = run(["kline", code, "--period", "month", "--limit", "36"])
        rows = parse_month_kline(txt)
        if rows:
            break
    if len(rows) < 7:
        return {"code": code, "name": name, "ok": False, "err": "月线数据不足"}
    cur_price = rows[-1]["last"] if rows[-1]["date"].startswith("2026-08") else rows[-1]["last"]
    # 月线趋势/反转: 用含当月盘中K线（实时，与猛兽Step 2.6口径一致）
    mf = month_frame(rows)
    # 武威G1: 用最近完整月（当月未走完时去掉当月K线，月末信号定稿）
    rows_g1 = rows
    if rows and re.match(r"^\d{4}-08", rows[-1]["date"]):
        rows_g1 = rows[:-1]
    g1, support, shrink = wuwei_g1(rows_g1)
    # 交易防护（ATR止损/盈亏比/离场计分）
    guard = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from trade_guard import check_stock
        guard = check_stock(code)
    except Exception:
        pass
    return {"code": code, "name": name, "ok": True, "mf": mf, "g1": g1,
            "support": support, "shrink": shrink, "price": cur_price, "guard": guard}

def load_pool_file(path="stock_pool.txt"):
    """读取股票池配置文件（兼容 '代码 # 名称' 或 'sh600000 名称' 或纯代码行）"""
    pool = []
    if not os.path.exists(path):
        return pool
    with open(path, encoding="utf-8") as f:
        for ln in f:
            s = ln.split("#")[0].strip()
            if not s:
                continue
            parts = s.split()
            code = parts[0].strip()
            m = re.match(r"^(sh|sz)?(\d{6})$", code)
            if not m:
                continue
            code = (m.group(1) or ("sh" if m.group(2).startswith("6") else "sz")) + m.group(2)
            name = ln.split("#")[-1].strip() if "#" in ln else ""
            pool.append((code, name))
    return pool

def push_pushplus(token, title, file_path=None, content=None):
    """PushPlus推送报告摘要或自定义内容"""
    import urllib.request, urllib.parse
    try:
        if content is None:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            # 截取报告前部关键内容（信号卡/总览）
            content = content[:4000] + ("\n\n...（完整报告见 IMA 知识库全盘量化文件夹）" if len(content) > 4000 else "")
        body = urllib.parse.urlencode({"token": token, "title": title, "content": content, "template": "markdown"}).encode()
        req = urllib.request.Request("https://pushplus.plus/send", data=body)
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = r.read().decode()
        print(f"[pushplus] {resp[:100]}")
    except Exception as e:
        print(f"[pushplus] 失败: {e}")

def append_signal_log(results, fin):
    """信号日志CSV累积（供胜率跟踪）"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        os.makedirs("outputs", exist_ok=True)
        log = "outputs/pool_signals_log.csv"
        need_header = not os.path.exists(log)
        with open(log, "a", encoding="utf-8") as f:
            if need_header:
                f.write("date,code,name,trend,gate,reversal,g1,support,finance,decision\n")
            for r in results:
                if not r["ok"]:
                    continue
                mf, g1 = r["mf"], r["g1"]
                fst = fin.get(r["code"], "无数据")
                support = f"{r['support']:.4f}" if r["support"] is not None else ""
                f.write(f"{today},{r['code']},{r['name']},{mf['trend']},{mf['gate']},"
                        f"{mf['reversal'] or ''},{g1},{support},{fst},{''}\n")
        print(f"[log] 信号日志已累积 → {log}")
    except Exception as e:
        print(f"[log] 失败: {e}")

def load_extend_signals(lianghua_path="panhou_lianghua.md"):
    """从全盘量化报告提取主力信号标的（主力主导放量/偏强放量/控盘），返回 [(code,name)]"""
    added = []
    if not os.path.exists(lianghua_path):
        if os.path.exists("outputs/" + lianghua_path):
            lianghua_path = "outputs/" + lianghua_path
        else:
            return added
    with open(lianghua_path, encoding="utf-8") as f:
        text = f.read()
    # 解析主力信号专表行: | 代码 | 名称 | 价格 | 信号 | ...
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 5 and re.match(r"^\d{6}$", parts[0]):
            sig = parts[3]
            if any(k in sig for k in ("主力主导放量", "主力偏强放量", "主力控盘")):
                code = ("sh" if parts[0].startswith("6") else "sz") + parts[0]
                added.append((code, f"{parts[1]}({sig[:4]})"))
    return added

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--pool-file", default="stock_pool.txt", help="股票池配置文件路径")
    ap.add_argument("--push", action="store_true", help="推送PushPlus")
    ap.add_argument("--auto-extend", action="store_true",
                    help="自动并入全盘量化当日主力信号（panhou_lianghua.md）")
    ap.add_argument("--holdings", default="", help="持仓代码列表(逗号分隔)，离场计分卡仅对持仓生效")
    ap.add_argument("--holdings-file", default="holdings.txt", help="持仓文件(每行一个代码)")
    ap.add_argument("--date", default="", help="指定日期(默认今天)，用于补生成历史股池跟踪")
    a = ap.parse_args()

    # 持仓集合
    holdings = set()
    if a.holdings:
        holdings = {c.strip() for c in a.holdings.split(",") if c.strip()}
    elif os.path.exists(a.holdings_file):
        with open(a.holdings_file, encoding="utf-8") as f:
            for ln in f:
                s = ln.split("#")[0].strip()
                for c in s.replace("，", ",").split(","):
                    c = c.strip()
                    if c:
                        holdings.add(c)

    DEFAULT_POOL = [
        ("sz000779", "甘咨询"), ("sz002596", "海南瑞泽"), ("sh600095", "湘财股份"),
        ("sz000026", "飞亚达(武威7月重仓)"),
        ("sh603259", "药明康德(8/4反转)"), ("sz002354", "天娱数科(8/4反转)"),
        ("sz000636", "风华高科(8/4反转)"), ("sz000725", "京东方A(8/4反转)"),
        ("sh600664", "哈药股份(8/4反转)"), ("sh600396", "华电辽能(8/4反转)"),
        ("sz000938", "紫光股份(8/4反转)"), ("sz000815", "美利云(8/4反转)"),
        ("sz000892", "欢瑞世纪(主力放量)"), ("sz000566", "海南海药(主力放量)"),
        ("sz002131", "利欧股份(主力放量)"),
    ]
    # 股池优先级: --pool 参数 > 配置文件 > 默认池
    if a.pool:
        pool = [(c.strip(), "") for c in a.pool.split(",") if c.strip()]
        pool_src = "命令行参数"
    else:
        file_pool = load_pool_file(a.pool_file)
        if not file_pool:
            file_pool = load_pool_file("quant_scripts/" + a.pool_file)  # GitHub runner路径
        if file_pool:
            pool = file_pool
            pool_src = f"配置文件({a.pool_file}, {len(pool)}只)"
        else:
            pool = DEFAULT_POOL
            pool_src = "默认池"
    # 自动并入当日主力信号（动态刷新）
    if a.auto_extend:
        extend = load_extend_signals()
        if extend:
            existing = {c for c, _ in pool}
            new = [(c, n) for c, n in extend if c not in existing]
            pool = pool + new
            pool_src += f" + 当日主力信号{len(extend)}只(新增{len(new)})"
    # 持仓强制并入跟踪池（确保离场计分卡每日都有数据，即使持仓不在任何股池）
    if holdings:
        pool_codes = {c for c, _ in pool}
        missing = [c for c in holdings if c not in pool_codes]
        if missing:
            pool = pool + [(c, f"持仓:{c}") for c in missing]
            pool_src += f" + 持仓{len(missing)}只(强制跟踪)"
    print(f"跟踪标的: {len(pool)} 只（来源: {pool_src}）\n")

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(track_stock, c, n): (c, n) for c, n in pool}
        for f in as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda r: r["code"])

    # 财务
    need_fin = [r["code"] for r in results if r["ok"]]
    fin = fetch_finance(need_fin)

    # ═══ 生成报告 ═══
    title = a.name or "股池标的跟踪报告"
    regime, regime_hint = load_regime_from_quant()
    L = []
    A = L.append
    A(f"# 📊 {title} · 三阶漏斗+交易防护整合版\n")
    A(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据：月线/日线K线+利润表（westock）")
    A("> **三阶漏斗**：① 月线反转（曾星智MA6/MA12+陶博士）→ ② 武威G1（双阴/一阴缩量回调）→ ③ v2.1质量否决（支撑≥5%+盈利）")
    A("> **交易防护**：ATR动态止损 + 盈亏比门槛(≥2) + 离场计分卡（八维计分卡启发）")
    A(f"> 📅 信号基准月：**2026-07**（月末完整月） | 股池来源：**{pool_src}** | 市场档位：**{regime}**（{regime_hint}）\n")

    # 汇总表（只显示有信号价值的：月线PASS或有G1信号；其余合并统计）
    sig_results = [r for r in results if r["ok"] and
                   (r["mf"]["gate"] == "PASS" or r["g1"] in ("双阴", "一阴"))]
    warn_count = len([r for r in results if r["ok"] and r["mf"]["gate"] == "WARN"
                      and r["g1"] not in ("双阴", "一阴")])
    block_count = len([r for r in results if r["ok"] and r["mf"]["gate"] == "BLOCK"])
    data_na = len([r for r in results if not r["ok"]])
    A("## 一、三阶漏斗总览\n")
    A(f"| 代码 | 名称 | 现价 | ①月线 | 闸门 | 反转信号 | ②G1 | 支撑 | ③v2.1 | 盈亏比 | 止损 | 决策 |")
    A("|:----|:----|:----:|:----:|:----:|:--------|:----:|:----:|:----:|:----:|:----:|:----:|")
    for r in sig_results:
        mf, g1 = r["mf"], r["g1"]
        sup_txt = f"{r['support']*100:.0f}%" if r["support"] is not None else "—"
        fst = fin.get(r["code"], "无数据")
        gate_txt = {"PASS": "🟢", "WARN": "🟡"}.get(mf["gate"], "❔")
        rev_txt = mf["reversal"] or "—"
        # 交易防护
        rr = r["guard"].get("rr") if r.get("guard") else None
        rr_txt = f"{rr:.1f}✅" if rr and rr >= 2 else f"{rr:.1f}❌" if rr else "—"
        stop_txt = str(r["guard"].get("stop")) if r.get("guard") and r["guard"].get("stop") else "—"
        rr_ok = rr is not None and rr >= 2.0
        if mf["gate"] == "PASS" and g1 in ("双阴", "一阴") and fst == "盈利" and (r["support"] or 0) >= 0.05:
            dec = "★ 三重共振" if rr_ok else "★ 共振(盈亏比不足)"
        elif mf["gate"] == "PASS" and g1 in ("双阴", "一阴"):
            dec = "二阶共振"
        elif mf["gate"] == "PASS":
            dec = "一阶通过"
        else:
            dec = "G1低吸信号"
        A(f"| {r['code']} | {r['name']} | {r['price']} | {mf['trend']} | {gate_txt} | {rev_txt} | {g1} | {sup_txt} | {fst} | {rr_txt} | {stop_txt} | **{dec}** |")
    if warn_count:
        A(f"| ... | **{warn_count} 只月线纠缠**（无G1信号） | — | 🟡 | — | — | — | — | — | 待确认 |")
    if block_count:
        A(f"| ... | **{block_count} 只月线空头** | — | 🔴 被月线闸门拦截 | — | — | — | — | — | 否决 |")
    if data_na:
        A(f"| ... | **{data_na} 只数据不足** | — | — | — | — | — | — | — | ⚠️ |")
    if not sig_results and not warn_count and not block_count and not data_na:
        A("| — | 无标的 | — | — | — | — | — | — | — | — |")

    # 三阶共振明细
    A("\n## 二、三阶共振标的（★ 可执行）\n")
    A("| 代码 | 名称 | 月线反转 | 武威G1 | 支撑 | 财务 | 建议 |")
    A("|:----|:----|:--------|:------|:----:|:----:|:----|")
    n_star = 0
    for r in results:
        if not r["ok"]:
            continue
        mf, g1 = r["mf"], r["g1"]
        fst = fin.get(r["code"], "无数据")
        if mf["gate"] == "PASS" and g1 in ("双阴", "一阴") and fst == "盈利" and (r["support"] or 0) >= 0.05:
            n_star += 1
            sup = f"{r['support']*100:.0f}%"
            weight = "重仓" if g1 == "双阴" else "轻仓"
            A(f"| {r['code']} | {r['name']} | {mf['reversal'] or mf['trend']} | {g1} | {sup} | {fst} | **{weight}关注**（月线破MA6离场） |")
    if n_star == 0:
        A("| — | 当前无三重共振标的 | — | — | — | — | — |")

    # 二阶/一阶明细（仅月线PASS或有G1信号）
    A("\n## 三、信号明细（一阶通过 / 二阶共振）\n")
    A("| 代码 | 名称 | ①月线 | ②G1 | ③v2.1 | 状态 |")
    A("|:----|:----|:----:|:----:|:----:|:----|")
    for r in results:
        if not r["ok"]:
            continue
        mf, g1 = r["mf"], r["g1"]
        fst = fin.get(r["code"], "无数据")
        sup_ok = (r["support"] or 0) >= 0.05
        if mf["gate"] == "PASS" and g1 in ("双阴", "一阴") and fst == "盈利" and sup_ok:
            continue  # 已在上表
        if mf["gate"] != "PASS" and g1 not in ("双阴", "一阴"):
            continue  # 纠缠/空头无G1，已合并计数
        sup_txt = f"支撑{round((r['support'] or 0)*100)}%" if r["support"] else ""
        A(f"| {r['code']} | {r['name']} | {mf['trend']}{'⚡'+mf['reversal'] if mf['reversal'] else ''} | {g1} | {fst}·{sup_txt} | 观察 |")

    # 被否决明细（仅BLOCK或数据不足）
    A("\n## 四、否决 / 拦截标的（三阶漏斗未通过）\n")
    A("| 代码 | 名称 | 拦截原因 |")
    A("|:----|:----|:--------|")
    for r in results:
        if not r["ok"]:
            A(f"| {r['code']} | {r['name']} | 数据不足 |")
            continue
        mf, g1 = r["mf"], r["g1"]
        fst = fin.get(r["code"], "无数据")
        if mf["gate"] != "BLOCK":
            continue
        reason = []
        reason.append("月线空头(BLOCK)")
        if g1 == "无":
            reason.append("无武威G1信号")
        if fst == "亏损":
            reason.append("亏损股")
        elif (r["support"] or 0) < 0.05 and r["support"] is not None:
            reason.append(f"浅支撑{round(r['support']*100)}%<5%")
        A(f"| {r['code']} | {r['name']} | {'、'.join(reason) or '未达条件'} |")

    A("\n---")
    A("⚠️ 本报告基于公开市场数据整理，不构成投资建议。三阶漏斗为量化历史规律总结，实战需结合大盘温度动态调整。")

    # 交易防护明细（ATR/离场计分）：持仓标的全显示 + 有信号标的
    A("\n## 五、交易防护明细（ATR止损 / 离场计分卡）\n")
    A(f"> 持仓 {len(holdings)} 只（--holdings）；离场计分仅对持仓有约束力，未持仓标的行为参考\n")
    A("| 代码 | 名称 | 持仓 | 月线 | ATR | ATR止损 | 盈亏比 | 离场分 | 离场状态 | 原因 | 止盈参考(t1/t2/t3·移动) |")
    A("|:----|:----|:----:|:----:|:----:|:----:|:----:|:----:|:----:|:----|:----|")
    shown = set()
    # 持仓标的第一优先
    for r in results:
        if not r["ok"] or r["code"] not in holdings:
            continue
        shown.add(r["code"])
        g = r.get("guard")
        mf = r["mf"]
        if g and g.get("ok"):
            reasons = "、".join(g.get("exit_reasons", [])[:3]) or "—"
            tp = g.get("take_profit") or {}
            tp_txt = f"{tp.get('t1_33','—')}/{tp.get('t2_66','—')}/{tp.get('t3_100','—')}·移{g.get('trail_stop','—')}" if tp else "—"
            A(f"| {r['code']} | {r['name']} | ✅ | {mf['trend']} | {g.get('atr')} | {g.get('stop')} | {g.get('rr')} | {g['exit_score']} | {g['exit_action']} | {reasons} | {tp_txt} |")
        else:
            A(f"| {r['code']} | {r['name']} | ✅ | {mf['trend']} | 数据获取失败 | — | — | — | — | — | — |")
    # 其余有信号标的（参考）
    for r in sig_results:
        if r["code"] in shown:
            continue
        g = r.get("guard")
        if not g or not g.get("ok"):
            continue
        held = "✅" if r["code"] in holdings else "—"
        reasons = "、".join(g.get("exit_reasons", [])[:3]) or "—"
        if r["code"] not in holdings and g["exit_score"] <= -2:
            status = "未持仓·参考"
        else:
            status = g["exit_action"]
        tp = g.get("take_profit") or {}
        tp_txt = f"{tp.get('t1_33','—')}/{tp.get('t2_66','—')}/{tp.get('t3_100','—')}·移{g.get('trail_stop','—')}" if tp else "—"
        A(f"| {r['code']} | {r['name']} | {held} | {r['mf']['trend']} | {g.get('atr')} | {g.get('stop')} | {g.get('rr')} | {g['exit_score']} | {status} | {reasons} | {tp_txt} |")
    A("\n> 💡 离场计分卡（八维启发）：月线破MA6(-2)/ATR止损破位(-2)/日线破MA20(-1)/MACD死叉(-1)；≤-2强制离场（仅对已持仓标的有约束力）")

    # ─── 六、组合层风控（B2·2026-08-10）：集中度/同向/组合离场联动 ───
    A("\n## 六、组合层风控（集中度 / 同向 / 组合离场）\n")
    A("> 默认约束（可调整）：单票≤15% / 单一板块≤30% / 同向信号≤5只 / 持仓≤5只\n")
    hold_scores = []
    for r in results:
        if r.get("ok") and r["code"] in holdings:
            g = r.get("guard")
            if g and g.get("ok"):
                hold_scores.append({"code": r["code"], "name": r["name"],
                                    "exit_score": g.get("exit_score", 0),
                                    "action": g.get("exit_action", "")})
    if hold_scores:
        n_hold = len(hold_scores)
        n_exit = sum(1 for h in hold_scores if h["exit_score"] <= -2)
        est_pos = min(100, n_hold * 15)  # 默认单票15%估算组合仓位
        A("| 约束项 | 状态 | 说明 |")
        A("|:----|:----|:----|")
        A(f"| 持仓数量 | {'✅' if n_hold <= 5 else '⚠️ 超限'} | {n_hold} 只（≤5默认）|")
        A(f"| 估算总仓位 | {'✅' if est_pos <= 60 else '⚠️ 偏高'} | 按单票15%估算 ≈ {est_pos}%（实际以你账户为准）|")
        A(f"| 触发离场 | {'⚠️' if n_exit >= 1 else '✅'} | {n_exit} 只触发离场卡 |")
        if n_exit >= 2:
            A(f"\n🔴 **组合降仓信号**：{n_exit} 只持仓触发强制离场（≥2），建议总仓位降至≤30%，优先处理离场分最低的标的\n")
        elif n_exit == 1:
            A(f"\n⚠️ **组合预警**：1 只持仓触发离场，关注是否扩散（≥2只=组合降仓）\n")
        else:
            A("\n✅ 组合健康：无持仓触发离场卡\n")
    else:
        A("（无持仓数据，跳过组合层风控——通过 --holdings / --holdings-file 传入持仓）\n")

    md = "\n".join(L)
    today = a.date if a.date else datetime.now().strftime("%Y-%m-%d")
    os.makedirs("outputs", exist_ok=True)
    out = os.path.join("outputs", f"股池标的跟踪报告_{today}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {out} ({len(md)} chars)")

    # 信号日志累积（胜率跟踪数据源）
    append_signal_log(results, fin)

    # PushPlus推送
    if a.push:
        token = os.environ.get("PUSH_TOKEN", "")
        if token:
            push_pushplus(token, f"📊 {title} {today}", out)
            # 持仓离场预警：持仓标的离场分≤-2时单独推送（醒目提醒）
            alerts = []
            for r in results:
                if not r["ok"] or r["code"] not in holdings:
                    continue
                g = r.get("guard")
                if g and g.get("ok") and g.get("exit_score", 0) <= -2:
                    alerts.append(r)
            if alerts:
                lines = [f"### 🔴 持仓离场预警 {today}", "",
                         f"> 以下持仓触发离场计分卡（≤-2 强制离场），请及时处理：", ""]
                for r in alerts:
                    g = r["guard"]
                    reasons = "、".join(g.get("exit_reasons", [])[:3]) or "—"
                    lines.append(f"**{r['name']}（{r['code']}）**：离场分 **{g['exit_score']}** → {g['exit_action']}")
                    lines.append(f"- 月线：{r['mf']['trend']} | ATR止损：{g.get('stop')} | 盈亏比：{g.get('rr')}")
                    lines.append(f"- 原因：{reasons}")
                    lines.append("")
                push_pushplus(token, f"🔴 持仓离场预警 {today}", content="\n".join(lines))
            # 组合降仓信号：≥2只持仓触发离场 → 独立推送（B2组合层风控）
            if len(alerts) >= 2:
                combo = [f"**{r['name']}（{r['code']}）** 离场分 {r['guard'].get('exit_score', 0)}" for r in alerts]
                push_pushplus(token, f"🔴🔴 组合降仓信号 {today}", content=(
                    f"### 组合层风控：{len(alerts)} 只持仓触发强制离场（≥2阈值）\n\n"
                    + "\n".join(combo)
                    + "\n\n建议：总仓位降至≤30%，优先处理离场分最低标的"))
        else:
            print("[push] 跳过（PUSH_TOKEN未设置）")
    print(md[:600])

if __name__ == "__main__":
    main()
