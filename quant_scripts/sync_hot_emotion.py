#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 GitHub bg 仓库同步 hot_emotion 产物到本地 outputs/（盘前报告引用前调用）。
2026-09-03：hot_emotion 已接入 quant_scan.yml 每日 15:30 盘后自动生成，
ima 本地生成盘前报告前先同步最新产物；若 GitHub 无当日数据 → 返回非0并提示本地降级补跑。

用法: python3 sync_hot_emotion.py [--check-date YYYY-MM-DD]
  不带 --check-date：同步后打印 latest 日期/温度
  带 --check-date：若 GitHub latest.date != 目标日期 返回 exit 1（提示需要降级补跑）
"""
import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.parse

REPO = "wuhj-hub/bg"
BRANCH = "main"
# 候选远程路径：仓库根（workflow 每日提交的最新）→ skills_backup 备份目录（兜底）
REMOTE_CANDIDATES = [
    "hot_emotion_latest.json",
    "skills_backup/盘前市场报告/scripts/outputs/hot_emotion_latest.json",
    "hot_emotion_history.json",
    "skills_backup/盘前市场报告/scripts/outputs/hot_emotion_history.json",
]
LOCAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")


def gh_get(url):
    r = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        r.add_header("Authorization", f"token {token}")
    r.add_header("User-Agent", "curl")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-date", help="校验 GitHub latest 是否等于该日期（否则 exit 1）")
    args = ap.parse_args()

    os.makedirs(LOCAL_DIR, exist_ok=True)
    api = f"https://api.github.com/repos/{REPO}/contents/"
    ok = 0
    latest_date = None
    # 每个目标文件按候选顺序尝试
    targets = {}
    for cand in REMOTE_CANDIDATES:
        name = cand.split("/")[-1]
        targets.setdefault(name, []).append(cand)
    for name, candidates in targets.items():
        fetched = False
        for cand in candidates:
            url = api + urllib.parse.quote(cand, safe="/") + f"?ref={BRANCH}"
            st, d = gh_get(url)
            if st == 200 and isinstance(d, dict) and d.get("content"):
                content = base64.b64decode(d["content"]).decode("utf-8")
                with open(os.path.join(LOCAL_DIR, name), "w", encoding="utf-8") as fp:
                    fp.write(content)
                ok += 1
                fetched = True
                if name == "hot_emotion_latest.json":
                    try:
                        latest_date = json.loads(content).get("date")
                    except json.JSONDecodeError:
                        pass
                print(f"✅ {name} ← {cand}")
                break
        if not fetched:
            print(f"⚠️ {name} 全部候选同步失败")

    if ok == 0:
        print("❌ 全部同步失败", file=sys.stderr)
        sys.exit(1)

    # 打印状态
    try:
        with open(os.path.join(LOCAL_DIR, "hot_emotion_latest.json"), encoding="utf-8") as fp:
            d = json.load(fp)
        print(f"📊 latest date={d.get('date')} 温度={d.get('score', {}).get('score')}/{d.get('score', {}).get('level')} "
              f"涨停={d.get('total')} 连板={d.get('lianban_cnt')} 最高={d.get('max_lb')}板")
    except Exception as e:
        print(f"⚠️ latest 解析失败: {e}")

    if args.check_date and latest_date != args.check_date:
        print(f"❌ GitHub latest={latest_date} != 目标 {args.check_date} → 需本地降级补跑: "
              f"python3 hot_emotion.py --date {args.check_date} --westock --kline-file <kline文件> "
              f"--end-date {args.check_date}", file=sys.stderr)
        sys.exit(1)
    print("✅ 同步完成")


if __name__ == "__main__":
    main()
