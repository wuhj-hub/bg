#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wangzhe_commit.py —— 把王者跟踪产物提交回仓库（GitHub Actions 用）

用法：python3 quant_scripts/wangzhe_commit.py
环境：GH_TOKEN（默认 github.token）
说明：用内联「GET sha → PUT」模式（git_push 类工具对新建文件路径处理有缺陷，见经验库）
"""
import os, json, base64, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8))
repo = os.environ.get("GITHUB_REPOSITORY", "wuhj-hub/bg")
tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
br = os.environ.get("TARGET_BRANCH", "main")
d = datetime.now(BJT).strftime("%Y-%m-%d")
files = ["outputs/wangzhe_signals.csv", "outputs/wangzhe_stats.json",
         f"outputs/涨停型王者_成功率报告_{d}.md",
         "outputs/caige_track.json"]
# 才哥文章存档目录（逐篇提交）
import glob
files += sorted(glob.glob("outputs/caige_articles/*.md")) + sorted(glob.glob("outputs/caige_articles/*.json"))

if not tok:
    print("[ERR] 未设置 GH_TOKEN")
    raise SystemExit(1)

for fp in files:
    if not os.path.exists(fp):
        print(f"[SKIP] {fp} 不存在")
        continue
    api = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(fp)}"
    sha = None
    try:
        r = urllib.request.Request(f"{api}?ref={br}", headers={"Authorization": f"token {tok}",
                                                               "Accept": "application/vnd.github+json"})
        sha = json.loads(urllib.request.urlopen(r, timeout=30).read())["sha"]
    except Exception:
        pass
    body = {"message": f"chore(王者跟踪): 更新 {fp.split('/')[-1]}", "branch": br,
            "content": base64.b64encode(open(fp, "rb").read()).decode()}
    if sha:
        body["sha"] = sha
    for attempt in range(3):
        try:
            r = urllib.request.Request(api, method="PUT", data=json.dumps(body).encode(),
                headers={"Authorization": f"token {tok}", "Accept": "application/vnd.github+json"})
            res = json.loads(urllib.request.urlopen(r, timeout=90).read())
            print(f"[OK] {fp} {'(更新)' if sha else '(新建)'} -> {res['commit']['sha'][:8]}")
            break
        except Exception as e:
            if attempt == 2:
                print(f"[ERR] {fp}: {e}")
