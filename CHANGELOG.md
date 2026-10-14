# bg 全量扫描体系 — 更新迭代记录

> 仓库：wuhj-hub/bg
> 工作流：全量扫描（复盘报告数据源）— `full_market_scan.yml`

---

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
