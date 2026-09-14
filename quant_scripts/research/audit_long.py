import pandas as pd, numpy as np
S = pd.read_csv("/sandbox/workspace/zxz_bt/outputs/long_sig_daily.csv", dtype={"date": str})
B = pd.read_csv("/sandbox/workspace/zxz_bt/outputs/long_base_daily.csv", dtype={"date": str})


def nw_t(x, lag=20):
    x = np.asarray(x, float); x = x[~np.isnan(x)]; n = len(x)
    if n < 40:
        return np.nan, np.nan, n
    m = x.mean(); d = x - m; g0 = (d @ d) / n; s = g0
    for L in range(1, min(lag, n - 1) + 1):
        w = 1 - L / (lag + 1)
        s += 2 * w * ((d[L:] @ d[:-L]) / n)
    se = np.sqrt(max(s, 1e-12) / n)
    return m / se, m, n


agg = B.groupby(["dim", "env"]).agg(s=("sum", "sum"), n=("n", "sum")).reset_index()
agg["mean"] = agg.s / agg.n
L = ["# 20年长样本验证（全历史，沪深主板）\n",
     "**方法**：3,120 只沪深主板 × 全历史日线（流式，剔除无效价格段），信号按日聚合成日均收益，"
     "与**同日全样本基线**相减得日度超额序列，再做 **Newey-West t 检验（lag=20，校正20日持有期重叠）**。"
     "|t|≥1.96 = 5% 显著。\n",
     "**基线（20日收益，全样本等权）**：" + "、".join(f"{r.dim}·{r.env} {r['mean']*100:+.2f}%" for _, r in agg.iterrows()) + "\n",
     "| 信号 | 环境 | 事件数 | 独立交易日 | 日均超额 | 事件加权超额 | t值 | 结论 |",
     "|---|---|---|---|---|---|---|---|"]
BB = B.groupby(["dim", "env", "date"])["sum"].sum()
BC = B.groupby(["dim", "env", "date"])["n"].sum()
res = []
for (sig, dim, env), g in S.groupby(["signal", "dim", "env"]):
    if len(g) < 30:
        continue
    gm = g.groupby("date")["sum"].sum(); gn = g.groupby("date")["n"].sum()
    bd = (BB.loc[(dim, env)] / BC.loc[(dim, env)])
    ex = ((gm / gn) - bd.reindex(gm.index)).dropna()
    t, m, nd = nw_t(ex.values, 20)
    ev_n = int(g["n"].sum())
    bb = B[(B.dim == dim) & (B.env == env)]
    ew = g["sum"].sum() / ev_n * 100 - bb["sum"].sum() / bb["n"].sum() * 100
    v = ("✅ 5%显著" if abs(t) >= 1.96 else ("🔸 10%显著" if abs(t) >= 1.64 else "❌ 不显著"))
    res.append((sig, dim, env, ev_n, nd, m * 100, t, v, ew))
res.sort(key=lambda x: (x[0], x[1], x[2]))
for r in res:
    L.append(f"| {r[0]} | {r[1]}·{r[2]} | {r[3]:,} | {r[4]:,} | {r[5]:+.2f}% | {r[8]:+.2f}% | {r[6]:+.2f} | {r[7]} |")
open("/sandbox/workspace/zxz_bt/outputs/long_audit.md", "w", encoding="utf-8").write("\n".join(L))
print("\n".join(L))
