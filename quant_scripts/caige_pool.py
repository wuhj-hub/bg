#!/usr/bin/env python3
"""
才哥战法股池扫描器 v1.0
========================
四大特征选股建立股池：
  1. 王者倍量柱（正版·涨停倍量+3日缩量确认）
  2. 旭日东升（超跌+缩量+反包）
  3. 凤凰归巢（两连板+量能递减）
  4. 瞒天过海（昨涨停+今日倍量阴 / 10日内突破阴线收盘）

数据源: westock (npx westock-data-skillhub@1.0.3) 批量K线
用法: python3 caige_pool.py [--limit N] [--include-st] [--out-dir outputs]
输出: outputs/才哥战法股池_{date}.md + 才哥战法股池_{date}.json
"""
import subprocess, sys, os, re, json, time, argparse
from datetime import datetime, timezone, timedelta
BJ_TZ = timezone(timedelta(hours=8))
def now_bj():
    return datetime.now(BJ_TZ)
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

WORKSPACE = Path("/sandbox/workspace")
BATCH = 100        # 每批股票数
KLIMIT = 130       # K线根数（60日线+涨停日前置需要）
WORKERS = 4

# ============================================================
# 工具函数
# ============================================================
def cli(cmd, timeout=180):
    full = f"npx -y westock-data-skillhub@1.0.3 {cmd}"
    for attempt in range(3):
        try:
            r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=timeout)
            if r.stdout.strip():
                return r.stdout
        except subprocess.TimeoutExpired:
            pass
        time.sleep(1)
    return ""

def parse_batch_kline(md):
    """解析批量kline输出 -> {symbol: [bars...]} bars按date升序"""
    lines = [l.strip() for l in md.split('\n') if l.strip()]
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith('| symbol |'):
            header_idx = i
            break
    if header_idx is None:
        return {}
    headers = [h.strip() for h in lines[header_idx].split('|')[1:-1]]
    groups = {}
    for ln in lines[header_idx + 2:]:
        if not ln.startswith('|'):
            continue
        parts = [p.strip() for p in ln.split('|')[1:-1]]
        if len(parts) < len(headers):
            continue
        row = dict(zip(headers, parts))
        sym = row['symbol']
        try:
            groups.setdefault(sym, []).append({
                'date': row['date'],
                'open': float(row['open']),
                'close': float(row['last']),
                'high': float(row['high']),
                'low': float(row['low']),
                'vol': float(row['volume']),
                'turnover': float(row['exchange']),   # 换手率 %
            })
        except ValueError:
            continue
    for sym in groups:
        groups[sym].sort(key=lambda x: x['date'])
    return groups

def normalize_code(code: str) -> str:
    """000001 -> sz000001; 600000 -> sh600000"""
    num = re.sub(r'\D', '', code)
    if num.startswith(('6', '9')):
        return 'sh' + num
    return 'sz' + num

def is_mainboard(code: str) -> bool:
    num = re.sub(r'\D', '', code)
    for p in ('688', '300', '301', '8', '43', '83', '87'):
        if num.startswith(p):
            return False
    return True

# ============================================================
# 四大战法检测
# ============================================================
def detect_wangzhe(bars, name):
    """王者倍量柱·正版：涨停日=T-3，今天=T+3 确认
    条件: 涨停(主板10%/ST5%) + 换手>5% + 量比1.5~4 + 后3日收盘均高于涨停价
          + 后2日量递减 + 后3日最高涨幅<9% + MA60向上 + 3日均量<涨停日量
    """
    if len(bars) < 65:
        return None
    i = len(bars) - 1
    t = i - 3
    if t < 4:
        return None
    b = bars
    is_st = 'ST' in name.upper()
    pct = 0.05 if is_st else 0.10
    limit_price = round(b[t - 1]['close'] * (1 + pct), 2)
    if b[t]['close'] < limit_price - 0.001:
        return None
    if not (b[t]['turnover'] > 5 and 1.5 <= b[t]['vol'] / b[t - 1]['vol'] <= 4):
        return None
    if min(b[t + 1]['close'], b[t + 2]['close'], b[t + 3]['close']) <= b[t]['close']:
        return None
    if not (b[t + 3]['vol'] < b[t + 2]['vol'] < b[t + 1]['vol']):
        return None
    if max(b[t + 1]['high'], b[t + 2]['high'], b[t + 3]['high']) / b[t]['close'] - 1 >= 0.09:
        return None
    ma60_now = sum(x['close'] for x in b[i - 59:i + 1]) / 60
    ma60_prev = sum(x['close'] for x in b[i - 60:i]) / 60
    if ma60_now < ma60_prev:
        return None
    if sum(x['vol'] for x in b[t + 1:t + 4]) / 3 >= b[t]['vol']:
        return None
    return {
        'type': '王者倍量柱(确认)',
        'limit_date': b[t]['date'],
        'limit_close': b[t]['close'],
        'vol_ratio': round(b[t]['vol'] / b[t - 1]['vol'], 2),
        'turnover': round(b[t]['turnover'], 2),
        'note': f'确认·涨停日{b[t]["date"]} 量比{b[t]["vol"]/b[t-1]["vol"]:.2f} 换手{b[t]["turnover"]:.1f}%'
    }

def detect_wangzhe_watch(bars, name):
    """涨停王者倍量柱·观察级：涨停+换手>5%+量比1.5~4出现即入池（T+0~T+2，等待3天确认升级）"""
    if len(bars) < 65:
        return None
    i = len(bars) - 1
    b = bars
    is_st = 'ST' in name.upper()
    pct = 0.05 if is_st else 0.10
    # 观察级：涨停倍量柱出现在最近3天内（t∈[i-2, i]），尚未走完3天确认期
    # （t=i-3 及更早已过确认期，由确认级 detect_wangzhe 判定，不重复入观察池）
    for t in range(max(1, i - 2), i + 1):
        if t < 1:
            continue
        limit_price = round(b[t - 1]['close'] * (1 + pct), 2)
        if b[t]['close'] < limit_price - 0.001:
            continue
        if b[t]['turnover'] > 5 and 1.5 <= b[t]['vol'] / b[t - 1]['vol'] <= 4:
            # 已出现且未走完3天确认（含今天出现）
            return {
                'type': '王者倍量柱(观察)',
                'limit_date': b[t]['date'],
                'limit_close': b[t]['close'],
                'vol_ratio': round(b[t]['vol'] / b[t - 1]['vol'], 2),
                'turnover': round(b[t]['turnover'], 2),
                'note': f'观察·涨停日{b[t]["date"]} 量比{b[t]["vol"]/b[t-1]["vol"]:.2f} 换手{b[t]["turnover"]:.1f}% 待3日确认'
            }
    return None


def detect_xuri(bars, name=None):
    """旭日东升：6日内>=4阴 + 跌幅达标 + 缩量 + 高开反包阳"""
    if len(bars) < 10:
        return None
    i = len(bars) - 1
    b = bars
    c_down = sum(1 for k in range(i - 5, i + 1) if b[k]['close'] < b[k - 1]['close'])
    o_down = sum(1 for k in range(i - 5, i + 1) if b[k]['close'] < b[k]['open'])
    if not (c_down >= 4 or o_down >= 4):
        return None
    d1 = (b[i - 3]['high'] - b[i - 1]['low']) / b[i - 3]['high'] * 100 > 9 \
         and (b[i - 2]['close'] - b[i - 1]['close']) / b[i - 2]['close'] * 100 > 3
    d2 = 1.045 < b[i - 6]['close'] / b[i - 1]['close'] < 1.20
    if not (d1 or d2):
        return None
    if b[i]['vol'] > b[i - 1]['vol'] * 1.1:
        return None
    y11 = (b[i - 1]['close'] < b[i - 1]['open']) or (b[i - 1]['close'] < b[i - 2]['close'])
    y22 = b[i - 1]['close'] > b[i - 1]['open']
    yang = (y11 or y22) and b[i]['open'] > min(b[i - 1]['close'], b[i - 1]['open']) \
           and b[i]['close'] > max(b[i - 1]['close'], b[i - 1]['open']) and b[i]['close'] > b[i]['open']
    if not yang:
        return None
    return {
        'type': '旭日东升',
        'note': f'今涨{(b[i]["close"]/b[i-1]["close"]-1)*100:.1f}% 量缩'
    }

def detect_fenghuang(bars, name=None):
    """凤凰归巢：前两日连续涨停(>=9.6%) + 量能递减"""
    if len(bars) < 5:
        return None
    i = len(bars) - 1
    b = bars
    if (b[i - 1]['close'] / b[i - 2]['close'] >= 1.096
            and b[i - 2]['close'] / b[i - 3]['close'] >= 1.096
            and b[i - 2]['vol'] < b[i - 1]['vol']
            and b[i]['vol'] < b[i - 1]['vol'] * 2):
        return {'type': '凤凰归巢', 'note': '两连板后量能递减'}
    return None

def detect_mantian(bars, name=None):
    """瞒天过海：
    (1) 当日：昨涨停 + 今收阴 + 量>昨量1.8倍 -> 倍量阴
    (2) 突破：最近10日内倍量阴，今收突破其收盘价且昨收未破
    """
    if len(bars) < 15:
        return None
    b = bars
    i = len(bars) - 1

    def is_zt(k):
        if k < 1:
            return False
        return b[k]['close'] >= round(b[k - 1]['close'] * 1.1, 2) - 0.001

    # (1) 今日倍量阴
    if b[i]['close'] < b[i]['open'] and b[i]['vol'] > b[i - 1]['vol'] * 1.8 and is_zt(i - 1):
        return {'type': '瞒天过海(当日)', 'note': f'昨涨停今倍量阴 量比{b[i]["vol"]/b[i-1]["vol"]:.1f}'}
    # (2) 突破
    for nn in range(1, 11):
        j = i - nn
        if j < 2:
            break
        if b[j]['close'] < b[j]['open'] and b[j]['vol'] > b[j - 1]['vol'] * 1.8 and is_zt(j - 1):
            if b[i]['close'] > b[j]['close'] and b[i - 1]['close'] < b[j]['close']:
                return {'type': '瞒天过海(突破)', 'note': f'{nn}日前倍量阴今突破'}
            break
    return None

# ============================================================
# 主流程
# ============================================================
DETECTORS = [
    ('王者倍量柱', detect_wangzhe),
    ('王者倍量柱(观察)', detect_wangzhe_watch),
    ('旭日东升', detect_xuri),
    ('凤凰归巢', detect_fenghuang),
    ('瞒天过海', detect_mantian),
]

def fetch_batch(codes):
    """拉取一批股票K线"""
    syms = ",".join(codes)
    md = cli(f"kline {syms} --period day --limit {KLIMIT}")
    if not md:
        return {}
    return parse_batch_kline(md)

def scan(pool, include_st=False):
    """pool: [(code, name), ...] -> {type: [signal...]}"""
    results = {t: [] for t, _ in DETECTORS}
    scanned = 0
    codes_list = [c for c, _ in pool]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {}
        for i in range(0, len(codes_list), BATCH):
            batch = codes_list[i:i + BATCH]
            futures[ex.submit(fetch_batch, batch)] = batch
        for fut in as_completed(futures):
            batch = futures[fut]
            try:
                bars_map = fut.result()
            except Exception:
                bars_map = {}
            for code in batch:
                name = dict(pool).get(code, '')
                bars = bars_map.get(code, [])
                if len(bars) < 10:
                    continue
                scanned += 1
                for tname, detector in DETECTORS:
                    sig = detector(bars, name)
                    if sig:
                        sig['code'] = code
                        sig['name'] = name.strip()
                        sig['close'] = bars[-1]['close']
                        results[tname].append(sig)
    return results, scanned

def build_report(results, scanned, date_str):
    lines = []
    lines.append(f"# 才哥战法股池 {date_str}\n")
    lines.append(f"**扫描时间**: {now_bj().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**扫描数量**: {scanned} 只（沪深主板）")
    total = sum(len(v) for v in results.values())
    lines.append(f"**信号总数**: {total} 个\n")
    for tname, _ in DETECTORS:
        sigs = results[tname]
        lines.append(f"\n## {tname}（{len(sigs)} 只）\n")
        if not sigs:
            lines.append("📭 今日无信号。\n")
            continue
        lines.append("| 代码 | 名称 | 收盘价 | 说明 |")
        lines.append("|------|------|--------|------|")
        for s in sorted(sigs, key=lambda x: -x['close']):
            lines.append(f"| {s['code']} | {s['name']} | {s['close']:.2f} | {s['note']} |")
        lines.append("")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='仅扫描前N只（测试用）')
    ap.add_argument('--include-st', action='store_true', help='包含ST股')
    ap.add_argument('--out-dir', default=str(WORKSPACE / 'outputs'))
    args = ap.parse_args()

    csv_path = WORKSPACE / 'all_mainboard.csv'
    pool = []
    with open(csv_path, encoding='utf-8-sig') as f:
        next(f)
        for ln in f:
            parts = ln.strip().split(',')
            if len(parts) < 2:
                continue
            code, name = parts[0].strip(), parts[1].strip()
            if not is_mainboard(code):
                continue
            if not args.include_st and 'ST' in name.upper():
                continue
            if '退' in name:  # 退市股排除
                continue
            pool.append((normalize_code(code), name))
    if args.limit:
        pool = pool[:args.limit]

    print(f"[INFO] 股票池 {len(pool)} 只，开始扫描（{len(pool)//BATCH+1} 批 × {WORKERS} 并发）...")
    t0 = time.time()
    results, scanned = scan(pool, args.include_st)
    print(f"[INFO] 扫描完成 耗时 {time.time()-t0:.0f}s 有效 {scanned} 只")

    date_str = now_bj().strftime('%Y-%m-%d')
    os.makedirs(args.out_dir, exist_ok=True)
    md_path = os.path.join(args.out_dir, f'才哥战法股池_{date_str}.md')
    json_path = os.path.join(args.out_dir, f'才哥战法股池_{date_str}.json')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(build_report(results, scanned, date_str))
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'scanned': scanned,
                   'results': results}, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 报告: {md_path}")
    print(f"[INFO] JSON: {json_path}")

    # 自动更新股池配置文件（供 pool_tracking_report.py 三阶漏斗跟踪，每日刷新为当日信号）
    pool_txt = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'caige_pool.txt')
    plines = [f"# 才哥战法股池 {date_str}（自动生成，四战法：王者倍量柱/旭日东升/凤凰归巢/瞒天过海）",
              "# 格式：代码 # 名称（战法类型）"]
    for tname, _ in DETECTORS:
        for s in results[tname]:
            plines.append(f"{s['code']} # {s['name']}（{tname}）")
    with open(pool_txt, 'w', encoding='utf-8') as f:
        f.write('\n'.join(plines) + '\n')
    print(f"[INFO] 股池配置已更新: {pool_txt}（{sum(len(v) for v in results.values())}只）")
    for tname, _ in DETECTORS:
        print(f"  {tname}: {len(results[tname])} 只")
        for s in results[tname]:
            print(f"    {s['code']} {s['name']} 收{s['close']:.2f} | {s['note']}")

if __name__ == '__main__':
    main()
