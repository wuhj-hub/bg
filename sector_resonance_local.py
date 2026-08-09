#!/usr/bin/env python3
"""板块资金共振本地复算（sector_resonance_local）——替代黑石外部API（dmtlh登录），自成一体

对齐黑石板块因子口径，用 westock 本地数据复算：
  - 抢筹(GRAB)   = 主力当日净流入>0 且 加速（当日>5日均值）且 板块涨幅>1%
  - 进场(ENTRY)  = 当日主力净流转正 + 5日主力净流为正（资金开始流入）
  - 吸筹(ABSORP) = 主力5日净流入>0 且 散户净流出（机构进散户出）
  - 控盘(CONTROL)= 缩量（量能比<0.85）且 沉淀率>3%（筹码锁定）
  - 共振(RESON)  = 板块涨幅>0 且 至少2个资金因子触发
强度分 = 触发因子数×2 + 涨幅分（zdf>0:1, >2%:2, >4%:3）+ 沉淀分

用法: python3 sector_resonance_local.py [--top 30]
输出: outputs/板块共振_latest.json + outputs/板块共振对照_{date}.md
JSON 结构兼容旧黑石版（resonance_boards/grab_top/entry_top/absorption_top），盘前③.3直接读取
"""
import json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

WESTOCK = ["npx", "-y", "westock-data-skillhub@1.0.3"]
OUT_DIR = "outputs"


def run(args, timeout=90):
    for i in range(3):
        try:
            r = subprocess.run(WESTOCK + args, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        time.sleep(2)
    return ""


def parse_hot_board(txt):
    """hot board 输出：返回 [(pt代码, 板块名, 涨幅%)]，列序 index|level|symbol|rank|rankdelta|date|stock_type|name|zdf|zxj"""
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 9 and re.match(r"^pt\d+$", parts[2]):
            try:
                zdf = float(parts[8].rstrip("%"))
            except ValueError:
                zdf = 0.0
            out.append((parts[2], parts[7], zdf))
    return out


def parse_board_full(txt):
    """board 输出：返回 {板块名: {zdf, zdf5, zdf20, lead}} 列序 name|changePct|turnoverRate|changePct5d|changePct20d|leadStock"""
    out = {}
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 6 and parts[0] not in ("name", "---") and "---" not in parts[0]:
            try:
                out[parts[0]] = {"zdf": float(parts[1].rstrip("%")),
                                 "zdf5": float(parts[3].rstrip("%")),
                                 "zdf20": float(parts[4].rstrip("%")),
                                 "lead": parts[5]}
            except (ValueError, IndexError):
                continue
    return out


def parse_kline(txt):
    """批量板块kline：{pt代码: [(date, close, amount)...]} 降序(最新在前)"""
    out = {}
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) >= 8 and re.match(r"^pt\d+$", parts[0]) and parts[1] != "date":
            try:
                out.setdefault(parts[0], []).append((parts[1], float(parts[3]), float(parts[7])))
            except ValueError:
                continue
    return out


def parse_asfund(raw):
    """asfund 表头驱动解析：{列名: 值}"""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return {}
    header = [p.strip() for p in lines[0].strip("|").split("|")]
    for ln in reversed(lines[1:]):
        d = [p.strip() for p in ln.strip("|").split("|")]
        if len(d) == len(header):
            return dict(zip(header, d))
    return {}


def sector_factors(pt_code, name, zdf, board_info, kl_rows):
    """单板块三维因子复算。kl_rows: [(date, close, amount)...] 降序"""
    f = {"name": name, "code": pt_code, "zdf": zdf,
         "zdf5": board_info.get("zdf5") if board_info else None,
         "zdf20": board_info.get("zdf20") if board_info else None,
         "lead": board_info.get("lead") if board_info else None}
    row = parse_asfund(run(["asfund", pt_code]))
    if not row:
        return None
    try:
        m1 = float(row.get("MainNetFlow", 0) or 0)
        m5 = float(row.get("MainNetFlow5D", 0) or 0)
        m10 = float(row.get("MainNetFlow10D", 0) or 0)
        r_in = float(row.get("RetailInFlow", 0) or 0)
        r_out = float(row.get("RetailOutFlow", 0) or 0)
        retail = r_in - r_out
    except Exception:
        return None

    # 量能：今日 vs 5日均成交额
    vol_ratio = None
    if kl_rows and len(kl_rows) >= 6:
        amt_now = kl_rows[0][2]
        amt_5 = sum(a for _, _, a in kl_rows[1:6]) / 5
        if amt_5 > 0:
            vol_ratio = amt_now / amt_5
    f["vol_ratio"] = round(vol_ratio, 2) if vol_ratio else None
    # 沉淀率：5日主力净流 / 5日成交额
    precip = None
    if kl_rows and len(kl_rows) >= 6:
        amt_sum5 = sum(a for _, _, a in kl_rows[:6])
        if amt_sum5 > 0:
            precip = m5 / amt_sum5 * 100
    f["precip"] = round(precip, 2) if precip is not None else None

    # 资金因子
    grab = (m1 > 0 and abs(m1) > abs(m5) * 0.3 and zdf > 1)  # 当日加速流入+板块上涨
    entry = (m1 > 0 and m5 > 0)
    absor = (m5 > 0 and retail < 0)
    control = (vol_ratio is not None and vol_ratio < 0.85 and precip is not None and precip > 3)
    trigs = [k for k, v in {"抢筹": grab, "进场": entry, "吸筹": absor, "控盘": control}.items() if v]
    resonance = (zdf > 0 and len(trigs) >= 2)

    f["factors"] = trigs
    f["resonance"] = resonance
    # 强度分
    zdf_score = 1 if zdf > 0 else (2 if zdf > 2 else (3 if zdf > 4 else 0))
    f["strength"] = len(trigs) * 2 + zdf_score + (1 if precip is not None and precip > 3 else 0)
    f["main_net_1d"] = round(m1 / 1e8, 1)
    f["main_net_5d"] = round(m5 / 1e8, 1)
    f["retail_net"] = round(retail / 1e8, 1)
    return f


def main():
    top_n = 30
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--top" and i + 1 < len(argv):
            top_n = int(argv[i + 1])

    # 1. 板块池：hot board TOP（含pt代码）+ board 全板块（涨幅/5日/20日/领涨）
    hot = parse_hot_board(run(["hot", "board", "--limit", str(top_n)]))
    board_map = parse_board_full(run(["board"]))
    print(f"[INFO] hot板块 {len(hot)} 个 | board全板块 {len(board_map)} 个", flush=True)

    # 2. 板块K线批量（量能）
    codes = [c for c, _, _ in hot]
    kl = parse_kline(run(["kline", ",".join(codes), "--period", "day", "--limit", "25"]) if codes else "")
    print(f"[INFO] 板块K线 {len(kl)} 个", flush=True)

    # 3. 逐板块 asfund（并发）
    def work(item):
        c, nm, zdf = item
        info = board_map.get(nm)
        return sector_factors(c, nm, zdf, info, kl.get(c, []))

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for f in ex.map(work, hot):
            if f:
                results.append(f)
    print(f"[INFO] 板块因子复算成功 {len(results)}/{len(hot)}", flush=True)

    res_boards = [r for r in results if r["resonance"]]
    res_boards.sort(key=lambda r: -r["strength"])
    grab_top = sorted([r for r in results if "抢筹" in r["factors"]], key=lambda r: -r["strength"])[:10]
    entry_top = sorted([r for r in results if "进场" in r["factors"]], key=lambda r: -r["main_net_5d"])[:10]
    abs_top = sorted([r for r in results if "吸筹" in r["factors"]], key=lambda r: -r["precip"] if r["precip"] else 0)[:10]
    ctl_top = sorted([r for r in results if "控盘" in r["factors"]], key=lambda r: -r["precip"] if r["precip"] else 0)[:10]

    today = datetime.now().strftime("%Y-%m-%d")
    js = {
        "date": today, "source": "local(westock复算·自成一体)",
        "resonance_boards": [{"name": r["name"], "code": r["code"], "zdf": r["zdf"], "strength": r["strength"],
                              "factors": r["factors"]} for r in res_boards],
        "grab_top": [{"name": r["name"], "code": r["code"], "value": r["strength"]} for r in grab_top],
        "entry_top": [{"name": r["name"], "code": r["code"], "value": r["main_net_5d"]} for r in entry_top],
        "absorption_top": [{"name": r["name"], "code": r["code"], "value": r["precip"] if r["precip"] else 0} for r in abs_top],
        "control_top": [{"name": r["name"], "code": r["code"], "value": r["precip"] if r["precip"] else 0} for r in ctl_top],
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "板块共振_latest.json")
    open(json_path, "w", encoding="utf-8").write(json.dumps(js, ensure_ascii=False, indent=1))

    # 报告
    L = [f"# 🧭 板块资金共振（本地复算） {today}", "",
         f"> 数据源：westock 本地复算（board涨幅 + 板块asfund资金 + 板块kline量能），无外部API依赖",
         f"> 因子：抢筹(主力加速+涨) / 进场(当日+5日净流转正) / 吸筹(主力进散户出) / 控盘(缩量高沉淀) / 共振(涨幅>0且≥2因子)", ""]
    L.append(f"## 一、板块共振信号（{len(res_boards)} 个）")
    L.append("| 板块 | 涨幅% | 5日% | 强度 | 触发因子 | 5D主力(亿) | 沉淀率% |")
    L.append("|---|---|---|---|---|---|---|")
    for r in res_boards:
        L.append(f"| {r['name']} | {r['zdf']} | {r['zdf5'] if r['zdf5'] is not None else '—'} | {r['strength']} | {'/'.join(r['factors'])} | {r['main_net_5d']} | {r['precip'] if r['precip'] is not None else '—'} |")
    L.append("")
    L.append("## 二、抢筹TOP（资金加速流入）")
    L.append("| 板块 | 涨幅% | 强度 | 5D主力(亿) | 沉淀率% |")
    L.append("|---|---|---|---|---|")
    for r in grab_top:
        L.append(f"| {r['name']} | {r['zdf']} | {r['strength']} | {r['main_net_5d']} | {r['precip'] if r['precip'] is not None else '—'} |")
    L.append("")
    L.append("## 三、进场TOP（资金开始流入）")
    L.append("| 板块 | 涨幅% | 5D主力(亿) | 沉淀率% |")
    L.append("|---|---|---|---|")
    for r in entry_top:
        L.append(f"| {r['name']} | {r['zdf']} | {r['main_net_5d']} | {r['precip'] if r['precip'] is not None else '—'} |")
    L.append("")
    L.append("## 四、吸筹TOP（机构进散户出）")
    L.append("| 板块 | 涨幅% | 5D主力(亿) | 散户净流(亿) | 沉淀率% |")
    L.append("|---|---|---|---|---|")
    for r in abs_top:
        L.append(f"| {r['name']} | {r['zdf']} | {r['main_net_5d']} | {r['retail_net']} | {r['precip'] if r['precip'] is not None else '—'} |")
    L.append("")
    md_path = os.path.join(OUT_DIR, f"板块共振对照_{today}.md")
    open(md_path, "w", encoding="utf-8").write("\n".join(L))
    print(f"[OK] {json_path}")
    print(f"[OK] {md_path}")
    print(f"共振板块 {len(res_boards)} | 抢筹 {len(grab_top)} | 进场 {len(entry_top)} | 吸筹 {len(abs_top)} | 控盘 {len(ctl_top)}")


if __name__ == "__main__":
    main()
