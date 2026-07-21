#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_mainboard.py —— 生成沪深主板股票清单 all_mainboard.csv

运行环境：GitHub Actions runner（需外网访问东方财富行情接口）。
沙箱环境东方财富接口被拦截，本地无法运行，仅在 GitHub runner 执行。

筛选规则（与盘前/复盘体系一致）：
  剔除 科创板(688) / 创业板(300,301) / 北交所(8,4,43,83,87) / ST
  保留 沪市主板(60*) + 深市主板(000/001/002/003*)

输出：all_mainboard.csv  (列: code,name)
"""
import json
import time
import csv
import sys
import urllib.parse
import urllib.request

EASTMONEY_API = "https://push2.eastmoney.com/api/qt/clist/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://quote.eastmoney.com/",
}


def fetch_once(fs, pn, ps=1000):
    """单次拉取东方财富股票列表。fs: 市场过滤器。"""
    params = {
        "pn": pn, "pz": ps, "po": "1", "np": "1", "fltt": "2",
        "invt": "2", "fid": "f3", "fs": fs,
        "fields": "f12,f14",
        "ut": "fa5fd1943c7fad33f6da12dfa3a9e7b2",
    }
    url = EASTMONEY_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_page(fs, pn, retries=6):
    """带重试的翻页拉取；全部重试失败返回 None。"""
    last = None
    for i in range(retries):
        try:
            return fetch_once(fs, pn)
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    print(f"[WARN] fetch {fs} pn={pn} failed after {retries} retries: {last}")
    return None


def is_mainboard(code: str, name: str) -> bool:
    """应用沪深主板过滤规则。"""
    if not code or not name:
        return False
    if "ST" in name.upper() or "*ST" in name.upper():
        return False
    # 排除科创板 / 创业板 / 北交所
    if code.startswith("688"):
        return False
    if code.startswith(("300", "301")):
        return False
    if code.startswith(("8", "4", "43", "83", "87")):
        return False
    # 主板：沪市 60*；深市 000/001/002/003*
    if code.startswith("60"):
        return True
    if code.startswith(("000", "001", "002", "003")):
        return True
    return False


def main():
    fs_list = ["m:0+t:6", "m:0+t:80"]  # 沪市, 深市
    codes = []
    for fs in fs_list:
        pn = 1
        while True:
            d = fetch_page(fs, pn)
            if d is None:
                # 该市场拉取失败，跳过（不影响另一市场）
                break
            arr = (d.get("data") or {}).get("diff") or []
            if not arr:
                break
            for it in arr:
                code = (it.get("f12") or "").strip()
                name = (it.get("f14") or "").strip()
                if is_mainboard(code, name):
                    codes.append((code, name))
            pn += 1
            time.sleep(0.3)
    # 去重（沪/深理论上不重叠，仍保险）
    seen = set()
    uniq = []
    for c in codes:
        if c[0] in seen:
            continue
        seen.add(c[0])
        uniq.append(c)
    if len(uniq) < 50:
        # 拉取明显异常（如网络故障只拿到零星数据），避免空扫/误扫
        print(f"[ERR] mainboard count too small ({len(uniq)}), abort to avoid empty scan")
        sys.exit(1)
    with open("all_mainboard.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name"])
        for c in uniq:
            w.writerow(c)
    print(f"[OK] mainboard count={len(uniq)} -> all_mainboard.csv")


if __name__ == "__main__":
    main()
