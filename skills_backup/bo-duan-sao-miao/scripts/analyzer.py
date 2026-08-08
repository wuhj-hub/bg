"""
===========================================
  🎯 股票短线操盘分析系统 v1.0
  聚焦 3-15 个交易日 | Loop Skill
===========================================
"""

import urllib.request
import json as json_lib
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import warnings
warnings.filterwarnings('ignore')

# ============================================
# 配置区 - 可自定义参数
# ============================================
CONFIG = {
    # 默认关注的股票池（可替换为你感兴趣的股票代码）
    "watch_list": {
        "600309": "万华化学",
        "002709": "天赐材料",
        "300870": "欧陆通",
        "300153": "科泰电源",
        "300274": "阳光电源",
        "300308": "中际旭创",
        "300738": "奥飞数据",
        "300418": "昆仑万维",
        "300687": "赛意信息",
        "300827": "上能电气",
        "300476": "胜宏科技",
        "601869": "长飞光纤",
        "002281": "光迅科技",
        "688668": "鼎通科技",
        "002585": "双星新材",
        "002859": "洁美科技",
        "688256": "寒武纪",
        "002466": "天齐锂业",
        "301308": "江波龙",
        "688191": "智洋创新",
        "002049": "紫光国微",
        "002594": "比亚迪",
        # --- 新增自选股（2026-06-10）---
        "300124": "汇川技术",
        "301565": "中仑新材",
        "002017": "东信和平",
        "300339": "润和软件",
        "301205": "联特科技",
        "300088": "长信科技",
        "300264": "佳创视讯",
        "300115": "长盈精密",
        "688039": "当虹科技",
        "688498": "源杰科技",
        "000933": "神火股份",
        "000021": "深科技",
        "301336": "趣睡科技",
        "300058": "蓝色光标",
        "300502": "新易盛",
        "603083": "剑桥科技",
        "001356": "富岭股份",
        "603986": "兆易创新",
    },
    # 短线参数
    "short_term_days": 15,    # 短线操作上限天数
    "min_term_days": 3,       # 短线操作下限天数
    "lookback_days": 120,     # 回溯天数（用于计算指标）
    # 止损止盈（单只）
    "stop_loss_pct": -0.07,   # 单只止损线 -7%
    "take_profit_pct": 0.14,  # 单只止盈线 +14%（盈亏比 2:1）
    # 组合风控
    "portfolio_stop_loss_pct": -0.05,  # 组合总止损线 -5%（3只同时亏损的硬止损）
    "batch_take_profit": True,          # 分批止盈：首只触达+14%时平一半
}

# ============================================
# 技术指标计算模块
# ============================================

def calc_ma(df):
    """移动平均线 MA5/MA10/MA20"""
    df['MA5'] = df['收盘'].rolling(5).mean()
    df['MA10'] = df['收盘'].rolling(10).mean()
    df['MA20'] = df['收盘'].rolling(20).mean()
    return df

def calc_macd(df, fast=12, slow=26, signal=9):
    """MACD 指标"""
    ema_fast = df['收盘'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['收盘'].ewm(span=slow, adjust=False).mean()
    df['DIF'] = ema_fast - ema_slow
    df['DEA'] = df['DIF'].ewm(span=signal, adjust=False).mean()
    df['MACD'] = 2 * (df['DIF'] - df['DEA'])
    return df

def calc_rsi(df, period=14):
    """RSI 相对强弱指数"""
    delta = df['收盘'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def calc_kdj(df, n=9, m1=3, m2=3):
    """KDJ 随机指标"""
    low_n = df['最低'].rolling(window=n).min()
    high_n = df['最高'].rolling(window=n).max()
    rsv = (df['收盘'] - low_n) / (high_n - low_n) * 100
    
    df['K'] = rsv.ewm(com=m1 - 1, adjust=False).mean()
    df['D'] = df['K'].ewm(com=m2 - 1, adjust=False).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    return df

def calc_bollinger(df, period=20, std_dev=2):
    """布林带"""
    df['BOLL_MID'] = df['收盘'].rolling(period).mean()
    rolling_std = df['收盘'].rolling(period).std()
    df['BOLL_UP'] = df['BOLL_MID'] + std_dev * rolling_std
    df['BOLL_DN'] = df['BOLL_MID'] - std_dev * rolling_std
    return df

def calc_volume_features(df):
    """量价分析"""
    df['VOL_MA5'] = df['成交量'].rolling(5).mean()
    df['VOL_MA10'] = df['成交量'].rolling(10).mean()
    df['VOL_RATIO'] = df['成交量'] / df['VOL_MA5']  # 量比
    return df

def calc_all_indicators(df):
    """计算所有技术指标"""
    df = calc_ma(df)
    df = calc_macd(df)
    df = calc_rsi(df)
    df = calc_kdj(df)
    df = calc_bollinger(df)
    df = calc_volume_features(df)
    return df

# ============================================
# 短线信号评分系统 (0-100)
# ============================================

def score_stock(df):
    """
    对最新一根K线进行短线评分
    返回: (总分, 信号详情dict)
    """
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    score = 50  # 基准分50
    signals = {}
    
    # --- 1. 均线多头排列 (权重 15) ---
    ma_score = 0
    if latest['MA5'] > latest['MA10'] > latest['MA20']:
        ma_score = 15
        signals['均线'] = "✅ 多头排列 (MA5>MA10>MA20)"
    elif latest['MA5'] < latest['MA10'] < latest['MA20']:
        ma_score = -15
        signals['均线'] = "❌ 空头排列 (MA5<MA10<MA20)"
    elif latest['收盘'] > latest['MA5']:
        ma_score = 8
        signals['均线'] = "⚡ 站上MA5，偏多"
    else:
        ma_score = -5
        signals['均线'] = "⚠️ 在MA5下方，偏空"
    score += ma_score
    
    # --- 2. MACD 金叉/死叉 (权重 15) ---
    macd_score = 0
    if prev['DIF'] <= prev['DEA'] and latest['DIF'] > latest['DEA']:
        macd_score = 15
        signals['MACD'] = "🔥 金叉！买入信号"
    elif prev['DIF'] >= prev['DEA'] and latest['DIF'] < latest['DEA']:
        macd_score = -15
        signals['MACD'] = "💀 死叉！卖出信号"
    elif latest['DIF'] > latest['DEA'] and latest['MACD'] > 0:
        macd_score = 8
        signals['MACD'] = "📈 DIF>DEA，红柱放大"
    elif latest['DIF'] > latest['DEA']:
        macd_score = 5
        signals['MACD'] = "📈 DIF>DEA，多头趋势"
    elif latest['MACD'] < 0 and latest['MACD'] > prev['MACD']:
        macd_score = 3
        signals['MACD'] = "🔄 绿柱缩短，有企稳迹象"
    else:
        macd_score = -5
        signals['MACD'] = "📉 DIF<DEA，空头趋势"
    score += macd_score
    
    # --- 3. RSI 超买超卖 (权重 10) ---
    rsi_val = latest['RSI']
    if rsi_val < 30:
        rsi_score = 10
        signals['RSI'] = f"🟢 RSI={rsi_val:.1f} 超卖区，反弹机会"
    elif rsi_val < 40:
        rsi_score = 5
        signals['RSI'] = f"🟡 RSI={rsi_val:.1f} 偏弱区"
    elif rsi_val > 80:
        rsi_score = -10
        signals['RSI'] = f"🔴 RSI={rsi_val:.1f} 超买区，注意回调"
    elif rsi_val > 70:
        rsi_score = -5
        signals['RSI'] = f"🟠 RSI={rsi_val:.1f} 偏强区，追高有风险"
    else:
        rsi_score = 0
        signals['RSI'] = f"⚪ RSI={rsi_val:.1f} 中性区"
    score += rsi_score
    
    # --- 4. KDJ 金叉/死叉 (权重 10) ---
    kdj_score = 0
    if prev['K'] <= prev['D'] and latest['K'] > latest['D'] and latest['J'] < 20:
        kdj_score = 10
        signals['KDJ'] = f"🔥 低位金叉！K={latest['K']:.1f} D={latest['D']:.1f} J={latest['J']:.1f}"
    elif prev['K'] >= prev['D'] and latest['K'] < latest['D'] and latest['J'] > 80:
        kdj_score = -10
        signals['KDJ'] = f"💀 高位死叉！K={latest['K']:.1f} D={latest['D']:.1f} J={latest['J']:.1f}"
    elif latest['J'] < 0:
        kdj_score = 8
        signals['KDJ'] = f"🟢 J值={latest['J']:.1f} 极度超卖"
    elif latest['J'] > 100:
        kdj_score = -8
        signals['KDJ'] = f"🔴 J值={latest['J']:.1f} 极度超买"
    else:
        kdj_score = 0
        signals['KDJ'] = f"⚪ K={latest['K']:.1f} D={latest['D']:.1f} J={latest['J']:.1f}"
    score += kdj_score
    
    # --- 5. 布林带位置 (权重 10) ---
    boll_pos = (latest['收盘'] - latest['BOLL_DN']) / (latest['BOLL_UP'] - latest['BOLL_DN'])
    if boll_pos < 0.1:
        boll_score = 10
        signals['布林'] = f"🟢 触及下轨 (位置{boll_pos:.0%})，超卖反弹"
    elif boll_pos < 0.3:
        boll_score = 5
        signals['布林'] = f"🟡 靠近下轨 (位置{boll_pos:.0%})"
    elif boll_pos > 0.9:
        boll_score = -10
        signals['布林'] = f"🔴 触及上轨 (位置{boll_pos:.0%})，注意压力"
    elif boll_pos > 0.7:
        boll_score = -3
        signals['布林'] = f"🟠 靠近上轨 (位置{boll_pos:.0%})"
    else:
        boll_score = 0
        signals['布林'] = f"⚪ 中轨附近 (位置{boll_pos:.0%})"
    score += boll_score
    
    # --- 6. 量价配合 (权重 10) ---
    vol_ratio = latest['VOL_RATIO']
    price_chg = (latest['收盘'] - prev['收盘']) / prev['收盘']
    if vol_ratio > 1.5 and price_chg > 0.01:
        vol_score = 10
        signals['量价'] = f"🔥 放量上涨！量比{vol_ratio:.2f}，涨幅{price_chg:.2%}"
    elif vol_ratio > 1.5 and price_chg < -0.01:
        vol_score = -10
        signals['量价'] = f"💀 放量下跌！量比{vol_ratio:.2f}，跌幅{price_chg:.2%}"
    elif vol_ratio < 0.7 and price_chg < -0.01:
        vol_score = 5
        signals['量价'] = f"🟡 缩量下跌，量比{vol_ratio:.2f}，抛压减轻"
    elif vol_ratio < 0.7 and price_chg > 0:
        vol_score = -3
        signals['量价'] = f"⚠️ 缩量上涨，量比{vol_ratio:.2f}，上涨乏力"
    else:
        vol_score = 0
        signals['量价'] = f"⚪ 量比{vol_ratio:.2f}，量价正常"
    score += vol_score
    
    # --- 7. 趋势动量 (权重 10) ---
    # 近5日涨幅
    if len(df) >= 6:
        pct_5d = (latest['收盘'] - df.iloc[-6]['收盘']) / df.iloc[-6]['收盘']
        if 0.03 < pct_5d < 0.08:
            mom_score = 8
            signals['动量'] = f"📈 5日涨{pct_5d:.2%}，健康上行"
        elif pct_5d > 0.12:
            mom_score = -5
            signals['动量'] = f"⚠️ 5日涨{pct_5d:.2%}，短期涨幅过大"
        elif pct_5d < -0.08:
            mom_score = 5
            signals['动量'] = f"🟢 5日跌{pct_5d:.2%}，可能超跌反弹"
        elif pct_5d < -0.03:
            mom_score = -3
            signals['动量'] = f"📉 5日跌{pct_5d:.2%}，弱势"
        else:
            mom_score = 0
            signals['动量'] = f"⚪ 5日变动{pct_5d:.2%}，震荡整理"
        score += mom_score
    
    # 限制总分在 0-100 之间
    score = max(0, min(100, score))
    
    return score, signals

# ============================================
# 买卖点建议生成
# ============================================

def generate_advice(score, signals, latest, df=None):
    """根据评分生成操作建议（含买卖价位标识）"""
    price = latest['收盘']
    stop_loss = price * (1 + CONFIG['stop_loss_pct'])
    take_profit = price * (1 + CONFIG['take_profit_pct'])
    
    if score >= 75:
        action = "🟢 强烈买入"
        detail = "多项指标共振看多，建议积极介入"
        position = "建议仓位: 30-50%"
    elif score >= 60:
        action = "🟡 轻仓试探"
        detail = "偏多信号，可小仓位布局"
        position = "建议仓位: 15-25%"
    elif score >= 45:
        action = "⚪ 观望等待"
        detail = "信号不明确，建议等待方向明朗"
        position = "建议仓位: 0% (空仓观望)"
    elif score >= 30:
        action = "🟠 谨慎减仓"
        detail = "偏空信号，持仓者考虑减仓"
        position = "建议仓位: 逐步降至10%以下"
    else:
        action = "🔴 建议清仓"
        detail = "多项指标共振看空，建议离场"
        position = "建议仓位: 0% (清仓)"
    
    advice = {
        '操作建议': action,
        '分析摘要': detail,
        '仓位建议': position,
        '当前价格': f"¥{price:.2f}",
        '止损价位': f"¥{stop_loss:.2f} ({CONFIG['stop_loss_pct']:.0%})",
        '止盈价位': f"¥{take_profit:.2f} ({CONFIG['take_profit_pct']:.0%})",
        '操作周期': f"{CONFIG['min_term_days']}-{CONFIG['short_term_days']}个交易日",
    }
    
    # ===== 买入/卖出价位标识（仅评分≥60的关注标的） =====
    if score >= 60 and df is not None and len(df) >= 20:
        ma5 = latest['MA5'] if pd.notna(latest['MA5']) else None
        ma10 = latest['MA10'] if pd.notna(latest['MA10']) else None
        ma20 = latest['MA20'] if pd.notna(latest['MA20']) else None
        boll_mid = latest['BOLL_MID'] if pd.notna(latest['BOLL_MID']) else None
        boll_up = latest['BOLL_UP'] if pd.notna(latest['BOLL_UP']) else None
        boll_dn = latest['BOLL_DN'] if pd.notna(latest['BOLL_DN']) else None
        high_20 = df['最高'].rolling(20).max().iloc[-1] if len(df) >= 20 else None
        low_20 = df['最低'].rolling(20).min().iloc[-1] if len(df) >= 20 else None
        
        # --- 判断信号类型 ---
        is_bullish_ma = ma5 is not None and ma10 is not None and ma20 is not None and ma5 > ma10 > ma20
        is_macd_bull = latest['DIF'] > latest['DEA']
        rsi_val = latest['RSI'] if pd.notna(latest['RSI']) else 50
        is_oversold = rsi_val < 30
        is_breakout = latest['涨跌幅'] >= 9.5 if '涨跌幅' in latest.index and pd.notna(latest['涨跌幅']) else False
        
        # --- 买入价位 ---
        buy_levels = []
        
        if is_bullish_ma:
            # 趋势延续型：回踩均线买入
            if ma10 is not None and ma10 < price:
                buy_levels.append(('①回踩MA10', ma10, (ma10 - price) / price * 100))
            if ma20 is not None and ma20 < price:
                buy_levels.append(('②回踩MA20', ma20, (ma20 - price) / price * 100))
            if boll_mid is not None and boll_mid < price:
                buy_levels.append(('③回踩布林中轨', boll_mid, (boll_mid - price) / price * 100))
        elif is_oversold:
            # 超跌反弹型：支撑位买入
            if boll_dn is not None:
                buy_levels.append(('①布林下轨', boll_dn, (boll_dn - price) / price * 100))
            if low_20 is not None:
                buy_levels.append(('②20日最低价', low_20, (low_20 - price) / price * 100))
            if ma20 is not None and ma20 < price:
                buy_levels.append(('③MA20支撑', ma20, (ma20 - price) / price * 100))
        elif is_breakout:
            # 涨停突破型：次日回踩确认
            if ma5 is not None and ma5 < price:
                buy_levels.append(('①回踩MA5确认', ma5, (ma5 - price) / price * 100))
            if ma10 is not None and ma10 < price:
                buy_levels.append(('②回踩MA10', ma10, (ma10 - price) / price * 100))
        else:
            # 混合型
            if ma10 is not None and ma10 < price:
                buy_levels.append(('①MA10支撑', ma10, (ma10 - price) / price * 100))
            if boll_mid is not None and boll_mid < price:
                buy_levels.append(('②布林中轨', boll_mid, (boll_mid - price) / price * 100))
            if ma20 is not None and ma20 < price:
                buy_levels.append(('③MA20支撑', ma20, (ma20 - price) / price * 100))
        
        # 去重并排序（距现价从近到远）
        seen = set()
        unique_buy = []
        for name, val, pct in buy_levels:
            key = f"{val:.2f}"
            if key not in seen and pct < 0:
                seen.add(key)
                unique_buy.append((name, val, pct))
        unique_buy.sort(key=lambda x: abs(x[2]))
        
        # 若无回踩买点，说明支撑位在上方，给出"现价可入"提示
        if not unique_buy:
            unique_buy.append(('现价可入(支撑在上方)', price, 0.0))
        
        # --- 卖出价位 ---
        sell_levels = []
        sell_levels.append(('①止损价', stop_loss, (stop_loss - price) / price * 100))
        
        if CONFIG.get('batch_take_profit', False):
            half_profit = price * (1 + CONFIG['take_profit_pct'] * 0.5)
            sell_levels.append(('②半仓止盈(+7%)', half_profit, (half_profit - price) / price * 100))
        
        sell_levels.append(('③全仓止盈(+14%)', take_profit, (take_profit - price) / price * 100))
        
        if boll_up is not None and boll_up > price:
            sell_levels.append(('④布林上轨压力', boll_up, (boll_up - price) / price * 100))
        if high_20 is not None and high_20 > price:
            sell_levels.append(('⑤20日最高价压力', high_20, (high_20 - price) / price * 100))
        
        # 去重
        seen_sell = set()
        unique_sell = []
        for name, val, pct in sell_levels:
            key = f"{val:.2f}"
            if key not in seen_sell:
                seen_sell.add(key)
                unique_sell.append((name, val, pct))
        
        # 信号类型标签
        if is_bullish_ma and is_macd_bull:
            signal_type = '📈趋势延续'
        elif is_oversold:
            signal_type = '🔄超跌反弹'
        elif is_breakout:
            signal_type = '🚀涨停突破'
        else:
            signal_type = '⚡混合信号'
        
        advice['信号类型'] = signal_type
        advice['买入价位'] = ' | '.join([f"{n}: ¥{v:.2f}({pct:+.1f}%)" for n, v, pct in unique_buy[:3]])
        advice['卖出价位'] = ' | '.join([f"{n}: ¥{v:.2f}({pct:+.1f}%)" for n, v, pct in unique_sell[:4]])
    
    return advice

# ============================================
# 数据获取 + 主分析流程
# ============================================

def fetch_stock_data(symbol):
    """获取单只股票的历史数据（腾讯财经API，前复权日线）"""
    # 判断交易所前缀
    if symbol.startswith('6'):
        prefix = 'sh'
    else:
        prefix = 'sz'
    
    count = CONFIG['lookback_days'] + 60
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{symbol},day,,,{count},qfq'
    
    req = urllib.request.Request(url, headers={'Referer': 'https://gu.qq.com'})
    time.sleep(0.3)  # 礼貌延迟，避免被限流
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json_lib.loads(resp.read())
    
    key = f'{prefix}{symbol}'
    klines = data['data'][key].get('qfqday', data['data'][key].get('day', []))
    
    if not klines:
        return None
    
    # 转换为DataFrame，格式：[日期, 开盘, 收盘, 最高, 最低, 成交量, (成交额)]
    # 不同股票返回列数可能不同（6或7列），只取前6列
    df = pd.DataFrame(klines).iloc[:, :6]
    df.columns = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
    df['开盘'] = df['开盘'].astype(float)
    df['收盘'] = df['收盘'].astype(float)
    df['最高'] = df['最高'].astype(float)
    df['最低'] = df['最低'].astype(float)
    df['成交量'] = df['成交量'].astype(float)
    df['涨跌幅'] = df['收盘'].pct_change() * 100
    
    return df

def analyze_single_stock(symbol, name):
    """分析单只股票"""
    try:
        df = fetch_stock_data(symbol)
        if df is None or len(df) < 30:
            return None
        
        df = calc_all_indicators(df)
        score, signals = score_stock(df)
        advice = generate_advice(score, signals, df.iloc[-1], df)
        
        return {
            '代码': symbol,
            '名称': name,
            '评分': score,
            '信号': signals,
            '建议': advice,
            '最新日期': str(df.iloc[-1]['日期']),
            '最新收盘': df.iloc[-1]['收盘'],
            '最新涨跌幅': df.iloc[-1].get('涨跌幅', 0),
        }
    except Exception as e:
        print(f"  ⚠️ {name}({symbol}) 分析失败: {e}")
        return None

def run_analysis():
    """运行完整分析"""
    print("=" * 70)
    print("  🎯 股票短线操盘分析系统 v1.0")
    print(f"  📅 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  📊 操作周期: {CONFIG['min_term_days']}-{CONFIG['short_term_days']} 个交易日")
    print(f"  🛡️ 单只止损: {CONFIG['stop_loss_pct']:.0%} | 单只止盈: {CONFIG['take_profit_pct']:.0%} (盈亏比2:1)")
    print(f"  🧱 组合硬止损: {CONFIG['portfolio_stop_loss_pct']:.0%} | 分批止盈: {'开' if CONFIG['batch_take_profit'] else '关'}")
    print("=" * 70)
    
    results = []
    watch_list = CONFIG['watch_list']
    total = len(watch_list)
    
    print(f"\n📡 正在获取 {total} 只股票数据...\n")
    
    for i, (symbol, name) in enumerate(watch_list.items(), 1):
        print(f"  [{i}/{total}] 分析中: {name}({symbol})...", end=" ")
        result = analyze_single_stock(symbol, name)
        if result:
            results.append(result)
            print(f"✅ 评分: {result['评分']}")
        else:
            print("❌ 跳过")
    
    if not results:
        print("\n❌ 未获取到任何有效数据，请检查网络连接或股票代码")
        return
    
    # 按评分排序
    results.sort(key=lambda x: x['评分'], reverse=True)
    
    # ============================================
    # 输出分析报告
    # ============================================
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + "📊 短线操盘分析报告（按评分排序）".center(60) + "║")
    print("╚" + "═" * 68 + "╝")
    
    for r in results:
        print(f"\n{'─' * 70}")
        print(f"  📌 {r['名称']}({r['代码']}) | 数据截至: {r['最新日期']}")
        print(f"  💰 最新价: ¥{r['最新收盘']:.2f} | 涨跌幅: {r['最新涨跌幅']:.2f}%")
        print(f"  🎯 短线评分: {r['评分']}/100")
        
        # 评分条
        bar_len = int(r['评分'] / 100 * 40)
        bar = "█" * bar_len + "░" * (40 - bar_len)
        print(f"  [{'🟢' if r['评分'] >= 60 else '🟡' if r['评分'] >= 45 else '🔴'}] [{bar}] {r['评分']}")
        
        print(f"\n  📡 技术指标信号:")
        for k, v in r['信号'].items():
            print(f"    {k:6s} │ {v}")
        
        print(f"\n  📋 操作建议:")
        for k, v in r['建议'].items():
            if k == '买入价位':
                print(f"    📥 {'买入价位':8s} │")
                for level in v.split(' | '):
                    print(f"         {level}")
            elif k == '卖出价位':
                print(f"    📤 {'卖出价位':8s} │")
                for level in v.split(' | '):
                    print(f"         {level}")
            else:
                print(f"    {k:8s} │ {v}")
    
    # ============================================
    # 总结
    # ============================================
    print(f"\n{'═' * 70}")
    print("📊 综合总结")
    print(f"{'═' * 70}")
    
    top_picks = [r for r in results if r['评分'] >= 60]
    avoid = [r for r in results if r['评分'] < 40]
    
    if top_picks:
        print(f"\n  🟢 短线关注标的 ({len(top_picks)}只):")
        for r in top_picks:
            price = r['最新收盘']
            print(f"    • {r['名称']}({r['代码']}) - 评分{r['评分']} - {r['建议']['操作建议']}")
            if '信号类型' in r['建议']:
                print(f"      {r['建议']['信号类型']} | 现价: ¥{price:.2f}")
            if '买入价位' in r['建议']:
                print(f"      📥 买入: {r['建议']['买入价位']}")
            if '卖出价位' in r['建议']:
                print(f"      📤 卖出: {r['建议']['卖出价位']}")
    else:
        print(f"\n  ⚪ 当前无明显短线机会，建议空仓观望")
    
    if avoid:
        print(f"\n  🔴 短线回避标的 ({len(avoid)}只):")
        for r in avoid:
            print(f"    • {r['名称']}({r['代码']}) - 评分{r['评分']} - {r['建议']['操作建议']}")
    
    print(f"\n{'─' * 70}")
    print("⚠️  风险提示:")
    print("  • 以上分析基于技术指标，不构成投资建议")
    print("  • 股市有风险，入市需谨慎")
    print("  • 严格执行止损纪律，单笔亏损不超过总资金的2%")
    print("  • 单只止损-7%/单只止盈+14% | 组合硬止损-5% | 分批止盈：触达平半")
    print("  • 短线操作核心：快进快出，不恋战")
    print(f"{'═' * 70}")

# ============================================
# 运行入口
# ============================================
if __name__ == "__main__":
    run_analysis()