"""Import a new or updated Word file into the library (check first, then import)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout)

from ..importer import check, import_file, is_word_file, machines_using
from ..library import Library, slugify
from .common import lang_name


def _differs(a: str, b: str) -> bool:
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    a, b = norm(a), norm(b)
    return not (a in b or b in a)


class DropLabel(QLabel):
    def __init__(self, on_file):
        super().__init__("Word-Datei (.docx) hierher ziehen\noder „Datei wählen …“")
        self.on_file = on_file
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(70)
        self.setStyleSheet("QLabel{border:2px dashed #999;border-radius:6px;padding:8px;}")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.on_file(Path(urls[0].toLocalFile()))


class ImportDialog(QDialog):
    def __init__(self, lib: Library, parent=None, module_id: str | None = None,
                 file: Path | None = None):
        super().__init__(parent)
        self.lib = lib
        self.file: Path | None = None
        self.checked = False
        self.imported_module: str | None = None
        self.setWindowTitle("Word-Datei importieren")
        self.resize(760, 680)
        lay = QVBoxLayout(self)

        frow = QHBoxLayout()
        self.drop = DropLabel(self.set_file)
        frow.addWidget(self.drop, 1)
        b = QPushButton("Datei wählen …")
        b.clicked.connect(self.choose_file)
        frow.addWidget(b)
        lay.addLayout(frow)

        box = QGroupBox("Ziel")
        form = QFormLayout(box)
        self.rb_update = QRadioButton("Bestehendes Modul aktualisieren / Sprache ergänzen")
        self.rb_new = QRadioButton("Neues Modul anlegen")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_update)
        grp.addButton(self.rb_new)
        form.addRow(self.rb_update)
        self.module_box = QComboBox()
        for m in sorted(lib.modules.values(), key=lambda m: (lib.slot_index(m.slot), m.label())):
            self.module_box.addItem(f"{m.label()}   [{m.id}]", m.id)
        form.addRow("   Modul:", self.module_box)
        form.addRow(self.rb_new)
        self.title_edit = QLineEdit()
        self.title_edit.textChanged.connect(self._title_changed)
        self.id_edit = QLineEdit()
        self.slot_box = QComboBox()
        for s in lib.slots:
            self.slot_box.addItem(s.label("de"), s.id)
        self.kind_box = QComboBox()
        self.kind_box.addItem("Ein Kapitel (Baugruppe)", "component")
        self.kind_box.addItem("Mehrere Kapitel (z. B. Allgemeines)", "chapters")
        form.addRow("   Titel:", self.title_edit)
        form.addRow("   ID:", self.id_edit)
        form.addRow("   Platz:", self.slot_box)
        form.addRow("   Art:", self.kind_box)
        self.lang_box = QComboBox()
        for code in lib.languages:
            self.lang_box.addItem(lang_name(code), code)
        form.addRow("Sprache der Datei:", self.lang_box)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("z. B. „Neue Fotos Drahtvorschub“")
        form.addRow("Änderungsnotiz:", self.note_edit)
        lay.addWidget(box)

        for w in (self.rb_update, self.rb_new, self.module_box, self.slot_box, self.kind_box,
                  self.lang_box):
            sig = w.toggled if isinstance(w, QRadioButton) else w.currentIndexChanged
            sig.connect(self._invalidate)
        self.rb_update.toggled.connect(self._mode_changed)

        lay.addWidget(QLabel("Prüfergebnis:"))
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        lay.addWidget(self.report, 1)

        brow = QHBoxLayout()
        brow.addStretch()
        self.check_btn = QPushButton("Prüfen")
        self.check_btn.clicked.connect(self.run_check)
        self.import_btn = QPushButton("Importieren")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self.run_import)
        cancel = QPushButton("Schließen")
        cancel.clicked.connect(self.reject)
        for w in (self.check_btn, self.import_btn, cancel):
            brow.addWidget(w)
        lay.addLayout(brow)

        if module_id and self.module_box.findData(module_id) >= 0:
            self.module_box.setCurrentIndex(self.module_box.findData(module_id))
            self.rb_update.setChecked(True)
        else:
            self.rb_update.setChecked(bool(lib.modules))
            self.rb_new.setChecked(not lib.modules)
        self._mode_changed()
        if file:
            self.set_file(file)

    # ---------------------------------------------------------------- state
    def _mode_changed(self) -> None:
        upd = self.rb_update.isChecked()
        self.module_box.setEnabled(upd)
        for w in (self.title_edit, self.id_edit, self.slot_box, self.kind_box):
            w.setEnabled(not upd)

    def _title_changed(self, text: str) -> None:
        self.id_edit.setText(slugify(text))
        self._invalidate()

    def _invalidate(self, *_):
        self.checked = False
        self.import_btn.setEnabled(False)

    def choose_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Word-Datei wählen", "", "Word (*.docx)")
        if f:
            self.set_file(Path(f))

    def set_file(self, path: Path) -> None:
        if not is_word_file(path):
            QMessageBox.warning(self, "Keine Word-Datei",
                                f"'{path.name}' ist keine .docx-Datei (oder eine Word-Sperrdatei ~$…).")
            return
        self.file = path
        self.drop.setText(f"{path.name}\n{path.parent}")
        if not self.title_edit.text():
            self.title_edit.setText(path.stem)
        self._invalidate()
        self.run_check()

    def _target(self):
        if self.rb_update.isChecked():
            m = self.lib.modules.get(self.module_box.currentData())
            return m, m.kind if m else "component", m.label(self.lang_box.currentData()) if m else ""
        return None, self.kind_box.currentData(), self.title_edit.text().strip()

    # ---------------------------------------------------------------- actions
    def run_check(self) -> None:
        if not self.file:
            QMessageBox.information(self, "Datei fehlt", "Bitte zuerst eine Word-Datei wählen.")
            return
        module, kind, title = self._target()
        rep = check(self.lib, self.file, kind=kind, title=title)
        lines = [rep.summary()]
        lang = self.lang_box.currentData()
        if module is not None:
            first = rep.headings[0].text if rep.headings else ""
            if module.kind == "component" and first and _differs(first, module.label(lang)) \
                    and _differs(first, module.label()):
                lines.append(f"\n[WARNING] Erste Überschrift „{first}“ passt nicht zum Modul "
                             f"„{module.label(lang)}“ – richtiges Modul gewählt?")
            if module.docx_path(lang).exists():
                lines.append(f"\n→ Ersetzt {lang}.docx von '{module.label()}' "
                             f"(alte Fassung wird archiviert, Version {module.version} → {module.version + 1}).")
            else:
                lines.append(f"\n→ Neue Sprache '{lang}' für '{module.label()}'.")
            used = machines_using(self.lib, module.id)
            if used:
                lines.append("Betroffene Maschinen (beim nächsten Erstellen aktuell): " + ", ".join(used))
        else:
            mid = self.id_edit.text().strip()
            if not mid:
                lines.append("\n[ERROR] Bitte Titel/ID angeben.")
                rep.add("error", "ID fehlt")
            elif mid in self.lib.modules:
                lines.append(f"\n[ERROR] ID '{mid}' gibt es schon.")
                rep.add("error", "ID existiert")
        self.report.setPlainText("\n".join(lines))
        self.checked = not rep.errors
        self.import_btn.setEnabled(self.checked)

    def run_import(self) -> None:
        if not self.checked or not self.file:
            return
        lang = self.lang_box.currentData()
        module, kind, title = self._target()
        if module is None:
            module = self.lib.new_module(self.id_edit.text().strip(), {lang: title},
                                         self.slot_box.currentData(), kind)
        rep = import_file(self.lib, self.file, module, lang, note=self.note_edit.text().strip())
        if rep.errors:
            self.report.setPlainText(rep.summary())
            return
        self.imported_module = module.id
        QMessageBox.information(self, "Importiert",
                                f"'{self.file.name}' ist jetzt {module.id}/{lang}.docx "
                                f"(Version {module.version}).")
        self.accept()
