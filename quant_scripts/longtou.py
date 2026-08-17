#!/usr/bin/env python3
"""
longtou.py —— 龙头战法模块 v1.0（五维定位 + 梯队跟踪 + 见顶预警）
================================================================
基于龙头战法体系（五维模板）：
  ① 题材逻辑(板块热度) ② 资金筹码(资金四层+龙虎榜机构) ③ 盘面地位(连板梯队)
  ④ 技术形态(量价/突破) ⑤ 风控确认(断板/止损)

梯队定位:
  总龙头    = 全市场最高连板（封单/辨识度最高）
  板块龙头  = 板块内最高连板
  中军      = 板块内成交额最大且非涨停（趋势核心）
  跟风龙    = 板块内低连板跟涨
  杂毛      = 识别后排蹭热度（标注回避）

见顶五维预警:
  ①量价背离(指数新高量缩) ②龙头崩塌(高位巨量开板/天地板) ③轮动散乱(热点<3天) ⑤散户亢奋(人工)

用法: python3 longtou.py [--limit N]
输出: outputs/龙头定位_{date}.md + longtou_pool.txt + 见顶预警(PushPlus)
================================================================
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BJ = timezone(timedelta(hours=8))
WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
BATCH = 20
KLIMIT = 6
WORKERS = 4

def cli(cmd, timeout=180):
    full = WESTOCK + cmd.split()
    for attempt in range(5):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            if r.stdout.strip() and "执行失败" not in r.stdout and "SKILL_0" not in r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""

def fetch_batch(symbols):
    md = cli(f"kline {','.join(symbols)} --period day --limit {KLIMIT} --fq qfq")
    groups = {}
    has_symbol = "| symbol |" in md
    for ln in md.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 9:
            continue
        try:
            if has_symbol:
                if parts[0] in ("symbol", "---"):
                    continue
                # 批量: | symbol | date | open | last | high | low | volume | amount | exchange |
                sym, d, o, c, h, l, amt = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[7]
            else:
                # 单股: | date | open | last | high | low | volume | amount | exchange |
                if not re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                    continue
                sym, d, o, c, h, l, amt = symbols[0], parts[0], parts[1], parts[2], parts[3], parts[4], parts[6]
            groups.setdefault(sym, []).append(
                {"date": d, "open": float(o), "close": float(c), "high": float(h),
                 "low": float(l), "amount": float(amt)})
        except (ValueError, IndexError):
            continue
    for sym in groups:
        groups[sym].sort(key=lambda x: x["date"])
    return groups

def fetch_asfund_lhb(symbol):
    """龙虎榜机构净买（亿）"""
    out = cli(f"asfund {symbol}")
    for ln in out.splitlines():
        s = ln.strip()
        if not s.startswith("|") or "LhbTradingDetails" in s:
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 10:
            continue
        try:
            detail = parts[9]
            inst_net = None
            if detail and detail != "-":
                inst_buy = inst_sell = 0.0
                try:
                    parsed = json.loads(detail)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if "机构专用" in str(item.get("Name", "")):
                                inst_buy += float(item.get("Buy") or 0)
                                inst_sell += float(item.get("Sell") or 0)
                except Exception:
                    parsed = None
                if inst_buy or inst_sell:
                    inst_net = round((inst_buy - inst_sell) / 1e8, 2)
            flow = float(parts[14]) / 1e8 if len(parts) > 14 else 0
            return {"inst_net": inst_net, "flow": round(flow, 2)}
        except (ValueError, IndexError, json.JSONDecodeError):
            continue
    return None

# ============================================================
def analyze_stock(sym, bars, name=""):
    """计算连板/涨幅/成交额/量价"""
    if len(bars) < 3:
        return None
    cur = bars[-1]
    prev = bars[-2]
    if prev["close"] <= 0:
        return None
    chg = (cur["close"] - prev["close"]) / prev["close"] * 100
    # 连板（从最新往回数涨停）
    boards = 0
    for i in range(len(bars) - 1, 0, -1):
        if bars[i]["close"] / bars[i - 1]["close"] >= 1.097:
            boards += 1
        else:
            break
    # 是否涨停（今日）
    is_zt = bars[-1]["close"] / bars[-2]["close"] >= 1.097
    # 量比（今日量 vs 前5日均量近似用amount）
    amt = cur["amount"] / 1e8
    amt_prev = sum(b["amount"] for b in bars[-6:-1]) / 5 / 1e8 if len(bars) >= 6 else amt
    vol_ratio = amt / amt_prev if amt_prev > 0 else 1
    # 天地板检测（今高接近涨停但收绿）
    tian_di = False
    if len(bars) >= 2:
        hi = cur["high"]
        lo = cur["low"]
        prev_c = prev["close"]
        if hi >= prev_c * 1.097 and cur["close"] < prev_c:  # 触及涨停但收阴
            tian_di = True
    return {"code": sym, "name": name, "close": cur["close"], "chg": round(chg, 2),
            "boards": boards, "is_zt": is_zt, "amount": round(amt, 2),
            "vol_ratio": round(vol_ratio, 1), "tian_di": tian_di,
            "open_board": is_zt and cur["high"] > cur["close"] * 1.001}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    date_str = datetime.now(BJ).strftime("%Y-%m-%d")

    pool = []
    with open("/sandbox/workspace/all_mainboard.csv", encoding="utf-8-sig") as f:
        next(f)
        for ln in f:
            parts = ln.strip().split(",")
            if len(parts) >= 2:
                code = parts[0].strip()
                if code.startswith(("688", "300", "301")) or "ST" in parts[1].upper() or "退" in parts[1]:
                    continue
                pool.append(("sh" + code if code.startswith("6") else "sz" + code, parts[1].strip()))
    if args.limit:
        pool = pool[:args.limit]
    print(f"[INFO] {date_str} 龙头定位扫描: {len(pool)} 只", flush=True)

    # Step1: 全市场数据
    bars_map = {}
    syms = [c for c, _ in pool]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for i in range(0, len(syms), BATCH):
            futs[ex.submit(fetch_batch, syms[i:i + BATCH])] = 1
        done = 0
        for f in as_completed(futs):
            for k, v in f.result().items():
                if len(v) >= 4:
                    bars_map[k] = v
            done += 1
            if done % 15 == 0:
                print(f"  [进度] {done}/{len(futs)} 批", flush=True)
    stats = {}
    for code, name in pool:
        r = analyze_stock(code, bars_map.get(code, []), name)
        if r:
            stats[code] = r
    print(f"[INFO] 有效 {len(stats)} 只", flush=True)

    # Step2: 梯队定位
    zt_stocks = {c: s for c, s in stats.items() if s["is_zt"]}
    max_boards = max((s["boards"] for s in zt_stocks.values()), default=0)
    # 总龙头：最高连板且成交额最大者（并列取辨识度）
    zong = [s for s in zt_stocks.values() if s["boards"] == max_boards and max_boards >= 2]
    zong.sort(key=lambda s: -s["amount"])
    # 中军候选：未涨停但成交额前30 + 涨幅温和
    jun_cand = sorted([s for s in stats.values() if not s["is_zt"]], key=lambda s: -s["amount"])[:30]
    # 跟风：涨停但连板=1 且成交额较小
    gen = [s for s in zt_stocks.values() if s["boards"] == 1]

    # Step3: 板块归属（board 行业涨幅榜 leadStock → 名称匹配全市场）
    hot = cli("board")
    sector_lead = {}  # 板块名 -> 领涨股名
    sector_rank = {}  # 板块名 -> 排名（顺序）
    _rk = 0
    for ln in hot.splitlines():
        s = ln.strip()
        if not s.startswith("|") or "leadStock" in s or "---" in s:
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 6:
            _rk += 1
            name = parts[0]
            lead = parts[5]
            m = re.search(r"([\u4e00-\u9fffA-Za-z]+)\((\d+\.?\d*)\)", lead)
            if m:
                sector_lead[name] = m.group(1)
                sector_rank[name] = _rk
    # 名称 → 代码映射（all_mainboard）
    name2code = {n.replace(" ", ""): c for c, n in pool}
    # 涨停股板块归属：领涨股名匹配
    for code, st in zt_stocks.items():
        nm = st["name"].replace(" ", "")
        for sec, lead in sector_lead.items():
            if lead.replace(" ", "") == nm:
                st["sector"] = sec
                st["sector_rank"] = sector_rank.get(sec, 99)
                break
        else:
            st["sector"] = ""
            st["sector_rank"] = 99
    # 板块龙头：板块内涨停股中连板最高者
    sector_boss = {}
    for code, st in zt_stocks.items():
        if st.get("sector"):
            sec = st["sector"]
            if sec not in sector_boss or st["boards"] > sector_boss[sec]["boards"]:
                sector_boss[sec] = st
    # 中军补充板块标注
    for st in jun_cand:
        nm = st["name"].replace(" ", "")
        st["sector"] = next((sec for sec, lead in sector_lead.items() if lead.replace(" ", "") == nm), "")

    # Step3.5: 机构锁仓识别（高连板梯队拉龙虎榜）
    print("[INFO] 高连板机构龙虎榜检查...", flush=True)
    gaolb_tmp = [s for s in zt_stocks.values() if s["boards"] >= 2]
    for s in gaolb_tmp:
        f = fetch_asfund_lhb(s["code"])
        s["inst_net"] = f["inst_net"] if f else None
        s["main_flow"] = f["flow"] if f else None
        s["inst_tag"] = "🏛️机构" if f and f["inst_net"] and f["inst_net"] > 0 else ""
        time.sleep(0.5)
    print(f"  机构龙虎榜完成 {len(gaolb_tmp)} 只")

    # Step4: 五维评分（简版：连板+量比+成交额+炸板）
    def score5(s):
        sc = 0
        sc += min(s["boards"], 7) * 10          # 盘面地位
        sc += min(s["vol_ratio"], 5) * 4         # 资金量能
        sc += min(s["amount"] / 5, 4) * 3        # 成交额(亿)
        if s["tian_di"]:
            sc -= 30
        if s["open_board"]:
            sc -= 10
        return sc
    for s in stats.values():
        s["score5"] = score5(s)

    # 输出
    os.makedirs("/sandbox/workspace/outputs", exist_ok=True)
    L = [f"# 🐲 龙头定位 {date_str}\n",
         f"**扫描**: {len(pool)} 只 | **涨停**: {len(zt_stocks)} | **最高连板**: {max_boards} 板\n"]
    # 总龙头
    L.append(f"\n## 👑 总龙头（{len(zong)}只）\n")
    if zong:
        L.append("| 代码 | 名称 | 连板 | 涨幅% | 成交亿 | 量比 | 五维分 |")
        L.append("|------|------|:---:|:---:|:---:|:---:|:---:|")
        for s in zong[:5]:
            L.append(f"| {s['code']} | {s['name']} | **{s['boards']}板** | {s['chg']:+.1f} | {s['amount']} | {s['vol_ratio']} | {s['score5']} |")
    # 高连板梯队（2板+）
    gaolb = sorted([s for s in zt_stocks.values() if s["boards"] >= 2], key=lambda s: (-s["boards"], -s["amount"]))
    L.append(f"\n## 🏆 高连板梯队（2板以上 {len(gaolb)}只）\n")
    if gaolb:
        L.append("| 代码 | 名称 | 连板 | 涨幅% | 成交亿 | 量比 | 板块 | 机构 | 五维分 |")
        L.append("|------|------|:---:|:---:|:---:|:---:|------|:---:|:---:|")
        for s in gaolb[:20]:
            L.append(f"| {s['code']} | {s['name']} | {s['boards']}板 | {s['chg']:+.1f} | {s['amount']} | {s['vol_ratio']} | {s.get('sector','')} | {s.get('inst_tag','')} | {s['score5']} |")
    # 板块龙头表
    L.append(f"\n## 🗂️ 板块龙头（{len(sector_boss)}个板块）\n")
    if sector_boss:
        L.append("| 板块 | 龙头 | 代码 | 连板 | 板块热度排名 |")
        L.append("|------|------|------|:---:|:---:|")
        for sec, st in sorted(sector_boss.items(), key=lambda x: x[1].get("sector_rank", 99))[:12]:
            L.append(f"| {sec} | {st['name']} | {st['code']} | {st['boards']}板 | {st.get('sector_rank','-')} |")
    # 中军
    L.append(f"\n## 🏛️ 中军候选（成交额TOP30非涨停·趋势核心）\n")
    L.append("| 代码 | 名称 | 涨幅% | 成交亿 | 量比 | 五维分 |")
    L.append("|------|------|:---:|:---:|:---:|:---:|")
    for s in jun_cand[:15]:
        L.append(f"| {s['code']} | {s['name']} | {s['chg']:+.1f} | {s['amount']} | {s['vol_ratio']} | {s['score5']} |")
    # 跟风
    L.append(f"\n## 🌬️ 跟风首板（{len(gen)}只，仅列成交额前15）\n")
    gen.sort(key=lambda s: -s["amount"])
    for s in gen[:15]:
        L.append(f"- {s['code']} {s['name']} 首板 {s['chg']:+.1f}% 成交{s['amount']}亿")
    # 见顶预警（含量价背离）
    L.append(f"\n## ⚠️ 见顶五维预警\n")
    warns = []
    # ① 量价背离：指数创新高但缩量
    try:
        idx = cli("kline sh000001 --period day --limit 6 --fq qfq")
        idx_rows = []
        for ln in idx.splitlines():
            s = ln.strip()
            if not s.startswith("|") or "date" in s or "---" in s:
                continue
            parts = [p.strip() for p in s.strip("|").split("|")]
            if re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
                try:
                    idx_rows.append({"d": parts[0], "c": float(parts[2]), "v": float(parts[5])})
                except ValueError:
                    continue
        if len(idx_rows) >= 3:
            last, prev = idx_rows[-1], idx_rows[-2]
            if last["c"] >= max(r["c"] for r in idx_rows[:-1]) and last["v"] < prev["v"] * 0.9:
                warns.append(f"①量价背离：指数创{len(idx_rows)-1}日新高但缩量({last['v']/1e8:.0f}亿 vs 前日{prev['v']/1e8:.0f}亿)")
    except Exception:
        pass
    if zong and any(s["tian_di"] or s["open_board"] for s in zong):
        warns.append("②龙头崩塌：总龙头开板/天地板")
    lb_2plus = sum(1 for s in zt_stocks.values() if s["boards"] >= 2)
    if lb_2plus <= 3:
        warns.append("连板梯队高度压缩（2板以上≤3只）→ 情绪冰点征兆")
    for s in zt_stocks.values():
        if s["tian_di"]:
            warns.append(f"天地板：{s['code']} {s['name']}")
    L.append("\n".join(f"- {w}" for w in warns) if warns else "- 暂无明显见顶信号")
    report = "\n".join(L)
    md_path = f"/sandbox/workspace/outputs/龙头定位_{date_str}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)
    # 跟踪池
    with open("/sandbox/workspace/longtou_pool.txt", "w", encoding="utf-8") as f:
        f.write(f"# 龙头池 {date_str}\n")
        for s in (zong + gaolb[:10] + jun_cand[:10]):
            f.write(f"{s['code']} # {s['name']}（{s['boards']}板/{s['score5']}分）\n")
    print(report[:2500])
    print(f"\n[OK] 报告: {md_path}")
    with open(f"/sandbox/workspace/outputs/龙头定位_{date_str}.json", "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "zong": zong, "gaolb": gaolb[:20], "jun": jun_cand[:15],
                   "gen": gen[:15], "warns": warns}, f, ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
