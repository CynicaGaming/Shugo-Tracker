# PyInstaller spec for ShugoTracker.exe  —  build with:  pyinstaller --noconfirm --clean ShugoTracker.spec
# Nearby players (opt-in) captures through Windows raw sockets; psutil finds the game's connections.
hidden = ["lz4.block", "PIL.ImageTk", "pystray._win32", "psutil"]

a = Analysis(
    ["shugo_tracker.py"],
    pathex=["."],
    hiddenimports=hidden,
    excludes=["scapy", "matplotlib", "numpy", "IPython", "PyQt5", "PySide2", "PySide6"],
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
    uac_admin=False,    # search needs no admin; turning Nearby on restarts the app as administrator
    upx=False,
    icon='assets/ShugoTracker.ico',
)
