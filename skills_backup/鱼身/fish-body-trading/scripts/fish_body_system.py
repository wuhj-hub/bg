#!/usr/bin/env python3
"""
鱼身交易系统 Fish Body Trading System v1.0
=============================================
基于三种经典鱼身模式的A股量化扫描系统

模式1: MACD空中加油 ⭐（最强信号）
   - 识别MACD在0轴上方运行，DIF回踩DEA不破，柱体由负转正
   - 对应案例：日发精机 2026/07

模式2: 均线回踩支撑（稳健信号）
   - 识别多头排列股票，回踩MA10/MA20关键支撑时缩量止跌
   - 对应案例：灵康药业（等待回调后介入）

模式3: 箱体突破（动量信号）
   - 识别窄幅整理后放量突破前高的加速启动点
   - 对应案例：红豆股份（中继整理后第二波）

数据源: westock-data (腾讯自选股)
用法:   python3 fish_body_system.py [--pool 股票池文件] [--mode 1|2|3|all]
"""

import subprocess
import json
import re
import sys
import os
import time
from datetime import datetime, timedelta
from typing import Optional

# ============================================================
# 配置区
# ============================================================
WESTOCK_CMD = "npx -y westock-data-skillhub@1.0.3"
BATCH_SIZE = 3  # westock-data 批量查询最大数（建议3-5只并行）
DATE_TODAY = "2026-07-05"

# 颜色输出
class Color:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def c(text, color):
    return f"{color}{text}{Color.END}"


# ============================================================
# 工具函数
# ============================================================

def run_cmd(cmd: str, timeout=60) -> str:
    """执行shell命令并返回stdout"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:
        return f""

def parse_markdown_table(text: str) -> list[dict]:
    """解析westock-data返回的Markdown表格为dict列表"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        return []
    
    # 找表头行
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith('|') and '---' not in line:
            # 检查是否包含关键列名
            if any(kw in line for kw in ['code', 'name', 'date', 'closePrice', 'macd.DIF', 'symbol']):
                header_idx = i
                break
    
    if header_idx is None:
        return []
    
    headers = [h.strip() for h in lines[header_idx].split('|')[1:-1]]
    
    # 数据行
    results = []
    for line in lines[header_idx+2:]:  # 跳过表头和分隔行
        if not line.startswith('|'):
            continue
        values = [v.strip() for v in line.split('|')[1:-1]]
        if len(values) == len(headers):
            row = {}
            for h, v in zip(headers, values):
                row[h] = v
            results.append(row)
    
    return results

def safe_float(val) -> Optional[float]:
    """安全转float"""
    if val is None or val == '-' or val == '':
        return None
    try:
        return float(val)
    except:
        return None

def safe_int(val) -> Optional[int]:
    if val is None or val == '-' or val == '':
        return None
    try:
        # 处理科学计数法和大数
        if 'e' in str(val).lower() or 'E' in str(val):
            return int(float(val))
        return int(float(val))
    except:
        return None


# ============================================================
# 数据获取层
# ============================================================

class DataFetcher:
    """获取股票技术数据"""
    
    @staticmethod
    def get_technical(codes: list[str]) -> dict[str, dict]:
        """批量获取技术指标"""
        if not codes:
            return {}
        
        # 分批次查询
        results = {}
        for i in range(0, len(codes), BATCH_SIZE):
            batch = codes[i:i+BATCH_SIZE]
            codes_str = ','.join(batch)
            cmd = f"{WESTOCK_CMD} technical {codes_str} --group all 2>/dev/null"
            raw = run_cmd(cmd)
            
            rows = parse_markdown_table(raw)
            for row in rows:
                code = row.get('code', '')
                if code:
                    results[code] = row
            
            time.sleep(0.5)  # 避免请求过快
        
        return results
    
    @staticmethod
    def get_kline(codes: list[str], limit=120) -> dict[str, list[dict]]:
        """批量获取K线"""
        results = {}
        for i in range(0, len(codes), BATCH_SIZE):
            batch = codes[i:i+BATCH_SIZE]
            codes_str = ','.join(batch)
            cmd = f"{WESTOCK_CMD} kline {codes_str} --period day --limit {limit} --fq qfq 2>/dev/null"
            raw = run_cmd(cmd)
            
            rows = parse_markdown_table(raw)
            for row in rows:
                code = row.get('symbol', row.get('code', ''))
                if code:
                    if code not in results:
                        results[code] = []
                    results[code].append(row)
            
            time.sleep(0.5)
        
        return results
    
    @staticmethod
    def get_fundflow(codes: list[str]) -> dict[str, dict]:
        """批量获取资金流向"""
        results = {}
        for i in range(0, len(codes), BATCH_SIZE):
            batch = codes[i:i+BATCH_SIZE]
            codes_str = ','.join(batch)
            cmd = f"{WESTOCK_CMD} asfund {codes_str} 2>/dev/null"
            raw = run_cmd(cmd)
            
            rows = parse_markdown_table(raw)
            for row in rows:
                code = row.get('code', '')
                if code:
                    results[code] = row
            
            time.sleep(0.5)
        
        return results
    
    @staticmethod
    def search_stock(keyword: str) -> list[dict]:
        """搜索股票"""
        cmd = f"{WESTOCK_CMD} search {keyword} 2>/dev/null"
        raw = run_cmd(cmd)
        return parse_markdown_table(raw)


# ============================================================
# 鱼身模式识别引擎
# ============================================================

class FishBodyEngine:
    """鱼身模式识别引擎"""
    
    @staticmethod
    def pattern_macd_air_refuel(tech: dict) -> Optional[dict]:
        """
        ⭐ MACD空中加油模式
        条件：
        1. DIF > 0, DEA > 0（均在0轴上方）
        2. DIF >= DEA（金叉状态）或最近刚完成金叉
        3. MACD柱最新值 > 0
        4. 前一期MACD柱 <= 0（刚从0轴下方翻红）
        5. 股价在MA5上方
        """
        dif = safe_float(tech.get('macd.DIF'))
        dea = safe_float(tech.get('macd.DEA'))
        macd_val = safe_float(tech.get('macd.MACD'))
        close = safe_float(tech.get('closePrice'))
        ma5 = safe_float(tech.get('ma.MA_5'))
        ma20 = safe_float(tech.get('ma.MA_20'))
        ma60 = safe_float(tech.get('ma.MA_60'))
        kdj_j = safe_float(tech.get('kdj.KDJ_J'))
        name = tech.get('name', '')
        code = tech.get('code', '')
        
        if any(v is None for v in [dif, dea, macd_val, close, ma5]):
            return None
        
        score = 0
        reasons = []
        
        # 条件1: DIF和DEA在0轴上方（多头市场）
        if dif > 0 and dea > 0:
            score += 25
            reasons.append("DIF/DEA在0轴上方")
        else:
            return None  # 硬性条件
        
        # 条件2: DIF >= DEA 或接近（金叉状态）
        if dif >= dea:
            score += 25
            reasons.append(f"DIF({dif:.2f})>=DEA({dea:.2f})金叉")
        elif abs(dif - dea) < 0.03:
            score += 15
            reasons.append(f"DIF({dif:.2f})接近DEA({dea:.2f})即将金叉")
        else:
            return None
        
        # 条件3: MACD柱由负转正（最关键信号）
        # 注意：这里我们只有最新值，需要从完整的技术数据判断
        # 我们通过macd值判断：macd柱>0且值不大（刚刚翻红）
        if macd_val > 0:
            if macd_val < 0.15:  # 刚刚翻红不久
                score += 30
                reasons.append(f"MACD柱{macd_val:.2f}>0加油成功")
            else:
                score += 15
                reasons.append(f"MACD柱{macd_val:.2f}>0但已走高")
        
        # 条件4: 股价在MA5上方（强势）
        if close > ma5:
            score += 10
            reasons.append(f"收盘{close}>MA5{ma5}")
        
        # 条件5: MA20 > MA60（多头排列判断）
        if ma20 and ma60 and ma20 > ma60:
            score += 5
            reasons.append("MA20>MA60多头排列")
        
        # 条件6: KDJ未严重超买（加分项）
        if kdj_j is not None and kdj_j < 85:
            score += 5
            reasons.append(f"KDJ_J={kdj_j:.0f}未超买")
        
        if score >= 60:
            return {
                'code': code,
                'name': name,
                'pattern': 'MACD空中加油 ⭐',
                'score': score,
                'price': close,
                'dif': dif,
                'dea': dea,
                'macd': macd_val,
                'reasons': reasons,
                'risk': '回调至MA5/MA10可加仓',
                'stop_loss': f"{ma5*0.95:.2f}" if ma5 else "—",
                'target': f"{close*1.15:.2f}" if close else "—"
            }
        
        return None
    
    @staticmethod
    def pattern_pullback_support(tech: dict, klines: list[dict] = None) -> Optional[dict]:
        """
        均线回踩支撑模式（对应灵康药业等待回调）
        条件：
        1. 收盘价 > MA20 > MA60（多头排列趋势向上）
        2. 股价在MA10或MA20附近（偏离不超过5%）
        3. 近期从高点回落（有回调动作）
        4. 成交量相对萎缩
        5. MACD在0轴上方
        """
        close = safe_float(tech.get('closePrice'))
        ma5 = safe_float(tech.get('ma.MA_5'))
        ma10 = safe_float(tech.get('ma.MA_10'))
        ma20 = safe_float(tech.get('ma.MA_20'))
        ma60 = safe_float(tech.get('ma.MA_60'))
        ma120 = safe_float(tech.get('ma.MA_120'))
        dif = safe_float(tech.get('macd.DIF'))
        dea = safe_float(tech.get('macd.DEA'))
        macd_val = safe_float(tech.get('macd.MACD'))
        boll_mid = safe_float(tech.get('boll.BOLL_MID'))
        name = tech.get('name', '')
        code = tech.get('code', '')
        
        if any(v is None for v in [close, ma20, ma60]):
            return None
        
        score = 0
        reasons = []
        
        # 条件1: 多头排列（MA20 > MA60）
        if ma20 > ma60:
            score += 20
            reasons.append(f"MA20({ma20:.2f})>MA60({ma60:.2f})多头排列")
        else:
            return None  # 硬性条件
        
        # 条件2: MACD在0轴上方（多头市场）
        if dif and dea and dif > 0 and dea > 0:
            score += 15
            reasons.append(f"MACD在0轴上方(DIF={dif:.2f})")
        elif macd_val and macd_val > 0:
            score += 10
            reasons.append("MACD柱>0")
        
        # 条件3: 股价在MA10或MA20附近（偏离度）
        if ma10:
            deviation = abs(close - ma10) / ma10 * 100
            if deviation < 5:
                score += 25
                reasons.append(f"股价在MA10附近(偏离{deviation:.1f}%)")
            elif deviation < 10:
                score += 15
                reasons.append(f"股价偏离MA10约{deviation:.1f}%")
            else:
                score += 5
        elif ma20:
            deviation = abs(close - ma20) / ma20 * 100
            if deviation < 5:
                score += 20
                reasons.append(f"股价在MA20附近(偏离{deviation:.1f}%)")
        
        # 条件4: 股价 > MA5（短线强势判断）
        if ma5 and close > ma5:
            score += 10
            reasons.append(f"收盘{close}>MA5{ma5}")
        
        # 条件5: 布林带中轨支撑
        if boll_mid and close >= boll_mid:
            score += 5
            reasons.append("站在布林中轨上方")
        
        # 条件6: MA120作为长期趋势判断
        if ma120 and close > ma120:
            score += 5
            reasons.append(f"收盘>MA120{ma120}长期趋势向上")
        
        # 计算回调幅度（如果有K线数据）
        if klines and len(klines) >= 10:
            prices = [safe_float(k.get('last', k.get('closePrice', 0))) for k in klines[:20]]
            prices = [p for p in prices if p is not None]
            if prices:
                high_20d = max(prices)
                if high_20d > close:
                    pullback_pct = (high_20d - close) / high_20d * 100
                    if 3 <= pullback_pct <= 15:
                        score += 15
                        reasons.append(f"已从20日高点回调{pullback_pct:.1f}%")
        
        if score >= 60:
            # 计算支撑位
            support_levels = []
            for level_name, level_val in [('MA10', ma10), ('MA20', ma20), ('布林中轨', boll_mid)]:
                if level_val and level_val < close:
                    support_levels.append(f"{level_name}={level_val:.2f}")
            
            return {
                'code': code,
                'name': name,
                'pattern': '均线回踩支撑',
                'score': score,
                'price': close,
                'dif': dif,
                'dea': dea,
                'macd': macd_val,
                'reasons': reasons,
                'support': ' / '.join(support_levels),
                'stop_loss': f"{ma20*0.95:.2f}" if ma20 else "—",
                'target': f"{close*1.12:.2f}" if close else "—"
            }
        
        return None
    
    @staticmethod
    def pattern_breakout(tech: dict, klines: list[dict] = None) -> Optional[dict]:
        """
        箱体突破模式（对应红豆股份中继突破）
        条件：
        1. 近期（5-10日）振幅较小（收敛整理）
        2. 放量突破整理区间高点
        3. MACD金叉状态
        4. 均线多头排列
        """
        close = safe_float(tech.get('closePrice'))
        ma5 = safe_float(tech.get('ma.MA_5'))
        ma20 = safe_float(tech.get('ma.MA_20'))
        ma60 = safe_float(tech.get('ma.MA_60'))
        dif = safe_float(tech.get('macd.DIF'))
        dea = safe_float(tech.get('macd.DEA'))
        macd_val = safe_float(tech.get('macd.MACD'))
        kdj_k = safe_float(tech.get('kdj.KDJ_K'))
        kdj_d = safe_float(tech.get('kdj.KDJ_D'))
        name = tech.get('name', '')
        code = tech.get('code', '')
        
        if any(v is None for v in [close, ma20]):
            return None
        
        score = 0
        reasons = []
        
        # 条件1: 多头排列
        if ma60 and ma20 > ma60:
            score += 20
            reasons.append(f"MA20({ma20:.2f})>MA60({ma60:.2f})")
        elif ma20:
            score += 10
            reasons.append(f"股价在MA20({ma20:.2f})上方")
        
        # 条件2: MACD金叉
        if dif and dea and dif > dea and dif > 0:
            score += 20
            reasons.append(f"MACD金叉(DIF={dif:.2f})")
        elif macd_val and macd_val > 0:
            score += 10
            reasons.append("MACD柱>0")
        
        # 条件3: KDJ金叉或向上
        if kdj_k and kdj_d and kdj_k > kdj_d:
            score += 10
            reasons.append(f"KDJ金叉(K={kdj_k:.0f}>D={kdj_d:.0f})")
        
        # 条件4: 股价在MA5上方（突破确认）
        if ma5 and close > ma5:
            score += 15
            reasons.append(f"收盘{close}>MA5{ma5}")
        
        # 条件5: 分析K线看是否有突破形态
        if klines and len(klines) >= 10:
            prices_10d = [safe_float(k.get('last', k.get('closePrice', 0))) for k in klines[:10]]
            volumes_10d = [safe_int(k.get('volume', 0)) for k in klines[:10]]
            prices_10d = [p for p in prices_10d if p is not None]
            volumes_10d = [v for v in volumes_10d if v is not None]
            
            if prices_10d and len(prices_10d) >= 5:
                latest_price = prices_10d[0] if klines[0].get('date', '') >= '2026' else prices_10d[-1]
                # 检查最近N天的振幅
                if len(prices_10d) >= 5:
                    recent_high = max(prices_10d[:5])
                    recent_low = min(prices_10d[:5])
                    amplitude = (recent_high - recent_low) / recent_low * 100
                    
                    if amplitude < 12 and latest_price >= recent_high * 0.98:
                        score += 15
                        reasons.append(f"近5日振幅{amplitude:.1f}%收敛突破")
            
            # 成交量放大判断
            if volumes_10d and len(volumes_10d) >= 5:
                avg_vol = sum(volumes_10d[1:6]) / max(len(volumes_10d[1:6]), 1)
                latest_vol = volumes_10d[0]
                if avg_vol > 0 and latest_vol > avg_vol * 1.3:
                    score += 10
                    reasons.append(f"成交量放大(最新{latest_vol} > 均值{avg_vol:.0f})")
        
        if score >= 60:
            return {
                'code': code,
                'name': name,
                'pattern': '箱体突破 🚀',
                'score': score,
                'price': close,
                'reasons': reasons,
                'stop_loss': f"{ma5*0.93:.2f}" if ma5 else "—",
                'target': f"{close*1.15:.2f}" if close else "—"
            }
        
        return None
    
    @staticmethod
    def full_scan(tech_data: dict, kline_data: dict) -> list[dict]:
        """全量扫描三种鱼身模式"""
        signals = []
        
        for code, tech in tech_data.items():
            klines = kline_data.get(code, [])
            
            # 模式1: MACD空中加油 ⭐
            signal1 = FishBodyEngine.pattern_macd_air_refuel(tech)
            if signal1:
                signal1['mode'] = 1
                signals.append(signal1)
            
            # 模式2: 均线回踩支撑
            signal2 = FishBodyEngine.pattern_pullback_support(tech, klines)
            if signal2:
                signal2['mode'] = 2
                signals.append(signal2)
            
            # 模式3: 箱体突破
            signal3 = FishBodyEngine.pattern_breakout(tech, klines)
            if signal3:
                signal3['mode'] = 3
                signals.append(signal3)
        
        # 按分数排序
        signals.sort(key=lambda x: x['score'], reverse=True)
        return signals


# ============================================================
# 股票池管理
# ============================================================

class StockPool:
    """股票池管理"""
    
    # 默认核心股票池（用户关注的标的）
    CORE_POOL = [
        'sh603669',  # 灵康药业
        'sh600400',  # 红豆股份
        'sz002520',  # 日发精机
    ]
    
    @staticmethod
    def from_file(filepath: str) -> list[str]:
        """从文件读取股票池"""
        codes = []
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        codes.append(line)
        except:
            print(f"  ⚠️ 无法读取文件: {filepath}")
        return codes
    
    @staticmethod
    def generate_ashare_pool() -> list[str]:
        """生成A股全量代码池（沪市主板+深市主板）"""
        pool = []
        # 沪市主板 sh600000-sh605999
        for i in range(600000, 606000):
            pool.append(f"sh{i}")
        # 深市主板 sz000001-sz003999
        for i in range(1, 4000):
            pool.append(f"sz{i:06d}")
        return pool


# ============================================================
# 报告生成
# ============================================================

class ReportGenerator:
    """信号报告生成"""
    
    @staticmethod
    def print_banner():
        print(f"""
{Color.CYAN}{'='*60}
  🐟 鱼身交易系统 Fish Body Trading System v1.0
  扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*60}{Color.END}
""")
    
    @staticmethod
    def print_signals(signals: list[dict]):
        """打印信号报告"""
        if not signals:
            print(f"\n{Color.YELLOW}  📭 当前无符合条件的鱼身信号{Color.END}")
            print(f"  💡 建议：扩大股票池或调整评分阈值再试\n")
            return
        
        # 按模式分组
        modes = {
            1: ('MACD空中加油 ⭐', Color.GREEN),
            2: ('均线回踩支撑', Color.CYAN),
            3: ('箱体突破 🚀', Color.YELLOW),
        }
        
        for mode_id, (mode_name, color) in modes.items():
            mode_signals = [s for s in signals if s.get('mode') == mode_id]
            if not mode_signals:
                continue
            
            print(f"\n{color}{'─'*50}")
            print(f"  📊 {mode_name}")
            print(f"{'─'*50}{Color.END}")
            
            for i, s in enumerate(mode_signals, 1):
                price_str = f"{s.get('price', 0):.2f}" if s.get('price') else '—'
                score_str = f"{s.get('score', 0)}分"
                
                print(f"\n  {c(f'#{i}', Color.BOLD)} {s.get('code','')} {s.get('name','')} "
                      f"| 评分: {c(score_str, Color.GREEN if s['score']>=80 else Color.YELLOW)} "
                      f"| 现价: {c(price_str, Color.BOLD)}")
                
                # 信号理由
                reasons = s.get('reasons', [])
                for r in reasons:
                    print(f"     ✅ {r}")
                
                # 风控参数
                stop = s.get('stop_loss', '—')
                target = s.get('target', '—')
                support = s.get('support', '')
                
                print(f"     {c('🛑 止损', Color.RED)}: {stop}  "
                      f"{c('🎯 目标', Color.GREEN)}: {target}")
                if support:
                    print(f"     📍 支撑位: {support}")
                if 'risk' in s:
                    print(f"     💡 策略: {s['risk']}")
    
    @staticmethod
    def print_holdings_analysis(core_codes: list[str], signals: list[dict]):
        """对核心持仓做专项分析"""
        print(f"\n{c('='*50, Color.CYAN)}")
        print(f"  📋 核心标的专项分析")
        print(f"{c('='*50, Color.CYAN)}")
        
        core_signals = [s for s in signals if s['code'] in core_codes]
        scanned_codes = [s['code'] for s in signals]
        
        for code in core_codes:
            matched = [s for s in core_signals if s['code'] == code]
            if matched:
                s = matched[0]
                score_text = f"{s['score']}分"
                print(f"\n  {c(s['code'], Color.BOLD)} {s['name']} → {c(s['pattern'], Color.GREEN)} "
                      f"评分:{c(score_text, Color.GREEN if s['score']>=80 else Color.YELLOW)}")
                for r in s['reasons']:
                    print(f"    ✅ {r}")
            else:
                print(f"\n  {c(code, Color.BOLD)} — {c('当前无信号', Color.YELLOW)}")


# ============================================================
# 主流程
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='鱼身交易系统 v1.0')
    parser.add_argument('--pool', type=str, default='core',
                        help='股票池: core(核心池) | all(全A股) | 文件路径')
    parser.add_argument('--mode', type=str, default='all',
                        help='扫描模式: 1(MACD空中加油) | 2(均线回踩) | 3(箱体突破) | all')
    parser.add_argument('--threshold', type=int, default=60,
                        help='信号评分阈值(默认60)')
    
    args = parser.parse_args()
    
    # ---- Banner ----
    ReportGenerator.print_banner()
    
    # ---- 构建股票池 ----
    print(f"\n{Color.CYAN}📡 构建股票池...{Color.END}")
    
    if args.pool == 'core':
        pool = StockPool.CORE_POOL
        print(f"  使用核心股票池: {len(pool)}只")
    elif args.pool == 'all':
        print(f"  生成全A股代码池...（这可能需要较长时间）")
        pool = StockPool.generate_ashare_pool()
        print(f"  全A股股票池: {len(pool)}只")
    else:
        pool = StockPool.from_file(args.pool)
        print(f"  从文件加载股票池: {len(pool)}只")
    
    if not pool:
        print(f"{Color.RED}  ❌ 股票池为空，退出{Color.END}")
        return
    
    # ---- 获取数据 ----
    print(f"\n{Color.CYAN}📊 获取技术数据...{Color.END}")
    tech_data = DataFetcher.get_technical(pool)
    if not tech_data:
        print(f"{Color.RED}  ❌ 数据获取失败{Color.END}")
        return
    print(f"  成功获取 {len(tech_data)} 只股票的技术指标")
    
    # 获取K线数据（用于模式2和模式3的辅助判断）
    print(f"\n{Color.CYAN}📈 获取K线数据...{Color.END}")
    kline_data = DataFetcher.get_kline(pool, limit=30)
    print(f"  成功获取 {len(kline_data)} 只股票的K线")
    
    # ---- 扫描信号 ----
    print(f"\n{Color.CYAN}🔍 扫描鱼身信号...{Color.END}")
    all_signals = FishBodyEngine.full_scan(tech_data, kline_data)
    
    # 按模式过滤
    if args.mode != 'all':
        mode_map = {'1': 1, '2': 2, '3': 3}
        target_mode = mode_map.get(args.mode)
        if target_mode:
            all_signals = [s for s in all_signals if s.get('mode') == target_mode]
    
    # 按阈值过滤
    all_signals = [s for s in all_signals if s['score'] >= args.threshold]
    
    # ---- 打印报告 ----
    ReportGenerator.print_signals(all_signals)
    
    # ---- 核心标的专项分析 ----
    ReportGenerator.print_holdings_analysis(StockPool.CORE_POOL, all_signals)
    
    # ---- 总结 ----
    print(f"\n{c('='*50, Color.CYAN)}")
    print(f"  扫描完成")
    print(f"  股票池: {len(pool)}只 | 共发现 {len(all_signals)} 个鱼身信号")
    print(f"  MACD空中加油: {len([s for s in all_signals if s.get('mode')==1])}个")
    print(f"  均线回踩支撑: {len([s for s in all_signals if s.get('mode')==2])}个")
    print(f"  箱体突破:     {len([s for s in all_signals if s.get('mode')==3])}个")
    print(f"{c('='*50, Color.CYAN)}")
    
    # ---- 保存结果 ----
    output_file = f"/sandbox/workspace/outputs/fish_body_signals_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    os.makedirs('/sandbox/workspace/outputs', exist_ok=True)
    try:
        with open(output_file, 'w') as f:
            json.dump(all_signals, f, ensure_ascii=False, indent=2)
        print(f"\n  📁 信号已保存: {output_file}")
    except:
        pass


if __name__ == '__main__':
    main()