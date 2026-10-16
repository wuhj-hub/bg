# skills_backup —— 已发布技能的仓库内备份（**归档目录，非线上运行目录**）

> 维护：`quant_scripts/guard.py`（把技能源 `SKILLS/<name>/…` 同步到此处）
> 守卫：每日 `guard_selfcheck.py` 做完整性自检（缺 `SKILL.md` / `scripts` 会告警并 exit 1）
> ⚠️ **请勿删除本目录**——会触发 guard_selfcheck 失败并丢失技能备份。

## 定位
- 本目录是 14 个自建技能在仓库里的**备份副本**，用于防误删/防覆盖与版本留存。
- **不是**线上运行目录：除下列 1 处例外，workflow 不执行本目录下任何脚本。

## 唯一例外（CI 真依赖）
- `盘前市场报告/scripts/market_charts.py` —— 由 `.github/workflows/quant_report.yml`（复盘「走势图」步）直接调用。
  - 原因：该脚本属「盘前市场报告」技能，CI 无技能安装环境，故直取仓库内副本。
  - 可选后续：若要彻底解耦，可把 canonical 提升为 `quant_scripts/market_charts.py`，workflow 改指该路径。

## 对「指标消费对账 / 分支 B」的口径
- 本目录下脚本**不计入**指标（`*_latest.json`）的「语义消费者」统计——它们是归档副本，不代表线上口径。
- 故对账 / 分支 B 扫描应**排除** `skills_backup/`（`quant_scripts/artifact_audit.py` 已在排除列表）。
