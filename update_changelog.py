#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
体系更新记录自动生成器（v2 · GitHub API 版）
=================================================
改造要点（2026-11-26）
1. **不再依赖本地 git 历史**：CI 是浅克隆（fetch-depth 1），原实现
   `git log --follow -1 -- CHANGELOG.md` 只能看到 1 条 commit，
   导致 `sha..HEAD` 恒为空 → 长期「没有新 commit，跳过更新」（实测停在 v2.72/10-27）。
   改用 GitHub API 读取 CHANGELOG 的最后提交时间 + `commits?since=` 拉取增量。
2. **不再用原生 git push**：并发提交必然被拒（! [rejected] fetch first），
   改为调用仓库根的 `git_api_commit.py`（Contents API + 409 重试）。
   与全仓 10-08 的提交层统一。
3. **插入位置修正**：CHANGELOG 是「最新在前」，原实现 append 到文件末尾，
   新版本会跑到最旧的位置。改为插在第一个 `## vX.Y` 之前。
4. **过滤自动产物 commit**：每日几十条「竞价统计逐日更新 / 体系自检 / 产物入库审计」
   属于运行日志而非体系变更，全部过滤，避免 CHANGELOG 被噪声淹没。
5. **记录层不得阻断主链**：任何异常只打 ::warning:: 并 exit 0。

用法：
  python3 update_changelog.py [--version=v2.73] [--dry-run]
环境变量：
  GITHUB_TOKEN（需 contents:write）、GH_REPO（默认 wuhj-hub/bg）
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

REPO = os.environ.get("GH_REPO", "wuhj-hub/bg")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
BRANCH = "main"
HERE = os.path.dirname(os.path.abspath(__file__))
CHANGELOG_FILE = os.path.join(HERE, "CHANGELOG.md")

# 自动产物 / 运行日志类 commit —— 不进 CHANGELOG
AUTO_PATTERNS = [
    "竞价统计", "体系自检", "产物入库审计", "report results", "premarket judgment",
    "review report", "kb health", "paper portfolio", "env compare", "xihu turns",
    "reversal pools", "system temp history", "wangzhe breakout", "多维度鱼身报告",
    "update changelog", "quant results", "market regime", "inbull", "monthly",
    "weekly", "backtest results", "report (", "report 202", "chore: report",
    "artifact audit", "selfcheck", "health",
]

CATEGORY = {
    "feat": "✨ 新功能",
    "fix": "🐛 修复",
    "refactor": "🔧 重构",
    "perf": "⚡ 性能",
    "docs": "📝 文档",
    "rename": "🏷️ 改名",
    "chore": "🔧 优化",
}
CATEGORY_ORDER = ["✨ 新功能", "🐛 修复", "🔧 重构", "⚡ 性能", "🏷️ 改名", "📝 文档", "🔧 优化"]

# chore 类里属于「产物落库」的特征词 —— 过滤掉，否则每天几十条淹没日志
NOISE_CHORE = [
    "更新 ", ".json", ".csv", ".md", "scan results", "env refresh", "妖股池",
    "(20", "report", "stats", "refresh", "results", "快报", "统计", "总览",
]


# ─────────────────────────── GitHub API ───────────────────────────
def api(path, retries=3):
    """GitHub API 读取：优先 curl（urllib 大响应易 IncompleteRead），再退 urllib。"""
    url = f"https://api.github.com/repos/{REPO}/{path}"
    last = None
    for _ in range(retries):
        try:
            r = subprocess.run(
                ["curl", "-s", "-H", f"Authorization: token {TOKEN}",
                 "-H", "User-Agent: bg-changelog",
                 "-H", "Accept: application/vnd.github+json", url],
                capture_output=True, text=True, timeout=60)
            if r.stdout.strip():
                return json.loads(r.stdout)
            last = (r.stderr or "empty response")[:200]
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2)
    try:  # urllib 兜底
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bg-changelog",
        })
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception as e:  # noqa: BLE001
        last = e
    print(f"::warning::GitHub API 调用失败 {path}: {last}")
    return None


def last_changelog_iso():
    """CHANGELOG.md 最后一次提交的时间（ISO8601）。"""
    d = api(f"commits?path=CHANGELOG.md&sha={BRANCH}&per_page=1")
    if isinstance(d, list) and d:
        return d[0]["commit"]["committer"]["date"]
    return None


def commits_since(iso):
    out, seen = [], set()
    for page in range(1, 21):
        q = (f"commits?sha={BRANCH}&per_page=50&page={page}"
             + (f"&since={urllib.parse.quote(iso)}" if iso else ""))
        d = api(q)
        if not isinstance(d, list) or not d:
            break
        for c in d:
            sha = c.get("sha", "")
            if sha in seen:
                continue
            seen.add(sha)
            out.append(c)
        if len(d) < 50:
            break
    return out


# ─────────────────────────── 解析 ───────────────────────────
def is_noise(msg):
    low = msg.lower()
    if low.startswith("changelog:"):
        return True
    return any(p.lower() in low for p in AUTO_PATTERNS)


def classify(commits):
    """commit 列表 → {分类: [行]}，只保留有类型前缀的实质变更。"""
    buckets = {}
    for c in commits:
        msg = (c.get("commit", {}).get("message") or "").split("\n")[0].strip()
        if not msg or is_noise(msg):
            continue
        m = re.match(r"(feat|fix|refactor|perf|docs|rename|chore)\s*(?:\([^)]*\))?\s*[:：]\s*(.+)", msg)
        if not m:
            continue
        kind, body = m.group(1), m.group(2).strip()
        if kind == "chore" and any(n.lower() in body.lower() for n in NOISE_CHORE):
            continue
        if len(body) > 110:
            body = body[:107] + "..."
        sha = c.get("sha", "")[:7]
        dt = (c.get("commit", {}).get("committer", {}).get("date") or "")[5:10]
        bucket = CATEGORY[kind]
        buckets.setdefault(bucket, []).append(f"- {body} (`{sha}` {dt})")
    return {k: buckets[k] for k in CATEGORY_ORDER if buckets.get(k)}


def latest_version():
    """CHANGELOG 是「最新在前」，取第一个 `## vX.Y` 作为当前版本。"""
    with open(CHANGELOG_FILE, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"(?m)^## v(\d+)\.(\d+)", content)
    if m:
        return int(m.group(1)), int(m.group(2))
    vs = [(int(a), int(b)) for a, b in re.findall(r"## v(\d+)\.(\d+)", content)]
    return max(vs) if vs else (2, 0)


def build_entry(version, changes):
    lines = [f"## {version} ({date.today().isoformat()})", ""]
    for cat in CATEGORY_ORDER:
        items = changes.get(cat)
        if not items:
            continue
        lines.append(f"### {cat}")
        lines.append("")
        lines.extend(items)
        lines.append("")
    return "\n".join(lines)


def insert_at_top(entry):
    with open(CHANGELOG_FILE, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"(?m)^## v\d+\.\d+", content)
    if not m:
        new = content.rstrip() + "\n\n---\n\n" + entry
    else:
        new = content[:m.start()] + entry + "\n---\n\n" + content[m.start():]
    with open(CHANGELOG_FILE, "w", encoding="utf-8") as f:
        f.write(new)


def submit(version):
    """优先走 git_api_commit.py（Contents API）；缺失时退回原生 git。"""
    commit_script = os.path.join(HERE, "git_api_commit.py")
    msg = f"changelog: {version} 体系更新记录"
    if os.path.exists(commit_script):
        r = subprocess.run([sys.executable, commit_script, "--msg", msg, "CHANGELOG.md"],
                           cwd=HERE, capture_output=True, text=True, timeout=120)
        print((r.stdout or "").strip()[-600:])
        if r.returncode == 0:
            return True
        print(f"::warning::git_api_commit 失败: {(r.stderr or '').strip()[:300]}")
    # 兜底
    for cmd in (["git", "add", "CHANGELOG.md"],
                ["git", "-c", "user.name=wuhj-hub", "-c", "user.email=94036320@qq.com",
                 "commit", "-m", msg],
                ["git", "push", "origin", "HEAD:main"]):
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 and cmd[1] != "add":
            print(f"::warning::兜底提交失败: {(r.stderr or '').strip()[:200]}")
            return False
    return True


# ─────────────────────────── 主流程 ───────────────────────────
def main():
    dry_run = "--dry-run" in sys.argv
    forced = None
    for a in sys.argv[1:]:
        if a.startswith("--version="):
            forced = a.split("=", 1)[1]

    major, minor = latest_version()
    if forced and re.fullmatch(r"v\d+\.\d+", forced):
        major, minor = map(int, forced[1:].split("."))
    else:
        minor += 1
    version = f"v{major}.{minor}"

    iso = last_changelog_iso()
    print(f"📋 CHANGELOG 最后更新: {iso or '（未知，取全部）'}")
    commits = commits_since(iso)
    changes = classify(commits)
    total = sum(len(v) for v in changes.values())
    print(f"📋 扫描 {len(commits)} 条 commit → 实质变更 {total} 条")

    if total == 0:
        print("ℹ️ 无实质变更，跳过（记录层静默退出）")
        return 0

    entry = build_entry(version, changes)
    print("─" * 60)
    print(entry)
    print("─" * 60)
    if dry_run:
        print("✅ --dry-run：未写入")
        return 0

    insert_at_top(entry)
    ok = submit(version)
    print(f"{'✅ 已提交' if ok else '⚠️ 本地已写入但未提交成功'} {version}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"::warning::update_changelog 异常（不影响主链）: {e}")
        sys.exit(0)
