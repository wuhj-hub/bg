#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git_push.py —— GitHub Contents API 推送工具（替代被沙箱清理的 git_api_commit.py）
用法：python3 git_push.py <repo> <branch> <path> <local_file> ["commit message"]
"""
import sys, os, json, base64, urllib.request, time

TOKEN = os.environ.get("GITHUB_TOKEN", "")

def api(url, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    body = json.dumps(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(req, body, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

def push(repo, branch, path, local_file, msg):
    content = open(local_file, "rb").read()
    b64 = base64.b64encode(content).decode()
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    # 先查 sha（存在则更新）
    _, existing = api(url, "GET")
    sha = existing.get("sha") if isinstance(existing, dict) else None
    data = {"message": msg, "content": b64, "branch": branch}
    if sha:
        data["sha"] = sha
    code, resp = api(url, "PUT", data)
    if code in (200, 201):
        print(f"✅ {path} ({len(content)}B) → {repo}/{branch}")
        return True
    print(f"❌ {path}: HTTP {code} {resp.get('message','')}")
    return False

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)
    repo, branch, path, local = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    msg = sys.argv[5] if len(sys.argv) > 5 else f"update {path}"
    ok = push(repo, branch, path, local, msg)
    sys.exit(0 if ok else 1)
