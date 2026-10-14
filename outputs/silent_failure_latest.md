# 🔍 体系自检元审计 · 2026-10-15

> 扫描 23 个 workflow ｜ 风险项 **133** ｜ 🔴高危 **0**

## 🟡中危·吞错误（120）

- artifact_audit.yml :: 运行产物入库审计 (L62) — 命中 2>/dev/null（屏蔽 stderr）, set +e, || echo（吞错误）, || true
- artifact_audit.yml :: 提交审计报告 (L84) — 命中 2>/dev/null（屏蔽 stderr）, set +e, || true
- beast_pool.yml :: 预热 westock 数据包 (L66) — 命中 || true
- beast_pool.yml :: 准备候选池 (L71) — 命中 2>/dev/null（屏蔽 stderr）, || true
- beast_pool.yml :: 提交产物 (L87) — 命中 set +e, || true
- bt_cycle.yml :: 回测周期回归（数据体检 + 基准 + 候选复核） (L33) — 命中 continue-on-error: true, set +e
- bt_cycle.yml :: 提交回测报告 (L51) — 命中 2>/dev/null（屏蔽 stderr）, set +e
- duowei_fish.yml :: 生成沪深主板清单（失败回退仓库缓存） (L77) — 命中 continue-on-error: true, || echo（吞错误）
- duowei_fish.yml :: 预热westock数据包 (L85) — 命中 continue-on-error: true, || true
- duowei_fish.yml :: 上传鱼身报告到「多维量化→多维度」文件夹 (L105) — 命中 2>/dev/null（屏蔽 stderr）, set +e, || true
- duowei_fish.yml :: 提交产物到仓库 (L131) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- emotion_backtest_monthly.yml :: 预热 westock 数据包 (L39) — 命中 || true
- emotion_backtest_monthly.yml :: 运行回测（120 交易日） (L48) — 命中 || true
- emotion_backtest_monthly.yml :: 提交报告 (L51) — 命中 2>/dev/null（屏蔽 stderr）, set +e, || true
- evidence_review.yml :: 生成 evidence 复核工作单 (L28) — 命中 || echo（吞错误）, || true
- evidence_review.yml :: 提交工作单到仓库（outputs/） (L40) — 命中 continue-on-error: true
- evidence_review.yml :: 回测周期回归（月度，report-only 不改代码） (L72) — 命中 continue-on-error: true, set +e
- evidence_review.yml :: PushPlus 推送复核提醒（含待复核/过期统计） (L89) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- guard_selfcheck.yml :: IMA 凭证预检（失效/疑似过期立即微信告警） (L50) — 命中 continue-on-error: true, || true
- guard_selfcheck.yml :: 上传自检报告到盘后量化文件夹（供查阅） (L62) — 命中 continue-on-error: true, || echo（吞错误）
- inbull_scan.yml :: 安装依赖（pandas + westock CLI 免npx） (L43) — 命中 || true
- inbull_scan.yml :: 入牛时点扫描 + 上传知识库 + 推送 + 提交 (L47) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- inbull_threshold_monitor.yml :: 安装依赖（pandas + westock CLI 免npx 备用） (L31) — 命中 || true
- inbull_threshold_monitor.yml :: 季度复算 + 漂移对比 + 上传知识库 + 推送 + 提交 (L35) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- intraday_monitor.yml :: 开盘八法强形态扫描+突破监控 (L116) — 命中 continue-on-error: true
- jingjia_track.yml :: 上传竞价报告到知识库「报告/竞价」 (L86) — 命中 continue-on-error: true, || echo（吞错误）
- market_regime.yml :: 提交判定结果到仓库 (L68) — 命中 continue-on-error: true, set +e, || true
- pool_winrate_biweekly.yml :: 安装依赖 + 全局 westock（免 npx 加速） (L66) — 命中 || echo（吞错误）
- pool_winrate_biweekly.yml :: 提交总览到仓库 (L79) — 命中 continue-on-error: true, || echo（吞错误）
- pool_winrate_biweekly.yml :: 上传知识库「报告 / 全盘量化」 (L94) — 命中 continue-on-error: true, || echo（吞错误）
- premarket_report.yml :: 生成盘前市场报告 (L74) — 命中 || echo（吞错误）
- premarket_report.yml :: 提交盘前预判到仓库（供复盘报告真实验证） (L87) — 命中 continue-on-error: true, set +e, || true
- probe_em.yml :: 东财板块接口参数探测（找可用 fs/ 端点） (L21) — 命中 continue-on-error: true
- probe_em.yml :: 同花顺页面数据内容验证（防hexin-v反爬空表） (L25) — 命中 2>/dev/null（屏蔽 stderr）, || echo（吞错误）
- probe_em.yml :: 同花顺板块页结构验证（行业列表+成分页） (L39) — 命中 2>/dev/null（屏蔽 stderr）
- probe_em.yml :: 东财板块成分拉取（行业+概念，覆盖全市场含次新） (L79) — 命中 2>/dev/null（屏蔽 stderr）, || echo（吞错误）, || true
- probe_em.yml :: 提交东财板块映射到仓库 (L85) — 命中 continue-on-error: true
- quant_report.yml :: 安装 Python 依赖（pandas+numpy+matplotlib）+ 中文字体 (L66) — 命中 || echo（吞错误）
- quant_report.yml :: 数据源连通性预检 + 股池备份 (L78) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || true
- quant_report.yml :: 上游扫描结果检查（失败则告警退出） (L104) — 命中 || true
- quant_report.yml :: 猛兽本月股池同步（主池/观察池分层 + 剔除不符合） (L114) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 双弦每日报告+月度股池同步（收编sx2单一出口） (L129) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 才哥战法股池扫描+跟踪（四战法独立股池） (L153) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 龙头战法池扫描（dragon_leader·100分五维） (L179) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 一统天下建仓区股池扫描+跟踪（多周期共振） (L196) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 妖股发现与跟踪池（启动入池+出货预警推送） (L221) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 龙头定位扫描（连板梯队+见顶五维预警） (L240) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 市场风格轴扫描（机构主导 vs 游资主导 + 猛兽双模式交叉验证） (L257) — 命中 continue-on-error: true
- quant_report.yml :: 四维共振评分（复用上游 quant_scan 产物，缺失则本地补跑兜底） (L264) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || echo（吞错误）
- quant_report.yml :: 全系统信号仲裁（统一出口·今日操作清单） (L285) — 命中 continue-on-error: true
- quant_report.yml :: 宁静AI卡位每日观察清单 (L290) — 命中 continue-on-error: true, || true
- quant_report.yml :: 创业板/科创四维补充扫描（代表性补充通道） (L298) — 命中 continue-on-error: true
- quant_report.yml :: 生成并上传股池标的跟踪报告（三阶漏斗） (L308) — 命中 continue-on-error: true
- quant_report.yml :: 持仓组合风控（portfolio_risk） (L325) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_report.yml :: 实盘执行纪律报告（trade_journal） (L335) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_report.yml :: 个股执行卡生成（持仓 + 当日信号仲裁候选） (L343) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 乖离低买扫描（一统天下·跌破MA5>7%） (L350) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || echo（吞错误）, || true
- quant_report.yml :: 入牛时点扫描（板块入牛/个股入牛·月线5线） (L367) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || echo（吞错误）
- quant_report.yml :: 市场状态判定（三级别力量·内联刷新） (L401) — 命中 continue-on-error: true, set +e, || true
- quant_report.yml :: 股池守护（数据源故障则不覆盖历史股池） (L429) — 命中 continue-on-error: true
- quant_report.yml :: 盘后数据健康审计（产物可信度） (L441) — 命中 continue-on-error: true, set +e, || true
- quant_report.yml :: 提交报告产物到仓库（供盘前报告引用） (L455) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || true
- quant_report.yml :: 自动生成复盘报告并上传 (L496) — 命中 continue-on-error: true, || echo（吞错误）
- quant_report.yml :: env 对照三系统温度（观察期） (L554) — 命中 continue-on-error: true, || echo（吞错误）
- quant_report.yml :: 资金四态胜率（抢筹/进场/控盘/观望） (L568) — 命中 continue-on-error: true, || echo（吞错误）, || true
- quant_report.yml :: 股池入池快照（OOS 数据维护） (L589) — 命中 continue-on-error: true, set +e, || true
- quant_report.yml :: 反转数值周线信号上传推送 (L626) — 命中 continue-on-error: true, || true
- quant_report.yml :: 体系自检 — 健康评分 / 市场状态 / 异常检测 (L673) — 命中 continue-on-error: true, set +e, || true
- quant_report.yml :: 推送自检报告到微信 (L691) — 命中 continue-on-error: true
- quant_scan.yml :: 生成沪深主板清单（失败回退缓存 all_mainboard.csv，不阻断） (L78) — 命中 continue-on-error: true, || echo（吞错误）
- quant_scan.yml :: IMA 凭证早期预检（失效立即微信告警，不阻断扫描） (L86) — 命中 continue-on-error: true, || true
- quant_scan.yml :: 预热westock数据包 (L96) — 命中 set +e, || true
- quant_scan.yml :: 板块成分映射（东财·runner 可达） (L126) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || echo（吞错误）, || true
- quant_scan.yml :: 全量量化扫描（盘后量化） (L147) — 命中 2>/dev/null（屏蔽 stderr）, || echo（吞错误）
- quant_scan.yml :: 热点情绪扫描（hot_emotion 连板梯队+情绪温度） (L163) — 命中 2>/dev/null（屏蔽 stderr）, set +e, || echo（吞错误）, || true
- quant_scan.yml :: 市场情绪状态与次日预判（emotion_forecast） (L187) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 年线广度扫描（站上年线个股占比） (L195) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 西湖广度扫描（下雨图：强势股/第二阶段/新高/新低） (L204) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 断档分歧板块择时信号 (L214) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || true
- quant_scan.yml :: 涨停概念排行（涨停股×概念聚合，热点概念排序） (L223) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 123/2B/ABC反转信号扫描 (L236) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: RSV相对强度扫描 (L244) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 西湖-RSV 多周期相对强度扫描（全市场） (L252) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 月线MACD监控 (L263) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || true
- quant_scan.yml :: 市场见顶五维监测（top_signal） (L270) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 量学扫描（黑马王子体系，与曾星智月线闸门同级） (L279) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 量学×月线联合输出（月线多头∩量学PASS） (L287) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 量学PASS分时量波验证（人线偏离检测） (L295) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || echo（吞错误）, || true
- quant_scan.yml :: 分时强度分析（信号股分时MACD） (L303) — 命中 continue-on-error: true
- quant_scan.yml :: 板块资金共振（本地复算·无外部依赖） (L308) — 命中 continue-on-error: true
- quant_scan.yml :: 一统天下多周期扫描（建仓区+月线反转+RSV50三线强度） (L325) — 命中 continue-on-error: true
- quant_scan.yml :: 四维共振评分（政策/资金/筹码/关联方四维证据链） (L334) — 命中 continue-on-error: true
- quant_scan.yml :: 上传三系统原始数据（鱼身/双弦/猛兽，盘前引用数据源） (L340) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, || true
- quant_scan.yml :: 上传全盘量化报告到全盘量化文件夹 (L374) — 命中 || true
- quant_scan.yml :: 扫描产物可信度审计 (L406) — 命中 continue-on-error: true, set +e, || true
- quant_scan.yml :: 环境唯一化引擎（env 温度 → 仓位总闸） (L422) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || echo（吞错误）, || true
- quant_scan.yml :: 提交扫描产物到仓库（供盘前引用/报告workflow读取） (L440) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e, || true
- quant_scan.yml :: 关键扫描产物检查（缺失即告警） (L498) — 命中 continue-on-error: true, || true
- selfcheck_daily.yml :: 预热 westock 数据包（避免首个 kl 调用冷启动失败） (L61) — 命中 || echo（吞错误）
- selfcheck_daily.yml :: ① 数据源交叉验证（westock × 东财 × 腾讯） (L66) — 命中 continue-on-error: true, set +e
- selfcheck_daily.yml :: ② 静默失败元审计（扫 workflow 自身的假绿风险） (L78) — 命中 continue-on-error: true, set +e
- selfcheck_daily.yml :: ③ 流水线自愈巡检（run状态/步骤耗时/产物新鲜度/脚本异常） (L90) — 命中 2>/dev/null（屏蔽 stderr）, continue-on-error: true, set +e
- selfcheck_daily.yml :: 提交自检产物到仓库 (L105) — 命中 2>/dev/null（屏蔽 stderr）, set +e
- selfcheck_daily.yml :: 异常告警到微信 (L124) — 命中 2>/dev/null（屏蔽 stderr）, || echo（吞错误）
- selfcheck_daily.yml :: 上传自检报告到盘后量化文件夹 (L142) — 命中 continue-on-error: true, || echo（吞错误）
- wangzhe_track.yml :: 安装 westock 取数 CLI（免 npx） (L63) — 命中 continue-on-error: true
- wangzhe_track.yml :: 涨停王者·合格标的漏斗 (L87) — 命中 continue-on-error: true
- wangzhe_track.yml :: 合格标的上传知识库 + 推送 (L92) — 命中 continue-on-error: true, || echo（吞错误）
- wangzhe_track.yml :: 才哥公众号文章跟踪 (L111) — 命中 continue-on-error: true
- weight_learn.yml :: 预热 westock 数据包 (L57) — 命中 continue-on-error: true, || echo（吞错误）
- weight_learn.yml :: 推送月度提案报告 (L65) — 命中 continue-on-error: true, || echo（吞错误）
- weight_learn.yml :: 上传提案到知识库「报告/指标存档」 (L79) — 命中 continue-on-error: true, || echo（吞错误）
- weight_learn.yml :: ② 权重改进回验（到期项） (L98) — 命中 continue-on-error: true
- weight_learn.yml :: 推送回验报告 (L109) — 命中 continue-on-error: true, || echo（吞错误）
- weight_learn.yml :: 提交提案 + 回验产物 + 台账 (L119) — 命中 set +e
- yao_gu_pool.yml :: 安装依赖 (L63) — 命中 || true
- yao_gu_pool.yml :: 预热 westock (L69) — 命中 || true
- yao_gu_pool.yml :: 准备主板清单 (L73) — 命中 || echo（吞错误）
- yao_gu_pool.yml :: 上传知识库（报告·全盘量化） (L89) — 命中 continue-on-error: true, || echo（吞错误）
- yao_gu_pool.yml :: 提交产物 (L105) — 命中 set +e, || true

## 🟡中危·依赖外部 cron（13）

- artifact_audit.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- beast_pool.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- bt_cycle.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- evidence_review.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- guard_selfcheck.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- inbull_scan.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- intraday_monitor.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- market_regime.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- premarket_report.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- selfcheck_daily.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- wangzhe_track.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- weight_learn.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆
- yao_gu_pool.yml :: on: 段 — 原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆

## 各 workflow 静默失败热点

| workflow | 风险数 | 高危 |
|---|---|---|
| artifact_audit.yml | 3 | — |
| beast_pool.yml | 4 | — |
| bt_cycle.yml | 3 | — |
| duowei_fish.yml | 4 | — |
| emotion_backtest_monthly.yml | 3 | — |
| evidence_review.yml | 5 | — |
| guard_selfcheck.yml | 3 | — |
| inbull_scan.yml | 3 | — |
| inbull_threshold_monitor.yml | 2 | — |
| intraday_monitor.yml | 2 | — |
| jingjia_track.yml | 1 | — |
| market_regime.yml | 2 | — |
| pool_winrate_biweekly.yml | 3 | — |
| premarket_report.yml | 3 | — |
| probe_em.yml | 5 | — |
| probe_kpl.yml | 0 | — |
| probe_search.yml | 0 | — |
| quant_report.yml | 32 | — |
| quant_scan.yml | 29 | — |
| selfcheck_daily.yml | 8 | — |
| wangzhe_track.yml | 5 | — |
| weight_learn.yml | 7 | — |
| yao_gu_pool.yml | 6 | — |
