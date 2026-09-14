"""① 启动前120日量价路径刻画（建仓-拉升-洗盘-主升）② 多因子组合走远率"""
import numpy as np
import pandas as pd

E = pd.read_csv("outputs/yaogu_events.csv")
df = pd.read_csv("data/kline_daily_vol.csv")
df = df[df.volume > 0].sort_values(["code", "date"]).reset_index(drop=True)
df["i"] = df.groupby("code").cumcount()
idx = {(r.code, r.date): r.i for r in df.itertuples()}
arr = df[["code"]].copy()
df["c"] = df["close"]; df["v"] = df["volume"]
grp = {k: (g["c"].values, g["v"].values) for k, g in df.groupby("code")}

E = E.dropna(subset=["max60", "volr", "pma20", "ind_ret20"]).copy()
E["far"] = E["max60"] >= 0.60
E["died"] = E["max60"] < 0.20

W = 120
paths_p, paths_v, lab = [], [], []
for r in E.itertuples():
    g = grp.get(r.code)
    if g is None:
        continue
    c, v = g
    k = idx.get((r.code, r.date))
    if k is None or k < W + 5 or k >= len(c):
        continue
    base = c[k]
    if base <= 0 or c[k - W] <= 0:
        continue
    p = c[k - W:k + 1] / base
    vv = v[k - W:k + 1]
    vm = vv.mean()
    if vm <= 0:
        continue
    paths_p.append(p); paths_v.append(vv / vm); lab.append(1 if r.far else (0 if r.died else -1))

paths_p = np.array(paths_p); paths_v = np.array(paths_v); lab = np.array(lab)
print("路径样本", len(lab), "走远", (lab == 1).sum(), "未走远", (lab == 0).sum())

L = []
L.append("# 妖股启动前量价路径（建仓-拉升-洗盘-主升）\n")
L.append(f"- 样本：{len(lab):,} 个启动事件，取启动日前 120 个交易日的量价路径（启动日收盘价归一=1.0）\n")

seg = [("T-120~-91（4个月前）", slice(0, 30)), ("T-90~-61", slice(30, 60)),
       ("T-60~-31", slice(60, 90)), ("T-30~-11", slice(90, 110)),
       ("T-10~-1（起点前10日）", slice(110, 120)), ("启动日", slice(119, 120))]
L.append("## 1. 价格路径（相对启动日收盘=1.0）\n")
L.append("| 区间 | 走远组 | 未走远组 | 差值 |")
L.append("|---|---|---|---|")
for nm, sl in seg:
    f = paths_p[lab == 1][:, sl].mean(); d = paths_p[lab == 0][:, sl].mean()
    L.append(f"| {nm} | **{f:.3f}** | {d:.3f} | {f-d:+.3f} |")

L.append("\n## 2. 成交量路径（相对前120日均量=1.0）\n")
L.append("| 区间 | 走远组 | 未走远组 | 差值 |")
L.append("|---|---|---|---|")
for nm, sl in seg:
    f = paths_v[lab == 1][:, sl].mean(); d = paths_v[lab == 0][:, sl].mean()
    L.append(f"| {nm} | **{f:.2f}** | {d:.2f} | {f-d:+.2f} |")

# 形态判定：建仓(横盘+量增) / 拉升(价升) / 洗盘(缩量回调) / 主升
L.append("\n## 3. 「建仓→拉升→洗盘→主升」形态验证\n")
for nm, s_e, s_p in [("建仓期T-120~-61：价平但量增", slice(0, 60), slice(0, 60)),
                     ("拉升期T-60~-21：价格上行", slice(60, 100), slice(60, 100)),
                     ("洗盘期T-20~-1：缩量回调", slice(100, 120), slice(100, 120))]:
    fv = paths_v[lab == 1][:, s_p].mean(); dv = paths_v[lab == 0][:, s_p].mean()
    fp = paths_p[lab == 1][:, s_e]; dp = paths_p[lab == 0][:, s_e]
    L.append(f"### {nm}")
    L.append(f"- 走远组：量 {fv:.2f}，价 {fp[:,0].mean():.3f}→{fp[:,-1].mean():.3f}（{(fp[:,-1].mean()/fp[:,0].mean()-1)*100:+.1f}%）")
    L.append(f"- 未走远组：量 {dv:.2f}，价 {dp[:,0].mean():.3f}→{dp[:,-1].mean():.3f}（{(dp[:,-1].mean()/dp[:,0].mean()-1)*100:+.1f}%）\n")

# 多因子组合
L.append("## 4. 多因子叠加（走远率基准 10.4%）\n")
L.append("| 组合条件 | 样本 | 走远率 | 60日涨幅中位 |")
L.append("|---|---|---|---|")
cond = {
    "① 涨停启动": (E.is_zt_hit >= .5),
    "①+② 温和放量(2-3倍)": (E.is_zt_hit >= .5) & (E.volr.between(2, 3)),
    "①+②+③ 高位(MA60上方>10%)": (E.is_zt_hit >= .5) & (E.volr.between(2, 3)) & (E.pma60 > .10),
    "①+②+③+④ 高波动(ATR>4.5%)": (E.is_zt_hit >= .5) & (E.volr.between(2, 3)) & (E.pma60 > .10) & (E.atr_pct > .045),
    "①+②+③+④+⑤ 行业超跌(60日<-15%)": (E.is_zt_hit >= .5) & (E.volr.between(2, 3)) & (E.pma60 > .10) & (E.atr_pct > .045) & (E.ind_ret60 < -.15),
    "【反例】非涨停+爆量(>5倍)+低位+低波": (E.is_zt_hit < .5) & (E.volr > 5) & (E.pma60 < 0) & (E.atr_pct < .03),
}
for k, v in cond.items():
    s = E[v]
    if len(s) > 0:
        L.append(f"| {k} | {len(s):,} | **{s.far.mean()*100:.1f}%** | {s.max60.median()*100:+.1f}% |")

L.append("\n## 5. 各因子单变量走远率排序（极值组）\n")
feat = {"ATR20>6%（高波动）": E.atr_pct > .06, "行业60日<-15%（板块超跌）": E.ind_ret60 < -.15,
        "低开<-3%启动": E.open_gap < -.03, "箱体>50%": E.box > .5, "一字板": (E.is_zt_hit >= .5) & (E.open_gap >= .09),
        "距60日高<-20%（深跌）": E.pdist_hi60 < -.20, "换手>1.2（活跃）": E.turn60 > 1.2,
        "MA60上方>10%（高位）": E.pma60 > .10, "前60日高波动>4.5%": E.amp > .045,
        "【劣】ATR<3%（低波）": E.atr_pct < .03, "【劣】窄箱体<15%": E.box < .15,
        "【劣】爆量8倍+": E.volr > 8, "【劣】非涨停放量大阳": E.is_zt_hit < .5}
rows = [(k, int(v.sum()), E[v].far.mean(), E[v].max60.median()) for k, v in feat.items() if v.sum() > 100]
rows.sort(key=lambda x: -x[2])
L.append("| 因子 | 样本 | 走远率 | 60日涨幅中位 |")
L.append("|---|---|---|---|")
for k, n, f, m in rows:
    L.append(f"| {k} | {n:,} | **{f*100:.1f}%** | {m*100:+.1f}% |")

open("outputs/yaogu_path.md", "w", encoding="utf-8").write("\n".join(L))
print("\n".join(L))
np.save("outputs/path_p.npy", paths_p); np.save("outputs/path_v.npy", paths_v); np.save("outputs/path_lab.npy", lab)
