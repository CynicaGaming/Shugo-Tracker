# PyInstaller spec for ShugoTracker.exe  —  build with:  pyinstaller --noconfirm --clean ShugoTracker.spec
from PyInstaller.utils.hooks import collect_submodules

# Nearby players (opt-in) captures through Npcap with scapy; psutil finds the game's connections.
hidden = (
    collect_submodules("scapy.layers")
    + collect_submodules("scapy.arch")
    + ["scapy.all", "scapy.sendrecv", "scapy.utils", "lz4.block", "PIL.ImageTk", "pystray._win32", "psutil"]
)

a = Analysis(
    ["shugo_tracker.py"],
    pathex=["."],
    hiddenimports=hidden,
    excludes=["matplotlib", "numpy", "IPython", "PyQt5", "PySide2", "PySide6"],
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
