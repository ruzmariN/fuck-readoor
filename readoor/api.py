# -*- coding: utf-8 -*-
"""readoor 业务接口封装。

域名不是写死的：先调 app/info 拿到该租户的 domain 配置（api / stat_w / user），
再按这些域名发后续请求。这样同一份代码可以跑在不同学校、不同区域的实例上。
"""
import time
import uuid

from .config import (DEFAULT_DOMAINS, EXAM_TYPES, FOLDER_SECTION_TYPE, MEDIA_TYPES,
                     PLATFORM_PC, TEST_SECTION_TYPE)
from .crypto import dynamic_field, encrypt_payload
from .net import Http


def _norm(url):
    return url if url.endswith("/") else url + "/"


class Readoor:
    def __init__(self, token, app_guid=None, platform=PLATFORM_PC, http=None, payload_key=None):
        self.token = token
        self.app_guid = app_guid
        self.platform = platform
        self.http = http or Http()
        self.domains = dict(DEFAULT_DOMAINS)
        self.app = {}
        self.payload_key = payload_key
        self._resolved = False

    # ---------------------------------------------------------------- 基础
    def _url(self, key, path):
        return _norm(self.domains.get(key) or DEFAULT_DOMAINS[key]) + path

    def _post(self, key, path, body=None):
        return self.http.post(self._url(key, path), body, token=self.token)

    def resolve(self):
        """拉应用信息并解析租户域名。"""
        if self._resolved:
            return self.app
        body = {}
        if self.app_guid:
            body["app_guid"] = self.app_guid
        data = self._post("api", "api/3.1/app/v1/app/info", body)
        info = data.get("data") or {}
        self.app = info
        self.app_guid = self.app_guid or info.get("app_guid")

        domain = info.get("domain") or {}
        mapping = {
            "api": domain.get("api"),
            "stat_w": domain.get("stat_w"),
            "stat_r": domain.get("stat_r"),
            "user": domain.get("user"),
            "a": domain.get("a"),
        }
        for key, value in mapping.items():
            if value:
                self.domains[key] = _norm(value)
        if self.domains.get("a"):
            self.http.origin = self.domains["a"].rstrip("/")
        self._resolved = True
        return self.app

    # ---------------------------------------------------------------- 课程发现
    def courses(self):
        """当前账号参加的所有课程任务。"""
        info = self.resolve()
        company_id = info.get("company_id")
        data = self._post("api", "api/3.0/app/v1/b/ttp/student/learningTask/getList",
                          {"company_id": str(company_id)})
        rows = ((data.get("data") or {}).get("list")) or []
        courses = []
        for row in rows:
            courses.append({
                "item_id": str(row.get("item_id")),
                "training_id": str(row.get("training_id") or "0"),
                "class_id": str(row.get("class_id") or row.get("group_id") or "0"),
                "project_id": str(row.get("project_id") or "0"),
                "book_name": row.get("book_name") or "",
                "book_type": row.get("book_type"),
                "status": row.get("status"),
            })
        return courses

    def course_detail(self, course):
        """补齐 spu_type / 名称。"""
        data = self._post("api", "api/3.1/app/v1/dms/spu/info", {
            "spu_guid": course["item_id"],
            "app_guid": self.app_guid,
            "platform": 11002,
        })
        info = ((data.get("data") or {}).get("info")) or {}
        course["spu_type"] = info.get("spu_type_id") or course.get("book_type") or 0
        course["name"] = course.get("book_name") or info.get("spu_name") or course["item_id"]
        return course

    # ---------------------------------------------------------------- 章节与进度
    def sections(self, spu_guid):
        """返回 (章节列表, section_id -> module_id 映射)。"""
        data = self._post("api", "api/3.1/app/v2/dms/spu/sections", {
            "spu_guid": spu_guid,
            "return_exception_file_flag": "1",
        })
        payload = data.get("data") or {}
        sections = payload.get("sections") or []
        module_of = {}
        for rel in payload.get("module_section_rel") or []:
            try:
                module_of[int(rel.get("section_id"))] = rel.get("module_id")
            except (TypeError, ValueError):
                continue
        return sections, module_of

    def courseware_duration(self, spu_guid, section_guid, module_id=None):
        """章节接口没带 file_duration 时的兜底：单独查课件信息。"""
        body = {"spu_guid": spu_guid, "section_guid": section_guid,
                "app_guid": self.app_guid}
        if module_id:
            body["module_id"] = module_id
        try:
            data = self._post("api", "api/3.1/app/v1/b/dms/courseware/info", body)
        except ApiError:
            return 0.0
        info = ((data.get("data") or {}).get("info")) or {}
        raw = (info.get("file_info") or {}).get("duration")
        try:
            return float(raw) if raw else 0.0
        except (TypeError, ValueError):
            return 0.0

    def points(self, course):
        data = self._post("api", "api/3.0/app/v1/b/ttp/student/points/get_points_list", {
            "spu_guid": course["item_id"],
            "item_id": course["item_id"],
            "group_id": course["class_id"],
            "train_id": course["training_id"],
            "project_id": course["project_id"],
        })
        return data.get("data") or {}

    def done_stats(self, course):
        company_id = (self.app or {}).get("company_id")
        data = self._post("api", "api/3.0/app/v1/b/ttp/student/points/getCoursewareResourceDone", {
            "group_id": course["class_id"],
            "train_id": course["training_id"],
            "project_id": course["project_id"],
            "item_id": course["item_id"],
            "company_id": str(company_id),
        })
        return data.get("data") or {}

    # ---------------------------------------------------------------- 上报
    def report(self, course, section, duration=0.0, refresher=False):
        """上报单个章节完成。返回服务端原始响应。"""
        cw_type = int(section.get("courseware_type") or 0)
        section_type = int(section.get("section_type") or 403)
        now_ms = int(time.time() * 1000)
        is_media = cw_type in MEDIA_TYPES

        lesson = {
            "media_theory_length": round(duration, 2) if is_media else 0,
            "max_position": round(duration, 2) if is_media else 0,
            "position": round(duration, 2) if is_media else 0,
            "study_time": int(duration) if is_media else 0,
            "end_time": int(now_ms / 1000) if is_media else 0,
            "start_time": int(now_ms / 1000 - duration) if is_media else 0,
            "session_id": str(uuid.uuid4()),
            "sequence_id": 1,
            "section_guid": section["section_guid"],
            "courseware_type": cw_type,
            "section_type": section_type,
        }
        # 一次性字段名，值 = is_done
        lesson[dynamic_field(now_ms)] = 1
        if refresher:
            # 部分「复习」类任务的 openStatus=4，前端会额外带 is_refresher
            lesson["is_refresher"] = "1"

        payload = {
            "base_data": {
                "app_id": (self.app or {}).get("app_id"),
                "company_id": (self.app or {}).get("company_id"),
                "time_stamp": now_ms,
                "class_id": course["class_id"],
                "train_id": course["training_id"],
                "project_id": course["project_id"],
                "platform_code": self.platform,
                "item_id": course["item_id"],
                "spu_type": course.get("spu_type") or 0,
            },
            "lesson_data": [lesson],
        }
        body = encrypt_payload(payload, self.payload_key)
        return self._post("stat_w", "api/3.1/stat/v1/b/stat31/stat/pStatIf", body)


def duration_of(section):
    for f in section.get("files") or []:
        try:
            if f.get("file_duration"):
                return float(f["file_duration"])
        except (TypeError, ValueError):
            continue
    return 0.0


def completable(sections):
    """可以靠进度上报完成的章节（排除目录、试卷和需要作答的题型）。"""
    result = []
    for s in sections:
        if s.get("section_type") in (FOLDER_SECTION_TYPE, TEST_SECTION_TYPE):
            continue
        cw = s.get("courseware_type")
        if not cw:
            continue
        try:
            if int(cw) in EXAM_TYPES:
                continue
        except (TypeError, ValueError):
            continue
        result.append(s)
    return result


def skipped(sections):
    """被跳过的章节及原因。"""
    out = []
    for s in sections:
        if s.get("section_type") == FOLDER_SECTION_TYPE:
            continue
        cw = s.get("courseware_type")
        if not cw:
            continue
        try:
            cw_int = int(cw)
        except (TypeError, ValueError):
            cw_int = 0
        if s.get("section_type") == TEST_SECTION_TYPE:
            out.append((s, "试卷节点"))
        elif cw_int in EXAM_TYPES:
            out.append((s, "需要考试作答"))
    return out
