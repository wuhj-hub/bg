"""资金特征：启动前潜伏量能、启动日多空强度、启动后资金持续性"""
import numpy as np
import pandas as pd

E = pd.read_csv("outputs/yaogu_events.csv").dropna(subset=["max60", "volr", "ind_ret20"]).copy()
df = pd.read_csv("data/kline_daily_vol.csv")
df = df[df.volume > 0].sort_values(["code", "date"]).reset_index(drop=True)
df["i"] = df.groupby("code").cumcount()
idx = {(r.code, r.date): r.i for r in df.itertuples()}
grp = {k: (g["close"].values, g["high"].values, g["low"].values, g["open"].values, g["volume"].values)
       for k, g in df.groupby("code")}

rec = []
for r in E.itertuples():
    g = grp.get(r.code); k = idx.get((r.code, r.date))
    if g is None or k is None or k < 130:
        continue
    c, h, l, o, v = g
    if c[k] <= 0:
        continue
    vma20 = v[k - 20:k].mean()
    if vma20 <= 0:
        continue
    # 潜伏量能：启动前5日 / 前10日 相对20日均量
    amb5 = v[k - 5:k].mean() / vma20
    amb10 = v[k - 10:k - 5].mean() / vma20
    amb20 = v[k - 20:k - 10].mean() / vma20
    # 启动日收盘位置（多空强度）
    rng = h[k] - l[k]
    pos = (c[k] - l[k]) / rng if rng > 0 else .5
    # 启动后路径
    n = len(c)
    fut = lambda w: (c[min(k + w, n - 1)] / c[k] - 1)
    fv = [v[min(k + w, n - 1)] / vma20 for w in (1, 3, 5, 10, 20)]
    rec.append([r.code, r.date, amb5, amb10, amb20, pos,
                fut(1), fut(3), fut(5), fut(10), fut(20),
                r.max60, r.volr, r.atr_pct, r.ret60, r.ind_ret60, r.is_zt_hit] + fv)

cols = ["code", "date", "amb5", "amb10", "amb20", "close_pos",
        "f1", "f3", "f5", "f10", "f20", "max60", "volr", "atr_pct", "ret60", "ind_ret60", "is_zt",
        "v1", "v3", "v5", "v10", "v20"]
F = pd.DataFrame(rec, columns=cols)
F["far"] = F.max60 >= .6
F.to_csv("outputs/yaogu_funds.csv", index=False)
base = F.far.mean()
print("样本", len(F), f"走远率 {base*100:.1f}%")

L = ["# 妖股资金特征\n", f"- 样本 {len(F):,} 个启动事件，走远率基准 **{base*100:.1f}%**\n"]

def cmp(f, labels, bins, name):
    L.append(f"### {name}\n")
    t = F.groupby(pd.cut(F[f], bins=bins, labels=labels), observed=True).agg(
        n=("far", "size"), far=("far", "mean"), med=("max60", "median"))
    L.append("| 分组 | 样本 | 走远率 | 60日涨幅中位 |")
    L.append("|---|---|---|---|")
    for k, r in t.iterrows():
        if r["n"] < 30: continue
        L.append(f"| {k} | {int(r['n']):,} | **{r['far']*100:.1f}%** | {r['med']*100:+.1f}% |")
    L.append("")

L.append("## 1. 启动前资金潜伏（量能爬坡）\n")
cmp("amb5", ["缩量(<0.8)", "平量(0.8~1.1)", "温和放量(1.1~1.5)", "明显放量(1.5~2.5)", "急放量(>2.5)"],
    [0, .8, 1.1, 1.5, 2.5, 99], name="启动前1~5日均量 / 20日均量")
cmp("amb20", ["<0.8", "0.8~1.1", "1.1~1.5", ">1.5"], [0, .8, 1.1, 1.5, 99],
    name="启动前11~20日均量 / 20日均量（更早期潜伏）")

L.append("## 2. 启动日多空强度\n")
cmp("close_pos", ["弱(收在下1/3)", "中(中间)", "强(收在上1/3)"], [-.01, .33, .66, 1.01],
    name="启动日收盘位置（收在当日区间何处）")

L.append("## 3. 启动后资金持续性（成交量 / 启动前20日均量）\n")
L.append("| 时点 | 走远组 | 未走远组 |")
L.append("|---|---|---|")
for w, col in [(1, "v1"), (3, "v3"), (5, "v5"), (10, "v10"), (20, "v20")]:
    a = F[F.far][col].mean(); b = F[~F.far][col].mean()
    L.append(f"| T+{w} | **{a:.2f}** | {b:.2f} |")

L.append("\n## 4. 启动后价格路径（相对启动日收盘）\n")
L.append("| 时点 | 走远组 | 未走远组 |")
L.append("|---|---|---|")
for w, col in [(1, "f1"), (3, "f3"), (5, "f5"), (10, "f10"), (20, "f20")]:
    a = F[F.far][col].mean(); b = F[~F.far][col].mean()
    L.append(f"| T+{w} | **{a*100:+.2f}%** | {b*100:+.2f}% |")

L.append("\n## 5. 高资金+高波动组合\n")
L.append("| 组合 | 样本 | 走远率 | 60日涨幅中位 |")
L.append("|---|---|---|---|")
conds = {
    "启动前温和放量(1.1~1.5)+高波": (F.amb5.between(1.1, 1.5)) & (F.atr_pct > .045),
    "启动前缩量+高波": (F.amb5 < .8) & (F.atr_pct > .045),
    "启动前急放量(>2.5)+高波": (F.amb5 > 2.5) & (F.atr_pct > .045),
    "收在上1/3+高波": (F.close_pos > .66) & (F.atr_pct > .045),
    "收在下1/3+高波": (F.close_pos < .33) & (F.atr_pct > .045),
    "缩量+高波+板块超跌": (F.amb5 < .8) & (F.atr_pct > .045) & (F.ind_ret60 < -.15),
    "缩量+高波+涨停": (F.amb5 < .8) & (F.atr_pct > .045) & (F.is_zt >= .5),
}
for k, v in conds.items():
    s = F[v]
    if len(s) > 100:
        L.append(f"| {k} | {len(s):,} | **{s.far.mean()*100:.1f}%** | {s.max60.median()*100:+.1f}% |")
open("outputs/yaogu_funds.md", "w", encoding="utf-8").write("\n".join(L))
print("\n".join(L))
