"""内存存储实现 —— 进程重启数据即丢失,仅用于开发/演示。"""
from __future__ import annotations

import threading

from ..models import Report, User
from .base import DuplicateWeekError, Storage


class MemoryStorage(Storage):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._users: dict[str, User] = {}
        self._username_index: dict[str, str] = {}
        self._reports: dict[str, Report] = {}
        self._sessions: dict[str, str] = {}

    # ---- 用户 ----
    def create_user(self, user: User) -> User:
        with self._lock:
            if user.username.lower() in self._username_index:
                raise ValueError("用户名已存在")
            self._users[user.id] = user
            self._username_index[user.username.lower()] = user.id
            return user

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> User | None:
        uid = self._username_index.get(username.lower())
        return self._users.get(uid) if uid else None

    def update_user(self, user: User) -> None:
        with self._lock:
            self._users[user.id] = user

    def list_users(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: u.created_at)

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            user = self._users.pop(user_id, None)
            if not user:
                return
            self._username_index.pop(user.username.lower(), None)
            # 级联:删该用户全部周报
            for rid in [rid for rid, r in self._reports.items() if r.user_id == user_id]:
                self._reports.pop(rid, None)
            # 级联:删该用户名下会话
            for tok in [t for t, uid in self._sessions.items() if uid == user_id]:
                self._sessions.pop(tok, None)

    # ---- 周报 ----
    def create_report(self, report: Report) -> Report:
        with self._lock:
            for r in self._reports.values():
                if r.user_id == report.user_id and r.week_start == report.week_start:
                    raise DuplicateWeekError(report.week_start)
            self._reports[report.id] = report
            return report

    def get_report(self, report_id: str) -> Report | None:
        return self._reports.get(report_id)

    def list_reports(self, user_id: str) -> list[Report]:
        reports = [r for r in self._reports.values() if r.user_id == user_id]
        return sorted(reports, key=lambda r: r.week_start, reverse=True)

    def update_report(self, report: Report) -> None:
        with self._lock:
            self._reports[report.id] = report

    def delete_report(self, report_id: str) -> None:
        with self._lock:
            self._reports.pop(report_id, None)

    # ---- 会话 ----
    def set_session(self, token: str, user_id: str) -> None:
        self._sessions[token] = user_id

    def get_session(self, token: str) -> str | None:
        return self._sessions.get(token)

    def delete_session(self, token: str) -> None:
        self._sessions.pop(token, None)
