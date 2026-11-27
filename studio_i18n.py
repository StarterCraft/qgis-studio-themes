"""Translations of the plugin's own texts (for now the ribbon's: its tabs,
group names, button labels and tooltips).

The language is QGIS's user interface language (Settings > Options >
General > Override system locale, else the system's), read once: QGIS
needs a restart to change it anyway. Texts are looked up by their English
original, in a context, since one English word can need two translations
(the "Select" group holds the "Select" button: "Выделение", "Выделить"):

- "title": tab and group names (studio_ribbon.TABS);
- "label": button labels (studio_ribbon.LABELS_BY_NAME);
- "text": other texts (tooltips, window titles).

A text with no translation in a language listed here: tr() gives the
English one, label() None, so the ribbon uses QGIS's own (translated) text
of the action instead of English.

Translations live in i18n/studio_<code>.ts, edited in Qt Linguist (contexts
as above). To add a language, copy i18n/studio_template.ts to
studio_<code>.ts, set its language and translate it. A .qm compiled from it
with lrelease, if present, is used instead of the .ts.
"""
import functools
import os
import xml.etree.ElementTree as ET

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QLocale, QTranslator

I18N = os.path.join(os.path.dirname(__file__), "i18n")


@functools.lru_cache(maxsize=1)
def language():
    """QGIS's user interface language as a two-letter code ("en", "ru"...)."""
    try:
        from qgis.core import QgsApplication  # pylint: disable=import-outside-toplevel
        name = QgsApplication.locale()
    except (ImportError, AttributeError, RuntimeError):
        name = ""
    if not name:
        settings = QgsSettings()
        overridden = settings.value("locale/overrideFlag", False, type=bool)
        name = settings.value("locale/userLocale", "", type=str) if overridden else ""
        name = name or QLocale().name()
    return (name or "en").replace("-", "_").split("_")[0].lower()


@functools.lru_cache(maxsize=1)
def _tables():
    """{context: {English: translation}} for QGIS's language, from
    i18n/studio_<code>.qm (compiled by lrelease) when there is one, else
    from i18n/studio_<code>.ts (Qt Linguist's file, read as XML). None when
    the language has neither file."""
    base = os.path.join(I18N, "studio_" + language())
    if not os.path.exists(base + ".ts"):
        return None
    try:
        root = ET.parse(base + ".ts").getroot()
    except (OSError, ET.ParseError):
        return None
    sources = {}
    tables = {}
    for context in root.iter("context"):
        name = context.findtext("name", "")
        for message in context.iter("message"):
            source = message.findtext("source")
            node = message.find("translation")
            if not source or node is None:
                continue
            sources.setdefault(name, []).append(source)
            if node.get("type") not in ("unfinished", "obsolete", "vanished") and node.text:
                tables.setdefault(name, {})[source] = node.text
    translator = QTranslator()
    if os.path.exists(base + ".qm") and translator.load(base + ".qm"):
        tables = {}
        for name, texts in sources.items():
            for source in texts:
                text = translator.translate(name, source)
                if text:
                    tables.setdefault(name, {})[source] = text
    return tables


def _table(context):
    return (_tables() or {}).get(context, {})


def tr(text, context="text"):
    """`text` in QGIS's language, or as it is when it has no translation."""
    return _table(context).get(text, text) if text else text


def label(text):
    """A button label in QGIS's language. None when the language has a
    translation here that misses this label: the action's own text,
    translated by QGIS, then fits the rest of the ribbon better than the
    English label. Languages with no translation here keep English labels."""
    if not text:
        return None
    if _tables() is None:
        return text
    return _table("label").get(text)
