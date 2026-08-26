#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
top_signal.py —— 市场见顶五维监测（《全球第一炒股笔录》独孤圣手体系·2026-08-26落地）
================================================================================
五维信号（小说原文："五个维度里，如果同时触发三个以上，别犹豫，那基本就是顶部区域"）：

  1. 量的背离     — 指数创新高但成交额萎缩（推动上涨的动力在衰竭，场外资金犹豫）
  2. 龙头崩塌     — 龙头池高位股破位/跌停（龙头的倒下比指数调整更早更准）
  3. 板块轮动散乱 — 热点活不过三天（主流资金找不到合力方向，各自为战）[需多日快照累积]
  4. 利空脱敏化   — 放量下跌日出现（行情末端风吹草动引发恐慌性抛售）
  5. 散户情绪亢奋 — 成交额创近250日天量（牛市来了刷屏、大妈开户）

规则：总分≥3 → 🔴 顶部区域（离场计分卡强制离场档）
      ==2 → 🟡 警戒      <2 → 🟢 正常

数据源：
  · 维度1/4/5：westock kline sh000001（指数日线，amount=成交额，单位元）
  · 维度2    ：龙头池 longtou_pool.txt（GitHub/quant_scripts）+ technical 批量均线
  · 维度3    ：westock board 板块涨幅TOP5 快照跨日对比（outputs/board_top_latest.json）
               数据缺失/未累积时该维度不计分（降级）

用法：
  python3 top_signal.py             # 实时监测，输出 JSON + 报告片段
  python3 top_signal.py --backtest  # 历史回测验证（2021-09 至今，滑动窗口）
  python3 top_signal.py --json      # 只输出 JSON（供 workflow 调用）
"""
import subprocess, sys, os, re, json, time
from datetime import datetime, date

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
BASE = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = os.path.join(BASE, "longtou_pool.txt")
BOARD_SNAP = os.path.join(BASE, "outputs", "board_top_latest.json")
OUT_JSON = os.path.join(BASE, "outputs", "top_signal_latest.json")
OUT_MD = os.path.join(BASE, "outputs", "见顶五维监测_{}.md")

def run(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_kline(txt):
    """解析 westock kline 表格 → 升序 rows[date,open,last,high,low,amount]"""
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
                for key in ("open", "last", "high", "low", "amount"):
                    if key in header:
                        row[key] = float(parts[header.index(key)])
                if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                    rows.append(row)
            except (ValueError, IndexError):
                pass
    rows.sort(key=lambda r: r["date"])
    return rows

def fetch_idx_kline(limit=1200):
    for _ in range(4):
        txt = run(["kline", "sh000001", "--period", "day", "--limit", str(limit)])
        rows = parse_kline(txt)
        if rows:
            return rows
        time.sleep(1.5)
    return []

def drop_intraday(rows):
    """剔除最后一根为今日盘中未收盘数据（防止量能失真）"""
    today = date.today().isoformat()
    if rows and rows[-1]["date"] == today and len(rows) > 1:
        return rows[:-1]
    return rows

def pct(a, b):
    return (a - b) / b * 100 if b else 0.0

# ═══════ 维度1：量的背离 ═══════
def dim1_vol_divergence(rows):
    """指数近10日内创新高(40日)但当日成交额 < 前20日均额×0.9 → 触发
    小说："指数还在创新高，但成交量跟不上了" """
    if len(rows) < 60:
        return False, "数据不足"
    recent = rows[-10:]
    base = rows[-40:-10]
    ref_avg = sum(r["amount"] for r in rows[-20:]) / 20
    new_high_days = []
    for r in recent:
        if r["last"] >= max(x["last"] for x in base) and r["last"] >= max(x["last"] for x in rows[-40:]):
            new_high_days.append(r)
    if not new_high_days:
        return False, "近10日未创40日新高"
    top = max(new_high_days, key=lambda r: r["last"])
    ratio = top["amount"] / ref_avg if ref_avg else 1
    if ratio < 0.9:
        return True, f"创新高日({top['date']})成交额{top['amount']/1e8:.0f}亿 < 前20日均额{ref_avg/1e8:.0f}亿的{ratio*100:.0f}%（动力衰竭）"
    return False, f"创新高日({top['date']})量能{ratio*100:.0f}%未萎缩"

# ═══════ 维度4：利空脱敏化（放量下跌=恐慌抛售）═══════
def dim4_panic_sell(rows):
    """近5日出现跌幅<-1.5%且成交额>前5日均额×1.5 → 触发
    小说："任何一点风吹草动都会引发恐慌性抛售" """
    if len(rows) < 12:
        return False, "数据不足"
    win = rows[-5:]
    for i, r in enumerate(win):
        if i == 0:
            continue
        prev = rows[-(5 + (len(win) - i))]
        if prev is None:
            continue
        chg = pct(r["last"], prev["last"])
        base_avg = sum(x["amount"] for x in rows[-(10 + (len(win) - i)):-(5 + (len(win) - i))]) / 5
        if chg < -1.5 and base_avg > 0 and r["amount"] > base_avg * 1.5:
            return True, f"{r['date']}放量下跌{chg:.1f}% 量{base_avg and r['amount']/base_avg:.1f}倍均量（恐慌抛售）"
    return False, "近5日无放量下跌"

# ═══════ 维度5：散户情绪亢奋（成交额天量）═══════
def dim5_euphoria(rows):
    """当日成交额创近250日新高 → 触发
    小说："当菜市场大妈都在讨论开户入市…最危险的信号"（天量=散户蜂拥的代理）"""
    if len(rows) < 260:
        return False, "数据不足(需250日)"
    latest = rows[-1]
    hist = [r["amount"] for r in rows[-250:]]
    if latest["amount"] >= max(hist):
        return True, f"{latest['date']}成交额{latest['amount']/1e8:.0f}亿创近250日天量（情绪亢奋）"
    rank = sum(1 for a in hist if a <= latest["amount"]) / len(hist) * 100
    if rank >= 99:
        return True, f"{latest['date']}成交额{latest['amount']/1e8:.0f}亿处于近250日{rank:.0f}%分位（接近天量）"
    return False, f"{latest['date']}成交额{latest['amount']/1e8:.0f}亿分位{rank:.0f}%"

# ═══════ 维度2：龙头崩塌 ═══════
def load_pool(fpath):
    if not os.path.exists(fpath):
        return []
    codes = []
    for ln in open(fpath, encoding="utf-8", errors="ignore"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"((?:sh|sz)\d{6})", s)
        if m:
            codes.append(m.group(1))
    # 去重保序
    seen = set()
    out = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

def dim2_dragon_collapse():
    """龙头池高位股破位（收盘<MA10且<MA20 且 乖离MA60>30% 视为高位回落）→ 崩塌比例≥30%触发
    小说："前期高位放量后开板，天地板甚至连续跌停…龙头倒下比指数调整更早更准" """
    codes = load_pool(POOL_FILE)
    if not codes:
        return False, "龙头池缺失", {"pool": 0, "collapsed": 0}
    tech_rows = []
    for i in range(0, len(codes), 20):
        batch = codes[i:i + 20]
        txt = run(["technical", ",".join(batch), "--group", "ma"])
        rows = parse_tech(txt)
        tech_rows.extend(rows)
        time.sleep(0.3)
    collapsed, total, details = [], 0, []
    for r in tech_rows:
        close = r.get("closePrice")
        ma10 = r.get("ma.MA_10")
        ma20 = r.get("ma.MA_20")
        ma60 = r.get("ma.MA_60")
        if None in (close, ma10, ma20):
            continue
        total += 1
        high_pos = (ma60 and close / ma60 > 1.3) if ma60 else True
        if close < ma10 and close < ma20 and high_pos:
            collapsed.append(r.get("code", "?"))
            details.append(f"{r.get('code')} 收盘{close:.2f}<MA10{ma10:.2f}&MA20{ma20:.2f}")
    ratio = len(collapsed) / total * 100 if total else 0
    if ratio >= 30 and len(collapsed) >= 2:
        return True, f"龙头池{total}只中{len(collapsed)}只高位破位({ratio:.0f}%)：{','.join(collapsed[:5])}", {"pool": total, "collapsed": len(collapsed), "ratio": round(ratio, 1)}
    return False, f"龙头池{total}只中{len(collapsed)}只破位({ratio:.0f}%)<30%", {"pool": total, "collapsed": len(collapsed), "ratio": round(ratio, 1)}

def parse_tech(txt):
    """解析 technical 批量输出（含[Batch]包装）"""
    out = []
    for block in txt.split("[Batch]"):
        lines = [l.strip() for l in block.splitlines() if l.strip().startswith("|")]
        if not lines:
            continue
        hdr = None
        for ln in lines:
            if "code" in ln and "---" not in ln:
                hdr = [h.strip() for h in ln.strip("|").split("|")]
                break
        if not hdr:
            continue
        for ln in lines[lines.index("| " + " | ".join(hdr) + " |") + 1:]:
            pass
    # 简化版：直接解析
    rows = []
    for block in txt.split("\n\n"):
        lines = [l.strip() for l in block.splitlines() if l.strip().startswith("|")]
        if not lines:
            continue
        hdr = None
        for ln in lines:
            if "code" in ln and "---" not in ln:
                hdr = [h.strip() for h in ln.strip("|").split("|")]
                break
        if not hdr:
            continue
        for ln in lines:
            if ln.startswith("| ---") or ln == "| " + " | ".join(hdr) + " |":
                continue
            v = [x.strip() for x in ln.strip("|").split("|")]
            if len(v) == len(hdr):
                d = dict(zip(hdr, v))
                row = {"code": d.get("code", "")}
                for k in ("closePrice", "ma.MA_5", "ma.MA_10", "ma.MA_20", "ma.MA_60", "ma.MA_120"):
                    try:
                        row[k] = float(d[k]) if d.get(k) not in (None, "", "-") else None
                    except (ValueError, KeyError):
                        row[k] = None
                rows.append(row)
    return rows

# ═══════ 维度3：板块轮动散乱 ═══════
def get_board_top():
    """westock board 涨幅段 TOP5 板块名；失败返回 None"""
    txt = run(["board"])
    if "执行失败" in txt or not txt.strip():
        return None
    names = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|") or "---" in s:
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        # board 涨幅段列形如 | 排名 | 板块 | 涨跌幅 | ...（以板块名为准，含中文）
        if len(parts) >= 3:
            cand = parts[1] if re.search(r"[\u4e00-\u9fff]", parts[1]) else parts[2]
            if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9·&]+", cand) and not re.search(r"\d\.\d", cand):
                if cand not in names:
                    names.append(cand)
        if len(names) >= 10:
            break
    return names[:10] if names else None

def dim3_rotation():
    """连续2日板块涨幅TOP5重合度<20% → 触发（热点活不过三天=各自为战）
    依赖 outputs/board_top_latest.json 历史快照，首日运行时为待累积状态"""
    if not os.path.exists(BOARD_SNAP):
        return False, "板块快照待累积（需连续运行2日）", {}
    try:
        snap = json.load(open(BOARD_SNAP, encoding="utf-8"))
    except Exception:
        return False, "快照损坏", {}
    prev_date = snap.get("date", "")
    prev_top = snap.get("top5", [])
    cur_top = get_board_top()
    if cur_top is None:
        return False, "板块数据暂不可用", {}
    cur5, prev5 = cur_top[:5], prev_top[:5]
    if not prev5:
        return False, "历史快照无TOP5", {}
    same = len(set(cur5) & set(prev5))
    if same <= 1:
        return True, f"板块TOP5轮换过快（{prev_date}:[{','.join(prev5)}] → 今日:[{','.join(cur5)}] 重合{same}个）", {"prev": prev5, "cur": cur5, "same": same}
    return False, f"板块TOP5重合{same}个，轮动有序", {"prev": prev5, "cur": cur5, "same": same}

def save_board_snap(cur_top):
    if not cur_top:
        return
    os.makedirs(os.path.join(BASE, "outputs"), exist_ok=True)
    json.dump({"date": date.today().isoformat(), "top5": cur_top[:5], "top10": cur_top},
              open(BOARD_SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ═══════ 汇总 ═══════
def compute_signal(rows, use_live=True):
    dims = {}
    dims["1_量的背离"] = dim1_vol_divergence(rows)
    dims["4_恐慌抛售"] = dim4_panic_sell(rows)
    dims["5_情绪亢奋"] = dim5_euphoria(rows)
    dims["2_龙头崩塌"] = dim2_dragon_collapse()
    dims["3_轮动散乱"] = dim3_rotation()
    triggered = [k for k, v in dims.items() if v[0]]
    score = len(triggered)
    if score >= 3:
        level, advice = "🔴 顶部区域", "离场计分卡升级：持仓股强制离场档，禁止开新仓"
    elif score == 2:
        level, advice = "🟡 警戒", "离场计分卡加-1：持仓收紧，新仓降档"
    else:
        level, advice = "🟢 正常", "无顶部信号，正常执行"
    return {
        "date": date.today().isoformat(),
        "score": score,
        "level": level,
        "advice": advice,
        "dims": {k: {"hit": v[0], "detail": v[1], "data": v[2] if len(v) > 2 else {}} for k, v in dims.items()},
        "triggered": triggered,
    }

def render_md(sig):
    today = date.today().isoformat()
    md = f"# 📉 市场见顶五维监测（《全球第一炒股笔录》体系）\n\n"
    md += f"**日期**：{today}  **总分**：**{sig['score']}/5**  **状态**：{sig['level']}\n\n"
    md += f"> {sig['advice']}\n\n---\n\n"
    for k, v in sig["dims"].items():
        mark = "✅" if v["hit"] else "➖"
        md += f"- {mark} **{k}**：{v['detail']}\n"
    md += "\n---\n\n*规则：五维触发≥3 = 顶部区域；2 = 警戒；<2 = 正常。维度2/3数据缺失时不计分。*\n"
    return md

def merge_events(dates_with_detail):
    """将连续多日触发的同一信号合并为事件（如信号持续3天只算1次）"""
    events = []
    for d, detail in dates_with_detail:
        if events and d == events[-1][1]:  # 同日跳过（理论上不出现）
            continue
        if events and close_dates(events[-1][1], d):
            events[-1] = (events[-1][0], d, events[-1][2])  # 延续
        else:
            events.append((d, d, detail))
    return events

def close_dates(d1, d2):
    """d2 是否为 d1 的下一交易日（日期间隔≤4天视为连续）"""
    from datetime import timedelta
    a = datetime.strptime(d1, "%Y-%m-%d")
    b = datetime.strptime(d2, "%Y-%m-%d")
    return 0 < (b - a).days <= 4

def backtest(rows):
    """历史回测：对 2021-08 至今逐日计算 维度1/4/5（2/3维无历史数据源），
    输出三信号事件（连续触发合并），对照关键历史时点。
    ⚠️ 数据窗口限制：westock 指数K线仅约5年（2021-08起），2015-06/2018-01 顶部无法验证"""
    print("\n══════ 历史回测验证（2021-08 至今 · 维度1/4/5，连续信号合并为事件）══════")
    print("⚠️ 数据窗口限制：westock 指数K线仅约5年，2015-06/2018-01 顶部不可验证")
    hits = {"1_量的背离": [], "4_恐慌抛售": [], "5_情绪亢奋": []}
    n = len(rows)
    for i in range(60, n):
        win = rows[:i + 1]
        d1 = dim1_vol_divergence(win)
        d4 = dim4_panic_sell(win)
        d5 = dim5_euphoria(win)
        if d1[0]:
            hits["1_量的背离"].append((win[-1]["date"], d1[1]))
        if d4[0]:
            hits["4_恐慌抛售"].append((win[-1]["date"], d4[1]))
        if d5[0]:
            hits["5_情绪亢奋"].append((win[-1]["date"], d5[1]))
    events = {k: merge_events(v) for k, v in hits.items()}
    for k, evs in events.items():
        print(f"\n{k} 事件 {len(evs)} 个：")
        for s, e, detail in evs:
            tag = f"{s}" if s == e else f"{s}~{e}"
            print(f"  {tag}  {detail}")
    # 关键时点对照（窗口±5交易日，每维最多计1次 → x/3）
    print("\n关键历史时点对照（窗口±5个交易日，每维计1次）:")
    key_dates = ["2021-12-13", "2022-01-04", "2022-04-27", "2022-10-31",
                 "2024-09-18", "2024-10-08", "2025-03-18", "2025-10-24"]
    for kd in key_dates:
        kd_idx = next((j for j, r in enumerate(rows) if r["date"] >= kd), None)
        if kd_idx is None:
            print(f"  {kd}: 超出数据窗口")
            continue
        w = rows[max(0, kd_idx - 5):kd_idx + 6]
        hit_dims = []
        for r in w:
            ri = rows.index(r)
            if dim1_vol_divergence(rows[:ri + 1])[0] and "1" not in hit_dims:
                hit_dims.append("1")
            if dim4_panic_sell(rows[:ri + 1])[0] and "4" not in hit_dims:
                hit_dims.append("4")
            if dim5_euphoria(rows[:ri + 1])[0] and "5" not in hit_dims:
                hit_dims.append("5")
        print(f"  {kd}: {len(hit_dims)}/3 维触发 {'[' + ','.join(hit_dims) + ']' if hit_dims else '（无）'}")
    return events

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"
    rows = fetch_idx_kline(1200)
    if not rows:
        print(json.dumps({"ok": False, "err": "指数K线获取失败"}, ensure_ascii=False))
        sys.exit(1)
    rows = drop_intraday(rows)
    if mode == "--backtest":
        backtest(rows)
        return
    sig = compute_signal(rows)
    os.makedirs(os.path.join(BASE, "outputs"), exist_ok=True)
    json.dump(sig, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = render_md(sig)
    open(OUT_MD.format(date.today().isoformat()), "w", encoding="utf-8").write(md)
    # 保存板块快照（供维度3次日对比）
    cur_top = get_board_top()
    save_board_snap(cur_top)
    if "--json" in sys.argv:
        print(json.dumps(sig, ensure_ascii=False, indent=1))
    else:
        print(md)
        print(f"\nJSON: {OUT_JSON}\nMD: {OUT_MD.format(date.today().isoformat())}")

if __name__ == "__main__":
    main()
