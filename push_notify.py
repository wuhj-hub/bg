#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送全量扫描完成通知到微信（轻量版——仅通知，完整报告在复盘报告中合成）。

环境变量：
  PUSH_TOKEN    : 推送服务 token / key（必填）
  PUSH_SERVICE  : pushplus(默认) | serverchan | wecom
"""

import os, sys, json, time, urllib.request

TOKEN = os.environ.get("PUSH_TOKEN", "")
SERVICE = os.environ.get("PUSH_SERVICE", "pushplus").lower()
TODAY = time.strftime("%Y-%m-%d")

MSG = f"""# 🔄 全量扫描完成 · {TODAY}

> 原始数据已上传至「报告」知识库 →「复盘报告」文件夹

📋 盘后量化_{TODAY}.md 已就绪，请使用「复盘报告」指令合成完整报告。
"""


def _post(url, body):
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def push_pushplus(token):
    body = json.dumps({
        "token": token,
        "title": f"全量扫描完成 {TODAY}",
        "content": MSG,
        "template": "markdown",
    }).encode("utf-8")
    return _post("https://www.pushplus.plus/send", body)


def main():
    if not TOKEN:
        print("PUSH_SKIP: PUSH_TOKEN not set")
        return
    try:
        if SERVICE == "pushplus":
            resp = push_pushplus(TOKEN)
        else:
            print("UNKNOWN_SERVICE", SERVICE)
            return
        print("PUSH_OK", resp[:300])
    except Exception as e:
        print("PUSH_ERR", repr(e)[:200])


if __name__ == "__main__":
    main()
