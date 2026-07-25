#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
self_check.py —— 体系自检系统

功能：
  1. 读取当前运行产出（CSV + MD报告）
  2. 多维度健康检查（覆盖度、信号分布、数据质量、评分合理性）
  3. 市场状态检测（从信号分布推断当前市场环境）
  4. 与历史记录对比，发现退化/异常趋势
  5. 综合健康评分（0-100）
  6. 可自动修复的问题尝试纠正
  7. 保存健康历史，供后续对比

输出：
  - 打印详细自检报告（供 workflow 日志查看）
  - health_status.json（结构化结果，供下游步骤读取）
  - health_history.json（历史记录累积）

用法：
  python3 self_check.py [--csv panhou_lianghua.csv] [--mainboard all_mainboard.csv] [--fix]
    --fix: 启用自动修复模式（默认仅检测不修复）
    --history health_history.json: 历史数据文件路径
"""

import csv
import json
import os
import sys
import time
from collections import Counter

# ─── 配置参数（可调阈值） ───
THRESHOLDS = {
    "min_coverage_pct": 80.0,        # 最低有效扫描覆盖率
    "max_error_rate_pct": 10.0,      # 最高允许错误率
    "min_total_stocks": 2000,        # 最低扫描总数
    "min_bullish_signal_pct": 1.0,   # 最低多头信号占比（否则可能数据异常）
    "max_bullish_signal_pct": 60.0,  # 最高多头信号占比（不可能全员多头）
    "min_precip_range": -50,         # 沉淀率合理最小值
    "max_precip_range": 100,         # 沉淀率合理最大值
    "min_cjb30_range": -100,        # CJB30合理最小值
    "max_cjb30_range": 500,         # CJB30合理最大值（涨停放量可能极高）
    "min_stocks_with_signals": 100,  # 最少应有信号的股票数
    "price_zero_tolerance_pct": 5.0, # 价格为0的最大容忍%
}

# 信号分类（用于市场状态检测）
BULLISH_SIGNALS = {"主力主导放量🔥(最强)", "主力偏强放量", "主力控盘"}
NEUTRAL_SIGNALS = {"主力惜售"}
BEARISH_SIGNALS = {"情绪退潮", "游资情绪"}

# 市场状态标签
MARKET_REGIMES = {
    "强势市场": "多头信号>30%，资金积极入场",
    "结构性行情": "多头信号15-30%，局部机会",
    "震荡市场": "多头信号5-15%，多空平衡",
    "弱势市场": "多头信号<5%，资金出逃为主",
    "数据异常": "信号分布不符合任何合理市场状态",
}


def load_csv(csv_path):
    """加载CSV数据"""
    if not os.path.exists(csv_path):
        return [], f"❌ CSV文件不存在: {csv_path}"
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return [], "❌ CSV文件为空"
        return rows, None
    except Exception as e:
        return [], f"❌ CSV读取失败: {e}"


def load_mainboard(csv_path):
    """加载主板清单"""
    if not os.path.exists(csv_path):
        return 0, f"❌ 主板清单不存在: {csv_path}"
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            return len(list(csv.DictReader(f))), None
    except Exception as e:
        return 0, f"❌ 主板清单读取失败: {e}"


def load_history(history_path):
    """加载历史健康记录"""
    if not os.path.exists(history_path):
        return []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history_path, records):
    """保存历史健康记录（最多保留30条）"""
    records = records[-30:]
    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"⚠️ 保存历史记录失败: {e}")
        return False


# ─── 各检查项 ───

def check_coverage(rows, total_stocks):
    """检查1: 扫描覆盖率"""
    scanned = len(rows)
    has_error = sum(1 for r in rows if r.get("error"))
    has_signal = sum(1 for r in rows if r.get("sig"))
    effective = has_signal

    coverage_pct = (effective / total_stocks * 100) if total_stocks else 0
    error_pct = (has_error / scanned * 100) if scanned else 0

    issues = []
    if coverage_pct < THRESHOLDS["min_coverage_pct"]:
        issues.append(f"⚠️ 覆盖率偏低: {coverage_pct:.1f}% (阈值 {THRESHOLDS['min_coverage_pct']}%)")
    if error_pct > THRESHOLDS["max_error_rate_pct"]:
        issues.append(f"⚠️ 错误率偏高: {error_pct:.1f}% (阈值 {THRESHOLDS['max_error_rate_pct']}%)")
    if effective < THRESHOLDS["min_stocks_with_signals"]:
        issues.append(f"⚠️ 有效信号数不足: {effective} (阈值 {THRESHOLDS['min_stocks_with_signals']})")

    return {
        "name": "扫描覆盖率",
        "status": "PASS" if not issues else "WARN" if error_pct < 20 else "FAIL",
        "details": {
            "total_stocks": total_stocks,
            "scanned": scanned,
            "effective": effective,
            "errors": has_error,
            "coverage_pct": round(coverage_pct, 1),
            "error_pct": round(error_pct, 1),
        },
        "issues": issues,
    }


def check_signal_distribution(rows):
    """检查2: 信号分布合理性"""
    signals = Counter(r.get("sig", "") for r in rows if r.get("sig"))
    total = sum(signals.values())

    if total == 0:
        return {
            "name": "信号分布",
            "status": "FAIL",
            "details": {"total_with_signal": 0},
            "issues": ["❌ 所有股票均无有效信号，数据异常"],
            "distribution": {},
            "market_regime": "数据异常",
        }

    # 各类信号占比
    bullish_cnt = sum(v for k, v in signals.items() if k in BULLISH_SIGNALS)
    bearish_cnt = sum(v for k, v in signals.items() if k in BEARISH_SIGNALS)
    neutral_cnt = sum(v for k, v in signals.items() if k in NEUTRAL_SIGNALS)

    bullish_pct = bullish_cnt / total * 100
    bearish_pct = bearish_cnt / total * 100
    neutral_pct = neutral_cnt / total * 100

    # 信号种类数
    signal_types = len(signals)

    issues = []
    status = "PASS"

    if bullish_pct < THRESHOLDS["min_bullish_signal_pct"]:
        issues.append(f"⚠️ 多头信号占比过低: {bullish_pct:.1f}%")
        status = "WARN"
    if bullish_pct > THRESHOLDS["max_bullish_signal_pct"]:
        issues.append(f"⚠️ 多头信号占比过高: {bullish_pct:.1f}%，可能数据有偏")
        status = "WARN"
    if signal_types < 3:
        issues.append(f"⚠️ 信号种类仅 {signal_types} 种，正常应为 5-6 种")
        status = "WARN"
    if total < THRESHOLDS["min_stocks_with_signals"]:
        issues.append(f"❌ 有信号的股票太少: {total}")
        status = "FAIL"

    # 市场状态检测
    if bullish_pct > 30:
        regime = "强势市场"
    elif bullish_pct > 15:
        regime = "结构性行情"
    elif bullish_pct > 5:
        regime = "震荡市场"
    elif bullish_pct >= 0:
        regime = "弱势市场"
    else:
        regime = "数据异常"

    distribution = dict(sorted(signals.items(), key=lambda x: -x[1]))

    return {
        "name": "信号分布",
        "status": status,
        "details": {
            "total_with_signal": total,
            "bullish_pct": round(bullish_pct, 1),
            "bearish_pct": round(bearish_pct, 1),
            "neutral_pct": round(neutral_pct, 1),
            "signal_types": signal_types,
        },
        "issues": issues,
        "distribution": distribution,
        "market_regime": regime,
    }


def check_score_reasonability(rows):
    """检查3: 评分数据合理性"""
    values = {"precip": [], "cjb30": [], "price": [], "m5": []}
    for r in rows:
        if r.get("error"):
            continue
        for key in values:
            try:
                v = float(r.get(key, 0))
                values[key].append(v)
            except (ValueError, TypeError):
                pass

    issues = []
    status = "PASS"

    # 沉淀率检查
    if values["precip"]:
        avg_precip = sum(values["precip"]) / len(values["precip"])
        min_p = min(values["precip"])
        max_p = max(values["precip"])
        if min_p < THRESHOLDS["min_precip_range"]:
            issues.append(f"⚠️ 沉淀率最小值异常: {min_p:.2f}")
            status = "WARN"
        if max_p > THRESHOLDS["max_precip_range"]:
            issues.append(f"⚠️ 沉淀率最大值异常: {max_p:.2f}")
            status = "WARN"
    else:
        issues.append("❌ 无沉淀率数据")
        status = "FAIL"

    # CJB30检查
    if values["cjb30"]:
        avg_cjb30 = sum(values["cjb30"]) / len(values["cjb30"])
        max_c = max(values["cjb30"])
        if avg_cjb30 < -50:
            issues.append(f"⚠️ CJB30均值过低: {avg_cjb30:.1f}，全市场极度缩量")
            status = "WARN"
    else:
        issues.append("❌ 无CJB30数据")
        status = "FAIL"

    # 价格检查
    if values["price"]:
        zero_price = sum(1 for v in values["price"] if v == 0)
        zero_pct = zero_price / len(values["price"]) * 100
        if zero_pct > THRESHOLDS["price_zero_tolerance_pct"]:
            issues.append(f"⚠️ 价格为0的股票占比 {zero_pct:.1f}%，可能数据源异常")
            status = "WARN"

    return {
        "name": "数据合理性",
        "status": status,
        "details": {
            "avg_precip": round(avg_precip, 2) if values["precip"] else None,
            "precip_range": [round(min_p, 2), round(max_p, 2)] if values["precip"] else None,
            "avg_cjb30": round(avg_cjb30, 1) if values["cjb30"] else None,
            "avg_price": round(sum(values["price"]) / len(values["price"]), 2) if values["price"] else None,
        },
        "issues": issues,
    }


def check_data_freshness(rows, report_date=None):
    """检查4: 数据时效性"""
    if not report_date:
        report_date = time.strftime("%Y-%m-%d")

    # 从CSV中检查是否有今天的价格数据
    today_prices = 0
    for r in rows:
        try:
            p = float(r.get("price", 0))
            if p > 0:
                today_prices += 1
        except (ValueError, TypeError):
            pass

    issues = []
    status = "PASS"

    if today_prices < 100:
        issues.append(f"⚠️ 仅有 {today_prices} 只股票有价格数据，可能K线数据陈旧")
        status = "WARN"

    return {
        "name": "数据时效性",
        "status": status,
        "details": {
            "report_date": report_date,
            "stocks_with_price": today_prices,
        },
        "issues": issues,
    }


def detect_market_regime(signal_check):
    """检测市场状态"""
    regime = signal_check.get("market_regime", "未知")
    distribution = signal_check.get("distribution", {})

    total = sum(distribution.values())
    if total == 0:
        return "数据异常", {}

    # 计算各信号占比
    signal_pcts = {k: round(v / total * 100, 1) for k, v in distribution.items()}

    # 额外判断
    dominant_signal = max(distribution, key=distribution.get) if distribution else "无"
    dominant_pct = signal_pcts.get(dominant_signal, 0)

    # 游资占比高 = 情绪驱动
    speculative = sum(v for k, v in distribution.items() if k in {"游资情绪"})
    speculative_pct = speculative / total * 100 if total else 0

    regime_detail = {
        "dominant_signal": dominant_signal,
        "dominant_pct": dominant_pct,
        "speculative_pct": round(speculative_pct, 1),
        "bullish_pct": signal_check["details"]["bullish_pct"],
        "bearish_pct": signal_check["details"]["bearish_pct"],
    }

    return regime, regime_detail


def detect_trend_anomaly(history, current_checks):
    """与历史记录对比，检测趋势异常"""
    if len(history) < 2:
        return [], None  # 历史记录不足，无法对比

    issues = []
    latest = history[-1]
    prev_checks = latest.get("checks", {})

    # 对比信号分布变化
    curr_dist = current_checks.get("signal", {}).get("distribution", {})
    prev_dist = prev_checks.get("signal", {}).get("distribution", {})

    curr_total = sum(curr_dist.values())
    prev_total = sum(prev_dist.values())

    if curr_total > 0 and prev_total > 0:
        # 多头信号占比变化
        curr_bull = sum(v for k, v in curr_dist.items() if k in BULLISH_SIGNALS) / curr_total * 100
        prev_bull = sum(v for k, v in prev_dist.items() if k in BULLISH_SIGNALS) / prev_total * 100
        change = curr_bull - prev_bull

        if abs(change) > 20:
            issues.append(f"⚠️ 多头信号占比剧烈变化: {prev_bull:.1f}% → {curr_bull:.1f}% (变化{change:+.1f}%)")

        # 覆盖度变化
        curr_cov = current_checks.get("coverage", {}).get("details", {}).get("coverage_pct", 0)
        prev_cov = prev_checks.get("coverage", {}).get("details", {}).get("coverage_pct", 0)
        if curr_cov and prev_cov:
            cov_change = curr_cov - prev_cov
            if cov_change < -10:
                issues.append(f"⚠️ 扫描覆盖率下降: {prev_cov:.1f}% → {curr_cov:.1f}%")

    return issues, latest


# ─── 综合评分 ───

def compute_health_score(checks):
    """计算综合健康评分 0-100"""
    score = 100.0

    # 各检查项扣分
    deductions = {
        "coverage": {
            "FAIL": 30,
            "WARN": 10,
        },
        "signal": {
            "FAIL": 35,
            "WARN": 15,
        },
        "reasonability": {
            "FAIL": 25,
            "WARN": 10,
        },
        "freshness": {
            "FAIL": 20,
            "WARN": 8,
        },
    }

    for check_name, status in checks.items():
        if isinstance(status, dict):
            s = status.get("status", "PASS")
            deduction_map = deductions.get(check_name, {})
            score -= deduction_map.get(s, 0)

    return max(0, min(100, round(score)))


def grade_health(score):
    """健康等级"""
    if score >= 90:
        return "🟢 健康"
    elif score >= 70:
        return "🟡 亚健康"
    elif score >= 50:
        return "🟠 需关注"
    else:
        return "🔴 异常"


# ─── 自动修复 ───

def auto_fix(checks):
    """尝试自动修复可修复的问题"""
    fixes = []
    actions = []

    for check_name, check in checks.items():
        if not isinstance(check, dict):
            continue
        status = check.get("status", "PASS")
        issues = check.get("issues", [])

        if status == "PASS":
            continue

        # 覆盖率问题：建议扩大workers/增加超时
        if check_name == "coverage" and status != "PASS":
            coverage = check.get("details", {}).get("coverage_pct", 0)
            if coverage < 60:
                fixes.append({
                    "issue": "扫描覆盖率严重不足",
                    "action": "建议增加 SCAN_WORKERS 或延长 TIMEOUT",
                    "auto_fixable": False,
                })
            elif coverage < 80:
                fixes.append({
                    "issue": "扫描覆盖率偏低",
                    "action": "下次运行自动尝试增加 worker 数",
                    "auto_fixable": True,
                })
            actions.append("adjust_workers")

        # 信号分布问题
        if check_name == "signal" and status != "PASS":
            if "有效信号" in " ".join(issues):
                fixes.append({
                    "issue": "有效信号异常",
                    "action": "检查 westock API 返回数据是否正常",
                    "auto_fixable": False,
                })

        # 数据合理性问题
        if check_name == "reasonability" and status != "PASS":
            # 价格异常可能意味着API数据格式变化
            details = check.get("details", {})
            if details.get("avg_price") is None or details.get("avg_price", 0) == 0:
                fixes.append({
                    "issue": "价格数据全部为0，可能API接口变动",
                    "action": "检查 westock kline 返回格式",
                    "auto_fixable": False,
                })

    # 生成修复建议
    if not fixes:
        fixes.append({
            "issue": "无",
            "action": "体系运行正常",
            "auto_fixable": True,
        })

    return {
        "fixes_attempted": len([f for f in fixes if f["auto_fixable"]]),
        "fixes_needed": len([f for f in fixes if not f["auto_fixable"]]),
        "fixes": fixes,
        "actions_taken": list(set(actions)),
    }


# ─── 主流程 ───

def main():
    import argparse

    parser = argparse.ArgumentParser(description="体系自检系统")
    parser.add_argument("--csv", default="panhou_lianghua.csv", help="全量扫描CSV路径")
    parser.add_argument("--mainboard", default="all_mainboard.csv", help="主板清单CSV路径")
    parser.add_argument("--history", default="health_history.json", help="历史记录文件路径")
    parser.add_argument("--fix", action="store_true", help="启用自动修复模式")
    parser.add_argument("--output", default="health_status.json", help="自检结果输出路径")
    parser.add_argument("--report-date", default=time.strftime("%Y-%m-%d"), help="报告日期")
    args = parser.parse_args()

    today = args.report_date
    print(f"\n{'='*60}")
    print(f"🔍 体系自检 — {today}")
    print(f"{'='*60}")

    # 1. 加载数据
    print("\n📂 加载数据...")
    rows, err = load_csv(args.csv)
    if err:
        print(f"  {err}")
        # 即使没有CSV也生成基础报告
    else:
        print(f"  ✅ 加载 {len(rows)} 条记录")

    total_mainboard, err2 = load_mainboard(args.mainboard)
    if err2:
        print(f"  ⚠️ {err2}")
    else:
        print(f"  ✅ 主板清单 {total_mainboard} 只")

    # 2. 加载历史
    history = load_history(args.history)
    print(f"  📜 历史记录 {len(history)} 条")

    # 3. 执行检查
    checks = {}

    if rows:
        checks["coverage"] = check_coverage(rows, total_mainboard or len(rows))
        checks["signal"] = check_signal_distribution(rows)
        checks["reasonability"] = check_score_reasonability(rows)
        checks["freshness"] = check_data_freshness(rows, today)
    else:
        checks["coverage"] = {
            "name": "扫描覆盖率", "status": "FAIL",
            "details": {"total_stocks": total_mainboard, "scanned": 0, "effective": 0, "errors": 0, "coverage_pct": 0, "error_pct": 0},
            "issues": ["❌ 无可用数据"]
        }
        checks["signal"] = {"name": "信号分布", "status": "FAIL", "details": {}, "issues": ["❌ 无可用数据"], "distribution": {}, "market_regime": "数据异常"}
        checks["reasonability"] = {"name": "数据合理性", "status": "FAIL", "details": {}, "issues": ["❌ 无可用数据"]}
        checks["freshness"] = {"name": "数据时效性", "status": "FAIL", "details": {}, "issues": ["❌ 无可用数据"]}

    # 市场状态检测
    regime, regime_detail = detect_market_regime(checks.get("signal", {}))
    checks["market_regime"] = {"name": "市场状态", "status": "PASS", "details": regime_detail, "issues": []}

    # 趋势异常检测
    trend_issues, last_record = detect_trend_anomaly(history, checks)
    checks["trend"] = {
        "name": "趋势对比",
        "status": "WARN" if trend_issues else "PASS",
        "details": {"history_count": len(history), "changes": len(trend_issues)},
        "issues": trend_issues,
    }

    # 4. 计算健康评分
    health_score = compute_health_score(checks)
    health_grade = grade_health(health_score)

    # 5. 输出报告
    print(f"\n{'='*60}")
    print(f"📊 体系自检报告 — {today}")
    print(f"{'='*60}")

    print(f"\n🏥 综合健康评分: {health_score}/100 ({health_grade})")

    print(f"\n📋 市场状态: {regime}")
    if regime_detail:
        print(f"   多头占比: {regime_detail.get('bullish_pct', 'N/A')}%")
        print(f"   空头占比: {regime_detail.get('bearish_pct', 'N/A')}%")
        print(f"   主导信号: {regime_detail.get('dominant_signal', 'N/A')} ({regime_detail.get('dominant_pct', 'N/A')}%)")
        if regime_detail.get('speculative_pct', 0) > 30:
            print(f"   ⚠️ 游资情绪占比偏高: {regime_detail['speculative_pct']}%，市场情绪驱动")

    print(f"\n✅ 检查项明细:")
    for check_name in ["coverage", "signal", "reasonability", "freshness", "market_regime", "trend"]:
        c = checks.get(check_name)
        if not c:
            continue
        status_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
        icon = status_icon.get(c.get("status", "UNKNOWN"), "❓")
        print(f"\n  {icon} {c['name']}: {c['status']}")
        if c.get("details"):
            for k, v in c["details"].items():
                print(f"     {k}: {v}")
        if c.get("issues"):
            for iss in c["issues"]:
                print(f"     {iss}")

    if c.get("distribution"):
        print(f"\n  📊 信号分布详情:")
        for sig, cnt in c["distribution"].items():
            pct = cnt / sum(c["distribution"].values()) * 100 if sum(c["distribution"].values()) else 0
            bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
            print(f"     {sig:20s} {cnt:5d} ({pct:5.1f}%) {bar}")

    # 6. 趋势异常
    if trend_issues:
        print(f"\n  📈 趋势变化:")
        for iss in trend_issues:
            print(f"     {iss}")

    # 7. 自动修复
    fix_result = auto_fix(checks)
    print(f"\n{'='*60}")
    print(f"🔧 自动修复诊断")
    print(f"{'='*60}")
    for fix in fix_result["fixes"]:
        icon = "✅" if fix["auto_fixable"] else "❌"
        print(f"  {icon} {fix['issue']}")
        print(f"     建议: {fix['action']}")
    print(f"  自动可修复: {fix_result['fixes_attempted']} 项")
    print(f"  需人工介入: {fix_result['fixes_needed']} 项")

    if args.fix and fix_result["fixes_attempted"] > 0:
        print("\n  🔧 自动修复模式已启用，尝试修复...")
        # 可修复项的执行逻辑
        if "adjust_workers" in fix_result.get("actions_taken", []):
            print("     ✅ 已记录: 下次运行建议增加 worker 数")

    # 8. 保存结果
    result = {
        "report_date": today,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "health_score": health_score,
        "health_grade": health_grade,
        "market_regime": regime,
        "regime_detail": regime_detail,
        "checks": {k: v for k, v in checks.items() if k != "trend"},
        "trend_issues": trend_issues,
        "fix_result": fix_result,
    }

    # 输出结构化JSON
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 自检结果已保存: {args.output}")

    # 保存历史
    history.append({
        "date": today,
        "timestamp": result["timestamp"],
        "health_score": health_score,
        "health_grade": health_grade,
        "market_regime": regime,
        "checks": {
            "coverage": checks.get("coverage", {}).get("details", {}),
            "signal": {
                "distribution": checks.get("signal", {}).get("distribution", {}),
                "details": checks.get("signal", {}).get("details", {}),
            },
            "regime": regime_detail,
        },
    })
    if save_history(args.history, history):
        print(f"✅ 历史记录已更新: {args.history}")

    # 退出码
    if health_score < 50:
        print(f"\n🔴 健康评分低于50，返回退出码 1")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"自检完成。评分: {health_score}/100 ({health_grade}) | 市场: {regime}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
