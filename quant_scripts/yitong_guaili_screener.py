#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yitong_guaili_screener.py —— 一统天下·乖离低买 全主板扫描器
====================================================================
信号口径（照搬 yitong_screener.py 的 guaili_buy）：
    BIAS = (C − MA5) / MA5 × 100  <  −7

历史验证（2026-09-14，3,120 只沪深主板 · 1991~2026 全历史 · Newey-West t 检验 lag=20）：
    **6/6 环境全部 5% 显著为正**，日均超额 +4.43% ~ +11.53%（t = +6.1 ~ +7.9）；
    长期熊市中位超额 +2.56%/20日、胜率 59%（均值为 +9.98%，受右尾影响，看中位）。
    —— 全体系 16 个待验信号中唯一「全环境显著为正」者。

用法: python3 yitong_guaili_screener.py [--limit 0] [--out outputs]
输出: outputs/乖离低买_{date}.md  +  outputs/乖离低买_latest.json
"""
import os, sys, json, csv, argparse, time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Referer": "http://stockpage.10jqka.com.cn/"}
N_TAIL = 30          # 只需尾部 30 根即可算 MA5 / BIAS / 20日涨幅
BIAS_TH = -7.0


def fetch_tail(six):
    """取该股最近 N_TAIL 根日线（升序），返回 (dates, opens, highs, lows, closes, vols)"""
    url = f"http://d.10jqka.com.cn/v6/line/hs_{six}/01/all.js"
    for _ in range(3):
        try:
            r = urllib.request.Request(url, headers=UA)
            t = urllib.request.urlopen(r, timeout=25).read().decode("utf-8", "ignore")
            i = t.find("{")
            if i < 0:
                return None
            d = json.JSONDecoder().raw_decode(t[i:])[0]
            pf = d["priceFactor"]; P = [int(x) for x in d["price"].split(",")]
            V = d["volumn"].split(",") if "volumn" in d else []
            md = d["dates"].split(","); k = 0; full = []
            for y, cnt in d["sortYear"]:
                for s in md[k:k + cnt]:
                    s = s.zfill(4); full.append(f"{y}-{s[:2]}-{s[2:]}")
                k += cnt
            n = min(len(full), len(P) // 4, len(V))
            if n < N_TAIL:
                return None
            base = n - N_TAIL
            dates = full[base:]; o = []; h = []; l = []; c = []; v = []
            for j in range(base, n):
                b = P[4 * j:4 * j + 4]
                l.append(b[0] / pf); o.append((b[0] + b[1]) / pf)
                h.append((b[0] + b[2]) / pf); c.append((b[0] + b[3]) / pf)
                v.append(float(V[j]) if V[j].isdigit() else 0.0)
            return dates, o, h, l, c, v
        except Exception:
            time.sleep(1.0)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只扫前 N 只（0=全部）")
    ap.add_argument("--out", default="outputs")
    args = ap.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pool_path = None
    for p in (os.path.join(base, "all_mainboard.csv"), "all_mainboard.csv",
              os.path.join(base, "quant_scripts", "all_mainboard.csv")):
        if os.path.exists(p):
            pool_path = p; break
    if not pool_path:
        print("[ERR] all_mainboard.csv 未找到"); sys.exit(1)
    pool = []
    for r in csv.DictReader(open(pool_path, encoding="utf-8-sig")):
        code = (r.get("code") or "").strip()
        name = (r.get("name") or "").strip()
        if len(code) == 6 and code.isdigit():
            pool.append(((("sh" if code[0] in "69" else "sz") + code), name))
    if args.limit:
        pool = pool[:args.limit]
    print(f"[INFO] 乖离低买扫描: {len(pool)} 只主板 | 阈值 BIAS<{BIAS_TH}%", flush=True)

    hits = []
    done = 0

    def work(item):
        return item, fetch_tail(item[0][2:])

    with ThreadPoolExecutor(8) as ex:
        for fu in as_completed({ex.submit(work, it): it for it in pool}):
            (code, name), res = fu.result()
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(pool)} 命中{len(hits)}", flush=True)
            if not res:
                continue
            dates, o, h, l, c, v = res
            if c[-1] <= 0.3 or len(c) < 21:
                continue
            if "ST" in name.upper() or "退" in name:
                continue
            ma5 = sum(c[-5:]) / 5
            if ma5 <= 0:
                continue
            bias = (c[-1] - ma5) / ma5 * 100
            if bias >= BIAS_TH:
                continue
            ret20 = (c[-1] / c[-21] - 1) * 100 if c[-21] > 0 else 0
            chg = (c[-1] / c[-2] - 1) * 100 if c[-2] > 0 else 0
            hits.append({"code": code, "name": name, "close": round(c[-1], 2),
                         "ma5": round(ma5, 2), "bias": round(bias, 2),
                         "chg": round(chg, 2), "ret20": round(ret20, 1), "date": dates[-1]})
    hits.sort(key=lambda x: x["bias"])
    date_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(args.out, exist_ok=True)
    L = [f"# 🎯 一统天下·乖离低买 {date_str}", "",
         f"> 信号：(C−MA5)/MA5×100 < {BIAS_TH}%（急跌乖离低吸）｜扫描主板 {len(pool)} 只 ｜ 命中 **{len(hits)}** 只",
         f"> 📊 20年历史验证：**6/6 环境全部 5% 显著为正**，中位超额 +2.56%/20日、胜率 59%（详见 ②.7）", ""]
    if hits:
        L.append("| 代码 | 名称 | 现价 | MA5 | 乖离% | 当日涨跌 | 20日涨幅 |")
        L.append("|---|---|---|---|---|---|---|")
        for x in hits[:40]:
            L.append(f"| {x['code'][2:]} | {x['name']} | {x['close']} | {x['ma5']} | "
                     f"**{x['bias']}%** | {x['chg']}% | {x['ret20']}% |")
        if len(hits) > 40:
            L.append(f"\n*（共 {len(hits)} 只，仅列最深的 40 只）*")
    else:
        L.append("*今日无标的进入乖离低买区（BIAS < −7%）*")
    L.append("\n> ⚠️ 机械规则输出，不构成投资建议；该信号为「急跌低吸」，须配合止损（建议 2×ATR）。")
    md = "\n".join(L)
    with open(os.path.join(args.out, f"乖离低买_{date_str}.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(args.out, "乖离低买_latest.json"), "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "threshold": BIAS_TH, "total": len(hits), "hits": hits},
                  f, ensure_ascii=False, indent=1)
    print(f"[OK] 命中 {len(hits)} 只 → {args.out}/乖离低买_{date_str}.md")


if __name__ == "__main__":
    main()
