#!/usr/bin/env python3
"""
盘中监控系统 v1.0
================
基于全部量化体系的盘中实时监控：
- 监控池：核心关注3只 + 28行业龙头 + 热搜股动态 + 板块异动
- 信号规则：突破MA20/跌破MA20/大涨预警/大跌预警/板块异动/放量异动
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

    log(f"监控池: {len(unique_pool)} 只")

    # ── 板块异动检测 ──
    board_moves = get_board_moves()
    for m in board_moves:
        emoji = "🟢" if m["zdf"] > 0 else "🔴"
        signals.append(f"{emoji} 板块异动: **{m['name']}** {m['zdf']:+.2f}%")

    # ── 个股监控 ──
    breakouts, breakdowns, alerts = [], [], []
    for code, name in unique_pool:
        daily = fetch_daily(code)
        if not daily:
            continue
        minute = fetch_minute(code)
        if not minute:
            continue
        price = minute["price"]
        zdf = (price - daily["prev_close"]) / daily["prev_close"] * 100 if daily["prev_close"] else 0

        # 突破MA20
        if daily["ma20"] and price > daily["ma20"] and daily["prev_close"] <= daily["ma20"]:
            breakouts.append(f"🚀 {name}({code}) 突破MA20 {price:.2f} > {daily['ma20']:.2f} ({zdf:+.2f}%)")
        # 跌破MA20
        elif daily["ma20"] and price < daily["ma20"] and daily["prev_close"] >= daily["ma20"]:
            breakdowns.append(f"🛑 {name}({code}) 跌破MA20 {price:.2f} < {daily['ma20']:.2f} ({zdf:+.2f}%)")
        # 大涨预警
        if zdf >= 8:
            alerts.append(f"🔥 {name}({code}) 大涨 {zdf:+.2f}% @{price:.2f}")
        # 大跌预警
        if zdf <= -5:
            alerts.append(f"⚠️ {name}({code}) 大跌 {zdf:+.2f}% @{price:.2f}")

    # 汇总信号
    all_sigs = breakouts + breakdowns + alerts + board_moves[:0]  # board已加入signals
    if not all_sigs:
        log(f"无触发信号（扫描{len(unique_pool)}只）")
        return

    # 构建推送内容（限制9000字符）
    content_lines = [f"# ⚡ 盘中监控 {now.strftime('%H:%M')}"]
    if board_moves:
        content_lines.append("\n## 📊 板块异动")
        for s in signals[:10]:
            content_lines.append(s)
    if breakouts:
        content_lines.append("\n## 🚀 突破信号")
        content_lines.extend(breakouts[:10])
    if breakdowns:
        content_lines.append("\n## 🛑 破位信号")
        content_lines.extend(breakdowns[:10])
    if alerts:
        content_lines.append("\n## ⚡ 异动预警")
        content_lines.extend(alerts[:15])
    content = "\n".join(content_lines)
    if len(content) > 9000:
        content = content[:9000] + "\n\n> ...（截断）"

    title = f"⚡盘中监控 {now.strftime('%H:%M')} ({len(breakouts)}突破/{len(breakdowns)}破位)"
    log(f"推送: {title}")
    results = push_message(title, content)
    for ch, ok in results:
        log(f"  {ch}: {'✅' if ok is True else ok}")

if __name__ == "__main__":
    main()
