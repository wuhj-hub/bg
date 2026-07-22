#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_fish_pool.py — 动态生成鱼身股票池（近20日日均成交额排名）

数据源：腾讯财经 web.ifzq.gtimg.cn（日K线，沙箱/runner 均可用，不受东方财富反爬影响）
输入：all_mainboard.csv（由 gen_mainboard.py 生成，沪深主板 ~3000只，code 为纯数字）
逻辑：
  1. 读取主板清单
  2. 对每只拉近20日日K线，按 成交量(手)×100×均价 估算成交额，算近20日日均
  3. 按日均成交额降序取前 TOP_N(300) 只
  4. 强制纳入核心关注3只（灵康/红豆/日发精机）
  5. 写出 stock_pool.txt（与鱼身 skill 原有格式兼容）

说明：腾讯K线接口仅返回 [date,open,close,high,low,volume(手)]，无直接成交额字段，
      故用 volume×100×均价 估算（与真实成交额高度线性相关，排名等价）。

用法：
  python3 gen_fish_pool.py                  # 读 ../all_mainboard.csv
  python3 gen_fish_pool.py /path/csv       # 指定主板清单
  python3 gen_fish_pool.py --force         # 强制重算
"""
import os, sys, time, csv, json
from datetime import datetime
from urllib.request import Request, urlopen

KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com"}
TOP_N = 300
RECENT = 20
CORE = [("sh603669", "灵康药业"), ("sh600400", "红豆股份"), ("sz002520", "日发精机")]


def get_json(url, retries=3):
    for i in range(retries):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.0 * (i + 1))


def est_daily_amount(code):
    """返回 近RECENT日 日均估算成交额(元)。无数据返回 0.0。"""
    url = f"{KLINE}?param={code},day,,,{RECENT},qfq"
    try:
        d = get_json(url)
        node = d.get("data", {}).get(code, {})
        kl = node.get("qfqday") or node.get("day") or []
        tot, n = 0.0, 0
        for k in kl:
            if len(k) < 6:
                continue
            o, c, h, l, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
            avg = (o + h + l + c) / 4.0
            tot += v * 100 * avg        # 手→股 × 均价 = 元
            n += 1
        if n == 0:
            return 0.0
        return tot / n
    except Exception:
        return 0.0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    csv_path = args[0] if args else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "all_mainboard.csv")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_pool.txt")

    if not os.path.exists(csv_path):
        print(f"[ERR] 找不到 {csv_path}，请先运行 gen_mainboard.py", file=sys.stderr)
        sys.exit(1)

    print("[1/3] 读取主板清单 ...")
    codes = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            c = row.get("code", "").strip()
            if len(c) == 6 and c.isdigit():
                codes.append(("sh" if c[0] == "6" else "sz") + c)
    print(f"      主板 {len(codes)} 只")

    print(f"[2/3] 估算近{RECENT}日日均成交额 ...")
    scored = []
    for i, code in enumerate(codes, 1):
        amt = est_daily_amount(code)
        scored.append((amt, code))
        if i % 500 == 0:
            print(f"      进度 {i}/{len(codes)}")
        time.sleep(0.02)
    scored.sort(reverse=True)
    top = scored[:TOP_N]
    core_codes = {c for c, _ in CORE}

    print(f"[3/3] 生成 stock_pool.txt（{TOP_N}只 + 核心{len(CORE)}只）")
    lines = []
    lines.append("# 🐟 鱼身交易系统 · 动态股票池（自动生成）")
    lines.append(f"# 生成: {datetime.now():%Y-%m-%d %H:%M}")
    lines.append(f"# 规则: 近{RECENT}日日均成交额(估算)排名前{TOP_N}只沪深主板（源自 all_mainboard.csv）")
    lines.append("# 由 gen_fish_pool.py 自动刷新，勿手工编辑")
    lines.append("")
    lines.append("# === 核心关注（强制纳入） ===")
    for code, name in CORE:
        lines.append(f"{code}  # {name}")
    lines.append("")
    lines.append(f"# === 动态排名前 {TOP_N} 只（近{RECENT}日日均成交额估算，亿元） ===")
    for amt, code in top:
        if code in core_codes:
            continue
        lines.append(f"{code}  # {amt/1e8:.1f}亿")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    final = len([l for l in lines if l and not l.startswith("#")])
    print(f"[OK] 共 {final} 只 -> {out}")


if __name__ == "__main__":
    main()
