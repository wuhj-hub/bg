#!/usr/bin/env python3
"""
liangxue_minute_check.py —— 量学PASS股 分时量波验证（量波卷第3章·2026-08-30）
============================================================================
对量学 PASS 标的做分时量波检查（量学三部曲之三·选时维度）：
  1. 人线为王（VWAP/均价线）：现价偏离人线 >4% → "4G为皇"回归预警
  2. 天人和谐：|偏离| <2% → 和谐续原势（持股）
  3. 当日位置：现价处于当日高低百分位（低吸/追高判断）
  4. 尾盘方向：尾盘30分钟斜率（最后半小时方向）
  5. 量波形态：分时波动率（尖角波=剧烈/圆角波=温和）

用法：
  python3 liangxue_minute_check.py                      # 默认量学PASS全部
  python3 liangxue_minute_check.py --top 10             # 只查TOP10
  python3 liangxue_minute_check.py --codes sh600036     # 指定代码
输出：outputs/liangxue_minute_check_latest.json + stdout
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]


def cli(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def parse_minute(txt):
    """解析分时：返回 [{time, price, vol, amount}]（累计量额）"""
    rows = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 5 or parts[0] == "code" or "---" in parts[0]:
            continue
        if re.match(r"^\d{4}$", parts[1]) and parts[1] >= "0930":
            try:
                rows.append({"time": parts[1], "price": float(parts[2]),
                             "vol": float(parts[3]), "amount": float(parts[4])})
            except (ValueError, IndexError):
                pass
    return rows


def check_minute(code):
    """单只分时量波检查"""
    txt = cli(["minute", code, "--limit", "240"])
    rows = parse_minute(txt)
    if len(rows) < 60:
        return {"code": code, "ok": False, "reason": f"分时数据不足({len(rows)})"}
    # 人线（VWAP）= 累计成交额 / (累计量×100)，量单位手
    last = rows[-1]
    vwap = last["amount"] / (last["vol"] * 100) if last["vol"] > 0 else last["price"]
    cur = last["price"]
    dev = (cur - vwap) / vwap * 100 if vwap > 0 else 0
    # 当日高低位置
    prices = [r["price"] for r in rows]
    lo, hi = min(prices), max(prices)
    pos = (cur - lo) / (hi - lo) * 100 if hi > lo else 50
    # 尾盘方向：最后30分钟（约30行）
    tail = rows[-30:]
    if len(tail) >= 5:
        tail_slope = (tail[-1]["price"] - tail[0]["price"]) / tail[0]["price"] * 100
    else:
        tail_slope = 0
    # 波动率（尖角/圆角判别）
    import statistics
    devs = [abs(r["price"] / vwap - 1) for r in rows]
    volatility = statistics.mean(devs) * 100 if devs else 0
    # 量波形态分级
    if dev > 4:
        wave = "超4G·回归预警"  # 天线远离人线超4G，必向人线回归
    elif dev > 2:
        wave = "4G边缘·谨慎"
    elif dev < -4:
        wave = "超4G·负偏离·反弹预警"
    elif dev < -2:
        wave = "4G边缘·负偏离"
    else:
        wave = "天人和谐·续原势"
    # 当日K线颜色（低开高走=上绿下红·必然上攻）
    open_p = rows[0]["price"]
    kline = "上绿下红·必然上攻" if cur > open_p else "上红下绿·注意回落"
    return {"code": code, "ok": True, "close": round(cur, 2), "vwap": round(vwap, 2),
            "dev_pct": round(dev, 1), "pos_pct": round(pos, 0), "tail_slope": round(tail_slope, 2),
            "volatility": round(volatility, 2), "wave": wave, "kline": kline}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="outputs/liangxue_latest.json")
    ap.add_argument("--top", type=int, default=0, help="只检查前N只PASS")
    ap.add_argument("--codes", default="", help="指定代码（逗号分隔）")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        items = [{"code": c, "name": "", "score": 0} for c in codes]
    else:
        if not os.path.exists(args.json):
            print(f"[ERR] {args.json} 不存在", file=sys.stderr)
            sys.exit(1)
        d = json.load(open(args.json, encoding="utf-8"))
        passes = [s for s in d.get("signals", []) if s.get("level") == "PASS"]
        passes.sort(key=lambda x: -x.get("score", 0))
        if args.top:
            passes = passes[:args.top]
        items = [{"code": s["code"], "name": s.get("name", ""), "score": s.get("score")} for s in passes]
    print(f"[INFO] 分时量波检查 {len(items)} 只...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(lambda it: {**check_minute(it["code"]), "name": it["name"],
                                          "score": it["score"]}, items))

    ok = [r for r in results if r.get("ok")]
    ok.sort(key=lambda r: -r.get("dev_pct", 0))
    out = {"date": datetime.now().strftime("%Y-%m-%d"),
           "desc": "量学PASS股分时量波验证（人线为王/4G为皇/天人和谐）",
           "total": len(ok), "check": ok}
    os.makedirs("outputs", exist_ok=True)
    json.dump(out, open("outputs/liangxue_minute_check_latest.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"✅ outputs/liangxue_minute_check_latest.json")

    print(f"\n分时量波验证（人线为王·4G为皇）: {len(ok)} 只")
    print(f"{'代码':<10}{'名称':<8}{'收盘':<8}{'人线':<8}{'偏离%':<7}{'位置%':<6}量波状态")
    for r in ok[:20]:
        print(f"{r['code']:<10}{r['name']:<8}{r['close']:<8}{r['vwap']:<8}"
              f"{r['dev_pct']:<7}{r['pos_pct']:<6} {r['wave']} | {r['kline']}")


if __name__ == "__main__":
    main()
