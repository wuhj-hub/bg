#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开盘啦(KaiplanLa)数据源探测 第二轮 — kpl.com.cn 深度探测（runner执行）。
第一轮结论：kaiplanla.cn 域名全局失效；kpl.com.cn 解析OK(47.96.43.186 阿里云)。
本轮：连通性 + 页面结构 + API/板块龙头接口线索。
用法: python3 runner_probe_kpl.py
"""
import json
import re
import socket
import subprocess

DOMAINS = ["kpl.com.cn", "www.kpl.com.cn", "api.kpl.com.cn", "app.kpl.com.cn", "m.kpl.com.cn"]
# 开盘啦特色页/接口候选路径（涨停梯队/题材库/情绪/竞价）
PAGES = ["/", "/limitup", "/zt", "/bankuai", "/plate", "/theme", "/market",
         "/api/", "/api/plate", "/api/v1/", "/api/v1/plate/list", "/api/limitup/list",
         "/api/bankuai/list", "/v1/plate/list", "/qingxu", "/sign/", "/login"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def fetch(url, follow=True):
    r = subprocess.run(
        ["curl", "-s", "-L" if follow else "", "--max-time", "10", "-o", "/tmp/kpl_b.html", "-w",
         "%{http_code}|%{content_type}|%{url_effective}|%{size_download}|%{time_total}",
         "-A", UA, url],
        capture_output=True, text=True, timeout=18)
    meta = r.stdout.strip().split("|")
    out = {"url": url, "code": meta[0] if meta else "?", "type": meta[1] if len(meta) > 1 else "?",
           "final": meta[2] if len(meta) > 2 else url, "size": meta[3] if len(meta) > 3 else "?",
           "time": meta[4] if len(meta) > 4 else "?"}
    try:
        out["head"] = open("/tmp/kpl_b.html", encoding="utf-8", errors="ignore").read()[:250].replace("\n", " ")
    except OSError:
        out["head"] = ""
    return out


def main():
    results = []
    # 连通性（https + http 双测：kpl可能只开80）
    for host in DOMAINS:
        try:
            infos = socket.getaddrinfo(host, 443)
            ips = sorted({i[4][0] for i in infos})
        except Exception as e:
            results.append({"host": host, "err": str(e)[:80]})
            continue
        for scheme in ("https", "http"):
            r = fetch(f"{scheme}://{host}/")
            results.append({"host": host, "ips": ips, "scheme": scheme, **r})

    # 深度：对可达域名探页面 + 提取线索
    for host, scheme in (("www.kpl.com.cn", "http"), ("www.kpl.com.cn", "https"), ("kpl.com.cn", "http")):
        try:
            body = open("/tmp/kpl_b.html", encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if not body:
            continue
        apis = sorted(set(re.findall(r'["\']([^"\']*(?:api|Api|API)[^"\']*)["\']', body)))[:15]
        nxt = sorted(set(re.findall(r'["\'](/_next/[^"\']+)["\']', body)))[:6]
        scripts = sorted(set(re.findall(r'src="([^"]+\.js)"', body)))[:10]
        if apis: results.append({"host": host, "api_hints": apis})
        if nxt: results.append({"host": host, "next_assets": nxt})
        if scripts: results.append({"host": host, "scripts": scripts})
        # 页面路径
        for p in PAGES[1:]:
            r = fetch(f"{scheme}://{host}{p}")
            if r["code"] not in ("404", "000") or r["size"] not in ("0", "?"):
                results.append(r)

    # v5: 从 _nuxt JS chunk 提取真实 API 端点（SSR壳内数据由异步API拉取）
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "15", "-o", "/tmp/kpl_limitup.html",
                            "-A", UA, "http://www.kpl.com.cn/limitup"],
                           capture_output=True, text=True, timeout=20)
        body = open("/tmp/kpl_limitup.html", encoding="utf-8", errors="ignore").read()
        js_files = sorted(set(re.findall(r'src="([^"]*?_nuxt/[a-f0-9]+\.js)"', body)))[:8]
        results.append({"nuxt_js_count": len(js_files), "js_samples": js_files[:5]})
        api_hits = []
        for js in js_files[:4]:
            js_url = "http://www.kpl.com.cn" + (js if js.startswith("/") else "/" + js)
            rj = subprocess.run(["curl", "-s", "--max-time", "12", "-A", UA, js_url],
                                capture_output=True, text=True, timeout=18)
            jsc = rj.stdout
            hits = sorted(set(re.findall(r'https?://[a-zA-Z0-9._-]+(?:/[a-zA-Z0-9_./{}$-]*)?', jsc)))
            hits2 = sorted(set(re.findall(r'/[a-zA-Z][a-zA-Z0-9_/.-]*(?:list|detail|data|info|rank|index)[a-zA-Z0-9_/.-]*', jsc)))
            if hits or hits2:
                api_hits.append({"js": js.split("/")[-1], "size": len(jsc),
                                 "urls": hits[:12], "paths": hits2[:12]})
        results.append({"api_discovery": api_hits})

        # v6: 深挖含 zhugepan 域名的业务 chunk 路径 + 探测 api.zhugepan.com
        try:
            r6 = subprocess.run(["curl", "-s", "--max-time", "12", "-A", UA,
                                 "http://www.kpl.com.cn/_nuxt/056ba4b.js"],
                                capture_output=True, text=True, timeout=18)
            biz = r6.stdout
            biz_paths = sorted(set(re.findall(r'/[a-zA-Z][a-zA-Z0-9_./-]{2,60}', biz)))
            biz_paths = [p for p in biz_paths if not p.endswith((".js", ".css", ".png", ".svg", ".json", ".html", ".map"))
                         and "node_modules" not in p and "webpack" not in p][:60]
            results.append({"biz_chunk_paths": biz_paths})
        except Exception as e:
            results.append({"biz_chunk_err": str(e)[:100]})

        # api.zhugepan.com 连通性 + 常见端点
        for host in ("api.zhugepan.com",):
            try:
                infos = socket.getaddrinfo(host, 443)
                ips = sorted({i[4][0] for i in infos})
            except Exception as e:
                results.append({"zhugepan_dns_err": str(e)[:80]})
                continue
            for scheme in ("https", "http"):
                rr = fetch(f"{scheme}://{host}/")
                results.append({"zhugepan": host, "ips": ips, "scheme": scheme, **rr})
            for p in ("/api/plate/list", "/api/limitup/list", "/api/v1/plate/list", "/plate/list", "/api/theme/list", "/api/bankuai", "/v1/limitup"):
                rr = fetch(f"http://{host}{p}")
                if rr["code"] not in ("404", "000") or rr["size"] not in ("0", "?"):
                    results.append({"zhugepan_path": p, **rr})
    except Exception as e:
        results.append({"api_discovery_err": str(e)[:120]})

    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
