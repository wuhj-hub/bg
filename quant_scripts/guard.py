#!/usr/bin/env python3
"""
guard.py —— 量化体系防护工具（防回滚 / 防覆盖 / 防丢失）
================================================================
核心原则：GitHub (wuhj-hub/bg) 是唯一真源；本地是可丢失工作区。

  status   : 比对本地关键文件 vs GitHub，报告 回滚/新修改/缺失/一致
  sync     : 本地 → GitHub 全量推送（修改后一键固化，防丢失）
  restore  : GitHub → 本地恢复（被平台回滚/沙箱清理后一键复原）
  logcheck : 日志类文件保护检查（只push不pull，防旧版覆盖丢失）

用法:
  python3 guard.py status            # 检查差异/回滚
  python3 guard.py sync [--dry]      # 推送本地到GitHub（--dry预览）
  python3 guard.py restore [--dry]   # 从GitHub恢复本地（--dry预览）
  python3 guard.py logcheck          # 日志文件行数保护检查

依赖: 环境变量 GITHUB_TOKEN（默认内置token）
================================================================
"""
import base64, json, os, re, subprocess, sys, tempfile, time

TOKEN = os.environ.get("GITHUB_TOKEN", "")
if not TOKEN:
    for env_path in ("/sandbox/workspace/.env", os.path.expanduser("~/.env")):
        if os.path.exists(env_path):
            for ln in open(env_path, encoding="utf-8", errors="ignore"):
                if ln.startswith("GITHUB_TOKEN="):
                    TOKEN = ln.strip().split("=", 1)[1].strip()
                    break
        if TOKEN:
            break
if not TOKEN:
    print("ERROR: 需要 GITHUB_TOKEN 环境变量或 /sandbox/workspace/.env 文件")
    sys.exit(1)
REPO = "wuhj-hub/bg"
API = f"https://api.github.com/repos/{REPO}/contents"

WORKSPACE = "/sandbox/workspace"
SKILLS = "/root/.skills"

# 自建技能白名单（备份范围；平台技能 ima-*/pdfkit 等不需要）
SELF_SKILLS = [
    "复盘报告", "猛兽体系", "盘前市场报告", "双弦投资系统",
    "双弦投资系统-月度股池", "鱼身", "wangbei-report", "wuwei-report",
    "xihu-report", "bo-duan-sao-miao", "duo-wei-du", "fish-body-trading",
    "强势体系", "个人23策略股票分析技能",
]

# workspace 根目录文件白名单（*.py 全量 + 指定数据/配置）
WS_ROOT_PATTERNS = [r".*\.py$", r"^caige_pool\.txt$", r"^all_mainboard\.csv$",
                    r"^holdings\.txt$", r"^王者倍量柱_正版指标\.md$"]
WS_EXCLUDE = [r"__pycache__", r"\.DS_Store", r"^outputs/", r"^uploads/",
              r"^connectors/", r"^skills/", r"^node_modules/"]

# 日志类文件：本地为唯一真源，禁止从GitHub拉旧版覆盖
LOG_FILES = ["pool_signals_log.csv", "仲裁信号日志.csv", "paper_portfolio.json",
             "caige_pool.txt", "holdings.txt"]


# ============================================================
# GitHub API（走 curl，带重试，比 urllib 稳）
# ============================================================
def gh(method, path, body=None, retry=3):
    url = f"{API}/{path}"
    cmd = ["curl", "-s", "--max-time", "120", "-X", method,
           "-H", f"Authorization: token {TOKEN}"]
    tmp = None
    if body is not None:
        # 大内容用 -d @文件 方式（Linux 单参数 128KB 限制，base64大文件会E2BIG）
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="guard_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f)
        cmd += ["-H", "Content-Type: application/json", "-d", f"@{tmp}"]
    cmd.append(url)
    try:
        for i in range(retry):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if r.stdout.strip():
                    return r.stdout
            except subprocess.TimeoutExpired:
                pass
            time.sleep(2)
        return None
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)

def gh_get(path):
    out = gh("GET", path)
    if not out:
        return None
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        return None
    return d

def gh_sha(path):
    d = gh_get(path)
    return d.get("sha") if d and "sha" in d else None

def gh_put(path, content, msg, sha=None):
    body = {"message": msg, "content": base64.b64encode(content.encode()).decode()}
    if sha:
        body["sha"] = sha
    out = gh("PUT", path, body)
    if not out:
        return False, "no response"
    try:
        d = json.loads(out)
        return ("content" in d), (d.get("content", {}).get("sha", "?")[:7] if "content" in d else d.get("message", "?"))
    except json.JSONDecodeError:
        return False, "bad json"


# ============================================================
# 文件收集
# ============================================================
def collect_local_files():
    """返回 [(rel_path, local_abs, github_path)]"""
    files = []
    # 1. workspace 根目录文件
    for name in os.listdir(WORKSPACE):
        p = os.path.join(WORKSPACE, name)
        if not os.path.isfile(p) or any(re.match(pat, name) for pat in WS_EXCLUDE):
            continue
        if any(re.match(pat, name) for pat in WS_ROOT_PATTERNS):
            gp = f"quant_scripts/{name}" if name.endswith(".py") else name
            files.append((name, p, gp))
    # 2. 自建技能资产 → skills_backup/<name>/...
    for skill in SELF_SKILLS:
        sdir = os.path.join(SKILLS, skill)
        if not os.path.isdir(sdir):
            continue
        gbase = f"skills_backup/{skill}"
        # 顶层 SKILL.md
        top_skill = os.path.join(sdir, "SKILL.md")
        if os.path.isfile(top_skill):
            files.append((f"{skill}/SKILL.md", top_skill, f"{gbase}/SKILL.md"))
        # scripts/*.py（仅一层，防嵌套坏目录）
        sdir_scripts = os.path.join(sdir, "scripts")
        if os.path.isdir(sdir_scripts):
            for fn in os.listdir(sdir_scripts):
                if fn.endswith(".py") and os.path.isfile(os.path.join(sdir_scripts, fn)):
                    files.append((f"{skill}/scripts/{fn}", os.path.join(sdir_scripts, fn),
                                  f"{gbase}/scripts/{fn}"))
        # references/**（仅一层）
        sdir_ref = os.path.join(sdir, "references")
        if os.path.isdir(sdir_ref):
            for fn in os.listdir(sdir_ref):
                lp = os.path.join(sdir_ref, fn)
                if os.path.isfile(lp):
                    files.append((f"{skill}/references/{fn}", lp, f"{gbase}/references/{fn}"))
    return files


# ============================================================
# 快速 sha 对比（trees API 一次拿全量 + git hash-object）
# ============================================================
def get_all_gh_shas():
    """返回 {path: blob_sha}（仓库全部文件）"""
    url = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"
    cmd = ["curl", "-s", "--max-time", "120", "-H", f"Authorization: token {TOKEN}", url]
    for i in range(3):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            d = json.loads(r.stdout)
            if "tree" in d:
                return {t["path"]: t["sha"] for t in d["tree"] if t["type"] == "blob"}
        except Exception:
            pass
        time.sleep(2)
    return {}

def local_blob_sha(path):
    """本地文件 blob sha（与GitHub一致）"""
    try:
        r = subprocess.run(["git", "hash-object", path], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return None


# ============================================================
# 子命令
# ============================================================
def cmd_status(files):
    print("=" * 70)
    print("🔍 guard status —— 本地 vs GitHub 差异检测（sha快速对比）")
    print("=" * 70)
    gh_shas = get_all_gh_shas()
    if not gh_shas:
        print("ERROR: 无法获取GitHub文件树（限流/网络）")
        return [], []
    modified, missing, ok = [], [], 0
    for rel, lp, gp in files:
        if not os.path.exists(lp):
            missing.append(rel)
            continue
        lsha = local_blob_sha(lp)
        gsha = gh_shas.get(gp)
        if gsha is None:
            modified.append((rel, "GitHub无此文件(新文件待sync)"))
        elif lsha == gsha:
            ok += 1
        else:
            mtime = os.path.getmtime(lp)
            import datetime
            t = datetime.datetime.fromtimestamp(mtime)
            modified.append((rel, f"内容不同(本地mtime {t.strftime('%m-%d %H:%M')} UTC)"))
    print(f"\n✅ 一致: {ok} | ⚠️ 差异: {len(modified)} | ❌ 缺失: {len(missing)}")
    if modified:
        print("\n⚠️ 差异文件（可能是新修改或回滚，请人工判断）:")
        for rel, why in modified[:40]:
            print(f"   {rel}  [{why}]")
    if missing:
        print("\n❌ 本地缺失（可 restore 恢复）:")
        for rel in missing[:20]:
            print(f"   {rel}")
    return modified, missing



def cmd_sync(files, dry=False):
    print("=" * 70)
    print("📦 guard sync —— 本地 → GitHub 全量推送（GitHub为唯一真源）")
    print("=" * 70)
    n_ok = n_err = 0
    for rel, lp, gp in files:
        if not os.path.exists(lp):
            continue
        content = open(lp, encoding="utf-8", errors="replace").read()
        gsha = gh_sha(gp)
        if dry:
            print(f"  [dry] push {gp} ({len(content)}B)")
            continue
        ok, info = gh_put(gp, content, f"guard: sync {rel}", gsha)
        if ok:
            n_ok += 1
        else:
            n_err += 1
            print(f"  ERR {gp}: {info}")
        if (n_ok + n_err) % 20 == 0:
            print(f"  ... {n_ok} ok / {n_err} err")
    print(f"\n✅ 推送完成: {n_ok} 成功 / {n_err} 失败")


def cmd_restore(files, dry=False):
    print("=" * 70)
    print("♻️  guard restore —— GitHub → 本地恢复（应对平台回滚/沙箱清理）")
    print("=" * 70)
    n_ok = n_err = 0
    for rel, lp, gp in files:
        gd = gh_get(gp)
        if not gd or "content" not in gd:
            continue
        content = base64.b64decode(gd["content"].replace("\n", "")).decode("utf-8", errors="replace")
        if dry:
            print(f"  [dry] restore {lp}")
            continue
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        with open(lp, "w", encoding="utf-8") as f:
            f.write(content)
        n_ok += 1
    print(f"\n✅ 恢复完成: {n_ok} 文件（{n_err} 失败）")


def cmd_logcheck():
    print("=" * 70)
    print("🛡️  guard logcheck —— 日志类文件保护（只push不pull）")
    print("=" * 70)
    for fn in LOG_FILES:
        local_paths = []
        for base in (WORKSPACE, os.path.join(SKILLS, "猛兽体系", "scripts", "outputs"),
                     os.path.join(SKILLS, "猛兽体系", "scripts")):
            p = os.path.join(base, fn)
            if os.path.exists(p):
                local_paths.append(p)
        for lp in local_paths:
            n = sum(1 for _ in open(lp, encoding="utf-8", errors="replace"))
            print(f"  📄 {lp}: {n} 行 (本地真源，禁止被GitHub旧版覆盖)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    dry = "--dry" in sys.argv[2:]
    files = collect_local_files() if cmd in ("status", "sync", "restore") else []
    if cmd == "status":
        cmd_status(files)
    elif cmd == "sync":
        cmd_sync(files, dry)
    elif cmd == "restore":
        cmd_restore(files, dry)
    elif cmd == "logcheck":
        cmd_logcheck()
    else:
        print(f"未知命令: {cmd}\n{__doc__}")


if __name__ == "__main__":
    main()
