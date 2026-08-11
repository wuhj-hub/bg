#!/usr/bin/env python3
"""市场宽度指标（黑石marketChangeDist启发）——全主板涨跌家数分布→市场温度
用法: python3 market_width.py [--pool all_mainboard.csv] [--batch 100]
输出: outputs/market_width_{date}.md + market_width_latest.json（供盘前/复盘引用）
"""
import csv, json, os, re, subprocess, sys, time
from datetime import datetime

POOL = "all_mainboard.csv"
BATCH = 100
OUT_DIR = "outputs"


def run(args, timeout=120):
    for i in range(3):
        try:
            r = subprocess.run(["npx", "-y", "westock-data-skillhub@1.0.3"] + args,
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""


def parse_batch(txt):
    """解析批量kline输出：{code: [(date, close, high), ...] 按日期升序}
    ⚠️ westock批量输出date降序（最新在前），调用方自行处理"""
    out = {}
    cur = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 5 or parts[0] == "symbol" or "---" in parts[0]:
            continue
        if re.match(r"^(sh|sz|bj)\d{6}$", parts[0]):
            cur = parts[0]
            # 批量列序: symbol|date|open|last|high|low|volume|amount|exchange
            out.setdefault(cur, []).append((parts[1], float(parts[3]), float(parts[4])))
    return out


def width_score(up_pct, strong_cnt, limitup_cnt, total):
    """市场宽度分0-100：上涨占比为主 + 强势/涨停加成"""
    score = up_pct * 100
    score += min(strong_cnt * 3, 20)
    score += min(limitup_cnt * 2, 10)
    return round(min(100, score), 1)


def main():
    pool = POOL
    batch = BATCH
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--pool" and i + 1 < len(argv):
            pool = argv[i + 1]
        if a == "--batch" and i + 1 < len(argv):
            batch = int(argv[i + 1])

    rows = list(csv.DictReader(open(pool, encoding="utf-8-sig")))
    rows = [r for r in rows if "退" not in r.get("name", "")]
    total = len(rows)
    print(f"[INFO] 股票池 {total}只（已过滤退市）", flush=True)

    chg = []  # (code, name, pct)
    touched, zhaban, lianban, lianban3 = [], [], [], []  # 涨停池代理：触板/炸板/连板(≥2)/高连板(≥3)
    lianban_cnt = {}  # code -> 连续涨停天数
    for i in range(0, total, batch):
        chunk = rows[i:i + batch]
        codes = [("sh" if c["code"].startswith("60") else "sz") + c["code"] for c in chunk]
        txt = run(["kline", ",".join(codes), "--period", "day", "--limit", "10"])
        data = parse_batch(txt)
        for c, r_ in zip(chunk, codes):
            kl = data.get(r_, [])
            if len(kl) >= 2:
                # ⚠️ westock批量输出date降序（最新在前）：kl[0]=最新, kl[1]=前一日
                d_last, c_last, h_last = kl[0]
                d_prev, c_prev, _ = kl[1]
                if c_prev and c_prev > 0:
                    pct = (c_last - c_prev) / c_prev * 100
                    chg.append((c["code"], c["name"], round(pct, 2)))
                    # 涨停池代理（2026-08-10）：触板/炸板
                    limit_p = c_prev * 1.10
                    if h_last and h_last >= limit_p * 0.99:
                        touched.append(c["code"])
                        if pct < 9.8:
                            zhaban.append(c["code"])
                    # S4 连板高度（2026-08-11）：limit 10 算连续涨停天数
                    days_lb = 0
                    for i in range(len(kl) - 1):
                        _, c0, _ = kl[i]
                        _, c1, _ = kl[i + 1]
                        if c1 > 0 and (c0 - c1) / c1 * 100 >= 9.8:
                            days_lb += 1
                        else:
                            break
                    if days_lb >= 1:
                        lianban_cnt[c["code"]] = days_lb
                        if days_lb >= 2:
                            lianban.append(c["code"])
                        if days_lb >= 3:
                            lianban3.append(c["code"])
        print(f"[{i + len(chunk)}/{total}] 已处理", flush=True)

    n = len(chg)
    up = [x for x in chg if x[2] > 0]
    down = [x for x in chg if x[2] < 0]
    flat = [x for x in chg if x[2] == 0]
    strong = [x for x in chg if x[2] >= 5]
    weak = [x for x in chg if x[2] <= -5]
    lu = [x for x in chg if x[2] >= 9.8]
    ld = [x for x in chg if x[2] <= -9.8]
    up_pct = len(up) / n if n else 0
    score = width_score(up_pct, len(strong), len(lu), n)

    if score >= 70:
        # 赚钱效应强但涨少跌多 → 结构性行情（涨停潮+分化）
        level = "🔥 结构性强（涨停潮·涨少跌多分化）" if up_pct < 0.45 else "🔥 强势（普涨格局）"
    elif score >= 55:
        level = "偏强（涨多跌少）"
    elif score >= 40:
        level = "震荡（多空均衡）"
    elif score >= 25:
        level = "偏弱（跌多涨少）"
    else:
        level = "❄️ 弱势（普跌格局）"

    today = datetime.now().strftime("%Y-%m-%d")
    md = f"""# 📊 市场宽度指标 {today}

> 全主板{total}只（过滤退市），有效{n}只 | 数据源：westock批量日K（最新交易日收盘）

## 市场温度：{level}（宽度分 {score}/100）

## 涨跌家数分布
| 分类 | 家数 | 占比 |
|---|---|---|
| 上涨 | {len(up)} | {up_pct*100:.1f}% |
| 下跌 | {len(down)} | {len(down)/n*100:.1f}% |
| 平盘 | {len(flat)} | {len(flat)/n*100:.1f}% |
| 强势(≥5%) | {len(strong)} | {len(strong)/n*100:.1f}% |
| 弱势(≤-5%) | {len(weak)} | {len(weak)/n*100:.1f}% |
| 涨停(≥9.8%) | {len(lu)} | {len(lu)/n*100:.1f}% |
| 跌停(≤-9.8%) | {len(ld)} | {len(ld)/n*100:.1f}% |

## 涨幅TOP10
| 代码 | 名称 | 涨幅% |
|---|---|---|
"""
    for c, nm, p in sorted(chg, key=lambda x: -x[2])[:10]:
        md += f"| {c} | {nm} | {p} |\n"
    md += "\n## 跌幅TOP10\n| 代码 | 名称 | 跌幅% |\n|---|---|---|\n"
    for c, nm, p in sorted(chg, key=lambda x: x[2])[:10]:
        md += f"| {c} | {nm} | {p} |\n"

    # 涨停池代理（2026-08-10·无涨停池接口自算）：连板高度/炸板率
    n_touch = len(set(touched))
    n_zhaban = len(set(zhaban))
    n_lianban = len(set(lianban))
    n_lianban3 = len(set(lianban3))
    max_lb = max(lianban_cnt.values()) if lianban_cnt else 0
    zhaban_rate = round(n_zhaban / n_touch * 100, 1) if n_touch else 0.0
    md += "\n## 涨停池代理（连板/炸板·批量K线自算）\n"
    md += "| 指标 | 数值 | 解读 |\n|---|---|---|\n"
    md += f"| 触板数(盘中触及涨停) | {n_touch} | 含涨停+炸板 |\n"
    md += f"| 炸板数(触板未封) | {n_zhaban} | {n_zhaban}/{n_touch} |\n"
    md += f"| **炸板率** | **{zhaban_rate}%** | {'✅情绪健康(<20%)' if zhaban_rate < 20 else ('⚠️情绪降温(20-40%)' if zhaban_rate < 40 else '🔴退潮预警(≥40%)')} |\n"
    md += f"| 二连板数 | {n_lianban} | 连板高度代理 |\n"
    md += f"| **三连板+** | {n_lianban3} | 最高连板 **{max_lb}板** |\n"

    # R2 极端行情熔断（2026-08-11）：跌停≥100 或 宽度分<25 → 🔴熔断
    fuse = ""
    if len(ld) >= 100 or score < 25:
        fuse = "🔴 极端行情熔断（跌停{}家 或 宽度分{}）——全仓防守，暂停开仓".format(len(ld), score)
        md += f"\n## ⛔ 熔断预警\n{fuse}\n"

    # 200日成本线（猛兽派日报启发·2026-08-11）：上证近200日收盘均价 ≈ 市场成本
    cost = {}
    try:
        ctxt = run(["kline", "sh000001", "--period", "day", "--limit", "250"])
        closes = []
        for ln in ctxt.splitlines():
            s = ln.strip()
            if s.startswith("|") and re.match(r"^\|\s*2026", s):
                parts = [p.strip() for p in s.strip("|").split("|")]
                # 单只K线列序: date|open|last|high|low (last=parts[2]，与批量symbol|date|open|last不同!)
                if len(parts) >= 4 and parts[2]:
                    try:
                        closes.append(float(parts[2]))
                    except ValueError:
                        pass
        if len(closes) >= 120:  # westock单只K线约146条上限，用实际可用数据近似成本线
            closes = closes[:min(len(closes), 200)]
            cost200 = sum(closes) / len(closes)
            cur = closes[0]
            ratio = round((cur - cost200) / cost200 * 100, 1)
            ma20_cost = sum(closes[:min(20, len(closes))]) / min(20, len(closes))
            slope = "上行" if ma20_cost > cost200 * 1.01 else ("下行" if ma20_cost < cost200 * 0.99 else "走平")
            cost = {"cur": round(cur, 2), "cost200": round(cost200, 2), "ratio": ratio, "slope": slope,
                    "zone": "浮盈·牛" if ratio > 0 else "浮亏·熊(解套抛压区)",
                    "days": len(closes)}
            md += "\n## 200日成本线（长期资金浮亏视角）\n"
            md += f"| 现价 | 成本线({cost['days']}日均) | 偏离 | 斜率 | 状态 |\n|---|---|---|---|---|\n"
            md += f"| {cost['cur']} | {cost['cost200']} | {cost['ratio']:+.1f}% | {cost['slope']} | **{cost['zone']}** |\n"
            md += f"> 猛兽派启发：价格在成本线下方=长期资金浮亏，反弹至成本线附近撞解套抛压\n"
    except Exception:
        pass

    os.makedirs(OUT_DIR, exist_ok=True)
    md_path = os.path.join(OUT_DIR, f"market_width_{today}.md")
    open(md_path, "w", encoding="utf-8").write(md)

    js = {
        "date": today, "total": total, "valid": n,
        "up": len(up), "down": len(down), "flat": len(flat),
        "strong": len(strong), "weak": len(weak),
        "limitup": len(lu), "limitdown": len(ld),
        "up_pct": round(up_pct * 100, 1), "score": score, "level": level,
        "top": sorted(chg, key=lambda x: -x[2])[:10],
        # 涨停/强势完整名单（供市场风格轴判中军结构）
        "limitup_list": [{"code": c, "name": nm, "pct": p} for c, nm, p in sorted(lu, key=lambda x: -x[2])],
        "strong_list": [{"code": c, "name": nm, "pct": p} for c, nm, p in sorted(strong, key=lambda x: -x[2])],
        # 涨停池代理（连板/炸板）
        "limitup_stats": {"touched": n_touch, "zhaban": n_zhaban, "zhaban_rate": zhaban_rate,
                          "lianban": n_lianban, "lianban3": n_lianban3, "max_lianban": max_lb,
                          "lianban_list": sorted(set(lianban)),
                          "lianban3_list": sorted(set(lianban3))},
        # R2 极端熔断
        "fuse": fuse,
        # 200日成本线（猛兽派启发）
        "cost_line": cost,
    }
    json_path = os.path.join(OUT_DIR, "market_width_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))
    print(f"[OK] {md_path}")
    print(f"[OK] {json_path}")
    print(f"宽度分={score} 等级={level} 上涨{len(up)} 强势{len(strong)} 涨停{len(lu)} 弱势{len(weak)} 跌停{len(ld)} | 触板{n_touch} 炸板{n_zhaban}({zhaban_rate}%) 二连板{n_lianban}")


if __name__ == "__main__":
    main()
