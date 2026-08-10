# bg 全量扫描体系 — 更新迭代记录

> 仓库：wuhj-hub/bg
> 工作流：全量扫描（复盘报告数据源）— `full_market_scan.yml`

---

## v2.7 (2026-07-26)

### 🐅 猛兽体系 v3.0 — 猛兽派选股公众号全公式集成

**核心指标升级：**
- **VAD指标替代TSI**：源自威廉姆斯成交量累积派发线，顶底背离识别更精准
- **OVS精确公式**：PV2/PV3/OV3标准计算（涨幅×成交金额），替代自研评分
- **SSV量价加权强度(200日)**：量价加权相对强度，新阈值SSV>100为强势区
- **RSL个股平均(144日)**：RSLine量价加权版，手机端也可使用
- **RS_D背离值(N=5/4双参数)**：斜率差底背离，低吸信号检测
- **伏击线低吸**：低波动率低吸点识别（M=5, N=20）
- **M8枢轴点检测**：缠论底分型+量价指标综合
- **G点检测(新版阈值)**：堆量间隙弱转强，PV3>55+OV3>45
- **双模式分类**：堆量模式(小盘) / 欧马模式(中大盘)自动识别

**双弦系统 v2.3 — 猛兽融合版：**
- Step0 大盘评分：猛兽三指数加权(上证×0.3+中证全指×0.4+深证综指×0.3)
- Step2 个股评分：VAD+OVS+SSV替代原MACD/RSI技术评分
- Step4 AND门控：冷市模式(温度<40)下需猛兽强信号(VAD>5/SSV>100/堆量)突破
- Step5 低吸检测：RS_D背离+伏击线+G点三维替代原VAD简版
- Step6 轮动报告：新增/移除/留存/轮动率跟踪（`format_rotation_report()`）
- 新增 `monthly_review.py`：月度自检机制（健康检查+质量评估+改进建议）

**配置：**
- `beast_screener.py`：OVS(N1=2,N2=4,M=15/13), VAD(N=14), SSV(N=200), RSL(N=144), RS_D(N=5/4), 伏击线(M=5,N=20)
- `run_shuangxian.py`：引入猛兽函数库，冷市门控+轮动报告+月尾自检提醒

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

---

## v2.6 (2026-07-24) — 全盘量化体系升级

### 🏷️ 命名统一
- **GitHub workflow**: `全量扫描（复盘报告数据源）` → `全盘量化扫描`
- **IMA 报告文件**: `盘后量化_*.md` → `全盘量化报告_*.md`
- **IMA CSV 文件**: `全量扫描数据_*.csv` → `全盘量化数据_*.csv`
- **脚本标题**: `# 盘后量化报告` → `# 全盘量化报告`
- **文件夹映射修正**: upload_main(盘后量化)→全盘量化文件夹, upload_extra(quant预运行)→复盘报告文件夹

### ✨ 新功能
- **主力信号专表** `full_market_dualdim.py`：新增 §三「主力信号专表（含低价标注💰）」，列出全部主力偏强放量(24)+主力控盘(4)+主力主导放量(1)个股，沉淀率降序排列
- **CSV上传**: 新增 `upload_csv` 步骤，全量扫描CSV同步到全盘量化文件夹，供盘前报告引用做④.4低价股池跟踪
- **CSV增加price字段**: 全量扫描CSV新增 `price` 列，便于下游按价格筛选

### 🤖 自动化
- **盘前报告自动化** `premarket_report.yml`：交易日 08:00(BJT) 自动生成盘前市场报告 → 上传盘前报告文件夹 → 推送手机
- **复盘报告自动化** `gen_review_report.py`：全盘量化扫描完成后自动生成复盘报告 → 上传复盘报告文件夹 → 推送手机
- **推送升级** `push_notify.py`：推送内容增加趋势对比表和关注池信号变动预警

### 🐛 修复
- **文件夹ID错误**: upload_main 使用错误的文件夹ID(`folder_7485234585034`)导致报告上传后无法在知识库找到 → 修正为 `folder_7485264708529742`(全盘量化)
- **CSV上传语法错误**: `\$` 转义符在GitHub Actions runner中导致shell语法错误 → 修正为正常 `$((i*10))`
- **Workflow空文件事故**: sed嵌套引号导致workflow被写为空文件(0字节) → 手动重建恢复(123行完整内容)

### 🗂️ IMA知识库结构
```
📁 报告
├── 📁 盘前报告 — 盘前市场报告_YYYY-MM-DD.md（交易日08:00自动出）
├── 📁 全盘量化 — 全盘量化报告_YYYY-MM-DD.md（含§三主力信号专表）
│               └─ 全盘量化数据_YYYY-MM-DD.csv（原始全量数据）
└── 📁 复盘报告 — 复盘报告_YYYY-MM-DD.md（盘后自动生成）
```

### 📊 7/24 量化扫描数据(参考)
- 扫描范围: 沪深主板(剔除科创/创业/北交所/ST) ≈ 2945只
- 信号分布: 主力主导放量🔥1只 + 主力偏强放量24只 + 主力控盘4只 + 游资情绪105只 + 情绪退潮2156只
- 关注股池轮换: ❌灵康药业/红豆股份/日发精机 → ✅甘咨询(🔥最强)/海南瑞泽(💰控盘)/湘财股份(💰放量)

---

## v2.8 (2026-08-10)


### 🔧 优化

- chore: update quant/fish_latest (2026-08-10) (0ffa688)