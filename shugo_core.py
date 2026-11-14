"""Entry point for shugo-core.exe, the Python half of the Electron app (see shugotracker/core.py)."""
import sys

from shugotracker.core import main

if __name__ == "__main__":
    sys.exit(main())
