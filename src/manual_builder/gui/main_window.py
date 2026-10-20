"""Main window: library (left) → manual (middle) → machine data & build (right)."""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QDrag, QKeySequence
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDockWidget,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSplitter, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ..build import BuildError, build_manual
from ..engines import available_engines
from ..library import Library, Machine, slugify
from .common import ISSUE_ICONS, MODULE_MIME, lang_name, open_path, std_icon
from .import_dialog import ImportDialog
from .module_dialog import ModuleDialog

ENGINE_NAMES = {"auto": "Automatisch", "word": "Microsoft Word", "libreoffice": "LibreOffice",
                "none": "Kein PDF (nur Word-Datei)"}


# ---------------------------------------------------------------- widgets

class LibraryTree(QTreeWidget):
    """Modules grouped by slot; items can be dragged into the manual list."""

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(["Modul", "Sprachen", "Daten"])
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setColumnWidth(0, 230)
        self.setColumnWidth(1, 70)

    def startDrag(self, actions):
        item = self.currentItem()
        mid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not mid:
            return
        mime = QMimeData()
        mime.setData(MODULE_MIME, mid.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class ManualList(QListWidget):
    """Ordered module list of the current machine. Accepts drops from the library."""
    dropped_module = Signal(str, int)
    order_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MODULE_MIME) or e.source() is self:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MODULE_MIME) or e.source() is self:
            e.acceptProposedAction()

    def dropEvent(self, e):
        if e.mimeData().hasFormat(MODULE_MIME):
            mid = bytes(e.mimeData().data(MODULE_MIME)).decode()
            row = self.indexAt(e.position().toPoint()).row()
            self.dropped_module.emit(mid, row if row >= 0 else self.count())
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
            self.order_changed.emit()


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
            res = build_manual(lib, machine, out_dir, pdf=pdf, engine=engine, log=self.log.emit)
            self.done.emit(res)
        except BuildError as e:
            self.failed.emit("Die Anleitung kann nicht erstellt werden:\n\n" + str(e))
        except Exception as e:  # pragma: no cover - shown to the user
            self.log.emit(traceback.format_exc())
            self.failed.emit(f"Fehler beim Erstellen: {e}")


# ---------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    def __init__(self, lib: Library):
        super().__init__()
        self.settings = QSettings("ProfilClip", "ManualBuilder")
        self.lib = lib
        self.machine = Machine(name="Neue Maschine", language=lib.default_language)
        self.dirty = False
        self.thread: QThread | None = None
        self.var_edits: dict[str, QLineEdit] = {}
        self.resize(1400, 860)
        self._build_ui()
        self.reload_library()
        last = self.settings.value("last_machine", "")
        if last and Path(last).exists() and Path(last).is_relative_to(self.lib.root):
            self.load_machine(Path(last))
        else:
            machines = self.lib.machines()
            if machines:
                self.load_machine(machines[0])
            else:
                self.show_machine()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        tb = QToolBar("Aktionen")
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        def act(text, icon, slot, shortcut=None):
            a = QAction(std_icon(icon), text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            tb.addAction(a)
            return a

        act("Neue Maschine", "SP_FileIcon", self.new_machine, QKeySequence.StandardKey.New)
        act("Speichern", "SP_DialogSaveButton", self.save_machine, QKeySequence.StandardKey.Save)
        act("Speichern unter …", "SP_DriveFDIcon", self.save_machine_as)
        act("Löschen", "SP_TrashIcon", self.delete_machine)
        tb.addSeparator()
        act("Word-Datei importieren …", "SP_ArrowDown", lambda: self.import_file())
        act("Bibliotheksordner", "SP_DirOpenIcon", lambda: open_path(self.lib.root))
        act("Bibliothek wechseln …", "SP_DirIcon", self.change_library)
        tb.addSeparator()
        self.build_action = act("Anleitung erstellen", "SP_MediaPlay", self.build,
                                QKeySequence("Ctrl+B"))

        # left: library
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Bibliothek</b> – Module in die Anleitung ziehen oder doppelklicken"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Suchen …")
        self.filter_edit.textChanged.connect(self.reload_library)
        ll.addWidget(self.filter_edit)
        self.tree = LibraryTree()
        self.tree.itemDoubleClicked.connect(self._tree_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        ll.addWidget(self.tree)
        self.module_info = QLabel()
        self.module_info.setWordWrap(True)
        self.module_info.setStyleSheet("color: palette(mid);")
        self.tree.currentItemChanged.connect(self._show_module_info)
        ll.addWidget(self.module_info)

        # middle: machine + module list
        mid = QWidget()
        ml = QVBoxLayout(mid)
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Maschine:</b>"))
        self.machine_box = QComboBox()
        self.machine_box.activated.connect(self._machine_selected)
        row.addWidget(self.machine_box, 1)
        ml.addLayout(row)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._name_changed)
        self.lang_box = QComboBox()
        for code in self.lib.languages:
            self.lang_box.addItem(lang_name(code), code)
        self.lang_box.activated.connect(self._lang_changed)
        form.addRow("Name:", self.name_edit)
        form.addRow("Sprache:", self.lang_box)
        ml.addLayout(form)
        ml.addWidget(QLabel("<b>Inhalt der Anleitung</b> (Reihenfolge per Ziehen ändern)"))
        self.list = ManualList()
        self.list.dropped_module.connect(self.add_module)
        self.list.order_changed.connect(self._list_reordered)
        self.list.itemDoubleClicked.connect(lambda it: self.edit_module(it.data(Qt.ItemDataRole.UserRole)))
        ml.addWidget(self.list, 3)
        brow = QHBoxLayout()
        for text, slot in (("▲", lambda: self.move_selected(-1)), ("▼", lambda: self.move_selected(1)),
                           ("Entfernen", self.remove_selected),
                           ("Standard-Reihenfolge", self.sort_standard)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            brow.addWidget(b)
        brow.addStretch()
        ml.addLayout(brow)
        ml.addWidget(QLabel("<b>Prüfung</b>"))
        self.issue_list = QListWidget()
        ml.addWidget(self.issue_list, 1)

        # right: variables + output
        right = QWidget()
        rl = QVBoxLayout(right)
        vbox = QGroupBox("Maschinendaten (Platzhalter)")
        self.var_form = QFormLayout(vbox)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(vbox)
        rl.addWidget(scroll, 1)
        obox = QGroupBox("Ausgabe")
        of = QFormLayout(obox)
        orow = QHBoxLayout()
        self.out_edit = QLineEdit(self.settings.value("output_dir", str(Path.home() / "Documents" / "Anleitungen")))
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(self._choose_out)
        orow.addWidget(self.out_edit)
        orow.addWidget(b)
        of.addRow("Ordner:", orow)
        self.pdf_check = QCheckBox("PDF erzeugen")
        self.pdf_check.setChecked(self.settings.value("pdf", "true") == "true")
        of.addRow("", self.pdf_check)
        self.engine_box = QComboBox()
        for e in ["auto"] + available_engines():
            self.engine_box.addItem(ENGINE_NAMES[e], e)
        of.addRow("Seitenlayout mit:", self.engine_box)
        rl.addWidget(obox)
        self.build_btn = QPushButton("Anleitung erstellen")
        self.build_btn.setMinimumHeight(44)
        self.build_btn.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.build_btn.clicked.connect(self.build)
        rl.addWidget(self.build_btn)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(mid)
        split.addWidget(right)
        split.setSizes([420, 560, 420])
        self.setCentralWidget(split)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        dock = QDockWidget("Protokoll", self)
        dock.setWidget(self.log)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [140], Qt.Orientation.Vertical)

    # ---------------------------------------------------------------- library
    def reload_library(self) -> None:
        self.lib.reload_modules()
        lang = self.machine.language
        flt = self.filter_edit.text().strip().lower()
        self.tree.clear()
        for slot in self.lib.slots:
            parent = QTreeWidgetItem([slot.label("de")])
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for m in sorted(self.lib.modules_in_slot(slot.id), key=lambda m: m.label()):
                if flt and flt not in (m.label(lang) + " " + m.id).lower():
                    continue
                n = {s: len(m.entries(s)) for s in ("maintenance", "spare_parts", "faults")}
                data = " ".join(f"{k}{v}" for k, v in (("W", n["maintenance"]), ("E", n["spare_parts"]),
                                                        ("S", n["faults"])) if v)
                it = QTreeWidgetItem([m.label(lang), ",".join(m.languages()) or "–", data])
                it.setData(0, Qt.ItemDataRole.UserRole, m.id)
                it.setToolTip(0, f"{m.id} · Version {m.version}\n{m.description}")
                it.setToolTip(2, "W = Wartung, E = Ersatzteile, S = Störungen")
                if m.has_text() and lang not in m.languages():
                    it.setIcon(1, std_icon("SP_MessageBoxWarning"))
                parent.addChild(it)
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)
        orphans = [m for m in self.lib.modules.values() if self.lib.slot(m.slot) is None]
        if orphans:
            parent = QTreeWidgetItem(["(ohne Platz)"])
            for m in orphans:
                it = QTreeWidgetItem([m.label(lang), ",".join(m.languages()), ""])
                it.setData(0, Qt.ItemDataRole.UserRole, m.id)
                parent.addChild(it)
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)

    def _show_module_info(self, item, _prev=None) -> None:
        mid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        m = self.lib.modules.get(mid) if mid else None
        if not m:
            self.module_info.setText("")
            return
        last = m.history[-1] if m.history else {}
        self.module_info.setText(f"{m.id} · Version {m.version} · zuletzt {last.get('date', '?')}"
                                 f"{(' – ' + m.description) if m.description else ''}")

    def _tree_double_clicked(self, item, _col) -> None:
        mid = item.data(0, Qt.ItemDataRole.UserRole)
        if mid:
            self.add_module(mid, self.list.count())

    def _tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        mid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        menu = QMenu(self)
        if mid:
            m = self.lib.modules[mid]
            menu.addAction("Zur Anleitung hinzufügen", lambda: self.add_module(mid, self.list.count()))
            menu.addAction("Bearbeiten (Titel, Wartung, Störungen …)", lambda: self.edit_module(mid))
            menu.addAction("Neue Fassung / Sprache importieren …", lambda: self.import_file(mid))
            lang = self.machine.language
            p = m.docx_path(lang) if m.docx_path(lang).exists() else (
                m.docx_path(m.languages()[0]) if m.languages() else None)
            if p:
                menu.addAction(f"In Word öffnen ({p.stem})", lambda: open_path(p))
            menu.addAction("Ordner öffnen", lambda: open_path(m.path))
            menu.addSeparator()
        menu.addAction("Neues Modul aus Word-Datei …", lambda: self.import_file())
        menu.addAction("Neues Modul ohne Text (nur Tabellen) …", self.new_data_module)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def edit_module(self, mid: str) -> None:
        m = self.lib.modules.get(mid)
        if not m:
            return
        dlg = ModuleDialog(self.lib, m, self, lang=self.machine.language)
        if dlg.exec() or dlg.changed_other:
            self.reload_library()
            self.show_machine(keep_vars=True)

    def import_file(self, module_id: str | None = None) -> None:
        dlg = ImportDialog(self.lib, self, module_id=module_id)
        if dlg.exec():
            self.reload_library()
            self.show_machine(keep_vars=True)
            self.log_line(f"Importiert: {dlg.imported_module}")

    def new_data_module(self) -> None:
        title, ok = QInputDialog.getText(self, "Neues Modul", "Titel (z. B. „Option Etikettierer“):")
        if not ok or not title.strip():
            return
        slots = [s.label("de") for s in self.lib.slots]
        idx = next((i for i, s in enumerate(self.lib.slots) if s.id == "options"), 0)
        slot, ok = QInputDialog.getItem(self, "Neues Modul", "Platz:", slots, idx, False)
        if not ok:
            return
        mid = slugify(title)
        if mid in self.lib.modules:
            QMessageBox.warning(self, "Gibt es schon", f"ID '{mid}' existiert bereits.")
            return
        self.lib.new_module(mid, {"de": title.strip()}, self.lib.slots[slots.index(slot)].id)
        self.reload_library()
        self.edit_module(mid)

    def change_library(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Bibliotheksordner wählen", str(self.lib.root))
        if not d:
            return
        try:
            lib = Library(Path(d))
        except FileNotFoundError as e:
            QMessageBox.warning(self, "Keine Bibliothek", str(e))
            return
        if not self.maybe_save():
            return
        self.lib = lib
        self.settings.setValue("library", str(lib.root))
        self.new_machine(ask=False)
        self.reload_library()

    # ---------------------------------------------------------------- machine
    def refresh_machine_box(self) -> None:
        self.machine_box.blockSignals(True)
        self.machine_box.clear()
        for p in self.lib.machines():
            try:
                name = Machine.load(p).name
            except Exception:
                name = p.stem
            self.machine_box.addItem(name, str(p))
        if self.machine.path is None:
            self.machine_box.addItem(f"{self.machine.name} (nicht gespeichert)", "")
            self.machine_box.setCurrentIndex(self.machine_box.count() - 1)
        else:
            self.machine_box.setCurrentIndex(max(0, self.machine_box.findData(str(self.machine.path))))
        self.machine_box.blockSignals(False)

    def show_machine(self, keep_vars: bool = False) -> None:
        if keep_vars:
            self._read_vars()
        m = self.machine
        self.name_edit.setText(m.name)
        self.lang_box.setCurrentIndex(max(0, self.lang_box.findData(m.language)))
        self.list.clear()
        for mid in m.modules:
            mod = self.lib.modules.get(mid)
            slot = self.lib.slot(mod.slot).label("de") if mod and self.lib.slot(mod.slot) else "?"
            text = f"{mod.label(m.language)}" if mod else f"⚠ {mid} (fehlt)"
            it = QListWidgetItem(f"{text}    · {slot}")
            it.setData(Qt.ItemDataRole.UserRole, mid)
            if mod and mod.has_text() and m.language not in mod.languages():
                it.setIcon(std_icon("SP_MessageBoxWarning"))
                it.setToolTip(f"Kein Text auf {m.language} – es wird {self.lib.default_language} verwendet")
            self.list.addItem(it)
        self._build_var_form()
        self.refresh_machine_box()
        self.update_issues()
        self._update_title()

    def _build_var_form(self) -> None:
        while self.var_form.rowCount():
            self.var_form.removeRow(0)
        self.var_edits = {}
        defaults = self.lib.default_variables(self.machine.language)
        keys = [v["key"] for v in self.lib.variables]
        keys += [k for k in self.machine.variables if k not in keys]
        labels = {v["key"]: v.get("label", v["key"]) for v in self.lib.variables}
        for key in keys:
            e = QLineEdit(self.machine.variables.get(key, ""))
            e.setPlaceholderText(defaults.get(key, "") or "")
            e.textEdited.connect(self._mark_dirty)
            self.var_form.addRow(labels.get(key, key) + ":", e)
            self.var_edits[key] = e
        b = QPushButton("+ weiterer Platzhalter")
        b.clicked.connect(self._add_variable)
        self.var_form.addRow("", b)
        hint = QLabel("Leere Felder nutzen den grauen Standardwert. "
                      "Im Word-Text schreiben Sie z. B. {{Maschinentyp}}.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        self.var_form.addRow(hint)

    def _add_variable(self) -> None:
        key, ok = QInputDialog.getText(self, "Platzhalter", "Name (ohne Klammern), z. B. Spannung:")
        if ok and key.strip():
            self._read_vars()
            self.machine.variables.setdefault(key.strip(), "")
            self._build_var_form()
            self._mark_dirty()

    def _read_vars(self) -> None:
        self.machine.variables = {k: e.text() for k, e in self.var_edits.items()
                                  if e.text() != "" or k in self.machine.variables}

    def _read_list(self) -> None:
        self.machine.modules = [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                                for i in range(self.list.count())]

    def update_issues(self) -> None:
        self.issue_list.clear()
        issues = self.lib.validate(self.machine)
        if not issues:
            it = QListWidgetItem("Alles in Ordnung")
            it.setIcon(std_icon("SP_DialogApplyButton"))
            self.issue_list.addItem(it)
        for i in issues:
            it = QListWidgetItem(i.message)
            it.setIcon(std_icon(ISSUE_ICONS[i.level]))
            self.issue_list.addItem(it)
        has_errors = any(i.level == "error" for i in issues)
        self.build_btn.setEnabled(not has_errors and self.thread is None)
        self.build_action.setEnabled(not has_errors and self.thread is None)

    def _mark_dirty(self, *_):
        self.dirty = True
        self._update_title()

    def _update_title(self) -> None:
        self.setWindowTitle(f"Manual Builder – {self.machine.name}{' *' if self.dirty else ''}"
                            f"   [{self.lib.root}]")

    def _name_changed(self, text: str) -> None:
        self.machine.name = text.strip() or "Unbenannt"
        self._mark_dirty()

    def _lang_changed(self) -> None:
        self._read_vars()
        self.machine.language = self.lang_box.currentData()
        self._mark_dirty()
        self.reload_library()
        self.show_machine()

    def add_module(self, mid: str, row: int) -> None:
        self._read_list()
        if mid in self.machine.modules:
            self.log_line(f"'{mid}' ist schon enthalten")
            return
        mod = self.lib.modules.get(mid)
        if mod:
            # same slot with max 1 -> replace instead of adding a second one
            slot = self.lib.slot(mod.slot)
            if slot and slot.max == 1:
                same = [x for x in self.machine.modules
                        if x in self.lib.modules and self.lib.modules[x].slot == mod.slot]
                if same:
                    i = self.machine.modules.index(same[0])
                    self.machine.modules[i] = mid
                    self.log_line(f"'{self.lib.modules[same[0]].label()}' durch '{mod.label()}' ersetzt")
                    self._read_vars()
                    self._mark_dirty()
                    self.show_machine()
                    return
            if row >= self.list.count():
                # put it at its standard position
                idx = self.lib.slot_index(mod.slot)
                row = len([x for x in self.machine.modules if x in self.lib.modules
                           and self.lib.slot_index(self.lib.modules[x].slot) <= idx])
        self.machine.modules.insert(row, mid)
        self._read_vars()
        self._mark_dirty()
        self.show_machine()

    def _list_reordered(self) -> None:
        self._read_list()
        self._mark_dirty()
        self.update_issues()

    def move_selected(self, delta: int) -> None:
        rows = sorted({self.list.row(i) for i in self.list.selectedItems()})
        if not rows:
            return
        self._read_list()
        mods = self.machine.modules
        if (delta < 0 and rows[0] == 0) or (delta > 0 and rows[-1] == len(mods) - 1):
            return
        for r in (rows if delta < 0 else reversed(rows)):
            mods[r + delta], mods[r] = mods[r], mods[r + delta]
        self._read_vars()
        self._mark_dirty()
        self.show_machine()
        for r in rows:
            self.list.item(r + delta).setSelected(True)

    def remove_selected(self) -> None:
        rows = sorted({self.list.row(i) for i in self.list.selectedItems()}, reverse=True)
        self._read_list()
        for r in rows:
            del self.machine.modules[r]
        self._read_vars()
        self._mark_dirty()
        self.show_machine()

    def sort_standard(self) -> None:
        self._read_list()
        self.machine.modules = self.lib.sort_by_slot(self.machine.modules)
        self._read_vars()
        self._mark_dirty()
        self.show_machine()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.list.hasFocus():
            self.remove_selected()
        else:
            super().keyPressEvent(e)

    # ---------------------------------------------------------------- files
    def maybe_save(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Änderungen speichern?",
                                 f"Änderungen an „{self.machine.name}“ speichern?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                 | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save_machine()
        return True

    def new_machine(self, ask: bool = True) -> None:
        if ask and not self.maybe_save():
            return
        self.machine = Machine(name="Neue Maschine", language=self.lib.default_language)
        self.machine.modules = [m.id for s in self.lib.slots if s.required
                                for m in self.lib.modules_in_slot(s.id)[:1]]
        self.dirty = False
        self.show_machine()

    def load_machine(self, path: Path) -> None:
        self.machine = Machine.load(path)
        self.dirty = False
        self.settings.setValue("last_machine", str(path))
        self.show_machine()

    def _machine_selected(self, idx: int) -> None:
        path = self.machine_box.itemData(idx)
        if not path or (self.machine.path and str(self.machine.path) == path):
            return
        if not self.maybe_save():
            self.refresh_machine_box()
            return
        self.load_machine(Path(path))

    def save_machine(self) -> bool:
        if self.machine.path is None:
            return self.save_machine_as()
        self._read_list()
        self._read_vars()
        self.machine.save()
        self.dirty = False
        self.settings.setValue("last_machine", str(self.machine.path))
        self.refresh_machine_box()
        self._update_title()
        self.log_line(f"Gespeichert: {self.machine.path.name}")
        return True

    def save_machine_as(self) -> bool:
        name, ok = QInputDialog.getText(self, "Speichern unter", "Name der Maschine:",
                                        text=self.machine.name)
        if not ok or not name.strip():
            return False
        path = self.lib.machines_dir / f"{slugify(name)}.yaml"
        if path.exists() and path != self.machine.path:
            if QMessageBox.question(self, "Überschreiben?", f"„{path.name}“ gibt es schon. Überschreiben?") \
                    != QMessageBox.StandardButton.Yes:
                return False
        self.machine.name = name.strip()
        self.machine.path = path
        self.name_edit.setText(self.machine.name)
        return self.save_machine()

    def delete_machine(self) -> None:
        if self.machine.path is None:
            return
        if QMessageBox.question(self, "Löschen?", f"Maschine „{self.machine.name}“ löschen? "
                                "(Die Module bleiben erhalten.)") != QMessageBox.StandardButton.Yes:
            return
        self.machine.path.unlink(missing_ok=True)
        self.dirty = False
        self.new_machine(ask=False)

    def closeEvent(self, e):
        if self.thread is not None:
            QMessageBox.information(self, "Bitte warten", "Die Anleitung wird gerade erstellt.")
            e.ignore()
            return
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()

    # ---------------------------------------------------------------- build
    def _choose_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Ausgabeordner", self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def log_line(self, text: str) -> None:
        self.log.appendPlainText(text)

    def build(self) -> None:
        if self.thread is not None:
            return
        self._read_list()
        self._read_vars()
        self.update_issues()
        if not self.build_btn.isEnabled():
            return
        out_dir = Path(self.out_edit.text()).expanduser()
        self.settings.setValue("output_dir", str(out_dir))
        self.settings.setValue("pdf", "true" if self.pdf_check.isChecked() else "false")
        self.log.clear()
        self.log_line(f"Erstelle „{self.machine.name}“ ({self.machine.language}) …")
        self.build_btn.setEnabled(False)
        self.build_btn.setText("Wird erstellt …")
        machine = Machine(name=self.machine.name, language=self.machine.language,
                          modules=list(self.machine.modules), variables=dict(self.machine.variables))
        self.thread = QThread()
        self.worker = BuildWorker(self.lib, machine, out_dir, self.pdf_check.isChecked(),
                                  self.engine_box.currentData())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log_line)
        self.worker.done.connect(self._build_done)
        self.worker.failed.connect(self._build_failed)
        self.thread.start()

    def _finish_thread(self) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait()
        self.thread = None
        self.build_btn.setText("Anleitung erstellen")
        self.update_issues()

    def _build_done(self, res) -> None:
        self._finish_thread()
        for i in res.issues:
            self.log_line(str(i))
        box = QMessageBox(self)
        box.setWindowTitle("Fertig")
        files = res.docx.name + (f"\n{res.pdf.name}" if res.pdf else "")
        warn = [i for i in res.issues if i.level == "warning"]
        box.setText(f"Die Anleitung wurde erstellt:\n\n{files}"
                    + (f"\n\n{len(warn)} Hinweise – siehe Protokoll." if warn else ""))
        open_pdf = box.addButton("PDF öffnen", QMessageBox.ButtonRole.AcceptRole) if res.pdf else None
        open_doc = box.addButton("Word öffnen", QMessageBox.ButtonRole.ActionRole)
        open_dir = box.addButton("Ordner öffnen", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Schließen", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is open_pdf and res.pdf:
            open_path(res.pdf)
        elif clicked is open_doc:
            open_path(res.docx)
        elif clicked is open_dir:
            open_path(res.docx.parent)

    def _build_failed(self, msg: str) -> None:
        self._finish_thread()
        self.log_line(msg)
        QMessageBox.critical(self, "Fehler", msg)
