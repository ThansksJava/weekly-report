# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

可自定义的周报系统(中文界面):FastAPI 后端 + 原生 HTML/CSS/JS 前端(无构建步骤),每个用户有独立账号、周报模板和下拉选项集,支持导出 PNG/Excel、导入历史 .xlsx、通过剪贴板 + mailto 发送邮件。

## 常用命令

```bash
# 环境(首次)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 运行(开发时加 --reload)
.venv/bin/uvicorn app.main:app --reload --port 8000

# 前端 JS 语法检查 / 后端导入检查
node --check app/static/app.js
.venv/bin/python3 -c "import app.main"

# 单元测试(标准库 unittest,无需 pytest;直接驱动存储层与端点函数)
.venv/bin/python3 -m unittest discover tests -v
```

没有 linter。tests/ 下有少量 unittest 用例(无 pytest/httpx 依赖)。其余验证方式是 curl 打 API + puppeteer-core(/tmp/wr-pptr)驱动系统 Chrome 截图核对 UI。

**并行开发(git worktree)**:`trees/` 目录(已 gitignore)放并行 worktree,每个对应一个分支。各 worktree 通过软链共用主目录的 `.venv`(`ln -sfn ../../.venv .venv`),无需重复装依赖;各自从所属目录加载代码、独立端口启动(主 8000,worktree 用 8001/8002/8003…),数据互相隔离(各自 `MemoryStorage` 内存实例)。

```bash
git worktree add trees/dev1 -b dev1
ln -sfn /Users/fengjie/workspace/unisys/weekly-report/.venv trees/dev1/.venv
cd trees/dev1 && .venv/bin/uvicorn app.main:app --reload --port 8001
```

**周报唯一性**:同一用户的同一周(`week_start`)只允许一份周报。约束下沉在存储层 `create_report`——重复时抛 `DuplicateWeekError`,新建/导入两个端点都捕获并返回 409。换数据库实现时务必保持这一不变量。

**指定周新建**:`POST /api/reports` 接受可选 body `{week_start}`(周内任意一天的 ISO 日期),后端按其 `weekday()` 归算到整周(周一~周日,见下「周跨度」);留空则取当前周。前端「新建周报」按钮弹出选周弹窗(`#newreport-modal`,独立 flatpickr `fpNew`),`weekRange()` 在前端预览将创建的日期范围,真正归算仍以后端为准;多模板时弹窗内同时提供模板选择(`#newreport-templates`),创建时一并传 `?template_id=`。

**周跨度**:`week_start`=本周一,`week_end`=本周日(`monday + 6` 天,整周)。新建周报([app/main.py](app/main.py) `create_report`)与导入兜底([app/importer.py](app/importer.py) 无法解析日期时)都按此归算。

## 架构

**存储抽象是核心设计**:业务代码只依赖 [app/storage/base.py](app/storage/base.py) 的 `Storage` 抽象接口(用户/周报/会话三组方法)。两个实现:`MemoryStorage`(内存,重启丢数据)与 `SqlStorage`([app/storage/sql.py](app/storage/sql.py),SQLAlchemy 持久化)。装配在 [app/main.py](app/main.py) `_make_storage()`,由环境变量 **`WR_DATABASE_URL`** 决定:**未设置 → `MemoryStorage`(默认,测试/快速开发);已设置 → `SqlStorage(url)`**,如 `sqlite:///./data/weekly_report.db`、`postgresql+psycopg://user:pw@host:5432/wr`(Postgres 另需 `psycopg`,见 requirements 注释)。`SqlStorage` 只在配了 DB 时才惰性导入(`storage/__init__.py` 的 `__getattr__`),故无 DB 时不强依赖 SQLAlchemy。

**SqlStorage 设计**:用 SQLAlchemy **Core**(非 ORM)定义 `users/reports/sessions` 三表,领域模型仍是 [app/models.py](app/models.py) 的 dataclass,读写时经 `User/Report` 的 `to_dict`/`from_dict` 做「行↔模型」映射。**混合模型**:可查询/约束字段用普通列,动态嵌套内容(`templates/option_sets/sections/review_history`)用 **`JSON` 列**(SQLite 落 TEXT、Postgres 落 JSON)。不变量落实:`UNIQUE(user_id, week_start)` 命中 `IntegrityError` → 抛 `DuplicateWeekError`;`delete_user` 同一事务显式删 reports+sessions+user(不只靠 DB 外键);用户名查重/查询大小写不敏感(`lower()`);`list_reports` 按 `week_start` 降序、`list_users` 按 `created_at`,与 `MemoryStorage` 一致。建表用 `metadata.create_all`(幂等,无 Alembic;改表结构目前需手动)。时间统一存 ISO 字符串(`String` 列),不用 datetime 类型。会话也持久化(重启不掉登录)。`tests/test_sql_storage.py` 用 `sqlite://`(StaticPool 内存库)跑契约测试。

**权限/角色系统**:`User` 有 `role`(`user`|`admin`)与 `status`(`pending`|`approved`|`rejected`)两字段。**普通用户注册后为 `pending`,只有管理员审核通过(`approved`)才能登录**;`login` 端点对 pending/rejected/admin 各返回 403。管理员从**独立地址 `/admin`**([app/static/admin.html](app/static/admin.html) + [admin.js](app/static/admin.js))登录,**用独立 cookie `wr_admin`**(普通用户用 `wr_session`,两套会话可同浏览器并存)。两个依赖:`current_user` 要求 role=user 且 approved;`current_admin` 要求 role=admin。管理端点 `/api/admin/*`:改自己密码、列出/新建(直接 approved)/删除/重置密码/审核(approve·reject)普通用户、查看任意普通用户的周报(`/api/admin/users/{uid}/reports` + 只读 `/api/admin/reports/{rid}`);均经 `current_admin`,且对普通用户的操作经 `_normal_user()` 拒绝越权操作管理员账号。

**删用户级联不变量**:`Storage.delete_user` 删用户时**必须同时删其全部周报与名下会话 token**(`MemoryStorage` 已实现;换数据库务必保持)。

**周报审批工作流**:`Report` 有 `review_status`(`draft`|`pending`|`approved`|`rejected`|`reopen_pending`)与 `review_history`(事件时间线)。状态机:新建/导入=`draft` → 用户「提交审核」=`pending`(**入一条 submit 事件并冻结内容快照**)→ 管理员「通过」=`approved` 或「拒绝」=`rejected`(均可附理由);`pending` 可被用户「撤回」回 `draft`,`rejected` 改后可重新提交。**已通过不能直接重编**:`approved` 时用户只能「申请修改」(`POST /api/reports/{id}/request-reopen`)→ `reopen_pending`(仍锁定),**须管理员同意后才放开**——管理员对 `reopen_pending` 执行 approve→`draft`(放开编辑,记 `reopen_approve`)/ reject→`approved`(驳回维持锁定,记 `reopen_reject`);用户也可「撤回申请」(`withdraw`:`reopen_pending`→`approved`)。`pending` 与 `reopen_pending` 统称待审(常量 `_REVIEWABLE`),共用 `_apply_review()`(按当前状态分流语义)、共同出现在待审队列与批量审批。**草稿对管理员不可见**(隐私门禁):`admin_user_reports` 与 `admin_get_report` 都过滤掉 `review_status=="draft"` 的周报,`_user_brief.report_count` 只统计非草稿。**编辑约束**:`PUT /api/reports/{id}` 与各 review 端点按状态校验,仅 `draft`/`rejected` 可编辑/提交,否则 409;前端 [app/static/app.js](app/static/app.js) 用 **`body.report-locked`** 锁定只读(`pending`/`approved`/`reopen_pending`),双保险。`review_history` 每条 `{id, action, at, actor, actor_role, reason, snapshot}`,`action` ∈ `submit|withdraw|approve|reject|reopen_request|reopen_approve|reopen_reject|reopen_cancel`,`snapshot` 仅 `submit` 携带。用户端点:`submit|withdraw|request-reopen`;管理端点:`GET /api/admin/reports/pending`(跨用户待审队列,每项带 `kind`:`submit` 新提交 / `reopen` 修改申请)、`POST /api/admin/reports/{id}/approve|reject`、`POST /api/admin/reports/review`(批量,返回 `{done,skipped}`,非待审跳过)。前端:用户端工具栏状态徽章 + 提交/撤回/申请修改/审核历史(`#history-modal`,submit 快照可只读全屏查看);管理端「待审批周报」区块(勾选批量 + 单条审批,新提交/修改申请用 `kind` 徽章区分、按钮文案相应为 通过·拒绝 / 同意·驳回,理由弹窗)与「查看周报」弹窗内状态徽章 + 审核历史时间线 + 就地审批。侧栏列表项均带状态徽章。

**默认账号(开发便利)**:[app/main.py](app/main.py) `_seed_default_users()` 在模块加载时确保存在管理员 `superadmin/superadmin`(role=admin)与开发便利普通用户 `demo/demo`(已审核),省去内存存储每次重启后重新注册登录的麻烦。构造用户走统一的 `_new_user()`。换持久化后端后可移除此段。

**数据模型**([app/models.py](app/models.py)):`Report` = 顶部信息(title/greeting/subtitle/week_start/week_end)+ 多个 `Section`;每个 Section 有自定义 `Column` 列表和 rows(行是 `{col_key: value}` 字典)。`Column.type` 为 `text` 或 `select`,select 列通过 `Column.options` 按名称绑定用户的选项集(`User.option_sets: dict[名称, list[候选值]]`)。"表头完全可自定义"就是靠这个动态列结构实现的。

**模板机制(多模板)**:每个用户拥有 `User.templates`(命名模板列表,每项 `{id, name, title, greeting, subtitle, sections}`,结构同 Report 去掉 id/user_id/日期)+ `User.default_template_id`。新建周报时深拷贝选中的模板(`POST /api/reports?template_id=...`,缺省用默认模板),标题中 `{start}`/`{end}` 占位符替换为本周日期(格式 `2026.06.08`)。前端"存为模板"做反向替换(日期 → 占位符)并提示命名(同名覆盖)。`/api/templates` 一组端点做增删改/设默认;`main.py` 的 `_ensure_templates` 保证用户至少有一个模板且 `default_template_id` 有效(老数据/空模板用户也安全)。默认模板正文在 [app/template.py](app/template.py),对应团队 Excel 周报格式(My Weekly Plan + OMSE 两区块);`default_templates()` 把它包装成初始模板列表。前端侧栏"+ 新建本周周报"按钮在有多个模板时弹出模板选择浮层,工具栏"模板管理"弹窗做重命名/设默认/删除(至少保留一个)/**修改**。"修改"进入**模板编辑模式**(`app.js` 的 `enterTemplateEdit`/`leaveTemplateMode`/`editingTemplateId`):复用周报编辑器,把模板正文塞进 `current` 当"伪周报"编辑,`editingTemplateId` 非空时 `saveReport` 改写回 `PUT /api/templates/{id}`(而非周报端点);此模式下 `body.tpl-editing` 类隐藏与周报实例相关的工具(导出/邮件/删除/存为模板/模板管理/日期选择),显示顶部 `#tpl-edit-bar` 提示条与"完成编辑"按钮。标题/副标题中的 `{start}`/`{end}` 占位符在模板模式下原样显示与编辑。

**前后端约定**:前端 [app/static/app.js](app/static/app.js) 是单文件 SPA,`current` 全局变量持有完整周报对象,所有编辑直接改它,1.5 秒防抖自动保存(整体 PUT)。`section.to_dict()` 的 JSON 结构在前后端间原样传递 —— 改 Section/Column 字段时两端都要动。认证是 httponly Cookie(`wr_session`)+ PBKDF2,所有 `/api/*`(除 register/login)经 `current_user` 依赖校验。

**导出/导入**:Excel 导出在 [app/export.py](app/export.py)(openpyxl,服务端,`GET /api/reports/{id}/xlsx`);前端导出按钮在锁定状态(待审/已通过/修改待审)下**跳过 saveReport**(否则 PUT 会 409 导致导出失效),直接拉取已存内容。导入 [app/importer.py](app/importer.py) 是启发式解析:首个非空行 = 标题(正则提取日期范围),≥3 个非空单元格的行 = 表头行,其上方文本行 = 区块名,首列 "No." = 启用序号列;完整兼容本系统导出格式,对外部 Excel 是尽力解析。

**邮件**:`mailto:` 不支持 HTML 正文,所以方案是前端把内联样式的 HTML 表格写入剪贴板(`ClipboardItem text/html`)再打开 mailto,用户在 Outlook 粘贴。

## 注意

- 前端外部依赖全部走 CDN(flatpickr 及其中文 locale、Google Fonts),离线环境会缺字体和该库。
- UI 文案、注释均为中文,设计风格为墨蓝/米白/朱红的商务编辑风(CSS 变量在 [app/static/style.css](app/static/style.css) 顶部),新增 UI 应沿用这些变量。
