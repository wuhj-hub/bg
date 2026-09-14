"""筹码（成本分布代理）+ 启动前形态分类"""
import numpy as np
import pandas as pd

E = pd.read_csv("outputs/yaogu_events.csv").dropna(subset=["max60", "volr", "ind_ret20"]).copy()
df = pd.read_csv("data/kline_daily_vol.csv")
df = df[df.volume > 0].sort_values(["code", "date"]).reset_index(drop=True)
df["i"] = df.groupby("code").cumcount()
idx = {(r.code, r.date): r.i for r in df.itertuples()}
grp = {k: (g["close"].values, g["high"].values, g["low"].values, g["volume"].values)
       for k, g in df.groupby("code")}

rec = []
for r in E.itertuples():
    g = grp.get(r.code)
    k = idx.get((r.code, r.date))
    if g is None or k is None or k < 130:
        continue
    c, h, l, v = g
    if c[k] <= 0 or c[k - 1] <= 0:
        continue

    def vwap(a, b):
        tp = (h[a:b] + l[a:b] + c[a:b]) / 3
        sv = v[a:b].sum()
        return (tp * v[a:b]).sum() / sv if sv > 0 else np.nan, tp, v[a:b]

    w20, tp20, v20 = vwap(k - 20, k)
    w60, tp60, v60 = vwap(k - 60, k)
    w120, _, _ = vwap(k - 120, k)
    if not (w20 > 0 and w60 > 0 and w120 > 0):
        continue
    wm = (tp60 * v60).sum() / v60.sum()
    conc = np.sqrt(((tp60 - wm) ** 2 * v60).sum() / v60.sum()) / wm   # 筹码集中度（越小越集中）
    rec.append([r.code, r.date,
                c[k] / w20 - 1, c[k] / w60 - 1, c[k] / w120 - 1,   # 获利盘程度
                conc,                                             # 集中度
                w20 / w60 - 1,                                    # 短期成本抬升（20日成本 vs 60日成本）
                r.ret60, r.max60, r.volr, r.ind_ret60, r.atr_pct, r.is_zt_hit, r.pma60])

C = pd.DataFrame(rec, columns=["code", "date", "dev20", "dev60", "dev120", "conc",
                               "cost20_60", "ret60", "max60", "volr", "ind_ret60", "atr_pct",
                               "is_zt", "pma60"])
C.to_csv("outputs/yaogu_chips.csv", index=False)
C["far"] = C.max60 >= .6
base = C.far.mean()
print("样本", len(C), "走远率", f"{base*100:.1f}%")

L = ["# 妖股筹码与形态特征\n", f"- 样本 {len(C):,} 个启动事件，走远率基准 **{base*100:.1f}%**\n"]

def cmp(f, labels, bins, name):
    L.append(f"### {name}\n")
    g = pd.cut(C[f], bins=bins, labels=labels)
    t = C.groupby(g, observed=True).agg(n=("far", "size"), far=("far", "mean"), med=("max60", "median"))
    L.append("| 分组 | 样本 | 走远率 | 60日涨幅中位 |")
    L.append("|---|---|---|---|")
    for k, r in t.iterrows():
        if r["n"] < 30: continue
        L.append(f"| {k} | {int(r['n']):,} | **{r['far']*100:.1f}%** | {r['med']*100:+.1f}% |")
    L.append("")

L.append("## 1. 筹码：获利盘 / 成本位置\n")
cmp("dev60", ["深度套牢(低于60日成本>15%)", "套牢(5~15%)", "成本附近(±5%)", "获利(5~15%)", "大幅获利(>15%)"],
    [-9, -.15, -.05, .05, .15, 9], name="启动日收盘 vs 60日成交量加权成本")
cmp("dev20", ["低于20日成本>10%", "低于0~10%", "高于0~10%", "高于>10%"],
    [-9, -.10, 0, .10, 9], name="启动日收盘 vs 20日成本")
cmp("cost20_60", ["20日成本远低于60日(<-5%)", "接近(-5~0%)", "抬升(0~5%)", "大幅抬升(>5%)"],
    [-9, -.05, 0, .05, 9], name="成本抬升：20日成本 vs 60日成本（>0=近期在吸筹抬价）")
cmp("conc", ["高度集中(<7%)", "集中(7~10%)", "分散(10~14%)", "很分散(>14%)"],
    [0, .07, .10, .14, 9], name="筹码集中度（60日成交价分布 std/均价，越小越集中）")

L.append("## 2. 启动前形态分类（前60日涨跌）\n")
cmp("ret60", ["深跌(<-25%)", "下跌(-25~-10%)", "横盘(-10~10%)", "上升(10~40%)", "大涨(>40%)"],
    [-9, -.25, -.10, .10, .40, 9], name="启动前60日涨跌幅")

L.append("## 3. 组合：形态 × 筹码 × 波动\n")
conds = {
    "深跌+筹码集中+高波": (C.ret60 < -.25) & (C.conc < .10) & (C.atr_pct > .045),
    "深跌+高波(任意筹码)": (C.ret60 < -.25) & (C.atr_pct > .045),
    "横盘+高波": (C.ret60.between(-.10, .10)) & (C.atr_pct > .045),
    "上升+高波": (C.ret60 > .10) & (C.atr_pct > .045),
    "横盘+低波+窄幅": (C.ret60.between(-.10, .10)) & (C.atr_pct < .03),
    "大幅获利(>20%成本上)+高波": (C.dev60 > .20) & (C.atr_pct > .045),
}
L.append("| 组合 | 样本 | 走远率 | 60日涨幅中位 |")
L.append("|---|---|---|---|")
for k, v in conds.items():
    s = C[v]
    if len(s) > 100:
        L.append(f"| {k} | {len(s):,} | **{s.far.mean()*100:.1f}%** | {s.max60.median()*100:+.1f}% |")
open("outputs/yaogu_chips.md", "w", encoding="utf-8").write("\n".join(L))
print("\n".join(L))
