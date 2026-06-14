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
        # 通过后不可直接编辑
        with self.assertRaises(HTTPException) as ctx:
            m.update_report(self.rid, _report_in(self.rep), user=self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        # 已通过不能直接 reopen,只能「申请修改」-> reopen_pending(仍锁定)
        out = m.request_reopen(self.rid, ReviewIn(reason="补一行"), user=self.user)
        self.assertEqual(out["review_status"], "reopen_pending")
        with self.assertRaises(HTTPException) as ctx:
            m.update_report(self.rid, _report_in(self.rep), user=self.user)
        self.assertEqual(ctx.exception.status_code, 409)
        # 管理员同意修改 -> draft,此后可编辑
        out = m.admin_approve_report(self.rid, ReviewIn(), admin=self.admin)
        self.assertEqual(out["review_status"], "draft")
        self.assertEqual(out["review_history"][-1]["action"], "reopen_approve")
        m.update_report(self.rid, _report_in(self.rep), user=self.user)

    def test_request_reopen_rejected_stays_approved(self):
        m.submit_report(self.rid, user=self.user)
        m.admin_approve_report(self.rid, ReviewIn(), admin=self.admin)
        m.request_reopen(self.rid, ReviewIn(), user=self.user)
        out = m.admin_reject_report(self.rid, ReviewIn(reason="本周已截止"), admin=self.admin)
        self.assertEqual(out["review_status"], "approved")  # 驳回 -> 维持已通过锁定
        self.assertEqual(out["review_history"][-1]["action"], "reopen_reject")

    def test_request_reopen_only_when_approved(self):
        with self.assertRaises(HTTPException) as ctx:  # draft 不能申请修改
            m.request_reopen(self.rid, ReviewIn(), user=self.user)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_withdraw_pending_and_reopen_request(self):
        # pending -> draft
        m.submit_report(self.rid, user=self.user)
        self.assertEqual(m.withdraw_report(self.rid, user=self.user)["review_status"], "draft")
        # reopen_pending -> approved(撤回修改申请)
        m.submit_report(self.rid, user=self.user)
        m.admin_approve_report(self.rid, ReviewIn(), admin=self.admin)
        m.request_reopen(self.rid, ReviewIn(), user=self.user)
        self.assertEqual(m.withdraw_report(self.rid, user=self.user)["review_status"], "approved")

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

    def test_reopen_request_in_queue_with_kind(self):
        m.submit_report(self.rid, user=self.user)
        m.admin_approve_report(self.rid, ReviewIn(), admin=self.admin)
        m.request_reopen(self.rid, ReviewIn(), user=self.user)
        queue = m.admin_pending_reports(admin=self.admin)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["kind"], "reopen")
        # 批量「同意」修改申请 -> draft
        out = m.admin_batch_review(BatchReviewIn(ids=[self.rid], action="approve", reason=""), admin=self.admin)
        self.assertEqual(out["done"], [self.rid])
        self.assertEqual(m.store.get_report(self.rid).review_status, "draft")


if __name__ == "__main__":
    unittest.main()
