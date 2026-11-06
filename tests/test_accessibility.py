"""Accessibility gates that can be checked without a browser (WCAG 2.2 AA contrast and page structure)."""

import importlib.util
import re
import unittest
from pathlib import Path

STYLESHEET = Path(__file__).resolve().parents[1] / "hydraulikdoc" / "styles.css"
UI_MODULE = Path(__file__).resolve().parents[1] / "hydraulikdoc" / "ui.py"
# Streamlit renders primary button labels in white; the stylesheet only sets the background.
STREAMLIT_PRIMARY_LABEL = "#ffffff"


def _top_level_rules(css: str) -> dict[str, dict[str, str]]:
    """First declaration block per selector outside media queries; enough for the flat project stylesheet."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.split(r"@media", css, maxsplit=1)[0]
    rules: dict[str, dict[str, str]] = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        declarations = {
            name.strip(): value.strip()
            for name, value in (item.split(":", 1) for item in body.split(";") if ":" in item)
        }
        for selector in selectors.split(","):
            rules.setdefault(" ".join(selector.split()), declarations)
    return rules


def _luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class ContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = _top_level_rules(STYLESHEET.read_text(encoding="utf-8"))
        cls.tokens = {name: value for name, value in cls.rules[":root"].items() if name.startswith("--")}

    def _colour(self, selector: str, prop: str) -> str:
        value = self.rules[selector][prop].replace("!important", "").split()[-1]
        if match := re.fullmatch(r"var\((--[\w-]+)\)", value):
            value = self.tokens[match.group(1)]
        self.assertRegex(value, r"^#[0-9a-fA-F]{6}$", f"{selector} {prop} must be a solid hex colour")
        return value

    def assertContrast(self, foreground: str, background: str, minimum: float, label: str) -> None:
        ratio = contrast(foreground, background)
        self.assertGreaterEqual(ratio, minimum, f"{label}: {ratio:.2f}:1 < {minimum}:1")

    def test_text_pairs_meet_wcag_aa(self) -> None:
        canvas = self._colour(".stApp", "background")
        surface = self.tokens["--hd-surface"]
        pairs = (
            ("Fließtext", self._colour(".stApp", "color"), canvas),
            ("Hinweistext auf Fläche", self.tokens["--hd-muted"], canvas),
            ("Hinweistext auf Karte", self.tokens["--hd-muted"], surface),
            (
                "Navigation",
                self._colour('[data-testid="stSidebar"] *', "color"),
                self._colour('[data-testid="stSidebar"]', "background"),
            ),
            (
                "Auswahlfeld in der Navigation",
                self._colour('[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="group"] *', "color"),
                self._colour('[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="group"]', "background"),
            ),
            (
                "Primärbutton",
                STREAMLIT_PRIMARY_LABEL,
                self._colour('.stButton > button[kind="primary"]', "background"),
            ),
            (
                "Primärbutton Hover",
                STREAMLIT_PRIMARY_LABEL,
                self._colour('.stButton > button[kind="primary"]:hover', "background"),
            ),
            ("Status Neu", self._colour(".hd-status-new", "color"), self._colour(".hd-status-new", "background")),
            (
                "Status in Arbeit",
                self._colour(".hd-status-in_progress", "color"),
                self._colour(".hd-status-in_progress", "background"),
            ),
            (
                "Status erledigt",
                self._colour(".hd-status-closed", "color"),
                self._colour(".hd-status-closed", "background"),
            ),
            ("Status offen", self._colour(".hd-status-open", "color"), self._colour(".hd-status-open", "background")),
            ("Demo-Kennzeichnung", self._colour(".hd-demo strong", "color"), self._colour(".hd-demo", "background")),
            ("Hinweisbox", self.tokens["--hd-ink"], self._colour(".hd-notice", "background")),
            ("Sperrhinweis", self.tokens["--hd-ink"], self._colour(".hd-blocked", "background")),
        )
        for label, foreground, background in pairs:
            with self.subTest(label):
                self.assertContrast(foreground, background, 4.5, label)

    def test_focus_indicator_is_visible_on_canvas_and_navigation(self) -> None:
        focus = self._colour(":focus-visible", "outline")
        for label, background in (
            ("Arbeitsfläche", self._colour(".stApp", "background")),
            ("Navigation", self._colour('[data-testid="stSidebar"]', "background")),
        ):
            with self.subTest(label):
                self.assertContrast(focus, background, 3.0, f"Fokusrahmen auf {label}")

    def test_reduced_motion_is_respected(self) -> None:
        self.assertIn("prefers-reduced-motion: reduce", STYLESHEET.read_text(encoding="utf-8"))


class StructureTests(unittest.TestCase):
    def test_every_working_page_has_a_single_h1_title(self) -> None:
        source = UI_MODULE.read_text(encoding="utf-8")
        pages = re.findall(
            r"^def _(assets|knowledge|condition_monitoring|fluid|incidents|governance|system)\(", source, re.M
        )
        self.assertEqual(len(pages), 7)
        for page in pages:
            body = source.split(f"def _{page}(", 1)[1].split("\ndef ", 1)[0]
            with self.subTest(page):
                self.assertEqual(body.count("st.title("), 1, f"_{page} needs exactly one st.title (h1)")
                self.assertNotIn("st.header(", body)


class DocumentLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        script = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "set-document-language.py"
        spec = importlib.util.spec_from_file_location("set_document_language", script)
        assert spec and spec.loader
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_streamlit_document_language_is_set_to_german(self) -> None:
        patched = self.module.set_document_language('<!doctype html><html lang="en"><head></head></html>', "de")
        self.assertIn('<html lang="de">', patched)
        self.assertNotIn('lang="en"', patched)

    def test_unexpected_markup_fails_the_build(self) -> None:
        with self.assertRaises(RuntimeError):
            self.module.set_document_language("<!doctype html><html><head></head></html>", "de")
        with self.assertRaises(ValueError):
            self.module.set_document_language('<html lang="en">', 'de" onload="x')

    def test_installed_streamlit_markup_is_still_patchable(self) -> None:
        document = self.module.streamlit_index().read_text(encoding="utf-8")
        self.assertIn('<html lang="de">', self.module.set_document_language(document, "de"))


if __name__ == "__main__":
    unittest.main()
