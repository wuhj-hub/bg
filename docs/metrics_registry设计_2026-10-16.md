# metrics.py —— 指标只读访问层 设计定稿（分支 B · top-8 试点）

> 2026-10-16 ｜ 前置：`docs/指标消费对账_2026-10-16.md`（对账证据）
> 定位：第 2 层治理的「指标层标准化」——**只读访问层**，`report_io`（副本读取层）的姊妹
> 范围：**top-8 指标试点**，不主张全量重构（50 个里 21 个长尾不动）

---

## 一、要解决的问题（来自对账）

1. **语义散落**：`market_width.score` 在 env 里被当作「含 +30 赚钱效应加成、需下压」，在 premarket/review 里被直接展示——同一字段两套理解，知识散在各消费者代码里。
2. **解析重复**：`quant_results`（stdout 文本集）里的「安全评分」被多个脚本各写一遍正则。
3. **契约隐式**：多数 latest 由变量名拼路径写出，静态定位不到「谁生产、有哪些字段」。
4. **副本稀释**：`hot_emotion` 等有 6 个 `skills_backup` 副本消费者。

**目标**：把「指标 → 字段定义 → 语义修饰 → 消费者」收口成一处显式契约；**不改业务逻辑**。

---

## 二、接口设计（只读、无副作用）

```python
# quant_scripts/metrics.py  —— 指标只读访问层（第2层·指标层标准化 · 分支B · 试点）
from report_io import load_latest  # 复用副本新鲜度选择（data_date>bar_date>trade_date>date）

# 1) 注册表：指标名 → 候选路径（多副本，交给 load_latest 选最新）
REGISTRY = {
  "market_width":  ("market_width_latest.json", "outputs/market_width_latest.json"),
  "quant_results": ("quant_results_latest.json", "outputs/quant_results_latest.json"),
  "rsv_strength":  ("outputs/rsv_strength_latest.json", "rsv_strength_latest.json"),
  "arbiter":       ("outputs/信号仲裁_latest.json", "信号仲裁_latest.json"),
  "qiankun_a":     ("outputs/qiankun_a_latest.json", "qiankun_a_latest.json"),
  "yearline":      ("outputs/yearline_breadth_latest.json", "yearline_breadth_latest.json"),
  "quad":          ("outputs/四维共振_latest.json", "四维共振_latest.json"),
  "sector_res":    ("outputs/板块共振_latest.json", "板块共振_latest.json"),
}

# 2) 通用层
def load(name) -> dict | None          # 取最新 dict；缺失/解析失败 → None（禁止假装中性）
def get(name, *keys, default=None)     # 安全取字段，支持嵌套 get("score","score")

# 3) 字段级 accessor：把「字段定义 + 语义修饰」收口（这是本层真正的价值）
def width_raw()      -> float | None   # market_width.score（原始，含赚钱效应加成）
def width_level()    -> str   | None   # market_width.level
def width_normalized()-> float| None   # env 用的「下压后」值——把 env 里硬编码的锚点搬到这里
def safety_score()   -> float | None   # quant_results.beast.stdout 的「安全评分」——收口那条正则
def rsv_launch()     -> list  | None   # rsv_strength.launch
def arb_operations() -> dict  | None   # 信号仲裁.operations
def qiankun_a_list() -> list  | None   # qiankun_a 的 A 级清单
def yearline_ratio() -> float | None   # yearline_breadth.ratio_pct
def quad_four_dim()  -> dict  | None   # 四维共振 四维合计
def sector_res()     -> dict  | None   # 板块共振 主结构
```

**原则**
- 只读、幂等、无副作用；不做任何写盘、不发起网络。
- 缺失/解析失败一律返回 `None` 并（可选）告警——**禁止用 50 假装中性**（沿用 env 加固教训）。
- **不复制业务判断**：accessor 只做「字段提取 + 已达成共识的刻度修饰」；分档/阈值仍留在各业务方。

---

## 三、top-8 指标的显式契约（生产者 / 关键字段 / 热点消费者）

| 指标 | 生产者 | 关键字段（顶层） | 语义消费者数 |
|---|---|---|---|
| `market_width` | `market_width.py`(根) | `score,breadth,bonus,level,up,valid,strong,weak,limitup,limitdown,cost_line,bar_date,date` | 9 |
| `quant_results` | `quant_scripts/run_all_quant.py` | stdout 文本集（beast/xihu/… 各段） | 8 |
| `rsv_strength` | `quant_scripts/rsv_strength.py` | `launch,hold,exit,signals,state,rsv_week,analyzed,date` | 8 |
| `arbiter`(信号仲裁) | `signal_arbiter.py` | `operations,ranked,counts,advice,pos_pct,market_top,env,mode,date` | 8 |
| `qiankun_a` | `full_market_dualdim.py` | `stocks[].{code,name,grade,lv,score,mainflow,phase,...},date` | 6 |
| `yearline` | `quant_scripts/yearline_breadth.py` | `ratio,ratio_pct,above_count_full,total,thresholds,level,date` | 6 |
| `quad`(四维共振) | `quad_resonance.py` | `stocks[].{code,name,level,four_dim_total,fund,chip},total,pool_size,date` | 6 |
| `sector_res`(板块共振) | `sector_resonance_local.py` | `resonance_boards,factors,absorption_top,control_top,entry_top,grab_top,date` | 6 |

> 字段清单为静态提取的**候选集**，迁移前逐个以真实产物核对（对账报告中的 `?` 项亦在此列）。

---

## 四、迁移清单（存量消费者，按热点渐进）

| 指标 | 迁移优先级 | 迁移方式 |
|---|---|---|
| `market_width`(score/level) | P0 | env_engine（去掉本地锚点，改 `width_normalized()`）、premarket、review |
| `quant_results`(安全评分) | P0 | env_engine 的正则 → `safety_score()`；其余消费者同 |
| `rsv_strength.launch` | P1 | premarket/pool_snapshot/paper_tracker |
| `信号仲裁.operations` | P1 | premarket/execution_card |
| `yearline.ratio_pct` | P1 | env_engine / premarket |
| `qiankun_a` / `quad` / `sector_res` | P2 | 相关消费方 |

**节奏铁律**：**一次只切一个指标**，切前做影子对拍、切后跑当天 CI 验证。

---

## 五、影子对拍方案（防回归，本体系强约束）

对每个要迁移的 accessor：
1. 写 `smoke_metrics_<name>.py`：对**同一份历史产物**，分别用「旧读取逻辑」与「新 metrics accessor」求值；
2. 逐字段比对，要求**完全一致**（数值容差 0 / 字符串严格等）；不一致先查口径再切；
3. 全等 → 切换该消费者；不等 → 记录差异原因（往往正是「语义散落」的真实分歧点，需先对齐）。

**首例（dogfood）**：`env_engine` 自己先切 `safety_score()` + `width_normalized()`，验证「回归原值」零差异。

---

## 六、前置项与风险

- ✅ **前置已处理（2026-10-16）**：`skills_backup/` 确认为**归档目录**（新增 `skills_backup/README.md`），并从 `sync_hot_emotion.py` 移除指向它的**死兜底路径**；语义消费者统计排除该目录（副本不再稀释分支 B）。唯一 CI 真依赖 `盘前市场报告/scripts/market_charts.py` 已在 README 标注（可选后续解耦）。skills_backup 由 guard_selfcheck/guard.py 守护，**不删除**。
- **风险**：本体系有「改脚本引回归」教训 → 本层**只读、不改业务**；逐个切换 + 影子对拍 + 当天 CI。
- **回滚**：accessor 失败一律返回 `None`，消费者保留原逻辑兜底（渐进切换期并存），可随时回退。
- **边界**：不做字段级强类型校验、不做自动 schema 断言（留给后续「字段契约审计」扩展 `param_contract_audit`）。

---

## 七、交付分阶段

1. ✅ **P0（2026-10-16 完成）**：`metrics.py`（`804a05e906`）+ `width_normalized`/`safety_score` 两个 accessor + env_engine dogfood（`8598759021`）+ 影子对拍 **0 差异**。
2. **P1**：rsv_strength / 信号仲裁 / yearline 三指标迁移。
3. **P2**：qiankun_a / quad / sector_res。
4. **收尾**：产出显式「指标注册表」（名→生产者→schema→消费者）并入 `docs/`，补上契约这一环。
