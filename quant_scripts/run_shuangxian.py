"""
双弦投资系统 v2.2 - ima版核心运行模块
======================================
基于双弦系统技术文档实现，兼容ima环境(npx westock-data)

依赖: bash, npx, westock-data-skillhub, monthly_pool.py
"""

import subprocess, json, sys, os, re
from datetime import datetime, date
from pathlib import Path
import csv as _csv
from concurrent.futures import ThreadPoolExecutor

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).parent.parent
POOLS_DIR = BASE_DIR / "pools"
SCRIPTS_DIR = BASE_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# 加入脚本路径（月度股池模块/猛兽函数库）——优先同目录 quant_scripts，沙箱 skills 作降级
for _d in (str(BASE_DIR / "quant_scripts"),
           "/sandbox/workspace/skills/双弦投资系统/scripts",
           "/sandbox/workspace/skills/猛兽体系/scripts"):
    if _d not in sys.path:
        sys.path.insert(0, _d)

POOLS_DIR.mkdir(exist_ok=True)
os.chdir(BASE_DIR)

# ============================================================
# 工具函数
# ============================================================
def cli(cmd: str) -> str:
    """执行westock-data CLI并返回输出"""
    full_cmd = f"npx -y westock-data-skillhub@1.0.3 {cmd}"
    try:
        r = subprocess.run(full_cmd, shell=True, capture_output=True,
                           text=True, timeout=120)
        return r.stdout
    except Exception as e:
        return f""

def parse_table(md: str) -> list[dict]:
    """解析Markdown表格为dict列表"""
    lines = [l.strip() for l in md.split('\n') if l.strip()]
    if not lines:
        return []
    header_idx = None
    for i, ln in enumerate(lines):
        if '| ---' in ln or '|:---' in ln:
            header_idx = i - 1
            break
    if header_idx is None or header_idx < 0:
        return []
    headers = [h.strip() for h in lines[header_idx].split('|') if h.strip()]
    data_lines = lines[header_idx + 2:]
    results = []
    for ln in data_lines:
        cols = [c.strip() for c in ln.split('|') if c.strip()]
        if len(cols) >= len(headers):
            row = {}
            for j, h in enumerate(headers):
                row[h] = cols[j] if j < len(cols) else ""
            results.append(row)
    return results

def get_val(row: dict, *keys) -> str:
    """从行数据中安全取值"""
    for k in keys:
        if k in row:
            return row[k]
    return ""


# ============================================================
# 1. 大盘温度计
# ============================================================
def thermometer() -> tuple[int, str]:
    """猛兽v3.0多指数聚合安全评分 (替代原自研温度计)
    来源: 猛兽体系 check_market_safety()
    三指数加权: 上证×0.3 + 中证全指×0.4 + 深证综指×0.3
    """
    try:
        # 动态导入猛兽函数（避免启动时未安装依赖）
        import importlib
        beast = importlib.import_module("beast_screener")
        safety = beast.check_market_safety()
        score = int(safety["score"])
        level = safety["level"]
        return score, level
    except Exception as e:
        # 回退到原简易温度计
        raw = cli("kline sh000001 --period day --limit 10")
        rows = parse_table(raw)
        if len(rows) < 3:
            return 50, "数据不足"
        closes = []
        for r in rows:
            for key in ["last", "最新", "收盘", "最新价", "收盘价"]:
                if key in r and r[key]:
                    try:
                        closes.append(float(r[key]))
                        break
                    except: pass
        if len(closes) < 3:
            return 50, "数据不足"
        latest = closes[0]
        low_10d = min(closes)
        high_10d = max(closes)
        pos = (latest - low_10d) / (high_10d - low_10d) if high_10d != low_10d else 0.5
        base = round(pos * 60) + 20
        base = max(0, min(100, base))
        level = "偏热" if base >= 65 else ("正常" if base >= 50 else ("偏冷" if base >= 40 else "冷区"))
        return base, level


# ============================================================
# 2. 板块资金扫描
# ============================================================
def scan_sectors() -> dict:
    """扫描热门板块前15，返回流入为正的板块列表"""
    raw = cli("hot board --limit 15")
    rows = parse_table(raw)
    inflow_sectors = []
    all_sectors = []
    for r in rows:
        name = get_val(r, "板块名称", "name")
        zdf_str = get_val(r, "涨跌幅", "zdf")
        try:
            zdf = float(zdf_str.replace("%", "").replace("+", ""))
        except:
            zdf = 0
        info = {"name": name, "zdf": zdf}
        all_sectors.append(info)
        if zdf > 0:
            inflow_sectors.append(info)
    return {"all": all_sectors[:15], "inflow": inflow_sectors}


# ============================================================
# 3. 候选股评分
# ============================================================
def norm_code(code):
    """纯数字代码 → sh/sz前缀（panhou池为纯数字）"""
    code = str(code).strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith(("6", "9", "5")):
        return "sh" + code
    return "sz" + code


def load_panhou_pool(path, phases=("抢筹", "吸筹", "进场"), limit=400):
    """从 panhou_lianghua.csv 按资金行为四态过滤候选池（2026-08-22接入）
    phases: 抢筹(加速建仓)/吸筹(机构买散户卖)/进场(温和建仓) —— 与双弦资金弦同源
    剔除：ST/退市；观望/情绪退潮不入池
    """
    pool = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f):
                phase = (row.get("phase") or "").strip()
                if phase not in phases:
                    continue
                code = (row.get("code") or "").strip()
                name = (row.get("name") or "").strip().replace(" ", "")
                if not code or not name:
                    continue
                if "ST" in name.upper() or "退" in name:
                    continue
                pool.append((norm_code(code), name))
                if limit and len(pool) >= limit:
                    break
    except Exception as e:
        print(f"[WARN] panhou池加载失败: {e}", file=sys.stderr)
    return pool


def score_stock(code: str, name: str, sector: str = "",
                sector_zdf: float = 0, index_temp: int = 50) -> dict:
    """对单只股票进行三维评分（猛兽v3.0增强版）
    
    资金维度 0-35: 主力净流入+龙虎榜 (双弦原有)
    技术维度 0-35: VAD趋势+OVS动量+SSV强度 (猛兽替代MACD/RSI)
    趋势维度 0-30: 大盘+板块+猛兽强度共振
    """
    result = {"code": code, "name": name, "price": 0,
              "fund_score": 0, "tech_score": 0, "trend_score": 0,
              "total_score": 0, "resonance": 0}
    
    # 获取资金流向数据
    fund_raw = cli(f"asfund {code}")
    
    # 获取价格 from technical (轻量)
    tech_raw = cli(f"technical {code} --group all")
    price = 0
    for row in parse_table(tech_raw):
        for key in ["closePrice", "last", "收盘价", "最新"]:
            if key in row and row[key]:
                try:
                    price = float(row[key])
                    break
                except: pass
        if price > 0:
            break
    result["price"] = price

    # 资金维度 0-35 (双弦原有 · 保留)
    fund_score = 15
    fund_rows = parse_table(fund_raw)
    if fund_rows:
        fr = fund_rows[0]
        net_str = fr.get("MainNetFlow", "")
        if net_str:
            try:
                net = float(net_str)
                if net > 0:
                    fund_score = 25 if net > 1e8 else 20
                elif net < -1e8:
                    fund_score = 5
                elif net < -1e7:
                    fund_score = 10
                else:
                    fund_score = 15
            except: pass
        lhb_str = fr.get("LhbInfos", "")
        if lhb_str and '"NetBuy"' in lhb_str:
            import json as _j
            try:
                lhb = _j.loads(lhb_str.replace("'", '"'))
                if isinstance(lhb, list) and len(lhb) > 0:
                    nb = float(lhb[0].get("NetBuy", 0))
                    if nb > 0:
                        fund_score = min(35, fund_score + 5)
            except: pass
    result["fund_score"] = min(35, fund_score)

    # 技术维度 0-35 (猛兽v3.0: VAD+OVS+SSV替代原MACD/RSI)
    tech_score = 15
    try:
        import importlib
        beast = importlib.import_module("beast_screener")
        df = beast.parse_kline_df(code, 250)
        if not df.empty and len(df) >= 30:
            # VAD中期动量评分 (0-15分)
            vad = beast.calc_vad(df, 14)
            vad_val = vad["vad"]
            result["vad"] = vad_val
            result["vad_trend"] = vad["vad_trend"]
            if vad_val > 8: tech_score = 28
            elif vad_val > 5: tech_score = 24
            elif vad_val > 3: tech_score = 20
            elif vad_val > 1: tech_score = 18
            elif vad_val > 0: tech_score = 16
            elif vad_val > -3: tech_score = 12
            else: tech_score = 8

            # OVS短期动量加分 (PV3>40 或堆量特征)
            ovs = beast.calc_ovs_exact(df)
            result["pv3"] = ovs["pv3"]
            result["ov3"] = ovs["ov3"]
            if ovs["pv3"] > 40 and ovs["pv3_ov3_ratio"] > 1:
                tech_score = min(35, tech_score + 5)
            elif ovs["pv3"] > 20:
                tech_score = min(35, tech_score + 3)

            # SSV量价加权强度加分
            ssv = beast.calc_ssv(df, 200)
            result["ssv2"] = ssv["ssv2"]
            if ssv["ssv2"] > 100:
                tech_score = min(35, tech_score + 5)
            elif ssv["ssv2"] > 50:
                tech_score = min(35, tech_score + 3)
            elif ssv["ssv2"] > 0:
                tech_score = min(35, tech_score + 1)
    except:
        # 猛兽不可用时回退到原MACD/RSI
        tech_rows = parse_table(tech_raw)
        if tech_rows:
            row = tech_rows[0]
            dif_str = row.get("macd.DIF", row.get("DIF", ""))
            dea_str = row.get("macd.DEA", row.get("DEA", ""))
            if dif_str and dea_str:
                try:
                    dif = float(dif_str) if dif_str != '-' else 0
                    dea = float(dea_str) if dea_str != '-' else 0
                    tech_score = 25 if dif > dea and dif > 0 else (20 if dif > dea else (8 if dif < 0 else 12))
                except: pass
            rsi_str = row.get("rsi.RSI_6", row.get("RSI_6", ""))
            if rsi_str and rsi_str != '-':
                try:
                    rsi = float(rsi_str)
                    if 30 < rsi < 70: tech_score = min(35, tech_score + 3)
                    elif rsi < 30: tech_score = min(35, tech_score + 5)
                except: pass
    result["tech_score"] = min(35, tech_score)

    # 趋势维度 0-30 (大盘+板块+猛兽SSV强度共振)
    trend_score = 12
    trend_score += 3 if index_temp >= 40 else -3
    trend_score += 3 if sector_zdf > 0 else -3 if sector_zdf < -2 else 0
    # SSV加分: SSV>100说明个股自身强度高
    if result.get("ssv2", 0) > 100:
        trend_score = min(30, trend_score + 3)
    elif result.get("ssv2", 0) > 50:
        trend_score = min(30, trend_score + 1)
    result["trend_score"] = max(0, min(30, trend_score))

    # 总分
    total = result["fund_score"] + result["tech_score"] + result["trend_score"]
    result["total_score"] = total

    # 共振评分 -3~+3 (增强: 加入猛兽信号)
    resonance = 0
    resonance += 1 if index_temp >= 55 else (-1 if index_temp < 40 else 0)
    resonance += 1 if sector_zdf > 1.5 else (-1 if sector_zdf < -2 else 0)
    resonance += 1 if fund_score >= 20 else (-1 if fund_score < 10 else 0)
    # 猛兽SSV增强共振
    if result.get("ssv2", 0) > 100:
        resonance += 1
    elif result.get("ssv2", 0) < -50:
        resonance -= 1
    result["resonance"] = max(-3, min(3, resonance))

    return result


# ============================================================
# 4.5 猛兽信号富集 (轻量级升级)
# ============================================================
def enrich_with_beast_signals(stocks: list[dict]) -> list[dict]:
    """
    对候选股列表运行猛兽v3.0信号检测，添加信号标签
    检测项: G点 / 伏击线 / RS_D背离 / 双模式 / SSV强度
    """
    try:
        import importlib
        beast = importlib.import_module("beast_screener")
        index_raw = beast.cli("kline sh000985 --period day --limit 30")
        index_df = beast.parse_kline_df("sh000985", 30)
    except Exception as e:
        # 猛兽不可用，原样返回
        for s in stocks:
            s["beast_tags"] = []
        return stocks

    enriched = []
    for s in stocks:
        code = s["code"]
        # 走猛兽K线获取
        df = beast.parse_kline_df(code, 250)
        if df.empty or len(df) < 30:
            s["beast_tags"] = []
            enriched.append(s)
            continue

        tags = []

        # OVS检测
        ovs = beast.calc_ovs_exact(df)
        s["pv3"] = ovs["pv3"]
        s["ov3"] = ovs["ov3"]

        # SSV强度
        ssv = beast.calc_ssv(df, 200)
        s["ssv2"] = ssv["ssv2"]
        if ssv["ssv2"] > 100:
            tags.append("SSV>100")

        # VAD趋势
        vad = beast.calc_vad(df, 14)
        s["vad"] = vad["vad"]
        s["vad_trend"] = vad["vad_trend"]

        # G点检测
        if not index_df.empty:
            gpoint = beast.detect_gpoint(df, index_df)
            s["has_gpoint"] = gpoint["has_gpoint"]
            if gpoint["has_gpoint"]:
                tags.append("G点")

            # RS_D背离
            rs_d5 = beast.calc_rs_d(df, index_df, 5)
            rs_d4 = beast.calc_rs_d(df, index_df, 4)
            s["dr5"] = rs_d5["dr"]
            s["dr4"] = rs_d4["dr"]
            if abs(rs_d5["dr"]) < 15 or abs(rs_d4["dr"]) < 15:
                tags.append("RS_D背离")

            # 伏击线
            ambush = beast.calc_ambush_line(df, 5, 20)
            s["ambush_score"] = ambush["ambush_score"]
            if ambush["ambush_score"] >= 3:
                tags.append("伏击线")

            # 双模式分类
            mode = beast.classify_mode(0, {"pv3": ovs["pv3"], "ov3": ovs["ov3"]})
            s["trade_mode"] = mode

        s["beast_tags"] = tags
        enriched.append(s)

    return enriched


# ============================================================
# 5. 主运行流程
# ============================================================
def run_daily(pool_path=None):
    """每日全量扫描（--pool panhou_lianghua.csv 接入资金四态动态池）"""
    today = date.today().isoformat()
    print(f"双弦投资系统 v2.2 ima版")
    print(f"运行时间: {today} {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 50)

    # Step 0: 大盘温度计
    print("\n[Step 0] 大盘温度计...")
    temp, level = thermometer()
    print(f"  温度: {temp}/100 ({level})")
    gate1 = temp >= 40
    print(f"  门控1(温度≥40): {'✅ 通过' if gate1 else '❌ 不通过'}")

    # Step 1: 板块扫描
    print("\n[Step 1] 板块扫描...")
    sectors = scan_sectors()
    print(f"  流入为正板块: {len(sectors['inflow'])}个")
    for s in sectors['inflow'][:5]:
        print(f"    + {s['name']} ({s['zdf']:+.2f}%)")
    for s in sectors['all'][:3]:
        if s['zdf'] < 0:
            print(f"    - {s['name']} ({s['zdf']:.2f}%)")

    # Step 2+3: 候选池评分（panhou资金四态动态池 + 硬编码保底，并发）
    print("\n[Step 2+3] 候选池评分（panhou资金四态 + 硬编码保底）...")
    # 硬编码保底（月度股池连续性：灵康/红豆/日发/蓝筹5只）
    base_stocks = [
        ("sh603669", "灵康药业", "医药生物"),
        ("sh600400", "红豆股份", "纺织服饰"),
        ("sz002520", "日发精机", "机械设备"),
        ("sh603501", "豪威集团", "半导体"),
        ("sh603986", "兆易创新", "存储器"),
        ("sh600487", "亨通光电", "通信设备"),
        ("sh601857", "中国石油", "石油石化"),
        ("sz002129", "TCL中环", "元件"),
    ]
    dyn_pool = []
    if pool_path and os.path.exists(pool_path):
        dyn_pool = load_panhou_pool(pool_path)
        print(f"  panhou资金四态候选: {len(dyn_pool)} 只（抢筹/吸筹/进场）")
    else:
        print("  ⚠️ 未指定panhou池（--pool），仅硬编码保底8只")

    tasks, seen = [], set()
    for code, name, sname in base_stocks:
        if code in seen:
            continue
        seen.add(code)
        tasks.append((code, name, sname))
    for code, name in dyn_pool:
        if code in seen:
            continue
        seen.add(code)
        tasks.append((code, name, ""))
    print(f"  总评分标的: {len(tasks)} 只（4线程并发）")

    def _score(t):
        code, name, sname = t
        sector_zdf = 0
        if sname:
            for s in sectors['all']:
                if sname[:2] in s['name'] or s['name'] in sname:
                    sector_zdf = s['zdf']
                    break
        return score_stock(code, name, sname, sector_zdf, temp)

    scored = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(_score, tasks):
            scored.append(r)
    scored.sort(key=lambda x: -x["total_score"])
    for r in scored[:15]:
        label = "S" if r["total_score"] >= 80 else "A" if r["total_score"] >= 65 else \
                "B" if r["total_score"] >= 50 else "C"
        resonance_label = ["逆势", "偏空", "中性", "偏多", "强共振"][min(4, max(0, r["resonance"] + 3))]
        print(f"  {r['code']} {r['name']}")
        print(f"    评分: {r['total_score']}分({label}) | "
              f"资金{r['fund_score']}+技术{r['tech_score']}+趋势{r['trend_score']}")
        print(f"    价格: {r['price']} | 共振: {r['resonance']} ({resonance_label})")

    # Step 4: AND门控 (猛兽增强版)
    print("\n[Step 4] AND门控过滤 (猛兽增强版)...")
    print(f"  主门控(温度≥40): {'✅ 通过' if gate1 else '❌ 不通过'}")
    if not gate1:
        print(f"  → 进入冷市模式: 需要猛兽强信号(SSV>100/VAD>5/堆量) + 资金≥10")
    gate_results = []
    for r in scored:
        # 从score_stock结果获取猛兽数据
        has_ssv_strong = r.get("ssv2", 0) > 100
        has_vad_strong = r.get("vad", 0) > 5
        has_ovs_duiliang = r.get("pv3", 0) > 40
        
        # 门控2: 板块条件
        gate2 = True
        
        # 门控3: 资金维度 (至少中性)
        gate3 = r["fund_score"] >= 10
        
        # 门控4: 猛兽信号 (SSV>100 OR VAD>5 OR 堆量特征)
        gate4 = has_ssv_strong or has_vad_strong or has_ovs_duiliang
        
        # 综合判断: 温度够则标准门控，温度低则需要猛兽信号加持
        if gate1:
            passed = gate2 and gate3
        else:
            # 冷市: 必须有猛兽强信号 + 资金不差
            passed = gate2 and gate3 and gate4
        
        if passed and r["price"] > 0:
            gate_results.append(r)
            beast_info = []
            if has_ssv_strong: beast_info.append("SSV>100")
            if has_vad_strong: beast_info.append("VAD强势")
            if has_ovs_duiliang: beast_info.append("堆量特征")
            info_str = f" | {' '.join(beast_info)}" if beast_info else ""
            print(f"  ✅ {r['code']} {r['name']} 评分{r['total_score']} 共振{r['resonance']}{info_str}")

    if not gate_results:
        print("  (无信号通过门控)")

    # Step 5: 猛兽信号富集 + 注入月度股池
    print("\n[Step 5] 猛兽信号富集 + 注入月度股池...")
    from monthly_pool import add_daily_results, MonthlyPool

    # 运行猛兽信号检测 (补充G点/伏击线/RS_D)
    all_candidates = []
    seen_codes = set()
    for r in gate_results:
        if r["code"] not in seen_codes:
            all_candidates.append({"code": r["code"], "name": r["name"], "price": r["price"],
                                    "score": r["total_score"]})
            seen_codes.add(r["code"])
    
    # 低吸候选: 未通过门控但有RS_D背离或伏击线信号的
    for r in scored:
        if r["code"] not in seen_codes:
            has_rsd_potential = abs(r.get("vad", 0)) < 5  # VAD收敛=可能底背离
            if has_rsd_potential and r["price"] <= 10:
                all_candidates.append({"code": r["code"], "name": r["name"], "price": r["price"],
                                        "score": r["total_score"]})
                seen_codes.add(r["code"])

    enriched = enrich_with_beast_signals(all_candidates)

    # 共振股池 (通过门控 + 价格≤10 + 有猛兽信号辅助)
    resonance_list = []
    for r in enriched:
        if r.get("score", 0) >= 50 and r["price"] <= 10 and r["price"] > 0:
            tags_str = " | ".join(r.get("beast_tags", []))
            mode_str = f" [{r.get('trade_mode','')}]" if r.get("trade_mode") else ""
            tags_display = f"猛兽: {tags_str}{mode_str}" if tags_str else ""
            resonance_list.append({
                "code": r["code"], "name": r["name"], "price": r["price"],
                "score": r["score"],
                "resonance_label": f"{['逆势','偏空','中性','偏多','强共振'][min(4, max(0, r.get('resonance',0)+3))] if 'resonance' in r else '中性'}",
                "sector": "",
                "reason": f"双弦门控通过 | {tags_display}" if tags_display else "双弦门控通过",
            })

    # 低吸池 (升级: RS_D背离 OR 伏击线≥3 OR G点触发)
    dip_list = []
    for r in enriched:
        in_gate = any(g["code"] == r["code"] for g in gate_results)
        if not in_gate and r["price"] <= 10:
            # 三维低吸检测
            has_rsd = "RS_D背离" in r.get("beast_tags", [])
            has_ambush = r.get("ambush_score", 0) >= 3
            has_gpoint = r.get("has_gpoint", False)
            has_vad_bias = r.get("vad_trend", "") in ("强势", "偏多")
            
            if has_rsd or has_ambush or has_gpoint or has_vad_bias:
                tags_str = " | ".join(r.get("beast_tags", []))
                mode_str = f" [{r.get('trade_mode','')}]" if r.get("trade_mode") else ""
                reasons = []
                if has_rsd: reasons.append("RS_D背离")
                if has_ambush: reasons.append("伏击线")
                if has_gpoint: reasons.append("G点")
                if has_vad_bias: reasons.append("VAD偏多")
                reason_str = " + ".join(reasons)
                dip_list.append({
                    "code": r["code"], "name": r["name"], "price": r["price"],
                    "score": r["score"], "sector": "",
                    "reason": f"{reason_str} | {tags_str}" if tags_str else reason_str,
                })

    result = add_daily_results(
        resonance_stocks=resonance_list,
        dip_stocks=dip_list,
    )

    print(f"  共振新增: {len(resonance_list)}只 (含猛兽信号)")
    print(f"  低吸新增: {len(dip_list)}只 (RS_D/伏击线/G点)")
    print(f"  当前月度股池总计: {result['total_count']}只")
    
    # 打印信号明细
    print("\n  信号明细:")
    if resonance_list:
        print("  【共振股】")
        for r in enriched:
            if any(g["code"] == r["code"] for g in resonance_list):
                tags = r.get("beast_tags", [])
                mode = r.get("trade_mode", "")
                print(f"    🟢 {r['code']} {r['name']} @{r['price']} "
                      f"评分{r['score']} | {', '.join(tags) if tags else '无信号'} | {mode}")
    if dip_list:
        print("  【低吸股】")
        for r in enriched:
            if any(d["code"] == r["code"] for d in dip_list):
                tags = r.get("beast_tags", [])
                print(f"    📉 {r['code']} {r['name']} @{r['price']} "
                      f"评分{r['score']} | {', '.join(tags) if tags else '无信号'}")

    # Step 6: 输出报告 (含猛兽信号标签 + 轮动信息)
    print("\n[Step 6] 月度股池报告:")
    pool = MonthlyPool()
    print(pool.format_report())
    
    # 轮动报告
    rotation = pool.format_rotation_report()
    if rotation:
        print(f"\n{rotation}")
    
    # 猛兽信号统计
    beast_signal_count = {"G点": 0, "伏击线": 0, "RS_D背离": 0, "SSV>100": 0}
    for r in enriched:
        for tag in r.get("beast_tags", []):
            if tag in beast_signal_count:
                beast_signal_count[tag] += 1
    total_signals = sum(beast_signal_count.values())
    if total_signals > 0:
        print(f"\n  🐅 猛兽信号统计: "
              f"{' | '.join([f'{k}: {v}只' for k, v in beast_signal_count.items() if v > 0])}")
    
    # 自检提醒
    try:
        from datetime import date as dt_date
        day_num = dt_date.today().day
        if day_num >= 25:
            print(f"\n  📋 【月尾提醒】本月已至{day_num}日，建议运行自检:")
            print(f"     python3 scripts/monthly_review.py --full")
        elif day_num % 7 == 0:
            print(f"\n  📋 【周检提醒】运行周度自检:")
            print(f"     python3 scripts/monthly_review.py")
    except:
        pass

    # 写入运行日志
    log = {
        "date": today,
        "temperature": temp,
        "level": level,
        "gate1": gate1,
        "signals": len(gate_results),
        "pool_total": result["total_count"],
    }
    log_file = POOLS_DIR / f"run_log_{today}.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 运行完成！日志已保存: {log_file}")
    return log


# ============================================================
# 命令行入口
# ============================================================
if __name__ == "__main__":
    pool_path = None
    if len(sys.argv) > 1 and sys.argv[1] == "--pool":
        pool_path = sys.argv[2] if len(sys.argv) > 2 else None
    run_daily(pool_path)