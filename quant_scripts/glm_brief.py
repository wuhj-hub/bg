#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glm_brief.py —— 盘前「🤖 GLM 外围传导研判」节生成器（2026-09-22 接入；09-23 扩容）

数据：默认自拉（美股 / 商品(原油·布伦特·黄金) / 港股 / A股指数 / 隔夜要闻 + 本地情绪·宽度 json）
     也可 --facts-file 指定事实文本
输出：Markdown 片段
用法：
  python3 glm_brief.py --out outputs/glm_brief_{date}.md
  python3 glm_brief.py --facts-file facts.txt --out g.md
"""
import os, sys, json, re, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_glm import chat

SYSTEM = '你是A股盘前策略分析师，语言精炼、结论明确，只基于给定数据，不编造。'
UA = {'User-Agent': 'Mozilla/5.0'}


def _ifzq(code, fq='qfqkline'):
    u = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,2,qfq'
    d = json.loads(urllib.request.urlopen(u, timeout=15).read().decode())
    node = d['data'][code]
    arr = node.get('qfqday') or node.get('day')
    c = [float(x[2]) for x in arr]
    return c[-1], (c[-1] / c[-2] - 1) * 100 if len(c) > 1 else 0


def _commodity():
    """商品：腾讯期货接口（逗号分隔，最后一项为名称；注意不是 '~'）"""
    out = []
    try:
        raw = urllib.request.urlopen(urllib.request.Request('https://qt.gtimg.cn/q=hf_CL,hf_OIL,hf_GC', headers=UA), timeout=15).read().decode('gbk', 'ignore')
        for ln in raw.split(';'):
            if '=' not in ln:
                continue
            p = ln.split('"')[1].split(',')
            if len(p) < 3:
                continue
            out.append(f'{p[-1]} {p[0]}({p[1]}%)')
    except Exception:
        pass
    return out


def _news(n=8):
    """隔夜要闻（新浪 7x24，与报告同源）"""
    try:
        u = f'https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size={n}&zhibo_id=152'
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=18).read().decode())
        items = d.get('result', {}).get('data', {}).get('feed', {}).get('list', [])
        out = []
        for it in items:
            t = re.sub(r'<[^>]+>', '', it.get('rich_text', '')).strip()
            if t:
                out.append(t[:80])
        return out[:n]
    except Exception:
        return []


def auto_facts():
    parts = []
    for code, lbl in [('usDJI', '道指'), ('usIXIC', '纳指'), ('usINX', '标普500')]:
        try:
            v, ch = _ifzq(code); parts.append(f'{lbl} {v:.0f}({ch:+.2f}%)')
        except Exception:
            pass
    parts += _commodity()
    for code, lbl in [('hkHSI', '恒生'), ('sh000001', '上证'), ('sz399006', '创业板'), ('sh000688', '科创50')]:
        try:
            v, ch = _ifzq(code); parts.append(f'{lbl} {v:.0f}({ch:+.2f}%)')
        except Exception:
            pass
    # 本地产物：情绪/宽度
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name, fn in [('hot_emotion_latest.json', lambda d: f"情绪温度{d.get('temperature','?')}({d.get('level','?')}) 涨停{d.get('zt_count','?')} 连板{d.get('lb_count','?')} 最高板{d.get('max_board','?')}"),
                     ('market_width_latest.json', lambda d: f"市场宽度 上涨占比{d.get('up_ratio','?')}% 涨停{d.get('limitup','?')} 跌停{d.get('limitdown','?')}")]:
        for p in (os.path.join(base, 'outputs', name), os.path.join(base, name), name):
            if os.path.exists(p):
                try:
                    parts.append(fn(json.load(open(p, encoding='utf-8')))); break
                except Exception:
                    pass
    # 隔夜要闻（供模型做「要闻联动」）
    news = _news(8)
    if news:
        parts.append('隔夜要闻：')
        parts += ['- ' + x for x in news]
    return '\n'.join(parts) if parts else '（无数据）'


def main():
    a = sys.argv[1:]
    facts = open(a[a.index('--facts-file') + 1], encoding='utf-8').read() if '--facts-file' in a else auto_facts()
    out = a[a.index('--out') + 1] if '--out' in a else None
    prompt = f"""以下是当日市场事实数据：

{facts}

请输出三部分（总长不超过300字）：
1. 【外围→A股传导】一段话，结合美股/商品/港股，指出驱动因素与多空定性（偏多/偏空/震荡）。
2. 【要闻联动】结合上面「隔夜要闻」，挑1-3条对A股有明确影响的，写明「消息 → 受益/受损板块」及方向（利好/利空）；若无可忽略的小事，就说"要闻对板块影响有限"。
3. 【今日关注】一行，列1-3个最值得关注的板块/方向。
格式用纯文本，不要表格。"""
    txt, usage = chat(prompt, system=SYSTEM, max_tokens=600)
    md = f"### 🤖 GLM 外围传导研判（GLM-4-Flash 自动生成）\n\n{txt.strip()}\n\n> 模型 glm-4-flash ｜ 用量 {usage.get('total_tokens')} tokens\n"
    if out:
        os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
        open(out, 'w', encoding='utf-8').write(md)
        print(f'OK -> {out} | tokens={usage.get("total_tokens")}')
    else:
        print(md)


if __name__ == '__main__':
    main()
