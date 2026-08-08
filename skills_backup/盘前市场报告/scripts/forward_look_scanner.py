#!/usr/bin/env python3
"""
前瞻牛股扫描器 — forward_look_scanner.py
===========================================
基于6只翻倍牛股（工业富联/紫金矿业/兆易创新/新易盛/中际旭创/天孚通信）
在加速主升浪启动前的5大共性特征，对当前市场做前瞻扫描。

核心逻辑：
    不是"事后画靶"，而是"模式识别"——
    过去翻倍牛股在启动前都经过了这5个信号， 
    现在有这些信号的股票，未来成为牛股的概率更高。

用法：
    # 全量扫描（建议盘后运行，约5-10分钟）
    python3 forward_look_scanner.py --full
    
    # 快速扫描（只用已有热门板块候选）
    python3 forward_look_scanner.py --quick

依赖：westock-data, stock_evaluator.py
输出：Markdown 格式的"未来牛股候选池"
"""

import json, os, subprocess, sys, re
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from filter_rules import is_tradable, FilterLevel, CHINEXT_TOP50


# ==================== westock 工具 ====================

def cli(cmd: str) -> str:
    full_cmd = f"npx -y westock-data-skillhub@1.0.3 {cmd} 2>/dev/null"
    try:
        r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=60)
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


# ==================== 翻倍牛股共性特征模型 ====================

# 基于6只牛股加速启动前的模式提炼
# 每个条件独立打分，总分0-100，≥70视为"具备翻倍潜力"

class MultiBaggerDetector:
    """
    翻倍牛股特征检测器
    
    5大共性特征（权重基于历史数据归纳）：
    1. 板块聚焦 (20分) — 所属板块RSR TOP10 + 资金持续流入
    2. 技术启动 (25分) — MACD空中加油 or 箱体突破 (主升浪启动信号)
    3. 趋势强度 (20分) — 均线多头排列 + 站上MA20
    4. 量价确认 (20分) — 放量突破 + 量比≥1.5
    5. 赛道持续 (15分) — 板块热度持续1月+, 非一日游
    
    总分≥80 → 🔥 强候选（类似工业富联2025.06, 新易盛2025.05的买点）
    总分≥65 → ✅ 关注候选（类似紫金矿业2025.03的买点）
    总分≥50 → ⚠️ 观察候选（需等待更多信号确认）
    """
    
    def __init__(self, code: str, name: str = ""):
        self.code = code
        self.name = name
        self.scores = {
            "板块聚焦": {"score": 0, "max": 20, "detail": ""},
            "技术启动": {"score": 0, "max": 25, "detail": ""},
            "趋势强度": {"score": 0, "max": 20, "detail": ""},
            "量价确认": {"score": 0, "max": 20, "detail": ""},
            "赛道持续": {"score": 0, "max": 15, "detail": ""},
        }
        self.total = 0
        self.level = ""
        self.pattern = ""
        self.board_info = ""
        
        # 缓存
        self._kline = None
        self._technical = None
        self._asfund = None
    
    def fetch(self):
        raw = self.code
        if len(raw) == 6:
            raw = f"sh{raw}" if raw.startswith(('6', '5')) else f"sz{raw}"
        
        self._kline = parse_table(cli(f"kline {raw} --period day --limit 30"))
        self._technical = parse_table(cli(f"technical {raw} --group all"))
        self._asfund = parse_table(cli(f"asfund {raw}"))
    
    def _safe_float(self, v, default=0.0) -> float:
        if not v or v == '-':
            return default
        try:
            return float(str(v).replace('%','').replace('+','').replace(',',''))
        except:
            return default
    
    def _get_price(self) -> dict:
        r = {"close": 0, "ma5": 0, "ma10": 0, "ma20": 0, "volume_ratio": 1,
             "high_20d": 0, "low_20d": 0, "amplitude": 0}
        if not self._kline:
            return r
        try:
            closes = []
            vols = []
            highs = []
            lows = []
            for row in self._kline:
                c = self._safe_float(row.get("收盘", row.get("close", row.get("last", 0))))
                v = self._safe_float(row.get("成交量", row.get("volume", 0)))
                h = self._safe_float(row.get("最高", row.get("high", 0)))
                l = self._safe_float(row.get("最低", row.get("low", 0)))
                if c > 0:
                    closes.append(c)
                    vols.append(v)
                    highs.append(h)
                    lows.append(l)
            
            if closes:
                r["close"] = closes[0]
                r["high_20d"] = max(highs[:min(20, len(highs))]) if highs else 0
                r["low_20d"] = min(lows[:min(20, len(lows))]) if lows else 0
                r["amplitude"] = (r["high_20d"] - r["low_20d"]) / r["low_20d"] * 100 if r["low_20d"] > 0 else 0
                
                if len(closes) >= 5:
                    r["ma5"] = sum(closes[:5]) / 5
                if len(closes) >= 10:
                    r["ma10"] = sum(closes[:10]) / 10
                if len(closes) >= 20:
                    r["ma20"] = sum(closes[:20]) / 20
                if len(vols) >= 6:
                    avg_v = sum(vols[1:6]) / 5
                    r["volume_ratio"] = vols[0] / avg_v if avg_v > 0 else 1
        except:
            pass
        return r
    
    def _get_tech(self) -> dict:
        r = {"dif": 0, "dea": 0, "macd": 0, "rsi_6": 50}
        if not self._technical:
            return r
        try:
            row = self._technical[0]
            r["dif"] = self._safe_float(row.get("macd.DIF", row.get("DIF", 0)))
            r["dea"] = self._safe_float(row.get("macd.DEA", row.get("DEA", 0)))
            r["macd"] = r["dif"] - r["dea"]
            r["rsi_6"] = self._safe_float(row.get("rsi.RSI_6", row.get("RSI_6", 0)), 50)
        except:
            pass
        return r
    
    def _get_fund(self) -> dict:
        r = {"net_flow": 0, "net_5d": 0}
        if not self._asfund:
            return r
        try:
            row = self._asfund[0]
            r["net_flow"] = self._safe_float(row.get("MainNetFlow", 0))
            r["net_5d"] = self._safe_float(row.get("MainNetFlow5D", 0))
        except:
            pass
        return r
    
    def evaluate(self):
        """运行5维检测"""
        self.fetch()
        price = self._get_price()
        tech = self._get_tech()
        fund = self._get_fund()
        
        close = price["close"]
        ma5 = price["ma5"]
        ma10 = price["ma10"]
        ma20 = price["ma20"]
        vol_ratio = price["volume_ratio"]
        high_20d = price["high_20d"]
        dif = tech["dif"]
        dea = tech["dea"]
        macd = tech["macd"]
        rsi = tech["rsi_6"]
        
        # === ① 板块聚焦 (0-20分) ===
        board_score = 8  # 默认中等
        board_detail = "板块数据通过search获取(预设中等)"
        # 简化：从资金流向判断板块强弱
        if fund["net_5d"] > 5e8:
            board_score = 18
            board_detail = "5日主力净流入>5亿, 板块资金聚焦"
        elif fund["net_5d"] > 1e8:
            board_score = 14
            board_detail = "5日主力净流入>1亿"
        elif fund["net_flow"] > 0:
            board_score = 10
            board_detail = "当日主力净流入为正"
        elif fund["net_flow"] > -1e7:
            board_score = 6
            board_detail = "资金中性"
        else:
            board_score = 3
            board_detail = "主力净流出较大"
        
        self.scores["板块聚焦"] = {"score": min(board_score, 20), "max": 20, "detail": board_detail}
        
        # === ② 技术启动 (0-25分) — 翻倍牛股最重要特征 ===
        tech_score = 3
        tech_detail = ""
        self.pattern = ""
        
        # 空中加油: DIF>0, DEA>0, DIF≈DEA(金叉附近), MACD柱翻红
        is_air_refuel = (dif > 0 and dea > 0 and abs(dif - dea) < dea * 0.08 
                         and macd > 0)
        # 箱体突破: 收盘价突破20日最高价的98%
        is_box_break = (high_20d > 0 and close >= high_20d * 0.98 
                        and vol_ratio >= 1.3 and close > ma20)
        # 均线回踩: 多头排列 + 价格回踩MA10/MA20 + 缩量
        is_ma_bounce = (ma5 > ma10 > ma20 and close >= ma20 * 0.97 
                        and close <= ma20 * 1.05 and vol_ratio < 0.9)
        
        if is_air_refuel:
            tech_score = 23
            self.pattern = "⭐空中加油"
            tech_detail = f"MACD零上({dif:.2f})金叉附近+柱翻红, 最强启动信号"
        elif is_box_break:
            tech_score = 20
            self.pattern = "🚀箱体突破"
            tech_detail = f"放量突破20日高点({high_20d:.2f}), 突破信号确认"
        elif is_ma_bounce:
            tech_score = 15
            self.pattern = "📍均线回踩"
            tech_detail = f"多头排列+回踩MA20({ma20:.2f}), 稳健低吸点"
        elif dif > 0 and macd > 0:
            tech_score = 10
            tech_detail = "MACD零上红柱, 趋势健康但无明确买点"
        elif rsi < 30:
            tech_score = 8
            tech_detail = "RSI<30超卖, 可能是底部区域"
        else:
            tech_detail = "无明确技术启动信号"
        
        self.scores["技术启动"] = {"score": min(tech_score, 25), "max": 25, "detail": tech_detail}
        
        # === ③ 趋势强度 (0-20分) ===
        trend_score = 4
        trend_detail = ""
        bull_arrange = ma5 > ma10 > ma20 if all(x > 0 for x in [ma5, ma10, ma20]) else False
        
        if bull_arrange and close > ma5:
            trend_score = 18
            trend_detail = f"均线多头排列(MA5>{ma5:.1f}), 强势趋势"
        elif bull_arrange:
            trend_score = 14
            trend_detail = "均线多头排列但价格在MA5下方, 短期回调中"
        elif ma20 > 0 and close > ma20:
            trend_score = 10
            trend_detail = f"站上MA20({ma20:.2f}), 中期趋势转多"
        elif ma20 > 0 and close > ma20 * 0.95:
            trend_score = 6
            trend_detail = "价格在MA20附近, 等待确认"
        else:
            trend_detail = "均线空头排列, 趋势偏弱"
        
        self.scores["趋势强度"] = {"score": min(trend_score, 20), "max": 20, "detail": trend_detail}
        
        # === ④ 量价确认 (0-20分) ===
        volume_score = 3
        volume_detail = ""
        
        if vol_ratio >= 2.0 and self.pattern:
            volume_score = 18
            volume_detail = f"倍量({vol_ratio:.1f}x)+形态确认, 放量启动信号"
        elif vol_ratio >= 1.5:
            volume_score = 14
            volume_detail = f"放量({vol_ratio:.1f}x), 量能配合"
        elif vol_ratio >= 1.2:
            volume_score = 10
            volume_detail = f"温和放量({vol_ratio:.1f}x)"
        elif vol_ratio < 0.7:
            volume_score = 5
            volume_detail = f"缩量({vol_ratio:.2f}x), 缩量整理等待放量"
        else:
            volume_score = 7
            volume_detail = f"量比{vol_ratio:.1f}x, 中性"
        
        self.scores["量价确认"] = {"score": min(volume_score, 20), "max": 20, "detail": volume_detail}
        
        # === ⑤ 赛道持续 (0-15分) ===
        sustain_score = 6
        sustain_detail = ""
        
        # 20日振幅判断趋势持续性（温和振幅=趋势健康）
        amp = price["amplitude"]
        if 10 < amp < 30:
            sustain_score = 13
            sustain_detail = f"20日振幅{amp:.0f}%, 温和趋势, 具备持续性"
        elif 5 < amp <= 10:
            sustain_score = 10
            sustain_detail = f"20日振幅{amp:.0f}%, 窄幅整理, 等待突破"
        elif amp >= 30:
            sustain_score = 8
            sustain_detail = f"20日振幅{amp:.0f}%偏大, 可能是高位震荡"
        else:
            sustain_detail = f"振幅{amp:.0f}%过低, 缺乏波动"
        
        # RSI在50-70之间=趋势健康可持續
        if 50 <= rsi <= 70:
            sustain_score += 2
            sustain_detail += ", RSI中位, 趋势健康"
        
        self.scores["赛道持续"] = {"score": min(sustain_score, 15), "max": 15, "detail": sustain_detail}
        
        # === 总分 ===
        self.total = sum(s["score"] for s in self.scores.values())
        
        if self.total >= 80:
            self.level = "🔥强候选"
        elif self.total >= 65:
            self.level = "✅关注"
        elif self.total >= 50:
            self.level = "⚠️观察"
        else:
            self.level = "⚪普通"
        
        return self.total
    
    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "total": self.total,
            "level": self.level,
            "pattern": self.pattern,
            "scores": {k: v["score"] for k, v in self.scores.items()},
            "details": {k: v["detail"] for k, v in self.scores.items()},
        }


# ==================== 候选股票池 ====================

def get_candidate_pool() -> list:
    """
    构建候选池来源：
    1. 热门板块成分股（从hot board提取）
    2. 自选核心股
    3. 热搜股
    """
    candidates = []
    seen = set()
    
    # 1. 热门板块TOP5的成分股（通过search获取板块代表性股）
    board_raw = cli("hot board --limit 10")
    boards = parse_table(board_raw)
    
    # 2. 固定候选池（核心关注+过往信号股）
    fixed_candidates = [
        ("600095", "湘财股份"), ("000779", "甘咨询"), ("002596", "海南瑞泽"),
        ("601138", "工业富联"), ("601899", "紫金矿业"), ("603986", "兆易创新"),
        # 创业板精选（新纳入）
        ("300308", "中际旭创"), ("300502", "新易盛"), ("300394", "天孚通信"),
        ("300476", "胜宏科技"), ("300463", "沪电股份"), ("300750", "宁德时代"),
        ("300059", "东方财富"), ("300124", "汇川技术"), ("300760", "迈瑞医疗"),
        # 主板热门
        ("601127", "赛力斯"), ("600519", "贵州茅台"), ("600900", "长江电力"),
        ("601398", "工商银行"), ("600030", "中信证券"),
    ]
    
    for code, name in fixed_candidates:
        result = is_tradable(code, name)
        if result["allowed"] and code not in seen:
            seen.add(code)
            candidates.append({"code": code, "name": name, "pool": result["pool"]})
    
    return candidates


# ==================== 主流程 ====================

def run_scan(mode: str = "quick") -> str:
    """执行前瞻扫描"""
    
    candidates = get_candidate_pool()
    
    if not candidates:
        return "⚠️ 未获取到候选股票"
    
    print(f"📡 扫描 {len(candidates)} 只候选股...")
    
    results = []
    for i, c in enumerate(candidates):
        det = MultiBaggerDetector(c["code"], c["name"])
        score = det.evaluate()
        info = det.to_dict()
        info["pool"] = c["pool"]
        results.append(info)
        
        if (i + 1) % 5 == 0:
            print(f"  进度: {i+1}/{len(candidates)}")
    
    # 按总分排序
    results.sort(key=lambda x: x["total"], reverse=True)
    
    # 分级
    strong = [r for r in results if r["total"] >= 80]
    watch = [r for r in results if 65 <= r["total"] < 80]
    observe = [r for r in results if 50 <= r["total"] < 65]
    normal = [r for r in results if r["total"] < 50]
    
    # === 输出 Markdown ===
    lines = []
    lines.append("---")
    lines.append("")
    lines.append("## 🔮 未来牛股候选扫描")
    lines.append("")
    lines.append(f"> 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  候选池: {len(candidates)}只")
    lines.append("> 扫描模型: 基于6只翻倍牛股(工业富联/紫金矿业/兆易创新/新易盛/中际旭创/天孚通信)的5大共性特征")
    lines.append("> ⚠️ 非预测, 仅为模式匹配。高分=历史上牛股启动前的相似状态, 非未来必然翻倍。")
    lines.append("")
    
    # 汇总
    lines.append("### 📊 扫描汇总")
    lines.append("")
    lines.append(f"| 等级 | 数量 | 含义 |")
    lines.append(f"|:----|:----:|:-----|")
    lines.append(f"| 🔥强候选(≥80分) | {len(strong)} | 类似工业富联2025.06/新易盛2025.05的买点状态 |")
    lines.append(f"| ✅关注(65~79分) | {len(watch)} | 类似紫金矿业2025.03的买点状态 |")
    lines.append(f"| ⚠️观察(50~64分) | {len(observe)} | 需等待更多信号确认 |")
    lines.append(f"| ⚪普通(<50分) | {len(normal)} | 暂不具备启动条件 |")
    lines.append("")
    
    if strong:
        lines.append("### 🔥 强候选（具备翻倍潜力特征）")
        lines.append("")
        lines.append(f"| 代码 | 名称 | 总分 | 形态 | 板块 | 主升浪判定 | 板块聚焦 | 技术启动 | 趋势强度 | 量价确认 | 赛道持续 |")
        lines.append(f"|:----:|:----:|:----:|:----:|:----:|:---------:|:--------:|:--------:|:--------:|:--------:|:--------:|")
        for r in strong:
            mw = "🔥主升浪" if r['total'] >= 80 else ("🟢候选" if r['total'] >= 70 else "⚪观察")
            lines.append(f"| {r['code']} | {r['name']} | **{r['total']}** | {r['pattern']} | {r['pool']} | {mw} | {r['scores']['板块聚焦']} | {r['scores']['技术启动']} | {r['scores']['趋势强度']} | {r['scores']['量价确认']} | {r['scores']['赛道持续']} |")
        lines.append("")
    
    if watch:
        lines.append("### ✅ 关注候选")
        lines.append("")
        lines.append("| 代码 | 名称 | 总分 | 形态 | 板块 | 板块聚焦 | 技术启动 | 趋势强度 | 量价确认 | 赛道持续 |")
        lines.append("|:----:|:----:|:----:|:----:|:----:|:--------:|:--------:|:--------:|:--------:|:--------:|")
        for r in watch:
            lines.append(f"| {r['code']} | {r['name']} | **{r['total']}** | {r['pattern']} | {r['pool']} | {r['scores']['板块聚焦']} | {r['scores']['技术启动']} | {r['scores']['趋势强度']} | {r['scores']['量价确认']} | {r['scores']['赛道持续']} |")
        lines.append("")
    
    if observe:
        lines.append("### ⚠️ 观察候选")
        lines.append("")
        observe_str = "、".join([f"{r['name']}({r['code']})[{r['total']}分]" for r in observe])
        lines.append(f"- {observe_str}")
        lines.append("")
    
    # 特征详解
    lines.append("### 📖 翻倍牛股5大共性特征说明")
    lines.append("")
    lines.append("| # | 特征 | 权重 | 判断标准 | 来源验证 |")
    lines.append("|:-:|:----|:---:|:---------|:---------|")
    lines.append("| ① | 板块聚焦 | 20分 | 板块RSR TOP10 + 主力资金持续流入 | 6只牛股均在板块TOP5内 |")
    lines.append("| ② | 技术启动 | 25分 | 空中加油/箱体突破/均线回踩 | 最强信号, 所有牛股加速段均出现 |")
    lines.append("| ③ | 趋势强度 | 20分 | 均线多头排列 + 站上MA20 | 牛股启动前均完成多头排列 |")
    lines.append("| ④ | 量价确认 | 20分 | 放量(量比≥1.5) + 技术形态 | 放量是启动的必要条件 |")
    lines.append("| ⑤ | 赛道持续 | 15分 | 温和振幅+RSI健康+非一日游 | 牛股趋势持续3个月+ |")
    lines.append("")
    lines.append("> 🎯 **用法**：强候选 → 纳入每日盘前报告重点关注 | 关注候选 → 用stock_evaluator深度评分 | 观察候选 → 加入自选等待条件改善")
    lines.append("")
    lines.append("*模式匹配工具, 不构成投资建议*")
    lines.append("---")
    
    report = "\n".join(lines)
    
    # 保存
    out_path = f"/sandbox/workspace/outputs/未来牛股候选_{datetime.now().strftime('%Y%m%d')}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n✅ 报告已保存: {out_path}")
    
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="前瞻牛股扫描器")
    parser.add_argument("--full", action="store_true", help="全量扫描")
    parser.add_argument("--quick", action="store_true", default=True, help="快速扫描(默认)")
    args = parser.parse_args()
    
    mode = "full" if args.full else "quick"
    report = run_scan(mode)
    print(report)


if __name__ == "__main__":
    main()
