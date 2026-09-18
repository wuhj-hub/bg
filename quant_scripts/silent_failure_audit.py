#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""silent_failure_audit.py —— 体系自检的「元审计」（2026-09-18）
============================================================
补的缺口：体系有 data_guard（产物可信度）、artifact_audit（写了没提交），
         但【没有东西审计 workflow 本身】—— 也就是"报 success 但实际没干活"的假绿。

背景案例（都真实发生过）：
  · 提交 step 用 ${{ github.token }} 做 PUT，但没声明 permissions: contents: write
    → PUT 403，step 仍报 success，只在日志打 [ERR] 静默跳过
    → 9/14 六 workflow 全绿而数据全空
  · `|| true` / `continue-on-error: true` 把子进程非零返回吞掉
    → 双弦静默崩溃 3 天，workflow 全 success
  · schedule cron 被注释后忘配外部 dispatch → 永远不会自动跑

本脚本静态扫描 .github/workflows/*.yml，输出四类风险：
  ①【假绿·高危】用 github.token 提交但缺 permissions: contents: write
  ②【静默失败】吞错误的步骤清单（|| true / continue-on-error / 2>/dev/null）
  ③【调度死链】无有效 schedule 且无 repository_dispatch → 不会自动运行
  ④【产物漏交】关键产物未出现在任何 workflow 的提交列表

用法:
  python3 silent_failure_audit.py --repo . --out outputs [--strict]
"""
import argparse, json, os, re, sys
from datetime import datetime

# 体系关键产物 —— 必须被某个 workflow 提交，否则消费方读到陈旧/空数据
KEY_ARTIFACTS = [
    "quant_results_latest.json", "market_width_latest.json", "hot_emotion_latest.json",
    "market_regime_latest.json", "sector_component_em.json", "panhou_lianghua.csv",
    "mode_aggregate_latest.json", "cross_source_latest.json",
]

# 吞错误的写法（命中即为静默失败风险点）
SWALLOW_PATTERNS = [
    (r"\|\|\s*true\b", "|| true"),
    (r"continue-on-error:\s*true", "continue-on-error: true"),
    (r"set\s*\+e", "set +e"),
    (r"\|\|\s*echo\b", "|| echo（吞错误）"),
    (r"2>\s*/dev/null", "2>/dev/null（屏蔽 stderr）"),
    (r"\|\|\s*:\s*$", "|| :"),
]

# 纯手动调试/探测工具：不自动跑是设计意图，不算死链
MANUAL_TOOLS = {"probe_em.yml", "probe_kpl.yml", "probe_search.yml", "probe_em_params.yml"}

# 核心脚本特征：吞错误发生在这些脚本上 → 升级为高危
CORE_HINTS = ["data_guard", "self_check", "market_width", "run_shuangxian", "beast",
              "fish_body", "hot_emotion", "signal_arbiter", "market_regime", "gen_"]


def parse_workflow(path):
    """轻量解析（不依赖 pyyaml）：返回 (text, steps[dict])"""
    text = open(path, encoding="utf-8", errors="ignore").read()
    lines = text.splitlines()
    steps, cur = [], None
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)- name:\s*(.+)$", ln)
        if m:
            if cur:
                steps.append(cur)
            cur = {"name": m.group(2).strip(), "line": i + 1, "body": []}
        elif cur is not None:
            # 下一个同级 step 或 job 边界
            if re.match(r"^\s{0,4}[a-z_]+:\s*$", ln) and "  " not in ln[:2]:
                steps.append(cur)
                cur = None
            else:
                cur["body"].append(ln)
    if cur:
        steps.append(cur)
    return text, steps


def audit_workflow(path):
    name = os.path.basename(path)
    text, steps = parse_workflow(path)
    issues = []
    low = text.splitlines()

    # ① 假绿：用 github.token / GH_TOKEN 提交但缺 permissions: contents: write
    uses_gh_token = bool(re.search(r"GH_TOKEN|github\.token", text))
    puts = bool(re.search(r"git push|contents/|curl.*-X\s*PUT", text))
    has_write = bool(re.search(r"permissions:\s*\n\s*contents:\s*write", text)) or \
                bool(re.search(r"permissions:\s*contents:\s*write", text))
    if uses_gh_token and puts and not has_write:
        issues.append({"level": "🔴高危·假绿", "step": "整个workflow",
                       "detail": "用 github.token 提交（git push / PUT Contents API）但未声明 "
                                 "permissions: contents: write → PUT 403 且 step 仍报 success，提交静默丢失"})

    # ② 静默失败热点
    for st in steps:
        body = "\n".join(st["body"])
        hits = [label for pat, label in SWALLOW_PATTERNS if re.search(pat, body)]
        if not hits:
            continue
        # 高危判据：吞错误 + 该步骤涉及「提交入库」或「关键产物生成」
        # （提交失败 = 数据静默丢失；产物失败 = 消费方读到陈旧/空数据）
        critical = bool(re.search(r"git push|git add|contents/|-X\s*PUT|upload_ima", body)) \
                   or any(h in body for h in ("hot_emotion", "market_width", "data_guard",
                                              "self_check", "market_regime", "sector_component",
                                              "gen_premarket", "gen_review"))
        core = any(h in body for h in CORE_HINTS) and critical
        issues.append({
            "level": "🔴高危·静默失败" if core else "🟡中危·吞错误",
            "step": f"{st['name']} (L{st['line']})",
            "detail": f"命中 {', '.join(sorted(set(hits)))}"
                      + ("；且包裹核心脚本 → 失败会被吞掉，workflow 仍绿" if core else ""),
        })

    # ③ 调度死链
    sched_lines = [l for l in low if re.match(r"^\s*(-\s*)?cron:", l)]
    active_cron = [l for l in sched_lines if not l.strip().startswith("#")]
    has_dispatch = bool(re.search(r"repository_dispatch", text))
    # 链式触发（被别的 workflow 唤起）也算「会自动跑」
    chained = bool(re.search(r"workflow_run|workflow_call", text))
    if not active_cron and not has_dispatch and not chained and name not in MANUAL_TOOLS:
        issues.append({"level": "🔴高危·调度死链", "step": "on: 段",
                       "detail": "无有效 schedule（cron 已注释/缺失）、无 repository_dispatch、也非链式触发 → 永远不会自动运行"})
    elif not active_cron and has_dispatch and not chained and name not in MANUAL_TOOLS:
        issues.append({"level": "🟡中危·依赖外部 cron", "step": "on: 段",
                       "detail": "原生 cron 已停用，仅靠外部 cron-job.org dispatch → 外部配置丢失即静默停摆"})

    # ④ 产物提交
    submitted = set(re.findall(r"([A-Za-z0-9_]+\.(?:json|csv|md|txt))", text))
    missing = [a for a in KEY_ARTIFACTS if a in text and a not in submitted]
    return name, issues, submitted, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--strict", action="store_true", help="有高危则 exit 1")
    a = ap.parse_args()

    wf_dir = os.path.join(a.repo, ".github", "workflows")
    files = sorted(f for f in os.listdir(wf_dir) if f.endswith((".yml", ".yaml"))) if os.path.isdir(wf_dir) else []
    if not files:
        print(f"[WARN] 未找到 workflow 目录: {wf_dir}", flush=True)
        sys.exit(0)

    date = datetime.now().strftime("%Y-%m-%d")
    all_issues, per_wf, covered = {}, {}, set()
    for f in files:
        name, issues, submitted, _ = audit_workflow(os.path.join(wf_dir, f))
        per_wf[name] = issues
        covered |= submitted
        for it in issues:
            all_issues.setdefault(it["level"], []).append(f"{name} :: {it['step']} — {it['detail']}")

    # ④ 全局：关键产物是否被任一 workflow 提交
    never = [x for x in KEY_ARTIFACTS if x not in covered]
    if never:
        all_issues.setdefault("🟡中危·产物漏交", []).append(
            "以下关键产物未出现在任何 workflow 提交列表：" + ", ".join(never))

    high = sum(len(v) for k, v in all_issues.items() if "高危" in k)

    L = [f"# 🔍 体系自检元审计 · {date}", "",
         f"> 扫描 {len(files)} 个 workflow ｜ 风险项 **{sum(len(v) for v in all_issues.values())}** ｜ 🔴高危 **{high}**", ""]
    for lvl in sorted(all_issues, key=lambda x: ("高危" not in x, "中危" not in x)):
        L += [f"## {lvl}（{len(all_issues[lvl])}）", ""] + [f"- {x}" for x in all_issues[lvl]] + [""]
    if not all_issues:
        L += ["## ✅ 未发现静默失败与调度死链", ""]

    # 明细表
    L += ["## 各 workflow 静默失败热点", "", "| workflow | 风险数 | 高危 |", "|---|---|---|"]
    for name in sorted(per_wf, key=lambda n: -len([i for i in per_wf[n] if "高危" in i["level"]])):
        hi = len([i for i in per_wf[name] if "高危" in i["level"]])
        L.append(f"| {name} | {len(per_wf[name])} | {hi if hi else '—'} |")
    L.append("")
    md = "\n".join(L)

    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, f"静默失败审计_{date}.md"), "w", encoding="utf-8").write(md)
    json.dump({"date": date, "workflows": len(files), "high_risk": high,
               "issues": all_issues, "per_workflow": per_wf},
              open(os.path.join(a.out, "silent_failure_audit.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(md, flush=True)
    if a.strict and high:
        sys.exit(1)


if __name__ == "__main__":
    main()
