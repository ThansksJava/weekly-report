"""模板管理单元测试:多命名模板的增删改、默认模板、按模板新建周报。

不依赖 pytest/httpx —— 直接驱动 main.py 中的端点函数(store 为模块级全局)。
运行:.venv/bin/python3 -m unittest discover tests -v
"""
import unittest

from fastapi import HTTPException

import app.main as m
from app.auth import hash_password
from app.main import RegisterIn, TemplateIn
from app.models import User
from app.storage import MemoryStorage


class TemplatesTest(unittest.TestCase):
    def setUp(self):
        m.store = MemoryStorage()
        # register 仅创建待审核用户、不再下发会话;模板端点接收 user 参数,直接取出即可
        m.register(RegisterIn(username="alice", password="secret"))
        self.user = m.store.get_user_by_username("alice")

    def test_new_user_has_one_default_template(self):
        data = m.list_templates(user=self.user)
        self.assertEqual(len(data["templates"]), 1)
        self.assertEqual(data["templates"][0]["id"], data["default_template_id"])
        self.assertEqual(data["templates"][0]["name"], "默认模板")

    def test_add_and_set_default(self):
        tpl = m.add_template(TemplateIn(name="精简版", title="T {start}"), user=self.user)
        self.assertEqual(tpl["name"], "精简版")
        data = m.list_templates(user=self.user)
        self.assertEqual(len(data["templates"]), 2)
        # 新增不改变默认
        self.assertNotEqual(data["default_template_id"], tpl["id"])
        # 设为默认
        m.set_default_template(tpl["id"], user=self.user)
        self.assertEqual(m.list_templates(user=self.user)["default_template_id"], tpl["id"])

    def test_rename_template(self):
        tid = self.user.templates[0]["id"]
        m.save_template(tid, TemplateIn(name="改名后", title="X"), user=self.user)
        self.assertEqual(self.user.templates[0]["name"], "改名后")

    def test_cannot_delete_last_template(self):
        tid = self.user.templates[0]["id"]
        with self.assertRaises(HTTPException) as ctx:
            m.delete_template(tid, user=self.user)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_delete_default_falls_back(self):
        extra = m.add_template(TemplateIn(name="extra"), user=self.user)
        default_id = self.user.default_template_id
        m.delete_template(extra["id"], user=self.user)  # 删非默认
        self.assertEqual(self.user.default_template_id, default_id)
        # 删默认 → 回退到剩余首个
        m.add_template(TemplateIn(name="another"), user=self.user)
        m.delete_template(default_id, user=self.user)
        ids = {t["id"] for t in self.user.templates}
        self.assertNotIn(default_id, ids)
        self.assertIn(self.user.default_template_id, ids)

    def test_create_report_uses_chosen_template(self):
        tpl = m.add_template(
            TemplateIn(name="只标题", title="Custom {start}", sections=[]),
            user=self.user,
        )
        rep = m.create_report(template_id=tpl["id"], user=self.user)
        self.assertTrue(rep["title"].startswith("Custom "))
        self.assertEqual(rep["sections"], [])

    def test_create_report_defaults_to_default_template(self):
        rep = m.create_report(user=self.user)
        # 默认模板含 My Weekly Plan / OMSE 两区块
        self.assertEqual(len(rep["sections"]), 2)


if __name__ == "__main__":
    unittest.main()
