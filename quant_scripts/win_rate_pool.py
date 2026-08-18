#!/usr/bin/env python3
"""
win_rate_pool.py —— 五大股池周度胜率汇总
====================================================
统计各股池历史信号至今的胜率/收益，判断哪些信号真正有效。

数据源:
  ① outputs/*.json 各股池历史信号（信号日收盘价在JSON内）
  ② westock 批量K线拉当前价

输出: outputs/股池胜率汇总_{date}.md + PushPlus推送
用法: python3 win_rate_pool.py
====================================================
"""
import subprocess, sys, os, re, json, glob, time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BJ = timezone(timedelta(hours=8))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]

def cli(cmd, timeout=120):
    full = WESTOCK + cmd.split()
    for attempt in range(3):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            if r.stdout.strip() and "执行失败" not in r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""

def fetch_price_on_date(code, date_str):
    """拉K线找指定日期收盘价（一统天下JSON无价格字段）"""
    md = cli(f"kline {code} --period day --limit 60 --fq qfq")
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        try:
            if len(parts) >= 4 and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]) and parts[0] == date_str:
                return float(parts[2])
        except ValueError:
            continue
    return None

def fetch_latest(symbols):
    """批量拉最新收盘 → {code: price}"""
    out = {}
    for i in range(0, len(symbols), 20):
        md = cli(f"kline {','.join(symbols[i:i+20])} --period day --limit 2 --fq qfq")
        has_symbol = "| symbol |" in md
        for ln in md.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            try:
                if has_symbol:
                    if parts[0] in ("symbol", "---"):
                        continue
                    out[parts[0]] = float(parts[3])  # 最新收盘
                else:
                    if not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                        continue
                    out[symbols[i]] = float(parts[2])
            except (ValueError, IndexError):
                continue
    return out

def collect_signals():
    """从各股池JSON收集信号 → {pool: [(code, name, date, price, tag)]}"""
    signals = {}
    os.makedirs("/sandbox/workspace/outputs", exist_ok=True)
    out_dir = "/sandbox/workspace/outputs"

    # 才哥战法（8/13, 8/14...）
    for f in sorted(glob.glob(f"{out_dir}/才哥战法股池_*.json")):
        m = re.search(r"_(\d{4}-\d{2}-\d{2})", f)
        date = m.group(1) if m else "?"
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for tname, sigs in d.get("results", {}).items():
            for s in sigs:
                signals.setdefault("才哥战法", []).append(
                    (s.get("code"), s.get("name", ""), date, s.get("close", s.get("price", 0)), tname))
    # 一统天下
    for f in sorted(glob.glob(f"{out_dir}/一统天下建仓区股池_*.json")):
        m = re.search(r"_(\d{4}-\d{2}-\d{2})", f)
        date = m.group(1) if m else "?"
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for s in d.get("results", []):
            entry = s.get("entry", date)
            price = s.get("close") or s.get("price") or 0
            signals.setdefault("一统天下", []).append(
                (s.get("code"), s.get("name", ""), entry, price,
                 f"{'★'*s.get('stars',3)}建仓"))
    # 妖股池
    for f in sorted(glob.glob(f"{out_dir}/妖股池_*.json")):
        m = re.search(r"_(\d{4}-\d{2}-\d{2})", f)
        date = m.group(1) if m else "?"
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for s in d.get("candidates", []):
            signals.setdefault("妖股池", []).append(
                (s.get("code"), s.get("name", ""), date, s.get("price", 0), s.get("level", "")))
    # 龙头定位
    for f in sorted(glob.glob(f"{out_dir}/龙头定位_*.json")):
        m = re.search(r"_(\d{4}-\d{2}-\d{2})", f)
        date = m.group(1) if m else "?"
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for grp in ("zong", "gaolb"):
            for s in d.get(grp, []):
                tag = "总龙头" if grp == "zong" else "高连板"
                signals.setdefault("龙头定位", []).append(
                    (s.get("code"), s.get("name", ""), date, s.get("close", 0), tag))
    return signals

def collect_system_signals():
    """从GitHub quant_results_latest 提取双弦/鱼身/猛兽信号（8/13）"""
    import base64, urllib.request
    signals = {}
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/wuhj-hub/bg/contents/quant_results_latest.json",
            headers={"Authorization": "token " + os.environ.get("GITHUB_TOKEN", "")} if os.environ.get("GITHUB_TOKEN") else {})
        d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        j = json.loads(base64.b64decode(d["content"]).decode())
        date = j.get("date", "?")
        # 双弦池
        for e in j.get("shuangxian", {}).get("pool_data", {}).get("entries", []):
            signals.setdefault("双弦月度池", []).append(
                (e.get("code"), e.get("name", ""), e.get("date_str", date), e.get("price", 0),
                 f"共振{e.get('score','')}分"))
        # 鱼身信号（stdout 正则）
        fs = j.get("fishbody", {}).get("stdout", "")
        for m in re.finditer(r"#\d+\s+(sh\d{6}|sz\d{6})\s+(\S+)\s+\d+分\s+现价([\d.]+)", fs):
            signals.setdefault("鱼身信号", []).append(
                (m.group(1), m.group(2), date, float(m.group(3)), "鱼身模式"))
    except Exception as e:
        print("[WARN] 三系统数据拉取失败:", e)
    # 猛兽领先股（8/13 知识库提取，价格按日期补）
    beast = [("sz000802", "北京文化", "领先66分"), ("sh603259", "药明康德", "领先51分"),
             ("sh600721", "百花医药", "领先50分"), ("sz001258", "立新能源", "领先48分"),
             ("sh605179", "一鸣食品", "领先46分"), ("sz002400", "省广集团", "领先41分"),
             ("sh600664", "哈药股份", "回调53分"), ("sz000938", "紫光股份", "回调50分")]
    for code, name, tag in beast:
        signals.setdefault("猛兽股池", []).append((code, name, "2026-08-13", 0, tag))
    return signals

def main():
    date_str = datetime.now(BJ).strftime("%Y-%m-%d")
    signals = collect_signals()
    for k, v in collect_system_signals().items():
        signals.setdefault(k, []).extend(v)
    # 去重：同池同code取最早信号
    all_codes = set()
    for pool, lst in signals.items():
        seen = {}
        for code, name, d, price, tag in lst:
            if code not in seen or d < seen[code][0]:
                seen[code] = (d, name, price, tag)
        signals[pool] = [(c, v[1], v[0], v[2], v[3]) for c, v in seen.items()]
        all_codes.update(seen.keys())
    print(f"[INFO] 信号汇总: " + " | ".join(f"{k}={len(v)}" for k, v in signals.items()))
    print(f"[INFO] 拉取当前价 {len(all_codes)} 只...", flush=True)
    latest = fetch_latest(sorted(all_codes))
    print(f"[INFO] 当前价完成 {len(latest)} 只")

    L = [f"# 📊 五大股池周度胜率汇总 {date_str}\n",
         f"> 统计各股池历史信号（信号日收盘价→最新收盘）\n"]
    order = ["才哥战法", "一统天下", "妖股池", "龙头定位", "双弦月度池", "鱼身信号", "猛兽股池"]
    for pool in order:
        lst = signals.get(pool, [])
        rets = []
        detail = []
        for code, name, d, price, tag in lst:
            cur = latest.get(code)
            if not cur:
                continue
            if not price:
                price = fetch_price_on_date(code, d)
                if not price:
                    continue
            r = (cur - price) / price * 100
            rets.append(r)
            detail.append((code, name, d, tag, round(r, 1)))
        L.append(f"\n## {pool}（样本 {len(rets)}）\n")
        if not rets:
            L.append("📭 无有效样本")
            continue
        win = sum(1 for x in rets if x > 0)
        avg = sum(rets) / len(rets)
        gains = [x for x in rets if x > 0]
        losses = [x for x in rets if x <= 0]
        pl = (sum(gains)/len(gains))/abs(sum(losses)/len(losses)) if gains and losses else 0
        L.append(f"| 指标 | 值 |")
        L.append(f"|------|----|")
        L.append(f"| 胜率 | **{win/len(rets)*100:.1f}%** ({win}/{len(rets)}) |")
        L.append(f"| 平均收益 | {avg:+.2f}% |")
        L.append(f"| 盈亏比 | {pl:.2f} |")
        L.append(f"| 最佳 | {max(rets):+.1f}% | 最差 | {min(rets):+.1f}% |")
        detail.sort(key=lambda x: -x[4])
        L.append(f"\n明细（按收益排序）:")
        L.append("| 代码 | 名称 | 信号日 | 类型 | 收益% |")
        L.append("|------|------|--------|------|------|")
        for c, n, dd, tg, r in detail:
            mark = "🟢" if r > 0 else "🔴"
            L.append(f"| {c} | {n} | {dd} | {tg} | {mark} {r:+.1f} |")
    report = "\n".join(L)
    path = f"/sandbox/workspace/outputs/股池胜率汇总_{date_str}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n[OK] 报告: {path}")
    # 推送
    try:
        import urllib.request, urllib.parse
        tok = os.environ.get("PUSH_TOKEN", "")
        if tok:
            body = urllib.parse.urlencode({"token": tok, "title": f"📊股池胜率汇总 {date_str}",
                                           "content": report[:4000], "template": "markdown"}).encode()
            urllib.request.urlopen(urllib.request.Request("https://pushplus.plus/send", data=body), timeout=15)
            print("[push] 已推送")
    except Exception as e:
        print("[push] 失败:", e)

if __name__ == "__main__":
    main()
