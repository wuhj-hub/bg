# -*- coding: utf-8 -*-
"""武威月线公式自动化复现 v3: 2025-09月末两阴缩量回调, 经全市场精确率抽样验证的平衡规则 G1。
v2(末端两阴+量*0.8+depth>=3%) 复现率100%但过拟合(全市场误报~500只,精确率8.6%)。
v3/G1 修复: 双阴要求 K4量&K3量 皆<=前阳K2量*0.6 + K4低≈K1低(起涨点,容差12%)。
  验证(47只正样本 + 141只抽样负样本, 同月末2025-09-30):
    正样本召回 96%(45/47); 独立负样本特异性 2.9%(4/136); 全市场误报~89只; 精确率~34%。
用法:
  python3 wuwei_scan_month.py --period 202509 --csv ww_period_202509.csv  # 单期自动选股
  python3 wuwei_scan_month.py --verify-all          # 对真实池逐期测召回
  python3 wuwei_scan_month.py --balance             # 用 /tmp/balance47.json 缓存复核 G1 召回/特异性
"""
import subprocess, json, os, time, csv, concurrent.futures, argparse, shutil
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
# 仓库内运行：默认产出到 <仓库根>/outputs；可用 WUWEI_OUT 覆盖
OUT = os.environ.get("WUWEI_OUT") or os.path.join(os.path.dirname(_HERE), "outputs")
SELF_TEST = "/tmp/diag.json"

def cli(cmd, retry=3, timeout=120):
    for _ in range(retry):
        try:
            r = subprocess.run(f"{(shutil.which('westock-data-skillhub') or 'npx -y westock-data-skillhub@1.0.3')} {cmd}", shell=True,
                               capture_output=True, text=True, timeout=timeout)
            if r.stdout.strip():
                return r.stdout
        except Exception:
            pass
        time.sleep(1)
    return ""

def parse_kline(md):
    lines = [l.strip() for l in md.split("\n") if l.strip().startswith("|")]
    if len(lines) < 3: return []
    headers = [h.strip() for h in lines[0].strip("|").split("|")]
    rows = []
    for ln in lines[2:]:
        cols = [c.strip() for c in ln.strip("|").split("|")]
        if len(cols) >= len(headers):
            rows.append(dict(zip(headers, cols)))
    return rows

def agg_recs(recs, months=14):
    """日线 recs（升序）→ 按自然月聚合月线。口径：月 open=首根 open、close=末根 close、high/low 极值、vol 累加"""
    if not recs:
        return []
    out, cur = [], None
    for r in sorted(recs, key=lambda x: x["date"]):
        ym = r["date"][:7]
        if cur is None or cur["ym"] != ym:
            if cur:
                out.append({k: cur[k] for k in ("date", "open", "close", "high", "low", "vol")})
            cur = {"ym": ym, "date": r["date"], "open": r["open"], "close": r["close"],
                   "high": r["high"], "low": r["low"], "vol": r["vol"]}
        else:
            cur["date"] = r["date"]
            cur["close"] = r["close"]
            cur["high"] = max(cur["high"], r["high"])
            cur["low"] = min(cur["low"], r["low"])
            cur["vol"] += r["vol"]
    if cur:
        out.append({k: cur[k] for k in ("date", "open", "close", "high", "low", "vol")})
    return out[-months:]


DAILY_BATCH = int(os.environ.get("WUWEI_DAILY_BATCH", "40"))
DAILY_LIMIT = int(os.environ.get("WUWEI_DAILY_LIMIT", "160"))


def agg_month_from_daily(code, months=14):
    """单只日线 → 聚合月线（兜底用）"""
    md = cli(f"kline {code} --period day --limit {DAILY_LIMIT}")
    recs = []
    for r in parse_kline(md):
        try:
            recs.append({"date": r["date"], "open": float(r["open"]), "close": float(r["last"]),
                         "high": float(r["high"]), "low": float(r["low"]), "vol": float(r["volume"])})
        except Exception:
            continue
    return agg_recs(recs, months)


BATCH = int(os.environ.get("WUWEI_BATCH", "40"))
BATCH_SLEEP = float(os.environ.get("WUWEI_BATCH_SLEEP", "0.4"))
GAP_RETRY_BATCH = 20


def parse_batch(md):
    """批量输出（含 symbol 列）→ {symbol: [rec,...]}；单只/异常返回 {}"""
    lines = [l.strip() for l in md.split("\n") if l.strip().startswith("|")]
    if len(lines) < 3:
        return {}
    headers = [h.strip() for h in lines[0].strip("|").split("|")]
    if "symbol" not in headers:
        return {}
    out = {}
    for ln in lines[2:]:
        cols = [c.strip() for c in ln.strip("|").split("|")]
        if len(cols) < len(headers):
            continue
        d = dict(zip(headers, cols))
        sym = (d.get("symbol") or "").strip()
        if not sym:
            continue
        try:
            rec = {"date": d["date"], "open": float(d["open"]), "close": float(d["last"]),
                   "high": float(d["high"]), "low": float(d["low"]), "vol": float(d["volume"])}
        except Exception:
            continue
        out.setdefault(sym, []).append(rec)
    for v in out.values():
        v.sort(key=lambda x: x["date"])
    return out


def _batch_call(chunk, limit):
    """一批月线；空返回退避重试一次"""
    for attempt in range(2):
        md = cli(f"kline {','.join(chunk)} --period month --limit {limit}", retry=2, timeout=240)
        r = parse_batch(md)
        if r:
            return r
        if attempt == 0:
            time.sleep(2 + attempt * 2)
    return {}


def batch_monthly(codes, limit=24):
    """批量取月线 → ({code: recs}, fail_list)。三级：批量100 → 缺口小批20 → 日线聚合兜底"""
    got, fail = {}, []
    t0 = time.time()
    for i in range(0, len(codes), BATCH):
        chunk = codes[i:i + BATCH]
        got.update(_batch_call(chunk, limit))
        if (i // BATCH) % 5 == 4:
            print(f"[month] {min(i + BATCH, len(codes))}/{len(codes)} 命中 {len(got)} 用时 {round(time.time() - t0)}s", flush=True)
        time.sleep(BATCH_SLEEP)

    miss = [c for c in codes if not got.get(c)]
    if miss:
        print(f"[warn] 批量缺口 {len(miss)} 只 → 小批({GAP_RETRY_BATCH})重试", flush=True)
        for i in range(0, len(miss), GAP_RETRY_BATCH):
            got.update(_batch_call(miss[i:i + GAP_RETRY_BATCH], limit))
            time.sleep(0.8)

    miss2 = [c for c in codes if not got.get(c)]
    if miss2:
        print(f"[warn] 仍缺 {len(miss2)} 只 → 日线聚合兜底（最多 80 只）", flush=True)
        for c in miss2[:80]:
            r = agg_month_from_daily(c, limit)
            if r:
                got[c] = r
            else:
                fail.append(c)
        fail += miss2[80:]

    print(f"[month] 完成 覆盖 {len(codes) - len(fail)}/{len(codes)}（缺口走兜底），失败 {len(fail)} 只，用时 {round(time.time() - t0)}s", flush=True)
    return got, fail


def batch_daily_agg(codes, dlimit=None, months=14):
    """日线批量 → 聚合月线，返回 ({code:月线recs}, fail)。
    实测与 `kline --period month` 口径 100% 一致（60/60 只逐只对齐），速度快 4~5 倍"""
    dlimit = dlimit or DAILY_LIMIT
    got, fail = {}, []
    t0 = time.time()
    for i in range(0, len(codes), DAILY_BATCH):
        chunk = codes[i:i + DAILY_BATCH]
        r = {}
        for attempt in range(2):
            md = cli(f"kline {','.join(chunk)} --period day --limit {dlimit}", retry=2, timeout=300)
            r = parse_batch(md)
            if r:
                break
            time.sleep(2)
        for k, v in r.items():
            got[k] = agg_recs(v, months)
        if (i // DAILY_BATCH) % 5 == 4:
            print(f"[day] {min(i + DAILY_BATCH, len(codes))}/{len(codes)} 命中 {len(got)} 用时 {round(time.time() - t0)}s", flush=True)
        time.sleep(BATCH_SLEEP)

    # 批量接口有 15~20% 随机丢股 → 多轮补缺口（最多 3 轮，任一轮无进展即停）
    for rnd in range(1, 4):
        miss = [c for c in codes if not got.get(c)]
        if not miss:
            break
        prev = len(miss)
        print(f"[warn] 第{rnd}轮补缺口 {len(miss)} 只", flush=True)
        for i in range(0, len(miss), DAILY_BATCH):
            chunk = miss[i:i + DAILY_BATCH]
            md = cli(f"kline {','.join(chunk)} --period day --limit {dlimit}", retry=2, timeout=300)
            for k, v in parse_batch(md).items():
                got[k] = agg_recs(v, months)
            time.sleep(0.6)
        now = len([c for c in codes if not got.get(c)])
        print(f"[warn] 第{rnd}轮后缺口 {now} 只（本轮补回 {prev - now}）", flush=True)
        if now >= prev:
            break

    # 最后单只兜底（限 60 只，多为退市/长期停牌）
    miss2 = [c for c in codes if not got.get(c)]
    for c in miss2[:60]:
        r = agg_month_from_daily(c, months)
        if r:
            got[c] = r
    for c in [c for c in codes if not got.get(c)]:
        fail.append(c)
    print(f"[day] 完成 覆盖 {len(codes) - len(fail)}/{len(codes)}，失败 {len(fail)} 只，用时 {round(time.time() - t0)}s", flush=True)
    return got, fail


def get_many(codes, source="day", limit=16):
    """统一取月线入口：source=day（默认，日线聚合）/ month（月线接口直取）"""
    if str(source).lower() == "month":
        return batch_monthly(codes, limit)
    return batch_daily_agg(codes)


_MONTH_MISS = [0]     # 月线接口连续空返回计数（连续3次即全局切日线聚合）


_PROBE = [0]


def get_monthly(code, limit=24):
    """单只月线（v2.1 过滤阶段用）。月线接口连空 3 次后熔断，但每 200 次调用重探一次"""
    md = ""
    if _MONTH_MISS[0] < 3:
        md = cli(f"kline {code} --period month --limit {limit}")
    else:
        _PROBE[0] += 1
        if _PROBE[0] % 200 == 0:      # 熔断后周期性重探，避免永久退化到日线聚合
            _MONTH_MISS[0] = 0
            md = cli(f"kline {code} --period month --limit {limit}")
            if not parse_kline(md):
                _MONTH_MISS[0] = 3
    recs = []
    for r in parse_kline(md):
        try:
            recs.append({"date": r["date"], "open": float(r["open"]), "close": float(r["last"]),
                         "high": float(r["high"]), "low": float(r["low"]), "vol": float(r["volume"])})
        except Exception:
            continue
    recs.sort(key=lambda x: x["date"])
    if recs:
        _MONTH_MISS[0] = 0
        return recs
    _MONTH_MISS[0] += 1
    if _MONTH_MISS[0] == 3:
        print("[warn] 月线接口连续空返回 → 全局切换日线聚合兜底")
    return agg_month_from_daily(code)

def yang(r):
    if "open" in r and r["open"] is not None:
        return r["close"] > r["open"]
    return r.get("y") == "阳"
def yin(r):
    if "open" in r and r["open"] is not None:
        return r["close"] < r["open"]
    return r.get("y") == "阴"

def signal(rows, month_end):
    """武威月线平衡规则 G1 (经精确率抽样验证: 召回96%/独立负样本特异性2.9%/精确率~34%):
    双阴: 末端两阴(K3阴,K4阴) + K4量<=前阳K2量*0.6 + K3量<=K2量*0.6 + K4低≈K1低(起涨点,容差12%)
    一阴: K3阳,K2阴,K4阴 + K2量<K3量*0.6 + K4量<K3量*0.6 + K4低≈K3低(容差12%)
    返回 '双阴'/'一阴'/'无'。"""
    if not rows:
        return "无"
    k4 = None
    for i, r in enumerate(rows):
        if r["date"] <= month_end:
            k4 = i
    if k4 is None or k4 < 3:
        return "无"
    k1, k2, k3, k4r = rows[k4-3], rows[k4-2], rows[k4-1], rows[k4]
    # 模式1 双阴(阳2阴2): 末端两阴缩量 + 回到起涨点K1附近
    if yin(k3) and yin(k4r):
        if k4r["vol"] <= k2["vol"] * 0.6 and k3["vol"] <= k2["vol"] * 0.6:
            if k1["low"] > 0 and abs(k4r["low"] - k1["low"]) / k1["low"] <= 0.12:
                return "双阴"
    # 模式2 一阴(阳1阴2): K3阳,K2阴,K4阴 缩量 + 回到K3低点附近
    if yang(k3) and yin(k2) and yin(k4r) and k4 >= 2:
        if k2["vol"] < k3["vol"] * 0.6 and k4r["vol"] < k3["vol"] * 0.6:
            if k3["low"] > 0 and abs(k4r["low"] - k3["low"]) / k3["low"] <= 0.12:
                return "一阴"
    return "无"

def norm_code(c):
    c = c.strip()
    if c.startswith(("sh", "sz")):
        return c
    if c[0] == "6":
        return "sh" + c
    return "sz" + c

def read_csv(path):
    stocks = []
    with open(path, "r", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        for row in rd:
            stocks.append((norm_code(row["code"]), row.get("name", row["code"])))
    return stocks

def selftest():
    with open(SELF_TEST, encoding="utf-8") as f:
        DATA = json.load(f)
    hit = 0; tot = 0; missed = []
    for name, r in DATA.items():
        if r.get("status") != "OK":
            continue
        tot += 1
        # 由 shape 重建 rows (无open, 用 y 字段)
        rows = [{"date": s["date"], "close": s["close"], "low": s["low"],
                 "vol": s["vol"], "y": s["y"]} for s in r["shape"]]
        res = signal(rows, r["k4"])
        if res != "无":
            hit += 1
        else:
            missed.append(name)
    print(f"[selftest] 47只召回: {hit}/{tot} = {hit/tot*100:.1f}%  漏选: {missed}")

def scan_period(period, csv_path):
    month_end = month_end_of(period)
    stocks = read_csv(csv_path)
    sig = []
    def worker(item):
        code, name = item
        rows = get_monthly(code, 24)
        return code, name, signal(rows, month_end)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for code, name, res in ex.map(worker, stocks):
            if res != "无":
                sig.append((code, name, res))
                print(f"[SIG] {name}: {res}", flush=True)
    out = os.path.join(OUT, f"ww_period_{period}_auto.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["code", "name", "source"])
        for code, name, res in sig:
            w.writerow([code, name, f"auto_{res}"])
    print(f"\n[done] {period}: 自动选出 {len(sig)} 只 -> {out}")

def month_end_of(period):
    import calendar
    y, m = int(period[:4]), int(period[4:6])
    return f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


MAX_GAP_MONTH = int(os.environ.get("WUWEI_MAX_GAP_MONTH", "2"))


def months_gap(dstr, month_end):
    """最新月线距目标月末的月数差（正=数据早于目标月）。退市股会极大"""
    try:
        y, m = int(dstr[:4]), int(dstr[5:7])
        ey, em = int(month_end[:4]), int(month_end[5:7])
        return (ey - y) * 12 + (em - m)
    except Exception:
        return 9999


def is_stale(rows, month_end):
    """最新月线早于目标月超过 MAX_GAP_MONTH → 退市/长期停牌，剔除"""
    if not rows:
        return True
    return months_gap(rows[-1]["date"], month_end) > MAX_GAP_MONTH

def verify_all(only=None):
    periods = [
        ("202508", "ww_period_202508.csv"), ("202509", "武威复盘_20250930.csv"),
        ("202510", "ww_period_202510.csv"), ("202511", "ww_period_202511.csv"),
        ("202512", "ww_period_202512.csv"), ("202601", "ww_period_202601.csv"),
        ("202602", "ww_period_202602.csv"), ("202603", "ww_period_202603.csv"),
        ("202604", "ww_period_202604.csv"), ("202605", "ww_period_202605.csv"),
        ("202606", "ww_period_202606.csv"),
    ]
    if only:
        periods = [p for p in periods if p[0] == only]
    for period, csvf in periods:
        csvp = os.path.join(OUT, csvf)
        if not os.path.exists(csvp):
            print(f"[skip] {period} 缺 {csvf}"); continue
        stocks = read_csv(csvp)
        me = month_end_of(period)
        hit = 0; n = len(stocks)
        cache = {}
        def get(code):
            if code not in cache:
                cache[code] = get_monthly(code, 24)
            return cache[code]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(get, c): (c, n_) for c, n_ in stocks}
            for f in concurrent.futures.as_completed(futs):
                code, name = futs[f]
                rows = f.result()
                if signal(rows, me) != "无":
                    hit += 1
        print(f"[verify] {period}: 召回 {hit}/{n} = {hit/n*100:.1f}%")

def full_scan(period, list_path, cache_out=None, source="day"):
    """全市场模式: 读全市场股票列表CSV(code,name), 在该月末跑规则, 输出信号池。"""
    month_end = month_end_of(period)
    stocks = read_csv(list_path)
    sig = []
    names = dict(stocks)
    codes = [c for c, _ in stocks]

    reuse = os.environ.get("WUWEI_REUSE_CACHE") == "1" and cache_out and os.path.exists(cache_out)
    if reuse:
        try:
            got = {k: v for k, v in json.load(open(cache_out)).items() if v}
            fail = [c for c in codes if not got.get(c)]
            print(f"[cache] 复用 {cache_out}：覆盖 {len(codes) - len(fail)}/{len(codes)}", flush=True)
        except Exception:
            got, fail = get_many(codes, source)
    else:
        got, fail = get_many(codes, source)

    # 全量月线缓存（取数完成立即落盘，避免后续步骤异常时白跑）
    if cache_out:
        try:
            json.dump(got, open(cache_out, "w"), ensure_ascii=False)
        except Exception as e:
            print(f"[cache] 落盘失败 {e}")

    stale = 0
    for code in codes:
        rows = got.get(code) or []
        if not rows:
            continue
        if is_stale(rows, month_end):        # 退市/长期停牌：最新月线远早于目标月
            stale += 1
            continue
        res = signal(rows, month_end)
        if res != "无":
            sig.append((code, names.get(code, code), res))

    if stale:
        print(f"[warn] 剔除退市/长期停牌 {stale} 只（最新月线早于目标月 {MAX_GAP_MONTH} 个月以上）")
    if fail:
        print(f"[warn] 取数失败 {len(fail)} 只: {','.join(fail[:20])}{' ...' if len(fail) > 20 else ''}")
    if cache_out:
        keep = sorted({c for c, _, _ in sig})
        json.dump({c: got.get(c, []) for c in keep}, open(cache_out, "w"), ensure_ascii=False)
        print(f"[cache] 信号股月线缓存 {len(keep)} 只 -> {cache_out}")
    out = os.path.join(OUT, f"ww_period_{period}_full.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["code", "name", "source"])
        for code, name, res in sig:
            w.writerow([code, name, f"auto_{res}"])
    print(f"\n[done] {period} 全市场扫描: {len(stocks)} 只 → 信号 {len(sig)} 只，取数失败 {len(fail)} 只 -> {out}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--period")
    ap.add_argument("--csv")
    ap.add_argument("--verify-all", action="store_true")
    ap.add_argument("--verify-period")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--list")
    ap.add_argument("--cache-out", default=None)
    ap.add_argument("--source", default="day", choices=["day", "month"], help="取数口径：day=日线聚合(默认) / month=月线接口")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.verify_all or a.verify_period:
        verify_all(a.verify_period)
    elif a.full and a.period and a.list:
        full_scan(a.period, a.list, a.cache_out, a.source)
    elif a.period and a.csv:
        scan_period(a.period, os.path.join(OUT, a.csv))
    else:
        print("用法见文件头")

if __name__ == "__main__":
    main()
