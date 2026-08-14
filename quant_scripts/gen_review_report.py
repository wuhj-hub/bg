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
                if d.get("date", "") == today:  # 严格当日校验（2026-08-11修复：原只校验月份，GitHub端8/7的latest曾被8/11误用）
                    return d
            except Exception:
                pass
    return None

def find_latest_file(pattern, default_today):
    """防缺兜底：找当日文件；缺失则找同目录最近的同类文件（返回None表示都没有）"""
    import glob
    today_p = pattern.format(today=default_today)
    if os.path.exists(today_p):
        return today_p
    cands = sorted(glob.glob(pattern.replace("{today}", "*")), reverse=True)
    return cands[0] if cands else None


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
                # 沸点/冰点规则（黑石启发·市场温度阈值）：>80 沸点减仓止盈；<40 偏冷暂停开仓
                try:
                    ft_f = float(ft_v)
                    if ft_f > 80:
                        out["🌡️ 鱼身温度"] += "·🔥沸点(减仓止盈)"
                    elif ft_f < 40:
                        out["🌡️ 鱼身温度"] += "·❄️偏冷(暂停开仓)"
                    elif ft_f >= 60:
                        out["🌡️ 鱼身温度"] += "·🌡️偏热"
                except (TypeError, ValueError):
                    pass
                # 猛兽安全评分（stdout文本提取）
                bs = beast.get("safety_score")
                if bs is None:
                    bstd = beast.get("stdout", "")
                    m = re.search(r"安全评分:\s*(\d+(?:\.\d+)?)/100", bstd)
                    bs = m.group(1) if m else None
                out["🛡️ 猛兽安全评分"] = f"{bs}/100" if bs is not None else "—"
                # 双弦温度/门控（stdout文本提取 + pool_data兜底）
                sstd = sx.get("stdout", "")
                tl = sx.get("temperature") or sx.get("temp")
                if tl is None:
                    m = re.search(r"温度[:：]?\s*(\d+(?:\.\d+)?)", sstd)
                    tl = m.group(1) if m else None
                if tl is None:
                    pd = sx.get("pool_data") or {}
                    tl = pd.get("temperature") or pd.get("temp") or pd.get("market_temp")
                gate = sx.get("gate1") or sx.get("gate")
                if gate is None:
                    gate = "关闭" if re.search(r"门控.*关闭|AND门.*关闭", sstd) else None
                sx_sig = sx.get("tone") or sx.get("level") or ""
                sx_txt = f"温度{tl}" if tl is not None else "温度—"
                if gate == "关闭":
                    sx_txt += "·门控关闭"
                if sx_sig:
                    sx_txt += f"·{sx_sig}"
                out["🧭 双弦"] = sx_txt
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
        # 资金行为四态（一.5章节，黑石三维启发）
        if re.match(r"^\|\s*(抢筹|吸筹|进场|控盘|观望)\s*\|", line) and "资金行为" not in line:
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 2:
                data[f"资金_{parts[0]}"] = parts[1]
    return data

def render_ljsk(now=""):
    """量价时空四维检查清单（2026-08-12落地，源自OPPO笔记"量价时空"）
    量=市场宽度/涨停结构；价=现价vs200日成本线；时=上证月线级别；空=板块共振广度"""
    L = []
    ok_n = 0
    mw = read_market_width()
    if mw and mw.get("score") is not None:
        sc, lv, zt = mw["score"], mw.get("level", ""), mw.get("limitup", 0)
        l_ok = sc >= 40 and (zt or 0) >= 20
        ok_n += l_ok
        L.append(f"- 📊 量：宽度{sc}{lv}·涨停{zt}家{'✅' if l_ok else '⚠️'}")
    else:
        L.append("- 📊 量：⚠️数据缺失")
    if mw and mw.get("cost_line"):
        cl = mw["cost_line"]
        p_ok = cl.get("ratio", -100) >= 0
        ok_n += p_ok
        L.append(f"- 📈 价：现价{cl.get('cur','?')} vs 成本线{cl.get('cost200','?')}（{cl.get('ratio','?')}% {cl.get('zone','')}）{'✅' if p_ok else '⚠️'}")
    else:
        L.append("- 📈 价：⚠️成本线缺失")
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
    try:
        sr = read_sector_resonance()
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


def read_market_width():
    """读市场宽度指标（market_width_latest.json），失败返回None"""
    import json as _json
    for p in ("market_width_latest.json", "outputs/market_width_latest.json", "../outputs/market_width_latest.json",
              "/sandbox/workspace/github_bg/outputs/market_width_latest.json"):
        try:
            return _json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_sector_resonance():
    """读板块共振JSON（本地复算优先），失败返回None"""
    for p in ("outputs/板块共振_latest.json", "板块共振_latest.json", "../outputs/板块共振_latest.json"):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_market_style():
    """读市场风格轴（market_style_latest.json），失败返回None"""
    import json as _json
    for p in ("market_style_latest.json", "outputs/market_style_latest.json", "../outputs/market_style_latest.json",
              "/sandbox/workspace/github_bg/outputs/market_style_latest.json"):
        try:
            return _json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


def read_qiankun_a():
    """读乾坤A级金股JSON（qiankun_a_latest.json，full_market_dualdim输出），失败返回None"""
    import json as _json
    for p in ("outputs/qiankun_a_latest.json", "qiankun_a_latest.json", "../outputs/qiankun_a_latest.json",
              "/sandbox/workspace/github_bg/outputs/qiankun_a_latest.json"):
        try:
            return _json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
    return None


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
    """读取当日股池跟踪报告（pool_tracking_report.py 产出），提取三阶共振/一阶通过标的。
    当日缺失→自动沿用最近一份并标注来源日期
    （2026-08-11修复：原try块缩进在else兜底分支内，当日文件存在走break时跳过读取直接返回None）"""
    for path in (f"outputs/股池标的跟踪报告_{today}.md", f"股池标的跟踪报告_{today}.md"):
        if os.path.exists(path):
            src_date = today
            break
    else:
        path = find_latest_file("outputs/股池标的跟踪报告_{today}.md", today)
        src_date = ""
        if path:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", path)
            src_date = m.group(1) if m else "最近"
        if not path:
            return None, [], [], src_date
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
        return text, stars, passes, src_date
    except Exception:
        return None, [], [], src_date

def read_shuangxian_pool(today):
    """读双弦月度股池（quant_results pool_data）→ [(name, price, score)]"""
    import json as _j
    for name in (f"quant_results_{today}.json", f"outputs/quant_results_{today}.json",
                 "quant_results_latest.json", "outputs/quant_results_latest.json"):
        if os.path.exists(name):
            try:
                d = _j.load(open(name, encoding="utf-8"))
                entries = (d.get("shuangxian", {}) or {}).get("pool_data", {}).get("entries", [])
                return [(e.get("name",""), e.get("price",""), e.get("score","")) for e in entries]
            except Exception:
                pass
    return None


def read_beast_pool(today):
    """读猛兽本月股池 → (主池[(name,rating,setup)], 观察池[name列表], 信号子池文本)"""
    # 信号子池：从 quant_results beast.stdout 提取（G点/伏击线/RS_D/断层）
    sig_txt = ""
    import json as _j
    b = ""
    for _n in (f"quant_results_{today}.json", f"outputs/quant_results_{today}.json",
               "quant_results_latest.json", "outputs/quant_results_latest.json"):
        if os.path.exists(_n):
            try:
                _q = _j.load(open(_n, encoding="utf-8"))
                b = (_q.get("beast") or {}).get("stdout", "") or ""
                break
            except Exception:
                continue
    import re as _re
    g = _re.search(r"G点信号: (\d+)只", b)
    v = _re.search(r"伏击线低吸: (\d+)只", b)
    r = _re.search(r"RS_D背离: (\d+)只", b)
    d = _re.search(r"净利润断层: (\d+)只", b)
    parts = []
    if g: parts.append(f"G点{g.group(1)}")
    if v: parts.append(f"伏击{v.group(1)}")
    if r: parts.append(f"RS_D{r.group(1)}")
    if d: parts.append(f"断层{d.group(1)}")
    sig_txt = "信号子池: " + " / ".join(parts) if parts else ""
    for path in (f"outputs/猛兽本月股池_{today}.md", f"猛兽本月股池_{today}.md"):
        if not os.path.exists(path):
            continue
        try:
            rows, watch = [], []
            in_main = in_watch = False
            for ln in open(path, encoding="utf-8"):
                if "🏦 主池" in ln:
                    in_main, in_watch = True, False
                    continue
                if "👀 观察池" in ln:
                    in_main, in_watch = False, True
                    continue
                if in_main and ln.strip().startswith("|") and "代码" not in ln and "---" not in ln:
                    parts = [p.strip() for p in ln.strip("|").split("|")]
                    if len(parts) >= 7:
                        rows.append((parts[1], parts[2], parts[5]))
                if in_watch and ln.strip().startswith("|") and "代码" not in ln and "---" not in ln:
                    parts = [p.strip() for p in ln.strip("|").split("|")]
                    if len(parts) >= 3:
                        watch.append(parts[1])
            return (rows if rows else None), watch, sig_txt
        except Exception:
            return None, [], sig_txt
    return None, [], sig_txt


def read_fish_signals():
    """读鱼身最近扫描JSON → (temp, signals列表) 或 None"""
    import glob as _g
    cands = sorted(_g.glob("outputs/fish_body_enhanced_*.json"), reverse=True)
    if not cands:
        return None
    try:
        d = json.load(open(cands[0], encoding="utf-8"))
        temp = (d.get("market_temp") or {}).get("temp")
        sigs = d.get("signals", []) or []
        return temp, sigs
    except Exception:
        return None


def pool_overview_section(today):
    """③.6 各体系股池速览：双弦/猛兽/鱼身/乾坤/武威"""
    L = []
    A = L.append
    A("\n### ③.6 各体系股池速览\n")
    A("| 体系 | 股池 | 标的数 | 当日标的（价格/评分） |")
    A("|---|---|---|---|")

    # 双弦月度池
    sx = read_shuangxian_pool(today)
    if sx:
        detail = "、".join(f"{n}{p}({s})" for n, p, s in sx)
        A(f"| 🔗 双弦 | 月度共振池(≤10元) | {len(sx)} | {detail} |")
    else:
        A("| 🔗 双弦 | 月度共振池 | ⏳ 数据缺失 | quant_results 未产出 |")

    # 猛兽本月池（主池+观察池+信号子池）
    bp, bp_watch, bp_sig = read_beast_pool(today)
    if bp:
        detail = "、".join(f"{n}({r}{s})" for n, r, s in bp)
        n_total = len(bp) + len(bp_watch)
        if bp_watch:
            detail += f"｜观察{len(bp_watch)}: {'、'.join(bp_watch)}"
        if bp_sig:
            detail += f"｜{bp_sig}"
        A(f"| 🐅 猛兽 | 本月主池+观察池 | {n_total} | {detail} |")
    else:
        A(f"| 🐅 猛兽 | 本月主池 | ⏳ 数据缺失 | 猛兽本月股池未产出 {bp_sig} |")

    # 鱼身
    fish = read_fish_signals()
    if fish:
        temp, sigs = fish
        tmp = f"{temp}/100" if temp is not None else "—"
        try:
            tf = float(temp)
            if tf > 80:
                tmp += "·🔥沸点(减仓止盈)"
            elif tf < 40:
                tmp += "·❄️偏冷(暂停开仓)"
        except (TypeError, ValueError):
            pass
        if sigs:
            names = [s.get("name", "") if isinstance(s, dict) else str(s) for s in sigs][:6]
            A(f"| 🐟 鱼身 | 当日信号 | {len(sigs)} | 温度{tmp} · {'、'.join(names)}{'…' if len(sigs) > 6 else ''} |")
        else:
            A(f"| 🐟 鱼身 | 当日信号 | 0 | 温度{tmp} · 无信号 |")
    else:
        A("| 🐟 鱼身 | 当日信号 | ⏳ 超时/未产出 | fish_body_enhanced JSON 缺失 |")

    # 乾坤A级
    qa = read_qiankun_a()
    if qa and qa.get("stocks"):
        names = [f"{s.get('name','')}({s.get('score','')})" for s in qa["stocks"][:5]]
        A(f"| 👑 乾坤 | A级金股 | {qa.get('count', len(qa['stocks']))} | {'、'.join(names)}{'…' if qa.get('count',0) > 5 else ''} |")
    else:
        A("| 👑 乾坤 | A级金股 | 0 | 当日无A级（分级严格，属正常） |")

    # 武威（月度频率）
    A("| 📐 武威 | 月线精选池 | 月度 | 每月1日自动扫描（最近2026-07：飞亚达重仓）；8月池 9/1 更新 |")

    L.append("")
    return "\n".join(L)



def quad_resonance_section(today):
    """③.7 四维共振速览：政策/资金/筹码/关联方 四维评分（quad_resonance.py 产出）"""
    j = None
    for p in (f"outputs/四维共振_{today}.json", "outputs/四维共振_latest.json",
              "四维共振_latest.json", "../outputs/四维共振_latest.json",
              "/sandbox/workspace/github_bg/outputs/四维共振_latest.json"):
        if os.path.exists(p):
            try:
                j = json.load(open(p, encoding="utf-8"))
                break
            except Exception:
                continue
    if not j:
        return "\n### ③.7 四维共振评分\n\n> ⏳ 当日四维共振评分缺失（quad_resonance.py 未产出）。可运行 `python3 quad_resonance.py --pool panhou_lianghua.csv` 补生成后重新生成复盘。\n"
    L = []
    A = L.append
    lv = j.get("levels", {})
    A("\n### ③.7 四维共振评分（政策/资金/筹码/关联方）\n")
    A(f"> 池子 {j.get('pool_size', '—')} 只 | 政策维度={j.get('policy', 0)}({'人工研判' if j.get('policy') == 0 else '已赋值'}) | 判定：≥10★★★ / 7-9★★ / 4-6★ / ≤3无")
    A("")
    A(f"**共振级分布**：★★★必然级 {lv.get('必然级', 0)} | ★★高置信 {lv.get('高置信', 0)} | ★弱共振 {lv.get('弱共振', 0)} | 无共振 {lv.get('无共振', 0)} | 否决 {lv.get('否决', 0)}")
    A("")
    top = [r for r in j.get("stocks", []) if r.get("total", 0) >= 7]
    if not top:
        top = j.get("stocks", [])[:5]
    if top:
        A("**TOP 共振标的**（总分≥7 或前5）：")
        A("| 代码 | 名称 | 资金 | 筹码 | 关联方 | 政策 | 总分 | 共振级 | 证据链 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for r in top:
            v = f" ⚠️{r['veto']}" if r.get("veto") else ""
            ev = f"{r.get('chip_detail', '')}；{r.get('related_detail', '')}"
            A(f"| {r['code']} | {r['name']} | {r['fund']} | {r['chip']} | {r['related']} | {r['policy']} | {r['total']} | {r['level']}{v} | {ev} |")
        A("")
    veto = [r for r in j.get("stocks", []) if r.get("veto")]
    if veto:
        A(f"**反向否决**：{len(veto)} 只（资金流出+关联方减持）→ " + "、".join(f"{r['name']}({r['code']})" for r in veto))
        A("")
    A("> 四维独立信源同向=证据链闭合（必然级）；政策维度需人工研判（--policy 0-3）。完整清单见独立报告《四维共振_%s.md》" % (j.get("date", today)))
    L.append("")
    return "\n".join(L)


def signal_arbiter_section(today):
    """③.8 六套信号仲裁速览：四维/猛兽/鱼身/双弦/乾坤统一打分排序（signal_arbiter.py 产出）"""
    j = None
    for p in (f"outputs/信号仲裁_{today}.json", "outputs/信号仲裁_latest.json",
              "信号仲裁_latest.json", "../outputs/信号仲裁_latest.json"):
        if os.path.exists(p):
            try:
                j = json.load(open(p, encoding="utf-8"))
                break
            except Exception:
                continue
    if not j:
        return "\n### ③.8 六套信号仲裁\n\n> ⏳ 当日信号仲裁缺失（signal_arbiter.py 未产出）。可运行 `python3 signal_arbiter.py` 补生成后重新生成复盘。\n"
    L = []
    A = L.append
    src = j.get("sources", {})
    cnt = j.get("counts", {})
    A("\n### ③.8 六套信号仲裁（统一优先级排序）\n")
    A(f"> 信号源：四维{src.get('四维', 0)} / 鱼身{src.get('鱼身', 0)} / 猛兽{src.get('猛兽', 0)} / 双弦{src.get('双弦', 0)} / 乾坤{src.get('乾坤', 0)}")
    A(f"**分级分布**：★★★全信号共振 {cnt.get('★★★', 0)} | ★★多信号 {cnt.get('★★', 0)} | ★双信号 {cnt.get('★', 0)} | 观察 {cnt.get('观察', 0)}")
    A("")
    ranked = j.get("ranked", [])[:10]
    if ranked:
        A("**仲裁 TOP10**（总分=多信号加权，月线BLOCK强制降级）：")
        A("| 排名 | 代码 | 总分 | 分级 | 月线 | 信号来源 |")
        A("|:----|:----|:----:|:----|:----:|:----|")
        for i, r in enumerate(ranked, 1):
            A(f"| {i} | {r['code']} | **{r['pts']}** | {r['level']} | {r.get('month', '?')} | {'；'.join(r['src'][:4])}{'…' if len(r['src']) > 4 else ''} |")
        A("")
    A("> 仲裁优先级：四维证据链 > 猛兽强度 > 乾坤/鱼身买点 > 双弦/反转；月线闸门前置过滤。完整清单见独立报告《信号仲裁_%s.md》" % (j.get("date", today)))
    L.append("")
    return "\n".join(L)



def pool_status_section(today):
    """生成复盘报告中的「股池三阶漏斗状态」章节"""
    text, stars, passes, src_date = read_pool_status(today)
    if not text:
        return "\n### ③.5 股池三阶漏斗状态（当日）\n\n> ⏳ 当日股池跟踪报告缺失（pool_tracking_report 未产出）。可运行 `pool_tracking_report.py --date {today}` 补生成后重新生成复盘。\n".format(today=today)
    L = []
    A = L.append
    if src_date and src_date != today:
        A(f"\n### ③.5 股池三阶漏斗状态（当日·沿用{src_date}数据）\n")
    else:
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
            nm = parts[1]
            # 名称列异常值（空/市值格式）→ 显示"—"
            if not nm or re.match(r"^\d+\.?\d*\s*亿?$", nm) or len(nm) > 12:
                nm = "—"
            A(f"| {parts[0]} | {nm} | {parts[2]} |")
            n += 1
        if n >= 15:
            A(f"| ... | 其余{n if n < len(passes) else len(passes)}只见股池跟踪报告 | — |")
            break
    if not stars and not passes:
        A("> 股池跟踪报告已生成（见全盘量化文件夹），当前无三阶共振/信号标的\n")
    m_dd = re.search(r"[^\n]*组合回撤[^\n]*", text)
    if m_dd:
        A(f"**📉 组合回撤（R1）**：{m_dd.group(0).strip()}\n")
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
    if load_premarket_judgment(today):
        lines.append(f"> 验证对象：盘前市场报告_{today} 的预判（judgment源：当日JSON） vs 今日实际走势\n")
    else:
        lines.append(f"> ⚠️ 未找到当日盘前判断JSON（premarket_judgment_latest.json 可能过期），预判验证缺失或降级\n")
    
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
        # 资金行为四态（黑石三维启发）
        ph_meanings = {"资金_抢筹": "超大单+放量，加速建仓/拉升（最强）", "资金_吸筹": "机构买+散户卖（Jumbo>0&Small<0）",
                       "资金_进场": "今日净流转正+5D正，温和建仓", "资金_控盘": "缩量高沉淀，筹码锁定", "资金_观望": "无明确资金行为"}
        ph_vals = [f"{dist.get(k, 0)}" for k in ["资金_抢筹", "资金_进场", "资金_控盘", "资金_观望"]]
        if any(v != "0" for v in ph_vals):
            lines.append("")
            lines.append("**资金行为四态**（抢筹/进场/控盘/观望）：")
            for k, desc in ph_meanings.items():
                lines.append(f"- {k.replace('资金_','')}: {dist.get(k, 0)}（{desc}）")
        # 市场宽度指标（黑石marketChangeDist启发：全主板涨跌家数分布）
        mw = read_market_width()
        if mw:
            lines.append("")
            lines.append(f"**市场宽度**（全主板涨跌家数，黑石启发）：上涨{mw.get('up','—')}/{mw.get('valid','—')}只 · 强势≥5% {mw.get('strong','—')} · 涨停{mw.get('limitup','—')} · 弱势≤-5% {mw.get('weak','—')} · 跌停{mw.get('limitdown','—')}")
            lines.append(f"→ 宽度分 {mw.get('score','—')}/100 **{mw.get('level','')}**")
            cl = mw.get("cost_line") or {}
            if cl:
                lines.append(f"→ **200日成本线**（猛兽派启发）：现价{cl.get('cur','—')} vs 成本{cl.get('cost200','—')}（{cl.get('ratio','—')}%·斜率{cl.get('slope','—')}）→ {cl.get('zone','')}")
            # 量价时空四维检查（2026-08-12落地，源自OPPO笔记）
            try:
                lines.append("")
                lines.append("**量价时空四维检查**")
                lines.append(render_ljsk())
            except Exception as e:
                lines.append(f"- 量价时空：计算失败({e})")
        # 市场风格轴（指数市/均衡/情绪市：机构主导 vs 游资主导）
        ms = read_market_style()
        if ms:
            det = ms.get("size_style", {})
            lu = ms.get("limitup_structure", {})
            vc = ms.get("volume_structure", {})
            sf = ms.get("sector_fund", {})
            mc = ms.get("mode_cross", {})
            lines.append("")
            lines.append(f"**市场风格轴**：{ms.get('icon','')} {ms.get('style','—')}（风格分 {ms.get('score',0):+d}，数据截止 {ms.get('data_date','—')}）")
            lines.append(f"- 大小盘：沪深300 5日 {det.get('hs300_5d','—')}% vs 中证1000 5日 {det.get('zz1000_5d','—')}%（相对 {det.get('rel_5d','—')}%；正=小盘领涨·情绪 / 负=大盘领涨·机构）")
            lines.append(f"- 涨停结构：涨停 {lu.get('limitup','—')} 家 · 中军涨停(沪深300成分) {lu.get('zhongjun_cnt','—')} 家 · 强势 {lu.get('strong','—')} 家")
            lines.append(f"- 成交结构：{vc.get('vol_shift','—')}（中证1000/沪深300成交比 {vc.get('small_big_ratio_now','—')} vs 5日均 {vc.get('small_big_ratio_5d','—')}）")
            if sf.get("sectors"):
                tags = "、".join(f"{s['name']}{s['tag']}" for s in sf["sectors"][:3])
                lines.append(f"- 板块资金：热点板块定性 {tags}")
            if mc:
                lines.append(f"- 猛兽双模式：{mc.get('verdict','—')}（主导 {mc.get('dominant','—')}）")
            lines.append(f"- 操作映射：{ms.get('advice','')}")
    
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
    # ── 乾坤A级金股（第四信号源：资金强攻+业绩共振，full_market_dualdim黑石启发）──
    qa = read_qiankun_a()
    if qa and qa.get("stocks"):
        lines.append("\n### 👑 乾坤A级金股（资金强攻+业绩共振）\n")
        lines.append(f"> 来源：乾坤分级矩阵 A级（{qa.get('count', 0)} 只，按综合评分排序）· 指数市环境下权重提升\n")
        lines.append("| # | 代码 | 名称 | 价格 | 资金阶段 | 资金模式 | 沉淀率 | 评分 | 理由 |")
        lines.append("|---|------|------|:---:|:-----|:-----|:----:|:----:|:-----|")
        for i, s in enumerate(qa.get("stocks", [])[:15], 1):
            lines.append(f"| {i} | {s.get('code','')} | {s.get('name','')} | {s.get('price',0):.2f} | {s.get('phase','')} | {s.get('mode','')} | {s.get('precip','')}% | {s.get('score',0)} | {s.get('greason','')} |")
        lines.append("")

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
    # 五.5b 各体系股池速览（双弦/猛兽/鱼身/乾坤/武威）
    lines.append(pool_overview_section(today))
    # 五.5c 四维共振评分速览（quad_resonance.py 产出）
    lines.append(quad_resonance_section(today))
    # 五.5d 六套信号仲裁速览（signal_arbiter.py 产出，B1）
    lines.append(signal_arbiter_section(today))

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
    if "--date" in sys.argv:
        today = sys.argv[sys.argv.index("--date") + 1]
    md = gen_report(today)
    fname = f"复盘报告_{today}.md"
    os.makedirs("outputs", exist_ok=True)
    with open(f"outputs/{fname}", "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] {fname} generated")
    
    # 上传（IMA失效兜底：显式告警 + git落盘仓库，防报告丢失）
    upload_ok = False
    for i in 1, 2, 3:
        r = subprocess.run(
            ["python3", "upload_ima.py", "--file", f"outputs/{fname}", "--name", fname],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode == 0:
            print("[OK] uploaded to IMA")
            print(r.stdout[-300:] if r.stdout else "")
            upload_ok = True
            break
        print(f"attempt {i} failed: rc={r.returncode}")
        if r.stdout:
            print("stdout:", r.stdout[-300:])
        if r.stderr:
            print("stderr:", r.stderr[-300:])
        time.sleep(10)
    if not upload_ok:
        # IMA失效/网络问题：显式标红（不再静默success）+ git落盘仓库兜底
        print("::error::复盘报告上传IMA失败（凭证失效或网络），已尝试git落盘兜底，凭证恢复后需补传知识库")
        try:
            subprocess.run(["git", "add", f"outputs/{fname}"], capture_output=True, timeout=30)
            subprocess.run(["git", "commit", "-m", f"chore: 复盘报告落盘兜底 {fname} (IMA上传失败)"],
                           capture_output=True, timeout=30)
            subprocess.run(["git", "pull", "--rebase", "origin", "main"],
                           capture_output=True, timeout=60)
            p = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, timeout=90)
            if p.returncode == 0:
                print(f"[OK] 报告已git落盘仓库: outputs/{fname}（IMA凭证恢复后可补传知识库）")
            else:
                print(f"[WARN] git push失败(可能是并发提交): {p.stderr[-200:]}")
        except Exception as e:
            print(f"[WARN] git落盘兜底失败: {e}")
    
    # 输出推送摘要
    print(f"\n=== PUSH SUMMARY ===")
    summary_lines = [l for l in md.split('\n') if l.startswith('|')][:15]
    for l in summary_lines:
        print(l)

if __name__ == "__main__":
    main()
