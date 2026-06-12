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
from .template import default_option_sets, default_template

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


class TemplateIn(BaseModel):
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
        template=default_template(),
        option_sets=default_option_sets(),
    )
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


# ---------- 模板 ----------
@app.get("/api/template")
def get_template(user: User = Depends(current_user)):
    return user.template or default_template()


@app.put("/api/template")
def save_template(body: TemplateIn, user: User = Depends(current_user)):
    user.template = body.model_dump()
    store.update_user(user)
    return {"ok": True}


@app.post("/api/template/reset")
def reset_template(user: User = Depends(current_user)):
    user.template = default_template()
    store.update_user(user)
    return user.template


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
def create_report(user: User = Depends(current_user)):
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    friday = monday + dt.timedelta(days=4)
    start, end = monday.isoformat(), friday.isoformat()
    tpl = copy.deepcopy(user.template or default_template())
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
        raise HTTPException(status_code=409, detail="本周周报已存在,请勿重复创建")
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
