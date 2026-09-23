#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财板块成分拉取。
⚠️ 2026-09-16 更正：**push2delay.eastmoney.com 在沙箱也可达**（此前认知「东财在沙箱全不可达」已过时）；
   而 push2.eastmoney.com 主域已全面 502 → 脚本改为多端点回退（push2delay 优先）。
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
from concurrent.futures import ThreadPoolExecutor, as_completed

# ⚠️ 2026-09-16：8 并发招致东财限流（实测覆盖 64 只 < 串行版 302 只）→ 降到 3 并保留请求间隔
WORKERS = 3

# ⚠️ 2026-09-16 关键修复：push2.eastmoney.com 已全面 502（主域挂），
#    探测发现 push2delay.eastmoney.com 完全正常（概念 total=504、成分 total=42）。
#    → 改为多端点依次回退，避免单域故障导致产物恒为空壳。
HOSTS = [
    "https://push2delay.eastmoney.com",
    "https://push2.eastmoney.com",
    "https://push2his.eastmoney.com",
]
API_PATH = "/api/qt/clist/get"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


def _try_host(host, params, retries=2):
    url = host + API_PATH + "?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            if d and d.get("data") and d["data"].get("diff"):
                return d["data"]
            return None                      # 该域可达但无数据
        except Exception:
            time.sleep(1.0 * (i + 1))
    return None


def get(params, retries=3):
    """多端点回退：任一域可用即返回"""
    for host in HOSTS:
        r = _try_host(host, params, retries=2)
        if r:
            return r
    return None


def fetch_board_list(fs, pz=100):
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
        # ⚠️ 2026-09-16 修复：原判断 `len(diff) < pz` 在东财单页上限(100) < pz(200) 时恒为真
        #    → 永远只取第 1 页（行业/概念各只 100 个）。改为按 total 翻页、以空页为终止。
        if not diff or pn * pz >= total:
            break
        pn += 1
        time.sleep(0.2)
    return out


def fetch_board_stocks(board_code, pz=100):
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
        # ⚠️ 2026-09-16 同上：去掉 `len(diff) < pz` 的伪终止条件
        if not diff or pn * pz >= total:
            break
        pn += 1
        time.sleep(0.15)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/sector_component_em.json")
    ap.add_argument("--concepts-only", action="store_true", help="只拉概念板块(更快)")
    ap.add_argument("--budget-sec", type=int, default=2000,
                    help="时间预算秒数；到点优雅保存退出(默认2000≈33分，避 workflow 40min 强杀)")
    ap.add_argument("--workers", type=int, default=WORKERS, help="并发数(默认3)")
    ap.add_argument("--force", action="store_true", help="忽略旧缓存，全量重拉")
    args = ap.parse_args()

    groups = []
    if not args.concepts_only:
        hy = fetch_board_list("m:90+t:2+f:!50")
        groups.append(("行业", hy))
        print(f"行业板块: {len(hy)} 个", flush=True)
    gn = fetch_board_list("m:90+t:3+f:!50")
    groups.append(("概念", gn))
    print(f"概念板块: {len(gn)} 个", flush=True)

    # ⚠️ 2026-09-15 改造：串行版 486 板块 × (请求+0.1s sleep) >20min 会被 timeout 砍掉
    #    （当日仅跑到 302 只就被杀）。改为 8 并发，各 worker 返回结果后主线程合并。
    tasks = [(bname, bcode) for gname, boards in groups for bcode, bname in boards if bcode.startswith("BK")]
    total_boards = len(tasks)

    # ── 断点续传：复用旧缓存，只拉缺失板块（板块成分变化很慢）──────────────
    sectors, code_sector, code_name = {}, {}, {}
    if not args.force and os.path.exists(args.out):
        try:
            old = json.load(open(args.out, encoding="utf-8"))
            sectors = old.get("sectors", {}) or {}
            code_name = old.get("code_name", {}) or {}
            code_sector = old.get("code_sector", {}) or {}
            print(f"续传：复用旧缓存 {len(sectors)} 板块 / {len(code_name)} 只", flush=True)
        except Exception as e:
            print(f"[WARN] 旧缓存不可用({e})，改为全量拉取", flush=True)
    todo = [(bn, bc) for bn, bc in tasks if bn not in sectors]
    print(f"共 {total_boards} 板块（待拉 {len(todo)}，{args.workers} 并发，预算 {args.budget_sec}s）", flush=True)

    def _one(item):
        bname, bcode = item
        try:
            stocks = fetch_board_stocks(bcode)
        except Exception:
            stocks = []
        time.sleep(0.06)          # 请求间隔，降低被限流概率
        codes = [sc for sc, sn in stocks if sc and sn]
        names = {sc: sn for sc, sn in stocks if sc and sn}
        return bname, codes, names

    def _merge(bname, codes, names):
        sectors[bname] = codes
        for sc in codes:
            lst = code_sector.setdefault(sc, [])
            if bname not in lst:
                lst.append(bname)
        for sc, sn in names.items():
            code_name.setdefault(sc, sn)

    def _save():
        data = {"date": time.strftime("%Y-%m-%d"), "sectors": sectors, "code_sector": code_sector,
                "code_name": code_name, "source": "eastmoney",
                "covered_boards": len(sectors), "total_boards": total_boards,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    t0 = time.time()
    done = 0
    ex = ThreadPoolExecutor(max_workers=args.workers)
    futs = {ex.submit(_one, t): t for t in todo}
    stopped = False
    try:
        for fu in as_completed(futs):
            try:
                bname, codes, names = fu.result()
            except Exception:
                continue
            _merge(bname, codes, names)
            done += 1
            if done % 50 == 0:
                print(f"  进度 +{done} | 累计 {len(sectors)}/{total_boards} 板块 | {len(code_name)} 只", flush=True)
                _save()                       # 周期性落盘 → 即便被强杀也不丢已拉部分
            if time.time() - t0 > args.budget_sec:
                stopped = True
                print(f"⏱ 达到时间预算 {args.budget_sec}s → 提前保存（剩余 {len(todo) - done} 板块下次续拉）", flush=True)
                break
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    _save()
    avg = sum(len(v) for v in code_sector.values()) / max(len(code_sector), 1)
    print(f"✅ {args.out}: {len(sectors)}/{total_boards} 板块 | {len(code_name)} 只 | 平均 {avg:.1f} 题材/股"
          + ("（未拉完，下次自动续传）" if stopped or len(sectors) < total_boards else ""))
    # 次新覆盖抽检（新浪漏的连板股）
    for c in ("003005", "601086", "605577", "603207"):
        print(f"  抽检 {c} {code_name.get(c,'?' )}: {code_sector.get(c, [])[:6]}")


if __name__ == "__main__":
    main()
