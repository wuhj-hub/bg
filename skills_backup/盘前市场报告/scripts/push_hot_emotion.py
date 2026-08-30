#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量上传 hot_emotion 模块产物到 GitHub bg 仓库（wuhj-hub/bg）。
用法: python3 push_hot_emotion.py
"""
import base64
import json
import os
import subprocess
import sys

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "wuhj-hub/bg"
BRANCH = "main"

SKILLS = "/sandbox/workspace/skills"
OUTS = f"{SKILLS}/盘前市场报告/scripts/outputs"

FILES = [
    # (本地路径, GitHub路径, commit消息)
    (f"{SKILLS}/盘前市场报告/scripts/hot_emotion.py",
     "skills_backup/盘前市场报告/scripts/hot_emotion.py",
     "hot_emotion.py 热点情绪模块（连板梯队+板块持续性+退潮预警）"),
    (f"{SKILLS}/盘前市场报告/SKILL.md",
     "skills_backup/盘前市场报告/SKILL.md",
     "盘前市场报告 SKILL.md 集成热点情绪（2.13/②.5/③.5）"),
    (f"{SKILLS}/复盘报告/SKILL.md",
     "skills_backup/复盘报告/SKILL.md",
     "复盘报告 SKILL.md 集成热点情绪（5.4/规范7.6）"),
    (f"{SKILLS}/复盘报告/SKILL.md",
     "skills_backup/复盘报告_SKILL.md",
     "复盘报告 SKILL.md 双结构备份同步"),
    (f"{OUTS}/hot_emotion_2026-08-18.md",
     "skills_backup/盘前市场报告/scripts/outputs/hot_emotion_2026-08-18.md",
     "hot_emotion 实测样例 8/18"),
    (f"{OUTS}/hot_emotion_latest.json",
     "skills_backup/盘前市场报告/scripts/outputs/hot_emotion_latest.json",
     "hot_emotion latest json"),
    (f"{OUTS}/hot_emotion_history.json",
     "skills_backup/盘前市场报告/scripts/outputs/hot_emotion_history.json",
     "hot_emotion history json"),
    (f"{OUTS}/tdx_2026-08-18.json",
     "skills_backup/盘前市场报告/scripts/outputs/tdx_2026-08-18.json",
     "tdx_screener 涨停数据样例 8/18"),
]


def api_call(method, url, payload=None):
    cmd = ["curl", "-s", "-X", method,
           "-H", f"Authorization: token {TOKEN}",
           "-H", "Content-Type: application/json"]
    if payload is not None:
        tmp = "/tmp/gh_payload.json"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        cmd += ["-d", f"@{tmp}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"raw": r.stdout, "stderr": r.stderr}


def get_sha(path):
    r = api_call("GET", f"https://api.github.com/repos/{REPO}/contents/{path}?ref={BRANCH}")
    return r.get("sha") if isinstance(r, dict) else None


def put_file(local, gh_path, msg):
    with open(local, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()
    old_sha = get_sha(gh_path)
    payload = {"message": msg, "content": content_b64, "branch": BRANCH}
    if old_sha:
        payload["sha"] = old_sha
    r = api_call("PUT", f"https://api.github.com/repos/{REPO}/contents/{gh_path}", payload)
    if isinstance(r, dict) and r.get("content"):
        print(f"✅ {gh_path} ({os.path.getsize(local)}B)")
        return True
    print(f"❌ {gh_path}: {json.dumps(r, ensure_ascii=False)[:300]}")
    return False


if __name__ == "__main__":
    ok = 0
    for local, gh, msg in FILES:
        if not os.path.exists(local):
            print(f"⏭️ 本地缺失，跳过: {local}")
            continue
        if put_file(local, gh, msg):
            ok += 1
    print(f"\n完成 {ok}/{len(FILES)}")
    sys.exit(0 if ok == len(FILES) else 1)
