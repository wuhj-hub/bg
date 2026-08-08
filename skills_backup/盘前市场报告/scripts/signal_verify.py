#!/usr/bin/env python3
"""
信号次日表现统计 — signal_verify.py
======================================
用途：读取昨日盘前报告中的推荐标的，查询今日实际走势，
      统计「次日最高涨幅」，建立报告的闭环验证机制。

集成点：
    复盘报告 Step 3「盘前预判验证」— 在现有的定性验证基础上，
    增加量化维度的「信号次日表现统计表」。
    
    也可独立运行，积累历史胜率数据。

用法：
    # 验证昨日盘前报告的标的今日表现
    python3 signal_verify.py
    
    # 指定日期回测
    python3 signal_verify.py --report-date 2026-07-23 --verify-date 2026-07-24

依赖：
    - 盘前市场报告_YYYY-MM-DD.md（知识库「盘前报告」文件夹）
    - westock kline 命令获取日K线
    
输出：Markdown 格式的信号验证报告
"""

import json, os, re, subprocess, sys
from datetime import datetime, timedelta

# ==================== 配置 ====================
KB_ID = "6kjd8jHpAyqf0xFVUo2xUWPaDAKapAWCw-Tki7V-aAs="
PRE_REPORT_FOLDER_ID = "folder_7485319502904253"  # 盘前报告文件夹
REPLAY_FOLDER_ID = "folder_7485234585035034"     # 复盘报告文件夹


def search_kb(query: str) -> list:
    cmd = f"""curl -s -X POST "https://ima.qq.com/openapi/wiki/v1/search_knowledge" \
  -H "ima-openapi-clientid: $IMA_OPENAPI_CLIENTID" \
  -H "ima-openapi-apikey: $IMA_OPENAPI_APIKEY" \
  -H "Content-Type: application/json" \
  -d '{{"query":"{query}","knowledge_base_id":"{KB_ID}"}}'"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        return data.get("data", {}).get("info_list", [])
    except:
        return []


def fetch_from_kb(media_id: str) -> str | None:
    cmd = f"""curl -s -X POST "https://ima.qq.com/openapi/wiki/v1/export_media_for_ima_sandbox" \
  -H "ima-openapi-clientid: $IMA_OPENAPI_CLIENTID" \
  -H "ima-openapi-apikey: $IMA_OPENAPI_APIKEY" \
  -H "Content-Type: application/json" \
  -d '{{"media_id":"{media_id}"}}'"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        if data.get("code") == 0:
            url = data["data"]["media_content_url_info"]["url"]
            r2 = subprocess.run(f"curl -s '{url}'", shell=True, capture_output=True, text=True, timeout=15)
            return r2.stdout
    except:
        pass
    return None


def fetch_kline_day(code: str, days: int = 5) -> list | None:
    """获取个股日K线（用于计算当日最高/最低/收盘）"""
    cmd = f"npx westock-data-skillhub@1.0.3 kline --code {code} --period day --limit {days} 2>/dev/null"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        lines = r.stdout.strip().split("\n")
        if len(lines) < 3:
            return None
        headers = lines[0].lower().split("\t")
        rows = []
        for line in lines[1:]:
            if not line.strip():
                continue
            vals = line.split("\t")
            if len(vals) >= len(headers):
                row = dict(zip(headers, vals))
                rows.append(row)
        return rows
    except:
        return None


def extract_stock_codes(text: str) -> list:
    """
    从报告文本中提取股票代码，同时尽量提取名称和推荐理由
    匹配格式：6位数字代码(可能是A股主板)
    同时尝试提取表格行 | 000779 | 甘咨询 |
    """
    stocks = []
    seen = set()
    
    # 匹配表格行
    table_pattern = re.compile(r'\|\s*(\d{6})\s*\|\s*([^|]+?)\s*\|')
    for m in table_pattern.finditer(text):
        code = m.group(1)
        name = m.group(2).strip()
        # 沪深主板过滤
        if not any(code.startswith(p) for p in ("688", "300", "301", "8", "43", "83", "87")):
            if code not in seen:
                seen.add(code)
                stocks.append({"code": code, "name": name})
    
    # 如果在表格中没找到，就用正则找代码（但没名称）
    if not stocks:
        code_pattern = re.findall(r'\b(6\d{5}|0\d{5})\b', text)
        for code in code_pattern:
            if code not in seen:
                seen.add(code)
                stocks.append({"code": code, "name": ""})
    
    return stocks


def get_today_kline(stock_code: str, verify_date: str) -> dict | None:
    """
    获取指定日期的日K线数据
    返回 {open, high, low, close, volume, amount, date} 或 None
    """
    klines = fetch_kline_day(stock_code, days=10)
    if not klines:
        return None
    
    # kline 降序（最新在前），找指定日期
    target_date = verify_date.replace("-", "")
    for k in klines:
        k_date = k.get("date", "").replace("-", "")
        if k_date == target_date:
            try:
                return {
                    "open": float(k.get("open", 0)),
                    "high": float(k.get("high", 0)),
                    "low": float(k.get("low", 0)),
                    "close": float(k.get("close", 0)),
                    "volume": float(k.get("volume", 0)),
                    "amount": float(k.get("amount", 0)),
                    "date": k.get("date", verify_date)
                }
            except (ValueError, KeyError):
                return None
    
    # 如果没找到指定日期，返回最新一条
    if klines:
        k = klines[0]
        try:
            return {
                "open": float(k.get("open", 0)),
                "high": float(k.get("high", 0)),
                "low": float(k.get("low", 0)),
                "close": float(k.get("close", 0)),
                "volume": float(k.get("volume", 0)),
                "amount": float(k.get("amount", 0)),
                "date": k.get("date", "未知")
            }
        except (ValueError, KeyError):
            return None
    
    return None


def find_yesterday_report(report_date: str) -> str | None:
    """从知识库找昨日盘前报告"""
    files = search_kb(f"盘前市场报告_{report_date}")
    if not files:
        # 尝试本地
        local_path = f"/sandbox/workspace/outputs/盘前市场报告_{report_date}.md"
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read()
        return None
    
    # 用第一个结果
    mid = files[0].get("media_id", "")
    if mid:
        return fetch_from_kb(mid)
    return None


def run_verify(report_date: str, verify_date: str, track_days: int = 1) -> str:
    """
    主流程（v2 - 支持多日跟踪）：
    1. 读取昨日盘前报告
    2. 提取推荐股票
    3. 查询T+1/T+3/T+5走势
    4. 统计次日/多日最高涨幅
    5. 输出验证报告
    
    Args:
        report_date: 盘前报告日期
        verify_date: 验证起始日期
        track_days: 跟踪天数（1=T+1, 3=T+3, 5=T+5）
    """
    # 1. 读报告
    report_content = find_yesterday_report(report_date)
    
    if not report_content:
        return (
            f"---\n\n"
            f"## 📊 信号次日表现统计\n\n"
            f"⏳ `盘前市场报告_{report_date}.md` 未找到，跳过信号验证\n\n"
            f"---\n"
        )
    
    # 2. 提取股票
    stocks = extract_stock_codes(report_content)
    if not stocks:
        return (
            f"---\n\n"
            f"## 📊 信号次日表现统计\n\n"
            f"⚠️ 报告中未解析到有效股票代码，请检查报告格式\n\n"
            f"---\n"
        )
    
    # 去重并限制数量
    seen = set()
    unique_stocks = []
    for s in stocks:
        if s["code"] not in seen:
            seen.add(s["code"])
            unique_stocks.append(s)
    stocks = unique_stocks[:30]
    
    # 3. 查询今日走势（v2 增加多日跟踪：T+1, T+3, T+5最高涨幅）
    results = []
    for s in stocks:
        kline = get_today_kline(s["code"], verify_date)
        if kline:
            # 昨日收盘作为基准
            prev_close = None
            klines = fetch_kline_day(s["code"], days=20)  # 多取一些用于多日跟踪
            if klines:
                for i, k in enumerate(klines):
                    k_date = k.get("date", "").replace("-", "")
                    target = report_date.replace("-", "")
                    if k_date == target:
                        try:
                            prev_close = float(k.get("close", 0))
                        except ValueError:
                            pass
                        break
            
            if prev_close is None or prev_close == 0:
                prev_close = kline["open"]
            
            # T+1
            high_pct = (kline["high"] / prev_close - 1) * 100 if prev_close > 0 else 0
            close_pct = (kline["close"] / prev_close - 1) * 100 if prev_close > 0 else 0
            
            # T+3 / T+5 跟踪（找验证日期后3/5个交易日内的最高价）
            high_3d_pct = high_pct
            high_5d_pct = high_pct
            if klines:
                verify_ts = verify_date.replace("-", "")
                verify_found = False
                count_after = 0
                max_high_3 = kline["high"]
                max_high_5 = kline["high"]
                
                for k in klines:
                    k_date = k.get("date", "").replace("-", "")
                    if k_date == verify_ts:
                        verify_found = True
                        continue
                    if verify_found:
                        count_after += 1
                        try:
                            k_high = float(k.get("high", 0))
                            if count_after <= 3:
                                max_high_3 = max(max_high_3, k_high)
                            if count_after <= 5:
                                max_high_5 = max(max_high_5, k_high)
                        except ValueError:
                            pass
                        if count_after >= 5:
                            break
                
                high_3d_pct = (max_high_3 / prev_close - 1) * 100 if prev_close > 0 else high_pct
                high_5d_pct = (max_high_5 / prev_close - 1) * 100 if prev_close > 0 else high_pct
            
            s.update({
                "prev_close": prev_close,
                "today_open": kline["open"],
                "today_high": kline["high"],
                "today_low": kline["low"],
                "today_close": kline["close"],
                "high_pct": round(high_pct, 2),
                "close_pct": round(close_pct, 2),
                "high_3d_pct": round(high_3d_pct, 2),  # T+3最高涨幅
                "high_5d_pct": round(high_5d_pct, 2),  # T+5最高涨幅
            })
            results.append(s)
    
    if not results:
        return (
            f"---\n\n"
            f"## 📊 信号次日表现统计\n\n"
            f"⚠️ 查询 {len(stocks)} 只股票日K线均失败，请稍后重试\n\n"
            f"---\n"
        )
    
    # 4. 统计（含多日跟踪）
    total = len(results)
    gain_high = sum(1 for r in results if r["high_pct"] > 0)
    gain_close = sum(1 for r in results if r["close_pct"] > 0)
    hit_3pct = sum(1 for r in results if r["high_pct"] >= 3)
    hit_5pct = sum(1 for r in results if r["high_pct"] >= 5)
    avg_high = sum(r["high_pct"] for r in results) / total if total > 0 else 0
    avg_close = sum(r["close_pct"] for r in results) / total if total > 0 else 0
    avg_high_3d = sum(r["high_3d_pct"] for r in results) / total if total > 0 else 0
    avg_high_5d = sum(r["high_5d_pct"] for r in results) / total if total > 0 else 0
    
    # 按次日最高涨幅排序
    results.sort(key=lambda x: x["high_pct"], reverse=True)
    
    # 5. 输出 Markdown
    lines = []
    lines.append("---")
    lines.append("")
    lines.append("## 📊 信号次日表现统计")
    lines.append("")
    lines.append(f"> 统计范围：{report_date}盘前报告推荐标的 → {verify_date}实际走势")
    lines.append("")
    
    # 汇总统计
    lines.append("### 📈 汇总")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|:----|:----:|")
    lines.append(f"| 统计标的数 | {total} |")
    lines.append(f"| 次日冲高胜率(最高>0) | {gain_high}/{total} ({gain_high/total*100:.1f}%) |")
    lines.append(f"| 收盘胜率(收盘>0) | {gain_close}/{total} ({gain_close/total*100:.1f}%) |")
    lines.append(f"| 平均次日最高涨幅 | +{avg_high:.2f}% |")
    lines.append(f"| 平均次日收盘涨幅 | {avg_close:+.2f}% |")
    if track_days >= 3:
        lines.append(f"| 平均T+3最高涨幅 | +{avg_high_3d:.2f}% |")
    if track_days >= 5:
        lines.append(f"| 平均T+5最高涨幅 | +{avg_high_5d:.2f}% |")
    lines.append(f"| 冲高≥3%标的数 | {hit_3pct}/{total} ({hit_3pct/total*100:.1f}%) |")
    lines.append(f"| 冲高≥5%标的数 | {hit_5pct}/{total} ({hit_5pct/total*100:.1f}%) |")
    lines.append("")
    
    # 详细排行（v2 增加T+3/T+5列）
    lines.append("### 📋 个股次日表现排行")
    lines.append("")
    if track_days >= 3:
        lines.append("| 排名 | 代码 | 名称 | 前收 | T+1最高% | T+1收盘% | T+3最高% | T+5最高% | 评分 |")
        lines.append("|:----:|:----:|:----:|:----:|:---------:|:---------:|:---------:|:---------:|:----:|")
    else:
        lines.append("| 排名 | 代码 | 名称 | 前收 | 今开 | 最高 | 最低 | 收盘 | 最高涨幅% | 收盘涨幅% | 评分 |")
        lines.append("|:----:|:----:|:----:|:----:|:----:|:----:|:----:|:----:|:---------:|:---------:|:----:|")
    
    for i, r in enumerate(results, 1):
        hp = r["high_pct"]
        cp = r["close_pct"]
        hp_str = f"+{hp:.2f}" if hp > 0 else f"{hp:.2f}"
        cp_str = f"+{cp:.2f}" if cp > 0 else f"{cp:.2f}"
        
        if hp >= 5:
            score = "🔥"
        elif hp >= 3:
            score = "✅"
        elif hp > 0:
            score = "⬆"
        else:
            score = "❌"
        
        if track_days >= 3:
            h3 = r.get("high_3d_pct", 0)
            h5 = r.get("high_5d_pct", 0)
            h3_str = f"+{h3:.2f}" if h3 > 0 else f"{h3:.2f}"
            h5_str = f"+{h5:.2f}" if h5 > 0 else f"{h5:.2f}"
            lines.append(f"| {i} | {r['code']} | {r['name']} | {r.get('prev_close',0):.2f} | {hp_str} | {cp_str} | {h3_str} | {h5_str} | {score} |")
        else:
            lines.append(f"| {i} | {r['code']} | {r['name']} | {r.get('prev_close',0):.2f} | {r.get('today_open',0):.2f} | {r.get('today_high',0):.2f} | {r.get('today_low',0):.2f} | {r.get('today_close',0):.2f} | {hp_str} | {cp_str} | {score} |")
    
    lines.append("")
    
    # 结论
    lines.append("### 💡 结论")
    lines.append("")
    if avg_high > 2:
        lines.append(f"- 🟢 报告信号质量**优秀**：平均次日最高涨幅 +{avg_high:.2f}%，冲高胜率 {gain_high/total*100:.1f}%")
    elif avg_high > 0:
        lines.append(f"- 🟡 报告信号质量**一般**：平均次日最高涨幅 +{avg_high:.2f}%，有待提升信号精准度")
    else:
        lines.append(f"- 🔴 报告信号质量**偏差**：平均次日最高涨幅 {avg_high:.2f}%，需重新审视选股逻辑")
    
    if hit_5pct > 0:
        lines.append(f"- 🔥 最高涨幅≥5%的标的：{hit_5pct}只，可复盘其共性特征")
    if hit_3pct > 0:
        lines.append(f"- ✅ 最高涨幅≥3%的标的：{hit_3pct}只，具备短线交易价值")
    
    lines.append("")
    lines.append("> ⚠️ 次日最高涨幅为盘中最大值，不代表实际能卖在最高点。实盘中建议结合量能和分时走势分批止盈。")
    lines.append("")
    lines.append("---")
    
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="信号次日表现统计")
    parser.add_argument("--report-date", help="盘前报告日期，默认昨天")
    parser.add_argument("--verify-date", help="验证日期，默认今天")
    parser.add_argument("--track-days", type=int, default=1, choices=[1, 3, 5],
                        help="跟踪天数：1=T+1, 3=T+3, 5=T+5（默认T+1）")
    args = parser.parse_args()
    
    today = datetime.now()
    
    report_date = args.report_date or (today - timedelta(days=1)).strftime("%Y-%m-%d")
    verify_date = args.verify_date or today.strftime("%Y-%m-%d")
    
    result = run_verify(report_date, verify_date, track_days=args.track_days)
    print(result)


if __name__ == "__main__":
    main()
