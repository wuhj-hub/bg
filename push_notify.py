#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送全量扫描结果到微信（PushPlus）。

作为 ima 上传的**独立备份通道**：
  - 不依赖 ima 上传成功（workflow 中以 if: always() 调用）
  - 读取 panhou_lianghua.md 提取关键摘要推送
  - 根据 IMA_UPLOAD_OK 环境变量区分 ima 是否已同步成功

环境变量：
  PUSH_TOKEN    : pushplus token（必填）
  PUSH_SERVICE  : pushplus(默认)
  IMA_UPLOAD_OK : true/false（ima 上传是否成功，缺省视为成功）
  RESULT_FILE   : 结果 md 路径（默认 panhou_lianghua.md）
"""

import os, json, time, urllib.request

TOKEN = os.environ.get("PUSH_TOKEN", "")
SERVICE = os.environ.get("PUSH_SERVICE", "pushplus").lower()
TODAY = time.strftime("%Y-%m-%d")
IMA_OK = os.environ.get("IMA_UPLOAD_OK", "true").lower() in ("true", "1", "ok", "")
RESULT_FILE = os.environ.get("RESULT_FILE", "panhou_lianghua.md")


def extract_summary(path, max_chars=5000):
    """读取结果 md，提取关键摘要（稳健截断，避免 PushPlus 超长）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception as e:
        return f"（无法读取结果文件 {path}：{e}）"
    lines = text.splitlines()
    keywords = ("★", "重点", "买入", "关注", "信号", "精选", "共振",
                "操作建议", "评分", ">>>", "候选", "预警")
    picked = [ln for ln in lines if any(k in ln for k in keywords)]
    body = "\n".join(picked[:60]) if picked else "\n".join(lines[:120])
    if len(body) > max_chars:
        body = body[:max_chars] + "\n\n…（结果过长已截断，完整版见 ima「复盘报告」）"
    return body


def build_msg():
    if IMA_OK:
        head = f"# ✅ 全量扫描完成 · {TODAY}\n\n> 已同步至 ima「复盘报告」知识库。"
    else:
        head = (f"# ⚠️ 全量扫描完成 · {TODAY}\n\n"
                f"> **ima 上传失败（OpenAPI 凭证可能已过期/失效）**，"
                f"以下是结果备份，请查收。")
    summary = extract_summary(RESULT_FILE)
    return f"{head}\n\n## 📊 关键结果\n\n{summary}\n\n---\n🤖 由 full_market_scan 自动推送（PushPlus 备份通道）"


def _post(url, body):
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def push_pushplus(token):
    body = json.dumps({
        "token": token,
        "title": ("⚠️扫描完成(ima失败) " if not IMA_OK else "扫描完成 ") + TODAY,
        "content": build_msg(),
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
