#!/usr/bin/env python3
"""
run_all_quant.py —— 盘后量化三系统预运行调度器
===================================================
在 GitHub Actions 上运行：双弦 + 鱼身 + 猛兽
输出结果文件供复盘报告和盘前报告引用。

用法：python3 run_all_quant.py
输出：
  - outputs/quant_results_YYYY-MM-DD.json  (汇总结果)
  - outputs/shuangxian_pool.json           (双弦月度股池原始输出)
  - outputs/fishbody_results.json           (鱼身原始输出)
  - outputs/beast_results.json              (猛兽原始输出)
"""

import subprocess, sys, os, json, shutil
from datetime import datetime
from pathlib import Path

NOW = datetime.now()
TODAY = NOW.strftime("%Y-%m-%d")
SCRIPTS_DIR = Path(__file__).parent
REPO_DIR = SCRIPTS_DIR.parent
OUTPUTS_DIR = REPO_DIR / "outputs"

# ============================================================
# 环境检查
# ============================================================

def check_env():
    """验证运行环境"""
    ok = True
    if shutil.which("npx") is None:
        print("[FAIL] npx not found — need node.js")
        ok = False
    # 验证主要脚本存在
    for f in ["run_shuangxian.py", "monthly_pool.py", "fish_body_enhanced.py",
              "beast_screener.py", "stock_pool.txt"]:
        if not (SCRIPTS_DIR / f).exists():
            print(f"[FAIL] missing {f}")
            ok = False
    return ok


# ============================================================
# 工具
# ============================================================

def run_py(script, args="", cwd=None, timeout=600):
    """运行 Python 脚本并返回 stdout"""
    if cwd is None:
        cwd = str(REPO_DIR)
    full_cmd = f"python3 {script} {args}"
    print(f"[RUN] {full_cmd}  (cwd={cwd})")
    try:
        r = subprocess.run(full_cmd, shell=True, capture_output=True,
                          text=True, timeout=timeout, cwd=cwd)
        if r.returncode != 0:
            print(f"[WARN] exit={r.returncode}: {r.stderr[:300]}")
        return r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        print(f"[FAIL] timeout ({timeout}s)")
        return "", "TIMEOUT"
    except Exception as e:
        print(f"[FAIL] {e}")
        return "", str(e)


# ============================================================
# 1. 双弦系统
# ============================================================

def run_shuangxian():
    """运行双弦投资系统"""
    print("\n" + "=" * 50)
    print("🔗 双弦投资系统")
    print("=" * 50)

    # 确保 monthly_pool.py 在可导入路径
    # 复制到 repo 根目录下的 scripts/，让 run_shuangxian.py 能找到
    target_dir = REPO_DIR / "scripts"
    target_dir.mkdir(exist_ok=True)
    shutil.copy2(SCRIPTS_DIR / "monthly_pool.py", target_dir / "monthly_pool.py")

    # 确保 pools 目录存在
    (REPO_DIR / "pools").mkdir(exist_ok=True)

    stdout, stderr = run_py("quant_scripts/run_shuangxian.py", cwd=str(REPO_DIR))

    # 收集双弦输出
    result = {"stdout": stdout[:2000], "stderr": stderr[:1000]}

    # 读取月度股池文件
    pool_files = list((REPO_DIR / "pools").glob("pool_*.json"))
    if pool_files:
        latest = max(pool_files, key=lambda p: p.stat().st_mtime)
        try:
            pool_data = json.load(open(latest, encoding="utf-8"))
            result["pool_file"] = latest.name
            result["pool_data"] = pool_data
            print(f"[OK] 双弦完成 — 股池: {latest.name}")
        except Exception as e:
            print(f"[WARN] 读取股池失败: {e}")
    else:
        print("[WARN] 未生成月度股池文件")

    return result


# ============================================================
# 2. 鱼身系统
# ============================================================

def run_fishbody():
    """运行鱼身增强系统"""
    print("\n" + "=" * 50)
    print("🐟 鱼身交易系统")
    print("=" * 50)

    stock_pool = str(SCRIPTS_DIR / "stock_pool.txt")
    stdout, stderr = run_py(
        f"quant_scripts/fish_body_enhanced.py --pool {stock_pool}",
        cwd=str(REPO_DIR)
    )

    result = {"stdout": stdout[:2000], "stderr": stderr[:1000]}

    # 收集鱼身输出文件
    output_files = list(REPO_DIR.glob("outputs/fish_body_enhanced_*.json"))
    if output_files:
        latest = max(output_files, key=lambda p: p.stat().st_mtime)
        try:
            fish_data = json.load(open(latest, encoding="utf-8"))
            result["output_file"] = latest.name
            result["signal_count"] = len(fish_data.get("signals", []))
            result["market_temp"] = fish_data.get("market_temp", {})
            print(f"[OK] 鱼身完成 — 信号: {result['signal_count']}个, 温度: {result['market_temp']}")
        except Exception as e:
            print(f"[WARN] 读取鱼身结果失败: {e}")
    else:
        print("[WARN] 未生成鱼身结果文件")

    return result


# ============================================================
# 3. 猛兽体系
# ============================================================

def run_beast():
    """运行猛兽趋势量化体系"""
    print("\n" + "=" * 50)
    print("🐅 猛兽趋势量化")
    print("=" * 50)

    stdout, stderr = run_py("quant_scripts/beast_screener.py", cwd=str(REPO_DIR))

    # 保存输出
    beast_out = OUTPUTS_DIR / "beast_results.txt"
    OUTPUTS_DIR.mkdir(exist_ok=True)
    beast_out.write_text(stdout[:20000], encoding="utf-8")

    result = {
        "stdout": stdout[:3000],
        "stderr": stderr[:1000],
        "output_file": "beast_results.txt"
    }
    print(f"[OK] 猛兽完成 — 输出保存到 {beast_out.name}")

    return result


# ============================================================
# 4. 汇总
# ============================================================

def main():
    print("=" * 50)
    print("📊 盘后量化 · 三系统预运行")
    print(f"   日期: {TODAY}")
    print(f"   脚本: {SCRIPTS_DIR}")
    print(f"   输出: {OUTPUTS_DIR}")
    print("=" * 50)

    if not check_env():
        print("[FAIL] 环境检查未通过，终止")
        sys.exit(1)

    OUTPUTS_DIR.mkdir(exist_ok=True)

    # 运行三个系统
    results = {
        "date": TODAY,
        "timestamp": NOW.strftime("%Y-%m-%d %H:%M:%S"),
        "shuangxian": run_shuangxian(),
        "fishbody": run_fishbody(),
        "beast": run_beast(),
    }

    # 保存汇总结果
    summary_file = OUTPUTS_DIR / f"quant_results_{TODAY}.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 汇总结果 → {summary_file}")

    # 列出所有输出文件
    print("\n📋 输出文件列表:")
    for f in sorted(OUTPUTS_DIR.iterdir()):
        if f.is_file():
            size = f.stat().st_size
            print(f"  {f.name:40s} {size:>8,} bytes")

    print("\n✅ 三系统预运行全部完成！")


if __name__ == "__main__":
    main()
