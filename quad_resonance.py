#!/usr/bin/env python3
"""四维共振评分器（quad_resonance）——政策/资金/筹码/关联方 四维独立证据链

框架来源：《四维共振思维框架》（政策=意志/资金=买盘/筹码=供给/关联方=内幕）
每维 0-3 分，四维求和 0-12：
  10-12 → ★★★ "必然"级（四维独立证据闭合，高置信重仓）
  7-9   → ★★ 高置信（标准仓位）
  4-6   → ★ 弱共振（轻仓试探）
  ≤3    → 不构成共振（观察/否决）
反向否决：资金流出(0) 且 关联方折价减持 → 整体否决标注

数据源：
  资金   = panhou_lianghua.csv（资金四态 phase / 沉淀率 precip）
  筹码   = westock chip（chipProfitRate获利盘 / chipConcentration90集中度）
  关联方 = westock lhb（龙虎榜NetBuy+机构席位）+ blocktrade（大宗CloseDiscountRate折价率）
  政策   = --policy 参数人工研判（0-3，默认0标注"需人工研判"）

用法: python3 quad_resonance.py [--pool panhou_lianghua.csv] [--policy 3] [--top 15]
输出: outputs/四维共振_{date}.md + outputs/四维共振_latest.json
"""
import csv, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
OUT_DIR = "outputs"


def run(args, timeout=60):
    for i in range(3):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""


def parse_table(txt):
    """多块表格解析：westock 输出多张表用空行分隔，逐块独立解析后合并。
    返回 [{列名: 值}, ...]（跨表合并）"""
    out = []
    for block in txt.split("\n\n"):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip().startswith("|")]
        if len(lines) < 3:
            continue
        header = [p.strip() for p in lines[0].strip("|").split("|")]
        for ln in lines[2:]:
            d = [p.strip() for p in ln.strip("|").split("|")]
            if len(d) == len(header):
                out.append(dict(zip(header, d)))
    return out


# ============================================================
# 维度评分
# ============================================================
def score_fund(phase, precip):
    """资金维度 0-3：四态优先，沉淀率兜底"""
    s = {"抢筹": 3, "吸筹": 2, "进场": 1, "控盘": 1, "观望": 0}.get(phase, 0)
    try:
        p = float(str(precip).rstrip("%"))
        if p > 5: s = max(s, 3)
        elif p > 2: s = max(s, 2)
        elif p > 0: s = max(s, 1)
    except Exception:
        pass
    return s


def score_chip(code):
    """筹码维度 0-3：chipProfitRate获利盘 + 集中度"""
    rows = parse_table(run(["chip", code]))
    if not rows:
        return 0, "无筹码数据"
    r = rows[0]
    try:
        profit = float(r.get("chipProfitRate", 0) or 0)
        conc90 = float(r.get("chipConcentration90", 99) or 99)
    except Exception:
        return 0, "筹码解析失败"
    if profit >= 70: s = 3
    elif profit >= 50: s = 2
    elif profit >= 30: s = 1
    else: s = 0
    detail = f"获利盘{profit:.0f}%"
    if conc90 < 15:
        s = min(3, s + 1)
        detail += f"·集中度{conc90:.1f}(集中)"
    else:
        detail += f"·集中度{conc90:.1f}"
    return s, detail


def score_related(code):
    """关联方维度 0-3：龙虎榜(机构/游资/净买) + 大宗(折价率)"""
    s, detail = 0, []
    # 龙虎榜（多块表：统计表含 NetBuy，明细表含 Name/机构专用）
    lhb_rows = parse_table(run(["lhb", code]))
    if lhb_rows:
        net = None
        for r in lhb_rows:
            if r.get("NetBuy"):
                try:
                    net = float(r["NetBuy"])
                    break
                except Exception:
                    pass
        detail_txt = [r for r in lhb_rows if r.get("Name") and r.get("Buy")]
        inst_buy = any("机构" in (r.get("Name", "") or "") and float(r.get("Buy", 0) or 0) > 0 for r in detail_txt)
        if net is not None and net > 0:
            s = max(s, 3 if inst_buy else 2)
            detail.append(f"龙虎榜净买{net/1e4:.0f}万{'机构' if inst_buy else '游资'}")
        elif net is not None:
            detail.append(f"龙虎榜净卖{abs(net)/1e4:.0f}万")
    # 大宗
    bt_rows = parse_table(run(["blocktrade", code]))
    if bt_rows and "CloseDiscountRate" in bt_rows[0]:
        try:
            disc = float(bt_rows[0].get("CloseDiscountRate", 0) or 0)
            if disc < 0:
                s = max(s, 2)
                detail.append(f"大宗溢价{abs(disc):.1f}%")
            elif disc <= 5:
                s = max(s, 1)
                detail.append(f"大宗近平价({disc:.1f}%)")
            else:
                detail.append(f"大宗折价{disc:.1f}%(减持)")  # 反向信号
        except Exception:
            pass
    if not detail:
        detail.append("无交易行为")
    return s, "；".join(detail)


# ============================================================
# 主流程
# ============================================================
def main():
    pool_path = "panhou_lianghua.csv"
    policy = 0
    top_n = 15
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--pool" and i + 1 < len(argv):
            pool_path = argv[i + 1]
        if a == "--policy" and i + 1 < len(argv):
            policy = int(argv[i + 1])
        if a == "--top" and i + 1 < len(argv):
            top_n = int(argv[i + 1])

    if not os.path.exists(pool_path):
        print(f"[ERR] 股票池不存在: {pool_path}")
        sys.exit(1)
    rows = list(csv.DictReader(open(pool_path, encoding="utf-8")))
    stocks = [(r["code"], r["name"], r.get("phase", ""), r.get("precip", 0)) for r in rows]
    print(f"[INFO] 股票池 {len(stocks)} 只（四维评分，政策维度={policy}）", flush=True)

    def work(item):
        code, name, phase, precip = item
        full = ("sh" if code.startswith("6") else "sz") + code
        fs = score_fund(phase, precip)
        cs, cd = score_chip(full)
        rs, rd = score_related(full)
        total = fs + cs + rs + policy
        if total >= 10: level = "★★★ 必然级"
        elif total >= 7: level = "★★ 高置信"
        elif total >= 4: level = "★ 弱共振"
        else: level = "无共振"
        # 反向否决：资金0 + 关联方折价/净卖
        veto = ""
        if fs == 0 and ("折价" in rd or "净卖" in rd):
            veto = "⚠️ 反向否决(资金流出+关联方减持)"
            level = "否决"
        return {"code": code, "name": name, "fund": fs, "chip": cs, "related": rs,
                "policy": policy, "total": total, "level": level, "veto": veto,
                "chip_detail": cd, "related_detail": rd}

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(work, stocks):
            if r:
                results.append(r)
    results.sort(key=lambda x: (-x["total"], x["code"]))

    today = datetime.now().strftime("%Y-%m-%d")
    js = {"date": today, "policy": policy, "pool_size": len(results),
          "levels": {"必然级": sum(1 for r in results if r["level"] == "★★★ 必然级"),
                     "高置信": sum(1 for r in results if r["level"] == "★★ 高置信"),
                     "弱共振": sum(1 for r in results if r["level"] == "★ 弱共振"),
                     "无共振": sum(1 for r in results if r["level"] == "无共振"),
                     "否决": sum(1 for r in results if r["level"] == "否决")},
          "stocks": results}
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "四维共振_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    L = [f"# 🧩 四维共振评分 {today}", "",
         f"> 框架：政策(意志) + 资金(买盘) + 筹码(供给) + 关联方(内幕) = 独立证据链闭合",
         f"> 池子 {len(results)} 只 | 政策维度={policy}({'人工研判' if policy == 0 else '已赋值'})",
         f"> 分级：≥10 ★★★必然 / 7-9 ★★高置信 / 4-6 ★弱共振 / ≤3 无共振 | 资金0+关联方减持=否决", ""]
    L.append("## 共振级分布")
    L.append(f"- ★★★ 必然级: {js['levels']['必然级']} | ★★ 高置信: {js['levels']['高置信']} | ★ 弱共振: {js['levels']['弱共振']} | 无共振: {js['levels']['无共振']} | 否决: {js['levels']['否决']}")
    L.append("")
    L.append("## 四维评分明细（TOP{0}）".format(min(top_n, len(results))))
    L.append("| 代码 | 名称 | 资金 | 筹码 | 关联方 | 政策 | 总分 | 共振级 | 筹码/关联方明细 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in results[:top_n]:
        v = f" {r['veto']}" if r["veto"] else ""
        L.append(f"| {r['code']} | {r['name']} | {r['fund']} | {r['chip']} | {r['related']} | {r['policy']} | {r['total']} | {r['level']}{v} | {r['chip_detail']}；{r['related_detail']} |")
    L.append("")
    L.append("## 说明")
    L.append("- 资金=四态(抢筹3/吸筹2/进场1)+沉淀率兜底 | 筹码=获利盘≥70%+集中度<15加成 | 关联方=龙虎榜机构3/游资2+大宗溢价2/平价1")
    L.append("- 政策维度需人工研判（--policy 0-3），当前为0不代表政策面差，而是未赋值")
    L.append("- 四维独立信源同向=证据链闭合；反向否决=资金流出且关联方减持时强制降级")
    md_path = os.path.join(OUT_DIR, f"四维共振_{today}.md")
    open(md_path, "w", encoding="utf-8").write("\n".join(L))
    print(f"[OK] {json_path}")
    print(f"[OK] {md_path}")
    print(f"共振分布: 必然{js['levels']['必然级']} 高置信{js['levels']['高置信']} 弱共振{js['levels']['弱共振']} 无共振{js['levels']['无共振']} 否决{js['levels']['否决']}")


if __name__ == "__main__":
    main()
