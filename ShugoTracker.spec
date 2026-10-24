# PyInstaller spec for ShugoTracker.exe  —  build with:  pyinstaller --noconfirm --clean ShugoTracker.spec
# The experimental packet-capture mode (--nearby) runs from source only: leaving scapy / psutil / lz4 out of
# the exe makes it much smaller, and a one-file exe unpacks everything it carries on every start.
hidden = ["PIL.ImageTk", "pystray._win32"]

a = Analysis(
    ["shugo_tracker.py"],
    pathex=["."],
    hiddenimports=hidden,
    excludes=["matplotlib", "numpy", "IPython", "scapy", "psutil", "lz4", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ShugoTracker",
    console=False,      # windowed: logs go to shugo-tracker.log in %APPDATA%\\ShugoTracker
    uac_admin=False,    # search needs no admin; the experimental --nearby mode must be run as administrator
    upx=False,
    icon='assets/ShugoTracker.ico',
)
