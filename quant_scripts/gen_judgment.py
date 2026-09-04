#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前预判(judgment)生成与推送 — 盘前报告生成后必须执行的闭环步骤。
背景(2026-09-04): 8/11固化丢失后 judgment 断链(8/12起缺/9/1一次/9/2+断),
复盘验证只能"推断"→ 预判质量无法积累。本脚本强制"报告→预判落盘→GitHub推送"。

用法:
  python3 gen_judgment.py --date 2026-09-05 --direction "震荡反弹" \
      --key-levels "上证支撑3930、压力3968" --position "30-50%" \
      --main-lines "AI算力/液冷,贵金属,航运港口" \
      --three-systems "fish:73偏热;beast:45.7中性;shuangxian:45中性" \
      --risk "年线广度26.4%熊结构;情绪3日降温" [--no-push]

或从报告文件自动提取(--from-md 盘前市场报告_YYYY-MM-DD.md)：解析信号卡/决策段生成。
输出: premarket_judgment_{date}.json + premarket_judgment_latest.json(本地outputs/ + 推GitHub根)
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import base64

REPO = "wuhj-hub/bg"
BRANCH = "main"
OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "outputs"))


def push_to_github(local_path, remote_name):
    """Contents API 推送文件到 GitHub 仓库根"""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("⚠️ 无 GITHUB_TOKEN，跳过推送（文件已存本地）", file=sys.stderr)
        return False
    api = f"https://api.github.com/repos/{REPO}/contents/"

    def req(url, method="GET", body=None):
        r = urllib.request.Request(url, method=method)
        r.add_header("Authorization", f"token {token}")
        r.add_header("User-Agent", "curl")
        r.add_header("Accept", "application/vnd.github+json")
        data = None
        if body is not None:
            r.add_header("Content-Type", "application/json")
            data = json.dumps(body).encode()
        try:
            with urllib.request.urlopen(r, data=data, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:200]

    ok = True
    for remote in (remote_name, "premarket_judgment_latest.json"):
        url = api + urllib.parse.quote(remote, safe="/")
        content = open(local_path, encoding="utf-8").read()
        st, d = req(url)
        body = {"message": f"chore: update premarket judgment ({remote_name})",
                "content": base64.b64encode(content.encode()).decode()}
        if st == 200:
            body["sha"] = d["sha"]
        st2, _ = req(url, "PUT", body)
        if st2 not in (200, 201):
            print(f"❌ 推送 {remote} 失败 HTTP {st2}", file=sys.stderr)
            ok = False
        else:
            print(f"✅ 推送 {remote} → GitHub")
    return ok


def extract_from_md(md_path, date):
    """从盘前报告 md 自动提取预判要素（信号卡+决策段+板块+纪律）"""
    md = open(md_path, encoding="utf-8").read()
    def clean(s):
        return re.sub(r"[*#`>]", "", s).strip()
    def grab(pattern, default=""):
        m = re.search(pattern, md, re.S)
        return clean(m.group(1)) if m else default
    direction = grab(r"综合决策[：:]\s*([^\n]+)")
    # 关键位: 优先数字对(支撑X压力Y), 报告常为 "支撑 3930（9/3低）/压力 3968（9/3高）"
    sm = re.search(r"支撑\s*[（(]?\s*(\d{4,5}(?:\.\d+)?)", md)
    pm = re.search(r"压力\s*[（(]?\s*(\d{4,5}(?:\.\d+)?)", md)
    key_levels = f"支撑{sm.group(1)}、压力{pm.group(1)}" if sm and pm else grab(r"关键位[：:]\s*([^\n]+)")
    pos = grab(r"仓位[：:\s]*([0-9]+%[^，。\n]*)")
    # 主线: 从 ⑥操作纪律 的"主线："行 或 ③主线判定后段落提取
    ml = re.search(r"主线[：:]\s*([^\n]+)", md)
    main_lines = []
    if ml:
        raw = clean(ml.group(1))
        for x in re.split(r"[、，,/;；]", raw):
            x = re.sub(r"\*|\d+\.?\s*", "", x).strip()
            if x and len(x) <= 14 and not x.startswith(("若", "等", "回避", "不追", "回调", "关注")):
                main_lines.append(x)
        main_lines = main_lines[:4]
    # 风险: ⑥利空行或"⚠️"提示
    lb = re.search(r"\*\*利空\*\*[：:]([^\n]+)", md)
    risk = clean(lb.group(1)) if lb else grab(r"回避[：:]\s*([^\n]+)")
    return {"date": date,
            "direction": (direction[:60] or "未提取到(请手动--direction)").split("，")[0] + "（详见报告）",
            "key_levels": key_levels[:60] or "未提取",
            "position": pos[:30] or "30-50%",
            "main_lines": main_lines or ["未提取"],
            "risk": risk[:120] or ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="交易日 YYYY-MM-DD")
    ap.add_argument("--from-md", help="从盘前报告 md 自动提取")
    ap.add_argument("--direction"); ap.add_argument("--key-levels")
    ap.add_argument("--position"); ap.add_argument("--main-lines", help="逗号分隔")
    ap.add_argument("--three-systems", help="格式 fish:73;beast:45;shuangxian:45")
    ap.add_argument("--risk")
    ap.add_argument("--no-push", action="store_true", help="只生成不推送")
    args = ap.parse_args()

    if args.from_md:
        d = extract_from_md(args.from_md, args.date)
    else:
        d = {"date": args.date}
    for k, v in [("direction", args.direction), ("key_levels", args.key_levels),
                 ("position", args.position), ("risk", args.risk)]:
        if v:
            d[k] = v
    if args.main_lines:
        d["main_lines"] = [x.strip() for x in args.main_lines.split(",") if x.strip()]
    if args.three_systems:
        ts = {}
        for part in args.three_systems.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                ts[k.strip()] = v.strip()
        d["three_systems"] = ts
    d.setdefault("generated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    d.setdefault("main_lines", [])
    d.setdefault("risk", "")
    # Schema 统一（2026-09-04）：复盘侧(gen_review_report)读 tone/operation/sectors/key_levels，
    # 兼容旧扩展字段 direction/position/main_lines——双向补齐避免验证读空
    d["tone"] = d.get("tone") or d.get("direction", "")            # 大盘方向/基调
    d["operation"] = d.get("operation") or (f"仓位{d.get('position','')}（详见报告）" if d.get("position") else "")
    sec = d.get("sectors") or ("、".join(d.get("main_lines", [])[:3]) if d.get("main_lines") else "")
    d["sectors"] = sec                                             # 板块方向
    d["key_levels"] = d.get("key_levels", "")
    d["direction"] = d.get("direction") or d["tone"]               # 扩展字段同步

    os.makedirs(OUT_DIR, exist_ok=True)
    local = os.path.join(OUT_DIR, f"premarket_judgment_{args.date}.json")
    with open(local, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"✅ 生成 {local}")
    print(json.dumps(d, ensure_ascii=False, indent=1)[:500])

    if not args.no_push:
        ok = push_to_github(local, f"premarket_judgment_{args.date}.json")
        if not ok:
            sys.exit(1)
    else:
        print("(dry-run: 未推送)")
    # 自检提示
    if d.get("date") != args.date:
        print("⚠️ date 字段不一致!", file=sys.stderr)
        sys.exit(1)
    print(f"✅ judgment 闭环完成: date={d['date']} 方向={d.get('direction','')[:30]}")


if __name__ == "__main__":
    main()
