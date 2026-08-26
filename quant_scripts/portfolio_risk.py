#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio_risk.py —— 组合层风控（P1-2 · 2026-08-26）
================================================================
解决"个股风控完善、组合层缺位"问题：
  ① 行业集中度  — 持仓行业分布 + Top1行业占比（>40%预警）
  ② 相关性矩阵  — 持仓日收益率相关系数（r>0.7 高相关预警=同涨同跌风险）
  ③ 组合回撤预警 — 组合净值历史累积（portfolio_nav_history.csv），-10%/-15%/-20% 三档预警
  ④ 个股离场计分 — 复用 trade_guard 离场计分卡（持仓专属）

数据：holdings.txt（代码 # 名称）+ westock profile(行业) + 腾讯proxy(近120日K线)
用法：python3 portfolio_risk.py [--holdings holdings.txt] [--push]
输出：outputs/组合风控_{date}.md + outputs/组合风控_latest.json
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime, date

BASE = os.path.dirname(os.path.abspath(__file__))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
NAV_HIST = os.path.join(BASE, "outputs", "portfolio_nav_history.csv")

def run(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_table(md):
    lines = [l.strip() for l in md.splitlines() if l.strip()]
    if not lines:
        return []
    hdr = None
    for i, ln in enumerate(lines):
        if ln.startswith("|") and "---" not in ln and "code" in ln:
            hdr = i
            break
    if hdr is None:
        return []
    hdrs = [h.strip() for h in lines[hdr].split("|")[1:-1]]
    res = []
    for ln in lines[hdr + 2:]:
        if not ln.startswith("|"):
            continue
        v = [x.strip() for x in ln.split("|")[1:-1]]
        if len(v) == len(hdrs):
            res.append(dict(zip(hdrs, v)))
    return res

def load_holdings(fpath):
    """holdings.txt: 代码 # 名称（可含 成本价 第四字段）"""
    out = []
    if not os.path.exists(fpath):
        # 尝试仓库根/上级
        for alt in ("holdings.txt", "../holdings.txt", "/sandbox/workspace/holdings.txt"):
            if os.path.exists(alt):
                fpath = alt
                break
        else:
            return out
    for ln in open(fpath, encoding="utf-8"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"((?:sh|sz)\d{6})\s*#\s*([^ ]+)", s)
        if m:
            cost = None
            mc = re.search(r"成本\s*[:：]?\s*([\d.]+)", s)
            if mc:
                cost = float(mc.group(1))
            out.append({"code": m.group(1), "name": m.group(2), "cost": cost})
    return out

def fetch_kline(code, limit=120):
    """腾讯proxy近N日K线（快）"""
    url = f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param={code},day,,,{limit},qfq"
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
        kl = d.get("data", {}).get(code, {}).get("qfqday") or d.get("data", {}).get(code, {}).get("day") or []
        rows = []
        for k in kl:
            try:
                rows.append({"date": k[0], "last": float(k[2])})
            except (ValueError, IndexError):
                continue
        rows.sort(key=lambda r: r["date"])
        return rows
    except Exception:
        return []

def get_industries(codes):
    """westock profile 批量行业"""
    ind = {}
    for i in range(0, len(codes), 20):
        txt = run(["profile", ",".join(codes[i:i + 20])])
        for r in parse_table(txt):
            ind[r.get("code", "")] = r.get("industry", "未知")
        time.sleep(0.2)
    return ind

def corr_matrix(prices_by_code):
    """日收益率相关系数矩阵，返回 (matrix, high_pairs)"""
    import math
    codes = list(prices_by_code.keys())
    rets = {}
    for c in codes:
        rows = prices_by_code[c]
        rs = []
        for i in range(1, len(rows)):
            if rows[i - 1]["last"] > 0:
                rs.append((rows[i]["last"] - rows[i - 1]["last"]) / rows[i - 1]["last"])
        rets[c] = rs
    n = min(len(v) for v in rets.values()) if rets else 0
    if n < 20:
        return {}, []
    mat, high_pairs = {}, []
    for a in codes:
        mat[a] = {}
        for b in codes:
            ra, rb = rets[a][-n:], rets[b][-n:]
            ma_, mb_ = sum(ra) / n, sum(rb) / n
            cov = sum((ra[i] - ma_) * (rb[i] - mb_) for i in range(n)) / n
            sa = math.sqrt(sum((x - ma_) ** 2 for x in ra) / n)
            sb = math.sqrt(sum((x - mb_) ** 2 for x in rb) / n)
            r = cov / (sa * sb) if sa > 0 and sb > 0 else 0
            mat[a][b] = round(r, 2)
            if a < b and r > 0.7:
                high_pairs.append((a, b, round(r, 2)))
    return mat, high_pairs

def nav_tracking(holdings, prices_by_code):
    """组合净值：等权持仓，按收盘价变化计算；累积 NAV 历史 + 回撤预警"""
    today = date.today().isoformat()
    # 当日组合相对基准（等权净值 = 平均涨跌幅）
    nav_today = 1.0
    pnl = {}
    for h in holdings:
        rows = prices_by_code.get(h["code"], [])
        if len(rows) >= 2:
            chg = (rows[-1]["last"] - rows[-2]["last"]) / rows[-2]["last"]
            pnl[h["code"]] = round(chg * 100, 2)
            nav_today *= (1 + chg) ** (1 / len(holdings)) if len(holdings) else 1.0
    # 读历史
    hist = []
    if os.path.exists(NAV_HIST):
        for ln in open(NAV_HIST, encoding="utf-8"):
            p = ln.strip().split(",")
            if len(p) >= 2 and p[0] != "date":  # 跳过表头
                try:
                    hist.append((p[0], float(p[1])))
                except ValueError:
                    continue
    # 去重（同日覆盖）
    hist = [(d, v) for d, v in hist if d != today]
    hist.append((today, round(nav_today, 4)))
    hist = hist[-250:]
    os.makedirs(os.path.dirname(NAV_HIST), exist_ok=True)
    with open(NAV_HIST, "w", encoding="utf-8") as f:
        f.write("date,nav\n")
        for d, v in hist:
            f.write(f"{d},{v}\n")
    # 回撤
    peak = max(v for _, v in hist)
    cur_nav = hist[-1][1]
    dd = (peak - cur_nav) / peak * 100 if peak else 0
    level = None
    if dd >= 20:
        level = "🔴 组合回撤≥20%（强制降仓）"
    elif dd >= 15:
        level = "🟠 组合回撤≥15%（减仓警戒）"
    elif dd >= 10:
        level = "🟡 组合回撤≥10%（关注）"
    else:
        level = "🟢 正常"
    return {"today_nav": round(nav_today, 4), "drawdown": round(dd, 1), "level": level,
            "hist_len": len(hist), "pnl_today": pnl, "peak": round(peak, 4)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdings", default="holdings.txt")
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()

    holdings = load_holdings(args.holdings)
    if not holdings:
        print("❌ 未读取到持仓（holdings.txt 缺失或格式不符）")
        sys.exit(1)
    codes = [h["code"] for h in holdings]
    print(f"持仓 {len(holdings)} 只: {', '.join(c for c in codes)}")

    # ① 行业
    industries = get_industries(codes)
    ind_cnt = {}
    for c in codes:
        ind = industries.get(c, "未知")
        ind_cnt[ind] = ind_cnt.get(ind, 0) + 1
        for h in holdings:
            if h["code"] == c:
                h["industry"] = ind
    top_ind = max(ind_cnt.items(), key=lambda x: x[1]) if ind_cnt else ("", 0)
    ind_ratio = top_ind[1] / len(codes) * 100
    ind_warn = ind_ratio > 40

    # ② 相关性 + ③ 净值（同一批K线）
    prices = {c: fetch_kline(c, 120) for c in codes}
    mat, high_pairs = corr_matrix(prices)
    nav = nav_tracking(holdings, prices)

    # 输出
    today = date.today().isoformat()
    js = {"date": today, "holdings": holdings, "industries": ind_cnt,
          "top_industry": {"name": top_ind[0], "ratio": round(ind_ratio, 1), "warn": ind_warn},
          "corr_high_pairs": high_pairs, "corr_matrix": mat, "nav": nav}
    os.makedirs(os.path.join(BASE, "outputs"), exist_ok=True)
    json.dump(js, open(os.path.join(BASE, "outputs", "组合风控_latest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    L = [f"# 🛡️ 持仓组合风控 {today}", ""]
    L.append(f"**持仓 {len(holdings)} 只**：" + "、".join(f"{h['name']}({h['code']})" for h in holdings))
    L.append("")
    L.append("## ① 行业集中度")
    for ind, cnt in sorted(ind_cnt.items(), key=lambda x: -x[1]):
        L.append(f"- {ind}: {cnt}只 ({cnt/len(codes)*100:.0f}%)")
    L.append(f"- **Top1: {top_ind[0]} {ind_ratio:.0f}%** {'⚠️ 超40%集中' if ind_warn else '✅ 分散'}")
    L.append("")
    L.append("## ② 持仓相关性（近120日收益率，r>0.7=高相关预警）")
    if high_pairs:
        for a, b, r in high_pairs:
            na = next((h["name"] for h in holdings if h["code"] == a), a)
            nb = next((h["name"] for h in holdings if h["code"] == b), b)
            L.append(f"- ⚠️ **{na} ↔ {nb} r={r}**（同涨同跌风险）")
    else:
        L.append("- ✅ 无高相关对（r>0.7）")
    if mat:
        codes_n = list(mat.keys())
        L.append("")
        L.append("| | " + " | ".join(next((h["name"][:4] for h in holdings if h["code"] == c), c) for c in codes_n) + " |")
        L.append("|" + "---|" * (len(codes_n) + 1))
        for a in codes_n:
            row = [next((h["name"][:4] for h in holdings if h["code"] == a), a)]
            for b in codes_n:
                row.append(f"{mat[a][b]:.2f}")
            L.append("| " + " | ".join(row) + " |")
    L.append("")
    L.append("## ③ 组合净值与回撤预警")
    L.append(f"- 今日组合净值变化：**{nav['today_nav']:.4f}**（等权）| 单日: " +
             "、".join(f"{h['name']}{nav['pnl_today'].get(h['code'], 0):+.1f}%" for h in holdings))
    L.append(f"- 累计回撤：**{nav['drawdown']}%**（峰值{nav['peak']:.4f}）→ **{nav['level']}**")
    L.append("- 预警线：-10%关注 / -15%减仓 / -20%强制降仓")
    L.append("")
    L.append("## ④ 个股离场状态")
    try:
        sys.path.insert(0, BASE)
        from trade_guard import check_stock
        for h in holdings:
            r = check_stock(h["code"])
            if r.get("ok"):
                L.append(f"- {h['name']}: 离场{r['exit_score']}（{r['exit_action']}）" +
                         (f"｜市场顶{r.get('market_top', {}).get('score', '?')}分" if r.get("market_top") else ""))
            else:
                L.append(f"- {h['name']}: {r.get('err', '查询失败')}")
    except Exception as e:
        L.append(f"- ⚠️ 离场计分不可用: {e}")
    L.append("")
    L.append("*规则：行业Top1>40%预警｜相关性r>0.7预警｜回撤-10/-15/-20%三档*")
    md = "\n".join(L)
    md_path = os.path.join(BASE, "outputs", f"组合风控_{today}.md")
    open(md_path, "w", encoding="utf-8").write(md)
    print(md)
    print(f"\n[OK] {md_path}")
    if args.push:
        token = os.environ.get("PUSH_TOKEN", "")
        if token:
            import urllib.request
            data = json.dumps({"token": token, "title": f"组合风控 {today}", "content": md[:4000]}).encode()
            req = urllib.request.Request("http://www.pushplus.plus/send", data=data,
                                         headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=20)
                print("[push] 已推送")
            except Exception as e:
                print(f"[push] 失败: {e}")

if __name__ == "__main__":
    main()
