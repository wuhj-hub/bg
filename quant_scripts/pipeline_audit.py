#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pipeline_audit.py —— 体系流水线自愈巡检器（2026-09-24）

背景：2026-09-23 出现两个「现有监控完全没发现」的异常：
  ① 鱼身脚本崩溃 → workflow 报 success（假绿），只有 stderr 里有 traceback；
  ② paper_tracker 逐只取数跑 3h → run 被 timeout 杀掉（conclusion=cancelled），
     而告警只监听 failure，cancelled/timeout 无人知。
→ 本脚本补上四类「漏检」：
  A. run 状态：failure / cancelled / timed_out（不只是 failure）
  B. 步骤耗时：单步骤 > 阈值 → 预警（超时前兆）
  C. 产物新鲜度：关键产物「停更 N 天」→ 预警（本次 paper_portfolio 49 天没更新无人知）
  D. 脚本异常：quant_results 各子模块 stderr 含 Traceback → 预警（覆盖「假绿」）

用法：
  python3 pipeline_audit.py [--days 2] [--step-min 25] [--json outputs/pipeline_audit.json] [--push]
"""
import os, re, json, time, argparse, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))
REPO = os.environ.get("BG_REPO", "wuhj-hub/bg")
TOK = os.environ.get("GITHUB_TOKEN", "")

# 关键产物：路径 → 允许的最大停更天数
FRESH = {
    "quant_results_latest.json": 1,
    "outputs/paper_portfolio.json": 2,
    "outputs/pool_entries.csv": 2,
    "market_width_latest.json": 1,
    "hot_emotion_latest.json": 1,
    "execution_cards_latest.json": 1,
    "market_regime_latest.json": 2,
    "outputs/sector_component_em.json": 5,
}


def api(path):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {TOK}", "Accept": "application/vnd.github+json", "User-Agent": "x"})
    for _ in range(3):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
        except Exception:
            time.sleep(2)
    return None


def api_commits(path, n=1):
    """某文件的最近提交（判断产物何时更新）"""
    return api(f"commits?path={urllib.parse.quote(path)}&per_page={n}")


# ── A. run 状态 ───────────────────────────────────────────────
def check_runs(days=2):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = api(f"actions/runs?per_page=100&created=%3E{urllib.parse.quote(since)}")
    bad, total = [], 0
    if d:
        for w in d.get("workflow_runs", []):
            total += 1
            c = w.get("conclusion")
            if c in ("failure", "cancelled", "timed_out", "startup_failure"):
                bad.append({"name": w["name"], "conclusion": c, "created": w["created_at"][:16],
                            "id": w["id"], "event": w.get("event")})
    return {"total": total, "bad": bad}


# ── B. 步骤耗时 ───────────────────────────────────────────────
def check_steps(step_min=25, sample=30):
    """扫描「每个 workflow 最近一次 run」（含 cancelled/timed_out），找慢步骤。
    ⚠️2026-09-25 修正：原 sample=4 只取最近 4 个不同 workflow，被高频的盘中监控挤掉，
    导致漏检全盘量化扫描的 55min 单步。改为覆盖全部 workflow（至多 sample 个）。"""
    d = api("actions/runs?per_page=100")
    heavy = []
    if not d:
        return heavy
    seen = set()
    for w in d.get("workflow_runs", []):
        if w["name"] in seen:
            continue
        seen.add(w["name"])
        if len(seen) > sample:
            break
        if w.get("status") != "completed":
            continue
        j = api(f"actions/runs/{w['id']}/jobs")
        for job in (j or {}).get("jobs", []):
            for s in job.get("steps", []):
                a, b = s.get("started_at"), s.get("completed_at")
                if not a or not b:
                    continue
                try:
                    t0 = datetime.fromisoformat(a.replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(b.replace("Z", "+00:00"))
                    mins = (t1 - t0).total_seconds() / 60
                except Exception:
                    continue
                if mins >= step_min:
                    heavy.append({"workflow": w["name"], "step": s["name"], "minutes": round(mins, 1)})
    return heavy


# ── C. 产物新鲜度 ─────────────────────────────────────────────
def check_freshness():
    stale = []
    for path, maxd in FRESH.items():
        c = api_commits(path, 1)
        if not c:
            stale.append({"path": path, "status": "缺失", "age": None})
            continue
        try:
            dt = datetime.fromisoformat(c[0]["commit"]["committer"]["date"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt).days
            if age > maxd:
                stale.append({"path": path, "status": f"停更{age}天", "age": age, "max": maxd})
        except Exception:
            pass
    return stale


# ── D. 脚本异常（假绿）────────────────────────────────────────
def check_script_errors():
    errs = []
    raw = None
    for p in ("quant_results_latest.json", "outputs/quant_results_latest.json"):
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/contents/{urllib.parse.quote(p)}",
                                         headers={"Authorization": f"token {TOK}",
                                                  "Accept": "application/vnd.github.raw", "User-Agent": "x"})
            raw = urllib.request.urlopen(req, timeout=60).read()
            break
        except Exception:
            continue
    if not raw:
        return errs
    try:
        d = json.loads(raw)
    except Exception:
        return errs
    for k in ("shuangxian", "beast", "fishbody"):
        st = ((d.get(k) or {}).get("stderr") or "")
        if "Traceback" in st:
            first = next((l for l in st.splitlines() if "Error" in l or "error" in l), st.splitlines()[0] if st else "")
            errs.append({"module": k, "error": first.strip()[:160]})
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--step-min", type=int, default=25)
    ap.add_argument("--json", default="outputs/pipeline_audit.json")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    runs = check_runs(a.days)
    heavy = check_steps(a.step_min)
    stale = check_freshness()
    scripterr = check_script_errors()

    issues = []
    if runs["bad"]:
        issues.append(f"❌ run 异常 {len(runs['bad'])} 个（" +
                      "、".join(f"{b['name']}:{b['conclusion']}" for b in runs["bad"][:5]) + "）")
    if heavy:
        issues.append("⚠️ 重步骤：" + "、".join(f"{h['workflow']}/{h['step']} {h['minutes']}min" for h in heavy[:5]))
    if stale:
        issues.append("⚠️ 产物停更：" + "、".join(f"{s['path']}({s['status']})" for s in stale[:5]))
    if scripterr:
        issues.append("❌ 脚本异常（假绿）：" + "、".join(f"{e['module']} {e['error'][:60]}" for e in scripterr))

    rep = {"date": datetime.now(BJT).strftime("%Y-%m-%d %H:%M"),
           "runs": runs, "heavy_steps": heavy, "stale_products": stale,
           "script_errors": scripterr, "issues": issues,
           "status": "FAIL" if (runs["bad"] or scripterr) else ("WARN" if (heavy or stale) else "PASS")}
    os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
    json.dump(rep, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"=== 流水线自愈巡检 {rep['date']} → {rep['status']} ===")
    print(f"近{a.days}天 runs: {runs['total']} 个 | 异常 {len(runs['bad'])}")
    for b in runs["bad"]:
        print(f"   ❌ {b['created']} {b['name']} → {b['conclusion']}")
    print(f"重步骤(≥{a.step_min}min): {len(heavy)}")
    for h in heavy[:8]:
        print(f"   ⚠️ {h['workflow']} / {h['step']} = {h['minutes']}min")
    print(f"产物停更: {len(stale)}")
    for s in stale:
        print(f"   ⚠️ {s['path']} → {s['status']}")
    print(f"脚本异常: {len(scripterr)}")
    for e in scripterr:
        print(f"   ❌ {e['module']}: {e['error']}")

    if a.push and issues:
        tk = os.environ.get("PUSH_TOKEN", "")
        if tk:
            body = json.dumps({"token": tk, "title": f"⚠️体系巡检 {rep['status']}",
                               "content": "\n".join(issues), "template": "txt"}).encode()
            try:
                urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body,
                                                              headers={"Content-Type": "application/json"}), timeout=15)
                print("推送 ✅")
            except Exception as e:
                print("推送失败", e)
    return 0 if rep["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
