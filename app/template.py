"""默认周报模板与选项集 —— 结构对应团队现有 Excel 周报格式,用户可在界面上完全自定义。"""
from __future__ import annotations

from typing import Any

from .models import new_id


def default_option_sets() -> dict[str, list[str]]:
    return {
        "项目": ["MA", "D890"],
        "优先级": ["High", "Medium", "Low"],
        "级别": ["L1", "L2", "L3"],
        "状态": ["Open", "In Progress", "Pending", "Closed"],
        "进度": [f"{i}%" for i in range(0, 101)],
    }


def default_templates() -> list[dict[str, Any]]:
    """新用户的初始模板集合:仅含一个名为「默认模板」的内置模板。"""
    return [named_template("默认模板", default_template())]


def named_template(name: str, body: dict[str, Any]) -> dict[str, Any]:
    """把模板正文(title/greeting/subtitle/sections)包装成带 id+name 的可管理模板。"""
    return {
        "id": new_id(),
        "name": name,
        "title": body.get("title", ""),
        "greeting": body.get("greeting", ""),
        "subtitle": body.get("subtitle", ""),
        "sections": body.get("sections", []),
    }


def preset_sections() -> list[dict[str, Any]]:
    """团队固定格式区块(My Weekly Plan + OMSE)。

    既是默认模板的正文,也作为「添加区块」时可直接套用的固定格式;
    每次调用都生成全新 id,调用方可安全直接使用。
    """
    return [
        {
            "id": new_id(),
            "name": "My Weekly Plan",
            "show_index": True,
            "columns": [
                {"key": "item", "label": "工作项", "width": 200},
                {"key": "detail", "label": "详细内容和目标描述", "width": 320},
                {"key": "status", "label": "完成状态", "width": 110, "type": "select", "options": "进度"},
                {"key": "remark", "label": "备注", "width": 320},
            ],
            "rows": [
                {"item": "", "detail": "", "status": "", "remark": ""},
            ],
        },
        {
            "id": new_id(),
            "name": "OMSE",
            "show_index": False,
            "columns": [
                {"key": "ticket", "label": "Ticket ID", "width": 100},
                {"key": "desc", "label": "Description", "width": 240},
                {"key": "project", "label": "Project (MA/D890)", "width": 130, "type": "select", "options": "项目"},
                {"key": "priority", "label": "Priority", "width": 100, "type": "select", "options": "优先级"},
                {"key": "level", "label": "Level(L1/L2/L3)", "width": 120, "type": "select", "options": "级别"},
                {"key": "component", "label": "Component", "width": 110},
                {"key": "owner", "label": "Owner", "width": 100},
                {"key": "status", "label": "Status", "width": 110, "type": "select", "options": "状态"},
                {"key": "raised", "label": "Date Raised", "width": 110},
                {"key": "closed", "label": "Date Closed", "width": 110},
                {"key": "effort", "label": "Effort (Hour/Day)", "width": 110},
                {"key": "release", "label": "Impl. Release", "width": 110},
                {"key": "comment", "label": "Comment", "width": 140},
            ],
            "rows": [
                {},
            ],
        },
    ]


def default_template() -> dict[str, Any]:
    return {
        "title": "Weekly plan & follow-up report {start} - {end}",
        "greeting": "Hi Team,",
        "subtitle": "My Weekly Plan({start} - {end})",
        "sections": preset_sections(),
    }
