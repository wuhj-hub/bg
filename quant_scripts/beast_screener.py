#!/usr/bin/env python3
"""
猛兽体系 · 趋势量化扫描系统 v2.1
=================================
三层漏斗 + Layer 3.5 Setup量化评分 (七维 + 抗跌孤狼 + RSVA + 净利润断层)
基于猛兽选股派知识库升级

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
def get_candidate_stocks(max_count: int = 0) -> list[dict]:
    """从 all_mainboard.csv 读取全量主板（替代 hot stock 精选）"""
    candidates = []
    csv_path = "all_mainboard.csv"
    if os.path.exists(csv_path):
        import csv
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("code", "").strip()
                name = row.get("name", "").strip()
                if not code or not name:
                    continue
                if not is_mainboard(code):
                    continue
                if not is_not_st(name):
                    continue
                pref = "sh" if code.startswith("6") else "sz"
                candidates.append({"code": pref + code, "name": name, "zdf": 0, "price": 0})
        print(f"[candidate] 全量主板: {len(candidates)} 只")
    else:
        # fallback: hot stock 精选
        raw = cli("hot stock --limit 50")
        rows = parse_table(raw)
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
                price = float(price_str) if price_str else 0
            except:
                price = 0
            candidates.append({"code": code, "name": name, "zdf": zdf, "price": price})
            if max_count > 0 and len(candidates) >= max_count:
                break
        print(f"[candidate] fallback hot stock: {len(candidates)} 只")
    # max_count > 0 时截断
    if max_count > 0 and len(candidates) > max_count:
        candidates = candidates[:max_count]
    return candidates
def ovs_score_stock(code: str, name: str) -> dict:
    result = {"code": code, "name": name, "ovs_total": 0,
              "ovs_volume": 0, "ovs_momentum": 0, "ovs_trend": 0}

    tech_raw = cli(f"technical {code} --group all")
    tech_rows = parse_table(tech_raw)
    if not tech_rows:
        return result
    row = tech_rows[0]

    # 量价评分 (0-35)
    vol_score = 15
    dif_str = row.get("macd.DIF", row.get("DIF", ""))
    dea_str = row.get("macd.DEA", row.get("DEA", ""))
    if dif_str and dea_str and dif_str != '-' and dea_str != '-':
        try:
            dif = float(dif_str); dea = float(dea_str)
            if dif > dea and dif > 0: vol_score = 28
            elif dif > dea: vol_score = 22
            elif dif < dea and dif < 0: vol_score = 8
            else: vol_score = 15
        except: pass
    rsi_str = row.get("rsi.RSI_6", row.get("RSI_6", ""))
    if rsi_str and rsi_str != '-':
        try:
            rsi = float(rsi_str)
            if rsi < 30: vol_score = min(35, vol_score + 5)
            elif 30 < rsi < 70: vol_score = min(35, vol_score + 3)
        except: pass
    result["ovs_volume"] = min(35, vol_score)

    # 动量评分 (0-35)
    mom_score = 15
    adx_str = row.get("dmi.ADX", row.get("ADX", ""))
    if adx_str and adx_str != '-':
        try:
            adx = float(adx_str)
            if adx > 25: mom_score = 28
            elif adx > 20: mom_score = 22
            elif adx > 15: mom_score = 18
            else: mom_score = 12
        except: pass
    kj_str = row.get("kdj.KDJ_J", row.get("KDJ_J", ""))
    if kj_str and kj_str != '-':
        try:
            kj = float(kj_str)
            if kj > 100: mom_score = min(35, mom_score + 5)
            elif kj > 80: mom_score = min(35, mom_score + 3)
        except: pass
    result["ovs_momentum"] = min(35, mom_score)

    # 趋势评分 (0-30)
    trend_score = 12
    ma5 = row.get("ma.MA_5", row.get("MA_5", ""))
    ma20 = row.get("ma.MA_20", row.get("MA_20", ""))
    ma60 = row.get("ma.MA_60", row.get("MA_60", ""))
    if ma5 and ma20 and ma60:
        try:
            m5 = float(ma5) if ma5 != '-' else 0
            m20 = float(ma20) if ma20 != '-' else 0
            m60 = float(ma60) if ma60 != '-' else 0
            if m5 > m20 > m60: trend_score = 25
            elif m5 > m20: trend_score = 18
            elif m5 > m60: trend_score = 15
        except: pass
    boll_mid = row.get("boll.BOLL_MID", row.get("BOLL_MID", ""))
    close_str = row.get("closePrice", row.get("last", ""))
    if boll_mid and close_str and boll_mid != '-' and close_str != '-':
        try:
            if float(close_str) > float(boll_mid):
                trend_score = min(30, trend_score + 5)
        except: pass
    result["ovs_trend"] = min(30, trend_score)
    result["ovs_total"] = result["ovs_volume"] + result["ovs_momentum"] + result["ovs_trend"]
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
    Setup量化评分 v2.1 (0-100分)
    七维评分：
      ① VCP波动收缩率 (0-20分)
      ② 均线系统 (0-20分) — 融入趋势判断
      ③ 成交量 (0-15分)
      ④ TSI趋势信噪比 (0-10分) — 融入抗跌逻辑
      ⑤ 突破确认+孤狼 (0-15分) — 融入孤狼检测
      ⑥ 净利润断层 (0-15分) — ★新增
      ⑦ RSVA相对强度 (0-5分) — ★新增
    """
    result = {
        "code": code, "name": name,
        "setup_total": 0,
        "vcp_score": 0, "ma_score": 0, "volume_score": 0,
        "tsi_score": 0, "breakout_score": 0,
        "gap_score": 0, "rsva_score": 0,
        "anti_fall_score": 0, "fundamental_score": 0,
        "details": {}
    }

    # ---- 获取K线数据 ----
    df = parse_kline_df(code, 60)
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
    #  ③ 成交量评分 (0-15分)
    # ============================================================
    vol_5 = df["volume"].tail(5).mean()
    vol_20 = df["volume"].tail(20).mean()
    vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1.0
    latest_vol = df["volume"].iloc[-1]
    vol_break_ratio = latest_vol / vol_20 if vol_20 > 0 else 0

    vol_score = 0
    if vol_ratio < 0.5: vol_score += 8
    elif vol_ratio < 0.7: vol_score += 5
    elif vol_ratio < 0.9: vol_score += 3

    if vol_break_ratio > 1.8: vol_score += 7
    elif vol_break_ratio > 1.4: vol_score += 5
    elif vol_break_ratio > 1.1: vol_score += 3

    result["volume_score"] = min(15, vol_score)
    result["details"]["vol_ratio_5_20"] = round(vol_ratio, 3)

    # ============================================================
    #  ④ TSI趋势信噪比 (0-10分) + 抗跌逻辑融入
    # ============================================================
    df["daily_return"] = df["close"].pct_change()
    recent_returns = df["daily_return"].tail(20).dropna()
    if len(recent_returns) >= 10:
        mu = recent_returns.mean()
        sigma = recent_returns.std()
        tsi = mu / sigma if sigma > 0 else 0

        if tsi > 0.8: tsi_score = 10
        elif tsi > 0.5: tsi_score = 8
        elif tsi > 0.3: tsi_score = 5
        elif tsi > 0.1: tsi_score = 3
        elif tsi > 0: tsi_score = 2
        elif tsi > -0.1: tsi_score = 1
        else: tsi_score = 0

        result["details"]["tsi"] = round(tsi, 3)

        # ★ 抗跌逻辑融入: 如果TSI为正，计算抗跌加分
        if tsi > 0 and not index_df.empty:
            anti = calc_anti_fall(df, index_df, 20)
            result["anti_fall_score"] = round(anti, 1)
            # 抗跌加分: 抗跌>70 加2分, >50加1分
            if anti > 70:
                tsi_score = min(10, tsi_score + 2)
            elif anti > 50:
                tsi_score = min(10, tsi_score + 1)
    else:
        tsi_score = 0

    result["tsi_score"] = tsi_score

    # ============================================================
    #  ⑤ 突破确认评分 (0-18分) + 高阳模式 + 孤狼信号
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

    # ★ 高阳模式量价行为分析 ★ (新增)
    # 识别近15日内的高阳（放量阳线）
    df['is_high_vol_up'] = ((df['close'] > df['open']) &
                            (df['volume'] > df['ma20_vol'] * 1.5)).astype(int)
    high_vol_dates = df[df['is_high_vol_up'] == 1].index
    recent_high_vol = [idx for idx in high_vol_dates if idx >= len(df) - 15]
    
    high_vol_mode = "无"
    if recent_high_vol:
        last_hv = recent_high_vol[-1]
        # 检查高阳后3日内的行为
        if last_hv + 3 < len(df):
            hv_close = df.loc[last_hv, 'close']
            d1_ret = (df.loc[last_hv+1, 'close'] - hv_close) / hv_close * 100 if hv_close else 0
            d2_ret = (df.loc[last_hv+2, 'close'] - hv_close) / hv_close * 100 if hv_close else 0
            d3_ret = (df.loc[last_hv+3, 'close'] - hv_close) / hv_close * 100 if hv_close else 0
            
            # 模式1: 快速推升（后续继续涨）
            if d1_ret > 0 and d2_ret > 0:
                b_score += 4
                high_vol_mode = "快速推升"
            # 模式2: 小K线浮盈（后续小K线不跌）
            elif d1_ret >= -1 and d2_ret >= -1 and d3_ret >= -1:
                b_score += 3
                high_vol_mode = "小K线浮盈"
            # 模式3: 价缓量急缩（量缩价稳）
            elif df.loc[last_hv+1, 'volume'] < df['ma20_vol'].loc[last_hv] * 0.8:
                b_score += 2
                high_vol_mode = "价缓量缩"
            # 模式4: 迅速跌落（风险警示，减分）
            elif d1_ret < -3 and df.loc[last_hv+1, 'volume'] > df['ma20_vol'].loc[last_hv]:
                b_score -= 2
                high_vol_mode = "迅速跌落⚠"
    
    result["details"]["high_vol_mode"] = high_vol_mode

    # ★ 孤狼检测: 近5日涨幅 > 大盘同期涨幅 + 5%
    if not index_df.empty and len(df) >= 6:
        try:
            stock_5d = (df['close'].iloc[-1] - df['close'].iloc[-6]) / df['close'].iloc[-6] * 100
            # 对齐大盘数据
            index_close_end = index_df['close'].iloc[-1] if len(index_df) > 0 else 0
            idx_slice = index_df[index_df['date'] <= df['date'].iloc[-1]]
            if not idx_slice.empty and len(idx_slice) >= 6:
                idx_5d = (idx_slice['close'].iloc[-1] - idx_slice['close'].iloc[-6]) / idx_slice['close'].iloc[-6] * 100
                lead = stock_5d - idx_5d
                result["details"]["lead_over_index"] = round(lead, 2)
                if lead > 10:
                    b_score += 5  # 孤狼特征: 显著跑赢大盘
                elif lead > 5:
                    b_score += 3
                elif lead > 2:
                    b_score += 1
        except:
            pass

    result["breakout_score"] = min(18, max(0, b_score))

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
    #  ⑦ RSVA相对强度评分 (0-5分) ★★ 新增
    # ============================================================
    if not index_df.empty:
        rsva = calc_rsva(df, index_df, 20)
        result["details"]["rsva"] = round(rsva, 1)
        if rsva >= 85: rsva_score = 5
        elif rsva >= 75: rsva_score = 4
        elif rsva >= 65: rsva_score = 3
        elif rsva >= 55: rsva_score = 2
        elif rsva >= 45: rsva_score = 1
        else: rsva_score = 0
    else:
        rsva_score = 0
    result["rsva_score"] = rsva_score

    # ============================================================
    #  ⑧ 基本面连续增速评分 (0-5分) ★★ 新增（回测胜率66.3%）
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
            # 连续两季高增速条件
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
    #  汇总Setup总分
    # ============================================================
    # 断层评分上限调整为12分（为基本面增速让出空间）
    gap_score_adj = min(12, result.get("gap_score", 0))
    result["setup_total"] = sum([
        result["vcp_score"], result["ma_score"], result["volume_score"],
        result["tsi_score"], result["breakout_score"],
        gap_score_adj,
        result["rsva_score"],
        result["fundamental_score"]
    ])
    result["gap_score_display"] = result["gap_score"]  # 保留原始值用于展示
    result["gap_score"] = gap_score_adj  # 使用调整后的值

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
    candidates = get_candidate_stocks(0)
    print(f"  获取到 {len(candidates)} 只候选股")
    if not candidates:
        print("\n❌ 无候选股，终止扫描")
        return

    # ---- Step 3: OVS评分 ----
    print("\n🔍 Step 3: OVS综合评分")
    print("-" * 40)
    ovs_results = [ovs_score_stock(c["code"], c["name"]) for c in candidates]
    ovs_results.sort(key=lambda x: x["ovs_total"], reverse=True)
    setup_candidates = [r for r in ovs_results if r["ovs_total"] >= 40][:15]
    if not setup_candidates:
        setup_candidates = ovs_results[:10]
    print(f"  OVS≥40分候选: {len(setup_candidates)} 只 → 进入Setup评分")

    # ---- Step 3.5: Setup量化评分 v2.2 ★ ----
    print("\n⭐ Step 3.5: Setup量化评分 v2.2 ★  (高阳模式+基本面增速)")
    print("=" * 80)
    print(f"  {'代码':<11} {'名称':<7} {'Setup':>5}  "
          f"{'VCP':>3} {'均线':>3} {'量能':>3} {'TSI':>3} {'突破':>3} {'断层':>3} {'RSVA':>3} {'基本':>3} 高阳模式")
    print("  " + "-" * 72)

    setup_results = []
    for i, c in enumerate(setup_candidates):
        print(f"  ⏳ 计算中 ({i+1}/{len(setup_candidates)})...", end="\r")
        setup = setup_score_stock(c["code"], c["name"], index_df)
        setup_results.append(setup)

        gap_tag = "⍟" if setup.get("gap_score_display", 0) >= 8 else ""
        hv_mode = setup["details"].get("high_vol_mode", "")
        # 高阳模式颜色标记
        hv_tag = ""
        if "快速推升" in hv_mode: hv_tag = "🚀"
        elif "小K线" in hv_mode: hv_tag = "✅"
        elif "迅速跌落" in hv_mode: hv_tag = "⚠️"

        print(f"  {c['code']:<11} {c['name']:<7} "
              f"{setup['setup_total']:>3}/{100:<2} "
              f"{setup['vcp_score']:>2}/{20:<2} "
              f"{setup['ma_score']:>2}/{20:<2} "
              f"{setup['volume_score']:>2}/{15:<2} "
              f"{setup['tsi_score']:>1}/{10:<2} "
              f"{setup['breakout_score']:>2}/{18:<2} "
              f"{setup['gap_score']:>1}/{12:<2}{gap_tag}"
              f"{setup['rsva_score']:>1}/{5:<2} "
              f"{setup['fundamental_score']:>1}/{5:<2} {hv_tag}{hv_mode}")
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
    # 条件: Setup≥40 + 突破评分≥10 + RSVA≥75 → 强势突破
    leaders = [s for s in setup_results
               if s["setup_total"] >= 40 and s["breakout_score"] >= 8
               and s["details"].get("rsva", 0) >= 65]

    print(f"\n{'=' * 72}")
    print("🟢 二、领先股 — 强势突破信号 (Setup≥40 + 突破强 + RSVA高)")
    print("=" * 72)
    if leaders:
        print(f"  {'代码':<11} {'名称':<7} {'Setup':>4} {'突破':>4} {'RSVA':>5} {'孤狼':>6} {'近高点':>6}  {'评级'}")
        print("  " + "-" * 60)
        for s in leaders:
            d = s["details"]
            lead_tag = f"+{d.get('lead_over_index',0):.0f}%" if d.get('lead_over_index',0) else ""
            level = "⭐⭐" if s["setup_total"] >= 55 else "⭐"
            gap_mark = " [断层]" if s["gap_score"] >= 8 else ""
            print(f"  {s['code']:<11} {s['name']:<7} "
                  f"{s['setup_total']:>3}/{100:<2} "
                  f"{s['breakout_score']:>2}/{15:<2} "
                  f"{d.get('rsva',0):>4.0f}  "
                  f"{lead_tag:>6} "
                  f"{d.get('dist_from_high_pct',0):>4.1f}% "
                  f"{level}{gap_mark}")
    else:
        print(f"  ⚠️ 当前无符合条件的领先股")
        print(f"  说明: 大盘危险区(安全评分23.6)，强势突破信号难以形成")

    # ====== 三、回调股（基底回撤末期） ======
    # 条件: VCP收缩明显 + 缩量 + 距高点有一定距离 → 基底回撤
    pullbacks = [s for s in setup_results
                 if (s["vcp_score"] >= 8 or
                     (s["details"].get("vol_ratio_5_20", 1) < 0.75
                      and s["details"].get("dist_from_high_pct", 0) > 5))
                 and s["setup_total"] >= 15]

    print(f"\n{'=' * 72}")
    print("🔵 三、回调股 — 基底回撤末期 (VCP收缩/缩量回踩)")
    print("=" * 72)
    if pullbacks:
        # 按VCP评分排序（VCP越高=收缩越明显=回调越充分）
        pullbacks.sort(key=lambda x: x["vcp_score"], reverse=True)
        print(f"  {'代码':<11} {'名称':<7} {'VCP':>4} {'距高点':>6} {'量比':>6} {'Setup':>4}  备注")
        print("  " + "-" * 60)
        for s in pullbacks:
            d = s["details"]
            vcp_note = ""
            if d.get("vcp_ratio", 1) < 0.6:
                vcp_note = "极致收缩"
            elif d.get("vcp_ratio", 1) < 0.8:
                vcp_note = "明显收缩"
            else:
                vcp_note = "量缩回踩"
            print(f"  {s['code']:<11} {s['name']:<7} "
                  f"{s['vcp_score']:>2}/{20:<2} "
                  f"{d.get('dist_from_high_pct',0):>5.1f}% "
                  f"{d.get('vol_ratio_5_20',1):>4.2f}  "
                  f"{s['setup_total']:>3}  {vcp_note}")
    else:
        print(f"  ⚠️ 当前无符合条件的回调股")
        print(f"  说明: 大盘处于上涨波段，多数股票振幅在扩大而非收缩")

    # ====== 四、综合评分表 ======
    print(f"\n{'=' * 72}")
    print("📋 四、候选股综合评分表")
    print("=" * 72)
    print(f"  {'排名':>3} {'代码':<11} {'名称':<7} "
          f"{'Setup':>4} {'VCP':>3} {'均线':>3} {'量能':>3} {'TSI':>3} {'突破':>3} {'断层':>3} {'RSVA':>4} {'总计':>4}")
    print("  " + "-" * 70)

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

        gap_mark = "⍟" if s["gap_score"] >= 8 else ""
        print(f"  {i:>2}  {s['code']:<11} {s['name']:<7} "
              f"{s['setup_total']:>3}/{100:<2} "
              f"{s['vcp_score']:>2}/{20:<2} "
              f"{s['ma_score']:>2}/{20:<2} "
              f"{s['volume_score']:>2}/{15:<2} "
              f"{s['tsi_score']:>1}/{10:<2} "
              f"{s['breakout_score']:>2}/{15:<2} "
              f"{s['gap_score']:>1}/{15:<2}{gap_mark}"
              f"{d.get('rsva',0):>4.0f}  "
              f"{total:>4} {cat}")

    # ---- Step 5: 操作建议 ----
    print(f"\n{'=' * 72}")
    print("💡 Step 5: 操作建议")
    print("=" * 72)

    gap_sigs = [s for s in setup_results if s["gap_score"] >= 8]

    if leaders:
        print(f"\n  🟢 【领先股关注】突破信号清晰, 可跟踪枢轴点确认")
        for s in leaders:
            d = s["details"]
            gap_info = f" [断层{s['gap_score']}分]" if s["gap_score"] >= 8 else ""
            print(f"     {s['name']}({s['code']}) Setup={s['setup_total']}分 "
                  f"距高点{d.get('dist_from_high_pct',0):.1f}%{gap_info}")

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
    print(f"\n{'=' * 72}")
    print("📋 综合总结")
    print("-" * 72)
    print(f"  大盘状态: {safety['level']} ({safety['score']:.0f}/100) 情绪: {safety['emotion_detail']}")
    print(f"  热门板块TOP3: {', '.join([s['name'] for s in sectors[:3]])}")
    print(f"  领先板块: {len(sectors)}个 | 领先股: {len(leaders)}只 | 回调股: {len(pullbacks)}只")
    print(f"  净利润断层信号: {len(gap_sigs)}只")
    print(f"\n  📌 三类信号解读:")
    print(f"     🟢 领先股 = 强势突破+高RSVA+孤狼特征 → 关注追涨/回调低吸")
    print(f"     🔵 回调股 = VCP收缩+缩量回踩 → 等待放量突破确认")
    print(f"     📊 断层股 = 净利润跳空+高增速 → 基本面驱动型Setup")
    print("=" * 72)


if __name__ == "__main__":
    main()