#!/usr/bin/env python3
"""
基于主力资金流向的全链路量化模型
=================================
参考文章：https://mp.weixin.qq.com/s/LBUHmIhirLVcZDXmK20F7A
核心逻辑：以大额资金净流入数据为基础，覆盖大盘择时→板块筛选→龙头挖掘→买卖验证

模块：
  1. 大盘择时 (Market Timing)    - 市场温度 0~100
  2. 板块资金扫描 (Sector Scan)   - 板块控盘度排序
  3. 龙头个股评分 (Stock Scoring) - 资金沉淀率 + 技术指标共振
  4. 三层趋势共振验证             - 大盘+板块+个股趋势验证
"""

import subprocess
import json
import re
import sys
from datetime import datetime, timedelta

# ============================================================
# 1. 数据获取层 - 调用 westock-data CLI
# ============================================================

def run_cli(cmd: str) -> str:
    """执行 westock-data CLI 并返回 stdout"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return r.stdout
    except Exception as e:
        return f""

def parse_markdown_table(md: str) -> list[dict]:
    """将 markdown 表格解析为 dict 列表"""
    lines = [l.strip() for l in md.split('\n') if l.strip()]
    if not lines:
        return []
    # 找到表头行（包含 | --- | 的上一行）
    header_idx = None
    for i, ln in enumerate(lines):
        if '| ---' in ln:
            header_idx = i - 1
            break
    if header_idx is None or header_idx < 0:
        return []

    headers = [h.strip() for h in lines[header_idx].split('|') if h.strip()]
    data_lines = lines[header_idx + 2:]  # skip header + separator
    results = []
    for ln in data_lines:
        if not ln.startswith('|'):
            continue
        vals = [v.strip() for v in ln.split('|') if v.strip()]
        if len(vals) == len(headers):
            results.append(dict(zip(headers, vals)))
    return results

def get_index_kline(code: str = "sh000001", days: int = 120) -> list[dict]:
    """获取指数K线"""
    raw = run_cli(f"npx -y westock-data-skillhub@1.0.3 kline {code} --period day --limit {days} 2>/dev/null")
    return parse_markdown_table(raw)

def get_board_kline(board_code: str, days: int = 60) -> list[dict]:
    """获取板块K线"""
    raw = run_cli(f"npx -y westock-data-skillhub@1.0.3 kline {board_code} --period day --limit {days} 2>/dev/null")
    return parse_markdown_table(raw)

def get_stock_kline(code: str, days: int = 60) -> list[dict]:
    """获取个股K线"""
    raw = run_cli(f"npx -y westock-data-skillhub@1.0.3 kline {code} --period day --limit {days} 2>/dev/null")
    return parse_markdown_table(raw)

def get_index_technical(code: str = "sh000001") -> dict:
    """获取指数技术指标"""
    raw = run_cli(f"npx -y westock-data-skillhub@1.0.3 technical {code} --group ma,macd,rsi,boll 2>/dev/null")
    rows = parse_markdown_table(raw)
    return rows[0] if rows else {}

def get_stock_technical(code: str) -> dict:
    """获取个股技术指标"""
    raw = run_cli(f"npx -y westock-data-skillhub@1.0.3 technical {code} --group macd,rsi,kdj,boll,ma 2>/dev/null")
    rows = parse_markdown_table(raw)
    return rows[0] if rows else {}

def get_stock_fund(code: str) -> dict:
    """获取A股资金流向"""
    raw = run_cli(f"npx -y westock-data-skillhub@1.0.3 asfund {code} 2>/dev/null")
    rows = parse_markdown_table(raw)
    return rows[0] if rows else {}

def get_hot_boards(limit: int = 15) -> list[dict]:
    """获取热门板块"""
    raw = run_cli(f"npx -y westock-data-skillhub@1.0.3 hot board --limit {limit} 2>/dev/null")
    return parse_markdown_table(raw)

def get_board_sectors() -> list[dict]:
    """获取行业板块排名"""
    raw = run_cli(f"npx -y westock-data-skillhub@1.0.3 board 2>/dev/null")
    return parse_markdown_table(raw)

# ============================================================
# 2. 大盘择时模块
# ============================================================

def calc_market_temperature(kline: list[dict], tech: dict) -> dict:
    """
    计算市场温度 (0~100)
    基于文章框架：融合量价、资金、情绪多维度
    
    评分维度：
    1. 趋势维度 (40%) : 均线排列 + MACD状态
    2. 动量维度 (25%) : RSI相对位置
    3. 量能维度 (20%) : 成交量相对变化
    4. 波动维度 (15%) : 价格相对布林带位置
    """
    if not kline or len(kline) < 20:
        return {"temperature": 50, "level": "中性区", "score_detail": {}}

    scores = {}
    
    # --- 提取收盘价序列（数据按日期降序，最新在最前，反转） ---
    closes_ordered = [float(k['last']) for k in kline]
    volumes_ordered = [float(k['volume']) for k in kline]
    closes = list(reversed(closes_ordered))  # 升序：最旧→最新
    volumes = list(reversed(volumes_ordered))
    latest = closes[-1]  # 最新价
    
    # --- 1. 趋势维度 (40分) ---
    trend_score = 0
    
    # 均线排列：MA5 > MA10 > MA20 为多头排列
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else latest
    ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else latest
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else latest
    
    if ma5 > ma10 > ma20:
        trend_score += 15  # 完美多头
    elif ma5 > ma20:
        trend_score += 10  # 趋势偏多
    else:
        trend_score += 5   # 弱势
    
    # MACD状态
    if 'macd.DIF' in tech and 'macd.DEA' in tech and 'macd.MACD' in tech:
        dif = float(tech['macd.DIF'] or 0)
        dea = float(tech['macd.DEA'] or 0)
        macd_val = float(tech['macd.MACD'] or 0)
        
        if dif > dea:
            trend_score += 15  # 金叉状态
            if macd_val > 0:
                trend_score += 10  # 红柱放大
        elif dif < dea and macd_val < 0:
            trend_score += 5   # 死叉
        else:
            trend_score += 10
    
    # 价格相对20日均线位置
    price_pos = (latest - ma20) / ma20 * 100  # 百分比偏离
    if -2 <= price_pos <= 2:
        trend_score += 0   # 围绕均线震荡
    else:
        trend_score += 0
    
    scores['trend'] = min(trend_score, 40)
    
    # --- 2. 动量维度 (25分) ---
    momentum_score = 0
    
    if 'rsi.RSI_6' in tech:
        rsi6 = float(tech['rsi.RSI_6'] or 50)
        rsi12 = float(tech['rsi.RSI_12'] or 50)
        
        if rsi6 > 70:
            momentum_score += 15  # 强势但可能过热
        elif rsi6 > 50:
            momentum_score += 20  # 中性偏强
        elif rsi6 > 30:
            momentum_score += 10  # 中性
        else:
            momentum_score += 5   # 弱势
        
        # RSI6与RSI12关系
        if rsi6 > rsi12:
            momentum_score += 5
    else:
        momentum_score = 15
    
    scores['momentum'] = min(momentum_score, 25)
    
    # --- 3. 量能维度 (20分) ---
    volume_score = 0
    
    if len(volumes) >= 20:
        vol_5_avg = sum(volumes[-5:]) / 5
        vol_20_avg = sum(volumes[-20:]) / 20
        
        vol_ratio = vol_5_avg / vol_20_avg if vol_20_avg > 0 else 1
        
        if vol_ratio > 1.5:
            volume_score += 20  # 放量明显，活跃
        elif vol_ratio > 1.2:
            volume_score += 15  # 温和放量
        elif vol_ratio > 0.8:
            volume_score += 10  # 量能正常
        else:
            volume_score += 5   # 缩量
    else:
        volume_score = 10
    
    scores['volume'] = min(volume_score, 20)
    
    # --- 4. 波动维度 (15分) ---
    vola_score = 0
    
    if 'boll.BOLL_UPPER' in tech and 'boll.BOLL_LOWER' in tech:
        upper = float(tech['boll.BOLL_UPPER'] or 0)
        lower = float(tech['boll.BOLL_LOWER'] or 0)
        mid = (upper + lower) / 2
        
        if upper - lower > 0:
            band_pos = (latest - lower) / (upper - lower) * 100
            
            if band_pos > 80:
                vola_score += 5   # 触及上轨，注意压力
            elif band_pos > 50:
                vola_score += 12  # 中轨上方，偏多
            elif band_pos > 20:
                vola_score += 8   # 中轨下方，偏弱
            else:
                vola_score += 3   # 触及下轨，超卖
    else:
        vola_score = 8
    
    scores['volatility'] = min(vola_score, 15)
    
    # --- 总温度 ---
    total = sum(scores.values())
    temperature = max(0, min(100, int(total)))
    
    # 温度区间判断
    if temperature >= 80:
        level = "🔥 沸点区 (风险>机会，逐步减仓)"
    elif temperature >= 65:
        level = "🌡️ 偏热区 (谨慎追高，持有为主)"
    elif temperature >= 45:
        level = "✅ 中性区 (结构性行情，围绕主线)"
    elif temperature >= 30:
        level = "🌊 偏冷区 (谨慎布局，关注机会)"
    elif temperature >= 20:
        level = "🧊 冰点区 (机会>风险，分批布局)"
    else:
        level = "❄️ 极寒区 (极度超卖，抄底机会)"
    
    # 近10日趋势
    recent_10 = closes[-10:] if len(closes) >= 10 else closes
    trend_dir = "up" if len(recent_10) >= 2 and recent_10[-1] > recent_10[0] else "down"
    trend_pct = (recent_10[-1] / recent_10[0] - 1) * 100 if recent_10[0] else 0
    
    return {
        "temperature": temperature,
        "level": level,
        "score_detail": {
            "趋势得分": scores.get('trend', 0),
            "动量得分": scores.get('momentum', 0),
            "量能得分": scores.get('volume', 0),
            "波动得分": scores.get('volatility', 0)
        },
        "trend_10d": f"{trend_pct:.2f}%",
        "trend_direction": "📈 上涨" if trend_dir == "up" else "📉 下跌",
        "ma_status": "多头排列" if ma5 > ma10 > ma20 else "震荡/空头",
        "rsi_6": float(tech.get('rsi.RSI_6', 50)),
        "current_index": f"{latest:.2f}"
    }

# ============================================================
# 3. 板块资金扫描 (板块控盘度排序)
# ============================================================

def scan_sectors() -> list[dict]:
    """
    板块资金扫描
    输出：按资金控盘度排序的板块列表
    
    解析 board 命令输出的多个独立 Markdown 表格
    """
    raw = run_cli("npx -y westock-data-skillhub@1.0.3 board 2>/dev/null")
    if not raw:
        return []
    
    # 按 **标题** 分割
    sections = re.split(r'\n\*\*.*?\*\*\n', raw)
    
    # 解析各表格
    industry_table = []
    concept_table = []
    fund_table = []
    
    for sec in sections:
        lines = [l.strip() for l in sec.split('\n') if l.strip()]
        # 找到 markdown 表格
        tbl_start = None
        for i, ln in enumerate(lines):
            if ln.startswith('|') and '---' in ln:
                tbl_start = i - 1
                break
        if tbl_start is None or tbl_start < 0:
            continue
        
        headers = [h.strip() for h in lines[tbl_start].split('|') if h.strip()]
        data_rows = []
        for ln in lines[tbl_start+2:]:
            if not ln.startswith('|'):
                continue
            vals = [v.strip() for v in ln.split('|') if v.strip()]
            if len(vals) == len(headers):
                data_rows.append(dict(zip(headers, vals)))
        
        if not data_rows:
            continue
        
        # 判断表格类型
        if 'mainNetInflow' in headers:
            fund_table = data_rows
        elif 'turnoverRate' in headers:
            if any('概念' in sec[:30] for sec in [sec]):
                concept_table = data_rows
            else:
                industry_table = data_rows
        else:
            if any('概念' in sec[:30] for sec in [sec]):
                concept_table = data_rows
            else:
                industry_table = data_rows
    
    # 合并行业和概念板块，添加资金数据
    result = []
    
    # 处理行业板块
    for b in industry_table:
        name = b.get('name', '')
        change = b.get('changePct', '0')
        turnover = b.get('turnoverRate', '0')
        change_5d = b.get('changePct5d', '0')
        change_20d = b.get('changePct20d', '0')
        
        try:
            change_val = float(change)
            change_5d_val = float(change_5d) if change_5d else 0
            
            # 寻找对应的资金数据
            fund_entry = next((f for f in fund_table if f.get('name') == name), None)
            inflow_val = float(fund_entry['mainNetInflow']) * 10000 if fund_entry and fund_entry.get('mainNetInflow', '0').replace('.','',1).replace('-','',1).isdigit() else 0
            inflow_5d_val = float(fund_entry['mainNetInflow5d']) * 10000 if fund_entry and fund_entry.get('mainNetInflow5d', '0').replace('.','',1).replace('-','',1).isdigit() else 0
            
            # 尝试智能解析
            if not fund_entry:
                try:
                    inflow_val = float(b.get('mainNetInflow', 0)) if b.get('mainNetInflow') else 0
                    inflow_5d_val = float(b.get('mainNetInflow5d', 0)) if b.get('mainNetInflow5d') else 0
                except (ValueError, TypeError):
                    inflow_val = 0
                    inflow_5d_val = 0
            
            # 控盘度评分 (0-100)
            control_score = 50  # baseline
            
            if change_val > 0:
                control_score += int(change_val * 2)  # 涨幅加分
            if change_5d_val > 5:
                control_score += 10
            if inflow_val > 0:
                control_score += 15
            if inflow_5d_val > 0:
                control_score += 10
            
            control_score = min(100, max(0, control_score))
            
            # 提取龙头股
            lead = b.get('leadStock', '')
            
            result.append({
                "name": name,
                "change_pct": f"{change_val:+.2f}%",
                "change_5d": f"{change_5d_val:+.2f}%",
                "main_inflow": inflow_val,
                "main_inflow_5d": inflow_5d_val,
                "control_score": control_score,
                "control_signal": "🔴 正控盘" if control_score >= 55 else "🟢 负控盘",
                "turnover": turnover,
                "lead_stock": lead,
                "type": "行业"
            })
        except (ValueError, TypeError):
            pass
    
    # 处理概念板块
    for b in concept_table:
        name = b.get('name', '')
        change = b.get('changePct', '0')
        turnover = b.get('turnoverRate', '0')
        change_5d = b.get('changePct5d', '0')
        change_20d = b.get('changePct20d', '0')
        
        try:
            change_val = float(change)
            change_5d_val = float(change_5d) if change_5d else 0
            
            control_score = 50
            if change_val > 0:
                control_score += int(change_val * 2)
            if change_5d_val > 5:
                control_score += 10
            control_score = min(100, max(0, control_score))
            
            lead = b.get('leadStock', '')
            
            result.append({
                "name": name,
                "change_pct": f"{change_val:+.2f}%",
                "change_5d": f"{change_5d_val:+.2f}%",
                "main_inflow": 0,
                "main_inflow_5d": 0,
                "control_score": control_score,
                "control_signal": "🔴 正控盘" if control_score >= 55 else "🟢 负控盘",
                "turnover": turnover,
                "lead_stock": lead,
                "type": "概念"
            })
        except (ValueError, TypeError):
            pass
    
    # 按控盘度排序
    result.sort(key=lambda x: x['control_score'], reverse=True)
    return result

# ============================================================
# 4. 龙头个股评分
# ============================================================

def score_stock(code: str, name: str = "") -> dict:
    """
    对单只个股进行综合评分
    基于：资金沉淀率 + 技术指标共振 + 趋势位置
    
    评分体系 (0~100):
    1. 资金维度 (35分): 主力净流入 + 多周期资金持续性
    2. 技术共振 (35分): MACD + RSI + KDJ + 布林带
    3. 趋势结构 (30分): 均线排列 + 量价关系
    """
    tech = get_stock_technical(code)
    fund = get_stock_fund(code)
    kline = get_stock_kline(code, 60)
    
    if not kline:
        return {"code": code, "name": name, "error": "无数据", "score": 0}
    
    scores = {}
    # K线数据按日期降序（最新在前），反转
    closes_ordered = [float(k['last']) for k in kline]
    closes = list(reversed(closes_ordered))
    latest_close = closes[-1]
    
    # --- 1. 资金维度 (35分) ---
    fund_score = 0
    
    if fund:
        main_net = float(fund.get('MainNetFlow', 0) or 0)
        main_5d = float(fund.get('MainNetFlow5D', 0) or 0)
        main_10d = float(fund.get('MainNetFlow10D', 0) or 0)
        main_20d = float(fund.get('MainNetFlow20D', 0) or 0)
        jumbo_net = float(fund.get('JumboNetFlow', 0) or 0)
        price = float(fund.get('ClosePrice', 1) or 1)
        
        # 单日主力净流入评分
        if main_net > 0:
            fund_score += 8
            if main_net > price * 1000000:  # 大额流入
                fund_score += 4
        
        # 多周期资金持续性（文章核心：多周期资金验证）
        positive_periods = 0
        if main_5d > 0: positive_periods += 1
        if main_10d > 0: positive_periods += 1
        if main_20d > 0: positive_periods += 1
        
        fund_score += positive_periods * 5  # 每多一个周期正流入+5
        
        # 特大单净流入（大额商业资金近似）
        if jumbo_net > 0:
            fund_score += 5
        
        # 资金沉淀率近似：短期净流入 / 成交量
        total_inflow = float(fund.get('MainInFlow', 0) or 0)
        total_outflow = float(fund.get('MainOutFlow', 0) or 0)
        if total_inflow + total_outflow > 0:
            sedimentation = (main_net) / (total_inflow + total_outflow) * 100
            if sedimentation > 10:
                fund_score += 8  # 高沉淀率
            elif sedimentation > 5:
                fund_score += 4
        
        # 股价下跌但资金正流入 = 洗盘特征（文章核心策略）
        if len(closes) >= 2:
            price_down = closes[-1] < closes[-2]
            if price_down and main_net > 0:
                fund_score += 5  # 洗盘特征加分
    
    scores['fund'] = min(fund_score, 35)
    
    # --- 2. 技术共振 (35分) ---
    tech_score = 0
    
    if tech:
        # MACD
        dif = float(tech.get('macd.DIF', 0) or 0)
        dea = float(tech.get('macd.DEA', 0) or 0)
        macd_val = float(tech.get('macd.MACD', 0) or 0)
        
        if dif > dea and macd_val > 0:
            tech_score += 10  # MACD金叉+红柱
        elif dif > dea:
            tech_score += 6   # 金叉但未放量
        elif macd_val < 0 and dif < dea:
            tech_score += 2   # 死叉
        
        # RSI
        rsi6 = float(tech.get('rsi.RSI_6', 50) or 50)
        rsi12 = float(tech.get('rsi.RSI_12', 50) or 50)
        
        if 50 <= rsi6 <= 70:
            tech_score += 8   # 强势区间
        elif rsi6 > 70:
            tech_score += 4   # 超买
        elif 30 <= rsi6 < 50:
            tech_score += 4   # 弱势
        else:
            tech_score += 2   # 超卖
        
        if rsi6 > rsi12:
            tech_score += 3   # 短期动量向上
        
        # KDJ
        kdj_k = float(tech.get('kdj.KDJ_K', 50) or 50)
        kdj_d = float(tech.get('kdj.KDJ_D', 50) or 50)
        
        if kdj_k > kdj_d:
            tech_score += 4
        if 20 <= kdj_d <= 80:
            tech_score += 2
        
        # 布林带位置
        boll_upper = float(tech.get('boll.BOLL_UPPER', 0) or 0)
        boll_mid = float(tech.get('boll.BOLL_MID', 0) or 0)
        boll_lower = float(tech.get('boll.BOLL_LOWER', 0) or 0)
        
        if boll_upper > boll_lower > 0:
            band_pos = (latest_close - boll_lower) / (boll_upper - boll_lower) * 100
            if 40 <= band_pos <= 70:
                tech_score += 6   # 中轨上方运行，健康
            elif band_pos < 20:
                tech_score += 3   # 接近下轨
            elif band_pos > 80:
                tech_score += 2   # 接近上轨
    
    scores['technical'] = min(tech_score, 35)
    
    # --- 3. 趋势结构 (30分) ---
    trend_score = 0
    
    if len(closes) >= 20:
        # 均线系统
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        
        if ma5 > ma10 > ma20:
            trend_score += 12  # 多头排列
        elif ma5 > ma10:
            trend_score += 8   # 短期偏多
        elif ma5 > ma20:
            trend_score += 5   # 震荡
        else:
            trend_score += 2   # 空头
        
        # 近10日趋势强度
        if len(closes) >= 10:
            recent_return = (closes[-1] - closes[-10]) / closes[-10] * 100
            if recent_return > 5:
                trend_score += 10
            elif recent_return > 2:
                trend_score += 7
            elif recent_return > -2:
                trend_score += 4
            else:
                trend_score += 1
        
        # 量价配合（成交量）
        vols_ordered = [float(k['volume']) for k in kline]
        volumes = list(reversed(vols_ordered))
        if len(volumes) >= 10:
            vol_latest = sum(volumes[-3:]) / 3
            vol_prior = sum(volumes[-10:-3]) / 7
            vol_ratio = vol_latest / vol_prior if vol_prior > 0 else 1
            
            if vol_ratio > 1.3:
                trend_score += 8  # 放量上涨（如果是上涨的话）
            elif vol_ratio > 0.8:
                trend_score += 5
    else:
        trend_score = 10
    
    scores['trend'] = min(trend_score, 30)
    
    # --- 总评分 ---
    total_score = sum(scores.values())
    total_score = max(0, min(100, int(total_score)))
    
    # 操作建议
    if total_score >= 80:
        suggestion = "🟢 强势买入"
    elif total_score >= 65:
        suggestion = "✅ 逢低买入，重点关注"
    elif total_score >= 50:
        suggestion = "🟡 观望，等待信号确认"
    elif total_score >= 35:
        suggestion = "🟠 谨慎，减仓或回避"
    else:
        suggestion = "🔴 建议回避"
    
    # 支撑/压力位
    support = f"{min(closes[-5:])*0.98:.2f}" if len(closes) >= 5 else "-"
    resistance = f"{max(closes[-5:])*1.02:.2f}" if len(closes) >= 5 else "-"
    
    # 买入价位建议（回踩支撑）
    if ma5 > 0:
        buy_zone_low = f"{min(ma5, ma10)*0.98:.2f}"
        buy_zone_high = f"{latest_close:.2f}"
    else:
        buy_zone_low = buy_zone_high = "-"
    
    return {
        "code": code,
        "name": name,
        "price": f"{latest_close:.2f}",
        "score": total_score,
        "suggestion": suggestion,
        "score_detail": {
            "资金维度": scores.get('fund', 0),
            "技术共振": scores.get('technical', 0),
            "趋势结构": scores.get('trend', 0)
        },
        "support": support,
        "resistance": resistance,
        "buy_zone": f"{buy_zone_low}~{buy_zone_high}",
        "ma_status": "多头排列" if len(closes) >= 20 and sum(closes[-5:])/5 > sum(closes[-10:])/10 > sum(closes[-20:])/20 else "震荡/调整"
    }

# ============================================================
# 5. 三层趋势共振验证
# ============================================================

def verify_resonance(index_tech: dict, board_kline: list[dict], stock_result: dict) -> dict:
    """
    三层趋势共振验证
    文章框架：大盘趋势 + 板块趋势 + 个股趋势 三层同步
    
    返回：
    - index_trend: 大盘趋势方向 (up/down/side)
    - board_trend: 板块趋势方向
    - stock_trend: 个股趋势方向
    - resonance: 是否三层共振
    """
    # 大盘趋势
    index_rsi = float(index_tech.get('rsi.RSI_6', 50) or 50)
    index_dif = float(index_tech.get('macd.DIF', 0) or 0)
    index_dea = float(index_tech.get('macd.DEA', 0) or 0)
    
    if index_dif > index_dea and index_rsi > 50:
        index_trend = "up"
        index_signal = "📈 趋势向上"
    elif index_dif < index_dea and index_rsi < 50:
        index_trend = "down"
        index_signal = "📉 趋势向下"
    else:
        index_trend = "side"
        index_signal = "➡️ 震荡整理"
    
    # 板块趋势
    if board_kline and len(board_kline) >= 10:
        board_closes = [float(b['last']) for b in board_kline]
        board_recent = (board_closes[-1] - board_closes[-10]) / board_closes[-10] * 100
        
        if board_recent > 5:
            board_trend = "up"
            board_signal = "📈 板块走强"
        elif board_recent < -5:
            board_trend = "down"
            board_signal = "📉 板块走弱"
        else:
            board_trend = "side"
            board_signal = "➡️ 板块震荡"
    else:
        board_trend = "side"
        board_signal = "➡️ 数据不足"
    
    # 个股趋势
    stock_score = stock_result.get('score', 50)
    if stock_score >= 65:
        stock_trend = "up"
        stock_signal = "📈 个股强势"
    elif stock_score >= 50:
        stock_trend = "side"
        stock_signal = "➡️ 个股中性"
    else:
        stock_trend = "down"
        stock_signal = "📉 个股弱势"
    
    # 共振判断
    directions = [index_trend, board_trend, stock_trend]
    
    if directions.count("up") == 3:
        resonance = "✅✅✅ 完美共振！三层同步向上 → 高胜率介入机会"
        resonance_score = 100
    elif directions.count("up") >= 2 and "down" not in directions:
        resonance = "✅✅ 较好共振，两层向上"
        resonance_score = 75
    elif directions.count("down") >= 2:
        resonance = "❌ 趋势共振向下，主力已离场，坚决规避"
        resonance_score = 10
    elif directions.count("up") >= 1:
        resonance = "⚠️ 部分共振，需进一步确认"
        resonance_score = 40
    else:
        resonance = "➖ 无共振信号"
        resonance_score = 25
    
    # 走势结构匹配（文章：板块强+个股弱=可观察补涨；板块弱+个股强=独立行情）
    if board_trend == "up" and stock_trend == "down":
        structure = "💡 板块强、个股弱 → 可观察等待补涨"
    elif board_trend == "down" and stock_trend == "up":
        structure = "⚠️ 板块弱、个股强 → 独立行情，持续性差，谨慎参与"
    elif board_trend == "up" and stock_trend == "up":
        structure = "✅ 板块个股同步向上 → 确定性最强"
    else:
        structure = "➡️ 结构中性"
    
    return {
        "index": index_signal,
        "board": board_signal,
        "stock": stock_signal,
        "resonance": resonance,
        "resonance_score": resonance_score,
        "structure": structure
    }

# ============================================================
# 6. 多周期资金验证
# ============================================================

def verify_multi_period_fund(fund: dict) -> dict:
    """
    多周期资金验证策略（文章核心策略）
    搭配每日净流入 + 3日 + 5日 + 20日 四层资金数据
    
    特别：股价下跌但20日控盘仍为正 = 洗盘特征
    """
    if not fund:
        return {"signal": "数据不足", "verdict": "⚠️ 无资金数据"}
    
    main_net = float(fund.get('MainNetFlow', 0) or 0)
    main_5d = float(fund.get('MainNetFlow5D', 0) or 0)
    main_10d = float(fund.get('MainNetFlow10D', 0) or 0)
    main_20d = float(fund.get('MainNetFlow20D', 0) or 0)
    
    # 各周期方向
    periods = {
        "当日主力净流入": main_net,
        "近5日主力净流入": main_5d,
        "近10日主力净流入": main_10d,
        "近20日主力净流入": main_20d
    }
    
    positive_count = sum(1 for v in periods.values() if v > 0)
    negative_count = sum(1 for v in periods.values() if v < 0)
    
    if positive_count == 4:
        verdict = "✅✅ 所有周期资金同步向上 → 主力坚定做多，持仓待涨"
    elif positive_count >= 3:
        verdict = "✅ 多数周期资金持续流入 → 中期看好"
    elif negative_count == 4:
        verdict = "❌❌ 所有周期资金同步向下 → 主力已离场，坚决规避"
    elif negative_count >= 3:
        verdict = "❌ 多数周期资金流出 → 减仓观望"
    elif main_net < 0 and main_20d > 0:
        verdict = "💡 股价下跌但20日控盘仍为正 → 大概率是洗盘，可逢低关注"
    elif main_net > 0 and main_5d < 0:
        verdict = "⚠️ 当日资金流入但中期流出 → 仅为短期脉冲行情"
    else:
        verdict = "➡️ 资金信号不明确，需结合其它维度"
    
    return {
        "periods": periods,
        "positive_periods": positive_count,
        "negative_periods": negative_count,
        "verdict": verdict
    }

# ============================================================
# 7. 主流程：生成完整量化报告
# ============================================================

def generate_report(stock_pool: list[tuple] = None):
    """
    生成完整量化模型报告
    
    stock_pool: [(code, name, board_code), ...] 待分析股票池
    """
    print("=" * 72)
    print("   🔍 主力资金量化模型 · 全链路扫描报告")
    print(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} (数据截至7月1日收盘)")
    print("   参考策略: 大额商业资金净流入 + 三层趋势共振 + 多周期资金验证")
    print("=" * 72)
    
    # ==================== 模块1：大盘择时 ====================
    print("\n" + "─" * 72)
    print("  📊 模块一：大盘择时 · 市场温度计")
    print("─" * 72)
    
    index_kline = get_index_kline("sh000001", 120)
    index_tech = get_index_technical("sh000001")
    
    temp_result = calc_market_temperature(index_kline, index_tech)
    
    print(f"\n  上证指数: {temp_result['current_index']}")
    print(f"  市场温度: {temp_result['temperature']}/100")
    print(f"  温度区间: {temp_result['level']}")
    print(f"  近10日走势: {temp_result['trend_direction']} ({temp_result['trend_10d']})")
    print(f"  均线状态: {temp_result['ma_status']}")
    print(f"  RSI(6): {temp_result['rsi_6']:.1f}")
    print(f"\n  评分明细:")
    for dim, score in temp_result['score_detail'].items():
        bar = "█" * (score // 2) + "░" * ((50 - score) // 2)
        print(f"    {dim}: {score:>4d}分 |{bar}|")
    
    # 根据温度给出操作建议
    if temp_result['temperature'] >= 80:
        print(f"\n  💡 建议: 市场过热，逐步减仓止盈，控制仓位在3成以下")
    elif temp_result['temperature'] >= 65:
        print(f"\n  💡 建议: 市场偏热，不追高，围绕主线轻仓参与")
    elif temp_result['temperature'] >= 45:
        print(f"\n  💡 建议: 结构性行情，聚焦主力资金持续流入的主线板块")
    elif temp_result['temperature'] >= 30:
        print(f"\n  💡 建议: 市场偏冷，关注超跌机会，分批布局")
    else:
        print(f"\n  💡 建议: 市场冰点，分批抄底，关注主力逆势建仓标的")
    
    # ==================== 模块2：板块扫描 ====================
    print("\n" + "─" * 72)
    print("  🏭 模块二：板块资金扫描 · 控盘度排名")
    print("─" * 72)
    
    sectors = scan_sectors()
    
    print(f"\n  {'排名':>4s} | {'板块名称':<12s} | {'涨幅':>8s} | {'控盘度得分':>10s} | {'控盘信号':<12s}")
    print(f"  {'-'*4:>4s} | {'-'*12:<12s} | {'-'*8:>8s} | {'-'*10:>10s} | {'-'*12:<12s}")
    
    for i, s in enumerate(sectors[:15], 1):
        print(f"  {i:>4d} | {s['name']:<12s} | {s['change_pct']:>8s} | {s['control_score']:>10d} | {s['control_signal']:<12s}")
    
    # 提取正控盘板块
    positive_boards = [s for s in sectors if s['control_score'] >= 50]
    if positive_boards:
        print(f"\n  ✅ 正控盘板块 ({len(positive_boards)}个): ", end="")
        print(", ".join([b['name'] for b in positive_boards[:8]]))
    
    # ==================== 模块3+4+5：个股评分 + 共振验证 ====================
    print("\n" + "─" * 72)
    print("  🎯 模块三～五：龙头个股评分 · 三层共振 · 多周期资金验证")
    print("─" * 72)
    
    if not stock_pool:
        # 默认分析池：从热门板块中选取代表性标的
        stock_pool = [
            ("sh601162", "天风证券", "pt01801193"),      # 证券Ⅱ
            ("sz300607", "拓斯达", "pt02GN2398"),        # 华为机器人
            ("sh600570", "恒生电子", "pt01801104"),      # 软件开发
            ("sh688981", "中芯国际", "pt01801081"),      # 半导体
            ("sh600519", "贵州茅台", "pt01801150"),      # 消费/医药
            ("sz000858", "五粮液", "pt01801150"),        # 消费
            ("sh600030", "中信证券", "pt01801193"),      # 证券
            ("sh601398", "工商银行", None),               # 银行
            ("sz002594", "比亚迪", None),                 # 新能源汽车
        ]
    
    results = []
    for code, name, board_code in stock_pool:
        print(f"\n  ┌─ {'='*60}")
        print(f"  ├─ 📍 {name} ({code})")
        print(f"  └─ {'='*60}")
        
        result = score_stock(code, name)
        
        if result.get('error'):
            print(f"     错误: {result['error']}")
            continue
        
        results.append(result)
        
        # 个股评分
        print(f"\n     综合评分: {result['score']}/100  |  {result['suggestion']}")
        print(f"     当前价格: ¥{result['price']}")
        print(f"     均线状态: {result['ma_status']}")
        print(f"     支撑/压力: ¥{result['support']} / ¥{result['resistance']}")
        if result['buy_zone']:
            print(f"     买入区间: ¥{result['buy_zone']}")
        
        print(f"\n     评分明细:")
        for dim, score in result['score_detail'].items():
            bar = "█" * (score // 2) + "░" * ((17 - score // 2))
            print(f"       {dim}: {score:>4d}/35分 |{bar}|")
        
        # 三层趋势共振验证
        if board_code:
            board_kline = get_board_kline(board_code, 30)
            resonance = verify_resonance(index_tech, board_kline, result)
            
            print(f"\n     三层趋势共振:")
            print(f"       大盘: {resonance['index']}")
            print(f"       板块: {resonance['board']}")
            print(f"       个股: {resonance['stock']}")
            print(f"       共振结论: {resonance['resonance']}")
            print(f"       结构判断: {resonance['structure']}")
        
        # 多周期资金验证
        fund = get_stock_fund(code)
        if fund:
            fund_verify = verify_multi_period_fund(fund)
            print(f"\n     多周期资金验证:")
            for period_name, val in fund_verify['periods'].items():
                arrow = "📈" if val > 0 else "📉"
                print(f"       {period_name}: {arrow} {val:>15,.0f}")
            print(f"      → {fund_verify['verdict']}")
        
        # 操作建议摘要
        print(f"\n     操作建议:")
        if result['score'] >= 65:
            print(f"       入场: 回踩均线支撑位（¥{result['support']}附近）分批建仓")
            print(f"       止损: 跌破关键支撑¥{result['support']} (-2%)")
            print(f"       止盈: 第一目标¥{result['resistance']}，第二目标+10%")
        elif result['score'] >= 50:
            print(f"       策略: 等待信号进一步确认，关注资金面变化")
        else:
            print(f"       策略: 暂时回避，等待趋势转好")
    
    # ==================== 总结 ====================
    print("\n" + "═" * 72)
    print("  📋 量化模型 · 综合评估与策略建议")
    print("═" * 72)
    
    # 按评分排序
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n  最优标的 TOP3:")
    for i, r in enumerate(results[:3], 1):
        print(f"    {i}. {r['name']:12s} ({r['code']:10s}) 评分: {r['score']:3d}/100  {r['suggestion']}")
    
    earn_buy = [r for r in results if r['score'] >= 65]
    watch = [r for r in results if 50 <= r['score'] < 65]
    avoid = [r for r in results if r['score'] < 50]
    
    print(f"\n  策略分布:")
    print(f"    🟢 强烈关注 (≥65分): {len(earn_buy)} 只")
    print(f"    🟡 观望等待 (50-64分): {len(watch)} 只")
    print(f"    🔴 建议回避 (<50分): {len(avoid)} 只")
    
    print(f"\n  仓位建议 (基于市场温度 {temp_result['temperature']}/100):")
    if temp_result['temperature'] >= 80:
        print(f"    ⚠️ 总仓位 ≤ 30%，以防守为主")
    elif temp_result['temperature'] >= 65:
        print(f"    ⚠️ 总仓位 30-50%，精选个股")
    elif temp_result['temperature'] >= 45:
        print(f"    ✅ 总仓位 50-70%，积极布局主线")
    else:
        print(f"    💡 总仓位 30-50%，分批低吸")
    
    print("\n" + "=" * 72)
    print("  ⚠️ 免责声明: 本模型仅供学习研究，不构成投资建议")
    print("     股市有风险，投资需谨慎。数据来源: 腾讯自选股")
    print("=" * 72)
    
    return results


if __name__ == "__main__":
    generate_report()
