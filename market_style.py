#!/usr/bin/env python3
"""市场风格轴（market_style）——指数市（机构主导）vs 情绪市（游资主导）三态判定

设计来源：《判断板块是"机构主导"还是"游资主导"》五大标准 → 映射为可量化指标：
  ① 龙头股东结构/市值      → 涨停中军结构（涨停股中沪深300大市值成分 = 中军）
  ② 板块指数走势与量能     → 大小盘相对强弱（沪深300 vs 中证1000，5/10/20日）+ 小盘脉冲 + 成交结构
  ③ 资金流向结构           → 涨幅TOP板块 asfund 主力/散户净流入定性（增强项）
  ④ 涨停股结构与梯队       → 涨停家数/涨停占比/强势占比/中军涨停（连板高度无数据源，以结构代理）
  ⑤ 消息面逻辑深度         → 不可量化，输出为人工研判项

打分 -100 ~ +100（正=情绪市/游资主导，负=指数市/机构主导）：
  A 大小盘相对强弱  ±40 | B 涨停结构与宽度 ±35 | C 成交结构 ±15 | D 板块资金定性 ±10
判定：≥+25 情绪市 | ≤-25 指数市 | 中间 均衡市

用法: python3 market_style.py [--width outputs/market_width_latest.json] [--hs300 quant_scripts/hs300.csv]
输出: outputs/market_style_{date}.md + market_style_latest.json（供盘前/复盘引用）
"""
import csv, json, os, re, subprocess, sys, time
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
OUT_DIR = "outputs"

# 大小盘指数：机构基准(大盘) vs 游资基准(小盘)
BIG_IDX = {"sh000016": "上证50", "sh000300": "沪深300"}   # 机构地盘
MID_IDX = {"sh000905": "中证500"}                          # 中间带
SMALL_IDX = {"sh000852": "中证1000"}                       # 游资场子
ALL_IDX = {**BIG_IDX, **MID_IDX, **SMALL_IDX, "sh000985": "中证全指", "sh000001": "上证指数"}


def run(args, timeout=120):
    for i in range(3):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""


def parse_kline(txt):
    """解析批量kline输出：{code: [(date, close, amount), ...]} ⚠️ 输出date降序（最新在前）"""
    out = {}
    cur = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 4 or parts[0] == "symbol" or "---" in parts[0]:
            continue
        if re.match(r"^(sh|sz|bj)\d{6}$", parts[0]):
            cur = parts[0]
            amt = float(parts[6]) if len(parts) > 6 and parts[6] else 0.0
            out.setdefault(cur, []).append((parts[1], float(parts[3]), amt))
    return out  # 每只股票内部降序：kl[0]=最新


def pct_n(closes, n):
    """最近n个交易日的涨跌幅(%)，closes降序(最新在前)"""
    if len(closes) > n:
        return (closes[0] - closes[n]) / closes[n] * 100
    return None


def find_file(names):
    """按候选路径列表找文件，返回第一个存在的"""
    for p in names:
        if os.path.exists(p):
            return p
    return None


def load_width(width_path):
    """读 market_width_latest.json，返回dict或None"""
    p = find_file(width_path) or find_file([
        "outputs/market_width_latest.json", "../outputs/market_width_latest.json",
        "/sandbox/workspace/github_bg/outputs/market_width_latest.json"])
    if not p:
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def load_mode_aggregate():
    """读猛兽双模式市场聚合（mode_aggregate_latest.json），失败返回None"""
    for p in ("outputs/mode_aggregate_latest.json", "mode_aggregate_latest.json",
              "../outputs/mode_aggregate_latest.json",
              "/sandbox/workspace/github_bg/outputs/mode_aggregate_latest.json"):
        if os.path.exists(p):
            try:
                return json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
    return None


def load_hs300(hs300_path):
    """读hs300成分股代码集合（含sh/sz前缀）"""
    p = find_file(hs300_path) or find_file([
        "quant_scripts/hs300.csv", "../quant_scripts/hs300.csv",
        "/sandbox/workspace/github_bg/quant_scripts/hs300.csv"])
    if not p:
        return set()
    try:
        rows = csv.reader(open(p, encoding="utf-8"))
        return {r[0].strip().lower() for r in rows if r and re.match(r"^(sh|sz)\d{6}$", r[0].strip().lower())}
    except Exception:
        return set()


# ============================================================
# A. 大小盘相对强弱（±40）—— 文章标准② 板块指数走势与量能
# ============================================================
def score_size_style(big_df, small_df, mid_df):
    """big=沪深300, small=中证1000, mid=中证500。返回(得分, 明细dict)"""
    sc, det = 0, {}

    def closes(df):
        return [c for _, c, _ in df] if df else []

    bc, sc_ = closes(big_df), closes(small_df)
    if len(bc) < 21 or len(sc_) < 21:
        return 0, {"err": "指数K线不足"}

    r5 = pct_n(sc_, 5) - pct_n(bc, 5)
    r10 = pct_n(sc_, 10) - pct_n(bc, 10)
    r20 = pct_n(sc_, 20) - pct_n(bc, 20)
    det.update({
        "hs300_5d": round(pct_n(bc, 5), 2), "hs300_10d": round(pct_n(bc, 10), 2),
        "zz1000_5d": round(pct_n(sc_, 5), 2), "zz1000_10d": round(pct_n(sc_, 10), 2),
        "rel_5d": round(r5, 2), "rel_10d": round(r10, 2), "rel_20d": round(r20, 2),
    })

    # 小盘领涨（情绪） vs 大盘领涨（机构）
    if r5 > 2: sc += 12
    elif r5 < -1: sc -= 12
    if r10 > 3: sc += 8
    elif r10 < -2: sc -= 8
    if r20 > 5: sc += 5
    elif r20 < -4: sc -= 5

    # 小盘垂直拉升脉冲（游资题材特征：1-3天涨幅大）
    small_1d = pct_n(sc_, 1)
    if small_1d is not None and small_1d > 3.5:
        sc += 8
        det["small_pulse_1d"] = round(small_1d, 2)
    if r5 > 10:
        sc += 7  # 5日涨超10% = 垂直拉升

    # 大盘45度趋势（机构特征：均线多头，站上20日线）
    if len(bc) >= 21:
        ma5 = sum(bc[:5]) / 5
        ma20 = sum(bc[:20]) / 20
        if bc[0] > ma5 > ma20:
            sc -= 5
            det["hs300_ma_trend"] = "多头排列"

    # 中证500作中间带：若小盘涨但中盘不跟 → 纯小票情绪；若三线齐涨 → 普涨(幅度加权已体现)
    if mid_df and len([c for _, c, _ in mid_df]) >= 6:
        mid_5d = pct_n([c for _, c, _ in mid_df], 5) or 0
        det["zz500_5d"] = round(mid_5d, 2)
        if r5 > 2 and mid_5d < r5 - 1:
            sc += 3  # 中小背离：资金抱团小盘题材
            det["small_mid_diverg"] = "小盘独涨·中盘不跟"

    return max(-40, min(40, sc)), det


# ============================================================
# B. 涨停结构与宽度（±35）—— 文章标准④ 涨停股结构与梯队
# ============================================================
def score_limitup_structure(width, hs300_set):
    """width=market_width JSON。返回(得分, 明细dict)"""
    if not width:
        return 0, {"err": "无市场宽度数据"}

    sc = 0
    n = width.get("valid", 0)
    lu = width.get("limitup", 0)
    strong = width.get("strong", 0)
    wscore = width.get("score", 50)
    det = {"limitup": lu, "strong": strong, "width_score": wscore, "level": width.get("level", "")}

    # 涨停家数（文章：机构市3-8家 / 游资市>15家爆发）
    if lu > 15: sc += 12
    elif lu >= 10: sc += 8
    elif lu >= 3: sc += 2
    elif n > 0 and lu < 3: sc -= 3

    # 中军涨停结构（文章：机构市大市值中军涨停 / 游资市纯小票）
    lu_list = width.get("limitup_list", [])
    zhongjun = [x for x in lu_list if x.get("code", "").lower() in hs300_set]
    det["zhongjun_cnt"] = len(zhongjun)
    det["zhongjun"] = [f"{x['name']}({x['pct']:.1f}%)" for x in zhongjun][:5]
    if zhongjun:
        sc -= 10  # 大市值中军涨停 = 机构资金主导
    elif lu > 10:
        sc += 5   # 涨停潮但无中军 = 纯游资生态

    # 强势股占比（情绪温度）
    if n > 0:
        strong_ratio = strong / n * 100
        det["strong_ratio"] = round(strong_ratio, 1)
        if strong_ratio > 5: sc += 8
        elif strong_ratio > 2.5: sc += 4
        elif strong_ratio < 1: sc -= 5

    # 宽度分（普涨=情绪热 / 弱势=情绪冰）
    if wscore >= 70: sc += 8
    elif wscore >= 55: sc += 3
    elif wscore >= 40: sc += 0
    elif wscore >= 25: sc -= 5
    else: sc -= 10

    # 炸板率修正（2026-08-10 涨停池代理·连板/炸板自算）：<20%情绪健康加分 / >40%退潮预警减分
    st = width.get("limitup_stats") or {}
    zr = st.get("zhaban_rate")
    if zr is not None:
        det["zhaban_rate"] = zr
        det["lianban"] = st.get("lianban", 0)
        if zr < 20:
            sc += 4  # 炸板率低=封板坚决，情绪健康
        elif zr < 40:
            sc += 0
        else:
            sc -= 8  # 炸板率高=触板即被砸，情绪退潮
    return max(-35, min(35, sc)), det


# ============================================================
# C. 成交结构（±15）—— 文章标准②/③ 量能脉冲与资金去向
# ============================================================
def score_volume_structure(big_df, small_df):
    """中小盘成交额相对大盘的占比变化：情绪市资金涌向小盘。返回(得分, 明细dict)"""
    if not big_df or not small_df:
        return 0, {"err": "K线不足"}
    big_amt = [a for _, _, a in big_df]
    small_amt = [a for _, _, a in small_df]
    if len(big_amt) < 6 or len(small_amt) < 6:
        return 0, {"err": "K线不足"}

    sc = 0
    ratio_now = small_amt[0] / big_amt[0] if big_amt[0] else 0
    ratio_5 = sum(small_amt[1:6]) / sum(big_amt[1:6]) if sum(big_amt[1:6]) else 0
    det = {
        "small_big_ratio_now": round(ratio_now, 3),
        "small_big_ratio_5d": round(ratio_5, 3),
    }
    if ratio_now > ratio_5 * 1.1:
        sc += 8   # 资金涌向中小盘
        det["vol_shift"] = "资金流向中小盘"
    elif ratio_now < ratio_5 * 0.9:
        sc -= 8   # 资金回流大盘
        det["vol_shift"] = "资金回流大盘"

    # 小盘量能脉冲（单日成交额>5日均值1.5倍 = 题材放量）
    small_pulse = small_amt[0] / (sum(small_amt[1:6]) / 5) if sum(small_amt[1:6]) else 1
    if small_pulse > 1.5:
        sc += 7
        det["small_vol_pulse"] = round(small_pulse, 2)
    return max(-15, min(15, sc)), det


# ============================================================
# D. 板块资金定性（±10，增强项）—— 文章标准③ 资金流向结构
# ============================================================
def score_sector_fund(top_n=5):
    """涨幅TOP板块的 asfund 主力/散户结构：主力净流入+散户净流出=机构型(-)，反之为游资型(+)"""
    txt = run(["hot", "board", "--limit", str(top_n)])
    sectors = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 9 and re.match(r"^pt\d+$", parts[2]):
            sectors.append((parts[2], parts[7], parts[8]))  # (code, name, zdf)
    if not sectors:
        return 0, {"err": "无板块数据"}

    def parse_asfund(raw):
        """asfund表格按表头驱动解析为 {列名: 值}，取最后一个与表头等宽的数据行"""
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip().startswith("|")]
        if len(lines) < 2:
            return {}
        header = [p.strip() for p in lines[0].strip("|").split("|")]
        for ln in reversed(lines[1:]):
            d = [p.strip() for p in ln.strip("|").split("|")]
            if len(d) == len(header):
                return dict(zip(header, d))
        return {}

    sc, det, items = 0, {}, []
    for code, name, zdf in sectors[:top_n]:
        row = parse_asfund(run(["asfund", code]))
        if not row:
            continue
        try:
            mn5 = float(row.get("MainNetFlow5D", 0) or 0)
            mn1 = float(row.get("MainNetFlow", 0) or 0)
            mn = mn5 if mn5 else mn1  # 5日累计优先（文章：主力连续5日净流入=机构）
            r_in = float(row.get("RetailInFlow", 0) or 0)
            r_out = float(row.get("RetailOutFlow", 0) or 0)
            retail = r_in - r_out
        except Exception:
            continue
        if mn > 0 and retail < 0:
            sc -= 3   # 主力净流入+散户净流出 = 机构吸筹
            tag = "机构型"
        elif mn <= 0:
            sc += 3   # 主力净流出却上涨 = 游资/散户推动
            tag = "游资型"
        else:
            sc += 1
            tag = "混合"
        items.append({"name": name, "zdf": zdf, "main_net5d": round(mn / 1e8, 1), "retail_net": round(retail / 1e8, 1), "tag": tag})
    det["sectors"] = items
    return max(-10, min(10, sc)), det


# ============================================================
# 主流程
# ============================================================
def main():
    width_path, hs300_path = [], []
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--width" and i + 1 < len(argv):
            width_path = [argv[i + 1]]
        if a == "--hs300" and i + 1 < len(argv):
            hs300_path = [argv[i + 1]]

    width = load_width(width_path)
    mode_agg = load_mode_aggregate()
    if mode_agg:
        print(f"[INFO] 猛兽双模式聚合: 主导={mode_agg.get('dominant','—')} {json.dumps(mode_agg.get('leaders', {}), ensure_ascii=False)}", flush=True)
    hs300_set = load_hs300(hs300_path)
    if width:
        print(f"[INFO] 市场宽度: 分{width.get('score')} {width.get('level','')} 涨停{width.get('limitup')} 强势{width.get('strong')}", flush=True)
    else:
        print("[WARN] 未找到 market_width_latest.json，B/C 轴部分数据缺失（可先运行 market_width.py）", flush=True)

    # 拉指数K线（批量）
    codes = list(ALL_IDX.keys())
    txt = run(["kline", ",".join(codes), "--period", "day", "--limit", "25"])
    kl = parse_kline(txt)
    big_df = kl.get("sh000300", [])
    small_df = kl.get("sh000852", [])
    mid_df = kl.get("sh000905", [])
    if not big_df or not small_df:
        print("[ERROR] 指数K线拉取失败", file=sys.stderr)
        sys.exit(1)

    # 四轴打分
    sc_a, det_a = score_size_style(big_df, small_df, mid_df)
    sc_b, det_b = score_limitup_structure(width, hs300_set)
    sc_c, det_c = score_volume_structure(big_df, small_df)
    sc_d, det_d = score_sector_fund()
    total = sc_a + sc_b + sc_c + sc_d

    # 三态判定
    if total >= 25:
        style, icon = "情绪市", "🔥"
        adv = ("游资主导·中小盘题材场子：主扫猛兽堆量模式/武威G1低吸，快进快出；"
               "警惕A字杀跌（文章：游资票暴涨暴跌、退潮即A杀），连板退潮日减仓")
    elif total <= -25:
        style, icon = "指数市", "🏦"
        adv = ("机构主导·大蓝筹地盘：主扫黑石乾坤金股/猛兽欧马模式/月线反转趋势股；"
               "回调缩量不破位可持股（文章：机构票45度慢牛、回调浅），趋势破60日线才离场")
    else:
        style, icon = "均衡市", "⚖️"
        adv = "多空风格混杂：三阶漏斗正常执行，大小盘均衡配置，单日脉冲后确认再追"

    today = datetime.now().strftime("%Y-%m-%d")
    data_date = kl["sh000300"][0][0] if kl.get("sh000300") else today
    # ⑤ 猛兽双模式交叉验证（不参与打分，仅交叉确认）
    cross = {}
    if mode_agg:
        dom = mode_agg.get("dominant", "无显著主导")
        if (style == "情绪市" and dom == "堆量模式") or (style == "指数市" and dom == "欧马模式"):
            verdict = "✅ 强共振（风格轴与猛兽双模式一致）"
        elif style == "均衡市":
            verdict = "ℹ️ 均衡市（风格轴中性，以猛兽信号为准）"
        else:
            verdict = "⚠️ 背离（风格轴与猛兽信号偏好不一致，注意结构分化）"
        cross = {"dominant": dom, "all": mode_agg.get("all", {}),
                 "leaders": mode_agg.get("leaders", {}), "pullbacks": mode_agg.get("pullbacks", {}),
                 "gpoints": mode_agg.get("gpoints", {}), "verdict": verdict,
                 "total_scored": mode_agg.get("total_scored", 0)}
    dom = cross.get("dominant", "无猛兽数据") if cross else "无猛兽数据"
    verdict = cross.get("verdict", "⚠️ 猛兽未运行或未输出聚合") if cross else "⚠️ 猛兽未运行或未输出聚合"
    js = {
        "date": today, "data_date": data_date,
        "style": style, "icon": icon, "score": total,
        "score_detail": {"size_style": sc_a, "limitup_structure": sc_b,
                         "volume_structure": sc_c, "sector_fund": sc_d},
        "size_style": det_a, "limitup_structure": det_b,
        "volume_structure": det_c, "sector_fund": det_d,
        "mode_cross": cross,
        "advice": adv,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "market_style_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    # 报告
    da = det_a; db = det_b; dc = det_c; dd = det_d
    md = f"""# 🎛️ 市场风格轴 {today}

> 数据截止 {data_date} | 指数市(机构主导·大蓝筹) ↔ 情绪市(游资主导·中小盘)
> 来源：《判断板块是"机构主导"还是"游资主导"》五大标准量化映射

## 判定：{icon} {style}（风格分 {total:+d} / -100~+100）

**操作映射**：{adv}

## ① 大小盘相对强弱（{sc_a:+d}/±40）· 文章标准②
- 沪深300近5日 {da.get('hs300_5d','—')}% / 10日 {da.get('hs300_10d','—')}% | 中证1000近5日 {da.get('zz1000_5d','—')}% / 10日 {da.get('zz1000_10d','—')}%
- 相对强弱：5日 {da.get('rel_5d','—')}% · 10日 {da.get('rel_10d','—')}% · 20日 {da.get('rel_20d','—')}%（正=小盘领涨·情绪，负=大盘领涨·机构）
- 中证500近5日 {da.get('zz500_5d','—')}% {da.get('small_mid_diverg','')} {da.get('hs300_ma_trend','')}
- 小盘脉冲1日 {da.get('small_pulse_1d','—')}%

## ② 涨停结构与宽度（{sc_b:+d}/±35）· 文章标准④
- 涨停 {db.get('limitup','—')} 家（机构市3-8家 / 游资市>15家爆发）· 强势≥5% {db.get('strong','—')} 家（占比 {db.get('strong_ratio','—')}%）
- 中军涨停（沪深300成分）{db.get('zhongjun_cnt','—')} 家{('：' + '、'.join(db.get('zhongjun', []))) if db.get('zhongjun') else ''}
- 宽度分 {db.get('width_score','—')} {db.get('level','')} {db.get('err','')}
- 注：连板高度/炸板率无数据源（westock无涨停池接口），以涨停家数+中军结构代理

## ③ 成交结构（{sc_c:+d}/±15）· 文章标准②/③
- 中证1000/沪深300成交额比：今 {dc.get('small_big_ratio_now','—')} vs 5日均 {dc.get('small_big_ratio_5d','—')} {dc.get('vol_shift','')} {dc.get('err','')}
- 小盘量能脉冲 {dc.get('small_vol_pulse','—')}（>1.5 = 题材放量）

## ④ 板块资金定性（{sc_d:+d}/±10）· 文章标准③
"""
    if dd.get("sectors"):
        md += "| 板块 | 涨幅% | 主力净流(亿) | 散户净流(亿) | 定性 |\n|---|---|---|---|---|\n"
        for s in dd["sectors"]:
            md += f"| {s['name']} | {s['zdf']} | {s['main_net5d']} | {s['retail_net']} | {s['tag']} |\n"
    else:
        md += f"- {dd.get('err', '无数据')}\n"
    md += f"""
## ⑥ 猛兽双模式交叉验证（堆量 vs 欧马）

- 主导模式：**{dom}**（评分股 {cross.get('total_scored', 0)} 只）
- 领先股 {json.dumps(cross.get('leaders', {}), ensure_ascii=False)} · 回调股 {json.dumps(cross.get('pullbacks', {}), ensure_ascii=False)} · G点 {json.dumps(cross.get('gpoints', {}), ensure_ascii=False)}
- 交叉验证：{verdict}
- 说明：猛兽信号=热搜候选池当日评分（样本小，仅作次级确认）；堆量=情绪+资金溢出小盘 / 欧马=产业+业绩成长中大盘

## ⑤ 消息面逻辑深度 · 文章标准⑤（人工研判项）
- 机构主导特征：持续产业逻辑（订单/出货/毛利率可量化验证）+ 研报密集覆盖
- 游资主导特征：单一事件催化 + 逻辑模糊难证伪 + 股吧/短视频传播
- 提示：风格轴只回答"谁在买"的结构问题，逻辑深度需人工结合新闻/研报确认

---
*风格轴 = 大小盘相对强弱(40) + 涨停结构宽度(35) + 成交结构(15) + 板块资金定性(10)，正分=情绪市，负分=指数市*
"""
    md_path = os.path.join(OUT_DIR, f"market_style_{today}.md")
    open(md_path, "w", encoding="utf-8").write(md)
    print(f"[OK] {md_path}")
    print(f"[OK] {json_path}")
    print(f"风格={style} 总分={total:+d} (A={sc_a:+d} B={sc_b:+d} C={sc_c:+d} D={sc_d:+d})")


if __name__ == "__main__":
    main()
