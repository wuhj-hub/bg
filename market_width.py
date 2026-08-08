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
    """解析批量kline输出：{code: [(date, close), ...] 按日期升序}"""
    out = {}
    cur = None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 4 or parts[0] == "symbol" or "---" in parts[0]:
            continue
        if re.match(r"^(sh|sz|bj)\d{6}$", parts[0]):
            cur = parts[0]
            out.setdefault(cur, []).append((parts[1], float(parts[3])))  # date, last(close)
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
    for i in range(0, total, batch):
        chunk = rows[i:i + batch]
        codes = [("sh" if c["code"].startswith("60") else "sz") + c["code"] for c in chunk]
        txt = run(["kline", ",".join(codes), "--period", "day", "--limit", "2"])
        data = parse_batch(txt)
        for c, r_ in zip(chunk, codes):
            kl = data.get(r_, [])
            if len(kl) >= 2:
                # ⚠️ westock批量输出date降序（最新在前）：kl[0]=最新, kl[1]=前一日
                d_last, c_last = kl[0]
                d_prev, c_prev = kl[1]
                if c_prev and c_prev > 0:
                    pct = (c_last - c_prev) / c_prev * 100
                    chg.append((c["code"], c["name"], round(pct, 2)))
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
    }
    json_path = os.path.join(OUT_DIR, "market_width_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))
    print(f"[OK] {md_path}")
    print(f"[OK] {json_path}")
    print(f"宽度分={score} 等级={level} 上涨{len(up)} 强势{len(strong)} 涨停{len(lu)} 弱势{len(weak)} 跌停{len(ld)}")


if __name__ == "__main__":
    main()
