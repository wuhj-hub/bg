#!/usr/bin/env python3
"""
kaipan_8.py —— 开盘八法·强形态扫描与突破预警
====================================================
9:45 后运行：对候选池（妖股/才哥/一统天下/自选）判定开盘八法形态，
筛选偏多强形态股票，给出当日突破预警位。

形态判定（三时段比较法）:
  第1盘 9:30-9:35 收盘 vs 昨收 | 第2盘 9:35-9:40 vs 第1盘 | 第3盘 9:40-9:45 vs 第2盘
  涨涨涨=三高盘(最强) | 跌涨涨=低接买盘(强) | 跌跌涨=止跌反弹(中)
  涨涨跌=强中拉回(观察) | 跌涨跌=多空胶着(中性) | 涨跌涨=短兵相接(观望)
  涨跌跌=上档卖压(偏空) | 跌跌跌=三低盘(最弱)

强形态优先级: 三高盘 > 低接买盘 > 止跌反弹 > 强中拉回

用法: python3 kaipan_8.py [--pool 自定义池txt] [--monitor 突破监控(默认关)]
输出: outputs/开盘强形态_{date}.md + 突破预警(PushPlus)
====================================================
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BJ = timezone(timedelta(hours=8))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
WORKERS = 3

def cli(cmd, timeout=60):
    full = WESTOCK + cmd.split()
    for attempt in range(3):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            if r.stdout.strip() and "执行失败" not in r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(1.5)
    return ""

def load_pool():
    """合并多个股池 txt → {code: name}"""
    pool = {}
    # ⚠️ 2026-09-15 修复：原只查 /sandbox/workspace/*.txt（=仓库根），但股池实际写在 quant_scripts/
    #    → 候选池恒为 0 只（开盘八法即使补算也无输入）。改为多候选：根目录 + quant_scripts/ + 脚本同级。
    _base = os.path.dirname(os.path.abspath(__file__))
    paths = []
    for _fn in ("yao_pool.txt", "caige_pool.txt", "yitong_pool.txt", "longtou_pool.txt", "holdings.txt"):
        for _d in ("/sandbox/workspace/quant_scripts", _base, "/sandbox/workspace"):
            _c = os.path.join(_d, _fn)
            if _c not in paths:
                paths.append(_c)
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for ln in f:
                s = ln.split("#")[0].strip()
                m = re.match(r"^(sh|sz)?(\d{6})$", s)
                if m:
                    code = (m.group(1) or ("sh" if m.group(2).startswith("6") else "sz")) + m.group(2)
                    name = ln.split("#")[-1].strip() if "#" in ln else ""
                    pool[code] = name
    return pool

def fetch_prev_close(code):
    """拉昨收 + 近5日平均成交额（2026-09-15：用于「放量确认」量比计算）
    返回 (prev_close, amt5avg) 或 None"""
    # ⚠️ 2026-09-15：单股 kline 接口间歇性返空（已知 flakiness），增加去复权回退
    md = cli(f"kline {code} --period day --limit 7 --fq qfq")
    if not any(x.strip().startswith("|") and re.match(r"^\|\s*\d{4}-\d{2}-\d{2}", x.strip()) for x in md.splitlines()):
        _md2 = cli(f"kline {code} --period day --limit 7")
        if any(x.strip().startswith("|") and re.match(r"^\|\s*\d{4}-\d{2}-\d{2}", x.strip()) for x in _md2.splitlines()):
            md = _md2
    rows = []
    has_symbol = "| symbol |" in md
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        try:
            if has_symbol:
                if parts[0] in ("symbol", "---"):
                    continue
                _amt = float(parts[7]) if len(parts) > 7 else 0.0
                rows.append((parts[1], float(parts[3]), _amt))
            else:
                if not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                    continue
                _amt = float(parts[6]) if len(parts) > 6 else 0.0
                rows.append((parts[0], float(parts[2]), _amt))
        except (ValueError, IndexError):
            continue
    rows.sort()
    if len(rows) < 2:
        return None
    prev_close = rows[-2][1]                      # 倒数第二根=昨收
    # 近5日平均成交额（不含今日，取倒数第2~6根）
    _amts = [a for _, _, a in rows[-6:-1] if a]
    amt5 = (sum(_amts) / len(_amts)) if len(_amts) >= 3 else None
    return (prev_close, amt5)

def fetch_minute(code):
    """当日分时 → [{time, price}]"""
    md = cli(f"minute {code}")
    rows = []
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 3 and re.match(r"\d{4}", parts[1]):
            try:
                amt = float(parts[4]) if len(parts) > 4 else 0.0   # 分钟 amount 为「当日累计成交额」
            except ValueError:
                amt = 0.0
            try:
                rows.append({"time": parts[1], "price": float(parts[2]), "amt": amt})
            except ValueError:
                continue
    return rows

def judge_8(rows, prev_close):
    """三盘判定 → (形态名, 三盘状态, 第3盘高点/低点)"""
    if len(rows) < 16 or not prev_close:
        return None
    # 9:30-9:35, 9:35-9:40, 9:40-9:45 三段（分钟数据 0930-0944）
    seg = {"1": [], "2": [], "3": []}
    for r in rows:
        t = r["time"]
        if t < "0935":
            seg["1"].append(r["price"])
        elif t < "0940":
            seg["2"].append(r["price"])
        elif t < "0945":
            seg["3"].append(r["price"])
    if not (seg["1"] and seg["2"] and seg["3"]):
        return None
    c1, c2, c3 = seg["1"][-1], seg["2"][-1], seg["3"][-1]
    up1 = c1 > prev_close
    up2 = c2 > c1
    up3 = c3 > c2
    pattern = f"{'涨' if up1 else '跌'}{'涨' if up2 else '跌'}{'涨' if up3 else '跌'}"
    names = {"涨涨涨": "三高盘", "涨涨跌": "强中拉回", "涨跌跌": "上档卖压",
             "跌涨涨": "低接买盘", "跌跌涨": "止跌反弹", "跌跌跌": "三低盘",
             "跌涨跌": "多空胶着", "涨跌涨": "短兵相接"}
    strength = {"三高盘": 5, "低接买盘": 4, "止跌反弹": 3, "强中拉回": 2,
                "多空胶着": 0, "短兵相接": 0, "上档卖压": -3, "三低盘": -5}
    h3 = max(seg["3"]); l3 = min(seg["3"])
    h1 = max(seg["1"]); l1 = min(seg["1"])
    # 三段量能（2026-09-15：与价格形态同为「三个5分钟」口径）
    #   分钟 amount 是「当日累计成交额」→ 段量用差分：v1=amt@0934, v2=amt@0939-amt@0934,
    #   v3=amt@0944-amt@0939。量能形态 = 后一段 vs 前一段的增减（两段比较，对应价格的两次转折）。
    def _amt_at(tt):
        v = [r["amt"] for r in rows if r["time"] <= tt and r.get("amt")]
        return v[-1] if v else 0.0
    a1, a2, a3 = _amt_at("0934"), _amt_at("0939"), _amt_at("0944")
    v1, v2, v3 = a1, max(a2 - a1, 0.0), max(a3 - a2, 0.0)
    vol_pattern = f"{'增' if v2 > v1 else '减'}{'增' if v3 > v2 else '减'}"
    # 末段量能保持度 = v3/v2（相对中段）。注意：正常形态是逐段递减（开盘量最大），
    # 故不能用"末段最大"这类绝对判据（会把所有票都滤掉），必须走相对分位（见下方 Step1.5）。
    tail_ratio = round(v3 / v2, 3) if v2 else None
    return {"pattern": names[pattern], "code3": f"{up1}{up2}{up3}",
            "h3": h3, "l3": l3, "h1": h1, "l1": l1,
            "strength": strength[names[pattern]], "prev_close": prev_close,
            "c3": c3, "v1": v1, "v2": v2, "v3": v3,
            "vol_pattern": vol_pattern, "tail_ratio": tail_ratio}

def analyze(code, name, prev_close_map):
    got = prev_close_map.get(code)
    if not got:
        got = fetch_prev_close(code)
    if not got:
        return None
    prev, amt5 = got if isinstance(got, tuple) else (got, None)
    rows = fetch_minute(code)
    if len(rows) < 16 or not prev:
        return None
    r = judge_8(rows, prev)
    if not r:
        return None
    # 放量确认（2026-09-15）：**纯分钟口径**，不依赖日线（单股 kline 接口间歇性返空）。
    #   量比 = 开盘15分钟累计成交额 ÷ (当日累计成交额 × 15/240)
    #   —— 含义：开盘 15 分钟的量强度相对「全天均匀节奏」的倍数（收盘口径下通常 5~10）。
    #   分母固定用 240，故盘中会整体偏高，但**所有股票同分母 → 相对排序可比**，
    #   而下游筛选用的是当日分位阈值（P60），系统性偏差不影响结果。
    amt15 = next((x["amt"] for x in rows if x["time"] >= "0944" and x["amt"]), None)
    amt_all = rows[-1]["amt"] if rows and rows[-1].get("amt") else None
    vol_ratio = None
    if amt15 and amt_all:
        vol_ratio = round(amt15 / (amt_all * 15 / 240), 3)
    return {"code": code, "name": name, "price": rows[-1]["price"],
            "vol_ratio": vol_ratio, "amt15": amt15, "amt_all": amt_all, **r}

def push_alert(title, content):
    try:
        import urllib.request, urllib.parse
        tok = os.environ.get("PUSH_TOKEN", "")
        if not tok:
            return
        body = urllib.parse.urlencode({"token": tok, "title": title, "content": content,
                                       "template": "markdown"}).encode()
        urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body), timeout=15)
        print("[push] 已推送:", title)
    except Exception as e:
        print("[push] 失败:", e)

def monitor_once(date_str):
    """突破监控：读当日强形态池，检查现价是否突破9:45高点"""
    jpath = f"/sandbox/workspace/outputs/开盘强形态_{date_str}.json"
    if not os.path.exists(jpath):
        print("[monitor] 无当日强形态数据，跳过")
        return
    data = json.load(open(jpath, encoding="utf-8"))
    strong = data.get("strong", [])
    if not strong:
        return
    # 已推送过的突破（防重复）
    pushed_file = f"/sandbox/workspace/outputs/开盘突破已推送_{date_str}.json"
    pushed = set()
    if os.path.exists(pushed_file):
        pushed = set(json.load(open(pushed_file, encoding="utf-8")))
    breaks = []
    for s in strong:
        code = s["code"]
        rows = fetch_minute(code)
        if not rows:
            continue
        cur = rows[-1]["price"]
        target = s["h3"]
        if cur >= target and code not in pushed:
            pct = (cur - s["prev_close"]) / s["prev_close"] * 100
            breaks.append(f"- {code} {s['name']} **突破{target:.2f}** 现价{cur:.2f}（{pct:+.1f}%）[{s['pattern']}]")
            pushed.add(code)
    if breaks:
        msg = f"📈 开盘强形态突破 {date_str}\n\n" + "\n".join(breaks)
        push_alert("📈突破预警", msg)
        json.dump(sorted(pushed), open(pushed_file, "w", encoding="utf-8"))
        print(f"[monitor] 突破 {len(breaks)} 只")
    else:
        print(f"[monitor] 无新突破（监控 {len(strong)} 只）")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", action="store_true", help="突破监控（读当日强形态池检查突破）")
    ap.add_argument("--auto", action="store_true", help="自动模式：9:45-9:55扫描，之后监控")
    ap.add_argument("--pool-file", default="")
    args = ap.parse_args()
    date_str = datetime.now(BJ).strftime("%Y-%m-%d")
    now_bj = datetime.now(BJ)
    _then_monitor = False      # 补算扫描后是否紧接着监控一次
    if args.auto:
        # 自动分阶段（2026-09-15 修复）
        # 原设计：9:40-9:55 扫描 → 9:55+ 监控。但实测 GitHub cron 在 9:40-9:55 几乎从不触发
        # （97 次运行 / 23 个交易日，平均仅 4.2 次/日、落在盘中的仅 2.3 次），导致强形态池
        # 从未生成、监控阶段永远打印"无当日强形态数据，跳过"——该功能上线以来从未生效。
        # 形态判定用的是 9:30-9:45 分钟K线，**属于历史数据、任何时间都能取**，
        # 故改为「当日缺强形态池就先补算」，并在补算后立即监控一次。
        hm = now_bj.hour * 100 + now_bj.minute
        jpath = f"/sandbox/workspace/outputs/开盘强形态_{date_str}.json"
        have_pool = os.path.exists(jpath)
        if now_bj.weekday() >= 5:
            print(f"[auto] {hm} 非交易日，跳过")
            return
        if 940 <= hm <= 955:
            args.monitor = False
            print(f"[auto] {hm} 扫描阶段")
        elif not have_pool and hm <= 1505:
            args.monitor = False
            _then_monitor = True
            print(f"[auto] {hm} 无当日强形态池 → 补算扫描（用 9:30-9:45 历史分钟K线）")
        elif 955 < hm <= 1505:
            args.monitor = True
            print(f"[auto] {hm} 监控阶段")
            monitor_once(date_str)
            return
        else:
            print(f"[auto] {hm} 跳过（非交易时段/已收盘）")
            return
    if args.monitor:
        monitor_once(date_str)
        return
    t0 = time.time()

    pool = load_pool()
    if args.pool_file and os.path.exists(args.pool_file):
        with open(args.pool_file, encoding="utf-8") as f:
            for ln in f:
                s = ln.split("#")[0].strip()
                m = re.match(r"^(sh|sz)?(\d{6})$", s)
                if m:
                    code = (m.group(1) or ("sh" if m.group(2).startswith("6") else "sz")) + m.group(2)
                    pool[code] = ln.split("#")[-1].strip() if "#" in ln else ""
    print(f"[INFO] {date_str} 开盘八法扫描: 候选池 {len(pool)} 只", flush=True)

    # Step0: 批量昨收（并发）
    codes = list(pool.keys())
    prev_close_map = {}
    print("[INFO] 拉取昨收...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_prev_close, c): c for c in codes}
        for f in as_completed(futs):
            v = f.result()
            if v:
                prev_close_map[futs[f]] = v
    print(f"  昨收完成 {len(prev_close_map)}/{len(codes)}，耗时 {time.time()-t0:.0f}s", flush=True)

    # Step1: 分时判定（并发）
    print("[INFO] 分时形态判定...", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(analyze, c, pool.get(c, ""), prev_close_map): c for c in codes}
        for f in as_completed(futs):
            r = f.result()
            if r:
                results.append(r)
    results.sort(key=lambda r: -r["strength"])
    elapsed = time.time() - t0
    # ⚠️ 2026-09-15 修复：候选池为空时 elapsed/len(results) 会 ZeroDivisionError 直接崩溃
    _per = f"{elapsed/len(results):.1f}s/只" if results else "—"
    print(f"[INFO] 判定完成 {len(results)} 只，总耗时 {elapsed:.0f}s（{_per}）", flush=True)

    # Step1.5 放量确认（2026-09-15 新增）：治「173 只强形态 / 35 只突破」的推送噪声
    #   量比 = 开盘15分钟成交额 ÷ 近5日全天平均成交额（均匀分布下 15/240 = 6.25%，开盘通常更高）
    #   用**当日前 40% 分位（P60）自适应阈值**——不拍固定值、随市况自适应；样本不足则不过滤（防误杀）。
    # 两把相对标尺（均取当日分位，自适应、不拍固定值）：
    #   ① 整体量比 = 开盘15min成交额 ÷ (当日累计额×15/240)   —— 「相对放量」
    #   ② 末段保持度 = v3/v2（第3个5分钟 ÷ 第2个5分钟）      —— 「尾段量能不衰减」
    _vr = sorted(r["vol_ratio"] for r in results if r.get("vol_ratio"))
    _tr = sorted(r["tail_ratio"] for r in results if r.get("tail_ratio"))
    THR = _vr[int(len(_vr) * 0.6)] if len(_vr) >= 20 else 0
    TTH = _tr[int(len(_tr) * 0.5)] if len(_tr) >= 20 else 0
    _med = _vr[len(_vr) // 2] if _vr else 0
    _tmed = _tr[len(_tr) // 2] if _tr else 0
    print(f"[INFO] 量比分布: 样本{len(_vr)} 中位{_med:.2f} → P60阈值 {THR:.2f} | "
          f"末段保持度(v3/v2) 中位{_tmed:.2f} → P50阈值 {TTH:.2f}", flush=True)

    # Step2: 输出
    # 量能确认 = 相对放量(P60) + 尾段不衰减(P50)，均基于「三个5分钟」的口径
    strong = [r for r in results if r["strength"] >= 3
              and (not THR or (r.get("vol_ratio") or 0) >= THR)
              and (not TTH or (r.get("tail_ratio") or 0) >= TTH)]
    _s3 = [r for r in results if r["strength"] >= 3]
    print(f"[INFO] 量能过滤: 形态达标 {len(_s3)} 只 → 过「放量+尾段」双标尺 {len(strong)} 只", flush=True)
    watch = [r for r in results if r["strength"] == 2]
    weak = [r for r in results if r["strength"] < 0]
    os.makedirs("/sandbox/workspace/outputs", exist_ok=True)
    md = [f"# 🌅 开盘八法·强形态扫描 {date_str}\n",
          f"**候选**: {len(pool)} | **有效判定**: {len(results)} | **耗时**: {elapsed:.0f}s\n"]
    md.append(f"\n## 🔥 强形态（{len(strong)}只·量能确认：放量P60≥{THR:.2f} 且 末段保持度P50≥{TTH:.2f}）→ 突破预警位 = 9:45高点\n")
    if strong:
        md.append("| 代码 | 名称 | 形态 | 量能(末段保持度) | 现价 | 9:45高 | 9:45低 | 预警位 | 量比 |")
        md.append("|------|------|------|------|------|--------|--------|--------|------|")
        for r in strong:
            _v = f"{r['vol_ratio']:.3f}" if r.get('vol_ratio') else "—"
            _t = f"{r['tail_ratio']:.2f}" if r.get('tail_ratio') is not None else "—"
            md.append(f"| {r['code']} | {r['name']} | **{r['pattern']}** | {r.get('vol_pattern','')}({_t}) | {r['price']:.2f} | {r['h3']:.2f} | {r['l3']:.2f} | **{r['h3']:.2f}** | {_v} |")
    else:
        md.append("📭 无强形态")
    md.append(f"\n## 👀 观察（{len(watch)}只）\n")
    for r in watch:
        md.append(f"- {r['code']} {r['name']} {r['pattern']} 现价{r['price']:.2f}")
    md.append(f"\n## ⚠️ 偏空（{len(weak)}只）\n")
    for r in weak[:10]:
        md.append(f"- {r['code']} {r['name']} {r['pattern']}")
    report = "\n".join(md)
    path = f"/sandbox/workspace/outputs/开盘强形态_{date_str}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n[OK] 报告: {path}")

    # 突破预警位 JSON（供监控）
    with open(f"/sandbox/workspace/outputs/开盘强形态_{date_str}.json", "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "elapsed": elapsed, "strong": strong}, f, ensure_ascii=False, indent=1)
    # 推送强形态清单
    if strong:
        lines = [f"🌅 开盘强形态 {date_str}（{len(strong)}只）\n"]
        for r in strong[:12]:
            _v = f" 量比{r['vol_ratio']:.2f}" if r.get('vol_ratio') else ""
            lines.append(f"- {r['code']} {r['name']} **{r['pattern']}** 突破位{r['h3']:.2f}{_v}")
        push_alert("🌅开盘强形态", "\n".join(lines))

    # 2026-09-15：补算场景下，紧接着做一次突破监控（触发稀少，一次运行把两件事都做完）
    if _then_monitor:
        print("[auto] 补算完成 → 继续突破监控")
        monitor_once(date_str)

if __name__ == "__main__":
    main()
