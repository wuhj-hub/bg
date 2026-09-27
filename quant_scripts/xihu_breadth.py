#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xihu_breadth.py —— 西湖广度温度计（下雨图 + 大盘量化）
=========================================================
方法论来源：西湖区的孩纸《西湖大盘量化分析系统升级版（解决无卡顿）》(2020-03-04)
  把通达信「横向统计函数 + 拓展数据」方案，复刻为纯 Python 的
    信号层（逐股 0/1）→ 统计层（全市场计数）→ 展示层（广度占比 / 下雨图）

四个信号（口径与原文公式一致）：
  强势股  : CLOSE / HHV(HIGH,250) > 0.9
  第二阶段: C>MA50>MA150>MA200 且 MA200 连升 N 日 且 C/LLV(C,200)>1.3 且 C/HHV(C,200)>T
  新高    : HIGH = HHV(HIGH,250) 且 上市 > 60 日
  新低    : LOW < 前 250 日最低价（不含当日）

三张广度图：
  QSG%  强势股占比（原文参考线 6 / 20）
  EJD%  第二阶段占比
  下雨图净值 = 新高数 − 新低数

数据源：westock-data-skillhub 批量日K（默认前复权，--limit 260）
输出：
  outputs/xihu_breadth_{date}.md          报告
  outputs/xihu_breadth_latest.json         结构化 JSON（供盘前/复盘引用）
  outputs/xihu_breadth_history.json        按日累积（供趋势/画净值曲线）

用法：
  python3 xihu_breadth.py --list all_mainboard.csv --batch 40   # 全量
  python3 xihu_breadth.py --stocks sh600000,sz000001 --limit 260  # 小样本测试
  python3 xihu_breadth.py --quick 12.5 30.0 850 120              # 快速模式（QSG% EJD% 新高 新低）
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
DATA_ROW = re.compile(r"^(sh|sz|bj)\d{6}$")


def run(args, timeout=150):
    """执行 westock CLI，返回原始输出（含重试）。"""
    for i in range(4):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(3 * (i + 1))
    return ""


def norm_code(code):
    """纯数字/带前缀 code -> sh/sz/bj 前缀。"""
    code = code.strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith(("6", "9", "5")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def parse_kline(raw):
    """解析批量K线输出 -> {wcode: [(date, open, close, high, low), ...] 按日期升序}
    批量列序: symbol|date|open|last|high|low|volume|amount|exchange，且 date 降序输出。"""
    out = {}
    for ln in raw.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 6 or not DATA_ROW.match(parts[0]):
            continue
        try:
            row = (parts[1], float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5]))
        except ValueError:
            continue
        out.setdefault(parts[0], []).append(row)
    for k in out:
        out[k].sort(key=lambda x: x[0])  # 升序（最旧在前）
    return out


def _ma(seq, i, n):
    """以 i 结尾、长度 n 的均值；数据不足返回 None。"""
    if i + 1 < n:
        return None
    return sum(seq[i - n + 1:i + 1]) / n


def eval_signals(kl, p):
    """对单只股票计算四信号。kl 为升序 (date,open,close,high,low)。
    返回 dict 或 None（数据过少）。"""
    n = len(kl)
    if n < 2:
        return None
    highs = [r[3] for r in kl]
    lows = [r[4] for r in kl]
    closes = [r[2] for r in kl]
    c_last = closes[-1]
    h_last = highs[-1]
    l_last = lows[-1]
    if not c_last or c_last <= 0:
        return None

    win = p["window"]  # 250
    w = min(win, n)
    hhv_h = max(highs[-w:])
    llv_c = min(closes[-w:]) if w else c_last
    hhv_c = max(closes[-w:]) if w else c_last

    # 强势股：收盘价在 250 日最高价的 90% 以内
    strong = (c_last / hhv_h) > p["strong_thr"] if hhv_h else False

    # 新高：当日最高价 = 250 日最高价，且上市 > 60 日
    new_high = (h_last >= hhv_h - 1e-6) and (n > 60)

    # 新低：当日最低价 < 前 250 日最低价（不含当日）
    new_low = False
    if n >= win + 1:
        prev_llv = min(lows[-win - 1:-1])
        new_low = l_last < prev_llv

    # 第二阶段（Minervini 趋势模板变体）
    stage2 = False
    if n >= 220:
        ma50 = _ma(closes, n - 1, 50)
        ma150 = _ma(closes, n - 1, 150)
        ma200 = _ma(closes, n - 1, 200)
        if ma50 and ma150 and ma200:
            trend = (c_last > ma50 > ma150 > ma200)
            # MA200 连升 N 日
            rising = True
            last_n = p["stage2_n"]
            for i in range(n - last_n, n):
                m_cur = _ma(closes, i, 200)
                m_prev = _ma(closes, i - 1, 200)
                if m_cur is None or m_prev is None or not (m_cur > m_prev):
                    rising = False
                    break
            # 较 200 日最低收盘涨幅 > 30%，且贴近 200 日最高收盘 > T
            c200_l = min(closes[-min(200, n):])
            c200_h = max(closes[-min(200, n):])
            gain_ok = (c_last / c200_l) > 1.3 if c200_l else False
            near_ok = (c_last / c200_h) > p["stage2_t"] if c200_h else False
            stage2 = trend and rising and gain_ok and near_ok

    return {
        "close": round(c_last, 3),
        "pct_to_high": round(c_last / hhv_h * 100, 1) if hhv_h else None,
        "strong": strong,
        "stage2": stage2,
        "new_high": new_high,
        "new_low": new_low,
        "bars": n,
    }


def load_list(path):
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if row and row[0].strip() and row[0].strip().lower() != "code":
                name = row[1].strip() if len(row) > 1 else ""
                out.append((row[0].strip(), name))
    return out


def _apply(chunk, codes, data, result, p):
    """把一批返回结果并入 result，返回本批有效数。"""
    got = 0
    for (code, name), wcode in zip(chunk, codes):
        if result.get(code, {}).get("strong") is not None:
            got += 1
            continue
        kl = data.get(wcode, [])
        sig = eval_signals(kl, p) if kl else None
        if sig:
            got += 1
            sig["name"] = name or result.get(code, {}).get("name", "")
            result[code] = sig
        else:
            prev = result.get(code, {})
            result[code] = {"name": name or prev.get("name", ""), "strong": None,
                            "stage2": None, "new_high": None, "new_low": None, "bars": len(kl)}
    return got


def scan(stocks, p):
    """批量扫描，返回 {code: {name, ...signals}}。
    runner 上 westock 批量偶发丢股票 → 收集缺口后小批(10)补取，仍缺则逐只补。"""
    result = {}
    n = len(stocks)
    batch = p["batch"]
    lacks = []
    for i in range(0, n, batch):
        chunk = stocks[i:i + batch]
        codes = [norm_code(c) for c, _ in chunk]
        raw = run(["kline", ",".join(codes), "--period", "day", "--limit", str(p["limit"])])
        data = parse_kline(raw)
        got = _apply(chunk, codes, data, result, p)
        missing = [c for c, w in zip(chunk, codes) if not data.get(w)]
        print(f"[{i + len(chunk)}/{n}] 本批有效 {got}/{len(chunk)}"
              + (f" | ⚠️缺 {len(missing)} 只" if missing else ""), flush=True)
        lacks.append((chunk, missing))

    # ── 缺口补齐：小批(10)复取 → 仍缺逐只补
    miss_stocks = [c for _, m in lacks for c in m]
    if miss_stocks:
        print(f"[补齐] 共 {len(miss_stocks)} 只缺数据，启动补偿…", flush=True)
        for j in range(0, len(miss_stocks), 10):
            sub = miss_stocks[j:j + 10]
            codes = [norm_code(c[0]) for c in sub]
            raw = run(["kline", ",".join(codes), "--period", "day", "--limit", str(p["limit"])])
            _apply(sub, codes, parse_kline(raw), result, p)
        still = [c for c in miss_stocks if result.get(c[0], {}).get("strong") is None]
        for (code, name) in still:
            wcode = norm_code(code)
            raw = run(["kline", wcode, "--period", "day", "--limit", str(p["limit"])])
            _apply([(code, name)], [wcode], parse_kline(raw), result, p)
        fixed = sum(1 for c in miss_stocks if result.get(c[0], {}).get("strong") is not None)
        print(f"[补齐] 成功补回 {fixed}/{len(miss_stocks)} 只", flush=True)
    return result


def aggregate(result):
    """统计层：全市场计数。"""
    valid = {c: v for c, v in result.items() if v.get("strong") is not None}
    n = len(valid)
    strong = sum(1 for v in valid.values() if v["strong"])
    stage2 = sum(1 for v in valid.values() if v["stage2"])
    new_high = sum(1 for v in valid.values() if v["new_high"])
    new_low = sum(1 for v in valid.values() if v["new_low"])
    return {
        "total": n,
        "strong": strong,
        "stage2": stage2,
        "new_high": new_high,
        "new_low": new_low,
        "qsg_pct": round(strong / n * 100, 2) if n else 0.0,
        "ejd_pct": round(stage2 / n * 100, 2) if n else 0.0,
        "net_high": new_high - new_low,
    }


def judge(agg):
    """展示层：给出广度定性判断。"""
    q = agg["qsg_pct"]
    if q >= 20:
        q_level = "🔥 极热（强势股占比>20%，原文上轨）"
    elif q >= 6:
        q_level = "🟢 健康（强势股占比 6%~20%）"
    else:
        q_level = "❄️ 偏冷（强势股占比<6%，原文下轨）"
    net = agg["net_high"]
    if net > 0:
        rain = "☀️ 晴（新高 > 新低）"
    elif net == 0:
        rain = "⛅ 阴（新高 = 新低）"
    else:
        rain = "🌧️ 雨（新高 < 新低，广度收缩）"
    return {"qsg_level": q_level, "rain": rain}


def build_report(agg, result, jd, date_str, p):
    top_high = sorted([(c, v) for c, v in result.items() if v.get("new_high")],
                      key=lambda x: -(x[1].get("pct_to_high") or 0))[:20]
    strong_list = sorted([(c, v) for c, v in result.items() if v.get("strong")],
                         key=lambda x: -(x[1].get("pct_to_high") or 0))
    stage2_list = sorted([(c, v) for c, v in result.items() if v.get("stage2")],
                         key=lambda x: -(x[1].get("pct_to_high") or 0))

    L = []
    L.append(f"# 🌧️ 西湖广度温度计（下雨图 + 大盘量化）— {date_str}\n")
    L.append(f"> 口径：沪深主板 {agg['total']} 只有效（日K口径，前复权）｜"
             f"参数 强势>0.9 · 第二阶段 N={p['stage2_n']}/T={p['stage2_t']} · 窗口{p['window']}日\n")
    L.append("## 核心数据\n")
    L.append("| 指标 | 数值 | 说明 |")
    L.append("|---|---|---|")
    L.append(f"| 强势股占比 QSG% | **{agg['qsg_pct']}%**（{agg['strong']}只） | 收盘≥250日高点的90% |")
    L.append(f"| 第二阶段占比 EJD% | **{agg['ejd_pct']}%**（{agg['stage2']}只） | 多头排列+均线抬升+贴近高点 |")
    L.append(f"| 新高家数 | {agg['new_high']} | 创250日新高 |")
    L.append(f"| 新低家数 | {agg['new_low']} | 创250日新低 |")
    L.append(f"| **下雨图净值** | **{agg['net_high']:+d}** | 新高−新低 |")
    L.append("")
    L.append("## 广度判读\n")
    L.append(f"- 强势股温度：{jd['qsg_level']}（参考线 6 / 20）")
    L.append(f"- 下雨图天气：{jd['rain']}")
    L.append("")

    L.append(f"## 创新高个股（{len(top_high)}只，展示前20）\n")
    L.append("| 代码 | 名称 | 收盘 | 距250日高点 |")
    L.append("|---|---|---|---|")
    for c, v in top_high:
        L.append(f"| {c} | {v['name']} | {v['close']} | {v['pct_to_high']}% |")
    L.append("")

    L.append(f"## 第二阶段个股（{len(stage2_list)}只，展示前25）\n")
    L.append("| 代码 | 名称 | 收盘 | 距250日高点 |")
    L.append("|---|---|---|---|")
    for c, v in stage2_list[:25]:
        L.append(f"| {c} | {v['name']} | {v['close']} | {v['pct_to_high']}% |")
    if len(stage2_list) > 25:
        L.append(f"| ... 其余 {len(stage2_list) - 25} 只省略 |")
    L.append("")
    L.append("---")
    L.append("*本报告由 xihu_breadth.py 自动生成｜复刻自「西湖大盘量化分析系统」｜量化规律总结非投资建议*")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="all_mainboard.csv")
    ap.add_argument("--stocks", help="逗号分隔的代码，直接指定股票池（测试用）")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--limit", type=int, default=260)
    ap.add_argument("--window", type=int, default=250)
    ap.add_argument("--strong-thr", type=float, default=0.9)
    ap.add_argument("--stage2-n", type=int, default=20)
    ap.add_argument("--stage2-t", type=float, default=0.75)
    ap.add_argument("--quick", nargs=4, metavar=("QSG", "EJD", "NHIGH", "NLOW"),
                    help="快速模式：直接给定 QSG% EJD% 新高数 新低数，跳过扫描")
    ap.add_argument("--outdir", default="outputs")
    args = ap.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(args.outdir, exist_ok=True)
    p = {"batch": args.batch, "limit": args.limit, "window": args.window,
         "strong_thr": args.strong_thr, "stage2_n": args.stage2_n, "stage2_t": args.stage2_t}

    if args.quick:
        qsg, ejd, nh, nl = args.quick
        agg = {"total": 0, "strong": 0, "stage2": 0, "new_high": int(nh), "new_low": int(nl),
               "qsg_pct": float(qsg), "ejd_pct": float(ejd), "net_high": int(nh) - int(nl)}
        result = {}
        jd = judge(agg)
        md = build_report(agg, result, jd, date_str, p)
        md_path = os.path.join(args.outdir, f"xihu_breadth_{date_str}.md")
        open(md_path, "w", encoding="utf-8").write(md)
        print(f"[OK] {md_path}")
        return

    if args.stocks:
        stocks = [(c.strip(), "") for c in args.stocks.split(",") if c.strip()]
    else:
        if not os.path.exists(args.list):
            print(f"[ERR] list not found: {args.list}", file=sys.stderr)
            sys.exit(1)
        stocks = load_list(args.list)
    print(f"[INFO] 股票池 {len(stocks)} 只", flush=True)

    result = scan(stocks, p)
    agg = aggregate(result)
    jd = judge(agg)

    md = build_report(agg, result, jd, date_str, p)
    md_path = os.path.join(args.outdir, f"xihu_breadth_{date_str}.md")
    open(md_path, "w", encoding="utf-8").write(md)

    js = {
        "date": date_str,
        "total": agg["total"],
        "strong": agg["strong"], "qsg_pct": agg["qsg_pct"],
        "stage2": agg["stage2"], "ejd_pct": agg["ejd_pct"],
        "new_high": agg["new_high"], "new_low": agg["new_low"], "net_high": agg["net_high"],
        "qsg_level": jd["qsg_level"], "rain": jd["rain"],
        "params": {"window": p["window"], "strong_thr": p["strong_thr"],
                   "stage2_n": p["stage2_n"], "stage2_t": p["stage2_t"]},
        "new_high_list": [{"code": c, "name": v["name"], "close": v["close"]}
                          for c, v in result.items() if v.get("new_high")][:200],
        "stage2_list": [{"code": c, "name": v["name"], "close": v["close"]}
                        for c, v in result.items() if v.get("stage2")][:200],
    }
    jpath = os.path.join(args.outdir, "xihu_breadth_latest.json")
    open(jpath, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    # 历史累积（按日期，供画净值曲线）
    hist_path = os.path.join(args.outdir, "xihu_breadth_history.json")
    hist = {}
    if os.path.exists(hist_path):
        try:
            hist = json.load(open(hist_path, encoding="utf-8"))
        except Exception:
            hist = {}
    hist[date_str] = {"qsg_pct": agg["qsg_pct"], "ejd_pct": agg["ejd_pct"],
                      "new_high": agg["new_high"], "new_low": agg["new_low"],
                      "net_high": agg["net_high"]}
    hist = {k: hist[k] for k in sorted(hist.keys())}
    open(hist_path, "w", encoding="utf-8").write(json.dumps(hist, ensure_ascii=False, indent=1))

    print(f"[OK] QSG%={agg['qsg_pct']} EJD%={agg['ejd_pct']} "
          f"新高{agg['new_high']} 新低{agg['new_low']} 净值{agg['net_high']:+d} | {jd['rain']}")
    print(f"[OK] {md_path}\n[OK] {jpath}\n[OK] {hist_path}")


if __name__ == "__main__":
    main()
