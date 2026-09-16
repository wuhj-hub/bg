# 🔍 产物入库审计 · 2026-09-16

> 扫描 114 个产出路径 / 58 个提交路径 / 24 个消费读取路径
> 🔴 高危（被读取且未提交）**0** ｜ 🟡 未提交 **61** ｜ ✅ 已提交 **53** ｜ ❔ 提交但未见生成 14

## 🟡 写而未提交（其余，多为研究/一次性产物）

| 产物 | 写出位置 |
|---|---|
| `000001.json` | skills_backup/强势体系/backtest.py |
| `_d.csv` | docs/backtests_archive/backtest_2b_mainboard.py, docs/backtests_archive/backtest_2b_mainboard_m30.py, docs/backtests_archive/backtest_30m_divergence_opt.py |
| `_m30.csv` | docs/backtests_archive/backtest_2b_mainboard_m30.py |
| `ai_chain_pool.json` | quant_scripts/evidence_review.py |
| `ai_chokepoint_watch_{var}.md` | quant_scripts/ai_chokepoint_guard.py |
| `artifact_audit.json` | quant_scripts/artifact_audit.py |
| `artifact_audit_{var}.md` | quant_scripts/artifact_audit.py |
| `beast_results.txt` | quant_scripts/monthly_pool_sync.py |
| `bt_2b_combo.json` | docs/backtests_archive/backtest_reversal_2b_combo.py |
| `bt_2b_results.json` | docs/backtests_archive/backtest_reversal_2b.py |
| `bt_30m_div_opt.json` | docs/backtests_archive/backtest_30m_divergence_opt.py |
| `bt_divergence.json` | docs/backtests_archive/backtest_reversal_divergence.py |
| `bt_results.json` | docs/backtests_archive/backtest_reversal_levels.py |
| `caige_urls.txt` | quant_scripts/caige_track.py |
| `combo_results.json` | docs/backtests_archive/backtest_reversal_combo.py |
| `evidence_review_{var}.md` | quant_scripts/evidence_review.py |
| `finance.json` | skills_backup/强势体系/wuwei_verify.py |
| `fish_body_enhanced_.json` | premarket_scripts/premarket_fishbody.py, skills_backup/盘前市场报告/scripts/premarket_fishbody.py |
| `funnel_results.json` | docs/backtests_archive/backtest_reversal_funnel.py |
| `holdings.txt` | quant_scripts/execution_card.py |
| `kline_month_adj.csv` | skills_backup/板块个股入牛时点/scripts/scan_inbull.py, skills_backup/板块个股入牛时点/scripts/ths_fetch.py |
| `kline_week_adj.csv` | skills_backup/板块个股入牛时点/scripts/ths_fetch_week.py |
| `liangxue_winrate_latest.json` | quant_scripts/win_rate_liangxue.py |
| `market_width_{var}.md` | market_width.py, quant_scripts/market_width.py |
| `panhou_lianghua.md` | full_market_dualdim.py |
| `pool.csv` | skills_backup/板块个股入牛时点/scripts/scan_inbull.py, skills_backup/板块个股入牛时点/scripts/ths_fetch.py, skills_backup/板块个股入牛时点/scripts/ths_fetch_week.py |
| `pool_51.txt` | skills_backup/强势体系/backtest.py |
| `rsv_strength_{var}.md` | quant_scripts/rsv_strength.py |
| `samples.json` | skills_backup/强势体系/wuwei_verify.py |
| `system_temp_history.json` | skills_backup/盘前市场报告/scripts/market_charts.py |
| `wangzhe_benchmark.json` | quant_scripts/wangzhe_track.py |
| `wuwei_verify_result.json` | skills_backup/强势体系/wuwei_verify.py |
| `{var}_d.csv` | docs/backtests_archive/backtest_reversal_levels.py, quant_scripts/fetch_mainboard_data.py |
| `{var}_day.json` | skills_backup/强势体系/wuwei_verify.py |
| `{var}_m30.csv` | quant_scripts/fetch_mainboard_data.py |
| `{var}_month.json` | skills_backup/强势体系/wuwei_verify.py |
| `{var}_w.csv` | docs/backtests_archive/backtest_reversal_levels.py |
| `乖离低买_{var}.md` | quant_scripts/yitong_guaili_screener.py |
| `信号仲裁_{var}.md` | quant_scripts/signal_arbiter.py, signal_arbiter.py |
| `入牛时点扫描_{var}.md` | skills_backup/板块个股入牛时点/scripts/scan_inbull.py |
| `双弦本月股池_{var}.md` | quant_scripts/dual_pool_sync.py |
| `反转数值周线信号_{var}.md` | quant_scripts/gen_review_report.py, quant_scripts/reversal_funnel_screener.py |
| `回测卡_{var}_{var}.json` | quant_scripts/backtest_gate.py |
| `回测卡_猛兽技术代理_持{var}周_{var}.md` | quant_scripts/beast_tech_backtest.py |
| `回测卡_鱼身{var}_持{var}日_{var}.md` | quant_scripts/fish3_backtest.py |
| `年线广度_{var}.md` | quant_scripts/yearline_breadth.py |
| `开盘强形态_{var}.json` | quant_scripts/kaipan_8.py |
| `才哥战法股池_{var}.json` | quant_scripts/caige_pool.py |
| `才哥战法股池_{var}.md` | quant_scripts/caige_pool.py |
| `执行纪律_{var}.md` | quant_scripts/trade_journal.py |
| `断档分歧_{var}.md` | quant_scripts/sector_divergence.py |
| `无为显性建仓标准_回测报告_{var}.md` | quant_scripts/wuwei_xianxing_report.py |
| `板块共振对照_{var}.md` | sector_resonance_local.py |
| `猛兽本月股池_{var}.md` | quant_scripts/monthly_pool_sync.py |
| `猛兽股池_{var}.md` | quant_scripts/monthly_pool_sync.py |
| `环境切换决策表_验证.md` | quant_scripts/research/regime_new.py |
| `组合风控_{var}.md` | quant_scripts/portfolio_risk.py |
| `股池标的跟踪报告_{var}.md` | quant_scripts/pool_tracking_report.py, skills_backup/猛兽体系/scripts/pool_tracking_report.py |
| `自选清单_{var}.txt` | quant_scripts/signal_arbiter.py, signal_arbiter.py |
| `见顶五维监测_{}.md` | quant_scripts/top_signal.py |
| `龙头定位_{var}.json` | quant_scripts/longtou.py, skills_backup/盘前市场报告/scripts/longtou.py |

## ✅ 已提交

`123_2b_latest.json`, `ai_chokepoint_watch_{var}.json`, `all_mainboard.csv`, `board_top_latest.json`, `caige_track.json`, `data_guard_audit_{var}.md`, `data_guard_{var}.md`, `fish_body_latest.json`, `hot_emotion_history.json`, `hot_emotion_latest.json`, `hot_emotion_{var}.md`, `liangxue_latest.json`, `liangxue_minute_check_latest.json`, `liangxue_month_join_latest.json`, `longtou_pool.txt`, `market_regime_latest.json`, `market_regime_latest.md`, `market_width_latest.json`, `mode_aggregate_latest.json`, `monthly_macd_latest.json`, `panhou_lianghua.csv`, `pool_{var}.json`, `premarket_judgment_latest.json`, `premarket_judgment_{var}.json`, `qiankun_a_latest.json`, `quant_results_latest.json`, `quant_results_{var}.json`, `rsv_strength_latest.json`, `sector_component_em.json`, `top_signal_latest.json`, `wangzhe_signals.csv`, `wangzhe_stats.json`, `yao_pool.txt`, `yearline_breadth_latest.json`, `yitong_pool.txt`, `{var}.json`, `{var}_latest.json`, `{var}_{var}.csv`, `{var}_{var}.json`, `{var}_{var}.md`, `乖离低买_latest.json`, `仲裁信号日志.csv`, `信号仲裁_latest.json`, `双弦观察池_latest.json`, `四维共振_chinext_kcb_latest.json`, `四维共振_latest.json`, `市场状态判定_{var}.md`, `情绪预判_latest.json`, `执行纪律_latest.json`, `断档分歧_latest.json`, `板块共振_latest.json`, `组合风控_latest.json`, `鱼身报告_latest.md`

## ❔ 提交但未见脚本生成（手工或外部产物）

| 产物 | 提交于 |
|---|---|
| `ai_chokepoint_watch_latest.json` | quant_report.yml |
| `caige_articles` | wangzhe_track.yml(via wangzhe_commit.py) |
| `caige_pool.txt` | quant_report.yml |
| `dragon_pool.txt` | quant_report.yml |
| `execution_cards_latest.json` | quant_report.yml |
| `hot_emotion_latest.md` | quant_scan.yml |
| `ima_cred_last_ok.json` | quant_scan.yml |
| `market_style_latest.json` | quant_report.yml |
| `一统天下建仓区股池_latest.json` | quant_report.yml, quant_scan.yml |
| `一统天下建仓区股池_latest.md` | quant_scan.yml |
| `四态胜率_{var}.md` | quant_report.yml |
| `涨停型王者_成功率报告` | wangzhe_track.yml(via wangzhe_commit.py) |
| `盘前市场报告_{var}.md` | premarket_report.yml |
| `资金快照_{var}.csv` | quant_scan.yml |
