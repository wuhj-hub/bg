# -*- coding: utf-8 -*-
"""全市场（沪深主板）日线抓取 → data_full.json
格式: {code: [[date, open, close, high, low], ...]}（降序，btframework 会自动修正）
"""
import os, re, json, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed

CSV = "all_mainboard.csv"
OUT = "data/bt_full.json"
LIMIT = 800
BATCH = 80
WORKERS = 4
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3", "kline"]

prefixes = ("600", "601", "603", "605", "000", "001", "002", "003")

codes = []
for ln in open(CSV, encoding="utf-8-sig"):
    p = ln.strip().split(",")
    if len(p) >= 1 and re.match(r"^\d{6}$", p[0].strip()) and p[0].strip().startswith(prefixes):
        c = p[0].strip()
        codes.append(("sh" if c.startswith("6") else "sz") + c)
print(f"主板股票数: {len(codes)}", flush=True)


def parse(text):
    res = {}
    cur = None
    for ln in text.splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not cells:
            continue
        if re.match(r"^(sh|sz)\d{6}$", cells[0]):
            cur = cells[0]
            vals = cells[1:]
        else:
            if cells[0] in ("date",) or set(cells[0]) <= set("-"):
                continue
            vals = cells
        if cur is None or len(vals) < 5:
            continue
        d, o, c, h, l = vals[0], vals[1], vals[2], vals[3], vals[4]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            continue
        try:
            res.setdefault(cur, []).append([d, float(o), float(c), float(h), float(l)])
        except ValueError:
            continue
    return res


def fetch(batch):
    for attempt in range(3):
        try:
            r = subprocess.run(WESTOCK + [",".join(batch), "--period", "day", "--limit", str(LIMIT)],
                               capture_output=True, text=True, timeout=240)
            out = r.stdout
            if out and ("|" in out):
                return parse(out)
        except Exception:
            pass
        time.sleep(2)
    return {}


data = {}
batches = [codes[i:i + BATCH] for i in range(0, len(codes), BATCH)]
t0 = time.time()
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = {ex.submit(fetch, b): i for i, b in enumerate(batches)}
    done = 0
    for fut in as_completed(futs):
        d = fut.result()
        data.update(d)
        done += 1
        if done % 5 == 0 or done == len(batches):
            print(f"进度 {done}/{len(batches)} | 已收 {len(data)} 只 | {time.time()-t0:.0f}s", flush=True)

json.dump(data, open(OUT, "w"), ensure_ascii=False)
print(f"完成: {len(data)} 只 → {OUT} | 用时 {time.time()-t0:.0f}s")
