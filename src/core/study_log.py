"""学习记录管理器 — 记录每次学习的模块、时长、进度快照，支持续学与删除。

数据文件：study_log.json（与 words.json 同目录，原子写入）。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from src.utils import get_user_data_path


class StudyLogManager:
    """管理学习记录的增删查和统计。线程安全（单用户场景下锁开销极低）。"""

    def __init__(self, path: Optional[str] = None):
        self._path = path or get_user_data_path("study_log.json")
        self._lock = threading.Lock()
        self._data: dict = self._load()

    # ------------------------------------------------------------------ #
    # 读取 / 持久化
    # ------------------------------------------------------------------ #
    def _load(self) -> dict:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"records": []}

    def _save(self):
        """原子写入：先写 .tmp 再 rename，防止断电丢数据。"""
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    # ------------------------------------------------------------------ #
    # 开始 / 更新 / 结束
    # ------------------------------------------------------------------ #
    def start(self, module: str, module_label: str) -> dict:
        """开始一次学习，返回新建的记录。"""
        rec = {
            "id": uuid.uuid4().hex[:12],
            "module": module,
            "module_label": module_label,
            "status": "active",
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
            "duration_sec": 0,
            "content_summary": "",
            "snapshot": None,
        }
        with self._lock:
            self._data["records"].insert(0, rec)
            self._save()
        return rec

    def update(self, record_id: str, snapshot: Any = None, content_summary: str = "") -> bool:
        """更新进度快照或摘要。返回是否找到对应记录。"""
        with self._lock:
            for rec in self._data["records"]:
                if rec["id"] == record_id:
                    if snapshot is not None:
                        rec["snapshot"] = snapshot
                    if content_summary:
                        rec["content_summary"] = content_summary
                    self._save()
                    return True
        return False

    def end(self, record_id: str, content_summary: str = "",
            snapshot: Any = None, status: str = "completed") -> Optional[dict]:
        """结束一次学习，计算时长并持久化。返回更新后的记录，找不到返回 None。"""
        with self._lock:
            for rec in self._data["records"]:
                if rec["id"] == record_id:
                    now = datetime.now()
                    rec["ended_at"] = now.isoformat()
                    try:
                        started = datetime.fromisoformat(rec["started_at"])
                        rec["duration_sec"] = max(0, int((now - started).total_seconds()))
                    except (ValueError, TypeError):
                        rec["duration_sec"] = 0
                    rec["status"] = status
                    if content_summary:
                        rec["content_summary"] = content_summary
                    if snapshot is not None:
                        rec["snapshot"] = snapshot
                    self._save()
                    return rec
        return None

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def get(self, record_id: str) -> Optional[dict]:
        with self._lock:
            for rec in self._data["records"]:
                if rec["id"] == record_id:
                    return dict(rec)
        return None

    def list_records(self, *,
                     module: Optional[str] = None,
                     status: Optional[str] = None,
                     date_from: Optional[str] = None,
                     date_to: Optional[str] = None,
                     limit: int = 100,
                     offset: int = 0) -> list[dict]:
        """查询记录列表，支持按模块/状态/日期过滤，按开始时间倒序。"""
        with self._lock:
            recs = self._data["records"]

        # 过滤
        result = []
        for rec in recs:
            if module and rec.get("module") != module:
                continue
            if status and rec.get("status") != status:
                continue
            if date_from:
                try:
                    if rec.get("started_at", "") < date_from:
                        continue
                except TypeError:
                    continue
            if date_to:
                try:
                    if rec.get("started_at", "") > date_to:
                        continue
                except TypeError:
                    continue
            result.append(dict(rec))

        # 分页
        return result[offset:offset + limit]

    # ------------------------------------------------------------------ #
    # 删除
    # ------------------------------------------------------------------ #
    def delete(self, record_id: str) -> bool:
        with self._lock:
            before = len(self._data["records"])
            self._data["records"] = [
                r for r in self._data["records"] if r["id"] != record_id
            ]
            if len(self._data["records"]) < before:
                self._save()
                return True
        return False

    # ------------------------------------------------------------------ #
    # 统计
    # ------------------------------------------------------------------ #
    def stats(self) -> dict:
        """返回汇总统计：今日/本周/本月时长、总次数、连续打卡天数、各模块占比。"""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        month_start = now.strftime("%Y-%m-01")

        with self._lock:
            recs = [r for r in self._data["records"] if r.get("ended_at")]

        today_sec = 0
        week_sec = 0
        month_sec = 0
        total_count = len(recs)
        module_sec: dict[str, int] = {}

        for rec in recs:
            started = rec.get("started_at", "")
            sec = rec.get("duration_sec", 0)
            mod = rec.get("module", "unknown")
            module_sec[mod] = module_sec.get(mod, 0) + sec

            if started >= today:
                today_sec += sec
            if started >= week_start:
                week_sec += sec
            if started >= month_start:
                month_sec += sec

        # 连续打卡天数
        streak = self._calc_streak(recs, now)

        return {
            "today_sec": today_sec,
            "week_sec": week_sec,
            "month_sec": month_sec,
            "total_count": total_count,
            "streak_days": streak,
            "module_breakdown": module_sec,
        }

    @staticmethod
    def _calc_streak(recs: list[dict], now: datetime) -> int:
        """计算连续学习天数（含今天）。"""
        # 收集所有有学习记录的日期
        days: set[str] = set()
        for rec in recs:
            started = rec.get("started_at", "")
            if started:
                days.add(started[:10])

        streak = 0
        check = now.strftime("%Y-%m-%d")
        # 今天有学习记录才算开始，否则从昨天开始检查
        if check not in days:
            check = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        while check in days:
            streak += 1
            check = (datetime.strptime(check, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        return streak
