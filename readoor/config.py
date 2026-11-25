# -*- coding: utf-8 -*-
"""全局常量与域名解析。

readoor 是多租户 SaaS：不同学校/出版社挂在不同的 app_guid、company_id 和域名上。
这里只保留「前端打包死的、全站一致」的常量；其余全部在运行时从 app/info 拉取，
这样换学校、换出版社、换区域节点都不用改代码。
"""

# 前端 SE 签名密钥：index.js -> useKeySecretStore().info.newKey
SE_KEY = "AUe#2jE31o90"

# pStatIf 请求体 AES 密钥：index.js -> encryptNew -> deriveKey("...")
PAYLOAD_KEY = "8c1ef35c1a24f94ce6422f3c4b77e19bec2aaec9c0d72251b82ccf40b22561a84c876c19d2cb9a"

# 本工具不内置任何租户 ID：app_guid 由 token 的 aud 字段推断，
# 或通过 --app-guid / --url 显式指定。

# 协议版本，随前端一起发布，1.0.0 已稳定很久
SE_VERSION = "1.0.0"

# 平台标识：PC 浏览器 pweb，移动端浏览器 mweb
PLATFORM_PC = "pweb"
PLATFORM_MOBILE = "mweb"

# 需要写入播放进度（时长/位置）的课件类型
# 101=pdf 102=epub 103=audio 104=video 105=附件 114=ppt 117=图片
# 118=试卷 121=互动 122=html 126=白板 111=3D 115=swf
MEDIA_TYPES = (103, 104)          # audio, video 需要时长

# 需要真实作答、无法用进度上报完成的类型（会跳过并提示）
EXAM_TYPES = (16, 17, 18, 19, 118)

# 试卷类节点（不是课件）
TEST_SECTION_TYPE = 404

# 目录节点（不可完成）
FOLDER_SECTION_TYPE = 401

# 默认域名，只有 app/info 拉不到 domain 时才用
DEFAULT_DOMAINS = {
    "api": "https://api3.readoor.cn/",
    "stat_w": "https://mrr.readoor.cn/",
    "stat_r": "https://stat-api.readoor.cn/",
    "user": "https://uc.readoor.cn/",
    "a": "https://a.readoor.cn/",
}
