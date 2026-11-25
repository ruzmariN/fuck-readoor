# -*- coding: utf-8 -*-
"""命令行入口。

设计目标是「换设备不用改代码」：
  - token 自动发现（多浏览器 / 多系统 / 环境变量 / 文件）
  - 课程自动发现（learningTask/getList）
  - 域名自动解析（app/info -> domain）
  - 网络抖动自动重试，签名时钟自动校正
"""
import argparse
import os
import sys
import time

from . import __version__
from .api import Readoor, completable, duration_of, skipped
from .config import MEDIA_TYPES, PLATFORM_MOBILE, PLATFORM_PC
from .keys import discover as discover_keys
from .net import ApiError, Http, TokenError
from .tokenstore import TOKEN_HELP, candidates, describe, jwt_aud


# ---------------------------------------------------------------- 输出
def _setup_stdio():
    """Windows 控制台默认 GBK，统一改成 UTF-8，避免 ✔/✘ 之类字符报错。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class Out:
    def __init__(self, quiet=False, no_color=False):
        self.quiet = quiet
        self.no_color = no_color or not sys.stdout.isatty() or os.environ.get("NO_COLOR")

    def _c(self, code, text):
        if self.no_color:
            return text
        try:
            return "\033[%sm%s\033[0m" % (code, text)
        except Exception:
            return text

    def info(self, msg=""):
        if not self.quiet:
            print(msg)

    def ok(self, msg):
        print(self._c("32", "✔ ") + msg)

    def warn(self, msg):
        print(self._c("33", "! ") + msg)

    def err(self, msg):
        print(self._c("31", "✘ ") + msg, file=sys.stderr)

    def dim(self, msg):
        if not self.quiet:
            print(self._c("2", msg))


def build_parser():
    p = argparse.ArgumentParser(
        prog="readoor-brush",
        description="教材出版服务平台（readoor）学习进度批处理 —— 自动发现课程并补齐未完成章节",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  readoor-brush                        # 自动找 token、自动发现全部课程、补完未完成章节
  readoor-brush --list                 # 只列出识别到的课程和进度
  readoor-brush --dry-run              # 只看差哪些章节，不发请求
  readoor-brush --course 5643989627…   # 只处理指定课程
  readoor-brush --all                  # 已完成的也重新上报
  readoor-brush --mobile               # 用 mweb 平台标识（手机端任务）
""")
    p.add_argument("--token", help="Bearer token（JWT）；不给则自动从浏览器/环境变量/文件发现")
    p.add_argument("--token-file", help="token 文件路径，默认 ~/.readoor-token")
    p.add_argument("--app-guid", help="租户 app_guid；默认从 token 的 aud 推断")
    p.add_argument("--se-key", help="覆盖 SE 签名密钥（自动提取失败时用）")
    p.add_argument("--payload-key", help="覆盖上报加密密钥（自动提取失败时用）")
    p.add_argument("--url", help="课程页 URL，用于解析 app_guid / spu_guid / training_id 等")
    p.add_argument("--course", action="append", help="只处理指定 spu_guid，可重复")
    p.add_argument("--list", action="store_true", help="只列出课程与进度")
    p.add_argument("--all", action="store_true", help="已完成的章节也重新上报")
    p.add_argument("--dry-run", action="store_true", help="不发送上报，只打印计划")
    p.add_argument("--sleep", type=float, default=0.6, help="每次上报间隔秒数（默认 0.6）")
    p.add_argument("--limit", type=int, default=0, help="本次最多上报 N 个章节（0 = 不限，调试用）")
    p.add_argument("--retries", type=int, default=2, help="网络失败重试次数（默认 2）")
    p.add_argument("--timeout", type=float, default=20, help="单请求超时秒数（默认 20）")
    p.add_argument("--proxy", help="HTTP(S) 代理，如 http://127.0.0.1:7890")
    p.add_argument("--insecure", action="store_true", help="跳过 HTTPS 证书校验（公司代理/抓包环境）")
    p.add_argument("--mobile", action="store_true", help="使用 mweb 平台标识")
    p.add_argument("--refresher", action="store_true", help="上报时附带 is_refresher=1（复习任务）")
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果（便于二次处理）")
    p.add_argument("--quiet", action="store_true", help="只输出错误")
    p.add_argument("--verbose", action="store_true", help="输出调试信息（密钥来源、跳过原因等）")
    p.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    p.add_argument("--version", action="version", version="readoor-brush " + __version__)
    return p


def parse_course_url(url):
    import urllib.parse
    u = urllib.parse.urlparse(url)
    parts = [x for x in u.path.split("/") if x]
    app_guid = parts[0] if parts and parts[0].isdigit() else None
    q = urllib.parse.parse_qs(u.query)
    origin = "%s://%s" % (u.scheme, u.netloc) if u.scheme and u.netloc else None
    return {
        "app_guid": app_guid,
        "spu_guid": (q.get("spu_guid") or [None])[0],
        "group_id": (q.get("group_id") or [None])[0],
        "train_id": (q.get("training_id") or [None])[0],
        "project_id": (q.get("project_id") or [None])[0],
        "origin": origin,
    }


def main(argv=None):
    _setup_stdio()
    args = build_parser().parse_args(argv)
    out = Out(quiet=args.quiet or args.json, no_color=args.no_color)

    hint = parse_course_url(args.url) if args.url else {}
    app_guid = args.app_guid or hint.get("app_guid")

    # ---- token（可能有多份候选，逐个试到能登录为止）
    tries = []
    if args.token:
        tries = [(args.token, "命令行 --token")]
    else:
        tries = list(candidates(app_guid=app_guid, token_file=args.token_file,
                                verbose=args.verbose))
    if not tries:
        out.err(TOKEN_HELP)
        return 2

    # 前端密钥：优先从线上 index.js 实时提取，失败回退内置默认值
    effective_guid = app_guid or (jwt_aud(tries[0][0]) if tries else None)
    if not effective_guid:
        out.err("无法确定租户 app_guid：token 中没有 aud，请用 --app-guid 或 --url 指定。")
        return 2
    keys = discover_keys(effective_guid,
                         origin=hint.get("origin") or "https://a.readoor.cn")
    # 命令行/环境变量可强制覆盖（跨租户、密钥轮换时用）
    if args.se_key or os.environ.get("READOOR_SE_KEY"):
        keys["se_key"] = args.se_key or os.environ["READOOR_SE_KEY"]
        keys["source"] = "manual"
    if args.payload_key or os.environ.get("READOOR_PAYLOAD_KEY"):
        keys["payload_key"] = args.payload_key or os.environ["READOOR_PAYLOAD_KEY"]
        keys["source"] = "manual"
    if args.verbose:
        out.dim("前端密钥来源: %s%s" % (
            keys.get("source"), " (v%s)" % keys["version"] if keys.get("version") else ""))

    client = None
    app = None
    token = source = None
    for cand, cand_source in tries:
        if app_guid and jwt_aud(cand) not in (None, app_guid):
            continue
        http = Http(timeout=args.timeout, retries=args.retries, proxy=args.proxy,
                    se_key=keys.get("se_key"), insecure=args.insecure)
        probe = Readoor(cand, app_guid=app_guid or jwt_aud(cand),
                        platform=PLATFORM_MOBILE if args.mobile else PLATFORM_PC,
                        http=http, payload_key=keys.get("payload_key"))
        try:
            app = probe.resolve()
        except (TokenError, ApiError) as exc:
            if args.verbose:
                out.warn("候选 token 不可用（%s）: %s" % (cand_source, exc))
            continue
        client, token, source = probe, cand, cand_source
        app_guid = probe.app_guid
        break

    if client is None:
        out.err("所有候选 token 都无法登录，请重新登录后重试。")
        out.err(TOKEN_HELP)
        return 2

    meta = describe(token)
    out.info("token 来源: %s" % (source or "未知"))
    out.info("账号: %s (aud=%s)" % (meta.get("user") or "?", app_guid))
    out.info("应用: %s  app_id=%s  company_id=%s" % (
        app.get("app_name"), app.get("app_id"), app.get("company_id")))

    # ---- 课程列表
    try:
        courses = client.courses()
    except TokenError as exc:
        out.err(str(exc))
        return 2
    if hint.get("spu_guid"):
        courses = [c for c in courses if c["item_id"] == hint["spu_guid"]] or [{
            "item_id": hint["spu_guid"],
            "training_id": hint.get("train_id") or "0",
            "class_id": hint.get("group_id") or "0",
            "project_id": hint.get("project_id") or "0",
            "book_name": "(URL 指定)",
        }]
    if args.course:
        wanted = set(args.course)
        courses = [c for c in courses if c["item_id"] in wanted]
    if not courses:
        out.err("没有识别到课程。确认账号有学习任务，或用 --url/--course 指定。")
        return 1

    for c in courses:
        try:
            client.course_detail(c)
        except ApiError as exc:
            out.warn("课程 %s 信息获取失败: %s" % (c["item_id"], exc))

    out.info("识别到 %d 门课程:" % len(courses))
    for c in courses:
        out.dim("  - %s | spu=%s | train=%s | class=%s | project=%s | spu_type=%s" % (
            c["name"], c["item_id"], c["training_id"], c["class_id"],
            c["project_id"], c.get("spu_type")))

    if args.list:
        # 只读模式：列出每门课的完成情况，不做任何写入
        summary = []
        for c in courses:
            try:
                sections, _module_of = client.sections(c["item_id"])
                targets_all = completable(sections)
                done = set(client.points(c).get("courseware_done") or [])
            except ApiError as exc:
                out.warn("%s: 进度读取失败 %s" % (c["name"], exc))
                continue
            out.info("  %s: %d / %d 已完成%s" % (
                c["name"], len(done), len(targets_all),
                "" if len(done) >= len(targets_all) else "，差 %d" % (len(targets_all) - len(done))))
            summary.append({
                "course": c["name"], "spu_guid": c["item_id"],
                "total": len(targets_all), "done": len(done),
                "remaining": len(targets_all) - len(done),
            })
        if args.json:
            import json
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    report = []
    exit_code = 0
    for c in courses:
        try:
            result = process_course(client, c, args, out)
        except TokenError as exc:
            out.err("登录态失效: %s" % exc)
            out.err(TOKEN_HELP)
            return 2
        except ApiError as exc:
            out.err("课程 %s 处理失败: %s" % (c["name"], exc))
            exit_code = 1
            continue
        report.append(result)
        if result["remaining"]:
            exit_code = exit_code or 3

    if args.json:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


def section_duration(client, course, section, module_of):
    """先读章节自带的 file_duration，缺失时再查课件信息。"""
    value = duration_of(section)
    if value:
        return value
    try:
        cw = int(section.get("courseware_type") or 0)
    except (TypeError, ValueError):
        cw = 0
    if cw in MEDIA_TYPES:
        module_id = module_of.get(section.get("id"))
        return client.courseware_duration(course["item_id"], section["section_guid"], module_id)
    return 0.0


def process_course(client, course, args, out):
    out.info("")
    out.info("=== %s ===" % course["name"])
    sections, module_of = client.sections(course["item_id"])
    targets_all = completable(sections)
    points = client.points(course)
    done = set(points.get("courseware_done") or [])
    out.info("节点 %d，可完成课件 %d，云端已完成 %d" % (len(sections), len(targets_all), len(done)))
    rate = points.get("completion_rate")
    if rate is not None:
        try:
            out.info("课程完成率: %.1f%%" % (float(rate) * 100))
        except (TypeError, ValueError):
            pass
    if points.get("time_status") not in (None, 1, "1"):
        out.warn("任务当前不在开放时间内（time_status=%s），上报可能被拒绝" % points.get("time_status"))
    for sec, reason in skipped(sections):
        out.warn("跳过 %s（%s）" % (sec.get("section_name") or sec.get("section_guid"), reason))

    targets = targets_all if args.all else [s for s in targets_all if s["section_guid"] not in done]
    if args.limit and args.limit > 0:
        targets = targets[:args.limit]
    out.info("本次待上报 %d 个" % len(targets))

    if args.dry_run:
        for s in targets:
            out.dim("  - %s [%s] %s" % (s["section_guid"], s.get("courseware_type"), s.get("section_name")))
        return {
            "course": course["name"], "spu_guid": course["item_id"],
            "total": len(targets_all), "done_before": len(done),
            "planned": len(targets), "ok": 0, "failed": 0,
            "done_after": len(done), "remaining": len(targets_all) - len(done),
            "dry_run": True,
        }

    ok = failed = 0
    for index, section in enumerate(targets, 1):
        try:
            resp = client.report(course, section,
                                 section_duration(client, course, section, module_of),
                                 refresher=args.refresher)
            good = resp.get("status") == 1
        except ApiError as exc:
            good = False
            resp = {"error": str(exc)}
        ok += 1 if good else 0
        failed += 0 if good else 1
        tag = "video" if int(section.get("courseware_type") or 0) in (102, 104) else "doc"
        line = "[%d/%d] %s %-4s %-5s %s" % (
            index, len(targets), section["section_guid"], section.get("courseware_type"), tag,
            "OK" if good else "FAIL")
        if good:
            out.info(line)
        else:
            out.warn(line + " " + str(resp)[:140])
        if index < len(targets):
            time.sleep(max(0.0, args.sleep))

    time.sleep(1.2)
    final_done = set(client.points(course).get("courseware_done") or [])
    stats = {}
    try:
        stats = client.done_stats(course)
    except ApiError:
        pass

    remaining = [s for s in targets_all if s["section_guid"] not in final_done]
    out.info("--- 云端复核: %d / %d" % (len(final_done), len(targets_all)))
    parts = ["%s=%s/%s" % (k, v.get("done"), v.get("total"))
             for k, v in sorted(stats.items()) if v.get("total")]
    if parts:
        out.dim("    按类型: " + "  ".join(parts))
    if remaining:
        out.warn("    仍未完成 %d 个: %s" % (
            len(remaining), ", ".join(s.get("section_name") or s["section_guid"] for s in remaining[:5])))
    else:
        out.ok("    全部章节已在云端标记完成")
    out.info("    本次上报 成功 %d / 失败 %d" % (ok, failed))

    return {
        "course": course["name"], "spu_guid": course["item_id"],
        "total": len(targets_all), "done_before": len(done),
        "planned": len(targets), "ok": ok, "failed": failed,
        "done_after": len(final_done), "remaining": len(remaining),
        "by_type": stats, "dry_run": False,
    }


if __name__ == "__main__":
    sys.exit(main())
