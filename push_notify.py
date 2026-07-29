#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送全量扫描结果到微信（PushPlus 备份通道）。

不依赖 ima 上传成功（workflow if: always() 调用）。
读取 panhou_lianghua.md 提取关键摘要推送。
根据 IMA_UPLOAD_OK / IMA_CRED_EXPIRED 动态提示：
  - 成功：已同步 ima
  - 凭证失效(401)：升级告警，请去 ima 重新生成并回填 secret（自愈指引）
  - 其他失败：结果备份
"""

import os
import json
import subprocess
import time
import smtplib
import email.utils
from email.mime.text import MIMEText
import urllib.request
from datetime import datetime, timedelta

TOKEN = os.environ.get("PUSH_TOKEN", "")
SERVICE = os.environ.get("PUSH_SERVICE", "pushplus").lower()
TODAY = time.strftime("%Y-%m-%d")
RUN_NUM = os.environ.get("RUN_NUMBER", "")
RUN_TAG = f" bg#{RUN_NUM}" if RUN_NUM else ""
IMA_OK = os.environ.get("IMA_UPLOAD_OK", "true").lower() in ("true", "1", "ok", "")
CRED_EXPIRED = os.environ.get("IMA_CRED_EXPIRED", "false").lower() in ("true", "1", "yes")
RESULT_FILE = os.environ.get("RESULT_FILE", "panhou_lianghua.md")
# 邮件配置
MAIL_ENABLED = os.environ.get("MAIL_ENABLED", "").lower() in ("true", "1", "yes")
MAIL_SMTP = os.environ.get("MAIL_SMTP", "smtp.qq.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "465"))
MAIL_USER = os.environ.get("MAIL_USER", "")
MAIL_PASS = os.environ.get("MAIL_PASS", "")  # SMTP授权码
MAIL_TO = os.environ.get("MAIL_TO", "")


def extract_summary(path, max_chars=15000):
    """读取结果 md，提取重点标的完整表格 + 信号释义（保留 Markdown 表格结构）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception as e:
        return f"（无法读取结果文件 {path}：{e}）"

    import re

    # 重点标的表格（从 ## 二、到 ## 三、之间，捕获完整的多段表格）
    table_match = re.search(r'## 二、重点标的.*?(?=## 三、)', text, re.DOTALL)
    sig_match = re.search(r'## 三、信号释义.*', text, re.DOTALL)

    parts = []
    if table_match:
        parts.append(table_match.group(0).strip())
    if sig_match:
        parts.append(sig_match.group(0).strip())

    if parts:
        body = "\n\n".join(parts)
    else:
        # fallback: 关键词提取
        lines = text.splitlines()
        keywords = ("★", "重点", "买入", "关注", "信号", "精选", "共振",
                    "操作建议", "评分", ">>>", "候选", "预警")
        picked = [ln for ln in lines if any(k in ln for k in keywords)]
        body = "\n".join(picked[:60]) if picked else "\n".join(lines[:120])

    if len(body) > max_chars:
        body = body[:max_chars] + "\n\n…（内容过长已截断，完整版见 ima「复盘报告」）"
    return body


def build_msg():
    """构建推送内容 — 优先使用完整报告，回退到摘要"""
    full_report = os.environ.get("FULL_REPORT_FILE", "")
    if full_report and os.path.exists(full_report):
        try:
            with open(full_report, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if len(content) > 15000:
                content = content[:15000] + "\n\n> ...（内容过长已截断，完整报告见IMA知识库）"
            return content
        except:
            pass
    
    if IMA_OK and not CRED_EXPIRED:
        head = f"# ✅ 全量扫描完成{RUN_TAG} · {TODAY}\n\n> 已同步至 ima「复盘报告」知识库。"
    elif CRED_EXPIRED:
        head = (
            f"# ⚠️ 全量扫描完成{RUN_TAG} · {TODAY}\n\n"
            f"> **ima OpenAPI 凭证已失效（上传持续 401 / skill auth failed）**，本次结果未能同步至 ima。\n\n"
            f"> **【需要您处理 · 自愈步骤】**\n"
            f"> 1. 打开 https://ima.qq.com/agent-interface 点「获取 API Key」重新生成一对 client_id / api_key\n"
            f"> 2. 把新值分别更新到 GitHub 仓库 Secrets：\n"
            f"> 　　· `IMA_OPENAPI_CLIENTID`\n> 　　· `IMA_OPENAPI_APIKEY`\n"
            f"> 3. 回填后下一次扫描将自动用新凭证成功（无需改代码）。\n\n"
            f"> 以下为本次结果备份："
        )
    else:
        head = (
            f"# ⚠️ 全量扫描完成{RUN_TAG} · {TODAY}\n\n"
            f"> **ima 上传失败（非凭证失效，疑似网络/限流）**，以下是结果备份："
        )
    summary = extract_summary(RESULT_FILE)
    return f"{head}\n\n## 📊 关键结果\n\n{summary}\n\n---\n🤖 由 full_market_scan{RUN_TAG} 自动推送（PushPlus 备份通道）"


def _post(url, body):
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def push_pushplus(token):
    if CRED_EXPIRED:
        title = f"⚠️ima凭证失效{RUN_TAG} 请重置 {TODAY}"
    elif not IMA_OK:
        title = f"⚠️扫描完成{RUN_TAG}(ima失败) {TODAY}"
    else:
        title = f"扫描完成{RUN_TAG} {TODAY}"
    body = json.dumps({
        "token": token,
        "title": title,
        "content": build_msg(),
        "template": "markdown",
    }).encode("utf-8")
    return _post("https://www.pushplus.plus/send", body)


def md_to_html(md: str) -> str:
    """简单Markdown转HTML（邮件用）"""
    import html as html_mod
    lines = md.split('\n')
    out = []
    in_table = False
    for line in lines:
        if line.startswith('# '):
            out.append(f'<h1>{html_mod.escape(line[2:])}</h1>')
        elif line.startswith('## '):
            out.append(f'<h2>{html_mod.escape(line[3:])}</h2>')
        elif line.startswith('### '):
            out.append(f'<h3>{html_mod.escape(line[4:])}</h3>')
        elif line.startswith('|') and '---' not in line:
            if not in_table:
                out.append('<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse">')
                in_table = True
            cols = [c.strip() for c in line.split('|')[1:-1]]
            tag = 'th' if out[-1].endswith('</tr>') and '<tr>' in out[-1] else 'td'
            out.append(f'<tr>{"".join(f"<{tag}>{html_mod.escape(c)}</{tag}>" for c in cols)}</tr>')
        elif line.strip().startswith('|---') or line.strip().startswith('|:---'):
            continue
        elif line.strip().startswith('> '):
            out.append(f'<blockquote>{html_mod.escape(line[2:])}</blockquote>')
        elif line.strip() == '':
            if in_table:
                out.append('</table>')
                in_table = False
            out.append('<br>')
        elif '---' in line and len(line.strip()) <= 4:
            out.append('<hr>')
        else:
            out.append(f'<p>{html_mod.escape(line)}</p>')
    if in_table:
        out.append('</table>')
    return '\n'.join(out)


def push_email(title, content):
    """SMTP邮件推送（HTML格式，兼容QQ邮箱）"""
    import html as html_mod
    if not MAIL_USER or not MAIL_PASS or not MAIL_TO:
        print("MAIL_SKIP: 邮件未配置(需MAIL_USER/MAIL_PASS/MAIL_TO)")
        return False
    try:
        html_content = md_to_html(content)
        html_body = f"""<html><body style="font-family:'Microsoft YaHei',Arial,sans-serif;font-size:14px;line-height:1.6;color:#333;padding:20px">
{html_content}
</body></html>"""
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = title
        msg["From"] = email.utils.formataddr(("全量扫描", MAIL_USER))
        msg["To"] = MAIL_TO
        msg["Date"] = email.utils.formatdate(localtime=True)
        
        server = smtplib.SMTP_SSL(MAIL_SMTP, MAIL_PORT, timeout=30)
        server.login(MAIL_USER, MAIL_PASS)
        server.sendmail(MAIL_USER, [MAIL_TO], msg.as_string())
        server.quit()
        print(f"MAIL_OK → {MAIL_TO}")
        return True
    except Exception as e:
        print(f"MAIL_ERR: {e}")
        return False


def main():
    results = []
    
    # PushPlus通道
    if TOKEN:
        try:
            if SERVICE == "pushplus":
                resp = push_pushplus(TOKEN)
                results.append(("PushPlus", "OK" if resp else "FAIL"))
        except Exception as e:
            results.append(("PushPlus", f"ERR: {e}"))
    
    # 邮件通道
    if MAIL_ENABLED:
        content = build_msg()
        title = f"全量扫描{RUN_TAG} {TODAY}"
        ok = push_email(title, content)
        results.append(("邮件", "OK" if ok else "FAIL"))
    
    if results:
        print(f"推送结果: {' | '.join([f'{n}={s}' for n,s in results])}")
    else:
        print("无推送通道启用")


if __name__ == "__main__":
    main()
