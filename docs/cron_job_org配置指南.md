# cron-job.org 精确配置指南（bg 量化体系）

> 整理时间：2026-09-18
> 用途：替代 GitHub 免费版不稳定的原生 cron，实现精确定时触发

---

## 一、为什么需要它

GitHub Actions 免费版的 `schedule` cron 存在**降频、随机延迟数小时、丢单**三类问题，实测：

| 现象 | 实例 |
|---|---|
| 丢单 | `market_regime` 9/17 未触发 |
| 降频 | `intraday_monitor` 理论应 28 次/交易日，实测仅 4.2 次 |
| 已放弃原生 cron | `quant_scan`、`premarket_report` 的 schedule **已被注释**，完全依赖外部触发 |

**cron-job.org** 是免费的外部定时服务，到点后向 GitHub 发 `repository_dispatch` 事件，从而精确触发 workflow。

---

## 二、核心配置（所有 job 通用）

### 请求设置

| 字段 | 值 |
|---|---|
| **URL** | `https://api.github.com/repos/wuhj-hub/bg/dispatches` |
| **Request method** | **POST** |
| **Request body** | `{"event_type":"<事件名>"}`  ← 每个 workflow 不同，见下表 |

### 请求头（Headers）

| 名称 | 值 |
|---|---|
| `Authorization` | `token <你的GitHub PAT>` |
| `Accept` | `application/vnd.github+json` |
| `Content-Type` | `application/json` |

> ⚠️ `Authorization` 的格式是 **`token ` + 空格 + PAT**（不是 `Bearer`）
> ⚠️ PAT 需有 **repo** 权限（你现有的 token 即可）

### 建议开启的选项（Advanced 标签页）

| 选项 | 建议值 | 说明 |
|---|---|---|
| **Save responses in history** | ✅ 开启 | 便于事后排查（否则只存状态码）|
| **Treat redirects as success** | ❌ 关闭 | dispatches 不重定向 |
| **Enable job** | ✅ 开启 | |
| **Failure notification** | 可选 | 连续失败时邮件提醒 |

---

## 三、⏰ 时区设置（最关键，容易错）

**cron-job.org 默认时区是 UTC**，设置时间前**必须**改：

```
Settings → 找到 "Timezone"
改为 → Asia/Shanghai  (UTC+8)
```

改完后，界面里填的小时数就**直接是北京时间**，不用再自己换算。

> ⚠️ 如果不改时区，你填 17:35 实际会在北京时间凌晨 01:35 触发 —— **这是最常见的错误**

---

## 四、各 Job 配置表（北京时间 + 权威事件名）

| # | Job 名称（建议） | **event_type** | 建议时间（北京）| cron 表达式 | 说明 |
|---|---|---|---|---|---|
| 1 | 盘前市场报告 | **`premarket-run`** | **06:35** | `35 6 * * 1-5` | ⚠️**原生 cron 已注释，必须配** |
| 2 | 全盘量化扫描 | **`quant-scan-run`** | **15:05** | `5 15 * * 1-5` | ⚠️**原生 cron 已注释，必须配** |
| 3 | 市场状态判定 | **`market-regime-run`** | **17:35** | `35 17 * * 1-5` | 与 workflow cron 17:30 错开 |
| 4 | 涨停型王者跟踪 | **`wangzhe-track-run`** | **15:35** | `35 15 * * 1-5` | 原 cron 就是 15:35 |
| 5 | 盘中监控 | **`intraday-monitor-run`** | **09:00-15:45 每15分** | `*/15 9-15 * * 1-5` | 见下方"高频 job 说明" |
| 6 | 产物入库审计 | **`artifact-audit-run`** | **06:05** | `5 6 * * *` | 盘前跑 |
| 7 | 体系自检 | **`guard-selfcheck-run`** | **09:35** | `35 9 * * *` | 原 cron 09:30 |
| 8 | 证据月度复核 | **`evidence-review-run`** | **每月1号 09:05** | `5 9 1 * *` | 低频，可选 |
| 9 | **体系自检**（数据源真实性+静默失败） | **`selfcheck-daily-run`** | **07:00** | `0 7 * * *` | 🆕2026-09-18 新增，盘前先验数据可信 |

### 🔍 如何自查 cron-job.org 上到底配了什么（推荐每月一次）

cron-job.org 的 job 列表**看不出 event_type**（它只显示 URL，而所有 job 的 URL 都一样），
所以判断「某个 workflow 被配了几次」要看 **GitHub Actions 的触发记录**：

1. 打开 `https://github.com/wuhj-hub/bg/actions` → 左侧点某个 workflow
2. 看每次运行的 **Event** 列：
   - `repository_dispatch` = 由 cron-job.org 触发（外部）
   - `schedule` = GitHub 原生 cron
   - `workflow_dispatch` = 手动点的
3. 统计 `repository_dispatch` 的**触发时刻**：
   - 同一 workflow 一天出现**两个固定时刻**（如 09:35 + 09:45）→ **配重了，删掉一个**
   - 出现非计划的时刻 → 可能是手动/其他来源，忽略

> 也可以在 cron-job.org 每个 job 的 **History** 标签页看实际触发记录，
> 标题重名时按 **Created** 时间先后区分。

**已知需处理**：`market-regime-run` 实测在 09:35 与 09:45 各触发一次（配了 2 个）。
且**时间点本身不对** —— 该 workflow 依赖收盘数据（市场宽度/涨停数），
盘中跑出来的是不完整快照（9/18 实例：早上 09:35 判「弱势偏熊」，盘后 17:35 判「震荡市」）。
**建议：删掉早上的两个，改配 1 个盘后 17:35。**

---

### ⚠️ 优先级：前两个（1、2）最重要

`premarket_report` 和 `quant_scan` 的 **原生 schedule 已被注释**（注释写着"避免与 cron-job.org 重复触发"）——
意味着**如果你没在 cron-job.org 配它们，这两个 workflow 就永远不会自动运行**。

### 高频 job 说明（第 5 个 · 盘中监控）

`intraday_monitor` 需要 **09:00~15:45 每 15 分钟**触发一次，即：

```
cron 表达式（Asia/Shanghai 时区下）: */15 9-15 * * 1-5
```

⚠️ 注意这会**每个交易日触发 28 次**，cron-job.org 免费版对高频 job 是允许的，但如果提示超限，可以：
- 改为 `*/30 9-15 * * 1-5`（每 30 分钟，14 次）
- 或只覆盖关键时段 `*/15 9-10,14-15 * * 1-5`（早盘+尾盘）

---

## 五、操作步骤（逐个 job）

```
1. cron-job.org → 登录 → "Create cronjob"

2. 【Common】
   Title:            盘前市场报告          ← 建议名
   URL:              https://api.github.com/repos/wuhj-hub/bg/dispatches
   Execution schedule: 选 "Every day" 或自定义 → 填 35 6 * * 1-5

3. 【Schedule】
   Timezone:         Asia/Shanghai         ← ⚠️ 必改
   Hours/Minutes:    按上表填，或直接用 cron 表达式模式

4. 【Advanced】→ Headers
   添加 3 条：
     Authorization:  token <PAT>
     Accept:         application/vnd.github+json
     Content-Type:   application/json

5. 【Advanced】→ Request body
   选 "Raw" → 填:  {"event_type":"premarket-run"}

6. Request method:  POST

7. ☑️ Save responses in history

8. 点 "TEST RUN" 立即验证
```

---

## 六、验证方法

### 立刻验证（推荐）

1. 在 cron-job.org 点 job 的 **"TEST RUN"**
2. 看去 **History** 页：
   - **状态码 = 204** → ✅ 成功（204 是 GitHub dispatches 接口的正常的空响应）
   - **401/403** → ❌ token 无效或权限不足
   - **404** → ❌ 仓库名/URL 写错
   - **422** → ❌ body 格式错（检查 JSON 引号）
3. 同时去 **GitHub → Actions** 看是否出现新运行记录

### 判据：区分触发来源

GitHub Actions 运行记录里有个 **event 字段**：

| event | 含义 |
|---|---|
| **`repository_dispatch`** | ✅ **cron-job.org 触发成功** |
| `schedule` | GitHub 原生 cron（不是你配的）|
| `workflow_dispatch` | 手动点的 |

**验证成功 = 在预期时间出现了 `repository_dispatch` 的记录。**

### 第二天自动验证

| 时间 | 应出现 |
|---|---|
| 明天 06:35 | 盘前市场报告 `[repository_dispatch]` |
| 明天 09:35 | 体系自检 `[repository_dispatch]` |
| 明天 15:05 | 全盘量化扫描 `[repository_dispatch]` |
| 明天 17:35 | 市场状态判定 `[repository_dispatch]` |

---

## 七、常见坑

| # | 坑 | 症状 | 解决 |
|---|---|---|---|
| 1 | **时区没改** | 凌晨触发 | 改 `Asia/Shanghai` |
| 2 | **Authorization 写成 `Bearer`** | 401 | 改回 `token <PAT>` |
| 3 | **body 没选 Raw** | 422 | 选 Raw 模式填 JSON |
| 4 | **event_type 写错** | workflow 不触发（204 但无反应）| 严格对照上表（如 `market-regime-run` 不能写成 `market_regime_run`）|
| 5 | **PAT 过期** | 401 | 换新 token |
| 6 | **URL 写成 `.../actions/workflows/xxx/dispatches`** | 404 | 正确是 `.../repos/{owner}/{repo}/dispatches` |
| 7 | 高频 job 触发太多 | cron-job.org 限额提示 | 降频到 30 分钟 |

---

## 八、当前状态备忘

截至 2026-09-18：

- ✅ 8 个 workflow 均已具备 `repository_dispatch` 通道（9/17 补齐 guard_selfcheck + evidence_review）
- ✅ 通道已验证可用（手动 POST 可触发成功）
- ⏳ **待完成**：cron-job.org 侧配置（用户操作中）

---

*本指南基于仓库内 9 个 workflow 的实际配置提取，事件名与 cron 值为权威值。*
