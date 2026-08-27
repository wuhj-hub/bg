#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tdx_cross_check.py —— 数据源冗余交叉验证（P1-7，2026-08-28）
============================================================
用途：对关键标的（指数/持仓股/强势池），对比【通达信 tdx】与【westock】的最新收盘价，
     差异 >0.5% 时告警（数据源不一致需人工核实）。

用法（tdx 是 MCP 工具，需在 ima 会话中用 tdx_quotes 取数后传入）：
  1. 会话中调用 tdx_quotes 批量查询关键标的 → 整理为 JSON：
     {"sh600519": {"close": 1390.0, "pct": -1.20}, "sz000001": {...}}
  2. 运行: python3 tdx_cross_check.py --tdx /tmp/tdx_quotes.json [--list 附加标的]
  3. 脚本自动用 westock 查询同标的现价，对比输出报告

输出：控制台差异表 + outputs/数据源交叉验证_{date}.md
"""
import argparse, json, os, re, subprocess, sys
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
THRESHOLD = 0.5  # 差异阈值 %

def cli(args, timeout=60):
    try:
        r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""

def westock_quote(code):
    """westock 取最新收盘（kline limit 2，返回降序）"""
    txt = cli(["kline", code, "--period", "day", "--limit", "2"])
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "date" in parts:
            header = parts
            continue
        if not header or "---" in parts[0] or len(parts) < 6:
            continue
        try:
            di = header.index("date")
            ci = header.index("last")  # 单股列序: date|open|last|high|low
            if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                rows.append((parts[di], float(parts[ci])))
        except (ValueError, IndexError):
            pass
    return rows[0] if rows else (None, None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tdx", required=True, help="tdx 侧行情 JSON: {code: {close, pct}}")
    ap.add_argument("--list", default="", help="附加标的（逗号分隔，如 sh600519,sz000001）")
    a = ap.parse_args()

    tdx_data = json.load(open(a.tdx, encoding="utf-8"))
    codes = list(tdx_data.keys())
    if a.list:
        codes += [c.strip() for c in a.list.split(",") if c.strip()]

    print(f"交叉验证 {len(codes)} 个标的（阈值 {THRESHOLD}%）\n")
    print(f"{'代码':<10}{'tdx收盘':>10}{'westock':>10}{'差异%':>8}  状态")
    print("-" * 52)
    diffs = []
    for code in codes:
        t = tdx_data.get(code, {})
        t_close = t.get("close")
        w_date, w_close = westock_quote(code)
        if t_close is None or w_close is None:
            print(f"{code:<10}{str(t_close):>10}{str(w_close):>10}{'—':>8}  ⚠️ 数据缺失")
            continue
        diff = (w_close / t_close - 1) * 100
        status = "✅" if abs(diff) <= THRESHOLD else f"🚨 差异{(diff):+.2f}%"
        if abs(diff) > THRESHOLD:
            diffs.append((code, diff))
        print(f"{code:<10}{t_close:>10.2f}{w_close:>10.2f}{diff:>+7.2f}%  {status}")

    # 输出报告
    today = datetime.now().strftime("%Y-%m-%d")
    L = [f"# 🔍 数据源交叉验证（tdx vs westock）{today}", "",
         f"> 标的 {len(codes)} 个｜差异阈值 {THRESHOLD}%｜westock 日期 {w_date or '—'}", ""]
    if diffs:
        L.append("## 🚨 需人工核实（差异超阈值）")
        for c, d in diffs:
            L.append(f"- {c}：差异 {d:+.2f}%")
        L.append("")
    L.append("## 说明")
    L.append("- 用途：数据源冗余校验，防止单点数据源错误影响信号（westock 为主，tdx 为校验）")
    L.append("- 正常状态：同一标的两个数据源收盘价差异应 <0.5%（复权口径差异除外）")
    md = "\n".join(L)
    os.makedirs("outputs", exist_ok=True)
    out = f"outputs/数据源交叉验证_{today}.md"
    open(out, "w", encoding="utf-8").write(md)
    print(f"\n[OK] {out}（{'发现差异' if diffs else '全部一致'}）")

if __name__ == "__main__":
    main()
