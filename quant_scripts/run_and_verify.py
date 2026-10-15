#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_and_verify.py —— 生产者「产出后自检」通用 wrapper（2026-10-15）

背景：workflow 中大量 `python3 X ... || echo "X失败(非致命)"` + `continue-on-error: true`
      → 生产者失败（尤其 argparse 秒退）被静默吞掉，CI 仍绿，产物断更无人知。
      （实证：pool_tracking_report.py 因未知参数 argparse 秒退，断更 60+ 天无告警）

本工具做三件事（可独立使用，也可串在生产者后面）：
  1) 可选先执行命令（--run "<shell>"），记录 rc 与耗时
  2) 校验期望产物：存在 / ≥min-bytes / （可选）含指定文本
  3) 异常时：打印 GitHub 注解(::error/::warning::) + 追加 outputs/silent_failures_{date}.log
     + 可选 PushPlus 微信推送（--push，env PUSH_TOKEN）

识别「秒退」：命令耗时 < --min-runtime（默认 0 关闭）即告警 —— argparse/导入错误通常 <1s。

用法：
  # A. 包裹执行 + 自检（推荐）
  python3 quant_scripts/run_and_verify.py --tag "第五步·股池跟踪" \
    --run "python3 quant_scripts/pool_tracking_report.py --push --auto-extend --holdings-file holdings.txt" \
    --expect "outputs/股池标的跟踪报告_{date}.md" --min-bytes 500 --min-runtime 2 --push

  # B. 仅自检（放在一步末尾）
  python3 quant_scripts/run_and_verify.py --tag "扫描核心产物" \
    --expect "quant_results_latest.json" --min-bytes 300 \
    --expect "market_width_latest.json" --expect "outputs/涨停概念排行_latest.json"

退出码：全部通过 →0；有问题 →1（放在无 continue-on-error 的步骤会显式失败）。
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.getcwd()


def _now_bj():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=8)


def today_bj():
    return _now_bj().strftime("%Y-%m-%d")


def gha(msg, kind="error"):
    """GitHub Actions 注解（在 run 摘要/日志中高亮）。"""
    m = msg.replace("\n", " ").replace("::", ":")
    print("::%s::%s" % (kind, m), flush=True)


def expand(pat, date):
    return pat.replace("{date}", date).replace("{today}", date)


def check_one(pat, date, min_bytes, must_contain=None):
    """→ (ok: bool, detail: str)。模式支持 {date}/{today} 与 * 通配。"""
    p = expand(pat, date)
    matches = sorted(glob.glob(p))
    if not matches:
        return False, "缺失 MISSING: %s" % p
    ok, bad, biggest = True, [], (None, -1)
    for m in matches:
        try:
            sz = os.path.getsize(m)
        except OSError:
            sz = -1
        if sz > biggest[1]:
            biggest = (m, sz)
        if sz < min_bytes:
            ok = False
            bad.append("过小 TOO_SMALL: %s (%dB<%dB)" % (m, sz, min_bytes))
        if must_contain:
            try:
                txt = open(m, encoding="utf-8", errors="ignore").read()
            except Exception:
                txt = ""
            if must_contain not in txt:
                ok = False
                bad.append("缺文本 MISSING_TEXT(%s): %s" % (must_contain, m))
    if ok:
        return True, "OK: %s → %d 个文件，最大 %s (%dB)" % (p, len(matches), biggest[0], biggest[1])
    return False, "; ".join(bad)


def _push(title, body):
    token = os.environ.get("PUSH_TOKEN", "")
    if not token:
        print("[push] 跳过（PUSH_TOKEN 未设置）")
        return
    try:
        data = urllib.parse.urlencode({"token": token, "title": title, "content": body,
                                       "template": "markdown"}).encode()
        req = urllib.request.Request("http://www.pushplus.plus/send", data=data)
        urllib.request.urlopen(req, timeout=20).read()
        print("[push] 已推送微信")
    except Exception as e:
        print("[push] 推送失败:", e)


def main():
    ap = argparse.ArgumentParser(description="生产者产出后自检 wrapper")
    ap.add_argument("--expect", action="append", default=[], help="期望产物（可多次；支持 {date} 与 *）")
    ap.add_argument("--date", default="", help="基准日期 YYYY-MM-DD（默认今天·北京）")
    ap.add_argument("--min-bytes", type=int, default=200, help="产物最小字节数（默认 200）")
    ap.add_argument("--tag", default="", help="标签（写日志/推送标题用）")
    ap.add_argument("--log", default="", help="失败落盘日志（默认 outputs/silent_failures_{date}.log）")
    ap.add_argument("--run", default="", help="先执行的 shell 命令（可选）")
    ap.add_argument("--min-runtime", type=float, default=0.0,
                    help="秒退阈值(秒)：命令耗时低于此值即告警（0=关闭）")
    ap.add_argument("--push", action="store_true", help="失败时 PushPlus 推送（env PUSH_TOKEN）")
    ap.add_argument("--quiet", action="store_true", help="成功时不打印 OK 明细")
    a = ap.parse_args()

    date = a.date or today_bj()
    tag = a.tag or "producer"
    log = a.log or os.path.join("outputs", "silent_failures_%s.log" % date)

    rc, dur = None, 0.0
    if a.run:
        cmd = expand(a.run, date)          # 命令内同样支持 {date}/{today} 占位
        t0 = time.time()
        try:
            rc = subprocess.run(cmd, shell=True).returncode
        except Exception as e:
            rc = 127
            print("[run] 执行异常:", e, flush=True)
        dur = time.time() - t0

    problems = []
    if rc is not None and rc != 0:
        problems.append("命令退出码非零 CMD_RC=%d: %s" % (rc, a.run.replace("\n", " ")))
    if rc is not None and a.min_runtime > 0 and dur < a.min_runtime:
        problems.append("疑似秒退 SECONDS_EXIT: 仅运行 %.2fs < %.1fs（参数/导入错误常见特征）"
                        % (dur, a.min_runtime))

    ok_details = []
    for pat in a.expect:
        ok, detail = check_one(pat, date, a.min_bytes)
        (ok_details if ok else problems).append(detail)

    head = "[%s] date=%s cmd_rc=%s dur=%.1fs expect=%d" % (tag, date, rc, dur, len(a.expect))
    if not problems:
        print("%s | ✅ ALL OK" % head)
        if not a.quiet:
            for d in ok_details:
                print("   ", d)
        return 0

    print("%s | ❌ PROBLEMS=%d" % (head, len(problems)), flush=True)
    lines = []
    for p in problems:
        print("   -", p, flush=True)
        gha("%s: %s" % (tag, p), kind="error")
        lines.append("%s\t%s\t%s" % (_now_bj().strftime("%Y-%m-%d %H:%M:%S"), tag, p))
    try:
        os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("   详情 →", log, flush=True)
    except Exception as e:
        print("   [warn] 写日志失败:", e, flush=True)

    if a.push:
        _push("⚠️ 生产者自检异常 · %s" % tag,
              "**%s** (%s)\n\n" % (tag, date) + "\n".join("- " + p for p in problems))
    return 1


if __name__ == "__main__":
    sys.exit(main())
