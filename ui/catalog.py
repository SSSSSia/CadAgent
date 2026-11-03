"""Qt TS catalog for the panel strings (Phase 9.2).

``t()`` reads this file for Chinese. A ``.qm`` next to it is optional:
``install_qtranslator`` loads it when lrelease has been run. The TS
file is enough for the panel, which does not call ``QObject.tr``.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape


def ts_path() -> str:
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(root, "resources", "translations", "cadagent_zh.ts")


def qm_path() -> str:
    return os.path.splitext(ts_path())[0] + ".qm"


def build_ts(english: dict, chinese: dict) -> str:
    """Qt linguist XML. Source text is the English string."""
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<!DOCTYPE TS>",
        '<TS version="2.1" language="zh_CN">',
        '<context>',
        "<name>CadAgent</name>",
    ]
    for key in english:
        source = english[key]
        target = chinese.get(key, source)
        lines.append("<message>")
        lines.append(f"<source>{escape(source)}</source>")
        lines.append(f"<translation>{escape(target)}</translation>")
        lines.append(f"<!-- key:{escape(key)} -->")
        lines.append("</message>")
    lines.append("</context>")
    lines.append("</TS>")
    lines.append("")
    return "\n".join(lines)


def load_catalog(path: str | None = None) -> dict[str, str]:
    """Map English source text to the Chinese translation."""
    tree = ET.parse(path or ts_path())
    catalog = {}
    for message in tree.getroot().iter("message"):
        source = message.findtext("source") or ""
        target = message.findtext("translation")
        if source and target:
            catalog[source] = target
    return catalog


def install_qtranslator(app=None) -> bool:
    """Install a QTranslator when a compiled ``.qm`` is present.

    Returns False when Qt or the ``.qm`` file is missing. The panel still
    translates through the TS catalog in that case.
    """
    qm = qm_path()
    if not os.path.isfile(qm):
        return False
    try:
        from PySide6.QtCore import QTranslator
    except Exception:
        return False
    if app is None:
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
        except Exception:
            app = None
    if app is None:
        return False
    translator = QTranslator(app)
    if not translator.load(qm):
        return False
    app.installTranslator(translator)
    return True
