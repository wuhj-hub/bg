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
try:
    import emotion_forecast as emo
except Exception:
    emo = None

BJ = timezone(timedelta(hours=8))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
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
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
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
    print(report)
    print(f"\n[OK] 报告: {md_path}\n[OK] 池: /sandbox/workspace/yao_pool.txt")

    # 预警推送（出货/分歧）
    alerts = [r for r in results if r["level"] in ("💥出货", "⚡分歧")]
    if alerts:
        try:
            import urllib.request, urllib.parse
            lines = [f"🐉 妖股预警 {date_str}\n"]
            if emotion_block:
                lines.append(emotion_block.replace("\n", "\n").strip() + "\n")
            for r in alerts[:10]:
                lines.append(f"- {r['code']} {r['name']} {r['price']:.2f} [{r['level']}] {r['alert']}")
            body = urllib.parse.urlencode({"token": os.environ.get("PUSH_TOKEN", ""),
                                           "title": "🐉妖股预警", "content": "\n".join(lines),
                                           "template": "markdown"}).encode()
            if body and os.environ.get("PUSH_TOKEN"):
                urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body), timeout=15)
                print("[push] 预警已推送")
        except Exception as e:
            print(f"[push] 失败: {e}")

if __name__ == "__main__":
    main()
