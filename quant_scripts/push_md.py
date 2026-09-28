#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push_md.py —— 通用 Markdown 推送（PushPlus）

环境变量：PUSH_TOKEN（必填）
用法：python3 push_md.py --file <path.md> --title "标题"
"""
import os, sys, json, argparse, urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--title", default="量化报告")
    ap.add_argument("--max", type=int, default=20000)
    a = ap.parse_args()

    tok = os.environ.get("PUSH_TOKEN", "")
    if not tok:
        print("[SKIP] 未设置 PUSH_TOKEN")
        return
    if not os.path.exists(a.file):
        print(f"[ERR] 文件不存在: {a.file}")
        return
    txt = open(a.file, encoding="utf-8", errors="replace").read()
    if len(txt) > a.max:
        txt = txt[:a.max] + "\n\n…（报告过长，完整版见知识库）"
    body = json.dumps({"token": tok, "title": a.title, "content": txt,
                       "template": "markdown"}).encode("utf-8")
    req = urllib.request.Request("https://www.pushplus.plus/send", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        print(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[ERR] 推送失败: {e}")


if __name__ == "__main__":
    main()
