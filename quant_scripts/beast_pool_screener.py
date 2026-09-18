#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""beast_pool_screener.py —— 猛兽「突破池」扫描器 + 分批减仓操作单

来源：猛兽派选股《巧用动量指标选股·总纲》（2026-01-13）
回测依据：bt_beast_timing.py（2026-09-18，1615 信号）
  T0+E6 方案：平均 +2.90% / 中位 +10.01% / 胜率 65% / 持有约 32 天
  年度：中位数为正 6/9 年；2024 由 −2.86% 转为 +0.86%

【突破池公式（原文照录）】
  RSV>74 AND RSV1>85 AND RSVHY>74
  AND LLV(REF(ABS(PV2),1),2)<6      {前置PV 小}
  AND PV3>12                        {现在PV 大}

【分批减仓（E6 方案）】
  +10% 减 1/3  →  +20% 再减 1/3  →  从最高点回撤 5% 清剩余

用法：
  python3 beast_pool_screener.py --scan              # 扫描当日突破池
  python3 beast_pool_screener.py --scan --push       # 扫描 + 推送
"""
import csv, json, os, re, sys, time, subprocess, argparse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import numpy as np

BJT = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "outputs")
if os.path.basename(BASE) == "quant_scripts":
    OUT = os.path.join(os.path.dirname(BASE), "outputs")
UA = {"User-Agent": "Mozilla/5.0"}

# ---------- 参数（照原文） ----------
N1 = 144          # RSV 周期
PV_N1, PV_N2, PV_M = 2, 4, 15      # OVS 参数
GS1, GS2 = 1.10, 1.20              # 减仓档位 +10% / +20%
TRAIL = 0.05                       # 峰值回撤 5% 清仓


def log(m):
    print(f"[{datetime.now(BJT).strftime('%H:%M:%S')}] {m}", flush=True)


def http_json(url, tries=3, timeout=40):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(1.2 * (i + 1))
    return {}


def fetch_industry_map():
    """拉全市场股票→行业映射（东财 f100）"""
    out = {}
    pn = 1
    while pn <= 60:
        u = ("https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=100&po=1&np=1&fltt=2&invt=2"
             "&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f100" % pn)
        d = http_json(u)
        data = d.get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            break
        for x in diff:
            if x.get("f12") and x.get("f100"):
                out[x["f12"]] = x["f100"]
        total = data.get("total") or 0
        if total and len(out) >= total:
            break
        pn += 1
    return out


def westock_kline(codes, limit=200, chunk=40, period="day"):
    """批量拉日线 → {code: [(date,o,h,l,c,v), ...] 日期升序}"""
    res = {}
    for k in range(0, len(codes), chunk):
        batch = codes[k:k + chunk]
        cmd = ["npx", "-y", "westock-data-skillhub@1.0.3", "kline",
               ",".join(batch), "--period", period, "--limit", str(limit)]
        txt = ""
        for attempt in range(2):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                txt = r.stdout or ""
                if txt:
                    break
            except Exception:
                time.sleep(2)
        for line in txt.splitlines():
            s = line.strip()
            if not s.startswith("|"):
                continue
            p = [x.strip() for x in s.strip("|").split("|")]
            if len(p) < 9 or not re.match(r"^(sh|sz)\d{6}$", p[0]):
                continue
            try:
                res.setdefault(p[0], []).append(
                    (p[1], float(p[2]), float(p[4]), float(p[5]), float(p[3]), float(p[6])))
                # 列序 symbol|date|open|last|high|low|volume|amount|exchange
                # 存成 (date, open, high, low, close, volume)
            except (ValueError, TypeError):
                continue
    for c in res:
        res[c].sort(key=lambda x: x[0])
    return res


def calc_rsv(close, high, low, mkt_close):
    """RSV均 = (RSV1 + RSV2)/2，N1=144"""
    n = len(close)
    if n < N1:
        return None, None
    lo = low[-N1:].min(); hi = high[-N1:].max()
    rsv1 = (close[-1] - lo) / (hi - lo) * 100 if hi > lo else 50.0
    lm = mkt_close[-1] if hasattr(mkt_close, "__len__") else mkt_close
    if lm is None or not np.isfinite(lm) or lm <= 0:
        rsv2 = 50.0
    else:
        rs = close / mkt_close
        seg = np.asarray(rs)[-N1:]
        lo2 = seg.min(); hi2 = seg.max()
        rsv2 = (seg[-1] - lo2) / (hi2 - lo2) * 100 if hi2 > lo2 else 50.0
    return (rsv1 + rsv2) / 2, rsv1


def calc_rsvhy(ind_close, ind_high, ind_low, mkt_close):
    """行业 RSVHY（同 RSV 算法，用行业指数）"""
    if ind_close is None or len(ind_close) < N1:
        return None
    lo = ind_low[-N1:].min(); hi = ind_high[-N1:].max()
    v1 = (ind_close[-1] - lo) / (hi - lo) * 100 if hi > lo else 50.0
    lm = mkt_close[-1] if hasattr(mkt_close, "__len__") else mkt_close
    if lm is None or not np.isfinite(lm) or lm <= 0:
        return (v1 + 50.0) / 2
    rshy = np.asarray(ind_close) / np.asarray(mkt_close)
    seg = rshy[-N1:]
    lo2 = seg.min(); hi2 = seg.max()
    v2 = (seg[-1] - lo2) / (hi2 - lo2) * 100 if hi2 > lo2 else 50.0
    return (v1 + v2) / 2


def calc_pv(close, high, low, vol):
    """OVS: PV2 (N1=2) / PV3 (N2=4, M=15)"""
    n = len(close)
    if n < PV_M + PV_N2 + 2:
        return None, None
    zf = np.zeros(n); bsr = np.zeros(n)
    for i in range(1, n):
        hi_ = max(high[i], close[i - 1]); lw_ = min(low[i], close[i - 1])
        zf[i] = (close[i] - close[i - 1]) / close[i - 1] if close[i - 1] else 0
        bsr[i] = abs(close[i] - close[i - 1]) / (hi_ - lw_) if hi_ > lw_ else 0
    pv2 = sum(bsr[j] * zf[j] * vol[j] / (vol[j - PV_N1 + 1:j + 1].mean() or 1)
              for j in range(n - PV_N1, n)) * 100
    pv3 = sum(zf[j] * vol[j] / (vol[j - PV_M + 1:j + 1].min() or 1)
              for j in range(n - PV_N2, n)) * 100
    return pv2, pv3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="限制扫描数量（调试用）")
    a = ap.parse_args()

    # ① 行业映射
    log("拉取行业映射（东财）…")
    ind_map = fetch_industry_map()
    log(f"  行业映射: {len(ind_map)} 只")

    # ② 候选池：全主板（真实运行时从 all_mainboard.csv 读）
    pool_path = None
    for p in (os.path.join(OUT, "..", "all_mainboard.csv"),
              os.path.join(BASE, "all_mainboard.csv"),
              "/sandbox/workspace/all_mainboard.csv"):
        if os.path.exists(p):
            pool_path = p; break
    if pool_path:
        rows = list(csv.DictReader(open(pool_path, encoding="utf-8-sig")))
        codes = [("sh" if r["code"].startswith("60") else "sz") + r["code"] for r in rows]
        log(f"候选池: {len(codes)} 只（{pool_path}）")
    else:
        codes = []
        log("[WARN] 未找到 all_mainboard.csv")

    if a.limit:
        codes = codes[:a.limit]
    if not codes:
        log("[ERR] 无候选股，退出"); return

    # ③ 批量拉日线（需 >= 145 日）
    log(f"批量拉取日线（{len(codes)} 只，limit=200）…")
    bars = westock_kline(codes, limit=200)
    log(f"  取到 {len(bars)} 只")

    # ④ 市场均价（用已取到的股票按日等权）
    ds = defaultdict(float); dc = defaultdict(int)
    for c, bs in bars.items():
        for b in bs:
            ds[b[0]] += b[4]; dc[b[0]] += 1
    mkt = {d: ds[d] / dc[d] for d in ds if dc[d] > 0}

    # ⑤ 行业指数（用已取到股票的行业归属，等价聚合）
    ind_day = defaultdict(lambda: defaultdict(list))
    for c, bs in bars.items():
        ind = ind_map.get(c[2:])
        if not ind:
            continue
        for b in bs:
            ind_day[ind][b[0]].append((b[4], b[2], b[3]))
    ind_series = {}
    for ind, dd in ind_day.items():
        dts = sorted(dd)
        ind_series[ind] = {
            "c": np.array([np.mean([x[0] for x in dd[d]]) for d in dts]),
            "h": np.array([np.max([x[1] for x in dd[d]]) for d in dts]),
            "l": np.array([np.min([x[2] for x in dd[d]]) for d in dts]),
            "idx": {d: i for i, d in enumerate(dts)},
        }

    # ⑥ 逐个判定突破池
    hits = []
    for c, bs in bars.items():
        if len(bs) < N1 + 5:
            continue
        d = [b[0] for b in bs]
        close = np.array([b[4] for b in bs]); high = np.array([b[2] for b in bs])
        low = np.array([b[3] for b in bs]); vol = np.array([b[5] for b in bs])
        mk = np.array([mkt.get(x, np.nan) for x in d])
        if np.isnan(mk).all():
            continue
        rsv, rsv1 = calc_rsv(close, high, low, mk)
        if rsv is None or rsv <= 74 or rsv1 is None or rsv1 <= 85:
            continue
        # 行业
        ind = ind_map.get(c[2:])
        rsvhy = None
        if ind in ind_series:
            S = ind_series[ind]; im = S["idx"]
            ic = np.array([S["c"][im[x]] if x in im else np.nan for x in d])
            ih = np.array([S["h"][im[x]] if x in im else np.nan for x in d])
            il = np.array([S["l"][im[x]] if x in im else np.nan for x in d])
            ok = ~np.isnan(ic)
            if ok.sum() >= N1:
                rsvhy = calc_rsvhy(ic[ok], ih[ok], il[ok], mk[ok])
        if rsvhy is None or rsvhy <= 74:
            continue
        pv2, pv3 = calc_pv(close, high, low, vol)
        if pv2 is None:
            continue
        # 前置 PV 小：用最近两日 PV2 近似（逐日重算成本高，此处按当日与前一日）
        prev_abs = []
        for back in (1, 2):
            seg_c = close[:-back]; seg_h = high[:-back]; seg_l = low[:-back]; seg_v = vol[:-back]
            p2, _ = calc_pv(seg_c, seg_h, seg_l, seg_v)
            if p2 is not None:
                prev_abs.append(abs(p2))
        if not prev_abs or min(prev_abs) >= 6:
            continue
        if pv3 <= 12:
            continue
        px = close[-1]
        hits.append({
            "code": c, "date": d[-1], "price": round(px, 2),
            "rsv": round(rsv, 1), "rsv1": round(rsv1, 1), "rsvhy": round(rsvhy, 1),
            "pv2": round(pv2, 2), "pv3": round(pv3, 2), "industry": ind,
            "cut1": round(px * GS1, 2), "cut2": round(px * GS2, 2),
            "trail": f"最高价回撤{TRAIL*100:.0f}%",
        })
    hits.sort(key=lambda x: -x["rsvhy"])
    log(f"突破池命中: {len(hits)} 只")

    # ⑦ 输出
    os.makedirs(OUT, exist_ok=True)
    json.dump(hits, open(os.path.join(OUT, "beast_pool_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    lines = [f"# 🐅 猛兽突破池 {datetime.now(BJT).strftime('%Y-%m-%d')}", "",
             f"**命中 {len(hits)} 只**（RSV>74 且 RSV1>85 且 RSVHY>74 且 前置PV<6 且 PV3>12）", "",
             "## 操作单（分批减仓）", "",
             "| 代码 | 名称 | 现价 | 减仓①(+10%) | 减仓②(+20%) | 清仓 | RSV | RSV1 | 行业强度 | 行业 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for hh in hits:
        lines.append(f"| {hh['code']} | — | {hh['price']} | **{hh['cut1']}** | **{hh['cut2']}** | "
                     f"{hh['trail']} | {hh['rsv']} | {hh['rsv1']} | {hh['rsvhy']} | {hh['industry']} |")
    lines += ["", "> 减仓①：+10% 卖出 1/3；减仓②：+20% 再卖 1/3；清仓：从最高点回撤 5% 卖剩余",
              "> 回测（1615信号）：平均+2.90% / 中位+10.01% / 胜率65% / 持有约32天"]
    md = "\n".join(lines)
    open(os.path.join(OUT, f"猛兽突破池_{datetime.now(BJT).strftime('%Y%m%d')}.md"), "w", encoding="utf-8").write(md)
    log(f"报告已存 outputs/猛兽突破池_{datetime.now(BJT).strftime('%Y%m%d')}.md")

    if a.push:
        tok = os.environ.get("PUSH_TOKEN", "")
        if not tok:
            log("[WARN] 无 PUSH_TOKEN")
        else:
            body = json.dumps({"token": tok,
                               "title": f"🐅 猛兽突破池 {len(hits)}只",
                               "content": md[:4000], "template": "markdown"}).encode()
            try:
                r = urllib.request.urlopen(urllib.request.Request(
                    "https://www.pushplus.plus/send", data=body,
                    headers={"Content-Type": "application/json"}), timeout=20)
                log(f"推送: {json.loads(r.read().decode()).get('code')}")
            except Exception as e:
                log(f"[WARN] 推送失败: {e}")


if __name__ == "__main__":
    main()
