#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_ima.py —— 将 markdown 报告上传到 ima 知识库（可选移入文件夹）

环境变量：
  IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY  (ima 开放 API 凭证，配到 GitHub Secrets)
  IMA_KB_ID      (目标知识库 ID，必填)
  IMA_FOLDER_ID  (可选，目标文件夹 ID；省略则传根目录)

用法：python3 upload_ima.py --file full_market_report.md
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
    string_to_sign = f"sha1\n{key_time}\n{sha1(http_string)}\n"
    signature = hmac_sha1(secret_key, string_to_sign)
    header_list = ";".join([k.lower() for k in header_keys])
    return "&".join([
        "q-sign-algorithm=sha1",
        f"q-ak={secret_id}",
        f"q-sign-time={key_time}",
        f"q-key-time={key_time}",
        "q-header-list=" + header_list,
        "q-url-param-list=",
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
    secret_id = cred["secret-id"]
    secret_key = cred["secret-key"]
    token = cred["token"]
    bucket = cred["bucket"]
    region = cred["region"]
    cos_key = cred["cos-key"]
    with open(file_path, "rb") as f:
        data = f.read()
    hostname = f"{bucket}.cos.{region}.myqcloud.com"
    pathname = f"/{cos_key}"
    sign_headers = {"content-length": str(len(data)), "host": hostname}
    auth = build_authorization(secret_id, secret_key, "PUT", pathname, sign_headers,
                               str(int(time.time())), str(int(time.time()) + 3600))
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


def move_to_folder(kb_id, media_id, folder_id):
    body = {
        "src_knowledge_base_id": kb_id,
        "dst_knowledge_base_id": kb_id,
        "dst_folder_id": folder_id,
        "infos": [{"media_id": media_id}],
    }
    resp = send_ima("openapi/wiki/v1/move_knowledge", json.dumps(body))
    if resp.get("code", 0) != 0:
        raise RuntimeError(f"move failed: {resp}")
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
    media_id, cred = create_media(kb_id, filename, size, 7, "text/markdown", "md")
    cos_upload(cred, fp, "text/markdown")
    print(f"[OK] uploaded media_id={media_id}")
    if folder_id:
        move_to_folder(kb_id, media_id, folder_id)
        print(f"[OK] moved to folder {folder_id}")


if __name__ == "__main__":
    main()
