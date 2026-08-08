#!/usr/bin/env python3
"""
猛兽体系 · 趋势量化扫描系统 v3.0
=================================
三层漏斗 + Layer 3.5 Setup量化评分 (猛兽派选股官方公式版)
  VAD中期动量 + SSV/RSL量价加权 + RS_D背离 + 伏击线
  + OVS精确公式(PV2/PV3/OV3) + M8枢轴点 + G点 + 双模式
基于猛兽选股派知识库全部公式集成

运行: python3 beast_screener.py
时间: 每日盘后 16:00+
"""

import subprocess, sys, os, re, json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# ============================================================
#              工具函数
# ============================================================
def cli(cmd: str) -> str:
    full_cmd = f"npx -y westock-data-skillhub@1.0.3 {cmd}"
    try:
        r = subprocess.run(full_cmd, shell=True, capture_output=True,
                           text=True, timeout=120)
        return r.stdout
    except:
        return ""

def parse_table(md: str) -> list[dict]:
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
    if not headers:
        return []
    data_lines = lines[header_idx + 2:]
    results = []
    for ln in data_lines:
        parts = ln.split('|')
        cols = [p.strip() for p in parts[1:-1]]
        if len(cols) >= len(headers):
            row = {h: cols[j] if j < len(cols) else "" for j, h in enumerate(headers)}
            results.append(row)
            continue
        cols = [c.strip() for c in parts if c.strip()]
        if len(cols) >= len(headers):
            row = {h: cols[j] if j < len(cols) else "" for j, h in enumerate(headers)}
            results.append(row)
    return results

def get_val(row: dict, *keys) -> str:
    for k in keys:
        if k in row:
            return row[k]
    return ""

def is_mainboard(code: str) -> bool:
    prefix = re.match(r'(?:sh|sz|)(\d+)', code)
    if not prefix:
        return False
    num = prefix.group(1)
    if num.startswith('688'): return False
    if num.startswith('300'): return False
    if num.startswith('301'): return False
    if num.startswith('8'): return False
    if num.startswith('43'): return False
    if num.startswith('83'): return False
    if num.startswith('87'): return False
    return True

def is_not_st(name: str) -> bool:
    if not name: return False
    return not ('ST' in name or '*ST' in name)

def parse_kline_df(code: str, limit: int = 60) -> pd.DataFrame:
    """获取K线并解析为DataFrame (时间正序)"""
    raw = cli(f"kline {code} --period day --limit {limit}")
    rows = parse_table(raw)
    if len(rows) < 10:
        return pd.DataFrame()
    records = []
    for r in rows:
        try:
            records.append({
                "date": get_val(r, "date", "日期"),
                "open": float(get_val(r, "open", "开盘")),
                "close": float(get_val(r, "last", "收盘", "收盘价", "最新")),
                "high": float(get_val(r, "high", "最高")),
                "low": float(get_val(r, "low", "最低")),
                "volume": float(get_val(r, "volume", "成交量", "vol")),
                "amount": float(get_val(r, "amount", "成交额", "amt")),
            })
        except (ValueError, TypeError):
            continue
    df = pd.DataFrame(records)
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    for col in ['open','close','high','low','volume','amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


# ============================================================
#      ★★★ 猛兽派选股 公众号公式函数库 ★★★
#      来源: 猛兽派选股公众号系列文章
# ============================================================

def calc_vad(df: pd.DataFrame, n: int = 14) -> dict:
    """
    VAD中期动量指标 — 源自威廉姆斯成交量累积派发线改进版
    来源: 《中短周期动量指标VAD和OVS》
    参数: N=14(周期)
    用途: 波段拐点判断，顶底背离识别
    """
    if df.empty or len(df) < n + 2:
        return {"vad": 0, "vad_signal": 0, "vad_trend": "中性"}
    
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    amounts = df['amount'].values
    
    # HI=MAX(H,REF(C,1)); LW=MIN(L,REF(C,1)); BSR=(C-REF(C,1))/(HI-LW); VAD:SUM(BSR*AMO,N)/10000000
    vad_values = []
    for i in range(1, len(closes)):
        hi = max(highs[i], closes[i-1])
        lw = min(lows[i], closes[i-1])
        denom = hi - lw if hi != lw else 1
        bsr = (closes[i] - closes[i-1]) / denom
        vad_values.append(bsr * amounts[i])
    
    if len(vad_values) < n:
        return {"vad": 0, "vad_signal": 0, "vad_trend": "中性"}
    
    vad = sum(vad_values[-n:]) / 10000000
    vad_prev = sum(vad_values[-n-1:-1]) / 10000000 if len(vad_values) >= n+1 else 0
    
    # 信号判断
    signal = 0
    if vad > 0 and vad_prev < 0:
        signal = 1    # 上穿零轴 = 买入信号
    elif vad < 0 and vad_prev > 0:
        signal = -1   # 下穿零轴 = 卖出信号
    elif vad > vad_prev * 1.1:
        signal = 2    # 加速上升
    elif vad < vad_prev * 0.9:
        signal = -2   # 加速下降
    
    trend = "强势" if vad > 5 else ("偏多" if vad > 1 else ("中性" if abs(vad) <= 1 else ("偏空" if vad > -5 else "弱势")))
    
    return {"vad": round(vad, 2), "vad_signal": signal, "vad_trend": trend,
            "vad_cross_up": signal == 1, "vad_cross_down": signal == -1}


def calc_ovs_exact(df: pd.DataFrame, n1: int = 2, n2: int = 4, m: int = 15) -> dict:
    """
    OVS短期动量指标 — 精确公式版
    来源: 《中短周期动量指标VAD和OVS》
    OVS基本定义: 涨幅 * 成交金额
    PV2: SUM(BSR*ZF*AMO/MA(AMO,N1),N1)*100
    PV3: SUM(ZF*AMO/LLV(AMO,M),N2)*100
    OV3: SUM(ZF*AMO,N2)/10060000
    双模式参数: M=15(堆量小盘), M=13(覆盖中大盘)
    """
    result = {"pv2": 0, "pv3": 0, "ov3": 0, "pv3_ov3_ratio": 0}
    
    if df.empty or len(df) < 20:
        return result
    
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    amounts = df['amount'].values
    n_rows = len(closes)
    
    # 逐日计算
    zf_list = []
    bsr_list = []
    for i in range(1, n_rows):
        hi = max(highs[i], closes[i-1])
        lw = min(lows[i], closes[i-1])
        denom = hi - lw if hi != lw else 1
        zf = (closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] != 0 else 0
        bsr = abs(closes[i] - closes[i-1]) / denom
        zf_list.append(zf)
        bsr_list.append(bsr)
    
    if len(zf_list) < max(n1, n2, m):
        return result
    
    # PV2: SUM(BSR*ZF*AMO/MA(AMO,N1),N1)*100
    pv2_vals = []
    for i in range(len(zf_list)):
        start = max(0, i - n1 + 1)
        segment_amo = amounts[start+1:i+2]  # +1 offset because zf_list starts from index 1
        ma_amo = np.mean(segment_amo) if len(segment_amo) > 0 else 1
        val = bsr_list[i] * zf_list[i] * amounts[i+1] / ma_amo if ma_amo != 0 else 0
        pv2_vals.append(val)
    pv2 = sum(pv2_vals[-n1:]) * 100 if len(pv2_vals) >= n1 else 0
    
    # PV3: SUM(ZF*AMO/LLV(AMO,M),N2)*100
    pv3_vals = []
    for i in range(len(zf_list)):
        # LLV(AMO,M): lowest amount in last M days
        lookback_start = max(0, i+1 - m + 1)
        llv_amo = min(amounts[lookback_start:i+2]) if (i+2 - lookback_start) > 0 else amounts[i+1]
        llv_amo = llv_amo if llv_amo > 0 else 1
        val = zf_list[i] * amounts[i+1] / llv_amo
        pv3_vals.append(val)
    pv3 = sum(pv3_vals[-n2:]) * 100 if len(pv3_vals) >= n2 else 0
    
    # OV3: SUM(ZF*AMO,N2)/10060000
    ov3_vals = [zf_list[i] * amounts[i+1] for i in range(len(zf_list))]
    ov3 = sum(ov3_vals[-n2:]) / 10060000 if len(ov3_vals) >= n2 else 0
    
    ratio = pv3 / ov3 if ov3 != 0 else 0
    
    return {"pv2": round(pv2, 2), "pv3": round(pv3, 2), "ov3": round(ov3, 2),
            "pv3_ov3_ratio": round(ratio, 2)}


def calc_ssv(df: pd.DataFrame, n: int = 200) -> dict:
    """
    SSV成交量加权相对强度指标
    来源: 《成交量加权以后的相对强度(SSV和RSL)》
    VWAP=SUM(AMO*C,N)/SUM(AMO,N)
    STDD=SQRT(SUM(POW((C-VWAP),2),N)/(N-1))
    SSV1=(C-VWAP)/VWAP*500
    SSV2=(C-VWAP)/STDD*100
    参数: N=200
    """
    result = {"ssv1": 0, "ssv2": 0, "vwap": 0}
    
    if df.empty or len(df) < n:
        # 用可用数据
        n = len(df)
        if n < 20:
            return result
    
    closes = df['close'].values[-n:]
    amounts = df['amount'].values[-n:]
    
    # VWAP = SUM(AMO*C,N) / SUM(AMO,N)
    sum_amo_c = sum(closes[i] * amounts[i] for i in range(n))
    sum_amo = sum(amounts)
    vwap = sum_amo_c / sum_amo if sum_amo != 0 else 0
    
    # STDD = SQRT(SUM(POW((C-VWAP),2),N)/(N-1))
    variance = sum(pow(closes[i] - vwap, 2) for i in range(n)) / (n - 1) if n > 1 else 0
    stdd = np.sqrt(variance)
    
    latest_close = closes[-1]
    
    # SSV1 = (C-VWAP)/VWAP*500
    ssv1 = (latest_close - vwap) / vwap * 500 if vwap != 0 else 0
    
    # SSV2 = (C-VWAP)/STDD*100
    ssv2 = (latest_close - vwap) / stdd * 100 if stdd != 0 else 0
    
    return {"ssv1": round(ssv1, 2), "ssv2": round(ssv2, 2), "vwap": round(vwap, 2)}


def calc_rsl(df: pd.DataFrame, index_df: pd.DataFrame, n: int = 144) -> dict:
    """
    RSL个股平均 — RSLine成交量加权版
    来源: 《成交量加权以后的相对强度(SSV和RSL)》
    RS=CLOSE/INDEXC
    VWRS=SUM(RS*AMO,N)/SUM(AMO,N)
    STDD=SQRT(SUM(POW((RS-VWRS),2),N)/(N-1))
    RSL1=(RS-VWRS)/VWRS*500
    RSL2=(RS-VWRS)/STDD*100
    参数: N=144
    """
    result = {"rsl1": 0, "rsl2": 0}
    
    if df.empty or index_df.empty:
        return result
    
    df_close = df[['date', 'close', 'amount']].copy()
    idx_close = index_df[['date', 'close']].copy()
    merged = pd.merge(df_close, idx_close, on='date', how='inner', suffixes=('_stock', '_index'))
    
    if len(merged) < min(n, 20):
        return result
    
    merged['rs'] = merged['close_stock'] / merged['close_index']
    
    n_actual = min(n, len(merged))
    rs_vals = merged['rs'].values[-n_actual:]
    amo_vals = merged['amount'].values[-n_actual:]
    
    # VWRS = SUM(RS*AMO,N) / SUM(AMO,N)
    vwrs = sum(rs_vals[i] * amo_vals[i] for i in range(n_actual)) / sum(amo_vals) if sum(amo_vals) != 0 else 0
    
    # STDD = SQRT(SUM(POW((RS-VWRS),2),N)/(N-1))
    variance = sum(pow(rs_vals[i] - vwrs, 2) for i in range(n_actual)) / (n_actual - 1) if n_actual > 1 else 0
    stdd = np.sqrt(variance)
    
    latest_rs = rs_vals[-1]
    
    # RSL1 = (RS-VWRS)/VWRS*500
    rsl1 = (latest_rs - vwrs) / vwrs * 500 if vwrs != 0 else 0
    
    # RSL2 = (RS-VWRS)/STDD*100
    rsl2 = (latest_rs - vwrs) / stdd * 100 if stdd != 0 else 0
    
    return {"rsl1": round(rsl1, 2), "rsl2": round(rsl2, 2), "rs_value": round(latest_rs, 4)}


def calc_rs_combined(df: pd.DataFrame, index_df: pd.DataFrame, n: int = 144) -> dict:
    """
    RSR个股综合强度 (RSV + SSV) / 2
    来源: 《RSR设置完整教程》
    RSV = (C-LLV(L,N))/(HHV(H,N)-LLV(L,N))*100
    SSV 从 calc_ssv 获取
    """
    result = {"rsv": 0, "ssv": 0, "rsr": 0}
    
    if df.empty or len(df) < 20:
        return result
    
    n_actual = min(n, len(df))
    closes = df['close'].values[-n_actual:]
    highs = df['high'].values[-n_actual:]
    lows = df['low'].values[-n_actual:]
    
    # RSV = (C-LLV(L,N))/(HHV(H,N)-LLV(L,N))*100
    hhv = max(highs)
    llv = min(lows)
    rsv = (closes[-1] - llv) / (hhv - llv) * 100 if (hhv - llv) != 0 else 50
    
    # SSV
    ssv_result = calc_ssv(df, n)
    ssv_norm = (ssv_result['ssv2'] + 200) / 4  # normalize SSV2 (~-200~+200) to ~0-100
    ssv_norm = max(0, min(100, ssv_norm))
    
    # RSR = (RSV + SSV_norm) / 2
    rsr = (rsv + ssv_norm) / 2
    
    return {"rsv": round(rsv, 1), "ssv_norm": round(ssv_norm, 1), "rsr": round(rsr, 1)}


def calc_rs_d(df: pd.DataFrame, index_df: pd.DataFrame, n: int = 5) -> dict:
    """
    RS_D背离值逆向低吸指标
    来源: 《高阶动量技巧——RS_D背离值逆向低吸交易原理和公式》
    IND=880003$CLOSE; RS=CLOSE/IND
    RR=SLOPE(RS,N)/RS*1000
    XL_I=SLOPE(IND,N)/IND*1000
    XL_C=SLOPE(C,N)/C*1000
    DR=XL_I-XL_C
    BS=15 (阈值)
    """
    result = {"rr": 0, "xl_i": 0, "xl_c": 0, "dr": 0, "dr_signal": 0}
    
    if df.empty or index_df.empty or len(df) < n + 2:
        return result
    
    df_close = df[['date', 'close']].copy()
    idx_close = index_df[['date', 'close']].copy()
    merged = pd.merge(df_close, idx_close, on='date', how='inner', suffixes=('_stock', '_index'))
    
    if len(merged) < n + 2:
        return result
    
    closes = merged['close_stock'].values
    idx_closes = merged['close_index'].values
    rs_vals = closes / idx_closes
    
    # SLOPE as linear regression coefficient
    x = np.arange(n)
    
    def slope(y_vals):
        if len(y_vals) < n:
            return 0
        y = y_vals[-n:]
        if np.std(y) == 0:
            return 0
        coeffs = np.polyfit(x, y, 1)
        return coeffs[0]
    
    # RR = SLOPE(RS,N)/RS*1000
    rs_slope = slope(rs_vals)
    rr = rs_slope / rs_vals[-1] * 1000 if rs_vals[-1] != 0 else 0
    
    # XL_I = SLOPE(IND,N)/IND*1000
    idx_slope = slope(idx_closes)
    xl_i = idx_slope / idx_closes[-1] * 1000 if idx_closes[-1] != 0 else 0
    
    # XL_C = SLOPE(C,N)/C*1000
    close_slope = slope(closes)
    xl_c = close_slope / closes[-1] * 1000 if closes[-1] != 0 else 0
    
    # DR = XL_I - XL_C
    dr = xl_i - xl_c
    
    # 信号: DR绝对值<15 时进入低吸区
    bs_threshold = 15
    signal = 0
    if abs(dr) < bs_threshold and dr > 0:
        signal = 1   # 低吸信号
    elif dr > bs_threshold:
        signal = -1  # 偏离过大
    elif dr < -bs_threshold:
        signal = -2  # 个股明显弱于大盘
    
    return {"rr": round(rr, 2), "xl_i": round(xl_i, 2), "xl_c": round(xl_c, 2),
            "dr": round(dr, 2), "dr_signal": signal}


def calc_ambush_line(df: pd.DataFrame, m: int = 5, n: int = 20) -> dict:
    """
    伏击线 — 低波动率低吸点识别
    来源: 《低吸伏击线和风险警戒线（附源码）》
    X=BARSCOUNT(C); XX=MIN(20,X); MM=MIN(M,X); NN=MIN(N,X)
    SD=STD(C,MM); MASD=MA(SD,NN); BOL=MA(C,XX)
    UB=BOL+5*SD; UBM=BOL+5*MASD
    """
    result = {"ub": 0, "ubm": 0, "ambush_score": 0}
    
    if df.empty or len(df) < max(m, n, 20):
        return result
    
    closes = df['close'].values
    n_rows = len(closes)
    
    xx = min(20, n_rows)
    mm = min(m, n_rows)
    nn = min(n, n_rows)
    
    # BOL = MA(C,XX)
    bol = np.mean(closes[-xx:])
    
    # SD = STD(C,MM)
    sd = np.std(closes[-mm:])
    
    # MASD = MA(SD,NN) — 用最近NN个标准差平均
    sd_vals = []
    for i in range(n_rows - nn, n_rows):
        start = max(0, i - mm + 1)
        sd_vals.append(np.std(closes[start:i+1]))
    masd = np.mean(sd_vals) if sd_vals else sd
    
    # UB = BOL + 5*SD
    ub = bol + 5 * sd
    
    # UBM = BOL + 5*MASD
    ubm = bol + 5 * masd
    
    # 当前价格相对伏击线的位置 — 越低越安全
    latest_close = closes[-1]
    ambush_score = 0
    if ub > 0:
        # 离伏击线越近越适合低吸
        pct_from_ub = (ub - latest_close) / ub * 100
        if 0 < pct_from_ub < 3:
            ambush_score = 5   # 在伏击线附近
        elif 0 < pct_from_ub < 6:
            ambush_score = 3
        elif pct_from_ub < 0:
            ambush_score = 1   # 已过伏击线
    
    return {"ub": round(ub, 2), "ubm": round(ubm, 2), "ambush_score": ambush_score}


def calc_rsi_slope(df: pd.DataFrame, n: int = 14) -> float:
    """计算RSI值"""
    if df.empty or len(df) < n + 1:
        return 50
    
    closes = df['close'].values
    gains, losses = 0, 0
    for i in range(-n, 0):
        change = closes[i] - closes[i-1]
        if change > 0:
            gains += change
        else:
            losses -= change
    
    avg_gain = gains / n
    avg_loss = losses / n
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def detect_pivot_point(df: pd.DataFrame) -> dict:
    """
    M8枢轴点检测 (简化版)
    来源: M8+VOL_金主图指标 Version2.0
    枢轴点 = TURN + REDK + INCV + SAFE
    """
    result = {"has_pivot": False, "pivot_score": 0, "pivot_detail": ""}
    
    if df.empty or len(df) < 30:
        return result
    
    closes = df['close'].values
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    amounts = df['amount'].values
    n_rows = len(df)
    
    # 取最近5日检测
    score = 0
    details = []
    
    for i in range(-5, 0):
        idx = n_rows + i
        if idx < 2:
            continue
        
        # TURN: 拐点 — 收盘>前2日最高 AND 前4日最高<前4日收盘最高
        turn = (closes[idx] > max(highs[idx-2], highs[idx-1]) and
                max(closes[idx-4:idx]) < max(highs[idx-4:idx]))
        
        # REDK: 实体阳线 — 收盘>前日*1.01, (C-L)<=2%波动
        redk = (closes[idx] > closes[idx-1] * 1.01 and
                closes[idx] > opens[idx] and
                (closes[idx] - lows[idx]) / (highs[idx] - lows[idx]) > 0.5 if highs[idx] != lows[idx] else False)
        
        # INCV: 量增 — 成交额>EMA(AMO,3) OR 成交额>LLV(AMO,34)*1.6
        ema_amo = np.mean(amounts[max(0, idx-3):idx+1])
        llv_amo = min(amounts[max(0, idx-34):idx+1])
        incv = amounts[idx] > ema_amo or amounts[idx] > llv_amo * 1.6
        
        # SAFE: 安全条件
        close_llv8 = closes[idx] / min(closes[max(0, idx-8):idx+1])
        safe = close_llv8 > 1.05
        
        if turn and redk and incv and safe:
            score += 4
            details.append(f"T{abs(i)}")
    
    if score >= 4:
        result["has_pivot"] = True
        result["pivot_score"] = min(15, score)
        result["pivot_detail"] = "+".join(details) if details else "有信号"
    
    return result


def detect_gpoint(df: pd.DataFrame, index_df: pd.DataFrame, mode: str = "标准") -> dict:
    """
    G点检测 — 堆量模式间隙弱转强信号
    来源: 《继续解密堆量模式间隙弱转强的G点特征》《猛兽体系进入双模式》
    更新: 双参数RS_D检测 + 新阈值
    """
    result = {"has_gpoint": False, "gpoint_score": 0, "mode": mode}
    
    if df.empty or len(df) < 30:
        return result
    
    # 1. 计算OVS指标
    ovs = calc_ovs_exact(df)
    pv3 = ovs['pv3']
    ov3 = ovs['ov3']
    pv2 = ovs['pv2']
    
    # 2. 计算RS_D双参数
    rs_d5 = calc_rs_d(df, index_df, 5)
    rs_d4 = calc_rs_d(df, index_df, 4)
    
    # 3. XZPV: ABS(PV2)<6
    xzpv = abs(pv2) < 6
    
    # 4. QZPV(新版): HHV(OV3,16)>45 AND HHV(PV3,16)>55
    # 需要16日回溯找HHV — 简化: 检查当前OV3>45且PV3>55
    qzpv = ov3 > 45 and pv3 > 55
    
    # 5. DRSS(双参数版): DR1<15 OR REF(DR1,1)<15 OR REF(DR2,1)<15
    drss = (abs(rs_d5['dr']) < 15 or abs(rs_d4['dr']) < 15)
    
    # 6. TURN条件 (简化版)
    closes = df['close'].values
    highs = df['high'].values
    n_rows = len(df)
    turn = False
    if n_rows >= 3:
        hhr = (highs[-1] - closes[-1]) / closes[-1] * 100 if closes[-1] != 0 else 0
        turn = hhr < 3.5
    
    # 综合评分
    score = 0
    if qzpv: score += 3
    if xzpv: score += 2
    if drss: score += 3
    if turn: score += 2
    
    result['gpoint_score'] = score
    result['has_gpoint'] = score >= 6
    result['details'] = {
        'pv3': pv3, 'ov3': ov3, 'pv2': pv2,
        'dr5': rs_d5['dr'], 'dr4': rs_d4['dr'],
        'qzpv': qzpv, 'xzpv': xzpv, 'drss': drss, 'turn': turn
    }
    
    return result


def classify_mode(market_cap: float = 0, indicators: dict = None) -> str:
    """
    双模式分类
    来源: 《猛兽体系进入双模式，以及边界调节》
    堆量模式: 情绪+资金溢出，盘子偏小
    欧马模式: 产业+业绩成长，三四百亿起步
    """
    if indicators is None:
        indicators = {}
    
    pv3 = indicators.get('pv3', 0)
    ov3 = indicators.get('ov3', 0)
    
    # 堆量模式特征: PV3>OV3(量比主导), 小盘
    if pv3 > ov3 and market_cap < 200:
        return "堆量模式"
    # 欧马模式特征: OV3主导或中大盘
    elif market_cap >= 300 or ov3 >= pv3:
        return "欧马模式"
    else:
        return "混合模式"


# ============================================================
#      Step 0: 大盘安全评分 (★★ 新增: 获取大盘K线供抗跌计算)
# ============================================================
def _score_single_index(code: str, name: str) -> dict:
    """对单个指数进行安全评分 (0-100)"""
    df = parse_kline_df(code, 30)
    if df.empty or len(df) < 10:
        return {"score": 50, "level": "数据不足", "close": 0, "df": df, "name": name}

    closes = df["close"].values
    latest = closes[-1]

    high_20 = max(closes[-20:])
    low_20 = min(closes[-20:])
    range_20 = high_20 - low_20 if high_20 != low_20 else 1
    pos_score = (latest - low_20) / range_20 * 40

    ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else 0
    ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else 0
    ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else 0
    trend_score = 30 if (ma5 > ma10 > ma20) else (20 if ma5 > ma10 else (10 if ma5 > ma20 else 0))

    if len(closes) >= 6:
        pct_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
        momentum_score = 30 if pct_5d > 3 else (20 if pct_5d > 1 else (15 if pct_5d > -1 else (8 if pct_5d > -3 else 0)))
    else:
        momentum_score = 15

    # ---- 新增①：成交额情绪 (-5 ~ +5) ----
    # 判断是恐慌放量、缩量衰竭企稳、还是价涨量增的健康状态
    vol_sentiment = 0
    if 'amount' in df.columns and len(df) >= 6:
        amounts = df['amount'].values
        latest_amt = amounts[-1]
        avg5_amt = np.mean(amounts[-6:-1])  # 前5日均额
        if avg5_amt > 0:
            vol_ratio = latest_amt / avg5_amt
            if pct_5d > 2 and vol_ratio > 1.2:
                vol_sentiment = 5    # 上涨放量，健康跟涨
            elif pct_5d > 0 and vol_ratio > 1:
                vol_sentiment = 3    # 上涨微放量
            elif pct_5d < -2 and vol_ratio > 1.3:
                vol_sentiment = -5   # 大跌放量 = 恐慌
            elif pct_5d < -1 and vol_ratio > 1.2:
                vol_sentiment = -3   # 下跌放量 = 弱势
            elif pct_5d < 0 and vol_ratio < 0.7:
                vol_sentiment = 3    # 缩量下跌 = 衰竭企稳
            elif pct_5d < 0 and 0.7 <= vol_ratio < 0.9:
                vol_sentiment = 1    # 微缩量下跌 = 空方力量衰减

    # ---- 新增②：动量加速度 (-5 ~ +5) ----
    # 比较5日与10日涨跌幅：减速下跌=可能见底，加速下跌=仍然危险
    accel_score = 0
    if len(closes) >= 11:
        pct_10d = (closes[-1] - closes[-11]) / closes[-11] * 100
        accel = pct_5d - pct_10d  # 正数=跌幅收窄/涨幅扩大
        if accel > 8:
            accel_score = 5
        elif accel > 4:
            accel_score = 3
        elif accel > 1:
            accel_score = 1
        elif accel > -1:
            accel_score = 0
        elif accel > -4:
            accel_score = -1
        elif accel > -8:
            accel_score = -3
        else:
            accel_score = -5

    total = min(100, max(0, pos_score + trend_score + momentum_score + vol_sentiment + accel_score))
    level = "安全" if total >= 70 else ("偏暖" if total >= 55 else ("中性" if total >= 40 else ("偏冷" if total >= 25 else "危险")))

    return {"score": total, "level": level, "close": latest, "name": name,
            "pos_score": pos_score, "trend_score": trend_score,
            "momentum_score": momentum_score,
            "vol_sentiment": vol_sentiment, "accel_score": accel_score, "df": df}


def check_market_safety() -> dict:
    """
    多指数聚合大盘安全评分 0-100

    同时评估3个代表性指数，加权聚合：
      - 上证指数 sh000001 (权重30%) — 沪市传统参考
      - 中证全指 sh000985 (权重40%) — 沪深全覆盖，主基准
      - 深证综指 sz399106 (权重30%) — 深市全量补充

    返回聚合评分、等级，以及中证全指的K线DataFrame供RSVA计算。
    """
    # 三指数独立评分
    idx_list = [
        ("sh000001", "上证指数", 0.3),
        ("sh000985", "中证全指", 0.4),
        ("sz399106", "深证综指", 0.3),
    ]

    results = []
    for code, name, weight in idx_list:
        r = _score_single_index(code, name)
        r["weight"] = weight
        results.append(r)

    # 加权聚合（不含广度情绪）
    raw_agg = sum(r["score"] * r["weight"] for r in results)

    # ---- 新增③：板块广度情绪 (-5 ~ +5) ----
    # 计算全市场板块中上涨板块的比例，反映市场参与广度
    breadth_score = 0
    try:
        board_raw = cli("board")
        board_rows = parse_table(board_raw)
        if board_rows:
            total_sectors = len(board_rows)
            positive_sectors = 0
            for br in board_rows:
                zdf_str = get_val(br, "changePct", "涨跌幅", "zdf")
                try:
                    zdf = float(zdf_str.replace("%", "").replace("+", ""))
                    if zdf >= 0:
                        positive_sectors += 1
                except:
                    pass
            if total_sectors > 0:
                breadth_ratio = positive_sectors / total_sectors
                if breadth_ratio > 0.7:
                    breadth_score = 5    # 普涨格局
                elif breadth_ratio > 0.55:
                    breadth_score = 3    # 多数上涨
                elif breadth_ratio > 0.45:
                    breadth_score = 1    # 涨跌互现略偏多
                elif breadth_ratio > 0.35:
                    breadth_score = -1   # 涨跌互现略偏空
                elif breadth_ratio > 0.2:
                    breadth_score = -3   # 多数下跌
                else:
                    breadth_score = -5   # 普跌格局
    except:
        pass

    agg_score = min(100, max(0, round(raw_agg + breadth_score, 1)))

    # 等级：取聚合分判定
    level = ("安全" if agg_score >= 70 else
             "偏暖" if agg_score >= 55 else
             "中性" if agg_score >= 40 else
             "偏冷" if agg_score >= 25 else "危险")

    # 各指数明细（含情绪子项）
    details = []
    for r in results:
        sub = f"{r['name']}: {r['score']:.0f}分"
        if r.get("vol_sentiment") or r.get("accel_score"):
            sub += f"(量{r['vol_sentiment']:>+d} 速{r['accel_score']:>+d})"
        details.append(sub)
    detail_str = " | ".join(details)

    # 使用覆盖面最广的中证全指 df 作为后续RSVA计算的基准
    main_df = results[1]["df"] if len(results) > 1 and not results[1]["df"].empty else results[0]["df"]
    main_close = results[1]["close"] if len(results) > 1 else results[0]["close"]

    # 情绪综述（含大盘安全评分，统一纳入"大盘情绪指标"）
    emotion_detail = f"安全{agg_score}/100({level}) " \
                     f"量{results[0].get('vol_sentiment',0):>+d}/{results[1].get('vol_sentiment',0):>+d}/{results[2].get('vol_sentiment',0):>+d} " \
                     f"速{results[0].get('accel_score',0):>+d}/{results[1].get('accel_score',0):>+d}/{results[2].get('accel_score',0):>+d} " \
                     f"广度{breadth_score:>+d}"

    return {
        "score": agg_score,
        "level": level,
        "index_close": main_close,
        "index_name": "中证全指",
        "df_30d": main_df,
        "details": detail_str,
        "idx_results": results,
        "breadth_score": breadth_score,
        "emotion_detail": emotion_detail,
    }


# ============================================================
#      Step 1: 板块RSR排名
# ============================================================
def get_sector_ranking(top_n: int = 5) -> list[dict]:
    raw = cli("board")
    rows = parse_table(raw)
    sectors = []
    for r in rows:
        name = get_val(r, "name", "板块名称")
        zdf_str = get_val(r, "changePct", "涨跌幅", "zdf")
        lb = get_val(r, "leadStock", "领涨股")
        try:
            zdf = float(zdf_str.replace("%", "").replace("+", ""))
        except:
            zdf = 0
        sectors.append({"name": name, "zdf": zdf, "lead_stock": lb})
    return sectors[:top_n]


# ============================================================
#      Step 2: 候选股获取
# ============================================================
def get_candidate_stocks(max_count: int = 25) -> list[dict]:
    raw = cli("hot stock --limit 50")
    rows = parse_table(raw)
    candidates = []
    seen = set()
    for r in rows:
        code = get_val(r, "code", "代码")
        name = get_val(r, "name", "名称")
        zdf_str = get_val(r, "zdf", "涨跌幅")
        price_str = get_val(r, "zxj", "最新价", "now_price")
        stype = get_val(r, "stock_type", "类型")

        if stype and stype != "GP-A":
            continue
        if not is_mainboard(code):
            continue
        if not is_not_st(name):
            continue
        if code in seen:
            continue
        seen.add(code)

        try:
            zdf = float(zdf_str.replace("%", "").replace("+", ""))
        except:
            zdf = 0
        try:
            price = float(price_str)
        except:
            price = 0

        candidates.append({"code": code, "name": name, "price": price, "zdf": zdf})
        if len(candidates) >= max_count:
            break
    return candidates


# ============================================================
#      Step 3: OVS综合评分 (★★ 优化: 增加RSVA指标获取)
# ============================================================
def ovs_score_stock(code: str, name: str, index_df=None) -> dict:
    """
    猛兽派选股·OVS评分 (v2.2 官方公式版)
    基于公众号精确公式: OVS = 涨幅*成交金额
    包含: PV2/PV3/OV3精确值 + VAD + SSV + RSL + RS_D综合评分
    """
    result = {"code": code, "name": name, "ovs_total": 0}

    # 获取K线数据 (需较多数据供OVS计算)
    df = parse_kline_df(code, 250)
    if df.empty or len(df) < 30:
        return result

    # 1. OVS精确公式计算
    ovs = calc_ovs_exact(df)
    result["pv2"] = ovs["pv2"]
    result["pv3"] = ovs["pv3"]
    result["ov3"] = ovs["ov3"]
    result["pv3_ov3_ratio"] = ovs["pv3_ov3_ratio"]

    # 2. VAD中期动量
    vad = calc_vad(df, 14)
    result["vad"] = vad["vad"]
    result["vad_signal"] = vad["vad_signal"]
    result["vad_trend"] = vad["vad_trend"]

    # 3. SSV量价加权强度
    ssv = calc_ssv(df, 200)
    result["ssv1"] = ssv["ssv1"]
    result["ssv2"] = ssv["ssv2"]

    # 4. RSL (需大盘数据)
    if index_df is not None and not index_df.empty:
        rsl = calc_rsl(df, index_df, 144)
        result["rsl1"] = rsl["rsl1"]
        result["rsl2"] = rsl["rsl2"]

        # 5. RS_D背离值
        rs_d = calc_rs_d(df, index_df, 5)
        result["dr5"] = rs_d["dr"]
        result["dr_signal"] = rs_d["dr_signal"]
        rs_d4 = calc_rs_d(df, index_df, 4)
        result["dr4"] = rs_d4["dr"]

        # 6. RSR综合
        rsr = calc_rs_combined(df, index_df, 144)
        result["rsr"] = rsr["rsr"]
        result["rsv"] = rsr["rsv"]

    # 综合评分 (基于OVS官方指标特征)
    score = 0

    # PV3评分: 量比强度
    if ovs["pv3"] > 40:
        score += 25
    elif ovs["pv3"] > 30:
        score += 20
    elif ovs["pv3"] > 20:
        score += 15
    elif ovs["pv3"] > 10:
        score += 10
    elif ovs["pv3"] > 5:
        score += 5

    # OV3评分: 成交额累计
    if ovs["ov3"] > 30:
        score += 20
    elif ovs["ov3"] > 20:
        score += 15
    elif ovs["ov3"] > 10:
        score += 10
    elif ovs["ov3"] > 5:
        score += 5

    # PV3>OV3加分 (堆量启动特征)
    if ovs["pv3_ov3_ratio"] > 1:
        score += 10

    # VAD趋势加分
    if vad["vad_trend"] == "强势":
        score += 15
    elif vad["vad_trend"] == "偏多":
        score += 10

    # SSV强度加分
    if ssv["ssv2"] > 100:
        score += 15
    elif ssv["ssv2"] > 50:
        score += 10
    elif ssv["ssv2"] > 0:
        score += 5

    # RSR综合加分
    if result.get("rsr", 0) > 80:
        score += 15
    elif result.get("rsr", 0) > 70:
        score += 10
    elif result.get("rsr", 0) > 60:
        score += 5

    result["ovs_total"] = min(100, max(0, score))
    return result


# ============================================================
#      ★★★ 新增: RSVA相对强度计算 ★★★
#      来源: 猛兽选股派《不做扩展数据，如何实现相对强度指标》
#      RSVA = (RSV1 + RSV2) / 2
#        RSV1 = 自身RSV  RSV2 = RSline归一化
# ============================================================
def calc_rsva(df: pd.DataFrame, index_df: pd.DataFrame, n: int = 20) -> float:
    """
    计算RSVA综合相对强度 (0-100)
    df: 个股K线DataFrame (时间正序)
    index_df: 上证指数K线DataFrame (时间正序)
    n: 周期参数 (默认20)
    """
    if df.empty or index_df.empty or len(df) < n or len(index_df) < n:
        return 50.0  # 默认中性值

    # 对齐日期范围
    df_close = df[['date','close']].copy()
    idx_close = index_df[['date','close']].copy()
    merged = pd.merge(df_close, idx_close, on='date', how='inner', suffixes=('_stock','_index'))
    if len(merged) < n:
        return 50.0

    stock_closes = merged['close_stock'].values
    index_closes = merged['close_index'].values
    stock_high = df['high'].tail(n).max()
    stock_low = df['low'].tail(n).min()

    # RSV1: 自身相对强度
    latest_close = stock_closes[-1]
    if stock_high == stock_low:
        rsv1 = 50.0
    else:
        rsv1 = (latest_close - stock_low) / (stock_high - stock_low) * 100
    rsv1 = max(0, min(100, rsv1))

    # RSline: 个股/指数比值
    rs = stock_closes / index_closes
    rs_min = rs.min()
    rs_max = rs.max()
    if rs_max == rs_min:
        rsv2 = 50.0
    else:
        rsv2 = (rs[-1] - rs_min) / (rs_max - rs_min) * 100
    rsv2 = max(0, min(100, rsv2))

    return (rsv1 + rsv2) / 2


# ============================================================
#      ★★★ 新增: 抗跌强度计算 ★★★
#       来源: 猛兽选股派《基底回撤末期的两种关键信号》
#       在大盘下跌时，个股跌幅小于大盘 = 抗跌
# ============================================================
def calc_anti_fall(df: pd.DataFrame, index_df: pd.DataFrame, window: int = 20) -> float:
    """
    计算抗跌强度 (0-100)
    在大盘下跌期间，个股相对大盘的表现
    """
    if df.empty or index_df.empty or len(df) < window or len(index_df) < window:
        return 50.0

    # 对齐日期
    df_close = df[['date','close']].copy()
    idx_close = index_df[['date','close']].copy()
    merged = pd.merge(df_close, idx_close, on='date', how='inner', suffixes=('_stock','_index'))
    if len(merged) < 10:
        return 50.0

    stock_rets = merged['close_stock'].pct_change().dropna().tail(window)
    index_rets = merged['close_index'].pct_change().dropna().tail(window)

    if len(stock_rets) < 5:
        return 50.0

    # 找大盘下跌的交易日
    down_days = index_rets < -0.005  # 大盘跌幅超过0.5%
    if down_days.sum() == 0:
        # 大盘没有下跌日，说明市场整体上涨，抗跌意义不大
        # 但仍比较相对表现
        rel_return = stock_rets.mean() - index_rets.mean()
        return max(0, min(100, 50 + rel_return * 500))

    # 在大盘下跌日中，个股的跌幅
    stock_down = stock_rets[down_days]
    index_down = index_rets[down_days]

    # 抗跌强度 = 个股比大盘少跌的比例
    total_index_loss = abs(index_down.sum())
    total_stock_loss = abs(stock_down.sum())

    if total_index_loss == 0:
        return 50.0

    # 如果个股在大盘跌时还涨了，抗跌极强
    if stock_down.mean() > 0:
        base = 80 + min(20, stock_down.mean() / abs(index_down.mean()) * 10)
        return min(100, base)

    # 个股比大盘少跌了多少
    ratio = 1 - total_stock_loss / total_index_loss
    score = 50 + ratio * 50
    return max(0, min(100, score))


# ============================================================
#      ★★★ 新增: 净利润断层检测 ★★★
#       来源: 猛兽选股派《猛派净利润跳空选股公式》
#       检测公告日前后的跳空缺口 + 扣非增速
# ============================================================
def detect_profit_gap(code: str) -> dict:
    """
    检测净利润断层信号
    返回: {gap_score: 0-15, details: {...}}
    """
    result = {"gap_score": 0, "gap_detected": False,
              "announce_date": "", "np_growth": 0, "has_gap": False}

    # 获取财务报表
    fin_raw = cli(f"finance {code} --type lrb --num 8")
    fin_rows = parse_table(fin_raw)
    if not fin_rows or len(fin_rows) < 2:
        return result

    # 最新一期财报
    latest = fin_rows[0]
    info_date_str = get_val(latest, "InfoPublDate", "infoPublDate")
    if not info_date_str:
        return result

    # 解析公告日期
    try:
        # 格式: "2025-10-30 00:00:00 +0800 CST"
        pub_date = info_date_str.split(" ")[0]
        result["announce_date"] = pub_date
        pub_dt = datetime.strptime(pub_date, "%Y-%m-%d")
    except:
        return result

    # 获取公告日前后K线 (前10日+后5日)
    df = parse_kline_df(code, 60)
    if df.empty or len(df) < 10:
        return result

    # 定位公告日在K线中的位置
    df['date_str'] = df['date'].astype(str)
    pub_mask = df['date_str'] == pub_date
    if not pub_mask.any():
        # 公告日可能不是交易日，找最近的交易日
        # 找公告日后第一个交易日
        future = df[df['date_str'] > pub_date]
        if future.empty:
            return result
        pub_idx = future.index[0]
    else:
        pub_idx = df[pub_mask].index[0]

    # 检查跳空缺口: 公告日后一天最低价 > 公告日前一天最高价
    if pub_idx + 1 < len(df) and pub_idx - 1 >= 0:
        day_before_high = df.loc[pub_idx - 1, 'high']
        day_after_low = df.loc[pub_idx + 1, 'low']
        gap_amount = day_after_low - day_before_high

        if gap_amount > 0:
            result["has_gap"] = True
            gap_pct = (day_after_low - day_before_high) / day_before_high * 100
            result["gap_pct"] = round(gap_pct, 2)

    # 检查公告日当天涨幅
    day0_open = df.loc[pub_idx, 'open']
    day0_close = df.loc[pub_idx, 'close']
    day0_chg = (day0_close - day0_open) / day0_open * 100

    # 计算扣非净利润增速 (用NPParentCompanyOwners_Q同比)
    if len(fin_rows) >= 5:
        try:
            np_latest = float(get_val(latest, "NPParentCompanyOwners_Q", "nPParentCompanyOwners_Q"))
            np_prev = float(get_val(fin_rows[4], "NPParentCompanyOwners_Q", "nPParentCompanyOwners_Q"))
            if np_prev != 0:
                np_growth = (np_latest - np_prev) / abs(np_prev) * 100
                result["np_growth"] = round(np_growth, 2)
            else:
                np_growth = 0
        except:
            np_growth = 0
    else:
        np_growth = 0

    # 综合评分 (0-15)
    score = 0
    # 有跳空缺口 + 涨幅 > 7%
    if result["has_gap"] and day0_chg > 7:
        score += 10
    elif day0_chg > 7:
        score += 6  # 公告日大涨但无缺口
    elif result["has_gap"]:
        score += 5

    # 扣非增速 > 20%
    if np_growth > 50:
        score += 5
    elif np_growth > 20:
        score += 3
    elif np_growth > 0:
        score += 1

    # 低位跳空加分 (股价在近60日均线附近或下方)
    if result["has_gap"] and not df.empty:
        close_now = df['close'].iloc[-1]
        ma60 = df['close'].tail(min(60, len(df))).mean()
        if close_now <= ma60 * 1.1:
            score = min(15, score + 3)

    result["gap_score"] = min(15, score)
    return result


# ============================================================
#      Step 3.5: Setup量化评分 v2.1 ★★★ 全面升级 ★★★
# ============================================================
def setup_score_stock(code: str, name: str, index_df: pd.DataFrame) -> dict:
    """
    Setup量化评分 v2.2 (猛兽派选股 官方公式版)
    九维评分：
      ① VCP波动收缩率 (0-20分)
      ② 均线系统 (0-20分) — 融入趋势判断
      ③ 成交量 (0-15分)
      ④ VAD中期动量 (0-10分) — ★ 替代TSI，源自猛兽派VAD指标
      ⑤ 突破确认+高阳模式+孤狼 (0-15分)
      ⑥ 净利润断层 (0-10分)
      ⑦ RSVA相对强度+SSV+RSL (0-10分) — ★ 新增SSV/RSL维度
      ⑧ 伏击线低吸评分 (0-5分) — ★ 新增
      ⑨ RS_D背离评分 (0-5分) — ★ 新增
    """
    result = {
        "code": code, "name": name,
        "setup_total": 0,
        "vcp_score": 0, "ma_score": 0, "volume_score": 0,
        "vad_score": 0, "breakout_score": 0,
        "gap_score": 0, "rsva_score": 0,
        "anti_fall_score": 0, "fundamental_score": 0,
        "ambush_score": 0, "rsd_score": 0,
        "gpoint_score": 0, "trade_mode": "",
        "details": {}
    }

    # ---- 获取K线数据 ----
    df = parse_kline_df(code, 250)  # ★ 增加数据量供SSV/RSL使用
    if df.empty or len(df) < 20:
        return result

    latest = df.iloc[-1]
    result["details"]["close"] = latest["close"]

    # ============================================================
    #  ① VCP波动收缩率评分 (0-20分)
    # ============================================================
    df["amplitude_pct"] = (df["high"] - df["low"]) / df["close"] * 100
    amp_5 = df["amplitude_pct"].tail(5).mean()
    amp_20 = df["amplitude_pct"].tail(20).mean()
    vcp_ratio = amp_5 / amp_20 if amp_20 > 0 else 1.0

    if vcp_ratio <= 0.30: vcp_score = 20
    elif vcp_ratio <= 0.45: vcp_score = 17
    elif vcp_ratio <= 0.60: vcp_score = 13
    elif vcp_ratio <= 0.75: vcp_score = 8
    elif vcp_ratio <= 0.90: vcp_score = 4
    elif vcp_ratio <= 1.0: vcp_score = 2
    else: vcp_score = 0

    result["vcp_score"] = vcp_score
    result["details"]["vcp_ratio"] = round(vcp_ratio, 3)

    # ============================================================
    #  ② 均线系统评分 (0-20分) — 融入趋势判断
    # ============================================================
    df["ema5"] = df["close"].ewm(span=5, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()
    df["ma5_vol"] = df["volume"].rolling(5).mean()
    df["ma20_vol"] = df["volume"].rolling(20).mean()

    # 重新获取latest（ema列已创建）
    latest = df.iloc[-1]

    ma_score = 0
    if latest["ema5"] > latest["ema20"] > latest["ema60"]:
        ma_score += 8
    elif latest["ema5"] > latest["ema20"]:
        ma_score += 4

    if len(df) >= 7:
        ema5_slope = (df["ema5"].iloc[-1] - df["ema5"].iloc[-6]) / df["ema5"].iloc[-6]
        if ema5_slope > 0.002: ma_score += 5
        elif ema5_slope > 0: ma_score += 2

    if len(df) >= 22:
        ema20_slope = (df["ema20"].iloc[-1] - df["ema20"].iloc[-21]) / df["ema20"].iloc[-21]
        if ema20_slope > 0.002: ma_score += 4
        elif ema20_slope > 0: ma_score += 2

    if latest["close"] > latest["ema60"]:
        ma_score += 3

    result["ma_score"] = min(20, ma_score)
    result["details"]["ema5"] = round(latest["ema5"], 2)
    result["details"]["ema20"] = round(latest["ema20"], 2)
    result["details"]["ema60"] = round(latest["ema60"], 2)

    # ============================================================
    #  ③ 成交量评分 (0-15分) — 融入堆量特征
    # ============================================================
    vol_5 = df["volume"].tail(5).mean()
    vol_20 = df["volume"].tail(20).mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1.0
    latest_vol = df["volume"].iloc[-1]
    vol_break_ratio = latest_vol / vol_20 if vol_20 > 0 else 0

    vol_score = 0
    if vol_ratio < 0.5: vol_score += 8  # 缩量
    elif vol_ratio < 0.7: vol_score += 5
    elif vol_ratio < 0.9: vol_score += 3

    if vol_break_ratio > 1.8: vol_score += 7  # 放量突破
    elif vol_break_ratio > 1.4: vol_score += 5
    elif vol_break_ratio > 1.1: vol_score += 3

    result["volume_score"] = min(15, vol_score)
    result["details"]["vol_ratio_5_20"] = round(vol_ratio, 3)

    # ============================================================
    #  ④ VAD中期动量评分 (0-10分) — ★ 替代TSI，融入抗跌逻辑
    #      来源: 猛兽派选股《VAD中期动量》
    # ============================================================
    vad = calc_vad(df, 14)
    vad_score = 0
    vad_val = vad["vad"]
    vad_signal = vad["vad_signal"]

    if vad_val > 8:
        vad_score = 10
    elif vad_val > 5:
        vad_score = 8
    elif vad_val > 3:
        vad_score = 6
    elif vad_val > 1:
        vad_score = 4
    elif vad_val > 0:
        vad_score = 3
    elif vad_val > -1:
        vad_score = 2
    elif vad_val > -3:
        vad_score = 1
    else:
        vad_score = 0

    # VAD上穿零轴加分
    if vad_signal == 1:
        vad_score = min(10, vad_score + 2)

    # 抗跌逻辑融入
    if not index_df.empty:
        anti = calc_anti_fall(df, index_df, 20)
        result["anti_fall_score"] = round(anti, 1)
        if anti > 70:
            vad_score = min(10, vad_score + 2)
        elif anti > 50:
            vad_score = min(10, vad_score + 1)
        result["details"]["anti_fall"] = round(anti, 1)

    result["vad_score"] = vad_score
    result["details"]["vad"] = vad_val
    result["details"]["vad_signal"] = vad_signal
    result["details"]["vad_trend"] = vad["vad_trend"]

    # ============================================================
    #  ⑤ 突破确认评分 (0-15分) + 高阳模式 + 孤狼信号
    # ============================================================
    b_score = 0

    # 价格接近60日最高
    high_60 = df["high"].max()
    dist_from_high = (high_60 - latest["close"]) / high_60 * 100 if high_60 > 0 else 100
    if dist_from_high < 2: b_score += 3
    elif dist_from_high < 5: b_score += 2
    elif dist_from_high < 10: b_score += 1
    result["details"]["dist_from_high_pct"] = round(dist_from_high, 2)

    # 收阳线
    if latest["close"] > latest["open"]:
        b_score += 2

    # 成交量递增
    if len(df) >= 4:
        vol_trend = (df["volume"].iloc[-1] > df["volume"].iloc[-2]) + \
                    (df["volume"].iloc[-2] > df["volume"].iloc[-3])
        b_score += vol_trend  # 最多+2

    # 站上20EMA
    if len(df) >= 22:
        ema20_up = (df["ema20"].iloc[-1] > df["ema20"].iloc[-21])
    else:
        ema20_up = False
    if latest["close"] > latest["ema20"] and ema20_up:
        b_score += 2

    # ★ 高阳模式量价行为分析
    df['is_high_vol_up'] = ((df['close'] > df['open']) &
                            (df['volume'] > df['ma20_vol'] * 1.5)).astype(int)
    high_vol_dates = df[df['is_high_vol_up'] == 1].index
    recent_high_vol = [idx for idx in high_vol_dates if idx >= len(df) - 15]
    
    high_vol_mode = "无"
    if recent_high_vol:
        last_hv = recent_high_vol[-1]
        if last_hv + 3 < len(df):
            hv_close = df.loc[last_hv, 'close']
            d1_ret = (df.loc[last_hv+1, 'close'] - hv_close) / hv_close * 100 if hv_close else 0
            d2_ret = (df.loc[last_hv+2, 'close'] - hv_close) / hv_close * 100 if hv_close else 0
            d3_ret = (df.loc[last_hv+3, 'close'] - hv_close) / hv_close * 100 if hv_close else 0
            
            if d1_ret > 0 and d2_ret > 0:
                b_score += 3
                high_vol_mode = "快速推升"
            elif d1_ret >= -1 and d2_ret >= -1 and d3_ret >= -1:
                b_score += 2
                high_vol_mode = "小K线浮盈"
            elif df.loc[last_hv+1, 'volume'] < df['ma20_vol'].loc[last_hv] * 0.8:
                b_score += 1
                high_vol_mode = "价缓量缩"
            elif d1_ret < -3 and df.loc[last_hv+1, 'volume'] > df['ma20_vol'].loc[last_hv]:
                b_score -= 1
                high_vol_mode = "迅速跌落⚠"
    
    result["details"]["high_vol_mode"] = high_vol_mode

    # ★ 孤狼检测
    if not index_df.empty and len(df) >= 6:
        try:
            stock_5d = (df['close'].iloc[-1] - df['close'].iloc[-6]) / df['close'].iloc[-6] * 100
            idx_slice = index_df[index_df['date'] <= df['date'].iloc[-1]]
            if not idx_slice.empty and len(idx_slice) >= 6:
                idx_5d = (idx_slice['close'].iloc[-1] - idx_slice['close'].iloc[-6]) / idx_slice['close'].iloc[-6] * 100
                lead = stock_5d - idx_5d
                result["details"]["lead_over_index"] = round(lead, 2)
                if lead > 10:
                    b_score += 3
                elif lead > 5:
                    b_score += 2
                elif lead > 2:
                    b_score += 1
        except:
            pass

    result["breakout_score"] = min(15, max(0, b_score))

    # ============================================================
    #  ⑥ 净利润断层评分 (0-15分) ★★ 新增
    # ============================================================
    try:
        gap_result = detect_profit_gap(code)
        result["gap_score"] = gap_result["gap_score"]
        result["details"]["gap_detected"] = gap_result.get("has_gap", False)
        result["details"]["np_growth"] = gap_result.get("np_growth", 0)
        result["details"]["announce_date"] = gap_result.get("announce_date", "")
        if gap_result.get("has_gap"):
            result["details"]["gap_pct"] = gap_result.get("gap_pct", 0)
    except Exception as e:
        result["gap_score"] = 0
        result["details"]["gap_error"] = str(e)

    # ============================================================
    #  ⑦ RSVA相对强度 + SSV/RSL综合评分 (0-10分) ★★ 升级
    #      来源: SSV(200日) + RSL(144日) + RSVA(20日) 三合
    # ============================================================
    rsva_score_total = 0
    if not index_df.empty:
        # 原RSVA (20日短期)
        rsva = calc_rsva(df, index_df, 20)
        result["details"]["rsva_20"] = round(rsva, 1)
        if rsva >= 85: rsva_score_total += 3
        elif rsva >= 75: rsva_score_total += 2
        elif rsva >= 65: rsva_score_total += 1

        # SSV (200日量价加权)
        ssv = calc_ssv(df, 200)
        result["details"]["ssv2"] = ssv["ssv2"]
        if ssv["ssv2"] > 100:
            rsva_score_total += 3
        elif ssv["ssv2"] > 50:
            rsva_score_total += 2
        elif ssv["ssv2"] > 0:
            rsva_score_total += 1

        # RSL (144日RSLine)
        rsl = calc_rsl(df, index_df, 144)
        result["details"]["rsl2"] = rsl["rsl2"]
        if rsl["rsl2"] > 100:
            rsva_score_total += 4
        elif rsl["rsl2"] > 50:
            rsva_score_total += 3
        elif rsl["rsl2"] > 0:
            rsva_score_total += 1
    else:
        rsva_score_total = 0
    result["rsva_score"] = min(10, rsva_score_total)

    # ============================================================
    #  ⑧ 基本面连续增速评分 (0-5分) ★★ 保留
    # ============================================================
    fundamental_score = 0
    try:
        fin_raw = cli(f"finance {code} --type sum --num 4")
        fin_rows = parse_table(fin_raw)
        if fin_rows and len(fin_rows) >= 2:
            r0 = fin_rows[0]
            r1 = fin_rows[1]
            rev_grow_s = get_val(r0, "OperatingRevenueGrowRate_Q")
            np_grow_s = get_val(r0, "NPParentCompanyYOY_Q")
            rev_grow_p_s = get_val(r1, "OperatingRevenueGrowRate_Q")
            np_grow_p_s = get_val(r1, "NPParentCompanyYOY_Q")
            rev_g = float(rev_grow_s.replace("%","")) if rev_grow_s and rev_grow_s != '-' else 0
            np_g = float(np_grow_s.replace("%","")) if np_grow_s and np_grow_s != '-' else 0
            rev_g_p = float(rev_grow_p_s.replace("%","")) if rev_grow_p_s and rev_grow_p_s != '-' else 0
            np_g_p = float(np_grow_p_s.replace("%","")) if np_grow_p_s and np_grow_p_s != '-' else 0
            if (rev_g > 10 and rev_g_p > 8 and np_g > 12 and np_g_p > 10) or \
               (np_g > 20 and rev_g > 15):
                fundamental_score = 5
            elif rev_g > 8 and np_g > 10:
                fundamental_score = 3
            result["details"]["rev_grow_q"] = rev_g
            result["details"]["np_grow_q"] = np_g
    except:
        pass
    result["fundamental_score"] = fundamental_score

    # ============================================================
    #  ⑨ 伏击线低吸评分 (0-5分) ★ 新增
    #      来源: 《低吸伏击线和风险警戒线》
    # ============================================================
    ambush = calc_ambush_line(df, 5, 20)
    result["ambush_score"] = ambush["ambush_score"]
    result["details"]["ambush_ub"] = ambush["ub"]
    # 伏击线越近 + SSV为正 = 低吸机会
    if ambush["ambush_score"] >= 3:
        result["ambush_score"] = min(5, ambush["ambush_score"] + (2 if result["details"].get("ssv2", 0) > 0 else 0))

    # ============================================================
    #  ⑩ RS_D背离评分 (0-5分) ★ 新增
    #      来源: 《高阶动量技巧——RS_D背离值逆向低吸交易》
    # ============================================================
    if not index_df.empty:
        rs_d5 = calc_rs_d(df, index_df, 5)
        rs_d4 = calc_rs_d(df, index_df, 4)
        dr5 = rs_d5["dr"]
        dr4 = rs_d4["dr"]
        result["details"]["dr5"] = dr5
        result["details"]["dr4"] = dr4
        
        rsd_score = 0
        # 双参数RS_D检测
        if abs(dr5) < 15 or abs(dr4) < 15:
            rsd_score += 3
            if dr5 > 0:  # 个股跑赢大盘
                rsd_score += 2
        elif abs(dr5) < 25 or abs(dr4) < 25:
            rsd_score += 2
        result["rsd_score"] = min(5, rsd_score)
    else:
        result["rsd_score"] = 0

    # ============================================================
    #  ⑪ G点检测 + 双模式分类 ★ 新增
    #      来源: 《继续解密堆量模式间隙弱转强的G点特征》
    #            《猛兽体系进入双模式，以及边界调节》
    # ============================================================
    # OVS数据
    ovs = calc_ovs_exact(df)
    result["details"]["pv3"] = ovs["pv3"]
    result["details"]["ov3"] = ovs["ov3"]
    result["details"]["pv3_ov3_ratio"] = ovs["pv3_ov3_ratio"]
    
    # G点检测
    gpoint = detect_gpoint(df, index_df)
    result["gpoint_score"] = gpoint["gpoint_score"]
    result["details"]["has_gpoint"] = gpoint["has_gpoint"]

    # 双模式分类
    mode_indicators = {"pv3": ovs["pv3"], "ov3": ovs["ov3"]}
    trade_mode = classify_mode(0, mode_indicators)
    result["trade_mode"] = trade_mode

    # ============================================================
    #  汇总Setup总分 (满分125 → 归一化到100)
    # ============================================================
    gap_score_adj = min(10, result.get("gap_score", 0))
    raw_total = sum([
        result["vcp_score"],     # 0-20
        result["ma_score"],      # 0-20
        result["volume_score"],  # 0-15
        result["vad_score"],     # 0-10
        result["breakout_score"],# 0-15
        gap_score_adj,           # 0-10
        result["rsva_score"],    # 0-10
        result["fundamental_score"], # 0-5
        result["ambush_score"],  # 0-5
        result["rsd_score"],     # 0-5
    ])
    # 归一化到100
    result["setup_total"] = min(100, int(raw_total * 100 / 115))
    result["gap_score_display"] = result["gap_score"]
    result["gap_score"] = gap_score_adj

    return result


# ============================================================
#                      主流程
# ============================================================
def main():
    print("=" * 72)
    print("  猛兽体系 · 趋势量化扫描系统 v2.2")
    print(f"  扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("  升级内容: 高阳模式量价行为 + 基本面连续增速 + 全信号回测验证")
    print("=" * 72)

    # ---- Step 0: 大盘安全评分 ----
    print("\n📊 Step 0: 大盘安全评分")
    print("-" * 40)
    safety = check_market_safety()
    index_df = safety.get("df_30d", pd.DataFrame())
    print(f"  {' | '.join([r['name']+': '+str(round(r['close'],2)) for r in safety.get('idx_results', [])])}")
    print(f"  安全评分: {safety['score']}/100  (加权: {safety.get('details', '')})")
    emo = safety.get('emotion_detail', '')
    print(f"  情绪指标: {emo}")
    print(f"  市场状态: {safety['level']}")

    # ---- Step 1: 板块RSR排名 ----
    print("\n📈 Step 1: 板块RSR排名 TOP5")
    print("-" * 40)
    sectors = get_sector_ranking(5)
    for i, s in enumerate(sectors, 1):
        print(f"  {i}. {s['name']:　<8} 涨跌幅: {s['zdf']:>+.2f}%  领涨: {s['lead_stock']}")

    # ---- Step 2: 候选股获取 ----
    print("\n🎯 Step 2: 候选股筛选（热搜股·主板过滤）")
    print("-" * 40)
    candidates = get_candidate_stocks(25)
    print(f"  获取到 {len(candidates)} 只候选股")
    if not candidates:
        print("\n❌ 无候选股，终止扫描")
        return

    # ---- Step 2.5: 产业锚定4 · 三季盈增基本面预筛选 ----
    try:
        import sys, os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        from industrial_anchor4 import calc_quarterly_growth
        
        anchor_enabled = os.environ.get("ANCHOR4_ENABLED", "true").lower() == "true"
        if anchor_enabled and len(candidates) > 3:
            print("\n🏭 Step 2.5: 产业锚定4 · 三季盈增筛选")
            print("-" * 40)
            anchor_passed = []
            total_candidates = len(candidates)
            for i, c in enumerate(candidates):
                print(f"  [{i+1}/{total_candidates}] {c['code']} {c['name']}...", end="\r")
                r = calc_quarterly_growth(c["code"])
                if r.get("error"):
                    # akshare可能失败，放行
                    anchor_passed.append(c)
                elif r["qualify"]:
                    c["anchor_score"] = r["score"]
                    c["avg_rev_growth"] = r["avg_rev_growth"]
                    c["avg_profit_growth"] = r["avg_profit_growth"]
                    anchor_passed.append(c)
                # 不通过的跳过
            if anchor_passed:
                print(f"  ✅ 通过三季盈增: {len(anchor_passed)}/{len(candidates)} 只")
                candidates = anchor_passed
            else:
                print(f"  ⚠️ 全部未通过，放行全部（保守策略）")
        else:
            print("  ⏭️ 产业锚定4跳过（未启用或候选过少）")
    except Exception as e:
        print(f"  ⚠️ 产业锚定4异常: {e}（跳过该筛选）")

    # ---- Step 2.6: 月线框架闸门（曾星智体系: MA6半年线+MA12年线+月线反转）----
    try:
        import sys, os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        from month_frame import check_month_trend
        
        month_enabled = os.environ.get("MONTH_GATE_ENABLED", "true").lower() == "true"
        if month_enabled and candidates:
            print("\n📅 Step 2.6: 月线框架闸门（曾星智: MA6半年线/MA12年线 + 月线反转）")
            print("-" * 40)
            n_pass = n_warn = n_block = n_rev = 0
            for i, c in enumerate(candidates):
                r = check_month_trend(c["code"])
                c["month_trend"] = r.get("trend", "无数据")
                c["month_gate"] = r.get("gate", "BLOCK")
                c["month_reversal"] = r.get("reversal")
                if r.get("reversal"):
                    n_rev += 1
                if c["month_gate"] == "PASS":
                    n_pass += 1
                elif c["month_gate"] == "WARN":
                    n_warn += 1
                else:
                    n_block += 1
                tag = "⚡反转" if r.get("reversal") else {"PASS": "🟢", "WARN": "🟡", "BLOCK": "🔴"}.get(c["month_gate"], "❔")
                print(f"  {c['code']} {c['name']} 月线{c['month_trend']} {tag} {r.get('reversal') or ''}")
            print(f"  📊 月线闸门: PASS {n_pass} / WARN {n_warn} / BLOCK {n_block}，反转信号 {n_rev} 只")
            print("  💡 规则: 月线多头(PASS)或反转信号→日线买点可靠; 纠缠(WARN)→降级; 空头(BLOCK)→日线信号可靠性低")
        else:
            print("  ⏭️ 月线闸门跳过（未启用或候选为空）")
    except Exception as e:
        print(f"  ⚠️ 月线闸门异常: {e}（跳过该步骤）")

    # ---- Step 3: OVS评分 ----
    print("\n🔍 Step 3: OVS综合评分 (官方PV2/PV3/OV3公式)")
    print("-" * 40)
    cand_map = {c["code"]: c for c in candidates}
    ovs_results = [ovs_score_stock(c["code"], c["name"], index_df) for c in candidates]
    # 透传月线框架字段（Step 2.6标注在candidates上，ovs_results为新dict需回填）
    for r in ovs_results:
        cm = cand_map.get(r["code"], {})
        r["month_trend"] = cm.get("month_trend", "")
        r["month_gate"] = cm.get("month_gate", "")
        r["month_reversal"] = cm.get("month_reversal", "")
    ovs_results.sort(key=lambda x: x["ovs_total"], reverse=True)
    setup_candidates = [r for r in ovs_results if r["ovs_total"] >= 40][:15]
    if not setup_candidates:
        setup_candidates = ovs_results[:10]
    print(f"  OVS≥40分候选: {len(setup_candidates)} 只 → 进入Setup评分")

    # ---- Step 3.5: Setup量化评分 v2.2 ★ 猛兽派官方公式版 ----
    print("\n⭐ Step 3.5: Setup量化评分 v2.2 ★  (猛兽派官方公式 - VAD/SSV/RSL/RS_D)")
    print("=" * 90)
    print(f"  {'代码':<11} {'名称':<7} {'总分':>4}  "
          f"{'VCP':>3} {'均线':>3} {'量能':>3} {'VAD':>3} {'突破':>3} {'断层':>3} {'强度':>3} {'伏击':>3} {'RS_D':>3} {'基本':>3} 模式  高阳")
    print("  " + "-" * 82)

    setup_results = []
    for i, c in enumerate(setup_candidates):
        print(f"  ⏳ 计算中 ({i+1}/{len(setup_candidates)})...", end="\r")
        setup = setup_score_stock(c["code"], c["name"], index_df)
        # 透传月线框架字段（Step 2.6）
        setup["month_trend"] = c.get("month_trend", "")
        setup["month_gate"] = c.get("month_gate", "")
        setup["month_reversal"] = c.get("month_reversal", "")
        setup_results.append(setup)

        gap_tag = "⍟" if setup.get("gap_score_display", 0) >= 8 else ""
        hv_mode = setup["details"].get("high_vol_mode", "")
        hv_tag = ""
        if "快速推升" in hv_mode: hv_tag = "🚀"
        elif "小K线" in hv_mode: hv_tag = "✅"
        elif "迅速跌落" in hv_mode: hv_tag = "⚠️"

        gpoint_tag = "⚡G" if setup["details"].get("has_gpoint", False) else ""
        mode_tag = setup.get("trade_mode", "")
        if mode_tag == "堆量模式": mode_tag = "📦堆量"
        elif mode_tag == "欧马模式": mode_tag = "🐎欧马"
        elif mode_tag == "混合模式": mode_tag = "🔀混合"

        print(f"  {c['code']:<11} {c['name']:<7} "
              f"{setup['setup_total']:>3}/{100:<2} "
              f"{setup['vcp_score']:>2}/{20:<2} "
              f"{setup['ma_score']:>2}/{20:<2} "
              f"{setup['volume_score']:>2}/{15:<2} "
              f"{setup['vad_score']:>1}/{10:<2} "
              f"{setup['breakout_score']:>2}/{15:<2} "
              f"{setup['gap_score']:>1}/{10:<2}{gap_tag}"
              f"{setup['rsva_score']:>1}/{10:<2} "
              f"{setup['ambush_score']:>1}/{5:<2} "
              f"{setup['rsd_score']:>1}/{5:<2} "
              f"{setup['fundamental_score']:>1}/{5:<2} "
              f"{mode_tag:>5} {hv_tag}{hv_mode} {gpoint_tag}")
    print()

    # ---- Step 4: 分类输出（领先板块 / 领先股 / 回调股） ----
    setup_results.sort(key=lambda x: x["setup_total"], reverse=True)

    # ====== 一、领先板块 ======
    print("\n" + "=" * 72)
    print("🔴 一、领先板块 TOP5")
    print("=" * 72)
    for i, s in enumerate(sectors, 1):
        print(f"  {i}. {s['name']:　<8} 涨幅: {s['zdf']:>+.2f}%  领涨: {s['lead_stock']}")

    # ====== 二、领先股（强势突破型） ======
    # 条件: Setup≥40 + 突破评分≥8 + RSVA(rsva_20)≥65 → 强势突破
    leaders = [s for s in setup_results
               if s["setup_total"] >= 40 and s["breakout_score"] >= 8
               and s["details"].get("rsva_20", 0) >= 65]

    print(f"\n{'=' * 72}")
    print("🟢 二、领先股 — 强势突破信号 (Setup≥40 + 突破强 + RSVA高)")
    print("=" * 72)
    if leaders:
        print(f"  {'代码':<11} {'名称':<7} {'总分':>4} {'突破':>4} {'RSVA':>5} {'孤狼':>6} {'近高点':>6}  模式  {'月线'}  {'评级'}")
        print("  " + "-" * 78)
        for s in leaders:
            d = s["details"]
            lead_tag = f"+{d.get('lead_over_index',0):.0f}%" if d.get('lead_over_index',0) else ""
            level = "⭐⭐" if s["setup_total"] >= 55 else "⭐"
            gap_mark = " [断层]" if s["gap_score_display"] >= 8 else ""
            gpoint_mark = " [G点]" if d.get("has_gpoint", False) else ""
            mode_tag = s.get("trade_mode", "")
            m_tag = ""
            if s.get("month_reversal"):
                m_tag = "⚡反转"
            elif s.get("month_gate") == "PASS":
                m_tag = "🟢多头"
            elif s.get("month_gate") == "WARN":
                m_tag = "🟡纠缠"
            elif s.get("month_gate") == "BLOCK":
                m_tag = "🔴空头"
            else:
                m_tag = "—"
            print(f"  {s['code']:<11} {s['name']:<7} "
                  f"{s['setup_total']:>3}/{100:<2} "
                  f"{s['breakout_score']:>2}/{15:<2} "
                  f"{d.get('rsva_20',0):>4.0f}  "
                  f"{lead_tag:>6} "
                  f"{d.get('dist_from_high_pct',0):>4.1f}% "
                  f"{mode_tag:>4} "
                  f"{m_tag:>6} "
                  f"{level}{gap_mark}{gpoint_mark}")
    else:
        print(f"  ⚠️ 当前无符合条件的领先股")
        print(f"  说明: 大盘危险区(安全评分23.6)，强势突破信号难以形成")

    # ====== 三、回调股（基底回撤末期 + 低吸信号） ======
    # 条件: VCP收缩 + 缩量 + 伏击线低吸 or RS_D背离 → 回调低吸
    pullbacks = [s for s in setup_results
                 if (s["vcp_score"] >= 8 or
                     (s["details"].get("vol_ratio_5_20", 1) < 0.75
                      and s["details"].get("dist_from_high_pct", 0) > 5))
                 and s["setup_total"] >= 15]

    print(f"\n{'=' * 72}")
    print("🔵 三、回调股 — 基底回撤末期 (VCP收缩/缩量回踩)")
    print("=" * 72)
    if pullbacks:
        pullbacks.sort(key=lambda x: x["vcp_score"], reverse=True)
        print(f"  {'代码':<11} {'名称':<7} {'VCP':>4} {'距高点':>6} {'量比':>6} {'总分':>4} {'伏击':>4} {'RS_D':>4} {'月线':>6} 备注")
        print("  " + "-" * 72)
        for s in pullbacks:
            d = s["details"]
            notes = []
            if d.get("vcp_ratio", 1) < 0.6:
                notes.append("极致收缩")
            elif d.get("vcp_ratio", 1) < 0.8:
                notes.append("明显收缩")
            else:
                notes.append("量缩回踩")
            if s["ambush_score"] >= 3:
                notes.append("🔔伏击线")
            if s["rsd_score"] >= 3:
                notes.append("📉RS_D背离")
            if d.get("has_gpoint", False):
                notes.append("⚡G点")
            m_tag = ""
            if s.get("month_reversal"):
                m_tag = "⚡反转"
            elif s.get("month_gate") == "PASS":
                m_tag = "🟢多头"
            elif s.get("month_gate") == "WARN":
                m_tag = "🟡纠缠"
            elif s.get("month_gate") == "BLOCK":
                m_tag = "🔴空头"
            else:
                m_tag = "—"
            print(f"  {s['code']:<11} {s['name']:<7} "
                  f"{s['vcp_score']:>2}/{20:<2} "
                  f"{d.get('dist_from_high_pct',0):>5.1f}% "
                  f"{d.get('vol_ratio_5_20',1):>4.2f}  "
                  f"{s['setup_total']:>3}  "
                  f"{s['ambush_score']:>1}/{5:<2} "
                  f"{s['rsd_score']:>1}/{5:<2} "
                  f"{m_tag:>6} "
                  f"{' '.join(notes)}")
    else:
        print(f"  ⚠️ 当前无符合条件的回调股")
        print(f"  说明: 大盘处于上涨波段，多数股票振幅在扩大而非收缩")

    # ====== 四、综合评分表 ======
    print(f"\n{'=' * 90}")
    print("📋 四、候选股综合评分表")
    print("=" * 90)
    print(f"  {'排名':>3} {'代码':<11} {'名称':<7} "
          f"{'总分':>4} {'VCP':>3} {'均线':>3} {'量能':>3} {'VAD':>3} {'突破':>3} {'断层':>3} {'强度':>4} {'锚定':>4} {'合计':>4}")
    print("  " + "-" * 86)

    for i, s in enumerate(setup_results, 1):
        d = s["details"]
        total = s["setup_total"] + next(
            (c["ovs_total"] for c in ovs_results if c["code"] == s["code"]), 0)

        # 分类标记
        cat = ""
        if s in leaders:
            cat = "领先"
        elif s in pullbacks:
            cat = "回调"

        gap_mark = "⍟" if s.get("gap_score_display", 0) >= 8 else ""
        anchor_score = next((c.get("anchor_score", "-") for c in candidates if c["code"] == s["code"]), "-")
        anchor_str = f"{int(anchor_score)}" if isinstance(anchor_score, (int, float)) else "-"
        print(f"  {i:>2}  {s['code']:<11} {s['name']:<7} "
              f"{s['setup_total']:>3}/{100:<2} "
              f"{s['vcp_score']:>2}/{20:<2} "
              f"{s['ma_score']:>2}/{20:<2} "
              f"{s['volume_score']:>2}/{15:<2} "
              f"{s['vad_score']:>1}/{10:<2} "
              f"{s['breakout_score']:>2}/{15:<2} "
              f"{s['gap_score']:>1}/{10:<2}{gap_mark}"
              f"{d.get('rsva_20',0):>4.0f}  "
              f"{anchor_str:>4} "
              f"{total:>4} {cat}")

    # ---- Step 5: 操作建议 ----
    print(f"\n{'=' * 72}")
    print("💡 Step 5: 操作建议")
    print("=" * 72)

    gap_sigs = [s for s in setup_results if s.get("gap_score_display", 0) >= 8]
    gpoint_sigs = [s for s in setup_results if s["details"].get("has_gpoint", False)]
    ambush_sigs = [s for s in setup_results if s.get("ambush_score", 0) >= 3]
    rsd_sigs = [s for s in setup_results if s.get("rsd_score", 0) >= 3]

    if leaders:
        print(f"\n  🟢 【领先股关注】突破信号清晰, 可跟踪枢轴点确认")
        for s in leaders:
            d = s["details"]
            gap_info = f" [断层{s['gap_score_display']}分]" if s["gap_score_display"] >= 8 else ""
            gpoint_info = f" [⚡G点]" if d.get("has_gpoint", False) else ""
            mode_info = f" ({s['trade_mode']})" if s.get("trade_mode") else ""
            print(f"     {s['name']}({s['code']}) Setup={s['setup_total']}分 "
                  f"距高点{d.get('dist_from_high_pct',0):.1f}%{gap_info}{gpoint_info}{mode_info}")

    if pullbacks:
        print(f"\n  🔵 【回调股低吸】VCP收缩/量缩回踩")
        for s in pullbacks[:3]:
            d = s["details"]
            extras = []
            if s["ambush_score"] >= 3: extras.append("伏击线")
            if s["rsd_score"] >= 3: extras.append("RS_D背离")
            if d.get("has_gpoint", False): extras.append("G点")
            extra_str = f" [{', '.join(extras)}]" if extras else ""
            print(f"     {s['name']}({s['code']}) VCP={s['vcp_score']}分 "
                  f"距高点{d.get('dist_from_high_pct',0):.1f}%{extra_str}")

    if gpoint_sigs:
        print(f"\n  ⚡ 【G点信号】堆量间隙弱转强")
        for s in gpoint_sigs:
            d = s["details"]
            print(f"     {s['name']}({s['code']}) PV3={d.get('pv3',0):.0f} "
                  f"OV3={d.get('ov3',0):.0f} 模式={s['trade_mode']}")

    if ambush_sigs:
        print(f"\n  🔔 【伏击线信号】低波动率低吸点")
        for s in ambush_sigs:
            print(f"     {s['name']}({s['code']}) 伏击线={s['ambush_score']}分 "
                  f"UB={s['details'].get('ambush_ub',0):.2f}")

    if rsd_sigs:
        print(f"\n  📉 【RS_D背离信号】低吸区")
        for s in rsd_sigs:
            d = s["details"]
            print(f"     {s['name']}({s['code']}) DR5={d.get('dr5',0):.1f} "
                  f"DR4={d.get('dr4',0):.1f}")

    if pullbacks:
        print(f"\n  🔵 【回调股关注】基底回撤末期, 等待放量突破确认")
        for s in pullbacks[:5]:
            d = s["details"]
            print(f"     {s['name']}({s['code']}) VCP收缩={d.get('vcp_ratio','N/A')} "
                  f"距高点{d.get('dist_from_high_pct',0):.1f}% "
                  f"Setup={s['setup_total']}分")

    if gap_sigs:
        print(f"\n  📊 【净利润断层信号】业绩超预期, 进一步分析基本面")
        for s in gap_sigs:
            d = s["details"]
            print(f"     {s['name']}({s['code']}) 扣非增速:{d.get('np_growth',0)}% "
                  f"跳空:{'是' if d.get('gap_detected') else '否'}")

    if not leaders and not pullbacks:
        print(f"\n  ⚠️  当前市场环境危险(安全评分23.6), 无明确信号")
        print(f"     建议等待大盘企稳后再关注")

    # ---- 综合总结 ----
    print(f"\n{'=' * 90}")
    print("📋 综合总结")
    print("-" * 90)
    print(f"  大盘状态: {safety['level']} ({safety['score']:.0f}/100) 情绪: {safety['emotion_detail']}")
    print(f"  热门板块TOP3: {', '.join([s['name'] for s in sectors[:3]])}")
    print(f"  领先板块: {len(sectors)}个 | 领先股: {len(leaders)}只 | 回调股: {len(pullbacks)}只")
    print(f"  净利润断层: {len(gap_sigs)}只 | G点信号: {len(gpoint_sigs)}只")
    print(f"  伏击线低吸: {len(ambush_sigs)}只 | RS_D背离: {len(rsd_sigs)}只")
    # 统计三季盈增通过数
    anchor_count = sum(1 for c in candidates if c.get("anchor_score", 0) > 0)
    if anchor_count:
        # total_candidates 在 Step 2.5 中定义
        try:
            print(f"  🏭 产业锚定4通过: {anchor_count}/{total_candidates}只")
        except NameError:
            print(f"  🏭 产业锚定4通过: {anchor_count}只")
    print(f"\n  📌 信号分类解读:")
    print(f"     🟢 领先股 = 强势突破+高RSVA+孤狼 → 跟踪枢轴点确认")
    print(f"     🔵 回调股 = VCP收缩+量缩回踩 → 等待放量突破/伏击线/RS_D确认")
    print(f"     ⚡ G点 = 堆量间隙弱转强信号 → 堆量模式/欧马模式双模式识别")
    print(f"     📊 断层股 = 净利润跳空+高增速 → 基本面驱动型Setup")
    print(f"     🔔 伏击线 = 低波动率低吸点 → 爬升途中回调末端")
    print(f"     📉 RS_D背离 = 斜率差底背离 → 动量角度低吸信号")
    print("=" * 90)


if __name__ == "__main__":
    main()