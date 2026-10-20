# PyInstaller spec – build with:  uv run pyinstaller packaging/manual_builder.spec --noconfirm
# Produces dist/Manual Builder.app (macOS) or dist/Manual Builder/Manual Builder.exe (Windows).
import sys
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("docx") + collect_data_files("docxcompose") + [
    ("../src/manual_builder/gui/assets", "manual_builder/gui/assets")]
hidden = ["win32com", "win32com.client", "pythoncom"] if sys.platform == "win32" else []

a = Analysis(["launch.py"], pathex=["../src"], datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                       "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Manual Builder",
          console=False, upx=False, icon="app_icon.ico" if sys.platform == "win32" else "app_icon.icns")
coll = COLLECT(exe, a.binaries, a.datas, name="Manual Builder", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Manual Builder.app", icon="app_icon.icns", bundle_identifier="de.profilclip.manualbuilder",
                 info_plist={"NSHighResolutionCapable": True,
                             "NSAppleEventsUsageDescription":
                                 "Manual Builder steuert Microsoft Word, um Inhaltsverzeichnis und PDF zu erzeugen."})
