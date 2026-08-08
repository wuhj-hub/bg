#!/usr/bin/env python3
"""
猛兽派选股 · 全信号因子回测系统 v1.0
=====================================
对热门沪深主板股进行全部选股信号的量化回测
覆盖: 堆量启动/G点/绿钻枢轴/高阳模式/TR持股线/TTM增长/连续增速/ROE

运行: python3 full_signal_backtest.py
"""

import subprocess, sys, os, re, json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

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
    if not lines: return []
    header_idx = None
    for i, ln in enumerate(lines):
        if '| ---' in ln or '|:---' in ln:
            header_idx = i - 1; break
    if header_idx is None: return []
    headers = [h.strip() for h in lines[header_idx].split('|') if h.strip()]
    data_lines = lines[header_idx + 2:]
    results = []
    for ln in data_lines:
        parts = ln.split('|')
        cols = [p.strip() for p in parts[1:-1]]
        if len(cols) >= len(headers):
            results.append({h: cols[j] if j < len(cols) else "" for j, h in enumerate(headers)})
        else:
            cols = [c.strip() for c in parts if c.strip()]
            if len(cols) >= len(headers):
                results.append({h: cols[j] if j < len(cols) else "" for j, h in enumerate(headers)})
    return results

def is_mainboard(code: str) -> bool:
    prefix = re.match(r'(?:sh|sz|)(\d+)', code)
    if not prefix: return False
    num = prefix.group(1)
    if num.startswith(('688','300','301','8','43','83','87')): return False
    return True

def get_kline_df(code: str, limit: int = 200) -> pd.DataFrame:
    raw = cli(f"kline {code} --period day --limit {limit}")
    rows = parse_table(raw)
    if len(rows) < 20: return pd.DataFrame()
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
        except: continue
    df = pd.DataFrame(records)
    if df.empty: return df
    df = df.sort_values("date").reset_index(drop=True)
    for c in ['open','close','high','low','volume','amount']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df

def get_val(row: dict, *keys) -> str:
    for k in keys:
        if k in row: return row[k]
    return ""

# ================================================================
#         信号因子定义 (全部16种可量化因子)
# ================================================================

def compute_all_signals(df: pd.DataFrame) -> pd.DataFrame:
    """对DataFrame逐日计算全部信号因子"""
    if df.empty or len(df) < 60: return df

    n = len(df)
    # --- 基础指标 ---
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma5_vol'] = df['volume'].rolling(5).mean()
    df['ma20_vol'] = df['volume'].rolling(20).mean()
    df['amplitude'] = (df['high'] - df['low']) / df['close'] * 100
    df['daily_ret'] = df['close'].pct_change()
    df['high_60'] = df['high'].rolling(60).max()
    df['low_60'] = df['low'].rolling(60).min()

    # --- RSV1 (自身强度) ---
    def rsv1(series_high, series_low, series_close, n=20):
        hh = series_high.rolling(n).max()
        ll = series_low.rolling(n).min()
        return (series_close - ll) / (hh - ll).replace(0, np.nan) * 100
    df['rsv1'] = rsv1(df['high'], df['low'], df['close'])

    # ============================================================
    #  信号1: 堆量启动信号 (基于OVS堆量模式)
    # ============================================================
    df['vol_ratio'] = df['ma5_vol'] / df['ma20_vol'].replace(0, np.nan)
    df['amount_ma5'] = df['amount'].rolling(5).mean()
    df['amount_ma20'] = df['amount'].rolling(20).mean()
    df['amount_ratio'] = df['amount_ma5'] / df['amount_ma20'].replace(0, np.nan)
    # PV3近似: 量比累加3日
    df['pv3'] = df['vol_ratio'].rolling(3).sum()
    # OV3近似: 成交额比累加3日
    df['ov3'] = df['amount_ratio'].rolling(3).sum()
    # 堆量启动: PV3>40, OV3>30, PV3>OV3, 且突破60日高点
    df['sig_duiliang_start'] = (
        (df['pv3'] > 3.0) & (df['ov3'] > 2.5) &
        (df['pv3'] > df['ov3']) &
        (df['close'] >= df['high_60'] * 0.98)
    ).astype(int)

    # ============================================================
    #  信号2: 堆量骑牛G点 (高位横盘后弱转强)
    # ============================================================
    # 条件: 之前有放量突破 → 然后缩量横盘 → 再次放量
    df['vol_surge'] = (df['volume'] > df['ma20_vol'] * 1.8).astype(int)
    # 放量突破标记（前10日内有放量且创新高）
    df['had_surge_10d'] = df['vol_surge'].rolling(10).sum() > 0
    # 当前缩量横盘: 量比<0.8, 价格波动小
    df['is_sideways'] = ((df['vol_ratio'] < 0.8) &
                         (df['amplitude'] < df['amplitude'].rolling(20).mean())).astype(int)
    # G点: 之前有放量→缩量横盘→现在再次放量且价格向上
    df['sig_g_point'] = (
        df['had_surge_10d'].shift(1) &
        (df['is_sideways'].rolling(5).sum() >= 3) &
        (df['volume'] > df['ma20_vol'] * 1.3) &
        (df['close'] > df['open'])
    ).astype(int)

    # ============================================================
    #  信号3: 绿钻 (极致缩量回踩)
    # ============================================================
    # 条件: 量比<0.5 + 价格在60日均线附近或上方 + 振幅小
    df['sig_green_diamond'] = (
        (df['vol_ratio'] < 0.5) &
        (df['close'] >= df['ema60'] * 0.95) &
        (df['close'] <= df['ema60'] * 1.05) &
        (df['amplitude'] < df['amplitude'].rolling(20).mean() * 0.7)
    ).astype(int)

    # ============================================================
    #  信号4: 枢轴信号 (缩量回撤末端反转)
    # ============================================================
    # 条件: 前期缩量 + 当日放量阳线 + 站上5EMA
    df['sig_pivot'] = (
        (df['vol_ratio'].shift(1) < 0.7) &
        (df['close'] > df['open']) &
        (df['volume'] > df['ma5_vol'] * 1.3) &
        (df['close'] > df['ema5'])
    ).astype(int)

    # ============================================================
    #  信号5: 高阳突破模式分类
    # ============================================================
    df['is_high_vol_up'] = (df['close'] > df['open']) & (df['volume'] > df['ma20_vol'] * 1.5)
    # 模式1: 快速推升 (高阳后3日内继续上涨)
    df['mode_fast_rise'] = (
        df['is_high_vol_up'] &
        (df['daily_ret'].shift(-1) > 0) &
        (df['daily_ret'].shift(-2) > 0)
    ).astype(int)
    # 模式2: 迅速跌落 (高阳后次日放量下跌击穿持股线)
    df['mode_fast_fall'] = (
        df['is_high_vol_up'] &
        (df['close'].shift(-1) < df['ema5'].shift(-1)) &
        (df['volume'].shift(-1) > df['ma20_vol'].shift(-1))
    ).astype(int)
    # 模式3: 小K线5日浮盈 (高阳后小K线不跌)
    df['mode_small_k'] = (
        df['is_high_vol_up'] &
        (df['close'].shift(-1) >= df['close']) &
        (abs(df['daily_ret'].shift(-1)) < 2)
    ).astype(int)
    # 模式4: 价缓量急缩 (红肥绿瘦)
    close_3d = df['close'].rolling(3).mean()
    df['mode_slow_price'] = (
        (df['volume'] < df['ma20_vol'] * 0.6) &
        (close_3d > close_3d.shift(1))
    ).astype(int)

    # ============================================================
    #  信号6: TR持股线 (动态支撑/止损参考)
    # ============================================================
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr14'] = df['tr'].rolling(14).mean()
    # TR持股线 = EMA20 - 2*ATR(14)  (近似猛兽派的持股线)
    df['tr_line'] = df['ema20'] - df['atr14'] * 2
    df['above_tr'] = (df['close'] > df['tr_line']).astype(int)
    df['break_tr'] = ((df['close'].shift(1) > df['tr_line'].shift(1)) &
                      (df['close'] <= df['tr_line'])).astype(int)

    # ============================================================
    #  信号7: TTM增长 + 当季增长 (基本面)
    # ============================================================
    # 这个需要finance数据，在后续单独处理

    # ============================================================
    #  信号8: ROE选股 (基本面)
    # ============================================================
    # 需要finance数据，后续处理

    # ============================================================
    #  信号9: 孤狼信号 (跑赢大盘)
    # ============================================================
    # 与前5日涨幅比较 (已集成在Setup评分中)
    ret_5d = df['close'].pct_change(5)
    df['sig_lone_wolf'] = (ret_5d > 0.05).astype(int)  # 5日涨幅>5%

    # ============================================================
    #  信号10: 抗跌信号
    # ============================================================
    # 大盘下跌时个股跌得少 — 需要指数数据，这里用简化版
    # 近10日最大回撤 < 5%
    max_drawdown_10d = 1 - df['close'].rolling(10).min() / df['close'].rolling(10).max()
    df['sig_anti_fall'] = (max_drawdown_10d < 0.05).astype(int)

    # ============================================================
    #  信号11-16: Setup评分各子维度信号
    # ============================================================
    # 均线多头
    df['sig_ma_bull'] = ((df['ema5'] > df['ema20']) & (df['ema20'] > df['ema60'])).astype(int)
    # VCP收缩
    amp_5 = df['amplitude'].rolling(5).mean()
    amp_20 = df['amplitude'].rolling(20).mean()
    df['vcp_ratio'] = amp_5 / amp_20
    df['sig_vcp'] = (df['vcp_ratio'] < 0.65).astype(int)
    # TSI信号
    mu = df['daily_ret'].rolling(20).mean()
    sigma = df['daily_ret'].rolling(20).std()
    df['tsi'] = mu / sigma
    df['sig_tsi'] = (df['tsi'] > 0.5).astype(int)
    # 突破确认
    dist_high = (df['high_60'] - df['close']) / df['high_60'] * 100
    df['sig_breakout'] = (dist_high < 3).astype(int)

    return df


def backtest_signal(df: pd.DataFrame, signal_col: str,
                    hold_days: list = [5, 10, 20],
                    signal_name: str = "") -> dict:
    """对单个信号做回测统计"""
    if signal_col not in df.columns:
        return {"signal": signal_name, "total_signals": 0, "error": "no data"}

    signal_dates = df[df[signal_col] == 1].index
    total = len(signal_dates)
    if total == 0:
        return {"signal": signal_name, "total_signals": 0}

    results = {"signal": signal_name, "total_signals": total}
    
    for hd in hold_days:
        win = 0
        returns = []
        for idx in signal_dates:
            if idx + hd < len(df):
                ret = (df.loc[idx + hd, 'close'] - df.loc[idx, 'close']) / df.loc[idx, 'close'] * 100
                returns.append(ret)
                if ret > 0:
                    win += 1
        if returns:
            results[f"win_rate_{hd}d"] = round(win / len(returns) * 100, 1)
            results[f"avg_return_{hd}d"] = round(np.mean(returns), 2)
            results[f"max_return_{hd}d"] = round(max(returns), 2)
            results[f"min_return_{hd}d"] = round(min(returns), 2)
            results[f"sample_{hd}d"] = len(returns)
        else:
            results[f"win_rate_{hd}d"] = 0
            results[f"avg_return_{hd}d"] = 0

    return results


def main():
    print("=" * 80)
    print("  猛兽派选股 · 全信号因子回测系统 v1.0")
    print(f"  回测时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("  信号覆盖: 堆量启动/G点/绿钻枢轴/高阳模式/TR持股线等")
    print("=" * 80)

    # ---- Step 1: 获取样本股 ----
    print("\n📦 Step 1: 获取回测样本股 (热门沪深主板股)")
    print("-" * 50)
    raw = cli("hot stock --limit 50")
    rows = parse_table(raw)
    sample_stocks = []
    seen = set()
    for r in rows:
        code = get_val(r, "code", "代码")
        name = get_val(r, "name", "名称")
        stype = get_val(r, "stock_type", "类型")
        if stype and stype != "GP-A": continue
        if not is_mainboard(code): continue
        if 'ST' in name or '*ST' in name: continue
        if code in seen: continue
        seen.add(code)
        sample_stocks.append({"code": code, "name": name})
    print(f"  获取到 {len(sample_stocks)} 只样本股")

    # ---- Step 2: 获取K线数据并计算信号 ----
    print("\n⚙️ Step 2: 获取K线数据并计算全部信号因子")
    print("-" * 50)
    
    all_signals_summary = {}  # signal_name -> list of results
    
    for i, stock in enumerate(sample_stocks):
        code = stock["code"]
        name = stock["name"]
        print(f"  [{i+1}/{len(sample_stocks)}] {name}({code})... ", end="", flush=True)
        
        df = get_kline_df(code, 150)
        if df.empty or len(df) < 60:
            print("数据不足,跳过")
            continue
        
        df = compute_all_signals(df)
        if df.empty or len(df) < 60:
            print("计算失败,跳过")
            continue
        
        # 收集所有信号的回测结果
        signal_cols = [c for c in df.columns if c.startswith('sig_') or c.startswith('mode_') or c.startswith('above_') or c.startswith('break_')]
        
        for sc in signal_cols:
            sig_name = sc.replace('sig_', '').replace('mode_', 'mode_')
            bt = backtest_signal(df, sc, hold_days=[5, 10, 20], signal_name=sig_name)
            if bt["total_signals"] > 0:
                if sc not in all_signals_summary:
                    all_signals_summary[sc] = {"count": 0, "win_5d": [], "win_10d": [], "win_20d": [],
                                                "ret_5d": [], "ret_10d": [], "ret_20d": []}
                all_signals_summary[sc]["count"] += bt["total_signals"]
                if "win_rate_5d" in bt:
                    all_signals_summary[sc]["win_5d"].append(bt["win_rate_5d"])
                    all_signals_summary[sc]["ret_5d"].append(bt["avg_return_5d"])
                if "win_rate_10d" in bt:
                    all_signals_summary[sc]["win_10d"].append(bt["win_rate_10d"])
                    all_signals_summary[sc]["ret_10d"].append(bt["avg_return_10d"])
                if "win_rate_20d" in bt:
                    all_signals_summary[sc]["win_20d"].append(bt["win_rate_20d"])
                    all_signals_summary[sc]["ret_20d"].append(bt["avg_return_20d"])
        
        print(f"信号计算完成")
        
        # ---- 基本面信号处理 ----
        fin_raw = cli(f"finance {code} --type sum --num 8")
        fin_rows = parse_table(fin_raw)
        if fin_rows and len(fin_rows) >= 4:
            try:
                # 解析财务数据
                # 最新一期
                r0 = fin_rows[0]  # 最新财报
                r4 = fin_rows[4]  # 去年同期（第5行，num=8时）
                
                # TTM扣非净利润: 最近4期扣非之和
                np_list = []
                rev_list = []
                for j in range(4):
                    np_val = get_val(fin_rows[j], "NPDeductNonRecurringPL", "nPDeductNonRecurringPL")
                    rev_val = get_val(fin_rows[j], "OperatingRevenue_Q", "operatingRevenue_Q")
                    if np_val:
                        try: np_list.append(float(np_val))
                        except: pass
                    if rev_val:
                        try: rev_list.append(float(rev_val))
                        except: pass
                
                # TTM同期对比
                np_list_prev = []
                rev_list_prev = []
                for j in range(4, min(8, len(fin_rows))):
                    np_val = get_val(fin_rows[j], "NPDeductNonRecurringPL", "nPDeductNonRecurringPL")
                    rev_val = get_val(fin_rows[j], "OperatingRevenue_Q", "operatingRevenue_Q")
                    if np_val:
                        try: np_list_prev.append(float(np_val))
                        except: pass
                    if rev_val:
                        try: rev_list_prev.append(float(rev_val))
                        except: pass
                
                # 获取直接同比数据
                rev_grow_str = get_val(r0, "OperatingRevenueGrowRate_Q", "operatingRevenueGrowRate_Q")
                np_grow_str = get_val(r0, "NPParentCompanyYOY_Q", "nPParentCompanyYOY_Q")
                roe_str = get_val(r0, "ROE", "roe")
                
                rev_grow_q = float(rev_grow_str.replace("%","")) if rev_grow_str and rev_grow_str != '-' else 0
                np_grow_q = float(np_grow_str.replace("%","")) if np_grow_str and np_grow_str != '-' else 0
                roe_val = float(roe_str.replace("%","")) if roe_str and roe_str != '-' else 0
                
                # TTM同比增速
                ttm_np = sum(np_list) if len(np_list) >= 4 else 0
                ttm_np_prev = sum(np_list_prev) if len(np_list_prev) >= 4 else 0
                ttm_rev = sum(rev_list) if len(rev_list) >= 4 else 0
                ttm_rev_prev = sum(rev_list_prev) if len(rev_list_prev) >= 4 else 0
                
                ttm_np_grow = (ttm_np - ttm_np_prev) / abs(ttm_np_prev) * 100 if ttm_np_prev != 0 else 0
                ttm_rev_grow = (ttm_rev - ttm_rev_prev) / abs(ttm_rev_prev) * 100 if ttm_rev_prev != 0 else 0
                
                # 上季增速
                r1 = fin_rows[1] if len(fin_rows) > 1 else None
                rev_grow_q1_str = get_val(r1, "OperatingRevenueGrowRate_Q", "operatingRevenueGrowRate_Q") if r1 else "0"
                np_grow_q1_str = get_val(r1, "NPParentCompanyYOY_Q", "nPParentCompanyYOY_Q") if r1 else "0"
                rev_grow_q1 = float(rev_grow_q1_str.replace("%","")) if rev_grow_q1_str and rev_grow_q1_str != '-' else 0
                np_grow_q1 = float(np_grow_q1_str.replace("%","")) if np_grow_q1_str and np_grow_q1_str != '-' else 0
                
                # 信号17: TTM增长选股
                sig_ttm = (ttm_rev_grow > 5 and ttm_np_grow > 8 and rev_grow_q > 8 and np_grow_q > 10)
                
                # 信号18: 连续两季高增速选股
                sig_growth2q = ((rev_grow_q > 10 and rev_grow_q1 > 8 and np_grow_q > 12 and np_grow_q1 > 10) or
                                (np_grow_q > 20 and rev_grow_q > 15))
                
                # 信号19: ROE选股
                # 获取过去3年的ROE
                roe_years = []
                for j in range(min(8, len(fin_rows))):
                    roe_s = get_val(fin_rows[j], "ROE", "roe")
                    if roe_s and roe_s != '-':
                        try: roe_years.append(float(roe_s.replace("%","")))
                        except: pass
                
                sig_roe = (len(roe_years) >= 3 and all(r > 15 for r in roe_years[:3]))
                
                # 将基本面信号标记到df中
                if sig_ttm:
                    df['sig_ttm_growth'] = 1
                else:
                    df['sig_ttm_growth'] = 0
                    
                if sig_growth2q:
                    df['sig_consec_growth'] = 1
                else:
                    df['sig_consec_growth'] = 0
                    
                if sig_roe:
                    df['sig_roe'] = 1
                else:
                    df['sig_roe'] = 0
                
                # 回测基本面信号
                fin_signal_cols = ['sig_ttm_growth', 'sig_consec_growth', 'sig_roe']
                for sc in fin_signal_cols:
                    bt = backtest_signal(df, sc, hold_days=[5, 10, 20], signal_name=sc.replace('sig_',''))
                    if bt["total_signals"] > 0:
                        if sc not in all_signals_summary:
                            all_signals_summary[sc] = {"count": 0, "win_5d": [], "win_10d": [], "win_20d": [],
                                                        "ret_5d": [], "ret_10d": [], "ret_20d": []}
                        all_signals_summary[sc]["count"] += bt["total_signals"]
                        if "win_rate_5d" in bt:
                            all_signals_summary[sc]["win_5d"].append(bt["win_rate_5d"])
                            all_signals_summary[sc]["ret_5d"].append(bt["avg_return_5d"])
                        if "win_rate_10d" in bt:
                            all_signals_summary[sc]["win_10d"].append(bt["win_rate_10d"])
                            all_signals_summary[sc]["ret_10d"].append(bt["avg_return_10d"])
                        if "win_rate_20d" in bt:
                            all_signals_summary[sc]["win_20d"].append(bt["win_rate_20d"])
                            all_signals_summary[sc]["ret_20d"].append(bt["avg_return_20d"])
                
                print(f"信号+基本面完成")
            except Exception as e:
                print(f"基本面计算异常:{e}")
        else:
            print(f"信号计算完成")

    # ---- Step 3: 输出回测报告 ----
    print(f"\n{'=' * 80}")
    print("📊 Step 3: 全信号因子回测报告")
    print("=" * 80)

    signal_names = {
        "sig_duiliang_start": "① 堆量启动信号",
        "sig_g_point": "② 堆量骑牛G点",
        "sig_green_diamond": "③ 绿钻信号",
        "sig_pivot": "④ 枢轴信号",
        "sig_lone_wolf": "⑤ 孤狼信号",
        "sig_anti_fall": "⑥ 抗跌信号",
        "sig_ma_bull": "⑦ 均线多头排列",
        "sig_vcp": "⑧ VCP收缩信号",
        "sig_tsi": "⑨ TSI信噪比信号",
        "sig_breakout": "⑩ 突破确认信号",
        "mode_fast_rise": "⑪ 高阳·快速推升",
        "mode_fast_fall": "⑫ 高阳·迅速跌落(风险)",
        "mode_small_k": "⑬ 高阳·小K线浮盈",
        "mode_slow_price": "⑭ 价缓量急缩(红肥绿瘦)",
        "above_tr": "⑮ TR持股线上方(健康)",
        "break_tr": "⑯ TR持股线跌破(风险)",
        "sig_ttm_growth": "⑰ TTM增长选股(基本面)",
        "sig_consec_growth": "⑱ 连续两季增速(基本面)",
        "sig_roe": "⑲ ROE连续三年>15%(基本面)",
    }

    # 输出表头
    print(f"\n  {'信号名称':<20} {'总信号':>6} {'5日胜率':>8} {'5日收益':>8} "
          f"{'10日胜率':>8} {'10日收益':>8} {'20日胜率':>8} {'20日收益':>8}")
    print("  " + "-" * 80)

    # 按总信号数排序
    sorted_signals = sorted(all_signals_summary.items(),
                           key=lambda x: x[1]["count"], reverse=True)

    for sig_key, data in sorted_signals:
        name = signal_names.get(sig_key, sig_key)
        win5 = round(np.mean(data["win_5d"]), 1) if data["win_5d"] else 0
        win10 = round(np.mean(data["win_10d"]), 1) if data["win_10d"] else 0
        win20 = round(np.mean(data["win_20d"]), 1) if data["win_20d"] else 0
        ret5 = round(np.mean(data["ret_5d"]), 2) if data["ret_5d"] else 0
        ret10 = round(np.mean(data["ret_10d"]), 2) if data["ret_10d"] else 0
        ret20 = round(np.mean(data["ret_20d"]), 2) if data["ret_20d"] else 0
        
        print(f"  {name:<20} {data['count']:>6} "
              f"{win5:>7.1f}% {ret5:>+7.2f}% "
              f"{win10:>7.1f}% {ret10:>+7.2f}% "
              f"{win20:>7.1f}% {ret20:>+7.2f}%")

    # ---- Step 4: 信号有效性评级 ----
    print(f"\n{'=' * 80}")
    print("🏆 Step 4: 信号有效性评级")
    print("=" * 80)

    # 按20日胜率排序
    effectiveness = []
    for sig_key, data in all_signals_summary.items():
        if not data["win_20d"]:
            continue
        win20 = np.mean(data["win_20d"])
        ret20 = np.mean(data["ret_20d"])
        total = data["count"]
        effectiveness.append({
            "name": signal_names.get(sig_key, sig_key),
            "win20": win20,
            "ret20": ret20,
            "count": total
        })

    effectiveness.sort(key=lambda x: x["win20"], reverse=True)

    print(f"\n  {'评级':>4} {'信号名称':<22} {'总信号':>6} {'20日胜率':>8} {'20日收益':>8}")
    print("  " + "-" * 55)
    for i, e in enumerate(effectiveness):
        if e["win20"] >= 55:
            rank = "⭐⭐⭐"
        elif e["win20"] >= 50:
            rank = "⭐⭐"
        elif e["win20"] >= 45:
            rank = "⭐"
        else:
            rank = "  -"
        print(f"  {rank:>4} {e['name']:<22} {e['count']:>6} "
              f"{e['win20']:>7.1f}% {e['ret20']:>+7.2f}%")

    # ---- 基本面信号单独报告 ----
    print(f"\n{'=' * 80}")
    print("📋 综合总结")
    print("-" * 80)
    print(f"  回测样本: {len(sample_stocks)} 只沪深主板热门股")
    print(f"  回测周期: 近150个交易日")
    print(f"  信号数量: {len(sorted_signals)} 个因子")
    print(f"\n  📌 信号有效性解读:")
    print(f"     ⭐⭐⭐ 胜率≥55% = 高有效性信号")
    print(f"     ⭐⭐  胜率50-55% = 中等有效性信号")
    print(f"     ⭐   胜率45-50% = 参考性信号")
    print(f"     -    胜率<45% = 有效性不足")
    print(f"\n  📌 注意: 回测基于历史数据，不保证未来表现")
    print(f"     基本面信号(TTM/ROE)需要财务数据API支持，未纳入本回测")
    print("=" * 80)


if __name__ == "__main__":
    main()
