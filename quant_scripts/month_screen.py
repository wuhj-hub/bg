#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""月线选股扫描（指标1 XG / 指标2 A5）

范围：沪深主板非 ST（剔除创业板 300/301、科创板 688/689、北交所、ST/*ST）
数据：腾讯前复权月线（newfqkline，单只最长 302 根 / 2001 至今，含成交量）
产物：outputs/月线选股_{YYYY-MM}.md、outputs/month_screen_latest.json

用法：
  python3 quant_scripts/month_screen.py --date 2026-10-28 --push
  python3 quant_scripts/month_screen.py --force            # 忽略「本月最后交易日」判断
"""
import argparse, csv, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
HOSTS = ["https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get",
         "https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get"]
WORKERS = int(os.environ.get('MS_WORKERS', '6'))


# ---------------- 股票池 / 名称 ----------------
def load_pool():
    for p in (os.path.join(ROOT, 'all_mainboard.csv'), os.path.join(os.getcwd(), 'all_mainboard.csv')):
        if os.path.exists(p):
            out = []
            for r in csv.DictReader(open(p, encoding='utf-8-sig')):
                c = (r.get('code') or '').strip()
                nm = (r.get('name') or '').replace('\u3000', '').strip()
                if not c.isdigit():
                    continue
                is_main = c.startswith(('60', '00'))
                if not is_main or 'ST' in nm.upper():
                    continue
                out.append(('sh' if c[0] == '6' else 'sz') + c)
            return sorted(set(out))
    return []


def snap_names(codes):
    """腾讯快照：名称（ST 判定以此为准）+ 现价"""
    def batch(ch):
        u = "https://qt.gtimg.cn/q=" + ",".join(ch)
        for _ in range(3):
            try:
                t = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read().decode('gbk', 'ignore')
                out = {}
                for ln in t.strip().split(';'):
                    ln = ln.strip()
                    if not ln.startswith('v_') or '="' not in ln:
                        continue
                    code = ln.split('=')[0][2:]
                    f = ln.split('="')[1].split('~')
                    if len(f) > 4 and f[1]:
                        out[code] = {'name': f[1].replace(' ', '').strip(), 'price': f[3]}
                return out
            except Exception:
                time.sleep(1.5)
        return {}
    snap = {}
    for i in range(0, len(codes), 100):
        snap.update(batch(codes[i:i + 100]))
    return snap


# ---------------- 月线取数 ----------------
def kline_one(sym):
    for host in HOSTS:
        u = f"{host}?param={sym},month,,,800,qfq"
        for _ in range(2):
            try:
                t = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25).read().decode('utf-8', 'ignore')
                d = json.loads(t)['data'][sym]
                arr = d.get('qfqmonth') or d.get('month') or []
                out = []
                for r in arr:
                    try:
                        out.append([r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
                    except Exception:
                        continue
                if out:
                    return sym, out
            except Exception:
                time.sleep(0.8)
    return sym, []


def fetch_klines(codes, cache_file=None):
    cache = {}
    if cache_file and os.path.exists(cache_file):
        try:
            cache = json.load(open(cache_file))
        except Exception:
            cache = {}
    todo = [c for c in codes if not cache.get(c)]
    print(f'[kline] 需取 {len(todo)} 只（缓存 {len(cache)}）', flush=True)
    t0, n = time.time(), 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for sym, arr in ex.map(kline_one, todo):
            cache[sym] = arr
            n += 1
            if n % 500 == 0:
                print(f'[kline] {n}/{len(todo)} {round(time.time()-t0)}s', flush=True)
    print(f'[kline] 完成 非空={sum(1 for v in cache.values() if v)} 用时{round(time.time()-t0)}s', flush=True)
    return cache


# ---------------- 指标计算 ----------------
def hv_true(mask, N, t):
    if t < 0:
        return None
    lo = max(0, t - N + 1)
    idx = np.flatnonzero(mask[lo:t + 1])
    return (t - (lo + idx[-1])) if len(idx) else None


def cnt(mask, N, t):
    if not N or N <= 0 or t < 0:
        return 0
    return int(mask[max(0, t - N + 1):t + 1].sum())


def anyx(mask, N, t):
    if not N or N <= 0 or t < 0:
        return False
    return bool(mask[max(0, t - N + 1):t + 1].any())


def cross_up(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    o = np.zeros(len(a), bool)
    ok = ~np.isnan(a) & ~np.isnan(b)
    o[1:] = ok[1:] & ok[:-1] & (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
    return o


def compute(rows):
    if len(rows) < 25:
        return None
    d = [r[0] for r in rows]
    o = np.array([r[1] for r in rows], float)
    c = np.array([r[2] for r in rows], float)
    h = np.array([r[3] for r in rows], float)
    v = np.array([r[5] for r in rows], float)
    n = len(c)
    S = lambda k: pd.Series(c).rolling(k).mean().values
    ma4, ma5, ma10 = S(4), S(5), S(10)
    if np.nanmin(ma4[-15:]) <= 0 or np.nanmin(ma10[-15:]) <= 0:
        return None
    vm5 = pd.Series(v).rolling(5).mean().values
    yin = c < o
    gold = cross_up(ma5, ma10)
    dead = cross_up(ma10, ma5)
    K1 = cross_up(c, ma10)

    def ratio_ok(base, x):
        return base is not None and not np.isnan(base) and base > 0 and (x / base * 100 - 100) < 50

    A2 = np.zeros(n, bool)
    for i in range(1, n):
        k2 = hv_true(K1, 10, i)
        ok = False
        if k2 and k2 > 0:
            ok = (cnt(yin, k2, i) == 1) and bool(yin[i]) and ratio_ok(ma10[i - k2], c[i])
        if not ok and K1[i]:
            ok = bool(yin[i]) and ratio_ok(ma10[i - 1], c[i])
        A2[i] = ok
    A4s = np.zeros(n, bool)
    for i in range(1, n):
        a3 = hv_true(A2, 10, i)
        if a3 and a3 > 0 and not (np.isnan(ma4[i]) or np.isnan(ma5[i]) or np.isnan(ma10[i])):
            A4s[i] = (c[i] > h[i - a3]) and ma4[i] > ma5[i] > ma10[i]

    A2b = np.zeros(n, bool)
    for i in range(1, n):
        a1 = hv_true(gold, 10, i)
        if not (a1 and a1 > 0):
            continue
        if np.isnan(ma4[i]) or np.isnan(ma5[i]) or np.isnan(ma10[i]) or not (ma4[i] > ma5[i] > ma10[i]):
            continue
        A2b[i] = (cnt(yin, a1, i) == 1) and bool(yin[i]) and ratio_ok(ma10[i - a1], c[i])
    A4b = np.zeros(n, bool)
    for i in range(1, n):
        a3 = hv_true(A2b, 10, i)
        if not (a3 and a3 > 0):
            continue
        if np.isnan(ma4[i]) or np.isnan(ma5[i]) or np.isnan(ma10[i]) or not (ma4[i] > ma5[i] > ma10[i]):
            continue
        a3p = hv_true(A2b, 10, i - 1) or 0
        if c[i] > h[i - a3] and c[i - 1] <= h[(i - 1) - a3p]:
            A4b[i] = True

    valid = np.flatnonzero(~np.isnan(vm5))
    qibao = None
    if len(valid):
        s0 = valid[0]; seg = vm5[s0:]
        dd = int(len(seg) - 1 - np.nanargmax(seg))
        qibao = float(seg[len(seg) - 1 - dd] / 2.0)

    neg = np.flatnonzero(c <= 0)
    e0 = int(neg[-1] + 1) if len(neg) else 0
    e12 = np.full(n, np.nan); e60 = np.full(n, np.nan)
    if n - e0 >= 5:
        e12[e0:] = pd.Series(c[e0:]).ewm(span=12, adjust=False).mean().values
        e60[e0:] = pd.Series(c[e0:]).ewm(span=60, adjust=False).mean().values

    return dict(d=d, o=o, c=c, h=h, v=v, n=n, ma4=ma4, ma5=ma5, ma10=ma10, vm5=vm5,
                K1=K1, A2=A2, A4s=A4s, gold=gold, dead=dead, A2b=A2b, A4b=A4b,
                qibao=qibao, e12=e12, e60=e60)


def eval_at(x, t):
    c, h, v = x['c'], x['h'], x['v']
    K2 = hv_true(x['K1'], 10, t)
    A3 = hv_true(x['A2'], 10, t)
    cntA4 = cnt(x['A4s'], A3 or 0, t)
    XG1 = bool(cntA4 == 1 and x['A4s'][t] and K2 and K2 > 0
               and cnt(x['dead'], K2, t) == 0 and anyx(v > x['qibao'], 3, t)
               and anyx(x['gold'], K2 + 2, t))
    A1 = hv_true(x['gold'], 10, t)
    A3b = hv_true(x['A2b'], 10, t)
    cntA4b = cnt(x['A4b'], A3b or 0, t)
    ea, eb = x['e12'][t], x['e60'][t]
    A5 = bool(cntA4b == 1 and x['A4b'][t] and A1 and A1 > 0
              and not np.isnan(ea) and not np.isnan(eb) and ea > eb and c[t] < 15)
    g = lambda z: (None if (z is None or (isinstance(z, float) and np.isnan(z))) else float(z))
    return dict(
        date=x['d'][t], close=float(c[t]), ma4=g(x['ma4'][t]), ma5=g(x['ma5'][t]), ma10=g(x['ma10'][t]),
        K1_date=(x['d'][t - K2] if (K2 and K2 > 0) else None), K2=K2,
        A2_date=(x['d'][t - A3] if (A3 and A3 > 0) else None), A3=A3,
        A4=bool(x['A4s'][t]), A4_refh=(float(h[t - A3]) if (A3 and A3 > 0) else None), cntA4=cntA4,
        qibao=x['qibao'], v_last=float(v[t]), v3=[float(v[i]) if i >= 0 else None for i in (t, t - 1, t - 2)],
        exist_v=anyx(v > x['qibao'], 3, t), dead=cnt(x['dead'], K2 or 0, t),
        gold=anyx(x['gold'], (K2 or 0) + 2, t), XG1=XG1,
        A1=A1, A2b_date=(x['d'][t - A3b] if (A3b and A3b > 0) else None), A3b=A3b,
        A4b=bool(x['A4b'][t]), A4b_refh=(float(h[t - A3b]) if (A3b and A3b > 0) else None),
        cntA4b=cntA4b, ema12=g(ea), ema60=g(eb), A5=A5, bars=x['n'], first=x['d'][0],
    )


# ---------------- 报告 ----------------
def w(x, n=0):
    return '-' if x is None else f'{x:.{n}f}'


def tbl1(lst):
    if not lst:
        return '_本期无信号_\n'
    h = ('| 代码 | 名称 | 收盘 | MA4 | MA5 | MA10 | 上穿MA10 | K2 | 回调阴线月 | A3 | 突破价位 | 近3月量(万手) | 起爆量(万手) | 上市月数 |\n'
         '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n')
    rows = []
    for r in sorted(lst, key=lambda z: -z['close']):
        v3 = ' / '.join(f'{x/1e4:.0f}' if x else '-' for x in r['v3'])
        rows.append(f"| {r['code']} | {r['name']} | {w(r['close'],2)} | {w(r['ma4'],2)} | {w(r['ma5'],2)} | {w(r['ma10'],2)} "
                    f"| {r['K1_date'][:7] if r['K1_date'] else '-'} | {r['K2']} | {r['A2_date'][:7] if r['A2_date'] else '-'} | {r['A3']} "
                    f"| {w(r['A4_refh'],2)} | {v3} | {(r['qibao'] or 0)/1e4:.0f} | {r['bars']} |")
    return h + '\n'.join(rows) + '\n'


def tbl2(lst):
    if not lst:
        return '_本期无信号_\n'
    h = ('| 代码 | 名称 | 收盘 | MA4 | MA5 | MA10 | 金叉距今 | 回调阴线月 | A3 | 突破价位 | EMA12 | EMA60 | 上市月数 |\n'
         '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n')
    rows = []
    for r in sorted(lst, key=lambda z: -z['close']):
        rows.append(f"| {r['code']} | {r['name']} | {w(r['close'],2)} | {w(r['ma4'],2)} | {w(r['ma5'],2)} | {w(r['ma10'],2)} "
                    f"| {r['A1']} | {r['A2b_date'][:7] if r['A2b_date'] else '-'} | {r['A3b']} | {w(r['A4b_refh'],2)} "
                    f"| {w(r['ema12'],2)} | {w(r['ema60'],2)} | {r['bars']} |")
    return h + '\n'.join(rows) + '\n'


def render(res, scanned, skipped, bar_date, cur_month_open=True):
    s1, s2 = res[0]['指标1'], res[0]['指标2']
    md = [f"# 月线选股扫描 · 指标1 / 指标2（沪深主板非ST）\n",
          f"**数据日期**：{bar_date}　**有效标的**：{scanned} 只（剔除 {skipped} 只：非主板/ST/停牌退市/数据不足）\n",
          "**数据口径**：腾讯前复权月线（含成交量，单只最长 302 根）；名称与 ST 状态取实时行情快照\n"]
    if cur_month_open:
        md.append("\n> ⚠️ 当月月线尚未走完，下列「本月信号」为月内成立状态，需月末收盘确认。\n")
    md.append(f"\n---\n\n## 一、指标1（XG）· {len(s1)} 只\n")
    md.append("C上穿MA10 → 其后仅1根阴线的回调且当月收阴、相对K1时MA10涨幅<50% → 自回调月起首次突破该阴线最高价且MA4>MA5>MA10 → K1以来无死叉、近3月有过起爆量能、K1附近有MA5上穿MA10。\n\n")
    md.append(tbl1(s1))
    md.append(f"\n## 二、指标2（A5）· {len(s2)} 只\n")
    md.append("MA5上穿MA10 → 其后仅1根阴线的回调且当月收阴、相对金叉时MA10涨幅<50%且MA4>MA5>MA10 → 自回调月起首次上穿该阴线最高价 → 仅此一次突破、EMA12>EMA60、收盘<15元。\n\n")
    md.append(tbl2(s2))
    for k, lbl in ((1, '上月'), (2, '前月')):
        if k not in res:
            continue
        md.append(f"\n## 三、{lbl}信号（已收盘，对照）\n\n### 指标1 · {len(res[k]['指标1'])} 只\n")
        md.append(tbl1(res[k]['指标1']))
        md.append(f"\n### 指标2 · {len(res[k]['指标2'])} 只\n")
        md.append(tbl2(res[k]['指标2']))
    md.append("""
---

## 口径说明

- CROSS(A,B)：A 当根 > B 且上一根 A ≤ B；COUNT/EXIST 窗口含当根；HHVBARS 取窗口内最近一次为真的距离（窗口内无则视作 0，被 `>0` 过滤）
- 起爆量 = REF(VM5, HHVBARS(VM5,560))/2；560 月超过 A 股全部历史，实际取该股全部可得月线（最长 302 根）中最大 5 月均量的一半
- 前复权对分红累计大的老股早期会出现负价，EMA 从最后一个非正价之后起算（规避），最近 10 根的均线不受影响
- 剔除规则：创业板 300/301、科创板 688/689、北交所、ST/*ST（按实时简称判定）
""")
    return '\n'.join(md)


def push(title, content):
    tok = os.environ.get('PUSH_TOKEN')
    if not tok:
        print('[push] 无 PUSH_TOKEN，跳过')
        return
    body = json.dumps({'token': tok, 'title': title, 'content': content, 'template': 'markdown'}).encode()
    try:
        req = urllib.request.Request('https://www.pushplus.plus/send', data=body,
                                     headers={'Content-Type': 'application/json'})
        print('[push]', urllib.request.urlopen(req, timeout=20).read().decode()[:200])
    except Exception as e:
        print('[push] 失败', e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=time.strftime('%Y-%m-%d'))
    ap.add_argument('--months', type=int, default=3)
    ap.add_argument('--outdir', default='outputs')
    ap.add_argument('--cache', default=None)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--push', action='store_true')
    ap.add_argument('--no-push', action='store_true')
    a = ap.parse_args()

    codes = load_pool()
    if not codes:
        print('[error] 未找到 all_mainboard.csv'); return 1
    print(f'[pool] 主板非ST {len(codes)} 只', flush=True)

    snap = snap_names(codes)
    codes = [c for c in codes if 'ST' not in snap.get(c, {}).get('name', '').upper()]
    print(f'[pool] 剔除 ST 后 {len(codes)} 只', flush=True)

    cache = fetch_klines(codes, a.cache)
    res = {k: {'指标1': [], '指标2': []} for k in range(a.months)}
    scanned = 0; skipped = 0; bar_dates = {}
    for code in codes:
        rows = cache.get(code) or []
        if not rows:
            skipped += 1; continue
        try:
            x = compute(rows)
        except Exception:
            skipped += 1; continue
        if x is None:
            skipped += 1; continue
        scanned += 1
        bar_dates[rows[-1][0]] = bar_dates.get(rows[-1][0], 0) + 1
        nm = snap.get(code, {}).get('name', '')
        for k in range(a.months):
            t = x['n'] - 1 - k
            if t < 20:
                continue
            r = eval_at(x, t)
            r['code'] = code; r['name'] = nm
            if r['XG1']:
                res[k]['指标1'].append(r)
            if r['A5']:
                res[k]['指标2'].append(r)

    if scanned < len(codes) * 0.5:
        print(f'[error] 有效标的仅 {scanned}/{len(codes)}，数据源异常，终止'); return 1
    bar_date = max(bar_dates, key=bar_dates.get) if bar_dates else a.date
    ym = bar_date[:7]
    # 当月未走完判断：最新 bar 日期不是月末最后交易日（用"日期年月 == 今天年月 且 今天 < 月末"近似）
    cur_open = (bar_date[:7] == a.date[:7])
    md = render(res, scanned, skipped, bar_date, cur_open)

    os.makedirs(a.outdir, exist_ok=True)
    p_md = os.path.join(a.outdir, f'月线选股_{ym}.md')
    open(p_md, 'w').write(md)
    payload = {'bar_date': bar_date, 'scanned': scanned, 'skipped': skipped,
               '指标1': {str(k): res[k]['指标1'] for k in res},
               '指标2': {str(k): res[k]['指标2'] for k in res}}
    json.dump(payload, open(os.path.join(a.outdir, 'month_screen_latest.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    print(f'[out] {p_md}  指标1={len(res[0]["指标1"])} 指标2={len(res[0]["指标2"])}')

    if a.push and not a.no_push:
        lines = [f"- **指标1（XG）** {len(res[0]['指标1'])} 只：" + ('、'.join(f"{r['name']}({r['close']:.2f})" for r in sorted(res[0]['指标1'], key=lambda z: -z['close'])) or '无'),
                 f"- **指标2（A5）** {len(res[0]['指标2'])} 只：" + ('、'.join(f"{r['name']}({r['close']:.2f})" for r in sorted(res[0]['指标2'], key=lambda z: -z['close'])) or '无')]
        push(f"📐 月线选股 {ym} ｜ 指标1 {len(res[0]['指标1'])} · 指标2 {len(res[0]['指标2'])}",
             f"**沪深主板非ST · 数据截至 {bar_date}**\n\n" + '\n'.join(lines) + "\n\n> 详见知识库「报告/全盘量化」")
    return 0


if __name__ == '__main__':
    sys.exit(main())
