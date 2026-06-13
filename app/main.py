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
COOKIE = "wr_session"


# ---------- 请求/响应模型 ----------
class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=4, max_length=100)
    display_name: str = ""
    email: str = ""


class LoginIn(BaseModel):
    username: str
    password: str


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


# ---------- 认证 ----------
def current_user(wr_session: str | None = Cookie(default=None)) -> User:
    if wr_session:
        uid = store.get_session(wr_session)
        if uid:
            user = store.get_user(uid)
            if user:
                return user
    raise HTTPException(status_code=401, detail="未登录")


@app.post("/api/register")
def register(body: RegisterIn, response: Response):
    if store.get_user_by_username(body.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        id=new_id(),
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
        email=body.email,
        templates=default_templates(),
        option_sets=default_option_sets(),
    )
    user.default_template_id = user.templates[0]["id"]
    store.create_user(user)
    token = new_token()
    store.set_session(token, user.id)
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=7 * 86400)
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


@app.post("/api/login")
def login(body: LoginIn, response: Response):
    user = store.get_user_by_username(body.username)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
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


@app.get("/api/reports")
def list_reports(user: User = Depends(current_user)):
    return [
        {"id": r.id, "title": r.title, "week_start": r.week_start, "week_end": r.week_end, "updated_at": r.updated_at}
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
    report.title = body.title
    report.greeting = body.greeting
    report.subtitle = body.subtitle
    report.week_start = body.week_start
    report.week_end = body.week_end
    report.sections = [Section.from_dict(s) for s in body.sections]
    report.updated_at = dt.datetime.now().isoformat(timespec="seconds")
    store.update_report(report)
    return {"ok": True, "updated_at": report.updated_at}


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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
