"""SqlStorage 存储契约测试:对 SQLite 内存库验证与 MemoryStorage 一致的行为不变量。

跑:.venv/bin/python3 -m unittest discover tests -v
需要 SQLAlchemy(requirements.txt 已含)。
"""
import unittest

from app.models import Report, Section, User
from app.storage import DuplicateWeekError
from app.storage.sql import SqlStorage


def _user(uid: str, username: str) -> User:
    return User(
        id=uid, username=username, password_hash="h", display_name=username,
        templates=[{"id": "t1", "name": "默认", "sections": []}],
        default_template_id="t1", option_sets={"项目": ["MA", "D890"]},
        created_at="2026-01-01T00:00:00",
    )


def _report(rid: str, user_id: str, week: str) -> Report:
    return Report(
        id=rid, user_id=user_id, title="T", greeting="Hi", subtitle="S",
        week_start=week, week_end=week, updated_at="2026-01-01T00:00:00",
        sections=[Section(id="s1", name="区块", columns=[], rows=[{"a": "1"}])],
    )


class SqlStorageTest(unittest.TestCase):
    def setUp(self):
        # 内存库 + StaticPool:同一进程内共享一份数据
        self.s = SqlStorage("sqlite://")

    def tearDown(self):
        self.s.engine.dispose()

    # ---- 用户 ----
    def test_user_roundtrip_json_fields(self):
        self.s.create_user(_user("u1", "alice"))
        got = self.s.get_user("u1")
        self.assertEqual(got.username, "alice")
        self.assertEqual(got.option_sets, {"项目": ["MA", "D890"]})
        self.assertEqual(got.templates[0]["name"], "默认")

    def test_username_case_insensitive_and_dup(self):
        self.s.create_user(_user("u1", "Alice"))
        self.assertIsNotNone(self.s.get_user_by_username("alice"))
        with self.assertRaises(ValueError):
            self.s.create_user(_user("u2", "ALICE"))

    def test_update_user(self):
        self.s.create_user(_user("u1", "alice"))
        u = self.s.get_user("u1")
        u.status = "rejected"
        self.s.update_user(u)
        self.assertEqual(self.s.get_user("u1").status, "rejected")

    def test_list_users_sorted_by_created_at(self):
        a = _user("u1", "a"); a.created_at = "2026-02-01T00:00:00"
        b = _user("u2", "b"); b.created_at = "2026-01-01T00:00:00"
        self.s.create_user(a); self.s.create_user(b)
        self.assertEqual([u.id for u in self.s.list_users()], ["u2", "u1"])

    # ---- 周报 ----
    def test_report_roundtrip_and_dup_week(self):
        self.s.create_user(_user("u1", "alice"))
        self.s.create_report(_report("r1", "u1", "2026-06-08"))
        got = self.s.get_report("r1")
        self.assertEqual(got.sections[0].rows, [{"a": "1"}])
        self.assertEqual(got.review_status, "draft")
        with self.assertRaises(DuplicateWeekError):
            self.s.create_report(_report("r2", "u1", "2026-06-08"))

    def test_list_reports_sorted_desc(self):
        self.s.create_user(_user("u1", "alice"))
        self.s.create_report(_report("r1", "u1", "2026-06-01"))
        self.s.create_report(_report("r2", "u1", "2026-06-08"))
        self.assertEqual([r.id for r in self.s.list_reports("u1")], ["r2", "r1"])

    def test_review_history_json_roundtrip(self):
        self.s.create_user(_user("u1", "alice"))
        r = _report("r1", "u1", "2026-06-08")
        r.review_status = "pending"
        r.review_history = [{"id": "e1", "action": "submit", "snapshot": {"title": "T", "sections": []}}]
        self.s.create_report(r)
        got = self.s.get_report("r1")
        self.assertEqual(got.review_status, "pending")
        self.assertEqual(got.review_history[0]["snapshot"]["title"], "T")

    # ---- 级联删除 ----
    def test_delete_user_cascades(self):
        self.s.create_user(_user("u1", "alice"))
        self.s.create_report(_report("r1", "u1", "2026-06-08"))
        self.s.set_session("tok", "u1")
        self.s.delete_user("u1")
        self.assertIsNone(self.s.get_user("u1"))
        self.assertEqual(self.s.list_reports("u1"), [])
        self.assertIsNone(self.s.get_session("tok"))

    # ---- 会话 ----
    def test_session_crud(self):
        self.s.create_user(_user("u1", "alice"))
        self.s.set_session("tok", "u1")
        self.assertEqual(self.s.get_session("tok"), "u1")
        self.s.delete_session("tok")
        self.assertIsNone(self.s.get_session("tok"))


if __name__ == "__main__":
    unittest.main()
