#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch.py —— 统一取数层（第 2 层 · 取数标准化）v0.2

v0.1：`kline`（日/周/月/分钟）+ `quote`（腾讯行情）。
v0.2（2026-10-15，阶段 3）新增：
- `asfund(codes, date=None)`  资金（westock asfund）
- `board()` / `hotboard(limit)`  板块（westock board / hot board）
- `minute(code, days=None)`  分时（westock **minute** 子命令；单只）
- **磁盘缓存**（opt-in）：`FETCH_CACHE=1`（或显式 cache_dir）开启；
  防倒灌规则：只信任「最后一根 bar 日期 < 今天(北京)」的缓存（=历史已完结），
  同交易日数据一律重取；另可用 `FETCH_CACHE_TTL`（秒）显式允许同日短期复用。

统一收口历史上被反复重写的 6 件事：**批量 / 重试退避 / 免 npx / 缺口兜底 / 解析 / 缓存**。

设计约束（沿用体系既有教训）：
- kline 批量 250/批、**串行**（并发会限流丢数）；缺口小批复取 + 逐只有限兜底（≤10 只）。
- 空返回视为瞬时抖动 → 重试 2~3 次含退避（westock 批量 kline 存在随机空返回）。
- 免 npx：`shutil.which("westock-data-skillhub")` 命中则直调，否则回退 npx。
- 解析表头驱动（兼容 batch 含 symbol / 单只无 symbol，列序变化不炸）。

用法：
    from fetch import kline, quote, asfund, board, hotboard, minute
    kl = kline(["sh600519", "sz000001"], period="day", limit=250)
    kl = kline(codes, period="day", limit=250, use_cache=True)
    f  = asfund(["600519"], date="2026-10-14")
    raw = board(); raw2 = hotboard(8)
详见知识库《第2层·取数层对账与设计草案_2026-10-14》。
"""
import os
import re
import json
import time
import shutil
import hashlib
import tempfile
import datetime
import subprocess
import urllib.request

_PERIOD_OK = {"day", "week", "month", "season", "year"}   # 2026-10-15 实测：本版仅支持这 5 个周期（m1 等已移除）
KLINE_BATCH = 250        # 批量大小（250/批零丢失）
GAP_BATCH = 40           # 缺口小批复取
GAP_PERSTOCK_CAP = 10    # 缺口逐只兜底上限（防退市票空耗）
TIMEOUT = 120

# ── 缓存配置 ──
# 默认放在系统临时目录（不落仓库 → 不进提交清单/不触发产物审计）；同一次 CI job 内跨 step 共享。
CACHE_DIR = (os.environ.get("FETCH_CACHE_DIR")
             or os.path.join(tempfile.gettempdir(), "bg_fetch_cache"))
_CACHE_ON = os.environ.get("FETCH_CACHE", "0").strip().lower() not in ("0", "", "false", "no")
CACHE_TTL = int(os.environ.get("FETCH_CACHE_TTL", "0") or "0")   # >0 才允许「同交易日」短期复用

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


def norm(code):
    """纯数字/带前缀 code → sh/sz/bj 前缀（asfund/minute 等子命令要求带前缀）。"""
    code = str(code).strip()
    if code.startswith(("sh", "sz", "bj", "pt")):
        return code
    if code.startswith(("6", "9", "5")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


# ══════════════════════════════════════════════════════════
#  缓存层（opt-in）
# ══════════════════════════════════════════════════════════
def _today_bj():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


def _cache_enabled(use_cache):
    return _CACHE_ON if use_cache is None else bool(use_cache)


def _kline_cache_path(code, period, fq):
    tag = hashlib.md5(("%s|%s|%s" % (code, period, fq or "nfq")).encode("utf-8")).hexdigest()[:16]
    return os.path.join(CACHE_DIR, "kline_%s_%s_%s.json" % (period, fq or "nfq", tag))


def _read_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(path, rec):
    """写缓存；防倒灌：若已有缓存最后一根 bar 日期更晚，则不覆盖。"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        old = _read_cache(path)
        if old:
            old_last = (old.get("bars") or [{}])[-1].get("date", "")
            new_last = (rec.get("bars") or [{}])[-1].get("date", "")
            if old_last and new_last and old_last > new_last:
                return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
    except Exception:
        pass


def _cache_usable(rec, period, limit, fq):
    """可用性判定：只信任历史已完结的缓存（最后 bar < 今天）；TTL>0 时允许同日短期复用。"""
    if not rec or rec.get("period") != period or rec.get("fq") != fq:
        return False
    bars = rec.get("bars") or []
    if not bars:
        return False
    if rec.get("limit", 0) < limit:
        return False
    last = bars[-1].get("date", "")
    today = _today_bj()
    if last < today:
        return True
    if CACHE_TTL > 0:
        try:
            age = time.time() - float(rec.get("fetched_at") or 0)
            return 0 <= age <= CACHE_TTL
        except Exception:
            return False
    return False


# ══════════════════════════════════════════════════════════
#  K线
# ══════════════════════════════════════════════════════════
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


def parse_kv_table(txt):
    """westock 长表（含 symbol/code 列）→ {symbol: {列名: 值(str)}}（表头驱动）。"""
    out, header = {}, None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if header is None:
            if ("symbol" in parts) or ("code" in parts):
                header = parts
            continue
        if "---" in parts[0]:
            continue
        if len(parts) < 2:
            continue
        try:
            sym = parts[header.index("symbol")] if "symbol" in header else parts[0]
            if not re.match(r"^[A-Za-z0-9]+$", sym or ""):
                continue
            out[sym] = {header[i]: parts[i] for i in range(min(len(header), len(parts)))}
        except (ValueError, IndexError):
            continue
    return out


def _fetch_kline_raw(codes, period, limit, fq):
    """底层：批量 + 缺口兜底，返回 {code: [bar,...]}（表头驱动解析）。"""
    def _args(batch):
        a = ["kline", ",".join(batch), "--period", period, "--limit", str(limit)]
        if fq:
            a += ["--fq", fq]
        return a

    def _fetch(batch):
        got = parse_kline_txt(_run(_args(batch)), limit=limit)
        if len(batch) == 1 and batch[0] not in got and "" in got:
            got[batch[0]] = got.pop("")
        return got

    result = {}
    for batch in chunks(codes, KLINE_BATCH):
        result.update(_fetch(batch))
        missing = [c for c in batch if c not in result]
        if missing:
            for sub in chunks(missing, GAP_BATCH):
                result.update(_fetch(sub))
            for c in [c for c in missing if c not in result][:GAP_PERSTOCK_CAP]:
                result.update(_fetch([c]))
    return result


def kline(codes, period="day", limit=250, fq=None, use_cache=None):
    """批量 K线 → {code: [bar, ...]}；缺口逐只有限兜底；可选磁盘缓存。

    use_cache: None=跟随 env FETCH_CACHE；True/False 强制。
    缓存命中条件见 `_cache_usable`（默认只复用历史已完结数据，防倒灌）。
    """
    assert period in _PERIOD_OK, "unsupported period: %s" % period
    codes = list(codes)
    cache_on = _cache_enabled(use_cache)
    out, need = {}, list(codes)
    if cache_on:
        need = []
        for c in codes:
            rec = _read_cache(_kline_cache_path(c, period, fq))
            if rec and _cache_usable(rec, period, limit, fq):
                out[c] = rec["bars"][-limit:] if limit else rec["bars"]
            else:
                need.append(c)
    fetched = _fetch_kline_raw(need, period, limit, fq) if need else {}
    if cache_on and fetched:
        for c, bars in fetched.items():
            _write_cache(_kline_cache_path(c, period, fq),
                         {"period": period, "fq": fq, "limit": limit,
                          "bars": bars, "fetched_at": time.time(), "fetched_day": _today_bj()})
    out.update(fetched)
    return out


# ══════════════════════════════════════════════════════════
#  行情快照 / 资金 / 板块 / 分时
# ══════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════
#  外部独立源适配器（阶段 4）
#  —— 把散落各脚本的「直连 URL + 手写解析 + 各自重试」收进本层。
# ══════════════════════════════════════════════════════════
GTIMG_URL = "https://qt.gtimg.cn/q="
GTIMG_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com"}


def parse_gtimg(raw):
    """腾讯行情响应 → {wcode: {...}}（wcode 带 sh/sz 前缀，表头=字段位）。

    字段位（实测）：1名称 3现价 4昨收 5今开 6成交量(手) 32涨跌幅% 33最高 34最低
    37成交额(万) 44流通市值(亿) 45总市值(亿) 47涨停价 48跌停价。
    """
    out = {}
    for seg in (raw or "").split(";"):
        seg = seg.strip()
        if not seg.startswith("v_") or "=" not in seg:
            continue
        try:
            wcode = seg.split("=")[0][2:].strip()
            val = seg.split('="', 1)[1].rstrip('"')
        except Exception:
            continue
        f = val.split("~")
        if len(f) < 6:
            continue

        def _f(i, d=None):
            try:
                return float(f[i])
            except Exception:
                return d
        rec = {"name": f[1], "code": f[2], "price": _f(3), "prev_close": _f(4), "open": _f(5)}
        for key, i in (("volume", 6), ("change_pct", 32), ("high", 33), ("low", 34),
                       ("amount", 37), ("mktcap_circ", 44), ("mktcap_total", 45),
                       ("limit_up", 47), ("limit_down", 48)):
            if i < len(f):
                v = _f(i)
                if v is not None:
                    rec[key] = v
        out[wcode] = rec
    return out


def ext_gtimg(codes, batch=50, timeout=20, retries=3, pause=0.0):
    """腾讯行情快照（qt.gtimg.cn，GBK，带重试）→ {wcode: {...}}。

    源：腾讯 gtimg（云 IP，不受东财反爬影响，沙箱/CI 均可用）。
    不存在的代码不返回 → 响应缺键即视为无效代码（gen_mainboard 依赖此特性）。
    """
    codes = [str(c).strip() for c in codes if str(c).strip()]
    codes = [c if c.startswith(("sh", "sz", "bj")) else norm(c) for c in codes]
    out = {}
    for batch_codes in chunks(codes, batch):
        raw = ""
        for attempt in range(retries):
            try:
                req = urllib.request.Request(GTIMG_URL + ",".join(batch_codes), headers=GTIMG_HEADERS)
                raw = urllib.request.urlopen(req, timeout=timeout).read().decode("gbk", "replace")
                if raw.strip():
                    break
            except Exception:
                pass
            time.sleep(1.5 * (attempt + 1))
        out.update(parse_gtimg(raw))
        if pause:
            time.sleep(pause)
    return out


def quote(codes):
    """腾讯行情批量快照 → {code: {name, price, prev_close, open}}（兼容旧接口）。
    新代码请优先用 `ext_gtimg`（字段更全）。"""
    full = ext_gtimg(codes)
    return {c: {"name": r["name"], "price": r.get("price"),
                "prev_close": r.get("prev_close"), "open": r.get("open")}
            for c, r in full.items()}


def raw(args, timeout=TIMEOUT):
    """通用透传：直接执行 westock 子命令并返回 **原始 stdout**（不解析）。

    用途：尚未标准化为结构化函数的子命令（如板块级 `asfund --market all`、
    `board --market all` 等），先统一走本层以复用「免 npx / 重试退避 / 超时」，
    解析逻辑仍由调用方保留（包裹式适配：优先本层，失败回退本地 run）。

    args: 字符串或列表，例如 "asfund --market all" / ["asfund","--market","all"]。
    """
    if isinstance(args, str):
        args = args.split()
    return _run(list(args), timeout=timeout)


def asfund(codes, date=None):
    """westock asfund 资金流向 → {code: {列名: 值(str)}}（表头驱动）。
    ⚠️ 必须带前缀代码（内部自动 norm）；date: 'YYYY-MM-DD'（YYYYMMDD 会返空）；缺省取最新。"""
    out = {}
    codes = [norm(c) for c in codes]
    for batch in chunks(codes, 60):
        args = ["asfund", ",".join(batch)]
        if date:
            args += ["--date", date]
        out.update(parse_kv_table(_run(args, timeout=240)))
    return out


def board():
    """westock 板块（行业+概念+资金，原始 markdown 文本）。"""
    return _run(["board"])


def hotboard(limit=8):
    """westock 热门板块（原始 markdown 文本）。"""
    return _run(["hot", "board", "--limit", str(limit)])


def minute(code, days=None):
    """westock **minute** 子命令分时 → list[dict]（单只，升序）。
    列：time, price, volume, amount（days>1 时另含 date）。
    ⚠️ 仅支持单只（批量会报 code param error）。"""
    args = ["minute", norm(code)]
    if days:
        args += ["--days", str(days)]
    txt = _run(args, timeout=180)
    rows, header = [], None
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if "time" in parts:
            header = parts
            continue
        if not header or "---" in parts[0]:
            continue
        try:
            row = {"time": parts[header.index("time")]}
            if "date" in header:
                row["date"] = parts[header.index("date")]
            if "price" in header:
                row["price"] = float(parts[header.index("price")])
            if "volume" in header:
                row["volume"] = float(parts[header.index("volume")])
            if "amount" in header:
                row["amount"] = float(parts[header.index("amount")])
            rows.append(row)
        except (ValueError, IndexError):
            continue
    return rows


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] or ["sh600519"]
    kl = kline(codes)
    print("kline codes:", {k: len(v) for k, v in kl.items()})
    for k, v in list(kl.items())[:1]:
        if v:
            print("  latest:", k, v[-1])
    print("quote:", quote(codes))
    print("asfund:", list(asfund(codes))[:3])
    print("minute:", minute(codes[0])[:3])
    print("board head:", (board() or "")[:80].replace("\n", " / "))
    print("hotboard head:", (hotboard(3) or "")[:80].replace("\n", " / "))
