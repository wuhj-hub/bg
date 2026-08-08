#!/usr/bin/env python3
"""分时强度分析（黑石minuteMacd启发）——信号股日内分时MACD+封板强度+尾盘方向
用法:
  python3 minute_strength.py                    # 默认: panhou_lianghua.csv TOP信号股
  python3 minute_strength.py --codes 601700,000009  # 指定代码
  python3 minute_strength.py --limit 15         # 只分析前N只
输出: outputs/minute_strength_{date}.md
"""
import csv, os, re, subprocess, sys, time
from datetime import datetime


def run(args, timeout=90):
    for i in range(3):
        try:
            r = subprocess.run(["npx", "-y", "westock-data-skillhub@1.0.3"] + args,
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""


def fetch_minute(wcode):
    """拉取分时数据 → [(time_int, price), ...] 升序"""
    txt = run(["minute", wcode, "--days", "1"])
    rows = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 3 and parts[0] == wcode and parts[1].isdigit():
            rows.append((int(parts[1]), float(parts[2])))
    return rows


def ema(vals, n):
    """EMA序列"""
    k = 2 / (n + 1)
    out = []
    e = None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def calc_macd(prices):
    """分时MACD(12/26/9) → (dif, dea, hist)"""
    e12 = ema(prices, 12)
    e26 = ema(prices, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    hist = [(d - e) * 2 for d, e in zip(dif, dea)]
    return dif, dea, hist


def cross_count(dif, dea):
    """金叉死叉次数"""
    gc = dc = 0
    for i in range(1, len(dif)):
        if dif[i - 1] <= dea[i - 1] and dif[i] > dea[i]:
            gc += 1
        if dif[i - 1] >= dea[i - 1] and dif[i] < dea[i]:
            dc += 1
    return gc, dc


def fetch_preclose(wcode):
    """拉前一日收盘价（涨停检测用）"""
    txt = run(["kline", wcode, "--period", "day", "--limit", "2"])
    closes = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 4 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
            closes.append(float(parts[2]))
    # kline输出降序：closes[0]=最新, closes[1]=前收
    return closes[1] if len(closes) >= 2 else (closes[0] if closes else 0)


def analyze(wcode, name, pre_close):
    """返回分时强度字典"""
    rows = fetch_minute(wcode)
    if len(rows) < 60:
        return None
    times = [r[0] for r in rows]
    prices = [r[1] for r in rows]
    open_p, high_p, low_p, close_p = prices[0], max(prices), min(prices), prices[-1]

    # 分时MACD
    dif, dea, hist = calc_macd(prices)
    gc, dc = cross_count(dif, dea)
    last_dif, last_dea = dif[-1], dea[-1]
    macd_bull = last_dif > last_dea
    hist_pos_ratio = sum(1 for h in hist if h > 0) / len(hist) if hist else 0

    # 收盘位置（日内高低点）
    rng = high_p - low_p
    close_pos = (close_p - low_p) / rng * 100 if rng else 50

    # 尾盘30分钟（14:30后）
    tail = [(t, p) for t, p in rows if t >= 1430]
    tail_dir = 0
    if len(tail) >= 2:
        tail_dir = (tail[-1][1] - tail[0][1]) / tail[0][1] * 100 if tail[0][1] else 0

    # 涨停检测（主板10%）
    limit_p = round(pre_close * 1.1, 2)
    is_limitup = close_p >= limit_p * 0.998
    seal_time = None
    if is_limitup:
        for t, p in rows:
            if p >= limit_p * 0.998:
                seal_time = t
                break

    # 分时强度评分（0-100）——黑石分时MACD启发
    score = 50
    # 1. MACD方向：零轴上多头最强，零轴下多头次之，空头弱
    if macd_bull and last_dif > 0:
        score += 15
    elif macd_bull:
        score += 8
    else:
        score -= 15
    # 2. 收盘位置（最重要）：收在日内高位=强，收在低位=弱（尾盘杀跌）
    if close_pos >= 90:
        score += 15
    elif close_pos >= 70:
        score += 8
    elif close_pos <= 10:
        score -= 20
    elif close_pos <= 30:
        score -= 8
    # 3. 尾盘30分钟方向
    if tail_dir > 0.5:
        score += 8
    elif tail_dir < -0.5:
        score -= 8
    # 4. 红柱占比仅作辅助（下跌趋势中红柱占比高是滞后假象，不加重）
    if hist_pos_ratio >= 0.7 and macd_bull and last_dif > 0:
        score += 5
    elif hist_pos_ratio <= 0.3 and not macd_bull:
        score -= 5
    # 5. 涨停封板（封板越早越强）
    if is_limitup and seal_time is not None:
        score = min(100, score + 25 - (seal_time - 930) / 60 * 3)

    return {
        "code": wcode, "name": name,
        "open": open_p, "high": high_p, "low": low_p, "close": close_p,
        "macd_bull": macd_bull, "gc": gc, "dc": dc,
        "hist_pos": round(hist_pos_ratio * 100), "close_pos": round(close_pos),
        "tail_dir": round(tail_dir, 2), "score": max(0, min(100, round(score))),
        "limitup": is_limitup, "seal_time": seal_time,
    }


def to_wcode(code):
    code = str(code).lower().strip()
    if code.startswith(("sh", "sz")):
        return code
    if code.startswith("60"):
        return "sh" + code
    if code.startswith(("000", "001", "002", "003")):
        return "sz" + code
    return code


def main():
    argv = sys.argv[1:]
    codes_arg, limit = None, 15
    for i, a in enumerate(argv):
        if a == "--codes" and i + 1 < len(argv):
            codes_arg = argv[i + 1].split(",")
        if a == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])

    targets = []
    if codes_arg:
        for c in codes_arg:
            targets.append((to_wcode(c), c))
    else:
        # 默认: panhou_lianghua.csv 信号强度TOP + 双击候选
        csvp = None
        for p in ("panhou_lianghua.csv", "outputs/panhou_lianghua.csv"):
            if os.path.exists(p):
                csvp = p
                break
        if not csvp:
            print("未找到 panhou_lianghua.csv")
            return
        rows = list(csv.DictReader(open(csvp, encoding="utf-8-sig")))
        ordered = sorted(rows, key=lambda r: (0 if r.get("sig", "") == "主力主导放量🔥(最强)" else 1, -float(r.get("score", 0) or 0)))
        dbl = [r for r in rows if r.get("matching") == "资金+业绩共振(双击候选)"]
        seen = set()
        for r in ordered + dbl:
            c = to_wcode(r["code"])
            if c in seen:
                continue
            seen.add(c)
            targets.append((c, r["name"]))
            if len(targets) >= limit:
                break

    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for wcode, name in targets:
        pre_close = fetch_preclose(wcode)
        res = analyze(wcode, name, pre_close)
        if not res:
            continue
        out.append(res)
        print(f"[{len(out)}] {wcode} {name} 分时强度{res['score']} MACD{'多' if res['macd_bull'] else '空'} 收盘位置{res['close_pos']}% 尾盘{res['tail_dir']}%", flush=True)

    os.makedirs("outputs", exist_ok=True)
    md = [f"# ⏱️ 分时强度分析 {today}", "",
          f"> 数据源：westock分钟数据 · 共{len(out)}只", ""]
    for r in sorted(out, key=lambda x: -x["score"]):
        seal = f" · 🔒封板{str(r['seal_time'])[:2]}:{str(r['seal_time'])[2:]}" if r["limitup"] else ""
        md.append(f"### {r['name']}（{r['code']}）分时强度 {r['score']}/100{seal}")
        md.append(f"- 分时MACD：{'多头(白上黄)' if r['macd_bull'] else '空头(白下黄)'} · 金叉{r['gc']}次/死叉{r['dc']}次 · 红柱占比{r['hist_pos']}%")
        md.append(f"- 日内：开{r['open']} 高{r['high']} 低{r['low']} 收{r['close']} · 收盘位置{r['close_pos']}%（0=最低 100=最高）")
        md.append(f"- 尾盘30分钟：{'↑' if r['tail_dir'] > 0 else '↓' if r['tail_dir'] < 0 else '→'} {r['tail_dir']}%")
        md.append("")
    path = f"outputs/minute_strength_{today}.md"
    open(path, "w", encoding="utf-8").write("\n".join(md))
    print(f"[OK] {path}")


if __name__ == "__main__":
    main()
