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
```

没有测试套件和 linter。验证方式是 curl 打 API + puppeteer-core(/tmp/wr-pptr)驱动系统 Chrome 截图核对 UI。

## 架构

**存储抽象是核心设计**:业务代码只依赖 [app/storage/base.py](app/storage/base.py) 的 `Storage` 抽象接口(用户/周报/会话三组方法)。当前用 `MemoryStorage`(内存,重启丢数据)。换数据库 = 在 `app/storage/` 新增实现类 + 改 [app/main.py](app/main.py) 顶部 `store: Storage = MemoryStorage()` 这一行。

**数据模型**([app/models.py](app/models.py)):`Report` = 顶部信息(title/greeting/subtitle/week_start/week_end)+ 多个 `Section`;每个 Section 有自定义 `Column` 列表和 rows(行是 `{col_key: value}` 字典)。`Column.type` 为 `text` 或 `select`,select 列通过 `Column.options` 按名称绑定用户的选项集(`User.option_sets: dict[名称, list[候选值]]`)。"表头完全可自定义"就是靠这个动态列结构实现的。

**模板机制**:`User.template`(结构同 Report 去掉 id/日期)在新建周报时深拷贝,标题中 `{start}`/`{end}` 占位符替换为本周日期(格式 `2026.06.08`)。前端"存为我的模板"做反向替换(日期 → 占位符)。默认模板在 [app/template.py](app/template.py),对应团队 Excel 周报格式(My Weekly Plan + OMSE 两区块)。

**前后端约定**:前端 [app/static/app.js](app/static/app.js) 是单文件 SPA,`current` 全局变量持有完整周报对象,所有编辑直接改它,1.5 秒防抖自动保存(整体 PUT)。`section.to_dict()` 的 JSON 结构在前后端间原样传递 —— 改 Section/Column 字段时两端都要动。认证是 httponly Cookie(`wr_session`)+ PBKDF2,所有 `/api/*`(除 register/login)经 `current_user` 依赖校验。

**导出/导入**:Excel 导出在 [app/export.py](app/export.py)(openpyxl,服务端);PNG 导出在前端用 html2canvas(导出前给报告加 `.exporting` class 隐藏交互元素,CSS 中维护)。导入 [app/importer.py](app/importer.py) 是启发式解析:首个非空行 = 标题(正则提取日期范围),≥3 个非空单元格的行 = 表头行,其上方文本行 = 区块名,首列 "No." = 启用序号列;完整兼容本系统导出格式,对外部 Excel 是尽力解析。

**邮件**:`mailto:` 不支持 HTML 正文,所以方案是前端把内联样式的 HTML 表格写入剪贴板(`ClipboardItem text/html`)再打开 mailto,用户在 Outlook 粘贴。

## 注意

- 前端外部依赖全部走 CDN(html2canvas、flatpickr 及其中文 locale、Google Fonts),离线环境会缺字体和这两个库。
- UI 文案、注释均为中文,设计风格为墨蓝/米白/朱红的商务编辑风(CSS 变量在 [app/static/style.css](app/static/style.css) 顶部),新增 UI 应沿用这些变量。
