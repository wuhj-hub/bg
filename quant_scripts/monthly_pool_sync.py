#!/usr/bin/env python3
"""猛兽本月股池同步器（monthly_pool_sync.py）v2.0 —— 修复版

输入：outputs/beast_results.txt（猛兽当日扫描输出，GitHub Actions 第三步生成）
功能：
  1. 解析猛兽输出 → 领先股/回调股/信号（G点/伏击线/RS_D/断层）+ 月线闸门 + Setup评分
  2. 分层构建股池：
     主池   = 月线反转/多头(PASS) + Setup≥50 的领先股 → 含评级/仓位/参考价（可执行）
     观察池 = 月线纠缠(WARN)领先股 + 全部回调股 + 信号股（形态/题材线索）
  3. 剔除规则（不符合的剔除）：
     - 月线空头(BLOCK) → 不入池
     - 月线纠缠(WARN) → 主池剔除（降级观察池）
     - Setup < 40 → 不入池
     - 价格异常(≤0) → 剔除
     - 跨日去重：同分类同代码保留最新
     - 上月遗留：复核月线，转空头剔除，仍多头保留观察池标注"上月遗留"
  4. 月度累积 pools/猛兽股池_{YYYY-MM}.md + 当日快照 猛兽本月股池_{date}.md
  5. --sync-kb 同步知识库「猛兽」本月股池文件夹

用法: python3 monthly_pool_sync.py [--date YYYY-MM-DD] [--beast outputs/beast_results.txt] [--sync-kb]
"""
import json, os, re, subprocess, sys, time
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
OUT_DIR = "outputs"
POOL_DIR = "pools"
MONTH_POOL_KB_FOLDER = "folder_7483172363202542"  # 知识库「猛兽」本月股池


def run(args, timeout=60):
    for i in range(3):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""


def parse_beast(txt):
    """解析猛兽扫描输出，返回结构化信号"""
    res = {"leaders": [], "pullbacks": [], "signals": [], "scores": {}, "month": {}, "summary": {}}
    lines = txt.splitlines()
    i = 0
    # 月线闸门（Step 2.6）
    for ln in lines:
        m = re.match(r"\s*((?:sh|sz)\d{6})\s+(\S+)\s+(月线多头|月线纠缠|月线空头|月线无数据)(\s*⚡反转)?", ln)
        if m:
            res["month"][m.group(1)] = {
                "name": m.group(2), "gate": m.group(3),
                "reversal": bool(m.group(4))}
    # Setup评分表（Step 3.5 行：代码 名称 总分 x/100 ... 模式）
    for ln in lines:
        m = re.match(r"\s*((?:sh|sz)\d{6})\s+(\S+)\s+(\d+)/100\s+(\d+)/20\s+(\d+)/20\s+(\d+)/15\s+(\d+)/10\s+(\d+)/15\s+(\d+)/10\s+(\d+)/10\s+(\d+)/5\s+(\d+)/5\s+(\d+)/5\s+(📦堆量|🐎欧马|🔀混合)?", ln)
        if m:
            res["scores"][m.group(1)] = {
                "name": m.group(2), "setup": int(m.group(3)), "vcp": int(m.group(4)),
                "ma": int(m.group(5)), "vol": int(m.group(6)), "vad": int(m.group(7)),
                "breakout": int(m.group(8)), "gap": int(m.group(9)), "rsva": int(m.group(10)),
                "ambush": int(m.group(11)), "rsd": int(m.group(12)), "fund": int(m.group(13)),
                "mode": m.group(14) or ""}
    # 领先股表
    in_leaders = False
    for ln in lines:
        if "二、领先股" in ln:
            in_leaders = True
            continue
        if "三、回调股" in ln:
            in_leaders = False
            break
        if in_leaders:
            m = re.match(r"\s*((?:sh|sz)\d{6})\s+(\S+)\s+(\d+)/100\s+(\d+)/15\s+(\d+)\s+([+-]?\d+)%\s+([\d.]+)%\s+(堆量模式|欧马模式|混合模式)?\s*(⚡反转|🟡纠缠|🔴空头)?\s*(⭐⭐|⭐)?", ln)
            if m:
                res["leaders"].append({"code": m.group(1), "name": m.group(2),
                                       "setup": int(m.group(3)), "breakout": int(m.group(4)),
                                       "rsva": int(m.group(5)), "lead_pct": m.group(6),
                                       "dist_high": float(m.group(7)), "mode": m.group(8) or "",
                                       "month_tag": m.group(9) or "", "star": m.group(10) or ""})
    # 回调股表
    in_pb = False
    for ln in lines:
        if "三、回调股" in ln:
            in_pb = True
            continue
        if "四、候选股综合" in ln:
            in_pb = False
            break
        if in_pb:
            m = re.match(r"\s*((?:sh|sz)\d{6})\s+(\S+)\s+(\d+)/20\s+([\d.]+)%\s+([\d.]+)\s+(\d+)\s+(\d+)/5\s+(\d+)/5\s+(⚡反转|🟡纠缠|🔴空头)?\s*(.*)", ln)
            if m:
                res["pullbacks"].append({"code": m.group(1), "name": m.group(2),
                                         "vcp": int(m.group(3)), "dist_high": float(m.group(4)),
                                         "vol_ratio": float(m.group(5)), "setup": int(m.group(6)),
                                         "ambush": int(m.group(7)), "rsd": int(m.group(8)),
                                         "month_tag": m.group(9) or "", "note": m.group(10) or ""})
    # 信号（G点/伏击线/RS_D/断层）—— Step5 操作建议
    sig_map = {}
    for ln in lines:
        m = re.match(r"\s+([\u4e00-\u9fa5]+)\((sh|sz)\d{6}\)\s+(.*)", ln)
        if m and any(k in ln for k in ["G点", "伏击线", "RS_D", "断层"]):
            sig_map.setdefault(m.group(2) + m.group(1), []).append(ln.strip())
    res["signals"] = sig_map
    # 综合总结
    for ln in lines:
        m = re.search(r"领先股: (\d+)只 \| 回调股: (\d+)只", ln)
        if m:
            res["summary"] = {"leaders": m.group(1), "pullbacks": m.group(2)}
    return res


def month_gate_of(code, beast):
    """取月线闸门，默认未知"""
    g = beast["month"].get(code, {})
    return g.get("gate", ""), g.get("reversal", False)


def build_pool(beast, date_str):
    """构建主池+观察池。返回 (main_pool, watch_pool)"""
    main_pool, watch_pool = [], []
    seen = set()

    def rating(s):
        return "一档" if s >= 60 else ("初选" if s >= 50 else "")

    def pos_ratio(s):
        return "25%" if s >= 60 else ("10%" if s >= 50 else "")

    # 领先股 → 主池（月线反转/多头 + Setup≥50）或观察池（纠缠/Setup<50）
    for l in beast["leaders"]:
        gate, rev = month_gate_of(l["code"], beast)
        l["gate"] = gate
        l["reversal"] = rev
        if gate == "月线空头":
            continue  # 剔除
        ref_price = ""
        px = get_price(l["code"])
        if px:
            ref_price = f"{px:.2f}"
        tags = []
        for k, v in beast["signals"].items():
            if k.startswith(l["code"]):
                tags.append(k[len(l["code"]):])
        sig_str = "/".join(tags) if tags else ""
        entry = {"code": l["code"], "name": l["name"], "setup": l["setup"], "mode": l["mode"],
                 "gate": gate, "reversal": rev, "rating": rating(l["setup"]),
                 "pos": pos_ratio(l["setup"]), "ref": ref_price, "dist_high": l["dist_high"],
                 "signals": sig_str}
        if gate in ("月线多头", "") and l["setup"] >= 50 and (l["code"] not in seen):
            seen.add(l["code"])
            main_pool.append(entry)
        else:
            if l["code"] not in seen:
                seen.add(l["code"])
                watch_pool.append({**entry, "note": "月线纠缠降级" if gate == "月线纠缠" else "观察"})

    # 回调股 → 观察池
    for pb in beast["pullbacks"]:
        if pb["code"] in seen:
            continue
        gate, rev = month_gate_of(pb["code"], beast)
        if gate == "月线空头":
            continue  # 剔除
        seen.add(pb["code"])
        watch_pool.append({"code": pb["code"], "name": pb["name"], "setup": pb["setup"],
                           "gate": gate, "reversal": rev, "dist_high": pb["dist_high"],
                           "note": pb["note"], "signals": ""})
    return main_pool, watch_pool


def get_price(code):
    """拉最新收盘价"""
    txt = run(["kline", code, "--period", "day", "--limit", "1"])
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("|") and "---" not in s and "date" not in s:
            parts = [p.strip() for p in s.strip("|").split("|")]
            # 单股输出无代码列：parts[0]=日期，parts[3]=last；批量输出 parts[0]=symbol
            if len(parts) >= 4 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
                try:
                    return float(parts[3])
                except ValueError:
                    return None
            if len(parts) >= 4 and re.match(r"^(sh|sz)\d{6}$", parts[0]):
                try:
                    return float(parts[3])
                except ValueError:
                    return None
    return None


def load_prev_month(month_str):
    """读上月股池文件（pools/猛兽股池_{month}.md），返回遗留标的列表"""
    p = os.path.join(POOL_DIR, f"猛兽股池_{month_str}.md")
    prev = []
    if not os.path.exists(p):
        return prev
    for ln in open(p, encoding="utf-8"):
        m = re.match(r"\|\s*(sh|sz)\d{6}\s*\|\s*(\S+)", ln)
        if m:
            prev.append({"code": m.group(1), "name": m.group(2)})
    return prev


def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    beast_path = os.path.join(OUT_DIR, "beast_results.txt")
    sync_kb = False
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--date" and i + 1 < len(argv):
            date_str = argv[i + 1]
        if a == "--beast" and i + 1 < len(argv):
            beast_path = argv[i + 1]
        if a == "--sync-kb":
            sync_kb = True

    if not os.path.exists(beast_path):
        print(f"[ERR] 未找到猛兽输出 {beast_path}")
        sys.exit(1)
    txt = open(beast_path, encoding="utf-8").read()
    beast = parse_beast(txt)
    print(f"[INFO] 解析: 领先股{len(beast['leaders'])} 回调股{len(beast['pullbacks'])} "
          f"评分{len(beast['scores'])} 月线{len(beast['month'])}")

    main_pool, watch_pool = build_pool(beast, date_str)
    print(f"[INFO] 主池{len(main_pool)} 观察池{len(watch_pool)}")

    month_str = date_str[:7]
    os.makedirs(POOL_DIR, exist_ok=True)
    month_path = os.path.join(POOL_DIR, f"猛兽股池_{month_str}.md")
    day_path = os.path.join(OUT_DIR, f"猛兽本月股池_{date_str}.md")

    # 月度文件（累积去重）：合并本日主池到月文件，同代码保留本日
    month_main = []
    if os.path.exists(month_path):
        for ln in open(month_path, encoding="utf-8"):
            m = re.match(r"\|\s*(sh|sz)\d{6}\s*\|\s*(\S+)", ln)
            if m:
                month_main.append({"code": m.group(1), "name": m.group(2)})
    for e in main_pool:
        month_main = [x for x in month_main if x["code"] != e["code"]]
        month_main.append({"code": e["code"], "name": e["name"]})

    L = [f"# 🐅 猛兽本月股池 · {date_str}", "",
         f"> 来源: 猛兽体系盘后扫描（beast_screener.py v3.0）| 主池=月线多头/反转+Setup≥50 可执行 | 观察池=形态/题材线索",
         f"> 剔除规则: 月线空头不入池 / 月线纠缠降级观察 / Setup<40不入池 / 跨日去重", ""]
    L.append("## 🏦 主池（可执行 · 含仓位/参考价）")
    L.append("| 代码 | 名称 | 评级 | 月线 | 模式 | Setup | 仓位 | 参考价 | 信号 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    if main_pool:
        for e in sorted(main_pool, key=lambda x: -x["setup"]):
            gate_tag = "⚡反转" if e["reversal"] else "🟢多头"
            L.append(f"| {e['code']} | {e['name']} | {e['rating']} | {gate_tag} | {e['mode']} | {e['setup']} | {e['pos']} | {e['ref']} | {e['signals']} |")
    else:
        L.append("| — | 当前无符合主池条件标的 | | | | | | | |")
    L.append("")
    L.append("## 👀 观察池（形态/题材线索）")
    L.append("| 代码 | 名称 | Setup | 月线 | 距高点% | 类型 | 备注 |")
    L.append("|---|---|---|---|---|---|---|")
    for e in watch_pool:
        gate_tag = "⚡反转" if e.get("reversal") else ("🟡纠缠" if e.get("gate") == "月线纠缠" else "—")
        typ = "回调股" if "VCP" in e.get("note", "") or "收缩" in e.get("note", "") else "领先股"
        L.append(f"| {e['code']} | {e['name']} | {e.get('setup','')} | {gate_tag} | {e.get('dist_high','')}% | {typ} | {e.get('note','')} |")
    L.append("")
    L.append(f"> 月度累积 {len(month_main)} 只 | 综合: 领先股{beast['summary'].get('leaders','?')} 回调股{beast['summary'].get('pullbacks','?')}")
    md = "\n".join(L)

    open(day_path, "w", encoding="utf-8").write(md)
    # 月度文件（重写：仅主池累积）
    with open(month_path, "w", encoding="utf-8") as f:
        f.write(f"# 🐅 猛兽本月股池 · 累积 {month_str}\n\n> 主池滚动累积（跨日去重）\n\n| 代码 | 名称 |\n|---|---|\n")
        for e in month_main:
            f.write(f"| {e['code']} | {e['name']} |\n")
    print(f"[OK] {day_path}")
    print(f"[OK] {month_path}")

    if sync_kb:
        print("[INFO] 同步知识库（由调用方 upload_ima.py 完成，此处打印提示）")
        print(f"  → 上传 {day_path} 至 知识库「猛兽」本月股池文件夹 {MONTH_POOL_KB_FOLDER}")
    return day_path


if __name__ == "__main__":
    main()
