#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cross_source_check.py —— 数据源交叉验证（2026-09-30 冗余版）
============================================================
补的缺口：体系原有 data_guard --probe 只验「能不能拉到」（连通性），
         从不验「拉到的是不是对的」（数值真实性）。

本脚本用【多个相互独立的源】对拍关键标的的收盘价与涨跌幅：
  A 主源   : westock（npx westock-data-skillhub，腾讯数据）—— 基准
  B 必需源 : 新浪 hq.sinajs（完全不同的数据体系）—— 2026-09-30 由东财迁移而来
  C 必需源 : 腾讯 qt.gtimg.cn（同体系不同接口，用于三方定位）
  D 机会源 : 东财 push2delay（可选）—— 在线则自动纳入四源对拍；离线则静默跳过，不影响判定

冗余设计：东财 push2/push2delay 主机 2026-09-29 起抖动（CI 与沙箱均取不到），
         故降级为「机会源」。任一必需源波动也不会连锁误报；东财恢复后校验自动更严。

判定：以 A 源为基准，对每个在线对照源，|价差| > THRESHOLD% 或 涨跌幅差 > PCT_THRESHOLD
     → 告警（exit 1）。必需源（A/B/C）缺失亦告警；机会源 D 离线不告警。

用法:
  python3 cross_source_check.py                      # 内置标的池（指数+持仓+基准）
  python3 cross_source_check.py --extra sh600000     # 追加标的
  python3 cross_source_check.py --no-opportunistic   # 禁用机会源（只用 A/B/C）
  python3 cross_source_check.py --out outputs
  python3 cross_source_check.py --json outputs/cross_source_latest.json
"""
import argparse, json, os, re, subprocess, sys, urllib.request
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
THRESHOLD = 0.5       # 收盘价差异阈值 %
PCT_THRESHOLD = 0.5   # 涨跌幅差异阈值 pct
SINA_API = "https://hq.sinajs.cn/list={codes}"
TX_API = "https://qt.gtimg.cn/q={codes}"
EM_API = "https://push2delay.eastmoney.com/api/qt/stock/get?secid={sid}&fields=f43,f57,f58,f59,f60,f170"

# 内置标的池：指数（大盘基准）+ 持仓股 + 高流动性基准票
DEFAULT_POOL = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh600519", "贵州茅台"),
    ("sz000001", "平安银行"),
    ("sh601318", "中国平安"),
    ("sh600797", "浙大网新"),
    ("sz000839", "国安股份"),
    ("sh600863", "华能蒙电"),
]


def _get(url, timeout=20, encoding=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return raw.decode(encoding or "utf-8", "ignore")


# ─────────── 源 A：westock ───────────
def westock_close(code):
    """返回 (date, close, pct) —— 涨跌幅需两次取数，用 limit=2 自算"""
    try:
        r = subprocess.run(WESTOCK + ["kline", code, "--period", "day", "--limit", "2"],
                           capture_output=True, text=True, timeout=120)
        rows = []
        for ln in r.stdout.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            if len(parts) < 6 or parts[0] == "date" or "---" in parts[0]:
                continue
            rows.append(parts)
        if len(rows) < 2:
            return None
        # 单股列序: date|open|last|high|low|volume|amount|exchange  → last 在 index 2
        d, c = rows[0][0], float(rows[0][2])
        c_prev = float(rows[1][2])
        pct = (c - c_prev) / c_prev * 100 if c_prev else None
        return (d, c, round(pct, 2) if pct is not None else None)
    except Exception:
        return None


# ─────────── 源 B（必需）：新浪 hq.sinajs ───────────
def sina_quote(codes):
    """批量 → {code: {name, close, pct}}。
    2026-09-30 由东财 push2delay 迁移至此：东财 push2/push2delay 主机自 09-29 起不可用；
    新浪为完全独立的行情体系，实测上证 3830.4513 / 茅台 1235.58 与 westock 一致。"""
    out = {}
    try:
        req = urllib.request.Request(SINA_API.format(codes=",".join(codes)),
                                     headers={"User-Agent": "Mozilla/5.0",
                                              "Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=20).read().decode("gbk", "ignore")
        for ln in raw.splitlines():
            m = re.match(r'var hq_str_(\w+)="([^"]*)"', ln.strip())
            if not m:
                continue
            f = m.group(2).split(",")
            if len(f) < 4:
                continue
            try:
                close = float(f[3]); prev = float(f[2])
                pct = (close - prev) / prev * 100 if prev else None
                out[m.group(1)] = {"name": f[0], "close": round(close, 3),
                                   "pct": round(pct, 2) if pct is not None else None}
            except Exception:
                pass
    except Exception:
        pass
    return out


# ─────────── 源 C（必需）：腾讯 qt.gtimg ───────────
def tx_quote(codes):
    """批量：返回 {code: {name, close, pct}}"""
    out = {}
    try:
        txt = _get(TX_API.format(codes=",".join(codes)), encoding="gbk")
        for ln in txt.splitlines():
            m = re.match(r'v_(\w+)="([^"]*)"', ln.strip())
            if not m:
                continue
            f = m.group(2).split("~")
            if len(f) < 33:
                continue
            try:
                out[m.group(1)] = {"name": f[1], "close": float(f[3]), "pct": float(f[32])}
            except Exception:
                pass
    except Exception:
        pass
    return out


# ─────────── 源 D（机会源）：东财 push2delay ───────────
def _em_secid(code):
    if code.startswith("sh"):
        return "1." + code[2:]
    if code.startswith("sz"):
        return "0." + code[2:]
    return None


def _em_one(code):
    sid = _em_secid(code)
    if not sid:
        return None
    try:
        j = json.loads(_get(EM_API.format(sid=sid), timeout=8))
        d = (j or {}).get("data") or {}
        if not d or d.get("f43") in (None, "-", 0):
            return None
        dec = int(d.get("f59") or 2)
        close = float(d["f43"]) / (10 ** dec)
        pct = float(d["f170"]) / 100 if d.get("f170") not in (None, "-") else None
        return {"name": d.get("f58"), "close": round(close, 3),
                "pct": round(pct, 2) if pct is not None else None}
    except Exception:
        return None


def em_quote(codes, enabled=True):
    """机会源：逐只取东财。先探活第一只，不通即判整源离线（返回 {}），避免逐只超时拖慢。"""
    if not enabled or not codes:
        return {}
    if _em_one(codes[0]) is None:
        return {}
    out = {}
    for code in codes:
        q = _em_one(code)
        if q:
            out[code] = q
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", nargs="*", default=[], help="追加标的（sh/sz+6位）")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--json", default=None)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--no-opportunistic", action="store_true", help="禁用机会源（东财）")
    a = ap.parse_args()

    pool = list(DEFAULT_POOL) + [(c, "") for c in a.extra]
    codes = [c for c, _ in pool]
    date = datetime.now().strftime("%Y-%m-%d")

    print(f"[INFO] 交叉验证 {len(codes)} 只标的（westock × 新浪 × 腾讯[ × 东财]）", flush=True)

    tx = tx_quote(codes)
    sn = sina_quote(codes)
    em = em_quote(codes, enabled=not a.no_opportunistic)
    em_on = bool(em)
    print(f"[INFO] 腾讯源取到 {len(tx)}/{len(codes)}", flush=True)
    print(f"[INFO] 新浪源取到 {len(sn)}/{len(codes)}", flush=True)
    if a.no_opportunistic:
        print("[INFO] 东财机会源：已禁用", flush=True)
    elif em_on:
        print(f"[INFO] 东财机会源：在线 {len(em)}/{len(codes)}（已纳入四源对拍）", flush=True)
    else:
        print("[INFO] 东财机会源：离线（跳过，不影响判定）", flush=True)

    results, alerts = [], []
    for code, name in pool:
        w = westock_close(code)
        e = sn.get(code)
        t = tx.get(code)
        m = em.get(code) if em_on else None
        nm = (e or {}).get("name") or (t or {}).get("name") or (m or {}).get("name") or name or code

        cands = [("新浪", e), ("腾讯", t)]
        if em_on:
            cands.append(("东财", m))

        maxdiff = maxpdiff = None
        bad = []
        for src, c in cands:
            if not (w and c and w[1]):
                continue
            d = abs(w[1] - c["close"]) / w[1] * 100
            maxdiff = d if maxdiff is None else max(maxdiff, d)
            if d > a.threshold:
                bad.append(f"{src}价差 {d:.2f}%（westock {w[1]} vs {src} {c['close']}）")
            if w[2] is not None and c.get("pct") is not None:
                pd = abs(w[2] - c["pct"])
                maxpdiff = pd if maxpdiff is None else max(maxpdiff, pd)
                if pd > PCT_THRESHOLD:
                    bad.append(f"{src}涨跌幅差 {pd:.2f}pct（westock {w[2]}% vs {src} {c['pct']}%）")

        row = {
            "code": code, "name": nm,
            "westock": {"date": w[0], "close": w[1], "pct": w[2]} if w else None,
            "sina": e, "tx": t, "em": m,
            "price_diff_pct": round(maxdiff, 3) if maxdiff is not None else None,
            "pct_diff": round(maxpdiff, 2) if maxpdiff is not None else None,
        }
        results.append(row)

        missing = [s for s, v in [("westock", w), ("新浪", e), ("腾讯", t)] if v is None]
        if missing:
            alerts.append(f"{nm}({code}) 必需源缺失：{','.join(missing)}")
        for x in bad:
            alerts.append(f"{nm}({code}) {x}")

    # ───── 报告 ─────
    ok = len(results) - len(alerts)
    cont = "新浪 hq.sinajs × 腾讯 qt.gtimg" + (" × 东财 push2delay" if em_on else "（东财 push2delay 离线·跳过）")
    L = [f"# 🔀 数据源交叉验证 · {date}", "",
         f"> 主源 westock ｜ 对照 {cont} ｜ 标的 {len(results)} 只 ｜ ✅一致 **{ok}** ｜ ⚠️异常 **{len(alerts)}**", ""]
    if alerts:
        L += ["## ⚠️ 数据源不一致（需人工核实）", ""] + [f"- {x}" for x in alerts] + [""]
    else:
        L += ["## ✅ 各源一致，数据源可信", ""]

    src_cols = ["新浪收盘", "腾讯收盘"] + (["东财收盘"] if em_on else [])
    L.append("| 标的 | 代码 | westock收盘 | " + " | ".join(src_cols) + " | 价差 | 涨跌幅差 |")
    L.append("|---" * (5 + len(src_cols)) + "|")
    for r in results:
        w = r["westock"]
        cells = [r["name"], r["code"], str(w["close"]) if w else "❌"]
        cells.append(str(r["sina"]["close"]) if r["sina"] else "❌")
        cells.append(str(r["tx"]["close"]) if r["tx"] else "—")
        if em_on:
            cells.append(str(r["em"]["close"]) if r["em"] else "—")
        cells.append(f"{r['price_diff_pct']}%" if r["price_diff_pct"] is not None else "—")
        cells.append(f"{r['pct_diff']}" if r["pct_diff"] is not None else "—")
        L.append("| " + " | ".join(cells) + " |")
    L.append("")
    md = "\n".join(L)

    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, f"数据源交叉验证_{date}.md"), "w", encoding="utf-8").write(md)
    jp = a.json or os.path.join(a.out, "cross_source_latest.json")
    os.makedirs(os.path.dirname(jp) or ".", exist_ok=True)
    json.dump({"date": date, "threshold": a.threshold, "total": len(results),
               "ok": ok, "alerts": alerts, "em_online": em_on, "results": results},
              open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(md[-1500:], flush=True)
    print(f"[OK] {jp}", flush=True)
    sys.exit(1 if alerts else 0)


if __name__ == "__main__":
    main()
