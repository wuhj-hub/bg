#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ima_cred_check.py — IMA OpenAPI 凭证健康检查（预检 + 健康度标记 + 疑似过期预警）
====================================================================================
背景：IMA 凭证过期无有效期提示，只能被动 401 检测（扫描1小时后才发现）。
本脚本提供三种主动机制：

  1) --probe        立即调 IMA 轻量 API 验证凭证；401 时推送微信告警（含自愈指引）并 exit 1
  2) --mark-ok      上传成功时把当天日期写入 ima_cred_last_ok.json（健康度标记）
  3) --staleness N  读 ima_cred_last_ok.json，距上次成功 > N 天 → 推送"疑似过期请检查"并 exit 1

集成：
  - guard_selfcheck.yml（每日09:30）：--probe + --staleness 7 → 失效立即告警（不用等15:30扫描）
  - full_market_scan.yml：上传成功后 --mark-ok；提交步骤把 ima_cred_last_ok.json 一并提交

环境变量：
  IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY   IMA API 凭证
  PUSH_TOKEN                                  PushPlus 推送 token（可选，无则不推送）
  GH_REPO                                     GitHub 仓库（可选，默认 wuhj-hub/bg）
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, date

PROBE_API = "openapi/wiki/v1/check_repeated_names"
LAST_OK_FILE = "ima_cred_last_ok.json"


def get_cred():
    cid = os.environ.get("IMA_OPENAPI_CLIENTID", "")
    key = os.environ.get("IMA_OPENAPI_APIKEY", "")
    if not cid or not key:
        print("❌ 未设置 IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY")
        sys.exit(2)
    return cid, key


def probe():
    """调 IMA 轻量 API 验证凭证。返回 (ok, detail)"""
    cid, key = get_cred()
    body = json.dumps({
        "knowledge_base_id": "6kjd8jHpAyqf0xFVUo2xUWPaDAKapAWCw-Tki7V-aAs=",
        "names": ["__ima_cred_probe__"],
    }).encode()
    req = urllib.request.Request(
        f"https://ima.qq.com/{PROBE_API}", data=body, method="POST",
        headers={
            "ima-openapi-clientid": cid,
            "ima-openapi-apikey": key,
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = r.read().decode("utf-8", "replace")
            return True, f"HTTP {r.status} {resp[:150]}"
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:150]
        if e.code in (401, 403) or "auth" in msg.lower():
            return False, f"HTTP {e.code} {msg}"
        return True, f"HTTP {e.code}（非凭证问题）{msg}"  # 5xx/限流不算凭证失效
    except Exception as e:
        return True, f"{type(e).__name__}（网络异常，非凭证问题）{str(e)[:100]}"


def pushplus(title, content):
    token = os.environ.get("PUSH_TOKEN", "")
    if not token:
        print("  (未设置 PUSH_TOKEN，跳过推送)")
        return
    data = json.dumps({
        "token": token, "title": title, "content": content, "template": "markdown",
    }).encode()
    req = urllib.request.Request("https://www.pushplus.plus/send", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"  pushplus: HTTP {r.status} {r.read()[:100]}")
    except Exception as e:
        print(f"  pushplus 推送失败: {e}")


def mark_ok():
    """记录最近一次凭证验证/上传成功日期"""
    today = datetime.now().strftime("%Y-%m-%d")
    with open(LAST_OK_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_ok": today, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f,
                  ensure_ascii=False, indent=1)
    print(f"✅ ima_cred_last_ok.json 已更新: {today}")


def staleness(days):
    """检查距上次成功是否超过 days 天 → 疑似过期预警"""
    if not os.path.exists(LAST_OK_FILE):
        print(f"⚠️ 未找到 {LAST_OK_FILE}（尚无成功记录），跳过疑似过期检查")
        return 0
    try:
        with open(LAST_OK_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        last = datetime.strptime(d["last_ok"], "%Y-%m-%d").date()
        gap = (date.today() - last).days
    except Exception as e:
        print(f"⚠️ {LAST_OK_FILE} 解析失败: {e}")
        return 0
    if gap > days:
        msg = (f"⚠️ **IMA 凭证疑似过期**：距上次成功使用已 **{gap} 天**（>{days} 天），请尽快检查。\n\n"
               f"> 自愈步骤：\n> 1. 打开 https://ima.qq.com/agent-interface 重新生成 client_id / api_key\n"
               f"> 2. 更新 GitHub Secrets：`IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY`\n"
               f"> 3. 回填后下一次扫描自动恢复")
        print(msg)
        pushplus(f"⚠️ima凭证疑似过期({gap}天未用) {date.today()}", msg)
        return 1
    print(f"✅ 距上次成功使用 {gap} 天（≤{days} 天），正常")
    return 0


def main():
    ap = argparse.ArgumentParser(description="IMA 凭证健康检查")
    ap.add_argument("--probe", action="store_true", help="调 IMA API 验证凭证，失效推送告警")
    ap.add_argument("--mark-ok", action="store_true", help="记录最近成功日期到 ima_cred_last_ok.json")
    ap.add_argument("--staleness", type=int, metavar="N", help="距上次成功 > N 天 → 疑似过期预警")
    args = ap.parse_args()

    exit_code = 0

    if args.probe:
        ok, detail = probe()
        if ok:
            print(f"✅ IMA 凭证有效: {detail}")
        else:
            msg = (f"⚠️ **ima OpenAPI 凭证已失效**（{detail}）\n\n"
                   f"> 【需要您处理 · 自愈步骤】\n"
                   f"> 1. 打开 https://ima.qq.com/agent-interface 点「获取 API Key」重新生成\n"
                   f"> 2. 更新 GitHub Secrets：`IMA_OPENAPI_CLIENTID` / `IMA_OPENAPI_APIKEY`\n"
                   f"> 3. 回填后下一次扫描将自动恢复")
            print(msg)
            pushplus(f"⚠️ima凭证失效 请重置 {date.today()}", msg)
            exit_code = 1

    if args.mark_ok:
        mark_ok()

    if args.staleness:
        rc = staleness(args.staleness)
        if rc:
            exit_code = rc

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
