"""GUI smoke test: drag & drop logic of the workspace (runs offscreen, skipped on CI)."""

import os
import shutil
from pathlib import Path

import pytest

LIB = Path.home() / "ProfilClip" / "Anleitungs-Bibliothek"
pytestmark = pytest.mark.skipif(bool(os.environ.get("CI")) or not LIB.exists(),
                                reason="needs the real library and a Qt platform")


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from manual_builder.gui import style
    a = QApplication.instance() or QApplication([])
    style.apply(a)
    return a


def _drop(widget, mime_type: str, payload: str, y: int):
    from PySide6.QtCore import QMimeData, QPointF, Qt
    from PySide6.QtGui import QDropEvent
    md = QMimeData()
    md.setData(mime_type, payload.encode())
    ev = QDropEvent(QPointF(10, y), Qt.DropAction.MoveAction, md, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    widget.dropEvent(ev)


def test_drag_and_drop_flow(app, tmp_path):
    from manual_builder.gui.main_window import CHAPTER_MIME, MODULE_MIME, MainWindow
    from manual_builder.library import Library, Machine

    lib_dir = tmp_path / "lib"
    shutil.copytree(LIB, lib_dir, ignore=shutil.ignore_patterns("archive"))
    lib = Library(lib_dir)
    win = MainWindow(lib)
    win.show()
    app.processEvents()
    ws = win.workspace
    assert ws.machine is not None
    start = list(ws.machine.modules)

    # drop a library tile at the end of the manual
    chapters = ws.manual.chapters
    _drop(chapters, MODULE_MIME, "option-drucker", 100000)
    assert ws.machine.modules[-1] == "option-drucker"

    # dropping another clipper replaces the current one (only one allowed)
    _drop(chapters, MODULE_MIME, "clipper-dcx5fc", 0)
    assert "clipper-dcx5fc" in ws.machine.modules and "clipper-dcx5s" not in ws.machine.modules

    # reorder: move first chapter tile to the end
    first = ws.machine.modules[0]
    _drop(chapters, CHAPTER_MIME, "0", 100000)
    assert ws.machine.modules[-1] == first

    # drag a chapter back onto the library removes it
    n = len(ws.machine.modules)
    _drop(ws.library, CHAPTER_MIME, str(n - 1), 10)
    assert len(ws.machine.modules) == n - 1

    # undo everything step by step
    for _ in range(4):
        ws.undo()
    assert ws.machine.modules == start

    # autosave writes the file
    ws.add_module("option-waage") if "option-waage" not in ws.machine.modules else ws.remove_index(
        ws.machine.modules.index("option-waage"))
    ws.save()
    assert Machine.load(ws.machine.path).modules == ws.machine.modules
    win.close()
