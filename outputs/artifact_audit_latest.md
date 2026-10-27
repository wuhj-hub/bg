# 🔍 产物入库审计 · 2026-10-28

> 扫描 91 个产出路径 / 112 个提交路径 / 31 个消费读取路径
> 🔴 高危（被读取且未提交）**0** ｜ 🟡 未提交 **9** ｜ ✅ 已提交 **82** ｜ ❔ 提交但未见生成 43 ｜ 🧬 陈旧副本 **0**

## 🟡 写而未提交（其余，多为研究/一次性产物）

| 产物 | 写出位置 |
|---|---|
| `_latest.json` | quant_scripts/param_contract_audit.py |
| `_latest.md` | quant_scripts/param_contract_audit.py |
| `em_industry.json` | quant_scripts/inbull_scan.py |
| `kline_{var}_{var}_{var}.json` | quant_scripts/fetch.py |
| `sw_l1_industry.json` | quant_scripts/inbull_scan.py |
| `入牛阈值漂移_{var}.md` | quant_scripts/inbull_threshold_monitor.py |
| `拥挤度监控_{var}.json` | quant_scripts/crowding_watch.py |
| `拥挤度监控_{var}.md` | quant_scripts/crowding_watch.py |
| `权重提案_{var}.json` | quant_scripts/learn_weights.py |

## ✅ 已提交

`123_2b_latest.json`, `ai_chokepoint_watch_{var}.json`, `all_mainboard.csv`, `attrib_latest.json`, `board_top_latest.json`, `caige_track.json`, `data_guard_audit_{var}.md`, `data_guard_{var}.md`, `env_history.json`, `env_latest.json`, `env_对照_latest.md`, `fish_body_latest.json`, `hot_emotion_history.json`, `hot_emotion_latest.json`, `hot_emotion_{var}.md`, `jingjia_auction.csv`, `jingjia_signals.csv`, `kb_health_latest.json`, `kb_health_latest.md`, `kb_health_{var}.md`, `liangxue_latest.json`, `liangxue_minute_check_latest.json`, `liangxue_month_join_latest.json`, `longtou_pool.txt`, `market_regime_latest.json`, `market_regime_latest.md`, `market_width_latest.json`, `mode_aggregate_latest.json`, `monthly_macd_latest.json`, `panhou_lianghua.csv`, `param_contract_latest.json`, `pipeline_audit.json`, `pool_{var}.json`, `premarket_judgment_.json`, `premarket_judgment_latest.json`, `premarket_judgment_{var}.json`, `qiankun_a_latest.json`, `quant_results_2.json`, `quant_results_latest.json`, `quant_results_{var}.json`, `reversal_perf_{var}.csv`, `reversal_pool_{var}.json`, `rsv_strength_latest.json`, `sector_component_em.json`, `system_temp_history.json`, `top_signal_latest.json`, `wangzhe_breakout_latest.json`, `wangzhe_breakout_pool.json`, `wangzhe_signals.csv`, `wangzhe_stats.json`, `xihu_breadth_history.json`, `xihu_breadth_latest.json`, `xihu_rsv_latest.json`, `xihu_turns_latest.json`, `yao_pool.txt`, `yearline_breadth_latest.json`, `yitong_pool.txt`, `{var}.json`, `{var}_latest.json`, `{var}_{var}.csv`, `{var}_{var}.json`, `{var}_{var}.md`, `乖离低买_latest.json`, `仲裁信号日志.csv`, `信号仲裁_latest.json`, `入牛时点_latest.json`, `入牛阈值漂移_latest.json`, `双弦观察池_latest.json`, `四维共振_chinext_kcb_latest.json`, `市场状态判定_{var}.md`, `归因_latest.md`, `情绪指标跟踪.json`, `情绪预判_latest.json`, `执行纪律_latest.json`, `断档分歧_latest.json`, `板块共振_latest.json`, `涨停概念排行_latest.json`, `王者突破_{var}.md`, `竞价快报_{var}.md`, `竞价统计_{var}.md`, `组合风控_latest.json`, `鱼身报告_latest.md`

## ❔ 提交但未见脚本生成（手工或外部产物）

| 产物 | 提交于 |
|---|---|
| `ai_chokepoint_watch_latest.json` | quant_report.yml |
| `artifact_audit.json` | artifact_audit.yml |
| `artifact_audit_latest.md` | artifact_audit.yml |
| `artifact_audit_{var}.md` | artifact_audit.yml |
| `beast_pool_latest.json` | beast_pool.yml |
| `caige_articles` | wangzhe_track.yml(via wangzhe_commit.py) |
| `caige_pool.txt` | quant_report.yml |
| `cross_source_latest.json` | selfcheck_daily.yml |
| `cross_source_latest.md` | selfcheck_daily.yml |
| `dragon_pool.txt` | quant_report.yml |
| `execution_cards_latest.json` | quant_report.yml |
| `glm_brief_review_{var}.md` | quant_report.yml |
| `glm_brief_{var}.md` | premarket_report.yml |
| `hot_emotion_latest.md` | quant_scan.yml |
| `ima_cred_last_ok.json` | quant_scan.yml |
| `market_style_latest.json` | quant_report.yml |
| `paper_portfolio.json` | quant_report.yml |
| `param_contract_latest.md` | selfcheck_daily.yml |
| `pipeline_audit_latest.json` | selfcheck_daily.yml |
| `pool_entries.csv` | quant_report.yml |
| `pool_quality.json` | quant_report.yml |
| `regime_history.csv` | pool_winrate_biweekly.yml |
| `reversal_perf_day.csv` | quant_report.yml |
| `reversal_perf_month.csv` | quant_report.yml |
| `reversal_perf_week.csv` | quant_report.yml |
| `reversal_pool_day.json` | quant_report.yml |
| `reversal_pool_month.json` | quant_report.yml |
| `reversal_pool_week.json` | quant_report.yml |
| `silent_failure_audit.json` | selfcheck_daily.yml |
| `silent_failure_latest.md` | selfcheck_daily.yml |
| `一统天下建仓区股池_latest.json` | quant_report.yml, quant_scan.yml |
| `一统天下建仓区股池_latest.md` | quant_scan.yml |
| `入牛时点扫描_{var}.md` | inbull_scan.yml, quant_report.yml |
| `四态胜率_{var}.md` | quant_report.yml |
| `四维共振_latest.json` | quant_report.yml, quant_scan.yml |
| `复盘报告_{var}.md` | quant_report.yml |
| `妖股池_{var}.json` | yao_gu_pool.yml |
| `妖股池_{var}.md` | yao_gu_pool.yml |
| `涨停型王者_成功率报告` | wangzhe_track.yml(via wangzhe_commit.py) |
| `猛兽突破池_{var}.md` | beast_pool.yml |
| `盘前市场报告_{var}.md` | premarket_report.yml |
| `西湖rsv全市场_{var}.md` | quant_scan.yml |
| `资金快照_{var}.csv` | quant_scan.yml |

## 🧬 多副本新鲜度（同名产物：仓库根 vs outputs/）

| 产物 | 根日期 | outputs日期 | 判定 |
|---|---|---|---|
| `sector_component_em.json` | 2026-10-26 | 2026-10-26 | 同步 |
| `xihu_breadth_history.json` | 2024-06-11 | 2024-06-11 | 同步 |
