#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_mainboard.py —— 生成沪深主板股票清单 all_mainboard.csv

数据源：腾讯财经 qt.gtimg.cn
  策略：遍历主板代码段（沪 600000-605999 / 深 000001-003999），
        批量向 qt.gtimg.cn 查询；不存在的代码腾讯直接不返回该行，
        故响应里出现的就是有效主板，天然无空号噪声。
  优势：腾讯 gtimg 云 IP 不受东方财富反爬限流影响（沙箱/runner 均可用）。

筛选：剔除 ST/*ST、退市（名称含"退"）；主板范围由代码段天然保证
      （沪 60* / 深 000/001/002/003，自动排除 688/300/301/8/4 等）。

输出：all_mainboard.csv  (列: code,name)   code 为纯数字（如 603669）
      与 full_market_dualdim.py 的 to_westock_code 转换契约一致。

2026-10-16：新增 --universe 支持（修复 quant_report「创业板/科创四维补充通道」静默失效——
  该通道用 `--universe chinext_kcb` 调用本脚本，但旧版 main() 不解析任何参数 →
  参数被静默忽略 → all_chinext_kcb.csv 从未生成 → 下游 if [ -f ] 分支跳过（自 2026-08-11 起）。
  现支持 universe=mainboard(默认，向后兼容) / chinext_kcb(创业板 300/301 + 科创 688/689)。

调试：设 GM_MAX=N 仅遍历前 N 个候选（沙箱小测用），不设则全量。
"""

import argparse
import os
import re
import sys
import time
import csv
import urllib.request

GTIMG = "https://qt.gtimg.cn/q="
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com"}
BATCH = 50


def gen_candidates(universe="mainboard"):
    """生成候选代码（带 sh/sz 前缀）。universe: mainboard(默认) / chinext_kcb。"""
    codes = []
    if universe == "chinext_kcb":
        for i in range(300000, 302000):      # 创业板 300/301*
            codes.append("sz%06d" % i)
        for i in range(688000, 690000):      # 科创板 688/689*
            codes.append("sh%06d" % i)
    else:                                     # 沪深主板（默认）
        for i in range(600000, 606000):      # 沪市主板 600/601/603/605*
            codes.append("sh%06d" % i)
        for i in range(1, 4000):             # 深市主板 000/001/002/003*
            codes.append("sz%06d" % i)
    return codes


def fetch_batch(batch):
    """带重试的批量查询（2026-08-26：qt.gtimg.cn 限流防护）"""
    url = GTIMG + ",".join(batch)
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("gbk", "replace")
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def parse(raw):
    """解析 qt.gtimg.cn 批量响应，返回 [(wcode, name), ...]。（本地回退实现）"""
    found = []
    for line in raw.split(";"):
        line = line.strip()
        if not line.startswith("v_"):
            continue
        m = re.match(r'v_(\w+)="([^"]*)"', line)
        if not m:
            continue
        wcode = m.group(1)                    # sh600000
        parts = m.group(2).split("~")
        if len(parts) < 3:
            continue
        name = parts[1].strip()
        if not name:
            continue
        if "ST" in name.upper():              # 剔除 ST / *ST
            continue
        if "退" in name:                      # 剔除退市股
            continue
        found.append((wcode, name))
    return found


def fetch_names_batch(batch):
    """2026-10-15：优先统一取数层 fetch.ext_gtimg（同源 qt.gtimg.cn，带重试），失败回退本地。
    返回 [(wcode, name), ...]（已剔除 ST/*ST/退市）。"""
    try:
        import sys as _sys
        _root = os.path.dirname(os.path.abspath(__file__))
        for _p in (_root, os.path.join(_root, "quant_scripts")):
            if _p not in _sys.path:
                _sys.path.insert(0, _p)
        from fetch import ext_gtimg as _eg
        out = []
        for w, r in _eg(batch, batch=BATCH).items():
            nm = (r.get("name") or "").strip()
            if not nm or "ST" in nm.upper() or "退" in nm:
                continue
            out.append((w, nm))
        return out
    except Exception:
        return parse(fetch_batch(batch))


def main():
    ap = argparse.ArgumentParser(description="生成股票清单（沪深主板 / 创业板+科创）")
    ap.add_argument("--universe", default="mainboard",
                    choices=["mainboard", "chinext_kcb"],
                    help="股票池：mainboard(默认) / chinext_kcb(创业板300/301 + 科创688/689)")
    ap.add_argument("--out", default="", help="输出 CSV 路径（默认按 universe 命名）")
    a = ap.parse_args()

    out_file = a.out or ("all_chinext_kcb.csv" if a.universe == "chinext_kcb"
                         else "all_mainboard.csv")
    codes = gen_candidates(a.universe)
    cap = os.environ.get("GM_MAX")
    if cap and cap.isdigit():
        codes = codes[:int(cap)]
        print(f"[INFO] GM_MAX={cap}, testing subset", file=sys.stderr)
    out = {}
    n = len(codes)
    for i in range(0, n, BATCH):
        batch = codes[i:i + BATCH]
        try:
            for wcode, name in fetch_names_batch(batch):
                out[wcode[2:]] = name         # 存纯数字 code
        except Exception as e:
            print(f"[WARN] batch {i} failed: {e}", file=sys.stderr)
        time.sleep(0.15)                      # 限速防限流（2026-08-26）
        if (i // BATCH) % 20 == 0:
            print(f"[INFO] progress {i}/{n}, found={len(out)}", file=sys.stderr)
    if len(out) < 100:
        print(f"[ERR] {a.universe} count too small ({len(out)}), abort", file=sys.stderr)
        sys.exit(1)
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name"])
        for c in sorted(out.keys()):
            w.writerow([c, out[c]])
    print(f"[OK] {a.universe} count={len(out)} -> {out_file}")


if __name__ == "__main__":
    main()
