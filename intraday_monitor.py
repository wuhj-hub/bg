#!/usr/bin/env python3
"""
盘中监控系统 v2.0（2026-09-15 改造）
=====================================
基于全部量化体系的盘中实时监控：
- 监控池：核心关注3只 + 28行业龙头 + 热搜股动态 + 板块异动
- 【v2.0 主推】王者封板信号：东财涨停池单请求 → 首板+换手>5%+价<10元+未炸板
  回测依据（3.3万样本/11年）：该判据 5 日超额 +0.89%（t=5.0，胜率 56.1%）
- 【v2.0 移除】突破MA20：回测超额 -0.42%（负贡献），已删除推送
- 保留：跌破MA20（风控）/大涨/大跌预警/板块异动
- 推送：PushPlus + 邮件

运行时机：交易日 09:30~11:30, 13:00~15:00，每30分钟一次
部署：GitHub Actions cron（`*/30 1-7 * * 1-5` UTC），脚本内判断交易时段
"""
import subprocess, json, os, sys, re, smtplib, email.utils, time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

# 北京时间 (UTC+8)
BJT = timezone(timedelta(hours=8))

# ── 配置 ──
PUSH_TOKEN = os.environ.get("PUSH_TOKEN", "")
PUSH_SERVICE = os.environ.get("PUSH_SERVICE", "pushplus")
MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "").lower() in ("true", "1", "yes")
MAIL_SMTP = os.environ.get("MAIL_SMTP", "smtp.qq.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "465"))
MAIL_USER = os.environ.get("MAIL_USER", "")
MAIL_PASS = os.environ.get("MAIL_PASS", "")
MAIL_TO = os.environ.get("MAIL_TO", "")

# ⚠️ 2026-09-16：盘中预警限定价格上限（用户要求：只推 10 元以内的股票）
#    覆盖：王者封板信号 + 个股预警（跌破MA20/大涨/大跌）+ 监控池预筛
MAX_PRICE = float(os.environ.get("INTRADAY_MAX_PRICE", "10"))

# 核心关注股票池（全盘量化主力信号）
CORE_STOCKS = [
    ("000779", "甘咨询"), ("002596", "海南瑞泽"), ("600095", "湘财股份"),
]

# 28申万行业龙头（自选watchlist）
WATCHLIST = [
    ("601398", "工商银行"), ("600030", "中信证券"), ("601318", "中国平安"),
    ("600519", "贵州茅台"), ("600887", "伊利股份"), ("600276", "恒瑞医药"),
    ("603259", "药明康德"), ("600196", "复星医药"), ("002594", "比亚迪"),
    ("002475", "立讯精密"), ("000725", "京东方A"), ("002371", "北方华创"),
    ("000333", "美的集团"), ("601899", "紫金矿业"), ("600900", "长江电力"),
    ("000063", "中兴通讯"), ("601728", "中国电信"), ("600487", "亨通光电"),
    ("601857", "中国石油"), ("601088", "中国神华"), ("600585", "海螺水泥"),
    ("600760", "中航沈飞"), ("600879", "航天电子"), ("002714", "牧原股份"),
    ("600309", "万华化学"), ("002027", "分众传媒"), ("601888", "中国中免"),
    ("600019", "宝钢股份"), ("603019", "中科曙光"), ("002129", "TCL中环"),
    ("601012", "隆基绿能"), ("000002", "万科A"), ("002352", "顺丰控股"),
    ("600031", "三一重工"),
]

# 月度股池/鱼身信号股（每日由盘后流程更新此文件）
SIGNAL_POOL_FILE = "signal_pool.json"  # 由盘后流程写入
WANGZHE_STATE_FILE = "outputs/wangzhe_pushed.json"  # 王者信号当日去重状态

# ── 工具 ──
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def cli(cmd, timeout=45):
    full = f"npx -y westock-data-skillhub@1.0.3 {cmd}"
    try:
        r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""

def parse_table(md):
    """解析westock markdown表格"""
    rows, header = [], None
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if any("---" in p for p in parts):
            continue
        if header is None:
            header = parts
            continue
        if len(parts) >= len(header):
            rows.append({header[i]: parts[i] for i in range(len(header))})
    return rows

def load_signal_pool():
    """读取信号股池（双弦/鱼身/猛兽信号股）"""
    pool = []
    if os.path.exists(SIGNAL_POOL_FILE):
        try:
            with open(SIGNAL_POOL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for s in data.get("stocks", []):
                pool.append((s["code"], s["name"]))
        except Exception:
            pass
    return pool


def load_dynamic_pool():
    """P3 动态监控池（2026-08-11）：持仓(holdings.txt) + 信号仲裁TOP5 自动纳入盘中监控
    返回 [(code纯数字, name)]，去重"""
    extra = []
    try:
        if os.path.exists("holdings.txt"):
            for ln in open("holdings.txt", encoding="utf-8"):
                s = ln.strip()
                if not s or s.startswith("#"):
                    continue
                parts = s.split()
                if not parts:
                    continue
                code = parts[0].replace("sh", "").replace("sz", "")
                name = s.split("#")[-1].strip() if "#" in s else code
                if code.isdigit():
                    extra.append((code, name))
        for p in ("outputs/信号仲裁_latest.json", "信号仲裁_latest.json"):
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                for r in d.get("ranked", [])[:5]:
                    code = r.get("code", "").replace("sh", "").replace("sz", "")
                    if code.isdigit():
                        extra.append((code, r.get("code", code)))
                break
    except Exception as e:
        print(f"[WARN] 动态监控池加载失败: {e}")
    return extra

def fetch_minute(code):
    """获取个股最新分时价格"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    raw = cli(f"minute {prefix}{code}")
    rows = parse_table(raw)
    if not rows:
        return None
    last = rows[-1]
    return {
        "time": last.get("time", ""),
        "price": float(last.get("price", 0)),
        "volume": float(last.get("volume", 0)),
    }

def fetch_daily(code, limit=60):
    """获取日线计算均线"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    raw = cli(f"kline {prefix}{code} --period day --limit {limit}")
    rows = parse_table(raw)
    if len(rows) < 25:
        return None
    closes = [float(r.get("last", 0)) for r in rows if r.get("last")]
    prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
    ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else 0
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else 0
    vols = [float(r.get("volume", 0)) for r in rows if r.get("volume")]
    avg_vol5 = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else 0
    return {
        "prev_close": prev_close, "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "avg_vol5": avg_vol5,
    }

def get_board_moves():
    """获取板块异动"""
    moves = []
    raw = cli("hot board --limit 15")
    rows = parse_table(raw)
    for r in rows:
        name = r.get("name", "")
        zdf = r.get("zdf", "")
        try:
            zdf_f = float(zdf)
        except (ValueError, TypeError):
            continue
        if abs(zdf_f) >= 3:
            moves.append({"name": name, "zdf": zdf_f})
    return moves

def fetch_wangzhe_signals():
    """王者封板扫描（v2.0）：东财涨停池单请求 → 筛「首板+换手>5%+价<10元+未炸板」

    回测依据（bt_filters.py，2015-2026，13706 样本）：
      首板+涨停+量比1.5~4+价<10元 → 5日超额 +0.89% (t=5.0)，胜率 56.1%，中位 +0.74%
      对照：原「上穿MA20」超额 -0.42%（胜率49%）→ 无效；T+1开盘追入 -0.99% → 最差
    东财涨停池字段：lbc连板数 / hs换手率 / zbc炸板次数 / fbt首次封板 / hybk行业
    """
    import urllib.request
    date = datetime.now(BJT).strftime("%Y%m%d")
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989"
           f"&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt%3Aasc&date={date}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
        pool = (json.loads(raw).get("data") or {}).get("pool") or []
    except Exception as e:
        log(f"[WARN] 涨停池获取失败: {e}")
        return []
    out = []
    for it in pool:
        try:
            code = str(it.get("c", ""))
            name = str(it.get("n", "")).strip()
            price = float(it.get("p", 0)) / 1000.0   # 东财价格字段 ×1000
            hs = float(it.get("hs", 0))              # 换手率(%)
            lbc = int(it.get("lbc") or 0)            # 连板数
            zbc = int(it.get("zbc") or 0)            # 炸板次数
            fbt = int(it.get("fbt") or 0)            # 首次封板 HHMMSS
        except (ValueError, TypeError):
            continue
        if not code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
            continue                                  # 仅沪深主板
        if "ST" in name.upper():
            continue
        if lbc != 1 or hs <= 5 or price > MAX_PRICE or zbc > 0:
            continue                                  # 王者封板四条件（含价格上限）
        out.append({"code": code, "name": name, "price": price,
                    "turnover": round(hs, 2), "fbt": fbt, "hybk": it.get("hybk", "")})
    out.sort(key=lambda x: x["fbt"])
    return out


def load_pushed():
    """读取当日已推送的王者信号（去重，供 GitHub Actions cache 跨次运行持久化）"""
    try:
        if os.path.exists(WANGZHE_STATE_FILE):
            with open(WANGZHE_STATE_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("date") == datetime.now(BJT).strftime("%Y-%m-%d"):
                return set(d.get("pushed", []))
    except Exception:
        pass
    return set()


def save_pushed(pushed):
    try:
        os.makedirs(os.path.dirname(WANGZHE_STATE_FILE) or ".", exist_ok=True)
        with open(WANGZHE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now(BJT).strftime("%Y-%m-%d"),
                       "pushed": sorted(pushed)}, f, ensure_ascii=False)
    except Exception as e:
        log(f"[WARN] 已推送状态保存失败: {e}")


def push_message(title, content):
    """PushPlus + 邮件双通道"""
    results = []
    if PUSH_TOKEN:
        try:
            body = json.dumps({
                "token": PUSH_TOKEN, "title": title,
                "content": content, "template": "markdown",
            }).encode("utf-8")
            import urllib.request
            req = urllib.request.Request("https://www.pushplus.plus/send", data=body,
                headers={"Content-Type": "application/json"})
            resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
            results.append(("PushPlus", resp.get("code") == 200))
        except Exception as e:
            results.append(("PushPlus", f"ERR {e}"))
    if MAIL_ENABLED and MAIL_USER and MAIL_PASS:
        try:
            html = content.replace("\n", "<br>").replace("|", " ")
            msg = MIMEText(f"<html><body>{html}</body></html>", "html", "utf-8")
            msg["Subject"] = title
            msg["From"] = email.utils.formataddr(("盘中监控", MAIL_USER))
            msg["To"] = MAIL_TO
            server = smtplib.SMTP_SSL(MAIL_SMTP, MAIL_PORT, timeout=20)
            server.login(MAIL_USER, MAIL_PASS)
            server.sendmail(MAIL_USER, [MAIL_TO], msg.as_string())
            server.quit()
            results.append(("邮件", True))
        except Exception as e:
            results.append(("邮件", f"ERR {e}"))
    return results

def is_trading_time(now):
    """判断是否在交易时段（含午休）"""
    hm = now.hour * 100 + now.minute
    if now.weekday() >= 5:
        return False
    # 09:15~11:35 提前15分钟（盘前），13:00~15:05
    if 915 <= hm <= 1135:
        return True
    if 1300 <= hm <= 1505:
        return True
    return False

def main():
    now = datetime.now(BJT).replace(tzinfo=None)  # 北京时间
    log(f"盘中监控启动 {now.strftime('%Y-%m-%d %H:%M')} (北京时间)")

    # 非交易时段直接退出
    if not is_trading_time(now):
        log("非交易时段，跳过")
        return

    signals = []
    pool = CORE_STOCKS + WATCHLIST + load_signal_pool()
    # P3 动态纳入：持仓 + 仲裁TOP5（2026-08-11）
    seen = {c for c, _ in pool}
    for c, n in load_dynamic_pool():
        if c not in seen:
            pool.append((c, n))
            seen.add(c)
    # 去重
    seen = set()
    unique_pool = []
    for code, name in pool:
        if code not in seen:
            seen.add(code)
            unique_pool.append((code, name))

    log(f"监控池: {len(unique_pool)} 只 | 价格上限: {MAX_PRICE:.2f} 元")

    # ── 【v2.0 主推】王者封板扫描（首板+换手>5%+价<10元+未炸板）──
    pushed = load_pushed()
    wz_all = fetch_wangzhe_signals()
    wz_new = [w for w in wz_all if f"{w['code']}_{w['fbt']}" not in pushed]
    log(f"王者封板: 全市场涨停池命中 {len(wz_all)} 只，新增 {len(wz_new)} 只")

    # ── 板块异动检测 ──
    board_moves = get_board_moves()
    for m in board_moves:
        emoji = "🟢" if m["zdf"] > 0 else "🔴"
        signals.append(f"{emoji} 板块异动: **{m['name']}** {m['zdf']:+.2f}%")

    # ── 个股监控 ──
    breakdowns, alerts = [], []   # v2.0: breakouts 已移除
    for code, name in unique_pool:
        daily = fetch_daily(code)
        if not daily:
            continue
        # ⚠️ 2026-09-16 价格上限预筛：昨收已超上限的标的直接跳过（省一次分时调用）
        if daily.get("prev_close", 0) > MAX_PRICE:
            continue
        minute = fetch_minute(code)
        if not minute:
            continue
        price = minute["price"]
        # ⚠️ 2026-09-16：现价复核（防止盘中跳涨突破上限后仍被推送）
        if price > MAX_PRICE:
            continue
        zdf = (price - daily["prev_close"]) / daily["prev_close"] * 100 if daily["prev_close"] else 0

        # 【v2.0】突破MA20 已移除：回测 5日超额 -0.42%、胜率49%（负贡献），改由王者封板信号替代
        # 跌破MA20（保留：风控警示）
        if daily["ma20"] and price < daily["ma20"] and daily["prev_close"] >= daily["ma20"]:
            breakdowns.append(f"🛑 {name}({code}) 跌破MA20 {price:.2f} < {daily['ma20']:.2f} ({zdf:+.2f}%)")
        # 大涨预警
        if zdf >= 8:
            alerts.append(f"🔥 {name}({code}) 大涨 {zdf:+.2f}% @{price:.2f}")
        # 大跌预警
        if zdf <= -5:
            alerts.append(f"⚠️ {name}({code}) 大跌 {zdf:+.2f}% @{price:.2f}")

    # 汇总信号
    all_sigs = breakdowns + alerts + board_moves[:0]  # board已加入signals（v2.0 移除 breakouts）
    if not all_sigs and not wz_new:
        log(f"无触发信号（扫描{len(unique_pool)}只 | 王者新封板0只）")
        return

    # 构建推送内容（限制9000字符）
    content_lines = [f"# ⚡ 盘中监控 {now.strftime('%H:%M')}",
                     f"> 预警范围：价格 ≤ {MAX_PRICE:.0f} 元"]
    if wz_new:
        content_lines.append("\n## 👑 王者封板信号（首板+换手>5%+价<10元）")
        content_lines.append("> 持有周期 **5日**（回测5日超额+0.89%/胜率56.1%，10日衰减）")
        for w in wz_new[:20]:
            t = f"{w['fbt']//10000:02d}:{w['fbt']//100%100:02d}" if w["fbt"] else "--:--"
            content_lines.append(
                f"👑 **{w['name']}**({w['code']}) {w['price']:.2f}元 换手{w['turnover']:.1f}% "
                f"封板{t} · {w['hybk']}")
    if board_moves:
        content_lines.append("\n## 📊 板块异动")
        for s in signals[:10]:
            content_lines.append(s)
    if breakdowns:
        content_lines.append("\n## 🛑 破位信号")
        content_lines.extend(breakdowns[:10])
    if alerts:
        content_lines.append("\n## ⚡ 异动预警")
        content_lines.extend(alerts[:15])
    content = "\n".join(content_lines)
    if len(content) > 9000:
        content = content[:9000] + "\n\n> ...（截断）"

    title = f"⚡盘中监控 {now.strftime('%H:%M')} (👑王者{len(wz_new)}/{len(breakdowns)}破位)"
    log(f"推送: {title}")
    results = push_message(title, content)
    for ch, ok in results:
        log(f"  {ch}: {'✅' if ok is True else ok}")
    # 记录已推送（跨次运行去重，由 workflow 的 actions/cache 持久化）
    if any(ok is True for _, ok in results) and wz_new:
        pushed |= {f"{w['code']}_{w['fbt']}" for w in wz_new}
        save_pushed(pushed)

if __name__ == "__main__":
    main()
