#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""artifact_audit.py —— 产物入库统一审计（根治「脚本写了、但从不提交」的静默断链）

背景（2026-09-16）：体系中已连续出现三类同源故障——
  ① sector_component_em.json 从 9/3 起是空壳且从未入库
  ② market_width_latest.json 仓库根与 outputs/ 两份分裂、审计误报陈旧
  ③ 乾坤A 产物 qiankun_a_latest.json、四态胜率输入 outputs/资金快照_*.csv 从不提交
     → 复盘/仲裁消费 3 周前陈旧数据、四态胜率机制从未产出结果
共同模式：**脚本在跑、step 显示 success、产物却没进仓库**，消费方读到旧版。

本工具：静态比对「脚本写出的文件路径」与「workflow 的提交列表」，
        列出所有产出 → 标出未提交的差集 → 有缺口则非零退出（供 CI 告警）。

用法：
  python3 artifact_audit.py [--repo DIR] [--out DIR] [--strict]
"""
import argparse
import glob
import json
import os
import re
from collections import defaultdict

# 期望被跟踪的产物类型
ART_EXT = (".json", ".csv", ".md", ".txt")
# 不需要提交的（中间文件/缓存/知识库上传件/纯日志）
WHITELIST = (
    "kline_daily", "hs300", "test_", "tmp", "/tmp", ".cache", "pycache",
    "requirements", "__init__", "data/", "pools/pool_",  # pools 由专用逻辑提交
    "screenshot", ".png", ".jpg",
    # 研究/回测/一次性脚本产物（不进流水线，无需提交）——2026-09-16 降噪
    "research/", "long_", "regime_new", "yaogu_", "weak_", "env_switch",
    "beast_setup_events", "beast_pool_stats", "skill.md", "trade_journal",
    "portfolio_nav_history", "liangxue_signals_log", "xianxing_signals_b",
    "bt_filters", "bt_intraday_vs_wangzhe", "bt_variants", "vcp_backtest",
    "wangzhe_confirm_stats", "anti_resilience", "execution_cards_", "market_style_",
    "hot_emotion_2", "rsv_strength_2", "market_width_2", "123_2b反转信号_",
)
# 已知由「非 git_api_commit」方式提交的（如 wangzhe_commit.py / intraday cache）
ALT_COMMIT = {
    "wangzhe_commit.py": ["wangzhe_signals.csv", "wangzhe_stats.json",
                          "涨停型王者_成功率报告", "caige_track.json", "caige_articles"],
}


def norm(p):
    """路径归一化：日期/变量占位 → {date}，统一取 basename（因 cp 常转存到仓库根）"""
    if not p:
        return ""
    p = p.strip().strip('"\'`,;\\|')
    # 统一所有动态占位符 → {VAR}（f-string 变量 / shell $var / $(date...) / %s / args.xxx）
    p = re.sub(r"\$?\{[a-zA-Z_.]+\}", "{VAR}", p)           # {today} / ${date} / {args.date}
    p = re.sub(r"\$?\(date[^)]*\)", "{VAR}", p)             # $(date +%Y-%m-%d)
    p = re.sub(r"%s", "{VAR}", p)                             # 旧式格式化
    p = re.sub(r"\d{4}-\d{2}-\d{2}", "{VAR}", p)            # 日期字面量 2026-09-16
    p = re.sub(r"\d{8}", "{VAR}", p)                          # 紧凑日期 20260916
    p = re.sub(r"[\*]", "", p)                                # glob 星号
    p = p.replace("{VAR}", "{var}")
    return os.path.basename(p).lower()


def fuzzy(a, b):
    """占位符 {date}/{var} 视为通配，用于跨路径匹配"""
    pat = re.escape(a).replace(r"\{date\}", "[^/]*").replace(r"\{var\}", "[^/]*")
    return re.fullmatch(pat, b) is not None


def is_art(p):
    return norm(p).endswith(ART_EXT) or any(k in p for k in ("caige_articles",))


def in_whitelist(p):
    n = norm(p)
    return any(w in n or w in p for w in WHITELIST)


# ── ① 提取「脚本写出的路径」 ─────────────────────────────────
WRITE_PATTERNS = [
    # open(X, "w"/"a")
    (r'open\(\s*f?["\']([^"\']{3,120})["\']\s*,\s*["\'][wa]', 1),
    # json.dump(obj, open(X, "w"))
    (r'json\.dump\([^,]{1,80},\s*open\(\s*f?["\']([^"\']{3,120})["\']', 1),
    # df.to_csv(X) / .to_csv(X, index=..)
    (r'to_csv\(\s*f?["\']([^"\']{3,120})["\']', 1),
    # path.write_text(X) / write_text(f"...")
    (r'write_text\(\s*f?["\']([^"\']{3,120})["\']', 1),
    # os.path.join(OUT, "x.json") / os.path.join(BASE, "outputs", "x")
    (r'os\.path\.join\([^)]*?["\']([^"\']{3,120}\.(?:json|csv|md|txt))["\']', 1),
    # shell: cp SRC outputs/Y   /   cp SRC Y
    (r'\bcp\s+[^\s]+\s+(?:\S*/)?([\w\u4e00-\u9fa5.\-]{3,80}\.(?:json|csv|md|txt))', 1),
    # shell: > outputs/Y  /  >> Y
    (r'>>?\s*"?(?:\S*/)?([\w\u4e00-\u9fa5.\-]{3,80}\.(?:json|csv|md|txt))', 1),
]


def extract_writes(root):
    """扫描所有 .py 与 workflow .yml，提取写路径 → {norm_path: [来源]}"""
    writes = defaultdict(set)
    files = []
    for pat in ("**/*.py", ".github/workflows/*.yml"):
        files += glob.glob(os.path.join(root, pat), recursive=True)
    for fp in files:
        try:
            txt = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        rel = os.path.relpath(fp, root)
        for rx, grp in WRITE_PATTERNS:
            for m in re.finditer(rx, txt):
                p = m.group(grp)
                if not is_art(p) or in_whitelist(p):
                    continue
                writes[norm(p)].add(rel)
    return writes


# ── ①b 提取「消费方读取路径」（判断断链危害等级）────────────
CONSUMERS = ("gen_premarket_report.py", "gen_review_report.py", "signal_arbiter.py",
             "run_all_quant.py", "market_style.py", "execution_card.py",
             "portfolio_risk.py", "gen_judgment.py", "report_selfcheck.py")
READ_PATTERNS = [
    r'open\(\s*f?["\']([^"\']{3,120})["\']\s*,\s*["\'][ra]',
    r'read_csv\(\s*f?["\']([^"\']{3,120})["\']',
    r'json\.load\(\s*open\(\s*f?["\']([^"\']{3,120})["\']',
    r'(?:exists|isfile)\(\s*f?["\']([^"\']{3,120})["\']',
    r'["\']((?:outputs/)?[\w\u4e00-\u9fa5.\-]{3,80}\.(?:json|csv))["\']',
]


def extract_reads(root):
    """扫描消费方脚本，提取它们读取的产物路径"""
    reads = defaultdict(set)
    for name in CONSUMERS:
        for fp in (os.path.join(root, "quant_scripts", name), os.path.join(root, name)):
            if not os.path.exists(fp):
                continue
            txt = open(fp, encoding="utf-8", errors="ignore").read()
            for rx in READ_PATTERNS:
                for m in re.finditer(rx, txt):
                    p = m.group(1)
                    if not is_art(p) or in_whitelist(p):
                        continue
                    reads[norm(p)].add(name)
    return reads


# ── ② 提取「workflow 提交列表」 ──────────────────────────────
def extract_commits(root):
    """解析 git_api_commit.py 调用后的文件列表（跨行 \\ 续行）+ 替代提交脚本白名单"""
    committed = defaultdict(set)
    for fp in glob.glob(os.path.join(root, ".github/workflows/*.yml")):
        try:
            raw = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        rel = os.path.basename(fp)
        # 去掉行尾续行符，合并成逻辑行
        merged = re.sub(r"\\\s*\n\s*", " ", raw)
        # ⚠️ 关键：$(date +%Y-%m-%d) 内含空格，会被后续空格分割成无效 token
        #    → 先把 date 参数折叠掉，再扫描
        merged = re.sub(r"\$\(date[^)]*\)", "$(date)", merged)
        merged = re.sub(r"\$\{?date\}?", "${date}", merged)
        for m in re.finditer(r"git_api_commit\.py\s+--msg\s+(?:\"[^\"]*\"|'[^']*')\s+(.*?)(?:\n\s*\n|\n\s*-|$)",
                             merged, re.S):
            body = m.group(1)
            for tok in re.split(r"\s+", body):
                tok = tok.strip().strip('"\'`|\\')
                if not tok or tok.startswith(("-", "#", "python", "||", "&&")):
                    continue
                if is_art(tok):
                    committed[norm(tok)].add(rel)
        # 替代提交方式
        for script, names in ALT_COMMIT.items():
            if script in raw:
                for n in names:
                    committed[norm(n)].add(f"{rel}(via {script})")
    return committed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--out", default=None)
    ap.add_argument("--strict", action="store_true", help="有缺口时非零退出")
    a = ap.parse_args()
    root = a.repo
    outdir = a.out or os.path.join(root, "outputs")
    if os.path.basename(root) == "quant_scripts":
        outdir = os.path.join(os.path.dirname(root), "outputs")

    writes = extract_writes(root)
    committed = extract_commits(root)
    reads = extract_reads(root)

    def covered(n, pool):
        """n 是否被 pool 中任一路径模糊覆盖"""
        if n in pool:
            return True
        return any(fuzzy(a, n) or fuzzy(n, a) for a in pool)

    all_norm = set(writes) | set(committed)
    missing, ok_list, orphan, high_risk = [], [], [], []
    for n in sorted(all_norm):
        w = n in writes
        c = covered(n, committed)
        if w and not c:
            missing.append((n, sorted(writes[n])))
            if covered(n, reads):        # 被消费方读取 → 高危
                high_risk.append((n, sorted(writes[n]), sorted(reads.get(n) or ["(模糊命中)"])))
        elif w and c:
            ok_list.append(n)
        elif not w:
            orphan.append((n, sorted(committed[n])))

    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    L = [f"# 🔍 产物入库审计 · {today}", "",
         f"> 扫描 {len(writes)} 个产出路径 / {len(committed)} 个提交路径 / {len(reads)} 个消费读取路径",
         f"> 🔴 高危（被读取且未提交）**{len(high_risk)}** ｜ 🟡 未提交 **{len(missing)}** ｜ ✅ 已提交 **{len(ok_list)}** ｜ ❔ 提交但未见生成 {len(orphan)}", ""]

    if high_risk:
        L += ["## 🔴 高危：被消费方读取、但从未提交（静默断链）", "",
              "| 产物 | 写出位置 | 被谁读取 |", "|---|---|---|"]
        for n, srcs, rds in high_risk:
            L.append(f"| `{n}` | {', '.join(srcs[:2])} | {', '.join(rds[:3])} |")
        L.append("")
    if missing:
        L += ["## 🟡 写而未提交（其余，多为研究/一次性产物）", "", "| 产物 | 写出位置 |", "|---|---|"]
        for n, srcs in missing:
            L.append(f"| `{n}` | {', '.join(srcs[:3])} |")
        L.append("")
    if ok_list:
        L += ["## ✅ 已提交", "", "`" + "`, `".join(ok_list) + "`", ""]
    if orphan:
        L += ["## ❔ 提交但未见脚本生成（手工或外部产物）", "", "| 产物 | 提交于 |", "|---|---|"]
        for n, srcs in orphan:
            L.append(f"| `{n}` | {', '.join(srcs[:3])} |")
        L.append("")

    text = "\n".join(L)
    print(text)
    os.makedirs(outdir, exist_ok=True)
    p_md = os.path.join(outdir, f"artifact_audit_{today}.md")
    open(p_md, "w", encoding="utf-8").write(text)
    json.dump({"date": today, "writes": {k: sorted(v) for k, v in writes.items()},
               "committed": {k: sorted(v) for k, v in committed.items()},
               "reads": {k: sorted(v) for k, v in reads.items()},
               "high_risk": [h[0] for h in high_risk],
               "missing": [m[0] for m in missing], "ok": ok_list, "orphan": [o[0] for o in orphan]},
              open(os.path.join(outdir, "artifact_audit.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n[OK] {p_md}（高危 {len(high_risk)} / 未提交 {len(missing)}）")
    if a.strict and high_risk:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
