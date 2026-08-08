#!/usr/bin/env python3
"""
个股综合评分卡 — stock_evaluator.py
========================================
基于统一交易体系 v3.0，对单只个股进行10维综合评价。

用法：
    # 评价单只个股
    python3 stock_evaluator.py 600095          # 湘财股份
    python3 stock_evaluator.py 000779          # 甘咨询
    python3 stock_evaluator.py 002596          # 海南瑞泽
    
    # 批量评价
    python3 stock_evaluator.py 600095,000779,002596 --batch
    
    # 指定日期（用于复盘）
    python3 stock_evaluator.py 600095 --date 2026-07-24

依赖：westock-data-skillhub (npx)
输出：Markdown 格式的个股综合评分卡
"""

import json, os, subprocess, sys, re
from datetime import datetime

# 引入统一过滤规则
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filter_rules import is_tradable, FilterLevel


# ==================== 配置 ====================
# 沪深主板过滤
BAD_PREFIXES = ("688", "300", "301", "8", "43", "83", "87")
# 知识库
KB_ID = "6kjd8jHpAyqf0xFVUo2xUWPaDAKapAWCw-Tki7V-aAs="


# ==================== westock 数据获取 ====================

def cli(cmd: str) -> str:
    """执行 westock CLI"""
    full_cmd = f"npx -y westock-data-skillhub@1.0.3 {cmd} 2>/dev/null"
    try:
        r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=60)
        return r.stdout
    except:
        return ""


def parse_table(md: str) -> list[dict]:
    """解析Markdown表格"""
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
    for k in keys:
        if k in row:
            return row[k]
    return ""


def safe_float(v, default=0.0) -> float:
    if not v or v == '-':
        return default
    try:
        return float(str(v).replace('%', '').replace('+', '').replace(',', ''))
    except:
        return default


# ==================== 10维评分 ====================

class StockEvaluator:
    """个股综合评分卡"""
    
    def __init__(self, code: str, stock_name: str = "", eval_date: str = None):
        # 标准化代码
        self.code = code
        self.name = stock_name
        self.eval_date = eval_date or datetime.now().strftime("%Y-%m-%d")
        
        # 原始数据缓存
        self._kline_day = None
        self._technical = None
        self._asfund = None
        self._board_info = None
        
        # 10维评分
        self.scores = {
            "大盘兼容性": {"score": 0, "max": 10, "detail": ""},
            "板块强度": {"score": 0, "max": 10, "detail": ""},
            "技术形态": {"score": 0, "max": 15, "detail": ""},
            "资金动向": {"score": 0, "max": 15, "detail": ""},
            "趋势强度": {"score": 0, "max": 15, "detail": ""},
            "基本面": {"score": 0, "max": 10, "detail": ""},
            "筹码结构": {"score": 0, "max": 10, "detail": ""},
            "信号共振": {"score": 0, "max": 10, "detail": ""},
            "风险等级": {"score": 0, "max": 5, "detail": ""},
        }
        
        # 新增：过滤信息和仓位建议
        self.filter_result = {"allowed": True, "pool": "主板", "reason": ""}
        self.position_action = "观望"
        self.position_reason = ""
        self.total = 0
        self.max_total = 100
        self.level = ""
        self.advice = ""
        self.system_match = ""
        self.details = {}  # 存储评分过程的详细数据
    
    def fetch_data(self):
        """获取所有必要数据"""
        raw_code = self.code
        if len(raw_code) == 6:
            if raw_code.startswith('6'):
                raw_code = f"sh{raw_code}"
            else:
                raw_code = f"sz{raw_code}"
        
        # 日K线（最近20日）
        self._kline_day = parse_table(cli(f"kline {raw_code} --period day --limit 20"))
        
        # 技术指标
        self._technical = parse_table(cli(f"technical {raw_code} --group all"))
        
        # 资金流向
        self._asfund = parse_table(cli(f"asfund {raw_code}"))
        
        # 板块信息
        self._board_info = parse_table(cli(f"hot board --limit 15"))
        
        # 获取股票名称（如果未提供）
        if not self.name and self._kline_day:
            for row in self._kline_day:
                n = get_val(row, "名称", "name")
                if n:
                    self.name = n
                    break
    
    def _get_price_data(self) -> dict:
        """从K线提取价格数据"""
        result = {"close": 0, "open": 0, "high": 0, "low": 0,
                  "ma5": 0, "ma10": 0, "ma20": 0, "ma60": 0,
                  "volume_ratio": 1, "amplitude_pct": 0}
        
        rows = self._kline_day
        if not rows:
            return result
        
        try:
            # 最新一条
            r0 = rows[0]
            result["close"] = safe_float(get_val(r0, "收盘", "收盘价", "close", "last"))
            result["open"] = safe_float(get_val(r0, "开盘", "open"))
            result["high"] = safe_float(get_val(r0, "最高", "high"))
            result["low"] = safe_float(get_val(r0, "最低", "low"))
            result["volume"] = safe_float(get_val(r0, "成交量", "volume"))
            
            # 均线计算（从K线序列中取收盘价计算）
            closes = []
            for r in rows:
                c = safe_float(get_val(r, "收盘", "收盘价", "close", "last"))
                if c > 0:
                    closes.append(c)
            
            if len(closes) >= 5:
                result["ma5"] = sum(closes[:5]) / 5
            if len(closes) >= 10:
                result["ma10"] = sum(closes[:10]) / 10
            if len(closes) >= 20:
                result["ma20"] = sum(closes[:20]) / 20
            if len(closes) >= 2:
                result["amplitude_pct"] = (max(closes) - min(closes)) / min(closes) * 100 if min(closes) > 0 else 0
            
            # 量比（当日量 / 前5日均量）
            if len(closes) >= 6:
                vols = []
                for r in rows:
                    v = safe_float(get_val(r, "成交量", "volume"))
                    if v > 0:
                        vols.append(v)
                if len(vols) >= 6:
                    avg_vol_5d = sum(vols[1:6]) / 5
                    result["volume_ratio"] = vols[0] / avg_vol_5d if avg_vol_5d > 0 else 1
                    
        except (IndexError, ZeroDivisionError):
            pass
        
        return result
    
    def _get_technical_data(self) -> dict:
        """从技术指标提取数据"""
        result = {"macd_dif": 0, "macd_dea": 0, "macd": 0,
                  "rsi_6": 50, "kdj_k": 50, "kdj_d": 50,
                  "boll_mid": 0, "boll_up": 0, "boll_dn": 0}
        
        if not self._technical:
            return result
        
        try:
            row = self._technical[0]
            result["macd_dif"] = safe_float(get_val(row, "macd.DIF", "DIF"))
            result["macd_dea"] = safe_float(get_val(row, "macd.DEA", "DEA"))
            result["macd"] = result["macd_dif"] - result["macd_dea"]
            result["rsi_6"] = safe_float(get_val(row, "rsi.RSI_6", "RSI_6"), 50)
            result["kdj_k"] = safe_float(get_val(row, "kdj.K", "K"), 50)
            result["kdj_d"] = safe_float(get_val(row, "kdj.D", "D"), 50)
        except:
            pass
        
        return result
    
    def _get_fund_data(self) -> dict:
        """从资金流向提取数据"""
        result = {"main_net_flow": 0, "main_net_flow_5d": 0,
                  "main_in_flow": 0, "main_out_flow": 0}
        
        if not self._asfund:
            return result
        
        try:
            row = self._asfund[0]
            result["main_net_flow"] = safe_float(get_val(row, "MainNetFlow", "main_net_flow"))
            result["main_net_flow_5d"] = safe_float(get_val(row, "MainNetFlow5D", "main_net_flow_5d"))
            result["main_in_flow"] = safe_float(get_val(row, "MainInFlow", "main_in_flow"))
            result["main_out_flow"] = safe_float(get_val(row, "MainOutFlow", "main_out_flow"))
        except:
            pass
        
        return result
    
    def _get_board_data(self) -> dict:
        """查个股所属板块"""
        result = {"board_name": "", "board_rank": 99, "board_zdf": 0}
        
        if not self._board_info:
            return result
        
        # 从搜索信息获取（简化：用第一个板块）
        # 实际应通过 search 或其它API查所属板块
        try:
            for i, row in enumerate(self._board_info, 1):
                name = get_val(row, "板块名称", "name")
                if name:
                    result["board_name"] = name
                    result["board_rank"] = i
                    result["board_zdf"] = safe_float(get_val(row, "涨跌幅", "zdf"))
                    break
        except:
            pass
        
        return result
    
    # ========== 各维度评分 ==========
    
    def score_market_compat(self, price: dict, tech: dict):
        """① 大盘兼容性 (0-10)"""
        # 简化：基于当前MACD状态做温度推断
        dif = tech["macd_dif"]
        macd = tech["macd"]
        
        score = 5  # 默认中等
        detail = ""
        
        if dif > 0 and macd > 0:
            score = 8
            detail = "MACD零上+红柱，多头环境，兼容大多数交易风格"
        elif dif > 0 > macd:
            score = 6
            detail = "MACD零上但柱体翻绿，短期回调中，适合回踩低吸"
        elif dif < 0 and macd < 0 and macd > -1:
            score = 4
            detail = "MACD零下，空头环境，仅适合底部背离潜伏"
        elif dif < 0 and macd < -1:
            score = 2
            detail = "MACD深度零下，强烈空头，不建议操作"
        
        # RSI超卖加分
        rsi = tech["rsi_6"]
        if rsi < 30:
            score += 1
            detail += "；RSI<30超卖，下跌空间有限"
        
        self.scores["大盘兼容性"] = {"score": min(score, 10), "max": 10, "detail": detail}
    
    def score_board(self, board: dict):
        """② 板块强度 (0-10)"""
        score = 3
        detail = ""
        
        rank = board["board_rank"]
        zdf = board["board_zdf"]
        
        if rank <= 3 and zdf > 0:
            score = 9
            detail = f"板块排名TOP{rank}(+{zdf:.2f}%)，资金聚焦方向"
        elif rank <= 5 and zdf > 0:
            score = 7
            detail = f"板块排名TOP{rank}(+{zdf:.2f}%)，较强"
        elif rank <= 10:
            score = 5
            detail = f"板块排名TOP{rank}，中等"
        elif zdf > 0:
            score = 4
            detail = "板块上涨但非热点"
        else:
            score = 2
            detail = "板块下跌，缺乏资金关注"
        
        if board["board_name"]:
            detail = f"[{board['board_name']}] " + detail
        else:
            detail = "板块信息未获取到，按中性评分"
        
        self.scores["板块强度"] = {"score": min(score, 10), "max": 10, "detail": detail}
    
    def score_technical(self, price: dict, tech: dict):
        """③ 技术形态 (0-15) — 鱼身三模式"""
        dif = tech["macd_dif"]
        dea = tech["macd_dea"]
        macd = tech["macd"]
        close = price["close"]
        ma5 = price["ma5"]
        ma10 = price["ma10"]
        ma20 = price["ma20"]
        vol_ratio = price["volume_ratio"]
        
        score = 3
        detail = ""
        pattern = ""
        
        # 判断均线排列
        bull_arrange = ma5 > ma10 > ma20 if ma10 > 0 and ma20 > 0 else False
        
        # 模式1: 空中加油（MACD零上+DIF回踩DEA不破+柱翻红）
        if dif > 0 and dea > 0 and dif >= dea * 0.98 and dif <= dea * 1.05:
            if macd > 0:
                score = 15
                pattern = "⭐空中加油"
                detail = f"MACD零上金叉附近+DIF回踩DEA，空中加油形态"
        
        # 模式2: 均线回踩（多头排列+缩量回调至MA10/MA20）
        elif bull_arrange and macd < 0 and vol_ratio < 0.8:
            if close >= ma20 * 0.97 and close <= ma20 * 1.03:
                score = 13
                pattern = "📍均线回踩"
                detail = f"多头排列+缩量回踩MA20({ma20:.2f})，均线回踩买点"
            elif close >= ma10 * 0.97 and close <= ma10 * 1.03:
                score = 12
                pattern = "📍均线回踩"
                detail = f"多头排列+缩量回踩MA10({ma10:.2f})，短线回踩买点"
        
        # 模式3: 箱体突破（放量突破前高）
        elif bull_arrange and vol_ratio >= 1.5 and macd > 0:
            score = 12
            pattern = "🚀箱体突破"
            detail = f"放量(量比{vol_ratio:.1f}x)+MACD红柱，突破形态"
        
        # 常规多头
        elif bull_arrange:
            score = 7
            detail = "均线多头排列，无明确买点信号"
        
        # 空头
        elif dif < 0 and dea < 0:
            score = 2
            detail = "MACD零下+均线空头，规避"
        
        # RSI超卖反弹潜力
        if tech["rsi_6"] < 30 and score < 5:
            score = max(score, 4)
            detail += "；RSI<30超卖，可能有反弹"
        
        self.details["pattern"] = pattern
        self.scores["技术形态"] = {"score": min(score, 15), "max": 15, "detail": detail}
    
    def score_fund(self, fund: dict):
        """④ 资金动向 (0-15)"""
        net = fund["main_net_flow"]
        net_5d = fund["main_net_flow_5d"]
        
        score = 3
        detail = ""
        
        if net > 1e8:  # >1亿
            score = 13
            detail = f"主力净流入+{net/1e8:.1f}亿，大资金积极买入"
        elif net > 0:
            score = 9
            detail = f"主力净流入+{net/1e4:.0f}万，资金偏多"
        elif net > -1e7:
            score = 6
            detail = f"主力净流出{abs(net)/1e4:.0f}万，流出不大"
        elif net > -1e8:
            score = 4
            detail = f"主力净流出{abs(net)/1e8:.1f}亿，资金出逃"
        else:
            score = 1
            detail = f"主力大幅流出{abs(net)/1e8:.1f}亿，严重失血"
        
        # 5日累计加分
        if net_5d > 5e8:
            score += 2
            detail += "；5日累计净流入强劲"
        elif net_5d < -5e8:
            score -= 1
            detail += "；5日累计大幅流出"
        
        self.scores["资金动向"] = {"score": max(0, min(score, 15)), "max": 15, "detail": detail}
    
    def score_trend(self, price: dict, tech: dict):
        """⑤ 趋势强度 (0-15) — 猛兽OVS浓缩"""
        dif = tech["macd_dif"]
        macd = tech["macd"]
        close = price["close"]
        ma20 = price["ma20"]
        vol_ratio = price["volume_ratio"]
        rsi = tech["rsi_6"]
        
        score = 4
        detail = ""
        
        # 突破确认
        has_breakthrough = close > ma20 * 1.05 and vol_ratio > 1.3 if ma20 > 0 else False
        # 高阳模式：近3日涨幅>8%
        has_high_yang = False
        if len(self._kline_day) >= 4:
            try:
                c_latest = safe_float(get_val(self._kline_day[0], "收盘", "close", "last"))
                c_3d_ago = safe_float(get_val(self._kline_day[3], "收盘", "close", "last"))
                if c_3d_ago > 0:
                    has_high_yang = (c_latest / c_3d_ago - 1) * 100 > 8
            except:
                pass
        
        # RSVA简化：RSI稳定性
        rsva_strong = 50 < rsi < 70 and macd > 0
        
        if has_breakthrough and has_high_yang:
            score = 14
            detail = "突破新高+高阳推升，强势趋势确认"
        elif has_breakthrough:
            score = 10
            detail = f"放量突破MA20+{vol_ratio:.1f}x，突破信号"
        elif has_high_yang:
            score = 9
            detail = "高阳模式(近3日涨>8%)，短线强势"
        elif rsva_strong:
            score = 7
            detail = "RSI中位区+MACD红柱，趋势健康"
        elif dif > 0:
            score = 5
            detail = "MACD零上，趋势偏多"
        else:
            detail = "MACD零下，趋势偏空"
        
        self.scores["趋势强度"] = {"score": min(score, 15), "max": 15, "detail": detail}
    
    def score_fundamental(self):
        """⑥ 基本面 (0-10)"""
        # 简化：通过westock获取基本面数据较慢，先做占位
        # 完整版应调 financial 接口
        score = 5  # 默认中性
        detail = "基本面数据需通过financial接口补充（暂用默认中性评分）"
        
        # 尝试获取净利润数据
        raw_code = self.code
        if len(raw_code) == 6:
            if raw_code.startswith('6'):
                raw_code = f"sh{raw_code}"
            else:
                raw_code = f"sz{raw_code}"
        
        fin_raw = cli(f"financial {raw_code} --report income --limit 2")
        if fin_raw and len(fin_raw) > 100:
            # 简化的净利润判断
            if "净利润" in fin_raw or "net_profit" in fin_raw.lower():
                score = 7
                detail = "有净利润数据，默认正向"
        
        self.scores["基本面"] = {"score": score, "max": 10, "detail": detail}
    
    def score_chip(self, price: dict, tech: dict):
        """⑦ 筹码结构 (0-10) — VCP+支撑"""
        close = price["close"]
        ma20 = price["ma20"]
        amplitude = price["amplitude_pct"]
        rsi = tech["rsi_6"]
        
        score = 3
        detail = ""
        
        # VCP收缩判断：近期振幅缩小
        vcp_contract = amplitude < 20 if amplitude > 0 else False
        
        # 支撑位判断
        has_support = ma20 > 0 and close >= ma20 * 0.95 and close <= ma20 * 1.05
        
        if vcp_contract and has_support:
            score = 9
            detail = f"VCP收缩+价格在MA20({ma20:.2f})附近，支撑明确"
        elif has_support:
            score = 6
            detail = f"价格在MA20({ma20:.2f})支撑附近"
        elif vcp_contract:
            score = 5
            detail = "VCP收缩中，但尚未触及支撑位"
        else:
            detail = "无明显支撑结构"
        
        # RSI超卖=更好的低吸位
        if rsi < 30 and score >= 5:
            score += 1
            detail += "，RSI超卖提供额外安全边际"
        
        self.scores["筹码结构"] = {"score": min(score, 10), "max": 10, "detail": detail}
    
    def score_resonance(self, price: dict, tech: dict):
        """⑧ 信号共振 (0-10) — 多系统交集"""
        pattern = self.details.get("pattern", "")
        dif = tech["macd_dif"]
        macd = tech["macd"]
        vol_ratio = price["volume_ratio"]
        
        systems = 0
        signals = []
        
        # 双弦信号：偏多评分
        if dif > 0 and macd > 0:
            systems += 1
            signals.append("双弦偏多")
        
        # 猛兽信号：突破或高阳
        if pattern in ("🚀箱体突破", "⭐空中加油"):
            systems += 1
            signals.append(f"猛兽{pattern}")
        
        # 鱼身信号：回踩买点
        if pattern in ("📍均线回踩", "⭐空中加油"):
            systems += 1
            signals.append(f"鱼身{pattern}")
        
        # 强势信号：放量突破
        if vol_ratio >= 1.5 and macd > 0:
            systems += 1
            signals.append("强势放量")
        
        score_map = {0: 0, 1: 4, 2: 7, 3: 9, 4: 10}
        score = score_map.get(systems, 10)
        
        detail = f"{systems}个系统同向: {'+'.join(signals)}" if signals else "无系统信号"
        
        self.scores["信号共振"] = {"score": score, "max": 10, "detail": detail}
    
    def score_risk(self, price: dict, tech: dict):
        """⑨ 风险等级 (0-5)"""
        close = price["close"]
        ma20 = price["ma20"]
        vol_ratio = price["volume_ratio"]
        
        score = 2
        detail = ""
        
        # 止损幅度
        if ma20 > 0:
            stop_pct = abs(close - ma20) / close * 100
        else:
            stop_pct = 5  # 默认
        
        if stop_pct < 3:
            score = 5
            detail = f"止损幅度{stop_pct:.1f}%(MA20)，风险可控"
        elif stop_pct < 5:
            score = 4
            detail = f"止损幅度{stop_pct:.1f}%(MA20)，正常"
        elif stop_pct < 8:
            score = 2
            detail = f"止损幅度{stop_pct:.1f}%(MA20)，偏大"
        else:
            score = 1
            detail = f"止损幅度{stop_pct:.1f}%(MA20)，太大不宜操作"
        
        # 量比过大=风险
        if vol_ratio > 3:
            score -= 1
            detail += "；量比>3，警惕放量出货"
        
        self.scores["风险等级"] = {"score": max(0, min(score, 5)), "max": 5, "detail": detail}
    
    def match_system(self, price: dict, tech: dict):
        """⑩ 体系匹配 — 建议用哪套系统"""
        pattern = self.details.get("pattern", "")
        dif = tech["macd_dif"]
        close = price["close"]
        ma20 = price["ma20"]
        
        if close <= 10 and dif < 0:
            self.system_match = "🔗 双弦低吸（低价+震荡，进入月度股池候选）"
        elif pattern == "⭐空中加油":
            self.system_match = "🐟 鱼身/⚡强势（空中加油买点）"
        elif pattern == "📍均线回踩":
            self.system_match = "🐟 鱼身（均线回踩低吸）"
        elif pattern == "🚀箱体突破":
            self.system_match = "⚡强势体系（箱体突破追涨）"
        elif dif > 0 and ma20 > 0 and close > ma20:
            self.system_match = "🐅 猛兽体系（趋势跟踪）"
        elif close <= 10:
            self.system_match = "🔗 双弦月度股池候选"
        else:
            self.system_match = "⚠️ 当前无明确匹配系统，观望"
    
    def evaluate(self) -> dict:
        """执行完整10维评价"""
        self.fetch_data()
        
        price = self._get_price_data()
        tech = self._get_technical_data()
        fund = self._get_fund_data()
        board = self._get_board_data()
        
        self.score_market_compat(price, tech)
        self.score_board(board)
        self.score_technical(price, tech)
        self.score_fund(fund)
        self.score_trend(price, tech)
        self.score_fundamental()
        self.score_chip(price, tech)
        self.score_resonance(price, tech)
        self.score_risk(price, tech)
        self.match_system(price, tech)
        
        # 过滤规则检查
        self.filter_result = is_tradable(self.code, self.name)
        
        # 仓位建议（基于评分+大盘+形态的新增维度）
        total = self.total
        market_compat = self.scores["大盘兼容性"]["score"]
        
        if not self.filter_result["allowed"]:
            self.position_action = "不交易"
            self.position_reason = f"🚫 {self.filter_result['reason']}"
        elif total >= 80 and market_compat >= 7:
            self.position_action = "🔵加仓"
            self.position_reason = f"评分{total}+大盘兼容{market_compat}/10, 可加仓"
        elif total >= 65 and market_compat >= 5:
            self.position_action = "🟢买入/持有"
            self.position_reason = f"评分{total}, 正常仓位持有"
        elif total >= 50:
            self.position_action = "🟡轻仓/观望"
            self.position_reason = f"评分{total}偏低, 轻仓试错或等待"
        elif total >= 35:
            self.position_action = "🔴减仓"
            self.position_reason = f"评分{total}<50, 建议减仓"
        else:
            self.position_action = "⚫清仓/回避"
            self.position_reason = f"评分{total}<35, 回避"
        
        # === 主升浪五维判定（基于已有10维评分聚合） ===
        # 条件1:大盘兼容 ≥6/10
        cond1 = self.scores["大盘兼容性"]["score"] >= 6
        # 条件2:板块强度 ≥6/10
        cond2 = self.scores["板块强度"]["score"] >= 6
        # 条件3:技术形态 ≥12/15 (空中加油/箱体突破)
        cond3 = self.scores["技术形态"]["score"] >= 12
        # 条件4:量价确认 ≥12/20 (放量+趋势强度叠加判断)
        cond4 = self.scores["趋势强度"]["score"] + self.scores["风险等级"]["score"] >= 15
        # 条件5:赛道持续 ≥8/10
        cond5 = self.scores["筹码结构"]["score"] + self.scores["信号共振"]["score"] >= 12
        
        conds_met = sum([cond1, cond2, cond3, cond4, cond5])
        self.main_wave_level = ""
        self.main_wave_detail = ""
        
        detail_parts = []
        detail_parts.append(f"大盘{'✅' if cond1 else '❌'}({self.scores['大盘兼容性']['score']}/10)")
        detail_parts.append(f"板块{'✅' if cond2 else '❌'}({self.scores['板块强度']['score']}/10)")
        detail_parts.append(f"技术{'✅' if cond3 else '❌'}({self.scores['技术形态']['score']}/15)")
        detail_parts.append(f"量价{'✅' if cond4 else '❌'}()")
        detail_parts.append(f"赛道{'✅' if cond5 else '❌'}()")
        
        if conds_met == 5:
            self.main_wave_level = "🔥主升浪"
            self.main_wave_detail = "5/5全部达标: 大盘稳定+板块聚焦+技术启动+放量确认+赛道持续"
        elif conds_met >= 4:
            self.main_wave_level = "🟢主升浪候选"
            self.main_wave_detail = f"{conds_met}/5达标, 接近主升浪启动"
        elif conds_met >= 3:
            self.main_wave_level = "🟡观察"
            self.main_wave_detail = f"{conds_met}/5达标, 需等待条件完善"
        else:
            self.main_wave_level = "⚪非主升浪"
            self.main_wave_detail = f"{conds_met}/5达标, 不具备主升浪条件"
        
        # 计算总分
        self.total = sum(v["score"] for v in self.scores.values())
        
        # 等级
        if self.total >= 85:
            self.level = "🔥强烈关注"
            self.advice = "优先操作，可标准仓位介入"
        elif self.total >= 70:
            self.level = "✅关注"
            self.advice = "可纳入观察，半仓试错"
        elif self.total >= 50:
            self.level = "⚠️一般"
            self.advice = "观望，等条件改善后轻仓试错"
        elif self.total >= 30:
            self.level = "🔴回避"
            self.advice = "不操作，如有持仓考虑减仓"
        else:
            self.level = "⚫危险"
            self.advice = "如有持仓应止损"
        
        return self.to_dict()
    
    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "date": self.eval_date,
            "total": self.total,
            "max_total": self.max_total,
            "level": self.level,
            "advice": self.advice,
            "system_match": self.system_match,
            "position_action": self.position_action,
            "position_reason": self.position_reason,
            "main_wave_level": self.main_wave_level,
            "main_wave_detail": self.main_wave_detail,
            "filter_pool": self.filter_result["pool"],
            "filter_allowed": self.filter_result["allowed"],
            "pattern": self.details.get("pattern", ""),
            "scores": self.scores,
        }
    
    def to_markdown(self) -> str:
        """输出Markdown格式评分卡"""
        d = self.to_dict()
        
        lines = []
        lines.append("---")
        lines.append("")
        lines.append(f"## 📋 个股综合评分卡")
        lines.append("")
        lines.append(f"**{d['name']} ({d['code']})** · {d['date']} · **{d['level']}** ({d['total']}/{d['max_total']}分)")
        lines.append("")
        lines.append(f"> {d['advice']}")
        lines.append("")
        lines.append("| 维度 | 得分 | 满分 | 说明 |")
        lines.append("|:----|:---:|:----:|:-----|")
        
        for name, info in d['scores'].items():
            bar = "█" * int(info['score'] / info['max'] * 10) if info['max'] > 0 else ""
            lines.append(f"| {name} | {info['score']} | {info['max']} | {info['detail']} |")
        
        lines.append("")
        lines.append(f"**信号形态**: {d['pattern'] or '无明确信号'}")
        lines.append("")
        lines.append(f"**推荐系统**: {d['system_match']}")
        lines.append("")
        
        # 操作建议表
        lines.append("### 🎯 操作建议")
        lines.append("")
        lines.append(f"| 项目 | 内容 |")
        lines.append(f"|:----|:-----|")
        lines.append(f"| 综合评分 | {d['total']}/{d['max_total']} |")
        lines.append(f"| 关注等级 | {d['level']} |")
        lines.append(f"| 操作建议 | {d['advice']} |")
        lines.append(f"| 信号形态 | {d['pattern'] or '无'} |")
        lines.append(f"| 适用系统 | {d['system_match']} |")
        if self.main_wave_level:
            lines.append(f"| 主升浪判定 | {self.main_wave_level} |")
            lines.append(f"| 判定明细 | {self.main_wave_detail} |")
        lines.append(f"| 仓位建议 | {self.position_action} |")
        lines.append(f"| 仓位理由 | {self.position_reason} |")
        lines.append(f"| 交易资格 | ✅ {self.filter_result['pool']} |" if self.filter_result['allowed'] else f"| 交易资格 | 🚫 {self.filter_result['pool']}: {self.filter_result['reason']} |")
        
        # 止损参考
        price_data = self._get_price_data()
        if price_data["ma20"] > 0:
            stop_price = price_data["ma20"] * 0.97
            lines.append(f"| 参考止损 | {stop_price:.2f} (MA20下方3%) |")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*数据来源：westock-data | 评分基于统一交易体系v3.0*")
        
        return "\n".join(lines)


# ==================== 主入口 ====================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="个股综合评分卡")
    parser.add_argument("codes", help="股票代码（多个用逗号分隔）")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="评价日期")
    parser.add_argument("--batch", action="store_true", help="批量模式，同时评价多只")
    args = parser.parse_args()
    
    codes = [c.strip() for c in args.codes.split(",")]
    
    for code in codes:
        ev = StockEvaluator(code, eval_date=args.date)
        result = ev.evaluate()
        print(ev.to_markdown())


if __name__ == "__main__":
    main()
