# 全市场双维扫描（GitHub Actions）

每天交易日 16:30（北京时间）自动扫描沪深主板约 3000 只股票，计算「资金沉淀率 + 放量趋势 CJB30」双维指标，套用双维定性矩阵生成报告，回传 ima 知识库。

## 文件说明
- `gen_mainboard.py`：从东方财富行情接口拉取沪深主板清单（剔除科创板 688 / 创业板 300·301 / 北交所 8·4·43·83·87 / ST），输出 `all_mainboard.csv`。**需在 GitHub runner 运行**（沙箱环境东方财富接口被拦截）。
- `full_market_dualdim.py`：读 `all_mainboard.csv`，并发调用 westock 算双维，输出 `full_market_dualdim.csv`（全量）与 `full_market_report.md`（分布统计 + 重点标的 Top50）。
- `upload_ima.py`：把报告上传到 ima 知识库（可选移入指定文件夹）。
- `.github/workflows/full_market_scan.yml`：定时调度（cron `30 8 * * 1-5` + 手动触发）。

## 双维口径（与盘前/复盘体系一致）
- 沉淀率 = MainNetFlow5D ÷ 近5日总成交额
- CJB30 = (今日成交额 − 近30日均量) / 近30日均量 × 100（>50% 为放量，≤50% 为缩量）
- 双维定性矩阵：

| 量能＼沉淀率 | 高(>10%) | 中(5-10%) | 低(<5%) |
|---|---|---|---|
| 放量(>50%) | 主力主导放量🔥(最强) | 主力偏强放量 | 游资情绪 |
| 缩量(≤50%) | 主力控盘 | 主力惜售 | 情绪退潮 |

## 部署步骤
1. 把本目录（含 `.github/`）推送到你的 GitHub 仓库。
2. 仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加：
   - `IMA_OPENAPI_CLIENTID`：ima 开放 API Client ID
   - `IMA_OPENAPI_APIKEY`：ima 开放 API Key
   - `IMA_KB_ID`：目标知识库 ID（已用 `6kjd8jHpAyqf0xFVUo2xUWPaDAKapAWCw-Tki7V-aAs=`，即含「复盘报告」的公开知识库）
   - `IMA_FOLDER_ID`：目标文件夹 ID（已为你新建「全市场双维扫描」文件夹 `folder_7485264708529742`，直接填此值即可，扫描结果会自动落在此文件夹）
3. Actions 页面启用 workflow，或 **Run workflow** 手动立即测试。

## 获取知识库 / 文件夹 ID
- 知识库 ID：ima 客户端知识库设置/分享链接中提取，或用 ima-knowledge skill 的 `search_knowledge_base` 查询。
- 文件夹 ID：用 `get_knowledge_list` 列出文件夹，取 `folder_id` 字段。

## 注意事项
- **扫描耗时长**：约 3000 股 × 2 次 westock 调用，GitHub 免费额度约 2000 分钟/月，每日自动跑可能超额度。建议：用 **public 仓库**（额度不限）或按需 **workflow_dispatch 手动触发**，或在 Secrets 环境提高 `SCAN_WORKERS`（默认 8）缩短时长。
- **沙箱环境无法运行本方案**（东方财富被拦截、无 GitHub 凭证），专为 GitHub Actions runner 设计。
- westock 偶发调用失败已内置重试（RETRIES=2）；个别股票超时会被跳过并记录到进度日志。
