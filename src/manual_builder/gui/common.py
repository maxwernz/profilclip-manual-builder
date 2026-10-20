"""Small shared GUI helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QStyle

MODULE_MIME = "application/x-manual-builder-module"

LANGUAGE_NAMES = {"de": "Deutsch", "en": "Englisch", "it": "Italienisch", "fr": "Französisch",
                  "es": "Spanisch", "nl": "Niederländisch", "pl": "Polnisch"}


def lang_name(code: str) -> str:
    return f"{LANGUAGE_NAMES.get(code, code)} ({code})"


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def std_icon(name: str):
    return QApplication.style().standardIcon(getattr(QStyle.StandardPixmap, name))


ISSUE_ICONS = {"error": "SP_MessageBoxCritical", "warning": "SP_MessageBoxWarning",
               "info": "SP_MessageBoxInformation"}
