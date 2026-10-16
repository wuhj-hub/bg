# bg 全量扫描体系 — 更新迭代记录

> 仓库：wuhj-hub/bg
> 工作流：全量扫描（复盘报告数据源）— `full_market_scan.yml`

---

## v2.47 (2026-10-17)

### 反转数值·日线 — 报告补历史展示（修复跟踪池持久化）+ 新增「突破段中大阳线」条件

- **修复(真 bug)：反转数值跟踪池从未持久化** —— `data/reversal_pool_*.json` / `data/reversal_perf_*.csv`
  列在「提交报告产物」清单（`quant_report.yml` L478），但**那一步在反转脚本运行（L516-520）之前**
  → 提交时池文件尚不存在 → `git_api_commit` 跳过 → 池从未入库 → 报告每天「新增 N、在池 0、移除 0」，
  看不到「该日期前符合的」（与 2026-10-15 复盘报告同款坑）
  - 修法：把 6 个文件从该清单移除，改为**反转脚本运行后立即单独提交**（`chore: reversal pools`）
  - 修复后「之前符合、今天仍有效」的标的正显示在「📌 在池跟踪」；首次运行池从空建立，次日起在池生效
- **新增(需求)：突破段中大阳线条件** —— 突破 2 倍反转数值的过程中（突破日所属「金叉」→「突破日」整段），
  须出现至少一根涨幅 ≥ `--big-yang-pct`（默认 **5%**）的阳线（**涨停板自然满足**）；**仅日线生效**，周/月线保持原口径
  - `eval_state(rows, big_yang_pct=…)` 返回 `big_yang/by_date/by_gain`；报告新增「突破段阳线」列
    （显示启动段最大阳线的日期+涨幅）；摘要推送同步
  - 实测（全主板样本 200 只）：金隅冀东(sz000401) 启动段最大仅 +3.11% → 被过滤；
    山东路桥(sz000498, +5.69%)、国新健康(sz000503, +10.06% 涨停) → 保留
- **加固**：`reversal_daily_screener.py` 取数增加本地 westock CLI 兜底（`_westock_run`）——
  `fetch.raw` 不可用/空返回时回退，避免无数据（原实现只走 `_fetch_layer`，无兜底）
- 提交：`quant_scripts/reversal_daily_screener.py` · `.github/workflows/quant_report.yml`

---

## v2.46 (2026-10-17)

### 体系自检 · 归因层（B1）

- 新增 `quant_scripts/attrib.py`：把自检的「X 失败」升级为「X 失败，**疑似原因 Y**」——**只建议、不自动改**
  - 读 artifact_audit / pipeline_audit / silent_failure / param_contract（+cross_source）产物
  - 规则 + **跨信号关联**（如"产物停更"×"同期 run 异常" → 归因到上游 run）
  - 每条附**证据来源**与**置信度**（高/中/低）；🔴/🟠/🟡 分级
  - 产物 `outputs/归因_latest.md` + `outputs/attrib_latest.json`
- `selfcheck_daily.yml`：新增「⑤ 归因分析」步；归因产物纳入提交清单 + 微信告警 + KB 上传
- 边界：**自动修复（B2）暂缓**——避免误修制造新的静默故障

---

## v2.45 (2026-10-16)

### 分支 B · P2 编码 + 收尾（qiankun_a / 四维共振 / 板块共振 + 指标注册表）

- `quant_scripts/metrics.py` 增补 accessor：`qiankun_info/stocks`、`quad_info/stocks/total`、`sector_res_info/boards/zhongjun`（f7c5595b07）
- 消费者迁移：`signal_arbiter.load_qiankun` + `load_four_dim`（13c67393bc）、`sector_divergence.load_latest_board`（a155c8e59b）
- **影子对拍**：三处旧 vs 新 → 0 差异（qiankun/four_dim/sector_board）
- 新增 `docs/指标注册表_2026-10-16.md`：把「指标→生产者→关键字段→消费者→accessor」固化为显式契约
- 修复隐患：P2 的 signal_arbiter 改从**当前仓库版**重建（避免覆盖 P1 的 load_rsv 迁移）
- 分支 B 三批（P0/P1/P2）完成；未迁项（intraday_monitor 内联块 / helper 读取者 / 长尾）已登记

---

## v2.44 (2026-10-16)

### 分支 B · P1 编码（rsv_strength / 信号仲裁 / yearline 迁入 metrics）

- `quant_scripts/metrics.py` 增补 accessor：`rsv_info/rsv_lists/rsv_launch`、`arb_info/arb_ranked/arb_operations/arb_counts/arb_sources/arb_date`、`yearline_info/yearline_ratio/yearline_level`（bd42ab80a8）
- 消费者迁移（取数收口到 metrics，原逻辑保留兜底）：
  - rsv：`beast_screener.load_rsg_map`(2cd9ae1a87) · `fish_body_enhanced.load_rsg_map`(0863c1ffd5) · `signal_arbiter.load_rsv`(ba953836dc)
  - arbiter：`execution_card.load_pool_candidates`(3635b4f3e7)
  - yearline：`env_engine.load_structure`(7bd09d2cc2)
- **影子对拍**：逐个函数 旧 vs 新 → **全部 0 差异**（load_rsg_map×2 / load_rsv / load_pool_candidates / load_structure）
- 有意未迁：`intraday_monitor.load_dynamic_pool` 的 arbiter 子块（多源函数内联，动手风险 > 收益）→ 留 P2

---

## v2.43 (2026-10-16)

### 分支 B · P0 编码（指标只读访问层 metrics.py + env dogfood）

- 新增 `quant_scripts/metrics.py`：指标**只读访问层**（`report_io` 的姊妹）
  - `load(name)` / `get(name,*keys)`：多副本交 `report_io` 选最新；缺失一律 `None`（不假装中性）
  - accessor：`safety_score()`（收口猛兽「安全评分」正则 + premarket 回退）、`width_raw/level/normalized()`（收口 market_width 的「50≈中性」下压锚点）
  - 登记 top-8 指标；rsv_strength/arbiter/qiankun_a/yearline/quad/sector_res 留待 P1/P2
- `quant_scripts/env_engine.py` dogfood：`load_index_trend`→`metrics.safety_score_info()`、`load_width`→`metrics.width_info()`、`ANCHORS["width"]`→`metrics.WIDTH_ANCHORS`（原逻辑保留为兜底）
- **影子对拍**：同一批真实产物，旧逻辑 vs 新 → **0 差异**（temp 33.7 / 6 子分全等）
- 只读、不改业务逻辑；失败回退原实现

---

## v2.42 (2026-10-16)

### 副本治理 · skills_backup 归档定位明确化

- 结论：`skills_backup/`（14 个已发布技能的仓库内备份）**不删除**——由 `guard_selfcheck.py` / `quant_scripts/guard.py` 每日守护完整性
- 新增 `skills_backup/README.md`：声明「归档目录、非线上运行目录」；标注唯一 CI 例外 `盘前市场报告/scripts/market_charts.py`
- `quant_scripts/sync_hot_emotion.py`：移除指向 `skills_backup/.../outputs/` 的**死兜底路径**（该目录在仓库中不存在），回到 canonical 单一来源
- 效果：`skills_backup/` 不再计入指标「语义消费者」统计（分支 B 范围不受副本稀释）

---

## v2.41 (2026-10-16)

### 分支 B · 指标层标准化（对账 + 设计定稿，docs）

- 新增 `docs/指标消费对账_2026-10-16.md`：静态扫描 258 脚本+23 workflow，定位 50 个 `*_latest.json` 的生产者/消费者/字段
  - 语义消费者 ≥4 的 **18 个**为分支 B 对象；长尾 21 个（≤1 消费者）不动；审计类消费者已由 `daily_artifacts.json` 覆盖
  - 三类实证：`market_width.score` 语义散落、`quant_results` 文本被多处正则解析、`hot_emotion` 有 6 个副本消费者
- 新增 `docs/metrics_registry设计_2026-10-16.md`：`metrics.py` 指标只读访问层设计（top-8 试点）
  - 接口：`load/get` + 字段级 accessor（把「字段定义+语义修饰」收口）；只读、缺失返回 None、不改业务逻辑
  - 迁移清单 + 影子对拍方案（一次一指标、切前对拍、切后当天 CI）+ 前置项（skills_backup 副本去留）
- 结论：分支 B 有价值但**只做热点 ~18 个、先 top-8 试点**，不主张全量重构

---

## v2.40 (2026-10-16)

### env 环境唯一化 · 新增第 6 子分「入牛广度」

- `quant_scripts/env_engine.py`：5 子分 → **6 子分**，新增 `inbull`（月线 5 力·入牛个股占比 %；源 `入牛时点_latest.json` 的 `breadth_pct`）
- 权重重分配（加总 = 1.00）：index_trend .28 / emotion .20 / width .18 / breadth .16 / structure .09 / **inbull .09**
- 锚点：`inbull [(0,0),(6,20),(12,40),(15,55),(20,72),(25,85),(40,98),(100,100)]`（对齐入牛三档 12/15/20 与回测中位 非牛 7.8 / 牛 39.1）
- 新增背离 `structure_vs_inbull`（慢变量内部一致性）
- 兼容性：消费方（gen_premarket_report / env_compare）均泛化读取，`subs` 增键向后兼容；缺失时 degraded + 权重按比例分摊
- 验证：AST OK + 沙箱冒烟（含 inbull → 温度 47.9 / 缺失 → 50.4 + degraded）

---

## v2.39 (2026-10-16)

### 取数层 阶段 3 · B 类残留清理

- 把 15 个「已 import fetch 但仍自建 westock」的脚本取数函数迁入 `fetch.raw`（插入式，保留兜底）：
  `beast_screener` `gen_premarket_report` `gen_review_report` `inbull_scan` `limitup_concept_rank`
  `month_frame` `monthly_macd_monitor` `portfolio_risk` `rsv_strength` `scan_123_2b` `top_signal`
  `xihu_breadth` `xihu_rsv` `wangzhe_track` `wangzhe_funnel`（commit 26432cea…e93031ed）
- wangzhe_track/wangzhe_funnel：新增模块级 `_fp(args,timeout)` 助手（fetch-first），替换 5 处内联 subprocess
- **有意保留** `cross_source_check.westock_close`（源自检基准，直连原始 westock）
- 验证：AST OK + 沙箱冒烟全走统一层（kline 349B / `_run_kline` 2×3 bars / `_fb` 2×3 bars）
- 更新 `docs/取数层迁移进度.md`（B 类残留 16 → 1）

---

## v2.38 (2026-10-16)

### 取数层 阶段 3 · 批次 4（其余 A 类收口）

- **批次 4a**（12 脚本；commit df5b3e83…7c10d8e3）：`jinji_emotion_backtest` `learn_weights`
  `liangxue_minute_check` `liangxue_month_join` `liangxue_screener` `longtou` `monthly_pool_sync`
  `paper_tracker` `pool_winrate_biweekly` `weight_change_review` `win_rate_tracker` `caige_pool`
- **批次 4b**（3 脚本；commit ac37de3d/20d6db26/33fbd894）：`ai_chokepoint_guard` `fetch_hot_kline` `reversal_funnel_screener`
  - paper_tracker 额外把 `get_bars_batch` 内联 subprocess 改走 `run()`（从而走 fetch）
- 手法：通用 AST 迁移器自动定位「含 subprocess+WESTOCK」的取数函数，按首参名+timeout 插入 fetch.raw 优先分支
- 验证：15 脚本 AST OK + 沙箱冒烟均走统一层返回真数据（kline 349B / 周线批量 130 bar×2 / fetch_chg120 -8.49）
- 更新 `docs/取数层迁移进度.md`（A 类 19 → 4，余 4 个为外部源工具）

---

## v2.37 (2026-10-16)

### 取数层 阶段 3 · 批次 3（盘中监控迁入统一层）

- 迁移 **`intraday_monitor.py`**（仓库根脚本；插入式，保留本地 npx 兜底；commit ddb17937）：
  `cli()` → 委托 `fetch.raw`（含 sys.path 注入 quant_scripts —— 根脚本取数层坑）
- 验证：AST OK；沙箱「根布局」冒烟 cli 走统一层（kline 349B / minute 14464B）
- 更新 `docs/取数层迁移进度.md`（A 类完全未用 fetch 由 20 → 19）

---

## v2.36 (2026-10-16)

### 取数层 阶段 3 · 批次 2（4 脚本迁入统一层）

- 迁移 **4 脚本**（插入式，保留本地 npx 兜底；commit f8eac5b2 / ff2ab6eb / d49c7b85 / 85ac9d73）：
  `data_guard._run` / `market_regime.sh` / `emotion_forecast.cli` / `kaipan_8.cli` → 委托 `fetch.raw`
- 验证：4 脚本 AST OK；沙箱冒烟 4 函数均走统一层返回真数据（kline 349B、指数批量 24557B）
- 更新 `docs/取数层迁移进度.md`（A 类完全未用 fetch 由 24 → 20）

---

## v2.35 (2026-10-16)

### 取数层 阶段 3 · 批次 1（4 脚本迁入统一层）

- 新增 **`migrate_fetch.py`**（插入式·最小侵入迁移器）：保留原 subprocess 逻辑作兜底，仅在取数函数前加「优先 fetch.raw」分支 → 行为等价、零回归
- 迁移 **4 脚本**（commit fc3e7417）：`yao_gu_pool` / `pool_tracking_report` / `pool_snapshot` / `reversal_daily_screener`
- 验证：4 脚本 AST OK；yao_gu_pool/pool_tracking/reversal 冒烟均走统一层返回正常；pool_snapshot._fetch_layer 实测 500B 含 date
- 更新 `docs/取数层迁移进度.md`（A 类完全未用 fetch 由 28 → 24）

---

## v2.34 (2026-10-16)

### 取数层 阶段 3（统一取数层调用点迁移）

- **基础设施确认完备**：`quant_scripts/fetch.py` 已含 `kline/quote/asfund/board/hotboard/minute/raw`
  + 外部源适配器（`ext_gtimg`/`ext_sina_quote`/`ext_fqkline`/`ext_em_ztpool`/`ext_ths_kline`）+ 磁盘缓存层
- **缓存已开**：quant_scan / quant_report / premarket_report / duowei_fish 的 job env（`FETCH_CACHE=1` + `FETCH_CACHE_TTL=18000`，防倒灌）
- **迁移样板**：`yearline_breadth.py` 取数委托 `fetch.raw`（免 npx + 重试退避），解析不变；沙箱冒烟 6 只样本 → 站上年线 3/6
- **新增 `docs/取数层迁移进度.md`**：59 个主链待迁移脚本清单（A 完全未用 fetch 28 / B 部分迁移 31）+ 分 4 批的推进方案

---

## v2.33 (2026-10-16)

### 数据可信度治理 11.5–11.6（契约自检扩散 + 参数契约）

#### 11.5 产物契约自检扩散到全 workflow
- `config/daily_artifacts.json` 扩容：**17 组**（quant_scan / quant_report + 新增 15 组）
- **15 个 workflow** 末尾新增「🧪 产物契约自检」步（`run_and_verify --manifest --workflow`）
- `run_and_verify.py` 支持 `{date8}`(YYYYMMDD) 占位

#### 11.6 A2 参数契约（防「传了参数但脚本不认」的静默失效）
- **实锤修复**：`gen_mainboard.py` 静默忽略 `--universe` → quant_report「创业板/科创四维补充通道」(2026-08-11 上线)**从未生效**
  - 新增 argparse `--universe {mainboard,chinext_kcb}` / `--out`；chinext_kcb = 创业板 300/301 + 科创 688/689 → `all_chinext_kcb.csv`（沙箱实测 1980 只）
  - 向后兼容：无参数仍生成主板（quant_scan / duowei_fish / yao_gu_pool 调用不变）
- `data_guard.py`：main() 增加未知 `--xxx` 参数显式告警
- 新增 `quant_scripts/param_contract_audit.py`（参数契约审计）+ 接入 `selfcheck_daily`（第 4 项自检，`--strict`）
  - 口径：脚本已知参数 = argparse add_argument ∪ 源码 `--选项` 字面量；对「无参数解析」脚本集空 → 任何传参判失配
  - 现状：**179 个带参调用，0 失配**

---

## v2.32 (2026-10-15)

### 数据可信度治理 11.1–11.4（取数层对账与设计 同源归一）

#### 11.1 消灭双副本（canonical = `outputs/`）
- 4 个 `*_latest` 原先在**仓库根 + outputs/** 各存一份 → 只保留 `outputs/` 一份
- 生产者停写根副本：`market_width.py`、`quant_scripts/env_engine.py`
- workflow：提交清单去掉根副本 + 移除 `cp` 到根的步骤（quant_scan / quant_report）
- 删除根副本：`env_latest.json` / `market_width_latest.json` / `qiankun_a_latest.json` / `四维共振_latest.json`

#### 11.2 产物契约集中化（单一事实来源）
- 新增 **`config/daily_artifacts.json`**：当日核心产物清单（`path` 支持 `{date}`，含 `min_bytes` / `producer`）
- `quant_scripts/run_and_verify.py` 新增 `--manifest <file>` `--workflow <name>`（清单驱动整批自检）
- quant_scan：**提交前**新增「🧪 产物契约自检」步（日志可随产物入库）
- quant_report：复盘步内串联契约自检（失败随复盘一并入库）

#### 11.3 清单扩容 + `optional` 语义
- 清单扩至 **quant_scan 25 项 / quant_report 16 项**
- 新增 `"optional": true`：偶发缺失仅 `::warning::`，**不计入退出码、不推送**（观察若干日稳定后转正）

#### 11.4 KB 上传「同日去重」语义
- `upload_ima.py`：新增 **`IMA_OVERWRITE`** + **自动判定**——文件名含日期（`YYYY-MM-DD` / `YYYYMMDD`）→ **同日覆盖**（旧同名条目先改名归档为 `<正名>_prev_<HHMMSS>`，再上传新版占用正名）；不含日期 → 同名跳过（原行为）
  - 背景：KB 无删除 API，旧逻辑（同名跳过）导致**同日改进版被旧版挡住 → KB 静默不更新**（10-15 复盘即此症）
- 移除 3 个 workflow 的显式 `IMA_SKIP_DUP`（jingjia_track / weight_learn / pool_winrate_biweekly），使日报类自动走覆盖

**验证**：rename_knowledge 自回滚实测通过；覆盖分支 mock 四态验证（含日期/不含日期/显式覆盖/显式跳过）均符合预期；YAML/AST 全绿。

---

## v2.31 (2026-10-15)

### P0-2「生产者产出后自检」落地 —— 让静默失败可见

**审计结论（23 workflow / 86 处脚本调用全扫）**：
- 参数契约：**53 个 argparse 脚本传参全部匹配** ✅（pool_tracking_report 是唯一失配，已修）｜32 个手写 sys.argv（未知参数静默忽略）
- 静默吞错面：**96 × `|| echo` + 103 × `continue-on-error` + 35 × `if: always()`** → 生产者崩了 CI 仍绿
- 双副本结构：4 个 `*_latest` 同时在仓库根 & outputs/（env / market_width / qiankun_a / 四维共振）→ ③.3 类僵尸温床

**新增 `quant_scripts/run_and_verify.py`**（生产者产出后自检 wrapper）：
- 校验产物：存在 / ≥min-bytes / （可选）含指定文本；支持 `{date}` 与 `*`
- 可选 `--run "<shell>"` 先执行命令；**秒退识别**（耗时 < --min-runtime → 告警，argparse/导入错误指纹）
- 异常时：GitHub 注解 `::error::` + 追加 `outputs/silent_failures_{date}.log` + 可选 PushPlus 推送
- 退出码：有问题 →1（无 continue-on-error 的步骤会显式失败）

**接线（7 处，附加式·零风险）**：
| workflow | 位置 |
|---|---|
| quant_scan | 市场宽度 / 西湖广度 / 涨停概念排行 / 一统天下多周期 |
| quant_report | 一统天下跟踪 / 第五步·股池标的跟踪 / 复盘报告 |

**🐞 顺带修复**：`outputs/复盘报告_{date}.md` 虽列在「提交报告产物」清单，但**该提交步（step 30）在复盘生成（step 31）之前运行** → 文件尚不存在 → **复盘报告从未入库 git**（KB-only 且受同名去重影响）。已在复盘步内补一次 `git_api_commit`（含 silent_failures 日志）。quant_scan 提交清单亦纳入该日志。

## v2.30 (2026-10-15)

### ③.5 断更**根因**修复 + 一统 timeout 核实 + 10-15 复盘全绿

**🐞 根因（v2.29 只改了 reader，未改生产者）**：`quant_report.yml` 第五步给 `pool_tracking_report.py` 传了 **脚本未定义的参数** `--holdings-file` 与 `--date` → **argparse 秒退 rc=2** → 两条命令（主命令 + 回退命令）全部瞬间失败 → 0.0min「success」（`continue-on-error` 吞掉）→ **默认名 `股池标的跟踪报告_{date}.md` 60+ 天未生成**。

**修复（`quant_scripts/pool_tracking_report.py`，commit 2de5cdf988）**：
- 补 `--date`（报告基准日；用于输出文件名 + 基准月）与 `--holdings-file`（读持仓码并入跟踪池）
- 顺带修 2 处硬编码：报告头「生成时间 2026-08-04 18:11」→ 动态；「信号基准月 2026-07」→ 按基准日推算上月
- 本地以 workflow 原始参数实测：rc=0，报告正常生成，基准月=2026-09

**一统 timeout 核实结论**：**不存在**。一统步（quant_scan L325 / quant_report L196）**从未设置 timeout-minutes**；本人三次改 workflow（55c4dc63/7807ccb37b/cc8e900a/174ce91c）**全部只加 FETCH_CACHE env，未碰任何 timeout**。早先 run 被 `cancelled` 的真因是 **`concurrency: cancel-in-progress: true`**（cron 新 run 取消在跑的旧 run），非超时。→ 无需 rollback。

**10-15 复盘 run #38714394719 全绿**：43/43 步 success，0 失败，含全部 30+ 迁移模块（一统 42.2min / 龙头战法 5.2min / 乖离低买 10.7min / 入牛时点 6.5min 等）。

**⚠️ 旁路发现（待决策）**：`upload_ima.py` 默认 `IMA_SKIP_DUP=1` → 同日重跑的报告**同名被跳过、KB 不更新**（10-15 修复版 复盘被 01:54 旧版挡住）。KB 无删除 API，"同日覆盖"需另设计（时间戳版/或对特定产物关 dedup）。

## v2.29 (2026-10-15)

### 又一处静默问题 + 根因修复

**症状（10-15 复盘发现）**：「③.5 股池三阶漏斗状态」**永远沿用 2026-08-11 数据**（与 03-09 修复的 ③.3 板块共振僵尸副本同一类病）。

**根因**：`read_pool_status(today)` 只认默认输出名 `outputs/股池标的跟踪报告_{date}.md`，但 `quant_report.yml` 里所有 `pool_tracking_report.py` 调用都用了 `--out-file` 自定义名（`才哥战法跟踪_*.md` / `一统天下跟踪_*.md`）→ **默认名 2 个月未生成** → `find_latest_file` 兜底永远停在 `股池标的跟踪报告_2026-08-11.md`。

**修复**（`gen_review_report.read_pool_status`）：
- 当日候选名扩展为 4 个：`股池标的跟踪报告_{date}.md` / `才哥战法跟踪_{date}.md` / `一统天下跟踪_{date}.md`（仓库根 + outputs/）
- 兜底同样按此顺序找最近一份
- 旁路发现：`outputs/` 中才哥战法跟踪_*.md 与 一统天下跟踪_*.md 数量=0 → `pool_tracking_report.py` 调用全 `|| echo` 默默失败 60+ 天（`--hide-rejected` 配合非致命标记），下一步应单独排查该脚本

### CI 冒烟 2（10-15 当日数据）
- 触发 run #38691584596：41/42 步 success，1 步「年线广度」cancelled（最后一步超时，**未影响已产出 41 步**）
- 自动带起 quant_report #38696472716（进行中，含全部 30+ 迁移模块）
- 盘前 10-15 报告 ③.3 板块主线含**当日新鲜数据**（出版/数字媒体/传媒/煤炭/影视院线/游戏Ⅱ/炼化及贸易/文化传媒概念，8 板块全部具体）—— ③.3 修复经真实数据闭环

## v2.28 (2026-10-15)

### 阶段 4 · 批次 4.5：同花顺（v6 line，差分解码）

**fetch.py** 新增：
- `ext_ths_kline(code, period="day", fq="hfq")` + `parse_ths` + `aggregate_monthly`
- 同花顺 v6 `d.10jqka.com.cn/v6/line/hs_{code}/{seg}/all.js` 差分解码：每根 bar 4 值 = [low, open−low, high−low, close−low] ÷ priceFactor；年份由 `sortYear` 推得
- **seg 语义实测**：`01`=日线前复权、`02`=日线**后复权**（约 2001 起全历史）、`11`=周线、`21`=月线
- 校验响应含 `quotebridge`（防反爬占位），带重试；多只由调用方并发（实测 12 workers 稳）

**消费方迁移**：
| 脚本 | 变更 | 对拍 |
|---|---|---|
| `inbull_threshold_monitor.py` | `fetch_ths` 走层内（日线02后复权 + aggregate_monthly） | **3 只月线全等**（302/425/306 根，逐字段 0 差异） |

一次收口了「同花顺差分解码」这一整块自研逻辑。

### 阶段 4 收尾情况
- 已覆盖外部源：腾讯（gtimg 行情 / fqkline 长历史 / gu）｜新浪（sinajs 行情 / 7×24 / ）｜东财（涨停池 / 个股）｜同花顺（v6 全历史）。
- 未迁移（均未接 CI / 体量或端点特殊）：sector_components(money.finance.sina)、beast_pool_screener+runner_fetch_em_sectors(push2delay clist 行业)、zj_filter、fetch_hist_index/fetch_history/fetch_mainboard_data。

## v2.27 (2026-10-15)

### 阶段 4 · 批次 4.4：东财（涨停池 + 个股快照）

**fetch.py** 新增：
- `ext_em_ztpool(date=None, pagesize=500)` —— 东财涨停池（push2ex getTopicZTPool）→ `{pool,qdate,tc}`；pool 字段 c/n/p(×1000)/zdp/amount/ltsz/hs/lbc/fbt/lbt/fund/zbc/hybk/zttj。非交易日 `{}`；未来日返回最近可用日。
- `ext_em_stock(code_or_secid)` + `em_secid(code)` —— 东财个股快照（push2delay stock/get，f43/f58/f59/f170→name/close/pct）。**机会源**（离线返回 None，静默跳过）。

**消费方迁移（影子对拍）**：
| 脚本 | 函数 | 对拍 |
|---|---|---|
| `limitup_concept_rank.py` | `fetch_ztpool` | 36 只涨停池逐字段**全等** + qdate 一致 |
| `wangzhe_track.py` | `scan`（涨停池段） | 36 只**完全一致** |
| `cross_source_check.py` | `_em_one` | 机会源，走层内；**沙箱 push2delay 离线无法对拍**（主机 RemoteDisconnected，与 09-29 起事实一致） |

**未迁移（未接 CI，离线工具）**：`zj_filter.py`（一次性研究脚本，硬编码日期）；`beast_pool_screener.py` / `runner_fetch_em_sectors.py`（push2delay clist 全市场行业映射，另一端点，体量较大）→ 留待 4.4b。

## v2.26 (2026-10-15)

### 阶段 4 · 批次 4.3：新浪系（行情 + 7×24 快讯）

**fetch.py** 新增：
- `ext_sina_quote(codes, batch=60, retries=3)` + `parse_sina_hq` —— 新浪 hq.sinajs（GBK，须带 `Referer: finance.sina.com.cn`）；字段 [0]名称 [1]今开 [2]昨收 [3]现价 [8]量 [9]额；自动算 pct。**与腾讯完全独立的行情体系**（cross_source_check 的必需源 B）。
- `ext_sina_news(n, with_time=False)` —— 新浪财经 7×24（zhibo_id=152）；返回 [text] 或 [{time,text}]。

**消费方迁移（影子对拍）**：
| 脚本 | 函数 | 对拍 |
|---|---|---|
| `cross_source_check.py` | `sina_quote` | 9 只标的（指数+个股）name/close/pct **完全一致** |
| `limitup_concept_rank.py` | `recent_news` | 输出一致 |
| `glm_brief.py` | `_news` | 输出一致 |
| `gen_premarket_report.py` | `get_news_7x24` | 与旧 curl 实现 **{time,text} 完全一致** |

一次性收口了「同一 7×24 源在 3 个脚本里被写 3 遍（其中 1 遍走 curl）」的重复。

**未迁移（未接 CI，离线工具）**：`sector_components.py`（money.finance.sina 板块清单+成分，双端点，体量较大）。

## v2.25 (2026-10-15)

### 阶段 4 · 批次 4.2：腾讯长历史 fqkline 适配器

**🐞 又一处静默回归（发现即修）**：腾讯 fqkline 的 **多股 `;` 批量端点已失效**（`{"msg":"param error"}`）。
`gen_fish_pool.est_batch`（2026-08-28 的「50只/批」提速）因此**一直返回 None → 静默退化为逐只**（~3000 次请求），文档里的提速说明早已失真。

**fetch.py**：新增 `ext_fqkline(codes, period, start, end, count, fq, workers, limit)` + `parse_fqkline`
- host 轮转 `ifzq.gtimg.cn → proxy.finance.qq.com → web.ifzq.gtimg.cn`（web.ifzq 长跑会被 WAF 501）
- 「收到权威响应即返回」避免对退市/空数据空耗重试；支持 `workers≤6` 受控并发
- 兼容 qfqday/hfqday/day/qfqmonth/hfqmonth/month 各键；amount=第9列(万)×10000

**消费方迁移（影子对拍，全部 0 差异）**：
| 脚本 | 函数 | 对拍 |
|---|---|---|
| `gen_fish_pool.py` | `est_batch` / `est_daily_amount` | 6 只日均成交额**逐位相同** |
| `portfolio_risk.py` | `fetch_kline` | 5 日收盘序列**完全一致** |
| `glm_brief.py` | `_ifzq` | 7 个指数(美股/恒生/上证/创业板/科创)收盘+涨跌幅**一致** |

均「优先 fetch 层、失败回退本地」。同步更正 `gen_fish_pool` 内失效注释。

## v2.24 (2026-10-15)

### 阶段 4 启动 · 外部独立源适配器（批次 4.1：腾讯行情）

**背景**：31 个脚本直连 9 类外部源（腾讯/新浪/东财/同花顺/开盘啦…），各自「拼 URL + 手写解析 + 各自重试」，是取数标准化最后一层。

**本批（腾讯行情）**：
- `fetch.py` 新增 `parse_gtimg(raw)` + **`ext_gtimg(codes, batch=50, retries=3)`**（qt.gtimg.cn，GBK，带重试）。
  字段位实测：1名称 3现价 4昨收 5今开 6量(手) 32涨跌幅% 33最高 34最低 37额(万) 44流通市值(亿) 45总市值(亿) 47涨停 48跌停。
- `quote()` 改为委托 `ext_gtimg`（向后兼容，返回 name/price/prev_close/open）。
- 消费方迁移（影子对拍，包裹式「优先 fetch 层、失败回退本地」）：
  - `quant_scripts/st_guard.py` `fetch_names` → ext_gtimg（8 只逐一对比 **0 差异**）。
  - `gen_mainboard.py` `fetch_names_batch`（新）→ ext_gtimg（含 ST 批次 **0 差异**，36 只 + 含 ST/PT 批次全等）。

**待办（阶段 4 剩余批次）**：4.2 腾讯长历史 fqkline（gen_fish_pool/fetch_hist_index/fetch_history）｜4.3 新浪（hq.sinajs→行情、zhibo→7x24 资讯、money.finance→行业成分）｜4.4 东财 push2ex 涨停池（limitup_concept_rank/wangzhe_track/beast_pool_screener）｜4.5 同花顺月线（inbull_threshold_monitor）。

## v2.23 (2026-10-15)

### 修复「根目录脚本无法导入 fetch」+ sector_flow 收口（阶段 3 收尾）

**🐞 关键静默 bug**：`fetch.py` 位于 `quant_scripts/`，而 **7 个根目录脚本**（`market_width / market_style / minute_strength / full_market_dualdim / signal_arbiter / quad_resonance / sector_resonance_local`）在 CI 中以 `python3 xxx.py`（cwd=仓库根）运行 → `sys.path[0]=仓库根` → `from fetch import ...` **必然 ImportError**（被 try/except 吞掉）→ 取数层形同虚设。
- 实测复现：隔离目录（脚本在根、fetch 在 quant_scripts）下 `market_style.fetch_kline_map` 返回 `{}`。
- 修复：所有根目录脚本在 `sys.path` 中**追加 `<root>/quant_scripts`**；修复后隔离目录实测各函数全部返回真实数据（kline_map 5×2、batch_asfund 2 条、fetch_month_closes 5 点、_board_text 1140B）。
- `quant_scripts/*` 下脚本不受影响（其 `sys.path[0]` 已是 quant_scripts）。

**fetch.py**：新增 `raw(args)` 通用透传 —— 供尚未标准化的子命令（如板块级 `asfund --market all`）复用「免 npx / 重试退避 / 超时」。

**`premarket_scripts/sector_flow.py`**：板块级 asfund 改为 `fetch.raw`（包裹式，失败回退 npx）。
> ⚠️ **实测发现**：本版 westock **已不支持 `asfund --market all`**（返回用法提示/空）→ 该模块的资金榜**功能已失效**，且**未被任何 workflow 引用**（23 个 workflow 全无）。板块级资金建议改用已标准化的 `fetch.board()`（含行业/概念 + 资金）。

## v2.22 (2026-10-15)

### ⚠️ 修复一次自致回归 ＋ 阶段 3 asfund 消费方迁移（8 文件）

**回归原因（重要教训）**：迁移过程使用了**静态源码镜像 `bg_src`** 作为编辑基线；当同一文件**第二次**被编辑时（如先做 kline 迁移、再做 board/asfund 迁移），基线仍是**旧镜像**，导致后一次提交**覆盖回**前一次迁移。
**受影响并已恢复的 5 个文件**：
- `gen_premarket_report.py`（丢失 fetch_kline_table 8 处 + calc_zengxingzhi 修复）
- `gen_review_report.py`（丢失 fetch_kline_table 3 处）
- `market_style.py`（丢失 fetch_kline_map）
- `beast_screener.py`（丢失 parse_kline_df 迁移）
- `full_market_dualdim.py`（丢失 batch_fetch_kline 迁移）
> 已全部按「当前仓库版本 + 丢失改动」重建，并做 27 文件标记全量核对 = **all-ok**。
> 规范（此后执行）：**任何回写前先从仓库取当前内容为基线**，绝不使用静态镜像。

**本批 asfund 消费方迁移**（均以当前版本为基线）：

| 文件 | 迁移点 | 影子对拍 |
|---|---|---|
| `quant_scripts/limitup_concept_rank.py` | `fetch_fund()` | 5 只 / **0 差异** |
| `quad_resonance.py` | `batch_asfund()`（保留本模块 tag 映射） | 5 只 / **0 差异** |
| `quant_scripts/fish_body_enhanced.py` | asfund → `fetch_asfund_rows()` | 修复「裸尾码恒空」（0→1 行） |

- `fish_body_enhanced` 实证：旧代码用**裸 6 位码**调 asfund → 恒返空（fund 维度失效）；新层自动 `norm()` 加前缀 → 恢复。测试例：`asfund 600519`=0 行、`asfund sh600519`=1 行。

## v2.21 (2026-10-15)

### ⚙️ 阶段 3 推进：缓存铺开 3 条流水线 ＋ 板块/资金消费方迁移（6 文件）

**① 缓存铺开**（job 级 env，同一次运行内跨 step 复用取数）：
- `quant_report.yml`（盘后）`FETCH_CACHE=1 / TTL=18000`
- `duowei_fish.yml`（盘后）`FETCH_CACHE=1 / TTL=18000`
- `premarket_report.yml`（盘前，数据全为历史已完结）`FETCH_CACHE=1`（TTL=0 即安全复用）

**② 消费方迁移**（board / hotboard / asfund → 统一取数层；均保留本地回退）：

| 文件 | 迁移点 | 影子对拍 |
|---|---|---|
| `sector_resonance_local.py` | `board()` + `hotboard()` | 文本**全等**(1140/585) |
| `market_style.py` | `hotboard()` | 文本**全等**(585) |
| `quant_scripts/beast_screener.py` | `board()`（2 处） | 文本**全等**(1140) |
| `quant_scripts/gen_premarket_report.py` | `hotboard()`（limit 10/5） | 文本**全等**(1033) |
| `quant_scripts/gen_review_report.py` | `hotboard()`（limit 10/5/8） | 文本**全等**(853) |
| `full_market_dualdim.py` | `batch_fetch_asfund()` | 37 只 / **0 差异** |

统一采用「优先 fetch 层、失败回退本地 run/cli」的包裹式适配，无需改调用点的解析逻辑。
**待迁**：`quad_resonance.batch_asfund`（自带 tag 映射）、`limitup_concept_rank.fetch_fund`（6 位码映射）、`fish_body_enhanced` 的 asfund、`premarket_scripts/sector_flow.py`。

## v2.20 (2026-10-15)

### ⚙️ 第 2 层·阶段 3 启动：取数层扩展 + 打开缓存（fetch v0.2）

**`quant_scripts/fetch.py` v0.2**（统一取数层）新增收口 + 缓存：

| 新增 | 说明 |
|---|---|
| `asfund(codes, date=None)` | 资金（westock asfund；内部自动 `norm()` 加前缀——实测**裸代码返空**，须 `sh600519`） |
| `board()` / `hotboard(limit)` | 板块原始文本（westock board / hot board） |
| `minute(code, days=None)` | 分时（westock **minute** 子命令；单只——批量报 `code param error`） |
| **磁盘缓存** | opt-in：`FETCH_CACHE=1`（+ `FETCH_CACHE_TTL` 秒）；默认目录 `/tmp/bg_fetch_cache`（**不落仓库**，跨 step 共享、跨运行隔离） |

- 实测修正：本版 westock **已不支持 `kline --period m1`**（仅 day/week/month/season/year），分钟数据改走 `minute` 子命令 → `_PERIOD_OK` 同步收窄。
- 缓存**防倒灌规则**：只信任「最后一根 bar 日期 < 今天(北京)」的缓存（=历史已完结）一律复用；同交易日数据默认重取，仅当显式 `FETCH_CACHE_TTL>0` 才允许同日短期复用；写入时旧数据更晚则不覆盖。
- 冒烟：kline 1.32s→**0.11s**、月线 1.06s→**0.04s**；`asfund`/`minute`/`board`/`hotboard` 均实测取到数据；默认（未开）不产生任何缓存目录 = 零行为变化。

**`.github/workflows/quant_scan.yml`**：`scan` job 级 env 打开 `FETCH_CACHE=1`、`FETCH_CACHE_TTL=18000`(5h)——同一次盘后运行内，21 个已迁移脚本对同一批全市场 K 线**首个取、其余复用**。

## v2.19 (2026-10-15)

### 🐛 第三例「列错位」修复（signal_arbiter 月线闸门） ＋ 阶段 2 第八批迁移（4 个）

**修复**：`signal_arbiter.py` 的 `month_gate()`（月线闸门 PASS/WARN/BLOCK）原硬编码 `parts[3]` 当 close，单股月线列序下实为 **high** → 与 `monthly_macd_monitor`、`gen_premarket_report.calc_zengxingzhi` **同族缺陷**。改为表头取 close + 取数委托。
- 实证差异：sh600519 旧 BLOCK→新 **WARN**；sz300750 旧 `?`→新 **BLOCK**；其余（sz000001/sz300750/sh601318/sh000001）亦有别。即此前**月线闸门对部分个股判定错误**，现已校正。

| 迁移脚本 | 迁移点 | 影子对拍 |
|---|---|---|
| `quant_scripts/xzz_force.py` | `kline()`（指数批量 月/日） | 9 指数 **0 差异** |
| `minute_strength.py` | `fetch_preclose()` | 4 只 **0 差异** |
| `full_market_dualdim.py` | `batch_fetch_kline()`（qfq） | 37 只 **0 差异** |
| `signal_arbiter.py` | `month_gate()` | 修复型（见上） |

- **累计已迁移 25 个 kline 调用点**。
- ⏸️ **未迁移（保留观察）**：`sector_resonance_local.py` 的板块 kline（pt 代码）——本环境 `board` 输出已无 `pt` 列、`kline ptXXXXXX` 返回空，**无法影子对拍**，故不动（待环境支持或换验证方式）。

## v2.18 (2026-10-15)

### 🐛 又修复一例「按批量列序解析单股输出」缺陷 ＋ 阶段 2 第七批迁移（4 个）

**修复**：`gen_premarket_report.py` 的 `calc_zengxingzhi()`（曾星智+双弦双体系市场定性）内联解析按**批量列序**读 `parts[1]/[3]/[4]/[5]`，但 kline 是**单股调用（无 symbol 列）** → 恒不匹配 → `data` 恒空 → **盘前报告该定性表长期为空**。改为表头驱动（`fetch_kline_table`）。
- 实证：修复前 `lines_len=0 / 判定「🟡震荡结构」bear=0 bull=0` → 修复后 8 大指数定性表齐全、`🐻 熊市结构` bear=8 bull=0。

| 迁移脚本 | 迁移点 | 影子对拍 |
|---|---|---|
| `gen_premarket_report.py` | 8 处 kline（含美股三大指数 batch） | 6 组对拍 **0 差异** |
| `gen_review_report.py` | 3 处 kline | 3 组 **0 差异** |
| `quant_scripts/beast_pool_screener.py` | `westock_kline()` | 37 只 **0 差异** |
| `quant_scripts/inbull_threshold_monitor.py` | `fetch_westock()` 月线 | new ⊇ old，值级 **0 差异** |

- **累计已迁移 21 个 kline 调用点**。
- 新增 `fetch_kline_table()` 通用小适配（返回 date 升序、键同 westock 表头、值为字符串），盘前/复盘共用同一语义。

## v2.17 (2026-10-15)

### 🐛 修复 monthly_macd_monitor 月线解析列错位 ＋ 阶段 2 第六批迁移（2 个）

**修复**：`quant_scripts/monthly_macd_monitor.py` 的 `parse_monthly()` 原硬编码 `parts[3]` 当 close，而单股月线列序为 `date|open|last|high|low` → 实际取到 **high**（列错位）。改为**表头驱动**取 `last/close`，并把取数委托 `fetch.kline`。
- 实证修正：2026-10 该行 close 由 3864.12(high) → **3767.23(真收盘)**；DIF 162.9→153.4、DEA 195.0→188.6、柱 -64.2→-70.3；近12月柱体路径改变（新序列更早转负）。
- 影响面：该脚本由 `quant_scan.yml` 第二步.1.8 运行 → `monthly_macd_latest.json` → **盘前报告「📉 月线MACD」行**（Seaborg 方法论）。故盘前报告该行数值/临界判定随之校正。
- 当前状态值两版同为「已死叉」，无方向性翻转；但历史临界时点会变。

| 迁移脚本 | 迁移点 | 影子对拍 |
|---|---|---|
| `market_style.py` | 指数批量 kline → `fetch_kline_map()` | 6 指数 / **0 差异** |
| `quant_scripts/inbull_scan.py` | `fetch_all()` 月线批量 | new ⊇ old，值级 **0 差异** |

- **累计已迁移 17 个 kline 调用点**。

## v2.16 (2026-10-14)

### 🚀 第 2 层·阶段 2 第五批迁移（2 个）

| 脚本 | 迁移点 | 影子对拍 |
|---|---|---|
| `quant_scripts/fish_body_enhanced.py` | 3 处 kline（大盘温度指数 / 个股评分 / 黄金起爆线） | 7 只 + 大盘 temp **一致** |
| `quant_scripts/dragon_leader.py` | `get_stock_hist()` 主源（kline qfq；东财/新浪回退保留） | 6 只 / **0 差异** |

- **累计已迁移 15 个 kline 调用点**。
- `fish_body_enhanced.py` 为「鱼身/多维」两条链路共享脚本，改动仅限取数入口；统一层负责 retry/免npx/缺口，脚本内原「首调冷启动重试」保留为回退。
- `dragon_leader.get_stock_hist()` 原 westock 分支输出的降序需 `recs.reverse()` 校正，fetch.kline 直接升序，已对齐；akshare 两路回退原样保留。

## v2.15 (2026-10-14)

### 🚀 第 2 层·阶段 2 第四批迁移（2 个）＋ 发现 1 处解析缺陷（待决策）

| 脚本 | 迁移点 | 影子对拍 |
|---|---|---|
| `quant_scripts/xihu_turns_check.py` | `fetch_index()`（上证指数 limit 900） | dates/closes **全等**（900 根） |
| `quant_scripts/month_frame.py` | `fetch_month_rows()`（月线，不复权） | 9 只 / **0 差异** |

- **累计已迁移 13 个 kline 调用点**。
- ⚠️ **发现缺陷（未改，留待决策）**：`quant_scripts/monthly_macd_monitor.py` 的 `parse_monthly()` 取 `parts[3]` 当 close（实测 2026-10-14 得 3864.12 = **high**，真收盘 3767.23）——单股月线列序为 `date|open|last|high|low|...`，作者疑似误用批量列序（`symbol|date|open|last|high|low`）。即该脚本的 MACD 实际跑在**最高价**序列上。属数据口径 bug（非模型先验），改动会改变其输出，故**本轮不迁移、先上报**。

## v2.14 (2026-10-14)

### 🚀 第 2 层·阶段 2 第三批迁移（5 个重脚本 → `fetch.kline`）

本批覆盖「全市场宽度 / 猛兽核心 / RSV强度 / 涨停概念 / 涨停王者漏斗」五个盘后主力：

| 脚本 | 迁移点 | 影子对拍 |
|---|---|---|
| `market_width.py` | 批量+缺口+逐只+上证指数（200日成本线，limit 250） | 批量 37 只 + 指数 250 根 / **0 差异** |
| `quant_scripts/beast_screener.py` | `parse_kline_df()`（单股，保留旧 cli 回退） | 6 只 ×(60/250) / **值级 0 差异** |
| `quant_scripts/xihu_rsv.py` | `fetch()`（批量，qfq） | 19 只 / **值级 0 差异** |
| `quant_scripts/limitup_concept_rank.py` | `fetch_all()`（日 qfq）+ `fetch_month_strength()`（月，不复权） | 日 37 / 月 37，**值级 0 差异** |
| `quant_scripts/wangzhe_funnel.py` | `fetch_klines()`（不复权） | 37 只 / **值级 0 差异** |

- **累计已迁移 11 个 kline 调用点**（+wangzhe_track/top_signal/xihu_breadth/scan_123_2b/rsv_strength/yitong_screener）。
- 附带修复：`xihu_rsv.fetch()` 旧「逐只兜底」因单股输出无 symbol 列而恒空（`parse_batch_kline` 要求 `symbol` 列）→ 现已由 fetch.kline 统一处理；`beast_screener` 旧路径硬编码 npx，现直调。
- 复权口径严格对齐：日线多为 `fq=qfq`，`wangzhe_funnel`/月线为**不复权**（保持原样），逐脚本核对，绝不臆改。

## v2.13 (2026-10-14)

### 🚀 第 2 层·阶段 2 第二批迁移（4 个批量取数主力 → `fetch.kline`）

本批均为「全市场/大池」批量取数脚本，改动集中在取数入口，模型逻辑零改动：

| 脚本 | 迁移点 | 影子对拍 |
|---|---|---|
| `quant_scripts/xihu_breadth.py` | `scan()` 批量+缺口+逐只兜底 → `fetch_kline()`（委托 fetch.kline，转 `(date,open,close,high,low)` 元组） | 37 只 / **0 差异** |
| `quant_scripts/scan_123_2b.py` | `fetch_kline_batch/one()`（qfq 前复权） | 37 只 / **0 差异** |
| `quant_scripts/rsv_strength.py` | `fetch_batch()` + 基准指数取数（day/week/month） | 值级 **0 差异**（旧 npx 路径偶发丢的 2 只被新层重试补回） |
| `quant_scripts/yitong_screener.py` | `fetch_kline()`（qfq） | day/week 各 22 只 / **0 差异** |

- 统一收益：**批量/重试退避/免 npx/缺口兜底/解析** 五件事收口到 `fetch.kline`；脚本本地只保留「结构转换」，去掉重复的 run/parse。
- 保留降级：每个新入口 `try/except` 兜底返回空，不崩关键路径；保留原有 `--fq qfq` 口径。
- 累计已迁移 **6 个** kline 调用点（wangzhe_track / top_signal / xihu_breadth / scan_123_2b / rsv_strength / yitong_screener）。

## v2.12 (2026-10-14)

### 🚀 第 2 层·阶段 2 首批迁移（取数 → `fetch.kline`）

- `quant_scripts/wangzhe_track.py`：`fetch_bars_batch` 委托 `fetch.kline`（保留原签名与元组返回）；**影子对拍：40 只样本命中 36 只、逐 bar 0 差异**。
- `quant_scripts/top_signal.py`：`fetch_idx_kline` 委托 `fetch.kline`（保留 date/open/last/high/low/amount 行结构）；**对拍：60 行 0 差异**。
- `quant_scripts/fetch.py` 修 bug：kline 单只（无 symbol 列）解析键回填为代码。
- 迁移原则：逐个脚本**影子双跑对拍一致后**才切换，不改任何模型逻辑。

---

## v2.11 (2026-10-14)

### 🚀 第 2 层「取数层标准化」启动

- 新增 `quant_scripts/fetch.py`（v0.1）：统一取数层，收口历史上反复重写的 5 件事——**批量 / 重试退避 / 免 npx / 缺口兜底 / 表头解析**；第 1 批覆盖 `kline`（日/周/月/分钟）与 `quote`（腾讯行情）。
- 冒烟测试：`kline sh600519,sz000001` 各 250 根、`quote` 正常（直调 bin 免 npx）。
- 产出《第2层·取数层对账与设计草案_2026-10-14》（知识库「指标存档」）：实测 83/188 文件含 westock 调用、55 份自建 `WESTOCK` 常量、20 份重复 `parse_kline`、仅 5 份有缓存 → 给出目标架构与四阶段迁移计划。
- 阶段 0（读取层 `report_io.py`）已于 v2.10 完成；本轮为阶段 1 起点。

---

## v2.10 (2026-10-14)

### ✨ 报告读取公共层 `report_io.py`（副本治理二期·A）

- 新增 `quant_scripts/report_io.py`：`load_latest(paths)` 按 `data_date>bar_date>trade_date>date` 取最新（首个无日期则保持）；另附 `first_readable()`。
- `gen_premarket_report.py` / `gen_review_report.py`：**所有多副本 reader 统一**改为 `from report_io import load_latest as _ri_load`（带 try/except 兜底：模块缺失时回退"取第一个可读"）；删除各自本地 `_pick_newest_json`。
- 验证：单元测试（板块共振/市场风格/西湖广度/乾坤/信号仲裁/一统股池 等 reader 在「根新-outputs旧」下均取"新"）；premarket CI run#54 success，③.3 正常。

### ✨ 自检静态检查 `check_reader_bypass`（副本治理二期·B）

- `quant_scripts/artifact_audit.py` 新增：列出「多副本产物被消费方**直接 `open()`**、却未走 `report_io.load_latest`」的读取点（编写期预警，不参与退出码）。
- 验证：mock 命中；真实仓库 CI run#32 `reader_bypass=[]`（A① 改造后已无旁路）。

### 📝 约定文档

- 新增 `docs/产物副本约定.md`（仓库内规则 + 存储策略 + 守门）；知识库《产物副本口径与新鲜度约定.md》同步。

---

## v2.9 (2026-10-14)

### 🐛 修复：报告产物「多副本陈旧劫持」

- **症状**：盘前报告 ③.3「资金维度板块主线」自 ≈2026-09-04 上线起逐字不变（恒为 08 月的半导体/元件/电子…）。
- **根因**：reader（`read_heshi_resonance` / `gen_review_report.read_sector_resonance`）把 `outputs/板块共振_latest.json` 排在候选路径首位，而该副本自 **2026-08-13** 起未再提交（`quant_scan` 只 `cp` 到仓库根并**只提交根副本**）→ 跨作业消费者（盘前/复盘作业自身不产该文件、仅 checkout）永远读到僵尸数据。
- **判别规则**：产物若在「消费作业之外的另一个作业」生成，其 `outputs/` 副本一旦掉出提交清单就会冻结；同一作业内生成的（信号仲裁/市场风格，由 quant_report 产并被同作业复盘消费）因运行时刚写过而安全。
- **修复**：
  - `gen_premarket_report.read_heshi_resonance` / `gen_review_report.read_sector_resonance` 改用新助手 `_pick_newest_json()`（按 `data_date>bar_date>trade_date>date` 取最新；首个无日期则保持）。
  - 删除 6 个陈旧 `outputs/` 副本：`板块共振_latest`(08-13)、`信号仲裁_latest`(08-11)、`market_style_latest`(08-11)、`xihu_breadth_latest`(09-27)、`黑石板块共振_latest`(08-07)、`liangxue_latest`(08-30)（均不在提交清单，不会复活）。
- **验证**：`workflow_dispatch` 重生成 10-14 盘前报告 → ③.3 已刷新为 10-13 数据；②「🗺️空 共振板块」由 9 → 8。

### ✨ 自检增强：多副本新鲜度

- `quant_scripts/artifact_audit.py` 新增 `check_dup_freshness()`：比对「仓库根 vs `outputs/`」同名产物日期，输出 `dup_freshness`/`dup_stale` 字段与「🧬 多副本新鲜度」节；`dup_stale>0` 即 `--strict` 退出 1。
- `.github/workflows/artifact_audit.yml` 告警接入 `dup_stale`。
- 验证：artifact_audit CI run31 `dup_stale=[]`。

---

## v2.8 (2026-09-30)

### 🔧 数据源自检加固（selfcheck ①）

- **源 B 迁移**：`cross_source_check.py` 的对照源由「东财 push2delay」改为「新浪 hq.sinajs」
  （东财 push2/push2delay 主机 2026-09-29 起时变抖动，CI 与沙箱均出现过不可用）
- **冗余结构**：升级为「必需源 + 机会源」——主源 westock ｜ 必需源 新浪 + 腾讯 ｜ **机会源 东财**（在线自动纳入四源对拍，离线静默跳过、不误报）
- 效果：`selfcheck_daily`「数据源」由 rc=1 → **rc=0**（09-30 实跑四源一致 9/9）

### 🔧 慢步骤取数批量化（性能）

- 根因：`npx -y westock-data-skillhub` 每次启动 **≈3.5s**，调用次数即主要成本
- `xihu_breadth.py` 默认 `--batch` 40→**250**；缺口小批 10→40 + 逐只补齐限 10 只
- `scan_123_2b.py` **逐只 → 批量 250**（新增 `parse_kline_batch`），npx 调用 3039→≈13；缺口兜底
- `yitong_screener.py` `BATCH` 40→**250** + 新增 `fetch_kline_gap()` 缺口兜底
- `quad_resonance.py` `batch_asfund` chunk 40→**250** + 缺口兜底
- `quant_scan.yml` 西湖广度 `--batch 40`→`250`
- 效果：西湖广度 25min→**~2.6min**；123/2B/ABC 27min→**~2min**（实测 250 只 52s，且新旧信号完全一致 201/201）
- 附：全市场池含 ~7.6% 已退市代码（本就无数据），已给「逐只补齐」加上限以杜绝空耗

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
---

## v2.9 (2026-08-12)


### 🔧 优化

- chore: update quant/fish_latest (2026-08-12) (a98099f)

---

## v3.0 (2026-09-06) — 周期级联执行卡 · 宁静卡位体系 · 体系韧性加固

> 跨度：2026-08-12（v2.9）→ 2026-09-06。此版本手工聚合，覆盖 v2.9 以来全部增量。

### 🃏 个股执行卡（张穗鸿「卷钱机器」周期级联落地）
- **`execution_card.py` 新增**：①上级周期门禁（月线+周线双闸门合成：月BLOCK→⛔拦截 / 月WARN或周BLOCK→🟡试仓×0.5 / 月PASS+周WARN→🟡谨慎×0.7 / 双PASS→✅放行）②资金预算（2×ATR止损 / 月线前12月高目标 / 盈亏比≥2 / 单票≤30%=张穗鸿3331 / 账户2%风险→最大亏损金额）③分批 5:3:2（B1底仓@信号确认→B2@回踩MA10→B3@突破前高；B1+B2波段到目标止盈，B3趋势跌破MA20离场）
- **盘前报告 ④.1 个股执行卡段**：`gen_premarket_report.py` 新增 read/render_execution_cards，读仓库根 execution_cards_latest.json 自动渲染
- **盘后 workflow**：`quant_report.yml` 第五.4.7 步每日自动对持仓生成执行卡并提交（供次日盘前引用）
- 实测（9/4收盘）：中石油/平安银行✅放行(盈亏比3.98/2.48)，海康🟡谨慎(21%)，茅台/华能🟡试仓(15%/14%)，浙大网新/国安股份⛔拦截(月线空头)——与既有月线闸门判断一致
- 依据：张穗鸿龙虎跃精修课第34/35节《同一只股票开三个卷钱机器》视频分析（百度网盘），思想同源但取其框架弃其信仰（其指标未经数据验证）

### 🎯 宁静卡位体系（题材质地裁决·evidence铁律）
- **AI硬件卡位链 30只** `ai_chain_pool.json`：光互连19/具身智能8/终端光学3，evidence分级（strong/medium/weak）+ 卡位评分80+
- **固态电池链 10只** `solid_battery_pool.json`：硫化物电解质/硫化锂/LLZO/锂金属负极环节，排除电芯整机厂
- **低空经济链 10只** `low_altitude_pool.json`：复材/电驱/空管/发动机/连接器环节，排除整机厂
- **商业航天链 10只** `space_pool.json`：T/R芯片/宇航FPGA/高可靠MLCC/连接器/材料（2026供需缺口=宇航级芯片83%居首）
- 四池自动合并（60只），多池观察：盘前③.4题材确认（卡位≥80）/卡位×信号交集（四维≥4+卡位≥70）/relabel过半追高警惕/证据待核验
- **evidence月度复核** `evidence_review.py` + workflow 每月1号自动生成工作单推送（strong/medium/weak 分级核验升级路径）

### 🏛️ 盘前/复盘链路重构（GitHub 自动 Phase1）
- `premarket_report.yml` 恢复 08:00(BJT) schedule，解除 ima 依赖，端到端闭环（报告+judgment+微信推送）
- **`gen_judgment.py` 新增**：盘前预判落盘标准化（schema 双兼容），修复 8/12-9/3 judgment 断链（SKILL.md 固化 Step5.6 强制纪律）
- 复盘报告：③.9 AI卡位主线尾声监测（🟢健康/🟡警惕/🔴尾声三态）+ ③.6 猛兽子池三元扩展（主池/观察池/信号子池）

### 📊 新指标与新模块
- **年线广度** `yearline_breadth.py`：站上年线占比（8/21实测 684/3024=22.6% bear级），剔除13只僵尸退市股
- **RSV均强度** `rsv_strength.py`：RSV均=(价格RSV1+相对基准RSV2)/2 N=144；880003 基准快照自动化（tdx 分页拉取）
- **市场宽度** `market_width.py`：涨跌家数+强势/涨停结构 → 宽度分 0-100
- **123-2B反转扫描** `scan_123_2b.py`（《专业投机原理》）：123法则/2B假突破/ABC末端 + 宏观-技术冲突环境裁决（冷市<40全部降级）
- **龙头战法 v2** `longtou.py`：五维定位/梯队/见顶预警/机构锁仓标签
- **张穗鸿指标验证**：九五至尊扩大样本 2516 信号——原版低价(≤15元)用法**证伪**（20日超额-0.22%），有效组合=九五至尊+环境关(上证>MA60)+股价>30元（10日+2.95%/20日+2.57%）
- **市场状态×策略矩阵 v2** `market_model_matrix.md`：18模块×三市态（牛/震荡/熊）完整映射
- **颜劼情绪周期统计**：82交易日 6态转移矩阵（高潮次日95%不转弱等）
- **做T狂人策略引擎** `zuot_kuangren.py`：132交易法（5m96均线+VWAP）
- 情绪预判 `emotion_forecast.py`、盘中监控、双弦月池分层（核心≥65入池/观察50-65独立跟踪）

### 🔧 数据铁律与韧性修复（关键坑固化）
- GitHub 断链根因链修复：提交步骤补 GITHUB_TOKEN env、secret 命名合规（禁 GITHUB_ 前缀）
- **kline 批量列序铁律**：批量输出首列=symbol 非 date、date 降序（最新在前）、exchange=换手率%
- market_width 涨跌全反修复；hot_emotion 接入 workflow + 仓库根累积起点 + 解析修复（'|'优先）
- ST 防线第三轮：代码级实时校验（st_guard 查 qt.gtimg.cn），9个标的输出脚本全部接入
- IMA 凭证健康检查 `ima_cred_check.py`（probe/mark-ok/staleness 三功能 + guard_selfcheck 每日预检）
- tdx 交叉验证（tdx_quotes vs westock 4/4 完全一致）；新浪分钟线/腾讯域名被沙箱封禁的降级方案
- 百度网盘直读通道 `baidu_pan.py`（xpan 原生 API + dlink 下载，token 持久化）

---
