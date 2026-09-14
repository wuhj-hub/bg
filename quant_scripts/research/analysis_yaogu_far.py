"""走得远 vs 未走远 妖股六维特征对比"""
import numpy as np
import pandas as pd

E = pd.read_csv("outputs/yaogu_events.csv")
E = E.dropna(subset=["max60", "volr", "pma20", "ind_ret20"])
E["far"] = E["max60"] >= 0.60          # 走远：60日最大涨幅 >=60%
E["died"] = E["max60"] < 0.20          # 未走远：<20%
N = len(E)
L = []
L.append("# 妖股「走得远」六维特征回测\n")
L.append(f"- 事件定义：**放量异动启动日** = 当日涨幅 5%~25% + 量比≥2 + 前20日涨幅<25%（相对平静的启动）")
L.append(f"- 样本：{N:,} 个启动事件（2022-09 ~ 2026-09，沪深主板，剔除 ST，前复权）")
L.append(f"- 标签：启动日收盘起 **60 个交易日内的最大涨幅**（max60）")
L.append(f"- 走远 = max60 ≥ 60%（**{E.far.sum():,} 个，{E.far.mean()*100:.1f}%**）；未走远 = max60 < 20%（{E.died.sum():,} 个，{E.died.mean()*100:.1f}%）\n")
q = E["max60"].describe(percentiles=[.1, .25, .5, .75, .9, .95, .99])
L.append("## 0. 走远程度分布\n")
L.append("| 分位 | p10 | p25 | 中位 | p75 | p90 | p95 | p99 |")
L.append("|---|---|---|---|---|---|---|---|")
L.append("| 60日最大涨幅 | " + " | ".join(f"{q[f'{p}%']*100:+.1f}%" for p in [10, 25, 50, 75, 90, 95, 99]) + " |\n")

def cmp(feat, labels=None, bins=None, name=None):
    """按特征分组看走远率"""
    L.append(f"### {name or feat}\n")
    if bins is not None:
        g = pd.cut(E[feat], bins=bins, labels=labels)
    else:
        g = E[feat]
    t = E.groupby(g, observed=True).agg(n=("far", "size"), far=("far", "mean"), med=("max60", "median"))
    L.append("| 分组 | 样本 | 走远率 | 60日均值涨幅中位 |")
    L.append("|---|---|---|---|")
    for k, r in t.iterrows():
        L.append(f"| {k} | {int(r['n']):,} | **{r['far']*100:.1f}%** | {r['med']*100:+.1f}% |")
    L.append("")

base = E.far.mean()
L.append(f"> 全样本走远率基准 = **{base*100:.1f}%**\n")
L.append("---\n")

L.append("## 1. 启动方式：是否涨停启动\n")
E["启动方式"] = np.where(E.is_zt_hit < .5, "非涨停·放量大阳",
                       np.where(E.open_gap >= .09, "一字板（涨停开盘）",
                                np.where(E.open_gap >= .02, "高开涨停", "低开/平开涨停（换手板）")))
cmp("启动方式")
cmp("volr", ["2-3倍", "3-5倍", "5-8倍", "8倍+"], [2, 3, 5, 8, 100], name="量比（启动日成交/20日均量）")

L.append("## 2. 外围市场（启动当日/前夜）\n")
cmp("us_prev", ["纳指跌>1%", "纳指跌0~1%", "纳指涨0~1%", "纳指涨>1%"], [-1, -.01, 0, .01, 1], name="前夜纳斯达克涨跌")
cmp("hk_day", ["恒生跌>1%", "恒生跌0~1%", "恒生涨0~1%", "恒生涨>1%"], [-1, -.01, 0, .01, 1], name="当日恒生涨跌")

L.append("## 3. 板块环境（所属行业等权）\n")
cmp("ind_ret20", ["行业20日<-10%", "-10~0%", "0~10%", ">10%"], [-1, -.1, 0, .1, 1], name="行业近20日涨幅")
cmp("ind_ret60", ["行业60日<-15%", "-15~0%", "0~15%", ">15%"], [-1, -.15, 0, .15, 1], name="行业近60日涨幅")

L.append("## 4. 筹码 / 吸筹形态（启动前）\n")
cmp("shrink", ["大幅缩量(<0.6)", "缩量(0.6~0.9)", "平量(0.9~1.2)", "放量(>1.2)"], [0, .6, .9, 1.2, 99], name="缩量度（前20日均量/前120日均量）")
cmp("box", ["窄箱体<15%", "15~30%", "30~50%", ">50%"], [0, .15, .3, .5, 9], name="启动前60日箱体高度")
cmp("turn60", ["低换手<0.5", "0.5~0.8", "0.8~1.2", "高换手>1.2"], [0, .5, .8, 1.2, 99], name="前60日换手活跃度（累计量/20日均量/60）")
cmp("amp", ["低波动<2%", "2~3%", "3~4.5%", "高波动>4.5%"], [0, .02, .03, .045, 1], name="前60日日波动率")

L.append("## 5. 启动前趋势形态（建仓-拉升-洗盘）\n")
cmp("pma20", ["价<MA20", "MA20上方0~6%", "MA20上方>6%"], [-1, -.02, .06, 1], name="启动前一日价格 vs MA20")
cmp("pma60", ["价<MA60", "MA60上方0~10%", "MA60上方>10%"], [-1, -.02, .10, 1], name="启动前一日价格 vs MA60")
cmp("ma_bull", ["非多头排列", "多头排列"], [-.5, .5, 1.5], name="均线多头排列（MA5>10>20>60）")
cmp("ret20", ["前20日跌", "0~10%", "10~25%"], [-1, 0, .1, .25], name="启动前20日涨幅")
cmp("pdist_hi60", ["距60日高<-20%", "-20~-10%", "-10~0%", "新高附近"], [-1, -.2, -.1, 0, .01], name="启动前一日距60日高点")
cmp("atr_pct", ["低波<3%", "3~4.5%", "4.5~6%", "高波>6%"], [0, .03, .045, .06, 1], name="启动前ATR20/价")

L.append("## 6. 资金特征\n")
cmp("open_gap", ["大幅低开<-3%", "-3~0%", "0~3%", "3~7%", "高开>7%"], [-1, -.03, 0, .03, .07, 1], name="启动日开盘涨幅（资金抢筹强度）")
cmp("pct", ["5~7%", "7~9.5%", "涨停≥9.5%"], [.049, .07, .095, .26], name="启动日涨幅")

E.to_csv("outputs/yaogu_events.csv", index=False)
open("outputs/yaogu_far.md", "w", encoding="utf-8").write("\n".join(L))
print("\n".join(L))

# 多因子：走远率最高的组合
L2 = []
L2.append("\n## 7. 高走远率组合（单条件+交叉）\n")
for f, lo, hi in [("volr", 5, 99), ("shrink", 0, .6), ("box", 0, .15),
                  ("pma20", 0, 0), ("ma_bull", .5, 1.5), ("is_zt_hit", .5, 1.5)]:
    s = E[(E[f] >= lo) & (E[f] <= hi)]
    if len(s) > 200:
        L2.append(f"- `{f} ∈ [{lo},{hi}]` → n={len(s):,}, 走远率 {s.far.mean()*100:.1f}%")
open("outputs/yaogu_combo.md","w",encoding="utf-8").write("\n".join(L2))
print("\n".join(L2))
