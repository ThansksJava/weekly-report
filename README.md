# 周报系统 Weekly Report System

基于 FastAPI 的可自定义周报系统:每个用户拥有自己的账号与周报模板,
支持自定义标题/问候语/区块/表头列,导出图片与 Excel,一键唤起邮件客户端。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000> ,注册一个账号即可使用。

## 功能

- **登录/注册**:PBKDF2 密码哈希 + Cookie 会话
- **完全可自定义**:标题、问候语、副标题、任意多个区块;每个区块的表头列可增删改名,行可增删;序号列可显示/隐藏
- **选项管理**:工具栏「选项管理」维护项目(MA/D890)、优先级、级别、状态、进度等选项集,可增删改、新建任意选项集;表头悬停 ⚙ 可把列设为「下拉」并绑定选项集,周报单元格即变为下拉选择
- **导入历史周报**:侧边栏「导入历史周报」上传 .xlsx(完整兼容本系统导出格式,对团队原有 Excel 格式做启发式尽力解析),自动还原标题/周期/各区块表格
- **日期组件**:flatpickr 中文日历,与整体主题统一
- **个人模板**:点击「存为我的模板」,把当前结构保存为默认模板,新建周报自动套用(日期自动替换 `{start}`/`{end}` 占位符)
- **自动保存**:编辑后 1.5 秒自动保存,也可 Ctrl/Cmd+S 手动保存
- **导出**:
  - 图片(PNG,2x 清晰度,html2canvas)
  - Excel(.xlsx,openpyxl,带边框/灰底表头样式)
- **发送邮件**:将带格式的 HTML 表格复制到剪贴板并唤起默认邮件客户端(如 Outlook),在正文中粘贴即得完整表格

## 架构

```text
app/
├── main.py          # FastAPI 路由(认证/模板/周报 CRUD/导出)
├── models.py        # 数据模型:User / Report / Section / Column
├── auth.py          # 密码哈希与会话令牌
├── template.py      # 默认周报模板(对应团队 Excel 格式)
├── export.py        # Excel 导出
├── storage/
│   ├── base.py      # Storage 抽象接口
│   └── memory.py    # 内存实现(可替换)
└── static/          # 前端 SPA(原生 HTML/CSS/JS)
```

### 更换数据库

业务代码只依赖 `storage/base.py` 的 `Storage` 抽象接口。
要切换到 SQLite/PostgreSQL/Redis 等,只需:

1. 在 `app/storage/` 下新增实现类(如 `sql.py` 的 `SqlStorage(Storage)`)
2. 修改 `app/main.py` 中的一行装配代码:

   ```python
   store: Storage = SqlStorage(...)  # 原为 MemoryStorage()
   ```

> 注意:当前为内存存储,**重启服务后数据会丢失**,仅用于开发演示。

## 邮件说明

浏览器无法直接把 HTML 写入 `mailto:` 正文(协议只支持纯文本)。
本系统采用的方案:点击「发送邮件」时把周报渲染成内联样式的 HTML 表格
写入剪贴板(`text/html`),同时打开默认邮件客户端;在 Outlook 正文中
按 Ctrl+V 粘贴,表格格式完整保留。如需全自动内嵌,可后续接入
Microsoft Graph API 或本机 Outlook COM 接口。
