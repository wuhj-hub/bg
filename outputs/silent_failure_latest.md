# 🔍 体系自检元审计 · 2026-09-21

> 扫描 14 个 workflow ｜ 风险项 **88** ｜ 🔴高危 **0**

## 🟡中危·吞错误（80）

- artifact_audit.yml :: 运行产物入库审计 (L33) — 命中 2>/dev/null（屏蔽 stderr）, set +e, || echo（吞错误）, || true
- artifact_audit.yml :: 提交审计报告 (L53) — 命中 2>/dev/null（屏蔽 stderr）, || true
- beast_pool.yml :: 预热 westock 数据包 (L46) — 命中 || true
- beast_pool.yml :: 准备候选池 (L51) — 命中 2>/dev/null（屏蔽 stderr）, || true
- beast_pool.yml :: 提交产物 (L67) — 命中 set +e, || true
- evidence_review.yml :: 生成 evidence 复核工作单 (L26) — 命中 || echo（吞错误）, || true
- evidence_review.yml :: 提交工作单到仓库（outputs/） (L38) — 命中 continue-on-error: true
- evidence_review.yml :: PushPlus 推送复核提醒（含待复核/过期统计） (L70) — 命中 continue-on-error: true, || echo（吞错误）
- guard_selfcheck.yml :: IMA 凭证预检（失效/疑似过期立即微信告警） (L32) — 命中 continue-on-error: true, || true
- guard_selfcheck.yml :: 上传自检报告到盘后量化文件夹（供查阅） (L44) — 命中 continue-on-error: true, || echo（吞错误）
- intraday_monitor.yml :: 开盘八法强形态扫描+突破监控 (L94) — 命中 continue-on-error: true
- market_regime.yml :: 提交判定结果到仓库 (L48) — 命中 continue-on-error: true, set +e, || true
- premarket_report.yml :: 生成盘前市场报告 (L45) — 命中 || echo（吞错误）
- premarket_report.yml :: 提交盘前预判到仓库（供复盘报告真实验证） (L57) — 命中 continue-on-error: true, set +e, || true
- probe_em.yml :: 东财板块接口参数探测（找可用 fs/ 端点） (L21) — 命中 continue-on-error: true
- probe_em.yml :: 同花顺页面数据内容验证（防hexin-v反爬空表） (L25) — 命中 2>/dev/null（屏蔽 stderr）, || echo（吞错误）
- probe_em.yml :: 同花顺板块页结构验证（行业列表+成分页） (L39) — 命中 2>/dev/null（屏蔽 stderr）
- probe_em.yml :: 东财板块成分拉取（行业+概念，覆盖全市场含次新） (L79) — 命中 2>/dev/null（屏蔽 stderr）, || echo（吞错误）, || true
- probe_em.yml :: 提交东财板块映射到仓库 (L85) — 命中 continue-on-error: true
- quant_report.yml :: 数据源连通性预检 + 股池备份 (L49) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || true
- quant_report.yml :: 上游扫描结果检查（失败则告警退出） (L73) — 命中 || true
- quant_report.yml :: 猛兽本月股池同步（主池/观察池分层 + 剔除不符合） (L83) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 双弦每日报告+月度股池同步（收编sx2单一出口） (L98) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 才哥战法股池扫描+跟踪（四战法独立股池） (L122) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 龙头战法池扫描（dragon_leader·100分五维） (L148) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 一统天下建仓区股池扫描+跟踪（多周期共振） (L165) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 妖股发现与跟踪池（启动入池+出货预警推送） (L190) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 龙头定位扫描（连板梯队+见顶五维预警） (L207) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 市场风格轴扫描（机构主导 vs 游资主导 + 猛兽双模式交叉验证） (L224) — 命中 continue-on-error: true
- quant_report.yml :: 四维共振评分（政策/资金/筹码/关联方四维证据链） (L231) — 命中 continue-on-error: true
- quant_report.yml :: 全系统信号仲裁（统一出口·今日操作清单） (L237) — 命中 continue-on-error: true
- quant_report.yml :: 宁静AI卡位每日观察清单 (L242) — 命中 continue-on-error: true, || true
- quant_report.yml :: 创业板/科创四维补充扫描（代表性补充通道） (L250) — 命中 continue-on-error: true
- quant_report.yml :: 生成并上传股池标的跟踪报告（三阶漏斗） (L260) — 命中 continue-on-error: true
- quant_report.yml :: 持仓组合风控（portfolio_risk） (L277) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_report.yml :: 实盘执行纪律报告（trade_journal） (L287) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_report.yml :: 个股执行卡生成（持仓 + 当日信号仲裁候选） (L295) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 乖离低买扫描（一统天下·跌破MA5>7%） (L302) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || echo（吞错误）, || true
- quant_report.yml :: 市场状态判定（三级别力量·内联刷新） (L323) — 命中 continue-on-error: true, set +e, || true
- quant_report.yml :: 股池守护（数据源故障则不覆盖历史股池） (L351) — 命中 continue-on-error: true
- quant_report.yml :: 盘后数据健康审计（产物可信度） (L363) — 命中 continue-on-error: true, set +e, || true
- quant_report.yml :: 提交报告产物到仓库（供盘前报告引用） (L377) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || true
- quant_report.yml :: 自动生成复盘报告并上传 (L414) — 命中 continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 股池信号实盘胜率跟踪 (L442) — 命中 continue-on-error: true, || echo（吞错误）, || true
- quant_report.yml :: 纸面组合跟踪（选股方法对比） (L467) — 命中 continue-on-error: true
- quant_report.yml :: 反转数值周线信号上传推送 (L486) — 命中 continue-on-error: true, || true
- quant_report.yml :: 体系自检 — 健康评分 / 市场状态 / 异常检测 (L524) — 命中 continue-on-error: true, set +e, || true
- quant_report.yml :: 推送自检报告到微信 (L542) — 命中 continue-on-error: true
- quant_scan.yml :: 生成沪深主板清单（失败回退缓存 all_mainboard.csv，不阻断） (L53) — 命中 continue-on-error: true, || echo（吞错误）
- quant_scan.yml :: IMA 凭证早期预检（失效立即微信告警，不阻断扫描） (L61) — 命中 continue-on-error: true, || true
- quant_scan.yml :: 预热westock数据包 (L71) — 命中 set +e, || true
- quant_scan.yml :: 板块成分映射（东财·runner 可达） (L98) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || echo（吞错误）, || true
- quant_scan.yml :: 全量量化扫描（盘后量化） (L119) — 命中 2>/dev/null（屏蔽 stderr）, || echo（吞错误）
- quant_scan.yml :: 热点情绪扫描（hot_emotion 连板梯队+情绪温度） (L135) — 命中 2>/dev/null（屏蔽 stderr）, set +e, || echo（吞错误）, || true
- quant_scan.yml :: 市场情绪状态与次日预判（emotion_forecast） (L159) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 年线广度扫描（站上年线个股占比） (L167) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 断档分歧板块择时信号 (L175) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || true
- quant_scan.yml :: 123/2B/ABC反转信号扫描 (L183) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: RSV相对强度扫描 (L191) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 西湖-RSV 多周期相对强度扫描（全市场） (L199) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 月线MACD监控 (L210) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || true
- quant_scan.yml :: 市场见顶五维监测（top_signal） (L217) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 量学扫描（黑马王子体系，与曾星智月线闸门同级） (L226) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 量学×月线联合输出（月线多头∩量学PASS） (L234) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 量学PASS分时量波验证（人线偏离检测） (L242) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 分时强度分析（信号股分时MACD） (L250) — 命中 continue-on-error: true
- quant_scan.yml :: 板块资金共振（本地复算·无外部依赖） (L255) — 命中 continue-on-error: true
- quant_scan.yml :: 一统天下多周期扫描（建仓区+月线反转+RSV50三线强度） (L272) — 命中 continue-on-error: true
- quant_scan.yml :: 上传三系统原始数据（鱼身/双弦/猛兽，盘前引用数据源） (L277) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || true
- quant_scan.yml :: 上传全盘量化报告到全盘量化文件夹 (L311) — 命中 || true
- quant_scan.yml :: 扫描产物可信度审计 (L343) — 命中 continue-on-error: true, set +e, || true
- quant_scan.yml :: 提交扫描产物到仓库（供盘前引用/报告workflow读取） (L358) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || true
- quant_scan.yml :: 关键扫描产物检查（缺失即告警） (L413) — 命中 continue-on-error: true, || true
- selfcheck_daily.yml :: 预热 westock 数据包（避免首个 kl 调用冷启动失败） (L38) — 命中 || echo（吞错误）
- selfcheck_daily.yml :: ① 数据源交叉验证（westock × 东财 × 腾讯） (L43) — 命中 continue-on-error: true, set +e
- selfcheck_daily.yml :: ② 静默失败元审计（扫 workflow 自身的假绿风险） (L55) — 命中 continue-on-error: true, set +e
- selfcheck_daily.yml :: 提交自检产物到仓库 (L67) — 命中 2>/dev/null（屏蔽 stderr）
- selfcheck_daily.yml :: 异常告警到微信 (L86) — 命中 || echo（吞错误）
- selfcheck_daily.yml :: 上传自检报告到盘后量化文件夹 (L102) — 命中 continue-on-error: true, || echo（吞错误）
- wangzhe_track.yml :: 才哥公众号文章跟踪 (L56) — 命中 continue-on-error: true

## 🟡中危·依赖外部 cron（8）

- beast_pool.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- guard_selfcheck.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- intraday_monitor.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- market_regime.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- premarket_report.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- quant_scan.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- selfcheck_daily.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- wangzhe_track.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆

## 各 workflow 静默失败热点

| workflow | 风险数 | 高危 |
|---|---|---|
| artifact_audit.yml | 2 | — |
| beast_pool.yml | 4 | — |
| evidence_review.yml | 3 | — |
| guard_selfcheck.yml | 3 | — |
| intraday_monitor.yml | 2 | — |
| market_regime.yml | 2 | — |
| premarket_report.yml | 3 | — |
| probe_em.yml | 5 | — |
| probe_kpl.yml | 0 | — |
| probe_search.yml | 0 | — |
| quant_report.yml | 29 | — |
| quant_scan.yml | 26 | — |
| selfcheck_daily.yml | 7 | — |
| wangzhe_track.yml | 2 | — |
