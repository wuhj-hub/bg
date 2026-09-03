#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺板块成分抓取（沙箱/runner均可达，无签名；翻页需hexin-v cookie待破解）。
产出: outputs/sector_component_ths.json — code→行业板块归属（每板块首页成分）
用法: python3 ths_sector_fetch.py [--concepts] [--out outputs/sector_component_ths.json]
"""
import argparse
import json
import os
import re
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(url, referer="https://q.10jqka.com.cn/"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("gbk", errors="ignore")


def fetch_board_list(page_type):
    """同花顺板块列表页 → [(代码, 名称)]，page_type: thshy=行业 / gn=概念 / dy=地域"""
    html = get(f"https://q.10jqka.com.cn/{page_type}/")
    # 板块链接: <a href="http://q.10jqka.com.cn/thshy/detail/code/881121/" ...>半导体</a>
    pat = re.compile(r'href="https?://q\.10jqka\.com\.cn/' + re.escape(page_type) +
                     r'/detail/code/(\d+)/"[^>]*>([^<]+)</a>')
    return [(m.group(1), m.group(2).strip()) for m in pat.finditer(html)]


def fetch_board_page(board_code, page_type, page=1):
    """板块成分页（HTML 表格）→ [(code, name)]，page=1 首页无cookie可取"""
    url = f"https://q.10jqka.com.cn/{page_type}/detail/code/{board_code}/"
    if page > 1:
        url = f"https://q.10jqka.com.cn/{page_type}/detail/field/199112/order/desc/page/{page}/ajax/1/"
    try:
        html = get(url, referer=f"https://q.10jqka.com.cn/{page_type}/detail/code/{board_code}/")
    except Exception:
        return []
    # 成分行: <a href=".../stock/688209/" ...>688209</a> 名称在相邻单元格
    rows = []
    # 匹配表格行: <tr>...<a href=".../stock/600000/">600000</a>...</tr> 名称从行内中文提取
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        m = re.search(r'href="[^"]*/stock/(\d{6})/[^"]*"[^>]*>.*?<td[^>]*>\s*<a[^>]*>([^<]{2,10})</a>', tr, re.S)
        if not m:
            m = re.search(r'href="[^"]*/stock/(\d{6})/"', tr)
            if m:
                # 名称: 找行内最后一个中文 td
                tds = re.findall(r"<td[^>]*>([^<]{2,10})</td>", tr)
                nm = next((t.strip() for t in reversed(tds) if re.fullmatch(r"[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9*]{1,9}", t.strip())), "")
                rows.append((m.group(1), nm))
        else:
            rows.append((m.group(1), m.group(2).strip()))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concepts", action="store_true", help="同时拉概念板块(400+请求,慢)")
    ap.add_argument("--out", default="outputs/sector_component_ths.json")
    args = ap.parse_args()

    groups = [("行业", "thshy")]
    if args.concepts:
        groups.append(("概念", "gn"))
        groups.append(("地域", "dy"))

    sectors = {}
    code_sector = {}
    code_name = {}
    for gname, page_type in groups:
        boards = fetch_board_list(page_type)
        print(f"{gname}板块: {len(boards)} 个", flush=True)
        for i, (bcode, bname) in enumerate(boards, 1):
            stocks = fetch_board_page(bcode, page_type)
            codes = []
            for scode, sname in stocks:
                if scode:
                    codes.append(scode)
                    code_sector.setdefault(scode, []).append(bname)
                    if sname and scode not in code_name:
                        code_name[scode] = sname
            sectors[f"{gname}:{bname}"] = codes
            if i % 20 == 0 or i == len(boards):
                print(f"  [{i}/{len(boards)}] {bname}: {len(codes)}只 | 累计{len(code_name)}只", flush=True)
            time.sleep(0.25)

    date = time.strftime("%Y-%m-%d")
    data = {"date": date, "source": "ths", "sectors": sectors, "code_sector": code_sector, "code_name": code_name}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"✅ {args.out}: {len(sectors)} 板块 | {len(code_name)} 只")
    for c in ("003005", "601086", "605577", "603207", "600540", "002909"):
        print(f"  抽检 {c} {code_name.get(c,'?' )}: {code_sector.get(c, [])[:4]}")


if __name__ == "__main__":
    main()
