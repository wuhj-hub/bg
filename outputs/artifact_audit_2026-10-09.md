# 🔍 产物入库审计 · 2026-10-09

> 扫描 71 个产出路径 / 95 个提交路径 / 30 个消费读取路径
> 🔴 高危（被读取且未提交）**0** ｜ 🟡 未提交 **2** ｜ ✅ 已提交 **69** ｜ ❔ 提交但未见生成 36

## 🟡 写而未提交（其余，多为研究/一次性产物）

| 产物 | 写出位置 |
|---|---|
| `em_industry.json` | quant_scripts/inbull_scan.py |
| `sw_l1_industry.json` | quant_scripts/inbull_scan.py |

## ✅ 已提交

`123_2b_latest.json`, `ai_chokepoint_watch_{var}.json`, `all_mainboard.csv`, `board_top_latest.json`, `caige_track.json`, `data_guard_audit_{var}.md`, `data_guard_{var}.md`, `env_history.json`, `env_latest.json`, `env_对照_latest.md`, `fish_body_latest.json`, `hot_emotion_history.json`, `hot_emotion_latest.json`, `hot_emotion_{var}.md`, `jingjia_auction.csv`, `jingjia_signals.csv`, `liangxue_latest.json`, `liangxue_minute_check_latest.json`, `liangxue_month_join_latest.json`, `longtou_pool.txt`, `market_regime_latest.json`, `market_regime_latest.md`, `market_width_latest.json`, `mode_aggregate_latest.json`, `monthly_macd_latest.json`, `panhou_lianghua.csv`, `pool_{var}.json`, `premarket_judgment_.json`, `premarket_judgment_latest.json`, `premarket_judgment_{var}.json`, `qiankun_a_latest.json`, `quant_results_2.json`, `quant_results_latest.json`, `quant_results_{var}.json`, `rsv_strength_latest.json`, `sector_component_em.json`, `system_temp_history.json`, `top_signal_latest.json`, `wangzhe_signals.csv`, `wangzhe_stats.json`, `xihu_breadth_history.json`, `xihu_breadth_latest.json`, `xihu_rsv_latest.json`, `xihu_turns_latest.json`, `yao_pool.txt`, `yearline_breadth_latest.json`, `yitong_pool.txt`, `{var}.json`, `{var}_latest.json`, `{var}_{var}.csv`, `{var}_{var}.json`, `{var}_{var}.md`, `乖离低买_latest.json`, `仲裁信号日志.csv`, `信号仲裁_latest.json`, `入牛时点_latest.json`, `双弦观察池_latest.json`, `四维共振_chinext_kcb_latest.json`, `四维共振_latest.json`, `市场状态判定_{var}.md`, `情绪指标跟踪.json`, `情绪预判_latest.json`, `执行纪律_latest.json`, `断档分歧_latest.json`, `板块共振_latest.json`, `涨停概念排行_latest.json`, `竞价统计_{var}.md`, `组合风控_latest.json`, `鱼身报告_latest.md`

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
| `pipeline_audit.json` | selfcheck_daily.yml |
| `pipeline_audit_latest.json` | selfcheck_daily.yml |
| `pool_entries.csv` | quant_report.yml |
| `pool_quality.json` | quant_report.yml |
| `silent_failure_audit.json` | selfcheck_daily.yml |
| `silent_failure_latest.md` | selfcheck_daily.yml |
| `一统天下建仓区股池_latest.json` | quant_report.yml, quant_scan.yml |
| `一统天下建仓区股池_latest.md` | quant_scan.yml |
| `入牛时点扫描_{var}.md` | inbull_scan.yml, quant_report.yml |
| `四态胜率_{var}.md` | quant_report.yml |
| `复盘报告_{var}.md` | quant_report.yml |
| `妖股池_{var}.json` | yao_gu_pool.yml |
| `妖股池_{var}.md` | yao_gu_pool.yml |
| `涨停型王者_成功率报告` | wangzhe_track.yml(via wangzhe_commit.py) |
| `猛兽突破池_{var}.md` | beast_pool.yml |
| `盘前市场报告_{var}.md` | premarket_report.yml |
| `纸面组合跟踪报告_{var}.md` | quant_report.yml |
| `西湖rsv全市场_{var}.md` | quant_scan.yml |
| `资金快照_{var}.csv` | quant_scan.yml |
