"""周报系统 API 入口。

存储后端在此装配:替换 MemoryStorage 为其他 Storage 实现即可切换数据库。
"""
from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import hash_password, new_token, verify_password
from .export import report_to_xlsx
from .importer import parse_xlsx
from .models import Report, Section, User, new_id
from .storage import DuplicateWeekError, MemoryStorage, Storage
from .template import default_option_sets, default_templates, named_template

app = FastAPI(title="Weekly Report System")
store: Storage = MemoryStorage()  # 替换此行即可切换数据库后端

STATIC_DIR = Path(__file__).parent / "static"
COOKIE = "wr_session"        # 普通用户会话 cookie
ADMIN_COOKIE = "wr_admin"    # 管理员会话 cookie(与普通用户隔离,可同浏览器并存)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _new_user(username: str, password: str, *, role: str = "user",
              status: str = "approved", display_name: str = "", email: str = "") -> User:
    """构造一个带默认模板/选项集的用户(注册、管理员新建、种子共用)。"""
    user = User(
        id=new_id(),
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        email=email,
        role=role,
        status=status,
        created_at=_now(),
        templates=default_templates(),
        option_sets=default_option_sets(),
    )
    user.default_template_id = user.templates[0]["id"]
    return user


def _seed_default_users() -> None:
    """启动时确保存在默认账号(内存存储重启即丢,换持久化后可移除)。
    - 管理员 superadmin/superadmin(从 /admin 入口登录)
    - 开发便利普通用户 demo/demo(已审核,可直接登录)
    """
    if not store.get_user_by_username("superadmin"):
        store.create_user(_new_user("superadmin", "superadmin", role="admin", display_name="超级管理员"))
    if not store.get_user_by_username("demo"):
        store.create_user(_new_user("demo", "demo"))


_seed_default_users()


# ---------- 请求/响应模型 ----------
class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=4, max_length=100)
    display_name: str = ""
    email: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


class AdminPasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=4, max_length=100)


class AdminNewUserIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=4, max_length=100)
    display_name: str = ""
    email: str = ""


class AdminResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=4, max_length=100)


class ReportIn(BaseModel):
    title: str = ""
    greeting: str = ""
    subtitle: str = ""
    week_start: str = ""
    week_end: str = ""
    sections: list[dict[str, Any]] = []


class NewReportIn(BaseModel):
    # 指定周报所属周内的任意一天(ISO 日期);留空则取当前周
    week_start: str = ""


class TemplateIn(BaseModel):
    name: str = ""
    title: str = ""
    greeting: str = ""
    subtitle: str = ""
    sections: list[dict[str, Any]] = []


class ReviewIn(BaseModel):
    reason: str = ""


class BatchReviewIn(BaseModel):
    ids: list[str] = []
    action: str = ""  # approve | reject
    reason: str = ""


# ---------- 认证 ----------
def current_user(wr_session: str | None = Cookie(default=None)) -> User:
    """普通用户依赖:要求已登录、角色为 user 且已审核通过。"""
    if wr_session:
        uid = store.get_session(wr_session)
        if uid:
            user = store.get_user(uid)
            if user and user.role == "user" and user.status == "approved":
                return user
    raise HTTPException(status_code=401, detail="未登录")


def current_admin(wr_admin: str | None = Cookie(default=None)) -> User:
    """管理员依赖:要求已登录且角色为 admin。"""
    if wr_admin:
        uid = store.get_session(wr_admin)
        if uid:
            user = store.get_user(uid)
            if user and user.role == "admin":
                return user
    raise HTTPException(status_code=401, detail="未登录")


@app.post("/api/register")
def register(body: RegisterIn):
    if store.get_user_by_username(body.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    # 新注册用户待管理员审核,不自动登录
    user = _new_user(
        body.username, body.password,
        status="pending", display_name=body.display_name, email=body.email,
    )
    store.create_user(user)
    return {"status": "pending", "username": user.username}


@app.post("/api/login")
def login(body: LoginIn, response: Response):
    user = store.get_user_by_username(body.username)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="管理员请从管理员入口 /admin 登录")
    if user.status == "pending":
        raise HTTPException(status_code=403, detail="账号待管理员审核,通过后方可登录")
    if user.status == "rejected":
        raise HTTPException(status_code=403, detail="账号未通过审核,请联系管理员")
    token = new_token()
    store.set_session(token, user.id)
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=7 * 86400)
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


@app.post("/api/logout")
def logout(response: Response, wr_session: str | None = Cookie(default=None)):
    if wr_session:
        store.delete_session(wr_session)
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "email": user.email}


# ---------- 管理员(独立入口 /admin,独立会话 cookie) ----------
def _user_brief(u: User) -> dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "email": u.email,
        "status": u.status,
        "created_at": u.created_at,
        "report_count": len(store.list_reports(u.id)),
    }


def _normal_user(uid: str) -> User:
    """取一个普通用户(管理操作目标),不存在或角色为 admin 时报错。"""
    target = store.get_user(uid)
    if not target or target.role != "user":
        raise HTTPException(status_code=404, detail="用户不存在")
    return target


@app.post("/api/admin/login")
def admin_login(body: LoginIn, response: Response):
    user = store.get_user_by_username(body.username)
    if not user or user.role != "admin" or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = new_token()
    store.set_session(token, user.id)
    response.set_cookie(ADMIN_COOKIE, token, httponly=True, samesite="lax", max_age=7 * 86400)
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


@app.post("/api/admin/logout")
def admin_logout(response: Response, wr_admin: str | None = Cookie(default=None)):
    if wr_admin:
        store.delete_session(wr_admin)
    response.delete_cookie(ADMIN_COOKIE)
    return {"ok": True}


@app.get("/api/admin/me")
def admin_me(admin: User = Depends(current_admin)):
    return {"id": admin.id, "username": admin.username, "display_name": admin.display_name}


@app.post("/api/admin/password")
def admin_change_password(body: AdminPasswordIn, admin: User = Depends(current_admin)):
    if not verify_password(body.old_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    admin.password_hash = hash_password(body.new_password)
    store.update_user(admin)
    return {"ok": True}


@app.get("/api/admin/users")
def admin_list_users(admin: User = Depends(current_admin)):
    return [_user_brief(u) for u in store.list_users() if u.role == "user"]


@app.post("/api/admin/users")
def admin_create_user(body: AdminNewUserIn, admin: User = Depends(current_admin)):
    if store.get_user_by_username(body.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = _new_user(
        body.username, body.password,
        status="approved", display_name=body.display_name, email=body.email,
    )
    store.create_user(user)
    return _user_brief(user)


@app.delete("/api/admin/users/{uid}")
def admin_delete_user(uid: str, admin: User = Depends(current_admin)):
    _normal_user(uid)
    store.delete_user(uid)
    return {"ok": True}


@app.post("/api/admin/users/{uid}/password")
def admin_reset_password(uid: str, body: AdminResetPasswordIn, admin: User = Depends(current_admin)):
    target = _normal_user(uid)
    target.password_hash = hash_password(body.new_password)
    store.update_user(target)
    return {"ok": True}


@app.post("/api/admin/users/{uid}/approve")
def admin_approve_user(uid: str, admin: User = Depends(current_admin)):
    target = _normal_user(uid)
    target.status = "approved"
    store.update_user(target)
    return _user_brief(target)


@app.post("/api/admin/users/{uid}/reject")
def admin_reject_user(uid: str, admin: User = Depends(current_admin)):
    target = _normal_user(uid)
    target.status = "rejected"
    store.update_user(target)
    return _user_brief(target)


@app.get("/api/admin/users/{uid}/reports")
def admin_user_reports(uid: str, admin: User = Depends(current_admin)):
    _normal_user(uid)
    return [
        {"id": r.id, "title": r.title, "week_start": r.week_start, "week_end": r.week_end,
         "updated_at": r.updated_at, "review_status": r.review_status}
        for r in store.list_reports(uid)
    ]


def _last_submit_at(report: Report) -> str:
    """取最近一次提交(submit)的时间,用于待审批队列排序/展示。"""
    subs = [e for e in report.review_history if e.get("action") == "submit"]
    return subs[-1]["at"] if subs else report.updated_at


def _apply_review(report: Report, action: str, admin: User, reason: str) -> None:
    """对 pending 周报执行审批(通过/拒绝);非 pending 抛 409。"""
    if report.review_status != "pending":
        raise HTTPException(status_code=409, detail="该周报当前不可审批")
    actor = admin.display_name or admin.username
    report.review_history.append(_review_event(action, actor, "admin", reason=reason))
    report.review_status = "approved" if action == "approve" else "rejected"
    store.update_report(report)


@app.get("/api/admin/reports/pending")
def admin_pending_reports(admin: User = Depends(current_admin)):
    items = []
    for u in store.list_users():
        if u.role != "user":
            continue
        for r in store.list_reports(u.id):
            if r.review_status == "pending":
                items.append({
                    "id": r.id, "user_id": u.id, "username": u.username,
                    "display_name": u.display_name, "title": r.title,
                    "week_start": r.week_start, "week_end": r.week_end,
                    "submitted_at": _last_submit_at(r),
                })
    items.sort(key=lambda x: x["submitted_at"])
    return items


@app.post("/api/admin/reports/{report_id}/approve")
def admin_approve_report(report_id: str, body: ReviewIn, admin: User = Depends(current_admin)):
    report = store.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="周报不存在")
    _normal_user(report.user_id)
    _apply_review(report, "approve", admin, body.reason)
    return report.to_dict()


@app.post("/api/admin/reports/{report_id}/reject")
def admin_reject_report(report_id: str, body: ReviewIn, admin: User = Depends(current_admin)):
    report = store.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="周报不存在")
    _normal_user(report.user_id)
    _apply_review(report, "reject", admin, body.reason)
    return report.to_dict()


@app.post("/api/admin/reports/review")
def admin_batch_review(body: BatchReviewIn, admin: User = Depends(current_admin)):
    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 必须为 approve 或 reject")
    done, skipped = [], []
    for rid in body.ids:
        report = store.get_report(rid)
        target = store.get_user(report.user_id) if report else None
        if not report or not target or target.role != "user" or report.review_status != "pending":
            skipped.append(rid)
            continue
        _apply_review(report, body.action, admin, body.reason)
        done.append(rid)
    return {"done": done, "skipped": skipped}


@app.get("/api/admin/reports/{report_id}")
def admin_get_report(report_id: str, admin: User = Depends(current_admin)):
    report = store.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="周报不存在")
    _normal_user(report.user_id)  # 仅允许查看普通用户的周报
    return report.to_dict()


# ---------- 模板管理(每个用户可拥有多个命名模板) ----------
def _ensure_templates(user: User) -> None:
    """保证用户至少有一个模板,且 default_template_id 指向一个有效模板。"""
    if not user.templates:
        user.templates = default_templates()
    ids = {t["id"] for t in user.templates}
    if user.default_template_id not in ids:
        user.default_template_id = user.templates[0]["id"]


def _find_template(user: User, tid: str) -> dict[str, Any] | None:
    return next((t for t in user.templates if t.get("id") == tid), None)


@app.get("/api/templates")
def list_templates(user: User = Depends(current_user)):
    _ensure_templates(user)
    store.update_user(user)
    return {"templates": user.templates, "default_template_id": user.default_template_id}


@app.post("/api/templates")
def add_template(body: TemplateIn, user: User = Depends(current_user)):
    _ensure_templates(user)
    tpl = named_template(body.name or "未命名模板", body.model_dump())
    user.templates.append(tpl)
    store.update_user(user)
    return tpl


@app.put("/api/templates/{tid}")
def save_template(tid: str, body: TemplateIn, user: User = Depends(current_user)):
    _ensure_templates(user)
    tpl = _find_template(user, tid)
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    data = body.model_dump()
    tpl["name"] = data["name"] or tpl["name"]
    for k in ("title", "greeting", "subtitle", "sections"):
        tpl[k] = data[k]
    store.update_user(user)
    return tpl


@app.delete("/api/templates/{tid}")
def delete_template(tid: str, user: User = Depends(current_user)):
    _ensure_templates(user)
    if len(user.templates) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个模板")
    if not _find_template(user, tid):
        raise HTTPException(status_code=404, detail="模板不存在")
    user.templates = [t for t in user.templates if t["id"] != tid]
    _ensure_templates(user)  # 删的若是默认模板,回退到首个
    store.update_user(user)
    return {"ok": True, "default_template_id": user.default_template_id}


@app.post("/api/templates/{tid}/default")
def set_default_template(tid: str, user: User = Depends(current_user)):
    _ensure_templates(user)
    if not _find_template(user, tid):
        raise HTTPException(status_code=404, detail="模板不存在")
    user.default_template_id = tid
    store.update_user(user)
    return {"ok": True, "default_template_id": tid}


# ---------- 选项集(项目/优先级/级别/状态等) ----------
class OptionSetsIn(BaseModel):
    option_sets: dict[str, list[str]]


@app.get("/api/options")
def get_options(user: User = Depends(current_user)):
    return user.option_sets or default_option_sets()


@app.put("/api/options")
def save_options(body: OptionSetsIn, user: User = Depends(current_user)):
    user.option_sets = {k: [v for v in vals if v.strip()] for k, vals in body.option_sets.items() if k.strip()}
    store.update_user(user)
    return user.option_sets


# ---------- 周报 ----------
def _fill_dates(text: str, start: str, end: str) -> str:
    s = start.replace("-", ".")
    e = end.replace("-", ".")
    return text.replace("{start}", s).replace("{end}", e)


def _review_event(action: str, actor: str, role: str, reason: str = "",
                  snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    ev = {"id": new_id(), "action": action, "at": _now(), "actor": actor, "actor_role": role, "reason": reason}
    if snapshot is not None:
        ev["snapshot"] = snapshot
    return ev


def _report_snapshot(report: Report) -> dict[str, Any]:
    """提交时冻结一份内容快照(不含 id/日期/审核字段)。"""
    return {
        "title": report.title,
        "greeting": report.greeting,
        "subtitle": report.subtitle,
        "sections": [s.to_dict() for s in report.sections],
    }


@app.get("/api/reports")
def list_reports(user: User = Depends(current_user)):
    return [
        {"id": r.id, "title": r.title, "week_start": r.week_start, "week_end": r.week_end,
         "updated_at": r.updated_at, "review_status": r.review_status}
        for r in store.list_reports(user.id)
    ]


@app.post("/api/reports")
def create_report(
    body: NewReportIn | None = None,
    template_id: str | None = None,
    user: User = Depends(current_user),
):
    _ensure_templates(user)
    base = dt.date.today()
    if body and body.week_start:
        try:
            base = dt.date.fromisoformat(body.week_start)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式无效")
    monday = base - dt.timedelta(days=base.weekday())
    sunday = monday + dt.timedelta(days=6)
    start, end = monday.isoformat(), sunday.isoformat()
    chosen = _find_template(user, template_id) if template_id else None
    chosen = chosen or _find_template(user, user.default_template_id) or user.templates[0]
    tpl = copy.deepcopy(chosen)
    sections = [Section.from_dict(s) for s in tpl.get("sections", [])]
    for s in sections:
        s.id = new_id()
    report = Report(
        id=new_id(),
        user_id=user.id,
        title=_fill_dates(tpl.get("title", ""), start, end),
        greeting=tpl.get("greeting", ""),
        subtitle=_fill_dates(tpl.get("subtitle", ""), start, end),
        week_start=start,
        week_end=end,
        sections=sections,
        updated_at=dt.datetime.now().isoformat(timespec="seconds"),
    )
    try:
        store.create_report(report)
    except DuplicateWeekError:
        raise HTTPException(status_code=409, detail=f"已存在 {start} 当周的周报,请勿重复创建")
    return report.to_dict()


def _owned_report(report_id: str, user: User) -> Report:
    report = store.get_report(report_id)
    if not report or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="周报不存在")
    return report


@app.get("/api/reports/{report_id}")
def get_report(report_id: str, user: User = Depends(current_user)):
    return _owned_report(report_id, user).to_dict()


@app.put("/api/reports/{report_id}")
def update_report(report_id: str, body: ReportIn, user: User = Depends(current_user)):
    report = _owned_report(report_id, user)
    if report.review_status not in ("draft", "rejected"):
        raise HTTPException(status_code=409, detail="周报审核中或已通过,不能修改")
    report.title = body.title
    report.greeting = body.greeting
    report.subtitle = body.subtitle
    report.week_start = body.week_start
    report.week_end = body.week_end
    report.sections = [Section.from_dict(s) for s in body.sections]
    report.updated_at = dt.datetime.now().isoformat(timespec="seconds")
    store.update_report(report)
    return {"ok": True, "updated_at": report.updated_at}


@app.post("/api/reports/{report_id}/submit")
def submit_report(report_id: str, user: User = Depends(current_user)):
    report = _owned_report(report_id, user)
    if report.review_status not in ("draft", "rejected"):
        raise HTTPException(status_code=409, detail="当前状态不能提交审核")
    actor = user.display_name or user.username
    report.review_history.append(
        _review_event("submit", actor, "user", snapshot=_report_snapshot(report))
    )
    report.review_status = "pending"
    store.update_report(report)
    return report.to_dict()


@app.post("/api/reports/{report_id}/withdraw")
def withdraw_report(report_id: str, user: User = Depends(current_user)):
    report = _owned_report(report_id, user)
    if report.review_status != "pending":
        raise HTTPException(status_code=409, detail="仅待审核的周报可撤回")
    actor = user.display_name or user.username
    report.review_history.append(_review_event("withdraw", actor, "user"))
    report.review_status = "draft"
    store.update_report(report)
    return report.to_dict()


@app.post("/api/reports/{report_id}/reopen")
def reopen_report(report_id: str, user: User = Depends(current_user)):
    report = _owned_report(report_id, user)
    if report.review_status != "approved":
        raise HTTPException(status_code=409, detail="仅已通过的周报可重新编辑")
    actor = user.display_name or user.username
    report.review_history.append(_review_event("reopen", actor, "user"))
    report.review_status = "draft"
    store.update_report(report)
    return report.to_dict()


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: str, user: User = Depends(current_user)):
    _owned_report(report_id, user)
    store.delete_report(report_id)
    return {"ok": True}


@app.post("/api/reports/import")
async def import_report(file: UploadFile = File(...), user: User = Depends(current_user)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")
    data = await file.read()
    try:
        report = parse_xlsx(data, user.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败:{e}")
    try:
        store.create_report(report)
    except DuplicateWeekError:
        raise HTTPException(
            status_code=409,
            detail=f"已存在 {report.week_start} 当周的周报,请勿重复导入",
        )
    return report.to_dict()


@app.get("/api/reports/{report_id}/xlsx")
def export_xlsx(report_id: str, user: User = Depends(current_user)):
    report = _owned_report(report_id, user)
    data = report_to_xlsx(report)
    filename = f"weekly-report-{report.week_start}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- 静态页面 ----------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
