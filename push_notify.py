#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送全量扫描结果到微信（PushPlus 备份通道）。

不依赖 ima 上传成功（workflow if: always() 调用）。
读取 panhou_lianghua.md 提取关键摘要推送。
根据 IMA_UPLOAD_OK / IMA_CRED_EXPIRED 动态提示：
  - 成功：已同步 ima
  - 凭证失效(401)：升级告警，请去 ima 重新生成并回填 secret（自愈指引）
  - 其他失败：结果备份
"""

import os, json, time, urllib.request

TOKEN = os.environ.get("PUSH_TOKEN", "")
SERVICE = os.environ.get("PUSH_SERVICE", "pushplus").lower()
TODAY = time.strftime("%Y-%m-%d")
IMA_OK = os.environ.get("IMA_UPLOAD_OK", "true").lower() in ("true", "1", "ok", "")
CRED_EXPIRED = os.environ.get("IMA_CRED_EXPIRED", "false").lower() in ("true", "1", "yes")
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
    if IMA_OK and not CRED_EXPIRED:
        head = f"# ✅ 全量扫描完成 · {TODAY}\n\n> 已同步至 ima「复盘报告」知识库。"
    elif CRED_EXPIRED:
        head = (
            f"# ⚠️ 全量扫描完成 · {TODAY}\n\n"
            f"> **ima OpenAPI 凭证已失效（上传持续 401 / skill auth failed）**，本次结果未能同步至 ima。\n\n"
            f"> **【需要您处理 · 自愈步骤】**\n"
            f"> 1. 打开 https://ima.qq.com/agent-interface 点「获取 API Key」重新生成一对 client_id / api_key\n"
            f"> 2. 把新值分别更新到 GitHub 仓库 Secrets：\n"
            f"> 　　· `IMA_OPENAPI_CLIENTID`\n> 　　· `IMA_OPENAPI_APIKEY`\n"
            f"> 3. 回填后下一次扫描将自动用新凭证成功（无需改代码）。\n\n"
            f"> 以下为本次结果备份："
        )
    else:
        head = (
            f"# ⚠️ 全量扫描完成 · {TODAY}\n\n"
            f"> **ima 上传失败（非凭证失效，疑似网络/限流）**，以下是结果备份："
        )
    summary = extract_summary(RESULT_FILE)
    return f"{head}\n\n## 📊 关键结果\n\n{summary}\n\n---\n🤖 由 full_market_scan 自动推送（PushPlus 备份通道）"


def _post(url, body):
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def push_pushplus(token):
    if CRED_EXPIRED:
        title = "⚠️ima凭证失效 请重置 " + TODAY
    elif not IMA_OK:
        title = "⚠️扫描完成(ima失败) " + TODAY
    else:
        title = "扫描完成 " + TODAY
    body = json.dumps({
        "token": token,
        "title": title,
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
