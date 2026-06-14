"""SQLAlchemy 存储实现 —— 持久化到 SQLite(开发)或 PostgreSQL(生产)。

设计:领域模型仍是 models.py 的 dataclass,这里用 SQLAlchemy Core 定义表,
读写时在「行 ↔ dataclass」之间手动映射(复用模型的 to_dict/from_dict)。
动态嵌套内容(sections/templates/option_sets/review_history)统一存 JSON 列,
SQLite 落 TEXT、Postgres 落 JSON,由 SQLAlchemy 自动适配。

通过环境变量 WR_DATABASE_URL 选用,如:
  sqlite:///./data/weekly_report.db
  postgresql+psycopg://user:pw@host:5432/wr
"""
from __future__ import annotations

from sqlalchemy import (
    JSON, Column, MetaData, String, Table, UniqueConstraint, create_engine, delete, event, func, insert, select, update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from ..models import Report, User
from .base import DuplicateWeekError, Storage

_metadata = MetaData()

users = Table(
    "users", _metadata,
    Column("id", String, primary_key=True),
    Column("username", String, nullable=False, unique=True, index=True),
    Column("password_hash", String, nullable=False),
    Column("display_name", String, default=""),
    Column("email", String, default=""),
    Column("role", String, default="user"),
    Column("status", String, default="approved"),
    Column("created_at", String, default=""),
    Column("default_template_id", String, default=""),
    Column("templates", JSON, default=list),
    Column("option_sets", JSON, default=dict),
)

reports = Table(
    "reports", _metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False, index=True),
    Column("title", String, default=""),
    Column("greeting", String, default=""),
    Column("subtitle", String, default=""),
    Column("week_start", String, default=""),
    Column("week_end", String, default=""),
    Column("updated_at", String, default=""),
    Column("review_status", String, default="draft"),
    Column("sections", JSON, default=list),
    Column("review_history", JSON, default=list),
    UniqueConstraint("user_id", "week_start", name="uq_report_user_week"),
)

sessions = Table(
    "sessions", _metadata,
    Column("token", String, primary_key=True),
    Column("user_id", String, nullable=False, index=True),
    Column("created_at", String, default=""),
)


class SqlStorage(Storage):
    def __init__(self, url: str, **engine_kw) -> None:
        is_sqlite = url.startswith("sqlite")
        is_memory = url in ("sqlite://", "sqlite:///:memory:")
        if is_sqlite:
            engine_kw.setdefault("connect_args", {"check_same_thread": False})
            if is_memory:
                # 内存库:用 StaticPool 让所有连接共享同一库(否则各连接各自一份)
                engine_kw.setdefault("poolclass", StaticPool)
        self.engine = create_engine(url, future=True, **engine_kw)
        if is_sqlite:
            # SQLite 默认不强制外键;此处主要为语义完整,删除级联仍由代码显式保证
            @event.listens_for(self.engine, "connect")
            def _fk_on(dbapi_conn, _rec):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _metadata.create_all(self.engine)  # 幂等建表(轻量「迁移」)

    # ---- 行 ↔ 模型 ----
    @staticmethod
    def _to_user(row) -> User:
        return User.from_dict(dict(row._mapping))

    @staticmethod
    def _to_report(row) -> Report:
        return Report.from_dict(dict(row._mapping))

    # ---- 用户 ----
    def create_user(self, user: User) -> User:
        with self.engine.begin() as conn:
            exists = conn.execute(
                select(users.c.id).where(func.lower(users.c.username) == user.username.lower())
            ).first()
            if exists:
                raise ValueError("用户名已存在")
            conn.execute(insert(users).values(**user.to_dict()))
        return user

    def get_user(self, user_id: str) -> User | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(users).where(users.c.id == user_id)).first()
            return self._to_user(row) if row else None

    def get_user_by_username(self, username: str) -> User | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users).where(func.lower(users.c.username) == username.lower())
            ).first()
            return self._to_user(row) if row else None

    def update_user(self, user: User) -> None:
        data = user.to_dict()
        data.pop("id", None)
        with self.engine.begin() as conn:
            conn.execute(update(users).where(users.c.id == user.id).values(**data))

    def list_users(self) -> list[User]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(users).order_by(users.c.created_at)).all()
            return [self._to_user(r) for r in rows]

    def delete_user(self, user_id: str) -> None:
        # 级联:同一事务内显式删其周报、会话、用户本身(跨库稳妥,不只依赖 DB 外键)
        with self.engine.begin() as conn:
            conn.execute(delete(reports).where(reports.c.user_id == user_id))
            conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
            conn.execute(delete(users).where(users.c.id == user_id))

    # ---- 周报 ----
    def create_report(self, report: Report) -> Report:
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(reports).values(**report.to_dict()))
        except IntegrityError as e:
            # 命中 UNIQUE(user_id, week_start) → 同一用户同一周已存在
            raise DuplicateWeekError(report.week_start) from e
        return report

    def get_report(self, report_id: str) -> Report | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(reports).where(reports.c.id == report_id)).first()
            return self._to_report(row) if row else None

    def list_reports(self, user_id: str) -> list[Report]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(reports).where(reports.c.user_id == user_id).order_by(reports.c.week_start.desc())
            ).all()
            return [self._to_report(r) for r in rows]

    def update_report(self, report: Report) -> None:
        data = report.to_dict()
        data.pop("id", None)
        with self.engine.begin() as conn:
            conn.execute(update(reports).where(reports.c.id == report.id).values(**data))

    def delete_report(self, report_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(reports).where(reports.c.id == report_id))

    # ---- 会话 ----
    def set_session(self, token: str, user_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.token == token))
            conn.execute(insert(sessions).values(token=token, user_id=user_id, created_at=""))

    def get_session(self, token: str) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(sessions.c.user_id).where(sessions.c.token == token)).first()
            return row[0] if row else None

    def delete_session(self, token: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.token == token))
