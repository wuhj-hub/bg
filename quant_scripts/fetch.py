#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch.py —— 统一取数层（第 2 层 · 取数标准化）v0.1

第 1 批：`kline`（日/周/月/分钟）+ `quote`（腾讯行情）。
统一收口历史上被反复重写的 5 件事：**批量 / 重试退避 / 免 npx / 缺口兜底 / 解析**。

设计约束（沿用体系既有教训）：
- kline 批量 250/批、**串行**（并发会限流丢数）；缺口小批复取 + 逐只有限兜底（≤10 只）。
- 空返回视为瞬时抖动 → 重试 2~3 次含退避（westock 批量 kline 存在随机空返回）。
- 免 npx：`shutil.which("westock-data-skillhub")` 命中则直调，否则回退 npx。
- 解析表头驱动（兼容 batch 含 symbol / 单只无 symbol，列序变化不炸）。

用法：
    from fetch import kline, quote
    kl = kline(["sh600519","sz000001"], period="day", limit=250)
    q  = quote(["sh600519"])
详见知识库《第2层·取数层对账与设计草案_2026-10-14》。
"""
import os
import re
import time
import shutil
import subprocess
import urllib.request

_PERIOD_OK = {"day", "week", "month", "m1", "m5", "m15", "m30", "m60"}
KLINE_BATCH = 250        # 批量大小（250/批零丢失）
GAP_BATCH = 40           # 缺口小批复取
GAP_PERSTOCK_CAP = 10    # 缺口逐只兜底上限（防退市票空耗）
TIMEOUT = 120

WESTOCK = ([shutil.which("westock-data-skillhub")]
           if shutil.which("westock-data-skillhub")
           else ["npx", "-y", "westock-data-skillhub@1.0.3"])


def _run(args, timeout=TIMEOUT, retries=3, backoff=2.0):
    """执行 westock 命令；空返回/异常 → 退避重试。"""
    for i in range(retries):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout and r.stdout.strip():
                return r.stdout
        except Exception:
            pass
        time.sleep(backoff * (i + 1))
    return ""


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def parse_kline_txt(txt, limit=None):
    """westock kline 表格 → {code: [{date,open,high,low,close,volume,amount}, ... 升序]}。
    表头驱动（兼容 batch 含 symbol 列 / 单只无 symbol）。"""
    by, header = {}, None
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
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", parts[di]):
                continue
            row = {"date": parts[di]}
            for key, hk in (("open", "open"), ("high", "high"), ("low", "low"),
                            ("close", "last"), ("volume", "volume"), ("amount", "amount")):
                if hk in header and header.index(hk) < len(parts):
                    try:
                        row[key] = float(parts[header.index(hk)])
                    except ValueError:
                        pass
            if "symbol" in header and header.index("symbol") < len(parts):
                sym = parts[header.index("symbol")]
            elif re.match(r"^(sh|sz|bj)\d{6}$", parts[0]):
                sym = parts[0]
            else:
                sym = ""
            by.setdefault(sym, []).append(row)
        except (ValueError, IndexError):
            pass
    for sym in by:
        by[sym].sort(key=lambda r: r["date"])
        if limit:
            by[sym] = by[sym][-limit:]
    return by


def kline(codes, period="day", limit=250, fq=None):
    """批量 K线 → {code: [bar, ...]}；缺口的逐只有限兜底。"""
    assert period in _PERIOD_OK, "unsupported period: %s" % period

    def _args(batch):
        a = ["kline", ",".join(batch), "--period", period, "--limit", str(limit)]
        if fq:
            a += ["--fq", fq]
        return a

    result = {}
    for batch in chunks(codes, KLINE_BATCH):
        result.update(parse_kline_txt(_run(_args(batch)), limit=limit))
        missing = [c for c in batch if c not in result]
        if missing:
            for sub in chunks(missing, GAP_BATCH):
                result.update(parse_kline_txt(_run(_args(sub)), limit=limit))
            for c in [c for c in missing if c not in result][:GAP_PERSTOCK_CAP]:
                result.update(parse_kline_txt(_run(["kline", c, "--period", period, "--limit", str(limit)]),
                                              limit=limit))
    return result


def quote(codes):
    """腾讯行情批量快照 → {code: {name, price, prev_close, open}}（batch 50，GBK）。"""
    out = {}
    for batch in chunks(codes, 50):
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=20).read().decode("gbk", "ignore")
        except Exception:
            continue
        for seg in raw.split(";"):
            seg = seg.strip()
            if "=" not in seg:
                continue
            code = seg.split("=")[0].replace("v_", "").strip()
            val = seg.split('="')[-1].rstrip('"')
            f = val.split("~")
            if len(f) < 6:
                continue
            try:
                out[code] = {"name": f[1], "price": float(f[3]),
                             "prev_close": float(f[4]), "open": float(f[5])}
            except ValueError:
                continue
    return out


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] or ["sh600519"]
    kl = kline(codes)
    print("kline codes:", {k: len(v) for k, v in kl.items()})
    for k, v in list(kl.items())[:1]:
        if v:
            print("  latest:", k, v[-1])
    print("quote:", quote(codes))
