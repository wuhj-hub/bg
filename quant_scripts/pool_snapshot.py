#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pool_snapshot.py —— 各股池「每日入池快照」（2026-09-23）

目的：为**未来的样本外回测**积累可追溯数据。
  现存问题：多数池只保留 latest 快照 → 无法回测（不知何时入池）。
  本脚本每日记录：
    ① outputs/pool_snapshots.jsonl —— 当日各池标的（逐日追加，一行一天）
    ② outputs/pool_entries.csv     —— 累计入池表（首次出现日 = entry_date，可算入池后收益）

用法：python3 pool_snapshot.py [--date YYYY-MM-DD]
"""
import os, re, json, csv, argparse
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))
SNAP = "outputs/pool_snapshots.jsonl"
ENTRY = "outputs/pool_entries.csv"
POOL_SOURCES = [
    ("鱼身", "quant_scripts/stock_pool.txt"),
    ("一统天下", "quant_scripts/yitong_pool.txt"),
    ("才哥", "quant_scripts/caige_pool.txt"),
    ("龙头", "quant_scripts/longtou_pool.txt"),
    ("龙头战法", "quant_scripts/dragon_pool.txt"),
    ("妖股", "quant_scripts/yao_pool.txt"),
    ("乾坤A", "outputs/qiankun_a_latest.json"),
    ("双弦", "outputs/双弦观察池_latest.json"),
    ("猛兽突破", "outputs/beast_pool_latest.json"),
    ("宁静卡位", "quant_scripts/ai_chain_pool.json"),
    ("低空经济", "quant_scripts/low_altitude_pool.json"),
    ("固态电池", "quant_scripts/solid_battery_pool.json"),
    ("商业航天", "quant_scripts/space_pool.json"),
    ("西湖RSV", "outputs/xihu_rsv_latest.json"),
]
FIELDS = ["entry_date", "pool", "code", "last_seen", "times_seen"]


def norm(c):
    c = (c or "").strip()
    if re.match(r"^(sh|sz)\d{6}$", c):
        return c
    m = re.search(r"(\d{6})", c)
    if not m:
        return ""
    d = m.group(1)
    return ("sh" if d[0] in ("6", "9") else "sz") + d


def collect():
    """→ {pool: set(codes)}"""
    out = {}
    for pool, path in POOL_SOURCES:
        if not os.path.exists(path):
            continue
        try:
            if path.endswith(".json"):
                raw = json.load(open(path, encoding="utf-8"))
                found = []

                def walk(x):
                    if isinstance(x, dict):
                        for k, v in x.items():
                            if k in ("code", "symbol", "ts_code") and isinstance(v, str):
                                found.append(v)
                            else:
                                walk(v)
                    elif isinstance(x, list):
                        for i in x:
                            walk(i)
                walk(raw)
                codes = {norm(c) for c in found}
            else:
                codes = {norm(c) for c in re.findall(r"\b(?:sh|sz)?\d{6}\b", open(path, encoding="utf-8", errors="ignore").read())}
            codes = {c for c in codes if c}
            if codes:
                out[pool] = codes
        except Exception as e:
            print(f"[WARN] {path}: {e}")
    return out


def load_entries():
    rows = {}
    if os.path.exists(ENTRY):
        try:
            for r in csv.DictReader(open(ENTRY, encoding="utf-8")):
                rows[(r["pool"], r["code"])] = r
        except Exception:
            pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(BJT).strftime("%Y-%m-%d"))
    a = ap.parse_args()
    today = a.date
    pools = collect()
    if not pools:
        print("❌ 未找到任何股池文件")
        return

    # ① 当日快照（逐日追加，去重同日）
    os.makedirs("outputs", exist_ok=True)
    snap_line = json.dumps({"date": today, "pools": {k: sorted(v) for k, v in pools.items()}}, ensure_ascii=False)
    existing = []
    if os.path.exists(SNAP):
        existing = [l for l in open(SNAP, encoding="utf-8").read().splitlines() if l.strip()]
        existing = [l for l in existing if json.loads(l).get("date") != today]      # 同日覆盖
    existing.append(snap_line)
    existing.sort(key=lambda l: json.loads(l).get("date", ""))
    open(SNAP, "w", encoding="utf-8").write("\n".join(existing) + "\n")

    # ② 累计入池表（首次出现 = entry_date）
    ent = load_entries()
    new_n, upd = 0, 0
    for pool, codes in pools.items():
        for c in sorted(codes):
            k = (pool, c)
            if k in ent:
                ent[k]["last_seen"] = today
                ent[k]["times_seen"] = str(int(ent[k].get("times_seen") or 0) + 1)
                upd += 1
            else:
                ent[k] = {"entry_date": today, "pool": pool, "code": c, "last_seen": today, "times_seen": "1"}
                new_n += 1
    with open(ENTRY, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for k in sorted(ent, key=lambda x: (ent[x]["entry_date"], x[0], x[1])):
            w.writerow({kk: ent[k].get(kk, "") for kk in FIELDS})
    print(f"✅ {today}: 池 {len(pools)} 个 | 标的 {sum(len(v) for v in pools.values())} 只 | 新增入池 {new_n} | 更新 {upd}")
    print(f"   → {SNAP}（{len(existing)} 天） | {ENTRY}（{len(ent)} 条）")


def backtest():
    """按 entry_date 算「入池后 5/10/20 日收益」→ 各池胜率/均值（数据够才出结果）"""
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    if not os.path.exists(ENTRY):
        print("❌ 无 pool_entries.csv")
        return
    rows = list(csv.DictReader(open(ENTRY, encoding="utf-8")))
    codes = sorted({r["code"] for r in rows})
    print(f"标的 {len(codes)} 只（entry_date 起算）", flush=True)
    WEST = ["npx", "-y", "westock-data-skillhub@1.0.3"]
    kline = {}

    def fb(b):
        try:
            out = subprocess.run(WEST + ["kline", ",".join(b), "--period", "day", "--limit", "120"],
                                 capture_output=True, text=True, timeout=300).stdout or ""
        except Exception:
            return {}
        d = {}
        for ln in out.splitlines():
            if not ln.strip().startswith("|"):
                continue
            p = [x.strip() for x in ln.strip().strip("|").split("|")]
            if re.match(r"^(sh|sz)\d{6}$", p[0]) and len(p) >= 7:
                try:
                    d.setdefault(p[0], []).append((p[1], float(p[3])))
                except ValueError:
                    pass
        for c in d:
            d[c].sort()
        return d

    batches = [codes[i:i + 40] for i in range(0, len(codes), 40)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(fb, batches):
            kline.update(res)

    def ret(code, entry_date, h):
        b = kline.get(code)
        if not b:
            return None
        idx = next((i for i, x in enumerate(b) if x[0] >= entry_date), None)
        if idx is None or idx + h >= len(b):
            return None
        c0, c1 = b[idx][1], b[idx + h][1]
        return (c1 / c0 - 1) * 100 if c0 > 0 else None

    agg = {}
    for r in rows:
        for h in (5, 10, 20):
            v = ret(r["code"], r["entry_date"], h)
            if v is not None:
                agg.setdefault((r["pool"], h), []).append(v)
    print(f"\n{'池':<10}{'样本':>6}{'5日':>10}{'10日':>10}{'20日':>10}")
    pools = sorted({p for p, _ in agg})
    for p in pools:
        line, n = f"{p:<10}", 0
        for h in (5, 10, 20):
            v = agg.get((p, h), [])
            if v:
                n = max(n, len(v))
                line += f"{(str(round(sum(v)/len(v),2))+'%'):>10}"
            else:
                line += f"{'—':>10}"
        print(f"{line}{'' if n else '（数据不足）'}")
    print("\n> ⚠️ 仅在 entry_date 之后有足够交易日时才有值；初期数据不足属正常。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(BJT).strftime("%Y-%m-%d"))
    ap.add_argument("--report", action="store_true", help="按入池日回测 5/10/20 日收益")
    a = ap.parse_args()
    if a.report:
        backtest()
    else:
        main()
