#!/usr/bin/env python3
"""
baidu_pan.py —— 百度网盘直读工具（原生API版，绕过bypy兼容问题）
====================================================
基于 xpan API + OAuth2 token（从 ~/.bypy/bypy.json 读取，方法B自建App身份）

命令:
  list [目录]       列出目录内容（默认 / 根目录 = 全盘）
  download <路径>   下载文件到本地（默认 ./downloads/）
  search <关键词>   搜索文件
  info              网盘信息（配额）
====================================================
"""
import json, os, sys, time, urllib.request, urllib.parse

TOKEN_FILE = os.path.expanduser("~/.bypy/bypy.json")
BASE = "https://pan.baidu.com/rest/2.0/xpan"

def get_token():
    d = json.load(open(TOKEN_FILE))
    return d.get("access_token", "")

def api(path, params):
    """调 xpan API，带 token 刷新重试"""
    tok = get_token()
    params["access_token"] = tok
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(2):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url), timeout=20)
            return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if '"errno":-6' in body and attempt == 0:  # token过期，尝试刷新
                refresh_token()
                continue
            return {"errno": e.code, "msg": body[:200]}
        except Exception as e:
            return {"errno": -1, "msg": str(e)}
    return {"errno": -9}

def refresh_token():
    """用 refresh_token 换新 access_token"""
    d = json.load(open(TOKEN_FILE))
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": d.get("refresh_token", ""),
        "client_id": d.get("client_id", "") or os.environ.get("BAIDU_API_KEY", ""),
        "client_secret": os.environ.get("BAIDU_API_SECRET", ""),
    }).encode()
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            "https://openapi.baidu.com/oauth/2.0/token", data=data), timeout=20)
        new = json.loads(r.read().decode())
        if "access_token" in new:
            d["access_token"] = new["access_token"]
            d["refresh_token"] = new.get("refresh_token", d.get("refresh_token"))
            json.dump(d, open(TOKEN_FILE, "w"))
            print("[token] 已刷新")
    except Exception as e:
        print("[token] 刷新失败:", e)

def fmt_size(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}PB"

def cmd_list(dir_path="/"):
    r = api("/file", {"method": "list", "dir": dir_path, "limit": 100, "order": "name"})
    if r.get("errno") != 0:
        print("❌ errno:", r.get("errno"), r.get("msg", ""))
        return
    items = r.get("list", [])
    if not items:
        print(f"📁 {dir_path} 为空")
        return
    print(f"📁 {dir_path}（{len(items)} 项）:")
    print(f"{'类型':<4} {'大小':>10}  {'名称'}")
    print("-" * 60)
    for it in items:
        t = "📂" if it.get("isdir") else "📄"
        sz = "-" if it.get("isdir") else fmt_size(it.get("size", 0))
        print(f"{t:<4} {sz:>10}  {it.get('server_filename', it.get('path'))}")

def cmd_download(path, out_dir="downloads"):
    r = api("/file", {"method": "download", "path": path})
    # download 接口返回文件流而非 JSON
    tok = get_token()
    url = BASE + "/file?" + urllib.parse.urlencode(
        {"method": "download", "path": path, "access_token": tok})
    os.makedirs(out_dir, exist_ok=True)
    fname = path.split("/")[-1]
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60) as resp, \
             open(os.path.join(out_dir, fname), "wb") as f:
            f.write(resp.read())
        print(f"✅ 已下载: {out_dir}/{fname}")
    except Exception as e:
        print("❌ 下载失败:", e)

def cmd_search(keyword):
    r = api("/file", {"method": "search", "key": keyword, "limit": 50})
    if r.get("errno") != 0:
        print("❌ errno:", r.get("errno"))
        return
    for it in r.get("list", []):
        t = "📂" if it.get("isdir") else "📄"
        print(f"{t} {it.get('path')}")

def cmd_info():
    r = api("/nas", {"method": "uinfo"})
    print(r)

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list(sys.argv[2] if len(sys.argv) > 2 else "/")
    elif cmd == "download":
        cmd_download(sys.argv[2])
    elif cmd == "search":
        cmd_search(sys.argv[2])
    elif cmd == "info":
        cmd_info()
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
