#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_em_params.py —— 东财板块接口参数探测（runner 专用，2026-09-16）

背景：`sector_component_em.json` 长期为空壳。probe_em 实测发现：
  行业板块列表 m:90+t:2+f:!50 → 100 个（✅ 可用）
  概念板块列表 m:90+t:3+f:!50 → 0 个（❌）
  成分 b:BK0475+f:!50       → 0 只（❌）
本脚本系统性试各种 fs 参数 / 端点，找出当前仍可用的组合。

用法（runner）：python3 quant_scripts/probe_em_params.py
"""
import json
import time
import urllib.parse
import urllib.request

API = "https://push2.eastmoney.com/api/qt/clist/get"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36",
       "Referer": "https://quote.eastmoney.com/"}


def try_fs(host, fs, pz=5, label=""):
    url = (f"{host}/api/qt/clist/get?pn=1&pz={pz}&po=1&np=1&fltt=2&invt=2"
           f"&fid=f3&fs={urllib.parse.quote(fs)}&fields=f12,f14")
    try:
        req = urllib.request.Request(url, headers=HDR)
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
        d = json.loads(raw)
        data = d.get("data") or {}
        diff = data.get("diff") or []
        names = [x.get("f14") for x in diff[:3]]
        return f"HTTP OK total={data.get('total')} got={len(diff)} {names}"
    except Exception as e:
        return f"ERR {type(e).__name__} {str(e)[:60]}"


def main():
    print("=" * 78)
    print("东财板块接口参数探测")
    print("=" * 78)

    print("\n【A. 板块列表（找行业/概念的可用 fs）】")
    for fs in ["m:90+t:2+f:!50", "m:90+t:2", "m:90+t:3+f:!50", "m:90+t:3",
               "m:90+t:1", "m:90+t:23", "m:90+t:2,m:90+t:3", "m:90+t:2+f:!50,m:90+t:3+f:!50",
               "m:90", "m:90+t:90"]:
        print(f"  {fs:<26} → {try_fs('https://push2.eastmoney.com', fs)}")
        time.sleep(0.4)

    print("\n【B. 板块成分（拿一个已知板块 BK0475 试各种写法）】")
    for fs in ["b:BK0475+f:!50", "b:BK0475", "b:BK0475+f:!2", "b:BK0475+f:!2,f:!50",
               "b:BK0475,f:BK0476", "b:BK0475+f:!9", "i:BK0475"]:
        print(f"  {fs:<26} → {try_fs('https://push2.eastmoney.com', fs)}")
        time.sleep(0.4)

    print("\n【C. 换端点（push2his / push2delay / 备用域）】")
    for host in ["https://push2his.eastmoney.com", "https://push2delay.eastmoney.com",
                 "https://push2.eastmoney.com"]:
        for fs in ["b:BK0475", "m:90+t:3"]:
            print(f"  {host.split('//')[1][:22]:<24}{fs:<14} → {try_fs(host, fs)}")
            time.sleep(0.4)

    print("\n【D. 板块成分备用端点（datacenter / 单一板块详情）】")
    urls = [
        "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b%3ABK0475&fields=f12,f14,f2,f3",
        "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_CORETHEME_BOARDTYPE&columns=ALL&pageSize=5&filter=(BOARD_CODE=%22BK0475%22)",
    ]
    for u in urls:
        try:
            req = urllib.request.Request(u, headers=HDR)
            raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
            print(f"  {u[:64]:<66} → {raw[:120]}")
        except Exception as e:
            print(f"  {u[:64]:<66} → ERR {type(e).__name__} {str(e)[:50]}")
        time.sleep(0.4)

    print("\n【E. 同花顺成分页（备选源，验证可用性）】")
    for u in ["https://q.10jqka.com.cn/thshy/detail/code/881101/",
              "https://q.10jqka.com.cn/gn/detail/code/301558/"]:
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36",
                "Referer": "https://q.10jqka.com.cn/"})
            raw = urllib.request.urlopen(req, timeout=15).read().decode("gbk", errors="ignore")
            import re
            codes = re.findall(r">(60[0-9]{4}|00[0-9]{4}|30[0-9]{4}|68[0-9]{4})<", raw)
            print(f"  {u[:60]:<62} → {len(raw)}B 成分代码命中 {len(set(codes))} 个 {list(set(codes))[:5]}")
        except Exception as e:
            print(f"  {u[:60]:<62} → ERR {type(e).__name__} {str(e)[:50]}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
