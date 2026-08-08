#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
full_market_dualdim.py —— 全盘量化扫描

读 all_mainboard.csv，对每只股票并发调用 westock-data-skillhub 计算：
  - 沉淀率 = MainNetFlow5D ÷ 近5日总成交额
  - CJB30 / B30V100 / VEAB（放量趋势，对齐盘前报告 §2.12）
套用双维定性矩阵得到信号，输出：
  - panhou_lianghua.csv（全量结果）
  - panhou_lianghua.md（分布统计 + 重点标的）

运行环境：GitHub Actions runner（westock 需外网 + node）。
注意：此脚本输出为复盘报告的原始数据源，不独立作为分析报告发布。
"""

import subprocess
import re
import json
import csv
import sys
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
TIMEOUT = 120
RETRIES = 2

SIGNAL_ORDER = {
    "主力主导放量🔥(最强)": 0,
    "游资情绪": 1,
    "主力控盘": 2,
    "主力偏强放量": 3,
    "主力惜售": 4,
    "情绪退潮": 5,
}


def run(args, timeout=TIMEOUT):
    for _ in range(RETRIES + 1):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            return r.stdout
        except Exception as e:
            if _ == RETRIES:
                return f"ERR:{e}"
            time.sleep(2)


def parse_kline(txt):
    rows = []
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if header and "---" not in parts[0]:
            try:
                if re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                    rows.append({"date": parts[0], "amount": float(parts[header.index("amount")]), "last": float(parts[header.index("last")])})
            except Exception:
                pass
    return sorted(rows, key=lambda r: r["date"])


def parse_asfund(txt):
    header = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "code" in parts:
            header = parts
            continue
        if header and "---" not in parts[0]:
            return {header[i]: parts[i] for i in range(min(len(header), len(parts)))}
    return None


def fnum(d, k):
    try:
        return float(d.get(k, 0))
    except Exception:
        return 0.0


def calc_board(amounts):
    n = len(amounts)
    if n < 105:
        return None
    today = amounts[-1]
    m30 = sum(amounts[n - 60:n - 30]) / 30.0
    m5_100 = sum(amounts[n - 105:n - 100]) / 5.0
    cjb30 = (today - m30) / m30 * 100 if m30 else 0
    b30v100 = m30 / m5_100 if m5_100 else 0
    recent = sum(amounts[n - 10:]) / 10.0
    prev = sum(amounts[n - 20:n - 10]) / 10.0
    veab = (recent - prev) / prev * 100 if prev else 0
    return {"cjb30": round(cjb30, 1), "b30v100": round(b30v100, 2), "veab": round(veab, 1)}


def classify(cjb30, precip):
    vol = "放量" if cjb30 > 50 else "缩量"
    if precip > 10:
        lv = "高"
    elif precip >= 5:
        lv = "中"
    else:
        lv = "低"
    m = {
        ("放量", "高"): "主力主导放量🔥(最强)",
        ("放量", "中"): "主力偏强放量",
        ("放量", "低"): "游资情绪",
        ("缩量", "高"): "主力控盘",
        ("缩量", "中"): "主力惜售",
        ("缩量", "低"): "情绪退潮",
    }
    return vol, lv, m[(vol, lv)]


def to_westock_code(code):
    if code.lower().startswith(("sh", "sz")):
        return code
    if code.startswith("60"):
        return "sh" + code
    if code.startswith(("000", "001", "002", "003")):
        return "sz" + code
    return code


def fund_phase(precip, cjb30, m5, m10, m20, mainflow, jumbo, small):
    """资金行为五态（黑石SUPER_CAPITAL三维+机构吸筹启发）
    控盘 = 缩量高沉淀（筹码锁定，趋势延续）
    抢筹 = 超大单+放量（加速建仓/拉升，最激进）
    吸筹 = 机构买+散户卖（Jumbo>0 & Small<0 & Jumbo>|Small|，黑石机构流/散户流反向）
    进场 = 今日净流转正+5D累计正（温和建仓）
    观望 = 无明确资金行为
    """
    if cjb30 < 50 and precip >= 10:
        return "控盘"
    # 抢筹：放量 + 超大单主导（超大单占5D净流≥30%）
    if jumbo > 0 and cjb30 >= 50 and m5 != 0 and jumbo / abs(m5) >= 0.3:
        return "抢筹"
    # 吸筹：机构超大单买入 + 散户小单卖出（黑石机构吸筹组合）
    if jumbo > 0 and small < 0 and jumbo > abs(small):
        return "吸筹"
    if mainflow > 0 and m5 > 0:
        return "进场"
    if m5 > 0 and precip >= 5:
        return "进场"
    return "观望"



def fund_mode(r5, r10, r20):
    """8大资金模式（黑石启发，r5=近5日沉淀率, r10=5-10日段占比, r20=10-20日段占比）"""
    pos5, pos10, pos20 = r5 > 0, r10 > 0, r20 > 0
    # 主力强攻型：近期强流入+中期正（机构/游资联合拉升）
    if r5 > 5 and r10 > 3 and pos20:
        return "主力强攻型"
    # 主力建仓型：温和持续流入（中长期有序建仓）
    if r5 > 2 and r10 > 2 and pos20:
        return "主力建仓型"
    # 短线抢筹型：近期强+中期弱正+20日负（游资短炒无沉淀）
    if r5 > 5 and r10 > 1 and not pos20:
        return "短线抢筹型"
    # 长线吸筹型：近期弱+20日强正（耐心资金逆向布局）
    if r5 < 2 and r10 < 2 and r20 > 3:
        return "长线吸筹型"
    # 资金撤退型：三周期全负
    if not pos5 and not pos10 and not pos20:
        return "资金撤退型"
    # 高位分歧型：短期出货+中长期沉淀
    if not pos5 and pos10 and r20 > 2:
        return "高位分歧型"
    # 趋势转多型：近两段转正+20日仍负（由空翻多）
    if pos5 and pos10 and not pos20:
        return "趋势转多型"
    # 均衡流入型：三周期温和正
    if pos5 and pos10 and pos20:
        return "均衡流入型"
    return "资金观望型"



def fetch_profit(wcode):
    """获取最新TTM归母净利润（元），失败返回None"""
    try:
        txt = run(["finance", wcode, "--num", "1"])
        for ln in txt.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            if "NPParentCompanyOwnersTTM" in parts:
                continue
            if "---" in parts[0]:
                continue
            for i, p in enumerate(parts):
                if p == "NPParentCompanyOwnersTTM":
                    continue
            # 按表头定位
            if len(parts) >= 10:
                try:
                    return float(parts[parts.index("NPParentCompanyOwnersTTM")] if "NPParentCompanyOwnersTTM" in parts else 0)
                except Exception:
                    pass
            break
    except Exception:
        pass
    return None


def fetch_profit_simple(wcode):
    """简化版：解析finance输出的TTM净利润列"""
    try:
        txt = run(["finance", wcode, "--num", "1"])
        header = None
        for ln in txt.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            if "NPParentCompanyOwnersTTM" in parts:
                header = parts
                continue
            if header and "---" not in parts[0] and len(parts) == len(header):
                try:
                    return float(parts[header.index("NPParentCompanyOwnersTTM")])
                except (ValueError, IndexError):
                    return None
    except Exception:
        pass
    return None


def process(stock):
    code, name = stock
    wcode = to_westock_code(code)
    try:
        kr = parse_kline(run(["kline", wcode, "--period", "day", "--limit", "130"]))
        ar = parse_asfund(run(["asfund", wcode]))
        if not kr or not ar:
            return None
        amounts = [r["amount"] for r in kr]
        if len(amounts) < 105:
            return None
        bt = calc_board(amounts)
        if not bt:
            return None
        m5 = fnum(ar, "MainNetFlow5D")
        m10 = fnum(ar, "MainNetFlow10D")
        m20 = fnum(ar, "MainNetFlow20D")
        mainflow = fnum(ar, "MainNetFlow")
        jumbo = fnum(ar, "JumboNetFlow")
        small = fnum(ar, "SmallNetFlow")
        denom = sum(amounts[-5:])
        precip = m5 / denom * 100 if denom else 0.0
        vol, lv, sig = classify(bt["cjb30"], precip)
        phase = fund_phase(precip, bt["cjb30"], m5, m10, m20, mainflow, jumbo, small)
        # 8大资金模式（黑石启发）
        turn5 = sum(amounts[-5:])
        turn10 = sum(amounts[-10:])
        r5 = precip  # 近5日沉淀率
        r10 = (m10 - m5) / turn5 * 100 if turn5 else 0  # 5-10日段占比
        r20 = (m20 - m10) / turn10 * 100 if turn10 else 0  # 10-20日段占比
        mode = fund_mode(r5, r10, r20)
        # 资金×业绩匹配（黑石第2层：只对流入类查财务，控制耗时）
        matching = ""
        if phase in ("抢筹", "吸筹", "进场"):
            profit = fetch_profit_simple(wcode)
            if profit is not None:
                if profit > 0:
                    matching = "资金+业绩共振(双击候选)" if phase != "控盘" else "控盘+盈利(稳健)"
                else:
                    matching = "纯资金炒作(亏损风险)"
        elif phase == "控盘":
            profit = fetch_profit_simple(wcode)
            if profit is not None:
                matching = "控盘+盈利(稳健)" if profit > 0 else "控盘+亏损(警惕)"
        return {
            "code": code, "name": name,
            "cjb30": bt["cjb30"], "b30v100": bt["b30v100"], "veab": bt["veab"],
            "precip": round(precip, 2), "m5": round(m5), "m10": round(m10), "m20": round(m20),
            "mainflow": round(mainflow), "jumbo": round(jumbo), "small": round(small),
            "vol": vol, "lv": lv, "sig": sig, "phase": phase, "mode": mode, "matching": matching,
            "price": kr[-1]["last"] if kr else 0,
        }
    except Exception as e:
        return {"code": code, "name": name, "error": str(e)}


def gen_report(results, dist, today):
    ordered = sorted(results, key=lambda r: (SIGNAL_ORDER.get(r["sig"], 9), -r["precip"]))
    L = []
    L.append(f"# 全盘量化报告（{today} 收盘）\n")
    L.append("> 范围：沪深主板（剔除科创板/创业板/北交所/ST），约 3000 只逐只扫描")
    L.append("> 双维口径：沉淀率 = MainNetFlow5D ÷ 近5日总成交额；CJB30 = (今日成交额 − 近30日均量)/近30日均量×100（>50% 为放量）\n")
    L.append("## 一、双维定性分布\n")
    L.append("| 定性 | 数量 |")
    L.append("|---|---|")
    for k, v in sorted(dist.items(), key=lambda x: SIGNAL_ORDER.get(x[0], 9)):
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## 一.5 资金行为分布（五态：抢筹/吸筹/进场/控盘/观望，黑石启发）\n")
    ph_dist = Counter(r["phase"] for r in results)
    L.append("| 资金行为 | 数量 | 含义 |")
    L.append("|---|---|---|")
    for ph, desc in [("抢筹", "超大单+放量，加速建仓/拉升，最强"), ("吸筹", "机构买+散户卖（Jumbo>0&Small<0），黑石机构吸筹组合"),
                     ("进场", "今日净流转正+5D累计正，温和建仓"), ("控盘", "缩量高沉淀，筹码锁定，趋势延续"), ("观望", "无明确资金行为")]:
        L.append(f"| {ph} | {ph_dist.get(ph, 0)} | {desc} |")
    L.append("")
    L.append("### 资金行为 TOP15（抢筹/吸筹优先）\n")
    ph_order = {"抢筹": 0, "吸筹": 1, "进场": 2, "控盘": 3, "观望": 4}
    ph_sorted = sorted(results, key=lambda r: (ph_order.get(r.get("phase", "观望"), 9), -r["precip"]))
    L.append("| 代码 | 名称 | 资金行为 | CJB30 | 沉淀率 | 5D净流(亿) | 今日净流(亿) | 超大单(亿) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in [x for x in ph_sorted if x.get("phase") in ("抢筹", "吸筹", "进场")][:15]:
        L.append(f"| {r['code']} | {r['name']} | {r['phase']} | {r['cjb30']} | {r['precip']}% | "
                 f"{r['m5']/1e8:.2f} | {r['mainflow']/1e8:.2f} | {r['jumbo']/1e8:.2f} |")
    L.append("")
    # 一.6 资金模式分布（8大模式，黑石启发）
    md_dist = Counter(r.get("mode", "资金观望型") for r in results)
    L.append("## 一.6 资金模式分布（8大模式：强攻/建仓/抢筹/吸筹/转多/均衡/撤退/分歧）\n")
    L.append("| 资金模式 | 数量 | 解读 |")
    L.append("|---|---|---|")
    for md, desc in [("主力强攻型", "机构/游资联合拉升，短期趋势明确"),
                     ("主力建仓型", "中长期资金有序流入，回调加仓机会"),
                     ("长线吸筹型", "耐心资金逆向布局，等待催化引爆"),
                     ("趋势转多型", "由空翻多底部回补，拐点确认后跟进"),
                     ("均衡流入型", "三周期温和流入，稳健上行弹性有限"),
                     ("短线抢筹型", "游资短炒无沉淀，脉冲行情追高危险"),
                     ("高位分歧型", "短期出货中长期沉淀，看量判洗盘/出货"),
                     ("资金撤退型", "资金持续出走，回避为主"),
                     ("资金观望型", "资金行为不明确")]:
        L.append(f"| {md} | {md_dist.get(md, 0)} | {desc} |")
    L.append("")
    # 一.7 资金×业绩匹配（黑石第2层启发）
    dbl = [r for r in results if r.get("matching") == "资金+业绩共振(双击候选)"]
    if dbl:
        L.append("## 一.7 资金×业绩匹配（双击候选：流入+盈利）\n")
        L.append("| 代码 | 名称 | 资金行为 | 模式 | CJB30 | 沉淀率 | 5D净流(亿) |")
        L.append("|---|---|---|---|---|---|---|")
        for r in sorted(dbl, key=lambda x: -x["precip"])[:15]:
            L.append(f"| {r['code']} | {r['name']} | {r['phase']} | {r.get('mode','')} | {r['cjb30']} | {r['precip']}% | {r['m5']/1e8:.2f} |")
        L.append("")
    pure = [r for r in results if r.get("matching") == "纯资金炒作(亏损风险)"]
    if pure:
        L.append(f"> ⚠️ 纯资金炒作警示（流入+亏损）：{len(pure)}只，见CSV matching字段\n")
    L.append("## 二、重点标的（按信号强度 + 沉淀率降序，前 50）\n")
    L.append("| 代码 | 名称 | CJB30 | 沉淀率 | 5D主力净流(亿) | 定性 |")
    L.append("|---|---|---|---|---|---|")
    top = [r for r in ordered if r["sig"] in ("主力主导放量🔥(最强)", "游资情绪", "主力控盘")][:50]
    for r in top:
        L.append(f"| {r['code']} | {r['name']} | {r['cjb30']} | {r['precip']}% | {r['m5']/1e8:.2f} | {r['sig']} |")
    L.append("")
    L.append("## 三、主力信号专表（含低价标注 💰）\n")
    L.append("")
    main_force = [r for r in results if r["sig"] in ("主力主导放量🔥(最强)", "主力偏强放量", "主力控盘")]
    main_force.sort(key=lambda r: -r["precip"])
    L.append("| 代码 | 名称 | 价格(元) | 信号类型 | CJB30 | 沉淀率 | 5D主力净流(亿) | 低价池 |")
    L.append("|---|---|:---:|---|---|---|---|")
    for r in main_force:
        lp = "💰" if r.get("price", 999) < 10 else ""
        price_str = f"{r['price']:.2f}" if r.get("price", 0) else "N/A"
        L.append(f"| {r['code']} | {r['name']} | {price_str} | {r['sig']} | {r['cjb30']} | {r['precip']}% | {r['m5']/1e8:.2f} | {lp} |")
    L.append("")
    L.append("> 💰 = 股价<10元，适合做低价股池跟踪\n")
    L.append("")
    L.append("## 四、信号释义\n")
    L.append("- 主力主导放量🔥(最强)：放量且高沉淀，主力建仓特征，优先关注（四号是最强信号）")
    L.append("- 游资情绪：放量但低沉淀，情绪驱动，需结合技术确认")
    L.append("- 主力控盘：缩量高沉淀，筹码锁定，观察突破")
    L.append("- 数据由 GitHub Actions 自动扫描生成，回传 ima 知识库")
    L.append("")
    L.append("> 📌 资金行为四态（黑石SUPER_CAPITAL三维启发）：抢筹=超大单+放量（最强）/ 进场=今日净流转正 / 控盘=缩量高沉淀 / 观望；与双维定性互补——定性看放量缩量，四态看资金行为阶段\n")
    open("panhou_lianghua.md", "w", encoding="utf-8").write("\n".join(L))


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "all_mainboard.csv"
    workers = int(os.environ.get("SCAN_WORKERS", "6"))
    rows = list(csv.DictReader(open(inp, encoding="utf-8-sig")))
    stocks = [(r["code"], r["name"]) for r in rows]
    print(f"[INFO] total stocks={len(stocks)} workers={workers}")
    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process, s): s for s in stocks}
        for f in as_completed(futs):
            r = f.result()
            done += 1
            if r and "error" not in r and r.get("sig"):
                results.append(r)
            if done % 200 == 0:
                print(f"[PROGRESS] {done}/{len(stocks)} ok={len(results)}")
    with open("panhou_lianghua.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "price", "cjb30", "b30v100", "veab",
                                          "precip", "m5", "m10", "m20", "mainflow", "jumbo", "small",
                                          "vol", "lv", "sig", "phase", "mode", "matching"])
        w.writeheader()
        for r in results:
            w.writerow(r)
    dist = Counter(r["sig"] for r in results)
    print("[DIST]", dict(dist))
    gen_report(results, dist, time.strftime("%Y-%m-%d"))
    print(f"[OK] scanned={len(results)} -> panhou_lianghua.csv + panhou_lianghua.md")


if __name__ == "__main__":
    main()
