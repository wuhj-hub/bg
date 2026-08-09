#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_selfcheck.py —— 报告逻辑验证环节 v1.0
============================================
对生成的盘前/复盘报告做关键字段自检，防止历史错误复发：
  1. 板块方向含"BK-HY"(取错列) → 报警
  2. 指数数据日期错位（今收≠当日） → 报警
  3. 三系统信号全"—"(字段不匹配) → 报警
  4. 盘前预判JSON关键字段缺失/格式错 → 报警
  5. 复盘③.5股池章节缺失 → 警告
自检失败 → 打印问题清单 + PushPlus推送报警（可选）

用法:
  python3 report_selfcheck.py --premarket premarket_judgment_latest.json
  python3 report_selfcheck.py --review outputs/复盘报告_2026-08-05.md
  python3 report_selfcheck.py --both --today 2026-08-05
"""
import argparse, json, os, re, sys, urllib.request, urllib.parse

def push_alert(title, issues):
    """PushPlus推送报警"""
    token = os.environ.get("PUSH_TOKEN", "")
    if not token:
        return
    try:
        content = "⚠️ 报告逻辑自检发现异常：\n\n" + "\n".join(f"- {i}" for i in issues)
        body = urllib.parse.urlencode({"token": token, "title": title,
                                       "content": content[:3800], "template": "txt"}).encode()
        req = urllib.request.Request("https://pushplus.plus/send", data=body)
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        print("[alert] 已推送报警")
    except Exception as e:
        print(f"[alert] 推送失败: {e}")

def check_premarket(path, today=""):
    """检查盘前预判JSON：sectors含BK-HY / 三系统全空 / key_levels格式 / date匹配"""
    issues = []
    if not os.path.exists(path):
        return [f"盘前JSON不存在: {path}"]
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return [f"盘前JSON解析失败: {e}"]
    # 1. sectors含板块类型代码
    sectors = d.get("sectors", "")
    if "BK-" in sectors or ("、" in sectors and len(sectors) < 4):
        issues.append(f"板块方向异常(疑似取错列): {sectors}")
    elif not sectors:
        issues.append("板块方向为空")
    # 2. 三系统全空
    sys3 = [d.get("fish_temp"), d.get("beast_score"), d.get("shuangxian")]
    if all(s in (None, "", "—") for s in sys3):
        issues.append("三系统信号全空(quant_results_latest缺失或字段不匹配)")
    # 3. key_levels格式
    kl = d.get("key_levels", "")
    if kl and not re.match(r"^(支撑|压力)\d{3,5}([、，]?(支撑|压力)\d{3,5})*", str(kl)):
        issues.append(f"关键位格式异常: {kl}")
    # 4. date匹配
    dt = str(d.get("date", ""))
    if today and dt and dt != today:
        issues.append(f"JSON日期{dt}≠今日{today}")
    return issues

def check_review(path, today=""):
    """检查复盘报告md：今收日期错位 / BK-HY / 三系统全空 / ③.5缺失"""
    issues = []
    if not os.path.exists(path):
        return [f"复盘报告不存在: {path}"]
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        return [f"复盘报告读取失败: {e}"]
    # 1. 板块方向含BK-HY
    if "BK-" in text:
        issues.append("报告含板块类型代码'BK-HY'(预判验证取错列)")
    # 2. 三系统全空
    if re.search(r"猛兽安全评分\|\s*—", text) and re.search(r"双弦\|\s*温度—", text):
        issues.append("三系统信号缺失(猛兽/双弦为—)")
    # 3. ③.5股池章节（今日应有）
    if today and "股池三阶漏斗状态" not in text:
        issues.append(f"③.5股池三阶漏斗状态章节缺失（今日应引用股池跟踪报告）")
    # 3.5 关键增强章节缺失（风格轴/宽度/主力信号——有数据应显示，缺失多为上游未跑）
    if "市场风格轴" not in text:
        issues.append("市场风格轴章节缺失（market_style_latest.json 未产出）")
    if "市场宽度" not in text:
        issues.append("市场宽度章节缺失（market_width_latest.json 未产出）")
    if "主力信号专表" not in text:
        issues.append("主力信号专表章节缺失（panhou_lianghua.csv 未产出）")
    # 4. 指数错位检测：今收列应为今日K线（无法直接验证数值，检查昨收/今收是否相同）
    m = re.findall(r"\| 上证指数 \| ([\d.]+) \| ([\d.]+) \|", text)
    if m and m[0][0] == m[0][1]:
        issues.append(f"上证指数昨收=今收({m[0][0]})，疑似数据未更新或错位")
    return issues

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--premarket", default="")
    ap.add_argument("--review", default="")
    ap.add_argument("--both", action="store_true")
    ap.add_argument("--today", default="")
    ap.add_argument("--alert", action="store_true", help="异常时PushPlus推送")
    a = ap.parse_args()
    today = a.today or os.environ.get("REPORT_DATE", "")
    all_issues = []
    if a.premarket:
        for p in a.premarket.split(","):
            if os.path.exists(p):
                all_issues += [f"[盘前 {os.path.basename(p)}] {i}" for i in check_premarket(p, today)]
    if a.review:
        for p in a.review.split(","):
            if os.path.exists(p):
                all_issues += [f"[复盘 {os.path.basename(p)}] {i}" for i in check_review(p, today)]
    if not all_issues:
        print("✅ 报告逻辑自检通过")
        return 0
    print("⚠️ 报告逻辑自检发现问题:")
    for i in all_issues:
        print(f"  - {i}")
    if a.alert:
        push_alert("⚠️ 报告逻辑自检异常", all_issues)
    return 1

if __name__ == "__main__":
    sys.exit(main())
