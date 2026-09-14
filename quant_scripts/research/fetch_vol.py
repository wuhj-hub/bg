"""拉全市场日线量价（同花顺 v6 line，前复权 adj=01，带 volumn 成交量）
输出 data/kline_daily_vol.csv: code,date,open,high,low,close,volume
"""
import os, csv, json, time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

OUT = "data/kline_daily_vol.csv"
KEEP = 1700
UA = {"User-Agent": "Mozilla/5.0", "Referer": "http://stockpage.10jqka.com.cn/"}


def fetch(code):
    url = f"http://d.10jqka.com.cn/v6/line/hs_{code[2:]}/01/all.js"
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            t = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
            i = t.find("{")
            if i < 0:
                return None
            d = json.JSONDecoder().raw_decode(t[i:])[0]
            pf = d["priceFactor"]
            p = [int(x) for x in d["price"].split(",")]
            v = d["volumn"].split(",")
            md = d["dates"].split(",")
            idx, full = 0, []
            for y, cnt in d["sortYear"]:
                for s in md[idx:idx + cnt]:
                    s = s.zfill(4)
                    full.append(f"{y}-{s[:2]}-{s[2:]}")
                idx += cnt
            n = min(len(full), len(v), len(p) // 4)
            full, v, p = full[-KEEP:], v[-KEEP:], p[-4 * min(n, KEEP):]
            n = len(full)
            rows = []
            for k in range(n):
                b = p[4 * k:4 * k + 4]
                if len(b) < 4:
                    continue
                lo = b[0]
                vol = v[k]
                rows.append([code, full[k], round((lo + b[1]) / pf, 3), round((lo + b[2]) / pf, 3),
                             round(lo / pf, 3), round((lo + b[3]) / pf, 3),
                             int(vol) if vol.isdigit() else 0])
            return rows
        except Exception:
            time.sleep(1.5)
    return None


def main():
    codes = [r["code"] for r in csv.DictReader(open("data/pool.csv", encoding="utf-8")) if len(r["code"]) == 8]
    done = set()
    if os.path.exists(OUT):
        for chunk in pd.read_csv(OUT, usecols=["code"], chunksize=200000):
            done |= set(chunk["code"].unique())
        print(f"已完成 {len(done)}")
    todo = [c for c in codes if c not in done]
    print(f"待拉 {len(todo)}")
    new = not os.path.exists(OUT)
    f = open(OUT, "a", encoding="utf-8", newline="")
    w = csv.writer(f)
    if new:
        w.writerow(["code", "date", "open", "high", "low", "close", "volume"])
    buf, n, fail = [], 0, 0
    with ThreadPoolExecutor(8) as ex:
        for fu in as_completed({ex.submit(fetch, c): c for c in todo}):
            r = fu.result()
            n += 1
            if r:
                buf.extend(r)
            else:
                fail += 1
            if len(buf) > 200000:
                w.writerows(buf); f.flush(); buf = []
            if n % 300 == 0:
                print(f"  {n}/{len(todo)} 失败{fail}", flush=True)
    if buf:
        w.writerows(buf)
    f.close()
    print("完成", n, "失败", fail)


if __name__ == "__main__":
    main()
