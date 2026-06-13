"""周报查重单元测试:同一用户同一周(week_start)只允许一份周报。

不依赖 pytest/httpx —— 直接驱动存储层与端点函数(store 为模块级全局)。
运行:.venv/bin/python3 -m unittest discover tests -v
"""
import unittest
import uuid

from fastapi import HTTPException

import app.main as m
from app.auth import hash_password
from app.export import report_to_xlsx
from app.models import User
from app.storage import DuplicateWeekError, MemoryStorage


def _make_user(username: str) -> User:
    u = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hash_password("x"),
        display_name=username,
    )
    m.store.create_user(u)
    return u


class DedupTest(unittest.TestCase):
    def setUp(self):
        # 每个用例用全新内存存储,互不干扰
        m.store = MemoryStorage()
        self.user = _make_user("alice")

    # ---- 存储层 ----
    def test_storage_rejects_same_user_same_week(self):
        r1 = m.create_report(user=self.user)
        dup = m.store.get_report(r1["id"])
        dup.id = str(uuid.uuid4())  # 不同 id,相同 (user_id, week_start)
        with self.assertRaises(DuplicateWeekError):
            m.store.create_report(dup)

    def test_storage_allows_different_users_same_week(self):
        m.create_report(user=self.user)
        bob = _make_user("bob")
        # 同一周,不同用户 —— 应允许
        m.create_report(user=bob)
        self.assertEqual(len(m.store.list_reports(self.user.id)), 1)
        self.assertEqual(len(m.store.list_reports(bob.id)), 1)

    # ---- 新建端点 ----
    def test_create_endpoint_blocks_second_same_week(self):
        m.create_report(user=self.user)
        with self.assertRaises(HTTPException) as ctx:
            m.create_report(user=self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(len(m.store.list_reports(self.user.id)), 1)

    # ---- 指定周新建 ----
    def test_create_for_specified_week(self):
        # 选周内任意一天(2026-06-17 是周三),应落到整周(周一~周日)
        r = m.create_report(body=m.NewReportIn(week_start="2026-06-17"), user=self.user)
        self.assertEqual(r["week_start"], "2026-06-15")  # 周一
        self.assertEqual(r["week_end"], "2026-06-21")    # 周日(整周)

    def test_create_rejects_invalid_date(self):
        with self.assertRaises(HTTPException) as ctx:
            m.create_report(body=m.NewReportIn(week_start="not-a-date"), user=self.user)
        self.assertEqual(ctx.exception.status_code, 400)

    # ---- 导入端点 ----
    def test_import_blocks_duplicate_week(self):
        r1 = m.create_report(user=self.user)
        xlsx = report_to_xlsx(m.store.get_report(r1["id"]))
        from app.importer import parse_xlsx

        rep = parse_xlsx(xlsx, self.user.id)
        # 导入的周与已存在的本周相同 —— 存储层应拒绝
        self.assertEqual(rep.week_start, r1["week_start"])
        with self.assertRaises(DuplicateWeekError):
            m.store.create_report(rep)
        self.assertEqual(len(m.store.list_reports(self.user.id)), 1)


if __name__ == "__main__":
    unittest.main()
