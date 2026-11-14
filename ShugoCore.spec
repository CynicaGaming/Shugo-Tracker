# PyInstaller spec for shugo-core.exe, the Python core the Electron app starts (pyinstaller --noconfirm ShugoCore.spec)
# A console program on purpose: it talks over stdin / stdout (Electron starts it hidden).
import os
hidden = ["lz4.block", "psutil"]
skill_data = [("shugotracker/data/skills.json.gz", "shugotracker/data")] \
    if os.path.exists("shugotracker/data/skills.json.gz") else []

a = Analysis(
    ["shugo_core.py"],
    pathex=["."],
    hiddenimports=hidden,
    datas=skill_data,
    excludes=["tkinter", "PIL", "scapy", "matplotlib", "numpy", "IPython", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="shugo-core", console=True, upx=False,
          icon="assets/ShugoTracker.ico")
