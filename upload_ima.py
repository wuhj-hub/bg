#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_ima.py —— 将 markdown 报告上传到 ima 知识库

环境变量：
  IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY  (ima 开放 API 凭证，配到 GitHub Secrets)
  IMA_KB_ID      (目标知识库 ID，必填)
  IMA_FOLDER_ID  (可选，目标文件夹 ID；省略则传根目录)

用法：python3 upload_ima.py --file panhou_lianghua.md --name "盘后量化_$(date +%Y-%m-%d).md"

注意：此脚本由 GitHub Actions 调用，数据上传到「复盘报告」文件夹作为复盘报告的数据源。
流程：create_media → cos_upload → add_knowledge（含 folder_id）
"""

import os
import sys
import json
import argparse
import hashlib
import hmac
import time
import urllib.parse
import urllib.request
from http.client import HTTPSConnection


def hmac_sha1(key, data):
    if isinstance(key, str):
        key = key.encode("utf-8")
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hmac.new(key, data, hashlib.sha1).hexdigest()


def sha1(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha1(data).hexdigest()


def build_authorization(secret_id, secret_key, method, pathname, headers, start_time, expired_time):
    key_time = f"{start_time};{expired_time}"
    header_keys = sorted(headers.keys())
    http_headers = "&".join([f"{k.lower()}={urllib.parse.quote(headers[k])}" for k in header_keys])
    http_string = f"{method.lower()}\n{pathname}\n\n{http_headers}\n"
    sign_key = hmac_sha1(secret_key, key_time)
    string_to_sign = f"sha1\n{key_time}\n{sha1(http_string)}\n"
    signature = hmac_sha1(sign_key, string_to_sign)
    header_list = ";".join([k.lower() for k in header_keys])
    return "&".join([
        "q-sign-algorithm=sha1",
        f"q-ak={secret_id}",
        f"q-sign-time={key_time}",
        f"q-key-time={key_time}",
        f"q-header-list=" + header_list,
        f"q-url-param-list=",
        f"q-signature={signature}",
    ])


def send_ima(api_path, body_str):
    for var in ("IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY"):
        if var not in os.environ:
            raise RuntimeError(f"missing env {var}")
    cid = os.environ["IMA_OPENAPI_CLIENTID"]
    key = os.environ["IMA_OPENAPI_APIKEY"]
    req = urllib.request.Request(
        f"https://ima.qq.com/{api_path}",
        data=body_str.encode("utf-8"),
        headers={"ima-openapi-clientid": cid, "ima-openapi-apikey": key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def create_media(kb_id, filename, size, media_type, content_type, file_ext):
    body = {
        "media_type": media_type,
        "file_name": filename,
        "file_size": size,
        "content_type": content_type,
        "knowledge_base_id": kb_id,
        "file_ext": file_ext,
    }
    resp = send_ima("openapi/wiki/v1/create_media", json.dumps(body))
    if resp.get("code", 0) != 0:
        raise RuntimeError(f"create_media failed: {resp}")
    return resp["data"]["media_id"], resp["data"]["cos_credential"]


def cos_upload(cred, file_path, content_type):
    secret_id = cred["secret_id"]
    secret_key = cred["secret_key"]
    token = cred["token"]
    bucket = cred["bucket_name"]
    region = cred["region"]
    cos_key = cred["cos_key"]
    with open(file_path, "rb") as f:
        data = f.read()
    hostname = f"{bucket}.cos.{region}.myqcloud.com"
    pathname = f"/{cos_key}"
    sign_headers = {"content-length": str(len(data)), "host": hostname}
    auth = build_authorization(secret_id, secret_key, "PUT", pathname, sign_headers,
                               cred["start_time"], cred["expired_time"])
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(len(data)),
        "Authorization": auth,
        "x-cos-security-token": token,
    }
    conn = HTTPSConnection(hostname, 443)
    conn.request("PUT", pathname, body=data, headers=headers)
    resp = conn.getresponse()
    if not (200 <= resp.status < 300):
        raise RuntimeError(f"COS upload failed {resp.status}: {resp.read().decode()}")
    conn.close()


def add_knowledge(kb_id, media_id, title, media_type, folder_id=None):
    """将已上传到 COS 的媒体关联到知识库"""
    body = {
        "media_type": media_type,
        "media_id": media_id,
        "title": title,
        "knowledge_base_id": kb_id,
    }
    if folder_id:
        body["folder_id"] = folder_id
    resp = send_ima("openapi/wiki/v1/add_knowledge", json.dumps(body))
    if resp.get("code", 0) != 0:
        raise RuntimeError(f"add_knowledge failed: {resp}")
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--name", default=None)
    a = ap.parse_args()
    kb_id = os.environ.get("IMA_KB_ID")
    if not kb_id:
        raise RuntimeError("IMA_KB_ID not set")
    folder_id = os.environ.get("IMA_FOLDER_ID", "")
    fp = a.file
    filename = a.name or os.path.basename(fp)
    size = os.path.getsize(fp)
    media_type = 7  # Markdown
    content_type = "text/markdown"
    file_ext = "md"

    # Step 1: 创建媒体条目，获取 COS 上传凭证
    media_id, cred = create_media(kb_id, filename, size, media_type, content_type, file_ext)
    print(f"[OK] create_media -> {media_id}")

    # Step 2: 上传文件内容到 COS
    cos_upload(cred, fp, content_type)
    print(f"[OK] cos_upload done")

    # Step 3: 将媒体关联到知识库（含目标文件夹）
    folder_arg = folder_id if folder_id else None
    add_knowledge(kb_id, media_id, filename, media_type, folder_id=folder_arg)
    folder_info = f"folder={folder_id}" if folder_id else "root"
    print(f"[OK] add_knowledge done ({folder_info})")
    print(f"[OK] 报告已发布: {filename}")


if __name__ == "__main__":
    main()
