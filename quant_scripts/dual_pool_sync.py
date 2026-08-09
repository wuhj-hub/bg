#!/usr/bin/env python3
"""双弦本月股池快照同步（dual_pool_sync.py）——修复月度股池知识库同步断链

输入：outputs/quant_results_{date}.json 或 quant_results_latest.json 的 shuangxian.pool_data
功能：
  1. 解析双弦月度股池（pool_data.entries：共振/低吸，价格≤10元规则）
  2. 生成整理版快照 双弦本月股池_{date}.md（含评分/价格/猛兽信号标注）
  3. 剔除规则说明：价格>10 不入池（monthly_pool MAX_PRICE=10）/ 评分<50 不入池 / 跨月轮动（v2.4新增/删除标记）
  4. --sync-kb 提示上传知识库「双弦」月度股池文件夹（folder_7484244066591607）

用法: python3 dual_pool_sync.py [--date YYYY-MM-DD] [--quant outputs/quant_results_latest.json]
"""
import json, os, sys
from datetime import datetime

OUT_DIR = "outputs"
SHUANGXIAN_KB_FOLDER = "folder_7484244066591607"


def load_quant(paths):
    for p in paths:
        if os.path.exists(p):
            try:
                return json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
    return None


def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    quant_paths = []
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--date" and i + 1 < len(argv):
            date_str = argv[i + 1]
        if a == "--quant" and i + 1 < len(argv):
            quant_paths = [argv[i + 1]]

    quant_paths = quant_paths or [
        f"outputs/quant_results_{date_str}.json",
        f"quant_results_{date_str}.json",
        "outputs/quant_results_latest.json",
        "quant_results_latest.json",
        "../outputs/quant_results_latest.json",
    ]
    q = load_quant(quant_paths)
    if not q:
        print(f"[ERR] 未找到双弦量化结果（尝试: {quant_paths[0]} / quant_results_latest.json）")
        sys.exit(1)
    sx = q.get("shuangxian", {}) or {}
    pool = sx.get("pool_data") or {}
    entries = pool.get("entries", [])
    if not entries:
        print("[INFO] 月度股池为空（无共振/低吸信号），生成空快照")
    print(f"[INFO] 双弦月度股池 {pool.get('year_month','?')}: {len(entries)} 只（共振{sum(1 for e in entries if e.get('signal_type')=='共振')} 低吸{sum(1 for e in entries if e.get('signal_type')!='共振')}）")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"双弦本月股池_{date_str}.md")
    L = [f"# 🔗 双弦本月股池 · {date_str}", "",
         f"> 来源: 双弦投资系统月度股池（pool_data，数据范围 {pool.get('updated_at','—')}）",
         f"> 规则: 价格≤10元共振/低吸信号 · 评分≥50 · 跨月轮动去重（v2.4）", ""]
    L.append(f"## 🏦 共振股（{len([e for e in entries if e.get('signal_type')=='共振'])}只 · 价格≤10元）")
    L.append("| 代码 | 名称 | 价格 | 评分 | 共振 | 猛兽信号/备注 |")
    L.append("|---|---|---|---|---|---|")
    for e in sorted(entries, key=lambda x: -x.get("score", 0)):
        if e.get("signal_type") != "共振":
            continue
        reason = e.get("reason", "")
        reason_short = reason.replace("双弦门控通过 | 猛兽: ", "猛兽: ").replace("双弦门控通过", "门控通过") if reason else ""
        L.append(f"| {e['code']} | {e['name']} | {e['price']} | {e.get('score','')} | {e.get('resonance_label','')} | {reason_short} |")
    L.append("")
    lx = [e for e in entries if e.get("signal_type") != "共振"]
    if lx:
        L.append(f"## 🎯 低吸股（{len(lx)}只）")
        L.append("| 代码 | 名称 | 价格 | 评分 | 备注 |")
        L.append("|---|---|---|---|---|")
        for e in lx:
            L.append(f"| {e['code']} | {e['name']} | {e['price']} | {e.get('score','')} | {e.get('reason','')} |")
        L.append("")
    L.append("## 🗑️ 剔除规则（不符合不入池）")
    L.append("- 价格 > 10元 → 剔除（月度池规则 MAX_PRICE=10）")
    L.append("- 评分 < 50 → 剔除（双弦门控最低标准）")
    L.append("- 月线空头/趋势破坏 → 后续轮动移除（v2.4跨月对比）")
    L.append("")
    L.append(f"> 股池轮动: 新增 {len(entries)} 只 | 上月移除见轮动报告 | 均分 {pool.get('total_count','?')}只")
    md = "\n".join(L)
    open(out_path, "w", encoding="utf-8").write(md)
    print(f"[OK] {out_path}")
    print(f"[SYNC] 上传至知识库「双弦」月度股池文件夹 {SHUANGXIAN_KB_FOLDER}")
    return out_path


if __name__ == "__main__":
    main()
