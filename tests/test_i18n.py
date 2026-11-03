import ast
import string
import unittest
from pathlib import Path

from hydraulikdoc.config import AppSettings, ConfigurationError
from hydraulikdoc.i18n import Message, msg, preferred_language, translate, translate_plural
from hydraulikdoc.interop import parse_asset_csv
from hydraulikdoc.security import InputRejected, validate_question
from hydraulikdoc.translations import ENGLISH

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / "fluid_advisor.py", *sorted((ROOT / "hydraulikdoc").glob("*.py")))
TRANSLATING_CALLS = {"tr", "msg", "tr_plural"}


def _source_texts() -> dict[str, str]:
    """Every literal German text handed to tr(), msg() or tr_plural(), with its location."""
    texts: dict[str, str] = {}
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in TRANSLATING_CALLS:
                continue
            arguments = node.args[1:3] if node.func.id == "tr_plural" else node.args[:1]
            for argument in arguments:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    texts.setdefault(argument.value, f"{path.name}:{node.lineno}")
    return texts


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


class CatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texts = _source_texts()

    def test_every_source_text_has_an_english_translation(self) -> None:
        missing = [f"{location}: {text}" for text, location in self.texts.items() if text not in ENGLISH]
        self.assertEqual(missing, [], "Missing English translations:\n" + "\n".join(missing))

    def test_placeholders_match_between_languages(self) -> None:
        for german, english in ENGLISH.items():
            with self.subTest(german):
                self.assertEqual(_placeholders(german), _placeholders(english))

    def test_catalogue_has_no_stale_entries(self) -> None:
        stale = sorted(set(ENGLISH) - set(self.texts))
        self.assertEqual(stale, [], "Translations no longer used in the code:\n" + "\n".join(stale))

    def test_notices_exist_in_both_languages(self) -> None:
        from hydraulikdoc.ui import AI_LITERACY_NOTICE, PRIVACY_NOTICE

        for notice in (AI_LITERACY_NOTICE, PRIVACY_NOTICE):
            self.assertEqual(set(notice), {"de", "en"})
            self.assertNotEqual(notice["de"], notice["en"])


class MessageTests(unittest.TestCase):
    def test_message_behaves_like_the_german_string(self) -> None:
        message = msg("Zeile {line}: asset_id doppelt", line=3)
        self.assertIsInstance(message, str)
        self.assertEqual(message, "Zeile 3: asset_id doppelt")
        self.assertEqual(translate(message, "en"), "Row 3: duplicate asset_id")
        self.assertEqual(translate(message, "de"), "Zeile 3: asset_id doppelt")

    def test_nested_messages_and_lists_are_translated(self) -> None:
        with self.assertRaises(ValueError) as raised:
            parse_asset_csv(b"asset_id,name,site,criticality\nA1,X,Y,extrem\nA1,X,Y,low\nA2,,Y,low\n")
        error = raised.exception.args[0]
        self.assertIsInstance(error, Message)
        self.assertIn("Zeile 2: criticality unbekannt", error)
        self.assertEqual(
            translate(error, "en"),
            "Import aborted, no data imported: Row 2: unknown criticality; Row 4: name and site are required",
        )

    def test_domain_validation_messages_are_translatable(self) -> None:
        with self.assertRaises(InputRejected) as raised:
            validate_question("x" * 30, max_chars=10)
        self.assertEqual(translate(raised.exception.args[0], "en"), "The question may contain at most 10 characters.")

    def test_unknown_text_falls_back_to_german(self) -> None:
        self.assertEqual(translate("Nur auf Deutsch", "en"), "Nur auf Deutsch")

    def test_plural_selection(self) -> None:
        singular, plural = "{n} Dokument bereit", "{n} Dokumente bereit"
        self.assertEqual(translate_plural(1, singular, plural, "en"), "1 document ready")
        self.assertEqual(translate_plural(3, singular, plural, "en"), "3 documents ready")
        self.assertEqual(translate_plural(0, singular, plural, "de"), "0 Dokumente bereit")


class LanguageSelectionTests(unittest.TestCase):
    def test_browser_preference_honours_quality_values(self) -> None:
        self.assertEqual(preferred_language("en-GB,en;q=0.9,de;q=0.8"), "en")
        self.assertEqual(preferred_language("fr-FR,de;q=0.7,en;q=0.9"), "en")
        self.assertEqual(preferred_language("de-CH"), "de")

    def test_unsupported_or_missing_preference_uses_fallback(self) -> None:
        self.assertEqual(preferred_language("fr-FR,it;q=0.5", fallback="en"), "en")
        self.assertEqual(preferred_language(None), "de")
        self.assertEqual(preferred_language("en;q=abc,de"), "de")

    def test_default_language_is_validated(self) -> None:
        self.assertEqual(
            AppSettings.from_environment({"APP_ENV": "test", "DEFAULT_LANGUAGE": "EN"}).default_language, "en"
        )
        with self.assertRaisesRegex(ConfigurationError, "DEFAULT_LANGUAGE"):
            AppSettings.from_environment({"APP_ENV": "test", "DEFAULT_LANGUAGE": "fr"})


if __name__ == "__main__":
    unittest.main()
