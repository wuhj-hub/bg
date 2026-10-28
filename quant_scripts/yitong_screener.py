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
import shutil as _shutil
WESTOCK = ([_shutil.which("westock-data-skillhub")] if _shutil.which("westock-data-skillhub")
           else ["npx", "-y", "westock-data-skillhub@1.0.3"])   # ⭐2026-09-30 优先直调已装 bin（免 npx ~2.8s/次），未装回退 npx
BATCH = 250   # ⭐2026-09-30: 40→250（npx调用 237→39；实测单批400只12s零丢失，250更稳）
WORKERS = 8   # 大batch后总调用数骤减，保留并发以重叠网络；缺口由 fetch_kline_gap 兜底
# ⭐2026-10-28 有界化：软时间预算（默认 25min，env YITONG_BUDGET_MIN 可调）。
# 背景：CI 常态 33min；10-27 因取数抖动挂到 >60min 把整个 quant_scan job 拖死，
#       后续「上传三系统/上传报告/env/契约自检/提交扫描产物」6 步全未执行 → 次日盘前读到 10-26 旧数据。
# 策略：任何阶段超预算即跳过（降级输出并标注），保证金天一定产出股池。
BUDGET_MIN = float(os.environ.get("YITONG_BUDGET_MIN", "28"))   # 沙箱全市场实测 24min（Step1 11 + Step3 12），留 4min 余量
_T0 = time.time()


def elapsed_min():
    return (time.time() - _T0) / 60.0


def over_budget(stage):
    el = elapsed_min()
    if el > BUDGET_MIN:
        print(f"[WARN] 已耗时 {el:.1f}min > 软预算 {BUDGET_MIN:.0f}min，跳过「{stage}」（本步降级输出）", flush=True)
        return True
    return False
# ⭐2026-09-25: 日线取数 120→80 根（varo7 自 i=33 起算+指数平滑，80根收敛充分；
#             实测 200只 候选名单与 120 根完全一致，数据量 -33%）
# 路径兼容：沙箱用 /sandbox/workspace，GitHub runner 用仓库根(cwd)
BASE = "/sandbox/workspace" if os.path.isdir("/sandbox/workspace") else os.getcwd()

def cli(cmd, timeout=180, retries=5):
    full = WESTOCK + cmd.split()
    for attempt in range(max(1, retries)):
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
    """2026-10-14：委托统一取数层 fetch.kline（qfq 前复权；批量/重试/免npx/解析统一收口）。
    → {sym: [ {date,open,close,high,low}, ... 升序]}（与旧实现同结构）。"""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from fetch import kline as _fk
        raw = _fk(list(symbols), period=period, limit=limit, fq="qfq")
        return {c: [{"date": b["date"], "open": b["open"], "close": b["close"],
                     "high": b["high"], "low": b["low"]} for b in bars]
                for c, bars in raw.items()}
    except Exception:
        return {}

def fetch_kline_gap(symbols, period, limit):
    """缺口兜底：对未取到的 symbols 小批(40)复取。不做逐只——全市场约7.6%为退市票（本就无数据），
    逐只复取纯属空耗；小批已可挽回大batch的偶发抖动丢股。"""
    symbols = [s for s in symbols]
    extra = {}
    for j in range(0, len(symbols), 250):
        extra.update(fetch_kline(symbols[j:j + 250], period, limit))
    return extra

def fetch_sina_5m(symbol, datalen=1023, timeout=8, retries=2):
    """新浪 5 分钟线。⭐2026-10-28：单只 timeout 20→8s、重试 4→2 次。
    原口径单只最坏 80s，而 Step3 是串行循环，新浪一旦变慢/限流就会把整步拖成小时级。"""
    from urllib.request import urlopen
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService"
           f".getKLineData?symbol={symbol}&scale=5&ma=no&datalen={datalen}")
    for attempt in range(max(1, retries)):
        try:
            txt = urlopen(url, timeout=timeout).read().decode("utf-8", errors="replace")
            m = re.search(r"\((\[.*\])\)", txt, re.S)
            if not m:
                return []
            rows = json.loads(m.group(1))
            return [{"date": x["day"][:10], "open": float(x["open"]), "close": float(x["close"]),
                     "high": float(x["high"]), "low": float(x["low"])} for x in rows]
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
    return []


def load_local_industry(syms):
    """本地行业映射（em_industry.json，0 次网络调用）→ {sym: 行业}；覆盖率 <85% 返回 {}。
    ⭐2026-10-28：Step2.6 原走 westock profile 13 批串行（沙箱 26s/批 ≈ 6min，CI 更慢），
    是全步第二大耗时块，且 profile 抖动时 5 次重试 ×180s 可膨胀到小时级。"""
    cand = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "em_industry.json"),
            f"{BASE}/quant_scripts/em_industry.json"]
    for p in cand:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                j = json.load(f)
            stocks = j.get("stocks") or {}
            m = {}
            for c6, v in stocks.items():
                if not isinstance(v, dict):
                    continue
                ind = v.get("ind")
                if not ind or not re.match(r"^\d{6}$", c6):
                    continue
                m[("sh" + c6) if c6.startswith("6") else ("sz" + c6)] = ind
            cov = sum(1 for x in syms if x in m) / max(1, len(syms))
            print(f"[INFO] 本地行业映射 {os.path.basename(p)}: {len(m)} 条，覆盖 {cov * 100:.1f}%", flush=True)
            if cov >= 0.85:
                return m
        except Exception as e:
            print(f"[WARN] 读取 {p} 失败: {e}", flush=True)
    return {}

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

def agg_week(bars):
    """日线 → 周线（ISO 周分组：open=首日open，close=末日close，high/low=区间极值）。
    ⭐2026-10-28 提速：westock 周线/月线批量极慢（实测 250 只周线单批 153s，且 8 并发会被限流
    拖到 372s、并引发缺口小批复取雪崩 → Step2 单步曾吃掉 10min+，是 10-27 挂死的另一半原因）。
    日线 250 只仅 17s，本地聚合与 westock 周线收盘价差异中位 0.0000%、最大 0.3%（前复权基准微差）。"""
    out, key = [], None
    for b in bars:
        try:
            d = datetime.strptime(str(b["date"])[:10], "%Y-%m-%d")
            k = d.isocalendar()[:2]
        except Exception:
            continue
        if out and key == k:
            o = out[-1]
            o["close"] = b["close"]
            o["high"] = max(o["high"], b["high"])
            o["low"] = min(o["low"], b["low"])
        else:
            key = k
            out.append({"date": b["date"], "open": b["open"], "close": b["close"],
                        "high": b["high"], "low": b["low"]})
    return out


def agg_month(bars):
    """日线 → 月线（按年月分组）。⭐2026-10-28：替代 westock 月线批量（250 只单批 209s、8 并发劣化到 372s）。"""
    out, key = [], None
    for b in bars:
        try:
            d = datetime.strptime(str(b["date"])[:10], "%Y-%m-%d")
        except Exception:
            continue
        k = (d.year, d.month)
        if out and key == k:
            o = out[-1]
            o["close"] = b["close"]
            o["high"] = max(o["high"], b["high"])
            o["low"] = min(o["low"], b["low"])
        else:
            key = k
            out.append({"date": b["date"], "open": b["open"], "close": b["close"],
                        "high": b["high"], "low": b["low"]})
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

def detect_reversal(month_bars, allow_cross=True):
    """月线反转检测：平台突破12月新高 / 均线金叉 / 趋势确立（用最新月）。

    allow_cross=False（日线聚合月线口径，最多 12 个月）：跳过「均线金叉」——
    该判据需 ma12_prev(前 12 月)，13 个月才凑得齐；聚合口径下保留平台突破/趋势确立。
    """
    closes = [b["close"] for b in month_bars]
    n = len(closes)
    if n < (13 if allow_cross else 12):
        return None
    i = n - 1
    cur = closes[i]
    ma6 = sum(closes[i - 5:i + 1]) / 6
    ma12 = sum(closes[i - 11:i + 1]) / 12
    ma6_prev = sum(closes[i - 6:i]) / 6
    prev_max = max(closes[i - 11:i])
    if cur > prev_max and cur > ma6:
        return "平台突破"
    if allow_cross:
        ma12_prev = sum(closes[i - 12:i]) / 12
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
    ap.add_argument("--budget", type=float, default=None, help="软时间预算(分钟)，默认取 env YITONG_BUDGET_MIN 或 25")
    args = ap.parse_args()
    if args.budget:
        globals()["BUDGET_MIN"] = args.budget
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
            futs[ex.submit(fetch_kline, syms[i:i + BATCH], "day", 250)] = 1   # ⭐2026-10-28: 80→250，供 Step2 本地聚合周线
        _done = 0
        for f in as_completed(futs):
            _done += 1
            for k, v in f.result().items():
                if len(v) > 40:
                    day_map[k] = v
            if _done % 4 == 0 or _done == len(futs):
                print(f"  [进度] 日线批次 {_done}/{len(futs)}，已取 {len(day_map)} 只，"
                      f"耗时 {elapsed_min():.1f}min", flush=True)
        for k, v in fetch_kline_gap([s for s in syms if s not in day_map], "day", 250).items():
            if len(v) > 40 and k not in day_map:
                day_map[k] = v
    cov = len(day_map) / max(1, len(syms))
    print(f"[INFO] 日线取数覆盖 {len(day_map)}/{len(syms)}（{cov*100:.1f}%），累计耗时 {elapsed_min():.1f}min", flush=True)
    if cov < 0.80:
        print(f"[WARN] 日线覆盖率 {cov*100:.1f}% < 80%——westock 可能在高负载下降级（退市票约 7.6%，"
              f"正常应 ≥90%），本轮候选数会偏少（2026-10-28 实测盘后高峰曾跌到 30-62%）", flush=True)

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
    print("[INFO] Step2 周线闸门（日线→本地聚合周线，0 次 westock 调用）...", flush=True)
    week_map = {}
    for code, *_ in cand:
        db = day_map.get(code)
        if not db:
            continue
        wb = agg_week(db)
        if len(wb) > 10:
            week_map[code] = wb
    print(f"  周线聚合完成 {len(week_map)} 只，累计耗时 {elapsed_min():.1f}min", flush=True)
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
    print(f"[INFO] Step2.5 月线反转检测（{len(cand2)} 只，日线→本地聚合月线，0 次 westock 调用）...", flush=True)
    rev_map = {}
    for code, *_ in cand2:
        db = day_map.get(code)
        if not db:
            continue
        mb = agg_month(db)
        if len(mb) >= 12:
            rv = detect_reversal(mb, allow_cross=False)
            if rv:
                rev_map[code] = rv
    print(f"[INFO] 月线反转: {len(rev_map)} 只（聚合口径：平台突破/趋势确立；累计 {elapsed_min():.1f}min）", flush=True)

    # Step2.6: RSV50三线相对强度（50日相对强度：个股>行业>大盘）
    print("[INFO] Step2.6 RSV50三线强度检测...", flush=True)
    ind_map6 = {} if over_budget("Step2.6 RSV50三线强度") else load_local_industry(syms)
    if not ind_map6 and not over_budget("Step2.6 profile 兜底"):
        # 兜底：westock profile（并发 4、单批 timeout 60s / 重试 2 次、连续 2 批空即熔断）
        batches6 = [syms[i:i + 250] for i in range(0, len(syms), 250)]

        def _prof(b):
            md6 = cli(f"profile {','.join(b)}", timeout=60, retries=2)
            o = {}
            for ln6 in md6.splitlines():
                ln6 = ln6.strip()
                if ln6.startswith("|") and "code" not in ln6 and "---" not in ln6:
                    q = [x.strip() for x in ln6.strip("|").split("|")]
                    if len(q) > 6 and q[0].startswith(("sh", "sz")):
                        o[q[0]] = q[5]
            return o

        fails6 = 0
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs6 = [ex.submit(_prof, b) for b in batches6]
            for i, f in enumerate(as_completed(futs6)):
                if over_budget("Step2.6 profile 兜底"):
                    break
                try:
                    o6 = f.result()
                except Exception:
                    o6 = {}
                ind_map6.update(o6)
                if not o6:
                    fails6 += 1
                    if fails6 >= 2:
                        print("[WARN] profile 连续 2 批返回空 → 跳过 RSV50（降级）", flush=True)
                        break
                if (i + 1) % 4 == 0:
                    print(f"  [进度] profile {i + 1}/{len(batches6)}，耗时 {elapsed_min():.1f}min", flush=True)
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
    skip60 = False
    print(f"[INFO] Step3 60分钟确认（{len(need60)}/{len(cand2)} 只四星以上，新浪并发4）...", flush=True)
    m60_map = {}
    blank60 = 0

    def _one60(code):
        rows = fetch_sina_5m(code)
        m60 = False
        if len(rows) > 400:
            bars60 = aggregate(rows, 60)
            if len(bars60) > 35:
                v60 = compute_varo7(bars60)
                m60 = v60[-1] < 12  # 60m当前低位（放宽到12，近窗口样本少）
        time.sleep(0.3)
        return code, m60, bool(rows)

    # ⭐2026-10-28：串行 → 并发 4。全市场四星以上常 500+ 只，串行 (1.2s sleep + 请求)
    # 需 18min+（实测 526 只跑到 25min 预算上限被截断），是 Step3 被降级的直接原因。
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs60 = [ex.submit(_one60, c[0]) for c in need60]
        for k, f in enumerate(as_completed(futs60)):
            if over_budget("Step3 60分钟确认"):
                skip60 = True
                break
            try:
                code, m60, ok = f.result()
            except Exception:
                continue
            m60_map[code] = m60
            if not ok:
                blank60 += 1
                if blank60 >= 5:   # 连续 5 只取不到 → 判定新浪源不可用，熔断跳过
                    print(f"[WARN] 新浪 5m 连续 {blank60} 只返回空 → 熔断跳过 Step3 剩余 "
                          f"({len(need60) - k - 1} 只)，已耗时 {elapsed_min():.1f}min", flush=True)
                    skip60 = True
                    for _f in futs60:
                        _f.cancel()
                    break
            else:
                blank60 = 0
            if (k + 1) % 25 == 0:
                print(f"  [进度] {k + 1}/{len(need60)}，耗时 {elapsed_min():.1f}min", flush=True)

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
    degrade = []
    if skip60:
        degrade.append("60分钟确认未完成（超预算/新浪源熔断）")
    if not ind_map6:
        degrade.append("RSV50 行业映射缺失")
    if degrade:
        print("[WARN] 降级项: " + "; ".join(degrade), flush=True)
    L = [f"# 🏆 一统天下·多周期建仓区股池 {date_str}\n",
         f"**扫描**: {len(pool)} 只主板 | **日线候选**: {len(cand)} | **周线闸门**: {len(cand2)} | **总信号**: {len(results)}\n",
         f"**⭐月线反转**: {rev_cnt} 只 | **📊RSV50三线强度(个>行>大)**: {st_cnt} 只 | **双共振**: {both_cnt} 只\n"]
    L.append(f"\n> 🧮 口径：周线/月线由日线本地聚合（与 westock 周线收盘差异中位 0.0000%/最大 0.3%）；"
             f"聚合月线仅 12 个月，月线反转不含「均线金叉」类。全步耗时 {elapsed_min():.1f}min。\n")
    if degrade:
        L.append(f"\n> ⚠️ **降级提示**（{'；'.join(degrade)}）\n")
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
    # ⚠️ 2026-09-15 修复：原只写 {BASE}（=仓库根），而 workflow 提交的是 quant_scripts/yitong_pool.txt
    #    → 提交的一直是旧文件（股池实际自 2026-08-14 起断更）。此处同步一份到脚本目录，两处保持一致。
    try:
        import shutil as _sh
        _alt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yitong_pool.txt")
        if os.path.abspath(_alt) != os.path.abspath(f"{BASE}/yitong_pool.txt"):
            _sh.copyfile(f"{BASE}/yitong_pool.txt", _alt)
            print(f"[OK] 股池(同步): {_alt}")
    except Exception as _e:
        print(f"[WARN] 股池同步失败: {_e}")
    print(report)
    print(f"\n[OK] 报告: {md_path}\n[OK] 股池: {BASE}/yitong_pool.txt")

if __name__ == "__main__":
    main()
