#!/usr/bin/env python3
"""板块资金共振本地复算 v2（sector_resonance_local）——独立口径，无外部API依赖

板块池：board 全行业+概念涨幅榜 + 板块资金流榜 合并（~36个），叠加 hot board 60 板块代码映射
数据源：westock board（三段：行业涨幅/概念涨幅/资金流）+ hot board（pt代码）+ 板块asfund（散户）+ 板块kline（量能）

独立口径因子（不再声明对齐黑石，自成一体）：
  抢筹 = 当日主力净流入>0 且 5日净流加速（当日>5日均值×0.3）且 板块涨幅>1%
  进场 = 当日主力净流转正 + 5日主力净流为正
  吸筹 = 5日主力净流入>0 且 散户净流出（机构进散户出，asfund口径）
  控盘 = 缩量（量能比<0.85）且 沉淀率>3%
  共振 = 板块涨幅>0 且 ≥2个资金因子触发
强度分 = 因子数×2 + 涨幅分(0-3) + 沉淀加分(1)

用法: python3 sector_resonance_local.py [--top 60]
输出: outputs/板块共振_latest.json + outputs/板块共振对照_{date}.md
JSON结构兼容旧黑石版（resonance_boards/grab_top/entry_top/absorption_top），盘前③.3直接读取
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
    """hot board：返回 {板块名: (pt代码, 涨幅%)}，列序 index|level|symbol|rank|rankdelta|date|stock_type|name|zdf|zxj"""
    out = {}
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
            out[parts[7]] = (parts[2], zdf)
    return out


def parse_board_full(txt):
    """board 三段解析：
    段1/2 行业+概念涨幅: name|changePct|turnoverRate|changePct5d|changePct20d|leadStock
    段3 资金流:          name|changePct|mainNetInflow|mainNetInflow5d|upDownRatio
    返回 {name: {...}}，资金段字段覆盖式合并
    """
    out = {}
    for ln in txt.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [p.strip() for p in s.strip("|").split("|")]
        if len(parts) < 5 or parts[0] in ("name", "---") or "---" in parts[0]:
            continue
        try:
            if len(parts) >= 6 and parts[1] != "---" and "changePct" not in parts[1]:
                out.setdefault(parts[0], {})["zdf"] = float(parts[1].rstrip("%"))
                out[parts[0]]["zdf5"] = float(parts[3].rstrip("%"))
                out[parts[0]]["zdf20"] = float(parts[4].rstrip("%"))
                out[parts[0]]["lead"] = parts[5]
            elif len(parts) >= 5 and parts[1] != "---" and "changePct" not in parts[1]:
                out.setdefault(parts[0], {})["zdf"] = float(parts[1].rstrip("%"))
                out[parts[0]]["main_in"] = float(parts[2]) / 1e4  # 万→亿
                out[parts[0]]["main_in5d"] = float(parts[3]) / 1e4
                out[parts[0]]["updown"] = parts[4]
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


def sector_factors(name, info, pt_code, retail_net, kl_rows):
    """单板块因子。info含 zdf/zdf5/main_in/main_in5d/lead；retail_net=散户净流(亿)或None；kl_rows降序"""
    f = {"name": name, "code": pt_code or "", "zdf": info.get("zdf", 0),
         "zdf5": info.get("zdf5"), "lead": info.get("lead")}
    m1 = info.get("main_in", 0) or 0
    m5 = info.get("main_in5d", 0) or 0
    f["main_net_1d"] = round(m1, 1)
    f["main_net_5d"] = round(m5, 1)

    vol_ratio = precip = None
    if kl_rows and len(kl_rows) >= 6:
        amt_now = kl_rows[0][2]
        amt_5 = sum(a for _, _, a in kl_rows[1:6]) / 5
        if amt_5 > 0:
            vol_ratio = amt_now / amt_5
        amt_sum5 = sum(a for _, _, a in kl_rows[:6])
        if amt_sum5 > 0:
            precip = m5 * 1e8 / amt_sum5 * 100
    f["vol_ratio"] = round(vol_ratio, 2) if vol_ratio else None
    f["precip"] = round(precip, 2) if precip is not None else None

    # 独立口径因子
    grab = (m1 > 0 and m5 > 0 and abs(m1) > abs(m5) * 0.3 and info.get("zdf", 0) > 1)
    entry = (m1 > 0 and m5 > 0)
    absor = (m5 > 0 and retail_net is not None and retail_net < 0)
    control = (vol_ratio is not None and vol_ratio < 0.85 and precip is not None and precip > 3)
    trigs = [k for k, v in {"抢筹": grab, "进场": entry, "吸筹": absor, "控盘": control}.items() if v]
    resonance = (info.get("zdf", 0) > 0 and len(trigs) >= 2)

    f["factors"] = trigs
    f["resonance"] = resonance
    zdf_s = 1 if info.get("zdf", 0) > 0 else (2 if info.get("zdf", 0) > 2 else (3 if info.get("zdf", 0) > 4 else 0))
    f["strength"] = len(trigs) * 2 + zdf_s + (1 if precip is not None and precip > 3 else 0)
    f["retail_net"] = round(retail_net, 1) if retail_net is not None else None
    return f


def main():
    top_n = 60
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--top" and i + 1 < len(argv):
            top_n = int(argv[i + 1])

    # 1. 板块池：board 三段（行业+概念+资金流，含资金/5日/20日/领涨）+ hot board（代码+涨幅）合并
    board_map = parse_board_full(run(["board"]))
    hot_map = parse_hot_board(run(["hot", "board", "--limit", str(top_n)]))
    pool = {}
    for nm, info in board_map.items():
        pool.setdefault(nm, {}).update(info)
    for nm, (pt, zdf) in hot_map.items():
        pool.setdefault(nm, {})["pt"] = pt
        pool[nm].setdefault("zdf", zdf)
    coded = [(nm, info, info.get("pt", "")) for nm, info in pool.items() if info.get("pt")]
    print(f"[INFO] 板块池 {len(pool)} 个（board {len(board_map)} + hot {len(hot_map)}，含代码 {len(coded)}）", flush=True)

    # 2. 有代码的板块：kline 量能 + asfund（资金补充+散户）
    kl = parse_kline(run(["kline", ",".join(c for _, _, c in coded), "--period", "day", "--limit", "25"]) if coded else "")

    def fetch_asfund(code):
        row = parse_asfund(run(["asfund", code]))
        if not row:
            return None
        try:
            r_in = float(row.get("RetailInFlow", 0) or 0)
            r_out = float(row.get("RetailOutFlow", 0) or 0)
            return {"retail": (r_in - r_out) / 1e8,
                    "main1": float(row.get("MainNetFlow", 0) or 0) / 1e8,
                    "main5": float(row.get("MainNetFlow5D", 0) or 0) / 1e8}
        except Exception:
            return None

    fund_map = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_asfund, c): nm for nm, _, c in coded}
        for f in futs:
            try:
                fund_map[futs[f]] = f.result()
            except Exception:
                pass

    # 3. 因子计算：资金优先 board 段3（main_in/main_in5d），hot 独有用 asfund 补充
    results = []
    for nm, info in pool.items():
        fd = fund_map.get(nm) or {}
        if "main_in" not in info and fd.get("main1") is not None:
            info["main_in"] = fd["main1"]
            info["main_in5d"] = fd.get("main5", 0)
        f = sector_factors(nm, info, info.get("pt", ""), fd.get("retail"), kl.get(info.get("pt", ""), []))
        if f:
            results.append(f)
    print(f"[INFO] 板块因子计算 {len(results)} 个", flush=True)

    res_boards = [r for r in results if r["resonance"]]
    res_boards.sort(key=lambda r: -r["strength"])
    grab_top = sorted([r for r in results if "抢筹" in r["factors"]], key=lambda r: -r["strength"])[:10]
    entry_top = sorted([r for r in results if "进场" in r["factors"]], key=lambda r: -r["main_net_5d"])[:10]
    abs_top = sorted([r for r in results if "吸筹" in r["factors"]], key=lambda r: -r["precip"] if r["precip"] else 0)[:10]
    ctl_top = sorted([r for r in results if "控盘" in r["factors"]], key=lambda r: -r["precip"] if r["precip"] else 0)[:10]

    today = datetime.now().strftime("%Y-%m-%d")
    js = {
        "date": today, "source": "local(westock独立口径·无外部依赖)",
        "pool_size": len(results),
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

    L = [f"# 🧭 板块资金共振（本地独立口径） {today}", "",
         f"> 数据源：westock 本地复算（board全行业+概念+资金流 {len(results)} 板块 + hot代码映射 + asfund散户 + kline量能），无外部API依赖",
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
        L.append(f"| {r['name']} | {r['zdf']} | {r['main_net_5d']} | {r['retail_net'] if r['retail_net'] is not None else '—'} | {r['precip'] if r['precip'] is not None else '—'} |")
    L.append("")
    L.append("## 五、控盘TOP（缩量高沉淀）")
    L.append("| 板块 | 涨幅% | 量能比 | 沉淀率% | 5D主力(亿) |")
    L.append("|---|---|---|---|---|")
    for r in ctl_top:
        L.append(f"| {r['name']} | {r['zdf']} | {r['vol_ratio'] if r['vol_ratio'] is not None else '—'} | {r['precip'] if r['precip'] is not None else '—'} | {r['main_net_5d']} |")
    L.append("")
    md_path = os.path.join(OUT_DIR, f"板块共振对照_{today}.md")
    open(md_path, "w", encoding="utf-8").write("\n".join(L))
    print(f"[OK] {json_path}")
    print(f"[OK] {md_path}")
    print(f"共振 {len(res_boards)} | 抢筹 {len(grab_top)} | 进场 {len(entry_top)} | 吸筹 {len(abs_top)} | 控盘 {len(ctl_top)}")


if __name__ == "__main__":
    main()
