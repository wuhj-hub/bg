#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开盘啦(KaiplanLa)数据源可达性探测 — 在 GitHub runner（外网正常）执行。
探测：域名解析/连通性/页面结构/API线索，输出结构化结论供人工判断。
用法: python3 runner_probe_kpl.py
"""
import json
import re
import socket
import ssl
import subprocess
import sys

DOMAINS = [
    "kaiplanla.cn", "www.kaiplanla.cn", "app.kaiplanla.cn",
    "api.kaiplanla.cn", "m.kaiplanla.cn", "stock.kaiplanla.cn",
    "kpl.com.cn", "www.kpl.com.cn",
]

# 可能的网页入口路径（开盘啦特色页面：涨停/题材库/情绪）
PAGES = ["/", "/zt", "/bankuai", "/plate", "/market", "/api/", "/api/plate/list",
         "/api/v1/plate", "/plate/list", "/home", "/limitup"]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def probe(host, path):
    """curl 探测单路径, 返回 (code, content_type, body_head, redirect)"""
    url = f"https://{host}{path}" if host not in ("kaiplanla.cn",) else f"http://{host}{path}"
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "12", "-o", "/tmp/kpl_body.html", "-w",
             "%{http_code}|%{content_type}|%{url_effective}|%{size_download}",
             "-A", UA, url],
            capture_output=True, text=True, timeout=20)
        meta = r.stdout.strip().split("|")
        code = meta[0] if meta else "?"
        ctype = meta[1] if len(meta) > 1 else "?"
        final_url = meta[2] if len(meta) > 2 else url
        size = meta[3] if len(meta) > 3 else "?"
        head = ""
        try:
            head = open("/tmp/kpl_body.html", encoding="utf-8", errors="ignore").read()[:400].replace("\n", " ")
        except OSError:
            pass
        return {"url": url, "code": code, "type": ctype, "final": final_url, "size": size, "head": head}
    except Exception as e:
        return {"url": url, "err": str(e)[:120]}


def main():
    results = []
    # DNS 解析检查
    for host in DOMAINS:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            results.append({"dns": host, "ips": sorted({i[4][0] for i in infos})})
        except Exception as e:
            results.append({"dns": host, "err": str(e)[:80]})

    # 网页入口探测（先确认主站可达, 再探页面）
    for host in DOMAINS[:3]:
        r = probe(host, "/")
        results.append(r)
        if str(r.get("code", "")).startswith("2") or str(r.get("code", "")).startswith("3"):
            # 抓 HTML 中 API 线索
            try:
                body = open("/tmp/kpl_body.html", encoding="utf-8", errors="ignore").read()
                apis = sorted(set(re.findall(r'["\'](/[a-zA-Z0-9_\-/]{3,60}(?:api|Api|API)[a-zA-Z0-9_\-/?=&.]*)["\']', body)))[:10]
                nxt = sorted(set(re.findall(r'["\'](/_next/static/[^"\']+)["\']', body)))[:5]
                if apis:
                    results.append({"api_hints": apis})
                if nxt:
                    results.append({"next_assets": nxt})
            except Exception:
                pass
            # 探常见路径
            for p in PAGES[1:]:
                r2 = probe(host, p)
                if str(r2.get("code", "")) != "404":
                    results.append(r2)

    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
