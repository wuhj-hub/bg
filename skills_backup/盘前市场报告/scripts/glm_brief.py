#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glm_brief.py —— 盘前「🤖 GLM 外围传导研判」节生成器（2026-09-22 接入）

数据来源（可选，缺省自动尝试读取 outputs/ 与仓库根）：
  --facts-file  事实数据文本（外围/A股/板块，自由格式；缺省自动拼装）
输出：Markdown 片段（嵌入盘前报告）
用法：
  python3 glm_brief.py --facts-file facts.txt --out outputs/glm_brief.md
  python3 glm_brief.py --facts-file facts.txt            # 打印到 stdout
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_glm import chat

SYSTEM = '你是A股盘前策略分析师，语言精炼、结论明确，只基于给定数据，不编造。'


def auto_facts():
    """自动拼装当日事实数据（尽力而为）"""
    parts = []
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    def load(name):
        for p in (os.path.join(base, 'outputs', name), os.path.join(base, name),
                  os.path.join(base, 'quant_scripts', name), name):
            if os.path.exists(p):
                try:
                    return json.load(open(p, encoding='utf-8'))
                except Exception:
                    pass
        return None
    mw = load('market_width_latest.json')
    if mw:
        parts.append(f"市场宽度: 上涨占比{mw.get('up_ratio','?')}% 涨停{mw.get('limitup','?')} 跌停{mw.get('limitdown','?')} 宽度分{mw.get('score','?')}")
    he = load('hot_emotion_latest.json')
    if he:
        parts.append(f"情绪: 温度{he.get('temperature','?')}({he.get('level','?')}) 涨停{he.get('zt_count','?')} 连板{he.get('lb_count','?')} 最高板{he.get('max_board','?')}")
    return '\n'.join(parts) if parts else '（无自动数据，请用 --facts-file 提供）'


def main():
    a = sys.argv[1:]
    facts = None
    if '--facts-file' in a:
        facts = open(a[a.index('--facts-file') + 1], encoding='utf-8').read()
    else:
        facts = auto_facts()
    out = a[a.index('--out') + 1] if '--out' in a else None
    prompt = f"""以下是当日市场事实数据：

{facts}

请输出两部分（总长不超过200字）：
1. 【外围→A股传导】一段话，指出驱动因素与多空定性（偏多/偏空/震荡）。
2. 【今日关注】一行，列1-3个最值得关注的板块/方向。
格式用纯文本，不要表格。"""
    txt, usage = chat(prompt, system=SYSTEM, max_tokens=500)
    md = f"### 🤖 GLM 外围传导研判（GLM-4-Flash 自动生成）\n\n{txt.strip()}\n\n> 模型 glm-4-flash ｜ 用量 {usage.get('total_tokens')} tokens\n"
    if out:
        open(out, 'w', encoding='utf-8').write(md)
        print(f'OK -> {out} | tokens={usage.get("total_tokens")}')
    else:
        print(md)


if __name__ == '__main__':
    main()
