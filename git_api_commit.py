#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git_api_commit.py — 用 GitHub Contents API 提交文件，绕开 git pull/push 并发冲突
====================================================================================
背景：full_market_scan.yml 原"提交量化汇总"步骤用 git commit+push，
     8/17 起连续失败（浅克隆 pull --rebase 冲突、多 workflow 并发 push 竞争），
     导致后续上传知识库/复盘报告/胜率跟踪全部被跳过。

方案：改用 Contents API（PUT + sha 校验）逐文件原子提交：
  - 并发安全：每个文件独立 PUT，冲突返回 409 时读取最新 sha 重试
  - 无需 git 历史：不依赖浅克隆/合并策略
  - 与 guard 自检等 workflow 的 git push 互不干扰

用法（workflow 内）：
  python3 git_api_commit.py --msg "chore: update quant_latest (2026-08-19)" \
      quant_results_latest.json fish_body_latest.json 板块共振_latest.json ...

环境变量：
  GITHUB_TOKEN  （workflow 自动注入，需 permissions: contents: write）
  GH_REPO       （默认 wuhj-hub/bg）
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time

REPO = os.environ.get("GH_REPO", "wuhj-hub/bg")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
BRANCH = "main"


def curl(method, url, payload=None):
    """curl 封装：GitHub API 用 curl 更稳（urllib 易 RemoteDisconnected）。"""
    cmd = ["curl", "-s", "-X", method,
           "-H", f"Authorization: token {TOKEN}",
           "-H", "User-Agent: git-api-commit",
           "-H", "Content-Type: application/json"]
    if payload is not None:
        tmp = "/tmp/gh_api_payload.json"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        cmd += ["-d", f"@{tmp}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        return {"raw": r.stdout[:300]}


def get_sha(gh_path):
    r = curl("GET", f"https://api.github.com/repos/{REPO}/contents/{gh_path}?ref={BRANCH}")
    return r.get("sha") if isinstance(r, dict) else None


def put_file(gh_path, content_b64, msg, retries=3):
    for i in range(retries):
        old_sha = get_sha(gh_path)
        payload = {"message": msg, "content": content_b64, "branch": BRANCH}
        if old_sha:
            payload["sha"] = old_sha
        r = curl("PUT", f"https://api.github.com/repos/{REPO}/contents/{gh_path}", payload)
        if isinstance(r, dict) and r.get("content"):
            return True
        # 409 并发冲突 → 拉最新 sha 重试
        if isinstance(r, dict) and r.get("message", "").startswith("409"):
            time.sleep(3)
            continue
        print(f"  ⚠️ {gh_path}: {str(r)[:200]}")
        time.sleep(3)
    return False


def main():
    ap = argparse.ArgumentParser(description="GitHub Contents API 提交")
    ap.add_argument("--msg", required=True, help="commit message")
    ap.add_argument("files", nargs="+", help="相对仓库根的文件路径（本地=远端）")
    args = ap.parse_args()

    if not TOKEN:
        print("错误：未设置 GITHUB_TOKEN", file=sys.stderr)
        sys.exit(1)

    ok = 0
    for path in args.files:
        if not os.path.exists(path):
            print(f"⏭️ 本地缺失，跳过: {path}")
            continue
        with open(path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()
        if put_file(path, content_b64, args.msg):
            print(f"✅ {path} ({os.path.getsize(path)}B)")
            ok += 1
        else:
            print(f"❌ {path}")
    print(f"\n完成 {ok}/{len(args.files)}")
    sys.exit(0 if ok > 0 else 1)


if __name__ == "__main__":
    main()
