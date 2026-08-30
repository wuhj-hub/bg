#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wuwei_xianxing_report.py —— 无为"显性建仓标准"回测分析报告生成
读取 outputs/xianxing_signals_b*.json → 统计胜率/收益/盈亏比/基准对比/市场分层 → md报告
"""
import json, os, statistics, collections

OUT = "/sandbox/workspace/outputs"

def load_all():
    sigs, bases = [], {}
    for f in os.listdir(OUT):
        if f.startswith("xianxing_signals_b") and f.endswith(".json"):
            d = json.load(open(os.path.join(OUT, f)))
            sigs.extend(d["signals"])
            bases.update(d.get("bases", {}))
    return sigs, bases

def group_by_shadow(sigs, cutoff):
    """shadow_pct<=cutoff 的信号；cutoff=None 表示全部"""
    if cutoff is None:
        return sigs
    return [s for s in sigs if s["shadow_pct"] <= cutoff]

def stats(sigs, key):
    """胜率/平均/中位/盈亏比/最大亏"""
    vals = [s[key] for s in sigs if s[key] is not None]
    if not vals:
        return None
    n = len(vals)
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    win_rate = len(wins) / n * 100
    avg = sum(vals) / n
    med = statistics.median(vals)
    pl = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    return {"n": n, "win": win_rate, "avg": avg, "med": med, "pl": pl, "maxloss": min(vals)}

def fmt(x):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.2f}"
    return str(x)

def main():
    sigs, bases = load_all()
    print(f"总信号: {len(sigs)}  有基准股票: {len(bases)}")

    md = []
    md.append("# 无为「显性建仓标准」回测报告")
    md.append("")
    md.append("**规则来源**：张德涛（无为老师）《交易必杀计》显性建仓成功标准")
    md.append("")
    md.append("- ① 量：至少为倍量（当日成交量 ≥ 2×前一日）")
    md.append("- ② 价：实体 ≥ 5%，实体=(收盘-开盘)/昨收")
    md.append("- ③ 影线：最好无上影线，上影越短越好（多档对比验证）")
    md.append("- ④ 周期：日线（60分钟数据不可得，日线为规则允许周期之一）")
    md.append("")
    md.append("**回测设置**：信号日收盘买入 → 持有5/10/20/60交易日收盘卖出；全A沪深主板（剔除ST/PT/退市），前复权日K，2022-08 ~ 2026-08（约1000根/只）")
    md.append("")
    md.append(f"**样本**：{len(sigs)} 个信号，覆盖 {len(bases)} 只有信号股票（全A沪深主板3117只中2770只出现过信号）")
    md.append("")
    md.append("---")
    md.append("")

    # ============ 1. 上影线档位对比 ============
    md.append("## 一、上影线条件多档对比（核心结论）")
    md.append("")
    md.append("| 档位 | 定义 | 信号数 | 持有 | 胜率 | 平均收益 | 中位收益 | 盈亏比 | 最大单笔亏 |")
    md.append("|------|------|-------:|------|-----:|---------:|---------:|-------:|-----------:|")
    tiers = [
        ("V0 不限上影", None),
        ("V3 上影≤实体30%", 30.0),
        ("V2 上影≤实体10%", 10.0),
        ("V1 严格无上影(≤0.1%)", 0.1),
    ]
    for name, cutoff in tiers:
        g = group_by_shadow(sigs, cutoff)
        for H in (5, 20, 60):
            st = stats(g, f"ret_{H}")
            if not st:
                continue
            md.append(f"| {name} | - | {st['n']} | {H}日 | {st['win']:.1f}% | {st['avg']:+.2f}% | {st['med']:+.2f}% | {fmt(st['pl'])} | {st['maxloss']:+.1f}% |")
        md.append("")

    # ============ 2. 基准对比（同股票随机买入） ============
    md.append("## 二、vs 同股票随机基准（规则是否有alpha）")
    md.append("")
    md.append("对每只信号股，计算其全样本任意日买入持有H日的平均收益/胜率作为基准；信号收益减去该基准即超额。")
    md.append("")
    md.append("| 档位 | 持有 | 信号胜率 | 基准胜率 | 胜率差 | 信号均收益 | 基准均收益 | 超额收益 |")
    md.append("|------|------|---------:|---------:|-------:|-----------:|-----------:|---------:|")
    for name, cutoff in tiers:
        g = group_by_shadow(sigs, cutoff)
        for H in (5, 20, 60):
            key = f"ret_{H}"
            hk = str(H)
            pairs = []
            for s in g:
                if s[key] is None or s["code"] not in bases:
                    continue
                b = bases[s["code"]].get(hk)
                if not b:
                    continue
                pairs.append((s[key], b))
            if len(pairs) < 30:
                continue
            sig_win = sum(1 for v, _ in pairs if v > 0) / len(pairs) * 100
            sig_avg = sum(v for v, _ in pairs) / len(pairs)
            b_avg = sum(b["avg"] for _, b in pairs) / len(pairs)
            b_win = sum(b["win"] for _, b in pairs) / len(pairs)
            md.append(f"| {name} | {H}日 | {sig_win:.1f}% | {b_win:.1f}% | {sig_win-b_win:+.1f}pct | {sig_avg:+.2f}% | {b_avg:+.2f}% | {sig_avg-b_avg:+.2f}pct |")
        md.append("")

    # ============ 3. 市场分层（V2档） ============
    md.append("## 三、市场分层（上影≤10%档）")
    md.append("")
    g2 = group_by_shadow(sigs, 10.0)
    regimes = ["牛", "震荡", "熊"]
    md.append("| 市场状态 | 信号数 | 持有 | 胜率 | 平均收益 |")
    md.append("|----------|-------:|------|-----:|---------:|")
    for rg in regimes:
        gr = [s for s in g2 if s.get("regime") == rg]
        if not gr:
            continue
        for H in (5, 20):
            st = stats(gr, f"ret_{H}")
            if not st:
                continue
            md.append(f"| {rg} | {st['n']} | {H}日 | {st['win']:.1f}% | {st['avg']:+.2f}% |")
        md.append("")

    # ============ 4. 信号特征 ============
    md.append("## 四、信号特征分布（V2档）")
    md.append("")
    g2 = group_by_shadow(sigs, 10.0)
    if g2:
        pcts = [s["pct_chg"] for s in g2]
        limit_up = sum(1 for p in pcts if p >= 9.8)
        big = sum(1 for p in pcts if 5 <= p < 9.8)
        vols = [s["vol_ratio"] for s in g2]
        bodies = [s["body_pct"] for s in g2]
        md.append(f"- 信号日涨幅：均值 {statistics.mean(pcts):.1f}%，涨停(≥9.8%)占比 {limit_up/len(pcts)*100:.0f}%，5%~9.8%占比 {big/len(pcts)*100:.0f}%")
        md.append(f"- 倍量比：中位 {statistics.median(vols):.1f} 倍，均值 {statistics.mean(vols):.1f} 倍")
        md.append(f"- 实体幅度：中位 {statistics.median(bodies):.1f}%，均值 {statistics.mean(bodies):.1f}%")
        md.append("")
        # 按涨幅区间细分胜率（V2，持有20日）
        md.append("**按信号日涨幅分组的20日持有表现**（检验是否涨停追高）")
        md.append("")
        md.append("| 信号日涨幅 | 信号数 | 胜率 | 平均收益 |")
        md.append("|-----------|-------:|-----:|---------:|")
        for lo, hi, label in [(5, 7, "5%~7%"), (7, 9.8, "7%~9.8%"), (9.8, 100, "≥9.8%涨停")]:
            gs = [s for s in g2 if lo <= s["pct_chg"] < hi]
            st = stats(gs, "ret_20")
            if st and st["n"] >= 10:
                md.append(f"| {label} | {st['n']} | {st['win']:.1f}% | {st['avg']:+.2f}% |")
        md.append("")

    # ============ 5. 实战修正组合（V2∩非涨停） ============
    md.append("## 五、实战修正组合：上影≤10% ∩ 非涨停（5%~9.8%）")
    md.append("")
    md.append("原始信号75%是涨停（追不进、且表现最差），实战可成交且有效的部分是非涨停显性建仓。")
    md.append("")
    fix = [s for s in g2 if 5 <= s["pct_chg"] < 9.8]
    md.append("| 持有 | 信号数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 |")
    md.append("|------|-------:|-----:|---------:|---------:|-------:|")
    for H in (5, 10, 20, 60):
        st = stats(fix, f"ret_{H}")
        md.append(f"| {H}日 | {st['n']} | {st['win']:.1f}% | {st['avg']:+.2f}% | {st['med']:+.2f}% | {fmt(st['pl'])} |")
    md.append("")
    md.append("**vs 同股票随机基准**")
    md.append("")
    md.append("| 持有 | 信号胜率 | 基准胜率 | 胜率差 | 信号均收益 | 基准均收益 | 超额收益 |")
    md.append("|------|---------:|---------:|-------:|-----------:|-----------:|---------:|")
    for H in (5, 10, 20, 60):
        key = f"ret_{H}"
        hk = str(H)
        pairs = [(s[key], bases[s["code"]][hk]) for s in fix if s[key] is not None and s["code"] in bases and bases[s["code"]].get(hk)]
        if len(pairs) < 30:
            continue
        sig_win = sum(1 for v, _ in pairs if v > 0) / len(pairs) * 100
        sig_avg = sum(v for v, _ in pairs) / len(pairs)
        b_avg = sum(b["avg"] for _, b in pairs) / len(pairs)
        b_win = sum(b["win"] for _, b in pairs) / len(pairs)
        md.append(f"| {H}日 | {sig_win:.1f}% | {b_win:.1f}% | {sig_win-b_win:+.1f}pct | {sig_avg:+.2f}% | {b_avg:+.2f}% | {sig_avg-b_avg:+.2f}pct |")
    md.append("")
    md.append("**市场分层（持有20日）**")
    md.append("")
    md.append("| 市场状态 | 信号数 | 胜率 | 平均收益 |")
    md.append("|----------|-------:|-----:|---------:|")
    for rg in regimes:
        gr = [s for s in fix if s.get("regime") == rg]
        st = stats(gr, "ret_20")
        if st and st["n"] >= 30:
            md.append(f"| {rg} | {st['n']} | {st['win']:.1f}% | {st['avg']:+.2f}% |")
    md.append("")

    # ============ 6. 年度分布 ============
    md.append("## 六、年度分布（V2档，持有20日）")
    md.append("")
    years = collections.OrderedDict()
    for s in g2:
        y = s["date"][:4]
        years.setdefault(y, []).append(s)
    md.append("| 年份 | 信号数 | 胜率 | 平均收益 |")
    md.append("|------|-------:|-----:|---------:|")
    for y, gs in years.items():
        st = stats(gs, "ret_20")
        md.append(f"| {y} | {st['n']} | {st['win']:.1f}% | {st['avg']:+.2f}% |")
    md.append("")

    # ============ 7. 结论 ============
    md.append("## 七、结论")
    md.append("")
    md.append("### 1）原始规则（倍量+实体5%）的真实胜率")
    md.append("- **长期无alpha**：全档信号持有20日胜率42.2%、60日41.2%，**显著低于同股票随机基准（48.6%/48.4%）**，超额收益为负（-1.0~-2.3pct）")
    md.append("- **短期微弱正超额**：持有5日均收益+0.46%（超额+0.14pct），因盈亏比1.47>1，但胜率仍低于基准3.9pct")
    md.append("- 中位收益为负（-0.97%~-3.97%），即**多数信号买入后是亏的**，靠少数大赢家拉回均值")
    md.append("")
    md.append("### 2）「无上影线」条件的价值")
    md.append("- **确认有效**：从V0→V1（严格无上影），5日胜率43.9%→46.1%、超额+0.14→+0.86pct，单调改善")
    md.append("- **但仅限短期**：20/60日上影过滤后负超额反而扩大（追涨后长持无益）")
    md.append("")
    md.append("### 3）真正的坑：涨停追高")
    md.append("- 75%的信号是当日涨停（≥9.8%），这20日胜率仅40.4%、均收益-0.10%——**涨停板买入既难成交又表现最差**")
    md.append("- 非涨停的温和显性建仓（5~9.8%）：20日胜率47.6%、均收益+1.85%，明显占优")
    md.append("")
    md.append("### 4）实战修正组合（上影≤10% ∩ 非涨停）")
    md.append("- 可成交形态：20日胜率46.7%、均收益+1.54%（超额+0.47pct）；5日超额最明显（+0.89pct）。相对随机基准**接近持平、略优**，非显著alpha")
    md.append("- **最强信号在市场分层**：熊市反弹窗口胜率59.4%、均收益+6.57%（20日），震荡市45.6%/+1.01%，牛市反而最差41.8%/-0.27%")
    md.append("- 即：非涨停显性建仓本质是**超跌反弹捕捉器**（熊市/震荡市深跌后的放量阳线），在牛市中追涨无优势")
    md.append("")
    md.append("### 5）总体判定")
    md.append("**无为「显性建仓标准」作为独立选股信号：不成立**（裸信号跑不赢随机买入）。但三个子条件有真实价值：")
    md.append("- ✅ **上影线过滤**（无上影/短上影=筹码锁定好）——短期正增量")
    md.append("- ✅ **非涨停过滤**（排除当日涨停）——避开追高陷阱，保留可成交信号")
    md.append("- ✅ **市场环境过滤**（仅熊市/震荡市使用）——胜率从41.8%提升到59.4%，这是最大的单一增益")
    md.append("- ⚠️ 剩余部分可作为**情绪/资金类叠加条件**（如配合主力资金流、板块共振）使用，而非独立入场依据")
    md.append("")
    md.append("### 6）回测局限")
    md.append("- 信号日收盘价买入假设：75%涨停信号实际无法成交，会**高估**原始规则的成交收益率")
    md.append("- 未计手续费/滑点（约0.1%~0.3%单边），对5日短线影响明显")
    md.append("- 前复权数据，分红送转已调整")
    md.append("- 60分钟周期未验证（westock无分钟K线），日线为规则允许周期之一")
    md.append("")

    report = "\n".join(md)
    path = os.path.join(OUT, "无为显性建仓标准_回测报告_2026-08-30.md")
    with open(path, "w") as f:
        f.write(report)
    print(f"报告已保存: {path}")
    print(report[:3000])

if __name__ == "__main__":
    main()
