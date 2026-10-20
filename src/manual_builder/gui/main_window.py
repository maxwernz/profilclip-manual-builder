"""Main window – everything in one view:

    ┌──────────┬───────────────────────────────────────────────────────────┐
    │ Maschinen│  Name of the machine · language · undo · PDF erstellen    │
    │          ├──────────────────────────────┬────────────────────────────┤
    │ ▸ SKT H10│  Bibliothek (tiles by group) │  Anleitung                 │
    │   SKT H8 │  ┌────┐ ┌────┐ ┌────┐        │  Maschinendaten            │
    │          │  │tile│ │tile│ │tile│  ──drag──▶ 1  Allgemeines      ×   │
    │          │  └────┘ └────┘ └────┘        │  10 Clipper DCX5S      ×   │
    │ ⚙        │                              │  status / result           │
    └──────────┴──────────────────────────────┴────────────────────────────┘

Tiles are dragged from the library into the manual, reordered there, and dragged
back (or ×) to remove them. Changes are saved automatically; Ctrl+Z undoes.
"""

from __future__ import annotations

import datetime as _dt
import traceback
from pathlib import Path

from PySide6.QtCore import QMimeData, QObject, QPoint, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QDrag, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from ..build import BuildError, build_manual
from ..engines import available_engines
from ..library import Library, Machine, Module, slugify
from ..outline import Entry, outline
from .common import open_path
from .flow import FlowLayout
from .icons import icon, pixmap, slot_style
from .import_dialog import ImportDialog
from .module_dialog import ModuleDialog
from .style import ACCENT, ERROR, MUTED, OK, WARN

MODULE_MIME = "application/x-manual-builder-module"
CHAPTER_MIME = "application/x-manual-builder-chapter"
LANG_LABELS = {"de": "Deutsch", "en": "English", "it": "Italiano", "fr": "Français", "es": "Español"}
MAIN_VARIABLES = [("Maschinentyp", "Maschinentyp"), ("Kunde", "Kunde"),
                  ("Seriennummer", "Seriennummer"), ("Baujahr", "Baujahr")]
ENGINE_NAMES = {"auto": "Automatisch (empfohlen)", "word": "Microsoft Word", "libreoffice": "LibreOffice",
                "none": "Kein PDF – nur Word-Datei"}


# ---------------------------------------------------------------- helpers

def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def icon_label(name: str, color: str, size: int = 18) -> QLabel:
    lbl = QLabel()
    lbl.setPixmap(pixmap(name, color, size))
    lbl.setFixedSize(size, size)
    return lbl


def badge(name: str, color: str, box: int = 32, size: int = 18) -> QLabel:
    """Colored icon on a light tinted square."""
    lbl = QLabel()
    lbl.setPixmap(pixmap(name, color, size))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setFixedSize(box, box)
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    lbl.setStyleSheet(f"background:rgba({r},{g},{b},30);border-radius:8px;")
    return lbl


def icon_button(name: str, tip: str, slot=None, color: str = "#3b4456") -> QToolButton:
    b = QToolButton()
    b.setObjectName("iconButton")
    b.setIcon(icon(name, color))
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def text_button(text: str, icon_name: str | None = None, name: str | None = None, slot=None,
                color: str = "#3b4456") -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if icon_name:
        b.setIcon(icon(icon_name, color))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def clear_layout(lay) -> None:
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def fmt_date(iso: str) -> str:
    try:
        return _dt.datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


def start_drag(source: QWidget, mime_type: str, payload: str) -> None:
    mime = QMimeData()
    mime.setData(mime_type, payload.encode())
    drag = QDrag(source)
    drag.setMimeData(mime)
    pm = source.grab()
    drag.setPixmap(pm)
    drag.setHotSpot(QPoint(min(pm.width() // 2, 40), pm.height() // 2))
    drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)


# ---------------------------------------------------------------- machines (left)

class MachineItem(QFrame):
    clicked = Signal()

    def __init__(self, machine: Machine, selected: bool, menu_factory):
        super().__init__()
        self.setObjectName("machineItem")
        self.setProperty("selected", selected)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 6, 8)
        lay.setSpacing(10)
        lay.addWidget(badge("machine", ACCENT if selected else "#64748b", 30, 16))
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(machine.name, "machineName"))
        typ = machine.variables.get("Maschinentyp", "")
        sub = " · ".join(x for x in (typ, machine.language.upper(), f"{len(machine.modules)} Bausteine") if x)
        col.addWidget(label(sub, "hint"))
        lay.addLayout(col, 1)
        more = QToolButton()
        more.setObjectName("iconButton")
        more.setIcon(icon("dots", "#8a93a3"))
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setMenu(menu_factory(machine))
        lay.addWidget(more)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class MachinesPanel(QFrame):
    selected = Signal(object)

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.setObjectName("sidebar")
        self.setFixedWidth(250)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 18, 12, 12)
        lay.setSpacing(6)
        brand = QHBoxLayout()
        brand.addWidget(badge("layers", ACCENT, 34, 20))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label("Anleitungs-Baukasten", "appName"))
        col.addWidget(label("Profil-Clip", "appSub"))
        brand.addLayout(col, 1)
        lay.addLayout(brand)
        lay.addSpacing(16)
        head = QHBoxLayout()
        head.addWidget(label("MASCHINEN", "panelCaption"), 1)
        head.addWidget(icon_button("plus", "Neue Maschine anlegen", self.new_machine, ACCENT))
        lay.addLayout(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Maschine suchen …")
        self.search.addAction(icon("search", "#8a93a3"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda: self.refresh())
        lay.addWidget(self.search)
        host = QWidget()
        self.list = QVBoxLayout(host)
        self.list.setContentsMargins(0, 4, 0, 4)
        self.list.setSpacing(4)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(host)
        lay.addWidget(sc, 1)
        lay.addWidget(text_button("Einstellungen", "settings", "flat", lambda: SettingsDialog(win).exec()))

    def refresh(self, current: Path | None = None) -> None:
        if current is None and self.win.workspace.machine is not None:
            current = self.win.workspace.machine.path
        clear_layout(self.list)
        flt = self.search.text().strip().lower()
        machines = []
        for p in self.win.lib.machines():
            try:
                machines.append(Machine.load(p))
            except Exception:
                continue
        machines.sort(key=lambda m: m.name.lower())
        for m in machines:
            if flt and flt not in (m.name + " " + " ".join(m.variables.values())).lower():
                continue
            it = MachineItem(m, current is not None and m.path == current, self._menu)
            it.clicked.connect(lambda m=m: self.selected.emit(m))
            self.list.addWidget(it)
        if not machines:
            self.list.addWidget(label("Noch keine Maschine.\nMit + eine neue anlegen.", "hint", wrap=True))
        self.list.addStretch()

    def _menu(self, machine: Machine) -> QMenu:
        menu = QMenu(self)
        menu.addAction(icon("edit"), "Umbenennen …", lambda: self.rename(machine))
        menu.addAction(icon("copy"), "Duplizieren …", lambda: self.duplicate(machine))
        menu.addSeparator()
        menu.addAction(icon("trash", ERROR), "Löschen", lambda: self.delete(machine))
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
        name, ok = QInputDialog.getText(self, "Neue Maschine", "Name (z. B. „SKT H10 Müller GmbH“):")
        if not ok or not name.strip():
            return
        lib = self.win.lib
        m = Machine(name=name.strip(), language=lib.default_language)
        m.modules = lib.sort_by_slot([mods[0].id for s in lib.slots if s.required
                                      for mods in [lib.modules_in_slot(s.id)] if mods])
        m.save(self._unique_path(name))
        self.selected.emit(m)

    def rename(self, machine: Machine) -> None:
        name, ok = QInputDialog.getText(self, "Umbenennen", "Neuer Name:", text=machine.name)
        if ok and name.strip():
            ws = self.win.workspace
            if ws.machine is not None and ws.machine.path == machine.path:
                ws.machine.name = name.strip()
                ws.name_edit.setText(ws.machine.name)
                ws.machine.save()
            else:
                machine.name = name.strip()
                machine.save()
            self.refresh()

    def duplicate(self, machine: Machine) -> None:
        name, ok = QInputDialog.getText(self, "Duplizieren", "Name der Kopie:", text=machine.name + " (Kopie)")
        if not ok or not name.strip():
            return
        copy = Machine(name=name.strip(), language=machine.language, modules=list(machine.modules),
                       variables=dict(machine.variables))
        copy.save(self._unique_path(name))
        self.selected.emit(copy)

    def delete(self, machine: Machine) -> None:
        if QMessageBox.question(self, "Löschen?", f"„{machine.name}“ löschen?\n\nNur die Zusammenstellung wird "
                                "gelöscht – Bausteine und erstellte PDFs bleiben erhalten.") \
                != QMessageBox.StandardButton.Yes:
            return
        if machine.path:
            machine.path.unlink(missing_ok=True)
        ws = self.win.workspace
        if ws.machine is not None and ws.machine.path == machine.path:
            ws.load(None)
            rest = self.win.lib.machines()
            if rest:
                self.selected.emit(Machine.load(rest[0]))
                return
        self.refresh()


# ---------------------------------------------------------------- library (middle)

class LibraryTile(QFrame):
    def __init__(self, ws: "Workspace", module: Module, used: bool):
        super().__init__()
        self.ws = ws
        self.module = module
        self._press: QPoint | None = None
        self.setObjectName("tile")
        self.setProperty("used", used)
        self.setFixedSize(172, 112)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        lang = ws.lang
        icon_name, color = slot_style(module.slot)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 6, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(badge(icon_name, color))
        top.addStretch()
        if used:
            ok = icon_label("check-circle", OK, 18)
            ok.setToolTip("Ist in der Anleitung enthalten")
            top.addWidget(ok)
        more = QToolButton()
        more.setObjectName("iconButton")
        more.setIcon(icon("dots", "#8a93a3"))
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setMenu(ws.library.module_menu(module, self))
        top.addWidget(more)
        lay.addLayout(top)
        title = label(module.label(lang), "tileTitle", wrap=True)
        title.setFixedHeight(36)
        title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(title)
        lay.addStretch()
        have = module.languages()
        n_f = len(module.entries("faults"))
        meta = []
        if have:
            meta.append(" ".join(c.upper() for c in have))
        else:
            meta.append("nur Tabellen")
        if n_f:
            meta.append(f"{n_f} Störungen")
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        bottom.addWidget(label(" · ".join(meta), "hint"))
        bottom.addStretch()
        if have and lang not in have:
            warn = icon_label("globe", WARN, 14)
            warn.setToolTip(f"Kein Text auf {LANG_LABELS.get(lang, lang)} – deutscher Text wird verwendet")
            bottom.addWidget(warn)
        lay.addLayout(bottom)
        tip = [module.label(lang), f"Version {module.version}"]
        if module.description:
            tip.append(module.description)
        tip.append("Ziehen oder doppelklicken zum Hinzufügen")
        self.setToolTip("\n".join(tip))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() \
                >= QApplication.startDragDistance():
            self._press = None
            start_drag(self, MODULE_MIME, self.module.id)

    def mouseReleaseEvent(self, e):
        self._press = None

    def mouseDoubleClickEvent(self, e):
        self.ws.add_module(self.module.id)

    def contextMenuEvent(self, e):
        self.ws.library.module_menu(self.module, self).exec(e.globalPos())


class LibraryPanel(QFrame):
    def __init__(self, ws: "Workspace"):
        super().__init__()
        self.ws = ws
        self.setObjectName("panel")
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 10, 12)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(icon_label("layers", ACCENT, 20))
        head.addWidget(label("Bibliothek", "panelTitle"))
        head.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Baustein suchen …")
        self.search.addAction(icon("search", "#8a93a3"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda: self.refresh())
        head.addWidget(self.search, 1)
        head.addWidget(text_button("Word-Datei hinzufügen", "upload", None, lambda: self.import_file()))
        head.addSpacing(6)
        lay.addLayout(head)
        lay.addWidget(label("Bausteine in die Anleitung ziehen · Doppelklick fügt hinzu · "
                            "zum Entfernen zurück hierher ziehen", "hint"))
        host = QWidget()
        self.sections = QVBoxLayout(host)
        self.sections.setContentsMargins(0, 0, 8, 0)
        self.sections.setSpacing(6)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(host)
        lay.addWidget(sc, 1)

    def refresh(self) -> None:
        clear_layout(self.sections)
        lib = self.ws.win.lib
        lang = self.ws.lang
        used = set(self.ws.machine.modules) if self.ws.machine else set()
        flt = self.search.text().strip().lower()
        for slot in lib.slots:
            mods = [m for m in sorted(lib.modules_in_slot(slot.id), key=lambda m: m.label(lang))
                    if not flt or flt in (m.label(lang) + " " + m.id).lower()]
            if not mods:
                continue
            icon_name, color = slot_style(slot.id)
            h = QHBoxLayout()
            h.setContentsMargins(0, 10, 0, 2)
            h.addWidget(icon_label(icon_name, color, 16))
            h.addWidget(label(slot.label("de"), "sectionTitle"))
            rule = ("eine Variante wählen" if slot.max == 1 and len(mods) > 1 else
                    "mehrere möglich" if slot.max is None else "")
            if slot.required:
                rule = (rule + " · " if rule else "") + "Pflicht"
            h.addWidget(label(rule, "hint"))
            h.addStretch()
            self.sections.addLayout(h)
            box = QWidget()
            flow = FlowLayout(box, spacing=10)
            for m in mods:
                flow.addWidget(LibraryTile(self.ws, m, m.id in used))
            self.sections.addWidget(box)
        self.sections.addStretch()

    def module_menu(self, module: Module, parent: QWidget) -> QMenu:
        menu = QMenu(parent)
        in_manual = self.ws.machine is not None and module.id in self.ws.machine.modules
        if in_manual:
            menu.addAction(icon("x"), "Aus der Anleitung entfernen",
                           lambda: self.ws.remove_index(self.ws.machine.modules.index(module.id)))
        else:
            menu.addAction(icon("plus", ACCENT), "Zur Anleitung hinzufügen",
                           lambda: self.ws.add_module(module.id))
        menu.addSeparator()
        menu.addAction(icon("table"), "Bearbeiten (Wartung, Ersatzteile, Störungen) …",
                       lambda: self.edit(module.id))
        lang = self.ws.lang
        have = module.languages()
        if have:
            p = module.docx_path(lang) if lang in have else module.docx_path(have[0])
            menu.addAction(icon("word"), f"In Word öffnen ({p.stem.upper()})", lambda: open_path(p))
        menu.addAction(icon("upload"), "Neue Fassung / Übersetzung hochladen …",
                       lambda: self.import_file(module.id))
        menu.addAction(icon("folder"), "Ordner öffnen", lambda: open_path(module.path))
        return menu

    def edit(self, mid: str) -> None:
        dlg = ModuleDialog(self.ws.win.lib, self.ws.win.lib.modules[mid], self, lang=self.ws.lang)
        dlg.exec()
        self.ws.reload_library()

    def import_file(self, module_id: str | None = None) -> None:
        dlg = ImportDialog(self.ws.win.lib, self, module_id=module_id)
        if dlg.exec():
            self.ws.reload_library()

    # dropping a chapter back on the library removes it
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(CHAPTER_MIME):
            e.acceptProposedAction()
            self.setProperty("dropTarget", True)
            repolish(self)

    def dragLeaveEvent(self, e):
        self.setProperty("dropTarget", False)
        repolish(self)

    def dropEvent(self, e):
        self.setProperty("dropTarget", False)
        repolish(self)
        idx = int(bytes(e.mimeData().data(CHAPTER_MIME)).decode())
        self.ws.remove_index(idx)
        e.acceptProposedAction()


# ---------------------------------------------------------------- manual (right)

class ChapterTile(QFrame):
    def __init__(self, ws: "Workspace", index: int, module: Module, entries: list[Entry]):
        super().__init__()
        self.ws = ws
        self.index = index
        self.module = module
        self._press: QPoint | None = None
        self.setObjectName("chapterTile")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        lang = ws.lang
        icon_name, color = slot_style(module.slot)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(icon_label("grip", "#b3bac6", 16))
        nums = [e.number for e in entries]
        num = label(nums[0] if len(nums) == 1 else (f"{nums[0]}–{nums[-1]}" if nums else "–"), "chapterNo")
        num.setFixedWidth(44)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(num)
        row.addWidget(badge(icon_name, color, 30, 17))
        col = QVBoxLayout()
        col.setSpacing(1)
        title = label(module.label(lang), "tileTitle")
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        col.addWidget(title)
        subs = sum(len(e.children) for e in entries)
        slot = ws.win.lib.slot(module.slot)
        bits = [slot.label("de") if slot else module.slot]
        if len(entries) > 1:
            bits.append(f"{len(entries)} Kapitel")
        if subs:
            bits.append(f"{subs} Abschnitte")
        n_f = len(module.entries("faults"))
        if n_f:
            bits.append(f"{n_f} Störungen")
        sub = label(" · ".join(bits), "hint")
        sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sub.setToolTip(" · ".join(bits))
        col.addWidget(sub)
        row.addLayout(col, 1)
        if module.has_text() and lang not in module.languages():
            w = icon_label("globe", WARN, 16)
            w.setToolTip(f"Kein Text auf {LANG_LABELS.get(lang, lang)} – deutscher Text wird verwendet")
            row.addWidget(w)
        expanded = module.id in ws.expanded
        self.expand_btn = icon_button("chevron-down" if expanded else "chevron-right",
                                      "Gliederung anzeigen", self.toggle, "#6b7385")
        self.expand_btn.setEnabled(bool(entries))
        row.addWidget(self.expand_btn)
        row.addWidget(icon_button("x", "Aus der Anleitung entfernen",
                                  lambda: ws.remove_index(self.index), "#8a93a3"))
        outer.addLayout(row)
        self.details = label("", "outlineText", wrap=True)
        lines = []
        for e in entries:
            if len(entries) > 1:
                lines.append(f"<b>{e.number}&nbsp;&nbsp;{e.text}</b>")
            lines += [f"<span style='color:{MUTED}'>{c.number}</span>&nbsp;&nbsp;{c.text}" for c in e.children]
        self.details.setText("<br>".join(lines) or f"<span style='color:{MUTED}'>keine Unterkapitel</span>")
        self.details.setContentsMargins(78, 0, 8, 6)
        self.details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.details.setVisible(expanded)
        outer.addWidget(self.details)

    def toggle(self) -> None:
        vis = not self.details.isVisible()
        self.details.setVisible(vis)
        self.expand_btn.setIcon(icon("chevron-down" if vis else "chevron-right", "#6b7385"))
        (self.ws.expanded.add if vis else self.ws.expanded.discard)(self.module.id)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() \
                >= QApplication.startDragDistance():
            self._press = None
            start_drag(self, CHAPTER_MIME, str(self.index))

    def mouseReleaseEvent(self, e):
        self._press = None

    def mouseDoubleClickEvent(self, e):
        self.toggle()

    def contextMenuEvent(self, e):
        self.ws.library.module_menu(self.module, self).exec(e.globalPos())


class ChapterList(QWidget):
    """Vertical list of chapter tiles; drop target for library tiles and for reordering."""

    def __init__(self, ws: "Workspace"):
        super().__init__()
        self.ws = ws
        self.setAcceptDrops(True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 4, 0)
        self.lay.setSpacing(6)
        self.tiles: list[ChapterTile] = []
        self.indicator = QFrame()
        self.indicator.setObjectName("dropIndicator")
        self.indicator.setFixedHeight(4)
        self.indicator.hide()
        self.empty = QLabel("Bausteine aus der Bibliothek hierher ziehen")
        self.empty.setObjectName("emptyDrop")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(160)

    def set_tiles(self, tiles: list[ChapterTile]) -> None:
        self.indicator.setParent(None)
        self.empty.setParent(None)
        clear_layout(self.lay)
        self.tiles = tiles
        for t in tiles:
            self.lay.addWidget(t)
        if not tiles:
            self.lay.addWidget(self.empty)
            self.empty.show()
        self.lay.addStretch()

    def _index_at(self, y: int) -> int:
        for i, t in enumerate(self.tiles):
            if y < t.geometry().center().y():
                return i
        return len(self.tiles)

    def _show_indicator(self, idx: int) -> None:
        self.lay.removeWidget(self.indicator)
        self.lay.insertWidget(idx, self.indicator)
        self.indicator.show()

    def _hide_indicator(self) -> None:
        self.lay.removeWidget(self.indicator)
        self.indicator.hide()

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MODULE_MIME) or e.mimeData().hasFormat(CHAPTER_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MODULE_MIME) or e.mimeData().hasFormat(CHAPTER_MIME):
            self._show_indicator(self._index_at(int(e.position().y())))
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._hide_indicator()

    def dropEvent(self, e):
        self._hide_indicator()
        idx = self._index_at(int(e.position().y()))
        md = e.mimeData()
        if md.hasFormat(MODULE_MIME):
            self.ws.add_module(bytes(md.data(MODULE_MIME)).decode(), idx)
        elif md.hasFormat(CHAPTER_MIME):
            self.ws.move_index(int(bytes(md.data(CHAPTER_MIME)).decode()), idx)
        e.acceptProposedAction()


class VariablesDialog(QDialog):
    def __init__(self, ws: "Workspace"):
        super().__init__(ws)
        self.ws = ws
        self.setWindowTitle("Maschinendaten")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(label("Maschinendaten", "title"))
        lay.addWidget(label("Diese Angaben ersetzen die Platzhalter {{Name}} in Titelseite, Kopfzeile und "
                            "Texten. Leere Felder verwenden den grauen Vorschlag.", "subtitle", wrap=True))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        lib = ws.win.lib
        m = ws.machine
        defaults = lib.default_variables(m.language)
        labels = {v["key"]: v.get("label", v["key"]) for v in lib.variables}
        self.edits: dict[str, QLineEdit] = {}
        for key in [v["key"] for v in lib.variables] + [k for k in m.variables if k not in labels]:
            e = QLineEdit(m.variables.get(key, ""))
            e.setPlaceholderText(defaults.get(key, ""))
            form.addRow(labels.get(key, key), e)
            self.edits[key] = e
        lay.addLayout(form)
        lay.addWidget(text_button("Eigenes Feld hinzufügen", "plus", "flat", self._add), 0,
                      Qt.AlignmentFlag.AlignLeft)
        self.form = form
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add(self) -> None:
        key, ok = QInputDialog.getText(self, "Eigenes Feld", "Name (ohne Klammern), z. B. Spannung:")
        if ok and key.strip() and key.strip() not in self.edits:
            e = QLineEdit()
            self.form.addRow(key.strip(), e)
            self.edits[key.strip()] = e

    def values(self) -> dict[str, str]:
        return {k: e.text() for k, e in self.edits.items() if e.text()}


class ManualPanel(QFrame):
    def __init__(self, ws: "Workspace"):
        super().__init__()
        self.ws = ws
        self.setObjectName("panel")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(icon_label("file", ACCENT, 20))
        head.addWidget(label("Anleitung", "panelTitle"))
        self.count_label = label("", "hint")
        head.addWidget(self.count_label)
        head.addStretch()
        head.addWidget(icon_button("sort", "Standard-Reihenfolge herstellen", ws.sort_standard))
        self.undo_btn = icon_button("undo", "Rückgängig (Strg+Z)", ws.undo)
        head.addWidget(self.undo_btn)
        lay.addLayout(head)

        # machine data (compact)
        data = QFrame()
        data.setObjectName("subCard")
        dl = QGridLayout(data)
        dl.setContentsMargins(12, 10, 12, 10)
        dl.setHorizontalSpacing(10)
        dl.setVerticalSpacing(4)
        self.var_edits: dict[str, QLineEdit] = {}
        for i, (key, text) in enumerate(MAIN_VARIABLES):
            r, c = divmod(i, 2)
            dl.addWidget(label(text, "fieldLabel"), r * 2, c)
            e = QLineEdit()
            e.textEdited.connect(ws.vars_changed)
            self.var_edits[key] = e
            dl.addWidget(e, r * 2 + 1, c)
        more = text_button("Alle Maschinendaten …", "edit", "flat", ws.edit_all_vars)
        dl.addWidget(more, 4, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(data)

        self.chapters = ChapterList(ws)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(self.chapters)
        lay.addWidget(sc, 1)

        # status
        self.issues = label("", None, wrap=True)
        self.issues.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.issues)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        lay.addWidget(self.progress)
        self.status = label("", "hint", wrap=True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.status)
        res = QHBoxLayout()
        self.open_pdf = text_button("PDF öffnen", "pdf", None, lambda: ws.open_result("pdf"), ERROR)
        self.open_doc = text_button("Word", "word", None, lambda: ws.open_result("docx"), ACCENT)
        self.open_dir = text_button("Ordner", "folder", None, lambda: ws.open_result("dir"))
        self.log_btn = text_button("Protokoll", "info", "flat", self._toggle_log)
        for b in (self.open_pdf, self.open_doc, self.open_dir, self.log_btn):
            b.hide()
            res.addWidget(b)
        res.addStretch()
        lay.addLayout(res)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        self.log.hide()
        lay.addWidget(self.log)

    def _toggle_log(self) -> None:
        self.log.setVisible(not self.log.isVisible())


# ---------------------------------------------------------------- workspace

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
            self.failed.emit("<br>".join(i.message for i in e.issues))
        except Exception as e:  # pragma: no cover - shown to the user
            self.log.emit(traceback.format_exc())
            self.failed.emit(str(e))


class Workspace(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.machine: Machine | None = None
        self.history: list[list[str]] = []
        self.expanded: set[str] = set()
        self.thread: QThread | None = None
        self.last_result = None
        self.save_timer = QTimer(self, singleShot=True, interval=400, timeout=self.save)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(12)

        # header
        head = QHBoxLayout()
        head.setSpacing(10)
        self.head_badge = badge("machine", ACCENT, 38, 22)
        head.addWidget(self.head_badge)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("titleEdit")
        self.name_edit.setToolTip("Name der Maschine – zum Ändern klicken")
        self.name_edit.textEdited.connect(self._name_changed)
        col.addWidget(self.name_edit)
        self.subtitle = label("", "hint")
        self.subtitle.setContentsMargins(8, 0, 0, 0)
        col.addWidget(self.subtitle)
        head.addLayout(col, 1)
        head.addWidget(icon_label("globe", MUTED, 16))
        self.lang_row = QHBoxLayout()
        self.lang_row.setSpacing(0)
        self.lang_group = QButtonGroup(self)
        head.addLayout(self.lang_row)
        head.addSpacing(10)
        self.build_btn = text_button("PDF erstellen", "play", "primary", self.build, "#ffffff")
        self.build_btn.setMinimumHeight(40)
        head.addWidget(self.build_btn)
        lay.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.library = LibraryPanel(self)
        self.manual = ManualPanel(self)
        body.addWidget(self.library, 3)
        body.addWidget(self.manual, 2)
        lay.addLayout(body, 1)

        undo = QAction(self)
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        undo.triggered.connect(self.undo)
        self.addAction(undo)
        build = QAction(self)
        build.setShortcut(QKeySequence("Ctrl+B"))
        build.triggered.connect(self.build)
        self.addAction(build)

    @property
    def lang(self) -> str:
        return self.machine.language if self.machine else self.win.lib.default_language

    # ---------------------------------------------------------------- load / save
    def load(self, machine: Machine | None) -> None:
        if self.machine is not None:
            self.save_timer.stop()
            self.save()
        self.machine = machine
        self.history = []
        self.last_result = None
        enabled = machine is not None
        for w in (self.name_edit, self.build_btn, self.manual, self.library):
            w.setEnabled(enabled)
        self.name_edit.setText(machine.name if machine else "Keine Maschine gewählt")
        self._build_lang_buttons()
        for key, e in self.manual.var_edits.items():
            e.setText(machine.variables.get(key, "") if machine else "")
            e.setPlaceholderText(self.win.lib.default_variables(self.lang).get(key, ""))
        for b in (self.manual.open_pdf, self.manual.open_doc, self.manual.open_dir, self.manual.log_btn):
            b.hide()
        self.manual.log.clear()
        self.manual.log.hide()
        self.manual.status.setText(f"Zuletzt erstellt am {fmt_date(machine.last_built)}"
                                   if machine and machine.last_built else "")
        if machine and machine.path:
            self.win.settings.setValue("last_machine", str(machine.path))
        self.refresh()

    def save(self) -> None:
        if self.machine is not None and self.machine.path is not None:
            self.machine.save()

    def _changed(self) -> None:
        self.save_timer.start()

    def reload_library(self) -> None:
        self.win.lib.reload_modules()
        self.refresh()

    # ---------------------------------------------------------------- views
    def _build_lang_buttons(self) -> None:
        clear_layout(self.lang_row)
        for b in self.lang_group.buttons():
            self.lang_group.removeButton(b)
        langs = self.win.lib.languages
        for i, code in enumerate(langs):
            name = "segFirst" if i == 0 else ("segLast" if i == len(langs) - 1 else "seg")
            b = text_button(code.upper(), None, name)
            b.setToolTip(LANG_LABELS.get(code, code))
            b.setCheckable(True)
            b.setChecked(self.machine is not None and code == self.machine.language)
            b.setEnabled(self.machine is not None)
            b.clicked.connect(lambda _=False, c=code: self.set_language(c))
            self.lang_group.addButton(b)
            self.lang_row.addWidget(b)

    def refresh(self) -> None:
        """Re-render library tiles, chapter tiles and the status line."""
        self.library.refresh()
        lib = self.win.lib
        m = self.machine
        tiles = []
        n_chapters = 0
        if m is not None:
            entries = outline(lib, m)
            by_module: dict[str, list[Entry]] = {}
            for e in entries:
                by_module.setdefault(e.module_id, []).append(e)
            n_chapters = len(entries)
            for i, mid in enumerate(m.modules):
                mod = lib.modules.get(mid)
                if mod is not None:
                    tiles.append(ChapterTile(self, i, mod, by_module.get(mid, [])))
        self.manual.chapters.set_tiles(tiles)
        self.manual.count_label.setText(f"· {n_chapters} Kapitel" if n_chapters else "")
        self.manual.undo_btn.setEnabled(bool(self.history))
        typ = (m.variables.get("Maschinentyp") or lib.default_variables(self.lang).get("Maschinentyp", "")) if m else ""
        out = Path(self.win.settings.value("output_dir", str(Path.home() / "Documents" / "Anleitungen")))
        try:
            out_txt = "~/" + out.relative_to(Path.home()).as_posix()
        except ValueError:
            out_txt = str(out)
        self.subtitle.setText(f"{typ} · {LANG_LABELS.get(self.lang, self.lang)} · PDF/Word nach {out_txt}"
                              if m else "Links eine Maschine wählen oder mit + anlegen")
        self._update_issues()

    def _update_issues(self) -> None:
        m = self.machine
        if m is None:
            self.manual.issues.setText("")
            return
        issues = [i for i in self.win.lib.validate(m) if i.level != "info" and "Variable" not in i.message]
        errors = [i for i in issues if i.level == "error"]
        lines = []
        for i in issues[:4]:
            color, sym = (ERROR, "●") if i.level == "error" else (WARN, "▲")
            lines.append(f"<span style='color:{color}'>{sym}</span> {i.message}")
        if len(issues) > 4:
            lines.append(f"<span style='color:{MUTED}'>… und {len(issues) - 4} weitere</span>")
        if not issues:
            lines.append(f"<span style='color:{OK}'>✓</span> <span style='color:{MUTED}'>Bereit zum Erstellen</span>")
        self.manual.issues.setText("<br>".join(lines))
        self.build_btn.setEnabled(not errors and self.thread is None)

    # ---------------------------------------------------------------- editing the module list
    def _snapshot(self) -> None:
        self.history.append(list(self.machine.modules))
        del self.history[:-50]

    def _flash(self, text: str) -> None:
        self.manual.status.setText(f"<span style='color:{MUTED}'>{text}</span>")

    def add_module(self, mid: str, idx: int | None = None) -> None:
        if self.machine is None:
            return
        lib = self.win.lib
        mods = self.machine.modules
        mod = lib.modules.get(mid)
        if mod is None:
            return
        if mid in mods:
            if idx is not None:
                self.move_index(mods.index(mid), idx)
            else:
                self._flash(f"„{mod.label(self.lang)}“ ist schon enthalten.")
            return
        self._snapshot()
        slot = lib.slot(mod.slot)
        if slot is not None and slot.max == 1:
            same = [x for x in mods if x in lib.modules and lib.modules[x].slot == mod.slot]
            if same:   # only one variant allowed → replace it in place
                pos = mods.index(same[0])
                mods[pos] = mid
                self._flash(f"„{lib.modules[same[0]].label(self.lang)}“ durch „{mod.label(self.lang)}“ ersetzt.")
                self._changed()
                self.refresh()
                return
        if idx is None:   # standard position
            si = lib.slot_index(mod.slot)
            idx = len([x for x in mods if x in lib.modules and lib.slot_index(lib.modules[x].slot) <= si])
        mods.insert(idx, mid)
        self._flash(f"„{mod.label(self.lang)}“ hinzugefügt.")
        self._changed()
        self.refresh()

    def move_index(self, src: int, dst: int) -> None:
        mods = self.machine.modules
        if not (0 <= src < len(mods)) or dst in (src, src + 1):
            return
        self._snapshot()
        mid = mods.pop(src)
        mods.insert(dst - 1 if dst > src else dst, mid)
        self._changed()
        self.refresh()

    def remove_index(self, i: int) -> None:
        mods = self.machine.modules
        if not (0 <= i < len(mods)):
            return
        self._snapshot()
        mid = mods.pop(i)
        mod = self.win.lib.modules.get(mid)
        self._flash(f"„{mod.label(self.lang) if mod else mid}“ entfernt – Strg+Z macht es rückgängig.")
        self._changed()
        self.refresh()

    def undo(self) -> None:
        if self.machine is None or not self.history:
            return
        self.machine.modules = self.history.pop()
        self._changed()
        self.refresh()

    def sort_standard(self) -> None:
        if self.machine is None:
            return
        self._snapshot()
        self.machine.modules = self.win.lib.sort_by_slot(self.machine.modules)
        self._changed()
        self.refresh()

    def set_language(self, code: str) -> None:
        self.machine.language = code
        for key, e in self.manual.var_edits.items():
            e.setPlaceholderText(self.win.lib.default_variables(code).get(key, ""))
        self._changed()
        self.refresh()

    def vars_changed(self, *_):
        for key, e in self.manual.var_edits.items():
            if e.text():
                self.machine.variables[key] = e.text()
            else:
                self.machine.variables.pop(key, None)
        self._changed()

    def edit_all_vars(self) -> None:
        if self.machine is None:
            return
        dlg = VariablesDialog(self)
        if dlg.exec():
            self.machine.variables = dlg.values()
            for key, e in self.manual.var_edits.items():
                e.setText(self.machine.variables.get(key, ""))
            self._changed()
            self.refresh()

    def _name_changed(self, text: str) -> None:
        if self.machine is not None:
            self.machine.name = text.strip() or "Unbenannt"
            self._changed()
            QTimer.singleShot(500, lambda: self.win.machines.refresh())

    # ---------------------------------------------------------------- build
    def build(self) -> None:
        if self.thread is not None or self.machine is None or not self.build_btn.isEnabled():
            return
        self.save()
        settings = self.win.settings
        out_dir = Path(settings.value("output_dir", str(Path.home() / "Documents" / "Anleitungen"))).expanduser()
        engine = settings.value("engine", "auto")
        mp = self.manual
        mp.log.clear()
        for b in (mp.open_pdf, mp.open_doc, mp.open_dir):
            b.hide()
        self.build_btn.setEnabled(False)
        self.build_btn.setText("Wird erstellt …")
        mp.progress.show()
        mp.status.setText("Bausteine werden zusammengesetzt …")
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
        self.manual.log.appendPlainText(text)
        if text.startswith("+ "):
            self.manual.status.setText(f"Füge ein: {text[2:]}")
        elif "Inhaltsverzeichnis" in text:
            self.manual.status.setText("Inhaltsverzeichnis und Seitenzahlen werden berechnet …")

    def _finish(self) -> None:
        if self.thread:
            self.thread.quit()
            self.thread.wait()
        self.thread = None
        self.manual.progress.hide()
        self.manual.log_btn.show()
        self.build_btn.setText("PDF erstellen")
        self._update_issues()

    def _done(self, res) -> None:
        self._finish()
        self.last_result = res
        self.machine.last_built = _dt.datetime.now().isoformat(timespec="minutes")
        self.save()
        for i in res.issues:
            self.manual.log.appendPlainText(str(i))
        warn = [i for i in res.issues if i.level == "warning"]
        name = res.pdf.name if res.pdf else res.docx.name
        self.manual.status.setText(f"<span style='color:{OK}'>✓ Fertig:</span> {name}"
                                   + (f" <span style='color:{MUTED}'>· {len(warn)} Hinweise im Protokoll</span>"
                                      if warn else ""))
        self.manual.open_pdf.setVisible(res.pdf is not None)
        self.manual.open_doc.show()
        self.manual.open_dir.show()
        self.win.machines.refresh()

    def _failed(self, msg: str) -> None:
        self._finish()
        self.manual.status.setText(f"<span style='color:{ERROR}'>Fehler:</span> {msg}")
        self.manual.log.show()

    def open_result(self, what: str) -> None:
        r = self.last_result
        if r:
            open_path(r.pdf if what == "pdf" else r.docx if what == "docx" else r.docx.parent)


# ---------------------------------------------------------------- settings

class SettingsDialog(QDialog):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)
        lay.addWidget(label("Einstellungen", "title"))
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(16)
        self.lib_edit = QLineEdit(str(win.lib.root))
        self.lib_edit.setReadOnly(True)
        r1 = QHBoxLayout()
        r1.addWidget(self.lib_edit)
        r1.addWidget(text_button("Ändern …", "folder", None, self._choose_lib))
        form.addRow("Bibliothek:", r1)
        form.addRow("", label("Ordner mit allen Bausteinen und Maschinen. Für mehrere Benutzer auf ein "
                              "Netzlaufwerk legen.", "hint", wrap=True))
        self.out_edit = QLineEdit(win.settings.value("output_dir", str(Path.home() / "Documents" / "Anleitungen")))
        r2 = QHBoxLayout()
        r2.addWidget(self.out_edit)
        r2.addWidget(text_button("Ändern …", "folder", None, self._choose_out))
        form.addRow("Fertige Anleitungen:", r2)
        self.engine = QComboBox()
        for e in ["auto"] + available_engines():
            self.engine.addItem(ENGINE_NAMES[e], e)
        self.engine.setCurrentIndex(max(0, self.engine.findData(win.settings.value("engine", "auto"))))
        form.addRow("Seitenzahlen & PDF mit:", self.engine)
        form.addRow("", label("Inhaltsverzeichnis, Seitenzahlen und PDF erzeugt Microsoft Word oder LibreOffice. "
                              "„Automatisch“ nimmt Word, falls vorhanden.", "hint", wrap=True))
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.new_lib: Library | None = None

    def _choose_lib(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Bibliothek wählen", self.lib_edit.text())
        if not d:
            return
        try:
            self.new_lib = Library(Path(d))
            self.lib_edit.setText(d)
        except FileNotFoundError:
            QMessageBox.warning(self, "Keine Bibliothek", "In diesem Ordner gibt es keine library.yaml.")

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
        else:
            self.win.workspace.refresh()
        self.accept()


# ---------------------------------------------------------------- window

class MainWindow(QMainWindow):
    def __init__(self, lib: Library):
        super().__init__()
        self.settings = QSettings("ProfilClip", "ManualBuilder")
        self.lib = lib
        self.setWindowTitle("Anleitungs-Baukasten")
        self.resize(1480, 900)
        self.setMinimumSize(1180, 700)
        root = QWidget()
        root.setObjectName("page")
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.workspace = Workspace(self)
        self.machines = MachinesPanel(self)
        self.machines.selected.connect(self.open_machine)
        rl.addWidget(self.machines)
        rl.addWidget(self.workspace, 1)
        self.setCentralWidget(root)
        self._open_initial()

    def _open_initial(self) -> None:
        last = self.settings.value("last_machine", "")
        paths = self.lib.machines()
        target = Path(last) if last and Path(last) in paths else (paths[0] if paths else None)
        self.open_machine(Machine.load(target) if target else None)

    def open_machine(self, machine: Machine | None) -> None:
        self.lib.reload_modules()
        self.workspace.load(machine)
        self.machines.refresh(machine.path if machine else None)

    def set_library(self, lib: Library) -> None:
        self.workspace.load(None)
        self.lib = lib
        self._open_initial()

    def closeEvent(self, e):
        if self.workspace.thread is not None:
            QMessageBox.information(self, "Bitte warten", "Die Anleitung wird gerade erstellt.")
            e.ignore()
            return
        self.workspace.save_timer.stop()
        self.workspace.save()
        e.accept()
