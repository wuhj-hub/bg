# 猛兽体系过滤规则

## 股票池过滤（统一规则）

```
NOT(CODELIKE('688'))    # 排除科创板
AND NOT(CODELIKE('300'))   # 排除创业板
AND NOT(CODELIKE('301'))   # 排除创业板
AND NOT(CODELIKE('8'))     # 排除北交所（8开头）
AND NOT(CODELIKE('43'))    # 排除北交所
AND NOT(CODELIKE('83'))    # 排除北交所
AND NOT(CODELIKE('87'))    # 排除北交所
AND NOT(NAMELIKE('ST'))    # 排除ST
AND NOT(NAMELIKE('*ST'))   # 排除*ST
```

## 候选股来源

- `westock-data hot` 热搜股票（市场热点人气股）
- 仅保留 stock_type="GP-A" 的股票（排除ETF/基金/北交所/科创板/创业板）

## Setup评分候选条件

- OVS总分 ≥ 40（中位数以上）
- 不含停牌股（status不含"S"或"U"）
- K线数据完整（至少20个交易日）