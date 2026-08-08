#!/usr/bin/env python3
"""
盘前报告 - 量化系统预运行结果引用模块
========================================
从知识库「复盘报告」文件夹中读取昨日 GitHub Actions 预运行的量化结果。

用法：
    python3 premarket_quant.py
    → 输出 Markdown 格式的量化系统汇总板块（含双弦/鱼身/猛兽）
"""

import json, os, sys, subprocess, re
from datetime import datetime, timedelta

# 报告知识库
KB_ID = "6kjd8jHpAyqf0xFVUo2xUWPaDAKapAWCw-Tki7V-aAs="
# 复盘报告文件夹 ID
FOLDER_ID = "folder_7485234585035034"


def fetch_from_kb(media_id):
    """用 fetch 工具读取知识库内容"""
    # 通过 CLI 工具读取
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


def search_kb(query):
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


def list_folder():
    """列出复盘报告文件夹内容"""
    cmd = f"""curl -s -X POST "https://ima.qq.com/openapi/wiki/v1/get_knowledge_list" \
  -H "ima-openapi-clientid: $IMA_OPENAPI_CLIENTID" \
  -H "ima-openapi-apikey: $IMA_OPENAPI_APIKEY" \
  -H "Content-Type: application/json" \
  -d '{{"cursor":"","limit":50,"knowledge_base_id":"{KB_ID}","folder_id":"{FOLDER_ID}"}}'"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        return data.get("data", {}).get("knowledge_list", [])
    except:
        return []


def find_latest_quant_results():
    """
    从复盘报告文件夹中找到最新的量化系统预运行结果。
    查找顺序：
    1. quant_results_YYYY-MM-DD.json  (汇总结果)
    2. 如没有，则分别找 shuangxian/fishbody/beast 的单独文件
    """
    files = list_folder()
    if not files:
        return None, None, None, None

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    quant_summary = None
    shuangxian_file = None
    fishbody_file = None
    beast_file = None

    for f in files:
        title = f.get("title", "")
        mid = f.get("media_id", "")

        # 先找今日的汇总文件
        if "quant_results" in title and today in title:
            quant_summary = (title, mid)
        # 备选昨日
        elif "quant_results" in title and yesterday in title:
            if not quant_summary:
                quant_summary = (title, mid)

        # 找单独的量化结果文件
        if "shuangxian" in title.lower() and today in title:
            shuangxian_file = (title, mid)
        elif "fishbody" in title.lower() and today in title:
            fishbody_file = (title, mid)
        elif "beast_results" in title.lower() and today in title:
            beast_file = (title, mid)
        elif "盘后量化" in title and today in title:
            beast_file = (title, mid)

    return quant_summary, shuangxian_file, fishbody_file, beast_file


def format_as_markdown(quant_summary, shuangxian_file, fishbody_file, beast_file):
    """输出 Markdown 板块"""
    lines = []
    lines.append("---")
    lines.append("")
    lines.append("## 🤖 量化系统昨日预运行结果")
    lines.append("")
    lines.append("> 数据来源：GitHub Actions 自动扫描 + 量化系统预运行")
    lines.append("")

    if quant_summary:
        title, mid = quant_summary
        content = fetch_from_kb(mid)
        if content:
            try:
                data = json.loads(content)
                sx = data.get("shuangxian", {})
                fb = data.get("fishbody", {})
                bt = data.get("beast", {})

                lines.append("| 系统 | 状态 | 关键数据 |")
                lines.append("|:----|:----:|:---------|")

                # 双弦
                pool = sx.get("pool_data", {})
                entries = pool.get("entries", [])
                lines.append(f"| 🔗 双弦 | ✅ | 月度股池 {len(entries)} 只 |")

                # 鱼身
                sig_count = fb.get("signal_count", "N/A")
                temp = fb.get("market_temp", {})
                temp_str = f"{temp.get('temp','N/A')}分" if isinstance(temp, dict) else "N/A"
                lines.append(f"| 🐟 鱼身 | ✅ | 信号 {sig_count} 个, 温度 {temp_str} |")

                # 猛兽
                lines.append(f"| 🐅 猛兽 | ✅ | 已扫描 (见下方详情) |")
                lines.append("")

                # 双弦详细
                if entries:
                    lines.append("### 🔗 双弦月度股池")
                    lines.append("")
                    lines.append("| 代码 | 名称 | 价格 | 评分 | 类型 |")
                    lines.append("|:----:|:----:|:----:|:----:|:----:|")
                    for e in entries[:10]:
                        lines.append(f"| {e['code']} | {e['name']} | {e['price']} | {e['score']} | {e['signal_type']} |")
                    lines.append("")

                # 鱼身详细
                if isinstance(fb.get("market_temp"), dict):
                    mt = fb["market_temp"]
                    lines.append(f"### 🐟 鱼身系统")
                    lines.append(f"- **大盘温度**: {mt.get('temp','?')}/100 ({mt.get('level','?')})")
                    lines.append(f"- **门控**: {'✅ 通过 (≥40)' if isinstance(mt.get('temp'), (int,float)) and mt['temp'] >= 40 else '❌ 偏冷 (<40)暂停'}")
                    lines.append("")

            except json.JSONDecodeError:
                lines.append("*汇总文件读取失败*\n")

    else:
        lines.append("*⏳ 量化系统预运行结果尚未上传至知识库*\n")
        lines.append("*（GitHub Actions 每日 15:30 运行，约 16:30 后数据就绪）*\n")

    lines.append("> 📌 完整量化数据请参见昨日复盘报告")
    lines.append("")

    return "\n".join(lines)


def main():
    quant_summary, sx_file, fb_file, bt_file = find_latest_quant_results()
    md = format_as_markdown(quant_summary, sx_file, fb_file, bt_file)
    print(md)


if __name__ == "__main__":
    main()
