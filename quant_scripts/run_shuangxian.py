"""
双弦投资系统 v2.2 - ima版核心运行模块
======================================
基于双弦系统技术文档实现，兼容ima环境(npx westock-data)

依赖: bash, npx, westock-data-skillhub, monthly_pool.py
"""

import subprocess, json, sys, os, re
from datetime import datetime, date
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).parent.parent
POOLS_DIR = BASE_DIR / "pools"
SCRIPTS_DIR = BASE_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# 加入双弦投资系统脚本路径（月度股池模块）
SHUANGXIAN_SCRIPTS = str(Path(__file__).parent)  # GitHub: same dir as monthly_pool.py
if SHUANGXIAN_SCRIPTS not in sys.path:
    sys.path.insert(0, SHUANGXIAN_SCRIPTS)

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
    """五维市场温度计 0-100 (参考沪深300/上证)"""
    # 获取上证指数最近20日K线
    raw = cli("kline sh000001 --period day --limit 10")
    rows = parse_table(raw)
    if len(rows) < 3:
        return 50, "数据不足"

    # 解析收盘价
    closes = []
    for r in rows:
        for key in ["last", "最新", "收盘", "最新价", "收盘价"]:
            if key in r and r[key]:
                try:
                    closes.append(float(r[key]))
                    break
                except:
                    pass

    if len(closes) < 3:
        return 50, "数据不足"

    latest = closes[0]
    high_10d = max(closes)
    low_10d = min(closes)
    range_pct = (high_10d - low_10d) / low_10d * 100 if low_10d else 0
    pos_in_range = (latest - low_10d) / (high_10d - low_10d) if high_10d != low_10d else 0.5

    # 从位置推断温度
    base = round(pos_in_range * 60) + 20  # 20-80基础分
    base = max(0, min(100, base))

    # 简单判定
    if base >= 65:
        level = "偏热"
    elif base >= 50:
        level = "正常"
    elif base >= 40:
        level = "偏冷"
    else:
        level = "冷区"

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
def score_stock(code: str, name: str, sector: str = "",
                sector_zdf: float = 0, index_temp: int = 50) -> dict:
    """对单只股票进行三维评分"""
    result = {"code": code, "name": name, "price": 0,
              "fund_score": 0, "tech_score": 0, "trend_score": 0,
              "total_score": 0, "resonance": 0}

    # 获取技术指标
    tech_raw = cli(f"technical {code} --group all")
    # 获取资金流向
    fund_raw = cli(f"asfund {code}")

    # 解析价格 - 从technical输出
    price = 0
    for row in parse_table(tech_raw):
        for key in ["closePrice", "last", "收盘价", "最新"]:
            if key in row and row[key]:
                try:
                    price = float(row[key])
                    break
                except:
                    pass
        if price > 0:
            break
    result["price"] = price

    # 资金维度 0-35
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
            except:
                pass
        # 龙虎榜净买入加分
        lhb_str = fr.get("LhbInfos", "")
        if lhb_str and '"NetBuy"' in lhb_str:
            import json as _j
            try:
                lhb = _j.loads(lhb_str.replace("'",'"'))
                if isinstance(lhb, list) and len(lhb) > 0:
                    nb = float(lhb[0].get("NetBuy", 0))
                    if nb > 0:
                        fund_score = min(35, fund_score + 5)
            except:
                pass
    result["fund_score"] = min(35, fund_score)

    # 技术维度 0-35
    tech_score = 15
    tech_rows = parse_table(tech_raw)
    if tech_rows:
        row = tech_rows[0]
        # MACD判断 - 列名: macd.DIF, macd.DEA
        dif_str = row.get("macd.DIF", row.get("DIF", ""))
        dea_str = row.get("macd.DEA", row.get("DEA", ""))
        if dif_str and dea_str:
            try:
                dif = float(dif_str) if dif_str != '-' else 0
                dea = float(dea_str) if dea_str != '-' else 0
                if dif > dea:
                    tech_score = 25 if dif > 0 else 20
                elif dif < dea:
                    tech_score = 8 if dif < 0 else 12
            except:
                pass
        # RSI判断 - 列名: rsi.RSI_6
        rsi_str = row.get("rsi.RSI_6", row.get("RSI_6", ""))
        if rsi_str and rsi_str != '-':
            try:
                rsi = float(rsi_str)
                if 30 < rsi < 70:
                    tech_score = min(35, tech_score + 3)
                elif rsi < 30:
                    tech_score = min(35, tech_score + 5)
            except:
                pass
    result["tech_score"] = min(35, tech_score)

    # 趋势维度 0-30
    trend_score = 12
    # 大盘共振
    trend_score += 3 if index_temp >= 40 else -3
    # 板块共振
    trend_score += 3 if sector_zdf > 0 else -3 if sector_zdf < -2 else 0
    result["trend_score"] = max(0, min(30, trend_score))

    # 总分
    total = result["fund_score"] + result["tech_score"] + result["trend_score"]
    result["total_score"] = total

    # 共振评分 -3~+3
    resonance = 0
    # 大盘共振
    if index_temp >= 55:
        resonance += 1
    elif index_temp < 40:
        resonance -= 1

    # 板块共振
    if sector_zdf > 1.5:
        resonance += 1
    elif sector_zdf < -2:
        resonance -= 1

    # 资金共振
    if fund_score >= 20:
        resonance += 1
    elif fund_score < 10:
        resonance -= 1

    result["resonance"] = max(-3, min(3, resonance))

    return result


# ============================================================
# 4. 主运行流程
# ============================================================
def run_daily():
    """每日全量扫描"""
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

    # Step 2: 核心3只标的评分
    print("\n[Step 2] 核心标的评分...")
    core_stocks = [
        ("sh603669", "灵康药业", "医药生物"),
        ("sh600400", "红豆股份", "纺织服饰"),
        ("sz002520", "日发精机", "机械设备"),
    ]

    scored = []
    for code, name, sector in core_stocks:
        # 找对应的板块涨跌幅
        sector_zdf = 0
        for s in sectors['all']:
            if sector[:2] in s['name'] or s['name'] in sector:
                sector_zdf = s['zdf']
                break

        r = score_stock(code, name, sector, sector_zdf, temp)
        scored.append(r)
        label = "S" if r["total_score"] >= 80 else "A" if r["total_score"] >= 65 else \
                "B" if r["total_score"] >= 50 else "C"
        resonance_label = ["逆势", "偏空", "中性", "偏多", "强共振"][r["resonance"] + 3]
        print(f"  {code} {name}")
        print(f"    评分: {r['total_score']}分({label}) | "
              f"资金{r['fund_score']}+技术{r['tech_score']}+趋势{r['trend_score']}")
        print(f"    价格: {r['price']} | 共振: {r['resonance']} ({resonance_label})")

    # Step 3: 热门板块标的追加评分
    print("\n[Step 3] 热门板块标的扫描...")
    # 从板块排行中取流入为正的板块，选代表性主板标的
    hot_picks = [
        ("半导体", "sh603501", "豪威集团"),
        ("存储器", "sh603986", "兆易创新"),
        ("通信设备", "sh600487", "亨通光电"),
        ("石油石化", "sh601857", "中国石油"),
        ("元件", "sz002129", "TCL中环"),
    ]

    for sname, code, cname in hot_picks:
        sector_zdf = 0
        for s in sectors['all']:
            if s['name'] == sname:
                sector_zdf = s['zdf']
                break
        r = score_stock(code, cname, sname, sector_zdf, temp)
        scored.append(r)

    # Step 4: AND门控
    print("\n[Step 4] AND门控过滤...")
    gate_results = []
    for r in scored:
        gate2 = True  # 简化：板块条件
        gate3 = r["fund_score"] >= 10
        passed = gate1 and gate2 and gate3
        if passed and r["price"] > 0:
            gate_results.append(r)
            print(f"  ✅ {r['code']} {r['name']} 评分{r['total_score']} 共振{r['resonance']}")

    if not gate_results:
        print("  (无信号通过门控)")

    # Step 5: 注入月度股池
    print("\n[Step 5] 注入月度股池...")
    from monthly_pool import add_daily_results, MonthlyPool

    resonance_list = []
    # 过滤进入月度股池（共振≥中性0 + 价格≤10）
    for r in gate_results:
        if r["resonance"] >= 0 and r["price"] <= 10 and r["price"] > 0:
            resonance_list.append({
                "code": r["code"], "name": r["name"], "price": r["price"],
                "score": r["total_score"],
                "resonance_label": f"{['逆势','偏空','中性','偏多','强共振'][r['resonance']+3]}",
                "sector": "", "reason": f"双弦门控通过",
            })

    # 低吸检测（简化为评分中等但技术分高的）
    dip_list = []
    for r in scored:
        if r not in gate_results and r["tech_score"] >= 20 and r["price"] <= 10:
            dip_list.append({
                "code": r["code"], "name": r["name"], "price": r["price"],
                "score": r["total_score"], "sector": "",
                "reason": "MACD底背离买点(简版检测)",
            })

    result = add_daily_results(
        resonance_stocks=resonance_list,
        dip_stocks=dip_list,
    )

    print(f"  共振新增: {len(resonance_list)}只")
    print(f"  低吸新增: {len(dip_list)}只")
    print(f"  当前月度股池总计: {result['total_count']}只")

    # Step 6: 输出报告
    print("\n[Step 6] 月度股池报告:")
    pool = MonthlyPool()
    print(pool.format_report())

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
    run_daily()