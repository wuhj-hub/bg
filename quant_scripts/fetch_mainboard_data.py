#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全主板数据拉取：日线(westock批量) + 30m(新浪并发)，缓存到 reversal_bt_data/"""
import os, re, sys, time, subprocess, json
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "outputs", "reversal_bt_data")
os.makedirs(DATA_DIR, exist_ok=True)
WESTOCK = "npx -y westock-data-skillhub@1.0.3"


def load_mainboard():
    """all_mainboard.csv (code,name) → [(sh600000, 名称)]（仓库根目录）"""
    out = []
    for base in (BASE, os.path.dirname(BASE)):
        fp = os.path.join(base, "all_mainboard.csv")
        if os.path.exists(fp):
            break
    for ln in open(fp, encoding="utf-8-sig"):
        p = ln.strip().split(",")
        if len(p) >= 2 and re.match(r"^\d{6}$", p[0].strip()):
            code = p[0].strip()
            if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
                out.append((("sh" if code.startswith("6") else "sz") + code, p[1].strip()))
    return out


def fetch_daily_batch(codes):
    done = 0
    for i in range(0, len(codes), 100):
        batch = codes[i:i + 100]
        try:
            r = subprocess.run(f"{WESTOCK} kline {','.join(batch)} --period day --limit 260",
                               shell=True, capture_output=True, text=True, timeout=180)
            rows_map = {}
            for ln in r.stdout.splitlines():
                m = re.match(r"\|\s*([a-z]{2}\d{6})\s*\|\s*([\d-]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", ln)
                if m:
                    sym = m.group(1)
                    rows_map.setdefault(sym, []).append((m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)))
            for sym, rows in rows_map.items():
                rows.sort(key=lambda r: r[0])
                with open(os.path.join(DATA_DIR, f"{sym}_D.csv"), "w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(",".join(r) + "\n")
            done += len(rows_map)
            print(f"  日线批{i//100+1}: +{len(rows_map)} (累计{done})", flush=True)
        except Exception as e:
            print(f"  [warn] 日线批{i//100+1}失败: {e}", flush=True)


def fetch_m30(code):
    fp = os.path.join(DATA_DIR, f"{code}_m30.csv")
    if os.path.exists(fp):
        return
    for attempt in range(3):
        try:
            url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
                   f"CN_MarketDataService.getKLineData?symbol={code}&scale=30&ma=no&datalen=1000")
            r = subprocess.run(f"curl -s -m 20 '{url}'", shell=True, capture_output=True, text=True, timeout=30)
            m = re.search(r"var\((.*)\)\s*;?\s*$", r.stdout, re.S)
            if not m:
                raise ValueError("解析失败")
            data = json.loads(m.group(1))
            if len(data) < 100:
                return  # 数据不足跳过
            with open(fp, "w", encoding="utf-8") as f:
                for d in data:
                    f.write(f"{d['day']},{d['open']},{d['high']},{d['low']},{d['close']}\n")
            return
        except Exception as e:
            if attempt == 2:
                print(f"  [warn] {code} m30失败: {e}")
            time.sleep(0.5)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    pool = load_mainboard()
    print(f"全主板: {len(pool)}只")
    codes = [c for c, _ in pool]

    if which in ("day", "both"):
        missing = [c for c in codes if not os.path.exists(os.path.join(DATA_DIR, f"{c}_D.csv"))]
        print(f"日线待拉: {len(missing)}")
        fetch_daily_batch(missing)

    if which in ("m30", "both"):
        missing = [c for c in codes if not os.path.exists(os.path.join(DATA_DIR, f"{c}_m30.csv"))]
        print(f"30m待拉: {len(missing)}")
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = {ex.submit(fetch_m30, c): c for c in missing}
            for i, f in enumerate(as_completed(futs)):
                f.result()
                if (i + 1) % 300 == 0:
                    print(f"  30m {i+1}/{len(missing)}", flush=True)
    print("✅ 数据拉取完成")


if __name__ == "__main__":
    main()
