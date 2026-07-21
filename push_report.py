#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把全市场双维扫描报告推送到微信（PushPlus / Server酱 / 企业微信机器人）。

环境变量：
  PUSH_TOKEN    : 推送服务 token / key（必填）
  PUSH_SERVICE  : pushplus(默认) | serverchan | wecom
  PUSH_REPORT   : 报告文件路径（默认 full_market_report.md）
"""
import os, sys, json, time, urllib.request

TOKEN = os.environ.get("PUSH_TOKEN", "")
SERVICE = os.environ.get("PUSH_SERVICE", "pushplus").lower()
REPORT = os.environ.get("PUSH_REPORT", "full_market_report.md")
# 推送服务单条长度限制（免费版普遍在 2~5 万字符），保守截断到 2 万
MAX_LEN = 20000


def read_report():
    try:
        with open(REPORT, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        print("REPORT_NOT_FOUND", REPORT)
        return None
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN] + "\n\n...（报告过长，仅推送前%d字，完整报告见 IMA 知识库「全市场双维扫描」）" % MAX_LEN
    return text


def _post(url, body):
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def push_pushplus(token, content):
    body = json.dumps({
        "token": token,
        "title": "全市场双维扫描 " + time.strftime("%Y-%m-%d"),
        "content": content,
        "template": "markdown",
    }).encode("utf-8")
    return _post("https://www.pushplus.plus/send", body)


def push_serverchan(token, content):
    body = json.dumps({"title": "全市场双维扫描", "desp": content}).encode("utf-8")
    return _post(f"https://sctapi.ftqq.com/{token}.send", body)


def push_wecom(token, content):
    body = json.dumps({"msgtype": "markdown", "markdown": {"content": content}}).encode("utf-8")
    return _post(f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={token}", body)


def main():
    if not TOKEN:
        print("PUSH_SKIP: PUSH_TOKEN not set")
        return
    content = read_report()
    if content is None:
        return
    try:
        if SERVICE == "pushplus":
            resp = push_pushplus(TOKEN, content)
        elif SERVICE in ("serverchan", "server酱", "ftqq"):
            resp = push_serverchan(TOKEN, content)
        elif SERVICE in ("wecom", "企业微信", "企微"):
            resp = push_wecom(TOKEN, content)
        else:
            print("UNKNOWN_SERVICE", SERVICE)
            return
        print("PUSH_OK", resp[:400])
    except Exception as e:
        print("PUSH_ERR", repr(e)[:200])


if __name__ == "__main__":
    main()
