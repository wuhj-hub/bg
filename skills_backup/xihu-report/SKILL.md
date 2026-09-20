---
name: xihu-report
description: 西湖区的孩纸 · 三重滤网扫描报告生成器。基于"大周期找趋势，小周期找买点"策略，扫描A股执行三重滤网系统（周线MACD>0轴→日线均线支撑买点→综合评分），生成结构化报告。同时内置「西湖-RSV 多周期相对强度模型」（猛兽框架×西湖方法，RSV50/144/250 + 共振）。当用户说"西湖区的孩子""三重滤网""大周期找趋势""小周期找买点""西湖区的孩纸""扫描三重滤网""西湖RSV""西湖-RSV""多周期相对强度"时触发。不适用于长线价值投资、基金分析、非A股市场。
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

---

## 🏔️ 西湖-RSV 多周期相对强度模型（猛兽框架 × 西湖方法）

> 2026-09-20 新增。以**猛兽体系框架为核心**（数据层/RSV体质/评分层/输出层），以**西湖框架为方法论**（多周期相对强度 + 新高能力 + 第二阶段 + 周线闸门）。

### 模型定义

```
RSV1(N) = (C - LLV(L,N)) / (HHV(H,N) - LLV(L,N)) × 100      # 价格在N日区间的位置
RSV2(N) = (RS - min(RS,N)) / (max(RS,N) - min(RS,N)) × 100  # 相对基准强度位置, RS=C/中证全指
RSV(N)  = (RSV1 + RSV2) / 2                                   # 单周期相对强度 0-100
CRS     = 0.25·RSV50 + 0.35·RSV144 + 0.40·RSV250             # 综合相对强度（趋势派偏长周期）
结构分  = 100×(0.40·强势股 + 0.35·第二阶段 + 0.25·站上50日线)
Score   = 0.80·CRS + 0.20·结构分                             # 0-100
```

- **基准**：中证全指 `sh000985`（对齐猛兽体系主基准）
- **周期**：50 / 144 / 250（对齐西湖 RPS 三周期）
- **共振层级**：三周期均≥85 = 🔥三周期共振 / ≥2周期 = ⚡双周期共振 / 一周期 = ·单周期强
- **RSV2 双口径**：`rel`（相对基准时序位置，默认）/ `cross`（全市场横截面RPS排名）

### 命令用法

```bash
# 全市场扫描（默认，读 all_mainboard.csv，仅沪深主板，剔除ST）
python3 quant_scripts/xihu_rsv.py --top 30 \
  --json outputs/xihu_rsv_latest.json \
  --report "outputs/西湖RSV全市场_$(date +%Y-%m-%d).md"

# 横截面RPS模式（RSV2 换为全市场N日涨幅排名百分位）
python3 quant_scripts/xihu_rsv.py --top 30 --rsv2-mode cross

# 指定标的
python3 quant_scripts/xihu_rsv.py --stocks sh600519,sz000993

# 独立计算横截面RPS
python3 quant_scripts/rps.py --top 30 --json outputs/rps_latest.json
```

### 输出

- JSON：`{date, bench, periods, total, top:[{code,name,close,rsv50,rsv144,rsv250,crs,structure,score,rating,resonance,weekly_gate}]}`
- 报告：`outputs/西湖RSV全市场_{date}.md`（TOP榜单表 + 分布统计）

### 体系融合

- **猛兽 `beast_screener.py`**：Setup ⑦项已接入（`RSVA(3)+SSV(3)+RSL(2)+西湖RSV(2)`，总上限10）；领先股表新增「西湖R」列；函数 `calc_xihu_rsv()`
- **盘前报告**：③.5b「西湖-RSV 多周期相对强度」节（`gen_premarket_report.py`）
- **每日自动**：`quant_scan.yml` 盘后扫描步骤「西湖-RSV 多周期相对强度扫描（全市场）」

### 验证锚点（2026-09-18 数据）

| 标的 | RSV50 | RSV144 | RSV250 | CRS | 共振 |
|---|---|---|---|---|---|
| 闽东电力 | 99.2 | 99.2 | 99.2 | 99.2 | 🔥三周期共振 |
| 招商银行 | 73.6 | 83.3 | 81.6 | 80.2 | ○三周期偏强 |
| 贵州茅台 | 36.8 | 41.1 | 35.1 | 37.6 | — |