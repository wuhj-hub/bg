#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caige_track.py —— 才哥（科德首席才哥·刘骥才）公众号文章 跟踪/解析/比较

背景：才哥是「涨停王者倍量柱」作者，其公众号每日发布「量价博弈」文章，
      含大盘点位判断、板块方向、个股案例、量价形态术语（峰峦叠翠/一阳穿四线/
      瞒天过海/凤凰归巢/地煞星/王者倍量柱/王者之师）及每日「量价博弈学习」考题。

⚠️ 抓取限制（2026-09-15 实测）：
   微信反爬——单篇文章可 curl 直取（HTTP 200），但公众号历史文章列表
   (mp/profile_ext) 返回「请在微信客户端打开」，无法自动枚举新文章。
   → 因此采用「URL 清单驱动」：新文章 URL 追加到 caige_urls.txt，本脚本每日解析增量。

用法：
  python3 caige_track.py --url <微信文章URL>      # 抓取单篇 → 解析 → 存档
  python3 caige_track.py --sync                   # 读取 caige_urls.txt 中的新增 URL 批量处理
  python3 caige_track.py --report                 # 汇总已有存档，生成跟踪报告
"""
import csv, json, os, re, sys, time, hashlib, subprocess, urllib.request, html as htmlmod
from collections import defaultdict
from datetime import datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "outputs")
if os.path.basename(BASE) == "quant_scripts":
    OUT = os.path.join(os.path.dirname(BASE), "outputs")
STORE = os.path.join(OUT, "caige_articles")
URLS_FILE = os.path.join(os.path.dirname(OUT), "caige_urls.txt") if os.path.basename(BASE) == "quant_scripts" \
    else os.path.join(BASE, "caige_urls.txt")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# 才哥量价博弈学的形态术语（用于文章中识别提及的形态）
TERMS = ["王者倍量柱", "王者之师", "峰峦叠翠", "一阳穿四线", "一阳穿多线", "瞒天过海",
         "凤凰归巢", "地煞星", "天煞型", "黑暗星君", "旭日东升", "阴阳双雄",
         "首板高阴", "否极泰来", "烂板成妖", "九阴真经", "九阳真经", "反包",
         "缩量回踩", "首板", "连板", "涨停", "倍量柱", "黄金柱", "量价博弈"]


def log(m):
    print(f"[{datetime.now(BJT).strftime('%H:%M:%S')}] {m}", flush=True)


def fetch(url, tries=3):
    """抓取文章 HTML。

    ⚠️ 2026-09-16 加固：微信文章含大量图片时（单篇可达 3.5MB），
    urllib 偶发 http.client.IncompleteRead（读了 2.4MB 还差 1.1MB）。
    → 三级兜底：urllib 重试 3 次 → curl --compressed 重试 → 抛错。
    """
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            data = urllib.request.urlopen(req, timeout=60).read()
            if data and len(data) > 5000:
                return data.decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    # 兜底：curl（对大响应更稳健）
    for i in range(2):
        try:
            r = subprocess.run(["curl", "-sL", "--compressed", "-A", UA,
                                "--max-time", "120", url],
                               capture_output=True, timeout=150)
            if r.stdout and len(r.stdout) > 5000:
                return r.stdout.decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
        time.sleep(3)
    raise RuntimeError(f"抓取失败（urllib+curl 均未成功）: {last}")


def to_text(raw):
    """HTML → 纯文本（保留段落）"""
    body = raw
    m = re.search(r'id="js_content"[^>]*>(.*?)</div>\s*<script', raw, re.S)
    if m:
        body = m.group(1)
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"</p>|</div>|</section>", "\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = htmlmod.unescape(body)
    body = re.sub(r"[ \t\u3000]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def parse(raw, url):
    """解析文章要素"""
    title = ""
    for pat in (r'property="og:title" content="([^"]*)"', r'var msg_title\s*=\s*[\'"]([^\'"]+)'):
        m = re.search(pat, raw)
        if m:
            title = m.group(1)
            break
    ct = ""
    m = re.search(r'var ct\s*=\s*"(\d+)"', raw)
    if m:
        ct = datetime.fromtimestamp(int(m.group(1)), BJT).strftime("%Y-%m-%d %H:%M")
    # 发布日：标题下方通常有「2026年9月15日」
    body = to_text(raw)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", body[:1200])
    pub = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else (ct[:10] if ct else "")

    # 大盘点位：压力/支撑
    levels = {}
    for m in re.finditer(r"(周[一二三四五]|明日|今日)?\s*压力[:：]\s*([\d,，、]+)", body):
        levels.setdefault("压力", []).extend(re.findall(r"\d+", m.group(2)))
    for m in re.finditer(r"(周[一二三四五]|明日|今日)?\s*支撑[:：]\s*([\d,，、]+)", body):
        levels.setdefault("支撑", []).extend(re.findall(r"\d+", m.group(2)))
    # 指数涨跌幅
    idx = []
    for m in re.finditer(r"(沪深300|上证指数|深证成指|创业板指)[^。\n]{0,40}?([涨下跌]{1,2})([\d.]+)%", body):
        idx.append(f"{m.group(1)} {m.group(2)}{m.group(3)}%")
    # 涨停高度（几板）
    height = ""
    m = re.search(r"(?:高度|空间)回到[了]?\s*([一二三四五六七八九十\d]+)板", body)
    if m:
        height = m.group(1) + "板"
    # 个股（中文简称带大写尾字母的写法，如 双星新C / 会稽S）
    stocks = re.findall(r"([\u4e00-\u9fa5]{2,4}[A-Z])(?![A-Za-z])", body)
    # 过滤非个股词（A股/A股市场/美联储/编号A 等固定语误匹配）
    _bad = ("编号", "短期", "长期", "接下", "回来", "美联", "市场", "今天", "不过",
            "但是", "所以", "如果", "可以", "我们", "这个", "那个", "什么", "已经")
    stocks = [x for x in stocks if not any(b in x for b in _bad)]
    stocks = list(dict.fromkeys(stocks))
    # 术语命中
    terms = [t for t in TERMS if t in body]
    # 量价博弈学习（考题）
    quiz = ""
    m = re.search(r"本期量价学习[-–—]?\s*([^\n]{4,80})", body)
    if m:
        quiz = m.group(1).strip()
    q_stocks = re.findall(r"([\u4e00-\u9fa5]{2,4}[A-Z])", quiz) if quiz else []
    if ct and pub == ct[:10]:
        ct = ct[11:]          # 避免「2026-09-15 2026-09-15 18:58」重复
    return {"url": url, "title": title, "pub": pub, "ct": ct, "text": body,
            "levels": {k: list(dict.fromkeys(v)) for k, v in levels.items()},
            "idx": idx, "height": height, "stocks": stocks, "terms": terms,
            "quiz": quiz, "quiz_stocks": q_stocks}


def save(art):
    os.makedirs(STORE, exist_ok=True)
    key = art["pub"] or art["ct"][:10] or hashlib.md5(art["url"].encode()).hexdigest()[:8]
    safe = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", (art["title"] or "")[:40])
    path = os.path.join(STORE, f"{key}_{safe}.md")
    lines = [f"# {art['title']}", "",
             f"- **发布**：{art['pub']} {art['ct']}",
             f"- **链接**：{art['url']}", "",
             f"- **大盘点位**：压力 {','.join(art['levels'].get('压力', []) or ['-'])} / "
             f"支撑 {','.join(art['levels'].get('支撑', []) or ['-'])}",
             f"- **指数**：{'; '.join(art['idx']) or '-'}",
             f"- **涨停高度**：{art['height'] or '-'}",
             f"- **形态术语命中**：{'; '.join(art['terms']) or '-'}",
             f"- **个股（案例）**：{'、'.join(art['stocks']) or '-'}",
             f"- **量价博弈学习**：{art['quiz'] or '-'}", "", "---", "",
             art["text"]]
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    json.dump({k: v for k, v in art.items() if k != "text"},
              open(path.replace(".md", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return path


def sync():
    """读取 caige_urls.txt 中尚未处理的 URL"""
    if not os.path.exists(URLS_FILE):
        log(f"[WARN] 未找到 URL 清单 {URLS_FILE}")
        return
    urls = [l.strip() for l in open(URLS_FILE, encoding="utf-8")
            if l.strip().startswith("http")]
    done = {json.load(open(os.path.join(STORE, f), encoding="utf-8"))["url"]
            for f in os.listdir(STORE) if f.endswith(".json")} if os.path.isdir(STORE) else set()
    todo = [u for u in urls if u not in done]
    log(f"清单 {len(urls)} 条，待处理 {len(todo)} 条")
    for u in todo:
        try:
            art = parse(fetch(u), u)
            p = save(art)
            log(f"✅ {art['pub']} {art['title'][:30]} → {os.path.basename(p)}")
        except Exception as e:
            log(f"❌ {u[:60]}: {e}")


def report():
    if not os.path.isdir(STORE):
        log("尚无存档")
        return
    arts = []
    for f in sorted(os.listdir(STORE)):
        if f.endswith(".json"):
            try:
                arts.append(json.load(open(os.path.join(STORE, f), encoding="utf-8")))
            except Exception:
                pass
    if not arts:
        log("尚无存档")
        return
    arts.sort(key=lambda a: a.get("pub") or "")
    log(f"共 {len(arts)} 篇")
    tc = defaultdict(int)
    for a in arts:
        for t in a.get("terms", []):
            tc[t] += 1
    print(f"\n{'日期':<12}{'标题':<34}{'压力':<16}{'支撑':<16}")
    for a in arts[-20:]:
        print(f"{a.get('pub',''):<12}{(a.get('title') or '')[:16]:<34}"
              f"{','.join(a.get('levels',{}).get('压力',[]) or ['-']):<16}"
              f"{','.join(a.get('levels',{}).get('支撑',[]) or ['-']):<16}")
    print("\n【形态术语出现频次】")
    for t, n in sorted(tc.items(), key=lambda x: -x[1])[:15]:
        print(f"  {t:<12} {n}")
    json.dump({"n": len(arts), "term_freq": dict(tc), "articles": arts},
              open(os.path.join(OUT, "caige_track.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    log(f"[OK] {os.path.join(OUT, 'caige_track.json')}")


def main():
    a = sys.argv[1:]
    url = None
    if "--url" in a:
        url = a[a.index("--url") + 1]
    do_sync = "--sync" in a
    do_report = "--report" in a
    if url:
        art = parse(fetch(url), url)
        p = save(art)
        log(f"✅ 已存档：{p}")
        print(f"  标题：{art['title']}")
        print(f"  发布：{art['pub']} {art['ct']}")
        print(f"  点位：压力 {art['levels'].get('压力')} / 支撑 {art['levels'].get('支撑')}")
        print(f"  指数：{art['idx']}")
        print(f"  高度：{art['height']}")
        print(f"  术语：{art['terms']}")
        print(f"  个股：{art['stocks']}")
        print(f"  考题：{art['quiz']} → {art['quiz_stocks']}")
    if do_sync:
        sync()
    if do_report or not (url or do_sync):
        report()


if __name__ == "__main__":
    main()
