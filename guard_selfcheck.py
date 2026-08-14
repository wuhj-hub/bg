#!/usr/bin/env python3
"""
guard_selfcheck.py —— GitHub Actions 备份完整性自检（每日定时）
================================================================
在 GitHub 端检查 skills_backup/ 与 quant_scripts/ 的备份完整性：
  1. 14 个自建技能必须存在 SKILL.md（非空）
  2. 有 scripts 的技能必须保留 .py 脚本
  3. quant_scripts/ 关键脚本存在（防误删/覆盖）
  4. 关键配置文件存在（caige_pool.txt / holdings.txt）
发现问题 → 生成报告 + PushPlus 推送告警 + exit 1

运行环境: GitHub Actions (ubuntu-latest)，仓库根目录 checkout
用法: python3 guard_selfcheck.py
输出: guard_selfcheck_<date>.md（仓库根目录）
================================================================
"""
import os, sys, glob
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))

SELF_SKILLS = [
    "复盘报告", "猛兽体系", "盘前市场报告", "双弦投资系统",
    "双弦投资系统-月度股池", "鱼身", "wangbei-report", "wuwei-report",
    "xihu-report", "bo-duan-sao-miao", "duo-wei-du", "fish-body-trading",
    "强势体系", "个人23策略股票分析技能",
]
SKILLS_WITH_SCRIPTS = [  # 必须有 scripts/*.py 的技能（依据GitHub实际备份结构）
    "猛兽体系", "盘前市场报告", "双弦投资系统", "双弦投资系统-月度股池",
    "鱼身", "bo-duan-sao-miao", "duo-wei-du", "fish-body-trading",
]
REQUIRED_QUANT = [  # quant_scripts/ 关键脚本（缺任一即告警）
    "caige_pool.py", "pool_tracking_report.py", "beast_screener.py",
    "run_all_quant.py", "gen_review_report.py", "gen_premarket_report.py",
    "fish_body_enhanced.py", "month_frame.py", "dual_pool_sync.py",
    "monthly_pool_sync.py", "gen_fish_pool.py", "paper_tracker.py",
    "win_rate_tracker.py", "guard.py",
]
REQUIRED_ROOT = ["caige_pool.txt", "holdings.txt", "all_mainboard.csv"]
MIN_SKILL_MD = 300      # SKILL.md 最小字节数（防空文件）
MIN_SCRIPT = 500        # 脚本最小字节数


def check():
    issues = []
    ok_count = 0

    # 1. 技能备份完整性
    for skill in SELF_SKILLS:
        md = f"skills_backup/{skill}/SKILL.md"
        if not os.path.exists(md):
            issues.append(f"❌ 技能「{skill}」SKILL.md 缺失: {md}")
        elif os.path.getsize(md) < MIN_SKILL_MD:
            issues.append(f"⚠️ 技能「{skill}」SKILL.md 过小({os.path.getsize(md)}B)")
        else:
            ok_count += 1
        sc_dir = f"skills_backup/{skill}/scripts"
        if os.path.isdir(sc_dir) or skill in SKILLS_WITH_SCRIPTS:
            py_files = glob.glob(f"{sc_dir}/*.py")
            if not py_files:
                issues.append(f"⚠️ 技能「{skill}」scripts 无 .py 脚本")
            else:
                small = [f for f in py_files if os.path.getsize(f) < MIN_SCRIPT]
                if small:
                    issues.append(f"⚠️ 技能「{skill}」存在过小脚本: {[os.path.basename(f) for f in small]}")
                ok_count += 1

    # 2. quant_scripts 关键脚本
    for sc in REQUIRED_QUANT:
        p = f"quant_scripts/{sc}"
        if not os.path.exists(p):
            issues.append(f"❌ quant_scripts/{sc} 缺失")
        elif os.path.getsize(p) < MIN_SCRIPT:
            issues.append(f"⚠️ quant_scripts/{sc} 过小({os.path.getsize(p)}B)")
        else:
            ok_count += 1

    # 3. 根目录关键配置
    for rc in REQUIRED_ROOT:
        if not os.path.exists(rc):
            issues.append(f"❌ 根目录 {rc} 缺失")
        else:
            ok_count += 1

    # 4. skills_backup 目录总数
    backup_dirs = [d for d in os.listdir("skills_backup") if os.path.isdir(f"skills_backup/{d}")] \
        if os.path.isdir("skills_backup") else []
    if len(backup_dirs) < len(SELF_SKILLS):
        issues.append(f"⚠️ skills_backup 仅 {len(backup_dirs)}/{len(SELF_SKILLS)} 个技能目录")

    return issues, ok_count


def gen_report(issues, ok_count):
    now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")
    L = [f"# 🛡️ guard 备份完整性自检 {now[:10]}\n",
         f"**运行时间**: {now}（北京时间）",
         f"**检查项**: {ok_count} 项通过 | **问题**: {len(issues)} 项\n"]
    if issues:
        L.append("## ⚠️ 发现的问题\n")
        for it in issues:
            L.append(f"- {it}")
        L.append("\n> 💡 修复建议: 在沙箱执行 `python3 guard.py status` 确认差异后 `guard.py sync` 重新固化，或 `guard.py restore` 恢复本地。")
    else:
        L.append("## ✅ 全部通过\n")
        L.append("- 14 个自建技能 SKILL.md 完整\n- scripts 脚本完整\n- quant_scripts 关键脚本完整\n- 根目录配置完整")
    L.append("\n---\n> 本检查由 guard_selfcheck.yml 每日定时运行，仅验证 GitHub 端备份完整性（无法检测沙箱回滚——沙箱侧请用 guard.py status）")
    return "\n".join(L)


def push_alert(title, content):
    import urllib.request, urllib.parse
    token = os.environ.get("PUSH_TOKEN", "")
    if not token:
        print("[push] 跳过（PUSH_TOKEN未设置）")
        return
    body = urllib.parse.urlencode({
        "token": token, "title": title, "content": content[:4000],
        "template": "markdown"}).encode()
    try:
        req = urllib.request.Request("https://pushplus.plus/send", data=body)
        with urllib.request.urlopen(req, timeout=15) as r:
            print("[push]", r.read().decode()[:100])
    except Exception as e:
        print("[push] 失败:", e)


def main():
    issues, ok_count = check()
    report = gen_report(issues, ok_count)
    fname = f"guard_selfcheck_{datetime.now(BJ).strftime('%Y-%m-%d')}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n[OK] 报告: {fname}")
    if issues:
        push_alert(f"🛡️ guard自检发现问题（{len(issues)}项）", report)
        print("[FINAL] FAIL - 存在问题")
        sys.exit(1)
    else:
        print("[FINAL] PASS - 备份完整")
        sys.exit(0)


if __name__ == "__main__":
    main()
