"""Entry point for the packaged ShugoTracker.exe (PyInstaller) and for `python shugo_tracker.py`."""
import os
import sys
import traceback


def _fatal(msg: str) -> None:
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(base, "shugo-tracker-crash.log"), "w", encoding="utf-8") as f:
            f.write(msg)
    except OSError:
        pass
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Shugo Tracker", msg[-1500:])
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from shugotracker.app import main
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        _fatal(traceback.format_exc())
        sys.exit(1)
