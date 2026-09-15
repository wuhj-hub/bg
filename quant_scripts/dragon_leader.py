#!/usr/bin/env python3
"""
龙头战法 - Dragon Leader Strategy Analysis System

五维评分体系：
  一、市场情绪与周期（30%）：情绪阶段(10) + 主线题材(10) + 周期龙头共振(10)
  二、龙头地位与辨识度（25%）：空间地位(10) + 身位领涨性(8) + 人气辨识度(7)
  三、技术形态与量价（20%）：均线系统(5) + 量价关系(8) + 关键形态(7)
  四、筹码与资金结构（15%）：筹码获利(5) + 资金流向(5) + 连板惯性(5)
  五、基本面与估值（10%）：业绩成长(5) + 流通市值(3) + 题材实质(2)
  总分 = 100分

Usage:
    python -X utf8 dragon_leader.py --date 20260504 --top 10 --html
    python -X utf8 dragon_leader.py                    # 默认当天、前5名
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import akshare as ak          # 仅作东财回退源用
except ImportError:               # 2026-09-15：缺失时降级为纯 westock 源（主源不受影响）
    ak = None
import pandas as pd
import numpy as np


# ============================================================
# 工具函数
# ============================================================

def _is_mainboard(code) -> bool:
    """bg 统一口径：仅沪深主板（60x/000/001/002/003），排除科创688/创业300·301/北交所"""
    c = str(code).strip().zfill(6)
    return c.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))


def _is_st(name) -> bool:
    n = str(name).upper().replace(" ", "")
    return ("ST" in n) or ("退" in n)


def _now_bj() -> str:
    """北京时间 YYYYMMDD（沙箱时钟可能偏差，统一按东八区）"""
    from datetime import timezone
    return (datetime.now(timezone(timedelta(hours=8)))).strftime("%Y%m%d")


def get_latest_trading_date() -> str:
    """获取最近一个交易日（跳过周末）"""
    d = datetime.now()
    # 如果当前时间在15:00前，且是工作日，使用昨天
    if d.weekday() < 5 and d.hour < 15:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime('%Y%m%d')


def safe_get(df, col, idx=0, default=0):
    """安全取值"""
    try:
        if df is None:
            return default
        if isinstance(df, pd.Series):
            val = df.get(col, default)
        else:
            if df.empty:
                return default
            val = df.iloc[idx][col]
        if pd.isna(val):
            return default
        return float(val)
    except (KeyError, IndexError, ValueError, TypeError):
        return default


def safe_str(df, col, idx=0, default=''):
    """安全取字符串"""
    try:
        if df is None:
            return default
        if isinstance(df, pd.Series):
            val = str(df.get(col, default))
        else:
            if df.empty:
                return default
            val = str(df.iloc[idx][col])
        if val == 'nan':
            return default
        return val.strip()
    except (KeyError, IndexError, ValueError, TypeError):
        return default


# ============================================================
# westock 数据源适配层（2026-09-15 方案A）
#   背景：本环境东财 push2*/push2his* 域名不可达（连接重置），
#   导致「板块排名/个股信息/资金流」三个接口失效 → 对应维度只能拿兜底分。
#   westock（腾讯）在本环境可达，故作为主源；akshare/东财 保留为回退。
#   注：本适配层仅替换 DataFetcher 的取数实现，评分逻辑（DragonLeaderScorer）一行未改。
# ============================================================
WESTOCK_CMD = ["npx", "-y", "westock-data-skillhub@1.0.3"]


def _westock(args, timeout=90):
    """调用 westock CLI，返回 markdown 文本；失败返回 ''"""
    import subprocess, time
    for _ in range(2):
        try:
            r = subprocess.run(WESTOCK_CMD + args, capture_output=True, text=True, timeout=timeout)
            out = r.stdout or ""
            if out.strip() and "执行失败" not in out:
                return out
        except Exception:
            pass
        time.sleep(1.0)
    return ""


def _md_tables(txt):
    """把 westock 的 markdown 文本解析为 [{表头:值}, ...]（按空行分块）"""
    import re
    tables = []
    for block in re.split(r"\n\s*\n", (txt or "").strip()):
        lines = [l for l in block.splitlines() if l.strip().startswith("|")]
        if len(lines) < 2:
            continue
        hdr = [c.strip() for c in lines[0].strip("|").split("|")]
        rows = []
        for l in lines[1:]:
            cells = [c.strip() for c in l.strip("|").split("|")]
            if not cells or set("".join(cells)) <= set("-: "):
                continue
            if len(cells) == len(hdr):
                rows.append(dict(zip(hdr, cells)))
        if rows:
            tables.append(rows)
    return tables


def _f(x, default=None):
    try:
        v = float(str(x).replace(",", ""))
        return v
    except (ValueError, TypeError):
        return default


# ============================================================
# 数据获取层
# ============================================================

class DataFetcher:
    """统一数据获取接口"""

    def __init__(self, target_date: str):
        self.target_date = target_date
        self._cache = {}

    def get_zt_pool(self) -> pd.DataFrame:
        """涨停池"""
        if 'zt_pool' not in self._cache:
            try:
                if ak is None:
                    raise RuntimeError("akshare 未安装：涨停池不可用（请 pip install akshare）")
                df = ak.stock_zt_pool_em(date=self.target_date)
                self._cache['zt_pool'] = df
            except Exception as e:
                print(f"[警告] 涨停池获取失败: {e}")
                self._cache['zt_pool'] = pd.DataFrame()
        return self._cache['zt_pool']

    def get_dt_pool(self) -> pd.DataFrame:
        """跌停池"""
        if 'dt_pool' not in self._cache:
            try:
                df = ak.stock_zt_pool_dtgc_em(date=self.target_date)
                self._cache['dt_pool'] = df
            except Exception as e:
                print(f"[警告] 跌停池获取失败: {e}")
                self._cache['dt_pool'] = pd.DataFrame()
        return self._cache['dt_pool']

    def get_lhb_detail(self) -> pd.DataFrame:
        """龙虎榜明细"""
        if 'lhb' not in self._cache:
            try:
                df = ak.stock_lhb_detail_em(start_date=self.target_date, end_date=self.target_date)
                self._cache['lhb'] = df
            except Exception as e:
                print(f"[警告] 龙虎榜获取失败: {e}")
                self._cache['lhb'] = pd.DataFrame()
        return self._cache['lhb']

    def get_lhb_stock(self, code: str) -> pd.DataFrame:
        """获取个股龙虎榜席位"""
        if f'lhb_{code}' not in self._cache:
            try:
                df = ak.stock_lhb_detail_em(start_date=self.target_date, end_date=self.target_date)
                df = df[df['代码'] == code]
                self._cache[f'lhb_{code}'] = df
            except Exception:
                self._cache[f'lhb_{code}'] = pd.DataFrame()
        return self._cache[f'lhb_{code}']

    def get_stock_hist(self, code: str, days: int = 120) -> pd.DataFrame:
        """个股日K线（主源: westock kline；回退: 东财→新浪）
        注：新浪源在本环境易被限流（实测 8 并发即封 IP），故以 westock 为主源。"""
        key = f'hist_{code}'
        if key not in self._cache:
            _df = pd.DataFrame()
            try:
                pre = 'sh' if code.startswith('6') else 'sz'
                tabs = _md_tables(_westock(["kline", pre + code, "--period", "day",
                                            "--limit", str(days), "--fq", "qfq"], timeout=120))
                if tabs:
                    recs = []
                    for r in tabs[0]:
                        d = r.get("date")
                        cl = _f(r.get("last"))
                        if not d or cl is None:
                            continue
                        recs.append({"日期": d, "开盘": _f(r.get("open")), "收盘": cl,
                                     "最高": _f(r.get("high")), "最低": _f(r.get("low")),
                                     "成交量": _f(r.get("volume"))})
                    recs.reverse()                      # westock 批量输出为降序 → 转升序
                    if len(recs) >= 10:
                        _df = pd.DataFrame(recs)
            except Exception:
                _df = pd.DataFrame()
            if not _df.empty:
                self._cache[key] = _df
                return self._cache[key]
            end_date = datetime.strptime(self.target_date, '%Y%m%d').strftime('%Y%m%d')
            start_date = (datetime.strptime(self.target_date, '%Y%m%d') - timedelta(days=days)).strftime('%Y%m%d')
            df = pd.DataFrame()
            try:
                df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                        start_date=start_date, end_date=end_date, adjust="qfq")
            except Exception:
                df = pd.DataFrame()
            if df is None or df.empty:
                try:
                    symbol = ('sh' if code.startswith('6') else 'sz') + code
                    sdf = ak.stock_zh_a_daily(symbol=symbol, start_date=start_date,
                                              end_date=end_date, adjust='qfq')
                    df = sdf.rename(columns={'date': '日期', 'open': '开盘', 'close': '收盘',
                                             'high': '最高', 'low': '最低', 'volume': '成交量',
                                             'amount': '成交额'})
                    df = df.reset_index(drop=True)
                except Exception as e:
                    print(f"[警告] {code} K线获取失败: {e}")
                    df = pd.DataFrame()
            self._cache[f'hist_{code}'] = df
        return self._cache[f'hist_{code}']

    def get_fund_flow(self, code: str) -> pd.DataFrame:
        """个股资金流向（主源: westock asfund；回退: 东财）
        统一输出列 '主力净流入-净额'（单位: 元），与原东财口径一致。"""
        key = f'flow_{code}'
        if key not in self._cache:
            df = pd.DataFrame()
            try:
                pre = 'sh' if code.startswith('6') else 'sz'
                tabs = _md_tables(_westock(["asfund", pre + code]))
                if tabs:
                    v = _f(tabs[0][0].get("MainNetFlow"))
                    if v is not None:
                        df = pd.DataFrame([{"主力净流入-净额": v}])
            except Exception:
                df = pd.DataFrame()
            if df.empty:                                     # 东财回退
                try:
                    df = ak.stock_individual_fund_flow(
                        stock=code, market="sz" if code.startswith(('0', '3')) else "sh")
                except Exception:
                    df = pd.DataFrame()
            self._cache[key] = df
        return self._cache[key]

    def get_sector_rank(self) -> pd.DataFrame:
        """板块涨跌排名（主源: westock board 行业板块；回退: 东财）"""
        if 'sector' not in self._cache:
            df = pd.DataFrame()
            try:
                tabs = _md_tables(_westock(["board"]))
                if tabs:
                    recs = []
                    for r in tabs[0]:                       # 第一块=行业板块
                        nm, ch = r.get("name"), _f(r.get("changePct"))
                        if nm and ch is not None:
                            recs.append({"板块名称": nm, "涨跌幅": ch})
                    if recs:
                        df = pd.DataFrame(recs)
            except Exception:
                df = pd.DataFrame()
            if df.empty:                                     # 东财回退
                try:
                    df = ak.stock_board_industry_name_em()
                except Exception:
                    df = pd.DataFrame()
            self._cache['sector'] = df
        return self._cache['sector']

    def get_stock_info(self, code: str) -> dict:
        """个股基本信息（主源: westock finance 取每股收益；回退: 东财补市值/PE/ROE）"""
        key = f'info_{code}'
        if key not in self._cache:
            info = {}
            try:
                pre = 'sh' if code.startswith('6') else 'sz'
                tabs = _md_tables(_westock(["finance", pre + code]))
                if tabs:
                    eps = tabs[0][0].get("BasicEPS")
                    if eps not in (None, "", "nan"):
                        info["每股收益"] = eps
            except Exception:
                pass
            try:                                             # 东财回退（可达时补充更多字段）
                df = ak.stock_individual_info_em(symbol=code)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        info.setdefault(str(row.iloc[0]), row.iloc[1])
            except Exception:
                pass
            self._cache[key] = info
        return self._cache[key]

    def get_market_overview(self) -> dict:
        """市场概览（涨跌家数、涨停跌停数等）"""
        overview = {
            'zt_count': len(self.get_zt_pool()),
            'dt_count': len(self.get_dt_pool()),
            'lhb_count': len(self.get_lhb_detail()),
        }
        return overview


# ============================================================
# 评分引擎
# ============================================================

class DragonLeaderScorer:
    """龙头战法五维评分引擎"""

    # 一线游资席位关键词
    HOT_MONEY_KEYWORDS = [
        '中信证券', '东方财富', '华鑫证券', '国泰君安', '财通证券',
        '华泰证券', '招商证券', '国信证券', '中国银河', '光大证券',
        '中泰证券', '申万宏源', '广发证券', '天风证券', '浙商证券',
        '东方证券', '兴业证券', '方正证券', '长江证券', '平安证券',
    ]

    def __init__(self, fetcher: DataFetcher):
        self.fetcher = fetcher
        self.market_overview = fetcher.get_market_overview()
        self._emotion_score = None

    def _calc_emotion_phase(self) -> dict:
        """
        市场情绪阶段判断
        返回: {'phase': str, 'score': int, 'desc': str}
        """
        zt_count = self.market_overview['zt_count']
        dt_count = self.market_overview['dt_count']

        if zt_count >= 50 and dt_count <= 10:
            return {'phase': '主升期', 'score': 8, 'desc': f'涨停{zt_count}家，跌停{dt_count}家，市场强势'}
        elif zt_count >= 30 and dt_count <= 20:
            return {'phase': '启动期', 'score': 10, 'desc': f'涨停{zt_count}家，跌停{dt_count}家，情绪启动'}
        elif zt_count >= 15 and dt_count >= zt_count * 0.5:
            return {'phase': '冰点转暖', 'score': 10, 'desc': f'涨停{zt_count}家，跌停{dt_count}家，冰点转暖'}
        elif zt_count < 10:
            return {'phase': '衰退期', 'score': 0, 'desc': f'涨停仅{zt_count}家，情绪衰退'}
        else:
            return {'phase': '高位震荡', 'score': 3, 'desc': f'涨停{zt_count}家，跌停{dt_count}家，高位震荡'}

    def _get_top_sectors(self) -> list:
        """获取当日最强板块"""
        try:
            df = self.fetcher.get_sector_rank()
            if not df.empty:
                # 按涨跌幅排序，取前5
                if '涨跌幅' in df.columns:
                    df_sorted = df.sort_values('涨跌幅', ascending=False)
                    return df_sorted.head(5)['板块名称'].tolist()
        except Exception:
            pass
        return []

    def _check_hot_money(self, lhb_df: pd.DataFrame) -> tuple:
        """检查龙虎榜中是否有游资席位"""
        has_hot = False
        hot_seats = []
        try:
            for _, row in lhb_df.iterrows():
                seat = str(row.get('营业部名称', ''))
                for kw in self.HOT_MONEY_KEYWORDS:
                    if kw in seat:
                        has_hot = True
                        hot_seats.append(seat)
                        break
        except Exception:
            pass
        return has_hot, hot_seats

    def _check_institution(self, lhb_df: pd.DataFrame) -> bool:
        """检查是否有机构席位"""
        try:
            for _, row in lhb_df.iterrows():
                seat = str(row.get('营业部名称', ''))
                if '机构' in seat:
                    return True
        except Exception:
            pass
        return False

    def _calc_ma_alignment(self, hist: pd.DataFrame) -> dict:
        """
        均线系统评分
        检查5/10/20/60日均线排列
        """
        score = 0
        desc = ''
        try:
            if hist.empty or len(hist) < 60:
                return {'score': 0, 'desc': '数据不足'}

            closes = hist['收盘'].values
            ma5 = np.mean(closes[-5:])
            ma10 = np.mean(closes[-10:])
            ma20 = np.mean(closes[-20:])
            ma60 = np.mean(closes[-60:])
            last_close = closes[-1]

            if ma5 > ma10 > ma20 > ma60:
                score = 5
                desc = '多头排列(5>10>20>60)'
            elif ma5 > ma10 > ma20:
                score = 4
                desc = '短中期多头，60日待突破'
            elif ma20 > ma60 and ma5 > ma10:
                score = 3
                desc = '均线粘合向上发散'
            elif ma5 < ma10 < ma20 < ma60:
                score = 0
                desc = '空头排列'
            else:
                score = 2
                desc = '均线交织，方向不明'

        except Exception as e:
            desc = f'计算异常: {e}'

        return {'score': score, 'desc': desc}

    def _calc_volume_price(self, hist: pd.DataFrame, code: str) -> dict:
        """
        量价关系评分
        缩量连板(8) > 回封分歧(7) > 放量突破(5) > 放量滞涨(0)
        """
        score = 0
        desc = ''
        try:
            if hist.empty or len(hist) < 3:
                return {'score': 0, 'desc': '数据不足'}

            volumes = hist['成交量'].values
            closes = hist['收盘'].values
            opens = hist['开盘'].values
            highs = hist['最高'].values
            lows = hist['最低'].values

            last_vol = volumes[-1]
            avg_vol = np.mean(volumes[-10:-1]) if len(volumes) > 10 else np.mean(volumes[:-1])
            vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1

            last_close = closes[-1]
            last_open = opens[-1]
            last_high = highs[-1]
            last_low = lows[-1]
            prev_close = closes[-2]

            pct = (last_close - prev_close) / prev_close * 100

            # 涨停判断
            is_zt = pct >= 9.8

            # 缩量涨停（T字板或缩量板）
            if is_zt and vol_ratio < 0.7:
                score = 8
                desc = f'缩量加速板，量比{vol_ratio:.1f}'
            # 爆量分歧后回封（上影线长但收盘涨停）
            elif is_zt and vol_ratio > 1.5:
                upper_shadow = (last_high - max(last_close, last_open)) / last_close * 100
                if upper_shadow > 2:
                    score = 7
                    desc = f'爆量分歧回封，量比{vol_ratio:.1f}，上影{upper_shadow:.1f}%'
                else:
                    score = 5
                    desc = f'放量涨停突破，量比{vol_ratio:.1f}'
            # 放量涨停
            elif is_zt and vol_ratio >= 0.7:
                score = 5
                desc = f'放量涨停，量比{vol_ratio:.1f}'
            # 大涨但未涨停
            elif pct > 5:
                if vol_ratio > 1.5:
                    score = 2
                    desc = f'放量滞涨{pct:.1f}%，量比{vol_ratio:.1f}'
                else:
                    score = 4
                    desc = f'温和放量上涨{pct:.1f}%'
            # 放量下跌
            elif pct < -2 and vol_ratio > 1.3:
                score = 0
                desc = f'放量下跌{pct:.1f}%'
            else:
                score = 2
                desc = f'涨跌幅{pct:.1f}%，量比{vol_ratio:.1f}'

        except Exception as e:
            desc = f'计算异常: {e}'

        return {'score': score, 'desc': desc}

    def _calc_key_pattern(self, hist: pd.DataFrame) -> dict:
        """
        关键形态识别
        仙人指路、一阳穿五线、双龙飞天、底部突破等
        """
        score = 0
        desc = ''
        try:
            if hist.empty or len(hist) < 10:
                return {'score': 0, 'desc': '数据不足'}

            closes = hist['收盘'].values
            highs = hist['最高'].values
            lows = hist['最低'].values
            opens = hist['开盘'].values
            volumes = hist['成交量'].values

            last_close = closes[-1]
            last_open = opens[-1]
            last_high = highs[-1]
            last_low = lows[-1]
            prev_close = closes[-2]

            ma5 = np.mean(closes[-5:])
            ma10 = np.mean(closes[-10:])
            ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else np.nan
            ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else np.nan
            ma120 = np.mean(closes[-120:]) if len(closes) >= 120 else np.nan

            # 仙人指路：长上影线+小实体+量能放大+站在均线上
            upper_shadow = last_high - max(last_close, last_open)
            body = abs(last_close - last_open)
            avg_vol = np.mean(volumes[-10:-1]) if len(volumes) > 10 else np.mean(volumes[:-1])
            if (upper_shadow > body * 2 and body < (last_close * 0.03)
                    and volumes[-1] > avg_vol * 1.3
                    and last_close > ma5 > ma10):
                score = 7
                desc = '仙人指路形态（长上影试盘+站上均线）'
                return {'score': score, 'desc': desc}

            # 一阳穿五线：一根大阳线穿越多条均线
            if (last_close > last_open and (last_close - last_open) / last_open > 0.05):
                crossed = 0
                if not np.isnan(ma5) and last_open < ma5 < last_close:
                    crossed += 1
                if not np.isnan(ma10) and last_open < ma10 < last_close:
                    crossed += 1
                if not np.isnan(ma20) and last_open < ma20 < last_close:
                    crossed += 1
                if not np.isnan(ma60) and last_open < ma60 < last_close:
                    crossed += 1
                if not np.isnan(ma120) and last_open < ma120 < last_close:
                    crossed += 1
                if crossed >= 3:
                    score = 7
                    desc = f'一阳穿{crossed}线（大阳穿越多条均线）'
                    return {'score': score, 'desc': desc}

            # 双龙飞天：连续两日大阳
            if (len(closes) >= 2 and
                    (closes[-1] - closes[-2]) / closes[-2] > 0.05 and
                    (closes[-2] - closes[-3]) / closes[-3] > 0.05):
                score = 7
                desc = '双龙飞天（连续两日大阳）'
                return {'score': score, 'desc': desc}

            # 底部放量突破年线或长期平台
            if not np.isnan(ma60) and not np.isnan(ma120):
                # 突破年线（250日均线附近用120日近似）
                if (closes[-2] < ma120 and last_close > ma120 and
                        volumes[-1] > avg_vol * 1.5):
                    score = 5
                    desc = '底部放量突破长期均线'
                    return {'score': score, 'desc': desc}

                # 底部平台突破
                recent_low = np.min(lows[-20:])
                if (last_close > recent_low * 1.15 and
                        closes[-5] < recent_low * 1.10 and
                        volumes[-1] > avg_vol * 1.5):
                    score = 5
                    desc = '底部平台放量突破'
                    return {'score': score, 'desc': desc}

            desc = '无显著经典形态'

        except Exception as e:
            desc = f'计算异常: {e}'

        return {'score': score, 'desc': desc}

    def _calc_chip_profit(self, hist: pd.DataFrame) -> dict:
        """
        筹码获利比例估算
        基于近期价格分布估算获利筹码占比
        """
        score = 0
        desc = ''
        try:
            if hist.empty or len(hist) < 20:
                return {'score': 0, 'desc': '数据不足'}

            closes = hist['收盘'].values
            current = closes[-1]

            # 近20日收盘价分布，估算获利比例
            profitable = np.sum(closes[-20:] < current)
            ratio = profitable / len(closes[-20:]) * 100

            if ratio >= 90:
                score = 5
                desc = f'获利盘{ratio:.0f}%（突破筹码峰）'
            elif ratio >= 70:
                score = 3
                desc = f'获利盘{ratio:.0f}%'
            else:
                score = 0
                desc = f'获利盘{ratio:.0f}%（套牢区）'

        except Exception as e:
            desc = f'计算异常: {e}'

        return {'score': score, 'desc': desc}

    def _calc_lianban_inertia(self, hist: pd.DataFrame, code: str) -> dict:
        """
        连板惯性评分
        前一日缩量/T字板(5) > 温和放量(3) > 爆量烂板(0)
        """
        score = 0
        desc = ''
        try:
            if hist.empty or len(hist) < 5:
                return {'score': 0, 'desc': '数据不足'}

            closes = hist['收盘'].values
            opens = hist['开盘'].values
            lows = hist['最低'].values
            volumes = hist['成交量'].values

            # 检查前一日
            prev_close = closes[-2]
            prev2_close = closes[-3]
            prev_pct = (prev_close - prev2_close) / prev2_close * 100
            prev_is_zt = prev_pct >= 9.8

            if not prev_is_zt:
                desc = '前一日非涨停'
                return {'score': 1, 'desc': desc}

            prev_vol = volumes[-2]
            avg_vol = np.mean(volumes[-10:-2]) if len(volumes) > 10 else np.mean(volumes[:-2])
            vol_ratio = prev_vol / avg_vol if avg_vol > 0 else 1

            prev_low = lows[-2]
            prev_open = opens[-2]

            # T字板：最低价接近开盘价，收盘涨停
            if prev_low <= prev_open * 1.005 and prev_close >= prev2_close * 1.098:
                score = 5
                desc = f'T字板/缩量板，量比{vol_ratio:.1f}'
            # 缩量板
            elif vol_ratio < 0.7:
                score = 5
                desc = f'缩量板，量比{vol_ratio:.1f}'
            # 温和放量
            elif vol_ratio <= 1.5:
                score = 3
                desc = f'温和放量板，量比{vol_ratio:.1f}'
            # 爆量烂板
            else:
                # 检查是否烂板（大幅震荡）
                prev_high = hist['最高'].values[-2]
                amplitude = (prev_high - prev_low) / prev_low * 100
                if amplitude > 10:
                    score = 0
                    desc = f'爆量烂板，振幅{amplitude:.1f}%'
                else:
                    score = 2
                    desc = f'放量板，量比{vol_ratio:.1f}'

        except Exception as e:
            desc = f'计算异常: {e}'

        return {'score': score, 'desc': desc}

    def score_stock(self, code: str, name: str, zt_row: pd.Series = None) -> dict:
        """
        对单只股票进行五维评分
        """
        result = {
            'code': code,
            'name': name,
            'scores': {},
            'total': 0,
            'level': '',
            'details': {},
        }

        # 获取必要数据
        hist = self.fetcher.get_stock_hist(code)
        lhb_df = self.fetcher.get_lhb_stock(code)
        fund_flow = self.fetcher.get_fund_flow(code)
        stock_info = self.fetcher.get_stock_info(code)
        zt_pool = self.fetcher.get_zt_pool()
        top_sectors = self._get_top_sectors()

        # --------------------------------------------------
        # 一、市场情绪与周期（30分）
        # --------------------------------------------------

        # 1. 情绪阶段判断（10分）
        emotion = self._calc_emotion_phase()
        result['details']['emotion_phase'] = emotion

        # 如果是衰退期，所有股票直接低分
        if emotion['phase'] == '衰退期':
            result['scores']['emotion_stage'] = 0
        else:
            result['scores']['emotion_stage'] = emotion['score']

        # 2. 主线题材聚焦（10分）
        sector = safe_str(zt_row, '所属行业') if zt_row is not None else ''
        if not sector:
            # 尝试从涨停池获取
            if not zt_pool.empty:
                match = zt_pool[zt_pool['代码'] == code]
                if not match.empty:
                    sector = safe_str(match, '所属行业')

        if sector and sector in top_sectors[:3]:
            result['scores']['sector_hot'] = 10
            result['details']['sector'] = f'{sector}（当日主线第{top_sectors.index(sector)+1}）'
        elif sector and sector in top_sectors:
            result['scores']['sector_hot'] = 5
            result['details']['sector'] = f'{sector}（支流题材）'
        elif sector:
            result['scores']['sector_hot'] = 3
            result['details']['sector'] = f'{sector}（非主流）'
        else:
            result['scores']['sector_hot'] = 2
            result['details']['sector'] = '板块信息缺失'

        # 3. 周期龙头共振（10分）
        # 找出当日最高板
        max_lianban = 0
        leader_code = ''
        if not zt_pool.empty and '连板数' in zt_pool.columns:
            for _, r in zt_pool.iterrows():
                lb = safe_get(r, '连板数', default=0)
                if lb > max_lianban:
                    max_lianban = lb
                    leader_code = str(r.get('代码', ''))

        current_lianban = 0
        if zt_row is not None:
            current_lianban = int(safe_get(zt_row, '连板数', default=1))
        elif not zt_pool.empty:
            match = zt_pool[zt_pool['代码'] == code]
            if not match.empty:
                current_lianban = int(safe_get(match, '连板数', default=1))

        if code == leader_code:
            result['scores']['leader_resonance'] = 10
            result['details']['lianban'] = f'市场最高板({max_lianban}板) - 空间龙头'
        elif current_lianban >= max_lianban - 1 and max_lianban >= 3:
            result['scores']['leader_resonance'] = 8
            result['details']['lianban'] = f'{current_lianban}板（与最高板{max_lianban}板共振）'
        elif current_lianban >= 2:
            result['scores']['leader_resonance'] = 5
            result['details']['lianban'] = f'{current_lianban}板'
        elif current_lianban == 1 and not hist.empty:
            # 首板先锋：检查是否在板块中率先涨停
            result['scores']['leader_resonance'] = 3
            result['details']['lianban'] = '首板，独立走势'
        else:
            result['scores']['leader_resonance'] = 0
            result['details']['lianban'] = f'{current_lianban}板'

        # --------------------------------------------------
        # 二、龙头地位与辨识度（25分）
        # --------------------------------------------------

        # 4. 空间地位（10分）
        if code == leader_code:
            result['scores']['space_position'] = 10
        elif current_lianban == max_lianban - 1 and max_lianban >= 3:
            result['scores']['space_position'] = 7
        elif current_lianban >= 3:
            result['scores']['space_position'] = 5
        elif current_lianban == 2:
            result['scores']['space_position'] = 3
        else:
            result['scores']['space_position'] = 1

        # 5. 身位与领涨性（8分）
        if not hist.empty and len(hist) >= 3:
            closes = hist['收盘'].values
            pct_3d = (closes[-1] - closes[-3]) / closes[-3] * 100
            if current_lianban >= 2:
                result['scores']['leadership'] = 8
                result['details']['leadership'] = '连板龙头，领涨性确认'
            elif pct_3d > 10:
                result['scores']['leadership'] = 6
                result['details']['leadership'] = f'3日涨幅{pct_3d:.1f}%，领涨先锋'
            elif pct_3d > 5:
                result['scores']['leadership'] = 4
                result['details']['leadership'] = f'3日涨幅{pct_3d:.1f}%，跟涨'
            else:
                result['scores']['leadership'] = 2
                result['details']['leadership'] = '跟风板'
        else:
            result['scores']['leadership'] = 2
            result['details']['leadership'] = '数据不足'

        # 6. 人气与辨识度（7分）
        has_hot_money, hot_seats = self._check_hot_money(lhb_df)
        has_institution = self._check_institution(lhb_df)

        # 历史连板记忆
        has_memory = False
        if not hist.empty and len(hist) >= 60:
            pct_changes = np.diff(hist['收盘'].values[-60:]) / hist['收盘'].values[-60:-1] * 100
            zt_days = np.sum(pct_changes >= 9.8)
            if zt_days >= 5:
                has_memory = True

        if has_hot_money and has_memory:
            result['scores']['popularity'] = 7
            result['details']['popularity'] = f'游资介入+连板记忆（活跃股）'
        elif has_hot_money:
            result['scores']['popularity'] = 5
            result['details']['popularity'] = f'游资席位现身'
        elif has_memory:
            result['scores']['popularity'] = 5
            result['details']['popularity'] = f'历史连板记忆（股性活跃）'
        elif has_institution:
            result['scores']['popularity'] = 4
            result['details']['popularity'] = f'机构关注'
        else:
            result['scores']['popularity'] = 2
            result['details']['popularity'] = '无明显人气信号'

        # --------------------------------------------------
        # 三、技术形态与量价（20分）
        # --------------------------------------------------

        # 7. 均线系统（5分）
        ma_result = self._calc_ma_alignment(hist)
        result['scores']['ma_system'] = ma_result['score']
        result['details']['ma'] = ma_result['desc']

        # 8. 量价关系（8分）
        vp_result = self._calc_volume_price(hist, code)
        result['scores']['volume_price'] = vp_result['score']
        result['details']['vol_price'] = vp_result['desc']

        # 9. 关键形态（7分）
        pattern_result = self._calc_key_pattern(hist)
        result['scores']['key_pattern'] = pattern_result['score']
        result['details']['pattern'] = pattern_result['desc']

        # --------------------------------------------------
        # 四、筹码与资金结构（15分）
        # --------------------------------------------------

        # 10. 筹码获利比例（5分）
        chip_result = self._calc_chip_profit(hist)
        result['scores']['chip_profit'] = chip_result['score']
        result['details']['chip'] = chip_result['desc']

        # 11. 资金流向（5分）
        flow_score = 2
        flow_desc = '无显著净流入'
        try:
            if not fund_flow.empty:
                # 尝试取最新数据
                for col in ['主力净流入-净额', '主力净流入净额', '主力净流入']:
                    if col in fund_flow.columns:
                        val = fund_flow[col].iloc[-1] if not fund_flow.empty else 0
                        if val > 0:
                            flow_score = 5
                            flow_desc = f'主力净流入{val/10000:.0f}万元'
                            break
                        elif val > -1000000:
                            flow_score = 3
                            flow_desc = f'资金平稳'
                        else:
                            flow_score = 0
                            flow_desc = f'主力净流出'
                        break
        except Exception:
            pass

        # 龙虎榜加分
        if has_hot_money:
            flow_score = max(flow_score, 4)
            flow_desc += '+游资买入'
        if has_institution:
            flow_score = min(flow_score + 1, 5)
            flow_desc += '+机构加持'

        result['scores']['fund_flow'] = flow_score
        result['details']['fund'] = flow_desc

        # 12. 连板惯性（5分）
        inertia_result = self._calc_lianban_inertia(hist, code)
        result['scores']['lianban_inertia'] = inertia_result['score']
        result['details']['inertia'] = inertia_result['desc']

        # --------------------------------------------------
        # 五、基本面与估值（10分）
        # --------------------------------------------------

        # 13. 业绩与成长（5分）
        perf_score = 2
        perf_desc = '业绩平稳'
        try:
            # 从stock_info获取
            if stock_info:
                eps = stock_info.get('每股收益', '0')
                pe = stock_info.get('市盈率-动态', '0')
                roe = stock_info.get('加权净资产收益率', '0')
                try:
                    eps_f = float(str(eps).replace(',', ''))
                    if eps_f > 0.5:
                        perf_score = 5
                        perf_desc = f'EPS={eps_f}元，业绩优良'
                    elif eps_f > 0:
                        perf_score = 3
                        perf_desc = f'EPS={eps_f}元，盈利'
                    else:
                        perf_score = 0
                        perf_desc = f'EPS={eps_f}元，亏损'
                except (ValueError, TypeError):
                    perf_desc = '业绩数据缺失'
        except Exception:
            pass
        result['scores']['performance'] = perf_score
        result['details']['performance'] = perf_desc

        # 14. 流通市值（3分）
        mv_score = 0
        mv_desc = ''
        try:
            mv = stock_info.get('流通市值', '0') if stock_info else '0'
            mv_str = str(mv)
            if (not mv_str or mv_str in ('0', 'nan', 'None')) and zt_row is not None:
                # 回退：用涨停池的流通市值（单位元）
                mv_val = float(zt_row.get('流通市值', 0)) / 1e8
            elif '亿' in mv_str:
                mv_val = float(mv_str.replace('亿', '').replace(',', ''))
            else:
                mv_val = float(mv_str) / 1e8 if mv_str else 0

            if 50 <= mv_val <= 200:
                mv_score = 3
                mv_desc = f'流通市值{mv_val:.0f}亿（最佳区间）'
            elif 30 <= mv_val < 50:
                mv_score = 1
                mv_desc = f'流通市值{mv_val:.0f}亿（偏小）'
            elif 200 < mv_val <= 300:
                mv_score = 2
                mv_desc = f'流通市值{mv_val:.0f}亿（偏大）'
            elif mv_val < 30:
                mv_score = 1
                mv_desc = f'流通市值{mv_val:.0f}亿（过小）'
            else:
                mv_score = 0
                mv_desc = f'流通市值{mv_val:.0f}亿（过大）'
        except Exception:
            mv_desc = '市值数据缺失'
        result['scores']['market_cap'] = mv_score
        result['details']['mv'] = mv_desc

        # 15. 题材实质（2分）
        # 基于板块和政策热词判断
        theme_score = 1
        theme_desc = '概念题材'
        policy_keywords = ['人工智能', '算力', '芯片', '半导体', '新能源', '储能',
                          '光伏', '风电', '锂电', '机器人', '自动驾驶', '数据要素',
                          '低空经济', '商业航天', '量子计算', '固态电池', '氢能']
        for kw in policy_keywords:
            if kw in sector or kw in name:
                theme_score = 2
                theme_desc = f'实质性题材（{kw}）'
                break
        result['scores']['theme_substance'] = theme_score
        result['details']['theme'] = theme_desc

        # --------------------------------------------------
        # 计算总分
        # --------------------------------------------------
        total = sum(result['scores'].values())
        result['total'] = total

        if total >= 80:
            result['level'] = '强关注'
            result['position_advice'] = '仓位可至8成'
        elif total >= 60:
            result['level'] = '一般关注'
            result['position_advice'] = '仓位不超过5成'
        else:
            result['level'] = '不建议操作'
            result['position_advice'] = '风险大于机会'

        return result


# ============================================================
# HTML报告生成
# ============================================================

def generate_html_report(results: list, target_date: str, emotion_phase: dict) -> str:
    """生成可视化HTML分析报告"""

    # 按总分排序
    results.sort(key=lambda x: x['total'], reverse=True)

    def score_bar(score, max_score, color_map=None):
        """生成评分条"""
        pct = score / max_score * 100
        if color_map is None:
            if pct >= 80:
                color = '#ff4444'
            elif pct >= 60:
                color = '#ff8800'
            elif pct >= 40:
                color = '#ffcc00'
            else:
                color = '#888'
        else:
            color = color_map.get(pct, '#888')
        return f'<div style="display:flex;align-items:center;gap:8px;">' \
               f'<div style="flex:1;height:20px;background:#333;border-radius:4px;overflow:hidden;">' \
               f'<div style="width:{pct}%;height:100%;background:{color};border-radius:4px;"></div>' \
               f'</div><span style="min-width:40px;text-align:right;font-size:14px;font-weight:bold;">{score}/{max_score}</span></div>'

    # 维度信息
    dimensions = [
        ('一、市场情绪与周期（30分）', ['emotion_stage', 'sector_hot', 'leader_resonance'],
         ['情绪阶段(10)', '主线题材(10)', '龙头共振(10)']),
        ('二、龙头地位与辨识度（25分）', ['space_position', 'leadership', 'popularity'],
         ['空间地位(10)', '身位领涨(8)', '人气辨识(7)']),
        ('三、技术形态与量价（20分）', ['ma_system', 'volume_price', 'key_pattern'],
         ['均线系统(5)', '量价关系(8)', '关键形态(7)']),
        ('四、筹码与资金结构（15分）', ['chip_profit', 'fund_flow', 'lianban_inertia'],
         ['筹码获利(5)', '资金流向(5)', '连板惯性(5)']),
        ('五、基本面与估值（10分）', ['performance', 'market_cap', 'theme_substance'],
         ['业绩成长(5)', '流通市值(3)', '题材实质(2)']),
    ]

    max_scores = [10, 10, 10, 10, 8, 7, 5, 8, 7, 5, 5, 5, 5, 3, 2]

    stock_cards = []
    for i, r in enumerate(results):
        level_color = '#ff4444' if r['total'] >= 80 else '#ff8800' if r['total'] >= 60 else '#888'
        level_bg = 'rgba(255,68,68,0.1)' if r['total'] >= 80 else 'rgba(255,136,0,0.1)' if r['total'] >= 60 else 'rgba(136,136,136,0.1)'

        dim_html = ''
        for dim_name, score_keys, score_names in dimensions:
            items_html = ''
            for key, name, ms in zip(score_keys, score_names, max_scores[len(items_html):]):
                sc = r['scores'].get(key, 0)
                items_html += f'<div style="margin-bottom:6px;"><span style="font-size:12px;color:#aaa;min-width:100px;display:inline-block;">{name}</span>{score_bar(sc, ms)}</div>'
                if len([k for k in score_keys if score_keys.index(k) <= score_keys.index(key)]) >= len(score_keys):
                    break
            dim_html += f'<div style="margin-bottom:16px;"><div style="font-size:13px;color:#ddd;margin-bottom:8px;font-weight:bold;">{dim_name}</div>{items_html}</div>'

        # 详情
        details_html = ''
        detail_items = [
            ('板块', r['details'].get('sector', '')),
            ('连板', r['details'].get('lianban', '')),
            ('领涨性', r['details'].get('leadership', '')),
            ('人气', r['details'].get('popularity', '')),
            ('均线', r['details'].get('ma', '')),
            ('量价', r['details'].get('vol_price', '')),
            ('形态', r['details'].get('pattern', '')),
            ('筹码', r['details'].get('chip', '')),
            ('资金', r['details'].get('fund', '')),
            ('惯性', r['details'].get('inertia', '')),
            ('业绩', r['details'].get('performance', '')),
            ('市值', r['details'].get('mv', '')),
            ('题材', r['details'].get('theme', '')),
        ]
        for label, val in detail_items:
            if val:
                details_html += f'<span style="display:inline-block;background:#2a2a3e;color:#aaa;font-size:11px;padding:2px 8px;border-radius:3px;margin:2px;">{label}: {val}</span>'

        card = f'''
        <div style="background:#1a1a2e;border:1px solid {level_color};border-radius:12px;padding:20px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div>
                    <span style="font-size:11px;color:#666;">#{i+1}</span>
                    <span style="font-size:18px;font-weight:bold;color:#fff;margin-left:8px;">{r['name']}</span>
                    <span style="font-size:13px;color:#888;margin-left:6px;">{r['code']}</span>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:28px;font-weight:bold;color:{level_color};">{r['total']}</div>
                    <div style="font-size:12px;color:#888;">/100分</div>
                </div>
            </div>
            <div style="display:inline-block;background:{level_bg};color:{level_color};font-size:13px;font-weight:bold;padding:4px 12px;border-radius:6px;margin-bottom:12px;">
                {r['level']} | {r['position_advice']}
            </div>
            {dim_html}
            <div style="margin-top:8px;">{details_html}</div>
        </div>
        '''
        stock_cards.append(card)

    emotion_desc = emotion_phase.get('desc', '')
    emotion_phase_name = emotion_phase.get('phase', '未知')

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>龙头战法分析报告 {target_date}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d0d1a; color:#e0e0e0; font-family:'Microsoft YaHei','PingFang SC',sans-serif; padding:20px; max-width:800px; margin:0 auto; }}
.header {{ text-align:center; padding:20px 0; border-bottom:2px solid #ff4444; margin-bottom:20px; }}
.header h1 {{ font-size:24px; color:#ff4444; }}
.header .date {{ font-size:14px; color:#888; margin-top:4px; }}
.emotion {{ background:linear-gradient(135deg,#1a1a3e,#2a1a3e); border-radius:10px; padding:16px; margin-bottom:20px; }}
.emotion h3 {{ color:#ff8800; margin-bottom:8px; }}
.section {{ margin-bottom:24px; }}
.warning {{ background:#2a1a1a; border:1px solid #ff4444; border-radius:8px; padding:12px; margin-bottom:16px; font-size:13px; color:#ff8888; }}
</style>
</head>
<body>
<div class="header">
    <h1>龙头战法 · 五维评分分析</h1>
    <div class="date">分析日期: {target_date}</div>
</div>

<div class="emotion">
    <h3>市场情绪: {emotion_phase_name}</h3>
    <p style="font-size:14px;color:#ccc;">{emotion_desc}</p>
    <p style="font-size:12px;color:#888;margin-top:4px;">涨停{emotion_phase.get('desc','').split('涨停')[1].split('家')[0] if '涨停' in emotion_desc else '-'}家 | 跌停{'-'}家</p>
</div>

<div class="warning">
    <strong>操作纪律：</strong>止损线3%-5%硬性执行 | 80分以上仓位8成 | 60-80分仓位不超过5成 | 模式纯粹，摒弃随意交易
</div>

<div class="section">
    <h2 style="font-size:18px;color:#fff;margin-bottom:16px;">评分排名</h2>
    {''.join(stock_cards)}
</div>

<div style="text-align:center;color:#555;font-size:11px;margin-top:30px;padding:16px;border-top:1px solid #222;">
    龙头战法分析系统 · 五维评分体系 · 仅供参考，不构成投资建议<br>
    数据来源: 东方财富 · AKShare
</div>
</body>
</html>'''
    return html


# ============================================================
# 主函数
# ============================================================

def run_dragon_leader_analysis(target_date: str = None, top_n: int = 10) -> list:
    """
    执行龙头战法分析
    """
    if target_date is None:
        target_date = get_latest_trading_date()

    print(f"[龙头战法] 分析日期: {target_date}")
    print(f"[龙头战法] 开始获取数据...\n")

    fetcher = DataFetcher(target_date)
    scorer = DragonLeaderScorer(fetcher)

    # 获取涨停池
    zt_pool = fetcher.get_zt_pool()
    if zt_pool.empty:
        print("[警告] 涨停池为空，可能非交易日或数据源问题")
        return []

    print(f"[龙头战法] 涨停股数量: {len(zt_pool)}")
    print(f"[龙头战法] 跌停股数量: {len(fetcher.get_dt_pool())}")
    print(f"[龙头战法] 龙虎榜数量: {len(fetcher.get_lhb_detail())}")

    emotion_phase = scorer._calc_emotion_phase()
    print(f"[龙头战法] 市场情绪: {emotion_phase['phase']} ({emotion_phase['desc']})")
    print()

    # 分析所有涨停股
    results = []
    total = len(zt_pool)

    for idx, (_, row) in enumerate(zt_pool.iterrows()):
        code = safe_str(row, '代码')
        name = safe_str(row, '名称')

        if not code:
            continue

        print(f"[分析] ({idx+1}/{total}) {name}({code})...", end=' ')

        try:
            result = scorer.score_stock(code, name, zt_row=row)
            results.append(result)
            print(f"{result['total']}分 [{result['level']}]")
        except Exception as e:
            print(f"失败: {e}")

    # 排序
    results.sort(key=lambda x: x['total'], reverse=True)

    print(f"\n{'='*60}")
    print(f"龙头战法分析完成！共分析 {len(results)} 只股票")
    print(f"{'='*60}")
    print(f"\n{'排名':<4}{'代码':<8}{'名称':<10}{'总分':<6}{'评级':<10}{'仓位建议'}")
    print(f"{'-'*60}")
    for i, r in enumerate(results[:top_n]):
        print(f"#{i+1:<3}{r['code']:<8}{r['name']:<10}{r['total']:<6}{r['level']:<10}{r['position_advice']}")

    return results


def main():
    parser = argparse.ArgumentParser(description='龙头战法 - 五维评分分析系统（bg 接入版）')
    parser.add_argument('--date', type=str, default=None, help='分析日期(YYYYMMDD)')
    parser.add_argument('--top', type=int, default=10, help='控制台输出前N名')
    parser.add_argument('--threshold', type=int, default=70, help='入池分数门槛（默认70）')
    parser.add_argument('--html', action='store_true', help='额外生成HTML报告')
    parser.add_argument('--output', type=str, default='outputs', help='报告/JSON 输出目录')
    parser.add_argument('--pool-out', type=str, default=None, help='股池文件路径（默认 quant_scripts/dragon_pool.txt）')
    args = parser.parse_args()

    target_date = args.date or get_latest_trading_date()
    if args.date is None:
        target_date = _now_bj()          # bg：默认按北京日期
    results = run_dragon_leader_analysis(target_date=target_date, top_n=args.top)
    if not results:
        print("\n[结果] 无分析结果")
        return

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    pool_path = args.pool_out or "quant_scripts/dragon_pool.txt"

    # ── 入池：仅沪深主板 + 非ST + 分数≥门槛 ──
    picked = [r for r in results
              if r['total'] >= args.threshold and _is_mainboard(r['code']) and not _is_st(r['name'])]

    # 股池文件（格式对齐 longtou_pool.txt）
    try:
        Path(pool_path).parent.mkdir(parents=True, exist_ok=True)
        with open(pool_path, "w", encoding="utf-8") as f:
            f.write(f"# 龙头战法池 {target_date}（阈值≥{args.threshold}｜仅主板·非ST）\n")
            for r in picked:
                f.write(f"{('sh' if r['code'].startswith('6') else 'sz')}{r['code']} # {r['name']}（{r['total']}分/{r['level']}）\n")
        print(f"[OK] 股池: {pool_path}（{len(picked)} 只）")
    except OSError as e:
        print(f"[WARN] 股池写出失败: {e}")

    # 报告（Markdown）
    md = [f"# 🐲 龙头战法池 · {target_date}\n",
          f"> 扫描涨停池 {len(results)} 只 ｜ 入池 **{len(picked)}** 只（≥{args.threshold}分·仅主板·非ST）\n",
          "| 排名 | 代码 | 名称 | 总分 | 评级 | 仓位建议 |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(picked, 1):
        md.append(f"| #{i} | {r['code']} | {r['name']} | **{r['total']}** | {r['level']} | {r['position_advice']} |")
    if not picked:
        md.append("\n📭 今日无标的达到入池门槛。")
    md_path = out_dir / f"龙头战法池_{target_date}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"[OK] 报告: {md_path}")

    # 全量 JSON（供下游/复盘引用）
    json_path = out_dir / f"dragon_leader_{target_date}.json"
    json_path.write_text(json.dumps(
        {"date": target_date, "threshold": args.threshold, "scanned": len(results),
         "picked": [r['code'] for r in picked], "results": results}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"[OK] JSON: {json_path}")

    if args.html:
        try:
            fetcher = DataFetcher(target_date)
            html = generate_html_report(results, target_date, DragonLeaderScorer(fetcher)._calc_emotion_phase())
            (out_dir / f"龙头战法报告_{target_date}.html").write_text(html, encoding="utf-8")
            print(f"[OK] HTML: {out_dir}/龙头战法报告_{target_date}.html")
        except Exception as e:
            print(f"[WARN] HTML 生成失败: {e}")

    print("\n" + "=" * 60)
    print(f"龙头战法 · 入池 {len(picked)} 只（阈值 {args.threshold}）")
    print("=" * 60)
    for i, r in enumerate(picked[:15], 1):
        print(f"  #{i:<2} {r['code']} {r['name']:<8} {r['total']:>3}分  {r['level']}")


if __name__ == '__main__':
    main()
