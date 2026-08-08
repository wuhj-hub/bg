---
name: wangbei-report
description: 王者倍量柱扫描报告生成器。运行倍量柱全量扫描，将突破信号生成 Markdown 报告并保存到「王者倍量柱」独立知识库。当用户说"王者倍量""倍量柱""生成倍量柱报告""倍量柱扫描复盘"时触发。不适用于盘中实时监控、其他策略分析、非A股市场。
---

# 王者倍量柱扫描报告

运行全市场倍量柱扫描，将突破信号整理为结构化报告，存入「王者倍量柱」独立知识库。

## 知识库信息

- **目标知识库**: 王者倍量
- **kb_id**: `jyrQP5Yr79WPyHx0O8Lf2QBRtu3FtqkDeXPfkTpNZtM=`
- **说明**: 独立知识库，与「盘前市场报告」平级

## 工作流

### Step 1: 运行扫描

执行扫描脚本：

```bash
python3 /sandbox/workspace/wangbei_scanner.py --mode scan
```

- 默认扫描全市场（约 2000+ 只），耗时 15-20 分钟
- 如用户要求快速出结果，加 `--limit 100`
- 扫描完成后结果自动保存到 `~/.wangbei_cache/scan_result.json`
- **告知用户正在扫描、预计耗时，请耐心等待**

### Step 2: 读取扫描结果

```bash
python3 -c "
import json, sys
from pathlib import Path
p = Path.home() / '.wangbei_cache' / 'scan_result.json'
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
# 🏆 王者倍量柱突破扫描报告

**扫描时间**: {scan_time}
**扫描数量**: {total_scanned} 只
**突破信号**: {signal_count} 个

---

## 突破信号列表

| 代码 | 名称 | 收盘价 | 阻力位 | 突破% | 量比 | 类型 | 倍量柱日 |
|------|------|--------|--------|-------|------|------|----------|
| ... | ... | ... | ... | ... | ... | ... | ... |

---

> 📊 数据来源: 王者倍量柱扫描 (wangbei_scanner.py)
> 📱 推送: PushPlus 同步已发送
```

**无信号时**：
```markdown
# 🏆 王者倍量柱突破扫描报告

**扫描时间**: {scan_time}
**扫描数量**: {total_scanned} 只

📭 今日未发现突破信号。

---

> 📊 数据来源: 王者倍量柱扫描 (wangbei_scanner.py)
```

将报告保存到工作区，文件名格式：`/sandbox/workspace/outputs/王者倍量柱报告_{YYYY-MM-DD}.md`

### Step 4: 上传到知识库

```bash
python3 /sandbox/workspace/skills/ima-knowledge/scripts/upload_file.py \
  --file-path /sandbox/workspace/outputs/王者倍量柱报告_{YYYY-MM-DD}.md \
  --knowledge-base-id jyrQP5Yr79WPyHx0O8Lf2QBRtu3FtqkDeXPfkTpNZtM=
```

### Step 5: 汇总告知用户

输出摘要：
- 扫描了多少只股票
- 发现多少个突破信号
- 报告是否成功上传到知识库
- 提醒 PushPlus 推送也已同步发出

## 注意事项

1. **仅交易日盘后使用** — 非交易日无新 K 线数据
2. **扫描耗时长** — 全量扫描约 15-20 分钟，务必提前告知用户
3. **结果文件** — `~/.wangbei_cache/scan_result.json`，脚本自动覆盖
4. **报告存放** — 工作区 `/sandbox/workspace/outputs/` 目录下
5. **PushPlus 同步** — 脚本内置推送，报告上传知识库的同时手机也会收到
