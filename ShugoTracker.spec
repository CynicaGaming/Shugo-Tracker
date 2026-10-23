# PyInstaller spec for ShugoTracker.exe  —  build with:  pyinstaller --noconfirm --clean ShugoTracker.spec
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("scapy.layers")
    + collect_submodules("scapy.arch")
    + ["scapy.all", "scapy.sendrecv", "scapy.utils", "lz4.block", "PIL.ImageTk"]
)

a = Analysis(
    ["shugo_tracker.py"],
    pathex=["."],
    hiddenimports=hidden,
    excludes=["matplotlib", "numpy", "IPython"],
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
    console=False,      # windowed: logs go to shugo-tracker.log next to the exe
    uac_admin=False,    # search needs no admin; the experimental --nearby mode must be run as administrator
    upx=False,
    icon=None,
)
