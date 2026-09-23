#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_tracker.py —— 纸面组合跟踪 v2（OOS 前瞻验证 · 不依赖实盘）
================================================================
v2 改造（2026-09-23，方案A）：
  ① 覆盖「体系所有股池」：--add 扫描各池文件，新标的自动入池（记录来源池）
  ② 到期退出：持有 ≥ MAX_DAYS 交易日后结仓（保留 closed 记录用于统计）
  ③ 落库闭环：产物需由 workflow 提交到仓库（原实现从不落库 → 每天白跑）
  ④ 定位修正：唯一价值 = **样本外(out-of-sample)前瞻验证**「回测结论在未来是否仍成立」

用法:
  python3 paper_tracker.py --init outputs/pool_signals_log.csv   # 首次初始化
  python3 paper_tracker.py --add                                 # 每日：各池新标的入池
  python3 paper_tracker.py --update                              # 每日：更新盈亏 + 到期结仓
  python3 paper_tracker.py --report                              # 输出对比报告
"""
import subprocess, sys, os, re, csv, json, argparse
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
PORTFOLIO = "outputs/paper_portfolio.json"
MAX_DAYS = 20          # 持有到期（自然日）
HOLD_CHECK = 20        # 与 MAX_DAYS 一致，便于阅读

# 体系各股池（来源名, 路径）——存在即采集
POOL_SOURCES = [
    ("鱼身", "quant_scripts/stock_pool.txt"),
    ("一统天下", "quant_scripts/yitong_pool.txt"),
    ("才哥", "quant_scripts/caige_pool.txt"),
    ("龙头", "quant_scripts/longtou_pool.txt"),
    ("龙头战法", "quant_scripts/dragon_pool.txt"),
    ("妖股", "quant_scripts/yao_pool.txt"),
    ("猛兽本月", "quant_scripts/beast_pool.txt"),
    ("乾坤A", "outputs/qiankun_a_latest.json"),
    ("双弦", "outputs/双弦观察池_latest.json"),
    ("猛兽突破", "outputs/beast_pool_latest.json"),
    ("宁静卡位", "quant_scripts/ai_chain_pool.json"),
    ("低空经济", "quant_scripts/low_altitude_pool.json"),
    ("固态电池", "quant_scripts/solid_battery_pool.json"),
    ("商业航天", "quant_scripts/space_pool.json"),
    ("西湖RSV", "outputs/xihu_rsv_latest.json"),
]


def run(args, timeout=45):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def parse_kline(txt):
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or "---" in parts[0]:
            continue
        try:
            di = header.index("date")
            ci = header.index("last")
            if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                rows.append((parts[di], float(parts[ci])))
        except (ValueError, IndexError):
            pass
    rows.sort(key=lambda r: r[0])
    return rows


def get_price(code):
    """日线 [(date, close)...] 升序；失败重试 3 次"""
    for _ in range(3):
        rows = parse_kline(run(["kline", code, "--period", "day", "--limit", "60"]))
        if rows:
            return rows
    return []


def load_rsg_state():
    rsg = {}
    for p in ("outputs/rsv_strength_latest.json", "rsv_strength_latest.json"):
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                for r in (d.get("launch", []) + d.get("hold", []) + d.get("exit", [])):
                    if r.get("code"):
                        rsg[r["code"]] = {"rsg_dev": r.get("rsg_dev"),
                                          "rsg_strong": bool(r.get("rsg_strong"))}
                break
            except Exception:
                continue
    return rsg


def _norm(code):
    """6位数字 → sh/sz 前缀"""
    c = (code or "").strip()
    if re.match(r"^(sh|sz)\d{6}$", c):
        return c
    m = re.search(r"(\d{6})", c)
    if not m:
        return ""
    d = m.group(1)
    if d[0] in ("6", "9"):
        return "sh" + d
    return "sz" + d


def collect_pool_codes():
    """扫描所有股池文件 → [(pool_name, code)]（txt 取代码；json 递归取 code 字段）"""
    out = []
    for pool, path in POOL_SOURCES:
        if not os.path.exists(path):
            continue
        try:
            if path.endswith(".json"):
                raw = json.load(open(path, encoding="utf-8"))
                found = []

                def walk(x):
                    if isinstance(x, dict):
                        for k, v in x.items():
                            if k in ("code", "symbol", "ts_code") and isinstance(v, str):
                                found.append(v)
                            else:
                                walk(v)
                    elif isinstance(x, list):
                        for i in x:
                            walk(i)
                walk(raw)
                codes = {_norm(c) for c in found}
            else:
                txt = open(path, encoding="utf-8", errors="ignore").read()
                codes = {_norm(c) for c in re.findall(r"\b(?:sh|sz)?\d{6}\b", txt)}
            for c in sorted(x for x in codes if x):
                out.append((pool, c))
        except Exception as e:
            print(f"  [WARN] 读取股池 {path} 失败: {e}")
    # 去重（同一只保留首个来源）
    seen, res = set(), []
    for pool, c in out:
        if c in seen:
            continue
        seen.add(c)
        res.append((pool, c))
    return res


def _load():
    if os.path.exists(PORTFOLIO):
        try:
            return json.load(open(PORTFOLIO, encoding="utf-8"))
        except Exception:
            pass
    return {"init_date": datetime.now().strftime("%Y-%m-%d"), "positions": [], "closed": []}


def _save(pf):
    os.makedirs(os.path.dirname(PORTFOLIO) or ".", exist_ok=True)
    json.dump(pf, open(PORTFOLIO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def init_portfolio(signals_file):
    signals = {}
    with open(signals_file, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            signals[(row.get("date", ""), row.get("code", ""))] = row
    pf = {"init_date": datetime.now().strftime("%Y-%m-%d"), "positions": [], "closed": []}
    for (sig_date, code), s in sorted(signals.items()):
        rows = get_price(code)
        if not rows:
            continue
        entry = next((c for d, c in rows if d >= sig_date), None)
        if entry is None:
            continue
        methods = ["A月线反转only"]
        if s.get("g1") in ("双阴", "一阴"):
            methods.append("B+武威G1")
        if s.get("finance") == "盈利":
            methods.append("C+v2.1盈利")
        pf["positions"].append({
            "code": code, "name": s.get("name", ""), "sig_date": sig_date, "entry": entry,
            "pool": "池信号", "methods": methods, "status": "open",
        })
    _save(pf)
    print(f"✅ 初始化: {len(pf['positions'])} 个信号")


def add_positions():
    """扫描各池 → 新标的入池（已持有/已结仓的跳过）"""
    pf = _load()
    have = {p["code"] for p in pf.get("positions", [])} | {p["code"] for p in pf.get("closed", [])}
    pools = collect_pool_codes()
    added, bypool = 0, {}
    for pool, code in pools:
        if code in have:
            continue
        rows = get_price(code)
        if not rows:
            continue
        pf.setdefault("positions", []).append({
            "code": code, "name": "", "sig_date": rows[-1][0], "entry": rows[-1][1],
            "pool": pool, "methods": [], "status": "open",
        })
        have.add(code)
        added += 1
        bypool[pool] = bypool.get(pool, 0) + 1
        print(f"  + [{pool}] {code} @{rows[-1][1]}")
    _save(pf)
    print(f"✅ 新增入池 {added} 只（池来源: {bypool or '无'}）")


def update_portfolio():
    pf = _load()
    if not pf.get("positions") and not pf.get("closed"):
        print("❌ 组合未初始化，先 --init/--add")
        return
    _rsg_now = load_rsg_state()
    closed_n = 0
    for p in list(pf.get("positions", [])):
        rows = get_price(p["code"])
        if not rows:
            continue
        p["cur_price"] = rows[-1][1]
        p["cur_date"] = rows[-1][0]
        p["ret"] = (p["cur_price"] / p["entry"] - 1) * 100
        try:
            p["days"] = (datetime.strptime(rows[-1][0], "%Y-%m-%d") - datetime.strptime(p["sig_date"], "%Y-%m-%d")).days
        except Exception:
            p["days"] = 0
        _rg = _rsg_now.get(p["code"], {})
        p["rsg_now"] = _rg.get("rsg_dev")
        p["rsg_now_strong"] = _rg.get("rsg_strong", False)
        # 到期结仓
        if p.get("days", 0) >= MAX_DAYS:
            p["status"] = "closed"
            p["close_ret"] = p["ret"]
            pf.setdefault("closed", []).append(p)
            pf["positions"].remove(p)
            closed_n += 1
    pf["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _save(pf)
    print(f"✅ 已更新：持仓 {len(pf.get('positions', []))} 只 | 本期到期结仓 {closed_n} 只 | 历史结仓 {len(pf.get('closed', []))} 只")


def _stat(rets):
    if not rets:
        return "—", "—", "—"
    wins = [r for r in rets if r > 0]
    return (f"{len(wins)/len(rets)*100:.0f}%", f"{sum(rets)/len(rets):+.2f}%", f"{sum(rets):+.1f}%")


def report():
    pf = _load()
    positions = [p for p in pf.get("positions", []) if "ret" in p]
    closed = [p for p in pf.get("closed", []) if "close_ret" in p]
    L = []
    A = L.append
    A("# 📊 纸面组合跟踪报告 v2（OOS 前瞻验证）\n")
    A(f"> 初始化 {pf.get('init_date')} | 更新 {pf.get('last_update')} | 在场 {len(positions)} 只 | 已结仓 {len(closed)} 只")
    A("> **口径**：入池日收盘 = 入场价；现价盈亏；持有 ≥20 天结仓。**定位 = 样本外前瞻**（回测结论在未来是否仍成立）\n")

    # 一、按股池分组（当前在场）
    A("## 一、各股池表现（在场持仓）\n")
    A("| 股池 | 持仓数 | 胜率 | 平均收益 | 累计 |")
    A("|:----|:---:|:----:|:-------:|:----:|")
    byp = {}
    for p in positions:
        byp.setdefault(p.get("pool", "?"), []).append(p["ret"])
    for k in sorted(byp, key=lambda x: -sum(byp[x]) / len(byp[x])):
        w, m, c = _stat(byp[k])
        A(f"| {k} | {len(byp[k])} | {w} | {m} | {c} |")

    # 二、已结仓统计（更有意义：完整周期）
    if closed:
        A("\n## 二、已结仓统计（完整持有周期，样本外验证）\n")
        A("| 股池 | 结仓数 | 胜率 | 平均收益 | 累计 |")
        A("|:----|:---:|:----:|:-------:|:----:|")
        bp2 = {}
        for p in closed:
            bp2.setdefault(p.get("pool", "?"), []).append(p["close_ret"])
        for k in sorted(bp2, key=lambda x: -sum(bp2[x]) / len(bp2[x])):
            w, m, c = _stat(bp2[k])
            A(f"| {k} | {len(bp2[k])} | {w} | {m} | {c} |")
        w, m, c = _stat([p["close_ret"] for p in closed])
        A(f"\n> **合计**：{len(closed)} 笔 | 胜率 {w} | 平均 {m} | 累计 {c}")

    # 三、在场明细
    A("\n## 三、在场持仓明细\n")
    A("| 代码 | 股池 | 入场日 | 入场价 | 现价 | 盈亏 | 天数 |")
    A("|:----|:----|:----|:----:|:----:|:----:|:----:|")
    for p in sorted(positions, key=lambda x: -x.get("ret", 0)):
        A(f"| {p['code']} | {p.get('pool','?')} | {p['sig_date']} | {p['entry']:.2f} | {p.get('cur_price',0):.2f} | {p.get('ret',0):+.1f}% | {p.get('days',0)} |")
    A("\n---")
    A("⚠️ 纸面模拟，非实盘记录，不构成投资建议。")
    md = "\n".join(L)
    os.makedirs("outputs", exist_ok=True)
    out = f"outputs/纸面组合跟踪报告_{datetime.now().strftime('%Y-%m-%d')}.md"
    open(out, "w", encoding="utf-8").write(md)
    print(f"[OK] {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="", help="从信号日志CSV初始化")
    ap.add_argument("--add", action="store_true", help="扫描所有股池，新标的入池")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.init:
        init_portfolio(a.init)
    elif a.add:
        add_positions()
    elif a.update:
        update_portfolio()
    elif a.report:
        report()
    else:
        print(__doc__)
