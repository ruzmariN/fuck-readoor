# -*- coding: utf-8 -*-
"""从线上前端包自动提取签名密钥与上报加密密钥。

readoor 的密钥是编译进 index.js 的常量，不同版本/不同租户的构建可能不同。
硬编码一份只能保证「当时那版」可用；这里在运行时抓一次首页 -> 找到 index.js
-> 正则提取，缓存到本地，并在提取失败时回退到内置默认值。

这样换学校、换出版社、平台升级前端版本，都不用改代码。
"""
import json
import os
import re
import time
import urllib.request

from .config import PAYLOAD_KEY, SE_KEY

BUNDLE_RE = re.compile(r"https://w\.readoor\.cn/[^\"'\s>]+?/js/index\.js")
NEW_KEY_RE = re.compile(r'keysecret"[\s\S]{0,600}?newKey:"([^"]+)"')
ENC_KEY_RE = re.compile(r'encryptNew\s*=\s*async\s*\w*\s*=>\s*\{[\s\S]{0,200}?deriveKey\("([^"]+)"\)')
VERSION_RE = re.compile(r"/v/(\d+)/")

CACHE_TTL = 24 * 3600  # 一天内不重复抓包


def cache_path():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "readoor-brush", "keys.json")


def _load_cache():
    try:
        with open(cache_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_cache(data):
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _get(url, timeout=20, ua=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, "replace")


def extract(html, bundle_text):
    found = {}
    m = NEW_KEY_RE.search(bundle_text)
    if m:
        found["se_key"] = m.group(1)
    m = ENC_KEY_RE.search(bundle_text)
    if m:
        found["payload_key"] = m.group(1)
    m = BUNDLE_RE.search(html)
    if m:
        found["bundle"] = m.group(0)
        v = VERSION_RE.search(m.group(0))
        if v:
            found["version"] = v.group(1)
    return found


def discover(app_guid, origin="https://a.readoor.cn", force=False, quiet=True):
    """返回 {"se_key","payload_key","bundle","version","source"}。"""
    key = "%s|%s" % (origin.rstrip("/"), app_guid)
    cache = _load_cache()
    item = cache.get(key) or {}
    if not force and item.get("ts", 0) + CACHE_TTL > time.time() and item.get("se_key") and item.get("payload_key"):
        item["source"] = "cache"
        return item

    result = {"se_key": SE_KEY, "payload_key": PAYLOAD_KEY, "source": "builtin"}
    try:
        html = _get("%s/%s/home" % (origin.rstrip("/"), app_guid))
        m = BUNDLE_RE.search(html)
        if m:
            bundle_text = _get(m.group(0))
            found = extract(html, bundle_text)
            if found.get("se_key"):
                result["se_key"] = found["se_key"]
            if found.get("payload_key"):
                result["payload_key"] = found["payload_key"]
            result.update({k: v for k, v in found.items() if k in ("bundle", "version")})
            result["source"] = "bundle"
    except Exception as exc:
        if not quiet:
            print("  ! 前端密钥自动提取失败，使用内置默认值: %s" % exc)
        return result

    if result.get("se_key") or result.get("payload_key"):
        result["ts"] = time.time()
        cache[key] = result
        _save_cache(cache)
    return result
