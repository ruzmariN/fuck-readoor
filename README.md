# Fuck Readoor

**交我学 / 教材出版服务平台**（readoor）课程速通工具。

一条命令，自动识别你账号下的所有课程，把还没看完的课件章节全部补齐，最后回查服务端确认真的完成了。不是改缓存，改的是后台真实认可的数据。

> 在我用过的所有网课平台中，交我学无疑是做的最烂的一个。此工具可以帮你快速跳过这个屎一样的平台，不在空洞的网课中浪费时间。

---

## 快速上手

### 第 1 步：装 Python

需要 Python 3.8 或更高版本。

- **Windows**：到 [python.org](https://www.python.org/downloads/) 下载安装包，安装时勾选 **Add Python to PATH**
- **macOS**：`brew install python` 或到官网下载
- **Linux**：`sudo apt install python3 python3-pip`（Debian/Ubuntu）

装完打开终端，输入 `python --version` 能看到版本号就成功了。

### 第 2 步：装依赖

```bash
cd readoor-brush
pip install -r requirements.txt
```

只有一个依赖 `cryptography`，几秒钟就好。

### 第 3 步：登录后直接跑

1. 用你的浏览器正常打开学习平台并完成登录。
2. 保持浏览器页面正常打开，回到终端执行：

```bash
python brush.py
```

脚本会自己从浏览器获取账号，并识别未完成课程，一键速通：

```
=== <课程名> ===
节点 <节点数>，可完成课件 <课件数>，云端已完成 <已完成数>
课程完成率: <百分比>
本次待上报 <待补数> 个
[1/<待补数>] <section_guid> 104  video  OK
[2/<待补数>] <section_guid> 101  doc    OK
...
--- 云端复核: <已完成数> / <课件数>
    按类型: 101=<a>/<b>  104=<c>/<d>
✔     全部章节已在云端标记完成
```

看到最后一行 `全部章节已在云端标记完成` 就完事了。

---

## 安卓或其他设备？

脚本默认会读本机浏览器的登录态。如果浏览器不在这台机器上（比如你的备用机、平板），手动把 token 粘过去就行。

### 手机 / 平板 / 另一台电脑

**第 1 步**，在**已登录课程页的浏览器**里取出 token：

- 电脑：按 `F12` 打开开发者工具 → `Console` 标签 → 粘贴下面这行 → 回车
- 手机：用支持控制台的浏览器（如 Kiwi、Yandex），或用电脑连 USB 调试

```js
JSON.parse(localStorage.getItem('token_<app_guid>')).token
```

> `<app_guid>` 换成课程页 URL 里第一段数字。

会输出一长串 `eyJ...` 开头的字符，这就是 token。

**第 2 步**，把这串字符存成文件：

```bash
# Linux / macOS
echo "eyJ..." > ~/.readoor-token

# Windows PowerShell
"eyJ..." | Out-File -Encoding utf8 $env:USERPROFILE\.readoor-token
```

**第 3 步**，在要跑脚本的机器上执行：

```bash
python brush.py
```

脚本会自动读取 `~/.readoor-token`。也可以用 `--token-file` 指定别的路径。

### 直接传 token

```bash
python brush.py --token "eyJ..."
```

或者设成环境变量：

```bash
# Linux / macOS
export READOOR_TOKEN="eyJ..."
# Windows PowerShell
$env:READOOR_TOKEN="eyJ..."
```

### token 会过期

有效期大约 12 小时。过期后脚本会提示「所有候选 token 都无法登录」，重新登录课程页再跑一次就行——脚本会自动读到新的。

---

## 支持的浏览器

只要浏览器把登录态存在本地，脚本就能自己找到：

**Windows**：Chrome、Edge、Brave、Chromium、Vivaldi、Opera、Firefox
**macOS**：以上全部 + Safari
**Linux**：以上全部（Safari 除外）

会扫描所有用户配置（Profile），并且只取属于当前课程平台的 token，不会乱动别的网站。

---


## 拓展命令

| 我想… | 命令 |
|---|---|
| 看有哪些课、各完成多少 | `python brush.py --list` |
| 补齐所有未完成章节 | `python brush.py` |
| 先看看会动哪些章节 | `python brush.py --dry-run` |
| 只刷一门课 | `python brush.py --course <spu_guid>` |
| 只刷当前打开的课程 | `python brush.py --url "<课程页URL>"` |
| 全部重新上报 | `python brush.py --all` |
| 先试 5 个 | `python brush.py --limit 5` |
| 手机/别的电脑 | 见上面「在别的设备上用」 |
| 输出 JSON 给脚本用 | `python brush.py --json` |
| 看详细日志 | `python brush.py --verbose` |

---

## 常见问题

**Q：提示找不到 token**
说明浏览器里没有这个平台的登录态。先打开课程页登录，再重跑。或者在别的设备上按上面的方法取 token。

**Q：提示「所有候选 token 都无法登录」**
token 过期了。重新登录课程页，再跑一次。

**Q：完成率一直不到 100%**
完成率只算课件章节（目录不算）。如果课程里有试卷/测验，平台要求真实作答，脚本会跳过它们——这部分得你自己做。

**Q：某些章节显示 FAIL**
先看是不是试卷类（本来就会跳过）。如果是普通章节，加 `--verbose` 看服务端返回的具体原因。部分课程有开放时间窗口，没到时间无法上报。

**Q：会不会封号**
脚本走的是平台自己的进度上报接口，频率也控制在正常范围（默认每个 0.6 秒）。但风险需要你自己评估，建议先用 `--limit 5` 小范围试。

**Q：能刷考试吗**
不能。试卷类需要真实作答，脚本会自动跳过并提示。

**Q：需要管理员权限吗**
不需要。只读浏览器本地文件 + 发 HTTPS 请求。

**Q：支持哪些课程类型**
PDF、EPUB、音频、视频、PPT、附件、图片、HTML 都可以。试卷/考试类会跳过。

---

## 工作原理

平台前端播放课件时，会向服务端发一条「学习进度」请求，服务端据此记录完成状态。脚本复刻的就是这条请求：读取你的登录态，按章节逐条发送同样的进度数据，再回查服务端确认写入成功。

因为用的是平台自己的接口，所以服务端看到的学习记录和真人播放完全一致，后台统计、教师端进度都会同步更新。

实现上做了几件事保证换环境也能跑：

- 课程、章节、租户信息全部从接口实时获取，没有任何写死
- 平台前端升级换了密钥，脚本会自动重新提取
- 网络抖动自动重试，本机时间不准自动校正

---

## 自检

不联网验证核心逻辑（签名、加密、章节筛选）：

```bash
python tests/test_offline.py
```

---

## 目录结构

```
readoor-brush/
├── brush.py               # 入口，就这一个要记
├── readoor/               # 源码
├── tests/test_offline.py  # 离线自检
├── requirements.txt
└── README.md
```

---

## 免责声明

本项目仅用于**个人账号**的学习记录整理与技术研究。使用前请确认符合所在学校/单位与平台的使用规定，因使用产生的后果由使用者自行承担。请勿用于代刷、牟利或侵犯他人账号。

## License

MIT
