---
name: xihu-report
description: 西湖区的孩纸 · 三重滤网扫描报告生成器。基于"大周期找趋势，小周期找买点"策略，扫描A股执行三重滤网系统（周线MACD>0轴→日线均线支撑买点→综合评分），生成结构化报告。当用户说"西湖区的孩子""三重滤网""大周期找趋势""小周期找买点""西湖区的孩纸""扫描三重滤网"时触发。不适用于长线价值投资、基金分析、非A股市场。
---

# 西湖区的孩纸 · 三重滤网扫描报告

基于小西（西湖区的孩纸）《大周期找趋势，小周期找买点》策略，对股票池执行三重滤网扫描，将信号整理为结构化报告，存入「吴华江的知识库」。

## 知识库信息

- **目标知识库**: 三重滤网扫描（订阅知识库）
- **kb_id**: `LyBCCx8bEKoh7XqRNly4y9aRfR5MBsjxJGA--aNS0rQ=`
- **存放位置**: 知识库根目录

## 策略核心

### 三重滤网交易系统

| 滤网层级 | 周期 | 判断标准 | 得分权重 |
|---------|------|---------|:-------:|
| 第一层 | 周线 | MACD在0轴上方（DIF≥0）确认大周期上升趋势 | 35分 |
| 第二层 | 日线 | 回踩20/50日线支撑、MACD底背离寻找买点 | 25-30分 |
| 第三层 | 综合 | 均线多头排列、多重信号共振确认 | 15-25分 |

### 买点类型
1. 🟢 回踩20日线支撑 — 短期回调企稳
2. 🟢 回踩50日线支撑 — 中期调整结束
3. 🟢 日线MACD底背离 — 价格新低但动能转强
4. 🟢 均线多头排列回调 — 中长期趋势良好

## 工作流

### Step 1: 运行扫描

执行扫描脚本：

```bash
python3 /sandbox/workspace/xihu_scanner.py --mode scan
```

- 默认扫描热搜股池（约50只），耗时 3-5 分钟
- 如需快速出结果：`--limit 30`
- 如需指定股票：`--stocks sh600519,sz000001`
- 扫描完成后结果自动保存到 `~/.xihu_cache/scan_result.json`
- **告知用户正在扫描、预计耗时，请耐心等待**

### Step 2: 读取扫描结果

```bash
python3 -c "
import json, sys
from pathlib import Path
p = Path.home() / '.xihu_cache' / 'scan_result.json'
if not p.exists():
    print('ERROR: 结果文件不存在')
    sys.exit(1)
data = json.load(open(p))
print(json.dumps(data, ensure_ascii=False, indent=2))
"
```

### Step 3: 生成 Markdown 报告文件

根据结果数量选择模板：

**有信号时**：
```markdown
# 🏆 西湖区的孩纸 · 三重滤网扫描报告

**策略来源**: 小西《大周期找趋势，小周期找买点》
**扫描时间**: {scan_time}
**扫描数量**: {total_scanned} 只
**周线向上**: {weekly_up} 只
**买点信号**: {signal_count} 个

---

## 核心逻辑说明
| 滤网层级 | 周期 | 判断标准 | 策略依据 |

## 买点信号股票
| 代码 | 名称 | 评分 | 现价 | MA20 | MA50 | 买点类型 | 建议买入价 | 止损位 | 目标位 |

## 观察名单（周线向上，等待买点）
| 代码 | 名称 | 评分 | 现价 | 距MA20% | 距MA50% |

## 周线向下（暂不关注）
| 代码 | 名称 | 现价 |
```

**无信号时**：
```markdown
# 🏆 西湖区的孩纸 · 三重滤网扫描报告

**扫描时间**: {scan_time}
**扫描数量**: {total_scanned} 只

📭 今日未发现符合条件的买点信号。

---
> 📊 数据来源: 腾讯自选股行情数据接口 (westock-data)
```

将报告保存到工作区，文件名格式：`/sandbox/workspace/outputs/西湖区的孩纸_三重滤网报告_{YYYY-MM-DD}.md`

### Step 4: 上传到知识库

```bash
python3 /sandbox/workspace/skills/ima-knowledge/scripts/upload_file.py \
  --file-path /sandbox/workspace/outputs/西湖区的孩纸_三重滤网报告_{YYYY-MM-DD}.md \
  --knowledge-base-id LyBCCx8bEKoh7XqRNly4y9aRfR5MBsjxJGA--aNS0rQ=
```

### Step 5: 汇总告知用户

输出摘要：
- 扫描了多少只股票
- 周线向上多少只（大周期趋势向好比例）
- 发现多少个买点信号（高评分标的）
- 报告是否成功上传到知识库

## 注意事项

1. **交易日盘后使用最佳** — 非交易日无新 K 线数据
2. **扫描耗时约 3-5 分钟** — 取决于股票池大小，务必提前告知用户
3. **结果文件** — `~/.xihu_cache/scan_result.json`，脚本自动覆盖
4. **报告存放** — 工作区 `/sandbox/workspace/outputs/` 目录下
5. **数据来源** — 腾讯自选股行情数据接口 (westock-data)