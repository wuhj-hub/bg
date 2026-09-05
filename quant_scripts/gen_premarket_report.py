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


def parse_quant_temps(quant):
    """从 quant_results 解析三系统温度（兼容结构化字段 + stdout 文本，2026-09-02修复）
    返回 (fish_temp, beast_score, sx_temp, sx_air)
      fish: fishbody.market_temp.score|temp
      beast: beast.safety_score 或 stdout '安全评分: X/100'
      sx: shuangxian.temperature 或 stdout '温度: X/100'；air_count
    """
    if not quant:
        return None, None, None, None
    fish = quant.get("fishbody") or quant.get("fish_body") or {}
    beast = quant.get("beast") or {}
    sx = quant.get("shuangxian") or {}
    # 鱼身
    ft_v = None
    ft = fish.get("market_temp") or {}
    if isinstance(ft, dict):
        ft_v = ft.get("score") if ft.get("score") is not None else ft.get("temp")
    # 猛兽
    bs = beast.get("safety_score") if isinstance(beast, dict) else None
    if bs is None:
        m = re.search(r"安全评分[:：]\s*([\d.]+)/100", str(beast.get("stdout", "")))
        if m:
            bs = float(m.group(1))
    # 双弦
    tl = sx.get("temperature") if isinstance(sx, dict) else None
    sx_air = sx.get("air_count") if isinstance(sx, dict) else None
    if tl is None:
        m = re.search(r"温度[:：]\s*(\d+)/100", str(sx.get("stdout", "")))
        if m:
            tl = float(m.group(1))
    return ft_v, bs, tl, sx_air

def build_judgment(idx_rows, sectors, quant):
    """基于三系统+指数+板块生成结构化预判（供复盘报告真实验证）
    A3风格轴硬接线（2026-08-10）：仓位=基准(三系统) + 风格分修正(±10%) + 温度修正(沸点-10%)，clamp 10%~70%"""
    ft_v, bs, tl, sx_air = parse_quant_temps(quant)
    ft_v2 = ft_v
    # 基准仓位（三系统综合）
    bearish = 0
    if sx_air is not None and sx_air >= 5:
        bearish += 1
    if bs is not None and bs < 40:
        bearish += 1
    if ft_v is not None and ft_v < 45:
        bearish += 1
    if bearish >= 2:
        tone, base_pos, note = "防守", 30, "以防守为主，不开新仓"
    elif bearish == 1:
        tone, base_pos, note = "中性偏防守", 40, "轻仓参与，严格止损"
    else:
        tone, base_pos, note = "中性偏多·结构性机会", 50, "可参与但控制仓位"

    # A3 风格分修正（读 market_style_latest.json）：情绪市+10% / 指数市-10%
    ms = read_market_style()
    style_fix = 0
    style_txt = ""
    mode_txt = ""
    if ms:
        try:
            sc = float(ms.get("score", 0))
            style = ms.get("style", "")
            if sc >= 25:      # 🔥情绪市：游资场子，仓位可上修，堆量/G1优先
                style_fix = 10
                style_txt = f"🔥情绪市({sc:+.0f})仓位+10%"
                mode_txt = "·主扫堆量模式/武威G1低吸"
            elif sc <= -25:   # 🏦指数市：机构场子，仓位下修，欧马/乾坤优先
                style_fix = -10
                style_txt = f"🏦指数市({sc:+.0f})仓位-10%"
                mode_txt = "·主扫欧马模式/乾坤金股"
            else:
                style_txt = f"⚖️均衡市({sc:+.0f})仓位不变"
        except (TypeError, ValueError):
            pass
    # 温度修正：鱼身>80 沸点减仓-10%
    temp_fix = 0
    try:
        if ft_v is not None and float(ft_v) > 80:
            temp_fix = -10
            style_txt += "·🔥沸点(温度>80)仓位-10%"
    except (TypeError, ValueError):
        pass
    pos = max(10, min(70, base_pos + style_fix + temp_fix))
    if bearish >= 2:
        pos = min(pos, 30)
    operation = f"仓位≤{pos}%，{note}"
    if style_txt:
        operation += f"（{style_txt}）"
    if mode_txt:
        operation += mode_txt
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
        "style_score": (ms or {}).get("score"),
        "style_name": (ms or {}).get("style"),
        "base_pos": base_pos, "style_fix": style_fix, "temp_fix": temp_fix, "final_pos": pos,
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
        if header and "---" not in parts[0]:
            row = {}
            for i, h in enumerate(header):
                if i < len(parts):
                    row[h] = parts[i]
            # 兼容批量(symbol|date|...)与单股(date|...)两种列序：date 校验按 header 对齐后的值
            if re.match(r"\d{4}-\d{2}-\d{2}", str(row.get("date", ""))):
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
                if "ST" in name.upper() or "退" in name:
                    continue  # 剔除ST/退市（热搜常混入ST股）
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

def get_news_7x24(maxn=10):
    """新浪财经7x24快讯（沙箱/runner均可达）。返回 [{time, text}]，失败返回[]"""
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "12",
                            "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=%d&zhibo_id=152" % maxn,
                            "-H", "User-Agent: Mozilla/5.0"],
                           capture_output=True, text=True, timeout=18)
        d = json.loads(r.stdout)
        items = d.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
        out = []
        for it in items:
            t = re.sub(r"<[^>]+>", "", it.get("rich_text", "")).strip()
            if t:
                out.append({"time": (it.get("create_time") or "")[11:16], "text": t[:80]})
        return out[:maxn]
    except Exception:
        return []


NEWS_SECTOR_MAP = [
    (["英伟达", "NVIDIA", "AI", "算力", "大模型", "服务器", "液冷"], "AI算力/液冷"),
    (["黄金", "金价"], "贵金属/黄金"),
    (["原油", "石油", "OPEC", "油气"], "油气/油服"),
    (["美联储", "加息", "降息", "利率"], "流动性(影响全局)"),
    (["半导体", "芯片", "晶圆"], "半导体/芯片"),
    (["军工", "国防", "导弹", "冲突"], "军工"),
    (["汽车", "新能源车", "特斯拉"], "汽车链"),
    (["机器人", "人形机器人", "具身"], "机器人"),
    (["光伏", "储能", "电池"], "新能源"),
    (["房地产", "地产", "楼市"], "地产链"),
    (["华为", "鸿蒙", "昇腾"], "华为链"),
]


def news_sector_hint(news):
    """新闻关键词 → 板块联动提示（规则化要闻解读）"""
    text_all = " ".join(n["text"] for n in news)
    hit = []
    for kws, sec in NEWS_SECTOR_MAP:
        if any(k.lower() in text_all.lower() for k in kws) and sec not in hit:
            hit.append(sec)
    if not hit:
        return ""
    return "📰 要闻联动：" + "、".join(hit) + "（隔夜消息面提示）"


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
        # 每股取最新2日 → 最新收盘 + 前收(前一交易日last) → 涨跌幅
        by_sym = {}
        for r in rows:
            by_sym.setdefault(r["symbol"], []).append(r)
        name_map = {"usDJI": "道指", "usIXIC": "纳指", "usINX": "标普"}
        lines.append("| 指数 | 收盘 | 前收 | 涨跌幅 |")
        lines.append("|---|---|---|---|")
        for sym in sorted(by_sym.keys()):
            bars = sorted(by_sym[sym], key=lambda x: x.get("date", ""))
            if len(bars) >= 2:
                last, prev = bars[-1]["last"], bars[-2]["last"]
                try:
                    chg = f"{(float(last)/float(prev)-1)*100:+.2f}%"
                except (ValueError, ZeroDivisionError):
                    chg = "—"
            else:
                last, prev, chg = bars[-1]["last"], "—", "—"
            lines.append(f"| {name_map.get(sym, sym)} | {last} | {prev} | {chg} |")

    lines.append("\n### 隔夜要闻（新浪7x24）\n")
    news = get_news_7x24(8)
    if news:
        for n in news:
            lines.append(f"- [{n['time']}] {n['text']}")
        hint = news_sector_hint(news)
        if hint:
            lines.append(f"\n{hint}\n")
        else:
            lines.append("")
    else:
        lines.append("- ⏳ 快讯获取失败\n")

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
    ft_v, bs, tl, sx_air = parse_quant_temps(quant)
    lines.append("| 系统 | 信号 |")
    lines.append("|:----|:----|")
    lines.append(f"| 🌡️ 鱼身温度 | {ft_v}/100" if ft_v is not None else "| 🌡️ 鱼身温度 | ⏳ 待量化运行 |")
    lines.append(f"| 🛡️ 猛兽安全评分 | {bs}/100" if bs is not None else "| 🛡️ 猛兽安全评分 | ⏳ 待量化运行 |")
    lines.append(f"| 🧭 双弦 | 温度{tl}/100·空头{sx_air}/8" if tl is not None else f"| 🧭 双弦 | 空头{sx_air}/8" if sx_air is not None else "| 🧭 双弦 | ⏳ 待量化运行 |")
    # 资金行为四态（读昨日全盘量化 panhou_lianghua.md 一.5章节）
    ph = read_fund_phase()
    if ph:
        lines.append(f"| 💰 资金行为 | 抢筹{ph.get('抢筹','—')} / 进场{ph.get('进场','—')} / 控盘{ph.get('控盘','—')}（昨日全市场） |")
    # 市场宽度指标（黑石marketChangeDist启发：全主板涨跌家数分布）
    mw = read_market_width()
    if mw:
        lines.append(f"| 📊 市场宽度 | 上涨{mw.get('up','—')}/{mw.get('valid','—')}只 · 强势{mw.get('strong','—')} · 涨停{mw.get('limitup','—')} · 跌停{mw.get('limitdown','—')} → 宽度分{mw.get('score','—')} {mw.get('level','')} |")
        cl = mw.get("cost_line") or {}
        if cl:
            lines.append(f"| 💰 200日成本线 | 现价{cl.get('cur','—')} vs 成本{cl.get('cost200','—')}（{cl.get('ratio','—')}%·斜率{cl.get('slope','—')}）→ **{cl.get('zone','')}** |")
    # 年线广度指标（V纪元方法论：站上年线个股占比=中期牛熊结构）
    yl = read_yearline_breadth()
    if yl:
        yl_level = yl.get("level", "")
        yl_icon = {"bull": "🟢", "mixed": "🟡", "bear": "🟠", "deep_bear": "🔴"}.get(yl_level, "")
        yl_label = {"bull": "牛市结构", "mixed": "结构分化", "bear": "熊市结构", "deep_bear": "深度熊市"}.get(yl_level, yl_level)
        lines.append(f"| 📈 年线广度 | 站上年线 **{yl.get('above','—')}/{yl.get('total','—')}**（{yl.get('ratio_pct','—')}%）{yl_icon} {yl_label} |")
    # RSV均相对强度（腰缠万贯144日：启动/持有/离场）
    rsv = read_rsv_strength()
    if rsv:
        n_launch = len(rsv.get("launch", []))
        n_hold = len(rsv.get("hold", []))
        n_exit = len(rsv.get("exit", []))
        rsv_icon = "🟢" if n_launch > 0 else "🟡" if n_hold > 0 else "🔴" if n_exit > 0 else "⚪"
        lines.append(f"| 📊 RSV强度 | 启动{n_launch} / 持有{n_hold} / 离场{n_exit} {rsv_icon} |")
    # 上证月线MACD（Seaborg方法论：死叉临界/已死叉=中期风险信号）
    mm = read_monthly_macd()
    if mm:
        lines.append(f"| 📉 月线MACD | 柱{mm.get('hist','—')}（DIF {mm.get('dif','—')} / DEA {mm.get('dea','—')}）{mm.get('status','')} |")
    # 🔥 热点情绪（hot_emotion：情绪温度+涨停/连板梯队，quant_scan自动产出）
    he = read_hot_emotion()
    if he:
        sc = he.get("score") or {}
        he_date = he.get("date", "")
        he_icon = "🔴" if sc.get("score", 0) >= 70 else "🟠" if sc.get("score", 0) >= 55 else "🟡" if sc.get("score", 0) >= 40 else "🔵"
        lines.append(f"| 🔥 热点情绪 | **{sc.get('score','—')}/100 {sc.get('level','')}** {he_icon} 涨停{he.get('total','—')} · 连板{he.get('lianban_cnt','—')} · 最高{he.get('max_lb','—')}板（{he_date}） |")
    
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
    
    # ②.5.2 市场风格轴（指数市/均衡/情绪市：机构主导 vs 游资主导）
    ms = read_market_style()
    if ms:
        sd = ms.get("score_detail", {})
        det = ms.get("size_style", {})
        lu = ms.get("limitup_structure", {})
        vc = ms.get("volume_structure", {})
        sf = ms.get("sector_fund", {})
        mc = ms.get("mode_cross", {})
        lines.append("\n### 🎛️ 市场风格轴（机构主导 vs 游资主导）\n")
        lines.append(f"- 风格：**{ms.get('icon','')} {ms.get('style','—')}**（风格分 {ms.get('score',0):+d}，数据截止 {ms.get('data_date','—')}）")
        lines.append(f"- 大小盘：沪深300 5日 {det.get('hs300_5d','—')}% vs 中证1000 5日 {det.get('zz1000_5d','—')}%（相对 {det.get('rel_5d','—')}%；正=小盘领涨·情绪 / 负=大盘领涨·机构）")
        lines.append(f"- 涨停结构：涨停 {lu.get('limitup','—')} 家 · 中军涨停(沪深300成分) {lu.get('zhongjun_cnt','—')} 家 · 强势 {lu.get('strong','—')} 家")
        lines.append(f"- 成交结构：{vc.get('vol_shift','—')}（中证1000/沪深300成交比 {vc.get('small_big_ratio_now','—')} vs 5日均 {vc.get('small_big_ratio_5d','—')}）")
        if sf.get("sectors"):
            tags = "、".join(f"{s['name']}{s['tag']}" for s in sf["sectors"][:3])
            lines.append(f"- 板块资金：热点板块定性 {tags}")
        else:
            lines.append(f"- 板块资金：{sf.get('err','无数据')}")
        if mc:
            lines.append(f"- 猛兽双模式：{mc.get('verdict','—')}（主导 **{mc.get('dominant','—')}** · 领先股 {json.dumps(mc.get('leaders',{}), ensure_ascii=False)}）")
        lines.append(f"- 操作映射：{ms.get('advice','')}")
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
    
    # 量价时空四维检查清单（2026-08-12落地，源自OPPO笔记·熊市先看抗跌/量价时空）
    try:
        lines.append("**量价时空四维检查**")
        lines.append(render_ljsk())
        lines.append("")
    except Exception as e:
        lines.append(f"- 量价时空：计算失败({e})")
    lines.append("\n## ③ 板块排行\n")
    board = get_board_data()
    if board:
        lines.append("| 排名 | 板块 | 涨跌幅 |")
        lines.append("|---|---|---|")
        lines.append(board)
    # ③.3 资金维度板块主线（本地复算板块共振：资金/涨幅/量能三维因子）
    hr = read_heshi_resonance()
    if hr:
        grab = hr.get("grab_top", [])[:5]
        entry = hr.get("entry_top", [])[:5]
        res = hr.get("resonance_boards", [])[:8]
        lines.append("")
        lines.append("### ③.3 资金维度板块主线（板块资金三维因子·本地复算）")
        lines.append("")
        if grab:
            lines.append(f"- 🚀 **抢筹TOP**（资金加速流入）：{' / '.join(f'{b["name"]}({b["value"]})' for b in grab)}")
        if entry:
            lines.append(f"- 📥 **进场TOP**（资金开始流入）：{' / '.join(f'{b["name"]}({b["value"]})' for b in entry)}")
        if res:
            lines.append(f"- 🧭 **板块共振**（资金因子≥2+上涨）：{'、'.join(b['name'] for b in res)}")
        # 🎯 主线中军捕获器（黑石启发：共振板块领涨龙头·资金验证）
        zj = hr.get("zhongjun_candidates", [])[:6]
        if zj:
            lines.append(f"- 🎯 **主线中军**（共振板块领涨龙头·5日主力验证）：{' / '.join(z['stock'] + '(' + z['board'] + '·5日' + str(z['main5']) + '亿)' for z in zj)}")
        lines.append("")
        lines.append(f"> 说明：{hr.get('source', '本地复算')}；因子=主力5日净流入/散户流出/量能/沉淀率，缺失时自动降级为仅涨跌幅排行")
    
    # ③.4 宁静卡位链观察（Serenity题材质地裁决：多卡位链池，缺数据静默跳过）
    try:
        _ai = render_ai_chokepoint()
        if _ai:
            lines.append(_ai)
    except Exception as e:
        lines.append(f"- 宁静卡位观察：读取失败({e})")
    
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


def read_heshi_resonance():
    """读板块共振JSON（本地复算优先，黑石外部版降级），失败返回None"""
    import json as _json
    for p in ("outputs/板块共振_latest.json", "板块共振_latest.json", "../outputs/板块共振_latest.json",
              "outputs/黑石板块共振_latest.json", "../outputs/黑石板块共振_latest.json",
              "/sandbox/workspace/github_bg/outputs/板块共振_latest.json"):
        try:
            return _json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_market_width():
    """读市场宽度指标（market_width_latest.json），失败返回None"""
    for p in ("market_width_latest.json", "outputs/market_width_latest.json", "../outputs/market_width_latest.json",
              "/sandbox/workspace/github_bg/outputs/market_width_latest.json"):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_ai_chokepoint_watch():
    """读宁静AI卡位观察清单（ai_chokepoint_watch_latest.json，盘后流水线产出），失败返回None"""
    for p in ("ai_chokepoint_watch_latest.json", "outputs/ai_chokepoint_watch_latest.json",
              "../outputs/ai_chokepoint_watch_latest.json",
              "/sandbox/workspace/github_bg/ai_chokepoint_watch_latest.json",
              "/sandbox/workspace/github_bg/outputs/ai_chokepoint_watch_latest.json"):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_yearline_breadth():
    """读年线广度指标（yearline_breadth_latest.json，V纪元方法论），失败返回None"""
    for p in ("yearline_breadth_latest.json", "outputs/yearline_breadth_latest.json", "../outputs/yearline_breadth_latest.json",
              "/sandbox/workspace/github_bg/outputs/yearline_breadth_latest.json",
              "/sandbox/workspace/yearline/outputs/yearline_breadth_latest.json"):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_rsv_strength():
    """读RSV均相对强度（rsv_strength_latest.json，腰缠万贯144日），失败返回None"""
    for p in ("rsv_strength_latest.json", "outputs/rsv_strength_latest.json", "../outputs/rsv_strength_latest.json",
              "/sandbox/workspace/github_bg/outputs/rsv_strength_latest.json"):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_monthly_macd():
    """读上证月线MACD监控（monthly_macd_latest.json，Seaborg方法论），失败返回None"""
    for p in ("monthly_macd_latest.json", "outputs/monthly_macd_latest.json", "../outputs/monthly_macd_latest.json",
              "/sandbox/workspace/github_bg/outputs/monthly_macd_latest.json"):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_hot_emotion():
    """读热点情绪温度（hot_emotion_latest.json，连板梯队+情绪温度+退潮预警），失败返回None"""
    for p in ("hot_emotion_latest.json", "outputs/hot_emotion_latest.json", "../outputs/hot_emotion_latest.json",
              "/sandbox/workspace/github_bg/outputs/hot_emotion_latest.json",
              "/sandbox/workspace/skills/盘前市场报告/scripts/outputs/hot_emotion_latest.json"):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def render_ai_chokepoint():
    """
    ③.4 宁静卡位链观察（Serenity题材质地裁决·多池，缺数据返回None）
    展示: ①卡位分≥80的题材确认候选 ②有信号且有卡位背书的交集 ③relabel警告(bearish前期)
    """
    w = read_ai_chokepoint_watch()
    if not w or not w.get("rows"):
        return None
    rows = w["rows"]
    L = []
    L.append("\n### ③.4 🔗 宁静卡位链观察（题材质地 · 盘后产出）")
    L.append("")
    # ① 卡位≥80
    top = [r for r in rows if (r.get("chokepoint") or 0) >= 80]
    if top:
        L.append("- ⭐ **题材确认候选**（卡位≥80）：" + " / ".join(r["name"] + "(" + str(r["chokepoint"]) + ")" for r in top))
    # ② 有信号×卡位≥70 交集（资金共振+题材质地背书）
    hit = [r for r in rows if (r.get("four_dim_total") or 0) >= 4 and (r.get("chokepoint") or 0) >= 70]
    if hit:
        L.append("- 🎯 **卡位×信号交集**（四维≥4+卡位≥70）：" + " / ".join(r["name"] + "(卡位" + str(r["chokepoint"]) + "·四维" + str(r["four_dim_total"]) + ")" for r in hit))
    # ③ relabel 警告（bearish前期：120日涨幅大=定价过半；阈值≥80%）
    rel = []
    for r in rows:
        c = r.get("chg120")
        if isinstance(c, str) and c.startswith("+"):
            try:
                v = float(c.rstrip("%").lstrip("+"))
            except Exception:
                v = 0
            if v >= 80 and (r.get("chokepoint") or 0) < 78:
                rel.append(r)
    if rel:
        L.append("- ⚠️ **relabel过半·追高警惕**（120日涨幅≥80%+卡位被摊薄）：" + " / ".join(r["name"] + "(" + str(r["chg120"]) + "·卡位" + str(r["chokepoint"]) + ")" for r in rel[:6]))
    # ④ 证据弱标的（证据铁律提示）
    wk = [r for r in rows if r.get("evidence") in ("weak", "none")]
    if wk:
        L.append("- 🔻 **证据待核验**（无强/中证据·若进信号将降级）：" + " / ".join(r["name"] + "(" + str(r["evidence"]) + ")" for r in wk))
    L.append(f"\n> 数据源：ai_chokepoint_watch_{w.get('date', '?')}（池内{len(rows)}只主板卡位链标的(多池)·卡位分=基础分+relabel自动衰减）")
    return "\n".join(L)


def render_ljsk(now=""):
    """量价时空四维检查清单（2026-08-12落地，源自OPPO笔记"量价时空"）
    量=市场宽度/涨停结构；价=现价vs200日成本线；时=上证月线级别；空=板块共振广度"""
    L = []
    ok_n = 0
    # 📊 量：宽度分 + 涨停家数
    mw = read_market_width()
    if mw and mw.get("score") is not None:
        sc, lv, zt = mw["score"], mw.get("level", ""), mw.get("limitup", 0)
        l_ok = sc >= 40 and (zt or 0) >= 20
        ok_n += l_ok
        L.append(f"- 📊 量：宽度{sc}{lv}·涨停{zt}家{'✅' if l_ok else '⚠️'}")
    else:
        L.append("- 📊 量：⚠️数据缺失")
    # 📈 价：现价 vs 200日成本线（cost_line）
    if mw and mw.get("cost_line"):
        cl = mw["cost_line"]
        p_ok = cl.get("ratio", -100) >= 0
        ok_n += p_ok
        L.append(f"- 📈 价：现价{cl.get('cur','?')} vs 成本线{cl.get('cost200','?')}（{cl.get('ratio','?')}% {cl.get('zone','')}）{'✅' if p_ok else '⚠️'}")
    else:
        L.append("- 📈 价：⚠️成本线缺失")
    # 🕐 时：上证月线 MA6/MA12 级别
    try:
        mtxt = run(["kline", "sh000001", "--period", "month", "--limit", "13"])
        mrows = parse_kline_table(mtxt)
        closes = [float(r["last"]) for r in mrows if "last" in r]
        if len(closes) >= 12:
            c = closes[-1]; ma6 = sum(closes[-6:]) / 6; ma12 = sum(closes[-12:]) / 12
            if c > ma6 > ma12:
                shi, t_ok = "月线多头", True
            elif c < ma6 and c < ma12:
                shi, t_ok = "月线空头", False
            else:
                shi, t_ok = "月线纠缠", False
            ok_n += t_ok
            L.append(f"- 🕐 时：上证{shi}（MA6 {ma6:.0f}/MA12 {ma12:.0f}）{'✅' if t_ok else '⚠️'}")
        else:
            L.append("- 🕐 时：⚠️月线数据不足")
    except Exception:
        L.append("- 🕐 时：⚠️计算失败")
    # 🗺️ 空：板块共振广度
    try:
        sr = read_heshi_resonance()
        if sr:
            boards = sr.get("resonance_boards") or []
            zj = sr.get("zhongjun_candidates") or []
            k_ok = len(boards) >= 3
            ok_n += k_ok
            L.append(f"- 🗺️ 空：共振板块{len(boards)}个·中军{len(zj)}只{'✅' if k_ok else '⚠️'}")
        else:
            L.append("- 🗺️ 空：⚠️板块共振数据缺失")
    except Exception:
        L.append("- 🗺️ 空：⚠️计算失败")
    L.append(f"- **量价时空综合：{ok_n}/4 维度达标**")
    return "\n".join(L)


def read_market_style():
    """读市场风格轴（market_style_latest.json），失败返回None"""
    for p in ("market_style_latest.json", "outputs/market_style_latest.json", "../outputs/market_style_latest.json",
              "/sandbox/workspace/github_bg/outputs/market_style_latest.json"):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


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
    # 支持 --date 参数（沙箱时钟比平台慢8小时，必须显式传平台日期，2026-08-12修复）
    today = datetime.now().strftime("%Y-%m-%d")
    if len(sys.argv) > 1:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})$", sys.argv[1])
        if m:
            today = m.group(1)
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
