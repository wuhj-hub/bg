# bg 全量扫描体系 — 更新迭代记录

> 仓库：wuhj-hub/bg
> 工作流：全量扫描（复盘报告数据源）— `full_market_scan.yml`

---

## v2.66 (2026-10-24)

### 新增：知识库上传健康检查（selfcheck 第 ⑥ 项）

**动因**：2026-10-23 kb_id 失效导致全链路上传静默失败一整天。`upload_ima.py` 侧已加 `::error::`
注解，但仍需一个**从知识库侧反向核对**的守卫，否则"报告没进库"依旧只能靠人工发现。

- 新增 `quant_scripts/kb_health_check.py`：按「最近 N 个交易日」逐日核对「报告」KB 的四个文件夹
  —— 复盘报告 / 盘前报告 / 全盘量化（任意当日文件）/ 竞价统计；从 `get_knowledge_list` 拉真实标题
  匹配（兼容 `_prev_` 归档），缺失即 `::warning::`，`--strict` 时 exit 1。产物
  `outputs/kb_health_{date}.md` + `kb_health_latest.{md,json}`。
- `selfcheck_daily.yml` 接入第 ⑥ 项（与其它四项同款受控捕获 `set +e → RC → $GITHUB_OUTPUT`）：
  - 产物纳入「提交自检产物到仓库」清单 → 入库
  - 告警步纳入 `KB` rc 判断 + 缺失明细（`知识库缺失:日期·类别/…`）→ 微信
  - 「上传自检报告到盘后量化文件夹」清单加 `kb_health_latest.md`
- 本地实测：最近 3 个交易日（10-23/10-22/10-21）全部 ✅；指定 `--date 2026-09-29` 时正确报
  `盘前报告 ❌缺 / 竞价统计 ❌缺` 并 exit 1。
- CI 结构校验：手动 dispatch selfcheck（run 40018576012）→ trade_gate success、selfcheck skipped
  （2026-10-24 为周六，守卫正常跳过）；端到端将于下周一 07:00 首次运行。

---

## v2.65 (2026-10-23)

### 修复：ima 平台强制 kb_id 新格式 → 全链路上传知识库静默失败

**根因**：ima 平台自 2026-10-23 起只接受 `ima_kb_XXXXXXXX`（8 位字母数字）格式的 kb_id，
旧长 id 一律返回 `code=220004 invalid or outdated knowledge_base_id`。CI 里 24 处仍引用
`${{ secrets.IMA_KB_ID }}`（secret 内为旧长 id `6kjd8jHp...=`）→ 当日**所有上传知识库步骤全部失败**；
每个调用都用 `|| echo "xxx上传失败"` 吞错，run 结论仍为 success，故长期未被发现。

**证据**（run 39929204026 日志）：`220004` 出现 15 次；KB 侧「报告/复盘报告」最新停在 10-21、
「报告/全盘量化」当日 0 份（仅人工补传 3 份反转报告）；而 `jingjia_track.yml`（已硬编码
`ima_kb_b5qpEC7v`）当日「报告/竞价」4 份上传成功 —— 对照组印证是 kb_id 来源差异。

**修复**
- 11 个 workflow 共 **24 处** `${{ secrets.IMA_KB_ID }}` → 硬编码 `ima_kb_b5qpEC7v`（均指向「报告」库）：
  `quant_report`(12)、`quant_scan`(3)、`premarket_report`、`selfcheck_daily`、`guard_selfcheck`、
  `inbull_scan`、`inbull_threshold_monitor`、`pool_winrate_biweekly`、`wangzhe_track`、`yao_gu_pool`、`probe_search`。
- `upload_ima.py` 新增 `resolve_kb_id()` 防呆：kb_id 非新格式时，按 `IMA_KB_NAME` / 旧 id→名称映射
  自动调 `search_knowledge_base` 解析最新 id，并打 `::warning::`；另在入口加 `::error::` 注解，
  避免失败被 `|| echo` 完全吞掉。

**已闭环（2026-10-23 22:58）**：secret `IMA_KB_ID` 已由用户更新为 `ima_kb_b5qpEC7v`，24 处硬编码
已回退为 `${{ secrets.IMA_KB_ID }}` 引用。验证：手动 dispatch `inbull_scan`（run 39974436102）全绿，
日志 `[OK] 报告已发布: 入牛时点扫描_2026-10-23.md`，KB「报告/全盘量化」侧确认新增该文件。

---

## v2.64 (2026-10-23)

### 反转数值：取消窗口扩展到周/月线 · 撤销创业板入池

- `reversal_daily_screener.py` → v7.4：**取消「新信号窗口」由日线扩展到周线/月线（三周期统一）**——
  结构有效即入池，仅受最大跟踪期约束（日 45 / 周 30 / 月 18 根）；存量观察区三周期一并关闭；
  `--use-window` 可整体回退到原窗口口径（day5/5 · week3/8 · month2/4）。
- **撤销创业板入池**（v2.63 的尝试）：删除 `all_chinext.csv`；`quant_report.yml` 日线股票池回到
  `all_mainboard.csv`；`--pool-file` 多文件能力保留（不影响现有调用）。
- 影响测算（抽样，"今日截面命中"）：
  - 日线（488 只）：4 → 14 只（全市场推算约 90~120 只）
  - 周线（200 只）：3 → 3 只（无变化，突破久远的结构多已失效）
  - 月线（200 只）：3 → 23 只，约 7.7 倍（全市场推算 300+ 只，月线报告会明显变长）

---

## v2.63 (2026-10-23)

### 反转数值·日线口径调整（取消新信号窗口 + 创业板纳入池）

- `quant_scripts/reversal_daily_screener.py` → v7.3：
  - **日线取消「新信号窗口」**：结构有效即入池（仅受最大跟踪期 `gap ≤ MAXGAP 45 根` 约束），
    存量观察区随之关闭；`--use-window` 可回退日线窗口，`--no-window` 可推广到周/月线（周/月线默认不变）。
  - **改2 判定明确化**：回调至水下、且 MACD 不低于 −0.618×金叉以来最高红柱（`m_low ≥ −0.618H`，即 `deep ≤ line`）；
    改1 保持「突破后未下水 且 回踩幅度 < 0.618H」。
  - **死叉当日（`SCB==0`）不再判「无结构」**，消除在池票逢死叉日被移出、次日又入池的抖动。
  - `--pool-file` 支持逗号分隔多文件（主板 + 创业板，自动去重）。
  - `BATCH` 250→100 + 批间 0.4s 退避 + 空批重试（250/批实测返回 success 但覆盖不足）。
  - 单只模式（`--pool <code>`）补解析：westock 单只输出无 symbol 列。
- 新增 `all_chinext.csv`（创业板 1455 只，含 sz300307 慈星股份）。
- `.github/workflows/quant_report.yml`：反转数值日线改扫「主板 + 创业板」，窗口交由脚本默认（不限）；周/月线保持主板 + 原窗口。

**影响测算（488 只抽样：主板 288 + 创业板 194）**
- 今日截面命中：现行 4 只 → 新口径 14 只（全市场推算约 90~120 只）。
- 8.25–10.20 区间累计入池（标的×日）：304 → 1317。

**案例 sz300307（旧口径永不出现，因创业板不在池）**
- 新口径复算：2026-05-15 起满足（改1，gap 5，价 7.19）→ 8-25~10-20 连续 35 个交易日在池
  → 10-21 结构失效移出（收 7.38），入池至出池 +2.6%。
- 旧口径漏因：回踩确认 8-19 才达标（回调深 2.46 < 线 2.98），此时距突破 6 根 > 窗口 5 根。

---

## v2.62 (2026-10-23)

### CI 加固 + 复盘闭环质量 + 中文字体提速（一日内 8 项修复）

**A. 静默断链修复**

- `bt_cycle`（回测周期·月度）：从上线起从未真正运行（唯一 run 是 2026-09-24 的 push 空 run，
  仓库无任何 `回测周期_*.md` 产物）。原触发只靠 cron-job.org 发 `repository_dispatch[bt-cycle-run]`，
  10-01 未触发。修法：`evidence_review.yml` 末尾内联 `workflow_dispatch bt_cycle.yml` +
  permissions 补 `actions: write`。首次真实运行已产出《回测周期报告 2026-10》
  （394 只有效标的；基准 MAX×2ATR 两段双正；T60/T120/F10/T20 × 2.5ATR 四个候选通过）。
- `emotion_backtest_monthly`：`--days 120 || true` 吞掉失败（10-01 run 全绿但产物停在 09-27）→
  改 rc 捕获 + `::error::` + PushPlus + `exit 1`。
- `quant_scan` 市场宽度产物自检：补 `--push` 与 `PUSH_TOKEN`（此前失败只写日志无告警）。
- `silent_failure_audit.py`：白名单加「产物契约自检」/`run_and_verify.py`，消除 15 个 workflow
  契约自检步的系统级误报（此前一直占着 1 项高危）。

**B. set -e 陷阱（bash）**

- `bt_cycle.yml` L62 `[ "$RC" != "0" ] && echo ...`：RC=0 时整条语句返回 1 → 步红（实测产物
  已成功入库却报失败）。`duowei_fish.yml` L149 `[ -n "$JSN" ] && cp ...`：JSN 为空时整步退出、
  后面 `git_api_commit`（提交 `鱼身报告_latest.md`）被跳过。均改为 `if ...; then ...; fi`。

**C. 盘中监控「全天 24 次全取消」**

- 根因链：cron-job.org 早盘漏单（09:00~10:45 无触发）→ 11:00 首次触发走 `kaipan_8.py --auto`
  补算路径（实测 27.3min 未结束，正常日该步 0.0min 秒退）→ job `timeout-minutes: 30` 到点
  整个 job 被 cancelled → 下次触发又从头补算，循环 24 次。
- 修法：该步加 step 级 `timeout-minutes: 15`（已有 continue-on-error，只失败本步不拖死 job）+
  job timeout 30→45 + 新增「开盘八法异常告警」步（`steps.kp8.outcome == 'failure'` 时推送）。
  run#1059 验证全绿。

**D. 复盘报告「盘前预判验证」四处失真**

- 关键位验证硬编码 `close >= 3800`（与盘前关键位无关 → 收盘 3690 一律判"需观察"，而盘前支撑
  3650 实际守住）；板块方向要求命中 ≥2 个才判对（盘前只给 3 个候选，命中「半导体」仍判证伪）；
  大盘方向只取上证涨跌且只在下跌时校验；明日展望同样只看上证 + 硬编码 3800 点。
- 修法：改用上证/深成/创业板**综合涨跌**；板块补「🟡 部分命中」档；关键位从 key_levels 解析
  数值；新增「防守 + 上涨 → 🟡 错过反弹」档；支撑位改动态整数关口。

**E. 盘前报告新增「②.10 反弹质量三检查」**

- 三项指标（昨日 vs 前 5 日均值）：涨停家数 / 创新低家数 / 强势股占比 qsg_pct。
  改善 ≥2 → 🟢 结构改善；1 → 🟡 偏弱；0 → 🔴 超跌反抽不追高。
- 2026-10-23 实测：涨停 46（均值 28.8，+59.7% 🟢）/ 创新低 505（均值 107.8，+368.5% 🔴）/
  强势股 3.43%（均值 3.8，-10.8% 🔴）→ 🟡 仅部分改善（1/3）。

**F. 新增 research_panic_rebound.py（研究脚本，不入 CI）**

上证全历史（8748 日）统计「恐慌日之后」：单日 ≤-1.2%~-2% 次日胜率 55.4~55.8%（基线 52.6%），
但 T+3/T+5 均值超额为负；只有单日 ≤-3%（n=337）或连 3 日累计 ≤-6%（n=250）时 T+5/T+10
才有 +0.34~+1.45pct 正超额。→ 抢反弹属小仓位试错，非重仓信号。

**G. 中文字体提速（盘后报告第 2 大耗时步）**

- 原 `apt-get update && apt-get install fonts-noto-cjk` 实测 **24.6min**（刷索引 + 下载 130MB
  全量 CJK 包）。改为 `actions/cache` 缓存 `~/.fonts` + 直下 8.3MB `NotoSansSC-Regular.otf`
  + `fc-cache` + 复制进 matplotlib `fonts/ttf` + python 校验可见性（看不到则 `::error::`）。
  预期 <1min。顺带给 pip 加 wheel 缓存。

**H. 取数层 v0.3（今日早些）**

- `fetch.py` 新增 `ext_em_margin`（东财 `RPTA_WEB_RZRQ_GGMX` 融资余额/占流通市值/5·10 日净买入）
  与 `ext_em_report`（东财研报：评级变动 0调高/1调低/2首次/3维持 + 当年·次年 EPS）；
  新增 `crowding_watch.py`（抱团瓦解监控：融资拥挤度 + 边际盈利上修广度 + 卖方关注度）。
- 实测（2026-10-23，AI 硬件链 18 只）：池内融资余额 1476.6 亿、10 日净买入 −192.0 亿
  （中际旭创 −65.95 亿 / 新易盛 −34.88 亿 / 寒武纪 −21.04 亿）；全市场边际上修广度 41.8%。

---

## v2.61 (2026-10-23)

### 取数层 v0.3 + 抱团瓦解监控：补齐「融资余额」与「研报上修广度」两块数据源

- 需求来源：Eagle量化《第四阶段的第三部分：杀白马》(2026-10-23) 的跟踪清单里，
  「融资余额拥挤度」「分析师盈利上修广度」两项体系里一直没有数据源
- `quant_scripts/fetch.py` v0.3 新增两个东财适配器：
  - `ext_em_margin(codes, date)` → 融资余额 / 占流通市值% / 5·10 日净买入
    （报表名 `RPTA_WEB_RZRQ_GGMX`，注意是 `RPTA_WEB_` 前缀；支持 `SCODE in (...)` 批量）
  - `ext_em_report(codes, begin, end)` → 评级变动（0调高/1调低/2首次/3维持）+ 当年·次年 EPS 预测
    （`pageSize` 上限 100；`ratingChange` 语义按东财页面 `data-bdcode` 对齐）
- 新增 `quant_scripts/crowding_watch.py`：三块指标 → `outputs/拥挤度监控_{date}.md|.json`
  1. 融资拥挤度（占流通市值比 = 水平；5/10 日净买入 = 方向）
  2. **边际**盈利上修广度（近 30 日 vs 前 30~120 日的 EPS 中位数，刻意不用「全年前后半」——
     半年跨度测的是累计上修幅度，会掩盖近一个月的边际转向）
  3. 卖方关注度（研报篇数近 30 日 vs 前 30 日，退潮 = 抱团松动前兆）
- 沙箱实测（2026-10-23，AI 硬件链 18 只 + 全市场）：池内融资余额 1476.64 亿、
  10 日净买入 −192.02 亿（中际旭创 −65.95 亿 / 新易盛 −34.88 亿 / 寒武纪 −21.04 亿）；
  融资余额占流通市值中位 3.37%（最高 胜宏科技 9.13%）；全市场边际上修广度 41.8%
  （上修 51 / 下修 71，可比 157 只）；池内研报篇数 −50%
- 口径局限（已写进 docstring）：两融 T+1；评级调低条数极少只作辅助；研报覆盖≠真实盈利上修

---

## v2.60 (2026-10-22)

### 竞价快报并入「三策略候选」（紫霞牛 / 一进二 / 超级竞价）

- 需求：快报不只看榜单，要结合统计里的三个竞价方式筛选
- 口径澄清（关键）：三策略均为「**当日收盘确认信号 → 次日集合竞价买入**」
  （`zixia_niu/yijiner/build_gzb` 在 `i > len(C)-2` 处刻意留出后一根用于回测收益，故当日信号必须等收盘）
  → 09:27 快报呈现的是「**上一交易日信号的今日竞价买点**」，既是唯一可执行时点、也与回测口径一致；
  今日新信号仍由 15:05 完整统计产出
- 实现：`--brief` 读 `data/jingjia_signals.csv` 最近信号日（< today）记录，与行情快照 join 出
  「昨收 / 今开 / 高开% / 竞价额」，**零额外取数**（快报仍 3.3min）
- 报告新增第四节：策略汇总（候选数 / 竞价高开 / 竞价低开 / 均值高开%）+ 三策略分组明细
- 实测（2026-10-22，信号日 10-21）：一进二 1 条（星光股份 +10.20%）、超级竞价 13 条（均值 +1.06%）、
  紫霞牛当日无信号

---

## v2.59 (2026-10-22)

### 竞价链路两段拆分：09:27 竞价快报（3.3min）+ 15:05 完整统计

- 需求：原来一次运行 30~40min（09:27 触发也要 10:07 才出报告），盘前用不上
- 拆法：
  - **09:27 → 竞价快报（`--brief`）**：只读腾讯行情快照（`fetch.ext_gtimg`，qt.gtimg），
    不经 westock m1、不加载日线、不重算信号 → 实测 CI **3.3min**
    （步内：60 次行情请求 ≈ 20s；09:25 撮合完成→09:30 前 amount 即竞价成交额）
    内容：竞价金额 Top20（资金主攻）/ 高开 Top20 / 低开 Top15 / 昨日信号今日竞价表现
    数据未就绪（有效只数 <100）自动 60s×2 重试
  - **15:05 → 完整统计**：原流程（m1 抓竞价入库 + 三策略信号 + T+1~T+5 收益回填 + 完整报告）
- 触发映射：`repository_dispatch[jingjia-track-run]`（cron-job.org 准点）与
  `schedule '27 1 * * 1-5'` → brief；`schedule '5 7 * * 1-5'` 与 `workflow_dispatch` → full
- 配套：`config/daily_artifacts.json` 的 jingjia 组 —— 两个 md 均设 `optional:true`
  （各自只在对应模式产出，避免另一种模式每天误报），新增 `outputs/竞价快报_{date}.md` 条目；
  提交清单与「报告/竞价」上传步改为双文件循环
- 知识库落点不变：「报告」→ 「竞价」（folder_7511006091703733）

---

## v2.58 (2026-10-22)

### ima 平台知识库 ID 迁移：旧 base64 长 ID 全部失效 → 统一改 `ima_kb_*` 新 ID

- 现象：duowei「上传鱼身报告到多维量化」步报 `create_media failed: {'code': 220004,
  'msg': 'invalid knowledge_base_id'}`；该 kb_id 值自 09-29 建链后从未改动，10-20 上传仍成功
- 定位（用 `openapi/wiki/v1/search_knowledge_base` 按名称查当前 ID + 逐个 `get_knowledge_list` 验活）：

  | 知识库 | 旧 ID（已失效） | 新 ID（有效） |
  |---|---|---|
  | 多维量化 | `RgPmCvOW2CgN3I-HVGEYfmBS_W0mkiYzHRuTGHP8_6o=` | **`ima_kb_bcxqaAnF`** |
  | 猛兽 | `9wlJWgbFxvKhhxzobeMHSJ7_eaUmHutVQXMzeNxh4DM=` | **`ima_kb_LCxys0NP`** |
  | 双弦 | `zw56pWsoAd18wp9A_2-_vFFAPbG51UZsuaGyvynm66g=` | **`ima_kb_zmenvjf6`** |
  | 报告 | `6kjd8jHpAyqf0xFVUo2xUWPaDAKapAWCw-Tki7V-aAs=` | **`ima_kb_b5qpEC7v`** |

- 结论：**不是知识库被删/重建**，是平台把 kb_id 体系从 base64 长串换成 `ima_kb_xxxxxxxx`；
  旧 ID 一律返回 220004。**folder_id 未迁移**（`folder_7478204537267754` 等仍有效）。
- 改动（5 文件 7 处，全部校验 yaml/ast 后提交）：
  - `duowei_fish.yml`（多维量化，含注释更正）｜`quant_report.yml`（猛兽 + 双弦）
  - `jingjia_track.yml`、`weight_learn.yml`、`ima_cred_check.py`（报告库旧 ID）
- 排查手法沉淀：`search_knowledge_base` body `{query|keyword, limit<=20}` 返回 `kb_id/kb_name/creator/base_type`；
  这是**唯一**能按名称查到知识库 ID 的 OpenAPI（list_* 系列全部 404）。
- 影响面：`secrets.IMA_KB_ID` 引用的多数上传步今日实测 success（说明 secret 已是新 ID）；
  写死旧 ID 的路径（含上传失败被 `|| echo` 吞掉的）此前已静默失效，本次一并修复。
- 上传步保留 `continue-on-error: true`（失败仍有 PushPlus 告警 + 产物已提交仓库），避免拖红主链路。

---

## v2.57 (2026-10-22)

### 修「动态鱼身股票池」取数失控（86.8min 被 cancel → 12.5min）+ pipeline_audit 宽度停更误报

**(A) `quant_scripts/gen_fish_pool.py` 取数重构（体系体检 P1）**

- 症状：该步耗时 10-15 **49.7min** → 10-16 36.9 → 10-19 23.4 → 10-20 37.4 → **10-21 86.8min**
  （duowei 链路整体 90.7min 后被 cancel）；10-22 quant_scan 卡在同一处，当日扫描拖到 **192min**
- 根因（实测三处叠加）：
  1. `_fetch_layer` 调 `fetch.ext_fqkline(codes, count=20)` **未传 workers** → 默认 workers=1
     **逐只串行**取腾讯 fqkline（全市场 3100 只 × 1 请求），遇 WAF 限流再叠加 4 次重试退避；
  2. 试改批量后仍不稳：westock 批量在 **250/批** 时大面积限流 —— 实测
     `[Batch] 状态: success | 总数: 250 | 成功: 10 | 失败: 240`（覆盖 4%），**100/批才稳定（覆盖 95%）**；
  3. main 的「逐只兜底」对 1556 只缺失标的逐只调腾讯 → 又一轮重试退避 30min+
- 改法：
  - 批量 kline **100/批**（批间 0.4s），单块覆盖 <60% 时 sleep 8s 重试一次，整体 <50% 才回落腾讯（workers=6）
  - 去掉「逐只回补」（all_mainboard 固有 ~7.6% 退市/停牌，本就无成交额、不该入池）
  - 新增 `_fill_by_quote()`：仍缺失的用**当日成交额**（qt.gtimg amount，万元→元）近似补排名依据
  - 成交额口径：优先真实 `amount`（元，westock 自带），缺失回退 volume×100×均价（旧估算口径）
- 实测（沙箱·无缓存·3127 只）：**751s（12.5min）**，有效覆盖 **3053/3127 = 97.6%**（行情兜底补 730 只）；
  产出 302 只（300+核心），Top10 = 药明康德 60.4亿 / 京东方 58.6亿 等大票，排序合理
- CI 预期：quant_scan job 内 FETCH_CACHE=1 且前面步骤已批量拉过全市场 K 线 → 缓存命中后再降；
  duowei 冷启动约 12~15min（原 86.8min 超时被杀）

**(B) `quant_scripts/pipeline_audit.py` 产物停更误报（体系体检 P2）**

- 症状：pipeline_audit 每天 status=FAIL，唯一 issue「market_width_latest.json 停更 5 个交易日」→ 每日微信告警
- 根因：`FRESH` 表仍监控**根副本**，而 10-15「消灭双副本」(11.1) 已删除根副本、canonical 移到 `outputs/`；
  `outputs/market_width_latest.json` 实际每日更新（10-19/20/21 均有 commit）
- 改法：FRESH 键改为 `outputs/market_width_latest.json`

---

## v2.56 (2026-10-20)

### 行情类型 → 股池分层（regime_history + 股池胜率总览第四节）+ 修「情绪指标跟踪」累积静默 bug

**(A) 新增 `quant_scripts/regime_history.py`（行情类型历史序列 · 指数口径）**

- 用途：limitup v4.6 的实盘「🧭 行情类型」依赖广度/涨停结构，**无历史**无法给历史信号样本分组；
  本脚本只用上证日线回算每日类型，形成可 join 的序列 → `data/regime_history.csv`
- 判据：三力（MA250/MA60/MA20 方向，斜率取近 20/10/5 根）+ 年线位置；**只在年线可用后输出**（口径单一）
- 实测：531 交易日（2024-08-06 ~ 2026-10-19）；全期 第1类 238 / 第2类 179 / 第3类 114 日；近250日 90/103/57
- 幂等（只依赖该日及之前数据）+ 提供 `ensure()`（缺失/过期自动重建，失败沿用旧文件不阻塞调用方）

**(B) `pool_winrate_biweekly.py` 新增「四、按行情类型分层」**

- 样本按「信号日/入池日所属行情类型」归组，输出 5/10/20/60 日 胜率 / 均值 / 样本数
- 覆盖：全池基准、TOP6 池、涨停王者（自带回测列，不重取）、量学、竞价（合并策略）
- **首跑结果**（2026-10-20，样本窗口 09-23~10-19）：
  · 全池基准 5日：第2类 **32% / -2.60%**（n=1220） vs 第3类 **28% / -3.02%**（n=1124）
  · 竞价：第3类 **39% / -0.94%**（n=269）明显优于第2类 **26% / -3.79%**（n=187）
    → 印证「竞价=概念龙头的执行层，只有弱市(第3类)才有相对超额」
  · 量学 第2类 5日 **40% / +0.20%**（本次唯一正均值）；双弦 第2类 5日 **45% / -0.62%**（池内最优）
  · ⚠️ **不可当结论**：第2类仅覆盖 **2 个入池日**、第3类 **11 个** → 当前分层≈「按入池时间切片」，混杂时间效应；
    报告已自动加「样本期警示」行（某类型入池日 <20 即提示），须按月累积后再读
  · 局限：pool_entries 仅 13 个交易日样本，20/60 日列大面积为空，需按月累积后才有统计意义

**(C) 修 `limitup_concept_rank.py`「情绪指标跟踪」跨月累积从未生效（静默 bug）**

- 根因：脚本只读写 `outputs/情绪指标跟踪.json`，而 CI 提交的是**仓库根**那份（workflow `cp outputs → 根` 覆盖）
  → 每次全新 checkout 都从空开始、根目录历史每日被覆盖（10-19 实测根目录只剩 1 天，"跨月跟踪"形同虚设）
- 修复：多路径合并读取（outdir 优先、根兜底）+ **双写两处**；当日记录覆盖同名日期
- 验证：种子 3 天 + 当日 → 合并为 4 天并集，两侧内容一致；regime/regime_label 随每日记录累积

**上线**：`pool_winrate_biweekly.yml` 提交步增提 `data/regime_history.csv`

---

## v2.55 (2026-10-20)

### 热板作战面板 · 新增「🧭 行情类型」判定（LimitupConceptRank v4.6）

- **来源**：曾星智《悟道01：短线行情的本质是什么》(2026-10-19) —— 短线行情分三类：
  ①大盘级全面上涨（牛市，各种手法都有效）②行业级普遍上涨（震荡市，涨势持续、龙头新高+底部股跟随反弹）
  ③概念级炒作（熊市/弱震荡，少数股连续涨停、多数股下跌）；链条=环境→推动力→形态→有效手法。
  推论：**环境错了，买点再好也是负期望**。
- **落地**：`quant_scripts/limitup_concept_rank.py` 报告最前面（市场情绪刻度之前）新增「🧭 行情类型」小节，新增 `--no-regime` 开关
- **判据**（全部取现成数据，仅新增 1 次指数取数，失败静默降级）：
  1. 指数三力 = 上证 MA250/MA60/MA20 方向（近 20/10/5 根斜率）+ 收盘相对年线位置（`fetch.ext_fqkline` 800 根，回退 `fetch.kline`）
  2. 全市场上涨家数占比（现成 km 当日 bar；≥55% 强 / ≤45% 弱）
  3. 涨停结构（家数/连板/首板/最高板/首板晋级率）
  4. 行业集中度 = 前3行业占涨停比（优先东财涨停池 `hybk` 字段，缺失回退概念口径；ups 三处构造已补 hybk）
- **判定规则**：三力≥2 向上 + 站上年线 + 广度强 → **第1类**；三力≤1 向上 + 跌破 MA60 + 广度弱 → **第3类**；其余 → **第2类**
  （第2类按行业集中度≥45% 细分「行业级」/「结构性过渡」；第3类最高板≥3 额外标注「概念炒作特征明确」）
- **输出**：报告=判定结论 + 判据表 + **策略侧重**（该做什么/该避免什么/仓位建议）；JSON 新增 `regime`；
  `情绪指标跟踪.json` 每日追加 `regime`/`regime_label`（为后续统计「三类行情下的股池胜率」留数据）
- **降级**：指数缺失 → 置信「低（指数缺失）」，只用广度+涨停结构；广度缺失（`--fast`）→ 置信「中（广度缺失）」
- **实测**（2026-10-19 真数据）：上证 3730.92、跌破年线 -6.5%、MA60/MA20 向下、广度 41.6%、涨停 39 家（最高 3 板）
  → 判定 **🔴 第3类 · 概念炒作型**，与曾星智当日「长期/中期/短期三大力量全部向下」判断一致。
  三分支与降级分支单测通过（构造数据：第1/2/3类 + 指数缺失降级）

---

## v2.54 (2026-10-18)

### 反转数值 · 存量观察区补齐价格门槛（v7.2）

- **问题**：v5 起的「📎 存量结构观察」只按「结构有效（valid + 大阳线）+ 超新信号窗口」筛选，
  未套用 `--max-price`，导致大量 10 元以上高位股进入观察区（10-16 全市场：日线 90 只里 74 只超价、
  周线 79 里 50、月线 302 里 235）
- **修正**：观察区条件增加 `last_close < max_price`，与「入池判定 / 在池移出（现价≥上限）」的价格门槛完全一致；
  全表（新增/在池/移除/观察）统一「现价 < 10 元」
- 观察区说明文案改为「仅因**超出新信号窗口**未入池」（价格达标已是前提，不再作为列示原因）
- **效果**（2026-10-16 全市场）：观察区 日线 90 → **16**、周线 79 → **29**、月线 302 → **67**；
  角度分布同步重算（日线 改1 15/改2 20、周线 43/4、月线 66/43）

---

## v2.53 (2026-10-18)

### 反转数值 · 月线改2 窗口收紧 6→4（v7.1）+ 跟踪池首次入库

- `--window-gai2` 月线默认 **6 → 4**：全市场实测（2026-10-16）新增 68 只（改1 25 / 改2 43）偏多，
  收紧到 4 根月线后新增 **42 只（改1 25 / 改2 17）**，观察区 302 只
- **跟踪池首次入库**：`data/reversal_pool_{day,week,month}.json` + `data/reversal_perf_{day,week,month}.csv`
  首次提交（此前因「提交步在产品生成之前」的 bug 从未入库，10-17 已修复该顺序）
  - 10-16 基线：日线 19 只 / 周线 18 只 / 月线 42 只
  - 作用：10-19 起的 CI 从此基线继续跟踪（在池/移除/胜率回填可衔接），而不是每次从空池重新开始
- 全市场 v7 结果（2026-10-16 数据，覆盖 3072~3125 只）：日线 新增19/观察90、周线 18/79、月线 42/302

---

## v2.52 (2026-10-18)

### 反转数值 · 分角度窗口 + 观察区截断 + 周/月线大阳线区间收紧（v7）

- **分角度新信号窗口**：改1（保持强势）走 `--window`（默认 day5 / week3 / month2）；
  改2（死叉回调）走新参数 `--window-gai2`（默认 day5 / **week8 / month6**）
  - 动因：全市场实测（2026-10-16）周线新增 15 只、月线新增 24 只**全部是改1，改2 为 0**——
    改2 必须走完「突破 → 回调 → 死叉下水但不破线」，天然慢于 3 根周线 / 2 根月线窗口，
    沿用改1 的窄窗口等于把改2 结构性挡在门外。改1 追求新鲜度、改2 追求回踩确认，窗口本就该分开
- **存量观察区截断**：新增 `--watch-max-gap`（默认 day15 / week8 / month6），替代原先的 `MAXGAP[tf]`
  ——月线观察区此前达 581 只、报告 85KB，实际不可用
- **周/月线「突破段大阳线」区间改为「突破日前 N 根」**：新增 `--bigyang-lookback`（默认 week6 / month6）；
  日线仍为「突破日所属金叉 → 突破日」（10-17 原需求）。原因：月线金叉可跨 1-2 年，
  例如新乡化纤的阳线取到 2024-04-30 +34.6%，原口径下该条件在月线几乎形同虚设（24 只新增全通过）
- **沙箱验证**（沪深主板前 150 只，数据截至 2026-10-16）
  - 周线：新增 0 → **1（改2）**、观察 4 → 2
  - 月线：新增 2 → **7（改1 2 / 改2 5）**、观察 19 → 9
  - 日线：新增 2（改1）、观察 7 → 4（口径未变）
- 报告头与启动日志同步显示「新信号窗口：改1 X 根 / 改2 Y 根」与大阳线区间口径

---

## v2.51 (2026-10-18)

### 反转数值 · 报告按「改1 / 改2」归类（v6）

- 报告四节（🆕 本次新增 / 📌 在池跟踪 / 🗑️ 本次移除 / 📎 存量结构观察）统一改为**按角度分组**渲染：
  `### 🅰️ 改1 · 保持强势（突破后 MACD 未下水）· N 只` / `### 🅱️ 改2 · 死叉回调（水下反转数值线上方）· N 只`，
  空组不渲染；组内保持原有排序（新增/在池/观察按距突破升序，移除按回调深降序）
- 分组后「角度」列不再重复显示（由子标题表达），表格变窄；`tbl()` 新增 `with_angle` 参数
- 报告首行新增 `> 🧭 角度分布（新增+在池+观察）：改1 X 只 ｜ 改2 Y 只`，PushPlus 摘要同步一行
- **沙箱验证**（沪深主板前 150 只，数据截至 2026-10-16）：日线 改1 8 / 改2 14、周线 改1 2 / 改2 2、
  月线 改1 4 / 改2 5；三份报告表格列错位 0

---

## v2.50 (2026-10-18)

### 反转数值 · 新增「📎 存量结构观察」区（v5）

- **动因**：v4（同日）把周/月线对齐日线后加了「新信号窗口」，7~9 月突破、形态仍完好但 gap 已超窗的老结构
  （如 TCL科技周线 gap=15、荣安地产 gap=7、海德股份 gap=6）会被整体丢弃，无法继续观察形态演变
- **做法**：结构仍有效（`valid` 回调未破线 **且** 突破段有大阳线）但不满足入池条件（超新信号窗口 / 现价≥上限）
  的标的，在报告单列一节「📎 存量结构观察」，附「未入池原因」列；**不入池、不计胜率**，且限 `MAXGAP[tf]` 跟踪期内
- 报告首行统计与 PushPlus 摘要同步带「观察 N」，新增/在池/移除逻辑完全不变
- **沙箱验证**（沪深主板前 150 只，数据截至 2026-10-16）：日线 观察 7 / 周线 4 / 月线 19（含 TCL科技周线 超窗口15>3），
  三份报告表格列错位 0

---

## v2.49 (2026-10-18)

### 反转数值 · 周线/月线口径对齐日线（三周期统一）

- **三个开关统一**（`quant_scripts/reversal_daily_screener.py` v4）
  - `only2 = False` — 周/月线不再「只留改2」，**改1 + 改2 双角度都收**
  - `nowin = False` — 周/月线恢复「新信号窗口」，默认 `WIN_DEFAULT day=5 / week=3 / month=2`（`--window` 可覆盖）
  - `req_bigyang = True` — 「突破段中大阳线（≥5%，涨停自然满足）」**三周期均要求**
- **修既有静默故障：月线从未产出过任何信号** —— `eval_state` 硬门槛 `len(rows) < 80 -> return None`，
  而 westock 月线**硬上限仅 61 根**（`--limit 124/500` 实返 61）→ 月线自 v3（2026-10-13）上线起报告恒为空。
  改为按周期 `MIN_BARS = {day: 80, week: 60, month: 40}`（月线 40 个月≈3.3 年，EMA26 已预热）
- **workflow**：`quant_report.yml` 周线调用加 `--window 3`、月线加 `--window 2`（对齐日线 `--window 5` 的时间尺度）
- **沙箱验证**（沪深主板前 150 只样本，数据截至 2026-10-16）
  - 日线：新增 2（sz000498 山东路桥 gap3、sz000503 国新健康 gap5）
  - 周线：0（样本内 valid+大阳线 4 只，但 gap<=3 且价<10 无命中）
  - 月线：新增 2（sz000100 TCL科技 gap2、sz000552 甘肃能化 gap2）——**首次产出**
  - 池三态（新增/在池/移除）、移出原因（现价≥上限）、报告列渲染均正常，表格列错位 0
- **仅存的周期差异**：最大跟踪期（day 45 / week 30 / month 18 根）、数据周期与长度

---

## v2.48 (2026-10-17)

### 新增「王者突破」选股 + 跟踪池（神龙摆尾尾部突破K × 王者倍量柱）

- **来源**：林中独步《神龙摆尾（三线合一）指标的一个小妙用》——`CG:=MA(C,15); FL:=HHV(CG,5); FS:=CG-(FL-CG);`
  突破K = `涨幅>=3% AND CROSS(C,FL) AND CG<>FS`；实顶(收盘)为强支撑、实底(开盘)破位转压力
- **融合口径**：同一根K线同时满足「神龙突破K」（结构证据）+「王者倍量柱」（量≥2×前5日均量 且 阳线 且 涨幅≥3%，量能证据）
  = **王者突破**（价量双确认）；仅满足其一的只在报告「单条件观察」列出，不入池
- **新脚本** `quant_scripts/wangzhe_breakout.py`
  - 取数走 `fetch`：行情快照预筛（涨幅≥3%）→ 只对候选取K线（3125 只压到 ~320 只）；月线仅对双确认信号取（长期力量 5 力）
  - 评分 = 量能 35 + 三线合一 25 + 横盘 15 + 月线5力 25；入池仅双确认，up to `--max-new`
  - 跟踪池 `data/wangzhe_breakout_pool.json`：每日更新 持有天数/最高浮盈/距实底%；**收盘跌破实底即删除**并记入 removed；
    `hold_top_days>=5` 标 🔥（对应文章「长期小阴小阳横盘不破突破K顶」）
- **接线**：`quant_report.yml` 新增「第五.9步 王者突破选股·跟踪池更新」（after 第五.8，before 推送）→ 跑脚本 → 立即 `git_api_commit`
  （含池/快照/报告）→ 上传「报告/全盘量化」；`config/daily_artifacts.json` quant_report 组 +3 项契约
- **回测结论（400只主板×800根，2023-10~2026-10）**：双条件信号 1784 个，T+5 +0.60%/T+20 +0.65%（基准 +0.24%/+1.01%），
  胜率 45.0% vs 47.9%；「T+5 不破实顶」子集后续更弱（-1.42%/+5日）→ **本形态无独立方向性 alpha（高波动彩票型）**，
  定位「候选观察池 + 防守线纪律」，禁止信号日追买；须叠加双弦/猛兽/鱼身共振
- **Skill**：`wangzhe-breakout`（王者突破扫描/跟踪）

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
