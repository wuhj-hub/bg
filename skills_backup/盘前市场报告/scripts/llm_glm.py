#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_glm.py —— 智谱 GLM 免费模型调用工具（2026-09-22 接入）

用途：给体系脚本提供零成本 LLM 调用（新闻解读 / 传导研判 / 摘要）
模型：glm-4-flash（永久免费、不限Token、30并发）；可切 glm-4.7-flash 等
认证：读环境变量 ZHIPU_API_KEY（Bearer），OpenAI 兼容端点
依赖：纯标准库（无 openai 包也可用）

用法：
  python3 llm_glm.py --prompt "解释什么是可转债"
  python3 llm_glm.py --prompt-file prompt.txt --out reply.md
  python3 llm_glm.py --prompt "..." --model glm-4.7-flash --max-tokens 1200
"""
import os, sys, json, urllib.request, urllib.error

URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'
DEFAULT_MODEL = 'glm-4-flash'


def chat(prompt, model=DEFAULT_MODEL, max_tokens=800, temperature=0.7, system=None):
    key = os.environ.get('ZHIPU_API_KEY', '')
    if not key:
        raise RuntimeError('缺少 ZHIPU_API_KEY 环境变量（请在 open.bigmodel.cn 控制台获取后配置）')
    msgs = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': prompt}]
    body = json.dumps({'model': model, 'messages': msgs,
                       'max_tokens': max_tokens, 'temperature': temperature}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=90).read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError('GLM 调用失败: ' + e.read().decode()[:200])
    return r['choices'][0]['message']['content'], r.get('usage', {})


def main():
    a = sys.argv[1:]
    prompt = model = out = None
    max_tokens = 800
    if '--prompt' in a:
        prompt = a[a.index('--prompt') + 1]
    if '--prompt-file' in a:
        prompt = open(a[a.index('--prompt-file') + 1], encoding='utf-8').read()
    model = a[a.index('--model') + 1] if '--model' in a else DEFAULT_MODEL
    out = a[a.index('--out') + 1] if '--out' in a else None
    if '--max-tokens' in a:
        max_tokens = int(a[a.index('--max-tokens') + 1])
    if not prompt:
        print(__doc__); return
    txt, usage = chat(prompt, model, max_tokens)
    if out:
        open(out, 'w', encoding='utf-8').write(txt)
        print(f'OK -> {out} | tokens={usage.get("total_tokens")}')
    else:
        print(txt)


if __name__ == '__main__':
    main()
