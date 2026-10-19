#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regime_history.py —— 行情类型历史序列（曾星智《悟道01》三类短线行情 · 指数口径）v1（2026-10-20）

背景：limitup_concept_rank.py v4.6 每日输出「🧭 行情类型」（指数三力 + 广度 + 涨停结构 + 行业集中度），
      但广度/涨停结构无历史 → 无法给历史信号样本分组。
本脚本：只用 **上证指数日线**（可完整回溯 800 根 ≈ 3 年）回算每日行情类型，形成可 join 的历史序列，
      供「股池 / 信号源 OOS 按行情类型分层」使用（pool_winrate_biweekly.py 第四节）。

判定口径（指数口径，与实盘口径的差异见报告注）：
  三力 = 长期 MA250（不足 260 根退 MA120，再退 MA60）/ 中期 MA60 / 短期 MA20 的方向
         方向 = 今日均线 vs 近 look 根前的均线（长期 look=20 / 中期 10 / 短期 5）
  第1类 大盘普涨：三力全上 + 收盘站上年线 + 收盘站上 MA60
  第3类 概念炒作：三力≤1 向上 + 收盘跌破 MA60
  第2类 行业级  ：其余（震荡/结构分化）
  注：实盘口径（v4.6）另加「全市场上涨家数占比 + 涨停结构 + 行业集中度」，历史口径无广度，故更粗。

起点：仅在年线（MA250）可用后输出（约近 2 年），保证全序列口径一致。
幂等：同一天重复运行结果一致（只依赖该日及之前的数据），可直接每日重建。

用法：
  python3 quant_scripts/regime_history.py [--sym sh000001] [--count 800]
         [--out data/regime_history.csv] [--quiet]
"""
import os, sys, csv, argparse
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DEFAULT = os.path.join(BASE, "data/regime_history.csv")

REGIME_LABEL = {1: "第1类·大盘普涨(牛市)",
                2: "第2类·行业级(震荡市)",
                3: "第3类·概念炒作(熊市/弱震荡)"}


def fetch_index_bars(sym="sh000001", count=800):
    """指数日线（腾讯长历史优先，回退 fetch.kline）→ [bar,...] 升序（dict: date/open/close/high/low）。"""
    try:
        _d = os.path.dirname(os.path.abspath(__file__))
        for _c in (_d, BASE):
            if _c not in sys.path:
                sys.path.insert(0, _c)
        from fetch import ext_fqkline as _ef
        d = _ef([sym], period="day", count=count) or {}
        bars = d.get(sym) or []
        if len(bars) >= 260:
            return bars
    except Exception:
        bars = []
    try:
        from fetch import kline as _fk
        d = _fk([sym], period="day", limit=250, fq=None) or {}
        b2 = d.get(sym) or []
        if len(b2) > len(bars):
            bars = b2
    except Exception:
        pass
    return bars


def _ma(closes, i, n, off=0):
    end = i + 1 - off
    if n <= 0 or end - n < 0:
        return None
    return sum(closes[end - n:end]) / n


def judge_at(closes, i):
    """第 i 根上的行情类型（指数口径）。数据不足返回 None。"""
    long_n = 250 if i + 1 >= 260 else (120 if i + 1 >= 130 else 60)
    ma_long = _ma(closes, i, long_n)
    ma60 = _ma(closes, i, 60)
    ma20 = _ma(closes, i, 20)
    if ma_long is None or ma60 is None or ma20 is None:
        return None

    def up(n, look):
        a, b = _ma(closes, i, n), _ma(closes, i, n, look)
        return None if (a is None or b is None) else (a > b)

    lu, mu, su = up(long_n, 20), up(60, 10), up(20, 5)
    if lu is None or mu is None or su is None:
        return None
    c = closes[i]
    above_long = c > ma_long
    above_mid = c > ma60
    n_up = int(lu) + int(mu) + int(su)
    if n_up == 3 and above_long and above_mid:
        t = 1
    elif n_up <= 1 and not above_mid:
        t = 3
    else:
        t = 2
    return {"regime": t, "label": REGIME_LABEL[t], "close": round(c, 2),
            "long_n": long_n, "ma_long": round(ma_long, 2), "ma60": round(ma60, 2),
            "ma20": round(ma20, 2), "n_up": n_up,
            "above_long": int(above_long), "above_mid": int(above_mid),
            "gap_long_pct": round((c / ma_long - 1) * 100, 2)}


def build(bars):
    """→ [{date, ...judge_at 字段}] 升序"""
    closes = [b["close"] if isinstance(b, dict) else b[2] for b in bars]
    dates = [b["date"] if isinstance(b, dict) else b[0] for b in bars]
    rows = []
    for i in range(len(closes)):
        r = judge_at(closes, i)
        if r and r.get("long_n") == 250:      # 只在满 250 根年线后输出 → 全序列口径一致
            r = dict(r)
            r["date"] = dates[i]
            rows.append(r)
    return rows


def write_csv(rows, path):
    cols = ["date", "regime", "label", "close", "long_n", "ma_long", "ma60", "ma20",
            "n_up", "above_long", "above_mid", "gap_long_pct"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in cols})


def load_map(path=None):
    """→ {date: regime}（供其它脚本 join；缺失返回 {}）"""
    path = path or OUT_DEFAULT
    if not os.path.exists(path):
        return {}
    out = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    out[r["date"]] = int(r["regime"])
                except (KeyError, ValueError):
                    continue
    except Exception:
        return {}
    return out


def ensure(path=None, count=800, max_stale_days=3):
    """保证历史序列存在且不过期 → {date: regime}。重建失败时保留旧文件（不阻塞调用方）。"""
    path = path or OUT_DEFAULT
    mp = load_map(path)
    need = True
    if mp:
        try:
            last = datetime.strptime(max(mp), "%Y-%m-%d")
            need = (datetime.now(BJ).replace(tzinfo=None) - last).days > max_stale_days
        except ValueError:
            need = True
    if need:
        try:
            rows = build(fetch_index_bars(count=count))
            if rows:
                write_csv(rows, path)
                mp = {r["date"]: r["regime"] for r in rows}
                print(f"[INFO] regime_history 重建 {len(rows)} 日（{rows[0]['date']} ~ {rows[-1]['date']}）", flush=True)
        except Exception as e:
            print(f"[WARN] regime_history 重建失败（沿用现有 {len(mp)} 日）: {e}", flush=True)
    return mp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="sh000001")
    ap.add_argument("--count", type=int, default=800)
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    bars = fetch_index_bars(a.sym, a.count)
    if not bars:
        print("[ERR] 指数数据获取失败")
        return 1
    rows = build(bars)
    if not rows:
        print("[ERR] 数据不足以计算（需 ≥70 根）")
        return 1
    write_csv(rows, a.out)
    if not a.quiet:
        import collections
        cnt = collections.Counter(r["regime"] for r in rows)
        last250 = rows[-250:]
        c250 = collections.Counter(r["regime"] for r in last250)
        print(f"[OK] {len(rows)} 个交易日（{rows[0]['date']} ~ {rows[-1]['date']}）→ {a.out}")
        print("     全期分布：" + "｜".join(f"{REGIME_LABEL[k]} {cnt[k]}日" for k in (1, 2, 3)))
        print(f"     近250日：" + "｜".join(f"{REGIME_LABEL[k]} {c250[k]}日" for k in (1, 2, 3)))
        print(f"     最新 {rows[-1]['date']}：{rows[-1]['label']}"
              f"（三力向上 {rows[-1]['n_up']}/3，距年线 {rows[-1]['gap_long_pct']:+.1f}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
