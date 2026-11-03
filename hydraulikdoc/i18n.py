"""German/English interface texts.

German source texts are the catalogue keys (gettext style), so the code stays readable and German
remains the reference language. Domain code returns :class:`Message` objects: they behave like
German strings everywhere (logs, tests, exceptions) but keep template and parameters, so the
interface can render them again in the reader's language.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

LANGUAGES: Mapping[str, str] = {"de": "Deutsch", "en": "English"}
DEFAULT_LANGUAGE = "de"


class Message(str):
    """A German text that can be re-rendered in another language."""

    template: str
    params: Mapping[str, Any]

    def __new__(cls, template: str, **params: Any) -> Message:
        instance = super().__new__(cls, _render(template, params, DEFAULT_LANGUAGE))
        instance.template = template
        instance.params = params
        return instance


def msg(template: str, **params: Any) -> Message:
    return Message(template, **params)


def translate(text: str, language: str, **params: Any) -> str:
    """Render ``text`` in ``language``; unknown texts fall back to the German source."""
    if isinstance(text, Message) and not params:
        template, params = text.template, dict(text.params)
    else:
        template = str(text)
    if language != DEFAULT_LANGUAGE:
        from .translations import ENGLISH

        template = ENGLISH.get(template, template)
    return _render(template, params, language)


def translate_plural(count: int, singular: str, plural: str, language: str, **params: Any) -> str:
    return translate(singular if count == 1 else plural, language, n=count, **params)


def _render(template: str, params: Mapping[str, Any], language: str) -> str:
    if not params:
        return template
    rendered = {}
    for name, value in params.items():
        if isinstance(value, Message):
            rendered[name] = translate(value, language)
        elif isinstance(value, list | tuple):
            rendered[name] = "; ".join(translate(item, language) for item in value)
        else:
            rendered[name] = value
    return template.format(**rendered)


def preferred_language(accept_language: str | None, fallback: str = DEFAULT_LANGUAGE) -> str:
    """First supported language from an Accept-Language header, honouring q-values."""
    if not accept_language:
        return fallback
    ranked = []
    for position, part in enumerate(accept_language.split(",")):
        tag, _, quality = part.strip().partition(";q=")
        try:
            weight = float(quality) if quality else 1.0
        except ValueError:
            continue
        ranked.append((-weight, position, tag.strip().lower()[:2]))
    for _, _, primary in sorted(ranked):
        if primary in LANGUAGES:
            return primary
    return fallback
