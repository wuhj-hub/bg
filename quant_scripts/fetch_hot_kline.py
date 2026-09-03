#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取全A主板日K（westock批量），供 hot_emotion --westock 模式补历史情绪数据。
用法: python3 fetch_hot_kline.py [--limit 25] [--out /tmp/kline_full.txt] [--batch 100] [--workers 4]
"""
import argparse
import subprocess
import sys
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

def norm(code):
    code = code.strip().zfill(6)
    return ('sh' if code.startswith(('6', '9')) else 'sz') + code

def fetch_batch(batch_codes, limit):
    """拉一批，返回文本。失败重试2次。"""
    codes = ','.join(norm(c) for c in batch_codes)
    for attempt in range(3):
        try:
            r = subprocess.run(
                ['npx', '-y', 'westock-data-skillhub@1.0.3', 'kline', codes,
                 '--period', 'day', '--limit', str(limit)],
                capture_output=True, text=True, timeout=120)
            out = r.stdout
            if '执行失败' in out or 'SKILL_006' in out or r.returncode != 0:
                time.sleep(3)
                continue
            return out
        except Exception as e:
            time.sleep(3)
    return ''  # 彻底失败返回空

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=25)
    ap.add_argument('--out', default='/tmp/kline_full.txt')
    ap.add_argument('--batch', type=int, default=100)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--csv', default='/sandbox/workspace/all_mainboard.csv')
    args = ap.parse_args()

    codes = []
    with open(args.csv, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('code'):
                continue
            code = line.split(',')[0].strip()
            if len(code) == 6 and code.isdigit():
                codes.append(code)
    print(f'总股票数: {len(codes)}', flush=True)

    batches = [codes[i:i + args.batch] for i in range(0, len(codes), args.batch)]
    print(f'批次数: {len(batches)} (batch={args.batch}, workers={args.workers})', flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(fetch_batch, b, args.limit): i for i, b in enumerate(batches)}
        ok, fail = 0, 0
        with open(args.out, 'w', encoding='utf-8') as f:
            for fut in as_completed(futures):
                txt = fut.result()
                if txt:
                    f.write(txt)
                    f.write('\n')
                    ok += 1
                else:
                    fail += 1
                done = ok + fail
                if done % 5 == 0 or done == len(batches):
                    el = time.time() - t0
                    print(f'进度 {done}/{len(batches)} | ok={ok} fail={fail} | 用时{el:.0f}s', flush=True)
    print(f'完成: {ok}/{len(batches)} 批成功, 输出 {args.out}, 总用时 {time.time()-t0:.0f}s')

if __name__ == '__main__':
    main()
