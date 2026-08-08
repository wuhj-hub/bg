---
name: 双弦投资系统
description: 双弦投资系统v2.3 ima运行版 - 基于双弦体系+猛兽v3.0信号融合的A股量化扫描系统，每日盘后运行，输出共振/低吸信号，自动积累月度股池。当用户说"双弦""跑双弦""双弦系统""双弦扫描"时触发。
---

# 双弦投资系统 v2.3 (ima运行版 · 猛兽v3.0融合)

## 🆕 v2.3 升级内容

| 升级方向 | 来源 | 效果 |
|:---------|:-----|:-----|
| ① 大盘评分 | 猛兽 `check_market_safety()` | 三指数加权(上证×0.3+中证全指×0.4+深证综指×0.3)，含广度情绪 |
| ② 信号标注 | 猛兽 G点/伏击线/RS_D/SSV | 月度股池每条标注猛兽信号标签 |
| ③ 低吸检测 | 猛兽VAD趋势替代原MACD简版 | 更准确的趋势判断 |

## 运行方式

```bash
# 手动运行（推荐盘后16:00后执行，约3分钟）
cd /sandbox/workspace/skills/双弦投资系统 && python3 scripts/run_shuangxian.py

# 查看月度股池
python3 /sandbox/workspace/skills/双弦投资系统/scripts/monthly_pool.py report
```

## 文件结构

| 文件 | 功能 |
|:----|:------|
| `scripts/run_shuangxian.py` | 双弦主运行脚本（猛兽温度计→板块→评分→门控→猛兽信号→月度股池） |
| `scripts/monthly_pool.py` | 月度股池管理（自动积累共振/低吸信号） |
| `pools/pool_YYYY-MM.json` | 月度股池JSON |

## 数据流

```
run_shuangxian.py
  ├─ Step0: 猛兽大盘评分 → 29/100 偏冷
  ├─ Step1: 板块扫描 → 热门板块TOP15
  ├─ Step2: 三维评分(资金35+技术35+趋势30)
  ├─ Step3: 热门板块标的追加
  ├─ Step4: AND门控(温度≥40+资金)
  ├─ Step5: 猛兽信号富集 → 月度股池注入
  └─ Step6: 月度股池报告
```

## 过滤规则
- 仅沪深主板: NOT(688/300/301/8/43/83/87/ST)
- 价格≤10元: 仅纳入≤10元标的
- 猛兽信号: 标注G点/伏击线/RS_D/SSV/双模式标签
