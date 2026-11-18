#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""衔接月线扫描 · 指定历史月份补跑驱动

用法：
  python3 ms_period.py --periods 2026-07,2026-08,2026-09 [--limit 30] [--qibao-upto]
说明：
  复用 month_screen.py 的取数/指标/渲染函数，把评估点 t 定到目标月份的最后一根月线 bar。
  --qibao-upto：起爆量门槛改用「截至该月」的 VM5 最大值（消除后续月份造成的前视污染）。
"""
import argparse, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import month_screen as ms


def qibao_upto(x, t):
    vm5 = x['vm5']
    valid = np.flatnonzero(~np.isnan(vm5))
    if not len(valid):
        return None
    s0 = int(valid[0])
    if t < s0:
        return None
    seg = vm5[s0:t + 1]
    return float(np.nanmax(seg) / 2.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--periods', required=True, help='逗号分隔，如 2026-07,2026-08')
    ap.add_argument('--outdir', default='outputs')
    ap.add_argument('--cache', default='ms_cache.json')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--max-price', type=float, default=15.0)
    ap.add_argument('--price-scope', default='all')
    ap.add_argument('--qibao-upto', action='store_true')
    a = ap.parse_args()

    periods = [p.strip() for p in a.periods.split(',') if p.strip()]
    codes = ms.load_pool()
    if not codes:
        print('[error] 未找到 all_mainboard.csv'); return 1
    print(f'[pool] 主板 {len(codes)} 只', flush=True)
    snap = ms.snap_names(codes)
    codes = [c for c in codes if 'ST' not in snap.get(c, {}).get('name', '').upper()]
    print(f'[pool] 剔除ST后 {len(codes)} 只', flush=True)
    if a.limit:
        codes = codes[:a.limit]

    cache = ms.fetch_klines(codes, a.cache)
    if a.cache:
        try:
            json.dump(cache, open(a.cache, 'w'))
            print(f'[cache] 写 {a.cache}', flush=True)
        except Exception as e:
            print('[cache] 写失败', e)
    os.makedirs(a.outdir, exist_ok=True)

    for p in periods:
        res = {'弱启': [], '强启': []}
        no_bar = 0; short = 0; bad = 0
        bd = {}
        t0 = time.time()
        for code in codes:
            rows = cache.get(code) or []
            if not rows:
                bad += 1; continue
            t = -1
            for i in range(len(rows) - 1, -1, -1):
                if rows[i][0][:7] <= p:
                    if rows[i][0][:7] == p:
                        t = i
                    break
            if t < 0:
                no_bar += 1; continue
            try:
                x = ms.compute(rows)
            except Exception:
                bad += 1; continue
            if x is None or t < 20 or t >= x['n']:
                short += 1; continue
            if a.qibao_upto:
                q = qibao_upto(x, t)
                if q:
                    x = dict(x); x['qibao'] = q
            r = ms.eval_at(x, t, a.max_price, a.price_scope)
            r['code'] = code; r['name'] = snap.get(code, {}).get('name', '')
            bd[rows[t][0]] = bd.get(rows[t][0], 0) + 1
            if r['XG1']:
                res['弱启'].append(r)
            if r['A5']:
                res['强启'].append(r)
        bar_date = max(bd, key=bd.get) if bd else p + '-28'
        scanned = len(codes) - no_bar - short - bad
        md = ms.render({0: res}, scanned, len(codes) - scanned, bar_date, False,
                       stale=0, label=p, mp=a.max_price, scope=a.price_scope)
        fn = os.path.join(a.outdir, f'衔接_{p}.md')
        open(fn, 'w').write(md)
        print(f'[{p}] 弱启 {len(res["弱启"])} / 强启 {len(res["强启"])} '
              f'| 有效 {scanned} 无该月bar {no_bar} 数据不足 {short} 取数失败 {bad} '
              f'| {round(time.time()-t0)}s -> {fn}', flush=True)
        # 明细 stdout 便于复核
        for kind in ('弱启', '强启'):
            lst = sorted(res[kind], key=lambda z: -z['close'])
            print(f'  {kind}: ' + '、'.join(f"{r['name']}({r['code'][2:]}){r['close']:.2f}" for r in lst))
    return 0


if __name__ == '__main__':
    sys.exit(main())
