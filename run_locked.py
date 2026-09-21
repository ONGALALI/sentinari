"""Backward-compatibility shim: the real launcher is now run_smi.py."""
from __future__ import annotations

import runpy
import sys


if __name__ == "__main__":
    print("run_locked.py is deprecated — use run_smi.py (same behavior).")
    runpy.run_path(str(__import__("pathlib").Path(__file__).resolve().parent / "run_smi.py"), run_name="__main__")
    sys.exit(0)
