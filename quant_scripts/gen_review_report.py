#!/usr/bin/env python3
"""
gen_review_report.py —— 复盘报告生成器 v2.0
由全盘量化扫描 workflow 末尾自动触发

输入：全盘量化报告 + 盘前市场报告（今日）+ 盘后量化原始数据
输出：复盘报告_YYYY-MM-DD.md → 上传复盘报告文件夹 + 推送

完整闭环：「盘前预判 → 交易时段 → 盘后量化 → 验证 → 明日展望」
"""
import subprocess, json, os, sys, time, re, csv, io, urllib.request, urllib.parse
from datetime import datetime, timedelta

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
KB_ID = os.environ.get("IMA_KB_ID", "")
CLIENT_ID = os.environ.get("IMA_OPENAPI_CLIENTID", "")
API_KEY = os.environ.get("IMA_OPENAPI_APIKEY", "")

def run(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except:
        return ""

def read_local_file(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def parse_kline_table(txt):
    """
    解析westock kline表格，兼容两种格式:
    1. 单股: | date | open | last | ... |  (第一列为日期)
    2. batch: | symbol | date | open | last | ... |  (第二列为日期)
    """
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if header and "---" not in parts[0]:
            # 找出日期所在列索引
            date_idx = header.index("date") if "date" in header else 0
            # 数据行第一列必须是日期或symbol
            if len(parts) >= len(header) and re.match(r"^(\d{4}-\d{2}-\d{2}|[a-z]{2}\d{6})$", parts[0]):
                rows.append({header[i]: parts[i] for i in range(min(len(header), len(parts)))})
    # ⚠️ westock kline输出为降序(最新在前)，统一按date升序排序，保证 rows[-1]=最新
    rows.sort(key=lambda r: r.get("date", ""))
    return rows

def parse_board_table(txt):
    """解析westock hot board输出（数据行第一列为数字index，板块名在name列、涨跌幅在zdf列）"""
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "name" in parts and "zdf" in parts:
            header = parts
            continue
        if header and "---" not in parts[0]:
            if len(parts) >= len(header) and re.match(r"^\d+$", parts[0]):
                rows.append({header[i]: parts[i] for i in range(min(len(header), len(parts)))})
    return rows

def load_premarket_judgment(today):
    """读取盘前报告生成器导出的结构化预判JSON（真实验证数据源）。
    优先当日文件，fallback latest。返回dict或None。"""
    for name in (f"premarket_judgment_{today}.json", "premarket_judgment_latest.json",
                 f"outputs/premarket_judgment_{today}.json", "outputs/premarket_judgment_latest.json"):
        if os.path.exists(name):
            try:
                with open(name, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("date", "").startswith(today[:7]):
                    return d
            except Exception:
                pass
    return None

def read_quant_results(today):
    """读取 run_all_quant.py 生成的量化汇总，提取三系统信号。返回dict或None。
    结构: {date, timestamp, shuangxian:{stdout,pool_file,pool_data}, fishbody:{market_temp,...}, beast:{stdout,...}}
    猛兽安全评分/双弦温度计在stdout文本中，正则提取。"""
    for name in (f"quant_results_{today}.json", "outputs/quant_results_{today}.json".format(today=today),
                 "quant_results_latest.json", "outputs/quant_results_latest.json"):
        if os.path.exists(name):
            try:
                with open(name, "r", encoding="utf-8") as f:
                    d = json.load(f)
                out = {}
                fish = d.get("fish_body") or d.get("fishbody") or {}
                beast = d.get("beast") or {}
                sx = d.get("shuangxian") or {}
                # 鱼身温度
                ft = (fish.get("market_temp") or {})
                if isinstance(ft, dict):
                    ft_v = ft.get("score") or ft.get("temperature") or ft.get("temp")
                else:
                    ft_v = None
                out["🌡️ 鱼身温度"] = f"{ft_v}/100" if ft_v is not None else "—"
                # 猛兽安全评分（stdout文本提取）
                bs = beast.get("safety_score")
                if bs is None:
                    bstd = beast.get("stdout", "")
                    m = re.search(r"安全评分:\s*([\d.]+)/100", bstd)
                    bs = m.group(1) if m else None
                out["🛡️ 猛兽安全评分"] = f"{bs}/100" if bs is not None else "—"
                # 双弦温度/门控（stdout文本提取）
                sstd = sx.get("stdout", "")
                tl = sx.get("temperature") or sx.get("temp")
                if tl is None:
                    m = re.search(r"温度[:计]?\s*([\d.]+)", sstd)
                    tl = m.group(1) if m else None
                gate = sx.get("gate1") or sx.get("gate")
                if gate is None:
                    gate = "关闭" if "AND门.*关闭|门控关闭" in sstd or "关闭" in sstd else None
                sx_sig = sx.get("tone") or sx.get("level") or ""
                out["🧭 双弦"] = "温度{} {}".format(tl if tl is not None else "—",
                                                   "·门控关闭" if gate == "关闭" else "",
                                                   sx_sig).strip()
                if any(v not in ("—", "温度—", "") for v in out.values()):
                    return out
            except Exception:
                pass
    return None

def calc_change(rows):
    if len(rows) >= 2:
        r1, r2 = rows[-1], rows[-2]
        return (float(r1["last"]) - float(r2["last"])) / float(r2["last"]) * 100
    return 0

def estimate_premarket_judgment(idx_rows, today=""):
    """盘前预判验证。
    优先使用盘前生成器导出的结构化预判（真实验证）；
    JSON缺失时退化为「按实际走势推断」，并明确标注⚠️推断。
    """
    judgments = []
    chg = 0
    close = 0
    if idx_rows:
        sh_rows = [r for r in idx_rows if r.get("symbol") == "sh000001"]
        if len(sh_rows) >= 2:
            chg = (float(sh_rows[-1]["last"]) - float(sh_rows[-2]["last"])) / float(sh_rows[-2]["last"]) * 100
            close = float(sh_rows[-1]["last"])
    actual_desc = f"实际走势：{'下跌' if chg < 0 else '上涨' if chg > 1 else '震荡'}" if idx_rows else "⏳ 指数数据暂不可用"

    # ── 真实预判路径：读取盘前生成器导出的结构化JSON ──
    pm = load_premarket_judgment(today) if today else None
    if pm:
        pre_tone = pm.get("tone", "")          # e.g. 偏多·结构性机会
        pre_ops = pm.get("operation", "")      # e.g. 仓位≤50%，可参与不追高
        pre_sectors = pm.get("sectors", "")    # e.g. AI应用/软件主线、半导体低吸
        pre_key = pm.get("key_levels", "")     # e.g. 支撑3800压力3850
        # 大盘方向验证
        if chg < -1:
            res_dir = "❌ 预判错误（市场大跌，盘前偏乐观）"
        elif chg < 0:
            res_dir = "❌ 预判错误（市场下跌，盘前未提示风险）" if ("偏多" in pre_tone or "乐观" in pre_tone) else "✅ 基本正确"
        elif chg < 1:
            res_dir = "⏳ 中性（市场小幅震荡）"
        else:
            res_dir = "✅ 正确（市场上涨）"
        judgments.append({"item": "大盘方向", "pre": pre_tone or "未给出", "actual": f"{close} ({chg:+.2f}%)", "result": res_dir})
        # 操作基调验证
        if pre_ops:
            res_ops = "✅ 防守策略正确" if ("防守" in pre_ops and chg < 0) else \
                      "❌ 偏激进（盘前建议参与但市场大跌）" if ("参与" in pre_ops and chg < -0.5) else \
                      "⏳ 中性"
            judgments.append({"item": "操作基调", "pre": pre_ops, "actual": actual_desc, "result": res_ops})
        # 板块方向验证（对比预判板块 vs 实际领涨）
        try:
            hot = run(["hot", "board", "--limit", "10"])
            hot_rows = parse_board_table(hot) if hot else []
            top_sectors = [r.get("name", "") for r in hot_rows[:3] if r.get("name")]
        except:
            top_sectors = []
        if pre_sectors:
            hit = [s for s in top_sectors if any(k in pre_sectors for k in (s[:2], s[:3]))]
            res_sec = "✅ 板块预判正确" if len(hit) >= 2 else "❌ 板块主线证伪" if top_sectors else "⏳ 板块数据缺失"
            judgments.append({"item": "板块方向", "pre": pre_sectors, "actual": f"实际领涨: {'、'.join(top_sectors) or '数据缺失'}", "result": res_sec})
        # 关键位验证（支撑/压力）
        if pre_key:
            hit_sup = "支撑" in pre_key and close >= 3800
            res_key = "✅ 支撑位判断正确" if hit_sup else "⚠️ 关键位需观察"
            judgments.append({"item": "关键位", "pre": pre_key, "actual": f"收 {close}", "result": res_key})
        return judgments

    # ── fallback：旧推断路径（盘前JSON缺失，明确标注）──
    if idx_rows:
        sh_rows = [r for r in idx_rows if r.get("symbol") == "sh000001"]
        if len(sh_rows) >= 2:
            if chg < -1:
                tone, pre_tone, result = "防守", "防守", "✅ 正确（市场下跌，防守基调匹配）"
            elif chg < 0:
                tone, pre_tone, result = "偏防守", "防守", "✅ 基本正确（市场微跌，防守基调合理）"
            elif chg < 1:
                tone, pre_tone, result = "中性偏防守", "中性/防守", "⏳ 中性（市场小幅震荡，需结合成交量判断）"
            else:
                tone, pre_tone, result = "进攻", "防守/中性", "❌ 偏保守（市场上涨但盘前偏防守，错失机会）"
            judgments.append({
                "item": "大盘方向",
                "pre": "⚠️ 推断预判（盘前JSON缺失）",
                "actual": f"{close} ({chg:+.2f}%)",
                "result": result
            })
    
    # 板块方向验证
    try:
        hot = run(["hot", "board", "--limit", "5"])
        hot_rows = parse_board_table(hot) if hot else []
        top_sectors = [r.get("name", "") for r in hot_rows[:3] if r.get("name")]
    except:
        top_sectors = []
    
    if not judgments:
        actual_desc = "⏳ 指数数据暂不可用"
    judgments.append({
        "item": "操作基调",
        "pre": "⚠️ 推断预判（盘前JSON缺失）",
        "actual": actual_desc,
        "result": "✅ 防守策略正确" if chg < 0 else "⏳ 防守偏保守" if chg > 0 else "✅ 中性无偏差"
    })
    
    sectors_str = "、".join(top_sectors[:3]) if top_sectors else "银行/白酒/电力（盘前预判）"
    judgments.append({
        "item": "板块方向",
        "pre": "⚠️ 推断预判（盘前JSON缺失）",
        "actual": f"领涨板块: {sectors_str}",
        "result": "✅ 防御方向匹配" if any(s in str(top_sectors) for s in ["银行", "酒", "电力"]) else "⏳ 部分偏差"
    })
    
    return judgments


def read_lianghua_report():
    """读取本地生成的全盘量化报告"""
    txt = read_local_file("panhou_lianghua.md")
    if not txt:
        # 尝试 outputs 目录
        today = datetime.now().strftime("%Y-%m-%d")
        fname = f"outputs/全盘量化报告_{today}.md"
        txt = read_local_file(fname)
    if not txt:
        print("[WARN] panhou_lianghua.md not found")
        return {}
    data = {}
    for line in txt.splitlines():
        if re.match(r"^\|\s*(主力主导放量|游资情绪|主力控盘|主力偏强放量|主力惜售|情绪退潮)", line):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 2:
                data[parts[0]] = parts[1]
    return data

def read_lianghua_csv():
    """读取全量CSV中提取主力信号低价股"""
    csv_path = "panhou_lianghua.csv"
    if not os.path.exists(csv_path):
        return []
    stocks = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sig = row.get("sig", "")
            if sig in ("主力主导放量🔥(最强)", "主力偏强放量", "主力控盘"):
                try:
                    price = float(row.get("price", 999))
                except:
                    price = 999
                stocks.append({
                    "code": row["code"], "name": row["name"],
                    "price": price, "sig": sig,
                    "precip": row.get("precip", "0"),
                    "m5": float(row.get("m5", 0)) / 1e8
                })
    stocks.sort(key=lambda s: s["price"])
    return stocks

def read_pool_status(today):
    """读取当日股池跟踪报告（pool_tracking_report.py 产出），提取三阶共振/一阶通过标的"""
    for path in (f"outputs/股池标的跟踪报告_{today}.md", f"股池标的跟踪报告_{today}.md"):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            stars, passes = [], []
            in_star = in_pass = False
            for ln in text.splitlines():
                if "二、三阶共振" in ln:
                    in_star, in_pass = True, False
                    continue
                if "三、信号明细" in ln or "三、二阶共振" in ln:
                    in_star, in_pass = False, True
                    continue
                if "四、否决" in ln or "## 四" in ln:
                    in_star = in_pass = False
                    continue
                s = ln.strip()
                if s.startswith("|") and not s.startswith("|:") and "代码" not in s:
                    if in_star and "三重共振" in s and "当前无" not in s:
                        stars.append(s)
                    elif in_pass and s.count("|") >= 6:
                        passes.append(s)
            return text, stars, passes
        except Exception:
            pass
    return None, [], []

def pool_status_section(today):
    """生成复盘报告中的「股池三阶漏斗状态」章节"""
    text, stars, passes = read_pool_status(today)
    if not text:
        return ""
    L = []
    A = L.append
    A("\n### ③.5 股池三阶漏斗状态（当日）\n")
    if stars:
        A("**★ 三阶共振标的（可执行）**\n")
        A("| 代码 | 名称 | 建议 |")
        A("|:----|:----|:----|")
        for s in stars:
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) >= 4:
                A(f"| {parts[0]} | {parts[1]} | {parts[-2] if len(parts) > 4 else '关注'} |")
    A("**一阶通过 / 信号标的（观察）**\n")
    A("| 代码 | 名称 | 月线状态 |")
    A("|:----|:----|:----|")
    n = 0
    for s in passes:
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 4 and re.match(r"^(sh|sz)\d{6}$", parts[0]):
            A(f"| {parts[0]} | {parts[1]} | {parts[2]} |")
            n += 1
        if n >= 15:
            A(f"| ... | 其余{n if n < len(passes) else len(passes)}只见股池跟踪报告 | — |")
            break
    if not stars and not passes:
        A("> 股池跟踪报告已生成（见全盘量化文件夹），当前无三阶共振/信号标的\n")
    A("\n> 📌 三阶漏斗=月线反转(趋势)→武威G1(低吸)→v2.1质量否决(支撑≥5%+盈利)，详见股池标的跟踪报告\n")
    return "\n".join(L)

def gen_report(today_str):
    today = today_str
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    
    lines = []
    lines.append(f"# 📊 复盘报告（{today}）\n")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("数据源：全盘量化扫描 + 盘前市场报告\n")
    
    # ════════════════════════════════════════
    # 一、大盘全景
    # ════════════════════════════════════════
    lines.append("## 一、大盘全景\n")
    idx = run(["kline", "sh000001,sz399001,sz399006,sh000688", "--period", "day", "--limit", "3"])
    idx_rows = parse_kline_table(idx)
    if idx_rows:
        lines.append("| 指数 | 昨收 | 今收 | 涨跌幅 |")
        lines.append("|---|---|---|---|")
        symbols = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指", "sh000688": "科创50"}
        rendered = 0
        for code, name in symbols.items():
            rows = [r for r in idx_rows if r.get("symbol") == code]
            if len(rows) >= 2:
                r_today, r_yest = rows[-1], rows[-2]
                chg = (float(r_today["last"]) - float(r_yest["last"])) / float(r_yest["last"]) * 100
                emoji = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"
                lines.append(f"| {name} | {r_yest['last']} | {r_today['last']} | {emoji} **{chg:+.2f}%** |")
                rendered += 1
        if rendered == 0:
            # batch查询失败，尝试逐只查询
            for code, name in symbols.items():
                one = run(["kline", code, "--period", "day", "--limit", "3"])
                one_rows = parse_kline_table(one)
                if len(one_rows) >= 2:
                    r_today, r_yest = one_rows[-1], one_rows[-2]
                    chg = (float(r_today["last"]) - float(r_yest["last"])) / float(r_yest["last"]) * 100
                    emoji = "🟢" if chg > 0 else "🔴" if chg < 0 else "⚪"
                    lines.append(f"| {name} | {r_yest['last']} | {r_today['last']} | {emoji} **{chg:+.2f}%** |")
                    rendered += 1
        if rendered == 0:
            lines.append("> ⏳ 指数数据暂不可用（收盘后westock更新延迟），以下为盘后量化分析")
    else:
        lines.append("> ⏳ 指数数据暂不可用（收盘后westock更新延迟），以下为盘后量化分析")
    
    # ════════════════════════════════════════
    # 二、盘前预判验证（新增！闭环核心）
    # ════════════════════════════════════════
    lines.append("\n## 二、盘前预判验证\n")
    lines.append(f"> 验证对象：盘前市场报告_{today} 的预判 vs 今日实际走势\n")
    
    judgments = estimate_premarket_judgment(idx_rows, today)
    if judgments:
        lines.append("| 验证项 | 盘前判断 | 收盘实际 | 结果 |")
        lines.append("|:----|:---------|:--------|:----:|")
        for j in judgments:
            lines.append(f"| {j['item']} | {j['pre']} | {j['actual']} | {j['result']} |")
    else:
        lines.append("⏳ 盘前报告数据不可用，跳过验证\n")
    
    # 简单统计验证准确率
    correct = sum(1 for j in judgments if "✅" in j['result'])
    total = len(judgments)
    if total > 0:
        lines.append(f"\n**盘前预判准确率：{correct}/{total} ({correct/total*100:.0f}%)**\n")
    
    # ════════════════════════════════════════
    # 三、盘后量化分析
    # ════════════════════════════════════════
    lines.append("\n## 三、盘后量化分析\n")
    dist = read_lianghua_report()
    if dist:
        lines.append("| 信号类型 | 数量 | 含义 |")
        lines.append("|:---------|:----:|:-----|")
        sig_meanings = {
            "主力主导放量🔥(最强)": "主力资金主导放量，买入信号最强",
            "主力偏强放量": "主力资金偏强，可关注",
            "主力控盘": "主力控盘度高，趋势延续概率大",
            "主力惜售": "主力锁仓不卖，筹码集中",
            "游资情绪": "游资主导，波动大快进快出",
            "情绪退潮": "市场情绪降温，需谨慎"
        }
        for sig in ["主力主导放量🔥(最强)", "主力偏强放量", "主力控盘", "主力惜售", "游资情绪", "情绪退潮"]:
            if sig in dist:
                meaning = sig_meanings.get(sig, "")
                lines.append(f"| {sig} | {dist[sig]} | {meaning} |")
    
    # ════════════════════════════════════════
    # 四、💰 主力信号专表
    # ════════════════════════════════════════
    lines.append("\n## 四、💰 主力信号专表\n")
    lines.append("> 来源：全量量化扫描 · 按信号强度排序\n")
    stocks = read_lianghua_csv()
    ALL_STOCKS = stocks[:30]  # 全部信号前30只
    cheap = [s for s in stocks if s["price"] < 10]
    if ALL_STOCKS:
        lines.append("\n### 全部信号 TOP30\n")
        lines.append("| # | 代码 | 名称 | 价格 | 信号 | 沉淀率 | 5D主力(亿) |")
        lines.append("|---|------|------|:---:|:-----|:----:|:---------:|")
        sig_emoji = {
            "主力主导放量🔥(最强)": "🔥",
            "主力偏强放量": "🟢",
            "主力控盘": "🔵",
            "主力惜售": "⚪",
            "游资情绪": "🎯",
            "情绪退潮": "🔻"
        }
        for i, s in enumerate(ALL_STOCKS, 1):
            emoji = sig_emoji.get(s["sig"], " ")
            sig_short = s["sig"][:15] + ".." if len(s["sig"]) > 15 else s["sig"]
            lines.append(f"| {i} | {s['code']} | {s['name']} | {s['price']:.2f} | {emoji} {sig_short} | {s['precip']}% | {s['m5']:.2f} |")
    
    if cheap:
        lines.append("\n### 💰 低价精选（≤10元）\n")
        lines.append("| # | 代码 | 名称 | 价格 | 信号 | 沉淀率 | 5D主力(亿) | 关注 |")
        lines.append("|---|------|------|:---:|:-----|:----:|:---------:|:----:|")
        for i, s in enumerate(cheap[:15], 1):
            emoji = sig_emoji.get(s["sig"], " ")
            focus = "⭐" if s["price"] < 5 else "👀"
            lines.append(f"| {i} | {s['code']} | {s['name']} | {s['price']:.2f} | {emoji} {s['sig'][:12]} | {s['precip']}% | {s['m5']:.2f} | {focus} |")
    
    # ════════════════════════════════════════
    # 五、尾盘异动扫描（新增！）
    # ════════════════════════════════════════
    lines.append("\n## 五、尾盘异动\n")
    # 获取今日板块排行（hot board 输出首列为数字index，用 parse_board_table）
    try:
        hot = run(["hot", "board", "--limit", "8"])
        hot_rows = parse_board_table(hot) if hot else []
        if hot_rows:
            lines.append("今日热门板块排行：\n")
            lines.append("| 排名 | 板块 | 涨跌幅 |")
            lines.append("|:---:|:----|:----:|")
            for i, r in enumerate(hot_rows[:8]):
                name = r.get("name", "")
                zdf = r.get("zdf", "")
                try:
                    zf = float(zdf)
                    emoji = "🟢" if zf > 0 else "🔴" if zf < 0 else "⚪"
                except:
                    emoji = ""
                lines.append(f"| {i+1} | {name} | {emoji} {zdf}% |")
        else:
            lines.append("⏳ 板块排行数据暂不可用\n")
    except:
        lines.append("⏳ 板块排行数据暂不可用\n")
    
    # 三系统盘后信号（优先 quant_results_{today}.json 盘后实际运行，fallback 盘前JSON快照）
    sys3 = read_quant_results(today)
    if sys3:
        lines.append("\n### 三系统盘后信号\n")
        lines.append("| 系统 | 信号 |")
        lines.append("|:----|:----|")
        for k, v in sys3.items():
            lines.append(f"| {k} | {v} |")
    else:
        pm3 = load_premarket_judgment(today)
        if pm3 and (pm3.get("fish_temp") or pm3.get("beast_score") or pm3.get("shuangxian")):
            lines.append("\n### 三系统信号快照（盘前）\n")
            lines.append("| 系统 | 信号 |")
            lines.append("|:----|:----|")
            lines.append(f"| 🌡️ 鱼身温度 | {pm3.get('fish_temp') or '—'} |")
            lines.append(f"| 🛡️ 猛兽安全评分 | {pm3.get('beast_score') or '—'} |")
            lines.append(f"| 🧭 双弦 | {pm3.get('shuangxian') or '—'} |")
    
    # 五.5 股池三阶漏斗状态（当日，pool_tracking_report.py 产出）
    lines.append(pool_status_section(today))

    # ════════════════════════════════════════
    # 六、明日展望（新增！闭环收口）
    # ════════════════════════════════════════
    lines.append("\n## 六、明日展望\n")
    
    # 基于今日走势给出明日预判
    if idx_rows:
        sh_rows = [r for r in idx_rows if r.get("symbol") == "sh000001"]
        if len(sh_rows) >= 2:
            chg = (float(sh_rows[-1]["last"]) - float(sh_rows[-2]["last"])) / float(sh_rows[-2]["last"]) * 100
            close = float(sh_rows[-1]["last"])
            
            if chg < -2:
                outlook = "大跌后次日有技术性反弹需求，但在系统性风险未解除前不宜抄底"
                tone = "⚪ 谨慎观望"
            elif chg < -1:
                outlook = "连续下跌但跌幅收窄，关注3800点支撑是否有效"
                tone = "⚪ 谨慎观望"
            elif chg < 0:
                outlook = "弱势震荡格局延续，量能萎缩说明抛压减轻但买盘不足"
                tone = "🟡 防守"
            elif chg < 1:
                outlook = "小幅企稳但反弹力度不足，需要放量确认"
                tone = "🟡 防守"
            elif chg < 2:
                outlook = "反弹良好，关注次日能否放量延续"
                tone = "🟢 偏乐观"
            else:
                outlook = "强势反弹，注意短期获利盘回吐压力"
                tone = "🟢 乐观"
        else:
            outlook = "数据不足，基于现有盘后量化信号给出建议"
            tone = "⚪ 中性"
    else:
        outlook = "数据不足，建议明日参考盘前报告判断"
        tone = "⚪ 中性"
    
    lines.append(f"| 维度 | 判断 |")
    lines.append(f"|:----|:----|")
    lines.append(f"| 操作基调 | {tone} |")
    lines.append(f"| 明日预判 | {outlook} |")
    lines.append(f"| 关注信号 | 鱼身温度、猛兽安全评分、双弦定性 |")

    # 反转数值周线信号池联动（F/D层，≤10元）
    fx_lines = []
    fx_fp = os.path.join("outputs", f"反转数值周线信号_{today_str}.md")
    if os.path.exists(fx_fp):
        try:
            content = open(fx_fp, encoding="utf-8").read()
            # 解析F层/D层表格行: | code | name | date | price | fz | depth | green | div |
            f_sigs, d_sigs = [], []
            cur_level = None
            for ln in content.splitlines():
                if "F层精选" in ln:
                    cur_level = "F"
                elif "D层标准" in ln:
                    cur_level = "D"
                elif cur_level and ln.startswith("| ") and "|:--" not in ln and ln.count("|") >= 7:
                    parts = [p.strip() for p in ln.split("|")[1:-1]]
                    if len(parts) >= 4 and parts[0].startswith(("sh", "sz")):
                        sig_str = f"{parts[1]}({parts[0]})"
                        if cur_level == "F":
                            f_sigs.append(sig_str)
                        elif cur_level == "D":
                            d_sigs.append(sig_str)
            if f_sigs or d_sigs:
                fx_lines.append("| 反转数值周线信号 | "
                                + ("🔴F: " + "、".join(f_sigs[:6]) if f_sigs else "🔴F: 无")
                                + ("；🟡D: " + "、".join(d_sigs[:6]) if d_sigs else "；🟡D: 无") + " |")
                fx_lines.append("| 信号说明 | 周线翻红+回调+超跌+底背离（F重仓/ D标准），持有4周，止损=信号周低点 |")
        except Exception as e:
            print(f"[warn] 反转数值信号解析失败: {e}")
    if fx_lines:
        lines.extend(fx_lines)
    
    lines.append("\n---\n")
    lines.append("⚠️ 本报告基于公开市场数据整理，不构成投资建议。\n")
    
    return "\n".join(lines)

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    md = gen_report(today)
    fname = f"复盘报告_{today}.md"
    os.makedirs("outputs", exist_ok=True)
    with open(f"outputs/{fname}", "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {fname} generated")
    
    # 上传
    for i in 1, 2, 3:
        r = subprocess.run(
            ["python3", "upload_ima.py", "--file", f"outputs/{fname}", "--name", fname],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode == 0:
            print("[OK] uploaded to IMA")
            print(r.stdout[-300:] if r.stdout else "")
            break
        print(f"attempt {i} failed: rc={r.returncode}")
        if r.stdout:
            print("stdout:", r.stdout[-300:])
        if r.stderr:
            print("stderr:", r.stderr[-300:])
        time.sleep(10)
    
    # 输出推送摘要
    print(f"\n=== PUSH SUMMARY ===")
    summary_lines = [l for l in md.split('\n') if l.startswith('|')][:15]
    for l in summary_lines:
        print(l)

if __name__ == "__main__":
    main()
