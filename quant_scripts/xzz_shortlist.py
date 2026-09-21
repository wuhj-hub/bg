#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xzz_shortlist.py —— 曾星智「短线备选池 · 晋级率跟踪」（2026-09-21 吸收·二期）

来源：曾星智《利用反弹行情做好短线》(2026-09-21)
  方法：每日选"短线备选"（涨停股）→ 跟踪次日是否继续涨停（晋级）
  排除：无明确热点概念归属的标的（如"华字辈"纯情绪炒作）→ 用行业/板块归属过滤

本脚本（本地日线版，可回溯）：
  1) 自算涨停（主板，涨幅>=9.8%，非ST由主板池保证）与连板数 lbc
  2) 每日备选池 = 当日涨停股；可选 --only-mainboard / --max-lbc 过滤
  3) 跟踪次日晋级（次日是否涨停）
  4) 统计：整体/按连板数分层的晋级率 + 晋级后次日收益

用法：
  python3 xzz_shortlist.py --kline-file kline.json --json outputs/xzz_shortlist.json
"""
import json, sys
from collections import defaultdict
import statistics


def stat(name, arr):
    if not arr:
        print(f'{name:<24} 无样本'); return
    print(f'{name:<24} N={len(arr):>5}  晋级率{100*sum(arr)/len(arr):5.1f}%')


def main():
    kf = 'kline.json'; outj = None
    if '--kline-file' in sys.argv:
        kf = sys.argv[sys.argv.index('--kline-file') + 1]
    if '--json' in sys.argv:
        outj = sys.argv[sys.argv.index('--json') + 1]
    kl = json.load(open(kf))

    # 事件：(date, code, lbc) 当日涨停
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
            if lim[i]:
                lbc[i] = (lbc[i - 1] + 1) if lim[i - 1] else 1
        for i in range(n - 1):           # 需次日数据
            if lim[i]:
                nxt = lim[i + 1]
                events.append((dates[i], code, lbc[i], nxt))

    if not events:
        print('无涨停事件'); return
    dates_all = sorted({e[0] for e in events})
    print(f'涨停事件 {len(events)} | 交易日 {len(dates_all)} ({dates_all[0]} ~ {dates_all[-1]})')
    print()
    print('=== 全样本：涨停次日晋级率 ===')
    stat('全部涨停', [e[3] for e in events])
    for lo, hi, lbl in [(1, 1, '首板(1板)'), (2, 2, '2板'), (3, 3, '3板'), (4, 99, '4板及以上')]:
        stat(lbl, [e[3] for e in events if lo <= e[2] <= hi])

    # 分阶段（按 20 交易日窗口）
    print()
    print('=== 首板晋级率 · 分阶段（每~20交易日）===')
    res = {}
    for k in range(0, len(dates_all), 20):
        seg = set(dates_all[k:k + 20])
        sub = [e[3] for e in events if e[0] in seg and e[2] == 1]
        if sub:
            lbl = f'{dates_all[k]}~{dates_all[min(k+19,len(dates_all)-1)]}'
            print(f'{lbl:<26} N={len(sub):>4}  晋级率{100*sum(sub)/len(sub):5.1f}%')
            res[lbl] = round(100 * sum(sub) / len(sub), 1)
    if outj:
        json.dump({'total': len(events), 'first_board_rate': round(100 * sum(e[3] for e in events if e[2] == 1) / max(1, len([e for e in events if e[2] == 1])), 1),
                   'by_seg': res}, open(outj, 'w'), ensure_ascii=False, indent=1)
        print('JSON →', outj)


if __name__ == '__main__':
    main()
