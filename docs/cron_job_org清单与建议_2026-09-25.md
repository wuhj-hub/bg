# cron-job.org 外部触发 · 清单与建议（2026-09-25 核对）

> 背景：GitHub 原生 cron 不可靠（实测延迟 2-8h、丢单），体系已统一改为
> **cron-job.org → repository_dispatch** 外部触发。截至 9/25，**全部 workflow 的原生 cron 已停用**
> （本轮注释掉最后两个：`artifact_audit`、`evidence_review`）。

## 一、当前 10 个 job（实测全部有效）

| # | job 名 | event_type | 计划时间（北京） | 实测状态 | 建议 |
|---|---|---|---|---|---|
| 1 | 产物入库审计 | `artifact-audit-run` | 每日 06:05 | ✅ 有记录 | **保留** |
| 2 | 体系自检 | `selfcheck-daily-run` | 每日 07:00 | ✅ 有记录 | **保留** |
| 3 | 盘前市场报告 | `premarket-run` | 交易日 08:00 | ✅ 有记录 | **保留** |
| 4 | guard备份自检 | `guard-selfcheck-run` | 每日 09:35 | ✅ 有记录 | **保留** |
| 5 | 盘中监控 | `intraday-monitor-run` | 交易日 09:00–15:45 / 15min | ✅ 42 次（近60条） | **保留** |
| 6 | 全盘量化扫描 | `quant-scan-run` | 交易日 15:05 | ✅ 有记录 | **保留** |
| 7 | 涨停型王者跟踪 | `wangzhe-track-run` | 交易日 15:35 | ✅ 有记录 | **保留** |
| 8 | 猛兽突破池扫描 | `beast-pool-run` | 交易日 16:00 | ✅ 有记录 | **保留** |
| 9 | **市场状态判定** | `market-regime-run` | 每日 17:35 | ⚠️ 有效但**冗余** | 🔻 **建议删除** |
| 10 | 证据月度复核 | `evidence-review-run` | 每月 1 日 09:05 | ✅ 有记录 | **保留**（现已含回测周期） |

**周期统一**：周一至周五（第 10 项为每月 1 日）。

## 二、唯一建议调整：#9 市场状态判定

**为什么冗余**：
```
17:35  market-regime-run   → 跑 market_regime.py（独立 workflow）
18:15  quant_report 内联     → 跑同一个 market_regime.py（且带数据源探针守卫）
```
两者计算**同一个产物** `market_regime_latest.json`，结果一致 → 后跑的覆盖先跑的，等于**白跑一次**。
且内联通道带守卫（`if: steps.dataguard.outputs.data_ok == 'true'`），**故障时不会用坏数据覆盖旧判定**，比独立通道更安全。

**操作**：在 cron-job.org 中删除 `market-regime-run` 这个 job。
- workflow 文件 `.github/workflows/market_regime.yml` **保留**（作手动入口 / 应急兜底）
- 删除后：市场状态判定由 `quant_report` 链路负责（每日 18:15 前后）

**预期收益**：每日省掉一次重复运行（约 4min runner 时间 + 一次冗余提交）。

## 三、无需新增 job

**回测周期**（10/1 起）已**内联**到 `evidence-review-run` 链路（每月 1 日 09:05 同一 job 内执行），
因此**不需要**在 cron-job.org 另外建 `bt-cycle-run` job。

## 四、维护提醒

1. **Token 有效期**：cron-job.org 的 Authorization header 用的是 GitHub PAT。已改为永久有效；
   若哪天换 token，需同步更新 **10 个 job** 的 header + 沙箱 `GITHUB_TOKEN`。
2. **重复 job 检查**：如发现某任务同日跑两次，先查 cron-job.org 是否有重复 job。
3. **验证方法**：⚠️ cron-job.org 显示 `204 Successful` + 绿勾 **≠ 真的触发了**（GitHub 对任何
   event_type 都返回 204）。必须用 GitHub Actions 的 Event 列（`repository_dispatch`）交叉验证。
