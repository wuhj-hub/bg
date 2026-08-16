#!/usr/bin/env python3
"""
kaipan_8.py —— 开盘八法·强形态扫描与突破预警
====================================================
9:45 后运行：对候选池（妖股/才哥/一统天下/自选）判定开盘八法形态，
筛选偏多强形态股票，给出当日突破预警位。

形态判定（三时段比较法）:
  第1盘 9:30-9:35 收盘 vs 昨收 | 第2盘 9:35-9:40 vs 第1盘 | 第3盘 9:40-9:45 vs 第2盘
  涨涨涨=三高盘(最强) | 跌涨涨=低接买盘(强) | 跌跌涨=止跌反弹(中)
  涨涨跌=强中拉回(观察) | 跌涨跌=多空胶着(中性) | 涨跌涨=短兵相接(观望)
  涨跌跌=上档卖压(偏空) | 跌跌跌=三低盘(最弱)

强形态优先级: 三高盘 > 低接买盘 > 止跌反弹 > 强中拉回

用法: python3 kaipan_8.py [--pool 自定义池txt] [--monitor 突破监控(默认关)]
输出: outputs/开盘强形态_{date}.md + 突破预警(PushPlus)
====================================================
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BJ = timezone(timedelta(hours=8))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
WORKERS = 3

def cli(cmd, timeout=60):
    full = WESTOCK + cmd.split()
    for attempt in range(3):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            if r.stdout.strip() and "执行失败" not in r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(1.5)
    return ""

def load_pool():
    """合并多个股池 txt → {code: name}"""
    pool = {}
    paths = ["/sandbox/workspace/yao_pool.txt", "/sandbox/workspace/caige_pool.txt",
             "/sandbox/workspace/yitong_pool.txt", "/sandbox/workspace/holdings.txt"]
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for ln in f:
                s = ln.split("#")[0].strip()
                m = re.match(r"^(sh|sz)?(\d{6})$", s)
                if m:
                    code = (m.group(1) or ("sh" if m.group(2).startswith("6") else "sz")) + m.group(2)
                    name = ln.split("#")[-1].strip() if "#" in ln else ""
                    pool[code] = name
    return pool

def fetch_prev_close(code):
    """批量拉昨收（day kline limit 2 最新两根）"""
    md = cli(f"kline {code} --period day --limit 2 --fq qfq")
    rows = []
    has_symbol = "| symbol |" in md
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        try:
            if has_symbol:
                if parts[0] in ("symbol", "---"):
                    continue
                rows.append((parts[1], float(parts[3])))
            else:
                if not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                    continue
                rows.append((parts[0], float(parts[2])))
        except (ValueError, IndexError):
            continue
    rows.sort()
    return rows[-2][1] if len(rows) >= 2 else None  # 倒数第二根=昨收

def fetch_minute(code):
    """当日分时 → [{time, price}]"""
    md = cli(f"minute {code}")
    rows = []
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 3 and re.match(r"\d{4}", parts[1]):
            try:
                rows.append({"time": parts[1], "price": float(parts[2])})
            except ValueError:
                continue
    return rows

def judge_8(rows, prev_close):
    """三盘判定 → (形态名, 三盘状态, 第3盘高点/低点)"""
    if len(rows) < 16 or not prev_close:
        return None
    # 9:30-9:35, 9:35-9:40, 9:40-9:45 三段（分钟数据 0930-0944）
    seg = {"1": [], "2": [], "3": []}
    for r in rows:
        t = r["time"]
        if t < "0935":
            seg["1"].append(r["price"])
        elif t < "0940":
            seg["2"].append(r["price"])
        elif t < "0945":
            seg["3"].append(r["price"])
    if not (seg["1"] and seg["2"] and seg["3"]):
        return None
    c1, c2, c3 = seg["1"][-1], seg["2"][-1], seg["3"][-1]
    up1 = c1 > prev_close
    up2 = c2 > c1
    up3 = c3 > c2
    pattern = f"{'涨' if up1 else '跌'}{'涨' if up2 else '跌'}{'涨' if up3 else '跌'}"
    names = {"涨涨涨": "三高盘", "涨涨跌": "强中拉回", "涨跌跌": "上档卖压",
             "跌涨涨": "低接买盘", "跌跌涨": "止跌反弹", "跌跌跌": "三低盘",
             "跌涨跌": "多空胶着", "涨跌涨": "短兵相接"}
    strength = {"三高盘": 5, "低接买盘": 4, "止跌反弹": 3, "强中拉回": 2,
                "多空胶着": 0, "短兵相接": 0, "上档卖压": -3, "三低盘": -5}
    h3 = max(seg["3"]); l3 = min(seg["3"])
    h1 = max(seg["1"]); l1 = min(seg["1"])
    return {"pattern": names[pattern], "code3": f"{up1}{up2}{up3}",
            "h3": h3, "l3": l3, "h1": h1, "l1": l1,
            "strength": strength[names[pattern]], "prev_close": prev_close,
            "c3": c3}

def analyze(code, name, prev_close_map):
    prev = prev_close_map.get(code)
    if prev is None:
        prev = fetch_prev_close(code)
    rows = fetch_minute(code)
    if len(rows) < 16 or not prev:
        return None
    r = judge_8(rows, prev)
    if not r:
        return None
    return {"code": code, "name": name, "price": rows[-1]["price"], **r}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", action="store_true", help="突破监控模式（循环检查）")
    ap.add_argument("--pool-file", default="")
    args = ap.parse_args()
    date_str = datetime.now(BJ).strftime("%Y-%m-%d")
    t0 = time.time()

    pool = load_pool()
    if args.pool_file and os.path.exists(args.pool_file):
        with open(args.pool_file, encoding="utf-8") as f:
            for ln in f:
                s = ln.split("#")[0].strip()
                m = re.match(r"^(sh|sz)?(\d{6})$", s)
                if m:
                    code = (m.group(1) or ("sh" if m.group(2).startswith("6") else "sz")) + m.group(2)
                    pool[code] = ln.split("#")[-1].strip() if "#" in ln else ""
    print(f"[INFO] {date_str} 开盘八法扫描: 候选池 {len(pool)} 只", flush=True)

    # Step0: 批量昨收（并发）
    codes = list(pool.keys())
    prev_close_map = {}
    print("[INFO] 拉取昨收...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_prev_close, c): c for c in codes}
        for f in as_completed(futs):
            v = f.result()
            if v:
                prev_close_map[futs[f]] = v
    print(f"  昨收完成 {len(prev_close_map)}/{len(codes)}，耗时 {time.time()-t0:.0f}s", flush=True)

    # Step1: 分时判定（并发）
    print("[INFO] 分时形态判定...", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(analyze, c, pool.get(c, ""), prev_close_map): c for c in codes}
        for f in as_completed(futs):
            r = f.result()
            if r:
                results.append(r)
    results.sort(key=lambda r: -r["strength"])
    elapsed = time.time() - t0
    print(f"[INFO] 判定完成 {len(results)} 只，总耗时 {elapsed:.0f}s（{elapsed/len(results):.1f}s/只）", flush=True)

    # Step2: 输出
    strong = [r for r in results if r["strength"] >= 3]
    watch = [r for r in results if r["strength"] == 2]
    weak = [r for r in results if r["strength"] < 0]
    os.makedirs("/sandbox/workspace/outputs", exist_ok=True)
    md = [f"# 🌅 开盘八法·强形态扫描 {date_str}\n",
          f"**候选**: {len(pool)} | **有效判定**: {len(results)} | **耗时**: {elapsed:.0f}s\n"]
    md.append(f"\n## 🔥 强形态（{len(strong)}只）→ 突破预警位 = 9:45高点\n")
    if strong:
        md.append("| 代码 | 名称 | 形态 | 现价 | 9:45高 | 9:45低 | 预警位 |")
        md.append("|------|------|------|------|--------|--------|--------|")
        for r in strong:
            md.append(f"| {r['code']} | {r['name']} | **{r['pattern']}** | {r['price']:.2f} | {r['h3']:.2f} | {r['l3']:.2f} | **{r['h3']:.2f}** |")
    else:
        md.append("📭 无强形态")
    md.append(f"\n## 👀 观察（{len(watch)}只）\n")
    for r in watch:
        md.append(f"- {r['code']} {r['name']} {r['pattern']} 现价{r['price']:.2f}")
    md.append(f"\n## ⚠️ 偏空（{len(weak)}只）\n")
    for r in weak[:10]:
        md.append(f"- {r['code']} {r['name']} {r['pattern']}")
    report = "\n".join(md)
    path = f"/sandbox/workspace/outputs/开盘强形态_{date_str}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n[OK] 报告: {path}")

    # 突破预警位 JSON（供监控）
    with open(f"/sandbox/workspace/outputs/开盘强形态_{date_str}.json", "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "elapsed": elapsed, "strong": strong}, f, ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
