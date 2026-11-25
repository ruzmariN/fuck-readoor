# -*- coding: utf-8 -*-
"""HTTP 层：不依赖 requests，只用标准库，方便在任意设备上直接跑。"""
import json
import random
import socket
import ssl
import time
import urllib.error
import urllib.request

from .crypto import Signer

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36"
)


class ApiError(RuntimeError):
    """接口返回了 status != 1。"""

    def __init__(self, message, status=None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class TokenError(ApiError):
    """token 无效 / 过期。"""


class Http:
    def __init__(self, timeout=20, retries=2, proxy=None, user_agent=None, origin=None,
                 se_key=None, insecure=False):
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.user_agent = user_agent or DEFAULT_UA
        self.origin = origin or "https://a.readoor.cn"
        self.signer = Signer(se_key)
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        if insecure:
            # 部分公司网络/抓包代理会替换证书，提供显式关闭校验的开关
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self.opener = urllib.request.build_opener(*handlers)

    # ---------------------------------------------------------------- 底层
    def raw_post(self, url, body, token=None, timeout=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": self.user_agent,
            "Origin": self.origin,
            "Referer": self.origin + "/",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, data=data, headers=headers)
        last = None
        for attempt in range(self.retries + 1):
            try:
                with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                    return resp.status, resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                body_text = exc.read().decode("utf-8", "replace")
                # 4xx 不重试（除 429）
                if exc.code != 429 and exc.code < 500:
                    return exc.code, body_text
                last = ApiError("HTTP %s" % exc.code, status=exc.code, payload={"body": body_text[:400]})
            except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
                last = ApiError("网络错误: %s" % exc)
            if attempt < self.retries:
                time.sleep(0.8 * (attempt + 1) + random.random() * 0.4)
        raise last or ApiError("请求失败")

    # ---------------------------------------------------------------- 业务
    def post(self, url, body=None, token=None, signed=True, timeout=None):
        """带 SE 签名的 POST，返回解析后的 dict。"""
        body = dict(body or {})
        if signed:
            body.update(self.signer.meta())
        status, text = self.raw_post(url, body, token=token, timeout=timeout)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise ApiError("响应不是 JSON (HTTP %s): %s" % (status, text[:200]), status=status)

        # 用服务端时间校正签名时钟
        if isinstance(data, dict) and data.get("time"):
            self.signer.observe(data["time"])

        if isinstance(data, dict) and data.get("status") == 1:
            return data

        message = ""
        if isinstance(data, dict):
            message = data.get("message") or data.get("msg") or ""
            if isinstance(message, dict):
                message = json.dumps(message, ensure_ascii=False)
        text_all = (str(message) + " " + json.dumps(data, ensure_ascii=False)[:300]).lower()
        if any(k in text_all for k in ("token", "登录", "login", "未授权", "unauthorized")):
            raise TokenError("登录态失效: %s" % (message or data), status=data.get("status"), payload=data)
        raise ApiError("接口返回异常: %s" % (message or data), status=data.get("status"), payload=data)
