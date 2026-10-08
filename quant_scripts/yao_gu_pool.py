#!/usr/bin/env python3
"""
yao_gu_pool.py —— 妖股发现与跟踪系统 v1.0
====================================================
发现（每日全主板扫描）:
  ① 启动确认: 近5日有涨停(≥9.7%) OR 3日涨幅>25%
  ② 底部属性: 距60日低点涨幅>30%（低位启动，排除高位接力）
  ③ 低价活跃: 价格<15元 + 近5日最大换手>5%（妖股偏好）

跟踪（存量池每日6维更新）:
  ① 连板高度   ② 资金四层(当日/5/10/20日主力净流)
  ③ 龙虎榜机构  ④ 天量分歧(换手>20日均3倍)
  ⑤ 乖离MA20   ⑥ KDJ_J

分级:
  💥出货 = 当日主力流出>1亿 且(机构卖/天量)
  ⚡分歧 = 天量 且 今日未涨停(开板)
  🔥加速 = 连板 且 资金流入
  📉退潮 = 连板结束 且 缩量下跌

用法: python3 yao_gu_pool.py [--limit N] [--pool-file yao_pool.txt]
输出: outputs/妖股池_{date}.md/json + yao_pool.txt + 预警推送(预警条目)
====================================================
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys as _sys
_sys.path.insert(0, "/sandbox/workspace")
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import emotion_forecast as emo
except Exception:
    emo = None

BJ = timezone(timedelta(hours=8))
import shutil as _shutil
_ws = _shutil.which("westock-data-skillhub")
WESTOCK = [_ws] if _ws else ["npx", "-y", "westock-data-skillhub@1.0.3"]
BATCH = 20
KLIMIT = 90
WORKERS = 4
MAX_PRICE = 15.0       # 低价妖股偏好
START_UP_DAYS = 5      # 启动确认窗口
BASE_RISE = 0.30       # 距60日低点涨幅>30% = 低位启动
ALERT_FLOW = 1.0       # 亿，出货预警阈值

def cli(cmd, timeout=180):
    full = WESTOCK + cmd.split()
    for attempt in range(5):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            out = r.stdout or ""
            if out.strip() and "执行失败" not in out and "SKILL_0" not in out:
                return out
        except Exception:
            pass
        time.sleep(2)
    return ""

def fetch_daily_batch(symbols):
    md = cli(f"kline {','.join(symbols)} --period day --limit {KLIMIT} --fq qfq")
    groups = {}
    has_symbol = "| symbol |" in md
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 9:
            continue
        try:
            if has_symbol:
                if parts[0] in ("symbol", "---"):
                    continue
                sym, d, o, c, h, l, ex = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[8]
            else:
                if not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                    continue
                sym, d, o, c, h, l, ex = symbols[0], parts[0], parts[1], parts[2], parts[3], parts[4], parts[7]
            groups.setdefault(sym, []).append(
                {"date": d, "open": float(o), "close": float(c), "high": float(h),
                 "low": float(l), "turnover": float(ex)})
        except (ValueError, IndexError):
            continue
    for sym in groups:
        groups[sym].sort(key=lambda x: x["date"])
    return groups

def fetch_asfund(symbol):
    out = cli(f"asfund {symbol}")
    for ln in out.splitlines():
        s = ln.strip()
        if not s.startswith("|") or "MainNetFlow" in s:
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 22:
            continue
        try:
            # asfund 列序: 0=code 1=Block 2=BlockTrade 3=Close 4=EndDate 5=Fwd 6=Jumbo
            # 7=Last 8=LhbInfos 9=LhbDetail 10=MainIn 11=Circ 12=IndRank 13=Rank
            # 14=MainNetFlow(当日) 15=MainNetFlow10D 16=MainNetFlow20D 17=MainNetFlow5D 18=OutFlow ...
            main_flow = float(parts[14]) / 1e8
            flow10 = float(parts[15]) / 1e8
            flow20 = float(parts[16]) / 1e8
            flow5 = float(parts[17]) / 1e8
            lhb = parts[8]
            inst_net = None
            # LhbDetail 含机构专用买卖明细（JSON数组）
            detail = parts[9]
            if detail and detail != "-":
                try:
                    inst_buy = inst_sell = 0.0
                    for item in json.loads(detail):
                        if "机构专用" in str(item.get("Name", "")):
                            b = float(item.get("Buy") or 0)
                            s = float(item.get("Sell") or 0)
                            inst_buy += b
                            inst_sell += s
                    if inst_buy or inst_sell:
                        inst_net = round((inst_buy - inst_sell) / 1e8, 2)
                except Exception:
                    pass
            return {"main_flow": main_flow, "f5": flow5, "f10": flow10, "f20": flow20,
                    "lhb": (lhb or "")[:80], "inst_net": inst_net}
        except (ValueError, IndexError):
            continue
    return None

# ============================================================
# 发现
# ============================================================
def detect_start(bars):
    """妖股启动检测 → (是否启动, 启动日, 距低点涨幅)"""
    if len(bars) < 62:
        return None
    n = len(bars)
    closes = [b["close"] for b in bars]
    lows = [b["low"] for b in bars]
    low60 = min(lows[-62:-2])          # 前60日低点（不含最近2日）
    cur = closes[-1]
    rise = (cur - low60) / low60 if low60 > 0 else 0
    # 启动确认：近5日涨停 或 3日涨幅>25%
    has_limit = False
    max_turn = 0
    for i in range(max(1, n - START_UP_DAYS), n):
        if bars[i]["close"] / bars[i - 1]["close"] >= 1.097:
            has_limit = True
        max_turn = max(max_turn, bars[i]["turnover"])
    rise3 = (closes[-1] / closes[-4] - 1) if n >= 4 else 0
    if has_limit or rise3 > 0.25:
        if rise > BASE_RISE and closes[-1] < MAX_PRICE and max_turn > 5:
            return {"start": True, "rise_from_low": round(rise * 100, 1), "limit": has_limit,
                    "rise3": round(rise3 * 100, 1), "max_turn": round(max_turn, 1)}
    return {"start": False, "rise_from_low": round(rise * 100, 1)}

# ============================================================
# 跟踪（6维）
# ============================================================
def track(bars, fund):
    """返回 6 维跟踪数据 + 分级"""
    n = len(bars)
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    turnovers = [b["turnover"] for b in bars]
    cur = closes[-1]
    # ① 连板高度
    boards = 0
    for i in range(n - 1, 0, -1):
        if bars[i]["close"] / bars[i - 1]["close"] >= 1.097:
            boards += 1
        else:
            break
    # ② 资金四层（fund）
    f = fund or {}
    # ④ 天量分歧
    avg_turn = sum(turnovers[-21:-1]) / 20 if len(turnovers) > 21 else 3
    today_turn = turnovers[-1]
    tianliang = today_turn > avg_turn * 3 and today_turn > 10
    # ⑤ 乖离 MA20
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else cur
    bias20 = (cur - ma20) / ma20 * 100
    # ⑥ KDJ_J（简化9日）
    rsv = []
    for i in range(n):
        ll, hh = min(lows[max(0, i - 8):i + 1]), max(highs[max(0, i - 8):i + 1])
        rsv.append((closes[i] - ll) / (hh - ll) * 100 if hh > ll else 50)
    k, d = 50.0, 50.0
    for v in rsv:
        k = (2 / 3) * k + (1 / 3) * v
        d = (2 / 3) * d + (1 / 3) * k
    j = 3 * k - 2 * d
    # 分级
    main_flow = f.get("main_flow", 0)
    inst_net = f.get("inst_net")
    if main_flow < -ALERT_FLOW and (inst_net is not None and inst_net < 0 or tianliang):
        level, alert = "💥出货", f"主力流出{abs(main_flow):.1f}亿" + ("+机构卖" if inst_net is not None else "") + ("+天量" if tianliang else "")
    elif tianliang and boards == 0:
        level, alert = "⚡分歧", f"天量换手{today_turn:.0f}%开板"
    elif boards >= 2 and main_flow > 0:
        level, alert = "🔥加速", f"{boards}连板+资金流入{main_flow:.1f}亿"
    elif boards == 0 and main_flow < 0:
        level, alert = "📉退潮", f"连板结束主力流出{abs(main_flow):.1f}亿"
    else:
        level, alert = "👀观察", ""
    return {"boards": boards, "flow": round(main_flow, 2), "f5": round(f.get("f5", 0), 2),
            "f10": round(f.get("f10", 0), 2), "f20": round(f.get("f20", 0), 2),
            "tianliang": tianliang, "turn": round(today_turn, 1), "bias20": round(bias20, 1),
            "kdj_j": round(j, 1), "level": level, "alert": alert, "price": cur}

# ============================================================
# 概念第一特征校验（曾星智《连板妖股的第一特征》2026-10-07）
# ============================================================
def load_hot_concepts(limit=12):
    """读当日热门概念（涨停概念排行_latest.json，limitup_concept_rank 产出）。读不到返回 ([], "")。"""
    for p in ("/sandbox/workspace/outputs/涨停概念排行_latest.json",
              "/sandbox/workspace/涨停概念排行_latest.json",
              "涨停概念排行_latest.json"):
        try:
            if os.path.exists(p):
                d = json.load(open(p, encoding="utf-8"))
                return (d.get("concept_rank", []) or [])[:limit], d.get("date", "")
        except Exception:
            continue
    return [], ""


def glm_concept_check(results, hot, date_str):
    """判定妖股候选「属不属于最近的热点概念」。
    返回 (markdown 文本, verdict_map{6位代码: (概念, 判定, 理由)})。调用方须 try/except 兜底。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from llm_glm import chat
    hot_lines = []
    for c in (hot or []):
        stocks = "、".join((c.get("stocks") or [])[:3])
        hot_lines.append(f"- {c.get('concept')}（{c.get('grade', '')}，涨停{c.get('n')}家，最高{c.get('maxlb')}板）"
                         + (f"：{stocks}" if stocks else ""))
    cand_lines = [f"- {r['name']}({r['code']}) 连板{r['boards']} 现价{r['price']:.2f} {r['level']}"
                  for r in results[:40]]
    prompt = (
        f"日期 {date_str}，A股短线。当日「热门概念（按涨停家数）」：\n" + "\n".join(hot_lines)
        + "\n\n「妖股候选」（近期低位启动的连板/涨停股）：\n" + "\n".join(cand_lines)
        + "\n\n判断每只候选是否符合短线第一特征：属不属于最近的热点概念。"
        "逐只严格按此格式输出一行（四段用 | 分隔，第一段务必含 6 位股票代码）：\n"
        "名称 代码 | 归属概念 | 判定 | 理由\n"
        "「归属概念」从上面概念里选最贴近的1个，都不沾边写“不属于热点”；"
        "「判定」只能是 ✅属于 或 ⚠️存疑 或 ❌不属于；「理由」一句(≤30字，结合该概念与个股业务的真实关联)。\n"
        "最后另起一行：关注：名称1、名称2…（≤5只，仅取自判定为✅的；若无则写“暂无”）。"
        "只基于给定信息与公开常识，不确定写“信息不足”，不要编造。")
    reply, _ = chat(prompt, max_tokens=1200,
                    system="你是A股短线热点与题材分析师，语言精炼、结论明确，只基于事实，不编造。")
    def _clean(s, pres):
        s = s.strip()
        for p in pres:
            if s.startswith(p):
                s = s[len(p):].strip("：: \u3000").strip()
        return s

    vmap = {}
    name2code = {r["name"]: r["code"][-6:] for r in results if r.get("name")}
    for ln in reply.splitlines():
        if "|" not in ln:
            continue
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 3:
            continue
        m = re.search(r"\d{6}", parts[0])
        c6 = m.group(0) if m else ""
        if not c6:                      # 模型漏写代码 → 回退按名称匹配
            for nm, cd in name2code.items():
                if nm and nm in parts[0]:
                    c6 = cd
                    break
        if not c6:
            continue
        vmap[c6] = (_clean(parts[1] if len(parts) > 1 else "", ["归属概念", "概念"]),
                    _clean(parts[2] if len(parts) > 2 else "", ["判定"]),
                    _clean(parts[3] if len(parts) > 3 else "", ["理由"]))
    return reply.strip(), vmap


def push_daily_summary(results, pool_n, cand_n, date_str, emotion_block=""):
    """B 方案：每日固定推送一条妖股池摘要（分级统计 + 重点关注 + 风险）。
    重点关注=GLM 判定 ✅属于热点者优先，缺失回退 🔥加速。返回是否已推送。"""
    try:
        import urllib.request, urllib.parse
        _order = ["💥出货", "⚡分歧", "🔥加速", "👀观察", "📉退潮"]
        stat = " ".join(f"{lvl}{sum(1 for r in results if r['level'] == lvl)}" for lvl in _order)
        lines = [f"🐉 **妖股池 {date_str}**",
                 f"扫描 {pool_n} 只主板 | 候选 {cand_n} | 分级：{stat}"]
        if emotion_block:
            lines.append(emotion_block.strip())
        focus = [r for r in results if str(r.get("verdict", "")).startswith("✅")]
        if not focus:
            focus = [r for r in results if r["level"] == "🔥加速"]
        if focus:
            lines.append("\n**🎯 重点关注（概念属热点 / 连板加速）**")
            for r in focus[:8]:
                cpt = r.get("concept")
                tag = f"｜{cpt}" if cpt and cpt != "不属于热点" else ""
                lines.append(f"- {r['code']} {r['name']} {r['price']:.2f} 连板{r['boards']} [{r['level']}]{tag}")
        alerts = [r for r in results if r["level"] in ("💥出货", "⚡分歧")]
        if alerts:
            lines.append("\n**⚠️ 出货/分歧（风险）**")
            for r in alerts[:10]:
                lines.append(f"- {r['code']} {r['name']} {r['price']:.2f} [{r['level']}] {r['alert']}")
        if not os.environ.get("PUSH_TOKEN"):
            print("[push] 无 PUSH_TOKEN，跳过推送")
            return False
        body = urllib.parse.urlencode({"token": os.environ["PUSH_TOKEN"],
                                       "title": f"🐉妖股池 {date_str}",
                                       "content": "\n".join(lines), "template": "markdown"}).encode()
        urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body), timeout=15)
        print("[push] 每日摘要已推送")
        return True
    except Exception as e:
        print(f"[push] 失败: {e}")
        return False


# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-glm", action="store_true", dest="no_glm", help="跳过概念第一特征校验")
    ap.add_argument("--no-push", action="store_true", dest="no_push", help="跳过每日摘要推送（复盘路径改用 push_report 推整份）")
    args = ap.parse_args()
    date_str = datetime.now(BJ).strftime("%Y-%m-%d")

    # 情绪状态（颜劼转移矩阵）
    emotion_block = ""
    if emo:
        lu, wd = emo.get_limitup_from_width()
        if lu is None:
            print("[INFO] 计算当日涨停家数（情绪判定）...", flush=True)
            lu = emo.calc_limitup_live()
        ej = emo.judge(lu, date_str) if lu is not None else None
        if ej:
            emotion_block = (f"\n## 🎭 市场情绪（颜劼转移矩阵）\n"
                             f"当日涨停 **{ej['limitup']}** 家 | 状态【{ej['state']}】 | "
                             f"**次日预判: {ej['next']}（{ej['next_prob']}%）**\n"
                             f"> {ej['advice']}\n")

    # 股票池
    pool = []
    with open("/sandbox/workspace/all_mainboard.csv", encoding="utf-8-sig") as f:
        next(f)
        for ln in f:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                code = parts[0].strip()
                if code.startswith(("688", "300", "301")) or "ST" in parts[1].upper() or "退" in parts[1]:
                    continue
                pool.append(("sh" + code if code.startswith("6") else "sz" + code, parts[1].strip()))
    if args.limit:
        pool = pool[:args.limit]
    syms = [c for c, _ in pool]
    print(f"[INFO] {date_str} 妖股扫描: {len(pool)} 只", flush=True)

    # Step1 发现
    print("[INFO] Step1 启动发现...", flush=True)
    bars_map = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for i in range(0, len(syms), BATCH):
            futs[ex.submit(fetch_daily_batch, syms[i:i + BATCH])] = 1
        done = 0
        for f in as_completed(futs):
            for k, v in f.result().items():
                if len(v) > 62:
                    bars_map[k] = v
            done += 1
            if done % 10 == 0:
                print(f"  [进度] {done}/{len(futs)} 批", flush=True)
    cand = []
    for code, name in pool:
        bars = bars_map.get(code)
        if not bars:
            continue
        r = detect_start(bars)
        if r and r["start"]:
            cand.append((code, name, r))
    print(f"[INFO] 妖股候选: {len(cand)} 只", flush=True)

    # Step2 跟踪（asfund 资金四层，串行）
    print(f"[INFO] Step2 资金跟踪（{len(cand)} 只）...", flush=True)
    results = []
    for i, (code, name, det) in enumerate(cand):
        fund = fetch_asfund(code)
        bars = bars_map[code]
        t = track(bars, fund)
        results.append({"code": code, "name": name, "price": t["price"], "start_info": det,
                        "boards": t["boards"], "flow": t["flow"], "f5": t["f5"], "f10": t["f10"],
                        "f20": t["f20"], "turn": t["turn"], "tianliang": t["tianliang"],
                        "bias20": t["bias20"], "kdj_j": t["kdj_j"], "level": t["level"],
                        "alert": t["alert"]})
        if (i + 1) % 5 == 0:
            print(f"  [进度] {i+1}/{len(cand)}", flush=True)
        time.sleep(0.8)

    # 排序：出货/分歧在前
    order = {"💥出货": 0, "⚡分歧": 1, "🔥加速": 2, "👀观察": 3, "📉退潮": 4}
    results.sort(key=lambda r: (order.get(r["level"], 9), -r["flow"]))
    # 实时ST/退市兜底（清单快照可能漏掉后续戴帽股）
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from st_guard import filter_st
        results, _d = filter_st(results)
        if _d:
            print(f"[ST过滤] 剔除 {len(_d)} 只: {[d['name'] for d in _d]}", flush=True)
    except Exception as e:
        print(f"[WARN] st_guard 校验失败: {e}", flush=True)

    # 输出
    os.makedirs("/sandbox/workspace/outputs", exist_ok=True)
    md = [f"# 🐉 妖股发现与跟踪池 {date_str}\n",
          f"**扫描**: {len(pool)} 只主板 | **候选**: {len(cand)} | **分级**: " +
          " ".join(f"{lvl}{sum(1 for r in results if r['level'] == lvl)}" for lvl in order) + "\n"]
    if emotion_block:
        md.insert(1, emotion_block)
    # ── 概念第一特征校验（GLM · 曾星智《连板妖股的第一特征》）──
    concept_md = ""
    if not args.no_glm and results:
        hot, _hotd = load_hot_concepts()
        if hot:
            try:
                ck, vmap = glm_concept_check(results, hot, date_str)
                for r in results:
                    hit = vmap.get(r["code"][-6:])
                    if hit:
                        r["concept"], r["verdict"], r["concept_reason"] = hit
                concept_md = ("\n## 🎯 概念第一特征校验（GLM · 曾星智第一特征）\n\n"
                              "> 判定妖股候选「属不属于最近的热点概念」——文章第一特征：**不属于者应放弃**。\n\n"
                              + ck + "\n\n> 模型 glm-4-flash ｜ 仅作参考、可能有误，请结合实盘判断。\n")
            except Exception as e:
                concept_md = f"\n## 🎯 概念第一特征校验（GLM）\n\n> 跳过（GLM 不可用：{e}）\n"
        else:
            print("[WARN] 未找到 涨停概念排行_latest.json，跳过概念校验", flush=True)
    if concept_md:
        md.append(concept_md)
    for lvl in ("💥出货", "⚡分歧", "🔥加速", "👀观察", "📉退潮"):
        grp = [r for r in results if r["level"] == lvl]
        if not grp:
            continue
        md.append(f"\n## {lvl}（{len(grp)}只）\n")
        md.append("| 代码 | 名称 | 现价 | 连板 | 主力当日 | 5日 | 10日 | 20日 | 换手% | 乖离20 | J值 | 信号 |")
        md.append("|------|------|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|------|")
        for r in grp:
            md.append(f"| {r['code']} | {r['name']} | {r['price']:.2f} | {r['boards']} | {r['flow']:+.2f}亿 | "
                      f"{r['f5']:+.2f} | {r['f10']:+.2f} | {r['f20']:+.2f} | {r['turn']:.0f} | {r['bias20']:+.0f} | "
                      f"{r['kdj_j']:.0f} | {r['alert'] or r['level']} |")
    report = "\n".join(md)
    md_path = f"/sandbox/workspace/outputs/妖股池_{date_str}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)
    json_path = f"/sandbox/workspace/outputs/妖股池_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "candidates": results}, f, ensure_ascii=False, indent=2)
    # 池配置
    with open("/sandbox/workspace/yao_pool.txt", "w", encoding="utf-8") as f:
        f.write(f"# 妖股池 {date_str}\n")
        for r in results:
            f.write(f"{r['code']} # {r['name']}（{r['level']}）\n")
    # ⚠️ 2026-09-15 修复：原只写仓库根，而 workflow 提交的是 quant_scripts/yao_pool.txt
    #    → 提交的一直是旧文件（股池实际自 2026-08-15 起断更）。此处同步一份到脚本目录。
    try:
        import shutil as _sh
        _alt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yao_pool.txt")
        if os.path.abspath(_alt) != os.path.abspath("/sandbox/workspace/yao_pool.txt"):
            _sh.copyfile("/sandbox/workspace/yao_pool.txt", _alt)
            print(f"[OK] 池(同步): {_alt}")
    except Exception as _e:
        print(f"[WARN] 池同步失败: {_e}")
    print(report)
    print(f"\n[OK] 报告: {md_path}\n[OK] 池: /sandbox/workspace/yao_pool.txt")

    # ── 每日摘要推送（B 方案：固定推一条，见 push_daily_summary）──
    #    复盘路径（quant_report 4.9 步）以 --no-push 运行 → 由 push_report 推整份，避免双推
    if not args.no_push:
        push_daily_summary(results, len(pool), len(cand), date_str, emotion_block)

if __name__ == "__main__":
    main()
