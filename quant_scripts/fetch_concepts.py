#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_concepts.py —— 个股「行业 + 概念」标签（东财 F10 · CoreConception）
=====================================================================
口径（2026-11-28 定）：**行业为主，概念为辅**

东财 ssbk 返回一只票所属的全部板块（约 20 个），混杂四类：
  · 行业     —— BOARD_RANK 1~3（轻工制造 / 造纸 / 特种纸）
  · 地域     —— "福建板块" 等（IS_PRECISE=0）
  · 特征     —— 股权分散 / 题材股 / 百日新高 / 沪股通 …（IS_PRECISE=0/null）
  · **精准概念** —— IS_PRECISE=="1"（光通信模块 / 5G概念 / 央国企改革 …）

本模块只抽「行业(rank≤3)」与「精准概念(IS_PRECISE=1)」，其余丢弃。

用法（库）：
    from fetch_concepts import ensure
    cmap = ensure(["600103", "000158"])   # → {c6: {"ind": [...], "concept": [...]}}
用法（CLI 自检）：
    python3 fetch_concepts.py 600103 000158
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "em_concept_map.json")
TTL_DAYS = 7
URL = "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code={}"

# 泛概念黑名单：无方向性（资金属性/交易属性/泛主题），聚合时会霸榜，直接丢弃
BOILERPLATE = {
    "央国企改革", "国企改革", "节能环保", "创投", "参股银行", "参股券商", "参股保险",
    "融资融券", "沪股通", "深股通", "MSCI中国", "富时罗素", "标准普尔", "转债标的",
    "股权转让", "股权分散", "破净股", "低价股", "预盈预增", "预亏预减", "高送转",
    "次新股", "注册制次新股", "QFII重仓", "社保重仓", "基金重仓", "机构重仓",
    "昨日涨停", "昨日连板", "昨日触板", "壳资源", "ST板块", "举牌", "增持回购",
    "同花顺漂亮100", "茅指数", "宁组合", "专精特新", "独角兽", "举牌概念",
}


def _sym(c6):
    return ("SH" if c6[:1] in ("6", "9", "5") else "SZ") + c6


def fetch_one(c6, timeout=20):
    """→ (行业列表, 概念列表)"""
    req = urllib.request.Request(URL.format(_sym(c6)), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "ignore"))
    inds, cons = [], []
    for x in d.get("ssbk") or []:
        nm = (x.get("BOARD_NAME") or "").strip()
        if not nm:
            continue
        try:
            rank = int(x.get("BOARD_RANK") or 99)
        except (TypeError, ValueError):
            rank = 99
        if rank <= 3:
            inds.append(nm)
        elif str(x.get("IS_PRECISE")) == "1":
            if nm not in BOILERPLATE:
                cons.append(nm)
    return inds, cons


def load_map():
    try:
        with open(CACHE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_map(m):
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, sort_keys=True)
    except Exception:  # noqa: BLE001
        pass


def ensure(codes, ttl_days=TTL_DAYS, sleep=0.15, verbose=False):
    """对给定代码补齐标签（只抓缺失/过期），返回 {c6: {...}}。

    单只失败不影响其它；失败时返回已有缓存或空标签。
    """
    m = load_map()
    today = date.today()
    out = {}
    for c6 in codes:
        c6 = str(c6).zfill(6)
        rec = m.get(c6)
        fresh = False
        if isinstance(rec, dict) and rec.get("ts"):
            try:
                fresh = (today - datetime.strptime(rec["ts"], "%Y-%m-%d").date()).days <= ttl_days
            except Exception:  # noqa: BLE001
                fresh = False
        if not fresh:
            try:
                inds, cons = fetch_one(c6)
                rec = {"ind": inds, "concept": cons, "ts": today.isoformat()}
                m[c6] = rec
                time.sleep(sleep)
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"[WARN] concept {c6}: {e}", file=sys.stderr)
                rec = rec if isinstance(rec, dict) else {"ind": [], "concept": [], "ts": ""}
        out[c6] = rec
    save_map(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="+")
    a = ap.parse_args()
    cmap = ensure(a.codes, sleep=0.2, verbose=True)
    for c6, rec in cmap.items():
        print(f"{c6}  行业={rec.get('ind')}  概念={rec.get('concept')}")


if __name__ == "__main__":
    sys.exit(main())
