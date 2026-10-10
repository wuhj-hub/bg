#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pool_winrate_biweekly.py —— 股池胜率「双周报」（2026-10-10）

口径：读 outputs/pool_entries.csv（pool_snapshot.py 每日累积，entry_date=首次入池日），
      对每个 (池, 标的) 计算**自入池日起**的 5/10/20/60 交易日收益 → 严格 OOS（非前视），
      按池聚合出「胜率 / 均值 / 样本数」，并单列 2026-10-10 新增的跟踪池。
      （注意：pool_quality.py 用的是「池当前标的回头算」，带选样偏差，不是业绩；
        本脚本按 entry_date 往后看，才是可外推的样本外口径。）

触发：由 .github/workflows/pool_winrate_biweekly.yml 每两周调用（脚本内做 ISO 周双周判断）。

用法：
  python3 pool_winrate_biweekly.py [--force] [--push] [--out PATH]
    --force  忽略双周判断，强制生成（手动补跑用）
    --push   PushPlus 推送摘要（env PUSH_TOKEN）
"""
import os, re, csv, json, argparse, subprocess, shutil, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))
ENTRY = "outputs/pool_entries.csv"
HOLDS = [5, 10, 20, 60]
# 2026-10-10 起新纳入跟踪的池（与 pool_snapshot.py / paper_tracker.py 的 EXTRA_POOLS 对应）
NEW_POOLS = {"四维共振", "信号仲裁", "乖离低买", "RSV强度", "123ABC"}
# ⭐免 npx：装了全局包直调（~0.7s/次），未装回退 npx（零风险）
WESTOCK = ([shutil.which("westock-data-skillhub")] if shutil.which("westock-data-skillhub")
           else ["npx", "-y", "westock-data-skillhub@1.0.3"])


def run(args, timeout=300):
    try:
        return subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout).stdout or ""
    except Exception:
        return ""


def parse_batch(txt):
    """批量K线 → {code: [(date, close)]} 升序"""
    out, hdr = {}, None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        p = [x.strip() for x in s.strip("|").split("|")]
        if "date" in p:
            hdr = p
            continue
        if not hdr or "---" in p[0]:
            continue
        try:
            di, ci = hdr.index("date"), hdr.index("last")
            if re.match(r"^(sh|sz)\d{6}$", p[0]) and re.match(r"^\d{4}-\d{2}-\d{2}$", p[di]):
                out.setdefault(p[0], []).append((p[di], float(p[ci])))
        except (ValueError, IndexError):
            pass
    for c in out:
        out[c].sort()
    return out


def trading_ret(bars, entry_date, h):
    """自 entry_date（或之后首个交易日）起 h 个交易日收益%（不足则 None）"""
    if not bars:
        return None
    idx = next((i for i, x in enumerate(bars) if x[0] >= entry_date), None)
    if idx is None or idx + h >= len(bars):
        return None
    c0, c1 = bars[idx][1], bars[idx + h][1]
    return (c1 / c0 - 1) * 100 if c0 > 0 else None


def agg_pool(vals):
    """→ (胜率%, 均值%, n) 或 None"""
    if not vals:
        return None
    win = sum(1 for x in vals if x > 0) / len(vals) * 100
    return round(win, 1), round(sum(vals) / len(vals), 2), len(vals)


def cell(res):
    if not res:
        return "—"
    win, avg, n = res
    return f"{win:.0f}% / {avg:+.2f}% (n={n})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略双周判断，强制生成")
    ap.add_argument("--push", action="store_true", help="PushPlus 推送摘要")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    now = datetime.now(BJ)
    wk = now.isocalendar()[1]
    if not a.force and wk % 2 != 0:
        print(f"[SKIP] ISO 第 {wk} 周（奇数周），非双周报告周；加 --force 可强制生成")
        return

    if not os.path.exists(ENTRY):
        print(f"[ERR] 缺 {ENTRY}（pool_snapshot.py 是否已跑？）")
        return
    rows = [r for r in csv.DictReader(open(ENTRY, encoding="utf-8")) if r.get("code") and r.get("entry_date")]
    if not rows:
        print("[ERR] pool_entries.csv 为空")
        return
    codes = sorted({r["code"] for r in rows})
    print(f"[INFO] {len(rows)} 条 / {len(codes)} 只，开始取日线", flush=True)

    kline = {}
    for i in range(0, len(codes), 250):
        kline.update(parse_batch(run(["kline", ",".join(codes[i:i + 250]), "--period", "day", "--limit", "250"])))
    print(f"[INFO] 取到 K 线 {len(kline)}/{len(codes)} 只", flush=True)

    # 基准：全池标的同时段等权（{h: (win,avg,n)}）
    base = {}
    for h in HOLDS:
        base[h] = agg_pool([v for r in rows
                            if (v := trading_ret(kline.get(r["code"]), r["entry_date"], h)) is not None])

    # 按池聚合
    agg = {}
    for r in rows:
        p, c, ed = r["pool"], r["code"], r["entry_date"]
        for h in HOLDS:
            v = trading_ret(kline.get(c), ed, h)
            if v is not None:
                agg.setdefault(p, {}).setdefault(h, []).append(v)

    date_str = now.strftime("%Y-%m-%d")
    out_path = a.out or f"outputs/股池胜率双周报_{date_str}.md"
    HDR = "| 池 | 5日 胜率/均值 | 10日 | 20日 | 60日 |"
    SEP = "|---|---|---|---|---|"

    L = [f"# 📊 股池胜率双周报 · {date_str}", "",
         "> **口径**：自 **入池日（entry_date）起** 的 5/10/20/60 **交易日**收益（严格 OOS，非前视）",
         f"> **样本**：`pool_entries.csv` {len(rows)} 条 / {len(codes)} 只 · 基准 = 全池标的同时段等权",
         f"> **周期**：双周（ISO 第 {wk} 周）· 生成 {now.strftime('%Y-%m-%d %H:%M')} 北京", ""]

    L += ["## 一、全部跟踪池（按 20日样本量排序）", "", HDR, SEP]
    order = sorted(agg, key=lambda p: -len(agg[p].get(20, next(iter(agg[p].values()), []))))
    for p in order:
        L.append(f"| {p} | " + " | ".join(cell(agg_pool(agg[p].get(h, []))) for h in HOLDS) + " |")
    L += ["", "**基准（全池同时段等权）**", "", HDR, SEP,
          "| 大盘代理 | " + " | ".join(cell(base[h]) for h in HOLDS) + " |", ""]

    L += ["## 二、🆕 2026-10-10 新增跟踪池", "", HDR, SEP]
    newp = sorted(p for p in agg if p in NEW_POOLS)
    if newp:
        for p in newp:
            L.append(f"| {p} | " + " | ".join(cell(agg_pool(agg[p].get(h, []))) for h in HOLDS) + " |")
    else:
        L.append("| （样本积累中） | — | — | — | — |")
    L += ["", "> 新池自 2026-10-10 盘后开始累积 entry_date；20/60 日列需样本持有满相应交易日才有值。", "",
          f"> 与「前视口径」的区别：pool_quality.py 取池当前标的回头算（有选样偏差）仅供参考；本表按入池日往后看，可外推。", ""]

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    open(out_path, "w", encoding="utf-8").write("\n".join(L))
    print(f"[OK] {out_path}")

    if a.push:
        tok = os.environ.get("PUSH_TOKEN")
        if tok:
            body = "\n".join(L[:50])
            data = urllib.parse.urlencode({"token": tok, "title": f"📊 股池胜率双周报 {date_str}",
                                           "content": body, "template": "markdown"}).encode()
            try:
                urllib.request.urlopen("https://pushplus.plus/send", data=data, timeout=20)
                print("[PUSH] ok")
            except Exception as e:
                print(f"[PUSH] fail: {e}")


if __name__ == "__main__":
    main()
