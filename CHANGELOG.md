# bg 全量扫描体系 — 更新迭代记录

> 仓库：wuhj-hub/bg
> 工作流：全量扫描（复盘报告数据源）— `full_market_scan.yml`

---

## v2.5 (2026-07-23)

### 三系统全量主板改造（并行版）

- **双弦系统** `run_shuangxian.py`：从 8 只硬编码标的 → 读 `all_mainboard.csv` 全量主板 ~2000 只，`ThreadPoolExecutor(max_workers=8)` 并发评分（technical + asfund），保留 3 核心标的独立评分
- **猛兽系统** `beast_screener.py`：候选来源从 `hot stock --limit 50` 精选 → 读 `all_mainboard.csv` 全量主板 OVS 扫评（高分进 Setup+引擎）
- **并行调度** `run_all_quant.py`：双弦+鱼身+猛兽三系统从串行 → `ThreadPoolExecutor(max_workers=3)` 并行执行
- 效果：覆盖范围扩大 **250 倍**（8→2000 只），预运行时间 **31→30 分钟**（不增反降）

### 板块过滤规则

```
NOT(CODELIKE('688')) AND NOT(CODELIKE('300')) AND NOT(CODELIKE('301'))
AND NOT(CODELIKE('8')) AND NOT(CODELIKE('43')) AND NOT(CODELIKE('92'))
AND NOT(NAMELIKE('ST')) AND NOT(NAMELIKE('*ST'))
```

---

## v2.4 (2026-07-23)

### ima 上传自愈机制

- 上传步内置 **3 次自动重试**（间隔 10/20/30s），应对瞬时网络/限流
- **401 智能识别**：重试中检测到 `401` / `skill auth failed` 立即判定凭证失效（写 `IMA_CRED_EXPIRED=true`），停止无谓重试
- **PushPlus 升级告警**：`push_notify.py` 按 `IMA_UPLOAD_OK` / `IMA_CRED_EXPIRED` 动态推送：
  - 正常：已同步 ima + 结果摘要
  - 凭证失效：`⚠️ima凭证失效 请重置`（含 ima.qq.com/agent-interface 链接 + 需更新的 Secret 名 + 操作指引）+ 结果备份
  - 其他失败：结果备份
- 推送 step `if: success()` → `if: always()`，不再依赖 ima 上传成功

---

## v2.3 (2026-07-23)

### OpenAPI 401 根因定位与修复

- **根因定位**：旧 `client_id 826d...` 对应 OpenAPI 应用失效/被撤销（非 api_key 拼错），多组不同 api_key 均返回 `skill auth failed`
- **修复**：在 ima.qq.com 重新获取 API Key 生成新凭证（client_id `89568ef...`），更新 GitHub Secrets：`IMA_OPENAPI_CLIENTID`、`IMA_OPENAPI_APIKEY`、`IMA_KB_ID`
- **闭环验证**：样本上传 run → 全量扫描 run 双重 `success`，整条流水线（扫描→鱼身池→预运行→上传→通知）全绿
- **环境变量**：认证头 `ima-openapi-clientid` + `ima-openapi-apikey`，路径 `https://ima.qq.com/openapi/wiki/v1/create_media`

---

## v2.2 (2026-07)

### 鱼身动态股票池 + 全量扫描

- 新增 `gen_fish_pool.py`：按近 20 日日均成交额排名前 **300 只**主板股，生成 `stock_pool.txt`
- 鱼身系统从 core 固定池（~30 只）切换到动态池（~300 只），覆盖范围扩大 10 倍
- `full_market_dualdim.py` 全量双维扫描上线：~3000 只主板股逐只 K 线+资金扫描
- `gen_mainboard.py` 生成沪深主板清单 `all_mainboard.csv`

---

## v2.1 (2026-07)

### 三系统预运行调度

- 新增 `run_all_quant.py`：串行调度双弦+鱼身+猛兽三系统
- 子进程超时从 600s → 1800s（修复因 timeout 导致的漏算）

---

## v2.0 (2026-07)

### 全市场量化扫描上线

- `full_market_scan.yml` 工作流创建
- 交易日 15:30 定时全量扫描 → 上传 ima「复盘报告」知识库
- 双弦、鱼身、猛兽三系统预运行
- PushPlus 推送通知
