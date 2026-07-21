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

调试：设 GM_MAX=N 仅遍历前 N 个候选（沙箱小测用），不设则全量。
"""

import os
import re
import sys
import time
import csv
import urllib.request

GTIMG = "https://qt.gtimg.cn/q="
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com"}
BATCH = 50


def gen_candidates():
    """生成主板候选代码（带 sh/sz 前缀）。"""
    codes = []
    for i in range(600000, 606000):          # 沪市主板 600/601/603/605*
        codes.append("sh%06d" % i)
    for i in range(1, 4000):                 # 深市主板 000/001/002/003*
        codes.append("sz%06d" % i)
    return codes


def fetch_batch(batch):
    url = GTIMG + ",".join(batch)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("gbk", "replace")


def parse(raw):
    """解析 qt.gtimg.cn 批量响应，返回 [(wcode, name), ...]。"""
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


def main():
    codes = gen_candidates()
    cap = os.environ.get("GM_MAX")
    if cap and cap.isdigit():
        codes = codes[:int(cap)]
        print(f"[INFO] GM_MAX={cap}, testing subset", file=sys.stderr)
    out = {}
    n = len(codes)
    for i in range(0, n, BATCH):
        batch = codes[i:i + BATCH]
        try:
            for wcode, name in parse(fetch_batch(batch)):
                out[wcode[2:]] = name         # 存纯数字 code
        except Exception as e:
            print(f"[WARN] batch {i} failed: {e}", file=sys.stderr)
            time.sleep(1)
        if (i // BATCH) % 20 == 0:
            print(f"[INFO] progress {i}/{n}, found={len(out)}", file=sys.stderr)
    if len(out) < 100:
        print(f"[ERR] mainboard count too small ({len(out)}), abort", file=sys.stderr)
        sys.exit(1)
    with open("all_mainboard.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name"])
        for c in sorted(out.keys()):
            w.writerow([c, out[c]])
    print(f"[OK] mainboard count={len(out)} -> all_mainboard.csv")


if __name__ == "__main__":
    main()
