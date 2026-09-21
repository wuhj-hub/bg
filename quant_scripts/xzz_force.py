#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xzz_force.py —— 曾星智「9大指数长期力量 / 短期力量」核对（2026-09-21 吸收）

来源：曾星智《利用反弹行情做好短线》(2026-09-21)
  长期力量：9大指数长期方向 → 全部向下 = 大方向熊市
  短期力量：领涨指数短期方向向上 → 短线反弹成立，适合做多

实现口径（原文未给公式，本脚本采用体系近似）：
  长期力量 = 月线 MA6 方向（本月MA6 vs 上月MA6）+ 收盘与MA6关系
  短期力量 = 日线 收盘 vs MA5 vs MA10

用法：
  python3 xzz_force.py            # 文本输出
  python3 xzz_force.py --json outputs/xzz_force_latest.json
"""
import subprocess, re, sys, json

IDX = {
    'sh000001': '上证', 'sz399001': '深证成指', 'sh000016': '上证50', 'sh000300': '沪深300',
    'sz399005': '中小100', 'sz399006': '创业板指', 'sh000688': '科创50',
    'bj899050': '北证50', 'sh000905': '中证500',
}
WEST = ['npx', '-y', 'westock-data-skillhub@1.0.3']


def kline(codes, period, limit):
    r = subprocess.run(WEST + ['kline', ','.join(codes), '--period', period, '--limit', str(limit)],
                       capture_output=True, text=True, timeout=300)
    out = {}; header = None
    for ln in r.stdout.splitlines():
        s = ln.strip()
        if not s.startswith('|'):
            continue
        p = [x.strip() for x in s.strip('|').split('|')]
        if 'date' in p:
            header = p; continue
        if not header or '---' in p[0]:
            continue
        try:
            si = header.index('symbol'); di = header.index('date'); ci = header.index('last')
        except ValueError:
            continue
        if re.match(r'^[a-z]{2}\d{6}$', p[si]) and re.match(r'^\d{4}-\d{2}-\d{2}$', p[di]):
            out.setdefault(p[si], []).append((p[di], float(p[ci])))
    for c in out:
        out[c].sort(key=lambda x: x[0])
    return out


def force(code, mon, day):
    m = mon.get(code); d = day.get(code)
    lf = sf = '无数据'
    if m and len(m) >= 7:
        mc = [x[1] for x in m]
        ma6 = sum(mc[-6:]) / 6; ma6p = sum(mc[-7:-1]) / 6
        lf = '向上' if (ma6 > ma6p and mc[-1] > ma6) else ('向下' if (ma6 < ma6p and mc[-1] < ma6) else '纠缠')
    if d and len(d) >= 10:
        dc = [x[1] for x in d]
        ma5 = sum(dc[-5:]) / 5; ma10 = sum(dc[-10:]) / 10
        sf = '向上' if dc[-1] > ma5 > ma10 else ('向下' if dc[-1] < ma5 < ma10 else '纠缠')
    return lf, sf


def main():
    out_json = None
    if '--json' in sys.argv:
        out_json = sys.argv[sys.argv.index('--json') + 1]
    codes = list(IDX.keys())
    mon = kline(codes, 'month', 14); day = kline(codes, 'day', 30)
    res = {}; lu = su = 0
    print(f'{"指数":<10}{"长期力量":>9}{"短期力量":>10}')
    for c, nm in IDX.items():
        lf, sf = force(c, mon, day)
        res[nm] = {'long': lf, 'short': sf}
        lu += lf == '向上'; su += sf == '向上'
        print(f'{nm:<10}{lf:>9}{sf:>10}')
    print(f'\n长期力量向上: {lu}/9  |  短期力量向上: {su}/9')
    print(f'→ 大方向: {"熊市(无指数长期向上)" if lu == 0 else ("牛市" if lu >= 6 else "震荡")}'
          f' | 短线做多: {"成立(≥2指数短期向上)" if su >= 2 else "不成立"}')
    if out_json:
        json.dump({'long_up': lu, 'short_up': su, 'detail': res},
                  open(out_json, 'w'), ensure_ascii=False, indent=1)
        print('JSON →', out_json)


if __name__ == '__main__':
    main()
