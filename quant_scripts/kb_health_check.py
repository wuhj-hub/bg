#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb_health_check.py —— 知识库上传健康检查（2026-10-24 新增）

背景：2026-10-23 ima 平台强制 kb_id 新格式（旧长 id → code=220004），CI 里所有
「上传知识库」步骤全部失败，但每处调用都写成 `upload_ima.py ... || echo "上传失败"`，
失败被吞掉、run 仍是 success → 一整天没有任何报告进库却无人察觉。

本脚本从 **知识库侧反向核对**：指定文件夹里是否真的存在「某交易日」的对应报告文件。
缺失即 WARN（--strict 时 exit 1），由 selfcheck_daily 统一告警到微信。

用法：
  python3 quant_scripts/kb_health_check.py --out outputs --lookback 3 --strict
  python3 quant_scripts/kb_health_check.py --date 2026-10-23 --include-today

环境变量：
  IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY   必填
  IMA_KB_ID                                   目标知识库（默认 ima_kb_b5qpEC7v = 「报告」）

产物：
  outputs/kb_health_{date}.md / kb_health_latest.md / kb_health_latest.json
"""
import os
import sys
import json
import argparse
from datetime import date, datetime, timedelta

# 统一按北京时间取日（不依赖 runner 的 TZ 设置）
os.environ.setdefault("TZ", "Asia/Shanghai")
try:
    import time as _time
    _time.tzset()
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from trade_day_check import judge as _is_trade_day
except Exception:                                   # 兜底：周末判定
    def _is_trade_day(dt):
        return dt.weekday() < 5

import urllib.request

DEFAULT_KB = "ima_kb_b5qpEC7v"      # 「报告」知识库（新格式）

# 检查项：(中文名, folder_id, 匹配模板 or None=任意含日期文件)
CHECKS = [
    ("复盘报告", "folder_7485234585035034", "复盘报告_{date}.md"),
    ("盘前报告", "folder_7485319502904253", "盘前市场报告_{date}.md"),
    ("全盘量化", "folder_7485264708529742", None),
    ("竞价统计", "folder_7511006091703733", "竞价统计_{date}.md"),
]


def _api(api_path, body):
    cid = os.environ.get("IMA_OPENAPI_CLIENTID")
    key = os.environ.get("IMA_OPENAPI_APIKEY")
    if not cid or not key:
        raise RuntimeError("缺少 IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY")
    req = urllib.request.Request(
        f"https://ima.qq.com/{api_path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"ima-openapi-clientid": cid, "ima-openapi-apikey": key,
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def list_titles(kb_id, folder_id, max_pages=20):
    """列出文件夹下全部条目标题（分页 cursor）。失败返回 None。"""
    titles, cursor = [], ""
    for _ in range(max_pages):
        body = {"knowledge_base_id": kb_id, "folder_id": folder_id, "limit": 50}
        if cursor:
            body["cursor"] = cursor
        resp = _api("openapi/wiki/v1/get_knowledge_list", body)
        if resp.get("code") not in (0, None):
            raise RuntimeError(f"get_knowledge_list failed: {resp.get('code')} {resp.get('msg')}")
        d = resp.get("data") or {}
        for it in (d.get("knowledge_list") or []):
            t = it.get("title")
            if t:
                titles.append(t)
        nxt = d.get("next_cursor") or ""
        if d.get("is_end") or not nxt or nxt == cursor:
            break
        cursor = nxt
    return titles


def recent_trade_days(n, include_today=False):
    """最近 n 个交易日（默认不含今天——selfcheck 早间跑，当天报告尚未产出）。"""
    out, cur = [], datetime.now().date() if include_today else datetime.now().date() - timedelta(days=1)
    guard = 0
    while len(out) < n and guard < 60:
        if _is_trade_day(cur):
            out.append(cur)
        cur -= timedelta(days=1)
        guard += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--kb-id", default=os.environ.get("IMA_KB_ID") or DEFAULT_KB)
    ap.add_argument("--lookback", type=int, default=3, help="回看最近 N 个交易日（不含今天）")
    ap.add_argument("--date", default="", help="只检查指定日期 YYYY-MM-DD")
    ap.add_argument("--include-today", action="store_true", help="把今天也纳入检查")
    ap.add_argument("--no-auction", action="store_true", help="跳过「竞价统计」检查（该链路周一至五独立跑）")
    ap.add_argument("--strict", action="store_true", help="有缺失则 exit 1")
    a = ap.parse_args()

    kb_id = (a.kb_id or DEFAULT_KB).strip()
    if not kb_id.startswith("ima_kb_"):
        print(f"::warning::IMA_KB_ID 不是新格式（{kb_id[:16]}…），检查可能失败")

    days = [datetime.strptime(a.date, "%Y-%m-%d").date()] if a.date else recent_trade_days(a.lookback, a.include_today)
    checks = list(CHECKS)
    if a.no_auction:
        checks = [c for c in checks if c[0] != "竞价统计"]

    # ── 逐文件夹取一次标题（复用，避免逐日重复拉取）──
    folder_titles, errors = {}, []
    for name, fid, _tpl in checks:
        if fid in folder_titles:
            continue
        try:
            folder_titles[fid] = list_titles(kb_id, fid)
        except Exception as e:
            folder_titles[fid] = None
            errors.append(f"{name}({fid}) 列举失败: {e}")
            print(f"::warning::{name} 列举失败：{e}")

    rows, missing = [], []
    for d in sorted(days, reverse=True):
        ds = d.strftime("%Y-%m-%d")
        row = {"date": ds, "cells": {}, "ok": True}
        for name, fid, tpl in checks:
            titles = folder_titles.get(fid)
            if titles is None:
                row["cells"][name] = "⚠️取数失败"
                row["ok"] = False
                continue
            if tpl is None:                       # 任意含日期文件
                n = sum(1 for t in titles if ds in t)
                row["cells"][name] = (f"✅{n}份" if n else "❌缺")
            else:
                key = tpl.format(date=ds)[:-3]    # 去掉 .md，兼容 _prev_ 归档
                n = sum(1 for t in titles if t.startswith(key))
                row["cells"][name] = (f"✅{n}份" if n else "❌缺")
            if row["cells"][name].startswith("❌"):
                row["ok"] = False
                missing.append(f"{ds} · {name}")
        rows.append(row)

    ok = all(r["ok"] for r in rows) and not errors
    stamp = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(a.out, exist_ok=True)

    # ── Markdown ──
    L = [f"# 🩺 知识库上传健康检查（{stamp}）", "",
         f"> 目标知识库：`{kb_id}`（报告）｜ 检查口径：从 **KB 侧反查**，而非只看 workflow 结论",
         f"> 检查范围：{len(days)} 个交易日（{'、'.join(d.strftime('%Y-%m-%d') for d in sorted(days, reverse=True))}）"
         f"｜ 状态：{'✅ 全部齐全' if ok else '⚠️ 存在缺失'}", ""]
    head = "| 日期 | " + " | ".join(c[0] for c in checks) + " | 结论 |"
    L += [head, "|:--|" + ":-:|" * len(checks) + ":--|"]
    for r in rows:
        cells = " | ".join(r["cells"].get(c[0], "-") for c in checks)
        L.append(f"| {r['date']} | {cells} | {'✅ 齐全' if r['ok'] else '⚠️ 缺失'} |")
    if missing:
        L += ["", "## ⚠️ 缺失清单", ""] + [f"- {m}" for m in missing]
        L += ["", "> 排查建议：① grep 当日 run 日志中的 `220004`（kb_id 失效）/ `::error::upload_ima`；"
                  "② 确认 `IMA_KB_ID` secret 为新格式 `ima_kb_XXXXXXXX`；"
                  "③ 确认对应 workflow 当日是否真的运行过。"]
    if errors:
        L += ["", "## ⚠️ 取数异常", ""] + [f"- {e}" for e in errors]
    L += ["", "---", "> 本检查只反映「文件是否进了知识库」，不校验报告内容正确性。"]
    md = "\n".join(L) + "\n"
    for fn in (os.path.join(a.out, f"kb_health_{stamp}.md"), os.path.join(a.out, "kb_health_latest.md")):
        open(fn, "w", encoding="utf-8").write(md)
    js = {"date": stamp, "kb_id": kb_id, "ok": ok,
          "days": [r["date"] for r in rows], "rows": rows, "missing": missing, "errors": errors}
    json.dump(js, open(os.path.join(a.out, "kb_health_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(md)
    if not ok:
        print("::warning::知识库上传健康检查发现缺失：" + "；".join(missing[:6]) + ("…" if len(missing) > 6 else ""))
    if a.strict and not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
