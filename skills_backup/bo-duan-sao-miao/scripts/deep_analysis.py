"""三只股票深度买卖点分析"""
import urllib.request
import json
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

CONFIG = {
    "stop_loss_pct": -0.07,
    "take_profit_pct": 0.14,
    "lookback_days": 120,
}

TARGETS = {
    "688668": "鼎通科技",
    "601869": "长飞光纤",
    "002281": "光迅科技",
}

def fetch_kline(symbol):
    if symbol.startswith('6'):
        prefix = 'sh'
    else:
        prefix = 'sz'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{symbol},day,,,180,qfq"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://gu.qq.com'
    })
    import time as t
    t.sleep(0.3)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    key = f'{prefix}{symbol}'
    klines = data['data'][key].get('qfqday', data['data'][key].get('day', []))
    if not klines:
        raise ValueError("无数据")
    df = pd.DataFrame(klines).iloc[:, :6]
    df.columns = ['日期','开盘','收盘','最高','最低','成交量']
    for col in ['开盘','收盘','最高','最低','成交量']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

def calc_all(df):
    df['MA5'] = df['收盘'].rolling(5).mean()
    df['MA10'] = df['收盘'].rolling(10).mean()
    df['MA20'] = df['收盘'].rolling(20).mean()
    df['MA60'] = df['收盘'].rolling(60).mean()
    ema12 = df['收盘'].ewm(span=12, adjust=False).mean()
    ema26 = df['收盘'].ewm(span=26, adjust=False).mean()
    df['DIF'] = ema12 - ema26
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD'] = 2 * (df['DIF'] - df['DEA'])
    delta = df['收盘'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    low_9 = df['最低'].rolling(9).min()
    high_9 = df['最高'].rolling(9).max()
    df['K'] = 100 * (df['收盘'] - low_9) / (high_9 - low_9)
    df['D'] = df['K'].rolling(3).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    df['BOLL_MID'] = df['收盘'].rolling(20).mean()
    std20 = df['收盘'].rolling(20).std()
    df['BOLL_UP'] = df['BOLL_MID'] + 2 * std20
    df['BOLL_DN'] = df['BOLL_MID'] - 2 * std20
    df['BOLL_POS'] = (df['收盘'] - df['BOLL_DN']) / (df['BOLL_UP'] - df['BOLL_DN'])
    df['VOL_MA5'] = df['成交量'].rolling(5).mean()
    df['VOL_RATIO'] = df['成交量'] / df['VOL_MA5']
    df['PCT_CHG_5'] = df['收盘'].pct_change(5) * 100
    df['PCT_CHG_10'] = df['收盘'].pct_change(10) * 100
    df['PCT_CHG_20'] = df['收盘'].pct_change(20) * 100
    # 计算近期支撑阻力
    df['HIGH_20'] = df['最高'].rolling(20).max()
    df['LOW_20'] = df['最低'].rolling(20).min()
    return df

def analyze(symbol, name):
    print(f"\n{'═'*65}")
    print(f"  📊 {name}({symbol}) 深度买卖点分析")
    print(f"{'═'*65}")
    
    df = fetch_kline(symbol)
    df = calc_all(df)
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    price = latest['收盘']
    
    # 基础信息
    print(f"\n  💰 最新价: ¥{price:.2f}")
    print(f"  📈 今日涨幅: {(price/latest['开盘']-1)*100:+.2f}%")
    print(f"  📉 5日涨跌: {latest['PCT_CHG_5']:+.2f}%")
    print(f"  📉 10日涨跌: {latest['PCT_CHG_10']:+.2f}%")
    print(f"  📉 20日涨跌: {latest['PCT_CHG_20']:+.2f}%")
    
    # 均线系统
    print(f"\n  {'─'*50}")
    print(f"  📡 均线系统")
    print(f"  {'─'*50}")
    mas = [
        ('MA5', latest['MA5']), ('MA10', latest['MA10']), 
        ('MA20', latest['MA20']), ('MA60', latest['MA60'])
    ]
    for label, val in mas:
        if pd.notna(val):
            arrow = "🔴" if price < val else "🟢"
            print(f"    {label}: ¥{val:.2f}  {arrow} {'跌破' if price < val else '站上'}")
    
    if pd.notna(latest['MA5']) and pd.notna(latest['MA10']) and pd.notna(latest['MA20']):
        ma_order = latest['MA5'] > latest['MA10'] > latest['MA20']
        print(f"    排列: {'✅ 多头排列' if ma_order else '❌ 空头排列'}")
        # 均线距离
        if ma_order:
            spread = (latest['MA5'] - latest['MA20']) / latest['MA20'] * 100
            print(f"    MA5-MA20 乖离: {spread:+.2f}%")
    
    # MACD
    print(f"\n  {'─'*50}")
    print(f"  📡 MACD 指标")
    print(f"  {'─'*50}")
    print(f"    DIF: {latest['DIF']:.3f}")
    print(f"    DEA: {latest['DEA']:.3f}")
    print(f"    MACD柱: {latest['MACD']:.3f}")
    
    # MACD趋势判断
    if latest['DIF'] > latest['DEA']:
        if latest['MACD'] > prev['MACD']:
            print(f"    状态: 📈 多头 + 红柱放大 → 偏多信号")
        else:
            print(f"    状态: 📈 多头 + 红柱缩小 → 动能减弱")
    else:
        if latest['MACD'] > prev['MACD']:
            print(f"    状态: 🔄 空头 + 绿柱缩短 → 企稳中")
        else:
            print(f"    状态: 📉 空头 + 绿柱放大 → 偏空信号")
    
    # 金叉死叉检测
    if prev['DIF'] <= prev['DEA'] and latest['DIF'] > latest['DEA']:
        print(f"    ⚡ 刚发生金叉！")
    elif prev['DIF'] >= prev['DEA'] and latest['DIF'] < latest['DEA']:
        print(f"    ⚠️ 刚发生死叉！")
    
    # RSI
    print(f"\n  {'─'*50}")
    print(f"  📡 RSI(14): {latest['RSI']:.1f}")
    print(f"  {'─'*50}")
    if latest['RSI'] < 20:
        print(f"    🟢 极度超卖 → 反弹概率极高")
    elif latest['RSI'] < 30:
        print(f"    🟢 超卖区 → 反弹机会较大")
    elif latest['RSI'] < 40:
        print(f"    ⚪ 偏弱区 → 有下行压力")
    elif latest['RSI'] < 60:
        print(f"    ⚪ 中性区 → 方向不明")
    elif latest['RSI'] < 70:
        print(f"    🟠 偏强区 → 上行但追高有风险")
    elif latest['RSI'] < 80:
        print(f"    🔴 超买区 → 回调风险上升")
    else:
        print(f"    🔴 极度超买 → 回调概率高")
    
    # KDJ
    print(f"\n  {'─'*50}")
    print(f"  📡 KDJ: K={latest['K']:.1f} D={latest['D']:.1f} J={latest['J']:.1f}")
    print(f"  {'─'*50}")
    if latest['K'] > latest['D'] and prev['K'] <= prev['D']:
        print(f"    🔥 刚金叉！买入信号")
    elif latest['K'] < latest['D'] and prev['K'] >= prev['D']:
        print(f"    ⚠️ 刚死叉！卖出信号")
    
    if latest['J'] < 0:
        print(f"    🟢 J值负值 → 极度超卖，底部区域")
    elif latest['J'] < 20:
        print(f"    🟢 J值低位 → 超卖区域")
    elif latest['J'] > 100:
        print(f"    🔴 J值过百 → 顶部区域")
    elif latest['J'] > 80:
        print(f"    🟠 J值高位 → 偏强，注意回落")
    else:
        print(f"    ⚪ J值中性")
    
    # 布林带
    print(f"\n  {'─'*50}")
    print(f"  📡 布林带")
    print(f"  {'─'*50}")
    print(f"    上轨: ¥{latest['BOLL_UP']:.2f}")
    print(f"    中轨: ¥{latest['BOLL_MID']:.2f}")
    print(f"    下轨: ¥{latest['BOLL_DN']:.2f}")
    print(f"    位置: {latest['BOLL_POS']*100:.0f}%")
    
    if latest['BOLL_POS'] < 0.05:
        print(f"    🟢 触及下轨 → 超卖，买入点")
    elif latest['BOLL_POS'] < 0.2:
        print(f"    🟢 靠近下轨 → 偏低位")
    elif latest['BOLL_POS'] > 0.95:
        print(f"    🔴 触及上轨 → 超买，卖出点")
    elif latest['BOLL_POS'] > 0.8:
        print(f"    🟠 靠近上轨 → 偏高位")
    else:
        print(f"    ⚪ 中轨附近 → 价格合理区")
    
    # 量价
    print(f"\n  {'─'*50}")
    print(f"  📡 量价分析")
    print(f"  {'─'*50}")
    print(f"    量比: {latest['VOL_RATIO']:.2f}")
    pct_chg_today = (price/latest['开盘']-1)*100
    if latest['VOL_RATIO'] > 1.5 and pct_chg_today > 3:
        print(f"    🟢 放量上涨 → 强势买入信号")
    elif latest['VOL_RATIO'] > 1.5 and pct_chg_today < -3:
        print(f"    🔴 放量下跌 → 恐慌卖出信号")
    elif latest['VOL_RATIO'] < 0.5 and pct_chg_today > 0:
        print(f"    🟠 缩量上涨 → 上涨乏力，警惕回落")
    elif latest['VOL_RATIO'] < 0.5 and pct_chg_today < 0:
        print(f"    🟢 缩量下跌 → 抛压减轻，可能企稳")
    else:
        print(f"    ⚪ 量价正常")
    
    # 关键价位
    print(f"\n  {'─'*50}")
    print(f"  🎯 关键买卖价位")
    print(f"  {'─'*50}")
    
    # 支撑位
    supports = []
    if pd.notna(latest['BOLL_DN']):
        supports.append(('布林下轨', latest['BOLL_DN']))
    if pd.notna(latest['LOW_20']):
        supports.append(('20日最低', latest['LOW_20']))
    if pd.notna(latest['MA60']):
        supports.append(('MA60', latest['MA60']))
    if pd.notna(latest['MA20']):
        supports.append(('MA20', latest['MA20']))
    supports = [(n, v) for n, v in supports if v < price]
    supports.sort(key=lambda x: x[1], reverse=True)
    
    # 压力位
    resistances = []
    if pd.notna(latest['BOLL_UP']):
        resistances.append(('布林上轨', latest['BOLL_UP']))
    if pd.notna(latest['HIGH_20']):
        resistances.append(('20日最高', latest['HIGH_20']))
    if pd.notna(latest['MA20']) and latest['MA20'] > price:
        resistances.append(('MA20', latest['MA20']))
    if pd.notna(latest['MA10']) and latest['MA10'] > price:
        resistances.append(('MA10', latest['MA10']))
    resistances.sort(key=lambda x: x[1])
    
    print(f"    📍 支撑位（下方）:")
    for name, val in supports[:3]:
        dist = (val - price) / price * 100
        print(f"      {name}: ¥{val:.2f} ({dist:+.1f}%)")
    
    print(f"    📍 压力位（上方）:")
    for name, val in resistances[:3]:
        dist = (val - price) / price * 100
        print(f"      {name}: ¥{val:.2f} ({dist:+.1f}%)")
    
    # 止损止盈
    stop_loss = price * (1 + CONFIG['stop_loss_pct'])
    take_profit = price * (1 + CONFIG['take_profit_pct'])
    print(f"\n    🛡️ 止损: ¥{stop_loss:.2f} (-7%)")
    print(f"    🎯 止盈: ¥{take_profit:.2f} (+14%)")
    
    # 近期趋势判断
    print(f"\n  {'─'*50}")
    print(f"  📊 综合买卖点判断")
    print(f"  {'─'*50}")
    
    signals_buy = []
    signals_sell = []
    
    # 买入信号
    if latest['DIF'] > latest['DEA'] and latest['MACD'] > prev['MACD']:
        signals_buy.append('MACD多头发散')
    if latest['DIF'] <= latest['DEA'] and latest['MACD'] > prev['MACD']:
        signals_buy.append('MACD绿柱缩短(企稳)')
    if latest['RSI'] < 30:
        signals_buy.append(f'RSI超卖({latest["RSI"]:.0f})')
    if latest['J'] < 20:
        signals_buy.append(f'KDJ超卖(J={latest["J"]:.0f})')
    if latest['BOLL_POS'] < 0.2:
        signals_buy.append(f'布林低位({latest["BOLL_POS"]*100:.0f}%)')
    if latest['VOL_RATIO'] < 0.5 and pct_chg_today < 0:
        signals_buy.append('缩量下跌(抛压枯竭)')
    if latest['K'] > latest['D'] and prev['K'] <= prev['D']:
        signals_buy.append('KDJ金叉')
    if prev['DIF'] <= prev['DEA'] and latest['DIF'] > latest['DEA']:
        signals_buy.append('MACD金叉')
    
    # 卖出信号
    if latest['DIF'] < latest['DEA'] and latest['MACD'] < prev['MACD']:
        signals_sell.append('MACD空头发散')
    if latest['RSI'] > 70:
        signals_sell.append(f'RSI超买({latest["RSI"]:.0f})')
    if latest['J'] > 100:
        signals_sell.append(f'KDJ超买(J={latest["J"]:.0f})')
    if latest['BOLL_POS'] > 0.8:
        signals_sell.append(f'布林高位({latest["BOLL_POS"]*100:.0f}%)')
    if latest['VOL_RATIO'] > 1.5 and pct_chg_today < -3:
        signals_sell.append('放量下跌')
    if latest['VOL_RATIO'] < 0.5 and pct_chg_today > 3:
        signals_sell.append('缩量暴涨(诱多)')
    if latest['K'] < latest['D'] and prev['K'] >= prev['D']:
        signals_sell.append('KDJ死叉')
    if prev['DIF'] >= prev['DEA'] and latest['DIF'] < latest['DEA']:
        signals_sell.append('MACD死叉')
    
    # 趋势状态
    trend = '中性'
    if pd.notna(latest['MA5']) and pd.notna(latest['MA20']):
        if latest['MA5'] > latest['MA20'] and price > latest['MA20']:
            trend = '偏多'
        elif latest['MA5'] < latest['MA20'] and price < latest['MA20']:
            trend = '偏空'
    
    print(f"    趋势状态: {trend}")
    print(f"    买入信号 ({len(signals_buy)}): {', '.join(signals_buy) if signals_buy else '无'}")
    print(f"    卖出信号 ({len(signals_sell)}): {', '.join(signals_sell) if signals_sell else '无'}")
    
    # 最终建议
    score_buy = len(signals_buy)
    score_sell = len(signals_sell)
    
    print(f"\n  🎯 操作建议: ", end='')
    if score_buy >= 3 and score_sell == 0:
        print("🟢 可建仓 — 多个买入信号共振，风险可控")
    elif score_buy >= 2 and score_sell <= 1:
        print("🟡 可试探 — 有买入信号，但需轻仓(10-15%)")
    elif score_buy >= 1 and score_sell <= 1:
        print("⚪ 观望 — 信号不够强，等更多确认")
    elif score_sell >= 2 and score_buy <= 1:
        print("🟠 减仓 — 卖出信号增多，降低仓位")
    elif score_sell >= 3:
        print("🔴 回避 — 多项卖出信号共振，不适合入场")
    else:
        print("⚪ 观望 — 多空信号拉锯，方向不明")
    
    # 最佳买点推测
    print(f"\n  💡 理想买入策略:")
    if trend == '偏多':
        # 回踩均线买
        ma_targets = []
        for label, val in [('MA10', latest['MA10']), ('MA20', latest['MA20'])]:
            if pd.notna(val) and val < price:
                ma_targets.append((label, val))
        if ma_targets:
            best_entry = ma_targets[0]
            print(f"    趋势偏多 → 回踩{best_entry[0]} (¥{best_entry[1]:.2f})时买入，止损设¥{best_entry[1]*0.95:.2f}")
        else:
            print(f"    趋势偏多但已站上所有均线 → 当前位置轻仓，止损¥{stop_loss:.2f}")
    else:
        # 等待企稳信号
        print(f"    趋势偏空 → 建议等待以下任一信号出现再考虑:")
        if latest['RSI'] > 30:
            print(f"      • RSI回落至30以下出现超卖")
        if not (latest['K'] > latest['D'] and prev['K'] <= prev['D']):
            print(f"      • KDJ金叉确认")
        if latest['BOLL_POS'] > 0.1:
            print(f"      • 价格触及布林下轨(¥{latest['BOLL_DN']:.2f})")
        print(f"    或等待价格站上MA20(¥{latest['MA20']:.2f})确认趋势反转后再入场")

for symbol, name in TARGETS.items():
    try:
        analyze(symbol, name)
    except Exception as e:
        print(f"\n  ❌ {name}({symbol}) 分析失败: {e}")

print(f"\n{'═'*65}")
print("  ⚠️ 以上分析基于技术指标，不构成投资建议。")
print("  止损 -7% 止盈 +14%，严格执行。")
print(f"{'═'*65}")
