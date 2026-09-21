#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xzz_shortlist.py —— 曾星智「短线备选池」两用工具（2026-09-21 吸收·二期+三期）

来源：曾星智《利用反弹行情做好短线》(2026-09-21)

模式一（--live，**每日用**）：当日「先锋备选池」
  当日涨停池 → 主板首板 → 各板块内「最早封板者」= 先锋
  依据三期回测：板块内先锋次日晋级率 20.2% > 全部首板 17.1% > 热门跟风股(<8%)
  用法：python3 xzz_shortlist.py --live                 # 当日
        python3 xzz_shortlist.py --live --date 20260921  # 指定日
        python3 xzz_shortlist.py --live --json outputs/xzz_pioneer_latest.json

模式二（--kline-file，统计用）：首板次日晋级率分层统计（二期）
  用法：python3 xzz_shortlist.py --kline-file kline.json
"""
import json, sys, urllib.request
from collections import defaultdict

UA = {'User-Agent': 'Mozilla/5.0'}


def ztpool(d):
    url = ('https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989'
           f'&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt%3Aasc&date={d}')
    try:
        j = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode())
        return ((j.get('data') or {}).get('pool') or [])
    except Exception as e:
        print('[WARN] 涨停池获取失败:', e)
        return []


def is_main(c):
    return c.startswith(('600', '601', '603', '605', '000', '001', '002', '003'))


def live(date=None):
    from datetime import datetime, timezone, timedelta
    if not date:
        date = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    pool = ztpool(date)
    if not pool:
        print(f'{date} 无涨停池数据（非交易日或未开盘）')
        return
    rows = []
    for p in pool:
        c = p.get('c') or ''
        if not is_main(c):
            continue
        rows.append({
            'code': ('sh' if c[0] == '6' else 'sz') + c, 'name': p.get('n', ''),
            'lbc': p.get('lbc') or 1, 'hybk': p.get('hybk') or '', 'fbt': p.get('fbt') or 999999,
            'zdp': round(p.get('zdp') or 0, 2), 'hs': round(p.get('hs') or 0, 2),
            'fund': p.get('fund') or 0,
        })
    # 各板块首板最早封板 = 先锋
    first = [r for r in rows if r['lbc'] == 1]
    best = {}
    for r in first:
        hy = r['hybk']
        if hy not in best or r['fbt'] < best[hy]['fbt']:
            best[hy] = r
    cnt = defaultdict(int)
    for r in rows:
        cnt[r['hybk']] += 1
    pioneers = sorted(best.values(), key=lambda x: x['fbt'])
    print(f'# 👑 曾星智短线·先锋备选池  {date}')
    print(f'\n当日主板涨停 {len(rows)} 只（首板 {len(first)} 只，覆盖板块 {len(cnt)} 个）\n')
    print('| 板块 | 先锋 | 封板时间 | 涨幅% | 换手% | 板块涨停数 |')
    print('|---|---|---|---|---|---|')
    for r in pioneers:
        t = str(r['fbt']).zfill(6)
        print(f"| {r['hybk']} | {r['name']}({r['code']}) | {t[:2]}:{t[2:4]}:{t[4:6]} | {r['zdp']} | {r['hs']} | {cnt[r['hybk']]} |")
    print(f'\n> 先锋 = 各板块内「最早封板的首板」；三期回测次日晋级率 ~20.2%（高于全部首板 17.1%）。')
    if '--json' in sys.argv:
        outj = sys.argv[sys.argv.index('--json') + 1]
        json.dump({'date': date, 'pioneers': pioneers, 'count': len(rows)},
                  open(outj, 'w'), ensure_ascii=False, indent=1)
        print('JSON →', outj)


def stat(name, arr):
    if not arr:
        print(f'{name:<24} 无样本'); return
    print(f'{name:<24} N={len(arr):>5}  晋级率{100*sum(arr)/len(arr):5.1f}%')


def stats(kf, outj=None):
    kl = json.load(open(kf))
    events = []
    for code, bars in kl.items():
        bars = sorted(bars, key=lambda x: x[0])
        n = len(bars)
        if n < 20:
            continue
        close = [b[2] for b in bars]; dates = [b[0] for b in bars]
        lim = [False] * n
        for i in range(1, n):
            if close[i - 1] > 0 and 0.098 <= close[i] / close[i - 1] - 1 <= 0.105:
                lim[i] = True
        lbc = [0] * n
        for i in range(1, n):
            lbc[i] = (lbc[i - 1] + 1) if (lim[i] and lim[i - 1]) else (1 if lim[i] else 0)
        for i in range(n - 1):
            if lim[i]:
                events.append((dates[i], code, lbc[i], lim[i + 1]))
    print(f'涨停事件 {len(events)}')
    stat('全部涨停', [e[3] for e in events])
    for lo, hi, lbl in [(1, 1, '首板'), (2, 2, '2板'), (3, 3, '3板'), (4, 99, '4板+')]:
        stat(lbl, [e[3] for e in events if lo <= e[2] <= hi])


if __name__ == '__main__':
    if '--live' in sys.argv:
        d = sys.argv[sys.argv.index('--date') + 1] if '--date' in sys.argv else None
        live(d)
    elif '--kline-file' in sys.argv:
        kf = sys.argv[sys.argv.index('--kline-file') + 1]
        stats(kf, sys.argv[sys.argv.index('--json') + 1] if '--json' in sys.argv else None)
    else:
        print(__doc__)
