---
name: 双弦投资系统-月度股池
description: 为双弦投资系统提供月度股池功能，自动积累本月10元以下的共振及低吸信号结果，按月滚动归档，并在每日推送中体现。当用户说"改进双弦""月度股池""本月股池""改进体系""月池"时触发。不适用于非A股市场、非双弦系统的场景。
---

# 🗂️ 双弦投资系统 - 月度股池模块

**版本**: v1.0 | **更新**: 2026-07-08

## 功能概述

为双弦投资系统(v2.2)增加**月度股池**功能：
- 自动积累本月触发**共振信号**（AND门控通过 + 共振≥+1）且价格≤10元的个股
- 自动积累本月触发**低吸信号**（MACD底背离买点）且价格≤10元的个股
- 每日推送时自动追加月度股池报告
- 月度自动滚动，历史按月归档

## 文件结构

| 文件 | 职责 |
|:----|:------|
| `scripts/monthly_pool.py` | 月度股池核心：数据模型、持久化、报告生成 |
| `scripts/pool_adapter.py` | 集成适配层：对接原系统的reporter/push模块 |
| `references/config.json` | 月度股池配置参数 |

## 数据流

原系统每日运行：
logic_chain.py → scoring.py → reporter.py → push.py
                                            ↑
月度股池模块注入：                             |
gate_results (共振股) ─┐                      |
divergence_results (低吸) ─┤→ monthly_pool.py ─┘
                         │    (积累+去重+归档)
                         └→ pool_adapter.py
                             (生成月度报告 → 追加到推送末尾)

## 集成方式

在 main.py 的 Step 4→Step 5 之间插入：

```python
from monthly_pool import integrate_daily_run

# 收集当日结果
resonance_stocks = [...]   # AND门控输出(共振≥+1且价格≤10)
divergence_stocks = [...]  # 底背离买点输出(价格≤10)

# 执行集成
result = integrate_daily_run(
    resonance_candidates=resonance_stocks,
    divergence_candidates=divergence_stocks,
    daily_report=report_content,  # reporter.py的输出
)

# 用增强后的报告替换原推送内容
push_content = result["enhanced_report"]
```

## 配置参数

| 参数 | 默认值 | 说明 |
|:----|:------:|:------|
| MAX_PRICE | 10.0 | 价格筛选上限（与系统一致） |
| MIN_RESONANCE_SCORE | 1 | 共振最低要求，≥+1（偏多及以上） |
| POOL_DIR | ../pools | 月度股池文件存储目录 |

## 去重规则

| 场景 | 处理 |
|:----|:------|
| 同一只股，先共振后低吸 | 保留"共振"标签（优先级更高） |
| 同一只股，先低吸后共振 | 升级为"共振"标签 |
| 同一只股，同信号重复触发 | 更新评分为较高值，保留最早触发日期 |
| 同一只股，跨月出现 | 分属于不同月份的股池 |