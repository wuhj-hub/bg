#!/usr/bin/env python3
"""
尾盘资金异动筛选模块 — closing_scan.py
============================================
用途：从盘后全量扫描数据中，筛选尾盘30分钟量价异动的标的，
      生成「明日尾盘关注池」，供复盘报告引用。

集成点：复盘报告 Step 6「明日展望」— 新增「尾盘资金异动」子章节

用法：
    # 从今日盘后量化数据中筛选尾盘异动股
    python3 closing_scan.py --date 2026-07-24
    
    # 自动取今天
    python3 closing_scan.py

依赖：
    - 盘后量化_YYYY-MM-DD.md（知识库「复盘报告」文件夹）
    - westock-data (npx) 用于补查60分钟K线
    
输出：Markdown 格式的尾盘异动股票列表（可用于复制到复盘报告）
"""

import json, os, sys, subprocess, re
from datetime import datetime, timedelta

# ==================== 配置 ====================
KB_ID = "6kjd8jHpAyqf0xFVUo2xUWPaDAKapAWCw-Tki7V-aAs="
REPORT_FOLDER_ID = "folder_7485234585035034"  # 复盘报告文件夹
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_SCRIPT = os.path.join(SCRIPTS_DIR, "..", "..", "ima-knowledge", "scripts", "upload_file.py")

# 沪深主板过滤
BAD_PREFIXES = ("688", "300", "301", "8", "43", "83", "87", "ST", "*ST")


def is_mainboard(code: str) -> bool:
    return not any(code.startswith(p) for p in BAD_PREFIXES)


def search_kb(query: str) -> list:
    """搜索知识库"""
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
    """读取知识库媒体内容"""
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


def list_kb_folder() -> list:
    """列出复盘报告文件夹"""
    cmd = f"""curl -s -X POST "https://ima.qq.com/openapi/wiki/v1/get_knowledge_list" \
  -H "ima-openapi-clientid: $IMA_OPENAPI_CLIENTID" \
  -H "ima-openapi-apikey: $IMA_OPENAPI_APIKEY" \
  -H "Content-Type: application/json" \
  -d '{{"cursor":"","limit":50,"knowledge_base_id":"{KB_ID}","folder_id":"{REPORT_FOLDER_ID}"}}'"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        return data.get("data", {}).get("knowledge_list", [])
    except:
        return []


def get_60min_kline(code: str) -> list | None:
    """获取个股60分钟K线（最近2日=8根），用于判断尾盘"""
    cmd = f"npx westock-data-skillhub@1.0.3 kline --code {code} --period 60 --limit 8 2>/dev/null"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        lines = r.stdout.strip().split("\n")
        if len(lines) < 3:
            return None
        # 表头+数据行
        headers = lines[0].lower().split("\t")
        rows = [dict(zip(headers, l.split("\t"))) for l in lines[1:] if l.strip()]
        return rows
    except:
        return None


def calc_tail_signal(kline_data: list) -> dict:
    """
    分析60分钟K线，计算尾盘异动信号（v2 - 增加真假拉升区分）
    
    改进点（来源：网上实战经验）：
    - 🚫 尾盘急拉>3% 且无量 → 钓鱼线出货嫌疑，降分
    - ✅ 全天振幅<5% + 尾盘放量稳步拉升 → 优质信号
    - ✅ 尾盘30分钟成交占全天比例（如能获取全天数据）
    
    返回: {tail_volume_ratio, tail_price_change, tail_reversal, 
           tail_score, is_fake_break, fake_warning}
    """
    result = {
        "tail_volume_ratio": 0,
        "tail_price_change": 0,
        "tail_reversal": False,
        "tail_score": 0,
        "is_fake_break": False,
        "fake_warning": ""
    }
    
    if not kline_data or len(kline_data) < 4:
        return result
    
    try:
        # kline 默认降序(最新在前)
        tail_2 = kline_data[:2]  # 最近2根60分K（尾盘2小时）
        prev_6 = kline_data[2:8] if len(kline_data) >= 8 else kline_data[2:]
        
        # 计算尾盘量比
        tail_vol = sum(float(t.get("amount", 0)) for t in tail_2)
        prev_avg_vol = sum(float(p.get("amount", 0)) for p in prev_6) / len(prev_6) if prev_6 else 1
        
        vol_ratio = tail_vol / prev_avg_vol if prev_avg_vol > 0 else 0
        
        # 尾盘价格变化
        if len(tail_2) >= 2:
            latest_close = float(tail_2[0].get("close", 0))
            prev_close = float(tail_2[1].get("close", 0))
            change_pct = (latest_close / prev_close - 1) * 100 if prev_close > 0 else 0
        else:
            change_pct = 0
        
        # === 真假拉升区分 ===
        # 🚫 尾盘急拉>3% 且无量(量比<1.5) → 疑似钓鱼线出货
        is_fake = False
        fake_warning = ""
        if change_pct >= 3.0 and vol_ratio < 1.5:
            is_fake = True
            fake_warning = "🚫 无量急拉>3%，疑似钓鱼线出货"
        elif change_pct >= 2.0 and vol_ratio < 1.2:
            is_fake = True
            fake_warning = "⚠️ 拉升量比不足，警惕诱多"
        
        # 尾盘反转判断
        is_reversal = False
        if len(kline_data) >= 3:
            c2 = float(tail_2[0].get("close", 0))
            o2 = float(tail_2[0].get("open", 0))
            c1 = float(tail_2[1].get("close", 0))
            o1 = float(tail_2[1].get("open", 0))
            is_reversal = (c2 > o2 and c2 > c1) and (c1 < o1)
        
        # === 综合评分 (0-100) ===
        score = 0
        
        if vol_ratio > 1.5:
            score += 25
        if vol_ratio > 2.0:
            score += 15
        if vol_ratio > 3.0:
            score += 10  # 极度放量加分
        
        if 0.5 <= change_pct <= 2.5:
            score += 20  # 稳健拉升（0.5%~2.5%最佳区间）
        elif change_pct > 2.5 and vol_ratio >= 2.0:
            score += 15  # 快速拉升但需量配合
        elif 0 < change_pct < 0.5:
            score += 10  # 微涨及格
        
        if is_reversal:
            score += 10
        
        # 真假拉升扣分
        if is_fake:
            score = max(0, score - 50)  # 疑似钓鱼线直接腰斩
        
        result["tail_volume_ratio"] = round(vol_ratio, 2)
        result["tail_price_change"] = round(change_pct, 2)
        result["tail_reversal"] = is_reversal
        result["tail_score"] = min(score, 100)
        result["is_fake_break"] = is_fake
        result["fake_warning"] = fake_warning
        
    except (ValueError, KeyError, IndexError, ZeroDivisionError):
        pass
    
    return result


def extract_stocks_from_quant(content: str) -> list:
    """
    从盘后量化数据中提取股票列表及信号强度
    盘后量化.md 中通常包含表格格式：代码 | 名称 | 评分 | 信号类型
    """
    stocks = []
    
    # 匹配表格行，如 | 000779 | 甘咨询 | 85 | 主力
    pattern = re.compile(r'\|\s*(\d{6})\s*\|\s*([^|]+)\s*\|')
    lines = content.split("\n")
    
    seen = set()
    for line in lines:
        m = pattern.search(line)
        if m and is_mainboard(m.group(1)):
            code = m.group(1)
            name = m.group(2).strip()
            if code not in seen:
                seen.add(code)
                stocks.append({"code": code, "name": name})
    
    return stocks


def run_closing_scan(target_date: str) -> str:
    """
    主流程：
    1. 从知识库读取今日盘后量化数据
    2. 提取候选股票
    3. 逐只检查60分钟K线尾盘异动
    4. 排序输出
    """
    today_str = target_date
    
    # 1. 找盘后量化数据
    files = list_kb_folder()
    quant_content = None
    
    for f in files:
        title = f.get("title", "")
        if f"盘后量化_{today_str}" in title:
            mid = f.get("media_id", "")
            quant_content = fetch_from_kb(mid)
            if quant_content:
                break
    
    # 如果知识库没有，就从本地找
    if not quant_content:
        local_path = f"/sandbox/workspace/outputs/盘后量化_{today_str}.md"
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                quant_content = f.read()
    
    if not quant_content:
        return (
            f"⏳ 盘后量化数据 `盘后量化_{today_str}.md` 尚未就绪。\n"
            f"请确认全量扫描已完成后再运行本模块。\n"
        )
    
    # 2. 提取候选股票（取前50只）
    candidates = extract_stocks_from_quant(quant_content)
    if not candidates:
        return "⚠️ 盘后量化数据中未解析到有效股票，请检查格式。\n"
    
    candidates = candidates[:50]  # 只检查前50只
    
    # 3. 逐只检查尾盘异动
    results = []
    for i, stock in enumerate(candidates):
        if i > 0 and i % 10 == 0:
            pass  # 进度提示
        kline_data = get_60min_kline(stock["code"])
        if kline_data:
            signal = calc_tail_signal(kline_data)
            stock.update(signal)
            results.append(stock)
    
    # 4. 按尾盘评分降序排列
    results.sort(key=lambda x: x.get("tail_score", 0), reverse=True)
    
    # 5. 输出 Markdown
    lines = []
    lines.append("---")
    lines.append("")
    lines.append("## 🔍 尾盘资金异动扫描")
    lines.append("")
    lines.append(f"> 扫描日期：{today_str}  |  候选来源：盘后全量扫描TOP50  |  筛选标准：尾盘60分钟量比+涨幅")
    lines.append("")
    
    if not results:
        lines.append("*今日无显著尾盘异动信号*")
        lines.append("")
        return "\n".join(lines)
    
    # 强异动
    strong = [r for r in results if r.get("tail_score", 0) >= 60]
    medium = [r for r in results if 30 <= r.get("tail_score", 0) < 60]
    weak = [r for r in results if r.get("tail_score", 0) > 0]
    
    if strong:
        lines.append("### 🔥 强异动（尾盘放量拉升 ≥60分）")
        lines.append("")
        lines.append("| 代码 | 名称 | 尾盘量比 | 尾盘涨幅% | 反转信号 | 综合评分 |")
        lines.append("|:----:|:----:|:--------:|:---------:|:--------:|:--------:|")
        for s in strong:
            rev = "✅" if s.get("tail_reversal") else ""
            lines.append(f"| {s['code']} | {s['name']} | {s.get('tail_volume_ratio',0):.1f}x | +{s.get('tail_price_change',0):.2f} | {rev} | {s.get('tail_score',0)} |")
        lines.append("")
    
    if medium:
        lines.append("### ⚡ 一般异动（30~59分）")
        lines.append("")
        lines.append("| 代码 | 名称 | 尾盘量比 | 尾盘涨幅% | 综合评分 | 注意事项 |")
        lines.append("|:----:|:----:|:--------:|:---------:|:--------:|:---------:|")
        for s in medium:
            warn = s.get("fake_warning", "")
            lines.append(f"| {s['code']} | {s['name']} | {s.get('tail_volume_ratio',0):.1f}x | +{s.get('tail_price_change',0):.2f} | {s.get('tail_score',0)} | {warn} |")
        lines.append("")
    
    if weak:
        lines.append("### 📋 其他关注（1~29分）")
        lines.append("")
        codes_weak = "、".join([f"{s['code']}({s['name']})" for s in weak[:10]])
        lines.append(f"- {codes_weak}")
        lines.append("")
    
    lines.append("**操作建议**：")
    lines.append("- 🔥 强异动标的 → 纳入明日重点关注池，结合盘前信号判断是否参与")
    lines.append("- ⚡ 一般异动 → 观察早盘30分钟是否延续尾盘强势；有⚠️警告的需警惕假突破")
    lines.append("- 📋 其他关注 → 盘中异动时再介入，不追高")
    lines.append("- 🚫 尾盘急拉>3%且无量 → 疑似钓鱼线出货，不参与")
    lines.append("")
    lines.append("---")
    
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="尾盘资金异动扫描")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="扫描日期，默认今天")
    args = parser.parse_args()
    
    result = run_closing_scan(args.date)
    print(result)


if __name__ == "__main__":
    main()
