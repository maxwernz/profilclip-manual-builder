"""Start the GUI and find (or create) the module library."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from .. import __version__
from ..library import Library


def _candidates(explicit: Path | None) -> list[Path]:
    out = []
    if explicit:
        out.append(explicit)
    stored = QSettings("ProfilClip", "ManualBuilder").value("library", "")
    if stored:
        out.append(Path(stored))
    exe_dir = Path(sys.executable).resolve().parent
    out += [Path.cwd() / "library", exe_dir / "library", exe_dir.parent / "library"]
    return out


def choose_library(parent=None) -> Library | None:
    while True:
        box = QMessageBox(parent)
        box.setWindowTitle("Bibliothek wählen")
        box.setText("Wo liegt die Modul-Bibliothek?\n\n"
                    "Die Bibliothek ist ein Ordner (z. B. auf dem Netzlaufwerk) mit library.yaml, "
                    "den Modulen und den gespeicherten Maschinen.")
        open_btn = box.addButton("Bibliothek öffnen …", QMessageBox.ButtonRole.AcceptRole)
        seed_btn = box.addButton("Neu aus bisherigen Anleitungen …", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Beenden", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is open_btn:
            d = QFileDialog.getExistingDirectory(parent, "Bibliotheksordner wählen")
            if not d:
                continue
            try:
                return Library(Path(d))
            except FileNotFoundError as e:
                QMessageBox.warning(parent, "Keine Bibliothek", str(e))
        elif clicked is seed_btn:
            legacy = QFileDialog.getExistingDirectory(parent, "Ordner „Bedienungsanleitungen“ wählen")
            if not legacy:
                continue
            target = QFileDialog.getExistingDirectory(parent, "Leeren Ordner für die neue Bibliothek wählen")
            if not target:
                continue
            if any(Path(target).iterdir()):
                QMessageBox.warning(parent, "Ordner nicht leer", "Bitte einen leeren Ordner wählen.")
                continue
            from ..seed import seed_from_legacy
            try:
                return seed_from_legacy(Path(legacy), Path(target), log=lambda *_: None)
            except Exception as e:  # pragma: no cover
                QMessageBox.critical(parent, "Fehler", f"Import fehlgeschlagen:\n{e}")
        else:
            return None


def run(library: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Anleitungs-Baukasten")
    app.setOrganizationName("ProfilClip")
    app.setApplicationVersion(__version__)
    from . import style
    style.apply(app)
    translator = QTranslator(app)   # German texts for standard buttons (Speichern, Abbrechen …)
    if translator.load(QLocale(QLocale.Language.German), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)

    lib = None
    for c in _candidates(library):
        if (c / "library.yaml").exists():
            lib = Library(c)
            break
    if lib is None:
        lib = choose_library()
        if lib is None:
            return 0
    QSettings("ProfilClip", "ManualBuilder").setValue("library", str(lib.root))

    from .main_window import MainWindow
    win = MainWindow(lib)
    win.show()
    return app.exec()
