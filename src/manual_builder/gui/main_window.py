"""Main window.

Two pages, chosen in the sidebar:
  * Anleitungen – one card per machine; opening one shows a simple form:
        1. Maschinendaten   2. Ausstattung (one choice per component)
    with a live preview of the table of contents and a single "PDF erstellen" button.
  * Bausteine   – the Word modules the manuals are made of (for whoever maintains the texts).
Changes to a machine are saved automatically.
"""

from __future__ import annotations

import datetime as _dt
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..build import BuildError, build_manual
from ..engines import available_engines
from ..library import Library, Machine, slugify
from ..outline import outline
from .common import open_path
from .import_dialog import ImportDialog
from .module_dialog import ModuleDialog
from .style import ERROR, MUTED, OK, WARN

LANG_LABELS = {"de": "Deutsch", "en": "English", "it": "Italiano", "fr": "Français", "es": "Español"}
MAIN_VARIABLES = ["Maschinentyp", "Kunde", "Seriennummer", "Baujahr"]
ENGINE_NAMES = {"auto": "Automatisch (empfohlen)", "word": "Microsoft Word", "libreoffice": "LibreOffice",
                "none": "Kein PDF – nur Word-Datei"}


# ---------------------------------------------------------------- small helpers

def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def card(name: str = "card") -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName(name)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(12)
    return f, lay


def button(text: str, name: str | None = None, slot=None) -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def scroll(widget: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.Shape.NoFrame)
    s.setWidget(widget)
    return s


def page_header(title: str, subtitle: str, action: QPushButton | None = None) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    col = QVBoxLayout()
    col.setSpacing(4)
    col.addWidget(label(title, "title"))
    col.addWidget(label(subtitle, "subtitle", wrap=True))
    lay.addLayout(col, 1)
    if action:
        lay.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)
    return w


def clear_layout(lay) -> None:
    while lay.count():
        item = lay.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def fmt_date(iso: str) -> str:
    try:
        return _dt.datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


# ---------------------------------------------------------------- page: manuals (home)

class MachineCard(QFrame):
    clicked = Signal()

    def __init__(self, lib: Library, machine: Machine, on_menu):
        super().__init__()
        self.setObjectName("machineCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(118)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 12, 14)
        top = QHBoxLayout()
        top.addWidget(label(machine.name, "cardTitle", wrap=True), 1)
        more = QToolButton()
        more.setObjectName("more")
        more.setText("⋯")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setMenu(on_menu(machine))
        top.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        typ = machine.variables.get("Maschinentyp") or lib.default_variables(machine.language).get("Maschinentyp", "")
        parts = [p for p in (typ, machine.variables.get("Kunde", ""), LANG_LABELS.get(machine.language,
                                                                                     machine.language)) if p]
        lay.addWidget(label(" · ".join(parts), "subtitle"))
        lay.addStretch()
        lay.addWidget(label(f"Zuletzt erstellt: {fmt_date(machine.last_built)}" if machine.last_built
                            else "Noch nicht erstellt", "hint"))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class HomePage(QWidget):
    open_machine = Signal(object)

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 30)
        outer.setSpacing(22)
        outer.addWidget(page_header(
            "Anleitungen",
            "Jede Maschine hat eine eigene Betriebsanleitung. Öffnen Sie eine Maschine, wählen Sie ihre "
            "Ausstattung – das Programm setzt die Anleitung aus den passenden Bausteinen zusammen.",
            button("+  Neue Anleitung", "primary", self.new_machine)))
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(16)
        outer.addWidget(scroll(self.grid_host), 1)

    def refresh(self) -> None:
        clear_layout(self.grid)
        machines = []
        for p in self.win.lib.machines():
            try:
                machines.append(Machine.load(p))
            except Exception:
                continue
        machines.sort(key=lambda m: m.last_built or "", reverse=True)
        cols = 3
        for i, m in enumerate(machines):
            c = MachineCard(self.win.lib, m, self._menu)
            c.clicked.connect(lambda m=m: self.open_machine.emit(m))
            self.grid.addWidget(c, i // cols, i % cols)
        if not machines:
            empty, lay = card()
            lay.addWidget(label("Noch keine Anleitung", "cardTitle"))
            lay.addWidget(label("Klicken Sie auf „Neue Anleitung“, um zu beginnen.", "subtitle"))
            self.grid.addWidget(empty, 0, 0, 1, cols)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)
        self.grid.setRowStretch(len(machines) // cols + 1, 1)

    def _menu(self, machine: Machine) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Öffnen", lambda: self.open_machine.emit(machine))
        menu.addAction("Duplizieren", lambda: self.duplicate(machine))
        menu.addSeparator()
        menu.addAction("Löschen", lambda: self.delete(machine))
        return menu

    def _unique_path(self, name: str) -> Path:
        base = slugify(name)
        path = self.win.lib.machines_dir / f"{base}.yaml"
        i = 2
        while path.exists():
            path = self.win.lib.machines_dir / f"{base}-{i}.yaml"
            i += 1
        return path

    def new_machine(self) -> None:
        name, ok = QInputDialog.getText(self, "Neue Anleitung", "Name der Maschine (z. B. „SKT H10 Müller GmbH“):")
        if not ok or not name.strip():
            return
        lib = self.win.lib
        m = Machine(name=name.strip(), language=lib.default_language)
        # sensible start: required chapters + the first variant of every single-choice component
        for s in lib.slots:
            mods = sorted(lib.modules_in_slot(s.id), key=lambda x: x.label())
            if mods and (s.required or (s.max == 1 and len(mods) == 1)):
                m.modules.append(mods[0].id)
        m.modules = lib.sort_by_slot(m.modules)
        m.save(self._unique_path(name))
        self.open_machine.emit(m)

    def duplicate(self, machine: Machine) -> None:
        name, ok = QInputDialog.getText(self, "Duplizieren", "Name der Kopie:", text=machine.name + " (Kopie)")
        if not ok or not name.strip():
            return
        copy = Machine(name=name.strip(), language=machine.language, modules=list(machine.modules),
                       variables=dict(machine.variables))
        copy.save(self._unique_path(name))
        self.refresh()

    def delete(self, machine: Machine) -> None:
        if QMessageBox.question(self, "Löschen?", f"„{machine.name}“ löschen?\n\n"
                                "Nur die Maschinen-Einstellung wird gelöscht – die Bausteine und bereits "
                                "erstellte PDFs bleiben erhalten.") == QMessageBox.StandardButton.Yes:
            if machine.path:
                machine.path.unlink(missing_ok=True)
            self.refresh()


# ---------------------------------------------------------------- page: edit one manual

class BuildWorker(QObject):
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, lib, machine, out_dir, pdf, engine):
        super().__init__()
        self.args = (lib, machine, out_dir, pdf, engine)

    def run(self):
        lib, machine, out_dir, pdf, engine = self.args
        try:
            self.done.emit(build_manual(lib, machine, out_dir, pdf=pdf, engine=engine, log=self.log.emit))
        except BuildError as e:
            self.failed.emit("\n".join(i.message for i in e.issues))
        except Exception as e:  # pragma: no cover - shown to the user
            self.log.emit(traceback.format_exc())
            self.failed.emit(str(e))


class EditorPage(QWidget):
    back = Signal()

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setObjectName("page")
        self.machine: Machine | None = None
        self.thread: QThread | None = None
        self.var_edits: dict[str, QLineEdit] = {}
        self.slot_widgets: list = []
        self.save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save)
        self.preview_timer = QTimer(self, singleShot=True, interval=150, timeout=self._refresh_preview)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 22, 36, 26)
        outer.setSpacing(14)

        # header: back · name · language
        head = QHBoxLayout()
        head.addWidget(button("←  Alle Anleitungen", "link", self._go_back))
        head.addStretch()
        outer.addLayout(head)
        row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("titleEdit")
        self.name_edit.setToolTip("Name der Anleitung – zum Ändern klicken")
        self.name_edit.textEdited.connect(self._name_changed)
        row.addWidget(self.name_edit, 1)
        row.addSpacing(16)
        row.addWidget(label("Sprache", "slotLabel"))
        self.lang_group = QButtonGroup(self)
        self.lang_group.setExclusive(True)
        self.lang_row = QHBoxLayout()
        self.lang_row.setSpacing(0)
        row.addLayout(self.lang_row)
        outer.addLayout(row)

        body = QHBoxLayout()
        body.setSpacing(20)
        outer.addLayout(body, 1)

        # left column: steps
        left = QWidget()
        self.left_lay = QVBoxLayout(left)
        self.left_lay.setContentsMargins(0, 0, 6, 0)
        self.left_lay.setSpacing(16)

        c1, l1 = card()
        l1.addLayout(self._step_title("1", "Maschinendaten",
                                      "Erscheinen auf der Titelseite und in der Kopfzeile."))
        self.var_form = QFormLayout()
        self.var_form.setHorizontalSpacing(18)
        self.var_form.setVerticalSpacing(10)
        l1.addLayout(self.var_form)
        self.more_btn = button("Weitere Angaben anzeigen", "link", self._toggle_more)
        l1.addWidget(self.more_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.more_host = QWidget()
        self.more_form = QFormLayout(self.more_host)
        self.more_form.setContentsMargins(0, 0, 0, 0)
        self.more_form.setHorizontalSpacing(18)
        self.more_form.setVerticalSpacing(10)
        self.more_host.setVisible(False)
        l1.addWidget(self.more_host)
        self.left_lay.addWidget(c1)

        c2, l2 = card()
        l2.addLayout(self._step_title("2", "Ausstattung",
                                      "Wählen Sie, welche Baugruppen diese Maschine hat. "
                                      "Nur die passenden Kapitel kommen in die Anleitung."))
        self.slot_grid = QGridLayout()
        self.slot_grid.setHorizontalSpacing(18)
        self.slot_grid.setVerticalSpacing(12)
        self.slot_grid.setColumnStretch(1, 1)
        l2.addLayout(self.slot_grid)
        self.left_lay.addWidget(c2)
        self.left_lay.addStretch()
        body.addWidget(scroll(left), 3)

        # right column: preview + build
        right = QVBoxLayout()
        right.setSpacing(16)
        c3, l3 = card()
        l3.addLayout(self._step_title("3", "Inhalt der Anleitung",
                                      "Vorschau des Inhaltsverzeichnisses. Kapitel aufklappen für Details."))
        self.preview = QTreeWidget()
        self.preview.setObjectName("preview")
        self.preview.setHeaderHidden(True)
        self.preview.setIndentation(14)
        self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        l3.addWidget(self.preview, 1)
        self.issue_label = label("", None, wrap=True)
        l3.addWidget(self.issue_label)
        right.addWidget(c3, 1)

        c4, l4 = card()
        self.build_btn = button("PDF erstellen", "primary", self.build)
        self.build_btn.setMinimumHeight(46)
        l4.addWidget(self.build_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        l4.addWidget(self.progress)
        self.status = label("", "hint", wrap=True)
        l4.addWidget(self.status)
        self.result_row = QHBoxLayout()
        self.open_pdf_btn = button("PDF öffnen", None, lambda: self._open("pdf"))
        self.open_doc_btn = button("Word-Datei öffnen", None, lambda: self._open("docx"))
        self.open_dir_btn = button("Ordner", None, lambda: self._open("dir"))
        for b in (self.open_pdf_btn, self.open_doc_btn, self.open_dir_btn):
            b.setVisible(False)
            self.result_row.addWidget(b)
        self.result_row.addStretch()
        l4.addLayout(self.result_row)
        self.details_btn = button("Protokoll anzeigen", "link", self._toggle_log)
        self.details_btn.setVisible(False)
        l4.addWidget(self.details_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        self.log.setMaximumHeight(160)
        l4.addWidget(self.log)
        right.addWidget(c4)
        right.setContentsMargins(0, 0, 0, 0)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(380)
        body.addWidget(rw, 2)
        self.last_result = None

    def _step_title(self, num: str, title: str, hint: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(4)
        row = QHBoxLayout()
        n = label(num, "stepNumber")
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(n)
        row.addWidget(label(title, "sectionTitle"))
        row.addStretch()
        col.addLayout(row)
        col.addWidget(label(hint, "hint", wrap=True))
        return col

    # ---------------------------------------------------------------- load
    def load(self, machine: Machine) -> None:
        self.machine = machine
        self.last_result = None
        self.name_edit.setText(machine.name)
        self._build_lang_buttons()
        self._build_vars()
        self._build_slots()
        self.status.setText("")
        self.log.clear()
        self.log.setVisible(False)
        self.details_btn.setVisible(False)
        for b in (self.open_pdf_btn, self.open_doc_btn, self.open_dir_btn):
            b.setVisible(False)
        if machine.last_built:
            self.status.setText(f"Zuletzt erstellt am {fmt_date(machine.last_built)}.")
        self._refresh_preview()

    def _build_lang_buttons(self) -> None:
        clear_layout(self.lang_row)
        for b in self.lang_group.buttons():
            self.lang_group.removeButton(b)
        langs = self.win.lib.languages
        for i, code in enumerate(langs):
            name = "segFirst" if i == 0 else ("segLast" if i == len(langs) - 1 else "seg")
            b = button(LANG_LABELS.get(code, code), name)
            b.setCheckable(True)
            b.setChecked(code == self.machine.language)
            b.clicked.connect(lambda _=False, c=code: self._lang_changed(c))
            self.lang_group.addButton(b)
            self.lang_row.addWidget(b)

    def _build_vars(self) -> None:
        for form in (self.var_form, self.more_form):
            while form.rowCount():
                form.removeRow(0)
        self.var_edits = {}
        lib = self.win.lib
        defaults = lib.default_variables(self.machine.language)
        labels = {v["key"]: v.get("label", v["key"]) for v in lib.variables}
        keys = [v["key"] for v in lib.variables] + [k for k in self.machine.variables
                                                     if k not in labels]
        for key in keys:
            e = QLineEdit(self.machine.variables.get(key, ""))
            e.setPlaceholderText(defaults.get(key, "") or "")
            e.textEdited.connect(self._vars_changed)
            self.var_edits[key] = e
            form = self.var_form if key in MAIN_VARIABLES else self.more_form
            form.addRow(labels.get(key, key).split(" (")[0], e)
        add = button("+ eigenes Feld", "link", self._add_variable)
        self.more_form.addRow("", add)
        self.more_form.addRow(label("Leere Felder verwenden den grauen Vorschlag. In den Word-Bausteinen "
                                    "werden die Felder als {{Name}} eingesetzt, z. B. {{Maschinentyp}}.",
                                    "hint", wrap=True))

    def _toggle_more(self) -> None:
        vis = not self.more_host.isVisible()
        self.more_host.setVisible(vis)
        self.more_btn.setText("Weitere Angaben ausblenden" if vis else "Weitere Angaben anzeigen")

    def _build_slots(self) -> None:
        clear_layout(self.slot_grid)
        self.slot_widgets = []
        lib = self.win.lib
        lang = self.machine.language
        chosen = set(self.machine.modules)
        row = 0
        for slot in lib.slots:
            mods = sorted(lib.modules_in_slot(slot.id), key=lambda m: m.label(lang))
            if not mods:
                continue
            name = label(slot.label("de"), "slotLabel")
            self.slot_grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignTop)
            if slot.max is None:                          # options: tick any number
                box = QWidget()
                bl = QGridLayout(box)
                bl.setContentsMargins(0, 0, 0, 0)
                bl.setHorizontalSpacing(16)
                checks = []
                for i, m in enumerate(mods):
                    cb = QCheckBox(m.label(lang).removeprefix("Option "))
                    cb.setChecked(m.id in chosen)
                    cb.setToolTip(m.description or m.label(lang))
                    cb.toggled.connect(self._selection_changed)
                    bl.addWidget(cb, i // 2, i % 2)
                    checks.append((cb, m.id))
                self.slot_grid.addWidget(box, row, 1)
                self.slot_widgets.append(("checks", slot.id, checks))
            elif slot.required and len(mods) == 1:        # always included
                self.slot_grid.addWidget(label(f"✓  {mods[0].label(lang)}  (immer enthalten)", "fixed"), row, 1)
                self.slot_widgets.append(("fixed", slot.id, mods[0].id))
            elif len(mods) == 1:                          # yes / no
                cb = QCheckBox(mods[0].label(lang))
                cb.setChecked(mods[0].id in chosen)
                cb.toggled.connect(self._selection_changed)
                self.slot_grid.addWidget(cb, row, 1)
                self.slot_widgets.append(("check", slot.id, (cb, mods[0].id)))
            else:                                         # choose one variant
                combo = QComboBox()
                if not slot.required:
                    combo.addItem("– nicht vorhanden –", "")
                for m in mods:
                    combo.addItem(m.label(lang), m.id)
                current = next((m.id for m in mods if m.id in chosen), "")
                combo.setCurrentIndex(max(0, combo.findData(current)))
                combo.currentIndexChanged.connect(self._selection_changed)
                combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.slot_grid.addWidget(combo, row, 1)
                self.slot_widgets.append(("combo", slot.id, combo))
            row += 1

    # ---------------------------------------------------------------- changes
    def _selection_changed(self, *_):
        mods = []
        for kind, _slot, w in self.slot_widgets:
            if kind == "fixed":
                mods.append(w)
            elif kind == "check":
                if w[0].isChecked():
                    mods.append(w[1])
            elif kind == "checks":
                mods += [mid for cb, mid in w if cb.isChecked()]
            elif kind == "combo" and w.currentData():
                mods.append(w.currentData())
        self.machine.modules = self.win.lib.sort_by_slot(mods)
        self._changed()

    def _vars_changed(self, *_):
        self.machine.variables = {k: e.text() for k, e in self.var_edits.items() if e.text()}
        self._changed(preview=False)

    def _add_variable(self) -> None:
        key, ok = QInputDialog.getText(self, "Eigenes Feld", "Name des Feldes (ohne Klammern), z. B. Spannung:")
        if ok and key.strip():
            self.machine.variables.setdefault(key.strip(), "")
            self._build_vars()
            self.more_host.setVisible(True)
            self._changed(preview=False)

    def _name_changed(self, text: str) -> None:
        self.machine.name = text.strip() or "Unbenannt"
        self._changed(preview=False)

    def _lang_changed(self, code: str) -> None:
        self.machine.language = code
        self._build_vars()
        self._build_slots()
        self._changed()

    def _changed(self, preview: bool = True) -> None:
        self.save_timer.start()
        if preview:
            self.preview_timer.start()

    def _save(self) -> None:
        if self.machine and self.machine.path:
            self.machine.save()

    def _go_back(self) -> None:
        self.save_timer.stop()
        self._save()
        self.back.emit()

    # ---------------------------------------------------------------- preview
    def _refresh_preview(self) -> None:
        lib = self.win.lib
        self.preview.clear()
        try:
            entries = outline(lib, self.machine)
        except Exception as e:  # pragma: no cover
            entries = []
            self.issue_label.setText(f"Vorschau nicht möglich: {e}")
        for e in entries:
            it = QTreeWidgetItem([f"{e.number}   {e.text}"])
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
            for c in e.children:
                it.addChild(QTreeWidgetItem([f"{c.number}   {c.text}"]))
            self.preview.addTopLevelItem(it)
        issues = [i for i in lib.validate(self.machine) if i.level != "info"
                  and "Variable" not in i.message]
        errors = [i for i in issues if i.level == "error"]
        lines = []
        for i in issues:
            color = ERROR if i.level == "error" else WARN
            lines.append(f"<span style='color:{color}'>{'●' if i.level == 'error' else '▲'}</span> {i.message}")
        if not issues:
            lines.append(f"<span style='color:{OK}'>✓</span> <span style='color:{MUTED}'>"
                         f"{len(entries)} Kapitel – bereit zum Erstellen</span>")
        self.issue_label.setText("<br>".join(lines))
        self.build_btn.setEnabled(not errors and self.thread is None)

    # ---------------------------------------------------------------- build
    def _toggle_log(self) -> None:
        self.log.setVisible(not self.log.isVisible())
        self.details_btn.setText("Protokoll ausblenden" if self.log.isVisible() else "Protokoll anzeigen")

    def build(self) -> None:
        if self.thread is not None or self.machine is None:
            return
        self._save()
        settings = self.win.settings
        out_dir = Path(settings.value("output_dir", str(Path.home() / "Documents" / "Anleitungen"))).expanduser()
        engine = settings.value("engine", "auto")
        self.log.clear()
        for b in (self.open_pdf_btn, self.open_doc_btn, self.open_dir_btn):
            b.setVisible(False)
        self.build_btn.setEnabled(False)
        self.build_btn.setText("Wird erstellt …")
        self.progress.setVisible(True)
        self.status.setText("Bausteine werden zusammengesetzt …")
        m = self.machine
        snapshot = Machine(name=m.name, language=m.language, modules=list(m.modules), variables=dict(m.variables))
        self.thread = QThread()
        self.worker = BuildWorker(self.win.lib, snapshot, out_dir, engine != "none", engine)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._log)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.thread.start()

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)
        if text.startswith("+ "):
            self.status.setText(f"Füge ein: {text[2:]}")
        elif "Inhaltsverzeichnis" in text:
            self.status.setText("Inhaltsverzeichnis und Seitenzahlen werden berechnet …")

    def _finish(self) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait()
        self.thread = None
        self.progress.setVisible(False)
        self.build_btn.setText("PDF erstellen")
        self.details_btn.setVisible(True)
        self._refresh_preview()

    def _done(self, res) -> None:
        self._finish()
        self.last_result = res
        self.machine.last_built = _dt.datetime.now().isoformat(timespec="minutes")
        self._save()
        for i in res.issues:
            self.log.appendPlainText(str(i))
        warn = [i for i in res.issues if i.level == "warning"]
        name = res.pdf.name if res.pdf else res.docx.name
        self.status.setText(f"<span style='color:{OK}'>✓ Fertig:</span> {name}"
                            + (f"<br><span style='color:{MUTED}'>{len(warn)} Hinweise im Protokoll</span>"
                               if warn else ""))
        self.open_pdf_btn.setVisible(res.pdf is not None)
        self.open_doc_btn.setVisible(True)
        self.open_dir_btn.setVisible(True)
        if res.pdf:
            open_path(res.pdf)

    def _failed(self, msg: str) -> None:
        self._finish()
        self.status.setText(f"<span style='color:{ERROR}'>Fehler:</span> {msg}")
        self.log.setVisible(True)

    def _open(self, what: str) -> None:
        r = self.last_result
        if not r:
            return
        open_path(r.pdf if what == "pdf" else r.docx if what == "docx" else r.docx.parent)


# ---------------------------------------------------------------- page: building blocks

class ModulesPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 30)
        outer.setSpacing(22)
        outer.addWidget(page_header(
            "Bausteine",
            "Aus diesen Bausteinen werden die Anleitungen zusammengesetzt. Jeder Baustein ist eine "
            "Word-Datei (je Sprache) plus Tabellen für Wartung, Ersatzteile und Störungen. "
            "Ändern Sie hier einen Baustein, ist er beim nächsten Erstellen in allen Anleitungen aktuell.",
            button("+  Word-Datei hinzufügen", "primary", lambda: self.import_file())))
        self.host = QWidget()
        self.list_lay = QVBoxLayout(self.host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(8)
        outer.addWidget(scroll(self.host), 1)

    def refresh(self) -> None:
        clear_layout(self.list_lay)
        lib = self.win.lib
        lib.reload_modules()
        for slot in lib.slots:
            mods = sorted(lib.modules_in_slot(slot.id), key=lambda m: m.label())
            if not mods:
                continue
            h = label(slot.label("de"), "sectionTitle")
            h.setContentsMargins(4, 10, 0, 2)
            self.list_lay.addWidget(h)
            for m in mods:
                self.list_lay.addWidget(self._row(m))
        self.list_lay.addStretch()

    def _row(self, m) -> QFrame:
        lib = self.win.lib
        f = QFrame()
        f.setObjectName("moduleRow")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(16, 10, 10, 10)
        col = QVBoxLayout()
        col.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(label(m.label(), "cardTitle"))
        have = m.languages()
        for code in lib.languages:
            if code in have:
                top.addWidget(label(code.upper(), "chip"))
            elif have:
                c = label(code.upper() + " fehlt", "chipMissing")
                top.addWidget(c)
        top.addStretch()
        col.addLayout(top)
        n = {s: len(m.entries(s)) for s in ("maintenance", "spare_parts", "faults")}
        bits = []
        if not have:
            bits.append("nur Tabellen, noch kein Text")
        for key, word in (("faults", "Störungen"), ("maintenance", "Wartungspunkte"), ("spare_parts", "Ersatzteile")):
            if n[key]:
                bits.append(f"{n[key]} {word}")
        last = m.history[-1] if m.history else {}
        bits.append(f"Stand {_dt.date.fromisoformat(last['date']).strftime('%d.%m.%Y')}" if last.get("date") else "")
        col.addWidget(label(" · ".join(b for b in bits if b), "hint"))
        lay.addLayout(col, 1)
        if have:
            p = m.docx_path("de") if "de" in have else m.docx_path(have[0])
            lay.addWidget(button("In Word öffnen", None, lambda _=False, p=p: open_path(p)))
        lay.addWidget(button("Bearbeiten", None, lambda _=False, mid=m.id: self.edit(mid)))
        more = QToolButton()
        more.setObjectName("more")
        more.setText("⋯")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Neue Fassung oder Übersetzung hochladen …", lambda mid=m.id: self.import_file(mid))
        menu.addAction("Ordner öffnen", lambda p=m.path: open_path(p))
        more.setMenu(menu)
        lay.addWidget(more)
        return f

    def edit(self, mid: str) -> None:
        dlg = ModuleDialog(self.win.lib, self.win.lib.modules[mid], self)
        dlg.exec()
        self.refresh()

    def import_file(self, module_id: str | None = None) -> None:
        dlg = ImportDialog(self.win.lib, self, module_id=module_id)
        if dlg.exec():
            self.refresh()


# ---------------------------------------------------------------- settings

class SettingsDialog(QDialog):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)
        lay.addWidget(label("Einstellungen", "title"))
        form = QFormLayout()
        form.setVerticalSpacing(14)
        form.setHorizontalSpacing(16)

        self.lib_edit = QLineEdit(str(win.lib.root))
        self.lib_edit.setReadOnly(True)
        r1 = QHBoxLayout()
        r1.addWidget(self.lib_edit)
        r1.addWidget(button("Ändern …", None, self._choose_lib))
        form.addRow("Bausteine-Ordner:", r1)
        form.addRow("", label("Hier liegen alle Bausteine und Maschinen. Für mehrere Benutzer auf ein "
                              "Netzlaufwerk legen.", "hint", wrap=True))

        self.out_edit = QLineEdit(win.settings.value("output_dir", str(Path.home() / "Documents" / "Anleitungen")))
        r2 = QHBoxLayout()
        r2.addWidget(self.out_edit)
        r2.addWidget(button("Ändern …", None, self._choose_out))
        form.addRow("Fertige Anleitungen:", r2)

        self.engine = QComboBox()
        for e in ["auto"] + available_engines():
            self.engine.addItem(ENGINE_NAMES[e], e)
        self.engine.setCurrentIndex(max(0, self.engine.findData(win.settings.value("engine", "auto"))))
        form.addRow("Seitenzahlen & PDF mit:", self.engine)
        form.addRow("", label("Für Inhaltsverzeichnis, Seitenzahlen und PDF wird Microsoft Word oder "
                              "LibreOffice benötigt. „Automatisch“ nimmt Word, falls vorhanden.",
                              "hint", wrap=True))
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.new_lib: Library | None = None

    def _choose_lib(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Bausteine-Ordner wählen", self.lib_edit.text())
        if not d:
            return
        try:
            self.new_lib = Library(Path(d))
            self.lib_edit.setText(d)
        except FileNotFoundError:
            QMessageBox.warning(self, "Kein Bausteine-Ordner",
                                "In diesem Ordner gibt es keine library.yaml.")

    def _choose_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Ordner für fertige Anleitungen", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _ok(self) -> None:
        s = self.win.settings
        s.setValue("output_dir", self.out_edit.text())
        s.setValue("engine", self.engine.currentData())
        if self.new_lib is not None:
            s.setValue("library", str(self.new_lib.root))
            self.win.set_library(self.new_lib)
        self.accept()


# ---------------------------------------------------------------- window

class MainWindow(QMainWindow):
    def __init__(self, lib: Library):
        super().__init__()
        self.settings = QSettings("ProfilClip", "ManualBuilder")
        self.lib = lib
        self.setWindowTitle("Anleitungs-Baukasten")
        self.resize(1320, 840)
        self.setMinimumSize(1050, 680)

        root = QWidget()
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 22, 14, 16)
        sl.setSpacing(4)
        sl.addWidget(label("Anleitungs-Baukasten", "appName"))
        sl.addWidget(label("Profil-Clip Betriebsanleitungen", "appSub"))
        sl.addSpacing(22)
        self.nav = QButtonGroup(self)
        self.nav_manuals = self._nav_button("Anleitungen", sl)
        self.nav_modules = self._nav_button("Bausteine", sl)
        sl.addStretch()
        settings_btn = button("Einstellungen", "navButton", lambda: SettingsDialog(self).exec())
        sl.addWidget(settings_btn)
        rl.addWidget(side)

        self.stack = QStackedWidget()
        self.home = HomePage(self)
        self.editor = EditorPage(self)
        self.modules = ModulesPage(self)
        for p in (self.home, self.editor, self.modules):
            self.stack.addWidget(p)
        rl.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.nav_manuals.clicked.connect(self.show_home)
        self.nav_modules.clicked.connect(self.show_modules)
        self.home.open_machine.connect(self.open_machine)
        self.editor.back.connect(self.show_home)
        self.show_home()

    def _nav_button(self, text: str, lay) -> QPushButton:
        b = button(text, "navButton")
        b.setCheckable(True)
        self.nav.addButton(b)
        lay.addWidget(b)
        return b

    def set_library(self, lib: Library) -> None:
        self.lib = lib
        self.show_home()

    def show_home(self) -> None:
        self.nav_manuals.setChecked(True)
        self.home.refresh()
        self.stack.setCurrentWidget(self.home)

    def show_modules(self) -> None:
        if self.stack.currentWidget() is self.editor:
            self.editor._save()
        self.nav_modules.setChecked(True)
        self.modules.refresh()
        self.stack.setCurrentWidget(self.modules)

    def open_machine(self, machine: Machine) -> None:
        self.lib.reload_modules()
        self.nav_manuals.setChecked(True)
        self.editor.load(machine)
        self.stack.setCurrentWidget(self.editor)

    def closeEvent(self, e):
        if self.editor.thread is not None:
            QMessageBox.information(self, "Bitte warten", "Die Anleitung wird gerade erstellt.")
            e.ignore()
            return
        self.editor.save_timer.stop()
        if self.stack.currentWidget() is self.editor:
            self.editor._save()
        e.accept()
