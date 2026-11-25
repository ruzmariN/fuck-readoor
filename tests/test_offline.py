# -*- coding: utf-8 -*-
"""离线自检：不联网，验证签名/加密/字段名/章节筛选逻辑。

    python -m tests.test_offline
"""
import base64
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import padding as sympad
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from readoor.api import completable, duration_of, skipped
from readoor.config import PAYLOAD_KEY, SE_KEY
from readoor.crypto import dynamic_field, encrypt_payload, md5, sign

PASSED = 0
FAILED = 0


def check(name, actual, expected):
    global PASSED, FAILED
    if actual == expected:
        PASSED += 1
        print("  ok   %s" % name)
    else:
        FAILED += 1
        print("  FAIL %s\n       实际: %r\n       期望: %r" % (name, actual, expected))


def check_true(name, value):
    check(name, bool(value), True)


# ---------------------------------------------------------------- 签名
def test_sign():
    ts, nonce = "1795596607", "11111111-2222-3333-4444-555555555555"
    # 与前端 v1Sign 的定义逐层手算
    inner = md5(SE_KEY + ts + nonce)
    expected = hashlib.md5((inner + ts + nonce).encode()).hexdigest()
    check("sign 与手算一致", sign(ts, nonce), expected)
    check("sign 是 32 位小写 hex", len(sign(ts, nonce)), 32)
    check("nonce 不同则签名不同", sign(ts, nonce) == sign(ts, nonce + "x"), False)
    check("secret 不同则签名不同", sign(ts, nonce) == sign(ts, nonce, "other"), False)


# ---------------------------------------------------------------- 加密
def decrypt_payload(blob, key_text=PAYLOAD_KEY):
    key = hashlib.sha256(key_text.encode()).digest()
    iv = base64.b64decode(blob["jfug"])
    ct = base64.b64decode(blob["data"])
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(ct) + dec.finalize()
    unpadder = sympad.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def test_encrypt():
    payload = {"hello": "世界", "n": 1}
    blob = encrypt_payload(payload)
    check("密文结构", sorted(blob.keys()), ["data", "jfug"])
    check("IV 为 16 字节", len(base64.b64decode(blob["jfug"])), 16)
    import json
    check("解密回原文", json.loads(decrypt_payload(blob).decode()), payload)
    check("两次加密 IV 不同", encrypt_payload(payload)["jfug"] == blob["jfug"], False)
    # 密文长度必须是 16 的整数倍
    check("密文长度为 16 的倍数", len(base64.b64decode(blob["data"])) % 16, 0)


# ---------------------------------------------------------------- 动态字段
def test_dynamic_field():
    now_ms = 1795596607000
    expected = base64.b64encode(str(now_ms).encode()).decode()[2:8]
    check("动态字段名 = btoa(ms)[2:8]", dynamic_field(now_ms), expected)
    check("动态字段名长度 6", len(dynamic_field(now_ms)), 6)


# ---------------------------------------------------------------- 章节筛选
def test_sections():
    sections = [
        {"section_guid": "a", "section_type": 401, "section_name": "目录"},
        {"section_guid": "b", "section_type": 403, "courseware_type": 101, "section_name": "pdf"},
        {"section_guid": "c", "section_type": 403, "courseware_type": 104, "section_name": "视频"},
        {"section_guid": "d", "section_type": 403, "courseware_type": 118, "section_name": "试卷"},
        {"section_guid": "e", "section_type": 404, "courseware_type": 101, "section_name": "试卷节点"},
        {"section_guid": "f", "section_type": 403, "section_name": "空节点"},
    ]
    guids = [s["section_guid"] for s in completable(sections)]
    check("目录/试卷/空节点被排除", guids, ["b", "c"])
    reasons = {s["section_guid"]: r for s, r in skipped(sections)}
    check("试卷被标记原因", reasons.get("d"), "需要考试作答")
    check("试卷节点被标记原因", reasons.get("e"), "试卷节点")

    video = {"files": [{"file_extension": "mp4", "file_duration": 115.518}]}
    check("时长解析", duration_of(video), 115.518)
    check("无时长返回 0", duration_of({"files": [{"pages": "5"}]}), 0.0)
    check("无 files 返回 0", duration_of({}), 0.0)


def main():
    print("readoor-brush 离线自检\n")
    for fn in (test_sign, test_encrypt, test_dynamic_field, test_sections):
        print("[%s]" % fn.__name__)
        fn()
    print("\n通过 %d，失败 %d" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
