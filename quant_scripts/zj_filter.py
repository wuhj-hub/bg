# -*- coding: utf-8 -*-
import urllib.request, json


def ztpool(d):
    url = ('https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989'
           f'&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt%3Aasc&date={d}')
    try:
        j = json.loads(urllib.request.urlopen(urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=20).read().decode())
        return ((j.get('data') or {}).get('pool') or [])
    except Exception:
        return []


days = ['20260904', '20260907', '20260908', '20260909', '20260910',
        '20260911', '20260915', '20260916', '20260917', '20260918']
pool = {d: ztpool(d) for d in days}


def is_main(c):
    return c.startswith(('600', '601', '603', '605', '000', '001', '002', '003'))


groups = {k: [0, 0] for k in ['A全部', 'C2(板块>=2)', 'C3(板块>=3)', 'C4(板块>=4)', 'D(板块有>=3板龙头)', 'E(板块家数第一)']}
for i in range(len(days) - 1):
    d, nd = days[i], days[i + 1]
    if not pool[d] or not pool[nd]:
        continue
    nxt = {p['c'] for p in pool[nd]}
    cnt = {}; maxlb = {}
    for p in pool[d]:
        hy = p.get('hybk') or ''
        cnt[hy] = cnt.get(hy, 0) + 1
        maxlb[hy] = max(maxlb.get(hy, 0), p.get('lbc') or 0)
    top = max(cnt.values()) if cnt else 0
    for p in pool[d]:
        c = p['c']; hy = p.get('hybk') or ''
        if not is_main(c) or p.get('lbc') != 1:
            continue
        up = c in nxt
        n2 = cnt.get(hy, 0)
        def add(k):
            groups[k][0] += 1; groups[k][1] += up
        add('A全部')
        if n2 >= 2: add('C2(板块>=2)')
        if n2 >= 3: add('C3(板块>=3)')
        if n2 >= 4: add('C4(板块>=4)')
        if maxlb.get(hy, 0) >= 3: add('D(板块有>=3板龙头)')
        if n2 == top and top >= 2: add('E(板块家数第一)')
print(f'{"组别":<24}{"N":>6}{"次日晋级率":>12}')
for k, (n, u) in groups.items():
    print(f'{k:<24}{n:>6}{100*u/max(1,n):>11.1f}%')

# F组：板块内最早封板(fbt最小)的首板 = 先锋
G = [0, 0]
for i in range(len(days) - 1):
    d, nd = days[i], days[i + 1]
    if not pool[d] or not pool[nd]:
        continue
    nxt = {p['c'] for p in pool[nd]}
    fb = {}
    for p in pool[d]:
        hy = p.get('hybk') or ''
        f = p.get('fbt') or 999999
        if p.get('lbc') == 1 and is_main(p['c']):
            if hy not in fb or f < fb[hy][1]:
                fb[hy] = (p['c'], f)
    for hy, (c, f) in fb.items():
        G[0] += 1; G[1] += (c in nxt)
print()
print(f'F 板块内先锋(最早封板首板)  N={G[0]:>4}  次日晋级率 {100*G[1]/max(1,G[0]):5.1f}%')
