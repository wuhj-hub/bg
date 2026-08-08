#!/usr/bin/env python3
"""
持仓追踪模块 — position_tracker.py
====================================
每日自动扫描持仓股，监控评分变化、技术面信号、环境变化。
弥补体系「买入后如何持有」的缺失环节。

用法：
    # 持仓文件格式 (JSON)
    # {"positions": [
    #   {"code": "600095", "name": "湘财股份", "entry_price": 8.54, "entry_date": "2026-07-20", "shares": 1000},
    # ]}
    
    # 检查持仓
    python3 position_tracker.py --portfolio my_positions.json
    
    # 模拟持仓（测试用）
    python3 position_tracker.py --demo

输出：Markdown 格式的持仓监控报告
"""

import json, os, subprocess, sys
from datetime import datetime, date
from pathlib import Path

# ==================== 配置 ====================
SCRIPTS_DIR = Path(__file__).parent
EVALUATOR = str(SCRIPTS_DIR / "stock_evaluator.py")
FILTER_RULES = str(SCRIPTS_DIR / "filter_rules.py")

# 默认持仓路径
DEFAULT_PORTFOLIO = str(SCRIPTS_DIR.parent / "positions" / "portfolio.json")

# 温度阈值
TEMP_HIGH = 70    # 进攻模式
TEMP_MID = 55     # 偏强
TEMP_LOW = 40     # 防守
TEMP_DANGER = 25  # 空仓


def load_portfolio(path: str = None) -> list:
    """加载持仓文件"""
    if path is None:
        path = DEFAULT_PORTFOLIO
    
    if not os.path.exists(path):
        # 返回空持仓
        return []
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("positions", [])


def get_market_temp() -> int:
    """获取当前大盘温度（简化版，通过westock）"""
    cmd = "npx -y westock-data-skillhub@1.0.3 kline sh000001 --period day --limit 10 2>/dev/null"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        lines = [l.strip() for l in r.stdout.split("\n") if l.strip()]
        closes = []
        for line in lines[2:]:  # 跳过表头和分隔线
            parts = line.split("|")
            if len(parts) >= 4:
                try:
                    c = float(parts[3].strip())  # last/close
                    closes.append(c)
                except:
                    pass
        if len(closes) >= 3:
            latest = closes[0]
            high_10d = max(closes)
            low_10d = min(closes)
            pos = (latest - low_10d) / (high_10d - low_10d) if high_10d != low_10d else 0.5
            temp = round(pos * 60) + 20
            return max(0, min(100, temp))
    except:
        pass
    return 50  # 默认中性


def check_position(position: dict, market_temp: int) -> dict:
    """
    对单个持仓进行监控检查
    
    返回: {
        "code", "name", "entry_price", "market_temp",
        "current_score": 当前评分,
        "score_change": 评分变化(与上次比),
        "macd_status": "金叉/死叉/红柱/绿柱",
        "stop_loss_price": 止损价(MA20*0.97),
        "alert_level": "正常/关注/警告/危险",
        "action": "持有/加仓/减仓/清仓",
        "reasons": [原因列表]
    }
    """
    result = {
        "code": position["code"],
        "name": position.get("name", position["code"]),
        "entry_price": position.get("entry_price", 0),
        "entry_date": position.get("entry_date", ""),
        "market_temp": market_temp,
        "current_score": 0,
        "score_change": 0,
        "prev_score": position.get("last_score", 0),
        "macd_status": "未知",
        "stop_loss_price": 0,
        "current_price": 0,
        "profit_pct": 0,
        "alert_level": "正常",
        "action": "持有",
        "reasons": []
    }
    
    # 运行 stock_evaluator 获取评分
    try:
        eval_cmd = f"python3 {EVALUATOR} {position['code']} 2>/dev/null"
        r = subprocess.run(eval_cmd, shell=True, capture_output=True, text=True, timeout=120)
        output = r.stdout
        
        # 从输出中提取评分
        import re
        score_match = re.search(r'(\d+)/(\d+)分', output)
        if score_match:
            result["current_score"] = int(score_match.group(1))
        
        # 提取信号形态
        pattern_match = re.search(r'\*\*信号形态\*\*:\s*(\S+)', output)
        if pattern_match:
            result["pattern"] = pattern_match.group(1)
        
        # 提取建议
        advice_match = re.search(r'操作建议.*?\|.*?\|(.+?)\|', output)
        if advice_match:
            result["advice_text"] = advice_match.group(1).strip()
        
        # 提取止损
        stop_match = re.search(r'参考止损.*?(\d+\.?\d*)', output)
        if stop_match:
            result["stop_loss_price"] = float(stop_match.group(1))
        
        # 提取当前价（从评分卡前面部分找价格信息）
        price_match = re.search(r'\((\d+\.?\d*)\)\s*·', output)
        if price_match:
            result["current_price"] = float(price_match.group(1))
        
    except Exception as e:
        result["reasons"].append(f"评估器异常: {e}")
    
    # 计算盈亏
    if result["current_price"] > 0 and result["entry_price"] > 0:
        result["profit_pct"] = round((result["current_price"] / result["entry_price"] - 1) * 100, 2)
    
    # 评分变化
    if result["prev_score"] > 0:
        result["score_change"] = result["current_score"] - result["prev_score"]
    
    # 判断MACD状态（从技术数据中）
    try:
        raw_code = position["code"]
        if len(raw_code) == 6:
            prefix = "sh" if raw_code.startswith("6") else "sz"
            tech_cmd = f"npx -y westock-data-skillhub@1.0.3 technical {prefix}{raw_code} --group macd 2>/dev/null"
            tr = subprocess.run(tech_cmd, shell=True, capture_output=True, text=True, timeout=30)
            if "diff" in tr.stdout.lower() or "dif" in tr.stdout.lower() or "dea" in tr.stdout.lower():
                result["macd_status"] = "✅ MACD数据可用"
            else:
                result["macd_status"] = "需刷新"
    except:
        pass
    
    # === 告警逻辑 ===
    
    # 1. 大盘环境降级
    if market_temp < TEMP_DANGER:
        result["alert_level"] = "危险"
        result["action"] = "清仓"
        result["reasons"].append(f"⚠️ 大盘温度{market_temp}<{TEMP_DANGER}(冰点), 环境极端恶化, 建议清仓")
    elif market_temp < TEMP_LOW:
        if result["profit_pct"] > 10:
            result["alert_level"] = "警告"
            result["action"] = "减仓"
            result["reasons"].append(f"⚠️ 大盘温度{market_temp}<{TEMP_LOW}(偏冷), 建议减仓至半仓以下")
        else:
            result["alert_level"] = "关注"
            result["action"] = "减仓"
            result["reasons"].append(f"📢 大盘温度{market_temp}<{TEMP_LOW}, 考虑减仓")
    
    # 2. 评分大幅下降
    if result["score_change"] <= -20:
        result["alert_level"] = "危险"
        result["action"] = "清仓"
        result["reasons"].append(f"🔴 评分从{result['prev_score']}降至{result['current_score']}(-{abs(result['score_change'])}分), 信号恶化")
    elif result["score_change"] <= -10:
        result["alert_level"] = "警告"
        result["action"] = "减仓"
        result["reasons"].append(f"🟡 评分下降{result['score_change']}分, 关注")
    
    # 3. 绝对评分低
    if result["current_score"] < 40 and result["current_score"] > 0:
        result["alert_level"] = "危险"
        result["action"] = "清仓"
        result["reasons"].append(f"🔴 当前评分{result['current_score']}<40, 已不具备持有条件")
    elif result["current_score"] < 55 and result["current_score"] > 0:
        if result["alert_level"] not in ("危险", "警告"):
            result["alert_level"] = "关注"
            result["action"] = "减仓"
            result["reasons"].append(f"🟡 评分{result['current_score']}<55, 偏弱, 考虑减仓")
    
    # 4. 加仓条件（评分高+有利润+大盘好）
    if (result["current_score"] >= 75 and market_temp >= TEMP_HIGH 
        and result["profit_pct"] > 5 and result["profit_pct"] < 30):
        result["action"] = "加仓"
        result["reasons"].append(f"🟢 评分{result['current_score']}+大盘{market_temp}+盈利{result['profit_pct']:+.1f}%, 可加仓")
    
    # 5. 盈利过多考虑止盈
    if result["profit_pct"] > 50:
        result["reasons"].append(f"💰 已盈利{result['profit_pct']:+.1f}%, 考虑分批止盈")
    
    return result


def generate_report(positions: list, output_file: str = None) -> str:
    """生成持仓监控报告"""
    market_temp = get_market_temp()
    
    temp_level = "🔥进攻" if market_temp >= TEMP_HIGH else \
                 "🟢偏强" if market_temp >= TEMP_MID else \
                 "🟡防守" if market_temp >= TEMP_LOW else \
                 "🔴观望" if market_temp >= TEMP_DANGER else \
                 "⚫空仓"
    
    lines = []
    lines.append("---")
    lines.append("")
    lines.append("## 📊 持仓追踪日报")
    lines.append("")
    lines.append(f"> {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  大盘温度: **{market_temp}/100** ({temp_level})")
    lines.append("")
    
    if not positions:
        lines.append("*当前无持仓*")
        lines.append("")
        lines.append("---")
        return "\n".join(lines)
    
    # 扫描每个持仓
    results = []
    for pos in positions:
        r = check_position(pos, market_temp)
        results.append(r)
    
    # 汇总统计
    alert_count = sum(1 for r in results if r["alert_level"] in ("警告", "危险"))
    gainers = sum(1 for r in results if r["profit_pct"] > 0)
    
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|:----|:----:|")
    lines.append(f"| 持仓数 | {len(results)} |")
    lines.append(f"| 盈利数 | {gainers}/{len(results)} |")
    lines.append(f"| 告警数 | {alert_count} |")
    lines.append(f"| 建议加仓 | {sum(1 for r in results if r['action']=='加仓')} |")
    lines.append(f"| 建议减仓/清仓 | {sum(1 for r in results if r['action'] in ('减仓','清仓'))} |")
    lines.append("")
    
    # 详细列表
    lines.append("### 持仓明细")
    lines.append("")
    lines.append("| 代码 | 名称 | 入场价 | 现价 | 盈亏% | 评分 | 评分变化 | 止损价 | 告警 | 建议 |")
    lines.append("|:----:|:----:|:-----:|:----:|:----:|:----:|:--------:|:-----:|:----:|:----:|")
    
    for r in results:
        profit_str = f"+{r['profit_pct']:.1f}%" if r['profit_pct'] > 0 else f"{r['profit_pct']:.1f}%"
        score_str = f"{r['current_score']}/100" if r['current_score'] > 0 else "—"
        change_str = f"{r['score_change']:+d}" if r['score_change'] != 0 else "="
        stop_str = f"{r['stop_loss_price']:.2f}" if r['stop_loss_price'] > 0 else "—"
        
        # 告警等级图标
        alert_icon = {"正常": "✅", "关注": "📢", "警告": "⚠️", "危险": "🚨"}.get(r["alert_level"], "❓")
        
        lines.append(f"| {r['code']} | {r['name']} | {r['entry_price']:.2f} | {r['current_price']:.2f} | {profit_str} | {score_str} | {change_str} | {stop_str} | {alert_icon} | {r['action']} |")
    
    lines.append("")
    
    # 告警详情
    alerts = [r for r in results if r["reasons"]]
    if alerts:
        lines.append("### 🚨 告警详情")
        lines.append("")
        for r in alerts:
            alert_icon = {"正常": "✅", "关注": "📢", "警告": "⚠️", "危险": "🚨"}.get(r["alert_level"], "❓")
            lines.append(f"**{alert_icon} {r['name']}({r['code']})**:")
            for reason in r["reasons"]:
                lines.append(f"- {reason}")
            lines.append("")
    
    # 操作汇总
    lines.append("### 📋 今日操作建议")
    lines.append("")
    
    add = [r for r in results if r["action"] == "加仓"]
    hold = [r for r in results if r["action"] == "持有"]
    reduce = [r for r in results if r["action"] == "减仓"]
    clear = [r for r in results if r["action"] == "清仓"]
    
    if add:
        items = [r['name'] + '(' + r['code'] + ')' for r in add]
        lines.append(f"**🟢 可加仓**: {'、'.join(items)}")
    if hold:
        items = [r['name'] + '(' + r['code'] + ')' for r in hold]
        lines.append(f"**✅ 继续持有**: {'、'.join(items)}")
    if reduce:
        items = [r['name'] + '(' + r['code'] + ')' for r in reduce]
        lines.append(f"**🟡 建议减仓**: {'、'.join(items)}")
    if clear:
        items = [r['name'] + '(' + r['code'] + ')' for r in clear]
        lines.append(f"**🔴 建议清仓**: {'、'.join(items)}")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*数据来源：统一交易体系v3.0  stock_evaluator | 持仓数据需手动维护 portfolio.json*")
    
    report = "\n".join(lines)
    
    # 保存
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"✅ 持仓报告已保存: {output_file}")
    
    return report


def demo():
    """演示模式：创建模拟持仓并运行"""
    demo_positions = [
        {"code": "600095", "name": "湘财股份", "entry_price": 8.54, 
         "entry_date": "2026-07-18", "shares": 2000, "last_score": 65},
        {"code": "601138", "name": "工业富联", "entry_price": 55.00, 
         "entry_date": "2026-07-10", "shares": 500, "last_score": 82},
        {"code": "000779", "name": "甘咨询", "entry_price": 9.90, 
         "entry_date": "2026-07-15", "shares": 3000, "last_score": 55},
        {"code": "300308", "name": "中际旭创(新)", "entry_price": 1200, 
         "entry_date": "2026-07-22", "shares": 100, "last_score": 78},
    ]
    
    print(generate_report(demo_positions, "/sandbox/workspace/outputs/持仓追踪日报_演示.md"))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="持仓追踪模块")
    parser.add_argument("--portfolio", help="持仓JSON文件路径")
    parser.add_argument("--output", help="输出报告路径")
    parser.add_argument("--demo", action="store_true", help="演示模式")
    args = parser.parse_args()
    
    if args.demo:
        demo()
        return
    
    path = args.portfolio or DEFAULT_PORTFOLIO
    positions = load_portfolio(path)
    
    if not positions:
        print(f"⚠️ 未找到持仓文件: {path}")
        print("   创建持仓文件或使用 --demo 模式。")
        print(f"   格式: {{\"positions\": [{{\"code\":\"600095\", \"name\":\"湘财股份\", \"entry_price\":8.54, \"shares\":1000}}]}}")
        return
    
    report = generate_report(positions, args.output)
    print(report)


if __name__ == "__main__":
    main()
