"""周报审批工作流单元测试:提交/撤回/通过/拒绝/重开 + 编辑约束 + 批量审批。

不依赖 pytest/httpx —— 直接驱动 main.py 中的端点函数(store 为模块级全局)。
运行:.venv/bin/python3 -m unittest discover tests -v
"""
import unittest

from fastapi import HTTPException

import app.main as m
from app.auth import hash_password
from app.main import BatchReviewIn, ReportIn, ReviewIn
from app.models import User
from app.storage import MemoryStorage


def _user(username: str, role: str = "user") -> User:
    u = m._new_user(username, "pw", role=role)
    m.store.create_user(u)
    return u


def _report_in(rep: dict) -> ReportIn:
    return ReportIn(
        title=rep["title"], greeting=rep["greeting"], subtitle=rep["subtitle"],
        week_start=rep["week_start"], week_end=rep["week_end"], sections=rep["sections"],
    )


class ReviewTest(unittest.TestCase):
    def setUp(self):
        m.store = MemoryStorage()
        self.user = _user("alice")
        self.admin = _user("root", role="admin")
        self.rep = m.create_report(user=self.user)  # draft
        self.rid = self.rep["id"]

    def test_new_report_is_draft(self):
        self.assertEqual(self.rep["review_status"], "draft")

    def test_submit_creates_snapshot_and_pending(self):
        out = m.submit_report(self.rid, user=self.user)
        self.assertEqual(out["review_status"], "pending")
        subs = [e for e in out["review_history"] if e["action"] == "submit"]
        self.assertEqual(len(subs), 1)
        self.assertIn("snapshot", subs[0])
        self.assertEqual(subs[0]["actor_role"], "user")

    def test_edit_blocked_while_pending(self):
        m.submit_report(self.rid, user=self.user)
        with self.assertRaises(HTTPException) as ctx:
            m.update_report(self.rid, _report_in(self.rep), user=self.user)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_reject_then_edit_then_resubmit(self):
        m.submit_report(self.rid, user=self.user)
        out = m.admin_reject_report(self.rid, ReviewIn(reason="格式不对"), admin=self.admin)
        self.assertEqual(out["review_status"], "rejected")
        self.assertEqual(out["review_history"][-1]["reason"], "格式不对")
        # rejected 可再编辑
        m.update_report(self.rid, _report_in(self.rep), user=self.user)
        # 重新提交
        out = m.submit_report(self.rid, user=self.user)
        self.assertEqual(out["review_status"], "pending")
        self.assertEqual(len([e for e in out["review_history"] if e["action"] == "submit"]), 2)

    def test_approve_locks_then_reopen(self):
        m.submit_report(self.rid, user=self.user)
        out = m.admin_approve_report(self.rid, ReviewIn(reason="OK"), admin=self.admin)
        self.assertEqual(out["review_status"], "approved")
        # 通过后不可编辑
        with self.assertRaises(HTTPException) as ctx:
            m.update_report(self.rid, _report_in(self.rep), user=self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        # 重新编辑 -> draft
        out = m.reopen_report(self.rid, user=self.user)
        self.assertEqual(out["review_status"], "draft")
        m.update_report(self.rid, _report_in(self.rep), user=self.user)  # 现在可编辑

    def test_withdraw(self):
        m.submit_report(self.rid, user=self.user)
        out = m.withdraw_report(self.rid, user=self.user)
        self.assertEqual(out["review_status"], "draft")

    def test_approve_non_pending_409(self):
        with self.assertRaises(HTTPException) as ctx:  # 仍是 draft
            m.admin_approve_report(self.rid, ReviewIn(), admin=self.admin)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_pending_queue_and_batch(self):
        bob = _user("bob")
        r2 = m.create_report(user=bob)["id"]
        m.submit_report(self.rid, user=self.user)
        m.submit_report(r2, user=bob)
        queue = m.admin_pending_reports(admin=self.admin)
        self.assertEqual({q["id"] for q in queue}, {self.rid, r2})
        # 批量通过(含一个非法 id -> skipped)
        out = m.admin_batch_review(
            BatchReviewIn(ids=[self.rid, r2, "nope"], action="approve", reason="批量"),
            admin=self.admin,
        )
        self.assertEqual(set(out["done"]), {self.rid, r2})
        self.assertEqual(out["skipped"], ["nope"])
        self.assertEqual(m.store.get_report(self.rid).review_status, "approved")
        self.assertEqual(m.admin_pending_reports(admin=self.admin), [])


if __name__ == "__main__":
    unittest.main()
