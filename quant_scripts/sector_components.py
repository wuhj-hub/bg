#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新浪行业板块成分拉取 → code→板块映射表（供 longtou 龙头板块归属 / hot_emotion 增强）。
数据源: money.finance.sina.com.cn (newSinaHy 板块清单 + Market_Center.getHQNodeData 成分)

输出: outputs/sector_component.json
  {
    "date": "2026-09-03",
    "sectors": {"银行业": ["600176","600184",...], ...},   # 板块 → 成分code列表
    "code_sector": {"600176": ["银行业", ...], ...},       # code → 板块列表
    "code_name": {"600176": "中国巨石", ...}              # code → 名称(全市场)
  }
用法: python3 sector_components.py [--out outputs/sector_component.json]
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

SINA_HY = "http://money.finance.sina.com.cn/q/view/newSinaHy.php"
SINA_GN = "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class"
SINA_NODE = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"


def http_get(url, decode="utf-8"):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode(decode, errors="ignore")


def fetch_sector_list(url, prefix):
    """返回 [(code, name), ...] 板块清单（GBK）"""
    raw = http_get(url, "gbk")
    out = []
    for m in re.finditer(r'"([a-z0-9_]+)":"([^"]*)"', raw):
        code = m.group(1)
        if not code.startswith(prefix):
            continue
        fields = m.group(2).split(",")
        name = fields[1] if len(fields) > 1 else ""
        if name:
            out.append((code, name))
    return out


def fetch_sector_stocks(node_code):
    """返回板块成分 [(code, name), ...]"""
    url = f"{SINA_NODE}?page=1&num=1000&sort=symbol&asc=1&node={node_code}"
    try:
        raw = http_get(url)
        arr = json.loads(raw)
        return [(x.get("code", ""), x.get("name", "")) for x in arr if x.get("code")]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs/sector_component.json")
    ap.add_argument("--date", help="数据日期（默认今天）")
    ap.add_argument("--type", choices=["industry", "concept", "all"], default="all",
                    help="industry=新浪49行业 / concept=新浪175概念 / all=两者(默认)")
    args = ap.parse_args()

    groups = []
    if args.type in ("industry", "all"):
        groups.append(("行业", fetch_sector_list(SINA_HY, "new_")))
    if args.type in ("concept", "all"):
        groups.append(("概念", fetch_sector_list(SINA_GN, "gn_")))

    sectors = {}
    code_sector = {}
    code_name = {}
    for gname, secs in groups:
        print(f"{gname}板块: {len(secs)} 个", flush=True)
        for i, (code, name) in enumerate(secs, 1):
            stocks = fetch_sector_stocks(code)
            codes = []
            for scode, sname in stocks:
                codes.append(scode)
                code_sector.setdefault(scode, []).append(name)
                if scode not in code_name:
                    code_name[scode] = sname
            sectors[name] = codes
            if i % 20 == 0 or i == len(secs):
                print(f"  [{i}/{len(secs)}] {name}: {len(codes)} 只", flush=True)
            time.sleep(0.2)

    date = args.date or __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    data = {"date": date, "sectors": sectors, "code_sector": code_sector, "code_name": code_name}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"✅ 输出 {args.out}: {len(sectors)} 板块, {len(code_name)} 只股票")
    covered = sum(1 for c in code_sector if code_sector[c])
    avg = sum(len(v) for v in code_sector.values()) / max(len(code_sector), 1)
    print(f"   覆盖: {covered} 只, 平均 {avg:.1f} 板块/股")


if __name__ == "__main__":
    main()
