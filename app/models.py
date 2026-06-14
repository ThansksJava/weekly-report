"""数据模型 —— 周报系统核心结构。

周报(Report)由顶部信息 + 多个区块(Section)组成。
每个区块拥有自定义列(Column)和若干行(行是 {col_key: value} 字典),
因此用户可以完全自定义表头、列数、区块数量。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    display_name: str
    email: str = ""
    # 角色:"user" 普通用户 | "admin" 管理员(从 /admin 入口登录)
    role: str = "user"
    # 审核状态:"pending" 待审核 | "approved" 已通过 | "rejected" 已拒绝
    # 新注册用户为 pending,只有管理员通过后(approved)才能登录;种子/管理员新建为 approved
    status: str = "approved"
    created_at: str = ""  # 注册时间(ISO),管理端列表展示
    # 用户的模板集合(新建周报时复制其一)。每个模板是一个 dict:
    #   {"id", "name", "title", "greeting", "subtitle", "sections"}
    # 结构同 Report.to_dict() 去掉 id/user_id/日期,额外带 id+name 用于管理。
    templates: list[dict[str, Any]] = field(default_factory=list)
    # 默认模板 id(新建周报未指定模板时使用);为空或失效时回退到模板列表首个
    default_template_id: str = ""
    # 用户的选项集:名称 -> 候选值列表,如 {"项目": ["MA","D890"], "优先级": [...]}
    # 列可绑定某个选项集,周报单元格即变为下拉选择
    option_sets: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "password_hash": self.password_hash,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "status": self.status,
            "created_at": self.created_at,
            "templates": self.templates,
            "default_template_id": self.default_template_id,
            "option_sets": self.option_sets,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "User":
        return User(
            id=d["id"],
            username=d["username"],
            password_hash=d["password_hash"],
            display_name=d.get("display_name", ""),
            email=d.get("email", ""),
            role=d.get("role", "user"),
            status=d.get("status", "approved"),
            created_at=d.get("created_at", ""),
            templates=list(d.get("templates") or []),
            default_template_id=d.get("default_template_id", ""),
            option_sets=dict(d.get("option_sets") or {}),
        )


@dataclass
class Column:
    key: str
    label: str
    width: int = 200  # 像素,用于前端与 Excel 列宽
    type: str = "text"  # text | select
    options: str = ""  # type=select 时绑定的选项集名称

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "width": self.width,
                "type": self.type, "options": self.options}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Column":
        return Column(
            key=d["key"], label=d.get("label", ""), width=int(d.get("width", 200)),
            type=d.get("type", "text"), options=d.get("options", ""),
        )


@dataclass
class Section:
    id: str
    name: str  # 区块名,如 "My Weekly Plan" / "OMSE"
    columns: list[Column] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    show_index: bool = True  # 是否显示 No. 序号列

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "columns": [c.to_dict() for c in self.columns],
            "rows": self.rows,
            "show_index": self.show_index,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Section":
        return Section(
            id=d.get("id") or new_id(),
            name=d.get("name", ""),
            columns=[Column.from_dict(c) for c in d.get("columns", [])],
            rows=[dict(r) for r in d.get("rows", [])],
            show_index=bool(d.get("show_index", True)),
        )


@dataclass
class Report:
    id: str
    user_id: str
    title: str  # 如 "Weekly plan & follow-up report 2026.05.11 - 2026.05.15"
    greeting: str  # 如 "Hi Team,"
    subtitle: str  # 如 "My Weekly Plan(2026.05.11 - 2026.05.15)"
    week_start: str  # ISO 日期
    week_end: str
    sections: list[Section] = field(default_factory=list)
    updated_at: str = ""
    # 审批状态:draft 草稿 | pending 待审核 | approved 已通过 | rejected 已拒绝
    review_status: str = "draft"
    # 审核历史(时间线)。每条:{id, action, at, actor, actor_role, reason, snapshot}
    #   action: submit|withdraw|approve|reject|reopen
    #   snapshot: 仅 submit 携带,{title, greeting, subtitle, sections} 的内容快照
    review_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "greeting": self.greeting,
            "subtitle": self.subtitle,
            "week_start": self.week_start,
            "week_end": self.week_end,
            "sections": [s.to_dict() for s in self.sections],
            "updated_at": self.updated_at,
            "review_status": self.review_status,
            "review_history": self.review_history,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Report":
        return Report(
            id=d["id"],
            user_id=d["user_id"],
            title=d.get("title", ""),
            greeting=d.get("greeting", ""),
            subtitle=d.get("subtitle", ""),
            week_start=d.get("week_start", ""),
            week_end=d.get("week_end", ""),
            sections=[Section.from_dict(s) for s in d.get("sections", [])],
            updated_at=d.get("updated_at", ""),
            review_status=d.get("review_status", "draft"),
            review_history=list(d.get("review_history") or []),
        )
