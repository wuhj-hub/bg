#!/usr/bin/env python3
"""
gen_premarket_report.py —— 盘前市场报告生成器
由 GitHub Actions 在交易日 08:00 自动触发

依赖：westock-data-skillhub (npx), upload_ima.py
输出：盘前市场报告_YYYY-MM-DD.md → 上传至盘前报告文件夹
"""

import subprocess, json, time, os, sys, re
from datetime import datetime, timedelta

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
TIMEOUT = 60

def run(args, timeout=TIMEOUT):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception as e:
        return f"ERR:{e}"

def run_curl(url):
    try:
        r = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=20)
        return r.stdout
    except:
        return ""

def load_quant_latest():
    """读取昨日盘后量化汇总（三系统信号），返回dict或None"""
    for name in ("quant_results_latest.json", "outputs/quant_results_latest.json"):
        if os.path.exists(name):
            try:
                with open(name, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
    return None

def build_judgment(idx_rows, sectors, quant):
    """基于三系统+指数+板块生成结构化预判（供复盘报告真实验证）"""
    fish = (quant.get("fish_body") or {}) if quant else {}
    beast = (quant.get("beast") or {}) if quant else {}
    sx = (quant.get("shuangxian") or {}) if quant else {}
    ft = fish.get("market_temp") or {}
    ft_v = ft.get("score") if isinstance(ft, dict) else None
    bs = beast.get("safety_score") if isinstance(beast, dict) else None
    sx_air = sx.get("air_count") if isinstance(sx, dict) else None  # 空头指数数量
    tl = sx.get("temperature") if isinstance(sx, dict) else None

    # 综合决策规则
    bearish = 0
    if sx_air is not None and sx_air >= 5:
        bearish += 1
    if bs is not None and bs < 40:
        bearish += 1
    if ft_v is not None and ft_v < 45:
        bearish += 1
    if bearish >= 2:
        tone = "防守"
        operation = "仓位≤30%，以防守为主，不开新仓"
    elif bearish == 1:
        tone = "中性偏防守"
        operation = "仓位≤40%，轻仓参与，严格止损"
    else:
        tone = "中性偏多·结构性机会"
        operation = "仓位≤50%，可参与但控制仓位"
    # 板块方向：领涨板块前3 + 提示
    sec_names = [r.get("name", "") for r in sectors[:3]]
    sector_hint = "、".join(sec_names) if sec_names else "关注领涨板块持续性"
    # 关键位：用上证近20日高低点粗算
    key_levels = "—"
    try:
        txt = run(["kline", "sh000001", "--period", "day", "--limit", "25"])
        rows = parse_kline_table(txt)
        if len(rows) >= 20:
            highs = [float(r["high"]) for r in rows[-20:] if r.get("high")]
            lows = [float(r["low"]) for r in rows[-20:] if r.get("low")]
            if highs and lows:
                key_levels = f"支撑{min(lows):.0f}、压力{max(highs):.0f}"
    except Exception:
        pass
    return {
        "tone": tone,
        "operation": operation,
        "sectors": sector_hint,
        "key_levels": key_levels,
        "fish_temp": f"{ft_v}/100" if ft_v is not None else "—",
        "beast_score": f"{bs}/100" if bs is not None else "—",
        "shuangxian": (f"空头{sx_air}/8" if sx_air is not None else "—"),
    }


def parse_kline_table(txt):
    """解析westock kline表格，返回列表"""
    rows = []
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if header and "---" not in parts[0] and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            row = {}
            for i, h in enumerate(header):
                if i < len(parts):
                    row[h] = parts[i]
            rows.append(row)
    # ⚠️ westock kline输出为降序(最新在前)，统一按date升序排序，保证 rows[-1]=最新
    rows.sort(key=lambda r: r.get("date", ""))
    return rows

def get_index_data():
    """获取四大指数最新K线"""
    lines = []
    codes = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指", "sh000688": "科创50"}
    
    for code, name in codes.items():
        txt = run(["kline", code, "--period", "day", "--limit", "3"])
        rows = parse_kline_table(txt)
        if len(rows) >= 2:
            d1, d2 = rows[-1], rows[-2]  # 倒数第一和第二（升序）
            change = (float(d1["last"]) - float(d2["last"])) / float(d2["last"]) * 100
            lines.append(f"| {name} | {d1['last']} | {d2['last']} | {change:+.2f}% |")
    return "\n".join(lines)

def get_board_data():
    """获取板块排行"""
    txt = run(["hot", "board", "--limit", "10"])
    lines = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and not s.startswith("|---"):
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 8 and parts[0].isdigit():
                idx, name, zdf = parts[0], parts[6], parts[7]
                lines.append(f"| {idx} | {name} | {zdf} |")
    return "\n".join(lines[:10])

def get_hot_stocks():
    """获取热门股票"""
    txt = run(["hot", "stock"])
    lines = []
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and "us" not in s and "688" not in s and "300" not in s:
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 5 and parts[0].startswith(("sh", "sz")):
                name, zdf = parts[1], parts[2]
                lines.append(f"| {parts[0]} | {name} | {zdf} |")
    return "\n".join(lines[:10])

def get_news():
    """获取隔夜新闻"""
    # 使用新闻API，这里用web search的简化版
    try:
        r = subprocess.run(
            ["curl", "-s", "https://stock.xueqiu.com/v5/stock/batch/quote.json?symbol=SH000001&extend=detail"],
            capture_output=True, text=True, timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        return r.stdout[:200]
    except:
        return ""

def get_index_monthly():
    """获取八大指数月线用于双弦定性"""
    codes = ["sh000001", "sz399106", "sh000016", "sh000300", 
             "sz399101", "sh000688", "sz399006", "sh000905"]
    names = ["上证指数", "深证综指", "上证50", "沪深300",
             "中小综指", "科创50", "创业板指", "中证500"]
    results = {}
    for code, name in zip(codes, names):
        txt = run(["kline", code, "--period", "month", "--limit", "6"])
        rows = parse_kline_table(txt)
        if rows:
            results[name] = rows
    return results

def calc_zengxingzhi():
    """曾星智+双弦双体系市场定性：8大指数月线 → MA60/MA120/半年涨跌/振幅 → 定性表"""
    codes = {"sh000001":"上证指数","sz399106":"深证综指","sh000016":"上证50","sh000300":"沪深300",
             "sz399101":"中小综指","sh000688":"科创50","sz399006":"创业板指","sh000905":"中证500"}
    data = {}
    for code in codes:
        txt = run(["kline", code, "--period", "month", "--limit", "10"])
        for ln in txt.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 6 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[1]) and parts[0] == code:
                try:
                    data.setdefault(code, []).append((parts[1], float(parts[3]), float(parts[4]), float(parts[5])))
                except:
                    pass
    lines = []
    bear = bull = 0
    for code, name in codes.items():
        rows = sorted(data.get(code, []))
        if len(rows) < 6:
            continue
        closes = [r[1] for r in rows]
        ma60 = sum(closes[-3:]) / 3
        ma120 = sum(closes[-6:]) / 6
        cur = closes[-1]
        half_chg = (cur / closes[-7] - 1) * 100 if len(closes) >= 7 else 0
        zx = "看多" if (cur > ma120 and half_chg > 0) else "看空" if (cur < ma120 and half_chg < 0) else "震荡"
        sx = "多头" if (closes[-1] > ma60 and cur > ma60) else "空头" if (closes[-1] < ma60 and cur < ma60) else "纠缠"
        if sx == "空头": bear += 1
        if sx == "多头": bull += 1
        h5 = max(r[2] for r in rows[-5:]); l5 = min(r[3] for r in rows[-5:])
        amp = (h5 - l5) / l5 * 100
        amp_txt = "高波动" if amp > 30 else "中波动" if amp > 15 else "低波动"
        zx_emoji = "🔴看空" if zx == "看空" else "🟡震荡" if zx == "震荡" else "🟢看多"
        lines.append(f"| {name} | {ma60:.0f} | {ma120:.0f} | {cur:.2f} | {half_chg:+.1f}% | {zx_emoji} | {sx} | {amp:.0f}%{amp_txt} |")
    qual = "🐻 熊市结构" if bear >= 6 else "🐂 牛市结构" if bull >= 6 else "🟡 震荡结构"
    return "\n".join(lines), qual, bear, bull

def gen_report(today_str):
    """生成完整盘前报告"""
    today = today_str
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    quant = load_quant_latest()
    
    lines = []
    lines.append(f"# 📊 盘前市场报告 · {today}\n")
    lines.append("布局：本报告采用「外围(输入) → 大盘(势) → 板块(线) → 个股(点)」信号传导链。")
    lines.append(f"数据截止：A股 {yesterday} 收盘；美股 {yesterday} 收盘。")
    lines.append("⚠️ 基于公开数据整理，不构成投资建议。\n")
    
    # ① 外围环境
    lines.append("## ① 外围环境\n")
    lines.append("### 美股三大指数\n")
    us = run(["kline", "usDJI,usIXIC,usINX", "--period", "day", "--limit", "3"])
    rows = parse_kline_table(us)
    if rows:
        lines.append("| 指数 | 最新 | 前日 | 涨跌幅 |")
        lines.append("|---|---|---|---|")
        for r in rows[-2:]:
            lines.append(f"| {r['symbol']} | {r['last']} | ... | ... |")
    
    lines.append("\n### 商品\n")
    oil = run_curl("https://api.exchangerate-api.com/v4/latest/USD")[:100] or "⏳ 数据获取中"
    lines.append(f"- 原油/黄金数据：正在采集\n")
    
    # ② 大盘
    lines.append("## ② 大盘定势\n")
    idx_data = get_index_data()
    if idx_data:
        lines.append("| 指数 | 最新 | 前收 | 涨跌幅 |")
        lines.append("|---|---|---|---|")
        lines.append(idx_data)
    
    # ②.5 三系统信号快照（引用昨日盘后量化）
    lines.append("\n### 三系统信号快照（{0}盘后）\n".format(yesterday))
    fish = (quant.get("fish_body") or {}) if quant else {}
    beast = (quant.get("beast") or {}) if quant else {}
    sx = (quant.get("shuangxian") or {}) if quant else {}
    ft = fish.get("market_temp") or {}
    ft_v = ft.get("score") if isinstance(ft, dict) else None
    bs = beast.get("safety_score") if isinstance(beast, dict) else None
    sx_air = sx.get("air_count") if isinstance(sx, dict) else None
    lines.append("| 系统 | 信号 |")
    lines.append("|:----|:----|")
    lines.append(f"| 🌡️ 鱼身温度 | {ft_v}/100" if ft_v is not None else "| 🌡️ 鱼身温度 | ⏳ 待量化运行 |")
    lines.append(f"| 🛡️ 猛兽安全评分 | {bs}/100" if bs is not None else "| 🛡️ 猛兽安全评分 | ⏳ 待量化运行 |")
    lines.append(f"| 🧭 双弦 | 空头{sx_air}/8" if sx_air is not None else "| 🧭 双弦 | ⏳ 待量化运行 |")
    # 资金行为四态（读昨日全盘量化 panhou_lianghua.md 一.5章节）
    ph = read_fund_phase()
    if ph:
        lines.append(f"| 💰 资金行为 | 抢筹{ph.get('抢筹','—')} / 进场{ph.get('进场','—')} / 控盘{ph.get('控盘','—')}（昨日全市场） |")
    
    # ②.5.1 曾星智+双弦双体系市场定性（8大指数月线）
    zx_table, zx_qual, zx_bear, zx_bull = calc_zengxingzhi()
    if zx_table:
        lines.append("\n### 双弦+曾星智双体系市场定性\n")
        lines.append(f"**双弦体系**（快弦MA20≈1月均/慢弦MA60≈3月均）：空头 {zx_bear}/8、多头 {zx_bull}/8 → {zx_qual}\n")
        lines.append("**曾星智体系**（半年线MA120≈6月均+6个月涨跌）：按「价在MA120上+半年涨>0=看多；价在MA120下+半年跌<0=看空」逐指数判定\n")
        lines.append("| 指数 | MA60(3月) | MA120(6月) | 最新 | 半年涨跌 | 曾星智 | 双弦 | 5月振幅 |")
        lines.append("|:----|:----|:----|:----|:----|:----:|:----:|:----|")
        lines.append(zx_table)
        lines.append("")
    
    # ②.6 综合决策
    idx_rows_all = []
    for code in ["sh000001", "sz399001", "sz399006", "sh000688"]:
        txt = run(["kline", code, "--period", "day", "--limit", "3"])
        idx_rows_all.extend(parse_kline_table(txt))
    board_txt = run(["hot", "board", "--limit", "5"])
    board_rows = []
    for ln in board_txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and not s.startswith("|---"):
            parts = [p.strip() for p in s.strip("|").split("|")]
            # 列序: index|level|symbol|rank|rankdelta|date|stock_type|name|zdf|zxj
            if len(parts) >= 9 and parts[0].isdigit():
                board_rows.append({"name": parts[7], "zdf": parts[8]})
    j = build_judgment(idx_rows_all, board_rows, quant)
    lines.append("\n### 🎯 综合决策\n")
    lines.append(f"- 大盘方向：**{j['tone']}**")
    lines.append(f"- 操作基调：**{j['operation']}**")
    lines.append(f"- 板块方向：{j['sectors']}")
    lines.append(f"- 关键位：{j['key_levels']}")
    # 四因子背离/共振（黑石启发）
    try:
        fa = calc_factor_analysis()
        if fa.get("ma"):
            lines.append(f"- 四因子：{fa.get('ma','')} | {fa.get('mom','')} | {fa.get('emotion','')} | {fa.get('fund','')}")
        for s in fa.get("signals", []):
            lines.append(f"  {s}")
        lines.append("")
    except Exception as e:
        lines.append(f"- 四因子：计算失败({e})\n")
    
    lines.append("\n## ③ 板块排行\n")
    board = get_board_data()
    if board:
        lines.append("| 排名 | 板块 | 涨跌幅 |")
        lines.append("|---|---|---|")
        lines.append(board)
    
    lines.append("\n## ④ 个股定点\n")
    lines.append("⏳ 每日量化数据由15:30全盘量化扫描生成，盘前时段引用昨日数据。\n")
    
    lines.append("\n## ⑤ 策略要点\n")
    lines.append(f"- 操作基调：{j['operation']}")
    lines.append(f"- 关注板块：{j['sectors']}")
    lines.append(f"- 关键位：{j['key_levels']}")
    # 四因子背离/共振（黑石启发）
    try:
        fa = calc_factor_analysis()
        if fa.get("ma"):
            lines.append(f"- 四因子：{fa.get('ma','')} | {fa.get('mom','')} | {fa.get('emotion','')} | {fa.get('fund','')}")
        for s in fa.get("signals", []):
            lines.append(f"  {s}")
        lines.append("")
    except Exception as e:
        lines.append(f"- 四因子：计算失败({e})\n")
    
    lines.append("---\n")
    lines.append("⚠️ 本报告基于公开市场数据整理，不构成投资建议。\n")
    
    return "\n".join(lines), j


def calc_factor_analysis():
    """四因子背离/共振分析（黑石启发：因子背离即机会，共振即趋势）
    均线=上证vs MA5/MA20 | 动量=5日涨幅 | 情绪=情绪退潮占比 | 资金=抢筹+吸筹占比
    """
    import statistics
    out = {"lines": [], "signals": []}
    # 1. 均线+动量（上证25日K线）
    rows = []
    try:
        txt = run(["kline", "sh000001", "--period", "day", "--limit", "25"])
        rows = parse_kline_table(txt)
    except Exception:
        pass
    if len(rows) >= 21:
        closes = [float(r["last"]) for r in rows]
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        cur = closes[-1]
        mom5 = (closes[-1] / closes[-6] - 1) * 100
        out["ma"] = f"上证{cur:.0f} vs MA5({ma5:.0f})/MA20({ma20:.0f})" + ("站上双均线" if cur > ma5 and cur > ma20 else "双均线下方" if cur < ma5 and cur < ma20 else "均线纠缠")
        out["mom"] = f"5日动量{mom5:+.1f}%"
        out["mom_high"] = mom5 > 2
        out["mom_low"] = mom5 < -1
    # 2. 情绪因子（情绪退潮占比）
    retreat = total = 0
    for name in ["panhou_lianghua.md", "outputs/panhou_lianghua.md"]:
        if os.path.exists(name):
            txt = open(name, encoding="utf-8").read()
            for ln in txt.splitlines():
                m = re.match(r"^\|\s*情绪退潮\s*\|\s*(\d+)\s*\|", ln)
                if m:
                    retreat = int(m.group(1))
                m2 = re.match(r"^\|\s*主力主导放量.*?\|\s*(\d+)\s*\|", ln) or re.match(r"^\|\s*游资情绪\s*\|\s*(\d+)\s*\|", ln)
            # 总数近似：退潮+游资+惜售+控盘+偏强+主导（从分布表汇总）
            sigs = re.findall(r"^\|\s*(?:主力主导放量.*?|主力偏强放量|主力控盘|主力惜售|游资情绪|情绪退潮)\s*\|\s*(\d+)\s*\|", txt, re.M)
            total = sum(int(x) for x in sigs) if sigs else 0
            break
    if total > 0:
        retreat_pct = retreat / total * 100
        out["emotion"] = f"情绪退潮占比{retreat_pct:.0f}%（{retreat}/{total}）"
        out["emotion_high"] = retreat_pct < 40  # 退潮少=情绪活跃
        out["emotion_low"] = retreat_pct > 60   # 退潮多=情绪冰点
    # 3. 资金因子（抢筹+吸筹占比）
    ph = read_fund_phase() or {}
    grab = int(ph.get("抢筹", 0)) + int(ph.get("吸筹", 0))
    total_ph = sum(int(ph.get(k, 0)) for k in ["抢筹", "吸筹", "进场", "控盘", "观望"])
    if total_ph > 0:
        grab_pct = grab / total_ph * 100
        out["fund"] = f"资金行为抢筹+吸筹{grab_pct:.0f}%（{grab}/{total_ph}）"
        out["fund_high"] = grab_pct > 20
        out["fund_low"] = grab_pct < 8
    # 4. 背离/共振判定（黑石四组合）
    if out.get("fund_high") and out.get("emotion_low"):
        out["signals"].append("🔵 资金高+情绪低 = **聪明钱逆势布局**（机构在散户恐惧时吸筹）")
    if out.get("fund_low") and out.get("emotion_high"):
        out["signals"].append("🔴 资金低+情绪高 = **散户追高、主力出货**（诱多风险）")
    if out.get("mom_high") and out.get("emotion_low"):
        out["signals"].append("🟡 动量高+情绪低 = **无量空涨**（动能不可持续）")
    if out.get("mom_low") and out.get("fund_high"):
        out["signals"].append("🟢 动量低+资金高 = **底部蓄力**（方向选择在即）")
    if out.get("mom_high") and out.get("emotion_high") and out.get("fund_high"):
        out["signals"].append("✅ 动量+情绪+资金三高 = **多头共振**（趋势加速）")
    return out


def read_fund_phase():
    """读取昨日全盘量化报告的资金行为四态（panhou_lianghua.md 一.5章节）"""
    import glob
    for name in ["panhou_lianghua.md", "outputs/panhou_lianghua.md"]:
        if os.path.exists(name):
            txt = open(name, encoding="utf-8").read()
            ph = {}
            for ln in txt.splitlines():
                m = re.match(r"^\|\s*(抢筹|吸筹|进场|控盘|观望)\s*\|\s*(\d+)\s*\|", ln)
                if m and "资金行为" not in ln:
                    ph[m.group(1)] = m.group(2)
            return ph if ph else None
    return None


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    md, judgment = gen_report(today)
    fname = f"盘前市场报告_{today}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {fname} generated ({len(md)} chars)")
    
    # 导出结构化预判JSON（供复盘报告真实验证读取）
    judgment["date"] = today
    jname = f"premarket_judgment_{today}.json"
    with open(jname, "w", encoding="utf-8") as f:
        json.dump(judgment, f, ensure_ascii=False, indent=2)
    with open("premarket_judgment_latest.json", "w", encoding="utf-8") as f:
        json.dump(judgment, f, ensure_ascii=False, indent=2)
    print(f"[OK] {jname} + latest 导出（预判字段：{judgment['tone']} / {judgment['operation']}）")
    
    # 上传
    upload_ok = False
    for i in 1, 2, 3:
        r = subprocess.run(
            ["python3", "upload_ima.py", "--file", fname, "--name", fname],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode == 0:
            upload_ok = True
            print("[OK] uploaded to IMA knowledge base")
            if r.stdout:
                print(r.stdout[-300:])
            break
        print(f"upload attempt {i} failed: rc={r.returncode}")
        if r.stderr:
            print("stderr:", r.stderr[-300:])
        time.sleep(10)
    
    if upload_ok:
        print("[OK] uploaded to IMA knowledge base")
    else:
        print("[WARN] upload failed, report saved locally")

if __name__ == "__main__":
    main()
