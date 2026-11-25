# -*- coding: utf-8 -*-
"""签名与加密。

readoor 前端对 base / user / statistics / mrr 四个域名的所有 POST 都追加一组
协议字段到 JSON body 里：

    ts     秒级时间戳（以服务端时间为准，前端会做 offset 校正）
    nonce  uuid4
    sign   md5( md5(secret + ts + nonce) + ts + nonce )
    v      "1.0.0"

学习进度上报 pStatIf 另外要求 body 整体 AES-256-CBC 加密：
    key = sha256(固定前端密钥)
    iv  = 16 随机字节
    out = {"data": base64(密文), "jfug": base64(iv)}
"""
import base64
import hashlib
import json
import os
import time
import uuid

from cryptography.hazmat.primitives import padding as sympad
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .config import PAYLOAD_KEY, SE_KEY, SE_VERSION


def md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def sign(ts, nonce, secret=None):
    """前端 v1Sign 的等价实现。"""
    secret = secret or SE_KEY
    inner = md5(secret + str(ts) + str(nonce))
    return md5(inner + str(ts) + str(nonce))


class Signer:
    """带服务端时间偏移校正的签名器。

    前端会观察 base 域返回的 time 字段并记下 delta，避免本机时钟不准导致签名
    被判定过期。这里做同样的事。
    """

    MAX_DRIFT = 3600  # 超过 1 小时的偏差不采信，避免把错误时间当成真

    def __init__(self, secret=None):
        self.secret = secret or SE_KEY
        self.offset = 0.0

    def now(self):
        return int(time.time() + self.offset)

    def observe(self, server_time):
        try:
            server_time = int(server_time)
        except (TypeError, ValueError):
            return
        delta = server_time - time.time()
        if abs(delta) <= self.MAX_DRIFT:
            self.offset = delta

    def meta(self):
        ts = str(self.now())
        nonce = str(uuid.uuid4())
        return {
            "ts": ts,
            "nonce": nonce,
            "sign": sign(ts, nonce, self.secret),
            "v": SE_VERSION,
        }


def encrypt_payload(payload, key_text=None):
    """AES-256-CBC + PKCS7，返回前端 pStatIf 需要的 {"data","jfug"}。"""
    key = hashlib.sha256((key_text or PAYLOAD_KEY).encode("utf-8")).digest()
    iv = os.urandom(16)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padder = sympad.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return {
        "data": base64.b64encode(ciphertext).decode("ascii"),
        "jfug": base64.b64encode(iv).decode("ascii"),
    }


def dynamic_field(now_ms):
    """前端用 btoa(毫秒时间戳).slice(2,8) 生成一个一次性字段名。

    该字段的值就是 is_done（1 表示完成）。服务端按同一算法复算字段名，
    所以时间戳必须与 base_data.time_stamp 完全一致。
    """
    raw = base64.b64encode(str(now_ms).encode("ascii")).decode("ascii")
    return raw[2:8]
