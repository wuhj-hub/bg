#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财板块成分拉取（GitHub runner 执行——沙箱 push2.eastmoney.com 被拦截）。
产出 code→行业/概念板块映射 + code→名称（覆盖全市场含次新，补新浪源 71% 短板）。
输出: outputs/sector_component_em.json
  {"date":..., "sectors": {"板块名":[codes]}, "code_sector": {"code":[板块名...]}, "code_name": {...}}
用法: python3 runner_fetch_em_sectors.py [--out outputs/sector_component_em.json]
"""
import argparse
import json
import os
import time
import urllib.request
import urllib.parse

API = "https://push2.eastmoney.com/api/qt/clist/get"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


def get(params, retries=3):
    url = API + "?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            if d and d.get("data") and d["data"].get("diff"):
                return d["data"]
            return None
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def fetch_board_list(fs, pz=200):
    """拉板块列表, 返回 [(code, name)]"""
    out = []
    pn = 1
    while True:
        d = get({"pn": pn, "pz": pz, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                 "fid": "f3", "fs": fs, "fields": "f12,f14"})
        if not d:
            break
        diff = d.get("diff", [])
        if not diff:
            break
        for item in diff:
            out.append((item.get("f12", ""), item.get("f14", "")))
        total = d.get("total", 0)
        if pn * pz >= total or len(diff) < pz:
            break
        pn += 1
        time.sleep(0.2)
    return out


def fetch_board_stocks(board_code, pz=200):
    """拉板块成分, 返回 [(code, name)]"""
    out = []
    pn = 1
    while True:
        d = get({"pn": pn, "pz": pz, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                 "fid": "f3", "fs": f"b:{board_code}+f:!50", "fields": "f12,f14"})
        if not d:
            break
        diff = d.get("diff", [])
        if not diff:
            break
        for item in diff:
            out.append((item.get("f12", ""), item.get("f14", "")))
        total = d.get("total", 0)
        if pn * pz >= total or len(diff) < pz:
            break
        pn += 1
        time.sleep(0.15)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/sector_component_em.json")
    ap.add_argument("--concepts-only", action="store_true", help="只拉概念板块(更快)")
    args = ap.parse_args()

    groups = []
    if not args.concepts_only:
        hy = fetch_board_list("m:90+t:2+f:!50")
        groups.append(("行业", hy))
        print(f"行业板块: {len(hy)} 个", flush=True)
    gn = fetch_board_list("m:90+t:3+f:!50")
    groups.append(("概念", gn))
    print(f"概念板块: {len(gn)} 个", flush=True)

    sectors = {}
    code_sector = {}
    code_name = {}
    total_boards = sum(len(g[1]) for g in groups)
    done = 0
    for gname, boards in groups:
        for bcode, bname in boards:
            if not bcode.startswith("BK"):
                continue
            stocks = fetch_board_stocks(bcode)
            codes = []
            for scode, sname in stocks:
                if scode and sname:
                    codes.append(scode)
                    code_sector.setdefault(scode, []).append(bname)
                    if scode not in code_name:
                        code_name[scode] = sname
            sectors[bname] = codes
            done += 1
            if done % 25 == 0 or done == total_boards:
                print(f"  进度 {done}/{total_boards} 板块 | 已覆盖 {len(code_name)} 只", flush=True)
            time.sleep(0.1)

    date = time.strftime("%Y-%m-%d")
    data = {"date": date, "sectors": sectors, "code_sector": code_sector, "code_name": code_name,
            "source": "eastmoney"}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    avg = sum(len(v) for v in code_sector.values()) / max(len(code_sector), 1)
    print(f"✅ {args.out}: {len(sectors)} 板块 | {len(code_name)} 只 | 平均 {avg:.1f} 题材/股")
    # 次新覆盖抽检（新浪漏的连板股）
    for c in ("003005", "601086", "605577", "603207"):
        print(f"  抽检 {c} {code_name.get(c,'?' )}: {code_sector.get(c, [])[:6]}")


if __name__ == "__main__":
    main()
