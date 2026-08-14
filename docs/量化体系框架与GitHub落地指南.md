# 🏛️ A股量化投资体系 · 全框架梳理与 GitHub 落地指南

> 版本: v3.0 | 更新: 2026-08-15 | 适用: workbuddy / ima.copilot 环境落地
> 核心原则: **GitHub 是唯一真源，workflow 自动运行，沙箱人工干预，知识库对外发布**

---

## 一、体系总览（一句话）

**每日自动闭环**：盘前报告(预测) → 盘中监控 → 全盘量化(数据) → 股池建立(才哥/一统天下/双弦/猛兽/鱼身) → 复盘报告(验证) → 次日盘前（预测迭代）

```
                ┌───────────── 盘前报告(08:00-09:00) ─────────────┐
                │   外围→大盘→板块→个股 四层级 + 三系统信号          │
                ▼                                                 │
        交易时段(09:30-15:00) ◀──── 盘中监控(intraday_monitor)      │
                │                                                 │
                ▼                                                 │
        GitHub Actions 15:30 全盘量化扫描 ────┐                    │
                │  ① 全市场资金扫描(full_market_dualdim)          │
                │  ② 三系统预运行(双弦/鱼身/猛兽)                 │
                │  ③ 股池建立(才哥/一统天下) + 四维/仲裁           │
                ▼                                                 │
        复盘报告(16:30-17:00) ── 预判验证 + 明日展望 ──────────────┘
```

## 二、GitHub 仓库结构（3 仓库）

| 仓库 | 角色 | 说明 |
|------|------|------|
| **wuhj-hub/bg** | 主仓 | 全部量化脚本 + 5 个 workflow + 数据产物 |
| wuhj-hub/sx2 | 双弦专属 | 双弦每日报告（已收编 bg 第三步.4.6，备用） |
| wuhj-hub/wuwei-monthly | 武威月度 | 每月 1 日自动扫描（G1 初筛→v2.1 过滤） |

### bg 仓库 5 个 Workflow

| Workflow | 触发 | 功能 |
|----------|------|------|
| `full_market_scan.yml` | 每交易日 15:30 + 手动 | **全盘量化主流程**（355 分钟预算） |
| `premarket_report.yml` | 每交易日 08:00 | 盘前报告生成（备用，主用沙箱） |
| `intraday_monitor.yml` | 盘中每 2 小时 | 盘中异动监控 |
| `guard_selfcheck.yml` | 每日 09:30 | **备份完整性自检**（14技能+14脚本） |
| `probe_search.yml` | 手动 | 探测/搜索任务 |

### full_market_scan.yml 步骤链（核心）

```
Step1  生成主板清单(gen_mainboard.py) → 预热westock
Step2  全量资金扫描(full_market_dualdim) → 市场宽度 → 分时强度 → 板块共振 → 鱼身池
Step3  三系统预运行(run_all_quant: 双弦+鱼身+猛兽)
  ├─3.4   上传三系统原始数据到知识库
  ├─3.4.5 猛兽本月股池同步
  ├─3.4.6 双弦每日报告+月度股池
  ├─3.4.7 才哥战法股池(四战法扫描+三阶漏斗跟踪)
  ├─3.4.8 一统天下建仓区股池(周线闸门→日线→60m)
  ├─3.5   市场风格轴(机构vs游资)
  ├─3.5b  四维共振评分(资金/筹码/关联方/政策)
  ├─3.5c  六套信号仲裁
  ├─3.5d  创业板/科创补充通道
  └─3.6   提交latest数据(push失败显式告警)
Step4  上传全盘量化报告
Step5  股池跟踪(三阶漏斗) → 复盘报告 → 胜率跟踪 → 纸面组合 → 反转信号
Step6  PushPlus推送 → CHANGELOG → 体系自检
```

## 三、核心脚本清单（quant_scripts/，44 个 .py）

### 🎯 股池扫描器（每日运行）
| 脚本 | 系统 | 产出 |
|------|------|------|
| `caige_pool.py` | 才哥四战法 | 王者倍量柱(确认/观察)/旭日东升/凤凰归巢/瞒天过海 → caige_pool.txt |
| `yitong_screener.py` | 一统天下建仓区 | 周线闸门→日线建仓区(VARO7<10)→60m确认 → yitong_pool.txt（五星分级） |
| `beast_screener.py` | 猛兽 v3.0 | 三层漏斗+Setup评分+G点/伏击线/RS_D → beast_results |
| `fish_body_enhanced.py` | 鱼身 v2.0 | 大盘温度+三模式买点 → 36信号/日 |
| `run_all_quant.py` | 三系统聚合 | quant_results_{date}.json（双弦+猛兽+鱼身） |
| `pool_tracking_report.py` | 三阶漏斗跟踪 | 月线→G1→v2.1质量否决 + 离场计分卡 + --hide-rejected/--out-file |

### 📊 市场分析（全盘扫描）
`full_market_dualdim.py`(双维资金) / `market_width.py`(宽度) / `market_style.py`(风格轴) / `sector_resonance_local.py`(板块共振) / `quad_resonance.py`(四维) / `signal_arbiter.py`(六源仲裁) / `qiankun`(乾坤A级) / `minute_strength.py`(分时强度)

### 🔬 回测体系（研究用）
`backtest_month_reversal_v4.py`(5方法对比) / `backtest_reversal_levels.py`(反转多级别) / `backtest_runner.py`(参数化) / `backtest_yitong.py`+`_multi.py`(一统天下) / `month_frame.py`(月线)

### 🛡️ 防护与运维
`guard.py`(status/sync/restore/logcheck) / `guard_selfcheck.py`(自检) / `gen_review_report.py`(复盘+上传兜底) / `gen_premarket_report.py`(盘前) / `trade_guard.py`(ATR止损+离场卡) / `paper_tracker.py`(纸面组合) / `win_rate_tracker.py`(胜率)

### 📈 做T辅助
`zuot_kuangren.py`(做T狂人：日线MA两分法+分时VWAP) / `yitong_60m_fullscan.py`(60m全市场验证)

## 四、股池系统矩阵（每日并行产出）

| 股池 | 逻辑 | 输出 | 知识库 |
|------|------|------|--------|
| 才哥战法（56只级） | 王者倍量柱/旭日东升/凤凰归巢/瞒天过海 | caige_pool.txt + 三阶漏斗跟踪 | 主KB盘后量化 |
| 一统天下建仓区（17只级） | 周线闸门→日线VARO7<10→60m | yitong_pool.txt + 五星分级 | 主KB盘后量化 |
| 双弦月度股池（≤10元） | 共振/低吸 + AND门控 | 月度累积 pools/ | 双弦KB |
| 猛兽本月股池 | 月线多头+Setup≥50 分层 | 月度累积 pools/ | 猛兽KB |
| 鱼身信号（36个/日） | 空中加油/回踩/箱体突破 | fish_body JSON | 主KB |
| 乾坤A级金股 | 资金强攻+业绩共振 | qiankun_a_latest.json | 主KB |
| 四维共振（114只级） | 资金/筹码/关联方/政策 | 四维共振_latest.json | 主KB |

## 五、知识库与推送链路

| 通道 | 用途 | 依赖 |
|------|------|------|
| **盘前市场报告 KB**(6kjd8j...) | 盘前/复盘/盘后量化 3 文件夹 | IMA 凭证 |
| 猛兽 KB / 双弦 KB / 王者倍量柱 KB | 独立股池 | IMA 凭证 |
| **PushPlus** | 盘前/复盘/股池/自检 推送手机 | PUSH_TOKEN |
| **GitHub 仓库** | 数据落盘（latest JSON） | GITHUB_TOKEN |

## 六、凭证与配置（落地关键）

| 凭证 | 位置 | 状态 |
|------|------|------|
| IMA ClientID/APIKey | 沙箱 `.env.ima` + **3仓库 secrets** | ✅ 2026-08-15 已更新 |
| GitHub Token | 沙箱 `.env`（不入库） | ✅ |
| PushPlus Token | 沙箱 env + 仓库 secrets PUSH_TOKEN | ✅ |
| westock | npx 包，无需凭证 | ✅ |
| 新浪 5 分钟 K 线 | 免费接口（间歇封禁→串行+间隔） | ⚠️ 仅候选股拉取 |

## 七、防护与容错（已落地 5 层）

1. **回滚防护**：`guard.py status`（trees API+blob sha 秒级检测）→ `restore` 恢复（GitHub 为唯一真源）
2. **备份自检**：`guard_selfcheck.yml` 每日 09:30 检查 14 技能+14 脚本完整性，异常 PushPlus 告警
3. **push 防静默**：workflow 内 git push 3 次失败 → `::error::`+exit 1（不再被 sleep 掩盖）
4. **上传兜底**：gen_review_report.py 上传 IMA 失败 → 显式标红 + git 落盘仓库（报告不丢）
5. **日志保护**：pool_signals_log 等日志只 push 不 pull（本地为唯一真源）

## 八、workbuddy 落地运行手册

### 初始化（一次性）
```bash
# 1. 拉取仓库（GitHub 为真源）
git clone https://github.com/wuhj-hub/bg.git /sandbox/workspace/bg
# 2. 凭证配置
echo "GITHUB_TOKEN=ghp_..." > /sandbox/workspace/.env          # 不入库
echo "IMA_OPENAPI_CLIENTID=..." > /sandbox/workspace/.env.ima  # ima凭证
echo "IMA_OPENAPI_APIKEY=..." >> /sandbox/workspace/.env.ima
# 3. 数据清单（workflow 第一步自动生成）
#    all_mainboard.csv（3033只主板）
# 4. 技能目录（14个自建技能，SKILL.md+scripts）
```

### 每日运行（自动 + 人工）
| 时间 | 事件 | 执行方 |
|------|------|--------|
| 09:30 | guard 备份自检 | workflow 自动 |
| 08:00-09:00 | **盘前报告** | 沙箱人工触发（技能）→ 上传KB+推送 |
| 09:30-15:00 | 盘中监控 | workflow 自动 |
| 15:30 | 全盘量化（355min） | workflow 自动 |
| 16:30-17:00 | **复盘报告** | 沙箱人工触发（技能）或 workflow 自动 |
| 任意 | 股池查询/个股分析 | 沙箱对话式（westock/脚本） |

### 故障恢复速查
```bash
# 报告缺失 → 检查
python3 guard.py status          # 本地vs GitHub 差异
python3 /sandbox/workspace/skills/盘前市场报告/scripts/premarket_quant.py  # 量化数据

# 凭证失效（skill auth failed）
→ 用户 ima 平台重新生成 → 更新 .env.ima + 3仓库secrets（pynacl加密PUT）

# 报告生成但上传失败
→ 检查 GitHub outputs/ 是否已 git 落盘（兜底生效）→ 凭证恢复后补传

# 新浪数据拉不到
→ 串行 + 间隔 1.2s + 只对候选股拉取（不要全市场并发）
```

## 九、关键命令速查

```bash
# 股池扫描
python3 caige_pool.py                    # 才哥四战法（8-12分钟）
python3 yitong_screener.py               # 一统天下建仓区（3-5分钟）
python3 zuot_kuangren.py sh600863 ...    # 做T分析（日线+分时）

# 防护
python3 guard.py status | sync | restore | logcheck

# 回测
python3 backtest_yitong_multi.py         # 一统天下多周期
python3 backtest_month_reversal_v4.py    # 月线反转5方法

# 数据
npx -y westock-data-skillhub@1.0.3 kline sh600000 --period day --limit 20
npx -y westock-data-skillhub@1.0.3 asfund sh600000     # 资金
```

## 十、演进路线（待办）

- [ ] 60m 全市场验证跑 GitHub Actions（yitong_60m_fullscan.py 已就绪）
- [ ] 一统天下扫描器接入盘前报告引用（④层新增信号源）
- [ ] 券商建仓区板块级信号跟踪（8/14 首现 6 只）
- [ ] 才哥/一统天下股池胜率累积（2-4 周后对比回测）

---

> ⚠️ 本文档为内部体系架构梳理，所有量化结论基于历史数据统计，不构成投资建议。
