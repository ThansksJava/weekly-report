"""富文本净化单测:白名单保留、危险内容剥离、html_to_text 降级。"""
import unittest

from app.sanitize import html_to_text, sanitize_rich_text


class SanitizeTest(unittest.TestCase):
    def test_keeps_allowed_tags_and_styles(self):
        for frag in [
            "<b>粗</b>", "<i>斜</i>", "<u>线</u>", "line<br>two",
            '<span style="color: #c2452c">红</span>',
            '<span style="font-size: 20px">大</span>',
            '<div style="text-align: center">中</div>',
        ]:
            self.assertEqual(sanitize_rich_text(frag), frag.replace("<br>", "<br>"))

    def test_strips_script_and_handlers(self):
        self.assertEqual(sanitize_rich_text("<script>alert(1)</script>hi"), "hi")
        out = sanitize_rich_text('<span onclick="x()" style="color:red">a</span>')
        self.assertNotIn("onclick", out)
        self.assertIn("color: red", out)

    def test_strips_links_images_unknown(self):
        self.assertEqual(sanitize_rich_text('<a href="http://x">y</a>'), "y")
        self.assertEqual(sanitize_rich_text('<img src="x.png">'), "")
        self.assertEqual(sanitize_rich_text("<table><tr><td>c</td></tr></table>"), "c")

    def test_drops_dangerous_style_values(self):
        out = sanitize_rich_text('<span style="color: red; background: url(x)">a</span>')
        self.assertIn("color: red", out)
        self.assertNotIn("url", out)

    def test_plaintext_escaped(self):
        self.assertEqual(sanitize_rich_text("a & b < c"), "a &amp; b &lt; c")

    def test_html_to_text_linebreaks_and_unescape(self):
        self.assertEqual(html_to_text("a<br>b"), "a\nb")
        self.assertEqual(html_to_text("<div>x</div><div>y</div>"), "x\ny")
        self.assertEqual(html_to_text("a &amp; b"), "a & b")
        self.assertEqual(html_to_text("plain"), "plain")
        self.assertEqual(html_to_text('<b>bold</b> text'), "bold text")


if __name__ == "__main__":
    unittest.main()
