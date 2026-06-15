"""富文本净化(纯标准库,无外部依赖)。

顶部三字段(标题/问候语/副标题)在前端是 contenteditable 富文本,内容以 HTML
形式存储。**所有写入路径都必须经过 sanitize_rich_text**,作为唯一可信入口:
白名单标签 + 受限内联样式,剥离脚本/事件/链接/图片等,杜绝跨用户(管理员查看)XSS。

html_to_text 用于 Excel 导出:富文本不便在 openpyxl 中还原,降级为带换行的纯文本。
"""
from __future__ import annotations

from html import escape, unescape
from html.parser import HTMLParser

# 允许的标签(execCommand + styleWithCSS 主要产出这些)
_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "br", "p", "div", "span"}
# 允许保留的内联样式属性
_ALLOWED_STYLE_PROPS = {
    "color", "font-size", "text-align", "font-weight", "font-style", "text-decoration",
}
_VOID_TAGS = {"br"}
# 换行语义标签(html_to_text 用)
_BLOCK_TAGS = {"p", "div"}


def _clean_style(value: str) -> str:
    """仅保留白名单内的 style 声明,丢弃可能含 url()/expression 等的危险值。"""
    out = []
    for decl in value.split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop = prop.strip().lower()
        val = val.strip()
        if prop not in _ALLOWED_STYLE_PROPS or not val:
            continue
        # 防注入:剔除含括号/分号转义等的可疑值(url()、expression() 等)
        if any(ch in val for ch in "(){}<>") or "javascript" in val.lower():
            continue
        out.append(f"{prop}: {val}")
    return "; ".join(out)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._open: list[str] = []  # 已输出的开标签栈(用于闭合配对)
        self._suppress = 0  # >0 时丢弃文本(位于 script/style 等内部)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style"):
            self._suppress += 1
            return
        if tag not in _ALLOWED_TAGS:
            return
        style = ""
        for k, v in attrs:
            if k.lower() == "style" and v:
                style = _clean_style(v)
        attr = f' style="{escape(style, quote=True)}"' if style else ""
        if tag in _VOID_TAGS:
            self.parts.append(f"<{tag}{attr}>")
        else:
            self.parts.append(f"<{tag}{attr}>")
            self._open.append(tag)

    def handle_startendtag(self, tag, attrs):
        # <br/> 之类
        if tag.lower() in _ALLOWED_TAGS:
            self.handle_starttag(tag, attrs)
            if tag.lower() not in _VOID_TAGS:
                self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style"):
            if self._suppress:
                self._suppress -= 1
            return
        if tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        # 闭合到匹配的开标签(容忍嵌套不规整)
        if tag in self._open:
            while self._open:
                top = self._open.pop()
                self.parts.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data):
        if self._suppress:
            return
        self.parts.append(escape(data))

    def close_remaining(self) -> None:
        while self._open:
            self.parts.append(f"</{self._open.pop()}>")


def sanitize_rich_text(html: str) -> str:
    """按白名单净化富文本 HTML;纯文本(无标签)会被安全转义为合法 HTML。"""
    if not html:
        return ""
    p = _Sanitizer()
    p.feed(html)
    p.close()
    p.close_remaining()
    return "".join(p.parts)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """把富文本 HTML 降级为纯文本(块级/`<br>` → 换行),用于 Excel 导出。"""
    if not html:
        return ""
    if "<" not in html:
        return unescape(html)
    p = _TextExtractor()
    p.feed(html)
    p.close()
    text = "".join(p.parts)
    # 折叠多余空行并去首尾空白
    lines = [ln.strip() for ln in text.split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            blank = True
    return "\n".join(out).strip()
