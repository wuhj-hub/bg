#!/usr/bin/env python3
"""
体系更新记录自动生成器
功能：扫描自上次CHANGELOG更新以来的commits → 分类汇总 → 追加新版本记录 → commit & push
用法：python3 update_changelog.py [--version v2.7] [--dry-run]
      --version: 手动指定版本号（不指定则自动递增）
      --dry-run: 仅预览不提交
"""

import os
import re
import sys
import subprocess
import json
from datetime import date, datetime

CHANGELOG_FILE = "CHANGELOG.md"

# ─── 辅助函数 ───

def run_cmd(cmd, capture=True):
    """执行shell命令"""
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def get_last_changelog_commit_sha():
    """获取最近一次修改CHANGELOG.md的commit SHA"""
    out, _, _ = run_cmd(f'git log --oneline --follow -1 -- "{CHANGELOG_FILE}"')
    if out:
        return out.split()[0]  # 返回short SHA
    return None

def get_commits_since(sha):
    """获取从指定commit以来的所有commit（按时间从旧到新）"""
    if not sha:
        out, _, _ = run_cmd("git log --oneline --reverse HEAD")
    else:
        out, _, _ = run_cmd(f"git log --oneline --reverse {sha}..HEAD")
    return [line for line in out.split("\n") if line.strip() and "changelog:" not in line]

def parse_commits(commit_lines):
    """解析commit消息，按类型分类"""
    categories = {
        "✨ 新功能": [],   # feat
        "🐛 修复": [],     # fix
        "🔧 优化": [],     # chore, refactor, perf
        "🏷️ 改名": [],     # rename
        "📝 文档": [],     # docs
    }
    
    for line in commit_lines:
        parts = line.split(" ", 1)
        sha = parts[0]
        msg = parts[1] if len(parts) > 1 else ""
        
        entry = f"- {msg} ({sha[:7]})"
        
        if msg.startswith("feat:"):
            categories["✨ 新功能"].append(entry)
        elif msg.startswith("fix:"):
            categories["🐛 修复"].append(entry)
        elif msg.startswith("rename:"):
            categories["🏷️ 改名"].append(entry)
        elif msg.startswith("chore:") or msg.startswith("refactor:") or msg.startswith("perf:"):
            categories["🔧 优化"].append(entry)
        elif msg.startswith("docs:"):
            categories["📝 文档"].append(entry)
        else:
            # 未分类的归入优化
            categories["🔧 优化"].append(entry)
    
    # 过滤空分类
    return {k: v for k, v in categories.items() if v}

def get_latest_version():
    """从CHANGELOG中提取最新版本号"""
    with open(CHANGELOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 匹配 ## vX.Y 格式
    matches = re.findall(r"## v(\d+)\.(\d+)", content)
    if not matches:
        return (2, 0)  # 默认从v2.0开始
    
    versions = [(int(m[0]), int(m[1])) for m in matches]
    return max(versions)

def format_version(major, minor):
    """格式化版本号"""
    return f"v{major}.{minor}"

def format_date():
    """返回格式化日期 YYYY-MM-DD"""
    return date.today().isoformat()

def build_changelog_entry(version, changes):
    """构建新的changelog条目文本"""
    today = format_date()
    lines = [f"\n---\n\n## {version} ({today})\n"]
    
    for category, items in changes.items():
        lines.append(f"\n### {category}\n")
        for item in items:
            lines.append(item)
    
    return "\n".join(lines)

def update_changelog(new_entry):
    """追加新条目到CHANGELOG.md末尾（在最后---之前插入）"""
    with open(CHANGELOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 在最后的 --- 之前插入新条目
    # 或者直接追加到文件末尾
    # CHANGELOG.md 最后是 --- 然后空行，我们在最后一个section后插入
    
    # 策略：在倒数第二个 --- 后面插入（最后一个 section 之后）
    # 更简单：直接追加到末尾
    with open(CHANGELOG_FILE, "a", encoding="utf-8") as f:
        f.write(new_entry)

def commit_and_push(version):
    """提交并推送CHANGELOG变更"""
    # 检查是否有变更
    out, _, _ = run_cmd("git status --porcelain -- CHANGELOG.md")
    if not out:
        print("⚠️ CHANGELOG.md 无变更，跳过提交")
        return False
    
    # 配置git用户
    run_cmd('git config user.name "wuhj-hub"')
    run_cmd('git config user.email "94036320@qq.com"')
    
    # 暂存、提交、推送
    run_cmd(f"git add {CHANGELOG_FILE}")
    out, err, code = run_cmd(f'git commit -m "changelog: {version} 体系更新记录"')
    if code != 0:
        print(f"❌ commit 失败: {err}")
        return False
    
    # 推送
    # GitHub Actions 环境中，GITHUB_TOKEN 有 push 权限
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        repo_url = f"https://x-access-token:{token}@github.com/wuhj-hub/bg.git"
        out, err, code = run_cmd(f"git push {repo_url} HEAD:main")
    else:
        out, err, code = run_cmd("git push origin HEAD:main")
    
    if code == 0:
        print(f"✅ 已推送 changelog: {version}")
        return True
    else:
        print(f"❌ push 失败: {err}")
        return False

def main():
    dry_run = "--dry-run" in sys.argv
    
    # 版本参数
    version_arg = None
    for arg in sys.argv[1:]:
        if arg.startswith("--version="):
            version_arg = arg.split("=", 1)[1]
    
    # 获取最新版本
    major, minor = get_latest_version()
    
    if version_arg:
        # 使用指定的版本号
        match = re.match(r"v(\d+)\.(\d+)", version_arg)
        if match:
            major, minor = int(match.group(1)), int(match.group(2))
        else:
            print(f"❌ 版本号格式错误: {version_arg}，应为 vX.Y")
            sys.exit(1)
    else:
        # 自动递增次版本号
        minor += 1
    
    new_version = format_version(major, minor)
    print(f"📋 当前版本: {format_version(major - (1 if not version_arg else 0), minor - (1 if not version_arg else 0))}")
    print(f"📋 新版本:   {new_version}")
    
    # 获取自上次CHANGELOG更新以来的commits
    last_sha = get_last_changelog_commit_sha()
    print(f"📋 上次CHANGELOG更新commit: {last_sha or '（最早）'}")
    
    commits = get_commits_since(last_sha)
    print(f"📋 发现 {len(commits)} 个新commit")
    
    if not commits:
        print("ℹ️  没有新commit，跳过更新")
        return
    
    # 分类
    changes = parse_commits(commits)
    
    print(f"\n📋 变更分类:")
    for cat, items in changes.items():
        print(f"  {cat}: {len(items)}条")
        for item in items:
            print(f"    {item}")
    
    # 构建条目
    new_entry = build_changelog_entry(new_version, changes)
    print(f"\n{'─'*60}")
    print("待追加内容:")
    print(new_entry)
    print(f"{'─'*60}")
    
    if dry_run:
        print("\n✅ --dry-run 模式，未实际写入")
        return
    
    # 写入
    update_changelog(new_entry)
    print(f"\n✅ CHANGELOG.md 已更新")
    
    # 提交推送
    success = commit_and_push(new_version)
    if not success:
        print("\n⚠️  提交/推送失败，CHANGELOG.md 本地已更新但未推送至远程")
        print("   可手动执行: git push")

if __name__ == "__main__":
    main()
