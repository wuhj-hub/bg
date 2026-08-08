"""
双弦投资系统 - 月度股池集成适配器 (pool_adapter.py)
===================================================
作为 reporter.py 和 push.py 的非侵入式扩展，在每日报告推送中注入月度股池。

集成方式（无需修改原系统代码）：
    在 main.py 的 Step 4（报告生成）之后、Step 5（推送）之前插入：

    ```python
    from monthly_pool import add_daily_results, get_monthly_pool_report

    # 1. 将当日结果加入月度股池
    add_daily_results(
        resonance_stocks=gate_results,   # AND门控通过的共振股 (价格≤10)
        dip_stocks=divergence_results,   # 底背离买点检测结果 (价格≤10)
    )

    # 2. 获取月度股池报告文本
    pool_report = get_monthly_pool_report()

    # 3. 追加到推送消息尾部（reporter.py 输出末尾 + pool_report）
    final_push_content = daily_report + "\\n" + pool_report
    ```
"""

import json
import os
from datetime import datetime, date
from typing import Optional

# 复用 monthly_pool 模块
from monthly_pool import MonthlyPool, POOL_DIR, MAX_PRICE, MIN_RESONANCE_SCORE


# ============================================================
# 增强推送内容生成
# ============================================================

def enhance_report(daily_report: str, base_dir: str = POOL_DIR) -> str:
    """
    将月度股池追加到每日报告末尾

    Args:
        daily_report: reporter.py 输出的原始报告文本
        base_dir: 月度股池存储目录

    Returns:
        追加了月度股池的完整推送文本
    """
    from monthly_pool import get_monthly_pool_report

    pool_section = get_monthly_pool_report(base_dir=base_dir)
    if not pool_section:
        return daily_report  # 月度股池为空，直接返回原报告

    # 追加到末尾
    enhanced = daily_report.rstrip() + "\n\n" + pool_section
    return enhanced


def get_daily_increment(resonance_added: list[dict],
                        dip_added: list[dict]) -> str:
    """
    生成"今日新增"摘要（用于推送头部提醒）

    Args:
        resonance_added: 今日新增的共振股列表
        dip_added: 今日新增的低吸股列表

    Returns:
        今日新增摘要文本
    """
    parts = []
    if resonance_added:
        names = [s["name"] for s in resonance_added]
        parts.append(f"共振新增{len(resonance_added)}只: {', '.join(names[:5])}")
        if len(names) > 5:
            parts[-1] += f" 等{len(names)}只"

    if dip_added:
        names = [s["name"] for s in dip_added]
        parts.append(f"低吸新增{len(dip_added)}只: {', '.join(names[:5])}")
        if len(names) > 5:
            parts[-1] += f" 等{len(names)}只"

    if parts:
        return "📌 本月股池更新: " + " | ".join(parts)
    return ""


# ============================================================
# 完整集成示例（适配 main.py 调用）
# ============================================================

def integrate_daily_run(resonance_candidates: list = None,
                        divergence_candidates: list = None,
                        daily_report: str = "",
                        base_dir: str = POOL_DIR) -> dict:
    """
    每日全流程集成函数：
    1. 将当日共振/低吸候选加入月度股池
    2. 返回增强后的推送内容和更新摘要

    Args:
        resonance_candidates:
            AND门控通过且共振≥+1的候选股列表
            每项格式: {
                "code": "sh600XXX",
                "name": "名称",
                "price": 9.50,
                "score": 85.0,
                "resonance_label": "偏多+1",
                "sector": "板块名",
                "reason": "共振偏多"
            }
        divergence_candidates:
            底背离买点检测通过的候选股
            每项格式: {
                "code": "sh600XXX",
                "name": "名称",
                "price": 8.20,
                "score": 60.0,
                "sector": "板块名",
                "reason": "MACD底背离买点"
            }
        daily_report: reporter.py 生成的每日报告
        base_dir: 月度股池目录

    Returns:
        {
            "added_resonance": [新增共振股],
            "added_dip": [新增低吸股],
            "monthly_stats": {月度统计},
            "enhanced_report": "增强后的推送内容",
            "update_summary": "更新摘要文本"
        }
    """
    pool = MonthlyPool(base_dir=base_dir)
    added_resonance = []
    added_dip = []

    # 1. 添加共振股（价格≤10元 + 共振≥偏多）
    if resonance_candidates:
        for s in resonance_candidates:
            if s.get("price", 999) <= MAX_PRICE:
                is_new = pool.add_resonance_stock(
                    code=s["code"], name=s["name"], price=s["price"],
                    score=s.get("score", 0),
                    resonance_label=s.get("resonance_label", ""),
                    sector=s.get("sector", ""),
                    reason=s.get("reason", ""),
                )
                if is_new:
                    added_resonance.append(s)

    # 2. 添加低吸股（价格≤10元）
    if divergence_candidates:
        for s in divergence_candidates:
            if s.get("price", 999) <= MAX_PRICE:
                is_new = pool.add_dip_stock(
                    code=s["code"], name=s["name"], price=s["price"],
                    score=s.get("score", 0),
                    sector=s.get("sector", ""),
                    reason=s.get("reason", ""),
                )
                if is_new:
                    added_dip.append(s)

    # 3. 保存到文件
    saved = pool.save()

    # 4. 生成增强报告
    enhanced = daily_report.rstrip()
    pool_section = pool.format_report()
    if pool_section:
        enhanced += "\n\n" + pool_section

    # 5. 生成更新摘要
    summary = get_daily_increment(added_resonance, added_dip)

    return {
        "added_resonance": added_resonance,
        "added_dip": added_dip,
        "monthly_stats": pool.get_stats(),
        "enhanced_report": enhanced,
        "update_summary": summary,
    }


# ============================================================
# 测试/演示
# ============================================================

if __name__ == "__main__":
    # 模拟当日运行数据
    test_resonance = [
        {"code": "sh601398", "name": "工商银行", "price": 7.26,
         "score": 82, "resonance_label": "强共振+2",
         "sector": "银行", "reason": "银行护盘共振"},
        {"code": "sh600031", "name": "三一重工", "price": 19.44,
         "score": 75, "resonance_label": "偏多+1",
         "sector": "工程机械", "reason": "工程机械复苏共振"},
        # 注意：三一19.44 > 10，不会被加入
        {"code": "sz000938", "name": "紫光股份", "price": 33.31,
         "score": 78, "resonance_label": "偏多+1",
         "sector": "半导体", "reason": "半导体共振"},
        # 价格>10，不会被加入
    ]

    test_dip = [
        {"code": "sh600887", "name": "伊利股份", "price": 25.07,
         "score": 62, "sector": "食品饮料",
         "reason": "MACD底背离买点"},
        # 价格>10，不会被加入
    ]

    test_report = """【双弦投资系统】2026-07-08 盘后报告
市场温度: 33°C (冷区)
...

四、AND门控
1. 工商银行 7.26 | 评分82 | 强共振+2
2. ...

五、主线军捕获器
..."""

    result = integrate_daily_run(
        resonance_candidates=test_resonance,
        divergence_candidates=test_dip,
        daily_report=test_report,
    )

    print("=" * 50)
    print("集成测试结果")
    print("=" * 50)
    print(f"\n📌 更新摘要: {result['update_summary']}")
    print(f"\n📊 月度统计: {json.dumps(result['monthly_stats'], ensure_ascii=False, indent=2)}")
    print(f"\n📋 增强报告(末尾200字符): ...{result['enhanced_report'][-200:]}")
    print(f"\n✅ 测试完成! 股池文件保存在: {POOL_DIR}")