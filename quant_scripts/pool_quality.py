#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pool_quality.py —— 体系「所有股池」表现回测/评估（2026-09-23）

口径：取各池**当前标的**，回测其已实现的 5/10/20/60 日收益（等权），
      并与同期基准（全部池标的均值=市场代理）对比 → 衡量"该池近期选股质量"。
说明：多数池只保存 latest 快照（无历史信号序列），故无法做严格的历史信号回测；
      可做严格回测的是有信号历史的池（王者倍量柱 wangzhe_signals.csv）。
用法：python3 pool_quality.py [--json outputs/pool_quality.json]
"""
import os, re, json, subprocess, argparse
from concurrent.futures import ThreadPoolExecutor

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
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
HOLDS = [5, 10, 20, 60]


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
    pools = {}
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
            codes = sorted(c for c in codes if c)
            if codes:
                pools[pool] = codes
        except Exception as e:
            print(f"[WARN] {path}: {e}")
    return pools


def fetch_batch(batch, limit=70):
    try:
        r = subprocess.run(WESTOCK + ["kline", ",".join(batch), "--period", "day", "--limit", str(limit)],
                           capture_output=True, text=True, timeout=300)
        txt = r.stdout or ""
    except Exception:
        return {}
    out = {}
    for ln in txt.splitlines():
        if not ln.strip().startswith("|"):
            continue
        p = [x.strip() for x in ln.strip().strip("|").split("|")]
        if re.match(r"^(sh|sz)\d{6}$", p[0]) and len(p) >= 7:
            try:
                out.setdefault(p[0], []).append((p[1], float(p[3])))     # (date, close=last)
            except ValueError:
                pass
        elif len(batch) == 1 and re.match(r"^\d{4}-\d{2}-\d{2}$", p[0]):
            try:
                out.setdefault(batch[0], []).append((p[0], float(p[2])))
            except (ValueError, IndexError):
                pass
    for c in out:
        out[c].sort(key=lambda x: x[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="outputs/pool_quality.json")
    a = ap.parse_args()
    pools = collect()
    allc = sorted({c for v in pools.values() for c in v})
    print(f"股池数 {len(pools)} | 标的（去重）{len(allc)}", flush=True)
    kline = {}
    batches = [allc[i:i + 40] for i in range(0, len(allc), 40)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, res in enumerate(ex.map(fetch_batch, batches)):
            kline.update(res)
            print(f"  批次 {i+1}/{len(batches)} 累计 {len(kline)}", flush=True)

    def ret(code, h):
        b = kline.get(code)
        if not b or len(b) <= h:
            return None
        c0, c1 = b[-1 - h][1], b[-1][1]
        return (c1 / c0 - 1) * 100 if c0 > 0 else None

    # 市场代理：所有标的等权
    mkt = {h: [r for c in allc if (r := ret(c, h)) is not None] for h in HOLDS}
    mkt_mean = {h: (sum(v) / len(v) if v else 0) for h, v in mkt.items()}

    res = {}
    print(f"\n{'池':<10}{'数量':>5}", "".join(f"{str(h)+'日':>10}" for h in HOLDS), f"{'20日超额':>10}")
    for pool, codes in sorted(pools.items()):
        row = {"n": len(codes)}
        line = f"{pool:<10}{len(codes):>5}"
        for h in HOLDS:
            vals = [r for c in codes if (r := ret(c, h)) is not None]
            v = round(sum(vals) / len(vals), 2) if vals else None
            row[f"r{h}"] = v
            line += f"{(str(v)+'%') if v is not None else '—':>10}"
        ex20 = (row["r20"] - mkt_mean[20]) if row.get("r20") is not None else None
        row["ex20"] = round(ex20, 2) if ex20 is not None else None
        line += f"{(str(row['ex20'])+'%') if row['ex20'] is not None else '—':>10}"
        print(line, flush=True)
        res[pool] = row
    print(f"\n{'市场代理':<10}{len(allc):>5}" + "".join(f"{(str(round(mkt_mean[h],2))+'%'):>10}" for h in HOLDS))

    os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
    json.dump({"date": __import__("time").strftime("%Y-%m-%d"), "pools": res,
               "market_proxy": {f"r{h}": round(mkt_mean[h], 2) for h in HOLDS}},
              open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✅ {a.json}")


if __name__ == "__main__":
    main()
