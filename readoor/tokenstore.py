# -*- coding: utf-8 -*-
"""登录态（token）发现。

readoor 把 token 存在浏览器 localStorage 的 `token_<app_guid>` 键里，
值是 JSON：{"token": "<JWT>", "time": "...", "userinfo": {...}}。

本模块在 Windows / macOS / Linux 上扫描常见浏览器的本地存储，按 JWT 的 aud
字段匹配 app_guid，避免拿到别的应用的 token。

支持的来源（按优先级）：
  1. 命令行 --token / 环境变量 READOOR_TOKEN
  2. --token-file 指定的文件，或 ~/.readoor-token
  3. Chromium 系：Chrome / Edge / Brave / Chromium / Vivaldi / Opera
  4. Firefox：storage/default/https+++<host>/ls/data.sqlite
  5. Safari（macOS）：~/Library/Safari/LocalStorage
"""
import base64
import glob
import json
import os
import re
import sqlite3
import sys
import tempfile

JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


# ---------------------------------------------------------------- JWT 工具
def jwt_payload(token):
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def jwt_aud(token):
    return jwt_payload(token).get("aud")


def jwt_exp(token):
    return jwt_payload(token).get("exp")


def token_alive(token):
    exp = jwt_exp(token)
    if not exp:
        return True
    import time
    return int(exp) > int(time.time()) + 30


def describe(token):
    p = jwt_payload(token)
    acc = (p.get("data") or {}).get("account") or {}
    return {
        "aud": p.get("aud"),
        "user": acc.get("name"),
        "biz_user_id": (p.get("data") or {}).get("biz_user_id"),
        "exp": p.get("exp"),
    }


# ---------------------------------------------------------------- 路径列表
def _home(*parts):
    return os.path.join(os.path.expanduser("~"), *parts)


def chromium_roots():
    """返回所有 Chromium 系浏览器的 User Data 根目录。"""
    roots = []
    appdata = os.environ.get("LOCALAPPDATA") or _home("AppData", "Local")
    roaming = os.environ.get("APPDATA") or _home("AppData", "Roaming")
    if sys.platform.startswith("win"):
        roots += [
            os.path.join(appdata, "Google", "Chrome", "User Data"),
            os.path.join(appdata, "Google", "Chrome Beta", "User Data"),
            os.path.join(appdata, "Google", "Chrome SxS", "User Data"),
            os.path.join(appdata, "Microsoft", "Edge", "User Data"),
            os.path.join(appdata, "BraveSoftware", "Brave-Browser", "User Data"),
            os.path.join(appdata, "Chromium", "User Data"),
            os.path.join(appdata, "Vivaldi", "User Data"),
            os.path.join(roaming, "Opera Software", "Opera Stable"),
        ]
    elif sys.platform == "darwin":
        support = _home("Library", "Application Support")
        roots += [
            os.path.join(support, "Google", "Chrome"),
            os.path.join(support, "Google", "Chrome Beta"),
            os.path.join(support, "Microsoft Edge"),
            os.path.join(support, "BraveSoftware", "Brave-Browser"),
            os.path.join(support, "Chromium"),
            os.path.join(support, "Vivaldi"),
            os.path.join(support, "com.operasoftware.Opera"),
        ]
    else:
        cfg = os.environ.get("XDG_CONFIG_HOME") or _home(".config")
        roots += [
            os.path.join(cfg, "google-chrome"),
            os.path.join(cfg, "google-chrome-beta"),
            os.path.join(cfg, "microsoft-edge"),
            os.path.join(cfg, "BraveSoftware", "Brave-Browser"),
            os.path.join(cfg, "chromium"),
            os.path.join(cfg, "vivaldi"),
            os.path.join(cfg, "opera"),
        ]
    return [r for r in roots if os.path.isdir(r)]


def firefox_roots():
    if sys.platform.startswith("win"):
        base = os.path.join(os.environ.get("APPDATA") or _home("AppData", "Roaming"), "Mozilla", "Firefox")
    elif sys.platform == "darwin":
        base = _home("Library", "Application Support", "Firefox")
    else:
        base = _home(".mozilla", "firefox")
    return [base] if os.path.isdir(base) else []


# ---------------------------------------------------------------- 解析实现
def _decode_text(blob):
    """leveldb 里的字符串可能是 UTF-16LE，也可能是 UTF-8。"""
    out = []
    for shift in (0, 1):
        try:
            out.append(blob[shift:].decode("utf-16le", "ignore"))
        except Exception:
            pass
    try:
        out.append(blob.decode("utf-8", "ignore"))
    except Exception:
        pass
    return out


def scan_token_in_blob(blob, app_guid):
    """在一个二进制块里找 aud 匹配的 JWT。"""
    best = None
    for text in _decode_text(blob):
        for hit in JWT_RE.findall(text):
            if app_guid and jwt_aud(hit) != app_guid:
                continue
            if not token_alive(hit):
                continue
            if not best or len(hit) > len(best):
                best = hit
    return best


def from_chromium(app_guid, all_matches=False):
    """扫描 Chromium 系浏览器的 Local Storage/leveldb。"""
    found = []
    for root in chromium_roots():
        # 每个 profile 目录下都有 Local Storage/leveldb
        patterns = [
            os.path.join(root, "*", "Local Storage", "leveldb"),
            os.path.join(root, "Local Storage", "leveldb"),
        ]
        level_dirs = []
        for pat in patterns:
            level_dirs += [p for p in glob.glob(pat) if os.path.isdir(p)]
        for level_dir in level_dirs:
            for name in sorted(os.listdir(level_dir)):
                if not (name.endswith(".ldb") or name.endswith(".log")):
                    continue
                path = os.path.join(level_dir, name)
                try:
                    with open(path, "rb") as fh:
                        blob = fh.read()
                except OSError:
                    continue  # 文件被浏览器独占时跳过
                hit = scan_token_in_blob(blob, app_guid)
                if hit:
                    found.append((path, hit))
    if not found:
        return ([], []) if all_matches else (None, None)
    # 取最新的一个（按 mtime）
    found.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
    if all_matches:
        return [h for _, h in found], [p for p, _ in found]
    return found[0][1], found[0][0]


def _read_sqlite(path, sql):
    """把 sqlite 复制到临时文件再读，避免被浏览器锁住。"""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite")
    tmp.close()
    try:
        import shutil
        shutil.copy2(path, tmp.name)
        con = sqlite3.connect(tmp.name)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()
    except Exception:
        return []
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def from_firefox(app_guid):
    for root in firefox_roots():
        for data_db in glob.glob(os.path.join(root, "*", "storage", "default", "https+++*", "ls", "data.sqlite")):
            rows = _read_sqlite(data_db, "SELECT key, value FROM data")
            for _key, value in rows:
                if value is None:
                    continue
                if isinstance(value, str):
                    value = value.encode("utf-8", "ignore")
                for text in _decode_text(value):
                    for hit in JWT_RE.findall(text):
                        if app_guid and jwt_aud(hit) != app_guid:
                            continue
                        if token_alive(hit):
                            return hit, data_db
    return None, None


def from_safari(app_guid):
    if sys.platform != "darwin":
        return None, None
    for path in glob.glob(_home("Library", "Safari", "LocalStorage", "*.localstorage")):
        rows = _read_sqlite(path, "SELECT key, value FROM ItemTable")
        for _key, value in rows:
            if not value:
                continue
            if isinstance(value, str):
                value = value.encode("utf-8", "ignore")
            for text in _decode_text(value):
                for hit in JWT_RE.findall(text):
                    if app_guid and jwt_aud(hit) != app_guid:
                        continue
                    if token_alive(hit):
                        return hit, path
    return None, None


def from_env():
    return os.environ.get("READOOR_TOKEN") or None


def from_file(path=None):
    path = path or os.path.join(os.path.expanduser("~"), ".readoor-token")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError:
        return None
    if not text:
        return None
    m = JWT_RE.search(text)
    if m:
        return m.group(0)
    return text or None


def candidates(app_guid=None, token_file=None, verbose=False):
    """按优先级产出所有候选 token（去重），用于逐个试到能登录为止。"""
    seen = set()

    def emit(token, source):
        if not token or token in seen:
            return None
        if app_guid and jwt_aud(token) not in (None, app_guid):
            return None
        seen.add(token)
        return token, source

    token = from_env()
    if token:
        item = emit(token, "环境变量 READOOR_TOKEN")
        if item:
            yield item

    token = from_file(token_file)
    if token:
        item = emit(token, "token 文件")
        if item:
            yield item

    for name, fn in (("chromium", from_chromium), ("firefox", from_firefox), ("safari", from_safari)):
        try:
            if fn is from_chromium:
                hits, wheres = fn(app_guid, all_matches=True)
            else:
                hit, where = fn(app_guid)
                hits, wheres = ([hit], [where]) if hit else ([], [])
        except Exception as exc:  # 单个浏览器失败不影响其它
            if verbose:
                print("  [%s] 跳过: %s" % (name, exc))
            continue
        for token, where in zip(hits, wheres):
            item = emit(token, "%s (%s)" % (name, where))
            if item:
                yield item


def discover(app_guid=None, token_file=None, verbose=False):
    """兼容旧接口：返回第一个候选。"""
    for token, source in candidates(app_guid, token_file, verbose):
        return token, source
    return None, None


TOKEN_HELP = """\
没找到登录 token。可以任选一种方式：

  1. 在本机浏览器登录课程页后直接重跑（脚本会自动读取 Chrome/Edge/Brave/Firefox）
  2. 手动指定：
       python brush.py --token "<JWT>"
  3. 写入文件（~/.readoor-token 或 --token-file 指定）：
       浏览器打开课程页 -> F12 -> Console 执行：
         JSON.parse(localStorage.getItem('token_<app_guid>')).token
       把输出整串粘进文件
  4. 手机/其它设备：同上用 F12/远程调试取出 token，写进 ~/.readoor-token
     再把文件同步到运行脚本的机器上
"""
