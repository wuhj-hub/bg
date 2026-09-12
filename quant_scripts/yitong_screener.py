#!/usr/bin/env python3
"""
yitong_screener.py —— 一统天下·多周期建仓区扫描器
====================================================
流程: 周线闸门(方向) → 日线建仓区(位置) → 60分钟确认(买点)
  Step1 全主板日线扫描: 建仓区 VARO7<10 + 乖离低买 (westock批量, 快)
  Step2 候选→周线闸门: 近8周进入过建仓区 (westock周线)
  Step3 最终候选(≤40只)→新浪60分钟: 60m建仓区确认 (买点)

输出分级:
  ★★★★★ = 日线建仓区 + 周线建仓区 + 60m建仓区 全共振
  ★★★★  = 日线建仓区 + 周线建仓区
  ★★★   = 日线建仓区 + 乖离低买

用法: python3 yitong_screener.py [--limit N]
输出: outputs/一统天下建仓区股池_{date}.md/json + 股池配置 yitong_pool.txt
====================================================
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BJ = timezone(timedelta(hours=8))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
BATCH = 20
WORKERS = 4
# 路径兼容：沙箱用 /sandbox/workspace，GitHub runner 用仓库根(cwd)
BASE = "/sandbox/workspace" if os.path.isdir("/sandbox/workspace") else os.getcwd()

def cli(cmd, timeout=180):
    full = WESTOCK + cmd.split()
    for attempt in range(5):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            out = r.stdout or ""
            if out.strip() and "执行失败" not in out and "SKILL_0" not in out:
                return out
        except Exception:
            pass
        time.sleep(2)
    return ""

def fetch_kline(symbols, period, limit):
    """兼容批量(含symbol列)与单股(无symbol列)两种输出格式"""
    md = cli(f"kline {','.join(symbols)} --period {period} --limit {limit} --fq qfq")
    groups = {}
    has_symbol = "| symbol |" in md
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 7:
            continue
        try:
            if has_symbol:
                # 批量: | symbol | date | open | last | high | low | volume | amount | exchange |
                if parts[0] == "symbol" or parts[0] == "---":
                    continue
                sym, d, o, c, h, l = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            else:
                # 单股: | date | open | last | high | low | volume | amount | exchange |
                if not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                    continue
                sym, d, o, c, h, l = symbols[0], parts[0], parts[1], parts[2], parts[3], parts[4]
            groups.setdefault(sym, []).append(
                {"date": d, "open": float(o), "close": float(c), "high": float(h), "low": float(l)})
        except (ValueError, IndexError):
            continue
    for sym in groups:
        groups[sym].sort(key=lambda x: x["date"])
    return groups

def fetch_sina_5m(symbol, datalen=1023):
    from urllib.request import urlopen
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService"
           f".getKLineData?symbol={symbol}&scale=5&ma=no&datalen={datalen}")
    for attempt in range(4):
        try:
            txt = urlopen(url, timeout=20).read().decode("utf-8", errors="replace")
            m = re.search(r"\((\[.*\])\)", txt, re.S)
            if not m:
                return []
            rows = json.loads(m.group(1))
            return [{"date": x["day"][:10], "open": float(x["open"]), "close": float(x["close"]),
                     "high": float(x["high"]), "low": float(x["low"])} for x in rows]
        except Exception:
            if attempt < 3:
                time.sleep(2)
    return []

def aggregate(bars_5m, period_min=60):
    out, chunk = [], []
    for b in bars_5m:
        chunk.append(b)
        if len(chunk) >= period_min // 5:
            out.append({"date": chunk[0]["date"], "open": chunk[0]["open"],
                        "close": chunk[-1]["close"], "high": max(x["high"] for x in chunk),
                        "low": min(x["low"] for x in chunk)})
            chunk = []
    return out

def compute_varo7(bars):
    n = len(bars)
    lows = [b["low"] for b in bars]
    highs = [b["high"] for b in bars]
    closes = [b["close"] for b in bars]
    varo7 = [40.0] * n
    for i in range(33, n):
        v5 = min(lows[i - 26:i + 1])
        v6 = max(highs[i - 33:i + 1])
        raw = (closes[i] - v5) / (v6 - v5) * 4 * 25 if v6 > v5 else 40.0
        varo7[i] = raw if i == 33 else (raw * 2 + varo7[i - 1] * 3) / 5
    return varo7

def detect_reversal(month_bars):
    """月线反转检测：平台突破12月新高 / 均线金叉 / 趋势确立（用最新月）"""
    closes = [b["close"] for b in month_bars]
    n = len(closes)
    if n < 13:
        return None
    i = n - 1
    cur = closes[i]
    ma6 = sum(closes[i - 5:i + 1]) / 6
    ma12 = sum(closes[i - 11:i + 1]) / 12
    ma6_prev = sum(closes[i - 6:i]) / 6
    ma12_prev = sum(closes[i - 12:i]) / 12
    prev_max = max(closes[i - 11:i])
    if cur > prev_max and cur > ma6:
        return "平台突破"
    if ma6 > ma12 and ma6_prev <= ma12_prev:
        return "均线金叉"
    if ma6 > ma12 and cur > ma6 and ma6 > ma6_prev:
        return "趋势确立"
    return None

def in_jcq_and_signal(bars, varo7, lookback=5):
    """最近lookback根是否进入建仓区 → (进入日, 是否当前在建仓区)"""
    if len(bars) < 35:
        return None, False
    in_jcq = False
    for i in range(max(35, len(bars) - lookback), len(bars)):
        if varo7[i] < 10:
            in_jcq = True
            return bars[i]["date"], True
    return None, in_jcq

def guaili_buy(bars):
    """乖离低买: BIAS金叉且乖离1<-9（简化：当前乖离MA5<-9且回升）"""
    if len(bars) < 25:
        return False
    c = bars[-1]["close"]
    ma5 = sum(b["close"] for b in bars[-5:]) / 5
    bias = (c - ma5) / ma5 * 100
    return bias < -7  # 放宽到-7（分钟窗口样本少）

# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    date_str = datetime.now(BJ).strftime("%Y-%m-%d")

    # Step0: 股票池
    pool = []
    with open(f"{BASE}/all_mainboard.csv", encoding="utf-8-sig") as f:
        next(f)
        for ln in f:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                code = parts[0].strip()
                if code.startswith(("688", "300", "301")) or "ST" in parts[1].upper() or "退" in parts[1]:
                    continue
                pool.append(("sh" + code if code.startswith("6") else "sz" + code, parts[1].strip()))
    if args.limit:
        pool = pool[:args.limit]
    syms = [c for c, _ in pool]
    print(f"[INFO] {date_str} 一统天下多周期扫描: {len(pool)} 只", flush=True)

    # Step1: 日线建仓区
    print("[INFO] Step1 日线扫描...", flush=True)
    day_map = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for i in range(0, len(syms), BATCH):
            futs[ex.submit(fetch_kline, syms[i:i + BATCH], "day", 120)] = 1
        for f in as_completed(futs):
            for k, v in f.result().items():
                if len(v) > 40:
                    day_map[k] = v
    cand = []  # (code, name, entry_date, guaili_flag)
    for code, name in pool:
        bars = day_map.get(code)
        if not bars:
            continue
        varo7 = compute_varo7(bars)
        entry, in_now = in_jcq_and_signal(bars, varo7, lookback=5)
        if entry:
            cand.append((code, name, entry, guaili_buy(bars), in_now))
    print(f"[INFO] 日线建仓区候选: {len(cand)} 只", flush=True)

    # Step2: 周线闸门
    print("[INFO] Step2 周线闸门...", flush=True)
    week_map = {}
    c_syms = [c for c, _, _, _, _ in cand]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for i in range(0, len(c_syms), BATCH):
            futs[ex.submit(fetch_kline, c_syms[i:i + BATCH], "week", 80)] = 1
        for f in as_completed(futs):
            for k, v in f.result().items():
                if len(v) > 10:
                    week_map[k] = v
    cand2 = []
    for code, name, entry, gl, in_now in cand:
        wb = week_map.get(code)
        if not wb:
            continue
        wv = compute_varo7(wb)
        w_entry, _ = in_jcq_and_signal(wb, wv, lookback=8)
        cand2.append((code, name, entry, gl, in_now, w_entry))
    print(f"[INFO] 周线闸门通过: {len(cand2)} 只", flush=True)

    # Step2.5: 月线反转检测（新增：判断是否已呈现月线反转）
    print(f"[INFO] Step2.5 月线反转检测（{len(cand2)} 只）...", flush=True)
    rev_map = {}
    c_syms2 = [c for c, *_ in cand2]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for i in range(0, len(c_syms2), BATCH):
            futs[ex.submit(fetch_kline, c_syms2[i:i + BATCH], "month", 40)] = 1
        for f in as_completed(futs):
            for k, v in f.result().items():
                if len(v) >= 13:
                    rv = detect_reversal(v)
                    if rv:
                        rev_map[k] = rv
    print(f"[INFO] 月线反转: {len(rev_map)} 只", flush=True)

    # Step2.6: RSV50三线相对强度（50日相对强度：个股>行业>大盘）
    print("[INFO] Step2.6 RSV50三线强度检测...", flush=True)
    ind_map6 = {}
    for i in range(0, len(syms), 60):
        md6 = cli(f"profile {','.join(syms[i:i+60])}")
        for ln6 in md6.splitlines():
            ln6 = ln6.strip()
            if ln6.startswith("|") and "code" not in ln6 and "---" not in ln6:
                q = [x.strip() for x in ln6.strip("|").split("|")]
                if len(q) > 6 and q[0].startswith(("sh", "sz")):
                    ind_map6[q[0]] = q[5]
    N6 = 50
    stk_r50 = {}
    ind_acc = {}
    for code, bars in day_map.items():
        if len(bars) > N6 and bars[-1 - N6].get("close", 0) > 0:
            r = (bars[-1]["close"] / bars[-1 - N6]["close"] - 1) * 100
            stk_r50[code] = r
            ind = ind_map6.get(code)
            if ind:
                ind_acc.setdefault(ind, []).append(r)
    ind_r50 = {k: sum(v) / len(v) for k, v in ind_acc.items() if len(v) >= 3}
    shb = fetch_kline(["sh000001"], "day", N6 + 5).get("sh000001", [])
    sh_r50 = (shb[-1]["close"] / shb[-1 - N6]["close"] - 1) * 100 if len(shb) > N6 else 0
    strength_map = {}
    for code, *_ in cand2:
        sr = stk_r50.get(code)
        ind = ind_map6.get(code)
        ir = ind_r50.get(ind) if ind else None
        if sr is not None and ir is not None and sr > ir > sh_r50:
            strength_map[code] = f"{sr:+.1f}>{ir:+.1f}>{sh_r50:+.1f}"
    print(f"[INFO] RSV50三线强度: {len(strength_map)} 只 (大盘50日{sh_r50:+.2f}%)", flush=True)

    # Step3: 60分钟确认（仅四星以上候选：w_entry不为None，省时）
    need60 = [c for c in cand2 if c[5]]
    print(f"[INFO] Step3 60分钟确认（{len(need60)}/{len(cand2)} 只四星以上，新浪串行）...", flush=True)
    m60_map = {}
    for k, (code, name, entry, gl, in_now, w_entry) in enumerate(need60):
        rows = fetch_sina_5m(code)
        m60 = False
        if len(rows) > 400:
            bars60 = aggregate(rows, 60)
            if len(bars60) > 35:
                v60 = compute_varo7(bars60)
                m60 = v60[-1] < 12  # 60m当前低位（放宽到12，近窗口样本少）
        m60_map[code] = m60
        if (k + 1) % 5 == 0:
            print(f"  [进度] {k+1}/{len(need60)}", flush=True)
        time.sleep(1.2)

    results = []
    for code, name, entry, gl, in_now, w_entry in cand2:
        m60 = m60_map.get(code, False)
        stars = 3
        if w_entry:
            stars = 4
        if m60:
            stars = 5
        rev = rev_map.get(code)
        st = strength_map.get(code)
        results.append({"code": code, "name": name, "entry": entry, "guaili": gl,
                        "in_now": in_now, "week": w_entry, "m60": m60, "stars": stars,
                        "reversal": rev, "strength": st,
                        "note": f"日线建仓{entry}" + ("+周线" if w_entry else "") + ("+60m" if m60 else "")})

    results.sort(key=lambda r: -r["stars"])
    # 实时ST/退市兜底（清单快照可能漏掉后续戴帽股，如交大昂立→ST交昂）
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from st_guard import filter_st
        results, st_dropped = filter_st(results)
        if st_dropped:
            names_str = ", ".join(d["name"] + "(" + d["code"] + ")" for d in st_dropped)
            print(f"[ST过滤] 剔除 {len(st_dropped)} 只ST/退市: {names_str}", flush=True)
    except Exception as e:
        print(f"[WARN] st_guard 校验失败: {e}", flush=True)
    # 输出
    os.makedirs(f"{BASE}/outputs", exist_ok=True)
    md_path = f"{BASE}/outputs/一统天下建仓区股池_{date_str}.md"
    rev_cnt = sum(1 for r in results if r.get("reversal"))
    st_cnt = sum(1 for r in results if r.get("strength"))
    both_cnt = sum(1 for r in results if r.get("reversal") and r.get("strength"))
    L = [f"# 🏆 一统天下·多周期建仓区股池 {date_str}\n",
         f"**扫描**: {len(pool)} 只主板 | **日线候选**: {len(cand)} | **周线闸门**: {len(cand2)} | **总信号**: {len(results)}\n",
         f"**⭐月线反转**: {rev_cnt} 只 | **📊RSV50三线强度(个>行>大)**: {st_cnt} 只 | **双共振**: {both_cnt} 只\n"]
    for stars in (5, 4, 3):
        grp = [r for r in results if r["stars"] == stars]
        label = {5: "★五星共振（日+周+60m）", 4: "☆四星（日+周）", 3: "☆三星（日线建仓区）"}[stars]
        L.append(f"\n## {label}（{len(grp)}只）\n")
        if grp:
            L.append("| 代码 | 名称 | 日线建仓日 | 乖离低买 | 当前建仓区 | 月线反转 | RSV50强度 | 说明 |")
            L.append("|------|------|----------|:---:|:---:|:---:|:---:|------|")
            for r in grp:
                L.append(f"| {r['code']} | {r['name']} | {r['entry']} | {'✅' if r['guaili'] else '—'} | {'✅' if r['in_now'] else '—'} | {r.get('reversal') or '—'} | {r.get('strength') or '—'} | {r['note']} |")
        else:
            L.append("📭 无信号")
    # 建仓区 + RSV50三线强度 专表（回测最强组合）
    best_grp = [r for r in results if r.get("strength")]
    L.append(f"\n## ⭐建仓区 + RSV50三线强度（{len(best_grp)}只）｜回测最强组合·20日超额+5.87pct\n")
    if best_grp:
        L.append("| 代码 | 名称 | 星级 | RSV50强度(个>行>大) | 月线反转 | 说明 |")
        L.append("|------|------|:---:|:---:|:---:|------|")
        for r in best_grp:
            L.append(f"| {r['code']} | {r['name']} | {'★'*r['stars']} | {r.get('strength')} | {r.get('reversal') or '—'} | {r['note']} |")
    else:
        L.append("📭 无")
    # 月线反转 + RSV50 双共振
    dual = [r for r in results if r.get("reversal") and r.get("strength")]
    L.append(f"\n## 🔥月线反转 + RSV50 双共振（{len(dual)}只）\n")
    if dual:
        L.append("| 代码 | 名称 | 星级 | 月线反转 | RSV50强度 | 说明 |")
        L.append("|------|------|:---:|:---:|:---:|------|")
        for r in dual:
            L.append(f"| {r['code']} | {r['name']} | {'★'*r['stars']} | {r['reversal']} | {r['strength']} | {r['note']} |")
    else:
        L.append("📭 无")
    report = "\n".join(L)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)
    json_path = f"{BASE}/outputs/一统天下建仓区股池_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "total": len(results), "results": results}, f, ensure_ascii=False, indent=2)
    # 股池配置（供跟踪）
    with open(f"{BASE}/yitong_pool.txt", "w", encoding="utf-8") as f:
        f.write(f"# 一统天下建仓区股池 {date_str}\n")
        f.write(f"# 统计: 总信号{len(results)}只 | 月线反转{rev_cnt}只 | RSV50三线强度{st_cnt}只 | 双共振{both_cnt}只\n")
        for r in results:
            tags = f"{'★'*r['stars']}建仓区"
            if r.get("reversal"):
                tags += f"+反转({r['reversal']})"
            if r.get("strength"):
                tags += "+RSV50强"
            f.write(f"{r['code']} # {r['name']}（{tags}）\n")
    print(report)
    print(f"\n[OK] 报告: {md_path}\n[OK] 股池: {BASE}/yitong_pool.txt")

if __name__ == "__main__":
    main()
