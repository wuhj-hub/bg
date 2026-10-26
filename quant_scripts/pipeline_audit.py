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
  python3 pipeline_audit.py [--days 3] [--step-min 25] [--json outputs/pipeline_audit.json] [--push]
"""
import os, re, sys, json, time, argparse, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))
REPO = os.environ.get("BG_REPO", "wuhj-hub/bg")
TOK = os.environ.get("GITHUB_TOKEN", "")

# 关键产物：路径 → 允许的最大停更天数
FRESH = {
    "quant_results_latest.json": 1,
    "outputs/paper_portfolio.json": 2,
    "outputs/pool_entries.csv": 2,
    "outputs/market_width_latest.json": 1,   # 2026-10-22：10-15「消灭双副本」后 canonical=outputs/，旧根路径已删除→每日误报「停更」
    "hot_emotion_latest.json": 1,
    "execution_cards_latest.json": 1,
    "market_regime_latest.json": 2,
    "outputs/sector_component_em.json": 5,
}


# ── 期望运行清单（2026-10-27 新增：应跑未跑检测）─────────────────────
# 背景：多数 workflow 的原生 cron 已停用，唯一触发源是外部 cron-job.org 的
#   repository_dispatch。外部配置一丢就「静默停摆」，而且**不会有任何告警**
#   （bt_cycle 从上线起到 2026-10-23 查产物才发现从未运行过）。
# 口径：只看「最近一次 success」的**交易日计龄**（trading_days_since，长假不累计），
#   超过容忍窗口即报。日更类容忍 1 个交易日 —— 07:00 自检时当日主链尚未运行属正常，
#   只有「连着两个交易日没跑」才报，避免每天误报。
# 不纳入：market_regime / inbull_scan（主通道是 quant_report 内联，独立 workflow 仅手动兜底）、
#         probe_*（手动调试工具）。
EXPECTED_RUNS = [
    # (workflow 文件名, 展示名, 容忍交易日, 仅交易日检查)
    ("quant_scan.yml", "全盘量化扫描", 1, True),
    ("quant_report.yml", "盘后报告生成", 1, True),
    ("premarket_report.yml", "盘前市场报告", 1, True),
    ("intraday_monitor.yml", "盘中监控", 1, True),
    ("wangzhe_track.yml", "涨停型王者跟踪", 1, True),
    ("beast_pool.yml", "猛兽突破池扫描", 1, True),
    ("yao_gu_pool.yml", "妖股池扫描", 1, True),
    ("jingjia_track.yml", "竞价统计·逐日跟踪", 1, True),
    ("selfcheck_daily.yml", "体系自检", 1, True),
    ("artifact_audit.yml", "产物入库审计", 1, True),
    ("guard_selfcheck.yml", "guard备份自检", 1, True),
    ("duowei_fish.yml", "多维度·鱼身报告更新", 1, True),
    ("pool_winrate_biweekly.yml", "股池胜率总览（双周）", 11, False),
    ("weight_learn.yml", "仲裁权重自学习（月度）", 25, False),
    ("emotion_backtest_monthly.yml", "情绪温度计回测（月度）", 25, False),
    ("bt_cycle.yml", "回测周期（月度）", 25, False),
    ("evidence_review.yml", "evidence月度复核提醒", 25, False),
    ("inbull_threshold_monitor.yml", "入牛阈值漂移监控（季度）", 70, False),
]


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
def check_runs(days=3):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = api(f"actions/runs?per_page=100&created=%3E{urllib.parse.quote(since)}")
    bad, noise = [], []
    runs = (d or {}).get("workflow_runs", [])
    total = len(runs)

    # ── 并发/重复触发取消降噪（2026-10-14）────────────────────────
    # 同一 workflow 被重复触发（cron-job.org 与原生 schedule 双跑、手动连点）时，
    # concurrency: cancel-in-progress 会把多余 run 标记为 conclusion=cancelled，
    # 属设计噪音而非故障。判据（二者取一即视为噪音）：
    #   ① 同 workflow 在其前后 30 分钟内有其它 run（并发取消）；
    #   ② 同 workflow 在同一天(UTC)内存在 success 的 run（重复触发、另有一次已成功）。
    # 真·超时取消（孤立、当天无成功）仍保留在 bad 中，不削弱原设计。
    ok_days = {(w.get("name"), (w.get("created_at") or "")[:10])
               for w in runs if w.get("conclusion") == "success"}

    # ── 成规模取消检测（2026-10-26 新增）──────────────────────────
    # 原判据②「同 workflow 当天有 success 即判噪音」存在致命盲区：
    #   「上午成功几次、下午起 24 次全 cancelled」会被整体判为噪音而彻底隐形
    #   （2026-10-23 实况：盘中监控 11:00~14:45 共 24 次 cancelled，但当天 09:00-09:30 有 success
    #     → 全部被忽略；且这是**连续 4 小时**的失效，不是偶发并发取消）。
    # 新增判据：同 workflow 同一天 cancelled ≥ 3 且 cancelled/(cancelled+success+...) > 50%
    #   → 判「成规模取消」= 真问题，进 bad（每批次只记 1 条代表，其余标注同类已记录）。
    _stat = {}
    for w in runs:
        _k = (w.get("name"), (w.get("created_at") or "")[:10])
        _s = _stat.setdefault(_k, [0, 0])
        if w.get("conclusion") == "cancelled":
            _s[0] += 1
        elif w.get("conclusion") in ("success", "failure", "timed_out"):
            _s[1] += 1

    def _mass_cancel(w):
        cs, ok = _stat.get((w.get("name"), (w.get("created_at") or "")[:10]), (0, 0))
        return cs >= 3 and cs / max(cs + ok, 1) > 0.5

    _mass_done = set()

    def _near(w):
        try:
            t0 = datetime.fromisoformat((w.get("created_at") or "").replace("Z", "+00:00"))
        except Exception:
            return False
        for o in runs:
            if o is w or o.get("name") != w.get("name"):
                continue
            try:
                t1 = datetime.fromisoformat((o.get("created_at") or "").replace("Z", "+00:00"))
            except Exception:
                continue
            if abs((t1 - t0).total_seconds()) <= 1800:
                return True
        return False

    for w in runs:
        c = w.get("conclusion")
        if c not in ("failure", "cancelled", "timed_out", "startup_failure"):
            continue
        item = {"name": w["name"], "conclusion": c, "created": (w.get("created_at") or "")[:16],
                "id": w["id"], "event": w.get("event")}
        if c == "cancelled":
            day = (w.get("created_at") or "")[:10]
            if _mass_cancel(w):
                cs, ok = _stat.get((w.get("name"), day), (0, 0))
                pct = cs * 100 // max(cs + ok, 1)
                if (w.get("name"), day) in _mass_done:
                    item["reason"] = f"成规模取消（同批次已记录 {cs} 次/{pct}%）"
                    noise.append(item)
                    continue
                _mass_done.add((w.get("name"), day))
                item["reason"] = f"成规模取消：当日 {cs} 次取消 / {ok} 次其它（取消占比 {pct}%）"
            elif (w.get("name"), day) in ok_days or _near(w):
                item["reason"] = "并发/重复触发取消"
                noise.append(item)
                continue
        bad.append(item)
    return {"total": total, "bad": bad, "noise": noise}


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
def _judge_trading(dt):
    """dt 是否交易日。无法判定时按『是』处理（保守，不漏报真异常）。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from trade_day_check import judge as _td_judge
        ok, _ = _td_judge(dt)
        return ok
    except Exception:
        return True


def is_trading_today():
    """今天(北京时)是否交易日。"""
    return _judge_trading(datetime.now(BJT))


def trading_days_since(start_dt):
    """从 start_dt『次日起』到今天(北京)之间的**交易日**数量。
    用于产物新鲜度：周末/长假不累计，避免节后首日误报『停更 N 天』。"""
    start_d = start_dt.astimezone(BJT).date() + timedelta(days=1)
    end_d = datetime.now(BJT).date()
    n, d = 0, start_d
    while d <= end_d and n < 999:
        if _judge_trading(datetime(d.year, d.month, d.day, tzinfo=BJT)):
            n += 1
        d += timedelta(days=1)
    return n


def check_freshness():
    # ⭐2026-10-05: 休市日跳过停更检查 —— 休市期 quant_scan/quant_report 本就不运行，关键产物
    #   "停更 N 天"属预期而非故障；此前按自然日计龄 → 每个休市日必然 WARN → 误推微信告警（狼来了）。
    if not is_trading_today():
        return None   # None = 本次跳过（区别于 [] = 已检查且无停更）
    stale = []
    for path, maxd in FRESH.items():
        c = api_commits(path, 1)
        if not c:
            stale.append({"path": path, "status": "缺失", "age": None})
            continue
        try:
            dt = datetime.fromisoformat(c[0]["commit"]["committer"]["date"].replace("Z", "+00:00"))
            age = trading_days_since(dt)          # 交易日计龄（周末/长假不累计）
            if age > maxd:
                nat = (datetime.now(timezone.utc) - dt).days
                stale.append({"path": path, "status": f"停更{age}个交易日(自然{nat}天)", "age": age, "max": maxd})
        except Exception:
            pass
    return stale


# ── C2. 应跑未跑（外部 cron 静默停摆）──────────────────────────────
def check_expected_runs():
    """清单里每个 workflow 的「最近一次 success」是否在容忍窗口内。
    返回 (issues, detail)。"""
    issues, detail = [], []
    today_trading = is_trading_today()
    for wf, label, tol, trading_only in EXPECTED_RUNS:
        if trading_only and not today_trading:
            continue
        d = api(f"actions/workflows/{urllib.parse.quote(wf)}/runs?per_page=1&status=success")
        rs = (d or {}).get("workflow_runs") or []
        if not rs:
            allr = api(f"actions/workflows/{urllib.parse.quote(wf)}/runs?per_page=1")
            ever = (allr or {}).get("workflow_runs") or []
            if ever:
                e0 = ever[0]
                last = (e0.get("created_at") or "")[:10]
                issues.append(f"🚨 从无成功：{label}（{wf}）最近一次={last} {e0.get('conclusion')}")
                detail.append({"workflow": wf, "label": label, "last_success": None,
                               "last_run": last, "age": None, "tol": tol})
            else:
                issues.append(f"🚨 从未运行：{label}（{wf}）—— 检查 cron-job.org 是否登记该 dispatch")
                detail.append({"workflow": wf, "label": label, "last_success": None,
                               "last_run": None, "age": None, "tol": tol})
            continue
        ts = (rs[0].get("created_at") or "")[:19]
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        age = trading_days_since(dt)
        detail.append({"workflow": wf, "label": label, "last_success": ts[:10],
                       "age": age, "tol": tol})
        if age > tol:
            issues.append(f"⏰ 超期未运行：{label}（{wf}）最近成功 {ts[:10]}，"
                          f"已 {age} 个交易日（容忍 {tol}）→ 检查外部 dispatch")
    return issues, detail


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
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--step-min", type=int, default=25)
    ap.add_argument("--json", default="outputs/pipeline_audit.json")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    runs = check_runs(a.days)
    heavy = check_steps(a.step_min)
    stale_raw = check_freshness()
    freshness_skipped = stale_raw is None
    stale = stale_raw or []
    scripterr = check_script_errors()
    expected, expected_detail = check_expected_runs()

    issues = []
    if runs["bad"]:
        issues.append(f"❌ run 异常 {len(runs['bad'])} 个（" +
                      "、".join(f"{b['name']}:{b['conclusion']}" for b in runs["bad"][:5]) + "）")
    if runs.get("noise"):
        issues.append(f"⏹️ 并发/重复触发取消 {len(runs['noise'])} 个（已忽略，不计入异常）")
    if heavy:
        # 2026-10-26：重步骤只作性能提示，不参与 status/退出码 ——
        #   此前 heavy 也算 WARN → 只要有 >25min 的步骤（竞价统计 40.9min 每天都有）
        #   自检就恒 rc=1、每天推「⚠️体系自检异常」到微信，形成告警疲劳、真异常被淹没。
        issues.append("⚠️ 重步骤：" + "、".join(f"{h['workflow']}/{h['step']} {h['minutes']}min" for h in heavy[:5]))
    if stale:
        issues.append("⚠️ 产物停更：" + "、".join(f"{s['path']}({s['status']})" for s in stale[:5]))
    if scripterr:
        issues.append("❌ 脚本异常（假绿）：" + "、".join(f"{e['module']} {e['error'][:60]}" for e in scripterr))
    if expected:
        issues.append(f"🚨 应跑未跑 {len(expected)} 项：" + "；".join(x[:90] for x in expected[:4]))

    rep = {"date": datetime.now(BJT).strftime("%Y-%m-%d %H:%M"),
           "runs": runs, "heavy_steps": heavy, "stale_products": stale,
           "freshness_skipped": freshness_skipped,
           "script_errors": scripterr, "expected_runs": expected_detail, "issues": issues,
           "status": "FAIL" if (runs["bad"] or scripterr or expected) else ("WARN" if stale else "PASS")}
    os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
    json.dump(rep, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"=== 流水线自愈巡检 {rep['date']} → {rep['status']} ===")
    print(f"近{a.days}天 runs: {runs['total']} 个 | 异常 {len(runs['bad'])}"
          + (f" | 并发取消(忽略) {len(runs['noise'])}" if runs.get("noise") else ""))
    for b in runs["bad"]:
        print(f"   ❌ {b['created']} {b['name']} → {b['conclusion']}")
    for b in runs.get("noise", []):
        print(f"   ⏹️ {b['created']} {b['name']} → cancelled（{b.get('reason','并发取消')}，已忽略）")
    print(f"重步骤(≥{a.step_min}min): {len(heavy)}")
    for h in heavy[:8]:
        print(f"   ⚠️ {h['workflow']} / {h['step']} = {h['minutes']}min")
    if freshness_skipped:
        print("产物停更: ⏭️ 休市日跳过")
    else:
        print(f"产物停更: {len(stale)}")
    for s in stale:
        print(f"   ⚠️ {s['path']} → {s['status']}")
    print(f"脚本异常: {len(scripterr)}")
    for e in scripterr:
        print(f"   ❌ {e['module']}: {e['error']}")
    print(f"应跑未跑: {len(expected)}  (清单 {len(expected_detail)} 项)"
          + ("  ⏭️ 休市日仅查非日更类" if not is_trading_today() else ""))
    for x in expected:
        print(f"   {x}")

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
