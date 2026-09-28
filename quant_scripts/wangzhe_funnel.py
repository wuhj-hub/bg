#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wangzhe_funnel.py —— 涨停王者 · 合格标的漏斗（逐条件过筛）

【标准】才哥·涨停王者（王侯倍量柱）严格口径：
  入池：涨停 + 首板 + 换手>5% + 量比 1.5~4 + 价格 < 10 元
  确认（涨停后 T+3，正版 A2~A5）：
    A2 后3日最低收盘 > 涨停日收盘
    A3 后3日量能依次递减
    A4a 后3日最高涨幅 < 9%
    A4b MA60 向上
    A5 后3日均量 < 涨停日量
  逐条件过筛，不满足即淘汰；全部满足 = 合格标的。

【窗口】默认 --since 2026-08-01（可由参数覆盖）

【用法】
  python3 wangzhe_funnel.py                      # 默认窗口 2026-08-01 起
  python3 wangzhe_funnel.py --since 2026-08-01 --date 2026-09-28
  python3 wangzhe_funnel.py --signals outputs/wangzhe_signals.csv

【输出】outputs/涨停王者_合格标的_{date}.md / .csv
"""
import os, re, sys, csv, json, argparse, subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(BASE), "outputs") if os.path.basename(BASE) == "quant_scripts" else os.path.join(BASE, "outputs")


def log(m):
    print(m, flush=True)


def _f(x):
    try:
        return float(x)
    except Exception:
        return None


def parse_kline(txt):
    out = {}
    for ln in (txt or "").splitlines():
        if not ln.strip().startswith("|"):
            continue
        p = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(p) < 7 or not re.match(r"^(sh|sz)\d{6}$", p[0]):
            continue
        try:
            out.setdefault(p[0], []).append([p[1], float(p[2]), float(p[3]), float(p[4]), float(p[5]), float(p[6])])
        except ValueError:
            continue
    for s in out:
        out[s].sort()
    return out


def _fb(batch, limit):
    for _ in range(2):
        try:
            r = subprocess.run(WESTOCK + ["kline", ",".join(batch), "--period", "day", "--limit", str(limit)],
                               capture_output=True, text=True, timeout=600)
            d = parse_kline(r.stdout)
            if d:
                return d
        except Exception:
            pass
    return {}


def fetch_klines(codes, limit=130):
    out = {}
    batches = [codes[i:i + 30] for i in range(0, len(codes), 30)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for d in ex.map(lambda b: _fb(b, limit), batches):
            out.update(d)
    return out


def fetch_names(codes):
    out = {}
    for i in range(0, len(codes), 30):
        try:
            r = subprocess.run(WESTOCK + ["profile", ",".join(codes[i:i + 30])],
                               capture_output=True, text=True, timeout=200)
            for ln in r.stdout.splitlines():
                if ln.strip().startswith("|"):
                    p = [x.strip() for x in ln.strip("|").split("|")]
                    if len(p) >= 2 and re.match(r"^(sh|sz)\d{6}$", p[0]):
                        out[p[0]] = p[1]
        except Exception:
            pass
    return out


def judge(code, sd, price, vr, b):
    """返回 (stage, detail)。stage ∈ 合格/淘汰/待确认/无数据"""
    if not b:
        return "无数据", None
    dates = [x[0] for x in b]
    if sd not in dates:
        return "无数据", None
    t = dates.index(sd)

    def lu(i):
        return i > 0 and b[i - 1][2] > 0 and (b[i][2] / b[i - 1][2] - 1) >= 0.098
    if not lu(t):
        real = next((i for i in range(t, max(0, t - 6), -1) if lu(i)), None)
        if real is None:
            return "淘汰", {"fail": "非涨停"}
        t = real
    if t < 59:
        return "无数据", None
    if not (price is not None and price < 10):
        return "淘汰", {"fail": "价格>=10"}
    if not (vr is None or 1.5 <= vr <= 4):
        return "淘汰", {"fail": "量比"}
    c_t, v_t = b[t][2], b[t][5]
    if t + 3 >= len(b):
        return "待确认", {"c_t": round(c_t, 2)}
    c13 = [b[t + 1][2], b[t + 2][2], b[t + 3][2]]
    h13 = [b[t + 1][3], b[t + 2][3], b[t + 3][3]]
    v13 = [b[t + 1][5], b[t + 2][5], b[t + 3][5]]
    ma60_t = sum(b[i][2] for i in range(t - 59, t + 1)) / 60
    ma60_t3 = sum(b[i][2] for i in range(t - 56, t + 4)) / 60
    ck = {"A2": min(c13) > c_t, "A3": v13[2] < v13[1] < v13[0],
          "A4a": max(h13) / c_t - 1 < 0.09, "A4b": ma60_t3 >= ma60_t, "A5": sum(v13) / 3 < v_t}
    fail = [k for k, v in ck.items() if not v]
    d = {"conf": b[t + 3][0], "c_t": round(c_t, 2),
         "r5": round((b[t + 8][2] / b[t + 3][2] - 1) * 100, 2) if t + 8 < len(b) else ""}
    return ("合格" if not fail else "淘汰"), {**d, "fail": ",".join(fail)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-01")
    ap.add_argument("--date", default=None, help="输出文件名日期，默认今天")
    ap.add_argument("--signals", default=os.path.join(OUT, "wangzhe_signals.csv"))
    ap.add_argument("--limit", type=int, default=130)
    a = ap.parse_args()
    from datetime import datetime, timezone, timedelta
    today = a.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    if not os.path.exists(a.signals):
        log(f"[ERR] 信号库不存在: {a.signals}")
        sys.exit(1)
    rows = [r for r in csv.DictReader(open(a.signals, encoding="utf-8")) if r.get("signal_date", "") >= a.since]
    log(f"[INFO] 窗口 {a.since} 起：信号 {len(rows)} 条")

    codes = sorted({r["code"] for r in rows})
    log(f"[INFO] 拉取日线 {len(codes)} 只…")
    kl = fetch_klines(codes, a.limit)
    log(f"[INFO] 日线 {len(kl)} 只")

    stat = defaultdict(int)
    ok, pend = [], []
    for r in rows:
        st, d = judge(r["code"], r["signal_date"], _f(r.get("price")), _f(r.get("vol_ratio")), kl.get(r["code"]))
        stat[st] += 1
        if st == "合格":
            ok.append((r, d))
        elif st == "待确认":
            pend.append((r, d))

    log(f"[INFO] 漏斗：窗口 {len(rows)} → 合格 {len(ok)} | 淘汰 {stat['淘汰']} | 待确认 {len(pend)} | 无数据 {stat['无数据']}")

    # 去重（按标的，取最近确认）
    by = defaultdict(list)
    for r, d in ok:
        by[r["code"]].append((r, d))
    names = fetch_names(sorted(by)) if by else {}
    nm = {}
    for r in rows:
        if r.get("name"):
            nm[r["code"]] = r["name"]
    nm.update(names)

    out = []
    for c, lst in by.items():
        lst.sort(key=lambda x: x[1].get("conf", ""), reverse=True)
        r5 = [x[1]["r5"] for x in lst if x[1].get("r5") not in ("", None)]
        out.append({"code": c, "name": nm.get(c, ""), "confirm_date": lst[0][1].get("conf", ""),
                    "times": len(lst), "price": lst[0][0].get("price", ""),
                    "r5": round(sum(r5) / len(r5), 2) if r5 else ""})
    out.sort(key=lambda x: x["confirm_date"], reverse=True)

    os.makedirs(OUT, exist_ok=True)
    md = os.path.join(OUT, f"涨停王者_合格标的_{today}.md")
    cs = os.path.join(OUT, f"涨停王者_合格标的_{today}.csv")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write(f"# 涨停王者 · 合格标的（窗口 {a.since} 起）\n\n")
        fh.write(f"> 生成 {today} ｜ 窗口内信号 {len(rows)} 条 → **合格标的 {len(out)} 只**（淘汰 {stat['淘汰']} / 待确认 {len(pend)}）\n\n")
        fh.write("| 代码 | 名称 | 确认日 | 确认次数 | 信号日价 | 确认后5日均值% |\n|---|---|---|---|---|---|\n")
        for r in out:
            fh.write(f"| {r['code']} | {r['name'] or '-'} | {r['confirm_date']} | {r['times']} | {r['price']} | {r['r5']} |\n")
    with open(cs, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["code", "name", "confirm_date", "times", "price", "r5"])
        w.writeheader()
        for r in out:
            w.writerow(r)
    log(f"[OK] {md}")
    log(f"[OK] {cs}")
    for r in out[:20]:
        log(f"   {r['code']} {r['name']} 确认日{r['confirm_date']}")


if __name__ == "__main__":
    main()
