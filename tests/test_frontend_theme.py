import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendThemeTest(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        css_hrefs = re.findall(r'href="/static/([^"]+\.css)"', self.html)
        self.css = "\n".join(
            (ROOT / "static" / href).read_text(encoding="utf-8")
            for href in css_hrefs
        )

    def test_loads_calligraphy_font_system(self):
        font_families = (
            "Liu+Jian+Mao+Cao",
            "Ma+Shan+Zheng",
            "Zhi+Mang+Xing",
            "ZCOOL+XiaoWei",
            "ZCOOL+KuaiLe",
            "Noto+Serif+SC",
        )

        for family in font_families:
            with self.subTest(family=family):
                self.assertIn(family, self.html)

    def test_declares_ink_wash_visual_tokens(self):
        expected_tokens = (
            "#1a1a1a",
            "#333333",
            "#666666",
            "#999999",
            "#F8F5F0",
            "#C41E3A",
            "#2E8B57",
            "#D4AF37",
        )

        for token in expected_tokens:
            with self.subTest(token=token):
                self.assertIn(token, self.css)

    def test_uses_ink_layout_decorations(self):
        expected_fragments = (
            "class=\"brand-seal\"",
            "class=\"vertical-text",
            ".ink-mountains",
            "writing-mode: vertical-rl",
            "filter: blur(",
        )

        combined = self.html + "\n" + self.css
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, combined)


if __name__ == "__main__":
    unittest.main()
