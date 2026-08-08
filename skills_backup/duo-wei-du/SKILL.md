---
name: duo-wei-du
description: 多维度量化扫描报告生成器。基于主力资金流向+三层趋势共振+多周期资金验证的全链路量化模型，每日盘后执行对选定股票池的多维度评分扫描，生成结构化报告并自动存入「多维量化」订阅知识库的「多维度」文件夹。当用户说"多维度扫描""多维量化""出多维度报告""运行量化模型""执行多维度扫描"时触发。不适用于盘中实时数据、个股深度财务分析、非A股市场。
---

# 多维度量化扫描

## 你的工作方式

你的核心任务是在盘后运行 `/sandbox/workspace/quant_model.py` 量化模型，对预设股票池进行全链路扫描（大盘择时 → 板块资金扫描 → 龙头个股评分 → 三层趋势共振验证 → 多周期资金验证），将结果以 Markdown 报告形式保存，并上传到「多维量化」订阅知识库的「多维度」文件夹中。

**关键原则：**
- 始终将报告保存到该知识库对应文件夹中，以确保每期报告可追溯
- 报告文件名格式：`多维量化报告_YYYY-MM-DD.md`
- 如果用户提供了自定义股票池，在运行前先修改脚本中的 `stock_pool` 变量
- 如果用户没有指定股票池，使用脚本默认的股票池即可

## 流程

### Phase 1：运行量化模型

运行量化模型生成报告：

```bash
cd /sandbox/workspace && python3 quant_model.py
```

脚本会自动完成以下5个模块的计算，并输出到终端：
1. **大盘择时**：基于量价+资金+情绪的市场温度计 (0~100)
2. **板块资金扫描**：覆盖50个板块（行业+概念），按「累计控盘度」排序，含5日/20日涨幅及资金流向
3. **龙头个股评分**：资金维度(35分) + 技术共振(35分) + 趋势结构(30分)
4. **三层趋势共振**：大盘+板块+个股趋势验证
5. **多周期资金验证**：当日/3日/5日/20日资金流向一致性检查

### Phase 2：保存报告到文件

将终端输出保存为 Markdown 文件：

```bash
cd /sandbox/workspace && python3 quant_model.py > "多维量化报告_YYYY-MM-DD.md"
```

其中 `YYYY-MM-DD` 替换为实际日期。

### Phase 3：上传到知识库

使用上传工具将报告文件上传到「多维量化」订阅知识库的「多维度」文件夹：

```bash
python3 /sandbox/workspace/skills/ima-knowledge/scripts/upload_file.py \
    --file-path "/sandbox/workspace/多维量化报告_YYYY-MM-DD.md" \
    --knowledge-base-id "RgPmCvOW2CgN3I-HVGEYfmBS_W0mkiYzHRuTGHP8_6o=" \
    --rename "多维量化报告_YYYY-MM-DD" \
    --folder-id "folder_7478204537267754"
```

- 知识库 ID：`RgPmCvOW2CgN3I-HVGEYfmBS_W0mkiYzHRuTGHP8_6o=`（多维量化）
- 目标文件夹：`多维度`（media_id: `folder_7478204537267754`）

### Phase 4：确认交付

告诉用户报告已完成，总结当日核心结果：
- 市场温度数值与区间
- 板块覆盖总数、正控盘/负控盘板块数量
- 最强板块 TOP3（名称+控盘度+龙头股）
- 最优个股 TOP3（评分+操作建议）
- 总仓位建议

## 多轮修改

### 修改股票池

如果用户想分析不同的股票，在运行前修改 `quant_model.py` 中的 `stock_pool` 列表：

```python
stock_pool = [
    ("sh600000", "浦发银行", None),
    ("sz002594", "比亚迪", None),
    # code, name, board_code(可选)
    # 过滤规则（通用）：仅保留沪深主板，排除科创板/创业板/北交所/ST
]
```

### 通用选股过滤规则

```python
# 所有股票池统一执行以下过滤：
# NOT(CODELIKE('688'))  AND NOT(CODELIKE('300'))  AND NOT(CODELIKE('301'))
# AND NOT(CODELIKE('8'))  AND NOT(CODELIKE('43'))  AND NOT(CODELIKE('83'))  AND NOT(CODELIKE('87'))
# AND NOT(NAMELIKE('ST'))  AND NOT(NAMELIKE('*ST'))
# 即：仅保留沪深主板（sh600xxx-sh605xxx, sz000xxx-sz004xxx, sz002xxx）
```

### 调整评分参数

如果用户想调整评分权重，修改 `score_stock` 函数中各维度权重：
- `fund_score` 上限35分（资金维度）
- `tech_score` 上限35分（技术共振）
- `trend_score` 上限30分（趋势结构）

## 工作流示例

### 示例1：每日盘后标准扫描

用户说"出多维度报告"：
1. 运行 `python3 quant_model.py` 获取全量扫描结果
2. 保存为 `多维量化报告_2026-07-02.md`
3. 上传到「多维量化」→「多维度」文件夹
4. 回复用户：市场温度、最优标的、仓位建议

### 示例2：带自定义股票池的扫描

用户说"多维度扫描一下这几个票：宁德时代、比亚迪、中芯国际"：
1. 修改 `stock_pool` 为 `[("sz002594","比亚迪",None),("sh600519","贵州茅台",None),("sh603019","中科曙光","pt01801081")]`
2. 运行并生成报告
3. 上传保存
4. 输出各股评分明细

## 管理信息

- 知识库名称：多维量化
- 知识库 ID：`RgPmCvOW2CgN3I-HVGEYfmBS_W0mkiYzHRuTGHP8_6o=`
- 文件夹名称：多维度
- 文件夹 media_id：`folder_7478204537267754`
- 模型脚本路径：`/sandbox/workspace/quant_model.py`
