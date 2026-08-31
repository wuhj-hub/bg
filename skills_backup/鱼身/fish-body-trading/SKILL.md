---
name: fish-body-trading
description: 鱼身交易系统 — 基于MACD空中加油、均线回踩支撑、箱体突破三种经典模式的A股量化扫描系统。融合多维度评分（资金+技术+趋势）+ 三层共振验证 + 大盘温度计。当用户说"鱼身交易""鱼身扫描""空中加油""吃鱼身""鱼身信号"时触发。不适用于长线价值投资、非A股市场、日内高频交易。
---

# 🐟 鱼身交易系统 v2.0（多维度融合版）

基于三种经典鱼身模式的A股量化扫描系统，融合多维度评分（资金35%+技术35%+趋势30%）、大盘温度计、三层共振验证。

## 核心模式

| 模式 | 评分等级 | 案例原型 | 核心理念 |
|:---:|:---:|:---|:---|
| ⭐ MACD空中加油 | 最强(100分) | 日发精机 | MACD在0轴上方，DIF回踩DEA不破，柱体翻红 |
| 📍 均线回踩支撑 | 稳健(100分) | 灵康药业 | 多头排列，回调至MA10/MA20缩量止跌 |
| 🚀 箱体突破 | 动量(100分) | 红豆股份 | 窄幅整理后放量突破前高 |

## 工作流

### Step 1: 运行鱼身扫描

```bash
# 核心股票池快速扫描（推荐）
python3 /sandbox/workspace/skills/fish-body-trading/scripts/fish_body_enhanced.py --pool core

# 全市场扫描（约5-10分钟）
python3 /sandbox/workspace/skills/fish-body-trading/scripts/fish_body_enhanced.py --pool all

# 只扫描MACD空中加油模式
python3 /sandbox/workspace/skills/fish-body-trading/scripts/fish_body_enhanced.py --pool core --mode 1

# v1.0版（纯鱼身模式，无多维度融合）
python3 /sandbox/workspace/skills/fish-body-trading/scripts/fish_body_system.py --pool core
```

### Step 2: 输出说明

系统会输出三层信息：

1. **大盘环境**：温度(0-100) + 等级（偏热/中性/冰点），温度<40自动拦截不开仓
2. **每只股票的多维度评分**：资金+技术+趋势三个维度的细分得分
3. **鱼身信号**：包含模式类型、综合评分（融合原始分+多维分+共振分）、止损/目标位、共振验证结果

### Step 3: 保存结果

扫描结果自动保存到 `/sandbox/workspace/outputs/fish_body_enhanced_{YYYYMMDD_HHMM}.json`

如需推送报告到知识库：

```bash
python3 /sandbox/workspace/skills/ima-knowledge/scripts/upload_file.py \
  --file-path /sandbox/workspace/outputs/fish_body_enhanced_{YYYYMMDD_HHMM}.json \
  --knowledge-base-id <kb_id>
```

## 参数说明

| 参数 | 默认值 | 说明 |
|:---|:---:|:---|
| `--pool` | core | core(核心3只) / all(全A股) / 文件路径 |
| `--mode` | all | 1(空中加油) / 2(均线回踩) / 3(箱体突破) / all |
| `--min-temp` | 40 | 最低大盘温度，低于此值不出信号 |

## 评分规则速查

**多维度评分（满分100）**：
- 资金维度(35分)：主力净流入 + 多周期持续性 + 特大单 + 资金沉淀率
- 技术共振(35分)：MACD + RSI + KDJ + 布林带位置
- 趋势结构(30分)：均线排列 + 近10日涨幅 + 量价配合

**鱼身模式评分（满分100）**：
- MACD空中加油：DIF/DEA位置(25) + 金叉(25) + MACD柱翻红(30) + MA5上方(10) + 多头排列(5) + KDJ未超买(5)

**综合评分 = 原始鱼身分 × (0.6 + 0.2×多维评分/100 + 0.2×共振分/100)**

## 注意事项

- 仅交易日盘后使用 — 非交易日无新K线数据
- 全量扫描约5-10分钟（4000+只），务必提前告知用户
- 结果文件保存在 /sandbox/workspace/outputs/ 目录
- 大盘温度<40时自动拦截，不建议强行开仓
- 最终评分<55的信号过滤不显示