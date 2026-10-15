#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""param_contract_audit.py —— 参数契约审计（2026-10-16 · 数据可信度治理 11.6）

背景：与 artifact_audit（产物契约）互补，本工具审计「参数契约」——
  ① 已实证：pool_tracking_report.py 因 workflow 传了脚本未定义的参数 → argparse 秒退 → 断更 60+ 天
  ② 已实证：gen_mainboard.py 不解析任何参数，但 workflow 传 `--universe chinext_kcb`
     → 参数被静默忽略 → all_chinext_kcb.csv 从未生成 → 下游 if [ -f ] 分支永恒跳过（自 2026-08-11）
  这类「传了参数但脚本不认」的静默失效，CI 永远绿、产物永远缺，靠人眼极难发现。

做法：静态比对「workflow 调用脚本时传的 --选项」vs「脚本源码中出现的 --选项」，
      列出「传了但脚本从不识别」的失配（含手写 sys.argv 脚本——它们不会秒退，只会静默忽略，更隐蔽）。

用法：
  python3 quant_scripts/param_contract_audit.py [--repo DIR] [--out DIR] [--strict]
退出码：默认 0（report-only）；--strict 时有失配 → 1（供 CI 告警）。
"""
import argparse
import glob
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ART = "param_contract"


def _today():
    return (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)).strftime("%Y-%m-%d")


def known_args(src):
    """脚本「已知参数」的宽松集合：argparse add_argument + 源码中的 --选项 字符串字面量。
    宽松是为了低误报（宁可漏报也不误伤）；对「脚本完全不解析参数」的脚本，集合为空 → 任何传参都判失配。"""
    known = set()
    for m in re.finditer(r'add_argument\(\s*["\'](-{1,2}[A-Za-z][\w\-]*)["\']', src):
        known.add(m.group(1))
    for m in re.finditer(r'["\'](-{1,2}[A-Za-z][\w\-]*)["\']', src):
        known.add(m.group(1))
    return known


def find_script(root, rel):
    for cand in (os.path.join(root, "quant_scripts", rel), os.path.join(root, rel)):
        if os.path.exists(cand):
            return cand
    return None


def main():
    ap = argparse.ArgumentParser(description="参数契约审计")
    ap.add_argument("--repo", default=os.getcwd(), help="仓库根（默认当前目录）")
    ap.add_argument("--out", default="outputs", help="输出目录")
    ap.add_argument("--strict", action="store_true", help="有失配则退出码 1")
    a = ap.parse_args()
    root = a.repo
    cache = {}

    def kn(rel):
        if rel not in cache:
            fp = find_script(root, rel)
            cache[rel] = known_args(open(fp, encoding="utf-8", errors="ignore").read()) if fp else None
        return cache[rel]

    problems = []
    n_calls = 0
    for wf in sorted(glob.glob(os.path.join(root, ".github/workflows/*.yml"))):
        raw = open(wf, encoding="utf-8", errors="ignore").read()
        merged = re.sub(r"\\\s*\n\s*", " ", raw)   # 折叠续行
        for m in re.finditer(r"python3\s+([\w./\-]+\.py)([^\n]*)", merged):
            rel = m.group(1)
            rest = re.split(r"\|\||&&|[|;&<>]|\$\(|\)", m.group(2))[0]
            passed = [t.split("=")[0] for t in rest.split() if t.startswith("-")]
            passed = [p for p in passed if len(p) > 1 and not p.startswith("---")]
            if not passed:
                continue
            n_calls += 1
            ka = kn(rel)
            if ka is None:
                continue
            miss = [p for p in passed if p not in ka and p.replace("=", "") not in ka]
            if miss:
                problems.append({"wf": os.path.basename(wf), "script": rel,
                                 "missing": sorted(set(miss)), "known": sorted(ka)})

    lines = ["# 🔗 参数契约审计 · %s" % _today(), "",
             "> 扫描 %d 个带参调用 ｜ 失配 **%d**" % (n_calls, len(problems)), ""]
    if problems:
        lines += ["## ❌ 参数失配（workflow 传了但脚本未识别）", "",
                  "| workflow | 脚本 | 失配参数 | 脚本已知参数 |", "|---|---|---|---|"]
        for p in problems:
            lines.append("| %s | `%s` | `%s` | %s |" % (
                p["wf"], p["script"], " ".join(p["missing"]),
                " ".join(p["known"][:10]) or "(无)"))
    else:
        lines.append("## ✅ 无失配")
    md = "\n".join(lines) + "\n"
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, ART + "_latest.md"), "w", encoding="utf-8").write(md)
    json.dump({"date": _today(), "calls": n_calls, "mismatches": problems},
              open(os.path.join(a.out, ART + "_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("[param_contract] calls=%d mismatches=%d" % (n_calls, len(problems)))
    for p in problems:
        print("  - [%s] %s : %s" % (p["wf"], p["script"], " ".join(p["missing"])))
    return 1 if (problems and a.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
