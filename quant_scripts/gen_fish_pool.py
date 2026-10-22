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
  4. 强制纳入核心关注2只（红豆/日发精机）
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
TOP_N = 300  # 2026-08-11 恢复：鱼身并发4workers已修复超时，扩回300提升覆盖（代表性优化B）
RECENT = 20
CORE = [("sh600400", "红豆股份"), ("sz002520", "日发精机")]


def get_json(url, retries=3):
    for i in range(retries):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.0 * (i + 1))


def _calc_amount(node):
    """从K线节点计算近RECENT日日均成交额(元)，无数据返回 0.0（本地回退实现）"""
    kl = node.get("qfqday") or node.get("day") or []
    tot, n = 0.0, 0
    for k in kl:
        if len(k) < 6:
            continue
        o, c, h, l, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
        avg = (o + h + l + c) / 4.0
        tot += v * 100 * avg        # 手→股 × 均价 = 元
        n += 1
    return tot / n if n else 0.0


def _calc_amount_bars(bars):
    """bar 列表 → 日均成交额(元)。

    2026-10-22：优先用真实 amount（westock 批量 kline 自带，元）；缺失时回退
    volume(手)×100×均价 估算（旧口径，腾讯 fqkline 无 amount 列时走这里）。
    """
    tot, n = 0.0, 0
    for b in bars or []:
        a = b.get("amount")
        if not a:
            v = b.get("volume")
            if v is None:
                continue
            avg = (b["open"] + b["high"] + b["low"] + b["close"]) / 4.0
            a = v * 100 * avg
        tot += a
        n += 1
    return tot / n if n else 0.0


def _fetch_layer(codes):
    """统一取数层：westock 批量 kline（100/批 + 批间退避）优先，整体失败回落腾讯逐只(并发6)。

    2026-10-22 修复（两次实测数据支撑）：
      ① 旧实现 ext_fqkline(workers=1) 逐只串行取全市场 3100 只 → 耗时 23~87min 且抖动，
         曾使 quant_scan 尾部拖长、duowei「动态生成鱼身股票池」跑到 86.8min 被取消；
      ② 批量也不能开 250/批：实测同一时段 `[Batch] 状态: success | 总数: 250 | 成功: 10 | 失败: 240`，
         即服务端在 250 只时大面积限流（覆盖仅 4%~50%），100/批才稳定（覆盖 95%）；
      ③ 缺失的 ~8% 多为退市/长期停牌（all_mainboard.csv 固有），本就无成交额、不该入池，
         故不再逐只回补（旧代码回补 1556 只 → 被腾讯重试退避拖 30min+）。
    """
    import sys as _sys
    _d = os.path.dirname(os.path.abspath(__file__))      # quant_scripts
    if _d not in _sys.path:
        _sys.path.insert(0, _d)
    from fetch import kline as _k, ext_fqkline as _f
    BATCH = 100
    got = {}
    for s in range(0, len(codes), BATCH):
        part = codes[s:s + BATCH]
        r = {}
        for attempt in range(2):
            try:
                r = {c: b for c, b in _k(part, period="day", limit=RECENT + 5, fq="qfq").items() if b}
            except Exception as e:
                print(f"      [WARN] 批量 kline 第 {s // BATCH + 1} 块异常：{e}", file=sys.stderr)
            if len(r) >= 0.6 * len(part) or attempt:
                break
            time.sleep(8)      # 疑似限流 → 退避后重试本块一次
        got.update(r)
        time.sleep(0.4)
    if len(got) < 0.5 * max(1, len(codes)):
        print(f"      [WARN] 批量覆盖仅 {len(got)}/{len(codes)}，回落腾讯逐只（并发6）", file=sys.stderr)
        try:
            got.update(_f([c for c in codes if c not in got], count=RECENT, workers=6))
        except Exception as e:
            print(f"      [WARN] 腾讯补取失败：{e}", file=sys.stderr)
    return got


def _fill_by_quote(codes):
    """行情兜底：用当日成交额（qt.gtimg 字段 amount，万元 → 元）近似补全缺失标的。

    仅用于「20 日批量取数失败且非退市」的少量标的（CI 上前面步骤已拉过全市场 K 线，
    缓存命中后缺失通常极少）。当日成交额与 20 日均值同量级，用于排名边界判断足够。
    """
    import sys as _sys
    _d = os.path.dirname(os.path.abspath(__file__))
    if _d not in _sys.path:
        _sys.path.insert(0, _d)
    try:
        from fetch import ext_gtimg as _g
        recs = _g(codes, batch=50)
    except Exception as e:
        print(f"      [WARN] 行情兜底失败：{e}", file=sys.stderr)
        return {}
    out = {}
    for c, r in (recs or {}).items():
        a = r.get("amount")          # 万元
        if a and a > 0:
            out[c] = float(a) * 1e4
    return out


def _est_daily_amount_local(code):
    url = f"{KLINE}?param={code},day,,,{RECENT},qfq"
    try:
        d = get_json(url)
        return _calc_amount(d.get("data", {}).get(code, {}))
    except Exception:
        return 0.0


def est_daily_amount(code):
    """单只 近RECENT日 日均成交额(元)。无数据返回 0.0。"""
    try:
        got = _fetch_layer([code])
        if got.get(code):
            return _calc_amount_bars(got[code])
    except Exception:
        pass
    return _est_daily_amount_local(code)


def est_batch(codes):
    """批量估算 近RECENT日日均成交额 → {code: 元}；退市/无行情返回 0。"""
    got = {}
    try:
        got = _fetch_layer(codes)
    except Exception as e:
        print(f"      [WARN] 取数失败：{e}", file=sys.stderr)
    scored = {c: _calc_amount_bars(got.get(c, [])) for c in codes}
    miss = [c for c in codes if not scored.get(c)]
    if miss:
        fill = _fill_by_quote(miss)
        if fill:
            scored.update({c: v for c, v in fill.items() if c in scored})
            print(f"      行情兜底补全 {len(fill)}/{len(miss)} 只（按当日成交额近似）")
    return scored


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

    print(f"[2/3] 估算近{RECENT}日日均成交额（westock 批量 kline 250/批 + 腾讯逐只兜底）...")
    t0 = time.time()
    scored = est_batch(codes) or {}
    valid = [c for c in codes if scored.get(c)]
    print(f"      有效 {len(valid)}/{len(codes)} 只（缺失为退市/停牌，无成交额不入池），耗时 {time.time() - t0:.1f}s")
    scored = sorted(((amt, c) for c, amt in scored.items() if amt > 0), reverse=True)
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
