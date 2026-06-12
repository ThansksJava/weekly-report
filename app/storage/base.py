"""存储层抽象接口。

业务代码只依赖 Storage 接口;当前实现为 MemoryStorage(内存),
后续可新增 SqlStorage / RedisStorage 等实现并在 main.py 中替换一行即可。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Report, User


class Storage(ABC):
    # ---- 用户 ----
    @abstractmethod
    def create_user(self, user: User) -> User: ...

    @abstractmethod
    def get_user(self, user_id: str) -> User | None: ...

    @abstractmethod
    def get_user_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    def update_user(self, user: User) -> None: ...

    # ---- 周报 ----
    @abstractmethod
    def create_report(self, report: Report) -> Report: ...

    @abstractmethod
    def get_report(self, report_id: str) -> Report | None: ...

    @abstractmethod
    def list_reports(self, user_id: str) -> list[Report]: ...

    @abstractmethod
    def update_report(self, report: Report) -> None: ...

    @abstractmethod
    def delete_report(self, report_id: str) -> None: ...

    # ---- 会话 ----
    @abstractmethod
    def set_session(self, token: str, user_id: str) -> None: ...

    @abstractmethod
    def get_session(self, token: str) -> str | None: ...

    @abstractmethod
    def delete_session(self, token: str) -> None: ...
