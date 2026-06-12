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
    # 用户的默认模板(新建周报时复制),结构同 Report.to_dict() 的 sections/标题部分
    template: dict[str, Any] | None = None
    # 用户的选项集:名称 -> 候选值列表,如 {"项目": ["MA","D890"], "优先级": [...]}
    # 列可绑定某个选项集,周报单元格即变为下拉选择
    option_sets: dict[str, list[str]] = field(default_factory=dict)


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
        }
