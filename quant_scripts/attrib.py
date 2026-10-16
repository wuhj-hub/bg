#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""attrib.py —— 体系自检「归因」层（B1）
=========================================================
把自检的「X 失败」升级为「X 失败，**疑似因为 Y**」——**只建议、不自动改**。

输入（有则读，缺则略）：
  outputs/artifact_audit.json        产物入库审计（高危断链/陈旧副本/绕过读取）
  outputs/pipeline_audit.json        流水线巡检（run 异常/重步骤/产物停更/脚本假绿）
  outputs/silent_failure_audit.json  静默失败元审计（吞错面）
  outputs/param_contract_latest.json 参数契约审计（传参失配）
  outputs/cross_source_latest.json   数据源交叉验证
输出：
  outputs/归因_latest.md + outputs/attrib_latest.json

用法：
  python3 quant_scripts/attrib.py --out outputs [--push]

设计原则：
  1. **只读 + 只建议**：绝不自动修改任何代码/产物（避免"自动修复制造新静默故障"）。
  2. 规则 + **跨信号关联**（如"产物停更"×"同期 run 异常" → 归因到 run）。
  3. 每条给出**置信度**（高/中/低）与**证据来源**，便于人工复核。
"""
import os
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _s(v, n=140):
    return str(v)[:n].replace("\n", " ")


def collect(outdir):
    o = outdir
    return {
        "art":  _load(os.path.join(o, "artifact_audit.json")),
        "pipe": _load(os.path.join(o, "pipeline_audit.json")),
        "meta": _load(os.path.join(o, "silent_failure_audit.json")),
        "pc":   _load(os.path.join(o, "param_contract_latest.json")),
        "cs":   _load(os.path.join(o, "cross_source_latest.json")),
    }


def analyze(d):
    """返回 [(severity, 现象, 证据, 疑似原因, 建议, 置信度)]"""
    items = []

    def add(sev, phen, ev, cause, advice, conf):
        items.append((sev, phen, ev, cause, advice, conf))

    art, pipe, meta, pc, cs = d["art"], d["pipe"], d["meta"], d["pc"], d["cs"]

    # 跨信号：本期是否存在 run 异常（用于给"产物停更"归因）
    bad_runs = (pipe or {}).get("runs", {}).get("bad") or []

    # ① 高危断链
    if art:
        for n in (art.get("high_risk") or []):
            add("🔴", f"产物断链：{n}",
                "artifact_audit.high_risk（被消费方读取但从未提交）",
                "① 该产物未进 git_api_commit 提交清单；或 ② 提交步早于生成步",
                "把该产物加入对应 workflow 提交清单；核对生成步是否在提交步之前", "高")
        for n in (art.get("dup_stale") or []):
            add("🟠", f"陈旧副本：{n}",
                "artifact_audit.dup_stale（仓库根 vs outputs 日期不一致）",
                "生产者作业 ≠ 消费者作业 → 某副本冻结、长期未被更新",
                "消费方改走 report_io.load_latest；把副本纳入提交清单或删除冻结副本", "高")
        for b in (art.get("reader_bypass") or [])[:8]:
            add("🟡", f"副本读取旁路：{b.get('consumer')}",
                f"未走 report_io.load_latest（{b.get('artifact')}）",
                "消费方直接 open() 读多副本产物，可能读到冻结副本",
                "改用 report_io.load_latest（编写期预警，非故障）", "低")

    # ② 参数失配
    if pc and pc.get("mismatches"):
        for m in (pc.get("mismatches") or [])[:12]:
            add("🟠", "参数契约失配", _s(m),
                "workflow 传了脚本未识别的 --选项（或脚本完全无参数解析）",
                "对齐脚本 argparse 与 workflow 调用（param_contract_audit --strict）", "高")

    # ③ 脚本异常（假绿）
    if pipe:
        for e in (pipe.get("script_errors") or []):
            add("🔴", f"脚本异常(假绿)：{e.get('module')}", _s(e.get("error")),
                "脚本 rc≠0 被 continue-on-error 吞掉，作业仍绿",
                "打开该步日志/stdout；确需吞错必须留痕（run_and_verify / 显式告警）", "中")

    # ④ run 异常
    for b in bad_runs:
        add("🔴", f"run 失败：{b.get('name')}",
            f"{b.get('created')} → {b.get('conclusion')}",
            "该 workflow 执行失败（根因见其失败步日志）",
            "打开该 run 的失败步日志；若与某产物停更同时出现，则很可能是同一根因", "中")

    # ⑤ 产物停更（× run 关联）
    if pipe:
        if pipe.get("freshness_skipped"):
            items.append(("ℹ️", "产物新鲜度检查", "休市日跳过（非交易日，正常）", "—", "无需处理", "高"))
        else:
            for s in (pipe.get("stale_products") or []):
                cause = "① 生产该产物的 workflow 未跑/失败；或 ② 非交易日；或 ③ 路径/文件名变更"
                conf = "中"
                if bad_runs:
                    cause = "疑为①：**同期存在 run 异常**（详见上表），很可能是上游失败导致下游产物未更新"
                    conf = "中高"
                add("🟡", f"产物停更：{s.get('path')}", _s(s.get("status")),
                    cause, "看该产物 producer 的最近 run 状态；确认是否休市；核对路径/文件名", conf)

    # ⑥ 重步骤（性能，非正确性）
    if pipe:
        for h in (pipe.get("heavy_steps") or []):
            add("🟡", f"重步骤：{h.get('workflow')}/{h.get('step')}", f"{h.get('minutes')}min",
                "取数调用次数多 / 未走 fetch 免 npx / 全市场逐只",
                "迁移到 fetch 层（减少调用次数）或增大批量（性能问题，非正确性）", "低")

    # ⑦ 静默失败（吞错面）
    if meta and meta.get("high_risk"):
        for i in (meta.get("issues") or [])[:12]:
            add("🟠", "吞错面（静默失败）", _s(i),
                "continue-on-error 吞掉了错误（作业仍绿）",
                "为该步加留痕：run_and_verify 或显式 ::warning::/告警", "中")

    # ⑧ 数据源（仅当显式不一致字段存在）
    if cs:
        vs = cs.get("diffs") or cs.get("mismatch") or cs.get("inconsistent")
        if vs:
            add("🟠", "数据源不一致", _s(vs), "源抖动（东财/推送源波动）或字段口径差异",
                "确认是否机会源离线；比对四源收盘价差是否超阈", "中")

    # 排序：🔴 > 🟠 > 🟡 > ℹ️
    order = {"🔴": 0, "🟠": 1, "🟡": 2, "ℹ️": 3}
    items.sort(key=lambda x: order.get(x[0], 9))
    return items


def render(items, outdir):
    today = datetime.now(BJT).strftime("%Y-%m-%d %H:%M")
    real = [i for i in items if i[0] != "ℹ️"]
    L = [f"# 🧭 体系自检 · 归因分析 · {today}", "",
         "> 输入：artifact_audit / pipeline_audit / silent_failure / param_contract / cross_source（缺者略）",
         "> **只建议、不自动改**；「疑似原因」为规则 + 跨信号推断，附**置信度**，请人工复核。", ""]
    if not real:
        L += ["## ✅ 未发现需归因的异常", ""]
        for i in items:
            L.append(f"- {i[0]} {i[1]}：{i[3]}")
    else:
        cnt = {s: sum(1 for i in real if i[0] == s) for s in ("🔴", "🟠", "🟡")}
        L += [f"**汇总**：🔴 {cnt['🔴']} ｜ 🟠 {cnt['🟠']} ｜ 🟡 {cnt['🟡']}", ""]
        for sev in ("🔴", "🟠", "🟡"):
            grp = [i for i in real if i[0] == sev]
            if not grp:
                continue
            label = {"🔴": "高危", "🟠": "中", "🟡": "提示"}[sev]
            L += [f"## {sev} {label}（{len(grp)}）", "",
                  "| 现象 | 证据 | 疑似原因 | 建议 | 置信 |", "|---|---|---|---|---|"]
            for _, phen, ev, cause, advice, conf in grp:
                L.append(f"| {phen} | {ev} | {cause} | {advice} | {conf} |")
            L.append("")
    L += ["---", "> 归因层（B1）：**只建议、不自动改**。自动修复（B2）暂缓——避免误修制造新的静默故障。", ""]
    md = "\n".join(L)
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, "归因_latest.md"), "w", encoding="utf-8").write(md)
    json.dump({"date": today, "counts": {"red": sum(1 for i in real if i[0] == '🔴'),
                                         "orange": sum(1 for i in real if i[0] == '🟠'),
                                         "yellow": sum(1 for i in real if i[0] == '🟡')},
               "items": [{"sev": a, "phen": b, "evidence": c, "cause": d_, "advice": e, "conf": f}
                         for a, b, c, d_, e, f in items]},
              open(os.path.join(outdir, "attrib_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return md, real


def main():
    ap = argparse.ArgumentParser(description="体系自检·归因层（B1：只建议不自动改）")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    items = analyze(collect(a.out))
    md, real = render(items, a.out)
    print(md)
    if a.push and real:
        tk = os.environ.get("PUSH_TOKEN", "")
        if tk:
            import urllib.request
            lines = [f"{s} {p}" for s, p, *_ in real[:8]]
            body = json.dumps({"token": tk, "title": f"🧭体系自检·归因 {len(real)}项",
                               "content": "\n".join(lines), "template": "txt"})
            try:
                urllib.request.urlopen(urllib.request.Request(
                    "https://pushplus.plus/send", data=body.encode(),
                    headers={"Content-Type": "application/json"}), timeout=15)
            except Exception:
                pass


if __name__ == "__main__":
    main()
