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
| **延迟数小时** | `guard_selfcheck` 应 09:30 → 实际 14:18（+4.8h）；`artifact_audit` 应 06:00 → 实际 07:45 |
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

> **本表于 2026-09-19 与 cron-job.org 实际配置逐项核对，为权威清单。**
> 原生 cron 状态：**除 evidence_review / artifact_audit 外，其余全部已停用**（避免与外部触发双跑）。

| # | Job 名称 | **event_type** | 运行时间（北京）| 周期 | 原生 cron |
|---|---|---|---|---|---|
| 1 | 产物入库审计 | **`artifact-audit-run`** | 06:05 | 周一至周五 | ⚠️ 暂留（见注）|
| 2 | 体系自检（数据源真实性+静默失败） | **`selfcheck-daily-run`** | 07:00 | 周一至周五 | 已停用 |
| 3 | 盘前市场报告 | **`premarket-run`** | 08:00 | 周一至周五 | 已注释 |
| 4 | guard备份自检 | **`guard-selfcheck-run`** | 09:35 | 周一至周五 | 已停用 |
| 5 | 盘中监控 | **`intraday-monitor-run`** | 09:00–15:45 每15分 | 周一至周五 | 已停用 |
| 6 | 全盘量化扫描 | **`quant-scan-run`** | 15:05 | 周一至周五 | 已注释 |
| 7 | 涨停型王者跟踪 | **`wangzhe-track-run`** | 15:35 | 周一至周五 | 已停用 |
| 8 | 猛兽突破池扫描 | **`beast-pool-run`** | 16:00 | 周一至周五 | 已停用 |
| 9 | 市场状态判定 | **`market-regime-run`** | 17:35 | 周一至周五 | 已停用 |
| 10 | 证据月度复核 | **`evidence-review-run`** | 每月1号 09:05 | 每月 | 保留（低频无妨）|

> **注｜artifact_audit 为何暂留原生 cron**：它 06:05 触发，而原生 cron 06:00（延迟到 07:45）——
> 两条通道并存期间保持原生兜底，等 cron-job.org 稳定运行 1-2 周后再注释。

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
| 8 | **换新 token 后未同步到所有 job** | 部分 job 401（其余正常）| 逐个 TEST RUN 排查，见 §9.3 |
| 9 | **204 但 workflow 没跑** | 界面绿勾、GitHub 无记录 | event_type 拼写错，见 §9.2 |
| 10 | **周期配成"每天"** | 周末空跑（全盘扫描 2.5h/次）| 改成周一至周五 |

---

## 八、当前状态备忘

截至 2026-09-19：

- ✅ **cron-job.org 已建 10 个 job**，覆盖全部需要定时的 workflow
- ✅ **5 个已验证有效**（GitHub 有 `repository_dispatch` 记录）：盘中监控、盘前市场报告、全盘量化扫描、市场状态判定、产物入库审计
- ✅ **原生 cron 已停用 6 个**：guard_selfcheck / intraday_monitor / wangzhe_track / beast_pool / market_regime / selfcheck_daily
- ⏳ **暂留原生 cron 1 个**：artifact_audit（双通道观察期）
- ✅ **Token 已设为永久有效**（响应头无 `token-expiration` 字段）
- ✅ **Job 周期已统一为周一至周五**（A股交易日相关）
- ⏳ **待自然验证**：体系自检 / guard自检 / 王者跟踪 / 猛兽池（周一触发时核对）

---

## 九、定期维护清单（每月核对一次）

> 下面这几项**在 cron-job.org 界面上完全看不出来**（job 永远显示绿勾），
> 只能主动去查。建议每月 1 号花 5 分钟过一遍。

### 9.1 🔴 Token 有效期（最隐蔽 —— 曾差点导致全线瘫痪）

**症状**：token 到期后**所有 job 集体 401**，但界面仍显示绿勾，极难定位。

**检查方法**：任一 job → **TEST RUN** → 弹窗点 **DETAILS** → **RESPONSE** 标签，看响应头：

```
github-authentication-token-expiration: 2026-09-20 14:25:57 UTC
```

| 情况 | 含义 | 动作 |
|---|---|---|
| **有**该字段 | token 有到期日 | 记下日期，**到期前更新** |
| **无**该字段 | ✅ 永久有效 | 无需处理 |

> **真实案例（2026-09-19）**：配置时 token 误选 1 天有效期，响应头显示次日即过期。
> 若未察觉，**周一全部 job 会 401**。现已改为**永久有效**。
> 教训：配置时若手滑选了短有效期，界面毫无提示，只有翻响应头才能发现。

### 9.2 触发记录双向核对（防止 event_type 写错）

**症状**：cron-job.org 显示 `204 Successful` + 绿勾，但 GitHub **什么都没发生**。

**原因**：GitHub dispatches API 对**任何** event_type 都回 204，即使没有 workflow 监听。
拼错一个字符（如漏掉 `-run` 后缀）就是这种"假成功"。

**核对方法**（两边记录对起来看）：

1. **cron-job.org**：每个 job 的 **History** → 记下 `Executed` 时刻
2. **GitHub**：`https://github.com/wuhj-hub/bg/actions/workflows/{name}.yml` → 看 **Event** 列
3. **两边对不上 = body 写错了**

### 9.3 Token 轮换 SOP（换 token 的连带影响）

**⚠️ 重新生成 token 会立即作废旧的**，而 token 存在多处，必须同步：

| 存放位置 | 数量 | 更新方式 |
|---|---|---|
| **cron-job.org 的每个 job** | 10 个 | 逐个 EDIT → HEADERS → 改 `Authorization` |
| **沙箱/本地脚本环境变量** | 1 处 | 重设 `GITHUB_TOKEN` |
| GitHub Actions 自身 | — | 一般不受影响（用 `github.token`）|

**轮换后必做**：对每个 job 点一次 **TEST RUN**，确认返回 **204**（不是 401）。

> 案例（2026-09-19）：换 token 后沙箱立即 401，因为环境变量还是旧值 —— 这类"单点未同步"很常见。

### 9.4 重复 job 检查

同一 workflow 配了 2 个 job → 一天触发多次。
（曾发生：`market-regime-run` 在 09:35 与 09:45 各触发一次）

**检查方法**：见第四章「🔍 如何自查 cron-job.org 上到底配了什么」。

### 9.5 时间与周期检查

| 项 | 正确值 | 错误后果 |
|---|---|---|
| **Timezone** | `Asia/Shanghai` | 不改 → 凌晨触发 |
| **周期（A股相关）** | 周一至周五 | 配成"每天" → 周末空跑（全盘扫描 2.5h/次，严重浪费额度）|

---

*本指南基于仓库内 14 个 workflow 的实际配置提取，事件名与 cron 值为权威值。*
*最后核对：2026-09-19*
