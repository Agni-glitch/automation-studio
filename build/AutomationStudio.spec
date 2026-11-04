# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec. Run through build/package.py (it builds the frontend, fetches the bundled
# Python and writes version_info.txt first). Produces one folder with two executables:
#   AutomationStudio.exe  windowed: desktop app + background service
#   studio.exe            console:  command-line interface
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(SPECPATH, "assets", "app.ico")
VERSION_FILE = os.path.join(SPECPATH, "output", "version_info.txt")

hiddenimports = (
    collect_submodules("engine")
    + collect_submodules("backend")
    + collect_submodules("desktop")
    + collect_submodules("database")
    # loaded by string name at runtime
    + collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("watchdog.observers")
    + ["pyautogui", "pyperclip", "pygetwindow", "pyscreeze", "PIL.ImageGrab", "main"]
    + collect_submodules("pystray")
)

datas = [
    (os.path.join(ROOT, "frontend", "dist"), os.path.join("frontend", "dist")),
    # the sandbox runs this file with the bundled interpreter, so it must exist on disk
    (os.path.join(ROOT, "engine", "sandbox", "_bootstrap.py"), os.path.join("engine", "sandbox")),
    (os.path.join(ROOT, "examples"), "examples"),
] + collect_data_files("webview")

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "_tkinter", "matplotlib", "numpy", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

gui = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AutomationStudio",
    console=False,
    icon=ICON,
    version=VERSION_FILE,
    upx=False,
)
cli = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="studio",
    console=True,
    icon=ICON,
    version=VERSION_FILE,
    upx=False,
)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="AutomationStudio", upx=False)
